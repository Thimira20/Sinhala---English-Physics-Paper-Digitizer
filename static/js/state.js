/**
 * Central State Store for Sinhala & English Physics Paper Digitizer.
 * Provides pub/sub reactive notifications when state changes.
 */

class StateStore {
    constructor() {
        this._state = {
            projectsList: [],
            project: null,
            currentPageIndex: 1,
            settings: null,
            queue: { pending: 0, running: 0 },
            saveStatus: 'saved', // 'saved' | 'saving' | 'offline'
            usage: { project_usd: 0.0, month_usd: 0.0 },
            activeDiagramId: null,
            isDrawingBox: false,
            equationErrorsCount: 0,
            originalMcqBlocks: new Map() // Key: `${pid}_${pageIdx}_${blockIdx}` -> originalText
        };
        this._listeners = new Map();
    }

    get state() {
        return this._state;
    }

    subscribe(key, callback) {
        if (!this._listeners.has(key)) {
            this._listeners.set(key, new Set());
        }
        this._listeners.get(key).add(callback);
        return () => this._listeners.get(key).delete(callback);
    }

    notify(key, value) {
        if (this._listeners.has(key)) {
            for (const cb of this._listeners.get(key)) {
                try {
                    cb(value, this._state);
                } catch (e) {
                    console.error(`Error in state listener for [${key}]:`, e);
                }
            }
        }
    }

    setProjectsList(list) {
        this._state.projectsList = list;
        this.notify('projectsList', list);
    }

    setProject(project) {
        this._state.project = project;
        this.notify('project', project);

        // Ensure current page index is valid
        if (project && project.page_order && project.page_order.length > 0) {
            if (!project.page_order.includes(this._state.currentPageIndex)) {
                this.setCurrentPage(project.page_order[0]);
            }
        }
    }

    setCurrentPage(pageIndex) {
        this._state.currentPageIndex = pageIndex;
        this._state.activeDiagramId = null;
        this.notify('currentPage', pageIndex);
    }

    getCurrentPage() {
        if (!this._state.project || !this._state.project.pages) return null;
        return this._state.project.pages[String(this._state.currentPageIndex)] || null;
    }

    updateCurrentPageField(field, value) {
        const page = this.getCurrentPage();
        if (page) {
            page[field] = value;
            this.notify('pageUpdate', { pageIndex: this._state.currentPageIndex, page });
        }
    }

    setSettings(settings) {
        this._state.settings = settings;
        this.notify('settings', settings);
    }

    setQueue(queue) {
        this._state.queue = queue;
        this.notify('queue', queue);
    }

    setSaveStatus(status) {
        this._state.saveStatus = status;
        this.notify('saveStatus', status);
    }

    setUsage(usage) {
        this._state.usage = usage;
        this.notify('usage', usage);
    }

    setActiveDiagramId(id) {
        this._state.activeDiagramId = id;
        this.notify('activeDiagramId', id);
    }

    setIsDrawingBox(val) {
        this._state.isDrawingBox = val;
        this.notify('isDrawingBox', val);
    }

    setEquationErrorsCount(count) {
        this._state.equationErrorsCount = count;
        this.notify('equationErrors', count);
    }

    // MCQ in-memory original text storage
    saveOriginalMcq(pid, pageIdx, blockIdx, originalText) {
        const key = `${pid}_${pageIdx}_${blockIdx}`;
        if (!this._state.originalMcqBlocks.has(key)) {
            this._state.originalMcqBlocks.set(key, originalText);
        }
    }

    getOriginalMcq(pid, pageIdx, blockIdx) {
        const key = `${pid}_${pageIdx}_${blockIdx}`;
        return this._state.originalMcqBlocks.get(key) || null;
    }
}

export const store = new StateStore();
