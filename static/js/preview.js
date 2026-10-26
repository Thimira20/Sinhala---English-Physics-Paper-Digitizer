/**
 * Live Preview Renderer with KaTeX, DOMPurify, Equation Error Detection,
 * Diagram Overlays, and MCQ Layout Switcher chips.
 */

import { protectMath, restoreMath, applyNumberingEscape, RE_UNCERTAIN_FLAG } from './dialect.js';
import { parseOptions, emit, detectLayout, canUseGridLayout, MCQ_LAYOUTS } from './mcq.js';
import { store } from './state.js';
import { api } from './api.js';
import { toast } from './toast.js';

class PreviewRenderer {
    constructor() {
        this.previewContainer = null;
        this.paperEl = null;
        this._renderTimeout = null;
        this._lastMarkdown = '';
        this._activePage = null;
        this._onMcqLayoutChange = null;
    }

    init(containerEl, onMcqLayoutChange = null) {
        this.previewContainer = containerEl;
        this.paperEl = containerEl.querySelector('#preview-paper') || containerEl;
        this._onMcqLayoutChange = onMcqLayoutChange;

        // Configure marked with katex extension
        if (window.marked && window.markedKatex) {
            window.marked.use(window.markedKatex({
                throwOnError: false,
                strict: 'ignore',
                output: 'html'
            }));
        }

        // Setup diagram context menu delegate
        this._setupContextMenu();
    }

    render(markdown, page, immediate = false) {
        this._lastMarkdown = markdown || '';
        this._activePage = page;

        if (this._renderTimeout) {
            clearTimeout(this._renderTimeout);
        }

        if (immediate) {
            this._executeRender();
        } else {
            this._renderTimeout = setTimeout(() => {
                this._executeRender();
            }, 150);
        }
    }

    _executeRender() {
        if (!this.paperEl) return;
        const page = this._activePage || store.getCurrentPage();
        const project = store.state.project;
        const pid = project ? project.id : '';

        if (page && page.status === 'processing') {
            this.paperEl.innerHTML = `
                <div class="preview-skeleton-wrap" style="padding: 20px 0;">
                    <div class="preview-skeleton-bar" style="width: 80%; height: 26px; margin-bottom: 24px;"></div>
                    <div class="preview-skeleton-bar" style="width: 100%;"></div>
                    <div class="preview-skeleton-bar" style="width: 95%;"></div>
                    <div class="preview-skeleton-bar" style="width: 70%; margin-bottom: 24px;"></div>
                    <div class="preview-skeleton-bar" style="width: 90%;"></div>
                    <div class="preview-skeleton-bar" style="width: 85%;"></div>
                </div>
            `;
            return;
        }

        let text = this._lastMarkdown;

        // 1. Protect math
        const { protectedText, mathTokens } = protectMath(text);
        let processed = protectedText;

        // 2. Numbering escape
        processed = applyNumberingEscape(processed);

        // 3. Pagebreak marker
        processed = processed.replace(/^\s*<!--\s*pagebreak\s*-->\s*$/gmi, '<hr class="pagebreak-divider" data-title="Page Break" />');

        // 4. MCQ blocks with index data attribute
        let mcqCounter = 0;
        processed = processed.replace(/<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi, (match, inner) => {
            const bIdx = mcqCounter++;
            if (project && page) {
                store.saveOriginalMcq(project.id, page.index, bIdx, match);
            }
            return `\n\n<div class="mcq-preview-block" data-mcq-idx="${bIdx}">\n\n${inner}\n\n</div>\n\n`;
        });

        // 5. Uncertain flags [?xyz?] -> <mark class="flag-uncertain">xyz</mark>
        processed = processed.replace(RE_UNCERTAIN_FLAG, '<mark class="flag-uncertain" title="Uncertain transcription: [?$1?]">$1</mark>');

        // 6. Diagrams {{DIAGRAM:dN}}
        const diagramsMap = new Map();
        if (page && page.diagrams) {
            for (const d of page.diagrams) {
                diagramsMap.set(d.id, d);
            }
        }

        processed = processed.replace(/\{\{DIAGRAM:(d\d+)\}\}/g, (match, did) => {
            const diag = diagramsMap.get(did);
            if (!diag) {
                return `<div class="diagram-missing-placeholder">[⚠ Diagram ${did} not found]</div>`;
            }
            const widthPct = diag.width_pct || 45;
            const imgSrc = `/files/${pid}/${diag.file}?v=${diag.version || 0}`;
            return `
                <div class="preview-diagram-wrapper" data-did="${did}">
                    <img class="preview-diagram-img" src="${imgSrc}" style="width: ${widthPct}%; max-width: 100%;" alt="${diag.label || did}" />
                    <div class="diagram-meta-badge">
                        <span class="diag-lbl">${diag.label || did}</span>
                        <span class="diag-dim">(${did} · ${widthPct}%)</span>
                    </div>
                </div>
            `;
        });

        // 7. Restore math
        processed = restoreMath(processed, mathTokens);

        // 8. Markdown Parse
        let rawHtml = '';
        try {
            rawHtml = window.marked ? window.marked.parse(processed) : processed;
        } catch (e) {
            console.error('Markdown parse error:', e);
            rawHtml = `<div class="preview-error">Markdown Parse Error: ${e.message}</div>`;
        }

        // 9. DOMPurify sanitize
        const cleanHtml = window.DOMPurify ? window.DOMPurify.sanitize(rawHtml, {
            ADD_TAGS: ['mark', 'u', 'hr'],
            ADD_ATTR: ['style', 'data-mcq-idx', 'data-did', 'data-title', 'target'],
            FORBID_TAGS: ['script', 'iframe'],
            FORBID_ATTR: ['onerror', 'onload', 'onclick']
        }) : rawHtml;

        this.paperEl.innerHTML = cleanHtml;

        // Post-processing: Equation error count and styling
        this._checkEquationErrors();

        // Attach MCQ floating chips
        this._attachMcqChips();
    }

    _checkEquationErrors() {
        const errorEls = this.paperEl.querySelectorAll('.katex-error');
        const count = errorEls.length;
        store.setEquationErrorsCount(count);

        errorEls.forEach(el => {
            el.classList.add('katex-error-highlight');
            el.setAttribute('title', 'LaTeX parsing error. Click to locate.');
            el.addEventListener('click', () => {
                const errText = el.textContent || '';
                window.dispatchEvent(new CustomEvent('jump-to-math-error', { detail: { text: errText } }));
            });
        });
    }

    _attachMcqChips() {
        const blocks = this.paperEl.querySelectorAll('.mcq-preview-block');
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        blocks.forEach((blockEl, idx) => {
            const blockIdx = parseInt(blockEl.getAttribute('data-mcq-idx'), 10);

            // Find current text of this block from markdown
            const allMatches = [...this._lastMarkdown.matchAll(/<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi)];
            if (!allMatches[blockIdx]) return;

            const blockText = allMatches[blockIdx][1];
            const currentLayout = detectLayout(blockText);
            const options = parseOptions(blockText);
            const canGrid = canUseGridLayout(options);

            // Create chip container
            const chipContainer = document.createElement('div');
            chipContainer.className = 'mcq-layout-chip-bar';

            const chipBtn = document.createElement('button');
            chipBtn.className = 'mcq-layout-chip';
            const curLabel = (MCQ_LAYOUTS.find(l => l.id === currentLayout) || {}).label || 'As original';
            chipBtn.innerHTML = `Layout: <strong>${curLabel}</strong> ▾`;

            const menu = document.createElement('div');
            menu.className = 'mcq-layout-menu';

            MCQ_LAYOUTS.forEach(layout => {
                const item = document.createElement('div');
                item.className = 'mcq-layout-menu-item';
                if (layout.id === currentLayout) item.classList.add('active');

                const disabled = !canGrid && layout.id !== 'list' && layout.id !== 'as_original';
                if (disabled) {
                    item.classList.add('disabled');
                    item.title = 'Options contain $$ or are too long (>120 chars) for multi-column grid.';
                }

                item.textContent = layout.label;
                item.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (disabled) return;
                    menu.classList.remove('open');
                    this._changeMcqLayout(blockIdx, layout.id, blockText, options);
                });
                menu.appendChild(item);
            });

            // "Apply to all on page" action
            const divider = document.createElement('div');
            divider.className = 'mcq-layout-menu-divider';
            menu.appendChild(divider);

            const applyPageItem = document.createElement('div');
            applyPageItem.className = 'mcq-layout-menu-item action-item';
            applyPageItem.textContent = 'Apply current layout to all on page';
            applyPageItem.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.remove('open');
                this._applyLayoutToAll(currentLayout, false);
            });
            menu.appendChild(applyPageItem);

            const applyProjectItem = document.createElement('div');
            applyProjectItem.className = 'mcq-layout-menu-item action-item';
            applyProjectItem.textContent = 'Apply layout to all MCQs in project';
            applyProjectItem.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.remove('open');
                this._applyLayoutToAll(currentLayout, true);
            });
            menu.appendChild(applyProjectItem);

            chipBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                // Close other open menus
                document.querySelectorAll('.mcq-layout-menu.open').forEach(m => {
                    if (m !== menu) m.classList.remove('open');
                });
                menu.classList.toggle('open');
            });

            chipContainer.appendChild(chipBtn);
            chipContainer.appendChild(menu);
            blockEl.prepend(chipContainer);
        });

        // Global dismiss for layout menus
        document.addEventListener('click', () => {
            document.querySelectorAll('.mcq-layout-menu.open').forEach(m => m.classList.remove('open'));
        }, { once: true });
    }

    _changeMcqLayout(blockIdx, targetLayout, currentBlockText, options) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        let newBlockText = '';
        if (targetLayout === 'as_original') {
            const orig = store.getOriginalMcq(project.id, page.index, blockIdx);
            newBlockText = orig ? orig : `<!-- mcq -->\n${currentBlockText}\n<!-- /mcq -->`;
        } else {
            newBlockText = emit(options, targetLayout);
        }

        // Replace the specific block in the markdown
        const allMatches = [...this._lastMarkdown.matchAll(/<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi)];
        if (!allMatches[blockIdx]) return;

        const match = allMatches[blockIdx];
        const updatedMarkdown = this._lastMarkdown.substring(0, match.index) +
            newBlockText +
            this._lastMarkdown.substring(match.index + match[0].length);

        if (this._onMcqLayoutChange) {
            this._onMcqLayoutChange(updatedMarkdown);
        }
    }

    async _applyLayoutToAll(layout, allProject = false) {
        if (allProject) {
            if (!confirm(`Apply ${layout} layout to all MCQs across all pages in this project?`)) return;
            const project = store.state.project;
            if (!project) return;
            try {
                for (const pageIdx of project.page_order) {
                    const p = project.pages[String(pageIdx)];
                    if (!p || !p.markdown) continue;
                    const newMd = p.markdown.replace(/<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi, (match, inner) => {
                        const options = parseOptions(inner);
                        if (options.length === 0) return match;
                        return emit(options, layout);
                    });
                    if (newMd !== p.markdown) {
                        p.markdown = newMd;
                        await api.updatePage(project.id, pageIdx, { markdown: newMd });
                    }
                }
                const curPage = store.getCurrentPage();
                if (curPage) {
                    window.documentEditor?.loadPageContent(curPage.index, curPage.markdown || '', { force: true });
                    this.render(curPage.markdown || '', curPage, true);
                }
                toast.success(`Applied ${layout} layout across all project MCQs.`);
            } catch (err) {
                toast.error(`Failed to apply MCQ layout: ${err.message}`);
            }
            return;
        }

        const page = store.getCurrentPage();
        if (!page || !this._onMcqLayoutChange) return;

        let updated = this._lastMarkdown.replace(/<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi, (match, inner) => {
            const options = parseOptions(inner);
            return emit(options, layout);
        });

        this._onMcqLayoutChange(updated);
        toast.success(`Applied ${layout} layout to all MCQs on this page.`);
    }

    _setupContextMenu() {
        const menu = document.createElement('div');
        menu.id = 'diagram-context-menu';
        menu.className = 'diagram-context-menu';
        menu.innerHTML = `
            <div class="ctx-item" data-action="width-25">Width: 25%</div>
            <div class="ctx-item" data-action="width-50">Width: 50%</div>
            <div class="ctx-item" data-action="width-75">Width: 75%</div>
            <div class="ctx-item" data-action="width-100">Width: 100%</div>
            <div class="ctx-item" data-action="width-custom">Custom width...</div>
            <div class="ctx-divider"></div>
            <div class="ctx-item" data-action="mode-normalize">Mode: Clean (Normalize)</div>
            <div class="ctx-item" data-action="mode-binary">Mode: High-Contrast Binary</div>
            <div class="ctx-item" data-action="mode-original">Mode: Original Crop</div>
            <div class="ctx-divider"></div>
            <div class="ctx-item" data-action="replace">Replace Image...</div>
            <div class="ctx-item ctx-danger" data-action="delete">Delete Diagram</div>
        `;
        document.body.appendChild(menu);

        let activeDid = null;

        this.paperEl.addEventListener('contextmenu', (e) => {
            const wrapper = e.target.closest('.preview-diagram-wrapper');
            if (!wrapper) return;

            e.preventDefault();
            activeDid = wrapper.getAttribute('data-did');
            menu.style.left = `${e.clientX}px`;
            menu.style.top = `${e.clientY}px`;
            menu.classList.add('open');
        });

        document.addEventListener('click', () => {
            menu.classList.remove('open');
        });

        menu.querySelectorAll('.ctx-item').forEach(item => {
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                menu.classList.remove('open');
                if (!activeDid) return;

                const action = item.getAttribute('data-action');
                await this._handleDiagramMenuAction(activeDid, action);
            });
        });
    }

    async _handleDiagramMenuAction(did, action) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        if (action.startsWith('width-')) {
            let widthPct = 50;
            if (action === 'width-25') widthPct = 25;
            else if (action === 'width-50') widthPct = 50;
            else if (action === 'width-75') widthPct = 75;
            else if (action === 'width-100') widthPct = 100;
            else if (action === 'width-custom') {
                const input = prompt('Enter diagram width percentage (15 to 100):', '50');
                if (!input) return;
                widthPct = parseInt(input, 10);
                if (isNaN(widthPct)) return;
            }
            try {
                const updated = await api.patchDiagram(project.id, page.index, did, { width_pct: widthPct });
                const d = page.diagrams.find(x => x.id === did);
                if (d) Object.assign(d, updated);
                this.render(this._lastMarkdown, page, true);
                toast.success(`Diagram ${did} width updated to ${widthPct}%`);
            } catch (err) {
                toast.error(`Failed to update diagram width: ${err.message}`);
            }
        } else if (action.startsWith('mode-')) {
            const mode = action.replace('mode-', '');
            try {
                const updated = await api.patchDiagram(project.id, page.index, did, { mode });
                const d = page.diagrams.find(x => x.id === did);
                if (d) Object.assign(d, updated);
                this.render(this._lastMarkdown, page, true);
                toast.success(`Diagram ${did} mode changed to ${mode}`);
            } catch (err) {
                toast.error(`Failed to update diagram mode: ${err.message}`);
            }
        } else if (action === 'replace') {
            const fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.accept = 'image/png,image/jpeg,image/webp';
            fileInput.onchange = async () => {
                if (fileInput.files.length === 0) return;
                try {
                    const updated = await api.replaceDiagram(project.id, page.index, did, fileInput.files[0]);
                    const d = page.diagrams.find(x => x.id === did);
                    if (d) Object.assign(d, updated);
                    this.render(this._lastMarkdown, page, true);
                    toast.success(`Diagram ${did} replaced successfully.`);
                } catch (err) {
                    toast.error(`Image replacement failed: ${err.message}`);
                }
            };
            fileInput.click();
        } else if (action === 'delete') {
            if (!confirm(`Delete diagram ${did}? This will also remove {{DIAGRAM:${did}}} from the text.`)) return;
            try {
                await api.deleteDiagram(project.id, page.index, did);
                page.diagrams = page.diagrams.filter(x => x.id !== did);
                // Also remove tag in markdown
                const cleanedMd = this._lastMarkdown.replace(new RegExp(`\\{\\{DIAGRAM:${did}\\}\\}`, 'g'), '');
                if (this._onMcqLayoutChange) {
                    this._onMcqLayoutChange(cleanedMd);
                }
                toast.info(`Diagram ${did} deleted.`);
            } catch (err) {
                toast.error(`Failed to delete diagram: ${err.message}`);
            }
        }
    }
}

export const previewRenderer = new PreviewRenderer();
