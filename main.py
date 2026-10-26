"""
Main FastAPI application entry point for Sinhala & English Physics Paper Digitizer.
Initializes routes, background job queue, static file serving, and logging.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import socket
import sys
import webbrowser
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config_manager import get_settings
from core.project_store import get_project_store
from core.job_queue import get_job_queue

from api.routes_projects import router as projects_router
from api.routes_settings import router as settings_router
from api.routes_ocr import router as ocr_router
from api.routes_diagrams import router as diagrams_router
from api.routes_export import router as export_router

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "workspace" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "app.log"
EXPORTS_DIR = PROJECT_ROOT / "workspace" / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

class ApiKeyFilter(logging.Filter):
    """SPEC P3-T09: Scrubs Gemini API key occurrences from all log output."""
    API_KEY_REGEX = re.compile(r"AIza[0-9A-Za-z\-_]{35}")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            settings_key = get_settings().gemini_api_key
        except Exception:
            settings_key = ""

        def mask_str(s: str) -> str:
            if settings_key and len(settings_key) > 8:
                s = s.replace(settings_key, "***API_KEY_MASKED***")
            s = self.API_KEY_REGEX.sub("***API_KEY_MASKED***", s)
            return s

        if isinstance(record.msg, str):
            record.msg = mask_str(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(mask_str(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: mask_str(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True

def setup_logging():
    logger = logging.getLogger("physics_digitizer")
    logger.setLevel(logging.INFO)
    
    key_filter = ApiKeyFilter()
    logger.addFilter(key_filter)
    
    if not logger.handlers:
        c_handler = logging.StreamHandler(sys.stdout)
        c_format = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
        c_handler.setFormatter(c_format)
        c_handler.addFilter(key_filter)
        logger.addHandler(c_handler)
        
        f_handler = RotatingFileHandler(str(LOG_FILE), maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
        f_format = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d]: %(message)s")
        f_handler.setFormatter(f_format)
        f_handler.addFilter(key_filter)
        logger.addHandler(f_handler)
    return logger

logger = setup_logging()

def cleanup_cache_lru(max_bytes: int = 500 * 1024 * 1024):
    """SPEC P3-T09: Cache limit of 500 MB with LRU deletion by atime/mtime at startup."""
    cache_dir = PROJECT_ROOT / "workspace" / "cache"
    if not cache_dir.exists():
        return
    files = [f for f in cache_dir.iterdir() if f.is_file()]
    total_size = sum(f.stat().st_size for f in files)
    if total_size <= max_bytes:
        return

    # Sort ascending by last access/modification time (oldest first)
    files.sort(key=lambda f: max(f.stat().st_atime, f.stat().st_mtime))
    bytes_removed = 0
    count_removed = 0
    for f in files:
        if total_size <= max_bytes:
            break
        sz = f.stat().st_size
        try:
            f.unlink(missing_ok=True)
            total_size -= sz
            bytes_removed += sz
            count_removed += 1
        except Exception as e:
            logger.warning(f"Could not delete cache file {f.name}: {e}")

    logger.info(f"LRU cache cleanup: removed {count_removed} files ({bytes_removed / (1024*1024):.1f} MB freed)")

def find_free_port(start_port: int = 8000, max_attempts: int = 50) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port

SERVER_PORT = find_free_port(get_settings().server_port)

@asynccontextmanager
async def lifespan(app: FastAPI):
    url = f"http://127.0.0.1:{SERVER_PORT}"
    logger.info(f"Server starting up on {url}")
    
    # LRU cache eviction at startup
    cleanup_cache_lru()

    # Reset any interrupted jobs from previous run
    store = get_project_store()
    for info in store.list_projects():
        try:
            async with store.edit(info["id"]) as p:
                for pg in p.pages.values():
                    if pg.status in ("queued", "processing"):
                        pg.status = "pending"
                        pg.error = "Interrupted (server restarted)"
        except Exception as e:
            logger.warning(f"Could not reset statuses for {info.get('id')}: {e}")

    # Start background job queue
    settings = get_settings()
    queue = get_job_queue()
    queue.start(
        max_concurrent=settings.max_concurrent_jobs,
        rpm=settings.requests_per_minute
    )

    async def open_browser():
        await asyncio.sleep(1.2)
        logger.info(f"Auto-opening system browser: {url}")
        webbrowser.open(url)
        
    asyncio.create_task(open_browser())
    yield
    
    logger.info("Stopping job queue...")
    await queue.stop()
    logger.info("Server shutting down.")

app = FastAPI(
    title="Sinhala & English Physics Paper Digitizer",
    version="1.0.0",
    lifespan=lifespan
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """SPEC P3-T09: Global exception handler returns JSON and logs traceback."""
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.exception(f"Unhandled server error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "type": type(exc).__name__,
            "detail": "An internal server error occurred. Check workspace/logs/app.log for details."
        }
    )

# Include Routers
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(ocr_router)
app.include_router(diagrams_router)
app.include_router(export_router)

# Mount static files
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

vendor_dir = STATIC_DIR / "vendor"
if vendor_dir.exists():
    app.mount("/vendor", StaticFiles(directory=str(vendor_dir)), name="vendor")

fonts_dir = STATIC_DIR / "fonts"
if fonts_dir.exists():
    app.mount("/fonts", StaticFiles(directory=str(fonts_dir)), name="fonts")

tests_dir = PROJECT_ROOT / "tests"
if tests_dir.exists():
    app.mount("/tests", StaticFiles(directory=str(tests_dir)), name="tests")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Sinhala & English Physics Paper Digitizer Backend Active"}

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "Sinhala & English Physics Paper Digitizer"}

# Secure file serving routes with path traversal guards
@app.get("/files/{pid}/{relpath:path}")
async def serve_project_file(pid: str, relpath: str):
    store = get_project_store()
    try:
        pdir = store.get_project_dir(pid).resolve()
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found.")

    target_file = (pdir / relpath).resolve()
    if not target_file.is_relative_to(pdir) or not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(target_file)

@app.get("/exports/{filename}")
async def serve_export_file(filename: str):
    exports_dir = EXPORTS_DIR.resolve()
    target_file = (exports_dir / filename).resolve()
    if not target_file.is_relative_to(exports_dir) or not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="Export not found.")

    return FileResponse(target_file)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=SERVER_PORT, log_level="info")
