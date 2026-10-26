import json
from pathlib import Path
import pytest
from core.markdown_dialect import (
    parse_mcq_options,
    detect_mcq_layout,
    can_use_grid_layout,
    emit_mcq,
    convert_mcq_blocks,
)

CASES_FILE = Path(__file__).resolve().parent / "js" / "mcq_cases.json"

@pytest.fixture
def mcq_cases():
    with open(CASES_FILE, encoding="utf-8") as f:
        return json.load(f)

def test_mcq_parsing_and_emission_roundtrip(mcq_cases):
    layouts = ["row5", "grid32", "grid2", "list"]

    for case in mcq_cases:
        options = case["options"]
        expected_can_grid = case["can_grid"]

        assert can_use_grid_layout(options) == expected_can_grid, f"Mismatch on {case['name']}"

        if expected_can_grid:
            for layout in layouts:
                emitted = emit_mcq(options, layout)
                assert emitted.startswith("<!-- mcq -->") and emitted.endswith("<!-- /mcq -->")
                inner = emitted.replace("<!-- mcq -->", "").replace("<!-- /mcq -->", "").strip()

                parsed = parse_mcq_options(inner)
                assert len(parsed) == len(options), f"Failed count for {case['name']} in {layout}"
                for i, opt in enumerate(options):
                    assert parsed[i]["label"] == opt["label"]
                    assert parsed[i]["content"] == opt["content"]
        else:
            emitted = emit_mcq(options, "list")
            inner = emitted.replace("<!-- mcq -->", "").replace("<!-- /mcq -->", "").strip()
            parsed = parse_mcq_options(inner)
            assert len(parsed) == len(options)

def test_detect_mcq_layout():
    row5_text = "|   |   |   |   |   |\n|---|---|---|---|---|\n| (1) A | (2) B | (3) C | (4) D | (5) E |"
    assert detect_mcq_layout(row5_text) == "row5"

    grid32_text = "|   |   |   |\n|---|---|---|\n| (1) A | (2) B | (3) C |\n| (4) D | (5) E |   |"
    assert detect_mcq_layout(grid32_text) == "grid32"

    grid2_text = "|   |   |\n|---|---|\n| (1) A | (2) B |\n| (3) C | (4) D |"
    assert detect_mcq_layout(grid2_text) == "grid2"

    list_text = "(1) Option A\n\n(2) Option B\n\n(3) Option C"
    assert detect_mcq_layout(list_text) == "list"

def test_convert_mcq_blocks():
    md = """Question 1
<!-- mcq -->
(1) 10 m
(2) 20 m
(3) 30 m
(4) 40 m
(5) 50 m
<!-- /mcq -->
End of question."""
    converted = convert_mcq_blocks(md, "row5")
    assert "| (1) 10 m | (2) 20 m | (3) 30 m | (4) 40 m | (5) 50 m |" in converted

    # Test as_original leaves untouched
    assert convert_mcq_blocks(md, "as_original") == md
