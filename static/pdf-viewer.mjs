import * as pdfjsLib from './vendor/pdf.min.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.mjs';

export class LocalLeafPDFViewer {
  constructor(container, onNavigate, onStatus) {
    this.container = container;
    this.onNavigate = onNavigate;
    this.onStatus = onStatus;
    this.document = null;
    this.generation = 0;
    this.zoom = 1;
    this.baseWidth = 612;
  }

  async load(url) {
    const generation = ++this.generation;
    this.container.replaceChildren();
    this.container.classList.add('loading');
    this.onStatus?.('正在载入 PDF…');
    const task = pdfjsLib.getDocument({
      url,
      cMapUrl: '/static/vendor/pdfjs-cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/static/vendor/pdfjs-standard-fonts/',
      wasmUrl: '/static/vendor/pdfjs-wasm/'
    });
    const document = await task.promise;
    if (generation !== this.generation) {
      await document.destroy();
      return;
    }
    if (this.document) await this.document.destroy();
    this.document = document;
    const first = await document.getPage(1);
    this.baseWidth = first.getViewport({scale: 1}).width;
    this.zoom = Math.max(.45, Math.min(1.25, (this.container.clientWidth - 38) / this.baseWidth));
    this.onStatus?.(this.zoom, document.numPages);
    for (let number = 1; number <= document.numPages; number++) {
      if (generation !== this.generation) return;
      await this.renderPage(number, generation);
    }
    this.container.classList.remove('loading');
  }

  async renderPage(number, generation) {
    const page = await this.document.getPage(number);
    if (generation !== this.generation) return;
    const base = page.getViewport({scale: 1});
    const outputScale = Math.min(3, Math.max(1.5, window.devicePixelRatio || 1));
    const viewport = page.getViewport({scale: outputScale});
    const shell = document.createElement('div');
    shell.className = 'pdf-page-shell';
    shell.dataset.page = number;
    const canvas = document.createElement('canvas');
    canvas.className = 'pdf-page-canvas';
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = `${base.width * this.zoom}px`;
    canvas.style.height = `${base.height * this.zoom}px`;
    canvas.dataset.bpWidth = base.width;
    canvas.dataset.bpHeight = base.height;
    canvas.title = `第 ${number} 页 · 双击跳转到 LaTeX 源码`;
    canvas.addEventListener('dblclick', event => this.reverseSearch(event, number, canvas));
    const badge = document.createElement('span');
    badge.className = 'pdf-page-number';
    badge.textContent = `${number} / ${this.document.numPages}`;
    shell.append(canvas, badge);
    this.container.append(shell);
    await page.render({canvas, canvasContext: canvas.getContext('2d'), viewport}).promise;
  }

  reverseSearch(event, page, canvas) {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * Number(canvas.dataset.bpWidth);
    const y = (event.clientY - rect.top) / rect.height * Number(canvas.dataset.bpHeight);
    this.onNavigate?.({page, x, y, canvas});
  }

  setZoom(delta) {
    if (!this.document) return;
    this.zoom = Math.max(.35, Math.min(2.5, this.zoom + delta));
    this.container.querySelectorAll('.pdf-page-canvas').forEach(canvas => {
      canvas.style.width = `${Number(canvas.dataset.bpWidth) * this.zoom}px`;
      canvas.style.height = `${Number(canvas.dataset.bpHeight) * this.zoom}px`;
    });
    this.onStatus?.(this.zoom, this.document.numPages);
  }

  clear() {
    this.generation++;
    if (this.document) this.document.destroy();
    this.document = null;
    this.container.replaceChildren();
  }
}
