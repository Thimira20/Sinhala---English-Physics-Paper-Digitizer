"""
Image Enhancements module for Phase 4:
- Automatic header/footer crop suggestion (OpenCV horizontal rule detection in top/bottom 15%)
- Erase region tool (white-out rectangles before OCR)
- Perspective correction for phone photos (4-corner contour detection + cv2.warpPerspective)
"""
import logging
import math
from typing import List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

def apply_erase_regions(img: Image.Image, erase_boxes_px: List[List[int]]) -> Image.Image:
    """
    Overlays pure white (#FFFFFF) rectangles on the given image for each [ymin, xmin, ymax, xmax] box.
    Coordinates are in pixel space of the input image.
    """
    if not erase_boxes_px:
        return img

    out_img = img.copy()
    draw = ImageDraw.Draw(out_img)
    w, h = out_img.size

    for box in erase_boxes_px:
        if len(box) != 4:
            continue
        ymin, xmin, ymax, xmax = box
        # Clamp to bounds
        xmin = max(0, min(xmin, w))
        xmax = max(0, min(xmax, w))
        ymin = max(0, min(ymin, h))
        ymax = max(0, min(ymax, h))
        if xmax > xmin and ymax > ymin:
            draw.rectangle([xmin, ymin, xmax, ymax], fill=(255, 255, 255))

    return out_img

def suggest_header_footer_crop(pil_img: Image.Image) -> Tuple[Optional[float], Optional[float]]:
    """
    SPEC P3-T10: OpenCV horizontal rule detection in the top/bottom 15% of the page.
    Returns (top_pct, bottom_pct) or (None, None) if no reliable lines detected.
    """
    img_np = np.array(pil_img)
    if img_np.ndim == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np

    h, w = gray.shape[:2]
    if h < 50 or w < 50:
        return None, None

    # Threshold for dark horizontal rules
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # 1. Top 15%
    top_limit = int(round(h * 0.15))
    top_roi = thresh[0:top_limit, :]
    min_line_len = max(20, int(w * 0.20))  # at least 20% of page width
    
    # Horizontal morphological kernel to highlight horizontal strokes
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_line_len // 2, 1))
    top_lines = cv2.morphologyEx(top_roi, cv2.MORPH_OPEN, horiz_kernel)
    
    suggested_top_pct: Optional[float] = None
    y_coords, _ = np.where(top_lines > 0)
    if len(y_coords) > 0:
        # The lowest detected horizontal rule in the top 15%
        lowest_header_y = int(np.percentile(y_coords, 90))
        # Place crop slightly below line (add margin)
        suggested_top_pct = round(min(14.9, (lowest_header_y + 8) / float(h) * 100.0), 1)

    # 2. Bottom 15%
    bottom_start = int(round(h * 0.85))
    bottom_roi = thresh[bottom_start:h, :]
    bottom_lines = cv2.morphologyEx(bottom_roi, cv2.MORPH_OPEN, horiz_kernel)
    
    suggested_bottom_pct: Optional[float] = None
    by_coords, _ = np.where(bottom_lines > 0)
    if len(by_coords) > 0:
        # The highest detected horizontal rule in bottom 15%
        highest_footer_y = bottom_start + int(np.percentile(by_coords, 10))
        # Place bottom crop slightly above the line
        bottom_margin_px = h - highest_footer_y + 8
        suggested_bottom_pct = round(min(14.9, bottom_margin_px / float(h) * 100.0), 1)

    return suggested_top_pct, suggested_bottom_pct

def order_points(pts: np.ndarray) -> np.ndarray:
    """Orders 4 coordinates: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    # Top-left has smallest sum (x+y), bottom-right has largest sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # Top-right has smallest difference (y-x), bottom-left has largest diff
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def correct_perspective(pil_img: Image.Image) -> Tuple[Image.Image, bool]:
    """
    SPEC P3-T10: Perspective correction for phone photos (4-corner detection + warpPerspective).
    Detects the boundary of a paper sheet photographed at an angle, unwarps it to a clean rectangle.
    Returns (corrected_image, success_flag).
    """
    img_np = np.array(pil_img)
    orig_h, orig_w = img_np.shape[:2]
    if orig_h < 100 or orig_w < 100:
        return pil_img, False

    # Work on resized copy for edge detection
    target_dim = 1000.0
    scale = target_dim / max(orig_h, orig_w)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    resized = cv2.resize(img_np, (new_w, new_h))

    if resized.ndim == 3:
        gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    else:
        gray = resized

    # Blur & Canny edge detection
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 30, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(edged, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

    doc_quad = None
    min_area = (new_w * new_h) * 0.25  # document must be at least 25% of image area

    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            doc_quad = approx.reshape(4, 2)
            break

    if doc_quad is None:
        return pil_img, False

    # Scale back points to original image size
    orig_pts = doc_quad.astype("float32") / scale
    rect = order_points(orig_pts)
    (tl, tr, br, bl) = rect

    # Calculate target width & height
    width_a = math.hypot(br[0] - bl[0], br[1] - bl[1])
    width_b = math.hypot(tr[0] - tl[0], tr[1] - tl[1])
    max_w = max(int(width_a), int(width_b))

    height_a = math.hypot(tr[0] - br[0], tr[1] - br[1])
    height_b = math.hypot(tl[0] - bl[0], tl[1] - bl[1])
    max_h = max(int(height_a), int(height_b))

    if max_w < 50 or max_h < 50:
        return pil_img, False

    dst = np.array([
        [0, 0],
        [max_w - 1, 0],
        [max_w - 1, max_h - 1],
        [0, max_h - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(
        img_np, M, (max_w, max_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255)
    )

    return Image.fromarray(warped), True
