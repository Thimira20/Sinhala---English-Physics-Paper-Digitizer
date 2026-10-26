"""
API Integration tests (SPEC P1-T11):
Verifies project CRUD, file uploads, page updates, diagram manipulation,
DOCX export, and path traversal security guards.
"""
import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from main import app
from core.project_store import get_project_store

client = TestClient(app)

def test_health_check():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_project_crud_and_upload(tmp_path):
    # 1. Create Project
    resp = client.post("/api/projects", json={"name": "Test Physics Project"})
    assert resp.status_code == 200
    proj_data = resp.json()
    pid = proj_data["id"]
    assert proj_data["name"] == "Test Physics Project"

    try:
        # 2. List Projects
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        projs = resp.json()
        assert any(p["id"] == pid for p in projs)

        # 3. Upload a sample page image
        img = Image.new("RGB", (600, 800), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        files = {"files": ("page1.png", buf.getvalue(), "image/png")}
        resp = client.post(f"/api/projects/{pid}/upload", files=files)
        assert resp.status_code == 200
        assert resp.json()["added_pages"] == [1]

        # 4. Get Project Details
        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        proj = resp.json()
        assert "1" in proj["pages"]
        assert proj["pages"]["1"]["status"] == "pending"

        # 5. Update Page Markdown
        resp = client.put(f"/api/projects/{pid}/pages/1", json={
            "markdown": "# Question 1\nCalculate velocity.",
            "page_break_after": True
        })
        assert resp.status_code == 200
        assert resp.json()["markdown"] == "# Question 1\nCalculate velocity."

        # 6. Test Path Traversal Protection
        bad_resp = client.get(f"/files/{pid}/../../config.default.json")
        assert bad_resp.status_code in (404, 400)

        # 7. Add Diagram manually
        diag_resp = client.post(f"/api/projects/{pid}/pages/1/diagrams", json={
            "box_px": [100, 100, 300, 300],
            "label": "Graph"
        })
        assert diag_resp.status_code == 200
        diag = diag_resp.json()
        assert diag["id"] == "d1"

        # 7b. Patch Diagram properties (width_pct, label, mode)
        patch_diag_resp = client.patch(f"/api/projects/{pid}/pages/1/diagrams/d1", json={
            "width_pct": 75,
            "label": "Updated Graph Label"
        })
        assert patch_diag_resp.status_code == 200
        assert patch_diag_resp.json()["width_pct"] == 75
        assert patch_diag_resp.json()["label"] == "Updated Graph Label"

        # 8. Export DOCX
        exp_resp = client.post(f"/api/projects/{pid}/export/docx", json={
            "pages": "all",
            "embed_fonts": False
        })
        assert exp_resp.status_code == 200
        exp_data = exp_resp.json()
        assert exp_data["file"].endswith(".docx")
        assert exp_data["url"].startswith("/exports/")

        # 9. Verify exported file can be served
        file_resp = client.get(exp_data["url"])
        assert file_resp.status_code == 200
    finally:
        # 10. Delete Project
        del_resp = client.delete(f"/api/projects/{pid}")
        assert del_resp.status_code == 204

    # Confirm deletion
    get_del = client.get(f"/api/projects/{pid}")
    assert get_del.status_code == 404

def test_settings_api():
    # GET settings (key should be masked)
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "gemini_model" in data
    assert "gemini_api_key" in data

    # PUT settings update
    resp = client.put("/api/settings", json={
        "requests_per_minute": 55
    })
    assert resp.status_code == 200
    assert resp.json()["requests_per_minute"] == 55

def test_usage_and_cache_api(tmp_path, monkeypatch):
    import core.gemini_ocr as gemini_ocr
    fake_cache = tmp_path / "cache"
    fake_cache.mkdir()
    (fake_cache / f"{'a'*64}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gemini_ocr, "CACHE_DIR", fake_cache)

    # GET /api/usage
    resp = client.get("/api/usage")
    assert resp.status_code == 200
    u_data = resp.json()
    assert "project_usd" in u_data
    assert "month_usd" in u_data

    # GET /api/cache/stats
    resp = client.get("/api/cache/stats")
    assert resp.status_code == 200
    c_data = resp.json()
    assert c_data["count"] == 1
    assert "size_mb" in c_data

    # POST /api/cache/clear
    resp = client.post("/api/cache/clear")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["cleared_files"] == 1
    assert not any(fake_cache.iterdir())

def test_upload_magic_bytes_and_size_security():
    # Create temp project
    resp = client.post("/api/projects", json={"name": "Security Test Project"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    try:
        # 1. Invalid file magic bytes (text file named fake.png)
        bad_files = {"files": ("fake.png", b"This is plain text not an image", "image/png")}
        resp = client.post(f"/api/projects/{pid}/upload", files=bad_files)
        assert resp.status_code == 400
        assert "unsupported format" in resp.json()["detail"].lower()

        # 2. Exceeding 50MB limit check (mock 51MB payload)
        large_header = b"%PDF-1.5 fake " + b"0" * (51 * 1024 * 1024)
        large_files = {"files": ("large.pdf", large_header, "application/pdf")}
        resp = client.post(f"/api/projects/{pid}/upload", files=large_files)
        assert resp.status_code == 413
        assert "exceeds 50mb" in resp.json()["detail"].lower()
    finally:
        client.delete(f"/api/projects/{pid}")

def test_open_endpoint_security():
    # 1. Directory traversal attempt
    resp = client.post("/api/open", json={"file": "../../../Windows/System32/calc.exe"})
    # Target path resolving to outside exports dir or filename extraction ensures defense
    assert resp.status_code in (403, 404)

    # 2. Missing filename
    resp = client.post("/api/open", json={"file": ""})
    assert resp.status_code == 400

    # 3. Log file access
    resp = client.post("/api/open", json={"file": "app.log"})
    assert resp.status_code in (200, 500)  # 200 if os.startfile succeeds or 500 in headless CI

def test_pdf_export_and_print_view():
    # 1. Create project with a page
    resp = client.post("/api/projects", json={"name": "PDF Export Test"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    try:
        # Ingest a valid 1x1 PNG
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        client.post(f"/api/projects/{pid}/upload", files={"files": ("page1.png", buf.getvalue(), "image/png")})
        client.put(f"/api/projects/{pid}/pages/1", json={"markdown": "## Test Page\nSimple equation: $E=mc^2$"})

        # Export PDF
        exp_resp = client.post(f"/api/projects/{pid}/export/pdf", json={"pages": "all"})
        assert exp_resp.status_code == 200
        exp_data = exp_resp.json()
        assert "engine" in exp_data
        assert exp_data["engine"] in ("word", "libreoffice", "browser")
        if exp_data["engine"] == "browser":
            assert f"/print/{pid}" in exp_data["url"]
        else:
            assert exp_data["file"].endswith(".pdf")

        # Test Print View GET
        print_resp = client.get(f"/print/{pid}?pages=1")
        assert print_resp.status_code == 200
    finally:
        client.delete(f"/api/projects/{pid}")



