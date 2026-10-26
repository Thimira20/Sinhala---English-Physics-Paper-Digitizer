"""
Tests for core.diagram_extractor: coordinate conversion, snap-to-content on synthetic drawings,
and background cleaning normalization.
"""
from pathlib import Path
import cv2
import numpy as np
import pytest
from core.diagram_extractor import (
    convert_normalized_box_to_work_pixels,
    snap_box_to_ink,
    clean_diagram_image,
    extract_diagram
)

def test_convert_normalized_box():
    # 1000 x 2000 image, 10% top crop (200px), 10% bot crop (200px) -> cropped_h = 1600px
    # box 0..1000 in cropped space: [100, 200, 500, 600]
    # ymin = 200 + 0.1 * 1600 = 360
    # ymax = 200 + 0.5 * 1600 = 1000
    # xmin = 0.2 * 1000 = 200
    # xmax = 0.6 * 1000 = 600
    box_px = convert_normalized_box_to_work_pixels(
        box_2d=[100, 200, 500, 600],
        work_w=1000,
        work_h=2000,
        top_pct=10.0,
        bottom_pct=10.0
    )
    assert box_px == [360, 200, 1000, 600]

def test_snap_box_expands_to_include_shape():
    # Create white canvas 500 x 500
    canvas = np.full((500, 500), 255, dtype=np.uint8)
    # Draw a black circle from y=100..200, x=100..200
    cv2.circle(canvas, (150, 150), 40, 0, -1)
    
    # Intentionally clipped initial box (only center of circle)
    clipped_ymin, clipped_xmin, clipped_ymax, clipped_xmax = 130, 130, 170, 170
    
    snapped_ymin, snapped_xmin, snapped_ymax, snapped_xmax = snap_box_to_ink(
        canvas, clipped_ymin, clipped_xmin, clipped_ymax, clipped_xmax, max_expand_px=50
    )
    
    # Snapped box should encompass the circle (110..190) + margin
    assert snapped_ymin <= 115
    assert snapped_ymax >= 185
    assert snapped_xmin <= 115
    assert snapped_xmax >= 185

def test_clean_diagram_cleans_grey_shadow():
    # Synthetic diagram crop with light-grey scan shadow (e.g. #DCDCDC / 220) and black lines (0)
    crop = np.full((100, 100, 3), 215, dtype=np.uint8)
    # Draw dark line
    crop[40:60, 20:80] = 0
    
    cleaned = clean_diagram_image(crop, mode="normalize")
    
    # Shadow background should be elevated to pure white 255
    assert cleaned[10, 10, 0] >= 250
    # Dark line remains dark
    assert cleaned[50, 50, 0] < 50
