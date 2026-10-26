"""
Background Job Queue: manages asynchronous OCR processing with concurrency control,
token-bucket rate limiting, per-project event subscriptions for SSE, and failure resilience.
"""
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Dict, List, Optional, Any, Callable, Set
from PIL import Image

from core.models import Project, Page, Diagram, Settings
from core.project_store import get_project_store
from core.config_manager import get_settings
from core.preprocessor import cropped, encode_for_gemini
from core.image_enhancements import apply_erase_regions
from core.gemini_ocr import ocr_page
from core.scrubber import scrub
from core.diagram_extractor import convert_normalized_box_to_work_pixels, extract_diagram
from core.markdown_dialect import count_uncertain_flags, convert_mcq_blocks

logger = logging.getLogger(__name__)

class TokenBucket:
    """Async token bucket rate limiter to adhere to requests_per_minute."""
    def __init__(self, rpm: int):
        self.capacity = float(rpm)
        self.tokens = float(rpm)
        self.rate = float(rpm) / 60.0 # tokens per second
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                # Wait until at least 1 token is available
                needed = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(min(needed, 1.0))

class JobQueue:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self.workers: List[asyncio.Task] = []
        self.token_bucket: TokenBucket = TokenBucket(60)
        self.running = False
        self.active: Set[tuple[str, int]] = set()
        self.running_count: Dict[str, int] = {}

    def is_active(self, pid: str, page: int) -> bool:
        return (pid, page) in self.active

    def get_queue_state(self, pid: str) -> Dict[str, Any]:
        pending = sum(1 for (p, _) in self.active if p == pid) - self.running_count.get(pid, 0)
        return {
            "type": "queue",
            "pending": max(0, pending),
            "running": self.running_count.get(pid, 0)
        }

    async def _emit_queue(self, pid: str):
        await self.broadcast(pid, self.get_queue_state(pid))

    def start(self, max_concurrent: int = 4, rpm: int = 60):
        if self.running:
            return
        self.running = True
        self.token_bucket = TokenBucket(rpm)
        for i in range(max_concurrent):
            t = asyncio.create_task(self._worker_loop(i + 1))
            self.workers.append(t)
        logger.info(f"JobQueue started with {max_concurrent} workers (RPM={rpm}).")

    async def stop(self):
        self.running = False
        for _ in self.workers:
            await self.queue.put(None)
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("JobQueue stopped.")

    def subscribe(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        if project_id not in self.subscribers:
            self.subscribers[project_id] = set()
        self.subscribers[project_id].add(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue):
        if project_id in self.subscribers:
            self.subscribers[project_id].discard(q)
            if not self.subscribers[project_id]:
                del self.subscribers[project_id]

    async def broadcast(self, project_id: str, event_data: Dict[str, Any]):
        if project_id in self.subscribers:
            for q in list(self.subscribers[project_id]):
                try:
                    q.put_nowait(event_data)
                except Exception:
                    pass

    async def enqueue(self, project_id: str, page_index: int, model_mode: str = "accurate", force: bool = False) -> bool:
        if (project_id, page_index) in self.active:
            return False
        self.active.add((project_id, page_index))

        store = get_project_store()
        async with store.edit(project_id) as proj:
            p_key = str(page_index)
            if p_key in proj.pages:
                proj.pages[p_key].status = "queued"
                proj.pages[p_key].error = None

        await self.broadcast(project_id, {
            "type": "page_status",
            "page": page_index,
            "status": "queued"
        })
        await self.queue.put({
            "project_id": project_id,
            "page_index": page_index,
            "model_mode": model_mode,
            "force": force
        })
        await self._emit_queue(project_id)
        return True

    async def _worker_loop(self, worker_id: int):
        store = get_project_store()
        while self.running:
            try:
                job = await self.queue.get()
                if job is None:
                    break

                pid = job["project_id"]
                page_idx = job["page_index"]
                model_mode = job.get("model_mode", "accurate")
                force = job.get("force", False)

                self.running_count[pid] = self.running_count.get(pid, 0) + 1
                await self._emit_queue(pid)
                try:
                    await self._process_job(pid, page_idx, model_mode, force)
                except Exception as e:
                    logger.error(f"Worker {worker_id} error processing {pid} page {page_idx}: {e}", exc_info=True)
                    try:
                        async with store.edit(pid) as proj:
                            p_key = str(page_idx)
                            if p_key in proj.pages:
                                proj.pages[p_key].status = "error"
                                proj.pages[p_key].error = str(e)
                        await self.broadcast(pid, {
                            "type": "page_status",
                            "page": page_idx,
                            "status": "error",
                            "error": str(e)
                        })
                    except Exception:
                        pass
                finally:
                    self.running_count[pid] = max(0, self.running_count.get(pid, 1) - 1)
                    self.active.discard((pid, page_idx))
                    await self._emit_queue(pid)
                    self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker loop {worker_id}: {e}")

    async def _process_job(self, project_id: str, page_index: int, model_mode: str, force: bool):
        store = get_project_store()
        settings = get_settings()

        # Rate limit token acquisition
        await self.token_bucket.acquire()

        p_key = str(page_index)
        crop_top = 0.0
        crop_bottom = 6.5
        work_file = ""
        erase_boxes: List[List[int]] = []

        async with store.edit(project_id) as proj:
            page = proj.pages[p_key]
            page.status = "processing"
            page.error = None
            crop_top = page.crop.top_pct
            crop_bottom = page.crop.bottom_pct
            work_file = page.work_file
            erase_boxes = [r.box_px for r in getattr(page, "erase_regions", [])]

        await self.broadcast(project_id, {
            "type": "page_status",
            "page": page_index,
            "status": "processing"
        })

        pdir = store.get_project_dir(project_id)
        work_path = pdir / work_file
        if not work_path.exists():
            raise FileNotFoundError(f"Work image not found: {work_path}")

        # 1. Virtual crop & encode for Gemini
        def _prepare_image():
            with Image.open(work_path) as w_img:
                if w_img.mode != "RGB":
                    w_img = w_img.convert("RGB")
                if erase_boxes:
                    w_img = apply_erase_regions(w_img, erase_boxes)
                cropped_img = cropped(w_img, crop_top, crop_bottom)
                jpeg_bytes = encode_for_gemini(
                    cropped_img,
                    max_long_edge=settings.send_max_long_edge_px,
                    quality=settings.send_jpeg_quality
                )
                return w_img.size, jpeg_bytes

        (work_w, work_h), jpeg_bytes = await asyncio.to_thread(_prepare_image)

        # Rate wait callback for SSE
        def _rate_wait(sec: float):
            asyncio.create_task(self.broadcast(project_id, {"type": "rate_wait", "seconds": sec}))

        # 2. Call OCR
        model_id = settings.gemini_model if model_mode == "accurate" else settings.gemini_draft_model
        ocr_res = await ocr_page(
            jpeg_bytes=jpeg_bytes,
            settings=settings,
            model_override=model_id,
            force_refresh=force,
            rate_wait_cb=_rate_wait
        )

        # 3. Scrubber pass
        scrubbed_md, removed_terms = scrub(ocr_res.markdown, settings)
        if settings.mcq_default_layout and settings.mcq_default_layout != "as_original":
            scrubbed_md = convert_mcq_blocks(scrubbed_md, settings.mcq_default_layout)

        # 4. Extract diagrams
        extracted_diagrams: List[Diagram] = []
        diagrams_dir = pdir / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)
        diag_version = int(time.time() * 1000)

        for d in ocr_res.diagrams:
            box_px = convert_normalized_box_to_work_pixels(
                box_2d=d.box_2d,
                work_w=work_w,
                work_h=work_h,
                top_pct=crop_top,
                bottom_pct=crop_bottom
            )
            clean_file = diagrams_dir / f"p{page_index:03d}_{d.id}.png"
            raw_file = diagrams_dir / f"p{page_index:03d}_{d.id}_raw.png"

            def _extract(b=box_px, c=clean_file, r=raw_file):
                return extract_diagram(
                    work_img_path=work_path,
                    box_px=b,
                    dest_clean_path=c,
                    dest_raw_path=r,
                    mode=settings.diagram_clean_mode
                )

            snapped_box, width_pct = await asyncio.to_thread(_extract)
            extracted_diagrams.append(Diagram(
                id=d.id,
                box_px=snapped_box,
                label=d.label,
                mode=settings.diagram_clean_mode,
                file=f"diagrams/{clean_file.name}",
                raw_file=f"diagrams/{raw_file.name}",
                replaced=False,
                width_pct=width_pct,
                version=diag_version
            ))

        # 5. Count uncertain flags
        flags_cnt = count_uncertain_flags(scrubbed_md)

        # 6. Save page results to project with conflict detection
        has_conflict = False
        async with store.edit(project_id) as proj:
            p = proj.pages[p_key]
            p.status = "done"
            p.error = None
            p.ocr_at = datetime.now().isoformat()
            if p.user_edited:
                p.ocr_markdown_pending = scrubbed_md
                has_conflict = True
            else:
                p.markdown = scrubbed_md
                p.ocr_markdown_pending = None
            p.diagrams = extracted_diagrams
            p.uncertain_count = flags_cnt
            p.cache_key = ocr_res.cache_key
            p.model_used = ocr_res.model_used
            p.tokens.input = ocr_res.usage.get("input", 0)
            p.tokens.output = ocr_res.usage.get("output", 0)
            p.tokens.thinking = ocr_res.usage.get("thinking", 0)
            p.cost_usd = ocr_res.cost_usd

        if has_conflict:
            await self.broadcast(project_id, {
                "type": "page_conflict",
                "page": page_index
            })

        await self.broadcast(project_id, {
            "type": "page_status",
            "page": page_index,
            "status": "done",
            "uncertain_count": flags_cnt,
            "cost_usd": ocr_res.cost_usd
        })
        logger.info(f"Page {page_index} of {project_id} digitized successfully.")

_job_queue = JobQueue()

def get_job_queue() -> JobQueue:
    return _job_queue
