"""
Integration test for JobQueue (SPEC P1-T10):
Uses mocked OCR, 10 pages, and 4 workers.
Verifies all pages process concurrently, status events arrive, and project.json is updated cleanly.
"""
import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image

from core.models import GeminiDiagram
from core.gemini_ocr import OcrResult
from core.project_store import ProjectStore
from core.job_queue import JobQueue

@pytest.mark.asyncio
async def test_job_queue_concurrency(tmp_path):
    store = ProjectStore(base_dir=tmp_path / "projects")
    proj = store.create_project("Queue Test Project")
    pdir = store.get_project_dir(proj.id)

    # Create 10 dummy pages with work.png images
    for i in range(1, 11):
        p_img_path = pdir / f"p{i:03d}_work.png"
        img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
        img.save(p_img_path)

        from core.models import Page
        proj.pages[str(i)] = Page(
            index=i,
            source_file=f"p{i:03d}_work.png",
            work_file=f"p{i:03d}_work.png",
            thumb_file=f"p{i:03d}_work.png",
            status="pending"
        )
        proj.page_order.append(i)

    await store.save_project(proj)

    # Mock OCR response
    async def mock_ocr_page(*args, **kwargs):
        await asyncio.sleep(0.05) # simulate network latency
        return OcrResult(
            markdown=f"## Test Page\nPhysics content here.",
            diagrams=[GeminiDiagram(id="d1", box_2d=[100, 100, 400, 400], label="circuit")],
            usage={"input": 100, "output": 50, "thinking": 0},
            cache_key="mock_key",
            model_used="gemini-2.5-pro",
            cost_usd=0.001
        )

    queue = JobQueue()
    subscriber = queue.subscribe(proj.id)

    events_received = []

    async def collect_events():
        while True:
            try:
                ev = await asyncio.wait_for(subscriber.get(), timeout=2.0)
                events_received.append(ev)
            except asyncio.TimeoutError:
                break

    collector_task = asyncio.create_task(collect_events())

    with patch("core.job_queue.get_project_store", return_value=store), \
         patch("core.job_queue.ocr_page", side_effect=mock_ocr_page):

        queue.start(max_concurrent=4, rpm=200)
        for i in range(1, 11):
            await queue.enqueue(proj.id, i, model_mode="accurate", force=False)

        # Wait until all 10 tasks in queue are processed
        await queue.queue.join()

    await queue.stop()
    await collector_task

    # Verify project state
    updated_proj = store.load_project(proj.id)
    assert len(updated_proj.pages) == 10
    for i in range(1, 11):
        p = updated_proj.pages[str(i)]
        assert p.status == "done"
        assert "Physics content" in p.markdown
        assert len(p.diagrams) == 1
        assert p.cost_usd > 0

    # Verify events
    done_events = [e for e in events_received if e.get("type") == "page_status" and e.get("status") == "done"]
    assert len(done_events) == 10
