/**
 * Export Dialog Component:
 * Export project to Word (.docx) or PDF (.pdf) with page selection,
 * uncertain flags stripping toggle, and font embedding options.
 */

import { api } from './api.js';
import { store } from './state.js';
import { toast } from './toast.js';

class ExportDialog {
    constructor() {
        this.modal = null;
        this.exportType = 'docx'; // 'docx' | 'pdf'
    }

    init() {
        this._buildDom();
        this._bindEvents();
    }

    _buildDom() {
        const modalEl = document.createElement('div');
        modalEl.id = 'export-modal';
        modalEl.className = 'modal-backdrop';
        modalEl.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-header">
                    <h3 id="export-modal-title">Export Document</h3>
                    <button class="modal-close-btn" id="btn-close-export">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Pages to Export</label>
                        <div class="radio-group">
                            <label><input type="radio" name="export-scope" value="all" checked /> All included pages</label>
                            <label><input type="radio" name="export-scope" value="selected" /> Selected pages (checkboxes)</label>
                            <label><input type="radio" name="export-scope" value="current" /> Current page only</label>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="export-chk-strip-flags" checked />
                            Clean uncertain reading flags ([?word?] &rarr; word)
                        </label>
                        <div id="export-flags-warning" class="help-text warning-text"></div>
                    </div>
                    <div class="form-group" id="export-group-embed-fonts">
                        <label class="checkbox-label">
                            <input type="checkbox" id="export-chk-embed-fonts" checked />
                            Embed Sinhala & Latin fonts into Word file
                        </label>
                        <span class="help-text">Guarantees identical appearance on computers without Noto Sans Sinhala installed.</span>
                    </div>
                    <div id="export-progress-container" class="export-progress-box" style="display: none;">
                        <div class="spinner"></div>
                        <span id="export-progress-text">Exporting document...</span>
                    </div>
                    <div id="export-result-box" class="export-result-box" style="display: none;"></div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-ghost" id="btn-cancel-export">Close</button>
                    <button class="btn btn-primary" id="btn-run-export">Export Now</button>
                </div>
            </div>
        `;

        document.body.appendChild(modalEl);
        this.modal = modalEl;
    }

    _bindEvents() {
        this.modal.querySelector('#btn-close-export').addEventListener('click', () => this.hide());
        this.modal.querySelector('#btn-cancel-export').addEventListener('click', () => this.hide());
        this.modal.querySelector('#btn-run-export').addEventListener('click', () => this._executeExport());
    }

    show(type = 'docx') {
        this.exportType = type;
        const titleEl = this.modal.querySelector('#export-modal-title');
        titleEl.textContent = type === 'docx' ? 'Export to Microsoft Word (.docx)' : 'Export to PDF (.pdf)';

        const embedGroup = this.modal.querySelector('#export-group-embed-fonts');
        embedGroup.style.display = (type === 'docx') ? 'block' : 'none';

        // Check flags warning
        const project = store.state.project;
        let totalFlags = 0;
        if (project && project.pages) {
            totalFlags = Object.values(project.pages).reduce((acc, p) => acc + (p.uncertain_count || 0), 0);
        }

        const warnEl = this.modal.querySelector('#export-flags-warning');
        if (totalFlags > 0) {
            warnEl.textContent = `⚠ Note: Project has ${totalFlags} flagged words. Stripping them will export your best guess without markers.`;
            warnEl.style.display = 'block';
        } else {
            warnEl.style.display = 'none';
        }

        // Reset progress/result
        this.modal.querySelector('#export-progress-container').style.display = 'none';
        this.modal.querySelector('#export-result-box').style.display = 'none';
        this.modal.querySelector('#btn-run-export').disabled = false;

        this.modal.classList.add('open');
    }

    hide() {
        this.modal.classList.remove('open');
    }

    async _executeExport() {
        const project = store.state.project;
        if (!project) return;

        const scope = this.modal.querySelector('input[name="export-scope"]:checked').value;
        const stripFlags = this.modal.querySelector('#export-chk-strip-flags').checked;
        const embedFonts = this.modal.querySelector('#export-chk-embed-fonts').checked;

        let pagesArg = 'all';
        if (scope === 'current') {
            pagesArg = [store.state.currentPageIndex];
        } else if (scope === 'selected') {
            pagesArg = project.page_order.filter(idx => project.pages[String(idx)] && project.pages[String(idx)].include_in_export);
            if (pagesArg.length === 0) {
                toast.error('No pages have the export checkbox selected.');
                return;
            }
        }

        const progressBox = this.modal.querySelector('#export-progress-container');
        const progressText = this.modal.querySelector('#export-progress-text');
        const resultBox = this.modal.querySelector('#export-result-box');
        const runBtn = this.modal.querySelector('#btn-run-export');

        progressBox.style.display = 'flex';
        progressText.textContent = this.exportType === 'docx' ? 'Building Word document & embedding fonts...' : 'Building PDF (trying Word COM -> LibreOffice -> Browser)...';
        resultBox.style.display = 'none';
        runBtn.disabled = true;

        try {
            let res;
            if (this.exportType === 'docx') {
                res = await api.exportDocx(project.id, {
                    pages: pagesArg,
                    merge: true,
                    strip_flags: stripFlags,
                    embed_fonts: embedFonts
                });
            } else {
                res = await api.exportPdf(project.id, {
                    pages: pagesArg,
                    merge: true,
                    strip_flags: stripFlags
                });
            }

            progressBox.style.display = 'none';
            resultBox.style.display = 'block';
            runBtn.disabled = false;

            let warnHtml = '';
            if (res.warnings && res.warnings.length > 0) {
                warnHtml = `<ul class="export-warnings-list">${res.warnings.map(w => `<li>${w}</li>`).join('')}</ul>`;
            }

            if (res.engine === 'browser') {
                window.open(res.url, '_blank');
                resultBox.innerHTML = `
                    <div class="export-success-message">
                        ✔ Document opened in Browser Print Preview!
                    </div>
                    <div style="margin-top: 10px;">
                        <a href="${res.url}" target="_blank" class="btn btn-outline btn-sm">🖨 Re-open Print View</a>
                    </div>
                    ${warnHtml}
                `;
                toast.info('Opened in print view.');
                return;
            }

            const engineLabel = res.engine ? `Engine: ${res.engine.toUpperCase()}` : '';

            resultBox.innerHTML = `
                <div class="export-success-message">
                    ✔ Document successfully generated! <small style="color: var(--text-secondary); margin-left: 8px;">${engineLabel}</small>
                </div>
                <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
                    <a href="${res.url}" class="btn btn-success btn-sm" download style="text-decoration: none;">
                        ⬇ Download ${res.file}
                    </a>
                    <button class="btn btn-outline btn-sm" id="btn-open-file" data-file="${res.file}">
                        📂 Open File
                    </button>
                    <button class="btn btn-outline btn-sm" id="btn-open-folder" data-file="${res.file}">
                        📁 Show in Folder
                    </button>
                </div>
                ${warnHtml}
            `;

            // Bind open file and folder buttons
            const openFileBtn = resultBox.querySelector('#btn-open-file');
            if (openFileBtn) {
                openFileBtn.addEventListener('click', async () => {
                    try {
                        await api.openExportedFile(res.file, false);
                        toast.info(`Opening ${res.file}...`);
                    } catch (e) {
                        toast.error(`Could not open file: ${e.message}`);
                    }
                });
            }

            const openFolderBtn = resultBox.querySelector('#btn-open-folder');
            if (openFolderBtn) {
                openFolderBtn.addEventListener('click', async () => {
                    try {
                        await api.openExportedFile(res.file, true);
                    } catch (e) {
                        toast.error(`Could not open folder: ${e.message}`);
                    }
                });
            }

            toast.success(`Export ready: ${res.file}`);

            // Automatically trigger download
            const a = document.createElement('a');
            a.href = res.url;
            a.download = res.file;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

        } catch (err) {
            progressBox.style.display = 'none';
            runBtn.disabled = false;
            resultBox.style.display = 'block';
            resultBox.innerHTML = `<div class="export-error-message">✖ Export failed: ${err.message}</div>`;
            toast.error(`Export failed: ${err.message}`);
        }
    }
}

export const exportDialog = new ExportDialog();
