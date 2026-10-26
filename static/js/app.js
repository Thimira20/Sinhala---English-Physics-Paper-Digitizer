/**
 * Main Application Shell & Orchestrator.
 * Coordinates project management, upload, page strip, resizable panes,
 * batch OCR, live SSE updates, and split-screen editing.
 */

import { api } from './api.js';
import { store } from './state.js';
import { toast } from './toast.js';
import { sourceViewer } from './viewer.js';
import { documentEditor } from './editor.js';
import { previewRenderer } from './preview.js';
import { settingsModal } from './settings.js';
import { exportDialog } from './exportdlg.js';
import { countUncertainFlags } from './dialect.js';

class AppController {
    constructor() {
        this.pageStripEl = null;
        this.draggedPageIdx = null;
        this._pageStartTimes = {};
        this._pageDurations = [25];
        this._budgetWarned = false;
    }

    async init() {
        console.log('Initializing Sinhala & English Physics Paper Digitizer...');

        this._bindShellDom();
        this._initSplitters();
        this._initSubcomponents();
        this._bindKeyboardGlobal();
        this._bindStoreEvents();

        // Load Settings
        try {
            const s = await api.getSettings();
            store.setSettings(s);
        } catch (e) {
            console.warn('Failed to load settings:', e);
        }

        // Load Projects
        await this.loadProjects();

        // Restore selected project or open first/create
        const savedPid = localStorage.getItem('selected_project_id');
        const projects = store.state.projectsList;

        if (savedPid && projects.some(p => p.id === savedPid)) {
            await this.openProject(savedPid);
        } else if (projects.length > 0) {
            await this.openProject(projects[0].id);
        } else {
            // Create default project on first boot
            const newProj = await api.createProject('2026 AL Physics Past Paper');
            await this.loadProjects();
            await this.openProject(newProj.id);
        }
    }

    _bindShellDom() {
        this.pageStripEl = document.getElementById('page-strip');

        // Topbar buttons
        document.getElementById('btn-projects-menu').addEventListener('click', () => this._openProjectsDrawer());
        document.getElementById('btn-edit-proj-name').addEventListener('click', () => this._renameProject());
        document.getElementById('btn-upload').addEventListener('click', () => document.getElementById('file-upload-input').click());
        document.getElementById('file-upload-input').addEventListener('change', (e) => this._handleFileUpload(e.target.files));

        document.getElementById('btn-prev-page').addEventListener('click', () => this.navigatePage(-1));
        document.getElementById('btn-next-page').addEventListener('click', () => this.navigatePage(1));

        document.getElementById('btn-flags-nav').addEventListener('click', () => {
            documentEditor.jumpToNextFlag(true);
        });

        const eqBadge = document.getElementById('equation-errors-badge');
        if (eqBadge) {
            eqBadge.addEventListener('click', () => {
                const errEl = document.querySelector('.katex-error');
                if (errEl) {
                    const errText = errEl.getAttribute('title') || errEl.textContent || '';
                    documentEditor.locateMathError(errText);
                }
            });
        }

        document.getElementById('btn-settings').addEventListener('click', () => settingsModal.show());
        document.getElementById('btn-export-docx').addEventListener('click', () => exportDialog.show('docx'));
        document.getElementById('btn-export-pdf').addEventListener('click', () => exportDialog.show('pdf'));

        // Batch OCR Run All dropdown
        const runAllBtn = document.getElementById('btn-run-all');
        const runAllMenu = document.getElementById('run-all-menu');
        runAllBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            runAllMenu.classList.toggle('open');
        });

        document.querySelectorAll('.run-all-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                runAllMenu.classList.remove('open');
                const modelMode = opt.getAttribute('data-mode'); // 'accurate' or 'draft'
                this._batchRunOcr(modelMode);
            });
        });

        const retryFailedBtn = document.getElementById('btn-retry-failed');
        if (retryFailedBtn) {
            retryFailedBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                runAllMenu.classList.remove('open');
                const proj = store.state.project;
                if (!proj) return;
                const failedPages = proj.page_order.filter(idx => {
                    const p = proj.pages[String(idx)];
                    return p && p.status === 'error';
                });
                if (failedPages.length === 0) {
                    toast.info('No failed pages to retry.');
                    return;
                }
                await api.triggerOcr(proj.id, { pages: failedPages, model: 'accurate', force: true, overwrite: true });
                toast.info(`Queued ${failedPages.length} failed page(s) for retry.`);
            });
        }

        document.addEventListener('click', () => {
            runAllMenu.classList.remove('open');
        });

        // Global Drag & Drop Upload anywhere on window
        window.addEventListener('dragover', (e) => {
            e.preventDefault();
            document.body.classList.add('drag-over-active');
        });

        window.addEventListener('dragleave', (e) => {
            if (e.relatedTarget === null) {
                document.body.classList.remove('drag-over-active');
            }
        });

        window.addEventListener('drop', (e) => {
            e.preventDefault();
            document.body.classList.remove('drag-over-active');
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                this._handleFileUpload(e.dataTransfer.files);
            }
        });

        // View Mode Toggle (Split / Editor / Preview)
        document.querySelectorAll('.view-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.view-toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const mode = btn.getAttribute('data-mode');
                this._setViewMode(mode);
            });
        });
    }

    _setViewMode(mode) {
        const rightPane = document.getElementById('right-pane');
        rightPane.classList.remove('mode-split', 'mode-editor-only', 'mode-preview-only');
        rightPane.classList.add(`mode-${mode}`);
        localStorage.setItem('editor_view_mode', mode);
    }

    _initSplitters() {
        // Horizontal pane splitters
        const split1 = document.getElementById('split-handle-1');
        const split2 = document.getElementById('split-handle-2');
        const splitEditor = document.getElementById('editor-preview-splitter');
        const leftPane = document.getElementById('left-pane');
        const centerPane = document.getElementById('center-pane');
        const rightPane = document.getElementById('right-pane');
        const editorSubpane = document.getElementById('editor-subpane');

        // Restore saved sizes
        const savedSizes = JSON.parse(localStorage.getItem('panel_sizes') || 'null');
        if (savedSizes) {
            if (savedSizes.left) leftPane.style.width = `${savedSizes.left}px`;
            if (savedSizes.center) centerPane.style.width = `${savedSizes.center}px`;
            if (savedSizes.editorSubpane && editorSubpane) editorSubpane.style.width = `${savedSizes.editorSubpane}px`;
        }

        let isDragging = null;
        let startX = 0;
        let startLeftW = 0;
        let startCenterW = 0;
        let startEditorW = 0;

        split1.addEventListener('mousedown', (e) => {
            isDragging = 'split1';
            startX = e.clientX;
            startLeftW = leftPane.getBoundingClientRect().width;
            document.body.classList.add('resizing-col');
            e.preventDefault();
        });

        split2.addEventListener('mousedown', (e) => {
            isDragging = 'split2';
            startX = e.clientX;
            startCenterW = centerPane.getBoundingClientRect().width;
            document.body.classList.add('resizing-col');
            e.preventDefault();
        });

        if (splitEditor) {
            splitEditor.addEventListener('mousedown', (e) => {
                isDragging = 'splitEditor';
                startX = e.clientX;
                startEditorW = editorSubpane.getBoundingClientRect().width;
                document.body.classList.add('resizing-col');
                e.preventDefault();
            });
        }

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            if (isDragging === 'split1') {
                const newW = Math.max(160, Math.min(380, startLeftW + dx));
                leftPane.style.width = `${newW}px`;
            } else if (isDragging === 'split2') {
                const newW = Math.max(300, Math.min(window.innerWidth - 450, startCenterW + dx));
                centerPane.style.width = `${newW}px`;
            } else if (isDragging === 'splitEditor' && editorSubpane) {
                const maxW = Math.max(250, rightPane.getBoundingClientRect().width - 250);
                const newW = Math.max(200, Math.min(maxW, startEditorW + dx));
                editorSubpane.style.width = `${newW}px`;
            }
        });

        window.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = null;
                document.body.classList.remove('resizing-col');
                sourceViewer.render();
                // Save sizes
                const sizes = {
                    left: leftPane.getBoundingClientRect().width,
                    center: centerPane.getBoundingClientRect().width,
                    editorSubpane: editorSubpane ? editorSubpane.getBoundingClientRect().width : undefined
                };
                localStorage.setItem('panel_sizes', JSON.stringify(sizes));
            }
        });
    }

    _initSubcomponents() {
        // Initialize Viewer
        sourceViewer.init(document.getElementById('viewer-container'), {
            onBoxCreated: (diag) => {
                documentEditor.insertAtCursor(`\n\n{{DIAGRAM:${diag.id}}}\n\n`);
            },
            onBoxDeleted: (did) => {
                const cur = documentEditor.getValue();
                const cleaned = cur.replace(new RegExp(`\\{\\{DIAGRAM:${did}\\}\\}`, 'g'), '');
                documentEditor.setValue(cleaned);
            },
            onBoxSelected: (did) => {
                documentEditor.locateDiagramTag(did);
            }
        });

        // Initialize Editor
        documentEditor.init(document.getElementById('editor-textarea'), (newMarkdown) => {
            const page = store.getCurrentPage();
            previewRenderer.render(newMarkdown, page);
            this._updateTopbarFlagsCount();
        });

        // Initialize Preview
        previewRenderer.init(document.getElementById('preview-container'), (updatedMarkdown) => {
            documentEditor.setValue(updatedMarkdown);
        });

        // Re-render preview on diagram recrop
        window.addEventListener('diagram-recropped', () => {
            previewRenderer.render(documentEditor.getValue(), store.getCurrentPage(), true);
        });

        // Initialize Settings Modal & Export Dialog
        settingsModal.init();
        exportDialog.init();

        // Restore view mode
        const savedViewMode = localStorage.getItem('editor_view_mode') || 'split';
        this._setViewMode(savedViewMode);
        document.querySelector(`.view-toggle-btn[data-mode="${savedViewMode}"]`)?.classList.add('active');
    }

    _bindKeyboardGlobal() {
        window.addEventListener('keydown', (e) => {
            // Alt + ArrowLeft / ArrowRight -> Page nav
            if (e.altKey && e.key === 'ArrowLeft') {
                e.preventDefault();
                this.navigatePage(-1);
            } else if (e.altKey && e.key === 'ArrowRight') {
                e.preventDefault();
                this.navigatePage(1);
            }
        });
    }

    _bindStoreEvents() {
        store.subscribe('project', (proj) => {
            this._renderPageStrip();
            this._updateTopbarProject();
        });

        store.subscribe('currentPage', (pageIdx) => {
            this._renderPageStripActiveState();
            this._updateTopbarPageNav();

            const page = store.getCurrentPage();
            if (page) {
                documentEditor.loadPageContent(page.index, page.markdown || '');
                previewRenderer.render(page.markdown || '', page, true);
            }
        });

        store.subscribe('saveStatus', (status) => {
            const badge = document.getElementById('save-status-badge');
            if (status === 'saving') {
                badge.className = 'status-badge badge-saving';
                badge.textContent = 'Saving...';
            } else if (status === 'saved') {
                badge.className = 'status-badge badge-saved';
                badge.textContent = '● Saved';
            } else {
                badge.className = 'status-badge badge-offline';
                badge.textContent = '⚠ Offline';
            }
        });

        store.subscribe('queue', (q) => {
            const pill = document.getElementById('queue-status-pill');
            if (!pill) return;
            if (q.running > 0 || q.pending > 0) {
                pill.style.display = 'inline-flex';
                const workers = (store.state.settings && store.state.settings.max_concurrent_jobs) || 4;
                const avgSec = (this._pageDurations.reduce((a, b) => a + b, 0) / this._pageDurations.length) || 25;
                const eta = Math.max(1, Math.ceil(((q.pending + q.running) * avgSec) / Math.max(1, workers) / 60));
                pill.textContent = `Processing ${q.running} · ${q.pending} waiting · ETA ~${eta} min`;
            } else {
                pill.style.display = 'none';
            }
        });

        store.subscribe('settings', (settings) => {
            const accSpan = document.getElementById('run-all-accurate-model');
            if (accSpan && settings.gemini_model) accSpan.textContent = `(${settings.gemini_model})`;
            const draftSpan = document.getElementById('run-all-draft-model');
            if (draftSpan && settings.gemini_draft_model) draftSpan.textContent = `(${settings.gemini_draft_model})`;
        });

        store.subscribe('equationErrors', (count) => {
            const badge = document.getElementById('equation-errors-badge');
            if (badge) {
                if (count > 0) {
                    badge.style.display = 'inline-flex';
                    badge.textContent = `✖ ${count} equation error${count > 1 ? 's' : ''}`;
                } else {
                    badge.style.display = 'none';
                }
            }
        });

        store.subscribe('usage', (u) => {
            const el = document.getElementById('topbar-project-spend');
            if (el) el.textContent = `$${u.project_usd.toFixed(2)} this proj`;
        });
    }

    // --- Projects Management ---
    async loadProjects() {
        try {
            const list = await api.getProjects();
            store.setProjectsList(list);
        } catch (err) {
            toast.error(`Failed to load projects: ${err.message}`);
        }
    }

    async openProject(pid) {
        try {
            documentEditor.resetDocs();
            const proj = await api.getProject(pid);
            store.setProject(proj);
            localStorage.setItem('selected_project_id', pid);

            const page = store.getCurrentPage();
            if (page) {
                documentEditor.loadPageContent(page.index, page.markdown || '', { force: true });
                previewRenderer.render(page.markdown || '', page, true);
                sourceViewer.loadCurrentPage();
            }

            // Connect SSE for live updates
            this._connectProjectSSE(pid);

            // Update usage
            this._refreshUsage(pid);

            toast.info(`Opened project: ${proj.name}`);
        } catch (err) {
            toast.error(`Failed to open project ${pid}: ${err.message}`);
        }
    }

    async _refreshUsage(pid) {
        try {
            const u = await api.getUsage(pid);
            store.setUsage(u);
            const s = store.state.settings;
            if (!this._budgetWarned && s && s.monthly_budget_warning_usd && u.month_usd >= s.monthly_budget_warning_usd) {
                this._budgetWarned = true;
                toast.error(`Monthly API spend ($${u.month_usd.toFixed(2)}) has reached or exceeded your budget warning limit ($${s.monthly_budget_warning_usd.toFixed(2)}).`);
            }
        } catch (_) {}
    }

    _connectProjectSSE(pid) {
        api.connectSSE(pid, (event) => {
            if (event.type === 'page_status') {
                const proj = store.state.project;
                if (!proj) return;
                const p = proj.pages[String(event.page)];
                if (p) {
                    p.status = event.status;
                    if (event.uncertain_count !== undefined) p.uncertain_count = event.uncertain_count;
                    if (event.cost_usd !== undefined) p.cost_usd = event.cost_usd;
                    if (event.error) p.error = event.error;

                    if (event.status === 'processing') {
                        this._pageStartTimes[event.page] = Date.now();
                    } else if (event.status === 'done') {
                        const start = this._pageStartTimes[event.page];
                        if (start) {
                            const dur = Math.round((Date.now() - start) / 1000);
                            this._pageDurations.push(dur);
                            if (this._pageDurations.length > 20) this._pageDurations.shift();
                            delete this._pageStartTimes[event.page];
                        }
                    } else if (event.status === 'error') {
                        delete this._pageStartTimes[event.page];
                        const shortErr = (event.error || 'OCR failed').substring(0, 50);
                        toast.error(`Page ${event.page} failed: ${shortErr}`, {
                            actionLabel: 'Retry',
                            onAction: () => {
                                api.triggerOcr(pid, { pages: [event.page], model: 'accurate', force: true, overwrite: true });
                            }
                        });
                    }

                    this._renderPageStrip();

                    // If it is the current page, reload its content from server or update view
                    if (p.index === store.state.currentPageIndex) {
                        if (event.status === 'done') {
                            api.getProject(pid).then(updated => {
                                store.setProject(updated);
                                const page = updated.pages[String(event.page)];
                                if (page && event.page === store.state.currentPageIndex) {
                                    documentEditor.loadPageContent(page.index, page.markdown || '', { force: true });
                                    previewRenderer.render(page.markdown || '', page, true);
                                    sourceViewer.render(); // new diagram boxes
                                }
                            });
                        } else if (event.status === 'processing') {
                            previewRenderer.render('', p, true);
                        }
                    }
                }
                this._refreshUsage(pid);
            } else if (event.type === 'rate_wait') {
                toast.showRateWait(event.seconds);
            } else if (event.type === 'queue') {
                store.setQueue({ pending: event.pending, running: event.running });
            } else if (event.type === 'page_conflict') {
                toast.show(`New OCR result available for Page ${event.page} (manual edits preserved).`, 'warning', 10000, {
                    actionLabel: 'Replace',
                    onAction: async () => {
                        const proj = await api.getProject(pid);
                        const pg = proj.pages[String(event.page)];
                        if (pg && pg.ocr_markdown_pending) {
                            await api.updatePage(pid, event.page, { markdown: pg.ocr_markdown_pending, user_edited: true });
                            if (event.page === store.state.currentPageIndex) {
                                documentEditor.loadPageContent(event.page, pg.ocr_markdown_pending, { force: true });
                                previewRenderer.render(pg.ocr_markdown_pending, pg, true);
                            }
                            toast.success(`Page ${event.page} replaced with new OCR result.`);
                        }
                    }
                });
            }
        });
    }

    async _renameProject() {
        const proj = store.state.project;
        if (!proj) return;
        const newName = prompt('Enter new project name:', proj.name);
        if (!newName || newName.trim() === proj.name) return;

        try {
            const updated = await api.updateProject(proj.id, { name: newName.trim() });
            store.setProject(updated);
            await this.loadProjects();
            toast.success('Project renamed.');
        } catch (err) {
            toast.error(`Failed to rename project: ${err.message}`);
        }
    }

    _openProjectsDrawer() {
        let drawer = document.getElementById('projects-drawer');
        if (!drawer) {
            drawer = document.createElement('div');
            drawer.id = 'projects-drawer';
            drawer.className = 'drawer-backdrop';
            drawer.innerHTML = `
                <div class="drawer-panel">
                    <div class="drawer-header">
                        <h3>Physics Digitizer Projects</h3>
                        <button class="modal-close-btn" id="btn-close-drawer">&times;</button>
                    </div>
                    <div class="drawer-toolbar">
                        <button class="btn btn-primary btn-sm" id="btn-drawer-new-project">✚ New Project</button>
                    </div>
                    <div class="drawer-body" id="drawer-projects-list"></div>
                </div>
            `;
            document.body.appendChild(drawer);

            drawer.querySelector('#btn-close-drawer').addEventListener('click', () => drawer.classList.remove('open'));
            drawer.querySelector('#btn-drawer-new-project').addEventListener('click', async () => {
                const name = prompt('Enter name for the new project:', 'Physics Paper');
                if (!name) return;
                try {
                    const created = await api.createProject(name);
                    await this.loadProjects();
                    await this.openProject(created.id);
                    drawer.classList.remove('open');
                } catch (err) {
                    toast.error(`Failed to create project: ${err.message}`);
                }
            });
        }

        const listEl = drawer.querySelector('#drawer-projects-list');
        listEl.innerHTML = store.state.projectsList.map(p => `
            <div class="project-list-card ${p.id === store.state.project?.id ? 'active' : ''}" data-pid="${p.id}">
                <div class="proj-card-info">
                    <strong class="proj-card-name">${p.name}</strong>
                    <span class="proj-card-meta">${p.page_count} pages · ${p.created_at ? p.created_at.substring(0, 10) : ''}</span>
                </div>
                <div class="proj-card-actions">
                    <button class="btn btn-sm btn-outline btn-open-p" data-pid="${p.id}">Open</button>
                    <button class="btn btn-sm btn-danger btn-del-p" data-pid="${p.id}" title="Delete project">&times;</button>
                </div>
            </div>
        `).join('');

        listEl.querySelectorAll('.btn-open-p').forEach(b => {
            b.addEventListener('click', () => {
                this.openProject(b.getAttribute('data-pid'));
                drawer.classList.remove('open');
            });
        });

        listEl.querySelectorAll('.btn-del-p').forEach(b => {
            b.addEventListener('click', async (e) => {
                e.stopPropagation();
                const pid = b.getAttribute('data-pid');
                if (!confirm(`Are you sure you want to permanently delete this project?`)) return;
                try {
                    await api.deleteProject(pid);
                    toast.info('Project deleted.');
                    await this.loadProjects();
                    if (store.state.project?.id === pid) {
                        const remaining = store.state.projectsList;
                        if (remaining.length > 0) await this.openProject(remaining[0].id);
                    }
                    this._openProjectsDrawer();
                } catch (err) {
                    toast.error(`Delete failed: ${err.message}`);
                }
            });
        });

        drawer.classList.add('open');
    }

    // --- Page Strip (Thumbnails, Reorder, Status Dots) ---
    _renderPageStrip() {
        if (!this.pageStripEl) return;
        const project = store.state.project;
        if (!project || !project.page_order) {
            this.pageStripEl.innerHTML = '<div class="empty-state">No pages. Click Upload or drop files.</div>';
            return;
        }

        const html = project.page_order.map((pageIdx, orderPos) => {
            const page = project.pages[String(pageIdx)];
            if (!page) return '';

            const statusClass = `status-${page.status || 'pending'}`;
            const flagsCount = page.uncertain_count !== undefined ? page.uncertain_count : countUncertainFlags(page.markdown || '');
            const isCur = (pageIdx === store.state.currentPageIndex);
            const isError = (page.status === 'error');

            return `
                <div class="strip-card ${page.status || 'pending'} ${isCur ? 'active' : ''}"
                     data-page-idx="${pageIdx}"
                     draggable="true">
                    ${isError ? `<button class="strip-retry-btn" data-page-idx="${pageIdx}" title="${page.error || 'Failed. Click to retry.'}">↻</button>` : ''}
                    <div class="strip-card-header">
                        <span class="strip-status-dot ${statusClass}" title="Status: ${page.status}"></span>
                        <span class="strip-page-num">${pageIdx}</span>
                        ${flagsCount > 0 ? `<span class="strip-flag-badge" title="${flagsCount} uncertain readings">⚠ ${flagsCount}</span>` : ''}
                        <input type="checkbox" class="strip-export-chk" ${page.include_in_export ? 'checked' : ''} title="Include in export" />
                    </div>
                    <div class="strip-thumb-wrap">
                        <img class="strip-thumb-img" src="/files/${project.id}/${page.thumb_file}" alt="Page ${pageIdx}" loading="lazy" />
                    </div>
                </div>
            `;
        }).join('');

        // Plus Add Page button card
        const addCardHtml = `
            <div class="strip-add-card" id="btn-strip-add-pages" title="Upload more pages to this project">
                <span>✚</span>
                <small>Add Pages</small>
            </div>
        `;

        this.pageStripEl.innerHTML = html + addCardHtml;
        this._bindPageStripEvents();
    }

    _bindPageStripEvents() {
        const project = store.state.project;
        if (!project) return;

        // Strip retry button clicks
        this.pageStripEl.querySelectorAll('.strip-retry-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const pIdx = parseInt(btn.getAttribute('data-page-idx'), 10);
                await api.triggerOcr(project.id, { pages: [pIdx], model: 'accurate', force: true, overwrite: true });
                toast.info(`Retrying Page ${pIdx}...`);
            });
        });

        // Card Click -> Select Page
        this.pageStripEl.querySelectorAll('.strip-card').forEach(card => {
            const pIdx = parseInt(card.getAttribute('data-page-idx'), 10);

            card.addEventListener('click', (e) => {
                if (e.target.classList.contains('strip-export-chk') || e.target.classList.contains('strip-retry-btn')) return;
                store.setCurrentPage(pIdx);
            });

            // Export checkbox
            const chk = card.querySelector('.strip-export-chk');
            if (chk) {
                chk.addEventListener('change', async (e) => {
                    e.stopPropagation();
                    const page = project.pages[String(pIdx)];
                    if (page) {
                        page.include_in_export = chk.checked;
                        await api.updatePage(project.id, pIdx, { include_in_export: chk.checked });
                    }
                });
            }

            // HTML5 Drag & Drop Reorder
            card.addEventListener('dragstart', (e) => {
                this.draggedPageIdx = pIdx;
                card.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });

            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
                this.pageStripEl.querySelectorAll('.strip-card').forEach(c => c.classList.remove('drag-over-target'));
            });

            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                card.classList.add('drag-over-target');
            });

            card.addEventListener('dragleave', () => {
                card.classList.remove('drag-over-target');
            });

            card.addEventListener('drop', async (e) => {
                e.preventDefault();
                card.classList.remove('drag-over-target');
                const targetIdx = pIdx;
                if (this.draggedPageIdx && this.draggedPageIdx !== targetIdx) {
                    await this._reorderPages(this.draggedPageIdx, targetIdx);
                }
            });

            // Context Menu (Right Click)
            card.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                this._showPageContextMenu(e.clientX, e.clientY, pIdx);
            });
        });

        // Add Pages button
        const addBtn = this.pageStripEl.querySelector('#btn-strip-add-pages');
        if (addBtn) {
            addBtn.addEventListener('click', () => document.getElementById('file-upload-input').click());
        }
    }

    _showPageContextMenu(x, y, pageIdx) {
        let menu = document.getElementById('page-strip-context-menu');
        if (!menu) {
            menu = document.createElement('div');
            menu.id = 'page-strip-context-menu';
            menu.className = 'diagram-context-menu';
            document.body.appendChild(menu);
        }

        const project = store.state.project;
        const page = project ? project.pages[String(pageIdx)] : null;
        if (!page) return;

        const s = store.state.settings || {};
        const accLabel = s.gemini_model ? `Re-run OCR (${s.gemini_model})` : 'Re-run OCR (Accurate Pro)';
        const draftLabel = s.gemini_draft_model ? `Re-run OCR (${s.gemini_draft_model})` : 'Re-run OCR (Draft Flash)';

        menu.innerHTML = `
            <div class="ctx-item" data-action="run-accurate">${accLabel}</div>
            <div class="ctx-item" data-action="run-draft">${draftLabel}</div>
            <div class="ctx-divider"></div>
            <div class="ctx-item" data-action="toggle-break">${page.page_break_after ? '✔ Page Break After' : '☐ Page Break After'}</div>
            <div class="ctx-divider"></div>
            <div class="ctx-item ctx-danger" data-action="delete">Delete Page ${pageIdx}</div>
        `;

        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;
        menu.classList.add('open');

        const closeMenu = () => menu.classList.remove('open');
        document.addEventListener('click', closeMenu, { once: true });

        menu.querySelectorAll('.ctx-item').forEach(item => {
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                closeMenu();
                const act = item.getAttribute('data-action');

                if (act === 'run-accurate' || act === 'run-draft') {
                    const mode = (act === 'run-accurate') ? 'accurate' : 'draft';
                    if (page.user_edited && !confirm(`Page ${pageIdx} has unsaved manual edits. Overwrite with new OCR transcription?`)) return;
                    await api.triggerOcr(project.id, { pages: [pageIdx], model: mode, force: true, overwrite: true });
                    toast.info(`Queued OCR for Page ${pageIdx}`);
                } else if (act === 'toggle-break') {
                    const newVal = !page.page_break_after;
                    page.page_break_after = newVal;
                    await api.updatePage(project.id, pageIdx, { page_break_after: newVal });
                    toast.info(`Page break after Page ${pageIdx}: ${newVal ? 'ON' : 'OFF'}`);
                } else if (act === 'delete') {
                    if (!confirm(`Delete Page ${pageIdx} from this project?`)) return;
                    await api.deletePage(project.id, pageIdx);
                    delete project.pages[String(pageIdx)];
                    project.page_order = project.page_order.filter(p => p !== pageIdx);
                    store.setProject(project);
                    toast.info(`Deleted Page ${pageIdx}`);
                }
            });
        });
    }

    async _reorderPages(draggedIdx, targetIdx) {
        const project = store.state.project;
        if (!project || !project.page_order) return;

        const order = [...project.page_order];
        const fromPos = order.indexOf(draggedIdx);
        const toPos = order.indexOf(targetIdx);

        if (fromPos < 0 || toPos < 0) return;

        order.splice(fromPos, 1);
        order.splice(toPos, 0, draggedIdx);

        project.page_order = order;
        this._renderPageStrip();

        try {
            await api.updateProject(project.id, { page_order: order });
            toast.success('Page reordered.');
        } catch (err) {
            toast.error(`Failed to save page order: ${err.message}`);
        }
    }

    _renderPageStripActiveState() {
        if (!this.pageStripEl) return;
        this.pageStripEl.querySelectorAll('.strip-card').forEach(card => {
            const pIdx = parseInt(card.getAttribute('data-page-idx'), 10);
            card.classList.toggle('active', pIdx === store.state.currentPageIndex);
        });
    }

    // --- Navigation & Header Updates ---
    navigatePage(delta) {
        const project = store.state.project;
        if (!project || !project.page_order || project.page_order.length === 0) return;

        const curIdx = store.state.currentPageIndex;
        const curPos = project.page_order.indexOf(curIdx);
        if (curPos < 0) return;

        const nextPos = curPos + delta;
        if (nextPos >= 0 && nextPos < project.page_order.length) {
            store.setCurrentPage(project.page_order[nextPos]);
        }
    }

    _updateTopbarProject() {
        const proj = store.state.project;
        if (!proj) return;
        document.getElementById('topbar-project-name').textContent = proj.name;
    }

    _updateTopbarPageNav() {
        const proj = store.state.project;
        if (!proj || !proj.page_order) return;

        const curIdx = store.state.currentPageIndex;
        const curPos = proj.page_order.indexOf(curIdx) + 1;
        const total = proj.page_order.length;

        document.getElementById('topbar-page-display').textContent = `${curPos || 1} / ${total || 1}`;
        this._updateTopbarFlagsCount();
    }

    _updateTopbarFlagsCount() {
        const proj = store.state.project;
        if (!proj) return;
        let total = 0;
        for (const pIdx of (proj.page_order || [])) {
            if (pIdx === store.state.currentPageIndex) {
                total += countUncertainFlags(documentEditor.getValue());
            } else {
                const p = proj.pages[String(pIdx)];
                if (p) {
                    total += (p.uncertain_count !== undefined ? p.uncertain_count : countUncertainFlags(p.markdown || ''));
                }
            }
        }
        const badge = document.getElementById('topbar-flags-count');
        badge.textContent = `${total} flag${total === 1 ? '' : 's'}`;
        document.getElementById('btn-flags-nav').style.display = total > 0 ? 'inline-flex' : 'none';
    }

    // --- File Upload ---
    async _handleFileUpload(files) {
        const project = store.state.project;
        if (!project) return;
        if (!files || files.length === 0) return;

        const uploadProgress = document.getElementById('upload-progress-bar');
        uploadProgress.style.display = 'block';
        uploadProgress.style.width = '0%';

        try {
            toast.info(`Uploading ${files.length} file(s)...`);
            const res = await api.uploadFiles(project.id, files, (pct) => {
                uploadProgress.style.width = `${pct}%`;
            });

            uploadProgress.style.display = 'none';
            toast.success(`Added ${res.added_pages.length} pages to project.`);

            // Refresh project
            const updated = await api.getProject(project.id);
            store.setProject(updated);

            if (res.added_pages.length > 0) {
                store.setCurrentPage(res.added_pages[0]);
            }
        } catch (err) {
            uploadProgress.style.display = 'none';
            toast.error(`Upload error: ${err.message}`);
        }
    }

    // --- Batch OCR ---
    async _batchRunOcr(modelMode) {
        const project = store.state.project;
        if (!project) return;

        // Check if any pages have user edits
        const editedPages = [];
        const donePages = [];
        for (const p of Object.values(project.pages)) {
            if (p.user_edited) editedPages.push(p.index);
            else if (p.status === 'done') donePages.push(p.index);
        }

        let overwrite = false;
        if (editedPages.length > 0) {
            const confirmed = confirm(
                `Warning: The following pages contain manual edits: [${editedPages.join(', ')}].\n` +
                `Overwriting will replace your manual edits with fresh AI transcriptions.\n\n` +
                `Do you want to re-OCR and overwrite them?`
            );
            if (!confirmed) return;
            overwrite = true;
        } else if (donePages.length > 0) {
            const confirmed = confirm(`Re-run OCR on all pages including ${donePages.length} already completed pages?`);
            overwrite = confirmed;
        }

        try {
            const res = await api.triggerOcr(project.id, {
                pages: 'all',
                model: modelMode,
                force: overwrite,
                overwrite: overwrite
            });
            toast.info(`Queued ${res.queued.length} pages for processing.`);
        } catch (err) {
            toast.error(`Failed to trigger OCR: ${err.message}`);
        }
    }
}

export const app = new AppController();

// Boot application when DOM is ready
window.addEventListener('DOMContentLoaded', () => {
    app.init();
});
