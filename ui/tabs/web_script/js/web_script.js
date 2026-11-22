(function () {
  if (typeof window.__bwDlCleanup === "function") window.__bwDlCleanup();
  const STORAGE_KEY = "bw_dl_crop_v1";
  const SAVE_URL = "http://127.0.0.1:@@SERVER_PORT@@/save";
  const CONFIG = {
    IDLE_MS: @@IDLE_MS@@,
    MIN_WAIT_MS: @@MIN_WAIT_MS@@,
    START_PAGE: @@START_PAGE@@,
    MAX_WAIT_MS: 15000,
    MOVE_WAIT_MS: 10000,
    POLL_INTERVAL_MS: 250,
    AFTER_CLICK_MS: 150,
    DPR_SCALE: @@DPR@@,
    AUTO_FIT_ON_START: true,
    READ_DIRECTION: "RTL",
    IMAGE_STABLE_COUNT: 2,
  };
  const DEFAULT_CROP = { top: 0, bottom: 0, left: 0, right: 0 };
  function loadCrop() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }
  const CROP = { ...DEFAULT_CROP, ...(loadCrop() || {}) };
  function saveCrop() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(CROP)); } catch {}
  }
  const nativeDpr = window.devicePixelRatio || 1;
  const ownDprDesc = Object.getOwnPropertyDescriptor(window, "devicePixelRatio");
  function applyDprOverride() {
    if (CONFIG.DPR_SCALE <= 1) return;
    try {
      const requested = Math.max(1, Math.min(4, Number(CONFIG.DPR_SCALE) || 1));
      const maxSafe = Math.max(1, Math.floor(12000 / Math.max(1, window.innerWidth)));
      const target = Math.min(requested, maxSafe);
      if (target <= nativeDpr) return;
      Object.defineProperty(window, "devicePixelRatio", { configurable: true, get: () => target });
      window.dispatchEvent(new Event("resize"));
    } catch {}
  }
  function restoreDprOverride() {
    if (CONFIG.DPR_SCALE <= 1) return;
    try {
      if (ownDprDesc) Object.defineProperty(window, "devicePixelRatio", ownDprDesc);
      else delete window.devicePixelRatio;
      window.dispatchEvent(new Event("resize"));
    } catch {}
  }
  applyDprOverride();
  let isRunning = false;
  let showCutLines = true;
  let didAutoFitOnStart = false;
  let lastNetworkTime = Date.now();
  let pageNum = 1;
  let rafId = null;
  let readyAt = Date.now() + 600;
  let cropMode = "";
  let forceCaptureRequested = false;
  let forceMoveRequested = false;
  let sleepResolve = null;
  let sleepTimer = null;
  const observer = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      const url = entry.name || "";
      if (@@TARGET@@) lastNetworkTime = Date.now();
    }
  });
  observer.observe({ entryTypes: ["resource"] });
  const styleEl = document.createElement("style");
  styleEl.id = "bw-dl-style";
  styleEl.textContent = `
    #bw-dl-panel {
      position: fixed; top: 16px; right: 16px; z-index: 2147483644;
      background: #18181b; color: #e4e4e7; border: 1px solid #3f3f46;
      border-radius: 4px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 12px; width: 230px; user-select: none; box-sizing: border-box;
    }
    #bw-dl-panel * { box-sizing: border-box; font-family: inherit; }
    #bw-dl-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 6px 10px; background: #27272a; border-bottom: 1px solid #3f3f46;
      cursor: move; font-weight: 600;
    }
    #bw-dl-body { padding: 8px 10px; display: flex; flex-direction: column; gap: 7px; }
    .bw-status { color: #a1a1aa; font-size: 11px; }
    .bw-row { display: flex; gap: 5px; }
    .bw-btn {
      padding: 6px 8px; border: 1px solid #3f3f46; border-radius: 3px;
      color: #e4e4e7; cursor: pointer; font-weight: 600; font-size: 12px; background: #27272a;
    }
    .bw-btn:hover:not(:disabled) { background: #3f3f46; }
    .bw-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .bw-btn-primary { background: #3f3f46; color: #fff; flex: 1; }
    .bw-btn-auto, .bw-btn-crop { flex: 1; }
    .bw-btn-crop.active { background: #52525b; color: #fff; border-color: #71717a; }
    .bw-btn-sm { padding: 2px 7px; font-size: 11px; }
    .bw-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
    .bw-field { display: flex; align-items: center; gap: 4px; }
    .bw-field label { font-size: 11px; color: #a1a1aa; width: 16px; }
    .bw-field input[type="number"] {
      width: 100%; background: #09090b; color: #e4e4e7;
      border: 1px solid #3f3f46; border-radius: 3px; padding: 3px 5px; font-size: 12px;
    }
    .bw-field input:disabled { opacity: .4; cursor: not-allowed; }
    .bw-crop-info { font-size: 11px; color: #a1a1aa; }
    #bw-crop-overlay {
      position: fixed; z-index: 2147483646; pointer-events: none;
      display: none; box-sizing: border-box;
    }
    .bw-mask { position: absolute; background: rgba(0, 0, 0, .35); pointer-events: none; }
    #bw-crop-box { position: absolute; border: 1px solid rgba(255, 255, 255, .4); pointer-events: none; }
    #bw-center-line {
      position: absolute; top: 0; bottom: 0; left: 50%;
      border-left: 1px dashed #facc15;
      box-shadow: 0 0 3px rgba(0, 0, 0, .9);
      pointer-events: none;
    }
    .bw-edge-handle { position: absolute; pointer-events: auto; }
    #bw-crop-overlay.locked .bw-edge-handle,
    #bw-crop-overlay.locked .bw-corner-handle,
    #bw-crop-overlay.locked .bw-pill { pointer-events: none; }
    .bw-edge-top, .bw-edge-bottom { left: 0; right: 0; height: 14px; margin-top: -7px; cursor: ns-resize; }
    .bw-edge-left, .bw-edge-right { top: 0; bottom: 0; width: 14px; margin-left: -7px; cursor: ew-resize; }
    .bw-line-h {
      position: absolute; left: 0; right: 0; top: 6px; height: 0;
      border-top: 1px dashed #e4e4e7; box-shadow: 0 0 2px rgba(0, 0, 0, .8); pointer-events: none;
    }
    .bw-line-v {
      position: absolute; top: 0; bottom: 0; left: 6px; width: 0;
      border-left: 1px dashed #e4e4e7; box-shadow: 0 0 2px rgba(0, 0, 0, .8); pointer-events: none;
    }
    .bw-pill {
      position: absolute; background: #27272a; color: #e4e4e7;
      border: 1px solid #52525b; font-size: 10px; font-weight: 600;
      padding: 1px 5px; border-radius: 2px; white-space: nowrap; pointer-events: auto;
    }
    .bw-pill-top { top: 9px; left: 50%; transform: translateX(-50%); cursor: ns-resize; }
    .bw-pill-bottom { bottom: 9px; left: 50%; transform: translateX(-50%); cursor: ns-resize; }
    .bw-pill-left { left: 9px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
    .bw-pill-right { right: 9px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
    .bw-corner-handle {
      position: absolute; width: 8px; height: 8px; margin-left: -4px; margin-top: -4px;
      background: #e4e4e7; border: 1px solid #18181b; pointer-events: auto;
    }
    #bw-rec-overlay {
      position: fixed; inset: 0; z-index: 2147483645; background: rgba(0, 0, 0, .25);
      display: none; align-items: center; justify-content: center;
      user-select: none; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    #bw-rec-box {
      position: relative; z-index: 2147483647; background: #18181b;
      border: 1px solid #3f3f46; border-radius: 4px; padding: 18px 24px;
      min-width: 260px; display: flex; flex-direction: column;
      align-items: center; gap: 10px; text-align: center; color: #e4e4e7;
    }
    #bw-rec-status { font-size: 13px; font-weight: 600; color: #f4f4f5; }
    #bw-rec-warn { font-size: 12px; color: #a1a1aa; line-height: 1.45; }
    .bw-rec-actions {
      display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; width: 100%;
    }
    .bw-rec-btn {
      padding: 7px 12px; border: 1px solid #52525b; border-radius: 3px;
      background: #27272a; color: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
    }
    .bw-rec-btn:hover { background: #3f3f46; }
    #bw-stop-btn { padding: 7px 16px; }
  `;
  document.head.appendChild(styleEl);
  const panel = document.createElement("div");
  panel.id = "bw-dl-panel";
  panel.innerHTML = `
    <div id="bw-dl-header"><span>캡처</span><button type="button" id="bw-collapse-btn" class="bw-btn bw-btn-sm">-</button></div>
    <div id="bw-dl-body">
      <button type="button" id="bw-start-btn" class="bw-btn bw-btn-primary">시작</button>
      <div class="bw-row">
        <button type="button" id="bw-crop-toggle-btn" class="bw-btn bw-btn-crop active">커트라인</button>
        <button type="button" id="bw-crop-autofit-btn" class="bw-btn bw-btn-auto">여백 맞춤</button>
        <button type="button" id="bw-crop-reset-btn" class="bw-btn bw-btn-sm">초기화</button>
      </div>
      <div class="bw-grid-2">
        <div class="bw-field"><label>상</label><input type="number" id="bw-crop-top" min="0" max="47.5" step="0.1"></div>
        <div class="bw-field"><label>하</label><input type="number" id="bw-crop-bottom" min="0" max="47.5" step="0.1"></div>
        <div class="bw-field"><label>좌</label><input type="number" id="bw-crop-left" min="0" max="47.5" step="0.1"></div>
        <div class="bw-field"><label>우</label><input type="number" id="bw-crop-right" min="0" max="47.5" step="0.1"></div>
      </div>
      <div id="bw-crop-info" class="bw-crop-info"></div>
      <div id="bw-status" class="bw-status">대기</div>
    </div>
  `;
  document.body.appendChild(panel);
  for (const evt of ["keydown", "keyup", "keypress"]) panel.addEventListener(evt, (e) => e.stopPropagation());
  const overlay = document.createElement("div");
  overlay.id = "bw-crop-overlay";
  overlay.innerHTML = `
    <div id="bw-mask-top" class="bw-mask"></div>
    <div id="bw-mask-bottom" class="bw-mask"></div>
    <div id="bw-mask-left" class="bw-mask"></div>
    <div id="bw-mask-right" class="bw-mask"></div>
    <div id="bw-crop-box"></div>
    <div id="bw-center-line"></div>
    <div class="bw-edge-handle bw-edge-top" data-handle="top"><div class="bw-line-h"></div><span id="bw-pill-top" class="bw-pill bw-pill-top">0%</span></div>
    <div class="bw-edge-handle bw-edge-bottom" data-handle="bottom"><div class="bw-line-h"></div><span id="bw-pill-bottom" class="bw-pill bw-pill-bottom">0%</span></div>
    <div class="bw-edge-handle bw-edge-left" data-handle="left"><div class="bw-line-v"></div><span id="bw-pill-left" class="bw-pill bw-pill-left">0%</span></div>
    <div class="bw-edge-handle bw-edge-right" data-handle="right"><div class="bw-line-v"></div><span id="bw-pill-right" class="bw-pill bw-pill-right">0%</span></div>
    <div class="bw-corner-handle" data-handle="tl" style="cursor:nwse-resize;"></div>
    <div class="bw-corner-handle" data-handle="tr" style="cursor:nesw-resize;"></div>
    <div class="bw-corner-handle" data-handle="bl" style="cursor:nesw-resize;"></div>
    <div class="bw-corner-handle" data-handle="br" style="cursor:nwse-resize;"></div>
  `;
  document.body.appendChild(overlay);
  const recOverlay = document.createElement("div");
  recOverlay.id = "bw-rec-overlay";
  recOverlay.innerHTML = `
    <div id="bw-rec-box">
      <div id="bw-rec-status">0장</div>
      <div id="bw-rec-warn">창을 끄거나 브라우저 화면 크기를<br>바꾸지 말고 그대로 켜두세요.</div>
      <div class="bw-rec-actions">
        <button type="button" id="bw-force-capture-btn" class="bw-rec-btn">강제 촬영</button>
        <button type="button" id="bw-force-move-btn" class="bw-rec-btn">강제 움직이기</button>
        <button type="button" id="bw-stop-btn" class="bw-rec-btn">중지하기</button>
      </div>
    </div>
  `;
  document.body.appendChild(recOverlay);
  const $ = (id) => document.getElementById(id);
  const statusEl = $("bw-status");
  const startBtn = $("bw-start-btn");
  const stopBtn = $("bw-stop-btn");
  const forceCaptureBtn = $("bw-force-capture-btn");
  const forceMoveBtn = $("bw-force-move-btn");
  const recBox = $("bw-rec-box");
  const recStatusEl = $("bw-rec-status");
  const collapseBtn = $("bw-collapse-btn");
  const bodyEl = $("bw-dl-body");
  const cropToggleBtn = $("bw-crop-toggle-btn");
  const cropResetBtn = $("bw-crop-reset-btn");
  const cropAutoFitBtn = $("bw-crop-autofit-btn");
  const cropInfoEl = $("bw-crop-info");
  const cropInputs = {
    top: $("bw-crop-top"),
    bottom: $("bw-crop-bottom"),
    left: $("bw-crop-left"),
    right: $("bw-crop-right"),
  };
  function isRecButtonTarget(target) {
    return !!(target && recBox && recBox.contains(target) && target.closest("button"));
  }
  function wakeWaiter() {
    if (sleepTimer) {
      clearTimeout(sleepTimer);
      sleepTimer = null;
    }
    if (sleepResolve) {
      const resolve = sleepResolve;
      sleepResolve = null;
      resolve();
    }
  }
  function getCropMode() {
    const canvases = getVisibleCanvases();
    if (!canvases.length) return cropMode || "horizontal";
    const union = getCanvasesUnionRect();
    if (!union) return cropMode || "horizontal";
    return union.width >= union.height ? "horizontal" : "vertical";
  }
  function setSymmetricCrop(edge, value) {
    value = Number(value);
    if (!Number.isFinite(value)) value = 0;
    value = Math.max(0, Math.min(47.5, value));
    value = round1(value);
    if (cropMode === "vertical") {
      if (edge !== "top" && edge !== "bottom") return;
      CROP.top = value;
      CROP.bottom = value;
    } else {
      if (edge !== "left" && edge !== "right") return;
      CROP.left = value;
      CROP.right = value;
    }
  }
  function applyCropMode(force = false) {
    const nextMode = getCropMode();
    if (!force && nextMode === cropMode) return;
    cropMode = nextMode;
    if (cropMode === "horizontal") {
      const value = round1((Number(CROP.left || 0) + Number(CROP.right || 0)) / 2);
      CROP.top = 0;
      CROP.bottom = 0;
      CROP.left = value;
      CROP.right = value;
    } else {
      const value = round1((Number(CROP.top || 0) + Number(CROP.bottom || 0)) / 2);
      CROP.left = 0;
      CROP.right = 0;
      CROP.top = value;
      CROP.bottom = value;
    }
    cropInputs.top.disabled = cropMode !== "vertical";
    cropInputs.bottom.disabled = cropMode !== "vertical";
    cropInputs.left.disabled = cropMode !== "horizontal";
    cropInputs.right.disabled = cropMode !== "horizontal";
    saveCrop();
    syncInputsFromState();
    updateCropVisuals();
  }
  let panelDrag = null;
  $("bw-dl-header").addEventListener("mousedown", (e) => {
    if (isRunning || e.target === collapseBtn) return;
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    panelDrag = { offsetX: e.clientX - rect.left, offsetY: e.clientY - rect.top };
  });
  collapseBtn.onclick = () => {
    const isHidden = bodyEl.style.display === "none";
    bodyEl.style.display = isHidden ? "flex" : "none";
    collapseBtn.textContent = isHidden ? "-" : "+";
  };
  function round1(n) { return Math.round(n * 10) / 10; }
  function syncInputsFromState() {
    for (const edge of ["top", "bottom", "left", "right"]) cropInputs[edge].value = CROP[edge];
    updateCropInfoText();
  }
  function updateCropInfoText() {
    const wPct = round1(100 - CROP.left - CROP.right);
    const hPct = round1(100 - CROP.top - CROP.bottom);
    const canvases = getVisibleCanvases();
    if (canvases.length) {
      const c = canvases[0];
      cropInfoEl.textContent = `${Math.round(c.width * wPct / 100)}x${Math.round(c.height * hPct / 100)} (${c.width}x${c.height})`;
    } else cropInfoEl.textContent = `${wPct}% x ${hPct}%`;
  }
  for (const edge of ["top", "bottom", "left", "right"]) {
    cropInputs[edge].addEventListener("input", () => {
      if (cropInputs[edge].disabled) return;
      setSymmetricCrop(edge, cropInputs[edge].value);
      saveCrop();
      syncInputsFromState();
      updateCropVisuals();
    });
  }
  cropResetBtn.onclick = () => {
    Object.assign(CROP, DEFAULT_CROP);
    saveCrop();
    syncInputsFromState();
    updateCropVisuals();
  };
  function getVisibleCanvases() {
    const list = [];
    for (const canvas of document.querySelectorAll("canvas")) {
      const style = getComputedStyle(canvas);
      const rect = canvas.getBoundingClientRect();
      if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity || "1") === 0 || rect.width < 100 || rect.height < 100) continue;
      list.push({ canvas, left: rect.left });
    }
    if (CONFIG.READ_DIRECTION === "RTL") list.sort((a, b) => b.left - a.left);
    else list.sort((a, b) => a.left - b.left);
    return list.map((item) => item.canvas);
  }
  function getCanvasesUnionRect() {
    const canvases = getVisibleCanvases();
    if (!canvases.length) return null;
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const c of canvases) {
      const r = c.getBoundingClientRect();
      left = Math.min(left, r.left);
      top = Math.min(top, r.top);
      right = Math.max(right, r.right);
      bottom = Math.max(bottom, r.bottom);
    }
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  }
  function detectMarginsOnSingleCanvas(canvas) {
    const w = canvas.width, h = canvas.height;
    if (w < 20 || h < 20) return null;
    const scale = Math.min(1, 1600 / Math.max(w, h));
    const pw = Math.max(10, Math.round(w * scale));
    const ph = Math.max(10, Math.round(h * scale));
    const probe = document.createElement("canvas");
    probe.width = pw;
    probe.height = ph;
    const ctx = probe.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(canvas, 0, 0, pw, ph);
    let data;
    try { data = ctx.getImageData(0, 0, pw, ph).data; } catch { return null; }
    const getPx = (x, y) => {
      const idx = (y * pw + x) * 4;
      return [data[idx], data[idx + 1], data[idx + 2], data[idx + 3]];
    };
    const tol = 12;
    const matchColor = (px, ref) => {
      if (ref[3] < 20) return px[3] < 20;
      return Math.abs(px[0] - ref[0]) <= tol && Math.abs(px[1] - ref[1]) <= tol && Math.abs(px[2] - ref[2]) <= tol && Math.abs(px[3] - ref[3]) <= tol;
    };
    const pickEdgeRef = (samples) => {
      let best = samples[0], bestCount = -1;
      for (const s of samples) {
        let cnt = 0;
        for (const o of samples) if (matchColor(o, s)) cnt++;
        if (cnt > bestCount) { bestCount = cnt; best = s; }
      }
      return best;
    };
    const isRowMargin = (y, ref) => {
      const maxMismatch = Math.max(1, Math.floor(pw * 0.0015));
      let mismatch = 0;
      for (let x = 0; x < pw; x++) if (!matchColor(getPx(x, y), ref) && ++mismatch > maxMismatch) return false;
      return true;
    };
    const isColMargin = (x, ref) => {
      const maxMismatch = Math.max(1, Math.floor(ph * 0.0015));
      let mismatch = 0;
      for (let y = 0; y < ph; y++) if (!matchColor(getPx(x, y), ref) && ++mismatch > maxMismatch) return false;
      return true;
    };
    const xs = [2, Math.floor(pw * .25), Math.floor(pw * .5), Math.floor(pw * .75), pw - 3];
    const ys = [2, Math.floor(ph * .25), Math.floor(ph * .5), Math.floor(ph * .75), ph - 3];
    const topRef = pickEdgeRef(xs.map((x) => getPx(x, 0)));
    const bottomRef = pickEdgeRef(xs.map((x) => getPx(x, ph - 1)));
    const leftRef = pickEdgeRef(ys.map((y) => getPx(0, y)));
    const rightRef = pickEdgeRef(ys.map((y) => getPx(pw - 1, y)));
    let topPx = 0, bottomPx = 0, leftPx = 0, rightPx = 0;
    while (topPx < ph && isRowMargin(topPx, topRef)) topPx++;
    while (bottomPx < ph - topPx && isRowMargin(ph - 1 - bottomPx, bottomRef)) bottomPx++;
    while (leftPx < pw && isColMargin(leftPx, leftRef)) leftPx++;
    while (rightPx < pw - leftPx && isColMargin(pw - 1 - rightPx, rightRef)) rightPx++;
    if (topPx + bottomPx >= ph * .92 || leftPx + rightPx >= pw * .92) return null;
    const pad = 2;
    topPx = Math.max(0, topPx - pad);
    bottomPx = Math.max(0, bottomPx - pad);
    leftPx = Math.max(0, leftPx - pad);
    rightPx = Math.max(0, rightPx - pad);
    return { top: topPx / ph * 100, bottom: bottomPx / ph * 100, left: leftPx / pw * 100, right: rightPx / pw * 100 };
  }
  function autoFitCrop(isInitial = false) {
    const canvases = getVisibleCanvases();
    if (!canvases.length) {
      if (!isInitial) statusEl.textContent = "캔버스 없음";
      return false;
    }
    if (canvases.every((c) => isBlankCanvas(c))) {
      if (!isInitial) statusEl.textContent = "화면 로딩 중";
      return false;
    }
    let result = null;
    if (canvases.length === 1) result = detectMarginsOnSingleCanvas(canvases[0]);
    else {
      const union = getCanvasesUnionRect();
      if (!union || union.width <= 0 || union.height <= 0) return false;
      let minLeft = Infinity, maxRight = -Infinity, minTop = Infinity, maxBottom = -Infinity;
      let validCount = 0;
      for (const c of canvases) {
        const m = detectMarginsOnSingleCanvas(c);
        if (!m) continue;
        validCount++;
        const r = c.getBoundingClientRect();
        minLeft = Math.min(minLeft, r.left + r.width * m.left / 100);
        maxRight = Math.max(maxRight, r.right - r.width * m.right / 100);
        minTop = Math.min(minTop, r.top + r.height * m.top / 100);
        maxBottom = Math.max(maxBottom, r.bottom - r.height * m.bottom / 100);
      }
      if (validCount) result = {
        top: (minTop - union.top) / union.height * 100,
        bottom: (union.bottom - maxBottom) / union.height * 100,
        left: (minLeft - union.left) / union.width * 100,
        right: (union.right - maxRight) / union.width * 100,
      };
    }
    if (!result) {
      if (!isInitial) statusEl.textContent = "여백 감지 실패";
      return false;
    }
    Object.assign(CROP, DEFAULT_CROP);
    if (cropMode === "vertical") setSymmetricCrop("top", (result.top + result.bottom) / 2);
    else setSymmetricCrop("left", (result.left + result.right) / 2);
    saveCrop();
    syncInputsFromState();
    updateCropVisuals();
    statusEl.textContent = `여백 맞춤: ${CROP.top} / ${CROP.bottom} / ${CROP.left} / ${CROP.right}`;
    return true;
  }
  cropAutoFitBtn.onclick = () => autoFitCrop(false);
  function updateCropVisuals() {
    if (!showCutLines) return;
    const { top: topPct, bottom: bottomPct, left: leftPct, right: rightPct } = CROP;
    const mTop = $("bw-mask-top").style;
    mTop.left = "0"; mTop.right = "0"; mTop.top = "0"; mTop.height = `${topPct}%`;
    const mBot = $("bw-mask-bottom").style;
    mBot.left = "0"; mBot.right = "0"; mBot.bottom = "0"; mBot.height = `${bottomPct}%`;
    const mLeft = $("bw-mask-left").style;
    mLeft.left = "0"; mLeft.top = `${topPct}%`; mLeft.bottom = `${bottomPct}%`; mLeft.width = `${leftPct}%`;
    const mRight = $("bw-mask-right").style;
    mRight.right = "0"; mRight.top = `${topPct}%`; mRight.bottom = `${bottomPct}%`; mRight.width = `${rightPct}%`;
    const box = $("bw-crop-box").style;
    box.top = `${topPct}%`; box.bottom = `${bottomPct}%`; box.left = `${leftPct}%`; box.right = `${rightPct}%`;
    overlay.querySelector(".bw-edge-top").style.top = `${topPct}%`;
    overlay.querySelector(".bw-edge-bottom").style.top = `${100 - bottomPct}%`;
    overlay.querySelector(".bw-edge-left").style.left = `${leftPct}%`;
    overlay.querySelector(".bw-edge-right").style.left = `${100 - rightPct}%`;
    $("bw-pill-top").textContent = `${topPct}%`;
    $("bw-pill-bottom").textContent = `${bottomPct}%`;
    $("bw-pill-left").textContent = `${leftPct}%`;
    $("bw-pill-right").textContent = `${rightPct}%`;
    overlay.querySelector('[data-handle="tl"]').style.left = `${leftPct}%`;
    overlay.querySelector('[data-handle="tl"]').style.top = `${topPct}%`;
    overlay.querySelector('[data-handle="tr"]').style.left = `${100 - rightPct}%`;
    overlay.querySelector('[data-handle="tr"]').style.top = `${topPct}%`;
    overlay.querySelector('[data-handle="bl"]').style.left = `${leftPct}%`;
    overlay.querySelector('[data-handle="bl"]').style.top = `${100 - bottomPct}%`;
    overlay.querySelector('[data-handle="br"]').style.left = `${100 - rightPct}%`;
    overlay.querySelector('[data-handle="br"]').style.top = `${100 - bottomPct}%`;
  }
  let lastRectKey = "";
  let lastCanvasDimKey = "";
  function syncOverlayLoop() {
    applyCropMode();
    if (!showCutLines && didAutoFitOnStart) return;
    const union = getCanvasesUnionRect();
    const canvases = getVisibleCanvases();
    if (!didAutoFitOnStart && CONFIG.AUTO_FIT_ON_START && Date.now() >= readyAt && union && union.width > 0) {
      if (autoFitCrop(true)) didAutoFitOnStart = true;
    }
    if (canvases.length) {
      const dimKey = `${canvases[0].width}x${canvases[0].height}`;
      if (dimKey !== lastCanvasDimKey) {
        lastCanvasDimKey = dimKey;
        updateCropInfoText();
      }
    }
    if (showCutLines) {
      if (union && union.width > 0 && union.height > 0) {
        const key = `${Math.round(union.left)},${Math.round(union.top)},${Math.round(union.width)},${Math.round(union.height)}`;
        if (key !== lastRectKey) {
          lastRectKey = key;
          overlay.style.display = "block";
          overlay.style.left = `${union.left}px`;
          overlay.style.top = `${union.top}px`;
          overlay.style.width = `${union.width}px`;
          overlay.style.height = `${union.height}px`;
          updateCropVisuals();
          updateCropInfoText();
        }
      } else if (lastRectKey !== "none") {
        lastRectKey = "none";
        overlay.style.display = "none";
        updateCropInfoText();
      }
    }
    rafId = requestAnimationFrame(syncOverlayLoop);
  }
  function setShowCutLines(on) {
    showCutLines = on;
    cropToggleBtn.classList.toggle("active", on);
    if (on) {
      lastRectKey = "";
      if (rafId) cancelAnimationFrame(rafId);
      syncOverlayLoop();
    } else overlay.style.display = "none";
  }
  cropToggleBtn.onclick = () => setShowCutLines(!showCutLines);
  let cropDrag = null;
  overlay.addEventListener("mousedown", (e) => {
    if (isRunning) return;
    const handle = e.target.closest("[data-handle]")?.dataset?.handle;
    if (!handle) return;
    const union = getCanvasesUnionRect();
    if (!union) return;
    const verticalHandle = ["top", "bottom", "tl", "tr", "bl", "br"].includes(handle);
    const horizontalHandle = ["left", "right", "tl", "tr", "bl", "br"].includes(handle);
    if (cropMode === "vertical" && !verticalHandle) return;
    if (cropMode === "horizontal" && !horizontalHandle) return;
    e.preventDefault();
    e.stopPropagation();
    cropDrag = { handle, union };
  });
  function onMouseMove(e) {
    if (panelDrag) {
      const maxX = Math.max(0, window.innerWidth - panel.offsetWidth);
      const maxY = Math.max(0, window.innerHeight - panel.offsetHeight);
      panel.style.left = `${Math.max(0, Math.min(maxX, e.clientX - panelDrag.offsetX))}px`;
      panel.style.top = `${Math.max(0, Math.min(maxY, e.clientY - panelDrag.offsetY))}px`;
      panel.style.right = "auto";
      return;
    }
    if (cropDrag) {
      const { handle, union } = cropDrag;
      if (cropMode === "vertical") {
        if (["top", "tl", "tr"].includes(handle)) setSymmetricCrop("top", ((e.clientY - union.top) / union.height) * 100);
        if (["bottom", "bl", "br"].includes(handle)) setSymmetricCrop("bottom", ((union.bottom - e.clientY) / union.height) * 100);
      } else {
        if (["left", "tl", "bl"].includes(handle)) setSymmetricCrop("left", ((e.clientX - union.left) / union.width) * 100);
        if (["right", "tr", "br"].includes(handle)) setSymmetricCrop("right", ((union.right - e.clientX) / union.width) * 100);
      }
      syncInputsFromState();
      updateCropVisuals();
    }
  }
  function onMouseUp() {
    if (cropDrag) { saveCrop(); cropDrag = null; }
    panelDrag = null;
  }
  function blockKeyInput(e) {
    if (!isRunning || !e.isTrusted) return;
    if (isRecButtonTarget(e.target)) return;
    if (e.cancelable) e.preventDefault();
    e.stopPropagation();
  }
  function blockWheelInput(e) {
    if (!isRunning || !e.isTrusted) return;
    if (e.cancelable) e.preventDefault();
    e.stopPropagation();
  }
  recOverlay.addEventListener("mousedown", (e) => {
    if (!e.isTrusted) return;
    if (isRecButtonTarget(e.target)) return;
    e.stopPropagation();
  });
  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
  window.addEventListener("keydown", blockKeyInput, true);
  window.addEventListener("keyup", blockKeyInput, true);
  window.addEventListener("keypress", blockKeyInput, true);
  window.addEventListener("wheel", blockWheelInput, { passive: false, capture: true });
  window.addEventListener("touchmove", blockWheelInput, { passive: false, capture: true });
  window.addEventListener("resize", () => applyCropMode());
  applyCropMode(true);
  syncInputsFromState();
  setShowCutLines(true);
  const sleep = (ms) => new Promise((resolve) => {
    sleepResolve = resolve;
    sleepTimer = setTimeout(() => {
      sleepTimer = null;
      if (sleepResolve === resolve) sleepResolve = null;
      resolve();
    }, ms);
  });
  function isEndOfBook() {
    const dialog = document.querySelector("#dialog div.dialogEndOfBook");
    return dialog && getComputedStyle(dialog).display === "block";
  }
  async function waitForNetworkIdle() {
    const start = Date.now();
    await sleep(CONFIG.MIN_WAIT_MS);
    while (isRunning && !forceCaptureRequested && !forceMoveRequested) {
      const now = Date.now();
      if (now - lastNetworkTime >= CONFIG.IDLE_MS) return true;
      if (now - start >= CONFIG.MAX_WAIT_MS) return true;
      await sleep(CONFIG.POLL_INTERVAL_MS);
    }
    return isRunning;
  }
  function extractSubCanvas(sourceCanvas, sx, sy, sw, sh) {
    const c = document.createElement("canvas");
    c.width = sw;
    c.height = sh;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(sourceCanvas, sx, sy, sw, sh, 0, 0, sw, sh);
    return c;
  }
  function hasCrop() {
    return CROP.top > 0 || CROP.bottom > 0 || CROP.left > 0 || CROP.right > 0;
  }
  function buildTargetCanvases(rawCanvases) {
    if (!rawCanvases.length) return [];
    if (!hasCrop()) return rawCanvases;
    if (rawCanvases.length === 1) {
      const single = rawCanvases[0];
      const w = single.width, h = single.height;
      const x1 = Math.round(w * CROP.left / 100);
      const x2 = Math.round(w * (1 - CROP.right / 100));
      const y1 = Math.round(h * CROP.top / 100);
      const y2 = Math.round(h * (1 - CROP.bottom / 100));
      const sw = x2 - x1, sh = y2 - y1;
      if (sw < 5 || sh < 5) return [];
      return [extractSubCanvas(single, x1, y1, sw, sh)];
    }
    const union = getCanvasesUnionRect();
    if (!union) return rawCanvases;
    const keepLeft = union.left + union.width * CROP.left / 100;
    const keepRight = union.right - union.width * CROP.right / 100;
    const keepTop = union.top + union.height * CROP.top / 100;
    const keepBottom = union.bottom - union.height * CROP.bottom / 100;
    const out = [];
    for (const c of rawCanvases) {
      const r = c.getBoundingClientRect();
      const ix1 = Math.max(r.left, keepLeft);
      const ix2 = Math.min(r.right, keepRight);
      const iy1 = Math.max(r.top, keepTop);
      const iy2 = Math.min(r.bottom, keepBottom);
      if (ix2 - ix1 < 5 || iy2 - iy1 < 5) continue;
      const scaleX = c.width / r.width;
      const scaleY = c.height / r.height;
      const sx = Math.max(0, Math.round((ix1 - r.left) * scaleX));
      const sy = Math.max(0, Math.round((iy1 - r.top) * scaleY));
      const sw = Math.min(c.width - sx, Math.round((ix2 - ix1) * scaleX));
      const sh = Math.min(c.height - sy, Math.round((iy2 - iy1) * scaleY));
      if (sw >= 5 && sh >= 5) out.push(extractSubCanvas(c, sx, sy, sw, sh));
    }
    return out;
  }
  function isBlankCanvas(canvas) {
    const probe = document.createElement("canvas");
    probe.width = 32;
    probe.height = 32;
    const ctx = probe.getContext("2d");
    ctx.drawImage(canvas, 0, 0, 32, 32);
    const data = ctx.getImageData(0, 0, 32, 32).data;
    const r0 = data[0], g0 = data[1], b0 = data[2], a0 = data[3];
    for (let i = 4; i < data.length; i += 4) {
      if (Math.abs(data[i] - r0) > 3 || Math.abs(data[i + 1] - g0) > 3 || Math.abs(data[i + 2] - b0) > 3 || Math.abs(data[i + 3] - a0) > 3) return false;
    }
    return true;
  }
  function canvasToBlob(canvas) {
    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  }
  async function getCanvasSignature() {
    const canvases = getVisibleCanvases();
    if (!canvases.length) return null;
    const signatures = [];
    for (const canvas of canvases) {
      if (isBlankCanvas(canvas)) return null;
      const blob = await canvasToBlob(canvas);
      if (!blob || blob.size < 2000) return null;
      signatures.push(`${canvas.width}x${canvas.height}:${await sha256(blob)}`);
    }
    return signatures.join("|");
  }
  async function waitForCanvasChange(previousSignature) {
    const start = Date.now();
    let candidate = null;
    let stableCount = 0;
    while (isRunning && !forceCaptureRequested && !forceMoveRequested && Date.now() - start < CONFIG.MOVE_WAIT_MS) {
      await waitForNetworkIdle();
      if (!isRunning || forceCaptureRequested || forceMoveRequested) return null;
      const current = await getCanvasSignature();
      if (current && current !== previousSignature) {
        if (current === candidate) stableCount++;
        else {
          candidate = current;
          stableCount = 1;
        }
        if (stableCount >= CONFIG.IMAGE_STABLE_COUNT) return current;
      } else {
        candidate = null;
        stableCount = 0;
      }
      await sleep(CONFIG.POLL_INTERVAL_MS);
    }
    return null;
  }
  async function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
  async function saveImageToLocal(filename, blob) {
    const data = await blobToBase64(blob);
    const res = await fetch(SAVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: document.title || "untitled", filename, data }),
    });
    if (!res.ok) throw new Error(`저장 실패 (${res.status})`);
  }
  async function sha256(blob) {
    const buf = await blob.arrayBuffer();
    const hashBuf = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(hashBuf)).map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  function clickLeftCenter() {
    const x = 20;
    const y = Math.round(window.innerHeight / 2);
    const prevPtr = recOverlay.style.pointerEvents;
    recOverlay.style.pointerEvents = "none";
    try {
      const target = document.elementFromPoint(x, y) || document.body;
      const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0, buttons: 1 };
      target.dispatchEvent(new PointerEvent("pointerdown", opts));
      target.dispatchEvent(new MouseEvent("mousedown", opts));
      target.dispatchEvent(new PointerEvent("pointerup", { ...opts, buttons: 0 }));
      target.dispatchEvent(new MouseEvent("mouseup", { ...opts, buttons: 0 }));
      target.dispatchEvent(new MouseEvent("click", { ...opts, buttons: 0 }));
    } finally { recOverlay.style.pointerEvents = prevPtr; }
  }
  function setStatus(msg) {
    statusEl.textContent = msg;
    recStatusEl.textContent = msg;
  }
  forceCaptureBtn.onclick = () => {
    if (!isRunning) return;
    forceCaptureRequested = true;
    wakeWaiter();
  };
  forceMoveBtn.onclick = () => {
    if (!isRunning) return;
    forceMoveRequested = true;
    wakeWaiter();
  };
  stopBtn.onclick = () => {
    isRunning = false;
    wakeWaiter();
    window.__bwDlCleanup();
  };
  startBtn.onclick = async () => {
    if (isRunning) return;
    isRunning = true;
    forceCaptureRequested = false;
    forceMoveRequested = false;
    startBtn.disabled = true;
    overlay.classList.add("locked");
    recOverlay.style.display = "flex";
    pageNum = CONFIG.START_PAGE;
    let screenIndex = 1;
    let previousSignature = null;
    let emptyWaitStart = null;
    try {
      while (isRunning) {
        if (forceMoveRequested) {
          forceMoveRequested = false;
          emptyWaitStart = null;
          setStatus(`강제 이동 중 (${pageNum - 1}장)`);
          lastNetworkTime = Date.now();
          clickLeftCenter();
          await sleep(CONFIG.AFTER_CLICK_MS);
          screenIndex++;
          continue;
        }
        setStatus(`${screenIndex}화면 / ${pageNum - 1}장`);
        if (!forceCaptureRequested) {
          if (!await waitForNetworkIdle()) break;
          if (!isRunning || isEndOfBook()) break;
          if (forceMoveRequested) continue;
        }
        let currentSignature = await getCanvasSignature();
        if (!forceCaptureRequested && !currentSignature) {
          if (emptyWaitStart === null) emptyWaitStart = Date.now();
          if (Date.now() - emptyWaitStart >= CONFIG.MOVE_WAIT_MS) {
            emptyWaitStart = null;
            setStatus(`로딩 지연 - 다시 이동 (${pageNum - 1}장)`);
            lastNetworkTime = Date.now();
            clickLeftCenter();
            await sleep(CONFIG.AFTER_CLICK_MS);
            screenIndex++;
            continue;
          }
          await sleep(CONFIG.POLL_INTERVAL_MS);
          continue;
        }
        emptyWaitStart = null;
        if (!forceCaptureRequested && previousSignature !== null && currentSignature === previousSignature) {
          setStatus(`화면 움직임 대기 중 (${pageNum - 1}장)`);
          currentSignature = await waitForCanvasChange(previousSignature);
          if (!isRunning) break;
          if (forceMoveRequested) continue;
          if (!forceCaptureRequested && !currentSignature) {
            setStatus(`10초 이상 움직임 없음 - 다시 이동 (${pageNum - 1}장)`);
            lastNetworkTime = Date.now();
            clickLeftCenter();
            await sleep(CONFIG.AFTER_CLICK_MS);
            screenIndex++;
            continue;
          }
        }
        const forced = forceCaptureRequested;
        forceCaptureRequested = false;
        const rawCanvases = getVisibleCanvases();
        const targetCanvases = buildTargetCanvases(rawCanvases);
        for (const canvas of targetCanvases) {
          if (!isRunning) break;
          if (!forced && isBlankCanvas(canvas)) continue;
          const blob = await canvasToBlob(canvas);
          if (!blob || (!forced && blob.size < 2000)) continue;
          await saveImageToLocal(`p${pageNum}.png`, blob);
          pageNum++;
        }
        previousSignature = currentSignature || await getCanvasSignature();
        screenIndex++;
        setStatus(`이동 중 (${pageNum - 1}장)`);
        lastNetworkTime = Date.now();
        clickLeftCenter();
        await sleep(CONFIG.AFTER_CLICK_MS);
      }
      window.__bwDlCleanup();
    } catch (err) {
      isRunning = false;
      startBtn.disabled = false;
      overlay.classList.remove("locked");
      recOverlay.style.display = "none";
      setStatus(`오류: ${err.message}`);
    }
  };
  window.__bwDlCleanup = () => {
    isRunning = false;
    wakeWaiter();
    if (rafId) cancelAnimationFrame(rafId);
    observer.disconnect();
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
    window.removeEventListener("keydown", blockKeyInput, true);
    window.removeEventListener("keyup", blockKeyInput, true);
    window.removeEventListener("keypress", blockKeyInput, true);
    window.removeEventListener("wheel", blockWheelInput, { passive: false, capture: true });
    window.removeEventListener("touchmove", blockWheelInput, { passive: false, capture: true });
    restoreDprOverride();
    panel.remove();
    overlay.remove();
    recOverlay.remove();
    styleEl.remove();
    delete window.__bwDlCleanup;
  };
})();