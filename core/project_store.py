"""
Project Store: handles project.json persistence, atomic disk writes,
per-project asyncio locks, and workspace project folder management.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Dict, List, Optional, Any
import uuid

from core.models import Project, Page

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = PROJECT_ROOT / "workspace" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

class ProjectStore:
    def __init__(self, base_dir: Path = PROJECTS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, asyncio.Lock] = {}
        self.clean_leftover_tmp()

    def clean_leftover_tmp(self) -> None:
        try:
            for tmp in self.base_dir.glob("*/project.json.*.tmp"):
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            for tmp in self.base_dir.glob("*/project.json.tmp"):
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to clean tmp project files: {e}")

    def get_lock(self, project_id: str) -> asyncio.Lock:
        if project_id not in self._locks:
            self._locks[project_id] = asyncio.Lock()
        return self._locks[project_id]

    def get_project_dir(self, project_id: str) -> Path:
        pdir = (self.base_dir / project_id).resolve()
        if not pdir.is_relative_to(self.base_dir.resolve()):
            raise ValueError(f"Path traversal attempt: {project_id}")
        return pdir

    def create_project(self, name: str) -> Project:
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = os.urandom(2).hex()
        pid = f"p_{now_str}_{suffix}"
        pdir = self.get_project_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "pages").mkdir(exist_ok=True)
        (pdir / "diagrams").mkdir(exist_ok=True)

        now_iso = datetime.now().isoformat()
        proj = Project(
            schema_version=1,
            id=pid,
            name=name.strip() or "Untitled Physics Paper",
            created_at=now_iso,
            updated_at=now_iso,
            page_order=[],
            pages={}
        )
        self.save_project_sync(proj)
        return proj

    def load_project(self, project_id: str) -> Project:
        pdir = self.get_project_dir(project_id)
        pfile = pdir / "project.json"
        if not pfile.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        last_err = None
        for attempt in range(5):
            try:
                data = json.loads(pfile.read_text(encoding="utf-8"))
                return Project.model_validate(data)
            except (PermissionError, json.JSONDecodeError) as e:
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        raise RuntimeError(f"Failed to load project {project_id}: {last_err}") from last_err

    def save_project_sync(self, project: Project) -> None:
        pdir = self.get_project_dir(project.id)
        pdir.mkdir(parents=True, exist_ok=True)
        pfile = pdir / "project.json"
        tmp_file = pdir / f"project.json.{uuid.uuid4().hex[:8]}.tmp"

        project.updated_at = datetime.now().isoformat()
        data = project.model_dump()
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        last_err = None
        for attempt in range(10):
            try:
                os.replace(tmp_file, pfile)
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        try:
            tmp_file.unlink(missing_ok=True)
        finally:
            raise RuntimeError(f"Failed to save project {project.id}: {last_err}") from last_err

    async def save_project(self, project: Project) -> None:
        lock = self.get_lock(project.id)
        async with lock:
            await asyncio.to_thread(self.save_project_sync, project)

    @asynccontextmanager
    async def edit(self, project_id: str):
        """Load, yield for modification, then save — all under the project lock."""
        lock = self.get_lock(project_id)
        async with lock:
            proj = await asyncio.to_thread(self.load_project, project_id)
            yield proj
            await asyncio.to_thread(self.save_project_sync, proj)

    def list_projects(self) -> List[Dict[str, Any]]:
        results = []
        for pdir in self.base_dir.iterdir():
            if pdir.is_dir() and (pdir / "project.json").exists():
                try:
                    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
                    results.append({
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "page_count": len(data.get("page_order", []))
                    })
                except Exception as e:
                    logger.warning(f"Error reading {pdir}: {e}")
        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return results

    def delete_project(self, project_id: str) -> bool:
        pdir = self.get_project_dir(project_id)
        if pdir.exists():
            shutil.rmtree(pdir)
            if project_id in self._locks:
                del self._locks[project_id]
            return True
        return False

_project_store = ProjectStore()

def get_project_store() -> ProjectStore:
    return _project_store
