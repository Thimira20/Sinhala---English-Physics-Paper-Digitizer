/**
 * API client module for Sinhala & English Physics Paper Digitizer.
 * Provides REST wrappers and SSE connection management with auto-reconnect.
 */

export class ApiClient {
    constructor() {
        this._eventSource = null;
        this._sseProjectId = null;
    }

    async _request(url, options = {}) {
        try {
            const res = await fetch(url, options);
            if (res.status === 204) {
                return null;
            }
            let data = {};
            try {
                data = await res.json();
            } catch (_) {}
            if (!res.ok) {
                const msg = data.detail || data.error || `Request failed with status ${res.status}`;
                if (res.status === 500) {
                    try {
                        const { toast } = await import('./toast.js');
                        toast.error(msg, 7000, {
                            actionLabel: 'See log',
                            onAction: () => {
                                fetch('/api/open', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ file: 'app.log' })
                                }).catch(() => {});
                            }
                        });
                    } catch (_) {}
                }
                throw new Error(msg);
            }
            return data;
        } catch (err) {
            console.error(`API Error on [${options.method || 'GET'} ${url}]:`, err);
            throw err;
        }
    }

    // --- Projects ---
    async getProjects() {
        return this._request('/api/projects');
    }

    async createProject(name) {
        return this._request('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
    }

    async getProject(pid) {
        return this._request(`/api/projects/${pid}`);
    }

    async updateProject(pid, data) {
        return this._request(`/api/projects/${pid}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    }

    async deleteProject(pid) {
        return this._request(`/api/projects/${pid}`, {
            method: 'DELETE'
        });
    }

    async uploadFiles(pid, files, onProgress = null) {
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }

        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `/api/projects/${pid}/upload`);

            if (xhr.upload && onProgress) {
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        const pct = Math.round((e.loaded / e.total) * 100);
                        onProgress(pct);
                    }
                };
            }

            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve({ ok: true });
                    }
                } else {
                    let errMsg = `Upload failed (${xhr.status})`;
                    try {
                        const d = JSON.parse(xhr.responseText);
                        if (d.detail) errMsg = d.detail;
                    } catch (_) {}
                    reject(new Error(errMsg));
                }
            };

            xhr.onerror = () => reject(new Error('Network error during file upload'));
            xhr.send(formData);
        });
    }

    // --- Pages ---
    async updatePage(pid, pageIndex, data) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    }

    async deletePage(pid, pageIndex) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}`, {
            method: 'DELETE'
        });
    }

    async suggestCrop(pid, pageIndex, apply = false) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/suggest-crop?apply=${apply}`, {
            method: 'POST'
        });
    }

    async fixPerspective(pid, pageIndex) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/perspective-fix`, {
            method: 'POST'
        });
    }

    async addEraseRegion(pid, pageIndex, boxPx) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/erase-regions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ box_px: boxPx })
        });
    }

    async deleteEraseRegion(pid, pageIndex, regionId) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/erase-regions/${regionId}`, {
            method: 'DELETE'
        });
    }

    // --- OCR ---
    async triggerOcr(pid, { pages = 'all', model = 'accurate', force = false, overwrite = false } = {}) {
        return this._request(`/api/projects/${pid}/ocr`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pages, model, force, overwrite })
        });
    }

    // --- Diagrams ---
    async saveDiagram(pid, pageIndex, data) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/diagrams`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    }

    async patchDiagram(pid, pageIndex, did, data) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/diagrams/${did}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    }

    async deleteDiagram(pid, pageIndex, did) {
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/diagrams/${did}`, {
            method: 'DELETE'
        });
    }

    async replaceDiagram(pid, pageIndex, did, file) {
        const formData = new FormData();
        formData.append('file', file);
        return this._request(`/api/projects/${pid}/pages/${pageIndex}/diagrams/${did}/replace`, {
            method: 'POST',
            body: formData
        });
    }

    // --- Export ---
    async exportDocx(pid, { pages = 'all', merge = true, strip_flags = true, embed_fonts = null } = {}) {
        return this._request(`/api/projects/${pid}/export/docx`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pages, merge, strip_flags, embed_fonts })
        });
    }

    async exportPdf(pid, { pages = 'all', merge = true, strip_flags = true } = {}) {
        return this._request(`/api/projects/${pid}/export/pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pages, merge, strip_flags })
        });
    }

    async openExportedFile(file, folder = false) {
        return this._request('/api/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file, folder })
        });
    }

    // --- Settings & Usage ---
    async getSettings() {
        return this._request('/api/settings');
    }

    async updateSettings(settings) {
        return this._request('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
    }

    async testKey(body = {}) {
        return this._request('/api/settings/test-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
    }

    async getUsage(projectId = null) {
        const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
        return this._request(`/api/usage${query}`);
    }

    async getCacheStats() {
        return this._request('/api/cache/stats');
    }

    async clearCache() {
        return this._request('/api/cache/clear', {
            method: 'POST'
        });
    }

    // --- SSE Event Streaming ---
    connectSSE(pid, onEvent, onError = null) {
        if (this._eventSource) {
            this._eventSource.close();
            this._eventSource = null;
        }

        this._sseProjectId = pid;
        const url = `/api/projects/${pid}/events`;
        const es = new EventSource(url);

        es.onmessage = (event) => {
            if (!event.data) return;
            try {
                const data = JSON.parse(event.data);
                if (onEvent) onEvent(data);
            } catch (err) {
                console.warn('Failed to parse SSE event data:', event.data, err);
            }
        };

        es.onerror = (err) => {
            if (onError) onError(err);
        };

        this._eventSource = es;
        return es;
    }

    disconnectSSE() {
        if (this._eventSource) {
            this._eventSource.close();
            this._eventSource = null;
            this._sseProjectId = null;
        }
    }
}

export const api = new ApiClient();
