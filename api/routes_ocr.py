"""
OCR Enqueue and SSE Event Streaming routes.
Allows batch triggering of page digitizing, force re-runs, and real-time SSE progress streaming.
"""
import json
import asyncio
import logging
from typing import List, Union, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.models import Project
from core.project_store import get_project_store
from core.job_queue import get_job_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["OCR"])

class OcrRequest(BaseModel):
    pages: Union[List[int], str] = "all"
    model: str = "accurate" # "accurate" or "draft"
    force: bool = False
    overwrite: bool = False

@router.post("/{pid}/ocr")
async def trigger_ocr(pid: str, req: OcrRequest):
    store = get_project_store()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    if not proj.pages:
        return {"queued": [], "skipped": []}

    target_pages = []
    if req.pages == "all":
        target_pages = list(proj.page_order)
    elif isinstance(req.pages, list):
        target_pages = [p for p in req.pages if str(p) in proj.pages]
    else:
        raise HTTPException(status_code=400, detail="Invalid pages parameter. Must be 'all' or list of integers.")

    queue = get_job_queue()
    queued = []
    skipped = []

    for p_idx in target_pages:
        page = proj.pages[str(p_idx)]
        if page.status == "done" and not req.overwrite and not req.force:
            skipped.append({"n": p_idx, "reason": "Already processed (use overwrite or force to re-run)."})
            continue
        if queue.is_active(pid, p_idx):
            skipped.append({"n": p_idx, "reason": "Already queued or processing."})
            continue

        if req.overwrite or req.force:
            async with store.edit(pid) as cur_proj:
                if str(p_idx) in cur_proj.pages:
                    cur_proj.pages[str(p_idx)].user_edited = False

        await queue.enqueue(
            project_id=pid,
            page_index=p_idx,
            model_mode=req.model,
            force=req.force
        )
        queued.append(p_idx)

    return {"queued": queued, "skipped": skipped}

@router.get("/{pid}/events")
async def stream_project_events(pid: str):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    queue = get_job_queue()
    client_q = queue.subscribe(pid)

    async def event_generator():
        try:
            # Send initial keepalive/connected event and current queue state
            yield f"data: {json.dumps({'type': 'connected', 'project_id': pid})}\n\n"
            yield f"data: {json.dumps(queue.get_queue_state(pid))}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(client_q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep SSE alive
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            queue.unsubscribe(pid, client_q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
