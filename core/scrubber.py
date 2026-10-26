"""
Scrubber module: strips branding, blacklist terms, phone numbers, URLs, emails,
and page numbering markers from extracted Markdown while preserving equations.
"""
import re
from typing import List, Tuple
from core.models import Settings
from core.markdown_dialect import protect_math, restore_math

RE_PHONE_PATTERNS = [
    re.compile(r"(?:\+94|0)\s?7\d[\s-]?\d{3}[\s-]?\d{4}"),
    re.compile(r"(?:\+94|0)\s?\d{2}[\s-]?\d{3}[\s-]?\d{4}")
]

RE_URL = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
RE_PAGE_MARKER = re.compile(r"^\s*-\s*\d+\s*-\s*$", re.MULTILINE)
RE_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")

def build_blacklist_regex(term: str) -> re.Pattern:
    escaped = re.escape(term.strip())
    # Allow variable whitespace between words
    pattern_str = re.sub(r"\\ ", r"\\s+", escaped)
    return re.compile(rf"\b{pattern_str}\b" if pattern_str.isalnum() else pattern_str, re.IGNORECASE)

def scrub(markdown: str, settings: Settings) -> Tuple[str, List[str]]:
    removed_items: List[str] = []
    if not markdown:
        return "", removed_items

    # 1. Protect math blocks so numbers inside formulas are never touched
    protected, math_tokens = protect_math(markdown)

    # 2. Blacklist removal
    for term in settings.branding_blacklist:
        if not term.strip():
            continue
        rx = build_blacklist_regex(term)
        matches = rx.findall(protected)
        if matches:
            removed_items.extend(matches)
            protected = rx.sub("", protected)

    # 3. Phone number scrubbing
    if settings.scrub_phone_numbers:
        for rx in RE_PHONE_PATTERNS:
            matches = rx.findall(protected)
            if matches:
                removed_items.extend(matches)
                protected = rx.sub("", protected)

    # 4. URLs and emails scrubbing
    if settings.scrub_urls_emails:
        urls = RE_URL.findall(protected)
        if urls:
            removed_items.extend(urls)
            protected = RE_URL.sub("", protected)

        emails = RE_EMAIL.findall(protected)
        if emails:
            removed_items.extend(emails)
            protected = RE_EMAIL.sub("", protected)

    # 5. Page markers like '- 3 -'
    page_markers = RE_PAGE_MARKER.findall(protected)
    if page_markers:
        removed_items.extend(page_markers)
        protected = RE_PAGE_MARKER.sub("", protected)

    # 6. Collapse excessive blank lines left behind
    protected = RE_EXCESSIVE_NEWLINES.sub("\n\n", protected)

    # 7. Restore protected math
    result = restore_math(protected, math_tokens)
    return result.strip(), removed_items
