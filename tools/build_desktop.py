"""
Automated PyInstaller Desktop Builder for Sinhala & English Physics Paper Digitizer.
SPEC P3-T10: PyInstaller one-folder build + desktop shortcut.
Bundles the application into dist/PhysicsDigitizer/ with all static assets, templates, and fonts.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def build_desktop_app():
    print("=" * 60)
    print("Starting PyInstaller Desktop Build...")
    print(f"Project root: {PROJECT_ROOT}")
    print("=" * 60)

    dist_dir = PROJECT_ROOT / "dist"
    build_dir = PROJECT_ROOT / "build"
    app_name = "PhysicsDigitizer"

    # PyInstaller arguments
    pyinstaller_cmd = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "pyinstaller.exe"),
        "--noconfirm",
        "--onedir",
        "--name", app_name,
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        # Assets & static folders
        "--add-data", f"{str(PROJECT_ROOT / 'static')};static",
        "--add-data", f"{str(PROJECT_ROOT / 'assets')};assets",
        "--add-data", f"{str(PROJECT_ROOT / 'config.default.json')};.",
        # Hidden imports
        "--hidden-import", "uvicorn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "pypandoc",
        "--hidden-import", "docx",
        "--hidden-import", "lxml",
        "--hidden-import", "fitz",
        "--hidden-import", "cv2",
        "--hidden-import", "PIL",
        "--hidden-import", "numpy",
        "--hidden-import", "sse_starlette",
        "--hidden-import", "google.genai",
        "--hidden-import", "win32com",
        "--hidden-import", "pythoncom",
        str(PROJECT_ROOT / "main.py")
    ]

    print("Running command:")
    print(" ".join(pyinstaller_cmd[:6]) + " ...")

    result = subprocess.run(pyinstaller_cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("[ERROR] PyInstaller build failed!")
        return False

    output_exe = dist_dir / app_name / f"{app_name}.exe"
    print("=" * 60)
    print(f"[SUCCESS] Standalone desktop build completed at: {output_exe}")
    print("=" * 60)

    # Generate desktop shortcut
    from tools.create_desktop_shortcut import create_desktop_shortcut
    create_desktop_shortcut(output_exe)
    return True

if __name__ == "__main__":
    success = build_desktop_app()
    sys.exit(0 if success else 1)
