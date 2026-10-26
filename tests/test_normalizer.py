"""
Unit tests for core.markdown_normalizer (SPEC P3-T01).
"""
import pytest
from pathlib import Path
from core.models import Project, Page, Diagram, Settings
from core.markdown_normalizer import normalize_markdown, normalize, extract_outside_math

def test_flags_handling():
    text = "මෙය [?සත්‍ය?] සහ [?අසත්‍ය?] අගයකි."
    # Strip flags
    res_stripped, warns = normalize_markdown(text, strip_flags=True)
    assert "[?" not in res_stripped
    assert "සත්‍ය" in res_stripped
    assert "අසත්‍ය" in res_stripped
    assert any("Stripped 2" in w for w in warns)

    # Keep flags
    res_kept, warns_kept = normalize_markdown(text, strip_flags=False)
    assert "[?සත්‍ය?]" in res_kept
    assert any("Exported with 2" in w for w in warns_kept)

def test_underline_conversion():
    text = "මෙය <u>වැදගත්</u> පාඩමකි."
    res, _ = normalize_markdown(text)
    assert "[වැදගත්]{.underline}" in res
    assert "<u>" not in res

def test_numbering_escape():
    text = "01. පළමු ප්‍රශ්නය\n(a) උප ප්‍රශ්නය"
    res, _ = normalize_markdown(text)
    assert r"01\. පළමු ප්‍රශ්නය" in res
    assert r"\(a) උප ප්‍රශ්නය" in res

def test_mcq_markers():
    # Grid/table MCQ gets MCQMarker
    grid_mcq = "<!-- mcq -->\n| (1) 10 | (2) 20 |\n| (3) 30 | (4) 40 |\n<!-- /mcq -->"
    res_grid, _ = normalize_markdown(grid_mcq)
    assert 'w:val="MCQMarker"' in res_grid
    assert "<!-- mcq -->" not in res_grid
    assert "<!-- /mcq -->" not in res_grid

    # List MCQ loses markers without adding table marker
    list_mcq = "<!-- mcq -->\n(1) 10\n(2) 20\n(3) 30\n<!-- /mcq -->"
    res_list, _ = normalize_markdown(list_mcq)
    assert 'w:val="MCQMarker"' not in res_list
    assert "<!-- mcq -->" not in res_list
    assert "(1) 10" in res_list

def test_pagebreak_marker():
    text = "Page 1 content\n\n<!-- pagebreak -->\n\nPage 2 content"
    res, _ = normalize_markdown(text)
    assert '<w:br w:type="page"/>' in res
    assert "<!-- pagebreak -->" not in res

def test_diagram_tag_expansion(tmp_path):
    diag_file = tmp_path / "diagrams" / "p001_d1.png"
    diag_file.parent.mkdir(parents=True, exist_ok=True)
    diag_file.write_bytes(b"dummy")

    diags_map = {
        "d1": {
            "file": "diagrams/p001_d1.png",
            "width_pct": 65,
            "mode": "normalize"
        }
    }
    text = "පහත රූපය බලන්න:\n\n{{DIAGRAM:d1}}\n\nවිස්තරය."
    res, warns = normalize_markdown(text, diagrams_map=diags_map, project_dir=tmp_path)
    expected_path = diag_file.resolve().as_posix()
    assert f"![]({expected_path}){{width=65%}}" in res
    assert len(warns) == 0

    # Missing diagram tag
    text_missing = "{{DIAGRAM:d99}}"
    res_missing, warns_missing = normalize_markdown(text_missing, diagrams_map=diags_map, project_dir=tmp_path)
    assert "{{DIAGRAM:d99}}" not in res_missing
    assert any("could not be resolved" in w for w in warns_missing)

def test_outside_sinhala_math():
    text = "$$\\text{ත්වරණය} = \\frac{v - u}{t}$$"
    res = extract_outside_math(text)
    assert "ත්වරණය =" in res
    assert "$$\\frac{v - u}{t}$$" in res
    assert "\\text{ත්වරණය}" not in res

def test_project_normalize_multiple_pages(tmp_path):
    settings = Settings(sinhala_math_mode="omml")
    proj = Project(
        id="p_test",
        name="Test Paper",
        created_at="2026-10-27T00:00:00",
        updated_at="2026-10-27T00:00:00"
    )
    p1 = Page(index=1, source_file="s1", work_file="w1", thumb_file="t1", markdown="Page 1 <u>test</u>", page_break_after=True)
    p2 = Page(index=2, source_file="s2", work_file="w2", thumb_file="t2", markdown="Page 2 text", page_break_after=False)
    proj.pages = {"1": p1, "2": p2}
    proj.page_order = [1, 2]

    res, warns = normalize([p1, p2], proj, settings)
    assert "[test]{.underline}" in res
    assert '<w:br w:type="page"/>' in res
    assert "Page 2 text" in res
