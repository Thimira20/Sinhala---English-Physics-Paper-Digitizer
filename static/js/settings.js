/**
 * Settings Modal and Cost / Usage Panel Component.
 * Supports API key testing, dynamic model listing, OCR parameters, typography,
 * branding blacklist chips, usage tracking, and cache clearing.
 */

import { api } from './api.js';
import { store } from './state.js';
import { toast } from './toast.js';

class SettingsModal {
    constructor() {
        this.modal = null;
        this.currentTab = 'api';
        this.settings = null;
    }

    init() {
        this._buildDom();
        this._bindEvents();
    }

    _buildDom() {
        const modalEl = document.createElement('div');
        modalEl.id = 'settings-modal';
        modalEl.className = 'modal-backdrop';
        modalEl.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-header">
                    <h3>⚙ Settings & Configuration</h3>
                    <button class="modal-close-btn" id="btn-close-settings">&times;</button>
                </div>
                <div class="modal-body settings-layout">
                    <div class="settings-sidebar">
                        <button class="settings-tab-btn active" data-tab="api">API & Models</button>
                        <button class="settings-tab-btn" data-tab="ocr">OCR & Queue</button>
                        <button class="settings-tab-btn" data-tab="crop">Crop Defaults</button>
                        <button class="settings-tab-btn" data-tab="fonts">Fonts & Layout</button>
                        <button class="settings-tab-btn" data-tab="math-mcq">Math & MCQ</button>
                        <button class="settings-tab-btn" data-tab="branding">Branding & Scrub</button>
                        <button class="settings-tab-btn" data-tab="usage">Usage & Spend</button>
                        <button class="settings-tab-btn" data-tab="maintenance">Maintenance</button>
                    </div>
                    <div class="settings-content">
                        <!-- API & Models -->
                        <div class="settings-tab-pane active" id="tab-api">
                            <h4>Gemini API Configuration</h4>
                            <div class="form-group">
                                <label for="setting-gemini-key">Gemini API Key</label>
                                <div class="input-with-button">
                                    <input type="password" id="setting-gemini-key" class="form-control" placeholder="AIzaSy..." />
                                    <button id="btn-test-key" class="btn btn-outline">Test Key</button>
                                </div>
                                <span class="help-text">Keys are stored locally in config.json and never logged.</span>
                            </div>
                            <div class="form-group">
                                <label for="setting-gemini-model">Accurate Model (Pro)</label>
                                <select id="setting-gemini-model" class="form-control"></select>
                            </div>
                            <div class="form-group">
                                <label for="setting-gemini-draft-model">Draft Model (Flash)</label>
                                <select id="setting-gemini-draft-model" class="form-control"></select>
                            </div>
                        </div>

                        <!-- OCR & Queue -->
                        <div class="settings-tab-pane" id="tab-ocr">
                            <h4>OCR Engine & Worker Concurrency</h4>
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label for="setting-rpm">Requests Per Minute (RPM)</label>
                                    <input type="number" id="setting-rpm" class="form-control" min="5" max="200" />
                                </div>
                                <div class="form-group col-6">
                                    <label for="setting-workers">Concurrent Workers</label>
                                    <input type="number" id="setting-workers" class="form-control" min="1" max="8" />
                                </div>
                            </div>
                            <div class="form-group">
                                <label for="setting-thinking-budget">Thinking Budget (tokens)</label>
                                <input type="number" id="setting-thinking-budget" class="form-control" min="0" max="8192" step="512" />
                                <span class="help-text">Set to 0 to disable thinking budget on models that do not support it.</span>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="setting-auto-deskew" />
                                    Enable automatic deskew on ingest
                                </label>
                            </div>
                        </div>

                        <!-- Crop Defaults -->
                        <div class="settings-tab-pane" id="tab-crop">
                            <h4>Default Page Crops</h4>
                            <p class="help-text">Applied automatically to uploaded pages unless individually overridden.</p>
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label for="setting-crop-top">Default Top Crop (%)</label>
                                    <input type="number" id="setting-crop-top" class="form-control" min="0" max="40" step="0.5" />
                                </div>
                                <div class="form-group col-6">
                                    <label for="setting-crop-bottom">Default Bottom Crop (%)</label>
                                    <input type="number" id="setting-crop-bottom" class="form-control" min="0" max="40" step="0.5" />
                                </div>
                            </div>
                        </div>

                        <!-- Fonts & Layout -->
                        <div class="settings-tab-pane" id="tab-fonts">
                            <h4>Typography & Document Styling</h4>
                            <div class="form-group">
                                <label for="setting-sinhala-font">Sinhala Font</label>
                                <input type="text" id="setting-sinhala-font" class="form-control" />
                            </div>
                            <div class="form-group">
                                <label for="setting-sinhala-fallback">Sinhala Fallback Font</label>
                                <input type="text" id="setting-sinhala-fallback" class="form-control" />
                            </div>
                            <div class="form-group">
                                <label for="setting-latin-font">Latin Font</label>
                                <input type="text" id="setting-latin-font" class="form-control" />
                            </div>
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label for="setting-font-size">Body Font Size (pt)</label>
                                    <input type="number" id="setting-font-size" class="form-control" min="8" max="18" step="0.5" />
                                </div>
                                <div class="form-group col-6">
                                    <label for="setting-line-spacing">Line Spacing</label>
                                    <input type="number" id="setting-line-spacing" class="form-control" min="1.0" max="2.0" step="0.05" />
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="setting-embed-fonts" />
                                    Embed fonts in DOCX (via Word COM)
                                </label>
                            </div>
                        </div>

                        <!-- Math & MCQ -->
                        <div class="settings-tab-pane" id="tab-math-mcq">
                            <h4>Physics Math & MCQ Formatting</h4>
                            <div class="form-group">
                                <label for="setting-math-mode">Sinhala Math Mode</label>
                                <select id="setting-math-mode" class="form-control">
                                    <option value="omml">Word OMML (Keep Sinhala inside Word equation)</option>
                                    <option value="outside">Outside (Move leading \\text{} out of equation)</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="setting-mcq-layout">Default MCQ Layout</label>
                                <select id="setting-mcq-layout" class="form-control">
                                    <option value="as_original">As original (Printed)</option>
                                    <option value="row5">1×5 row</option>
                                    <option value="grid32">3-column grid</option>
                                    <option value="grid2">2-column grid</option>
                                    <option value="list">Vertical list</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="setting-clean-mode">Default Diagram Cleaning Mode</label>
                                <select id="setting-clean-mode" class="form-control">
                                    <option value="normalize">Normalize (Remove shadow & clean background)</option>
                                    <option value="binary">High-contrast Binary</option>
                                    <option value="original">Original Crop</option>
                                </select>
                            </div>
                        </div>

                        <!-- Branding & Scrub -->
                        <div class="settings-tab-pane" id="tab-branding">
                            <h4>Branding Removal & Privacy Scrubbing</h4>
                            <div class="form-group">
                                <label>Branding Blacklist (Institutes / Teachers)</label>
                                <div class="chips-input-container" id="blacklist-chips-container">
                                    <div class="chips-list" id="blacklist-chips-list"></div>
                                    <input type="text" id="input-new-blacklist" placeholder="Type name & press Enter..." />
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="setting-scrub-phones" />
                                    Scrub Sri Lankan Phone Numbers (+94 / 07x)
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="setting-scrub-urls" />
                                    Scrub Web URLs and E-mail addresses
                                </label>
                            </div>
                        </div>

                        <!-- Usage & Spend -->
                        <div class="settings-tab-pane" id="tab-usage">
                            <h4>API Spend & Budget Warnings</h4>
                            <div class="usage-summary-card">
                                <div class="usage-item">
                                    <span class="usage-title">Current Project Spend</span>
                                    <span class="usage-val" id="usage-val-project">$0.00</span>
                                </div>
                                <div class="usage-item">
                                    <span class="usage-title">Current Month Spend</span>
                                    <span class="usage-val" id="usage-val-month">$0.00</span>
                                </div>
                            </div>
                            <div class="form-group" style="margin-top: 16px;">
                                <label for="setting-budget-warning">Monthly Budget Warning Threshold ($ USD)</label>
                                <input type="number" id="setting-budget-warning" class="form-control" min="1" max="500" step="1" />
                            </div>
                        </div>

                        <!-- Maintenance -->
                        <div class="settings-tab-pane" id="tab-maintenance">
                            <h4>Storage & Cache Management</h4>
                            <p>Disk cache stores previous Gemini OCR results to avoid redundant API billing.</p>
                            <div class="cache-stats-card">
                                <div>Cached pages: <strong id="cache-files-count">0</strong></div>
                                <div>Total disk size: <strong id="cache-size-mb">0 MB</strong></div>
                            </div>
                            <button id="btn-clear-cache" class="btn btn-danger" style="margin-top: 12px;">Clear Cache</button>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-ghost" id="btn-cancel-settings">Cancel</button>
                    <button class="btn btn-primary" id="btn-save-settings">Save Changes</button>
                </div>
            </div>
        `;

        document.body.appendChild(modalEl);
        this.modal = modalEl;
    }

    _bindEvents() {
        // Tab switching
        const tabs = this.modal.querySelectorAll('.settings-tab-btn');
        tabs.forEach(btn => {
            btn.addEventListener('click', () => {
                tabs.forEach(b => b.classList.remove('active'));
                this.modal.querySelectorAll('.settings-tab-pane').forEach(p => p.classList.remove('active'));

                btn.classList.add('active');
                const targetId = `tab-${btn.getAttribute('data-tab')}`;
                const pane = this.modal.querySelector(`#${targetId}`);
                if (pane) pane.classList.add('active');
            });
        });

        // Close handlers
        this.modal.querySelector('#btn-close-settings').addEventListener('click', () => this.hide());
        this.modal.querySelector('#btn-cancel-settings').addEventListener('click', () => this.hide());

        // Test API Key
        this.modal.querySelector('#btn-test-key').addEventListener('click', async () => {
            const rawKey = this.modal.querySelector('#setting-gemini-key').value.trim();
            const btn = this.modal.querySelector('#btn-test-key');
            btn.textContent = 'Testing...';
            btn.disabled = true;

            try {
                const res = await api.testKey({ gemini_api_key: rawKey });
                if (res.ok) {
                    toast.success(`API Key is valid! Found ${res.models.length} vision models.`);
                    this._populateModelDropdowns(res.models);
                } else {
                    toast.error(`Key test failed: ${res.error}`);
                }
            } catch (err) {
                toast.error(`Error testing key: ${err.message}`);
            } finally {
                btn.textContent = 'Test Key';
                btn.disabled = false;
            }
        });

        // Blacklist chips input
        const chipInput = this.modal.querySelector('#input-new-blacklist');
        chipInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const val = chipInput.value.trim();
                if (val) {
                    this._addBlacklistChip(val);
                    chipInput.value = '';
                }
            }
        });

        // Clear cache
        this.modal.querySelector('#btn-clear-cache').addEventListener('click', async () => {
            if (!confirm('Clear all cached Gemini responses? Subsequent OCR passes will re-bill API tokens.')) return;
            try {
                const res = await api.clearCache();
                toast.success(`Cleared ${res.cleared_files} cached files.`);
                this._loadCacheStats();
            } catch (err) {
                toast.error(`Failed to clear cache: ${err.message}`);
            }
        });

        // Save settings
        this.modal.querySelector('#btn-save-settings').addEventListener('click', () => this._save());
    }

    async show() {
        try {
            this.settings = await api.getSettings();
            store.setSettings(this.settings);
            this._populateForm(this.settings);
            this._loadUsage();
            this._loadCacheStats();
            this.modal.classList.add('open');
        } catch (err) {
            toast.error(`Failed to load settings: ${err.message}`);
        }
    }

    hide() {
        this.modal.classList.remove('open');
    }

    _populateForm(s) {
        this.modal.querySelector('#setting-gemini-key').value = s.gemini_api_key || '';
        this._populateModelDropdowns([s.gemini_model, s.gemini_draft_model, 'gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-2.5-pro', 'gemini-2.5-flash']);
        this.modal.querySelector('#setting-gemini-model').value = s.gemini_model;
        this.modal.querySelector('#setting-gemini-draft-model').value = s.gemini_draft_model;

        this.modal.querySelector('#setting-rpm').value = s.requests_per_minute;
        this.modal.querySelector('#setting-workers').value = s.max_concurrent_jobs;
        this.modal.querySelector('#setting-thinking-budget').value = s.thinking_budget;
        this.modal.querySelector('#setting-auto-deskew').checked = !!s.auto_deskew;

        this.modal.querySelector('#setting-crop-top').value = s.default_top_crop_percent;
        this.modal.querySelector('#setting-crop-bottom').value = s.default_bottom_crop_percent;

        this.modal.querySelector('#setting-sinhala-font').value = s.sinhala_font;
        this.modal.querySelector('#setting-sinhala-fallback').value = s.sinhala_fallback_font;
        this.modal.querySelector('#setting-latin-font').value = s.latin_font;
        this.modal.querySelector('#setting-font-size').value = s.body_font_size_pt;
        this.modal.querySelector('#setting-line-spacing').value = s.line_spacing;
        this.modal.querySelector('#setting-embed-fonts').checked = !!s.embed_fonts_in_docx;

        this.modal.querySelector('#setting-math-mode').value = s.sinhala_math_mode;
        this.modal.querySelector('#setting-mcq-layout').value = s.mcq_default_layout;
        this.modal.querySelector('#setting-clean-mode').value = s.diagram_clean_mode;

        this.modal.querySelector('#setting-scrub-phones').checked = !!s.scrub_phone_numbers;
        this.modal.querySelector('#setting-scrub-urls').checked = !!s.scrub_urls_emails;
        this.modal.querySelector('#setting-budget-warning').value = s.monthly_budget_warning_usd;

        // Populate chips
        const chipContainer = this.modal.querySelector('#blacklist-chips-list');
        chipContainer.innerHTML = '';
        for (const item of (s.branding_blacklist || [])) {
            this._addBlacklistChip(item);
        }
    }

    _populateModelDropdowns(models) {
        const unique = [...new Set(models)].filter(Boolean);
        const selAcc = this.modal.querySelector('#setting-gemini-model');
        const selDraft = this.modal.querySelector('#setting-gemini-draft-model');

        const curAcc = selAcc.value || this.settings?.gemini_model;
        const curDraft = selDraft.value || this.settings?.gemini_draft_model;

        selAcc.innerHTML = unique.map(m => `<option value="${m}">${m}</option>`).join('');
        selDraft.innerHTML = unique.map(m => `<option value="${m}">${m}</option>`).join('');

        if (curAcc && unique.includes(curAcc)) selAcc.value = curAcc;
        if (curDraft && unique.includes(curDraft)) selDraft.value = curDraft;
    }

    _addBlacklistChip(text) {
        const list = this.modal.querySelector('#blacklist-chips-list');
        const chip = document.createElement('div');
        chip.className = 'chip';
        chip.innerHTML = `
            <span>${text}</span>
            <button type="button" class="chip-remove">&times;</button>
        `;
        chip.querySelector('.chip-remove').addEventListener('click', () => chip.remove());
        list.appendChild(chip);
    }

    async _loadUsage() {
        const pid = store.state.project ? store.state.project.id : null;
        try {
            const usage = await api.getUsage(pid);
            store.setUsage(usage);
            this.modal.querySelector('#usage-val-project').textContent = `$${usage.project_usd.toFixed(4)}`;
            this.modal.querySelector('#usage-val-month').textContent = `$${usage.month_usd.toFixed(4)}`;
        } catch (err) {
            console.warn('Could not load usage:', err);
        }
    }

    async _loadCacheStats() {
        try {
            const stats = await api.getCacheStats();
            this.modal.querySelector('#cache-files-count').textContent = stats.count;
            this.modal.querySelector('#cache-size-mb').textContent = `${stats.size_mb} MB`;
        } catch (err) {
            console.warn('Could not load cache stats:', err);
        }
    }

    async _save() {
        const chips = [...this.modal.querySelectorAll('#blacklist-chips-list .chip span')].map(s => s.textContent.trim());

        const payload = {
            gemini_api_key: this.modal.querySelector('#setting-gemini-key').value.trim(),
            gemini_model: this.modal.querySelector('#setting-gemini-model').value,
            gemini_draft_model: this.modal.querySelector('#setting-gemini-draft-model').value,
            requests_per_minute: parseInt(this.modal.querySelector('#setting-rpm').value, 10),
            max_concurrent_jobs: parseInt(this.modal.querySelector('#setting-workers').value, 10),
            thinking_budget: parseInt(this.modal.querySelector('#setting-thinking-budget').value, 10),
            auto_deskew: this.modal.querySelector('#setting-auto-deskew').checked,
            default_top_crop_percent: parseFloat(this.modal.querySelector('#setting-crop-top').value),
            default_bottom_crop_percent: parseFloat(this.modal.querySelector('#setting-crop-bottom').value),
            sinhala_font: this.modal.querySelector('#setting-sinhala-font').value.trim(),
            sinhala_fallback_font: this.modal.querySelector('#setting-sinhala-fallback').value.trim(),
            latin_font: this.modal.querySelector('#setting-latin-font').value.trim(),
            body_font_size_pt: parseFloat(this.modal.querySelector('#setting-font-size').value),
            line_spacing: parseFloat(this.modal.querySelector('#setting-line-spacing').value),
            embed_fonts_in_docx: this.modal.querySelector('#setting-embed-fonts').checked,
            sinhala_math_mode: this.modal.querySelector('#setting-math-mode').value,
            mcq_default_layout: this.modal.querySelector('#setting-mcq-layout').value,
            diagram_clean_mode: this.modal.querySelector('#setting-clean-mode').value,
            branding_blacklist: chips,
            scrub_phone_numbers: this.modal.querySelector('#setting-scrub-phones').checked,
            scrub_urls_emails: this.modal.querySelector('#setting-scrub-urls').checked,
            monthly_budget_warning_usd: parseFloat(this.modal.querySelector('#setting-budget-warning').value)
        };

        try {
            const saved = await api.updateSettings(payload);
            store.setSettings(saved);
            toast.success('Settings saved successfully.');
            this.hide();
        } catch (err) {
            toast.error(`Failed to save settings: ${err.message}`);
        }
    }
}

export const settingsModal = new SettingsModal();
