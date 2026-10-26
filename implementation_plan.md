# Sinhala & English Physics Paper Digitizer: Implementation Spec (Agent-Ready)

> [!IMPORTANT]
> **This document is the single source of truth.** It replaces `plan.md`. If `plan.md` and this document conflict, follow this document. Everything needed to build the app is written here. Do not rely on outside context.

---

## 0. Rules for the Implementing Agent (read first)

1. **Work phase by phase.** Implement Phase 1, then **STOP** and report to the user. Do the same after Phase 2. Never start the next phase without user approval.
2. **Follow the task IDs in order** (`P1-T01`, `P1-T02`, …). A task is complete only when its **Done when** criteria pass.
3. **🧑 USER CHECK** steps need a human (opening a file in MS Word, judging Sinhala accuracy). At those steps, prepare everything, tell the user exactly what to check, and wait.
4. **Never invent facts:**
   - **Gemini model IDs:** get them at runtime with `client.models.list()`. Defaults are in config and must be verified.
   - **Prices:** put them in config with a `# verify` note. The user confirms them.
   - **Library versions/URLs:** check they exist before pinning them.
5. **Platform:** Windows 10/11, Python **3.11 or 3.12**, PowerShell. Paths use `pathlib.Path`. Never hard-code drive letters. The project root may contain spaces and `&` (e.g. `D:\Sinhala & English Physics Paper Digitizer`), so always quote paths in `.bat` files and in subprocess calls use list arguments, never `shell=True`.
6. **Code conventions:**
   - Type hints everywhere and Pydantic v2 models for all API payloads.
   - `logging` (never `print`) and no global mutable state except `app.state`.
   - Every module gets a module docstring. Functions longer than ~40 lines get split.
7. **Build location:** the project root is the workspace folder `d:\Sinhala & English Physics Paper Digitizer\`. Put the app directly in it (no extra `physics_digitizer/` sub-folder).

---

## 1. Product Summary & Confirmed Decisions

This is a local web app for a Sri Lankan Physics teacher.
- **Input:** scanned or photographed past papers and tutes (JPG/PNG/WEBP or multi-page PDF) containing Sinhala + English text, LaTeX-style equations (including vertical fractions with Sinhala words) and diagrams.
- **Output:** clean, editable **.docx** and **.pdf** files with third-party branding removed.
- **Workflow:** upload → OCR with Gemini → review and edit in a split-screen editor → export.

| Topic | Decision |
|---|---|
| Runtime | FastAPI + uvicorn on `127.0.0.1`. Opens the default browser. **No Electron, Tauri or Playwright** |
| RAM | Must work well on an 8 GB machine (Python process peak < 600 MB) |
| OCR | Google Gemini via the official `google-genai` SDK (paid tier) |
| Default models | Accurate: `gemini-2.5-pro`. Draft: `gemini-2.5-flash` (**verify IDs at runtime**) |
| Parallelism | 4 concurrent OCR jobs, 60 requests per minute (configurable) |
| Sinhala font | **Noto Sans Sinhala** (static TTFs, bundled). Fallback: Iskoola Pota |
| Latin font | **Noto Sans** (bundled). Math font: Cambria Math (Word default) |
| MS Word | Installed. **Word COM** (`pywin32`) is used for PDF export and font embedding |
| MCQ layout | Default "as original" + per-block **MCQ Layout Switcher** |
| Inputs | Both clean scans and phone photos (EXIF rotate always on; deskew is a toggle) |
| Encoding | Unicode only. Legacy FM fonts are not supported |

---

## 2. Tech Stack (pinned choices)

| Layer | Choice | Notes |
|---|---|---|
| Server | `fastapi`, `uvicorn[standard]`, `python-multipart`, `sse-starlette` | SSE for job progress |
| Validation | `pydantic>=2`, `pydantic-settings` (optional) | |
| PDF/Image | `pymupdf`, `pillow`, `opencv-python-headless`, `numpy` | |
| AI | `google-genai` | Use the **async** client `client.aio` |
| DOCX | **`pypandoc_binary`** (bundles Pandoc ≥ 3.x, so nothing else to install), `python-docx`, `lxml` | Fall back to `pypandoc.download_pandoc()` only if the binary wheel fails |
| Word automation | `pywin32` | Word COM for embedding fonts and PDF export |
| Frontend | Vanilla HTML/CSS/JS (ES modules, no build step) | |
| Editor | **EasyMDE** (CodeMirror 5 inside) | Overlay modes for highlighting |
| Markdown preview | **marked** + **marked-katex-extension** (matching major versions) + **KaTeX** + **DOMPurify** | All **vendored locally** in `static/vendor/` |
| Tests | `pytest`, `pytest-asyncio` | |

Vendored JS is downloaded **once** by `tools/fetch_vendor.py` from jsDelivr (`https://cdn.jsdelivr.net/npm/<pkg>@<version>/...`). The script writes the exact versions to `static/vendor/VERSIONS.txt`. The app never loads a CDN at runtime.

---

## 3. Folder Structure

```text
<project root>/
├── setup.bat                    # venv, pip install, fetch vendor JS, install fonts, checks
├── run.bat                      # activate venv, python main.py
├── requirements.txt
├── config.default.json          # shipped defaults (committed)
├── config.json                  # user settings, created on first run (gitignored)
├── .gitignore                   # config.json, workspace/, .venv/
├── main.py                      # app factory, routers, lifespan, browser auto-open
├── api/
│   ├── __init__.py
│   ├── routes_projects.py       # projects CRUD, upload, page update, reorder
│   ├── routes_ocr.py            # enqueue OCR, SSE events
│   ├── routes_diagrams.py       # add/update/delete box, recrop, replace image
│   ├── routes_export.py         # docx / pdf / print view
│   └── routes_settings.py       # get/put settings, test key, list models
├── core/
│   ├── __init__.py
│   ├── config_manager.py
│   ├── models.py                # all Pydantic models (Project, Page, Diagram, Settings, ...)
│   ├── project_store.py         # load/save project.json (atomic, per-project lock)
│   ├── preprocessor.py
│   ├── prompts.py               # SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION
│   ├── gemini_ocr.py
│   ├── job_queue.py
│   ├── scrubber.py
│   ├── diagram_extractor.py
│   ├── markdown_dialect.py      # shared regexes: flags, diagram tags, mcq blocks, numbering escape
│   ├── markdown_normalizer.py   # editor Markdown -> Pandoc-ready Markdown
│   ├── docx_exporter.py
│   ├── docx_postprocess.py
│   ├── word_com.py
│   └── pdf_exporter.py
├── tools/
│   ├── fetch_vendor.py
│   ├── install_fonts.py
│   ├── build_reference_docx.py  # generates assets/reference.docx programmatically
│   ├── spike_omml.py            # Phase 1 risk spike
│   └── run_pipeline.py          # CLI: file -> markdown + diagrams + docx
├── assets/
│   ├── reference.docx           # generated by tools/build_reference_docx.py
│   └── fonts/                   # NotoSansSinhala-Regular/Bold.ttf, NotoSans-Regular/Bold/Italic.ttf, OFL.txt
├── static/
│   ├── index.html
│   ├── print.html               # print view for browser PDF fallback
│   ├── css/style.css
│   ├── css/preview.css          # A4 paper styling (shared by preview + print)
│   ├── css/print.css
│   ├── fonts/                   # woff2/ttf copies of the Noto fonts for the browser
│   ├── js/app.js  api.js  state.js  viewer.js  editor.js  preview.js
│   │   mcq.js  dialect.js  settings.js  exportdlg.js  toast.js
│   └── vendor/                  # easymde, marked, marked-katex-extension, katex(+fonts), dompurify, VERSIONS.txt
├── tests/
│   ├── fixtures/                # sample .md, sample .docx, synthetic diagram images
│   ├── samples/                 # real pages supplied by the user (gitignored)
│   └── test_*.py
└── workspace/                   # runtime data (gitignored)
    ├── cache/                   # {sha256}.json
    ├── logs/app.log
    ├── exports/
    └── projects/{project_id}/
        ├── project.json
        ├── pages/               # p001_source.png, p001_work.png, p001_thumb.jpg
        └── diagrams/            # p001_d1.png, p001_d1_raw.png
```

> [!NOTE]
> Uploads and diagrams are stored **per project**, which makes deleting a project trivial. This replaces the flat `uploads/` and `diagrams/` folders from `plan.md`.

---

## 4. Configuration (`config.default.json`)

```json
{
  "gemini_api_key": "",
  "gemini_model": "gemini-2.5-pro",
  "gemini_draft_model": "gemini-2.5-flash",
  "thinking_budget": 2048,
  "requests_per_minute": 60,
  "max_concurrent_jobs": 4,
  "pricing_usd_per_million_tokens": {
    "gemini-2.5-pro":   { "input": 1.25, "output": 10.0 },
    "gemini-2.5-flash": { "input": 0.30, "output": 2.50 }
  },
  "monthly_budget_warning_usd": 10,
  "send_max_long_edge_px": 2400,
  "send_jpeg_quality": 90,
  "default_top_crop_percent": 0.0,
  "default_bottom_crop_percent": 6.5,
  "auto_deskew": false,
  "sinhala_font": "Noto Sans Sinhala",
  "sinhala_fallback_font": "Iskoola Pota",
  "latin_font": "Noto Sans",
  "body_font_size_pt": 11,
  "line_spacing": 1.15,
  "embed_fonts_in_docx": true,
  "sinhala_math_mode": "omml",
  "mcq_default_layout": "as_original",
  "diagram_clean_mode": "normalize",
  "pdf_engine_order": ["word", "libreoffice", "browser"],
  "branding_blacklist": ["Samitha Ratnayake", "Innovative Physics"],
  "scrub_phone_numbers": true,
  "scrub_urls_emails": true,
  "server_port": 8000
}
```

- The prices are placeholders. **Verify them** against the current Google pricing page and let the user confirm.
- `sinhala_math_mode`: `"omml"` keeps Sinhala inside the Word equation. `"outside"` moves leading Sinhala `\text{}` out of the equation (fallback, §13).
- `config_manager.py`:
  - Deep-merge the defaults with `config.json` and validate into a `Settings` Pydantic model.
  - Save atomically (write to `.tmp`, then `os.replace`).
  - `GET /api/settings` returns the key masked (`"AIza…abcd"`). `PUT` only replaces the key if a new non-masked value is sent.

---

## 5. Data Model & Coordinate Conventions

### 5.1 Images per page
| File | Meaning |
|---|---|
| `pNNN_source.png` | Raw upload (PDF page rendered at 300 DPI, or the image file). Never modified |
| `pNNN_work.png` | `source` after EXIF rotation (+ deskew if enabled). **All coordinates refer to this image** |
| `pNNN_thumb.jpg` | 240 px wide thumbnail for the page strip |

**Crop is virtual.** It is stored as percentages and applied in memory when sending to Gemini. It never creates a new file.

### 5.2 Coordinate rule (important)
- Gemini returns `box_2d = [ymin, xmin, ymax, xmax]` normalized 0–1000 **relative to the cropped image it was sent**.
- Immediately convert to **pixel coordinates in `work.png`** and store those:
  ```
  crop_top_px  = round(work_h * top_pct / 100)
  cropped_h    = work_h - crop_top_px - round(work_h * bottom_pct / 100)
  y_px = crop_top_px + v / 1000 * cropped_h     (for ymin, ymax)
  x_px = v / 1000 * work_w                       (for xmin, xmax)
  ```
- Changing the crop later therefore **never invalidates diagram boxes**.

### 5.3 `project.json` (Pydantic: `Project`, `Page`, `Diagram`)
```json
{
  "schema_version": 1,
  "id": "p_20261025_133500_ab12",
  "name": "2019 AL Physics Paper I",
  "created_at": "2026-10-25T13:35:00+05:30",
  "updated_at": "2026-10-25T13:40:00+05:30",
  "page_order": [1, 2, 3],
  "pages": {
    "1": {
      "index": 1,
      "source_file": "pages/p001_source.png",
      "work_file": "pages/p001_work.png",
      "thumb_file": "pages/p001_thumb.jpg",
      "width": 2480, "height": 3508,
      "crop": { "top_pct": 0.0, "bottom_pct": 6.5, "override": false },
      "deskew": false,
      "status": "pending",
      "error": null,
      "model_used": "gemini-2.5-pro",
      "cache_key": "…",
      "markdown": "…{{DIAGRAM:d1}}…",
      "user_edited": false,
      "diagrams": [
        {
          "id": "d1",
          "box_px": [410, 120, 1180, 1300],
          "label": "circuit",
          "mode": "normalize",
          "file": "diagrams/p001_d1.png",
          "replaced": false,
          "width_pct": 47
        }
      ],
      "include_in_export": true,
      "page_break_after": true,
      "uncertain_count": 3,
      "tokens": { "input": 1850, "output": 2100, "thinking": 900 },
      "cost_usd": 0.0233
    }
  }
}
```
- `status` is one of `pending | queued | processing | done | error`.
- `box_px` is `[ymin, xmin, ymax, xmax]` in `work.png` pixels.
- `width_pct = round((xmax - xmin) / work_w * 100)`, clamped to the range 15–100.
- Diagram IDs are unique per page. A new manual box gets `d{max+1}`.
- **Re-OCR on a page with `user_edited=true`** must ask the user first (the UI shows a confirm dialog and the API needs `?overwrite=true`).

---

## 6. Gemini Prompt & Schema (verbatim, `core/prompts.py`)

```python
PROMPT_VERSION = "v1"
SCHEMA_VERSION = "v1"
```

### 6.1 System instruction (use exactly)
````text
You are an expert Sri Lankan Physics document digitizer specializing in Sinhala and English typesetting.
Convert the provided physics document page image into clean Markdown with LaTeX math, returned as JSON that matches the given schema.

STRICT RULES

1. VERBATIM SINHALA & ENGLISH ACCURACY
- Transcribe all Sinhala text into accurate Sinhala Unicode.
- DO NOT correct, rephrase, or modernize Sinhala spelling or grammar. Preserve the exact printed characters (e.g., කල vs කළ, ණ vs න, ළ vs ල).
- Keep English terms in parentheses exactly as printed.
- UNCERTAINTY FLAG: if a word or character is blurry, smudged or ambiguous, wrap your best reading as [?word?].
- NEVER put [?...?] inside math. If part of an equation is uncertain, write the equation as best you can and put [?eq?] immediately after the closing $ or $$.

2. REMOVE BRANDING, HEADERS & FOOTERS
- Omit teacher names, tuition institute names, logos, phone numbers, URLs, e-mail addresses, social-media handles, watermarks, running headers/footers and page numbers (e.g., "- 3 -").

3. EQUATIONS
- Inline math: $...$ . Display math: $$...$$ on its own line with a blank line before and after.
- Sinhala words inside math MUST be wrapped in \text{...}, e.g.
  $$\text{භාගික දෝෂය} = \frac{\text{දෝෂය}}{\text{පාඨාංකය}}$$
- Use only LaTeX supported by KaTeX: \frac, \dfrac, \sqrt, ^, _, \pm, \times, \div, \cdot, \theta, \Delta, \pi, \lambda, \mu, \Omega, \alpha, \beta, \omega, \vec, \overline, \hat, \left( \right), \approx, \propto, \rightarrow, \begin{aligned}...\end{aligned}, \begin{cases}...\end{cases}.
- FORBIDDEN: \si, \SI, \cancel, \require, \newcommand, \def, \begin{align}, \begin{equation}, \begin{eqnarray}, \tag, \label.
- Units: write as \text{ m s}^{-1}, \text{ kg}, \Omega, ^{\circ}\text{C}.

4. TEXT FORMATTING
- Printed headings -> "# ", "## ", "### " by visual hierarchy.
- Bold -> **bold**. Underline -> <u>underlined</u>. Do not use italics unless printed in italics.
- Content inside a gray shaded box (e.g., a "වැදගත්" note or a shaded heading) -> every line starts with "> ".
- Keep question numbering exactly as printed at the start of the line (e.g., "01.", "(a)", "(i)", "A.").
- Separate paragraphs with one blank line. Do not hard-wrap lines inside a paragraph.
- Tables -> Markdown pipe tables. A header row is required; if the printed table has no header, use a header row of empty cells ("|  |  |").
- Table cells must contain only inline content (text, $...$, {{DIAGRAM:dN}}). No $$...$$ inside tables.

5. MULTIPLE-CHOICE OPTIONS
- Wrap every option set in marker lines exactly like this:
  <!-- mcq -->
  ...options...
  <!-- /mcq -->
- Copy the printed layout:
  * All 5 options in one row -> a 1-row pipe table with 5 columns.
  * Options in a grid (e.g. 3 + 2, or 2 columns) -> a pipe table with the same number of columns; leave unused cells empty.
  * Options stacked vertically -> one option per line, a blank line between options.
- Each option starts with its printed label, e.g. "(1)", "(2)" ... "(5)".
- The header row of an MCQ table is empty cells.

6. DIAGRAMS, CIRCUITS, GRAPHS, FIGURES
- For each physics diagram, circuit, free-body diagram, ray diagram, graph or figure (NOT decorative logos), add an item to "diagrams":
  * id: "d1", "d2", ... in reading order
  * box_2d: [ymin, xmin, ymax, xmax] normalized 0-1000 relative to THIS image, tightly enclosing the whole figure including its labels and axis numbers
  * label: a short English description (e.g. "circuit with two resistors")
- Insert {{DIAGRAM:d1}} at the figure's position in reading order: on its own line with blank lines around it, or inline inside a table cell / MCQ option if the figure belongs to that option.
- DO NOT transcribe any text that is part of a figure (labels, axis values, component values); it stays in the image.

7. READING ORDER
- For two-column pages, transcribe the left column completely, then the right column.

8. OUTPUT
- Return only the JSON object. "markdown" holds the full page Markdown.
````

### 6.2 Response schema (`core/models.py`)
```python
class GeminiDiagram(BaseModel):
    id: str
    box_2d: list[int]          # [ymin, xmin, ymax, xmax], 0..1000
    label: str

class GeminiPageResult(BaseModel):
    markdown: str
    diagrams: list[GeminiDiagram]
```

### 6.3 Call (async)
```python
client = genai.Client(api_key=settings.gemini_api_key)
resp = await client.aio.models.generate_content(
    model=model_id,
    contents=[types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
              "Digitize this page."],
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0,
        response_mime_type="application/json",
        response_schema=GeminiPageResult,
        thinking_config=types.ThinkingConfig(thinking_budget=settings.thinking_budget),
    ),
)
result = resp.parsed or GeminiPageResult.model_validate_json(repair_json(resp.text))
usage = resp.usage_metadata  # prompt_token_count, candidates_token_count, thoughts_token_count
```
- If the SDK version uses different field names, check the installed SDK and adapt. Keep the same behaviour.
- `thinking_config` is only applied if the model supports it. If not, catch the error and retry once without it.

---

## 7. Markdown Dialect Contract (shared by prompt, editor, preview, exporter)

Every component must accept exactly this dialect. The regexes live in **`core/markdown_dialect.py`** and are mirrored in **`static/js/dialect.js`**. Their test vectors are in `tests/fixtures/dialect_cases.json`.

| Element | Syntax | Preview (browser) | DOCX export |
|---|---|---|---|
| Uncertain word | `[?word?]` regex `\[\?(.+?)\?\]` | yellow `<mark>` | brackets removed (warning count in export dialog) |
| Diagram | `{{DIAGRAM:d1}}` regex `\{\{DIAGRAM:(d\d+)\}\}` | `<img>` | Markdown image with absolute path + `{width=NN%}` |
| Inline / display math | `$…$`, `$$…$$` | KaTeX | Pandoc → OMML |
| Underline | `<u>x</u>` | native `<u>` | converted to `[x]{.underline}` |
| Callout box | lines starting `> ` | grey box (CSS) | `Block Text` style (shaded) |
| MCQ block | `<!-- mcq -->` … `<!-- /mcq -->` | layout chip + table/list | borderless equal-width table (§P3-T04) |
| Page break | `<!-- pagebreak -->` on its own line | dashed line | raw OpenXML page break |
| Question numbering | `01.` / `(a)` / `(i)` / `(1)` at line start | **literal text** | **literal text** |

**Numbering escape rule.** This stops Markdown from turning `01.` / `(1)` into auto-numbered lists that renumber or lose the leading zero. Before rendering (preview) and before Pandoc (export), apply this rule outside math and code:
```
^(\s*)(\d+)\.(\s)                 ->  \1\2\\.\3        # "01. " -> "01\. "
^(\s*)\(([0-9]+|[a-zA-Z]|[ivxIVX]+)\)(\s)  ->  \1\\(\2)\3   # "(a) " -> "\(a) "
```
The user never sees the escapes. They exist only in the render/export pipeline.

**MCQ canonical forms** (what `mcq.js` emits):
````text
<!-- mcq -->
|  |  |  |  |  |
|---|---|---|---|---|
| (1) $2\,\text{m}$ | (2) $4\,\text{m}$ | (3) $6\,\text{m}$ | (4) $8\,\text{m}$ | (5) $10\,\text{m}$ |
<!-- /mcq -->
````
````text
<!-- mcq -->
(1) පළමු පිළිතුර

(2) දෙවන පිළිතුර

(3) …
<!-- /mcq -->
````
Layouts: `as_original`, `row5` (1×5), `grid32` (3 columns), `grid2` (2 columns), `list`.
- Parse rule: split the block into options at each `(N)` label (in table cells or list lines). Each option's content is everything up to the next label, kept as-is.
- The original layout text is stored in `data-original` (in memory per session) so "As original" can restore it exactly.

---

## 8. API Contract

All JSON. Errors return `{"detail": "<message>"}` with a proper HTTP status.

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/` | – | `static/index.html` |
| GET | `/api/projects` | – | `[{id, name, updated_at, page_count}]` |
| POST | `/api/projects` | `{name}` | `Project` |
| GET | `/api/projects/{pid}` | – | `Project` |
| PATCH | `/api/projects/{pid}` | `{name?, page_order?}` | `Project` |
| DELETE | `/api/projects/{pid}` | – | `204` |
| POST | `/api/projects/{pid}/upload` | multipart `files[]` (jpg/png/webp/pdf, ≤ 50 MB each) | `{added_pages:[n…]}` |
| PUT | `/api/projects/{pid}/pages/{n}` | `{markdown?, crop?, deskew?, include_in_export?, page_break_after?}` | `Page` |
| DELETE | `/api/projects/{pid}/pages/{n}` | – | `204` |
| POST | `/api/projects/{pid}/ocr` | `{pages:[n…] or "all", model:"accurate" or "draft", force:false, overwrite:false}` | `{queued:[n…], skipped:[{n, reason}]}` |
| GET | `/api/projects/{pid}/events` | – | **SSE** stream (below) |
| POST | `/api/projects/{pid}/pages/{n}/diagrams` | `{id?, box_px, mode?}` (no id = create) | `Diagram` |
| DELETE | `/api/projects/{pid}/pages/{n}/diagrams/{did}` | – | `204` |
| POST | `/api/projects/{pid}/pages/{n}/diagrams/{did}/replace` | multipart `file` | `Diagram` |
| POST | `/api/projects/{pid}/export/docx` | `{pages:[n…] or "all", merge:true, strip_flags:true}` | `{file, url, warnings:[…]}` |
| POST | `/api/projects/{pid}/export/pdf` | same | `{file, url, engine, warnings}` |
| GET | `/print/{pid}` | `?pages=…` | print HTML |
| GET | `/files/{pid}/{relpath}` | – | file. **Must stay inside `workspace/projects/{pid}`** (check `resolve().is_relative_to()`) |
| GET | `/exports/{filename}` | – | file from `workspace/exports` |
| GET/PUT | `/api/settings` | `Settings` (masked key) | `Settings` |
| POST | `/api/settings/test-key` | – | `{ok, models:[ids that support generateContent]}` |
| GET | `/api/usage` | – | `{project_usd, month_usd}` |

**SSE events** (`event: message`, `data:` JSON):
```json
{"type":"page_status","page":3,"status":"processing"}
{"type":"page_status","page":3,"status":"done","uncertain_count":2,"cost_usd":0.021}
{"type":"page_status","page":4,"status":"error","error":"429 rate limit, retrying in 8s"}
{"type":"rate_wait","seconds":8}
{"type":"queue","pending":5,"running":4}
```

---

## 9. PHASE 1: Backend Core Pipeline + Risk Spikes

**Goal:** prove the pipeline from the CLI and Swagger (`/docs`) before any UI exists. The pipeline is: page → Gemini → clean Markdown + diagrams → Sinhala-correct DOCX.

### P1-T01 Project skeleton & setup scripts
- Create the folder tree from §3, `requirements.txt`, `.gitignore` and `config.default.json` (§4).
- `setup.bat` steps (quote all paths):
  1. `py -3.12 -m venv .venv` (fall back to `py -3.11`).
  2. `.venv\Scripts\python -m pip install -r requirements.txt`.
  3. `python tools\fetch_vendor.py`.
  4. `python tools\install_fonts.py`.
  5. `python -c "import pypandoc; print(pypandoc.get_pandoc_version())"`.
  6. Check Word COM: `python -c "import win32com.client as w; w.Dispatch('Word.Application').Quit()"`. Print OK/WARN.
  7. `python tools\build_reference_docx.py`.
- `run.bat`: `call .venv\Scripts\activate` then `python main.py`.
- **Done when:** a fresh `setup.bat` finishes without errors and `run.bat` serves a placeholder page at `http://127.0.0.1:8000`.

### P1-T02 Fonts (`tools/install_fonts.py`)
- Download **static** TTFs (Regular + Bold) of Noto Sans Sinhala and Noto Sans (Regular, Bold, Italic) from the official notofonts GitHub releases (`github.com/notofonts/sinhala`, `github.com/notofonts/latin-greek-cyrillic`) into `assets/fonts/`. Include `OFL.txt`.
  > [!WARNING]
  > Do **NOT** use the variable font files (`NotoSansSinhala[wdth,wght].ttf`). MS Word handles variable fonts poorly and bold may not work. Only use static instances.
- Install per-user without admin rights:
  1. Copy the files to `%LOCALAPPDATA%\Microsoft\Windows\Fonts\`.
  2. Register under `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts` (`"Noto Sans Sinhala (TrueType)" = <full path>`).
  3. Broadcast `WM_FONTCHANGE`.
- Copy the files to `static/fonts/` as well, for `@font-face`.
- Idempotent: skip fonts that are already installed.
- **Done when:** "Noto Sans Sinhala" appears in Word's font list (🧑 USER CHECK the first time).

### P1-T03 Config manager (`core/config_manager.py`, `core/models.py`)
- Implement as described in §4. `Settings` is a Pydantic model and `get_settings()` is a FastAPI dependency.
- **Done when:** `tests/test_config.py` passes (merge, atomic save, key masking, keeping the old key when the masked value is sent back).

### P1-T04 RISK SPIKE A: Sinhala inside Word equations (`tools/spike_omml.py`)
1. Write `tests/fixtures/spike.md` containing:
   - a Sinhala paragraph
   - **bold Sinhala**
   - an inline equation
   - `$$\text{භාගික දෝෂය} = \frac{\text{දෝෂය}}{\text{පාඨාංකය}}$$`
   - a blockquote
   - a pipe table
   - an underlined word
2. Convert with Pandoc using `assets/reference.docx` (P3-T02 can be built minimally now), then apply `docx_postprocess.fix_sinhala()` (a first version of P3-T05).
3. Save as `workspace/exports/spike_raw.docx`, then run the Word COM font-embed pass and save as `spike_embedded.docx`.
4. 🧑 **USER CHECK:** open both files in Word.
   - Pass = Sinhala in the fraction is shaped correctly (no dotted circles or boxes), bold Sinhala looks bold, and the font is Noto Sans Sinhala.
   - If it fails → set `sinhala_math_mode="outside"` as the default and record it in `README.md`.
- **Done when:** the user confirms the result and the decision is recorded.

### P1-T05 Preprocessor (`core/preprocessor.py`)
- `ingest_upload(project, files) -> list[int]`:
  - Images: Pillow open → `ImageOps.exif_transpose` → RGB → save `source.png`.
  - PDF: `fitz.open(stream=...)`. For each page, `get_pixmap(dpi=300)` → `save()` straight to disk, then free it (`pix = None`). Never hold all pages in memory.
  - Create `work.png` (copy, or deskew if enabled) and `thumb.jpg`.
- `deskew(img) -> img`:
  1. Grayscale → Otsu inverse threshold.
  2. `cv2.minAreaRect` on the ink pixel coordinates.
  3. Rotate only if |angle| is between 0.3° and 10°, using a white border fill.
- `cropped(work_img, top_pct, bottom_pct) -> Image` (in memory).
- `encode_for_gemini(img) -> bytes`: resize so the long edge ≤ `send_max_long_edge_px` (LANCZOS), save as JPEG at `send_jpeg_quality`.
- **Done when:** `tests/test_preprocessor.py` passes. It must include a 3-page PDF fixture where the peak RSS increase is < 200 MB.

### P1-T06 Gemini OCR (`core/gemini_ocr.py`)
- `async def ocr_page(jpeg: bytes, model_id: str, force: bool) -> OcrResult`, where `OcrResult = {markdown, diagrams_norm, usage, cache_key, model_used}`.
- Cache key: `sha256(jpeg_bytes + PROMPT_VERSION + SCHEMA_VERSION + model_id)`. Read/write `workspace/cache/{key}.json`, skipped if `force`.
- Retry on `google.genai.errors.APIError` with `code` in {429, 500, 503} and on network timeouts:
  - Delays: 4, 8, 16, 32 s, each with ±20% jitter, max 4 retries.
  - Emit a `rate_wait` event through a callback.
- `repair_json(text)`:
  - Strip code fences.
  - Double any single backslash that is not followed by a valid JSON escape character (`["\\/bfnrtu]`).
  - Fix this specific case: `\t` or `\f` followed by letters is usually LaTeX (`\theta`, `\frac`), so escape it to `\\t` / `\\f` when the next characters spell a known LaTeX command.
- Validate the boxes: clamp to 0–1000, require ymin<ymax and xmin<xmax, and drop invalid ones (log them).
- Ensure every `{{DIAGRAM:dN}}` in the Markdown has a matching box and vice versa. Orphan tags stay in the text and get `missing=true`.
- Cost = (input × in_price + (output + thinking) × out_price) / 1e6, using the config pricing.
- **Done when:** `tests/test_gemini_ocr.py` passes with a **mocked** client (cache hit, retry path, repair_json cases, box validation), plus one real call in `tools/run_pipeline.py`.

### P1-T07 RISK SPIKE B: Accuracy & cost
- `tools/run_pipeline.py <file> --model accurate|draft` writes `out/<name>/page_N.md`, the diagram PNGs, `page_N.docx` and `cost.txt`.
- Run it on 5 user-supplied hard pages with both models.
- 🧑 **USER CHECK:** the user compares the Sinhala accuracy. Confirm the default model and record the cost per page.
- **Done when:** the user confirms.

### P1-T08 Scrubber (`core/scrubber.py`)
- `scrub(markdown, settings) -> (markdown, removed:list[str])`.
- Blacklist entry → regex: escape it, replace spaces with `\s+`, case-insensitive.
- Phone patterns:
  - `(?:\+94|0)\s?7\d[\s-]?\d{3}[\s-]?\d{4}`
  - `(?:\+94|0)\s?\d{2}[\s-]?\d{3}[\s-]?\d{4}`
- URL/email: standard patterns.
- Page markers: `^\s*-\s*\d+\s*-\s*$`.
- **Never touch text inside `$…$` / `$$…$$`.** Tokenize math out first, then put it back.
- Collapse 3+ blank lines into 2.
- **Done when:** `tests/test_scrubber.py` passes, including a case where a number inside math is not removed.

### P1-T09 Diagram extractor (`core/diagram_extractor.py`)
- `extract(work_img, box_px, mode) -> (clean_png_path, raw_png_path, final_box_px)`:
  1. **Pad** by 1% of the page width on each side and clamp to the image.
  2. **Snap to content:**
     - Binarize (Otsu).
     - While any border row/column of the box has more than 0.5% ink pixels, grow that side by 8 px, up to +5% of the page per side.
     - Then trim fully white outer rows and columns, keeping a 6 px margin.
  3. **Clean:**
     - `normalize` (default): gray → `bg = GaussianBlur(gray, (0,0), sigma=25)` → `norm = gray / bg * 255` → stretch the 2nd–98th percentiles to 0–255 → `fastNlMeansDenoising(h=7)` → values > 235 become 255.
     - `binary`: adaptive Gaussian threshold (block 31, C 10).
     - `original`: crop only.
  4. Save both `raw` and `clean` PNGs (DPI metadata 300).
- `process_page(project, page)` converts the normalized boxes to `box_px` (§5.2), extracts each one and fills `Diagram` entries.
- **Done when:** `tests/test_diagram_extractor.py` passes. It uses synthetic images: a clipped box grows to include the full shape, and a grey background becomes white.

### P1-T10 Job queue (`core/job_queue.py`)
- One `JobQueue` in `app.state`:
  - `asyncio.Queue`.
  - `max_concurrent_jobs` worker tasks.
  - An async token bucket (`requests_per_minute`).
  - Per-project subscriber lists for SSE.
- Pipeline per job:
  1. Set status `processing` (emit event).
  2. Crop + encode.
  3. `ocr_page`.
  4. Scrub.
  5. Diagrams.
  6. Count flags.
  7. Save the project under a per-project `asyncio.Lock`.
  8. Set status `done` (emit event).
- Exceptions → `status=error` with the message.
- CPU-heavy work (OpenCV, PIL) runs in `asyncio.to_thread`.
- **Done when:** the integration test passes. It uses a mocked OCR, 10 pages and 4 workers: all pages are processed, events arrive in order per page and `project.json` is valid.

### P1-T11 Project store + API (Phase 1 subset) + `main.py`
- `project_store.py`:
  - `create`, `load`, `save` (atomic), `delete`, `list`.
  - An `asyncio.Lock` per project.
- Routes: projects CRUD, upload, OCR enqueue, SSE events, files (with the path guard), settings.
- `main.py`:
  - Find a free port starting at `server_port`.
  - In the lifespan hook, start the job queue and schedule `webbrowser.open(url)` 1 s after start.
  - Mount `static/`.
  - Configure rotating logging (`workspace/logs/app.log`, 5 × 2 MB).
  - Bind to `127.0.0.1` only.
- **Done when:** in Swagger, you can create a project, upload a PDF, run OCR on all pages, and GET the project with Markdown + diagrams.

### P1-T12 Minimal export
- First versions of `markdown_normalizer.py`, `docx_exporter.py` and `docx_postprocess.py` (full versions in Phase 3), enough for `run_pipeline.py` to produce a DOCX.

### ✅ Phase 1 exit criteria → STOP and report to user
- [ ] Spikes A and B have been confirmed by the user (or the fallback decision is recorded).
- [ ] `python tools\run_pipeline.py tests\samples\x.pdf` produces Markdown, diagrams and a DOCX.
- [ ] A second run makes 0 API calls (cache hit).
- [ ] 20 pages with 4 workers finish in < 3 min with no unhandled 429 errors. Python peak RAM is < 600 MB.
- [ ] All `pytest` tests pass.

---

## 10. PHASE 2: Split-Screen Review Editor

**Goal:** the teacher reviews, fixes and organizes the pages entirely in the browser, and nothing is ever lost.

### Visual design
- Dark UI:
  - background `#0f1220`, panels `#171a2b`, borders `#262a40`
  - accent `#7c9cff`, success `#3ecf8e`, warning `#f5b84b`, error `#ff6b6b`
- Fonts: Inter for the UI and Noto Sans Sinhala for Sinhala.
- Animations: subtle hover/press transitions (150 ms), skeleton shimmer while pages are processing.
- The preview is a white A4 "paper" with a soft shadow, using the **same fonts and sizes as the DOCX** (`preview.css` is shared with the print view).

### Layout (`index.html`)
```
┌───────────────────────────────────────────────────────────────────────────────┐
│ [≡ Projects] Project name ✎ | [⬆ Upload] [▶ Run all ▾ Pro/Flash] ◀ 3/20 ▶       │
│ [⚠ 4 flags ▸] [⚙] [Export Word] [Export PDF]          ● Saved   $0.42 this proj  │
├──────────────┬─────────────────────────────┬──────────────────────────────────┤
│ PAGE STRIP   │ SOURCE VIEWER                │ EDITOR │ PREVIEW  (split / tabs)   │
│ thumbnails   │ work.png + crop lines        │ EasyMDE       A4 paper (KaTeX)     │
│ status dots  │ diagram boxes (drag/resize)  │                                    │
│ ☑ export     │ zoom/pan                     │ MCQ chips: [Layout: As original ▾] │
│ drag reorder │ [Re-run OCR] [Deskew ☐]      │                                    │
└──────────────┴─────────────────────────────┴──────────────────────────────────┘
```
- The three columns are resizable with drag handles, and their sizes persist in `localStorage`.
- All interactive elements get unique IDs (e.g. `btn-upload`, `btn-run-all`, `btn-export-docx`, `page-strip`, `viewer-canvas`, `editor`, `preview`).

### P2-T01 App shell, state & API client
- `state.js`: a small pub/sub store holding `{project, currentPage, settings, queue}`.
- `api.js`: fetch wrappers plus an `EventSource` for SSE (auto-reconnect).
- `toast.js`: toast notifications.
- **Done when:** the projects menu lists, creates, opens and deletes projects, and the selected project is remembered in `localStorage`.

### P2-T02 Upload & page strip
- Drag-and-drop anywhere, or the Upload button. Shows a progress bar.
- Each thumbnail shows:
  - a status dot (grey pending, blue pulsing processing, green done, red error)
  - a ⚠ badge with the flag count
  - an export checkbox
- Drag to reorder (HTML5 DnD) → `PATCH page_order`. The right-click menu has: re-run OCR (Pro/Flash), delete page, toggle "page break after".
- **Done when:** a 20-page PDF upload shows 20 thumbnails, and reordering persists after a reload.

### P2-T03 Source viewer (`viewer.js`)
- Uses a `<canvas>` for the image plus an absolutely positioned SVG overlay. Wheel zooms, space+drag or middle-drag pans, and "Fit" resets the view.
- **Crop lines:** two horizontal draggable lines with % labels. The cropped area is drawn with a 50% dark veil.
  - Scope toggle: "This page" / "All pages without override".
  - Saved via `PUT` after the user stops dragging (debounced).
- **Diagram boxes:** rectangles with an ID label and 8 resize handles.
  - Drag to move, handles to resize. Releasing sends `POST …/diagrams` with the new `box_px`, and the server recrops (P2-T07).
  - "✚ Box" tool: draw a new box. This creates the diagram and inserts `{{DIAGRAM:dN}}` at the editor cursor.
  - Delete key / 🗑: removes the box and its tag. If the tag is already gone, confirm first.
  - Clicking a box scrolls the editor to its tag and highlights it.
- **Done when:** resizing a box updates the preview image within about 1 s.

### P2-T04 Editor (`editor.js`)
- EasyMDE with the toolbar: bold, underline (wraps `<u>`), heading, quote, table, `$`, `$$`, `\frac{}{}` template, `\text{}` wrap, insert diagram, page break, undo/redo.
- Turn off EasyMDE's own preview and spell-checker (Sinhala gives false errors).
- CodeMirror overlays (`cm.addOverlay`) for `[?…?]` (yellow background), `{{DIAGRAM:…}}` (chip colour), math (tinted) and MCQ markers (dimmed).
- **Flag navigator:**
  - `F8` jumps to the next flag (across pages) and `Shift+F8` to the previous one. The match is selected.
  - `Ctrl+Enter` with the cursor inside a flag accepts it (removes `[?` `?]`).
  - The top-bar button shows the total count.
- Autosave: 1.5 s after typing stops, `PUT markdown` (also sets `user_edited=true`). The status shows "Saving… / ● Saved / ⚠ Offline (retrying)".
- Undo history per page: keep a separate CodeMirror doc per page (`CodeMirror.Doc`) so history survives page switching.
- **Done when:** typing Sinhala with a Wijesekara or phonetic IME works, flags are highlighted, and edits survive a reload.

### P2-T05 Live preview (`preview.js`, `dialect.js`)
Pipeline on every edit (throttled to 150 ms):
1. Protect math segments.
2. Apply the numbering escape (§7).
3. Convert `<!-- pagebreak -->` to `<hr class="pb">`.
4. Turn MCQ markers into wrapper divs.
5. Convert `[?x?]` to `<mark class="flag">x</mark>`.
6. Replace `{{DIAGRAM:id}}` with `<img src="/files/{pid}/{file}?v={mtime}" style="width:NN%">`.
7. Restore math.
8. `marked.parse` with `marked-katex-extension` (`throwOnError:false`, `strict:"ignore"`, `output:"html"`).
9. Sanitize with `DOMPurify` (allow `mark`, `u`, KaTeX classes and `style` on `img`).

Then:
- CSS: `.katex .text, .katex .mord.text { font-family: 'Noto Sans Sinhala', 'Noto Sans', sans-serif; }` and hide empty `thead` rows in MCQ tables.
- **Equation validator:** collect `.katex-error` elements, outline them in red and show "✖ N equation errors" in the status bar. Clicking it jumps to the source line.
- Approximate scroll sync from the editor to the preview (by heading/paragraph index).
- **Done when:** the Sinhala fraction example renders correctly, and a broken `\frac{` shows a red error without breaking the rest of the page.

### P2-T06 MCQ Layout Switcher (`mcq.js`)
- Find the `<!-- mcq -->` blocks in the editor text and render a floating chip `Layout: <current> ▾` next to each block in the **preview**, plus a gutter marker in the editor.
- Options: As original / 1×5 row / 3-column grid / 2-column grid / Vertical list.
- `parseOptions(blockText) -> [{label, content}]` and `emit(options, layout) -> blockText`, following the canonical forms in §7.
  - Options whose content contains `$$` or more than 120 characters can only use `list` (the other choices are greyed out and show a tooltip).
- Remember the block's original text (in memory, keyed by page and block index) for "As original".
- "Apply to all MCQs on this page / in the project" buttons. The default for new OCR results comes from `mcq_default_layout` (`as_original` = keep the Gemini output).
- **Done when:** `tests/js/mcq_cases.json` round-trips all layouts with no change to the options. Verify manually in the browser and with a small `node`-free test page `static/tests/mcq_test.html`.

### P2-T07 Diagram API & image tools
- Implement the diagram endpoints from §8. A recrop runs `diagram_extractor.extract` in a thread and returns the updated `Diagram` with a new `mtime`.
- The preview right-click menu on an image offers: mode (Clean / Binary / Original), Replace image… (upload), Width (25/50/75/100% or custom). Width writes `width_pct`.
- **Done when:** replacing an image and changing its mode both reflect in the preview.

### P2-T08 Batch & job UX
- "Run all ▾" button: Accurate (Pro) / Draft (Flash). It skips pages that are `done` unless the user confirms.
- If any page has `user_edited`, show a confirmation listing those pages before overwriting them.
- SSE updates the dots and a queue pill: "Processing 4 · 12 waiting · ETA ~2 min". `rate_wait` shows a countdown toast.
- Pages can be edited while others are still processing.
- **Done when:** running 20 pages gives live updates, and errors show a Retry action.

### P2-T09 Settings modal & cost panel (`settings.js`)
- Sections:
  - **API:** key (masked), Test key button. The model dropdowns are filled from `test-key` → `models`.
  - **OCR:** RPM, workers, thinking budget, auto-deskew.
  - **Crop defaults.**
  - **Fonts & layout:** Sinhala/Latin font, size, line spacing, embed fonts.
  - **Math:** `sinhala_math_mode`.
  - **MCQ default layout.**
  - **Diagrams:** clean mode.
  - **PDF engine order.**
  - **Branding:** blacklist chips (add/remove), phone/URL scrub toggles.
  - **Usage:** project spend, month spend, budget warning, pricing table (editable).
  - **Maintenance:** cache size, Clear cache button.
- **Done when:** all settings persist to `config.json` and take effect without a restart (re-read on each use).

### ✅ Phase 2 exit criteria → STOP and report to user
- [ ] A full 10-page review is possible without touching the terminal.
- [ ] Crops, boxes, Markdown, MCQ layouts and page order survive a browser restart.
- [ ] Every flag can be reached by keyboard. KaTeX errors are visible.
- [ ] The UI never freezes while OCR runs.
- [ ] 🧑 USER CHECK: the teacher tries the UI on a real paper and gives feedback.

---

## 11. PHASE 3: High-Fidelity Export, Merge, Polish & Hardening

**Goal:** the DOCX/PDF looks professionally typeset, and installation is one click.

### P3-T01 Markdown normalizer (`core/markdown_normalizer.py`)
`normalize(pages, project, settings, strip_flags) -> (pandoc_md, warnings)`, applied in this order:
1. For each included page in `page_order`, take its Markdown.
2. Protect math segments.
3. If `strip_flags`, `[?x?]` → `x` and count them in warnings.
4. `<u>x</u>` → `[x]{.underline}`.
5. Numbering escape (§7).
6. `{{DIAGRAM:id}}` → a Markdown image using the absolute POSIX path of the diagram's `file` (or the raw file if mode is `original`), followed by `{width=NN%}`. Missing diagram → remove the tag and add a warning.
7. MCQ blocks: replace `<!-- mcq -->` with a raw OpenXML marker paragraph before the table:
   ````text
   ```{=openxml}
   <w:p><w:pPr><w:pStyle w:val="MCQMarker"/></w:pPr></w:p>
   ```
   ````
   and delete `<!-- /mcq -->`. List-layout MCQs simply lose the markers.
8. `<!-- pagebreak -->`, plus the join between pages when `page_break_after`, becomes:
   ````text
   ```{=openxml}
   <w:p><w:r><w:br w:type="page"/></w:r></w:p>
   ```
   ````
9. If `sinhala_math_mode == "outside"`: for display math that starts with `\text{<Sinhala>} =`, move the Sinhala text out as a normal paragraph prefix.
10. Restore math. Make sure display math has blank lines around it.
- **Done when:** `tests/test_normalizer.py` passes, using vectors from `dialect_cases.json`.

### P3-T02 Reference DOCX generator (`tools/build_reference_docx.py`)
An agent cannot design the template by hand in Word, so it is **generated programmatically**:
1. `pandoc -o assets/reference.docx --print-default-data-file reference.docx`. Use `pypandoc.get_pandoc_path()` and `subprocess.run([...])`.
2. Open it with python-docx and edit the styles through XML (python-docx `font.name` only sets ascii/hAnsi):
   - **docDefaults `rPrDefault`** and the **Normal** style:
     - `w:rFonts ascii=hAnsi=eastAsia=<latin_font> cs=<sinhala_font>`
     - `w:sz` = `w:szCs` = size × 2
     - `w:lang w:val="en-GB" w:bidi="si-LK"`
     - line spacing `w:spacing w:line=276 w:lineRule="auto"` (1.15)
   - **Body Text, First Paragraph, Compact** (the styles Pandoc uses for paragraphs) are `basedOn Normal`. Remove any font overrides they have.
   - **Heading 1/2/3**: Latin + CS fonts, `w:b` + `w:bCs`, sizes 16/13/12 pt, dark-blue colour `1F3864`, spacing before 12/10/8 pt.
   - **Block Text**: `w:shd w:fill="F2F2F2"`, left border 3 pt `A6A6A6`, left/right indent 0.25", spacing 6 pt, no italics.
   - **Table** (table style): single 0.5 pt borders `BFBFBF`, cell margins 0.08".
   - **MCQ Table** (new table style): no borders, `tblW` 100% pct.
   - **MCQMarker** (new paragraph style): hidden, 1 pt.
   - Section: A4 (11906 × 16838 twips), margins 2 cm (1134 twips).
3. Re-run the script automatically whenever the font/size/spacing settings change (the exporter compares a hash of those settings stored in `assets/reference.hash`).
- **Done when:** the generated `reference.docx` opens in Word, and its styles show Noto Sans Sinhala as the "Complex script" font.

### P3-T03 DOCX exporter (`core/docx_exporter.py`)
```python
pypandoc.convert_text(
    pandoc_md, to="docx",
    format="markdown+tex_math_dollars+raw_attribute+bracketed_spans+pipe_tables-fancy_lists",
    outputfile=str(out_path),
    extra_args=[f"--reference-doc={ref_docx}"],
)
```
- Then `docx_postprocess.run(out_path, settings)`. If `embed_fonts_in_docx`, run `word_com.embed_fonts(out_path)`.
- File name: `{project_name}_{YYYYMMDD_HHMM}.docx` with unsafe characters removed (keep Sinhala characters).
- **Done when:** exporting the spike Markdown and a 3-page project produces valid DOCX files.

### P3-T04 MCQ tables in DOCX (inside `docx_postprocess.py`)
For each paragraph with `pStyle=MCQMarker`:
1. Take the next sibling `w:tbl`.
2. Set its `w:tblStyle` to `MCQTable`, `tblW` to 5000 pct, and equal `w:gridCol` widths.
3. Delete its header row if all cells are empty.
4. Delete the marker paragraph.
- **Done when:** the test asserts there are no marker paragraphs left and that MCQ tables have the right style and no header row.

### P3-T05 Sinhala post-processor (`core/docx_postprocess.py`)
Process `word/document.xml` (and the headers/footers/footnotes parts if present) with lxml through python-docx `part.element`.
- Sinhala test: `re.compile("[\u0D80-\u0DFF]")`.
- **Every `w:r`** (normal text):
  - Make sure `w:rPr` is its first child.
  - Set `w:rFonts`: `ascii`/`hAnsi`/`eastAsia` = Latin font (only if not already set), `cs` = Sinhala font. Word picks the cs font for Sinhala characters automatically, so mixed runs need **no splitting**.
  - If `w:b` exists, add `w:bCs`. If `w:i` exists, add `w:iCs`. If `w:sz` exists, add `w:szCs` with the same value.
  - If the run has Sinhala, add or update `w:lang w:bidi="si-LK"`.
- **Every `m:r`** (math) **containing Sinhala**:
  - Child order must be `m:rPr` → `w:rPr` → `m:t`. Create missing elements in that order.
  - `m:rPr` must contain `<m:nor/>` (normal text, not math italic) and `<m:sty m:val="p"/>`.
  - `w:rPr` gets `w:rFonts w:ascii=w:hAnsi=w:cs=<sinhala_font>` and `w:lang w:bidi="si-LK"`.
  - Math runs **without** Sinhala are left untouched (they keep Cambria Math).
- Respect the `w:rPr` child order defined by the OOXML schema: `rStyle, rFonts, b, bCs, i, iCs, …, sz, szCs, …, lang`. Use a helper `insert_in_order(rPr, element)` with that order list.
- Save, then validate by reopening with python-docx.
- **Done when:** `tests/test_docx_postprocess.py` passes on a fixture DOCX with `w:cs` on Sinhala runs, `bCs` present and correct `m:r` child order. Also, 🧑 USER CHECK: Word opens the file without a repair prompt.

### P3-T06 Word COM (`core/word_com.py`)
- A single dedicated worker thread with a `queue.Queue` of jobs (Word COM is single-threaded). The thread calls `pythoncom.CoInitialize()` once.
- `embed_fonts(path)`:
  1. `word = DispatchEx("Word.Application")`, `Visible=False`, `DisplayAlerts=0`.
  2. `doc = word.Documents.Open(abs, ReadOnly=False, AddToRecentFiles=False)`.
  3. `doc.EmbedTrueTypeFonts = True`, `doc.SaveSubsetFonts = False`, `doc.DoNotEmbedSystemFonts = True`.
  4. `doc.Save()`.
- `to_pdf(docx, pdf)`: `doc.ExportAsFixedFormat(OutputFileName=pdf, ExportFormat=17, OptimizeFor=0, CreateBookmarks=1)`.
- Always `doc.Close(False)` and `word.Quit()` in `finally`.
- Timeout of 90 s per job. If it times out, kill only the `WINWORD.EXE` process this module started (record its PID via `win32process.GetWindowThreadProcessId` on `word.ActiveWindow.Hwnd`, or compare the process list before/after starting Word).
- If `pywin32` is missing or Word can't be reached, raise `WordUnavailable`. The callers fall back.
- **Done when:** both functions work on the spike file, and running export twice in a row leaves no orphaned `WINWORD.EXE`.

### P3-T07 PDF exporter (`core/pdf_exporter.py`)
Try the engines in `pdf_engine_order`:
1. **word:** export the DOCX (P3-T03), then `word_com.to_pdf`.
2. **libreoffice:** find `soffice.exe` in `C:\Program Files\LibreOffice\program\` or on PATH. Run `[soffice, "--headless", "--convert-to", "pdf", "--outdir", out, docx]` with a 120 s timeout.
3. **browser:** return `{engine:"browser", url:"/print/{pid}?pages=…"}`. The UI opens it in a new tab and calls `window.print()` automatically.
   - `print.html` reuses the `preview.js` pipeline plus `print.css`:
     - `@page { size: A4; margin: 20mm; }`
     - `hr.pb { break-after: page; border: 0; }`
     - `.katex-display, img, table { break-inside: avoid; }`
     - Hide the flag `mark` background.
- **Done when:** the PDF is produced by Word on the user's machine, and the browser fallback prints correct A4 pages.

### P3-T08 Export dialog (`exportdlg.js`)
- Options:
  - Pages: all / selected (export checkboxes) / current.
  - Merge into a single file (default on).
  - Strip remaining `[?]` flags (shows the count, e.g. "⚠ 3 unresolved flags").
  - Format: Word / PDF.
- Shows a progress spinner. When finished: "Open file", "Open folder" (`os.startfile` via a small endpoint `POST /api/open` that only allows paths inside `workspace/exports`), the engine used and any warnings.
- **Done when:** both formats export from the UI.

### P3-T09 Hardening & quality
- Security:
  - Bind to localhost only.
  - Uploads: check type by magic bytes (`%PDF`, PNG/JPEG/WEBP signatures) and enforce the 50 MB size limit.
  - Path guards on every file endpoint.
  - The API key is never logged (add a logging filter).
  - `config.json` is gitignored.
- Housekeeping:
  - Deleting a project removes its folder.
  - Cache limit of 500 MB with LRU deletion by atime/mtime at startup.
- Error handling: a global exception handler returns JSON and logs the traceback. The UI shows a toast with a short message and "See log".
- `README.md`: setup, run, troubleshooting (fonts, Word COM, API key, Pandoc), and the spike decisions.
- **Done when:** all tests pass and the README is complete.

### P3-T10 Nice-to-haves (only if the user asks)
- Automatic header/footer crop suggestion: OpenCV horizontal rule detection in the top/bottom 15% of the page.
- An "Erase region" tool: white-out rectangles before OCR (for logos inside the page body).
- Perspective correction for phone photos (4-corner detection + `warpPerspective`).
- PyInstaller one-folder build + desktop shortcut.

### ✅ Phase 3 exit criteria → final report
- [ ] The DOCX opens without a repair prompt. Sinhala, bold Sinhala and Sinhala inside fractions render in Noto Sans Sinhala.
- [ ] The DOCX renders correctly on a PC **without** the Noto fonts installed (embedded fonts).
- [ ] Callouts are grey shaded boxes. Diagrams have proportional widths. MCQ tables are borderless with no header.
- [ ] A merged 20-page export takes < 20 s for DOCX and < 40 s for PDF via Word.
- [ ] On a fresh machine, `setup.bat` → `run.bat` works end to end.

---

## 12. Testing Strategy

| Level | What | Where |
|---|---|---|
| Unit | config, scrubber, dialect regexes, normalizer, repair_json, box conversion, post-processor XML | `tests/test_*.py` |
| Integration | job queue with mocked Gemini, API via `httpx.AsyncClient` + `ASGITransport` | `tests/test_api.py` |
| Golden | 5–10 real pages → exported DOCX checked by eye in Word | 🧑 user, each phase |
| Frontend | dialect/MCQ vectors in `static/tests/*.html` (open in a browser, results shown in green/red) | manual |

**Never call the real Gemini API in `pytest`.** Real calls only happen in `tools/run_pipeline.py` and the app.

---

## 13. Risks & Fallbacks

| Risk | Detection | Fallback |
|---|---|---|
| Word doesn't shape Sinhala inside OMML | Spike A | `sinhala_math_mode="outside"`. Last resort: render that equation to PNG with KaTeX (via the browser print view) |
| Gemini boxes are badly wrong | Phase 2 review | Manual box tools (P2-T03) |
| Gemini returns invalid JSON | `repair_json` fails | Retry once with the same request. Then mark the page as error with a "Retry" action |
| Model IDs change or are retired | `test-key` model list | Dropdown in Settings. Config defaults are only defaults |
| Word COM hangs | 90 s timeout | Kill the app-started Word process, then try the next PDF engine |
| Variable font breaks bold in Word | P1-T02 | Use only static TTFs |

---

## Appendix A: Why This Spec Differs From `plan.md`

| `plan.md` approach | Problem | This spec |
|---|---|---|
| Diagram boxes embedded in Markdown text | Fragile parsing, boxes can't be edited | Structured JSON output: `diagrams[]` + `{{DIAGRAM:dN}}` tags |
| Gemini boxes used as-is | Boxes are approximate and clip labels | Snap-to-content + manual box editor |
| Boxes relative to the cropped image | Changing the crop breaks them | Stored in `work.png` pixel coordinates (§5.2) |
| `<u>` passed to Pandoc | Pandoc drops raw HTML in DOCX | `[x]{.underline}` |
| Only `w:rFonts` injected | Bold Sinhala needs `w:bCs`, size needs `w:szCs` | Full CS property mirroring + `w:lang bidi` |
| Per-run XML everywhere | Brittle, and styles are ignored | Generated `reference.docx` + targeted post-processing |
| OMML font fix unspecified | Wrong child order → "corrupt file" | Exact `m:rPr → w:rPr → m:t` order + `m:nor` |
| Naive Marked + KaTeX | Marked mangles math | `marked-katex-extension` + math protection |
| Markdown numbered lists | `01.` / `(1)` get renumbered | Numbering escape rule (§7) |
| LibreOffice as main PDF engine | Weak with OMML + Sinhala | MS Word COM first |
| CDN scripts | Breaks offline, versions drift | Vendored + `VERSIONS.txt` |
| Hand-built reference.docx | An AI agent can't do it | `tools/build_reference_docx.py` |
| Cache key = image + prompt | Stale results across models | + model + schema version |
| No queue or persistence | 429 errors, lost work | Async queue, token bucket, `project.json` autosave |
