/**
 * Editor Component:
 * EasyMDE with custom toolbar, CodeMirror overlay highlights (flags, diagrams, math, MCQ),
 * per-page undo history (CodeMirror.Doc), flag navigator (F8, Shift+F8, Ctrl+Enter to accept),
 * and debounced autosave.
 */

import { store } from './state.js';
import { api } from './api.js';
import { toast } from './toast.js';
import { countUncertainFlags } from './dialect.js';

class DocumentEditor {
    constructor() {
        this.easyMDE = null;
        this.cm = null;
        this.textarea = null;
        this.pageDocs = new Map(); // pageIndex -> CodeMirror.Doc
        this.autosaveTimer = null;
        this._isSwitchingDoc = false;
        this._onChangeCallback = null;
    }

    init(textareaEl, onChangeCallback = null) {
        this.textarea = textareaEl;
        this._onChangeCallback = onChangeCallback;

        // Initialize EasyMDE with custom toolbar
        this.easyMDE = new window.EasyMDE({
            element: this.textarea,
            autoDownloadFontAwesome: false,
            spellChecker: false,
            nativeSpellcheck: false,
            autofocus: false,
            indentWithTabs: false,
            tabSize: 4,
            status: false,
            toolbar: [
                {
                    name: 'bold',
                    action: window.EasyMDE.toggleBold,
                    className: 'fa fa-bold',
                    title: 'Bold (**bold**)'
                },
                {
                    name: 'underline',
                    action: (editor) => this._wrapSelection(editor, '<u>', '</u>'),
                    className: 'fa fa-underline',
                    title: 'Underline (<u>underlined</u>)'
                },
                {
                    name: 'heading',
                    action: window.EasyMDE.toggleHeadingSmaller,
                    className: 'fa fa-header',
                    title: 'Heading (# / ## / ###)'
                },
                '|',
                {
                    name: 'quote',
                    action: window.EasyMDE.toggleBlockquote,
                    className: 'fa fa-quote-left',
                    title: 'Callout / Shaded box (> )'
                },
                {
                    name: 'table',
                    action: window.EasyMDE.drawTable,
                    className: 'fa fa-table',
                    title: 'Insert Pipe Table'
                },
                '|',
                {
                    name: 'math-inline',
                    action: (editor) => this._wrapSelection(editor, '$', '$'),
                    className: 'fa fa-dollar-sign',
                    title: 'Inline Math ($...$)'
                },
                {
                    name: 'math-display',
                    action: (editor) => this._insertDisplayMath(editor),
                    className: 'fa fa-calculator',
                    title: 'Display Math ($$...$$)'
                },
                {
                    name: 'frac',
                    action: (editor) => this._insertFrac(editor),
                    className: 'fa fa-divide',
                    title: 'Fraction (\\frac{num}{den})'
                },
                {
                    name: 'text-wrap',
                    action: (editor) => this._wrapSelection(editor, '\\text{', '}'),
                    className: 'fa fa-font',
                    title: 'Wrap Sinhala in \\text{...}'
                },
                '|',
                {
                    name: 'insert-diagram',
                    action: (editor) => this._promptInsertDiagram(editor),
                    className: 'fa fa-image',
                    title: 'Insert Diagram tag ({{DIAGRAM:d1}})'
                },
                {
                    name: 'pagebreak',
                    action: (editor) => this._insertPageBreak(editor),
                    className: 'fa fa-file-text-o',
                    title: 'Insert Page Break'
                },
                '|',
                {
                    name: 'undo',
                    action: window.EasyMDE.undo,
                    className: 'fa fa-undo',
                    title: 'Undo (Ctrl+Z)'
                },
                {
                    name: 'redo',
                    action: window.EasyMDE.redo,
                    className: 'fa fa-repeat',
                    title: 'Redo (Ctrl+Y)'
                }
            ]
        });

        this.cm = this.easyMDE.codemirror;

        // EasyMDE bundles CodeMirror privately; window.CodeMirror is undefined.
        // Get the Doc constructor from the running instance instead.
        this.DocCtor = (this.cm.constructor && this.cm.constructor.Doc)
            ? this.cm.constructor.Doc
            : this.cm.getDoc().constructor;
        this.docMode = this.cm.getOption('mode');   // reuse EasyMDE's mode (gfm/markdown)

        // Register custom CodeMirror syntax overlays
        this._setupOverlays();

        // Register keyboard shortcuts
        this._setupKeybindings();

        // Listen for content changes
        this.cm.on('change', () => {
            if (this._isSwitchingDoc) return;
            const text = this.getValue();
            const page = store.getCurrentPage();
            if (page) {
                page.markdown = text;
                page.user_edited = true;
                page.uncertain_count = countUncertainFlags(text);
            }
            if (this._onChangeCallback) {
                this._onChangeCallback(text);
            }
            this._debounceAutosave();
        });

        // Jump to math error event
        window.addEventListener('jump-to-math-error', (e) => {
            this.locateMathError(e.detail.text);
        });
    }

    _setupOverlays() {
        const overlay = {
            token: (stream) => {
                // 1. Uncertain flag: [?...?]
                if (stream.match(/^\[\?.*?\?\]/)) {
                    return 'flag-uncertain';
                }
                // 2. Diagram tag: {{DIAGRAM:d1}}
                if (stream.match(/^\{\{DIAGRAM:d\d+\}\}/)) {
                    return 'diagram-tag';
                }
                // 3. MCQ markers: <!-- mcq --> or <!-- /mcq -->
                if (stream.match(/^<!--\s*\/?mcq\s*-->/i)) {
                    return 'mcq-marker';
                }
                // 4. LaTeX display math: $$...$$
                if (stream.match(/^\$\$.*?\$\$/)) {
                    return 'math-token';
                }
                // 5. LaTeX inline math: $...$
                if (stream.match(/^\$[^\$\n]+?\$/)) {
                    return 'math-token';
                }

                stream.next();
                return null;
            }
        };

        this.cm.addOverlay(overlay);
        this._setupMcqLineHighlighter();
        this._setupScrollSync();
    }

    _setupMcqLineHighlighter() {
        let timer = null;
        const updateMcqLines = () => {
            if (!this.cm) return;
            const doc = this.cm.getDoc();
            const lineCount = doc.lineCount();
            let insideMcq = false;
            for (let i = 0; i < lineCount; i++) {
                const text = doc.getLine(i);
                if (/<!--\s*mcq\s*-->/i.test(text)) {
                    insideMcq = true;
                    this.cm.addLineClass(i, 'background', 'cm-mcq-line');
                    continue;
                }
                if (/<!--\s*\/mcq\s*-->/i.test(text)) {
                    this.cm.addLineClass(i, 'background', 'cm-mcq-line');
                    insideMcq = false;
                    continue;
                }
                if (insideMcq) {
                    this.cm.addLineClass(i, 'background', 'cm-mcq-line');
                } else {
                    this.cm.removeLineClass(i, 'background', 'cm-mcq-line');
                }
            }
        };
        this.cm.on('change', () => {
            if (timer) clearTimeout(timer);
            timer = setTimeout(updateMcqLines, 200);
        });
        setTimeout(updateMcqLines, 300);
    }

    _setupScrollSync() {
        let scrollTimer = null;
        this.cm.on('scroll', () => {
            if (scrollTimer) return;
            scrollTimer = setTimeout(() => {
                scrollTimer = null;
                const scrollInfo = this.cm.getScrollInfo();
                const topLine = this.cm.lineAtHeight(scrollInfo.top, 'local');
                let blockIdx = 0;
                let prevBlank = true;
                for (let i = 0; i <= topLine; i++) {
                    const lineText = this.cm.getLine(i).trim();
                    if (lineText.length > 0 && prevBlank) {
                        blockIdx++;
                    }
                    prevBlank = (lineText.length === 0);
                }

                const previewPaper = document.getElementById('preview-paper');
                if (!previewPaper) return;
                const blockElements = previewPaper.children;
                const targetIdx = Math.max(0, Math.min(blockElements.length - 1, blockIdx - 1));
                if (blockElements[targetIdx]) {
                    const container = document.getElementById('preview-container');
                    if (container) {
                        const targetOffset = blockElements[targetIdx].offsetTop;
                        container.scrollTo({ top: targetOffset - 40, behavior: 'smooth' });
                    }
                }
            }, 100);
        });
    }

    _setupKeybindings() {
        const existing = this.cm.getOption('extraKeys') || {};
        this.cm.setOption('extraKeys', Object.assign({}, existing, {
            'F8': () => this.jumpToNextFlag(true),
            'Shift-F8': () => this.jumpToNextFlag(false),
            'Ctrl-Enter': () => this.acceptCurrentFlag(),
            'Cmd-Enter': () => this.acceptCurrentFlag()
        }));

        // Global fallback if editor doesn't have focus
        window.addEventListener('keydown', (e) => {
            if (e.key !== 'F8') return;
            if (e.target && e.target.closest && e.target.closest('.CodeMirror')) return;
            e.preventDefault();
            this.jumpToNextFlag(!e.shiftKey);
        });
    }

    _wrapSelection(editor, before, after) {
        const cm = editor.codemirror;
        const selection = cm.getSelection();
        cm.replaceSelection(`${before}${selection}${after}`);
        cm.focus();
    }

    _insertDisplayMath(editor) {
        const cm = editor.codemirror;
        const selection = cm.getSelection() || 'E = mc^2';
        cm.replaceSelection(`\n\n$$\n${selection}\n$$\n\n`);
        cm.focus();
    }

    _insertFrac(editor) {
        const cm = editor.codemirror;
        const selection = cm.getSelection() || '';
        cm.replaceSelection(`\\frac{${selection}}{}`);
        cm.focus();
    }

    _promptInsertDiagram(editor) {
        const cm = editor.codemirror;
        const page = store.getCurrentPage();
        let nextDid = 'd1';
        if (page && page.diagrams && page.diagrams.length > 0) {
            nextDid = page.diagrams[0].id;
        }
        const did = prompt('Enter diagram tag ID to insert:', nextDid);
        if (did) {
            cm.replaceSelection(`\n\n{{DIAGRAM:${did.trim()}}}\n\n`);
            cm.focus();
        }
    }

    _insertPageBreak(editor) {
        const cm = editor.codemirror;
        cm.replaceSelection('\n\n<!-- pagebreak -->\n\n');
        cm.focus();
    }

    _docKey(pageIndex) {
        const pid = store.state.project ? store.state.project.id : 'none';
        return `${pid}:${pageIndex}`;
    }

    resetDocs() {
        this.pageDocs.clear();
    }

    loadPageContent(pageIndex, markdownText, { force = false } = {}) {
        this._isSwitchingDoc = true;
        const key = this._docKey(pageIndex);
        let doc = this.pageDocs.get(key);
        const text = markdownText || '';

        if (!doc) {
            doc = new this.DocCtor(text, this.docMode);
            this.pageDocs.set(key, doc);
        } else if (force && doc.getValue() !== text) {
            doc.setValue(text); // server version wins (e.g. OCR just finished)
        }

        this.cm.swapDoc(doc);
        this._isSwitchingDoc = false;

        if (this._pendingFlagSelection) {
            const dir = this._pendingFlagSelection;
            this._pendingFlagSelection = null;
            setTimeout(() => {
                const fullText = this.getValue();
                const matches = [...fullText.matchAll(/\[\?(.+?)\?\]/g)];
                if (matches.length > 0) {
                    const m = (dir === 'first') ? matches[0] : matches[matches.length - 1];
                    const fromPos = this.cm.posFromIndex(m.index);
                    const toPos = this.cm.posFromIndex(m.index + m[0].length);
                    this.cm.setSelection(fromPos, toPos);
                    this.cm.scrollIntoView({ from: fromPos, to: toPos }, 80);
                    this.cm.focus();
                }
            }, 60);
        }

        if (this._onChangeCallback) {
            this._onChangeCallback(this.getValue());
        }
    }

    getValue() {
        return this.cm ? this.cm.getValue() : '';
    }

    setValue(text) {
        if (!this.cm) return;
        this.cm.setValue(text);
    }

    insertAtCursor(text) {
        if (!this.cm) return;
        this.cm.replaceSelection(text);
        this.cm.focus();
    }

    /**
     * Flag Navigator:
     * Jumps to the next or previous [?...?] match across all pages in the project.
     */
    jumpToNextFlag(forward = true) {
        if (!this.cm) return;

        const cursor = this.cm.getCursor();
        const fullText = this.cm.getValue();
        const flagRegex = /\[\?(.+?)\?\]/g;
        const matches = [...fullText.matchAll(flagRegex)];
        const curOffset = this.cm.indexFromPos(cursor);

        let targetMatch = null;
        if (forward) {
            targetMatch = matches.find(m => m.index > curOffset);
        } else {
            const before = matches.filter(m => m.index < curOffset);
            targetMatch = before.length > 0 ? before[before.length - 1] : null;
        }

        if (targetMatch) {
            const fromPos = this.cm.posFromIndex(targetMatch.index);
            const toPos = this.cm.posFromIndex(targetMatch.index + targetMatch[0].length);
            this.cm.setSelection(fromPos, toPos);
            this.cm.scrollIntoView({ from: fromPos, to: toPos }, 80);
            this.cm.focus();
            return;
        }

        // Cross-page jump
        const proj = store.state.project;
        if (!proj || !proj.page_order || proj.page_order.length === 0) {
            toast.info('No uncertain flags found.');
            return;
        }

        const curPageIdx = store.state.currentPageIndex;
        const order = proj.page_order;
        const curPos = order.indexOf(curPageIdx);

        let targetPageIdx = null;
        if (forward) {
            for (let step = 1; step <= order.length; step++) {
                const idx = order[(curPos + step) % order.length];
                const pg = proj.pages[String(idx)];
                const text = (idx === curPageIdx) ? fullText : (pg ? pg.markdown || '' : '');
                if (text.includes('[?')) {
                    targetPageIdx = idx;
                    break;
                }
            }
        } else {
            for (let step = 1; step <= order.length; step++) {
                const idx = order[(curPos - step + order.length) % order.length];
                const pg = proj.pages[String(idx)];
                const text = (idx === curPageIdx) ? fullText : (pg ? pg.markdown || '' : '');
                if (text.includes('[?')) {
                    targetPageIdx = idx;
                    break;
                }
            }
        }

        if (targetPageIdx === null) {
            toast.info('No uncertain flags in this project.');
            return;
        }

        if (targetPageIdx === curPageIdx) {
            // Wrap on current page
            targetMatch = forward ? matches[0] : matches[matches.length - 1];
            if (targetMatch) {
                const fromPos = this.cm.posFromIndex(targetMatch.index);
                const toPos = this.cm.posFromIndex(targetMatch.index + targetMatch[0].length);
                this.cm.setSelection(fromPos, toPos);
                this.cm.scrollIntoView({ from: fromPos, to: toPos }, 80);
                this.cm.focus();
            }
            return;
        }

        // Switch page
        this._pendingFlagSelection = forward ? 'first' : 'last';
        store.setCurrentPage(targetPageIdx);
    }

    /**
     * Accepts flag: removes [? and ?], leaving transcribed text.
     */
    acceptCurrentFlag() {
        if (!this.cm) return;
        const cursor = this.cm.getCursor();
        const line = this.cm.getLine(cursor.line);
        const col = cursor.ch;

        // Check if cursor is inside [?...?]
        const flagRegex = /\[\?(.+?)\?\]/g;
        let match;
        while ((match = flagRegex.exec(line)) !== null) {
            const startCol = match.index;
            const endCol = match.index + match[0].length;
            if (col >= startCol && col <= endCol) {
                const innerWord = match[1];
                const fromPos = { line: cursor.line, ch: startCol };
                const toPos = { line: cursor.line, ch: endCol };
                this.cm.replaceRange(innerWord, fromPos, toPos);
                toast.success(`Accepted flag: "${innerWord}"`);
                return;
            }
        }
    }

    locateDiagramTag(did) {
        if (!this.cm) return;
        const tag = `{{DIAGRAM:${did}}}`;
        const text = this.cm.getValue();
        const idx = text.indexOf(tag);
        if (idx !== -1) {
            const from = this.cm.posFromIndex(idx);
            const to = this.cm.posFromIndex(idx + tag.length);
            this.cm.setSelection(from, to);
            this.cm.scrollIntoView({ from, to }, 100);
            this.cm.focus();
        }
    }

    locateMathError(errorText) {
        if (!this.cm) return;
        const text = this.cm.getValue();
        // Extract a snippet to search for
        const snippet = errorText.substring(0, 20).replace(/KaTeX parse error:\s*/, '').trim();
        if (!snippet) return;
        const idx = text.indexOf(snippet);
        if (idx !== -1) {
            const from = this.cm.posFromIndex(idx);
            const to = this.cm.posFromIndex(idx + snippet.length);
            this.cm.setSelection(from, to);
            this.cm.scrollIntoView({ from, to }, 100);
            this.cm.focus();
        }
    }

    _debounceAutosave() {
        if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
        store.setSaveStatus('saving');

        this.autosaveTimer = setTimeout(async () => {
            const page = store.getCurrentPage();
            const project = store.state.project;
            if (!page || !project) return;

            try {
                await api.updatePage(project.id, page.index, {
                    markdown: this.getValue()
                });
                store.setSaveStatus('saved');
            } catch (err) {
                console.error('Autosave failed:', err);
                store.setSaveStatus('offline');
                toast.error(`Autosave failed: ${err.message}`);
            }
        }, 1500);
    }
}

export const documentEditor = new DocumentEditor();
