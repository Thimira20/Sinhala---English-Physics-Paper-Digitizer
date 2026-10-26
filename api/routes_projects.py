"""
Project Management API routes: CRUD for projects, file uploading (PDF & images),
page ordering, and individual page updates.
"""
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from core.models import Project, Page, EraseRegion
from core.project_store import get_project_store
from core.config_manager import get_settings
from core.preprocessor import ingest_file, create_thumbnail
from core.image_enhancements import suggest_header_footer_crop, correct_perspective
from PIL import Image

router = APIRouter(prefix="/api/projects", tags=["Projects"])

class CreateProjectRequest(BaseModel):
    name: str

class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    page_order: Optional[List[int]] = None

@router.get("", response_model=List[dict])
async def list_all_projects():
    store = get_project_store()
    return store.list_projects()

@router.post("", response_model=Project)
async def create_new_project(req: CreateProjectRequest):
    store = get_project_store()
    return store.create_project(req.name)

@router.get("/{pid}", response_model=Project)
async def get_project_details(pid: str):
    store = get_project_store()
    try:
        return store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

@router.patch("/{pid}", response_model=Project)
async def update_project_metadata(pid: str, req: UpdateProjectRequest):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    async with store.edit(pid) as proj:
        if req.name is not None:
            proj.name = req.name.strip()
        if req.page_order is not None:
            proj.page_order = req.page_order
        return proj

@router.delete("/{pid}", status_code=204)
async def delete_project_endpoint(pid: str):
    store = get_project_store()
    if not store.delete_project(pid):
        raise HTTPException(status_code=404, detail="Project not found.")
    return None

@router.post("/{pid}/upload")
async def upload_files_to_project(pid: str, files: List[UploadFile] = File(...)):
    store = get_project_store()
    settings = get_settings()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    pdir = store.get_project_dir(pid)

    uploaded_data = []
    for upload in files:
        file_bytes = await upload.read()
        if len(file_bytes) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File {upload.filename} exceeds 50MB limit.")

        # Magic bytes check (SPEC P3-T09)
        is_pdf = file_bytes.startswith(b"%PDF")
        is_png = file_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpeg = file_bytes.startswith(b"\xff\xd8\xff")
        is_webp = len(file_bytes) >= 12 and file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP"

        if not (is_pdf or is_png or is_jpeg or is_webp):
            raise HTTPException(
                status_code=400,
                detail=f"File '{upload.filename}' has an unsupported format. Allowed formats: PDF, PNG, JPEG, WEBP."
            )

        uploaded_data.append((file_bytes, upload.filename or "uploaded_page.png"))

    added_pages = []
    async with store.edit(pid) as proj:
        start_idx = max(proj.page_order) + 1 if proj.page_order else 1
        for file_bytes, filename in uploaded_data:
            pages = ingest_file(
                file_bytes=file_bytes,
                filename=filename,
                project_dir=pdir,
                start_index=start_idx,
                deskew_enabled=settings.auto_deskew,
                default_top_crop=settings.default_top_crop_percent,
                default_bottom_crop=settings.default_bottom_crop_percent
            )
            for p in pages:
                proj.pages[str(p.index)] = p
                proj.page_order.append(p.index)
                added_pages.append(p.index)
                start_idx = p.index + 1

    return {"added_pages": added_pages}

@router.put("/{pid}/pages/{page_idx}", response_model=Page)
async def update_page_content(pid: str, page_idx: int, update_data: dict):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    updated_page = None
    async with store.edit(pid) as proj:
        if p_key not in proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")

        page = proj.pages[p_key]
        if "markdown" in update_data:
            page.markdown = update_data["markdown"]
            page.user_edited = True
        if "crop" in update_data:
            c = update_data["crop"]
            page.crop.top_pct = c.get("top_pct", page.crop.top_pct)
            page.crop.bottom_pct = c.get("bottom_pct", page.crop.bottom_pct)
            page.crop.override = c.get("override", True)
        if "deskew" in update_data:
            page.deskew = bool(update_data["deskew"])
        if "include_in_export" in update_data:
            page.include_in_export = bool(update_data["include_in_export"])
        if "page_break_after" in update_data:
            page.page_break_after = bool(update_data["page_break_after"])
        updated_page = page

    return updated_page

@router.delete("/{pid}/pages/{page_idx}", status_code=204)
async def delete_page(pid: str, page_idx: int):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    async with store.edit(pid) as proj:
        if p_key in proj.pages:
            del proj.pages[p_key]
        if page_idx in proj.page_order:
            proj.page_order.remove(page_idx)
    return None

class EraseRegionRequest(BaseModel):
    box_px: List[int]

@router.post("/{pid}/pages/{page_idx}/suggest-crop")
async def suggest_crop_endpoint(pid: str, page_idx: int, apply: bool = False):
    store = get_project_store()
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

    with Image.open(work_path) as img:
        top_pct, bottom_pct = suggest_header_footer_crop(img)

    detected = (top_pct is not None or bottom_pct is not None)
    res_top = top_pct if top_pct is not None else page.crop.top_pct
    res_bottom = bottom_pct if bottom_pct is not None else page.crop.bottom_pct

    if apply and detected:
        async with store.edit(pid) as p:
            pg = p.pages[p_key]
            if top_pct is not None:
                pg.crop.top_pct = top_pct
            if bottom_pct is not None:
                pg.crop.bottom_pct = bottom_pct
            pg.crop.override = True

    return {
        "detected": detected,
        "top_pct": res_top,
        "bottom_pct": res_bottom,
        "applied": apply and detected
    }

@router.post("/{pid}/pages/{page_idx}/perspective-fix")
async def perspective_fix_endpoint(pid: str, page_idx: int):
    store = get_project_store()
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
    thumb_path = pdir / page.thumb_file

    with Image.open(work_path) as img:
        corrected_img, success = correct_perspective(img)
        if not success:
            return {"success": False, "message": "No clean 4-corner document boundary could be detected."}

        corrected_img.save(work_path, format="PNG")
        create_thumbnail(corrected_img, thumb_path)
        new_w, new_h = corrected_img.size

    async with store.edit(pid) as p:
        pg = p.pages[p_key]
        pg.width = new_w
        pg.height = new_h

    return {
        "success": True,
        "message": "Perspective corrected successfully.",
        "width": new_w,
        "height": new_h
    }

@router.post("/{pid}/pages/{page_idx}/erase-regions", response_model=EraseRegion)
async def add_erase_region(pid: str, page_idx: int, req: EraseRegionRequest):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    created_region = None
    async with store.edit(pid) as proj:
        if p_key not in proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        page = proj.pages[p_key]
        existing_ids = [r.id for r in getattr(page, "erase_regions", [])]
        idx = 1
        while f"e{idx}" in existing_ids:
            idx += 1
        eid = f"e{idx}"
        region = EraseRegion(id=eid, box_px=req.box_px)
        if not hasattr(page, "erase_regions"):
            page.erase_regions = []
        page.erase_regions.append(region)
        created_region = region

    return created_region

@router.delete("/{pid}/pages/{page_idx}/erase-regions/{region_id}", status_code=204)
async def delete_erase_region(pid: str, page_idx: int, region_id: str):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    p_key = str(page_idx)
    async with store.edit(pid) as proj:
        if p_key not in proj.pages:
            raise HTTPException(status_code=404, detail="Page not found.")
        page = proj.pages[p_key]
        page.erase_regions = [r for r in getattr(page, "erase_regions", []) if r.id != region_id]

    return None

