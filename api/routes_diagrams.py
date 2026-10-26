import asyncio
import logging
from pathlib import Path
import time
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from core.models import Diagram
from core.project_store import get_project_store
from core.config_manager import get_settings
from core.diagram_extractor import extract_diagram

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["Diagrams"])

class SaveDiagramRequest(BaseModel):
    id: Optional[str] = None
    box_px: Optional[List[int]] = None
    mode: Optional[str] = "normalize"
    label: Optional[str] = None
    width_pct: Optional[int] = None

class UpdateDiagramRequest(BaseModel):
    mode: Optional[str] = None
    width_pct: Optional[int] = None
    label: Optional[str] = None
    box_px: Optional[List[int]] = None

@router.post("/{pid}/pages/{page_idx}/diagrams", response_model=Diagram)
async def save_or_recrop_diagram(pid: str, page_idx: int, req: SaveDiagramRequest):
    store = get_project_store()
    settings = get_settings()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    if p_key not in proj.pages:
        raise HTTPException(status_code=404, detail="Page not found.")

    page = proj.pages[p_key]
    pdir = store.get_project_dir(pid)
    work_path = pdir / page.work_file
    if not work_path.exists():
        raise HTTPException(status_code=404, detail="Work image not found.")

    diagrams_dir = pdir / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    # Determine diagram ID
    did = req.id
    if not did:
        existing_nums = []
        for d in page.diagrams:
            if d.id.startswith("d") and d.id[1:].isdigit():
                existing_nums.append(int(d.id[1:]))
        next_num = max(existing_nums) + 1 if existing_nums else 1
        did = f"d{next_num}"

    clean_file = diagrams_dir / f"p{page_idx:03d}_{did}.png"
    raw_file = diagrams_dir / f"p{page_idx:03d}_{did}_raw.png"
    clean_mode = req.mode or settings.diagram_clean_mode

    # If box_px is given, run extraction before entering lock
    if req.box_px:
        snapped_box, calculated_width_pct = await asyncio.to_thread(
            extract_diagram,
            work_img_path=work_path,
            box_px=req.box_px,
            dest_clean_path=clean_file,
            dest_raw_path=raw_file,
            mode=clean_mode
        )
        final_box = snapped_box
        final_width_pct = req.width_pct if req.width_pct is not None else calculated_width_pct
    else:
        existing_diag = next((d for d in page.diagrams if d.id == did), None)
        if not existing_diag:
            raise HTTPException(status_code=400, detail="box_px required for new diagram")
        final_box = existing_diag.box_px
        final_width_pct = req.width_pct if req.width_pct is not None else existing_diag.width_pct

    now_version = int(time.time() * 1000)
    diag_obj = Diagram(
        id=did,
        box_px=final_box,
        label=req.label or did,
        mode=clean_mode,
        file=f"diagrams/{clean_file.name}",
        raw_file=f"diagrams/{raw_file.name}",
        replaced=False,
        width_pct=max(15, min(100, final_width_pct)),
        version=now_version
    )

    async with store.edit(pid) as cur_proj:
        if p_key not in cur_proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        cur_page = cur_proj.pages[p_key]
        updated = False
        for i, d in enumerate(cur_page.diagrams):
            if d.id == did:
                cur_page.diagrams[i] = diag_obj
                updated = True
                break
        if not updated:
            cur_page.diagrams.append(diag_obj)

    return diag_obj

@router.patch("/{pid}/pages/{page_idx}/diagrams/{did}", response_model=Diagram)
async def patch_diagram(pid: str, page_idx: int, did: str, req: UpdateDiagramRequest):
    store = get_project_store()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    if p_key not in proj.pages:
        raise HTTPException(status_code=404, detail="Page not found.")

    page = proj.pages[p_key]
    target_diag = next((d for d in page.diagrams if d.id == did), None)
    if not target_diag:
        raise HTTPException(status_code=404, detail="Diagram not found.")

    pdir = store.get_project_dir(pid)
    work_path = pdir / page.work_file

    new_box = target_diag.box_px
    new_mode = target_diag.mode
    re_extracted = False

    # If mode or box_px changed, re-extract before lock
    if (req.mode is not None and req.mode != target_diag.mode) or req.box_px is not None:
        new_mode = req.mode or target_diag.mode
        new_box = req.box_px or target_diag.box_px
        clean_file = pdir / target_diag.file
        raw_file = pdir / (target_diag.raw_file or f"diagrams/p{page_idx:03d}_{did}_raw.png")
        snapped_box, _ = await asyncio.to_thread(
            extract_diagram,
            work_img_path=work_path,
            box_px=new_box,
            dest_clean_path=clean_file,
            dest_raw_path=raw_file,
            mode=new_mode
        )
        new_box = snapped_box
        re_extracted = True

    result_diag = None
    async with store.edit(pid) as cur_proj:
        if p_key not in cur_proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        diag = next((d for d in cur_proj.pages[p_key].diagrams if d.id == did), None)
        if not diag:
            raise HTTPException(status_code=404, detail="Diagram not found.")

        if req.width_pct is not None:
            diag.width_pct = max(15, min(100, req.width_pct))
        if req.label is not None:
            diag.label = req.label
        if re_extracted:
            diag.box_px = new_box
            diag.mode = new_mode
            diag.version = int(time.time() * 1000)
        result_diag = diag

    return result_diag

@router.delete("/{pid}/pages/{page_idx}/diagrams/{did}", status_code=204)
async def delete_diagram(pid: str, page_idx: int, did: str):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    async with store.edit(pid) as cur_proj:
        if p_key not in cur_proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        page = cur_proj.pages[p_key]
        initial_len = len(page.diagrams)
        page.diagrams = [d for d in page.diagrams if d.id != did]
        if len(page.diagrams) == initial_len:
            raise HTTPException(status_code=404, detail="Diagram not found.")

    pdir = store.get_project_dir(pid)
    for ext in ["", "_raw"]:
        fpath = pdir / "diagrams" / f"p{page_idx:03d}_{did}{ext}.png"
        if fpath.exists():
            try:
                fpath.unlink()
            except Exception:
                pass

    return None

@router.post("/{pid}/pages/{page_idx}/diagrams/{did}/replace", response_model=Diagram)
async def replace_diagram(pid: str, page_idx: int, did: str, file: UploadFile = File(...)):
    store = get_project_store()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    if p_key not in proj.pages:
        raise HTTPException(status_code=404, detail="Page not found.")

    target_diag = next((d for d in proj.pages[p_key].diagrams if d.id == did), None)
    if target_diag is None:
        raise HTTPException(status_code=404, detail="Diagram not found.")

    pdir = store.get_project_dir(pid)
    dest_path = pdir / target_diag.file
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    dest_path.write_bytes(contents)

    result_diag = None
    async with store.edit(pid) as cur_proj:
        if p_key not in cur_proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        diag = next((d for d in cur_proj.pages[p_key].diagrams if d.id == did), None)
        if not diag:
            raise HTTPException(status_code=404, detail="Diagram not found.")
        diag.replaced = True
        diag.version = int(time.time() * 1000)
        result_diag = diag

    return result_diag
