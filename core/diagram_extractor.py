"""
Diagram Extractor: crops diagrams from high-resolution (300 DPI) work images,
snaps bounding boxes to ink boundaries to prevent clipped labels,
cleans scan shadows/background noise via background division + contrast stretching,
and saves DPI-tagged clean & raw diagram PNGs.
"""
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import cv2
import numpy as np
from PIL import Image

from core.models import Diagram, GeminiDiagram

logger = logging.getLogger(__name__)

def snap_box_to_ink(img_gray: np.ndarray, ymin: int, xmin: int, ymax: int, xmax: int, max_expand_px: int = 150) -> Tuple[int, int, int, int]:
    """
    Expands bounding box if ink pixels touch the borders (to include clipped labels/arrowheads),
    then trims outer white margins.
    """
    h, w = img_gray.shape
    _, thresh = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 1. Expand sides while border contains ink
    step = 8
    expanded = True
    expand_count = 0

    while expanded and expand_count < max_expand_px:
        expanded = False
        expand_count += step

        # Top border
        if ymin > 0:
            top_row = thresh[ymin:min(ymin+3, h), xmin:xmax]
            if np.mean(top_row > 0) > 0.005:
                ymin = max(0, ymin - step)
                expanded = True

        # Bottom border
        if ymax < h:
            bot_row = thresh[max(0, ymax-3):ymax, xmin:xmax]
            if np.mean(bot_row > 0) > 0.005:
                ymax = min(h, ymax + step)
                expanded = True

        # Left border
        if xmin > 0:
            left_col = thresh[ymin:ymax, xmin:min(xmin+3, w)]
            if np.mean(left_col > 0) > 0.005:
                xmin = max(0, xmin - step)
                expanded = True

        # Right border
        if xmax < w:
            right_col = thresh[ymin:ymax, max(0, xmax-3):xmax]
            if np.mean(right_col > 0) > 0.005:
                xmax = min(w, xmax + step)
                expanded = True

    # 2. Trim outer white margins within the box
    sub_thresh = thresh[ymin:ymax, xmin:xmax]
    coords = np.column_stack(np.where(sub_thresh > 0))
    if len(coords) > 20:
        sub_ymin, sub_xmin = coords.min(axis=0)
        sub_ymax, sub_xmax = coords.max(axis=0)
        margin = 6
        ymin = max(0, ymin + sub_ymin - margin)
        xmin = max(0, xmin + sub_xmin - margin)
        ymax = min(h, ymin + sub_ymax + margin)
        xmax = min(w, xmin + sub_xmax + margin)

    return ymin, xmin, ymax, xmax

def clean_diagram_image(crop_bgr: np.ndarray, mode: str = "normalize") -> np.ndarray:
    """
    Cleans diagram image.
    'normalize': division by blurred background to remove scan shadows, contrast stretching,
    light denoising, and clipping near-white pixels to pure #FFFFFF.
    'binary': adaptive Gaussian thresholding.
    'original': returns original crop untouched.
    """
    if mode == "original":
        return crop_bgr

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)

    if mode == "binary":
        bin_img = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
        return cv2.cvtColor(bin_img, cv2.COLOR_GRAY2BGR)

    # mode == "normalize" (default)
    # Estimate background illumination with large Gaussian blur
    blur_kernel = 51
    bg = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
    bg = np.maximum(bg, 1) # Prevent div by 0

    norm = (gray.astype(np.float32) / bg.astype(np.float32)) * 255.0
    norm = np.clip(norm, 0, 255).astype(np.uint8)

    # Contrast stretch (percentiles 2 to 98)
    p2, p98 = np.percentile(norm, (2, 98))
    if p98 > p2:
        norm = np.clip((norm - p2) * (255.0 / (p98 - p2)), 0, 255).astype(np.uint8)

    # Near-white pixels become pure white #FFFFFF
    norm[norm > 230] = 255

    # Light denoising
    cleaned = cv2.fastNlMeansDenoising(norm, h=7)
    cleaned[cleaned > 235] = 255

    return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)

def convert_normalized_box_to_work_pixels(
    box_2d: List[int],
    work_w: int,
    work_h: int,
    top_pct: float,
    bottom_pct: float
) -> List[int]:
    """
    Converts Gemini 0..1000 normalized coordinates (relative to the cropped image)
    into absolute pixel coordinates on work.png (§5.2).
    """
    ymin_n, xmin_n, ymax_n, xmax_n = box_2d
    crop_top_px = int(round(work_h * (top_pct / 100.0)))
    crop_bot_px = int(round(work_h * (bottom_pct / 100.0)))
    cropped_h = work_h - crop_top_px - crop_bot_px

    ymin_px = crop_top_px + int(round((ymin_n / 1000.0) * cropped_h))
    ymax_px = crop_top_px + int(round((ymax_n / 1000.0) * cropped_h))
    xmin_px = int(round((xmin_n / 1000.0) * work_w))
    xmax_px = int(round((xmax_n / 1000.0) * work_w))

    return [ymin_px, xmin_px, ymax_px, xmax_px]

def extract_diagram(
    work_img_path: Path,
    box_px: List[int],
    dest_clean_path: Path,
    dest_raw_path: Path,
    mode: str = "normalize"
) -> Tuple[List[int], int]:
    """
    Crops, snaps to ink boundaries, cleans, and saves diagram images.
    Returns (snapped_box_px, width_pct).
    """
    dest_clean_path.parent.mkdir(parents=True, exist_ok=True)
    img_bgr = cv2.imread(str(work_img_path))
    if img_bgr is None:
        raise ValueError(f"Could not load image: {work_img_path}")

    h, w = img_bgr.shape[:2]
    ymin, xmin, ymax, xmax = box_px

    # Pad 1% of page width
    pad = int(round(w * 0.01))
    ymin = max(0, ymin - pad)
    xmin = max(0, xmin - pad)
    ymax = min(h, ymax + pad)
    xmax = min(w, xmax + pad)

    # Snap to content ink
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    max_expand = int(round(w * 0.05))
    ymin, xmin, ymax, xmax = snap_box_to_ink(gray, ymin, xmin, ymax, xmax, max_expand_px=max_expand)

    # Raw crop
    raw_crop = img_bgr[ymin:ymax, xmin:xmax]
    cv2.imwrite(str(dest_raw_path), raw_crop)

    # Clean crop
    clean_crop = clean_diagram_image(raw_crop, mode=mode)
    cv2.imwrite(str(dest_clean_path), clean_crop)

    width_pct = int(round(((xmax - xmin) / float(w)) * 100.0))
    width_pct = max(15, min(100, width_pct))

    return [ymin, xmin, ymax, xmax], width_pct
