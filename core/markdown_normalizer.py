"""
Markdown Normalizer: transforms editor Markdown into Pandoc-ready Markdown (SPEC P3-T01).
Translates <u> to Pandoc bracketed spans [x]{.underline}, injects OpenXML markers
for borderless MCQ tables and page breaks, protects question numbers, resolves diagram paths,
and optionally extracts leading Sinhala text from equations when sinhala_math_mode is 'outside'.
"""
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from core.models import Settings
from core.markdown_dialect import (
    protect_math,
    restore_math,
    apply_numbering_escape,
    strip_uncertain_flags,
    count_uncertain_flags,
    RE_UNDERLINE,
    RE_DIAGRAM_TAG,
    RE_MCQ_BLOCK,
    RE_PAGEBREAK
)

OPENXML_MCQ_MARKER = "```{=openxml}\n<w:p><w:pPr><w:pStyle w:val=\"MCQMarker\"/></w:pPr></w:p>\n```\n\n"
OPENXML_PAGEBREAK = "\n\n```{=openxml}\n<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>\n```\n\n"

RE_SINHALA = re.compile(r"[\u0D80-\u0DFF]")
RE_OUTSIDE_MATH = re.compile(r"\$\$\s*\\text\{([^}]+)\}\s*=\s*([\s\S]+?)\$\$")

def extract_outside_math(text: str) -> str:
    """Moves leading Sinhala text out of display math as a paragraph prefix."""
    def _repl(m: re.Match) -> str:
        label = m.group(1).strip()
        body = m.group(2).strip()
        if RE_SINHALA.search(label):
            return f"\n\n{label} =\n\n$${body}$$\n\n"
        return m.group(0)
    return RE_OUTSIDE_MATH.sub(_repl, text)

def normalize_markdown(
    markdown: str,
    diagrams_map: Optional[Dict[str, Dict[str, Any]]] = None,
    project_dir: Optional[Path] = None,
    strip_flags: bool = True,
    sinhala_math_mode: str = "omml"
) -> Tuple[str, List[str]]:
    """
    Transforms review editor Markdown into Pandoc-compliant Markdown for DOCX generation.
    Returns (normalized_markdown, warnings).
    """
    warnings: List[str] = []
    if not markdown:
        return "", warnings

    flags_count = count_uncertain_flags(markdown)
    if flags_count > 0:
        if strip_flags:
            markdown = strip_uncertain_flags(markdown)
            warnings.append(f"Stripped {flags_count} unresolved [?...?] flags.")
        else:
            warnings.append(f"Exported with {flags_count} unresolved [?...?] flags.")

    from core.gemini_ocr import sanitize_latex_escapes
    markdown = sanitize_latex_escapes(markdown)

    # 1. Protect math blocks
    protected, math_tokens = protect_math(markdown)

    # 2. Convert <u>text</u> to Pandoc native underline span [text]{.underline}
    protected = RE_UNDERLINE.sub(r"[\1]{.underline}", protected)

    # 3. Apply question numbering escape (01. -> 01\., (a) -> \(a))
    protected = apply_numbering_escape(protected)

    # 4. Handle MCQ block markers
    def _mcq_repl(match: re.Match) -> str:
        content = match.group(1).strip()
        if "|" in content:
            return f"{OPENXML_MCQ_MARKER}{content}\n\n"
        return f"{content}\n\n"

    protected = RE_MCQ_BLOCK.sub(_mcq_repl, protected)

    # 5. Handle page breaks
    protected = RE_PAGEBREAK.sub(OPENXML_PAGEBREAK, protected)

    # 6. Diagram tags {{DIAGRAM:d1}} -> ![](path){width=NN%}
    def _diag_repl(match: re.Match) -> str:
        did = match.group(1)
        if diagrams_map and did in diagrams_map:
            d_info = diagrams_map[did]
            # If mode is original and original_file available, use it; else use file
            mode = d_info.get("mode", "normalize")
            rel_file = d_info.get("raw_file", "") if mode == "original" and d_info.get("raw_file") else d_info.get("file", "")
            width_pct = d_info.get("width_pct", 50)
            if project_dir and rel_file:
                abs_file = (project_dir / rel_file).resolve().as_posix()
                return f"![]({abs_file}){{width={width_pct}%}}"
        warnings.append(f"Diagram tag {{{did}}} could not be resolved to an image file.")
        return ""

    protected = RE_DIAGRAM_TAG.sub(_diag_repl, protected)

    # 7. Restore protected math blocks
    result = restore_math(protected, math_tokens)

    # 8. Handle outside Sinhala math mode if enabled
    if sinhala_math_mode == "outside":
        result = extract_outside_math(result)

    # 9. Ensure display math has blank lines around it for Pandoc parsing
    result = re.sub(r"([^\n])\n\$\$", r"\1\n\n$$", result)
    result = re.sub(r"\$\$\n([^\n])", r"$$\n\n\1", result)

    return result, warnings

def normalize(
    pages: List[Any],
    project: Any,
    settings: Settings,
    strip_flags: bool = True
) -> Tuple[str, List[str]]:
    """
    High-level normalizer iterating across all included pages of a project (SPEC P3-T01).
    Returns (unified_pandoc_markdown, warnings).
    """
    all_warnings: List[str] = []
    page_mds: List[str] = []

    # Map all diagrams across pages
    diagrams_map: Dict[str, Dict[str, Any]] = {}
    for p in pages:
        diags = getattr(p, "diagrams", []) or []
        for d in diags:
            did = getattr(d, "id", None) or d.get("id")
            if did:
                diagrams_map[did] = {
                    "file": getattr(d, "file", None) or d.get("file", ""),
                    "raw_file": getattr(d, "raw_file", None) or d.get("raw_file", ""),
                    "mode": getattr(d, "mode", "normalize") or d.get("mode", "normalize"),
                    "width_pct": getattr(d, "width_pct", 50) or d.get("width_pct", 50)
                }

    from core.project_store import get_project_store
    store = get_project_store()
    project_dir = store.get_project_dir(getattr(project, "id", str(project)))

    for i, p in enumerate(pages):
        raw_md = getattr(p, "markdown", "") or ""
        if not raw_md.strip():
            continue

        p_norm, p_warns = normalize_markdown(
            markdown=raw_md,
            diagrams_map=diagrams_map,
            project_dir=project_dir,
            strip_flags=strip_flags,
            sinhala_math_mode=getattr(settings, "sinhala_math_mode", "omml")
        )
        all_warnings.extend(p_warns)

        # Append page break if requested on page, unless it's the very last page
        if getattr(p, "page_break_after", False) and i < len(pages) - 1:
            p_norm += OPENXML_PAGEBREAK

        page_mds.append(p_norm)

    merged_pandoc_md = "\n\n".join(page_mds)
    return merged_pandoc_md, all_warnings
