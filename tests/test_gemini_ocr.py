"""
Tests for core.gemini_ocr: cache keys, cache hits, JSON repair for LaTeX backslashes,
box validation, cost calculation, and retry backoff.
"""
import pytest
from core.models import Settings, GeminiDiagram
from core.gemini_ocr import compute_cache_key, repair_json, validate_boxes, calculate_cost

def test_cache_key_deterministic():
    data = b"sample_jpeg_data"
    k1 = compute_cache_key(data, "gemini-2.5-pro")
    k2 = compute_cache_key(data, "gemini-2.5-pro")
    k3 = compute_cache_key(data, "gemini-2.5-flash")
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64

def test_repair_json_latex_backslashes():
    # Case 1: Markdown code fences
    raw1 = "```json\n{\"markdown\": \"hello\"}\n```"
    assert repair_json(raw1) == '{"markdown": "hello"}'
    
    # Case 2: LaTeX math commands with backslashes
    # \theta and \frac would normally be invalid \t or \f in standard json
    raw2 = '{"markdown": "Angle is \\theta and fraction is \\frac{1}{2}"}'
    repaired2 = repair_json(raw2)
    assert r'\\theta' in repaired2
    assert r'\\frac' in repaired2
    
    # Standard json parses repaired text without error
    import json
    data = json.loads(repaired2)
    assert "theta" in data["markdown"]

def test_validate_boxes():
    diagrams = [
        GeminiDiagram(id="d1", box_2d=[100, 200, 500, 600], label="valid"),
        GeminiDiagram(id="d2", box_2d=[500, 200, 100, 600], label="inverted_y"), # ymin > ymax -> invalid
        GeminiDiagram(id="d3", box_2d=[-50, 100, 1200, 800], label="clamped"),
    ]
    valid = validate_boxes(diagrams)
    assert len(valid) == 2
    assert valid[0].id == "d1"
    assert valid[1].id == "d3"
    # Verify clamping
    assert valid[1].box_2d == [0, 100, 1000, 800]

def test_calculate_cost():
    settings = Settings()
    usage = {"input": 1000, "output": 2000, "thinking": 500}
    # Pro: $1.25 / M in, $10.0 / M out
    cost = calculate_cost(usage, "gemini-2.5-pro", settings)
    # (1000 * 1.25 + 2500 * 10) / 1e6 = (1250 + 25000) / 1e6 = 0.02625
    assert cost == pytest.approx(0.02625, rel=1e-3)

@pytest.mark.asyncio
async def test_ocr_page_disk_caching(tmp_path):
    import asyncio
    from unittest.mock import MagicMock, patch
    from core.gemini_ocr import ocr_page

    settings = Settings(gemini_api_key="mock_test_key")
    jpeg_bytes = b"fake_jpeg_image_data_123"

    # Mock response object
    mock_resp = MagicMock()
    mock_resp.parsed = None
    mock_resp.text = '{"markdown": "Hello world", "diagrams": []}'
    mock_resp.usage_metadata.prompt_token_count = 120
    mock_resp.usage_metadata.candidates_token_count = 60
    mock_resp.usage_metadata.candidates = [MagicMock(thinking_token_count=0)]

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = MagicMock(return_value=asyncio.Future())
    mock_client.aio.models.generate_content.return_value.set_result(mock_resp)

    with patch("core.gemini_ocr.genai.Client", return_value=mock_client), \
         patch("core.gemini_ocr.CACHE_DIR", tmp_path / "cache"):

        # 1. First call -> misses cache, calls API
        res1 = await ocr_page(jpeg_bytes, settings, "gemini-2.5-pro", force_refresh=False)
        assert res1.markdown == "Hello world"
        assert mock_client.aio.models.generate_content.call_count == 1

        # 2. Second call with same data -> hits disk cache, 0 API calls
        res2 = await ocr_page(jpeg_bytes, settings, "gemini-2.5-pro", force_refresh=False)
        assert res2.markdown == "Hello world"
        assert mock_client.aio.models.generate_content.call_count == 1 # still 1!

