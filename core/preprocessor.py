"""
Preprocessor module: handles PDF rendering (300 DPI, one page at a time),
EXIF-aware image normalization, deskewing with OpenCV, non-destructive cropping,
and thumbnail/Gemini-ready image generation.
"""
import io
import logging
from pathlib import Path
from typing import List, Tuple
import cv2
import numpy as np
from PIL import Image, ImageOps
try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

from core.models import Page, PageCrop

logger = logging.getLogger(__name__)

def deskew(pil_img: Image.Image) -> Image.Image:
    """
    Detects slight skew angle using OpenCV minAreaRect on text pixels.
    Rotates image if 0.3 <= |angle| <= 10.0 degrees with a clean white fill.
    """
    img_np = np.array(pil_img)
    if img_np.ndim == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np

    # Otsu inverse threshold to extract ink pixels
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 100:
        return pil_img

    rect = cv2.minAreaRect(coords)
    angle = rect[-1]

    # Convert OpenCV angle to [-45, 45] range
    if angle < -45:
        angle = -(90 + angle)
    elif angle > 45:
        angle = 90 - angle
    else:
        angle = -angle

    if 0.3 <= abs(angle) <= 10.0:
        logger.info(f"Deskewing image by {angle:.2f} degrees")
        return pil_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    return pil_img

def cropped(work_img: Image.Image, top_pct: float, bottom_pct: float) -> Image.Image:
    """Returns an in-memory virtual crop without modifying the source image."""
    w, h = work_img.size
    top_px = int(round(h * (top_pct / 100.0)))
    bottom_px = int(round(h * (1.0 - bottom_pct / 100.0)))
    top_px = max(0, min(top_px, h - 10))
    bottom_px = max(top_px + 10, min(bottom_px, h))
    return work_img.crop((0, top_px, w, bottom_px))

def encode_for_gemini(img: Image.Image, max_long_edge: int = 2400, quality: int = 90) -> bytes:
    """
    Downscales image so max(w, h) <= max_long_edge and encodes as high-quality JPEG.
    Used for token-efficient and fast Gemini Vision uploads.
    """
    w, h = img.size
    max_dim = max(w, h)
    if max_dim > max_long_edge:
        scale = max_long_edge / float(max_dim)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        img = img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

def create_thumbnail(img: Image.Image, thumb_path: Path, thumb_width: int = 240, quality: int = 85) -> None:
    """Generates a small thumbnail for the UI page strip."""
    w, h = img.size
    scale = thumb_width / float(w)
    thumb_h = int(round(h * scale))
    thumb = img.resize((thumb_width, thumb_h), resample=Image.Resampling.LANCZOS)
    if thumb.mode != "RGB":
        thumb = thumb.convert("RGB")
    thumb.save(thumb_path, format="JPEG", quality=quality)

def ingest_file(
    file_bytes: bytes,
    filename: str,
    project_dir: Path,
    start_index: int = 1,
    deskew_enabled: bool = False,
    default_top_crop: float = 0.0,
    default_bottom_crop: float = 6.5
) -> List[Page]:
    """
    Ingests an uploaded PDF or image file.
    For PDFs: renders pages at 300 DPI strictly one page at a time to keep RAM peak < 600 MB.
    Returns list of Page models.
    """
    pages_dir = project_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    created_pages: List[Page] = []
    current_index = start_index

    is_pdf = filename.lower().endswith(".pdf") or file_bytes[:4] == b"%PDF"

    if is_pdf:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        logger.info(f"Ingesting PDF with {total_pages} pages")

        for page_num in range(total_pages):
            page_idx_str = f"p{current_index:03d}"
            source_file = pages_dir / f"{page_idx_str}_source.png"
            work_file = pages_dir / f"{page_idx_str}_work.png"
            thumb_file = pages_dir / f"{page_idx_str}_thumb.jpg"

            # Render 300 DPI one page at a time
            pdf_page = doc[page_num]
            pix = pdf_page.get_pixmap(dpi=300)
            pix.save(str(source_file))
            w, h = pix.width, pix.height
            pix = None # Free memory immediately

            # Open with PIL
            with Image.open(source_file) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode != "RGB":
                    img = img.convert("RGB")

                if deskew_enabled:
                    work_img = deskew(img)
                    work_img.save(work_file, format="PNG")
                    w, h = work_img.size
                else:
                    img.save(work_file, format="PNG")

                create_thumbnail(img, thumb_file)

            created_page = Page(
                index=current_index,
                source_file=f"pages/{source_file.name}",
                work_file=f"pages/{work_file.name}",
                thumb_file=f"pages/{thumb_file.name}",
                width=w,
                height=h,
                crop=PageCrop(top_pct=default_top_crop, bottom_pct=default_bottom_crop, override=False),
                deskew=deskew_enabled,
                status="pending"
            )
            created_pages.append(created_page)
            current_index += 1
        doc.close()

    else:
        # Single image upload (.jpg, .png, .webp)
        page_idx_str = f"p{current_index:03d}"
        source_file = pages_dir / f"{page_idx_str}_source.png"
        work_file = pages_dir / f"{page_idx_str}_work.png"
        thumb_file = pages_dir / f"{page_idx_str}_thumb.jpg"

        with Image.open(io.BytesIO(file_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(source_file, format="PNG")

            if deskew_enabled:
                work_img = deskew(img)
                work_img.save(work_file, format="PNG")
                w, h = work_img.size
            else:
                img.save(work_file, format="PNG")
                w, h = img.size

            create_thumbnail(img, thumb_file)

        created_page = Page(
            index=current_index,
            source_file=f"pages/{source_file.name}",
            work_file=f"pages/{work_file.name}",
            thumb_file=f"pages/{thumb_file.name}",
            width=w,
            height=h,
            crop=PageCrop(top_pct=default_top_crop, bottom_pct=default_bottom_crop, override=False),
            deskew=deskew_enabled,
            status="pending"
        )
        created_pages.append(created_page)

    return created_pages
