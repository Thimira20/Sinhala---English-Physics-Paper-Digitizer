"""
Markdown Dialect Contract implementation: shared regex patterns and transformation rules
used across prompt processing, editor overlays, live preview, and DOCX normalization.
"""
import re
from typing import List, Tuple, Callable

# Regular expressions for dialect elements
RE_UNCERTAIN_FLAG = re.compile(r"\[\?(.+?)\?\]")
RE_DIAGRAM_TAG = re.compile(r"\{\{DIAGRAM:(d\d+)\}\}")
RE_MCQ_BLOCK = re.compile(r"<!--\s*mcq\s*-->([\s\S]*?)<!--\s*/mcq\s*-->", re.IGNORECASE)
RE_PAGEBREAK = re.compile(r"^\s*<!--\s*pagebreak\s*-->\s*$", re.MULTILINE | re.IGNORECASE)
RE_UNDERLINE = re.compile(r"<u>([\s\S]*?)</u>", re.IGNORECASE)

# LaTeX math tokens (display and inline)
RE_MATH = re.compile(r"(\$\$(?:\\\$|[^\$])+?\$\$|\$(?:\\\$|[^\$\n])+?\$)", re.DOTALL)

def protect_math(text: str) -> Tuple[str, List[str]]:
    """Replaces math blocks with placeholders so subsequent regexes don't corrupt equations."""
    math_tokens: List[str] = []
    
    def _repl(match: re.Match) -> str:
        idx = len(math_tokens)
        math_tokens.append(match.group(0))
        return f"__MATH_TOKEN_{idx}__"

    protected_text = RE_MATH.sub(_repl, text)
    return protected_text, math_tokens

def restore_math(text: str, math_tokens: List[str]) -> str:
    """Restores protected math tokens."""
    for idx, token in enumerate(math_tokens):
        text = text.replace(f"__MATH_TOKEN_{idx}__", token)
    return text

def apply_numbering_escape(text: str) -> str:
    """
    Prevents Markdown engines from auto-numbering questions (e.g. '01.' becoming '1.' or restarting lists).
    Must be called on text with math protected.
    """
    # 01. -> 01\.
    text = re.sub(r"^(\s*)(\d+)\.(\s)", r"\1\2\\.\3", text, flags=re.MULTILINE)
    # (a) -> \(a) or (1) -> \(1)
    text = re.sub(r"^(\s*)\(([0-9]+|[a-zA-Z]|[ivxIVX]+)\)(\s)", r"\1\\(\2)\3", text, flags=re.MULTILINE)
    return text

def count_uncertain_flags(text: str) -> int:
    return len(RE_UNCERTAIN_FLAG.findall(text))

def strip_uncertain_flags(text: str) -> str:
    return RE_UNCERTAIN_FLAG.sub(r"\1", text)

# --- MCQ Dialect Handling ---

def parse_mcq_options(block_content: str) -> List[dict]:
    """
    Parses options from an MCQ block inner text.
    Returns list of dicts: [{'label': str, 'content': str}]
    """
    if not block_content:
        return []

    cleaned = block_content.strip()

    # Check if it's a pipe table
    if "|" in cleaned:
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        cell_contents = []
        for line in lines:
            if re.match(r"^\|[\s\-:|]+\|$", line):
                continue
            parts = [p.strip() for p in line.split("|")]
            if line.startswith("|") and len(parts) > 0:
                parts.pop(0)
            if line.endswith("|") and len(parts) > 0:
                parts.pop()
            for part in parts:
                if part:
                    cell_contents.append(part)

        options = []
        for cell in cell_contents:
            m = re.match(r"^(\([0-9a-zA-ZivxIVX]+\)|[0-9a-zA-Z]\.)\s*(.*)$", cell, flags=re.DOTALL)
            if m:
                options.append({
                    "label": m.group(1),
                    "content": m.group(2).strip()
                })
            elif options:
                options[-1]["content"] += " " + cell

        if options:
            return options

    # Otherwise line/paragraph based
    label_pattern = re.compile(r"(?:^|\n\s*)(\([0-9a-zA-ZivxIVX]+\)|[0-9a-zA-Z]\.)\s*")
    matches = list(label_pattern.finditer(cleaned))
    if not matches:
        return []

    options = []
    for i in range(len(matches)):
        cur = matches[i]
        next_m = matches[i + 1] if i + 1 < len(matches) else None
        label = cur.group(1)
        start_idx = cur.end()
        end_idx = next_m.start() if next_m else len(cleaned)
        content = cleaned[start_idx:end_idx].strip()
        options.append({"label": label, "content": content})

    return options

def detect_mcq_layout(block_content: str) -> str:
    """Detects current layout of an MCQ block text: row5, grid32, grid2, or list."""
    trimmed = block_content.strip()
    if "|" not in trimmed:
        return "list"

    lines = [l.strip() for l in trimmed.splitlines() if l.strip() and not re.match(r"^\|[\s\-:|]+\|$", l.strip())]
    first_row = next((l for l in lines if "|" in l), None)
    if not first_row:
        return "list"

    cols = len([c.strip() for c in first_row.split("|") if c.strip()])
    if cols >= 5:
        return "row5"
    if cols == 3:
        return "grid32"
    if cols == 2:
        return "grid2"
    return "list"

def can_use_grid_layout(options: List[dict]) -> bool:
    """Options containing '$$' or > 120 chars can only use 'list'."""
    for opt in options:
        content = opt.get("content", "")
        if "$$" in content:
            return False
        if len(content) > 120:
            return False
    return True

def emit_mcq(options: List[dict], layout: str) -> str:
    """Emits canonical MCQ block Markdown according to the specified layout."""
    if not options:
        return ""

    if layout == "list" or (not can_use_grid_layout(options) and layout != "as_original"):
        body = "\n\n".join(f"{o['label']} {o['content']}" for o in options)
        return f"<!-- mcq -->\n{body}\n<!-- /mcq -->"

    col_count = 5
    if layout == "row5":
        col_count = 5
    elif layout == "grid32":
        col_count = 3
    elif layout == "grid2":
        col_count = 2

    header = "| " + " | ".join([" "] * col_count) + " |"
    divider = "|" + "|".join(["---"] * col_count) + "|"

    rows = []
    for i in range(0, len(options), col_count):
        chunk = options[i:i + col_count]
        cells = [f"{o['label']} {o['content']}" for o in chunk]
        while len(cells) < col_count:
            cells.append(" ")
        rows.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, divider] + rows)
    return f"<!-- mcq -->\n{table}\n<!-- /mcq -->"

def convert_mcq_blocks(markdown: str, target_layout: str) -> str:
    """Converts all MCQ blocks in markdown to target_layout if applicable."""
    if not target_layout or target_layout == "as_original":
        return markdown

    def _replace_block(m: re.Match) -> str:
        inner = m.group(1).strip()
        opts = parse_mcq_options(inner)
        if not opts:
            return m.group(0)
        return emit_mcq(opts, target_layout)

    return RE_MCQ_BLOCK.sub(_replace_block, markdown)

