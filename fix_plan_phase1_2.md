# Fix Plan: Phase 1 & Phase 2 Broken Items

Project root: `d:\Sinhala & English Physics Paper Digitizer\`
Source of truth: `SPEC.md`. **Do NOT start Phase 3.**

> [!IMPORTANT]
> **Rules for the implementing model**
> 1. Do the fixes **in the order below** (F1 → F13). Later fixes assume earlier ones are done.
> 2. After each fix, run its **Done when** check. Do not mark a fix done without running it.
> 3. Run `.venv\Scripts\pytest -q` after every backend fix. All tests must stay green.
> 4. **Never report a check as passed unless you saw its output.** If a tool returns "still running" or no result, say so.
> 5. Restart the server after backend changes: stop the old `python main.py`, then run `.venv\Scripts\python main.py`.
> 6. For browser checks, hard-reload (Ctrl+Shift+R) so cached JS is not used.
> 7. Do not click "Clear cache" and do not delete projects in the UI while testing.

---

## Summary table

| # | Problem | Severity | Files |
|---|---|---|---|
| F1 | Editor crash: `Cannot read properties of undefined (reading 'Doc')` → editor & preview blank | 🔴 Blocker | `static/js/editor.js` |
| F2 | Editor shows stale/wrong text (cache not per project, no refresh when OCR finishes) | 🔴 Blocker | `static/js/editor.js`, `static/js/app.js` |
| F3 | Test `test_usage_and_cache_api` deletes the **real** OCR cache | 🔴 Data loss | `tests/test_api.py`, `api/routes_settings.py` |
| F4 | `WinError 5 Access is denied` when saving `project.json`; lost updates between autosave and worker | 🔴 Blocker | `core/project_store.py`, all `api/routes_*.py`, `core/job_queue.py` |
| F5 | Pages stuck in `queued` forever after restart/error; "Run all" skips them | 🟠 High | `main.py`, `core/job_queue.py`, `api/routes_ocr.py` |
| F6 | Queue pill never shows (no `queue` SSE events); no Retry for error pages | 🟠 High | `core/job_queue.py`, `static/js/app.js`, `static/css/style.css` |
| F7 | Preview reloads every image on every keystroke (`?v=Date.now()`) | 🟠 High | `core/models.py`, `api/routes_diagrams.py`, `core/job_queue.py`, `static/js/preview.js` |
| F8 | CSS loads Google Fonts from internet (spec forbids CDN at runtime) | 🟠 High | `static/css/style.css`, `static/css/preview.css`, `tools/fetch_vendor.py` |
| F9 | Editor keybindings: `setOption('extraKeys')` wipes EasyMDE shortcuts; F8 fires twice | 🟡 Medium | `static/js/editor.js` |
| F10 | "Run all" menu labels hard-coded to `gemini-2.5-pro/flash`; `/api/usage` month logic wrong & slow | 🟡 Medium | `static/index.html`, `static/js/app.js`, `api/routes_settings.py` |
| F11 | Missing spec features (MCQ "apply to project", scroll sync, shimmer, ETA, gutter marker) | 🟡 Medium | `static/js/*.js`, CSS |
| F12 | Phase 1 records missing: `README.md` with Spike A/B decisions | 🟡 Medium | `README.md` (new) |
| F13 | Final end-to-end acceptance run (Phase 1 + Phase 2 exit criteria) | ✅ Verify | – |

---

## F1 — Editor crash (`CodeMirror.Doc` undefined)

**Cause.** `static/js/editor.js` → `loadPageContent()` calls `new window.CodeMirror.Doc(...)`. The vendored `easymde.min.js` bundles CodeMirror **internally** and does **not** expose `window.CodeMirror`. So the function throws, the doc is never swapped, and the editor + preview stay empty.

**Fix.** Get the `Doc` constructor from the live editor instance instead of the global.

In `static/js/editor.js`:

1. In `init()`, right after `this.cm = this.easyMDE.codemirror;`, add:
   ```js
   // EasyMDE bundles CodeMirror privately; window.CodeMirror is undefined.
   // Get the Doc constructor from the running instance instead.
   this.DocCtor = (this.cm.constructor && this.cm.constructor.Doc)
       ? this.cm.constructor.Doc
       : this.cm.getDoc().constructor;
   this.docMode = this.cm.getOption('mode');   // reuse EasyMDE's mode (gfm/markdown)
   ```
2. In `loadPageContent()`, replace
   ```js
   doc = new window.CodeMirror.Doc(markdownText || '', 'markdown');
   ```
   with
   ```js
   doc = new this.DocCtor(markdownText || '', this.docMode);
   ```
3. Search the whole `static/` folder for any other `window.CodeMirror` usage and replace it the same way:
   `grep -r "window.CodeMirror" static/js` → must return nothing afterwards.

**Done when**
- Hard-reload `http://127.0.0.1:8000/`. Browser console has **no** `TypeError ... 'Doc'`.
- Type `Hello [?test?] $\frac{a}{b}$` in the editor → text appears, `[?test?]` is yellow, preview shows "Hello", a yellow mark and a rendered fraction.

---

## F2 — Editor/page sync bugs

**Causes.**
- `pageDocs` is a `Map` keyed only by `pageIndex`. Switching projects reuses page 1's doc from the previous project.
- When OCR finishes for the **current** page, `app.js` calls `store.setProject(...)` which only fires the `project` event. The `currentPage` listener (which loads the editor) does not run, so the new Markdown never appears.
- `loadPageContent` refuses to overwrite when `user_edited` is true, even on a fresh server load.

**Fix.**

In `static/js/editor.js`:

1. Key docs by project + page:
   ```js
   _docKey(pageIndex) {
       const pid = store.state.project ? store.state.project.id : 'none';
       return `${pid}:${pageIndex}`;
   }
   ```
   Use `this._docKey(pageIndex)` everywhere `this.pageDocs.get/set(pageIndex)` is used.
2. Add a reset method and a `force` flag:
   ```js
   resetDocs() { this.pageDocs.clear(); }

   loadPageContent(pageIndex, markdownText, { force = false } = {}) {
       this._isSwitchingDoc = true;
       const key = this._docKey(pageIndex);
       let doc = this.pageDocs.get(key);
       const text = markdownText || '';
       if (!doc) {
           doc = new this.DocCtor(text, this.docMode);
           this.pageDocs.set(key, doc);
       } else if (force && doc.getValue() !== text) {
           doc.setValue(text);            // server version wins (e.g. OCR just finished)
       }
       this.cm.swapDoc(doc);
       this._isSwitchingDoc = false;
       if (this._onChangeCallback) this._onChangeCallback(this.getValue());
   }
   ```
3. In the `change` handler, also skip when `_isSwitchingDoc` is true (already present) **and** when the change origin is `'setValue'` from a forced load: wrap `doc.setValue(text)` in the `_isSwitchingDoc = true` block (as above) so it does not trigger autosave or set `user_edited`.

In `static/js/app.js`:

4. In `openProject(pid)`, call `documentEditor.resetDocs()` **before** `store.setProject(proj)`.
5. In `_connectProjectSSE`, when `event.status === 'done'` for the current page, replace the reload with:
   ```js
   api.getProject(pid).then(updated => {
       store.setProject(updated);
       const page = updated.pages[String(event.page)];
       if (page && event.page === store.state.currentPageIndex) {
           documentEditor.loadPageContent(page.index, page.markdown || '', { force: true });
           previewRenderer.render(page.markdown || '', page, true);
           sourceViewer.render();          // new diagram boxes
       }
   });
   ```
   For `done` events on **other** pages, just update the thumbnail/status (do not touch the editor).
6. After `store.setProject(proj)` in `openProject`, explicitly load the current page (the `currentPage` event may not fire if the index did not change):
   ```js
   const page = store.getCurrentPage();
   if (page) {
       documentEditor.loadPageContent(page.index, page.markdown || '', { force: true });
       previewRenderer.render(page.markdown || '', page, true);
       sourceViewer.loadCurrentPage();
   }
   ```

**Done when**
- Open project A page 1, type text, wait for "● Saved". Open project B → editor shows B's page 1, not A's text. Go back to A → your text is there.
- Run OCR on the current page (or simulate by `PUT /api/projects/{pid}/pages/{n}` with new markdown in Swagger, then reload) → editor shows new text.
- Reload browser → edits survive.

---

## F3 — Test wipes the real OCR cache (data loss)

**Cause.** `tests/test_api.py::test_usage_and_cache_api` calls `POST /api/cache/clear`, which deletes every file in the **real** `workspace/cache`. Also `routes_settings.py` uses `Path("workspace/cache")` (relative to the current folder) instead of the shared constant.

**Fix.**

1. In `api/routes_settings.py`, use the shared constant, read at call time so tests can patch it:
   ```python
   import core.gemini_ocr as gemini_ocr

   @router.get("/cache/stats")
   async def get_cache_stats():
       cache_dir = gemini_ocr.CACHE_DIR
       ...
   @router.post("/cache/clear")
   async def clear_cache():
       cache_dir = gemini_ocr.CACHE_DIR
       ...
   ```
   Remove the `Path("workspace/cache")` lines.
2. In `tests/test_api.py`, isolate the cache:
   ```python
   def test_usage_and_cache_api(tmp_path, monkeypatch):
       import core.gemini_ocr as gemini_ocr
       fake_cache = tmp_path / "cache"
       fake_cache.mkdir()
       (fake_cache / "dummy.json").write_text("{}", encoding="utf-8")
       monkeypatch.setattr(gemini_ocr, "CACHE_DIR", fake_cache)

       r = client.get("/api/cache/stats");  assert r.json()["count"] == 1
       r = client.post("/api/cache/clear"); assert r.json()["cleared_files"] == 1
       assert not any(fake_cache.iterdir())
       # usage part unchanged
   ```
3. Check every other test for writes into the real `workspace/` (`grep -rn "workspace" tests/`). `test_project_crud_and_upload` creates and deletes a real project — acceptable, but it must delete it at the end even if an assert fails: wrap in `try/finally` with `client.delete(...)`.
4. Add a safety check to `clear_cache`: only delete `*.json` files whose name is a 64-char hex string (`re.fullmatch(r"[0-9a-f]{64}\.json", f.name)`).

> [!WARNING]
> The cache that was already deleted cannot be recovered. Re-running OCR on those pages will cost API tokens again. Tell the user this.

**Done when**
- Put a file `workspace/cache/keepme_test.json` there, run `pytest -q`, file still exists. (Then delete it manually.)
- All tests pass.

---

## F4 — `WinError 5 Access is denied` + lost updates on `project.json`

**Causes.**
1. On Windows, `os.replace(tmp, project.json)` fails if any other handle (another request reading the file, antivirus, Windows Search indexer) has `project.json` open at that instant.
2. Route handlers do **load → modify → save without holding the project lock**. The autosave (`PUT pages/{n}`), the job worker, and diagram routes can each load an old copy and overwrite each other's changes (lost update). Only the worker uses the lock.

**Fix.**

### 4a. Robust atomic write — `core/project_store.py`
Replace the body of `save_project_sync` with a retrying write:
```python
import time, uuid

def save_project_sync(self, project: Project) -> None:
    pdir = self.get_project_dir(project.id)
    pdir.mkdir(parents=True, exist_ok=True)
    pfile = pdir / "project.json"
    tmp_file = pdir / f"project.json.{uuid.uuid4().hex[:8]}.tmp"   # unique tmp per write
    project.updated_at = datetime.now().isoformat()
    data = project.model_dump()
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    last_err = None
    for attempt in range(10):                     # ~2.75 s worst case
        try:
            os.replace(tmp_file, pfile)
            return
        except PermissionError as e:              # WinError 5 / 32
            last_err = e
            time.sleep(0.05 * (attempt + 1))
    try:
        tmp_file.unlink(missing_ok=True)
    finally:
        raise RuntimeError(f"Failed to save project {project.id}: {last_err}") from last_err
```
Also make `load_project` retry the same way on `PermissionError` (5 tries, 50 ms) and on `json.JSONDecodeError` (file mid-replace).

On startup (`ProjectStore.__init__` or lifespan), delete leftover `project.json.*.tmp` files.

### 4b. One locked read-modify-write helper — `core/project_store.py`
Add:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def edit(self, project_id: str):
    """Load, yield for modification, then save — all under the project lock."""
    lock = self.get_lock(project_id)
    async with lock:
        proj = await asyncio.to_thread(self.load_project, project_id)
        yield proj
        await asyncio.to_thread(self.save_project_sync, proj)
```
Keep `save_project()` for compatibility but do **not** call `save_project` inside an `edit()` block (deadlock: `asyncio.Lock` is not re-entrant).

### 4c. Use `store.edit()` everywhere a project is modified
Convert each of these to `async with store.edit(pid) as proj:` (raise `HTTPException(404)` on `FileNotFoundError` **outside** the block):

| File | Functions |
|---|---|
| `api/routes_projects.py` | `update_project_metadata`, `upload_files_to_project` (do the slow `ingest_file` **before** entering the lock, then add pages inside), `update_page_content`, `delete_page` |
| `api/routes_diagrams.py` | `save_or_recrop_diagram`, `patch_diagram`, `delete_diagram`, `replace_diagram` (run `extract_diagram` in `asyncio.to_thread` **before** taking the lock; only the dict update + save happen inside) |
| `core/job_queue.py` | `enqueue` (status → queued), the "processing" update, the final "done" update, the error update in `_worker_loop` |

Important in `update_page_content`: when the worker writes `done` results, it must not be overwritten by a late autosave of old text, and vice-versa. With the lock both are serialized; additionally, in the worker's final save, **if `p.user_edited` became True while OCR was running** (user typed during processing), keep the user's markdown and put the OCR result in a new field `p.ocr_markdown_pending` instead, and broadcast `{"type":"page_conflict","page":n}`. (Add `ocr_markdown_pending: Optional[str] = None` to `Page` in `core/models.py`.) The UI may show a toast "New OCR result available for page n — Replace?" (simple `confirm()` is fine).

Also: `routes_ocr.trigger_ocr` with `overwrite=true` must reset `user_edited=False` when queuing.

### 4d. Stress test — new file `tests/test_project_store_concurrency.py`
```python
import asyncio, pytest
from core.project_store import ProjectStore
from core.models import Page

@pytest.mark.asyncio
async def test_concurrent_edits_no_lost_updates(tmp_path):
    store = ProjectStore(base_dir=tmp_path)
    proj = store.create_project("c")
    for i in range(1, 21):
        proj.pages[str(i)] = Page(index=i, source_file="s", work_file="w", thumb_file="t")
    store.save_project_sync(proj)

    async def bump(i):
        async with store.edit(proj.id) as p:
            p.pages[str(i)].markdown = f"page {i}"
    await asyncio.gather(*(bump(i) for i in range(1, 21)))

    final = store.load_project(proj.id)
    assert all(final.pages[str(i)].markdown == f"page {i}" for i in range(1, 21))
```

**Done when**
- New test passes, all tests pass.
- In the UI: start OCR on 4+ pages and keep typing in the editor of another page during processing → no `WinError 5` in `workspace/logs/app.log`, no page ends in `error` with "Failed to save project", and your typed text is still there after reload.

---

## F5 — Pages stuck in `queued`

**Cause.** `queued`/`processing` status is saved to disk, but the in-memory `asyncio.Queue` is lost on restart (or the job dies). `trigger_ocr` then skips those pages forever ("Currently in state queued").

**Fix.**

1. `core/job_queue.py` — track live jobs in memory:
   ```python
   self.active: set[tuple[str, int]] = set()   # in __init__
   def is_active(self, pid: str, page: int) -> bool:
       return (pid, page) in self.active
   ```
   - In `enqueue`: if `(pid, page)` already in `active` → return `False` (do not double-queue). Otherwise add it, then queue the job, return `True`.
   - In `_worker_loop` `finally:` → `self.active.discard((pid, page_idx))`.
2. `api/routes_ocr.py` — replace the status check:
   ```python
   if queue.is_active(pid, p_idx):
       skipped.append({"page": p_idx, "reason": "Already queued or processing."})
       continue
   ```
   (Delete the old `page.status in ("queued","processing")` check.)
3. `main.py` lifespan, **before** `queue.start(...)`: reset stale statuses in every project:
   ```python
   store = get_project_store()
   for info in store.list_projects():
       try:
           async with store.edit(info["id"]) as p:
               for pg in p.pages.values():
                   if pg.status in ("queued", "processing"):
                       pg.status = "pending"
                       pg.error = "Interrupted (server restarted)"
       except Exception as e:
           logger.warning(f"Could not reset statuses for {info['id']}: {e}")
   ```
4. Fix the response key: `skipped` items use `"page"` but SPEC §8 says `{n, reason}`. Use `{"n": p_idx, "reason": ...}` and update `app.js` if it reads it.

**Done when**
- Manually set a page to `"status": "queued"` in a `project.json`, restart server → it is `pending`.
- "Run all" now queues it.
- Clicking "Run all" twice quickly does not process any page twice (check log: one "Calling Gemini API" per page).

---

## F6 — Queue pill + Retry action

**Cause.** The backend never broadcasts `{"type":"queue",...}` events, so the pill never shows. Error pages have no Retry button (SPEC P2-T08).

**Fix.**

1. `core/job_queue.py` — add counters and a helper:
   ```python
   self.running_count: dict[str, int] = {}     # pid -> running jobs
   async def _emit_queue(self, pid: str):
       pending = sum(1 for (p, _) in self.active if p == pid) - self.running_count.get(pid, 0)
       await self.broadcast(pid, {"type": "queue",
                                  "pending": max(0, pending),
                                  "running": self.running_count.get(pid, 0)})
   ```
   Call `_emit_queue(pid)` after enqueue, when a job starts (increment `running_count`), and when it ends (decrement, in `finally`).
2. On SSE connect (`routes_ocr.stream_project_events`), send the current queue state right after the `connected` event.
3. `static/js/app.js` queue pill: show ETA. Keep a rolling average of job durations (from `processing` → `done` timestamps per page, default 25 s):
   ```js
   const eta = Math.ceil(((q.pending + q.running) * avgSec) / Math.max(1, workers) / 60);
   pill.textContent = `Processing ${q.running} · ${q.pending} waiting · ETA ~${eta} min`;
   ```
   `workers` = `store.state.settings.max_concurrent_jobs`.
4. Retry action:
   - Page strip: for `status === 'error'`, render a small `↻` button on the card (`class="strip-retry-btn"`, `title` = the error text). Click → `api.triggerOcr(pid, {pages:[n], model:'accurate', force:true, overwrite:true})`.
   - On the SSE `page_status` `error` event → `toast.error(\`Page ${n} failed: ${short error}\`)` with a "Retry" button inside the toast. Extend `toast.show()` to accept an optional `{actionLabel, onAction}`.
   - Also add "Retry failed pages" item to the "Run all ▾" menu → queues all pages with `status === 'error'`.
5. Show the error text in the source-viewer toolbar area when the current page is in `error` (one line, red, ellipsis, full text in `title`).

**Done when**
- Queue 5 pages → pill shows "Processing 4 · 1 waiting · ETA ~N min" and disappears when done.
- A page that failed (e.g. temporarily set a wrong API key) shows ↻; after fixing the key, ↻ re-runs it successfully.

---

## F7 — Preview reloads all images on every keystroke

**Cause.** `preview.js` builds `src=".../file.png?v=${Date.now()}"` on every render (every 150 ms while typing) → every diagram re-downloads and flickers. SPEC says use `?v={mtime}`.

**Fix.**
1. `core/models.py` → `Diagram`: add `version: int = 0`.
2. Wherever a diagram image file is (re)written — `routes_diagrams.save_or_recrop_diagram`, `patch_diagram` (when re-extracted), `replace_diagram`, and `job_queue._process_job` — set `diag.version = int(time.time() * 1000)`.
3. `static/js/preview.js`: `const imgSrc = \`/files/${pid}/${diag.file}?v=${diag.version || 0}\`;`
4. After a recrop/replace/patch, the JS must copy the returned `Diagram` (including the new `version`) into `page.diagrams` before re-rendering (`viewer.js _recropBox` already does `Object.assign(diag, updated)` — verify; do the same in `preview.js _handleDiagramMenuAction` for mode/width/replace using the API response instead of only setting one field).
5. Listen for the `diagram-recropped` window event in `app.js` and call `previewRenderer.render(documentEditor.getValue(), store.getCurrentPage(), true)` (currently nothing listens to it).
6. Same issue for thumbnails in `app.js _renderPageStrip` (`?v=${Date.now()}`): use a fixed value, e.g. `?v=${project.updated_at ? '' : ''}` — simplest: no query string at all (thumbnails never change).

**Done when**
- DevTools → Network: typing in the editor produces **no** new image requests.
- Resizing a box in the viewer updates the preview image within ~1 s (SPEC P2-T03 done criterion).

---

## F8 — Remove internet font loading

**Cause.** `style.css` and `preview.css` start with `@import url('https://fonts.googleapis.com/...')`. SPEC §2: the app never loads a CDN at runtime.

**Fix.**
1. Delete both `@import url('https://fonts.googleapis.com/...')` lines.
2. Add local `@font-face` rules at the top of `static/css/preview.css` (shared by app + print view). The TTFs already exist in `static/fonts/`:
   ```css
   @font-face { font-family: 'Noto Sans Sinhala'; src: url('/static/fonts/NotoSansSinhala-Regular.ttf') format('truetype'); font-weight: 400; font-display: swap; }
   @font-face { font-family: 'Noto Sans Sinhala'; src: url('/static/fonts/NotoSansSinhala-Bold.ttf') format('truetype'); font-weight: 700; font-display: swap; }
   @font-face { font-family: 'Noto Sans'; src: url('/static/fonts/NotoSans-Regular.ttf') format('truetype'); font-weight: 400; font-display: swap; }
   @font-face { font-family: 'Noto Sans'; src: url('/static/fonts/NotoSans-Bold.ttf') format('truetype'); font-weight: 700; font-display: swap; }
   @font-face { font-family: 'Noto Sans'; src: url('/static/fonts/NotoSans-Italic.ttf') format('truetype'); font-style: italic; font-display: swap; }
   ```
3. Inter (UI font): add it to `tools/fetch_vendor.py` from `@fontsource/inter` on jsDelivr. **First verify the version and file names exist** (open `https://data.jsdelivr.com/v1/packages/npm/@fontsource/inter` to get the latest version, then check `https://cdn.jsdelivr.net/npm/@fontsource/inter@<ver>/files/` for `inter-latin-400-normal.woff2`, `-500-`, `-600-`, `-700-`). Save to `static/fonts/` and add `@font-face` rules for `'Inter'` in `style.css`. Record the version in `static/vendor/VERSIONS.txt`.
   If downloading fails, fall back to `--font-ui: 'Segoe UI', system-ui, sans-serif;` and note it.
4. Grep: `grep -rn "googleapis\|cdn.jsdelivr\|unpkg" static/` → must return nothing (except comments in `fetch_vendor.py`, which is under `tools/`, not `static/`).

**Done when**
- With Wi-Fi/network **off**, reload the app: Sinhala text in the editor preview renders in Noto Sans Sinhala (DevTools → Elements → Computed → "Rendered Fonts" shows `Noto Sans Sinhala`), and the Network tab shows no external requests.

---

## F9 — Keybinding conflicts

**Causes.**
- `this.cm.setOption('extraKeys', {...})` **replaces** EasyMDE's own extraKeys (Ctrl-B bold, Ctrl-I, etc.).
- F8 is bound in CodeMirror **and** on `window` → when the editor is focused, F8 jumps two flags.
- SPEC: F8 must jump to the next flag **across pages**; current code only searches the current page.

**Fix (`static/js/editor.js`).**
1. Merge instead of replace:
   ```js
   const existing = this.cm.getOption('extraKeys') || {};
   this.cm.setOption('extraKeys', Object.assign({}, existing, {
       'F8': () => this.jumpToNextFlag(true),
       'Shift-F8': () => this.jumpToNextFlag(false),
       'Ctrl-Enter': () => this.acceptCurrentFlag(),
       'Cmd-Enter': () => this.acceptCurrentFlag(),
   }));
   ```
2. Global listener: ignore when the event comes from inside CodeMirror:
   ```js
   window.addEventListener('keydown', (e) => {
       if (e.key !== 'F8') return;
       if (e.target.closest && e.target.closest('.CodeMirror')) return;
       e.preventDefault();
       this.jumpToNextFlag(!e.shiftKey);
   });
   ```
3. Cross-page jump: in `jumpToNextFlag`, if no match after (or before) the cursor on this page, look through `project.page_order` for the next (or previous) page whose `markdown` contains `[?`. Switch to it with `store.setCurrentPage(n)`, then after the doc loads, select its first (or last) flag. Wrap around at the ends. Only show "No uncertain flags" when the **whole project** has none.
4. Top-bar flags button: show the **project total** (sum of each page's flag count; for the current page use the live editor text). SPEC P2-T04 says "total count".
5. Equation error status: add a top-bar/status item `✖ N equation errors` bound to the `equationErrors` store event (currently the count is stored but never shown). Click → `documentEditor.locateMathError(...)` for the first `.katex-error` in the preview.

**Done when**
- Ctrl+B in the editor makes text bold.
- With 3 flags on page 1 and 2 on page 3, pressing F8 five times visits all 5 in order and wraps to the first. Shift+F8 goes backwards.
- `Ctrl+Enter` inside `[?word?]` leaves `word`.
- Typing `$\frac{$` shows "✖ 1 equation errors" and the rest of the preview still renders.

---

## F10 — Hard-coded model labels; usage endpoint

1. `static/index.html`: replace the fixed text `gemini-2.5-pro (higher accuracy)` / `gemini-2.5-flash (...)` with empty spans `id="run-all-accurate-model"` and `id="run-all-draft-model"`. In `app.js`, on the `settings` store event, fill them with `settings.gemini_model` and `settings.gemini_draft_model`. Do the same in the page-strip context menu ("Re-run OCR (Accurate …)").
2. `api/routes_settings.py` `get_usage`:
   - Load each project **once** (currently it loads all projects twice when `project_id` is missing).
   - `project_usd` = cost of the requested project only (0 if none requested — do not sum everything).
   - Month spend should not use the project's `created_at`. Add `ocr_at: Optional[str] = None` to `Page` (set in the worker when status becomes `done`) and sum `cost_usd` of pages whose `ocr_at` starts with the current `YYYY-MM`.
   - Move the imports to the top of the file.
3. Budget warning: in `app.js`, after refreshing usage, if `month_usd >= settings.monthly_budget_warning_usd`, show a warning toast once per session.

**Done when**
- Changing the model in Settings changes the labels in "Run all ▾" without reloading.
- `/api/usage?project_id=X` returns only X's cost.

---

## F11 — Missing Phase 2 spec features

Implement after F1–F10 work. Each is small.

| Spec ref | Feature | Where / how |
|---|---|---|
| P2-T06 | "Apply to all MCQs **in the project**" | `preview.js` MCQ menu: add item. For each page in `page_order`, apply `parseOptions`/`emit` to every `<!-- mcq -->` block whose options pass `canUseGridLayout` (else use `list`), then `api.updatePage(pid, n, {markdown})`. Ask `confirm()` first. Update the open editor doc via `loadPageContent(..., {force:true})`. |
| P2-T06 | Editor gutter marker for MCQ blocks | `editor.js`: on change (debounced), clear and re-add `cm.addLineClass(line, 'background', 'cm-mcq-line')` for lines inside mcq blocks; style lightly in CSS. |
| P2-T06 | `mcq_default_layout` for new OCR results | `core/job_queue.py` after scrub: if `settings.mcq_default_layout != "as_original"`, convert MCQ blocks. Needs a Python port of `parseOptions`/`emit` in `core/markdown_dialect.py` + unit tests `tests/test_mcq.py` using `tests/fixtures/mcq_cases.json`. |
| P2-T06 | Test file location | SPEC names `tests/js/mcq_cases.json`. Move `tests/fixtures/mcq_cases.json` → `tests/js/mcq_cases.json` and update the fetch path in `static/tests/mcq_test.html`. |
| P2-T05 | Scroll sync editor → preview | `editor.js`: on `cm` `scroll`, find the top visible line, count block index (headings/blank-line-separated paragraphs) up to that line, scroll the preview so the same-index block element (`#preview-paper > *`) is at the top. Throttle 100 ms. |
| Visual | Skeleton shimmer for processing pages | CSS `@keyframes shimmer` gradient on `.strip-card.processing .strip-thumb-wrap` and on the preview paper when the current page is `processing` (show 6 grey bars instead of content). |
| P2-T03 | Space+drag pan | `viewer.js`: `e.spaceKey` does not exist. Track `this.spaceDown` via `keydown/keyup` for `' '` (ignore when typing in inputs/CodeMirror) and use it in `_onMouseDown`. |
| P2-T03 | Delete box when tag is already gone → confirm; otherwise no confirm | `viewer.js _deleteActiveBox`: check if `{{DIAGRAM:id}}` exists in `documentEditor.getValue()`; only `confirm()` when it does **not**. |
| P2-T03 | Crop scope "All pages" should also update `settings.default_*_crop_percent` | `viewer.js _debounceSaveCrop` (scope `all`): also `api.updateSettings({default_top_crop_percent, default_bottom_crop_percent})`. |
| Layout | Editor/preview splitter is not draggable | `app.js`: make `#editor-preview-splitter` resize `#editor-subpane` width (persist to `localStorage` like the others) and show it in split mode (`display:block`). |

**Done when** each row's behaviour is visible in the browser, and `static/tests/mcq_test.html` still shows all tests passed.

---

## F12 — Phase 1 records (`README.md`)

Create `README.md` at the project root with:
1. **Install & run**: `setup.bat`, `run.bat`, URL.
2. **Spike A result** (Sinhala inside Word equations): ask the user to open `workspace/exports/spike_raw.docx` and `spike_embedded.docx` in Word and confirm: Sinhala inside the fraction is shaped correctly (no dotted circles/boxes), bold Sinhala is bold, font is Noto Sans Sinhala. Record **PASS → `sinhala_math_mode = "omml"`** or **FAIL → set default `"outside"` in `config.default.json` and `core/models.py`**.
3. **Spike B result**: which model the user chose as default and the cost per page (from `out/*/cost.txt`).
4. **Model IDs actually used** (from `config.json` / Settings) and the note that prices are unverified placeholders until the user confirms them against Google's pricing page.
5. **Known limitations**.

> [!NOTE]
> Fill in the Spike A/B answers **only from the user's reply**. Do not invent results.

Also align defaults: `core/models.py` defaults (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `thinking_budget=0`) differ from `config.default.json`/SPEC (`gemini-2.5-pro`, `gemini-2.5-flash`, `2048`). Ask the user which are correct, then make `config.default.json` and `Settings` defaults identical.

---

## F13 — Final acceptance run (do this last, report honestly)

Restart the server, hard-reload the browser, then check each item and write the actual result next to it.

### Phase 1 exit criteria
- [ ] `pytest -q` → all pass (paste the summary line).
- [ ] `python tools\run_pipeline.py tests\samples\<file>.pdf` → produces `.md`, diagrams and `.docx` in `out/`.
- [ ] Run the same command again → log shows "Cache hit" for every page and **0** "Calling Gemini API" lines.
- [ ] 20 pages, 4 workers: total time < 3 min, no unhandled 429; peak RAM of the Python process < 600 MB (measure with `Get-Process python | Select-Object WS` polling every 2 s, or `psutil` in a small script). Record numbers.
- [ ] Spike A and B decisions recorded in `README.md` (from the user).

### Phase 2 exit criteria
- [ ] Browser console: **zero** errors on load and while using the app.
- [ ] Full 10-page review done only in the browser: upload → Run all → edit text → fix flags with F8/Ctrl+Enter → adjust crop → move/resize/add/delete a diagram box → change an MCQ layout → reorder pages → toggle export checkbox.
- [ ] Close the browser completely, reopen `http://127.0.0.1:8000` → same project opens; crops, boxes, Markdown, MCQ layouts and page order are all preserved.
- [ ] Every flag reachable with F8/Shift+F8 across pages; KaTeX errors visible with count.
- [ ] While OCR runs on several pages, typing in the editor stays smooth (no freeze), no `WinError 5` in `workspace/logs/app.log`.
- [ ] Network tab: no requests to external domains.
- [ ] 🧑 USER CHECK: the teacher tries it on a real paper and gives feedback.

Report format for the user:
```
Phase 1: PASS / FAIL — list each criterion with result
Phase 2: PASS / FAIL — list each criterion with result
Open issues: ...
```
Then **STOP**. Do not start Phase 3 until the user asks.
