/**
 * Source Viewer Component:
 * Canvas-based work image viewer with SVG overlay, pan/zoom, draggable crop lines,
 * diagram bounding boxes with 8 resize handles, and box drawing tool.
 */

import { store } from './state.js';
import { api } from './api.js';
import { toast } from './toast.js';

class SourceViewer {
    constructor() {
        this.container = null;
        this.canvas = null;
        this.ctx = null;
        this.svg = null;

        // Image state
        this.img = new Image();
        this.imgLoaded = false;
        this.imgNaturalWidth = 0;
        this.imgNaturalHeight = 0;

        // Transform state (pan / zoom)
        this.scale = 1.0;
        this.translateX = 0;
        this.translateY = 0;
        this.isPanning = false;
        this.panStartX = 0;
        this.panStartY = 0;

        // Interactive tool state
        this.tool = 'select'; // 'select' | 'draw_box' | 'erase'
        this.isDrawingBox = false;
        this.isDrawingErase = false;
        this.drawStartPoint = null;

        // Dragging box or handle state
        this.draggingBoxId = null;
        this.draggingHandle = null; // null | 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'move'
        this.dragStartMouse = null;
        this.dragInitialBox = null;

        // Draggable Crop lines
        this.draggingCrop = null; // null | 'top' | 'bottom'
        this.cropSaveTimeout = null;

        // Scope toggle for crop: 'page' | 'all'
        this.cropScope = 'page';

        this._onBoxCreated = null;
        this._onBoxDeleted = null;
        this._onBoxSelected = null;
    }

    init(containerEl, { onBoxCreated, onBoxDeleted, onBoxSelected } = {}) {
        this.container = containerEl;
        this._onBoxCreated = onBoxCreated;
        this._onBoxDeleted = onBoxDeleted;
        this._onBoxSelected = onBoxSelected;

        this._buildDom();
        this._bindEvents();

        // Subscribe to store updates
        store.subscribe('currentPage', () => this.loadCurrentPage());
        store.subscribe('pageUpdate', () => this.render());
    }

    _buildDom() {
        this.container.innerHTML = `
            <div class="viewer-toolbar">
                <div class="viewer-tools-left">
                    <button id="btn-draw-box" class="btn btn-sm btn-outline" title="Draw a new diagram box (inserts tag into editor)">✚ Draw Box</button>
                    <button id="btn-erase-tool" class="btn btn-sm btn-outline" title="Erase Region (Redact logo/watermark before OCR)">🧹 Erase</button>
                    <button id="btn-auto-crop" class="btn btn-sm btn-ghost" title="Auto-detect header & footer crop lines using OpenCV">Auto Crop</button>
                    <button id="btn-perspective" class="btn btn-sm btn-ghost" title="Perspective Fix: Unwarp phone photo to 2D rectangle">📐 Unwarp</button>
                    <button id="btn-fit-view" class="btn btn-sm btn-ghost" title="Fit to screen">Fit</button>
                    <button id="btn-zoom-out" class="btn btn-sm btn-icon" title="Zoom out">−</button>
                    <span id="zoom-level-text" class="zoom-level">100%</span>
                    <button id="btn-zoom-in" class="btn btn-sm btn-icon" title="Zoom in">+</button>
                    <span id="viewer-page-error" class="viewer-page-error" style="display:none; color: var(--error); font-size: 0.75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px; margin-left: 8px;" title=""></span>
                </div>
                <div class="viewer-tools-right">
                    <label class="toolbar-checkbox" title="Apply deskew filter to source image">
                        <input type="checkbox" id="chk-viewer-deskew"> Deskew
                    </label>
                    <div class="crop-scope-selector" title="Crop applies to:">
                        <select id="sel-crop-scope" class="select-sm">
                            <option value="page">Crop: This page</option>
                            <option value="all">Crop: All pages</option>
                        </select>
                    </div>
                </div>
            </div>
            <div class="viewer-viewport" id="viewer-viewport">
                <canvas id="viewer-canvas" class="viewer-canvas"></canvas>
                <svg id="viewer-svg" class="viewer-svg"></svg>
            </div>
        `;

        this.viewport = this.container.querySelector('#viewer-viewport');
        this.canvas = this.container.querySelector('#viewer-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.svg = this.container.querySelector('#viewer-svg');
        this.zoomText = this.container.querySelector('#zoom-level-text');
        this.btnDrawBox = this.container.querySelector('#btn-draw-box');
        this.btnEraseTool = this.container.querySelector('#btn-erase-tool');
        this.btnAutoCrop = this.container.querySelector('#btn-auto-crop');
        this.btnPerspective = this.container.querySelector('#btn-perspective');
        this.chkDeskew = this.container.querySelector('#chk-viewer-deskew');
        this.selCropScope = this.container.querySelector('#sel-crop-scope');
    }

    _bindEvents() {
        // Zoom buttons
        this.container.querySelector('#btn-zoom-in').addEventListener('click', () => this.zoom(1.2));
        this.container.querySelector('#btn-zoom-out').addEventListener('click', () => this.zoom(0.8));
        this.container.querySelector('#btn-fit-view').addEventListener('click', () => this.fitView());

        // Box draw toggle
        this.btnDrawBox.addEventListener('click', () => {
            this.tool = (this.tool === 'draw_box') ? 'select' : 'draw_box';
            this.btnDrawBox.classList.toggle('active', this.tool === 'draw_box');
            this.btnEraseTool.classList.remove('active');
            this.svg.classList.toggle('crosshair-mode', this.tool === 'draw_box');
        });

        // Erase tool toggle
        this.btnEraseTool.addEventListener('click', () => {
            this.tool = (this.tool === 'erase') ? 'select' : 'erase';
            this.btnEraseTool.classList.toggle('active', this.tool === 'erase');
            this.btnDrawBox.classList.remove('active');
            this.svg.classList.toggle('crosshair-mode', this.tool === 'erase');
        });

        // Auto Crop button
        this.btnAutoCrop.addEventListener('click', async () => {
            const page = store.getCurrentPage();
            const project = store.state.project;
            if (!page || !project) return;
            try {
                this.btnAutoCrop.disabled = true;
                this.btnAutoCrop.textContent = 'Detecting...';
                const res = await api.suggestCrop(project.id, page.index, true);
                if (res.detected) {
                    page.crop.top_pct = res.top_pct;
                    page.crop.bottom_pct = res.bottom_pct;
                    page.crop.override = true;
                    this.render();
                    toast.success(`Crop margins detected: Top ${res.top_pct}%, Bottom ${res.bottom_pct}%`);
                } else {
                    toast.info('No distinct horizontal rule lines found in top/bottom 15%.');
                }
            } catch (err) {
                toast.error(`Auto-crop detection failed: ${err.message}`);
            } finally {
                this.btnAutoCrop.disabled = false;
                this.btnAutoCrop.textContent = 'Auto Crop';
            }
        });

        // Perspective button
        this.btnPerspective.addEventListener('click', async () => {
            const page = store.getCurrentPage();
            const project = store.state.project;
            if (!page || !project) return;
            try {
                this.btnPerspective.disabled = true;
                this.btnPerspective.textContent = 'Unwarping...';
                const res = await api.fixPerspective(project.id, page.index);
                if (res.success) {
                    page.width = res.width;
                    page.height = res.height;
                    toast.success('Perspective corrected successfully!');
                    this.loadCurrentPage();
                } else {
                    toast.warning(res.message || 'Could not detect 4 document corners.');
                }
            } catch (err) {
                toast.error(`Perspective correction failed: ${err.message}`);
            } finally {
                this.btnPerspective.disabled = false;
                this.btnPerspective.textContent = '📐 Unwarp';
            }
        });

        // Deskew toggle
        this.chkDeskew.addEventListener('change', async () => {
            const page = store.getCurrentPage();
            const project = store.state.project;
            if (!page || !project) return;
            const checked = this.chkDeskew.checked;
            page.deskew = checked;
            try {
                await api.updatePage(project.id, page.index, { deskew: checked });
                toast.info(`Deskew ${checked ? 'enabled' : 'disabled'}`);
            } catch (err) {
                toast.error(`Failed to update deskew: ${err.message}`);
            }
        });

        this.selCropScope.addEventListener('change', () => {
            this.cropScope = this.selCropScope.value;
        });

        // Wheel zoom centered on cursor
        this.viewport.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
            this.zoomAtPoint(zoomFactor, e.clientX, e.clientY);
        }, { passive: false });

        // Pan and interact with overlay
        this.viewport.addEventListener('mousedown', (e) => this._onMouseDown(e));
        window.addEventListener('mousemove', (e) => this._onMouseMove(e));
        window.addEventListener('mouseup', (e) => this._onMouseUp(e));

        // Space key pan tracking
        this.spaceDown = false;
        window.addEventListener('keydown', (e) => {
            if (e.key === ' ' && !this._isTypingInInput(e)) {
                this.spaceDown = true;
                if (this.viewport && !this.isPanning) this.viewport.style.cursor = 'grab';
            }
        });
        window.addEventListener('keyup', (e) => {
            if (e.key === ' ') {
                this.spaceDown = false;
                if (this.viewport && !this.isPanning) this.viewport.style.cursor = 'default';
            }
        });

        // Resize observer
        const ro = new ResizeObserver(() => {
            if (this.imgLoaded) this.render();
        });
        ro.observe(this.viewport);

        // Keyboard shortcuts: Delete box
        window.addEventListener('keydown', (e) => {
            if ((e.key === 'Delete' || e.key === 'Backspace') && !this._isTypingInInput(e)) {
                if (store.state.activeDiagramId) {
                    this._deleteActiveBox();
                }
            }
        });
    }

    _isTypingInInput(e) {
        const tag = (e.target.tagName || '').toLowerCase();
        return tag === 'input' || tag === 'textarea' || e.target.isContentEditable || (e.target.closest && e.target.closest('.CodeMirror'));
    }

    loadCurrentPage() {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) {
            this._clear();
            return;
        }

        this.chkDeskew.checked = !!page.deskew;
        this._updatePageError(page);

        const workUrl = `/files/${project.id}/${page.work_file}?v=${Date.now()}`;
        this.imgLoaded = false;
        this.img.src = workUrl;
        this.img.onload = () => {
            this.imgLoaded = true;
            this.imgNaturalWidth = this.img.naturalWidth;
            this.imgNaturalHeight = this.img.naturalHeight;
            this.fitView();
        };
        this.img.onerror = () => {
            console.error('Failed to load image:', workUrl);
            this._clear();
        };
    }

    _clear() {
        this.imgLoaded = false;
        if (this.ctx && this.canvas) {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
        if (this.svg) {
            this.svg.innerHTML = '';
        }
        this._updatePageError(null);
    }

    _updatePageError(page) {
        const errEl = this.container ? this.container.querySelector('#viewer-page-error') : null;
        if (!errEl) return;
        if (page && page.status === 'error' && page.error) {
            errEl.style.display = 'inline-block';
            errEl.textContent = `⚠ ${page.error}`;
            errEl.title = page.error;
        } else {
            errEl.style.display = 'none';
            errEl.textContent = '';
            errEl.title = '';
        }
    }

    fitView() {
        if (!this.imgLoaded || !this.viewport) return;
        const vpRect = this.viewport.getBoundingClientRect();
        if (vpRect.width <= 0 || vpRect.height <= 0) return;

        const pad = 24;
        const availW = vpRect.width - pad * 2;
        const availH = vpRect.height - pad * 2;

        const scaleW = availW / this.imgNaturalWidth;
        const scaleH = availH / this.imgNaturalHeight;
        this.scale = Math.min(scaleW, scaleH, 1.5);

        this.translateX = (vpRect.width - this.imgNaturalWidth * this.scale) / 2;
        this.translateY = (vpRect.height - this.imgNaturalHeight * this.scale) / 2;

        this.render();
    }

    zoom(factor) {
        if (!this.viewport) return;
        const rect = this.viewport.getBoundingClientRect();
        this.zoomAtPoint(factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
    }

    zoomAtPoint(factor, clientX, clientY) {
        const vpRect = this.viewport.getBoundingClientRect();
        const mouseX = clientX - vpRect.left;
        const mouseY = clientY - vpRect.top;

        const newScale = Math.min(Math.max(this.scale * factor, 0.15), 5.0);
        const actualFactor = newScale / this.scale;

        this.translateX = mouseX - (mouseX - this.translateX) * actualFactor;
        this.translateY = mouseY - (mouseY - this.translateY) * actualFactor;
        this.scale = newScale;

        this.render();
    }

    render() {
        if (!this.imgLoaded || !this.canvas || !this.viewport) return;

        const vpRect = this.viewport.getBoundingClientRect();
        this.canvas.width = vpRect.width;
        this.canvas.height = vpRect.height;

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw work image
        const renderW = this.imgNaturalWidth * this.scale;
        const renderH = this.imgNaturalHeight * this.scale;

        this.ctx.drawImage(
            this.img,
            this.translateX,
            this.translateY,
            renderW,
            renderH
        );

        if (this.zoomText) {
            this.zoomText.textContent = `${Math.round(this.scale * 100)}%`;
        }

        this._updatePageError(store.getCurrentPage());

        // Render SVG overlay (crop lines, veils, diagram boxes)
        this._renderOverlay();
    }

    _renderOverlay() {
        if (!this.svg) return;
        this.svg.setAttribute('viewBox', `0 0 ${this.canvas.width} ${this.canvas.height}`);
        this.svg.innerHTML = '';

        const page = store.getCurrentPage();
        if (!page) return;

        const crop = page.crop || { top_pct: 0.0, bottom_pct: 6.5 };
        const renderX = this.translateX;
        const renderY = this.translateY;
        const renderW = this.imgNaturalWidth * this.scale;
        const renderH = this.imgNaturalHeight * this.scale;

        const topCropY = renderY + (renderH * crop.top_pct / 100);
        const bottomCropY = renderY + renderH - (renderH * crop.bottom_pct / 100);

        // 1. Veils over cropped areas
        const veilTop = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        veilTop.setAttribute('x', renderX);
        veilTop.setAttribute('y', renderY);
        veilTop.setAttribute('width', renderW);
        veilTop.setAttribute('height', Math.max(0, topCropY - renderY));
        veilTop.setAttribute('class', 'crop-veil');
        this.svg.appendChild(veilTop);

        const veilBottom = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        veilBottom.setAttribute('x', renderX);
        veilBottom.setAttribute('y', bottomCropY);
        veilBottom.setAttribute('width', renderW);
        veilBottom.setAttribute('height', Math.max(0, renderY + renderH - bottomCropY));
        veilBottom.setAttribute('class', 'crop-veil');
        this.svg.appendChild(veilBottom);

        // 2. Crop Lines (horizontal draggable lines)
        this._createCropLine(topCropY, renderX, renderW, 'top', `Top: ${crop.top_pct.toFixed(1)}%`);
        this._createCropLine(bottomCropY, renderX, renderW, 'bottom', `Bottom: ${crop.bottom_pct.toFixed(1)}%`);

        // 3. Diagram bounding boxes
        if (page.diagrams) {
            for (const diag of page.diagrams) {
                this._renderDiagramBox(diag, renderX, renderY);
            }
        }

        // 4. Erase regions
        if (page.erase_regions) {
            for (const region of page.erase_regions) {
                this._renderEraseRegion(region, renderX, renderY);
            }
        }
    }

    _createCropLine(yPos, xPos, width, type, labelText) {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `crop-line-group crop-${type}`);
        g.setAttribute('data-crop-type', type);

        // Wide hit area for easy grabbing
        const hitLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        hitLine.setAttribute('x1', xPos);
        hitLine.setAttribute('y1', yPos);
        hitLine.setAttribute('x2', xPos + width);
        hitLine.setAttribute('y2', yPos);
        hitLine.setAttribute('class', 'crop-hit-line');
        g.appendChild(hitLine);

        // Visible dashed line
        const visLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        visLine.setAttribute('x1', xPos);
        visLine.setAttribute('y1', yPos);
        visLine.setAttribute('x2', xPos + width);
        visLine.setAttribute('y2', yPos);
        visLine.setAttribute('class', 'crop-visible-line');
        g.appendChild(visLine);

        // Label pill
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', xPos + 12);
        text.setAttribute('y', type === 'top' ? yPos - 6 : yPos + 16);
        text.setAttribute('class', 'crop-line-label');
        text.textContent = labelText;
        g.appendChild(text);

        this.svg.appendChild(g);
    }

    _renderDiagramBox(diag, renderX, renderY) {
        const [ymin, xmin, ymax, xmax] = diag.box_px;
        const boxX = renderX + xmin * this.scale;
        const boxY = renderY + ymin * this.scale;
        const boxW = (xmax - xmin) * this.scale;
        const boxH = (ymax - ymin) * this.scale;

        const isActive = (store.state.activeDiagramId === diag.id);

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `diagram-box-group ${isActive ? 'active' : ''}`);
        g.setAttribute('data-did', diag.id);

        // Box rectangle
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', boxX);
        rect.setAttribute('y', boxY);
        rect.setAttribute('width', boxW);
        rect.setAttribute('height', boxH);
        rect.setAttribute('class', 'diagram-box-rect');
        g.appendChild(rect);

        // Label chip on top-left of box
        const labelText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        labelText.setAttribute('x', boxX + 6);
        labelText.setAttribute('y', Math.max(16, boxY - 6));
        labelText.setAttribute('class', 'diagram-box-label');
        labelText.textContent = `${diag.label || diag.id} (${diag.id})`;
        g.appendChild(labelText);

        // If active, render 8 resize handles
        if (isActive) {
            const handles = [
                { id: 'nw', x: boxX, y: boxY },
                { id: 'n',  x: boxX + boxW / 2, y: boxY },
                { id: 'ne', x: boxX + boxW, y: boxY },
                { id: 'e',  x: boxX + boxW, y: boxY + boxH / 2 },
                { id: 'se', x: boxX + boxW, y: boxY + boxH },
                { id: 's',  x: boxX + boxW / 2, y: boxY + boxH },
                { id: 'sw', x: boxX, y: boxY + boxH },
                { id: 'w',  x: boxX, y: boxY + boxH / 2 }
            ];

            const hSize = 8;
            for (const h of handles) {
                const handleRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                handleRect.setAttribute('x', h.x - hSize / 2);
                handleRect.setAttribute('y', h.y - hSize / 2);
                handleRect.setAttribute('width', hSize);
                handleRect.setAttribute('height', hSize);
                handleRect.setAttribute('class', `diagram-resize-handle handle-${h.id}`);
                handleRect.setAttribute('data-handle', h.id);
                handleRect.setAttribute('data-did', diag.id);
                g.appendChild(handleRect);
            }
        }

        this.svg.appendChild(g);
    }

    _renderEraseRegion(region, renderX, renderY) {
        const [ymin, xmin, ymax, xmax] = region.box_px;
        const boxX = renderX + xmin * this.scale;
        const boxY = renderY + ymin * this.scale;
        const boxW = (xmax - xmin) * this.scale;
        const boxH = (ymax - ymin) * this.scale;

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', 'erase-box-group');
        g.setAttribute('data-eid', region.id);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', boxX);
        rect.setAttribute('y', boxY);
        rect.setAttribute('width', boxW);
        rect.setAttribute('height', boxH);
        rect.setAttribute('class', 'erase-box-rect');
        g.appendChild(rect);

        const labelText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        labelText.setAttribute('x', boxX + 6);
        labelText.setAttribute('y', Math.max(16, boxY - 6));
        labelText.setAttribute('class', 'erase-box-label');
        labelText.textContent = `🧹 ${region.id}`;
        g.appendChild(labelText);

        const delBtn = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        delBtn.setAttribute('x', boxX + Math.max(20, boxW - 14));
        delBtn.setAttribute('y', boxY + Math.min(boxH - 4, 16));
        delBtn.setAttribute('class', 'erase-delete-btn');
        delBtn.setAttribute('data-eid', region.id);
        delBtn.textContent = '✖';
        g.appendChild(delBtn);

        this.svg.appendChild(g);
    }

    _clientToWorkPixels(clientX, clientY) {
        const vpRect = this.viewport.getBoundingClientRect();
        const viewX = clientX - vpRect.left;
        const viewY = clientY - vpRect.top;

        const workX = Math.round((viewX - this.translateX) / this.scale);
        const workY = Math.round((viewY - this.translateY) / this.scale);

        return {
            x: Math.max(0, Math.min(this.imgNaturalWidth, workX)),
            y: Math.max(0, Math.min(this.imgNaturalHeight, workY))
        };
    }

    _onMouseDown(e) {
        if (!this.imgLoaded) return;

        // Space + drag or Middle mouse button -> Pan
        if (e.button === 1 || this.spaceDown || (e.button === 0 && e.altKey)) {
            this.isPanning = true;
            this.panStartX = e.clientX - this.translateX;
            this.panStartY = e.clientY - this.translateY;
            this.viewport.style.cursor = 'grabbing';
            e.preventDefault();
            return;
        }

        if (e.button !== 0) return; // Only primary button

        // 1. Tool: Draw Box Mode
        if (this.tool === 'draw_box') {
            const pt = this._clientToWorkPixels(e.clientX, e.clientY);
            this.isDrawingBox = true;
            this.drawStartPoint = pt;
            e.preventDefault();
            return;
        }

        // 1b. Tool: Erase Tool Mode
        if (this.tool === 'erase') {
            const pt = this._clientToWorkPixels(e.clientX, e.clientY);
            this.isDrawingErase = true;
            this.drawStartPoint = pt;
            e.preventDefault();
            return;
        }

        // Check if clicked delete on an erase region
        const delEraseBtn = e.target.closest('.erase-delete-btn');
        if (delEraseBtn) {
            const eid = delEraseBtn.getAttribute('data-eid');
            this._deleteEraseRegion(eid);
            e.preventDefault();
            e.stopPropagation();
            return;
        }

        // 2. Check if clicked on a resize handle
        const handleEl = e.target.closest('.diagram-resize-handle');
        if (handleEl) {
            const did = handleEl.getAttribute('data-did');
            const handleId = handleEl.getAttribute('data-handle');
            this._startBoxDrag(did, handleId, e);
            e.preventDefault();
            return;
        }

        // 3. Check if clicked inside a diagram box
        const boxEl = e.target.closest('.diagram-box-group');
        if (boxEl) {
            const did = boxEl.getAttribute('data-did');
            store.setActiveDiagramId(did);
            if (this._onBoxSelected) this._onBoxSelected(did);
            this._startBoxDrag(did, 'move', e);
            e.preventDefault();
            return;
        }

        // 4. Check if clicked on crop line
        const cropEl = e.target.closest('.crop-line-group');
        if (cropEl) {
            const type = cropEl.getAttribute('data-crop-type');
            this.draggingCrop = type;
            e.preventDefault();
            return;
        }

        // Click on background -> deselect active box or pan
        store.setActiveDiagramId(null);
        this.render();

        // Default click-drag pans if not drawing
        this.isPanning = true;
        this.panStartX = e.clientX - this.translateX;
        this.panStartY = e.clientY - this.translateY;
        this.viewport.style.cursor = 'grabbing';
    }

    _startBoxDrag(did, handleId, e) {
        const page = store.getCurrentPage();
        if (!page) return;
        const diag = (page.diagrams || []).find(d => d.id === did);
        if (!diag) return;

        this.draggingBoxId = did;
        this.draggingHandle = handleId;
        this.dragStartMouse = this._clientToWorkPixels(e.clientX, e.clientY);
        this.dragInitialBox = [...diag.box_px]; // [ymin, xmin, ymax, xmax]
    }

    _onMouseMove(e) {
        if (this.isPanning) {
            this.translateX = e.clientX - this.panStartX;
            this.translateY = e.clientY - this.panStartY;
            this.render();
            return;
        }

        // Crop line dragging
        if (this.draggingCrop) {
            const pt = this._clientToWorkPixels(e.clientX, e.clientY);
            const page = store.getCurrentPage();
            if (!page) return;

            if (this.draggingCrop === 'top') {
                const pct = Math.max(0, Math.min(45, (pt.y / this.imgNaturalHeight) * 100));
                page.crop.top_pct = Math.round(pct * 10) / 10;
            } else if (this.draggingCrop === 'bottom') {
                const fromBottom = this.imgNaturalHeight - pt.y;
                const pct = Math.max(0, Math.min(45, (fromBottom / this.imgNaturalHeight) * 100));
                page.crop.bottom_pct = Math.round(pct * 10) / 10;
            }

            this.render();
            this._debounceSaveCrop();
            return;
        }

        // Draw Box Mode
        if (this.isDrawingBox && this.drawStartPoint) {
            const cur = this._clientToWorkPixels(e.clientX, e.clientY);
            this._drawTempBox(this.drawStartPoint, cur);
            return;
        }

        // Draw Erase Box Mode
        if (this.isDrawingErase && this.drawStartPoint) {
            const cur = this._clientToWorkPixels(e.clientX, e.clientY);
            this._drawTempEraseBox(this.drawStartPoint, cur);
            return;
        }

        // Box Drag / Resize
        if (this.draggingBoxId && this.dragInitialBox) {
            const cur = this._clientToWorkPixels(e.clientX, e.clientY);
            const dx = cur.x - this.dragStartMouse.x;
            const dy = cur.y - this.dragStartMouse.y;

            let [ymin, xmin, ymax, xmax] = this.dragInitialBox;

            if (this.draggingHandle === 'move') {
                const boxW = xmax - xmin;
                const boxH = ymax - ymin;
                xmin = Math.max(0, Math.min(this.imgNaturalWidth - boxW, xmin + dx));
                ymin = Math.max(0, Math.min(this.imgNaturalHeight - boxH, ymin + dy));
                xmax = xmin + boxW;
                ymax = ymin + boxH;
            } else {
                // Resize via handles
                if (this.draggingHandle.includes('w')) xmin = Math.min(xmax - 20, Math.max(0, xmin + dx));
                if (this.draggingHandle.includes('e')) xmax = Math.max(xmin + 20, Math.min(this.imgNaturalWidth, xmax + dx));
                if (this.draggingHandle.includes('n')) ymin = Math.min(ymax - 20, Math.max(0, ymin + dy));
                if (this.draggingHandle.includes('s')) ymax = Math.max(ymin + 20, Math.min(this.imgNaturalHeight, ymax + dy));
            }

            const page = store.getCurrentPage();
            const diag = (page.diagrams || []).find(d => d.id === this.draggingBoxId);
            if (diag) {
                diag.box_px = [Math.round(ymin), Math.round(xmin), Math.round(ymax), Math.round(xmax)];
                this.render();
            }
        }
    }

    _drawTempBox(p1, p2) {
        let tempEl = this.svg.querySelector('#temp-drawn-box');
        if (!tempEl) {
            tempEl = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            tempEl.id = 'temp-drawn-box';
            tempEl.setAttribute('class', 'diagram-temp-box');
            this.svg.appendChild(tempEl);
        }

        const xmin = Math.min(p1.x, p2.x);
        const xmax = Math.max(p1.x, p2.x);
        const ymin = Math.min(p1.y, p2.y);
        const ymax = Math.max(p1.y, p2.y);

        tempEl.setAttribute('x', this.translateX + xmin * this.scale);
        tempEl.setAttribute('y', this.translateY + ymin * this.scale);
        tempEl.setAttribute('width', (xmax - xmin) * this.scale);
        tempEl.setAttribute('height', (ymax - ymin) * this.scale);
    }

    _drawTempEraseBox(p1, p2) {
        let tempEl = this.svg.querySelector('#temp-drawn-erase-box');
        if (!tempEl) {
            tempEl = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            tempEl.id = 'temp-drawn-erase-box';
            tempEl.setAttribute('class', 'erase-temp-box');
            this.svg.appendChild(tempEl);
        }

        const xmin = Math.min(p1.x, p2.x);
        const xmax = Math.max(p1.x, p2.x);
        const ymin = Math.min(p1.y, p2.y);
        const ymax = Math.max(p1.y, p2.y);

        tempEl.setAttribute('x', this.translateX + xmin * this.scale);
        tempEl.setAttribute('y', this.translateY + ymin * this.scale);
        tempEl.setAttribute('width', (xmax - xmin) * this.scale);
        tempEl.setAttribute('height', (ymax - ymin) * this.scale);
    }

    async _onMouseUp(e) {
        if (this.isPanning) {
            this.isPanning = false;
            if (this.viewport) this.viewport.style.cursor = this.spaceDown ? 'grab' : 'default';
        }

        if (this.draggingCrop) {
            this.draggingCrop = null;
        }

        // Complete drawing a new diagram box
        if (this.isDrawingBox && this.drawStartPoint) {
            this.isDrawingBox = false;
            const tempEl = this.svg.querySelector('#temp-drawn-box');
            if (tempEl) tempEl.remove();

            const p2 = this._clientToWorkPixels(e.clientX, e.clientY);
            const xmin = Math.min(this.drawStartPoint.x, p2.x);
            const xmax = Math.max(this.drawStartPoint.x, p2.x);
            const ymin = Math.min(this.drawStartPoint.y, p2.y);
            const ymax = Math.max(this.drawStartPoint.y, p2.y);

            // Minimum box size threshold (15px)
            if ((xmax - xmin) > 15 && (ymax - ymin) > 15) {
                await this._createNewBox([ymin, xmin, ymax, xmax]);
            }

            this.tool = 'select';
            this.btnDrawBox.classList.remove('active');
            this.svg.classList.remove('crosshair-mode');
            this.drawStartPoint = null;
            return;
        }

        // Complete drawing an erase region
        if (this.isDrawingErase && this.drawStartPoint) {
            this.isDrawingErase = false;
            const tempEl = this.svg.querySelector('#temp-drawn-erase-box');
            if (tempEl) tempEl.remove();

            const p2 = this._clientToWorkPixels(e.clientX, e.clientY);
            const xmin = Math.min(this.drawStartPoint.x, p2.x);
            const xmax = Math.max(this.drawStartPoint.x, p2.x);
            const ymin = Math.min(this.drawStartPoint.y, p2.y);
            const ymax = Math.max(this.drawStartPoint.y, p2.y);

            if ((xmax - xmin) > 15 && (ymax - ymin) > 15) {
                await this._addEraseRegion([Math.round(ymin), Math.round(xmin), Math.round(ymax), Math.round(xmax)]);
            }

            this.tool = 'select';
            this.btnEraseTool.classList.remove('active');
            this.svg.classList.remove('crosshair-mode');
            this.drawStartPoint = null;
            return;
        }

        // Complete dragging or resizing box -> send recrop to server
        if (this.draggingBoxId) {
            const did = this.draggingBoxId;
            this.draggingBoxId = null;
            this.draggingHandle = null;
            this.dragStartMouse = null;
            this.dragInitialBox = null;

            await this._recropBox(did);
        }
    }

    async _addEraseRegion(boxPx) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;
        try {
            const reg = await api.addEraseRegion(project.id, page.index, boxPx);
            if (!page.erase_regions) page.erase_regions = [];
            page.erase_regions.push(reg);
            this.render();
            toast.success(`Added erase region ${reg.id} (will be redacted before OCR)`);
        } catch (err) {
            toast.error(`Failed to add erase region: ${err.message}`);
        }
    }

    async _deleteEraseRegion(eid) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;
        try {
            await api.deleteEraseRegion(project.id, page.index, eid);
            page.erase_regions = (page.erase_regions || []).filter(r => r.id !== eid);
            this.render();
            toast.info(`Deleted erase region ${eid}`);
        } catch (err) {
            toast.error(`Failed to delete erase region: ${err.message}`);
        }
    }

    async _createNewBox(boxPx) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        try {
            const diag = await api.saveDiagram(project.id, page.index, {
                box_px: boxPx
            });

            // Update local state
            const existingIdx = (page.diagrams || []).findIndex(d => d.id === diag.id);
            if (existingIdx >= 0) {
                page.diagrams[existingIdx] = diag;
            } else {
                page.diagrams.push(diag);
            }

            store.setActiveDiagramId(diag.id);
            this.render();

            if (this._onBoxCreated) {
                this._onBoxCreated(diag);
            }

            toast.success(`Created diagram ${diag.id}`);
        } catch (err) {
            toast.error(`Failed to create box: ${err.message}`);
        }
    }

    async _recropBox(did) {
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        const diag = (page.diagrams || []).find(d => d.id === did);
        if (!diag) return;

        try {
            const updated = await api.saveDiagram(project.id, page.index, {
                id: did,
                box_px: diag.box_px,
                mode: diag.mode
            });
            Object.assign(diag, updated);
            this.render();
            // Re-render preview to load updated crop
            window.dispatchEvent(new CustomEvent('diagram-recropped', { detail: { did } }));
        } catch (err) {
            toast.error(`Failed to update diagram crop: ${err.message}`);
        }
    }

    async _deleteActiveBox() {
        const did = store.state.activeDiagramId;
        if (!did) return;
        const page = store.getCurrentPage();
        const project = store.state.project;
        if (!page || !project) return;

        const editorText = window.documentEditor ? window.documentEditor.getValue() : '';
        const tagExists = editorText.includes(`{{DIAGRAM:${did}}}`);
        if (!tagExists) {
            if (!confirm(`Tag {{DIAGRAM:${did}}} is already missing from editor text. Delete diagram ${did}?`)) return;
        }

        try {
            await api.deleteDiagram(project.id, page.index, did);
            page.diagrams = (page.diagrams || []).filter(d => d.id !== did);
            store.setActiveDiagramId(null);
            this.render();

            if (this._onBoxDeleted) {
                this._onBoxDeleted(did);
            }
            toast.info(`Deleted diagram ${did}`);
        } catch (err) {
            toast.error(`Failed to delete diagram: ${err.message}`);
        }
    }

    _debounceSaveCrop() {
        if (this.cropSaveTimeout) clearTimeout(this.cropSaveTimeout);
        this.cropSaveTimeout = setTimeout(async () => {
            const page = store.getCurrentPage();
            const project = store.state.project;
            if (!page || !project) return;

            try {
                if (this.cropScope === 'all') {
                    try {
                        await api.updateSettings({
                            default_top_crop_percent: page.crop.top_pct,
                            default_bottom_crop_percent: page.crop.bottom_pct
                        });
                    } catch (e) {
                        console.warn('Failed to update default crop settings:', e);
                    }

                    // Apply to all pages without override
                    for (const p of Object.values(project.pages)) {
                        if (!p.crop.override) {
                            p.crop.top_pct = page.crop.top_pct;
                            p.crop.bottom_pct = page.crop.bottom_pct;
                            await api.updatePage(project.id, p.index, {
                                crop: {
                                    top_pct: p.crop.top_pct,
                                    bottom_pct: p.crop.bottom_pct,
                                    override: false
                                }
                            });
                        }
                    }
                    toast.success('Crop saved across all pages without override.');
                } else {
                    page.crop.override = true;
                    await api.updatePage(project.id, page.index, {
                        crop: {
                            top_pct: page.crop.top_pct,
                            bottom_pct: page.crop.bottom_pct,
                            override: true
                        }
                    });
                }
            } catch (err) {
                toast.error(`Failed to save crop: ${err.message}`);
            }
        }, 600);
    }
}

export const sourceViewer = new SourceViewer();
