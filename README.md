# Sinhala & English Physics Paper Digitizer

An offline-first, high-precision digitizer designed for Sri Lankan A/L Physics past papers. It ingests scanned PDF or image exam papers, runs Gemini Vision OCR, generates clean Sinhala/English Markdown with LaTeX equations and extracted diagram figures, and provides a split-view interactive editor with live KaTeX preview, diagram cropping, and export to DOCX/PDF.

---

## 1. Installation & Running

### Requirements
- Windows 10/11 (64-bit)
- Python 3.10+ (recommended: Python 3.11)
- Google Gemini API Key

### Quick Start
1. Clone or extract this repository into your workspace.
2. Run `setup.bat` to create the virtual environment (`.venv`) and install all dependencies:
   ```cmd
   setup.bat
   ```
3. Run `run.bat` to start the local web application:
   ```cmd
   run.bat
   ```
4. Open your browser and navigate to:
   ```
   http://127.0.0.1:8000/
   ```
5. Click **Settings** (gear icon) in the top-right corner to input your Gemini API key and adjust model preferences.

---

## 2. Spike A Results: Sinhala Inside Word Equations

During Phase 1 exploration, we evaluated whether complex Sinhala Unicode characters render accurately inside native Microsoft Word equation objects (OMML) versus placing Sinhala text outside equations:

- **Finding**: Native Word OMML with the embedded **Noto Sans Sinhala** font renders Sinhala text inside equations cleanly without broken conjunct glyphs or dotted circles on modern Microsoft 365 / Word 2019+.
- **Configuration**:
  - Default setting: `"sinhala_math_mode": "omml"` (in `config.default.json` and `core/models.py`).
  - Fallback option: If using older versions of Microsoft Word (Word 2013/2016) where OMML font substitution may cause broken ligatures, set `"sinhala_math_mode": "outside"` in Settings to keep Sinhala text in normal paragraph runs outside equation tags.

---

## 3. Spike B Results: Gemini Model Selection & Cost Analysis

We benchmarked Gemini vision models on sample Sinhala physics examination pages:

- **Accurate Model**: `gemini-3.8-flash` (or `gemini-2.5-pro` for complex handwritten diagrams). Excels at transcribing complex physics fractions, Greek symbols ($\theta, \omega, \mu$), and Sinhala technical terms.
- **Draft Model**: `gemini-3.5-flash-lite` (or `gemini-2.5-flash`). Extremely fast transcription suitable for draft passes and rapid initial review.
- **Estimated Costs**:
  - Processing a typical past paper page consumes ~1,500 – 3,000 input tokens and ~800 – 1,500 output tokens.
  - Estimated cost: ~$0.002 to $0.008 per page using Flash tier models.
- **Pricing Note**:
  The rates defined in `config.default.json` (`pricing_usd_per_million_tokens`) are initial placeholders. Users should verify current pricing at [Google Cloud / AI Studio Pricing](https://ai.google.dev/pricing).

---

## 4. Architecture & Key Features (Phase 1 & Phase 2)

- **3-Pane Split Workspace**:
  - **Left Pane**: Page strip with reorderable thumbnails, status dots (pending, queued, processing, done, error), uncertain flag counts, and retry buttons.
  - **Center Pane**: High-performance canvas-based source viewer with SVG overlays, space+drag panning, wheel zooming, draggable top/bottom margin crop lines, and interactive diagram bounding boxes.
  - **Right Pane**: Split-view editor featuring EasyMDE/CodeMirror with syntax highlighting for `[?uncertain?]` flags, diagram tags `{{DIAGRAM:id}}`, and live preview with KaTeX mathematical typography.
- **Offline-First & CDN-Free**:
  - All fonts (**Noto Sans Sinhala**, **Noto Sans**, **Inter**) and vendor libraries (**CodeMirror/EasyMDE**, **KaTeX**, **DOMPurify**, **Marked**) are vendored locally in `static/vendor/` and `static/fonts/`.
  - Zero CDN requests are made at runtime.
- **Resilient Concurrency & Windows File Safety**:
  - Project state persistence (`project.json`) uses locked read-modify-write transactions (`ProjectStore.edit()`) and retrying atomic replacement to eliminate Windows file-locking race conditions (`WinError 5 Access is denied`).
  - Background OCR jobs run through an asynchronous queue with live Server-Sent Events (SSE) broadcasting real-time progress and dynamic ETAs.

---

## 5. Troubleshooting & Operations Guide

### 1. Sinhala & Latin Fonts
- **Requirement**: For Microsoft Word to render Sinhala characters without dotted circles or broken conjunct glyphs, **Noto Sans Sinhala** should ideally be installed on the host operating system.
- **Font Embedding**: The exporter includes an "Embed fonts in DOCX" option (enabled by default). When enabled on machines with Microsoft Word installed, Word COM embeds the true-type font definitions directly into the `.docx` document so that it renders identically on recipient machines without the font installed.
- **Font Files**: Bundled static TTFs reside in `static/fonts/` (`NotoSansSinhala-Regular.ttf`, `NotoSansSinhala-Bold.ttf`, `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf`).

### 2. Microsoft Word Automation & COM
- **Requirements**: Microsoft Word 2016, 2019, 2021, or Microsoft 365 (64-bit or 32-bit) with `pywin32`.
- **Process Isolation & Safety**: Word COM runs on a dedicated single-threaded worker thread with an enforced 90-second timeout per export. The worker records the exact PID of started `WINWORD.EXE` instances to guarantee no orphaned background processes are left running on errors.
- **PDF Engine Fallback**: If Microsoft Word is not installed or COM fails:
  1. The exporter automatically falls back to **LibreOffice** headless (`soffice.exe --headless`).
  2. If LibreOffice is also absent, it seamlessly falls back to the **Browser Print Engine** (`/print/{pid}`), opening a typeset A4 print-preview tab that invokes native `window.print()` for 1-click "Save as PDF".

### 3. Google Gemini API Key & Vision Models
- **API Key Setup**: Click the **Settings** gear icon in the top-right header, paste your Gemini API key, and click **Test Key**. The app verifies the key and automatically populates the available vision models.
- **Log Security**: The logging subsystem includes an `ApiKeyFilter` that scrubs all occurrences of Gemini API keys from terminal output and `workspace/logs/app.log`.
- **Model Deprecations**: Note that older models like `gemini-2.5-flash` have been retired by Google. Always select active models such as `gemini-3.5-flash-lite` (draft) and `gemini-3.5-flash` or `gemini-2.5-pro` (accurate) in the Settings modal.

### 4. Pandoc & DOCX Conversion
- **Bundled Engine**: Pandoc is bundled via `pypandoc_binary` (no system Pandoc installation is necessary).
- **Template Rebuilding**: The high-fidelity OpenXML reference template (`assets/reference.docx`) is auto-generated and hashed (`assets/reference.hash`). If font sizes or paragraph spacing settings change in `config.json`, the exporter automatically rebuilds the template on the fly.
- **Inspection & Logs**: Server logs are saved to `workspace/logs/app.log`. In case of any unhandled error, the user interface displays a notification with a direct "See log" action button to inspect errors.

---

## 6. Known Limitations

1. **Microsoft Word Font Rendering**: Word requires the `Noto Sans Sinhala` font to be present or embedded in exported `.docx` documents for accurate offline rendering of Sinhala typography.
2. **Scan Quality**: Highly degraded or low-resolution scans (<150 DPI) may yield higher numbers of uncertain flags (`[?text?]`). The built-in Deskew filter and manual diagram cropping tools help mitigate poor scan orientation.

