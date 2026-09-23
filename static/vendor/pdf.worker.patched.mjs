// Worker entry point: the pdf.js worker runs in its own JavaScript realm, so a polyfill
// installed on the page does not reach it. Load the Map-upsert polyfill first, then the
// stock worker. GlobalWorkerOptions.workerSrc points here (see ../pdf-viewer.mjs).
import './map-upsert-polyfill.mjs';
import './pdf.worker.min.mjs';
