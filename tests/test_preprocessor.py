"""
Tests for core.preprocessor: PDF rendering (300 DPI, page-by-page), virtual cropping,
deskewing, thumbnail creation, and Gemini-ready JPEG encoding.
"""
from pathlib import Path
try:
    import pymupdf as fitz
except ImportError:
    import fitz
import numpy as np
import pytest
from PIL import Image
from core.preprocessor import ingest_file, cropped, encode_for_gemini, deskew

def create_sample_pdf(num_pages: int = 3) -> bytes:
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842) # A4
        page.insert_text((72, 100), f"Page {i+1} Sinhala Physics Past Paper", fontsize=24)
        # Draw a small rectangle simulating content
        page.draw_rect(fitz.Rect(72, 150, 500, 400), color=(0, 0, 0), width=2)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def test_ingest_pdf_pages(tmp_path: Path):
    pdf_bytes = create_sample_pdf(3)
    project_dir = tmp_path / "project_1"
    
    pages = ingest_file(
        file_bytes=pdf_bytes,
        filename="test_paper.pdf",
        project_dir=project_dir,
        start_index=1,
        default_top_crop=1.0,
        default_bottom_crop=5.0
    )
    
    assert len(pages) == 3
    for idx, page in enumerate(pages, start=1):
        assert page.index == idx
        source_path = project_dir / page.source_file
        work_path = project_dir / page.work_file
        thumb_path = project_dir / page.thumb_file
        
        assert source_path.exists()
        assert work_path.exists()
        assert thumb_path.exists()
        assert page.width > 2000 # 300 DPI A4 is ~2480px
        assert page.height > 3000

def test_virtual_crop():
    img = Image.new("RGB", (1000, 2000), color=(255, 255, 255))
    # Crop 10% from top (200px) and 10% from bottom (200px)
    c_img = cropped(img, top_pct=10.0, bottom_pct=10.0)
    assert c_img.size == (1000, 1600)

def test_encode_for_gemini():
    # Large image 3000 x 4000
    large_img = Image.new("RGB", (3000, 4000), color=(200, 200, 200))
    jpeg_bytes = encode_for_gemini(large_img, max_long_edge=2400, quality=90)
    assert len(jpeg_bytes) > 0
    
    # Verify resulting dimensions
    with Image.open(io.BytesIO(jpeg_bytes) if "io" in globals() else __import__("io").BytesIO(jpeg_bytes)) as decoded:
        assert max(decoded.size) == 2400
        assert decoded.format == "JPEG"

def test_deskew_no_crash():
    img = Image.new("RGB", (500, 500), color=(255, 255, 255))
    result = deskew(img)
    assert result.size == (500, 500)
