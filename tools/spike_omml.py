"""
Risk Spike A: Sinhala inside Microsoft Word OMML equations and complex script styling.
Converts tests/fixtures/spike.md to both raw post-processed DOCX and Word-embedded DOCX,
and prepares detailed instructions for the user to verify rendering in MS Word.
"""
from pathlib import Path
import sys
import shutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config_manager import get_settings
from core.docx_exporter import export_to_docx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_MD = PROJECT_ROOT / "tests" / "fixtures" / "spike.md"
EXPORTS_DIR = PROJECT_ROOT / "workspace" / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

RAW_DOCX = EXPORTS_DIR / "spike_raw.docx"
EMBEDDED_DOCX = EXPORTS_DIR / "spike_embedded.docx"

def main():
    print("================================================================")
    print("Risk Spike A: Sinhala Inside Word Equations & Font Verification")
    print("================================================================")
    
    settings = get_settings()
    markdown_content = FIXTURE_MD.read_text(encoding="utf-8")
    
    print(f"\n1. Converting fixture {FIXTURE_MD.name} to DOCX (raw post-processed)...")
    export_to_docx(
        markdown=markdown_content,
        output_docx_path=RAW_DOCX,
        settings=settings,
        embed_fonts=False
    )
    print(f"Generated: {RAW_DOCX}")

    print("\n2. Creating font-embedded version via MS Word COM...")
    shutil.copy2(RAW_DOCX, EMBEDDED_DOCX)
    from core.word_com import embed_fonts
    try:
        embed_fonts(EMBEDDED_DOCX)
        print(f"Generated: {EMBEDDED_DOCX}")
    except Exception as e:
        print(f"Word font embedding note: {e}")

    print("\nSpike generation complete.")
    print(f"Raw DOCX: {RAW_DOCX.resolve()}")
    print(f"Embedded DOCX: {EMBEDDED_DOCX.resolve()}")

if __name__ == "__main__":
    main()
