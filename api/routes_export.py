"""
Export API routes: export projects to Microsoft Word (.docx) and PDF (.pdf).
Supports merging multiple pages, diagram resolution, Sinhala font embedding, and flag stripping.
"""
import re
import logging
from pathlib import Path
from typing import List, Union, Optional, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.models import Project, Settings
from core.project_store import get_project_store
from core.config_manager import get_settings
from core.docx_exporter import export_to_docx
from core import word_com

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Export"])

EXPORTS_DIR = Path("workspace/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

class ExportRequest(BaseModel):
    pages: Union[List[int], str] = "all"
    merge: bool = True
    strip_flags: bool = True
    embed_fonts: Optional[bool] = None

def _assemble_project_markdown(
    proj: Project,
    target_page_indices: List[int]
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    md_parts = []
    diagrams_map: Dict[str, Dict[str, Any]] = {}

    for idx in target_page_indices:
        p_key = str(idx)
        if p_key not in proj.pages:
            continue
        page = proj.pages[p_key]
        if not page.markdown:
            continue

        for d in page.diagrams:
            diagrams_map[d.id] = {
                "file": d.file,
                "width_pct": d.width_pct
            }

        page_md = page.markdown.strip()
        if page.page_break_after:
            page_md += "\n\n<!-- pagebreak -->\n"
        md_parts.append(page_md)

    merged_md = "\n\n".join(md_parts)
    return merged_md, diagrams_map

@router.post("/api/projects/{pid}/export/docx")
async def export_project_docx(pid: str, req: ExportRequest):
    store = get_project_store()
    settings = get_settings()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    target_pages = []
    if req.pages == "all":
        target_pages = [idx for idx in proj.page_order if proj.pages[str(idx)].include_in_export]
    elif isinstance(req.pages, list):
        target_pages = [idx for idx in req.pages if str(idx) in proj.pages]
    else:
        raise HTTPException(status_code=400, detail="Invalid pages parameter.")

    if not target_pages:
        raise HTTPException(status_code=400, detail="No pages selected for export.")

    merged_md, diagrams_map = _assemble_project_markdown(proj, target_pages)
    pdir = store.get_project_dir(pid)

    safe_name = re.sub(r'[\\/*?:"<>| ]', "_", proj.name).strip("_") or "paper"
    out_filename = f"{safe_name}_{pid[:8]}.docx"
    out_docx_path = EXPORTS_DIR / out_filename

    should_embed = req.embed_fonts if req.embed_fonts is not None else settings.embed_fonts_in_docx

    try:
        exported_path, warnings = export_to_docx(
            markdown=merged_md,
            output_docx_path=out_docx_path,
            settings=settings,
            diagrams_map=diagrams_map,
            project_dir=pdir,
            strip_flags=req.strip_flags,
            embed_fonts=should_embed
        )
    except Exception as e:
        logger.error(f"DOCX export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")

    return {
        "file": out_filename,
        "url": f"/exports/{out_filename}",
        "warnings": warnings
    }

from core.pdf_exporter import export_project_to_pdf

@router.post("/api/projects/{pid}/export/pdf")
async def export_project_pdf(pid: str, req: ExportRequest):
    store = get_project_store()
    settings = get_settings()
    try:
        proj = store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    target_pages = []
    if req.pages == "all":
        target_pages = [idx for idx in proj.page_order if proj.pages[str(idx)].include_in_export]
    elif isinstance(req.pages, list):
        target_pages = [idx for idx in req.pages if str(idx) in proj.pages]
    else:
        raise HTTPException(status_code=400, detail="Invalid pages parameter.")

    if not target_pages:
        raise HTTPException(status_code=400, detail="No pages selected for export.")

    merged_md, diagrams_map = _assemble_project_markdown(proj, target_pages)
    pdir = store.get_project_dir(pid)

    safe_name = re.sub(r'[\\/*?:"<>| ]', "_", proj.name).strip("_") or "paper"
    out_pdf_filename = f"{safe_name}_{pid[:8]}.pdf"
    out_pdf_path = EXPORTS_DIR / out_pdf_filename

    res = export_project_to_pdf(
        merged_md=merged_md,
        output_pdf_path=out_pdf_path,
        settings=settings,
        project_id=pid,
        target_pages=target_pages,
        diagrams_map=diagrams_map,
        project_dir=pdir,
        strip_flags=req.strip_flags
    )
    return res

class OpenRequest(BaseModel):
    file: Optional[str] = None
    folder: bool = False

@router.post("/api/open")
async def open_exported_file(req: OpenRequest):
    """
    Opens an exported file or reveals it in Windows File Explorer (SPEC P3-T08).
    Protected: Only paths strictly inside workspace/exports are allowed.
    """
    if not req.file:
        raise HTTPException(status_code=400, detail="Filename required.")

    if req.file in ("logs/app.log", "app.log", "log"):
        log_path = (EXPORTS_DIR.parent / "logs" / "app.log").resolve()
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch()
        import os
        import subprocess
        try:
            if req.folder:
                subprocess.Popen(["explorer", f"/select,{str(log_path)}"])
            else:
                os.startfile(str(log_path))
            return {"status": "ok", "opened": "app.log"}
        except Exception as e:
            logger.error(f"Failed to open log file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to open log: {e}")

    # Prevent directory traversal
    clean_name = Path(req.file).name
    target_path = (EXPORTS_DIR / clean_name).resolve()

    # Safety check: must be inside EXPORTS_DIR
    if not str(target_path).startswith(str(EXPORTS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied: outside exports directory.")

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Exported file not found.")

    import os
    import subprocess
    try:
        if req.folder:
            # Highlight file in Windows Explorer
            subprocess.Popen(["explorer", f"/select,{str(target_path)}"])
        else:
            # Open file with default registered application
            os.startfile(str(target_path))
        return {"status": "ok", "opened": clean_name}
    except Exception as e:
        logger.error(f"Failed to open file {clean_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open file: {e}")

@router.get("/print/{pid}")
async def print_view(pid: str, pages: Optional[str] = None):
    store = get_project_store()
    try:
        store.load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found.")

    print_html_path = Path("static/print.html")
    if print_html_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(print_html_path)

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="<h3>Print view not available</h3>")


