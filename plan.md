4. Core Technical Implementation Details
A. config.json (No Hardcoded Models or Keys)
Initialize config.json with:

JSON
{
  "gemini_api_key": "YOUR_API_KEY_HERE",
  "gemini_model": "gemini-2.5-flash",
  "default_top_crop_percent": 0.0,
  "default_bottom_crop_percent": 6.5,
  "sinhala_font": "Iskoola Pota",
  "branding_blacklist": [
    "Samitha Ratnayake",
    "Innovative Physics"
  ]
}
Allow the user to update these settings directly from a Settings modal in the UI.

B. Deterministic Pre-Processing (core/preprocessor.py)
Accept single/multiple images (.jpg, .png, .webp) or a .pdf file.

For PDFs, use fitz.open() and render each page at dpi=300 into workspace/uploads/.

Before calling Gemini, crop top_crop_percent from the top and bottom_crop_percent from the bottom of the image using Pillow. (In the UI, show visual horizontal crop lines on the left preview pane so the user can adjust the crop percentage per page or for the whole batch).

C. Gemini Vision API, Caching & System Prompt (core/gemini_ocr.py)
Compute the SHA-256 hash of the cropped image + prompt. If workspace/cache/{hash}.json exists and force_refresh=False, return the cached result immediately.

Implement retry with exponential backoff (initial delay 4s, multiplier 2, max 4 retries) for HTTP 429 (Rate Limit) or 503 errors.

Use this exact System Instruction for Gemini:

Plaintext
You are an expert Sri Lankan Physics document digitizer specializing in Sinhala and English typesetting.
Convert the provided physics document page into clean Markdown with LaTeX math.

STRICT RULES:
1. VERBATIM SINHALA & ENGLISH ACCURACY:
   - Transcribe all Sinhala text into accurate Sinhala Unicode.
   - DO NOT correct, rephrase, or modernize Sinhala spelling or grammar (e.g., preserve exact characters like නිමානය vs නිමානයනය, කල vs කළ).
   - Keep English terms in parentheses exactly as printed.
   - UNCERTAINTY FLAG: If any word or character is blurry, smudged, or ambiguous, wrap your best reading in [?word?] so the teacher can review it.
2. REMOVE BRANDING, HEADERS & FOOTERS:
   - Ignore and omit any remaining teacher names, tuition institute names, logos, phone numbers, watermarks, or page numbers (e.g., "- 3 -").
3. EQUATIONS & SINHALA FRACTIONS:
   - Format all inline equations with $...$ and standalone equations with $$...$$.
   - When an equation or vertical fraction contains Sinhala words, wrap the Sinhala words inside \text{...}, for example:
     $$\text{භාගික දෝෂය} = \frac{\text{දෝෂය}}{\text{පාඨාංකය}}$$
   - Use proper LaTeX commands for symbols: \pm, \times, \div, \theta, \Delta, \pi.
4. FORMATTING & CALLOUT BOXES:
   - Preserve bold (**...**) and underlined text (<u>...</u>).
   - If a heading or "වැදගත්" (Important) note is inside a gray shaded box, wrap that block in a blockquote (> ...).
5. PHYSICS DIAGRAMS & GRAPHS:
   - Whenever there is a physics diagram, circuit, free-body diagram, or graph (ignore decorative logos), insert a placeholder on its own line in the exact document position using normalized 0-1000 coordinates [ymin, xmin, ymax, xmax]:
     {{DIAGRAM: [ymin, xmin, ymax, xmax]}}
After receiving the Markdown text from Gemini, run a case-insensitive regex pass to strip any strings listed in branding_blacklist.

D. Diagram Cropping & Enhancement (core/diagram_extractor.py)
Parse the Markdown for all {{DIAGRAM: [ymin, xmin, ymax, xmax]}} tags.

Convert the 0–1000 normalized coordinates to actual pixel coordinates on the cropped 300 DPI image (add a small 10px padding).

Crop the region using Pillow, convert to grayscale in OpenCV, apply gentle denoising and adaptive thresholding or contrast stretching so gray scan shadows become pure white (#FFFFFF) while keeping diagram lines crisp.

Save to workspace/diagrams/diag_{page}_{idx}.png and replace the placeholder in Markdown with standard Markdown image syntax: ![Diagram](/workspace/diagrams/diag_{page}_{idx}.png).

E. The Split-Screen Review & Pre-Export Editor UI (static/)
Top Bar: Upload Photos/PDF button, Batch Page Selector (Page 1 of N), [?word?] Uncertainty Jump button (highlights any [?...] flags in yellow), Settings button, "Export to Word (.docx)" button, and "Export to PDF" button.

Left Pane (Source Viewer): Displays the uploaded page image with interactive Top/Bottom crop sliders and a "Re-run OCR on Page" button.

Right Pane (Live Editor & Preview):

A Markdown + LaTeX editor on top/left and a live-rendered A4 preview (using Marked.js + KaTeX) on bottom/right so the teacher can edit Sinhala theories, fix equations, delete unwanted text, or upload/replace images before exporting.

Include a "Merge Selected Pages into Single Tute" button that concatenates all reviewed pages in the batch into one unified document before export.

F. Word (.docx) Exporter with Sinhala Complex Script (w:cs) Fix (core/docx_exporter.py)
Before calling pypandoc.convert_text(..., to='docx', format='markdown+tex_math_dollars'), rewrite image URLs (/workspace/diagrams/...) to local filesystem paths so Pandoc embeds the images cleanly.

CRITICAL SINHALA FONT POST-PROCESSING: Open the Pandoc-generated .docx using python-docx. Iterate through all paragraphs, tables, runs, AND all Office Math (<m:oMath> / <m:r>) XML elements using lxml (oxml). Inject or update <w:rPr><w:rFonts w:ascii="Iskoola Pota" w:hAnsi="Iskoola Pota" w:cs="Iskoola Pota" w:eastAsia="Iskoola Pota"/></w:rPr> so that both normal Sinhala paragraphs and Sinhala text inside vertical Word equations render cleanly in Iskoola Pota (or the configured sinhala_font) without falling back to broken glyphs.

Style Markdown blockquotes (> ...) as lightly shaded gray callout boxes (#F2F2F2 background shading in Word XML) to match the original tute's shaded headings and "වැදගත්" boxes.

5. Deliverables
Generate all files cleanly according to the folder structure.

Include a setup script or clear terminal instructions to install dependencies (pip install ...) and verify pandoc availability (using pypandoc.download_pandoc() automatically if Pandoc is not installed on the system).


---

### How to Start Right Now
1. **Quick Free Test (5 Minutes)[cite: 2]:** Before running the code, you can test the exact System Prompt in Section 4C inside **Google AI Studio** with 2–3 of your toughest past paper pages (especially pages with circuits or tables) to see how it handles `[?word?]` flags and Sinhala fractions[cite: 2, 3].
2. **Build in Antigravity:** Paste the Master Prompt above into Antigravity. It is self-contained and instructs the agent to auto-download Pandoc via `pypandoc.download_pandoc()` so you don't even have to install Pandoc manually.

Would you like me to also write a quick standalone 40-line Python script that you can ru