"""
Unit and Integration Tests for Phase 4 Features:
- Erase region tool (white-out rectangles before OCR)
- Automatic header/footer crop suggestion (OpenCV horizontal rule detection)
- Perspective correction for phone photos
- Desktop shortcut and packaging validation
"""
import io
import numpy as np
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from main import app
from core.image_enhancements import apply_erase_regions, suggest_header_footer_crop, correct_perspective
from tools.create_desktop_shortcut import create_desktop_shortcut

client = TestClient(app)

def test_apply_erase_regions():
    # Create black image 400x400
    img = Image.new("RGB", (400, 400), color=(0, 0, 0))
    # Erase box [50, 50, 150, 150] (ymin, xmin, ymax, xmax)
    erased = apply_erase_regions(img, [[50, 50, 150, 150]])

    arr = np.array(erased)
    # Check pixels inside box are pure white (255, 255, 255)
    assert np.all(arr[75, 75] == [255, 255, 255])
    assert np.all(arr[100, 100] == [255, 255, 255])
    # Check pixels outside box remain black (0, 0, 0)
    assert np.all(arr[10, 10] == [0, 0, 0])
    assert np.all(arr[200, 200] == [0, 0, 0])

def test_suggest_header_footer_crop():
    # Create white page 800x1200
    img = Image.new("RGB", (800, 1200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw horizontal rule in top 10% (y = 80, length 400px)
    draw.line([(100, 80), (700, 80)], fill=(0, 0, 0), width=3)

    # Draw horizontal rule in bottom 10% (y = 1120, length 400px)
    draw.line([(100, 1120), (700, 1120)], fill=(0, 0, 0), width=3)

    top_pct, bottom_pct = suggest_header_footer_crop(img)

    assert top_pct is not None
    assert 5.0 <= top_pct <= 12.0

    assert bottom_pct is not None
    assert 5.0 <= bottom_pct <= 12.0

def test_correct_perspective_no_crash():
    # Plain image should return (original, False) gracefully
    img = Image.new("RGB", (600, 800), color=(240, 240, 240))
    corrected, success = correct_perspective(img)
    assert isinstance(corrected, Image.Image)

def test_phase4_api_endpoints():
    # 1. Create project
    resp = client.post("/api/projects", json={"name": "Phase 4 Test Project"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    try:
        # 2. Upload sample image with divider rules
        img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.line([(100, 70), (700, 70)], fill=(0, 0, 0), width=3)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        files = {"files": ("p1.png", buf.getvalue(), "image/png")}
        resp = client.post(f"/api/projects/{pid}/upload", files=files)
        assert resp.status_code == 200

        # 3. Test suggest-crop endpoint
        crop_resp = client.post(f"/api/projects/{pid}/pages/1/suggest-crop?apply=true")
        assert crop_resp.status_code == 200
        crop_data = crop_resp.json()
        assert "detected" in crop_data
        assert "top_pct" in crop_data
        assert "bottom_pct" in crop_data

        # 4. Test erase region endpoints (POST + DELETE)
        erase_resp = client.post(f"/api/projects/{pid}/pages/1/erase-regions", json={
            "box_px": [100, 100, 250, 400]
        })
        assert erase_resp.status_code == 200
        erase_data = erase_resp.json()
        eid = erase_data["id"]
        assert eid.startswith("e")
        assert erase_data["box_px"] == [100, 100, 250, 400]

        # Verify page now has erase region
        p_resp = client.get(f"/api/projects/{pid}")
        assert p_resp.status_code == 200
        p_data = p_resp.json()
        assert len(p_data["pages"]["1"]["erase_regions"]) == 1

        # Delete erase region
        del_erase = client.delete(f"/api/projects/{pid}/pages/1/erase-regions/{eid}")
        assert del_erase.status_code == 204

        # Confirm deleted
        p_resp2 = client.get(f"/api/projects/{pid}")
        assert len(p_resp2.json()["pages"]["1"]["erase_regions"]) == 0

        # 5. Test perspective-fix endpoint
        fix_resp = client.post(f"/api/projects/{pid}/pages/1/perspective-fix")
        assert fix_resp.status_code == 200
        assert "success" in fix_resp.json()

    finally:
        client.delete(f"/api/projects/{pid}")

def test_desktop_shortcut_creation():
    # Test shortcut creation function runs without throwing exceptions
    success = create_desktop_shortcut()
    assert isinstance(success, bool)
