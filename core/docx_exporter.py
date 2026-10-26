"""
DOCX Exporter: orchestrates Pandoc Markdown -> DOCX conversion, applies reference.docx
styles, executes OpenXML post-processing for Sinhala fonts and OMML math, and optionally
embeds TrueType fonts via MS Word COM.
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import pypandoc

from core.models import Settings
from core.markdown_normalizer import normalize_markdown
from core.docx_postprocess import fix_sinhala_and_styles
from core import word_com

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DOCX = PROJECT_ROOT / "assets" / "reference.docx"

def export_to_docx(
    markdown: str,
    output_docx_path: Path,
    settings: Settings,
    diagrams_map: Optional[Dict[str, Dict[str, Any]]] = None,
    project_dir: Optional[Path] = None,
    strip_flags: bool = True,
    embed_fonts: Optional[bool] = None
) -> Tuple[Path, List[str]]:
    """
    Exports Markdown with embedded LaTeX math to a cleanly formatted Microsoft Word document (.docx).
    """
    output_docx_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Normalize markdown
    norm_md, warnings = normalize_markdown(
        markdown=markdown,
        diagrams_map=diagrams_map,
        project_dir=project_dir,
        strip_flags=strip_flags
    )

    # 2. Pandoc conversion with verified reference.docx
    from tools.build_reference_docx import ensure_reference_docx
    ref_docx = ensure_reference_docx({
        "sinhala_font": settings.sinhala_font,
        "latin_font": settings.latin_font,
        "body_font_size_pt": settings.body_font_size_pt,
        "line_spacing": settings.line_spacing
    })

    extra_args = [
        f"--reference-doc={ref_docx.resolve()}",
        "--standalone"
    ]
    if project_dir is not None:
        extra_args.append(f"--resource-path={project_dir.resolve()}")

    logger.info(f"Converting markdown to DOCX via Pandoc -> {output_docx_path.name}")
    pypandoc.convert_text(
        source=norm_md,
        to="docx",
        format="markdown+tex_math_dollars+raw_attribute+bracketed_spans+pipe_tables-fancy_lists",
        outputfile=str(output_docx_path.resolve()),
        extra_args=extra_args
    )

    # 3. Post-process OpenXML (Sinhala w:cs, bold CS, OMML math font and ordering, MCQ tables)
    logger.info(f"Running OpenXML post-processor on {output_docx_path.name}")
    fix_sinhala_and_styles(
        docx_path=output_docx_path,
        sinhala_font=settings.sinhala_font,
        latin_font=settings.latin_font
    )

    # 4. Embed fonts via Word COM if enabled
    should_embed = embed_fonts if embed_fonts is not None else settings.embed_fonts_in_docx
    if should_embed:
        try:
            logger.info("Triggering Word COM font embedding...")
            word_com.embed_fonts(output_docx_path)
        except Exception as e:
            msg = f"Word COM font embedding skipped or failed: {e}"
            logger.warning(msg)
            warnings.append(msg)

    return output_docx_path, warnings
