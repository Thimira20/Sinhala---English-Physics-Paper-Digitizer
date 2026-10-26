"""
Settings API routes: get/update configuration, test API key via google-genai,
and list available vision models.
"""
from datetime import datetime
import re
from fastapi import APIRouter, HTTPException
from core.models import Settings
from core.config_manager import get_config_manager, get_settings
from core.project_store import get_project_store
import core.gemini_ocr as gemini_ocr
from google import genai

router = APIRouter(prefix="/api", tags=["Settings"])

@router.get("/settings", response_model=Settings)
async def get_current_settings():
    settings = get_settings()
    return settings.masked_copy()

@router.put("/settings", response_model=Settings)
async def update_settings(new_settings: dict):
    mgr = get_config_manager()
    try:
        saved = mgr.save_settings(new_settings)
        return saved.masked_copy()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/settings/test-key")
async def test_api_key(body: dict = None):
    key = ""
    if body and "gemini_api_key" in body:
        key = body["gemini_api_key"]
    if not key or key.startswith("AIza") and "..." in key:
        key = get_settings().gemini_api_key

    if not key:
        raise HTTPException(status_code=400, detail="Gemini API key is required.")

    try:
        client = genai.Client(api_key=key)
        # List models supporting generateContent
        models_pager = client.models.list()
        supported = []
        for m in models_pager:
            m_name = getattr(m, "name", "")
            actions = getattr(m, "supported_actions", []) or getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in actions or "generate_content" in str(actions).lower() or "gemini" in m_name:
                clean_name = m_name.replace("models/", "")
                supported.append(clean_name)
        return {"ok": True, "models": supported}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}

@router.get("/usage")
async def get_usage(project_id: str = None):
    store = get_project_store()
    project_usd = 0.0
    month_usd = 0.0
    now_prefix = datetime.now().strftime("%Y-%m")

    for p_info in store.list_projects():
        pid = p_info["id"]
        try:
            proj = store.load_project(pid)
            proj_cost = sum(p.cost_usd for p in proj.pages.values())
            if project_id and pid == project_id:
                project_usd = round(proj_cost, 4)
            # Sum cost of pages digitized this month
            for pg in proj.pages.values():
                date_check = getattr(pg, "ocr_at", None)
                if date_check and date_check.startswith(now_prefix):
                    month_usd += pg.cost_usd
        except Exception:
            continue

    return {
        "project_usd": round(project_usd, 4),
        "month_usd": round(month_usd, 4)
    }

@router.get("/cache/stats")
async def get_cache_stats():
    cache_dir = gemini_ocr.CACHE_DIR
    if not cache_dir.exists():
        return {"count": 0, "size_mb": 0.0}
    files = [f for f in cache_dir.glob("*.json") if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "count": len(files),
        "size_mb": round(total_bytes / (1024 * 1024), 2)
    }

@router.post("/cache/clear")
async def clear_cache():
    cache_dir = gemini_ocr.CACHE_DIR
    cleared = 0
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            # Only delete files matching 64-char hex sha256.json
            if re.fullmatch(r"[0-9a-f]{64}\.json", f.name):
                try:
                    f.unlink()
                    cleared += 1
                except Exception:
                    pass
    return {"ok": True, "cleared_files": cleared}


