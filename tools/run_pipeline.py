"""
CLI Runner for Sinhala & English Physics Paper Digitizer (SPEC P1-T07 & P1-T12).
Usage:
    python tools/run_pipeline.py <file_path> [--model accurate|draft] [--force] [--embed-fonts]

Executes the complete backend pipeline from the CLI:
1. Ingestion & Preprocessing (PDF DPI=300 extraction or image EXIF transpose + deskew)
2. Gemini OCR with disk caching (SHA-256)
3. Watermark / Advertisement scrubbing
4. Diagram extraction & contrast cleaning
5. Markdown normalization & Pandoc DOCX export with Sinhala OpenXML post-processing
6. Writes results and cost summary to out/<name>/
"""
import argparse
import asyncio
import io
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import Settings, Page, Diagram
from core.config_manager import get_settings
from core.preprocessor import ingest_file, cropped, encode_for_gemini
from core.gemini_ocr import ocr_page
from core.scrubber import scrub
from core.diagram_extractor import convert_normalized_box_to_work_pixels, extract_diagram
from core.docx_exporter import export_to_docx

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s]: %(message)s"
)
logger = logging.getLogger("run_pipeline")

async def process_pipeline(
    input_file: Path,
    model_mode: str = "accurate",
    force: bool = False,
    embed_fonts: bool = False
):
    start_time = time.time()
    settings = get_settings()

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)

    stem = input_file.stem
    out_dir = PROJECT_ROOT / "out" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    diagrams_dir = out_dir / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(f"Physics Paper Digitizer CLI Pipeline")
    print(f"Input: {input_file.name} | Model: {model_mode} | Force: {force}")
    print("=" * 65)

    # 1. Ingest input file
    print(f"\n1. Ingesting {input_file.name}...")
    file_bytes = input_file.read_bytes()
    temp_pdir = out_dir / "_temp_work"
    temp_pdir.mkdir(parents=True, exist_ok=True)

    pages = ingest_file(
        file_bytes=file_bytes,
        filename=input_file.name,
        project_dir=temp_pdir,
        start_index=1,
        deskew_enabled=settings.auto_deskew,
        default_top_crop=settings.default_top_crop_percent,
        default_bottom_crop=settings.default_bottom_crop_percent
    )
    print(f"Extracted {len(pages)} page(s).")

    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0
    total_cost_usd = 0.0
    merged_markdown_parts = []
    global_diagrams_map: Dict[str, Dict[str, Any]] = {}

    model_id = settings.gemini_model if model_mode == "accurate" else settings.gemini_draft_model

    # 2. Process each page
    for p in pages:
        p_num = p.index
        print(f"\n--- Processing Page {p_num}/{len(pages)} ---")

        work_path = temp_pdir / p.work_file
        with Image.open(work_path) as w_img:
            work_w, work_h = w_img.size
            cropped_img = cropped(w_img, p.crop.top_pct, p.crop.bottom_pct)
            jpeg_bytes = encode_for_gemini(
                cropped_img,
                max_long_edge=settings.send_max_long_edge_px,
                quality=settings.send_jpeg_quality
            )

        print(f"Running Gemini OCR ({model_id})...")
        ocr_res = await ocr_page(
            jpeg_bytes=jpeg_bytes,
            settings=settings,
            model_override=model_id,
            force_refresh=force
        )

        in_tok = ocr_res.usage.get("input", 0)
        out_tok = ocr_res.usage.get("output", 0)
        think_tok = ocr_res.usage.get("thinking", 0)
        total_input_tokens += in_tok
        total_output_tokens += out_tok
        total_thinking_tokens += think_tok
        total_cost_usd += ocr_res.cost_usd

        print(f"OCR Complete: {in_tok} in / {out_tok} out / {think_tok} thinking (${ocr_res.cost_usd:.4f})")

        # 3. Scrub
        scrubbed_md, removed = scrub(ocr_res.markdown, settings)
        if removed:
            print(f"Scrubbed {len(removed)} watermarks/patterns: {removed[:3]}")

        # 4. Extract Diagrams
        page_diagrams_map = {}
        for d in ocr_res.diagrams:
            box_px = convert_normalized_box_to_work_pixels(
                box_2d=d.box_2d,
                work_w=work_w,
                work_h=work_h,
                top_pct=p.crop.top_pct,
                bottom_pct=p.crop.bottom_pct
            )
            clean_file = diagrams_dir / f"p{p_num:03d}_{d.id}.png"
            raw_file = diagrams_dir / f"p{p_num:03d}_{d.id}_raw.png"

            snapped_box, width_pct = extract_diagram(
                work_img_path=work_path,
                box_px=box_px,
                dest_clean_path=clean_file,
                dest_raw_path=raw_file,
                mode=settings.diagram_clean_mode
            )
            page_diagrams_map[d.id] = {
                "file": f"diagrams/{clean_file.name}",
                "width_pct": width_pct
            }
            global_diagrams_map[d.id] = page_diagrams_map[d.id]
            print(f"Extracted diagram {d.id} -> {clean_file.name} (width {width_pct}%)")

        # Save page markdown
        page_md_file = out_dir / f"page_{p_num}.md"
        page_md_file.write_text(scrubbed_md, encoding="utf-8")
        merged_markdown_parts.append(scrubbed_md)

        # 5. Export individual page DOCX
        page_docx_file = out_dir / f"page_{p_num}.docx"
        export_to_docx(
            markdown=scrubbed_md,
            output_docx_path=page_docx_file,
            settings=settings,
            diagrams_map=page_diagrams_map,
            project_dir=out_dir,
            strip_flags=True,
            embed_fonts=embed_fonts
        )
        print(f"Generated page DOCX: {page_docx_file.name}")

    # 6. Export Merged DOCX
    merged_md = "\n\n<!-- pagebreak -->\n\n".join(merged_markdown_parts)
    merged_docx_file = out_dir / f"{stem}_merged.docx"
    export_to_docx(
        markdown=merged_md,
        output_docx_path=merged_docx_file,
        settings=settings,
        diagrams_map=global_diagrams_map,
        project_dir=out_dir,
        strip_flags=True,
        embed_fonts=embed_fonts
    )
    print(f"\nGenerated Merged DOCX: {merged_docx_file.name}")

    # 7. Write cost & timing summary
    elapsed = time.time() - start_time
    cost_summary = (
        f"Input File: {input_file.name}\n"
        f"Total Pages: {len(pages)}\n"
        f"Model: {model_id} ({model_mode})\n"
        f"Execution Time: {elapsed:.2f} seconds\n"
        f"Input Tokens: {total_input_tokens}\n"
        f"Output Tokens: {total_output_tokens}\n"
        f"Thinking Tokens: {total_thinking_tokens}\n"
        f"Total Cost USD: ${total_cost_usd:.5f}\n"
        f"Avg Cost Per Page: ${total_cost_usd / max(1, len(pages)):.5f}\n"
    )
    cost_file = out_dir / "cost.txt"
    cost_file.write_text(cost_summary, encoding="utf-8")

    print("\n" + "=" * 65)
    print("PIPELINE EXECUTION COMPLETE")
    print(cost_summary)
    print(f"Output files located in: {out_dir.resolve()}")
    print("=" * 65)

def main():
    parser = argparse.ArgumentParser(description="Sinhala & English Physics Paper Digitizer Pipeline Runner")
    parser.add_argument("file", help="Path to PDF or image file to digitize")
    parser.add_argument("--model", choices=["accurate", "draft"], default="accurate", help="Gemini model mode (default: accurate)")
    parser.add_argument("--force", action="store_true", help="Force re-run ignoring cache")
    parser.add_argument("--embed-fonts", action="store_true", help="Embed TrueType fonts into DOCX via Word COM")

    args = parser.parse_args()
    asyncio.run(process_pipeline(
        input_file=Path(args.file),
        model_mode=args.model,
        force=args.force,
        embed_fonts=args.embed_fonts
    ))

if __name__ == "__main__":
    main()
