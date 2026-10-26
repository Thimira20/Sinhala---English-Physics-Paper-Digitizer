"""
Multi-engine PDF Exporter (SPEC P3-T07).
Attempts PDF generation according to settings.pdf_engine_order:
1. 'word': Uses MS Word COM ExportAsFixedFormat for highest fidelity Sinhala & OMML equations.
2. 'libreoffice': Uses headless soffice.exe if installed.
3. 'browser': Returns browser print endpoint URL /print/{pid} with @media print styling.
"""
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from core.models import Project, Settings
from core.docx_exporter import export_to_docx
from core import word_com

logger = logging.getLogger(__name__)

def find_libreoffice_executable() -> Optional[str]:
    """Locates soffice.exe on Windows PATH or standard installation directory."""
    which_path = shutil.which("soffice")
    if which_path:
        return which_path

    standard_paths = [
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for p in standard_paths:
        if p.exists():
            return str(p)
    return None

def convert_with_libreoffice(docx_path: Path, output_pdf_path: Path, timeout_sec: int = 120) -> bool:
    """Converts a DOCX file to PDF using headless LibreOffice."""
    soffice = find_libreoffice_executable()
    if not soffice:
        raise RuntimeError("LibreOffice executable (soffice.exe) not found.")

    out_dir = output_pdf_path.parent
    cmd = [
        soffice,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        str(docx_path)
    ]
    logger.info(f"Running headless LibreOffice PDF conversion: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, timeout=timeout_sec)
    if res.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {res.stderr.decode('utf-8', errors='ignore')}")

    generated_pdf = out_dir / f"{docx_path.stem}.pdf"
    if generated_pdf.exists() and generated_pdf != output_pdf_path:
        os.replace(generated_pdf, output_pdf_path)

    return output_pdf_path.exists()

def export_project_to_pdf(
    merged_md: str,
    output_pdf_path: Path,
    settings: Settings,
    project_id: str,
    target_pages: List[int],
    diagrams_map: Optional[Dict[str, Dict[str, Any]]] = None,
    project_dir: Optional[Path] = None,
    strip_flags: bool = True
) -> Dict[str, Any]:
    """
    Exports a project to PDF trying engines in settings.pdf_engine_order.
    Returns result dictionary containing engine name, url, file, and warnings.
    """
    engine_order = settings.pdf_engine_order or ["word", "libreoffice", "browser"]
    warnings: List[str] = []

    # Temporary DOCX path for file-based conversion engines
    temp_docx_path = output_pdf_path.parent / f"{output_pdf_path.stem}_temp.docx"

    for engine in engine_order:
        engine_clean = engine.strip().lower()

        if engine_clean == "word":
            try:
                logger.info("Attempting PDF export via MS Word COM engine...")
                # 1. Export intermediate DOCX
                export_to_docx(
                    markdown=merged_md,
                    output_docx_path=temp_docx_path,
                    settings=settings,
                    diagrams_map=diagrams_map,
                    project_dir=project_dir,
                    strip_flags=strip_flags,
                    embed_fonts=False # Local Word conversion doesn't need embedded fonts
                )
                # 2. Convert to PDF
                word_com.to_pdf(temp_docx_path, output_pdf_path)
                logger.info(f"Successfully generated PDF via Word COM: {output_pdf_path.name}")
                return {
                    "engine": "word",
                    "file": output_pdf_path.name,
                    "url": f"/exports/{output_pdf_path.name}",
                    "warnings": warnings
                }
            except Exception as e:
                msg = f"Word COM PDF engine failed or unavailable: {e}"
                logger.warning(msg)
                warnings.append(msg)
            finally:
                if temp_docx_path.exists():
                    temp_docx_path.unlink(missing_ok=True)

        elif engine_clean == "libreoffice":
            try:
                logger.info("Attempting PDF export via LibreOffice headless engine...")
                export_to_docx(
                    markdown=merged_md,
                    output_docx_path=temp_docx_path,
                    settings=settings,
                    diagrams_map=diagrams_map,
                    project_dir=project_dir,
                    strip_flags=strip_flags,
                    embed_fonts=False
                )
                convert_with_libreoffice(temp_docx_path, output_pdf_path)
                logger.info(f"Successfully generated PDF via LibreOffice: {output_pdf_path.name}")
                return {
                    "engine": "libreoffice",
                    "file": output_pdf_path.name,
                    "url": f"/exports/{output_pdf_path.name}",
                    "warnings": warnings
                }
            except Exception as e:
                msg = f"LibreOffice PDF engine failed or unavailable: {e}"
                logger.warning(msg)
                warnings.append(msg)
            finally:
                if temp_docx_path.exists():
                    temp_docx_path.unlink(missing_ok=True)

        elif engine_clean == "browser":
            logger.info("Falling back to Browser Print PDF engine.")
            pages_query = ",".join(map(str, target_pages))
            print_url = f"/print/{project_id}?pages={pages_query}"
            return {
                "engine": "browser",
                "file": None,
                "url": print_url,
                "warnings": warnings
            }

    # If all engines fail or list is exhausted without browser
    pages_query = ",".join(map(str, target_pages))
    return {
        "engine": "browser",
        "file": None,
        "url": f"/print/{project_id}?pages={pages_query}",
        "warnings": warnings
    }
