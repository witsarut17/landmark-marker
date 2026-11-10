// ImageViewer: แสดงภาพ 1 ภาพบน canvas พร้อมซูม/เลื่อน, แปลงพิกัด, วาดจุด และวาง/ลากจุดผ่านแว่นขยาย
//
// หัวใจเรื่องพิกัด (ห้ามแก้โดยไม่รัน tests/test_coordinates.py ใหม่):
//   จอ (CSS px วัดจากมุมซ้ายบนของ canvas) = t + s * ภาพ (px ต้นฉบับ)
//   ภาพ = (จอ - t) / s
//   s, tx, ty อยู่ในหน่วย CSS px จึงไม่ขึ้นกับ devicePixelRatio
//   origin ภาพ = มุมซ้ายบนของพิกเซลซ้ายบน (กึ่งกลางพิกเซล i = i + 0.5) แบบ COCO
//
// การวางจุด (session): เริ่มที่ตำแหน่งที่กด แล้วขยับแบบละเอียด
//   จุด = จุดเริ่ม + (ตำแหน่งนิ้วตอนนี้ - ตำแหน่งนิ้วตอนเริ่ม) / sL
//   sL = สเกลแว่นขยาย (px จอ ต่อ px ภาพ) ≥ 4 -> นิ้วขยับ 1 px จอ = จุดขยับ ≤ 0.25 px ภาพ
(function () {
  'use strict';
  const CFG = window.MARKER_CONFIG;

  class ImageViewer {
    constructor(container, opts = {}) {
      this.container = container;
      this.opts = opts;
      this.canvas = document.createElement('canvas');
      this.canvas.className = 'viewer-canvas';
      container.appendChild(this.canvas);
      this.ctx = this.canvas.getContext('2d');

      this.img = null; this.W = 0; this.H = 0;
      this.s = 1; this.tx = 0; this.ty = 0; this.fitScale = 1;
      this.cssW = 0; this.cssH = 0;

      this.pointers = new Map();   // pointerId -> {x, y, type}
      this.gesture = null;         // pending | pan | pinch | session | idle
      this.session = null;         // การวาง/ลากจุดที่กำลังทำ
      this.hover = null;           // พิกัดภาพใต้เมาส์/ปากกา
      this.message = opts.emptyMessage || '';
      this._raf = 0;
      // ปรับการแสดงผลเท่านั้น (ไม่แก้ไฟล์ ไม่กระทบพิกัด)
      this.adjust = { brightness: 1, contrast: 1, invert: false };
      this._src = null;            // canvas ภาพที่ปรับแล้ว (null = ใช้ภาพต้นฉบับ)
      this._adjTimer = 0;

      this._bindEvents();
      // จัดการขนาดในเฟรมถัดไป (ไม่ทำใน callback ของ ResizeObserver โดยตรง -> ไม่เกิด "ResizeObserver loop")
      this._roRaf = 0;
      const schedule = () => {
        if (this._roRaf) return;
        this._roRaf = requestAnimationFrame(() => { this._roRaf = 0; this._resize(); });
      };
      this._ro = new ResizeObserver(schedule);
      this._ro.observe(container);
      window.addEventListener('resize', schedule);   // เผื่อ dpr เปลี่ยน (ย้ายจอ / ซูมเบราว์เซอร์)
      this._resize();
    }

    // ---------- พิกัด ----------
    screenToImage(x, y) { return { x: (x - this.tx) / this.s, y: (y - this.ty) / this.s }; }
    imageToScreen(u, v) { return { x: this.tx + u * this.s, y: this.ty + v * this.s }; }
    get zoom() { return this.s / this.fitScale; }
    clampToImage(p) { return { x: Math.min(this.W, Math.max(0, p.x)), y: Math.min(this.H, Math.max(0, p.y)) }; }

    loupeScale() {
      const L = CFG.loupe;
      const sL = Math.max(L.minScreenPxPerImagePx, this.s * L.magnify, this.s);
      return Math.min(Math.max(L.maxScreenPxPerImagePx, this.s), sL);
    }

    _local(e) {
      const r = this.canvas.getBoundingClientRect();
      const kx = r.width ? this.cssW / r.width : 1;
      const ky = r.height ? this.cssH / r.height : 1;
      return { x: (e.clientX - r.left) * kx, y: (e.clientY - r.top) * ky };
    }

    // ---------- ภาพ ----------
    setImage(img, W, H) {
      this._abortGesture();
      this.img = img; this.W = W; this.H = H;
      this.hover = null; this.message = '';
      this._src = null;
      this._buildAdjusted();
      this.resetView();
    }

    clear(message = '') {
      this._abortGesture();
      this._src = null;
      this.img = null; this.W = 0; this.H = 0;
      this.hover = null; this.message = message;
      this._emit(); this.requestRender();
    }

    resetView() {
      if (!this.img || !this.cssW || !this.cssH) { this.requestRender(); return; }
      this.fitScale = Math.min(this.cssW / this.W, this.cssH / this.H) * CFG.view.fitMargin;
      this.s = this.fitScale;
      this.tx = (this.cssW - this.W * this.s) / 2;
      this.ty = (this.cssH - this.H * this.s) / 2;
      this._emit(); this.requestRender();
    }

    // ซูมให้พอดีกรอบ [x1,y1,x2,y2] เผื่อขอบ margin (สัดส่วนของขนาดกรอบ แต่ละด้าน)
    fitBox(b, margin = 0.15) {
      if (!this.img || !this.cssW || !this.cssH || !b) { this.resetView(); return; }
      const bw = Math.max(1, (b[2] - b[0]) * (1 + 2 * margin));
      const bh = Math.max(1, (b[3] - b[1]) * (1 + 2 * margin));
      const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
      this.s = this._clampScale(Math.min(this.cssW / bw, this.cssH / bh));
      this.tx = this.cssW / 2 - cx * this.s;
      this.ty = this.cssH / 2 - cy * this.s;
      this._emit(); this.requestRender();
    }

    setView(s, tx, ty) { this.s = s; this.tx = tx; this.ty = ty; this._emit(); this.requestRender(); }

    // ---------- ปรับความสว่าง/ความเปรียบต่าง/กลับสี (แสดงผลเท่านั้น) ----------
    setAdjust(a) {
      this.adjust = Object.assign({}, this.adjust, a);
      clearTimeout(this._adjTimer);
      this._adjTimer = setTimeout(() => { this._buildAdjusted(); this.requestRender(); }, 60);
    }

    _isDefaultAdjust() {
      const a = this.adjust;
      return a.brightness === 1 && a.contrast === 1 && !a.invert;
    }

    _buildAdjusted() {
      if (!this.img || this._isDefaultAdjust()) { this._src = null; return; }
      const { brightness: b, contrast: c, invert } = this.adjust;
      const lut = new Uint8ClampedArray(256);
      for (let v = 0; v < 256; v++) {
        let x = (v / 255) * b;
        x = (x - 0.5) * c + 0.5;
        if (invert) x = 1 - x;
        lut[v] = Math.round(x * 255);
      }
      const cv = this._src || document.createElement('canvas');
      cv.width = this.W; cv.height = this.H;
      const ctx = cv.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(this.img, 0, 0);
      const im = ctx.getImageData(0, 0, this.W, this.H);
      const d = im.data;
      for (let i = 0; i < d.length; i += 4) { d[i] = lut[d[i]]; d[i + 1] = lut[d[i + 1]]; d[i + 2] = lut[d[i + 2]]; }
      ctx.putImageData(im, 0, 0);
      this._src = cv;
    }

    _source() { return this._src || this.img; }
    _userView() { if (this.opts.onUserView) this.opts.onUserView(); }

    _clampScale(s) {
      const v = CFG.view;
      const min = this.fitScale * v.minZoomRelative;
      const max = Math.max(this.fitScale, v.maxScreenPxPerImagePx);   // 1 px จอ ≥ 0.1 px ภาพ
      return Math.min(max, Math.max(min, s));
    }

    zoomAt(cx, cy, newScale) {
      const p = this.screenToImage(cx, cy);
      this.s = this._clampScale(newScale);
      this.tx = cx - p.x * this.s;
      this.ty = cy - p.y * this.s;
      this._emit(); this.requestRender();
    }

    // ขนาดช่องเปลี่ยน: ไม่ยกเลิกการวางจุด (การวางใช้พิกัดหน้าจอ ไม่ขึ้นกับตำแหน่ง/ขนาดช่อง)
    _resize() {
      // ขนาดจริงแบบมีทศนิยม (clientWidth/Height ปัดเป็นจำนวนเต็ม -> ภาพยืดเล็กน้อยเมื่อช่องสูง เช่น 457.5 px)
      const rc = this.container.getBoundingClientRect();
      const w = rc.width, h = rc.height;
      if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1;
      const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
      if (w === this.cssW && h === this.cssH && this.canvas.width === bw && this.canvas.height === bh) return;
      const hadView = this.img && this.cssW > 0;
      const c = hadView ? this.screenToImage(this.cssW / 2, this.cssH / 2) : null;
      this.cssW = w; this.cssH = h;
      this.canvas.width = bw;
      this.canvas.height = bh;
      if (hadView) {
        const oldFit = this.fitScale;
        this.fitScale = Math.min(w / this.W, h / this.H) * CFG.view.fitMargin;
        this.s = this._clampScale(this.s * (this.fitScale / oldFit));
        this.tx = w / 2 - c.x * this.s;
        this.ty = h / 2 - c.y * this.s;
        this._emit();
      } else {
        this.resetView();
      }
      this.requestRender();
    }

    // ---------- วาด ----------
    requestRender() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = 0; this.render(); });
    }

    _points() { return this.opts.getPoints ? this.opts.getPoints() : []; }

    render() {
      const ctx = this.ctx, c = this.canvas;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = '#111';
      ctx.fillRect(0, 0, c.width, c.height);
      if (!this.cssW) return;
      const kx = c.width / this.cssW, ky = c.height / this.cssH;

      if (!this.img) {
        if (this.message) {
          ctx.setTransform(kx, 0, 0, ky, 0, 0);
          ctx.fillStyle = '#aaa';
          ctx.font = '16px system-ui, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(this.message, this.cssW / 2, this.cssH / 2);
        }
        return;
      }

      ctx.imageSmoothingEnabled = this.s < CFG.view.pixelatedAboveScale;
      ctx.setTransform(this.s * kx, 0, 0, this.s * ky, this.tx * kx, this.ty * ky);
      ctx.drawImage(this._source(), 0, 0, this.W, this.H);

      // ชั้นทับ (หน่วย CSS px)
      ctx.setTransform(kx, 0, 0, ky, 0, 0);
      if (this.opts.onOverlay) this.opts.onOverlay(ctx, this);
      const ses = this.session;
      for (const p of this._points()) {
        if (ses && ses.mode === 'move' && ses.idx === p.idx) continue;
        const q = this.imageToScreen(p.x, p.y);
        this._drawMark(ctx, q.x, q.y, p.idx, p.selected ? 'selected' : 'normal');
      }
      if (ses) {
        const q = this.imageToScreen(ses.point.x, ses.point.y);
        this._drawMark(ctx, q.x, q.y, ses.idx, 'active');
        this._drawLoupe(ctx, kx, ky);
      }
    }

    _drawMark(ctx, x, y, idx, style) {
      const color = CFG.marks.colors[idx] || '#fff';
      const r = style === 'normal' ? 8 : 10;
      ctx.save();
      for (const [w, col] of [[4, 'rgba(0,0,0,0.85)'], [style === 'normal' ? 2 : 2.5, color]]) {
        ctx.lineWidth = w; ctx.strokeStyle = col;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        // ขีดสั้นนอกวง (ไม่บังจุดกึ่งกลาง)
        ctx.moveTo(x - r - 6, y); ctx.lineTo(x - r, y);
        ctx.moveTo(x + r, y); ctx.lineTo(x + r + 6, y);
        ctx.moveTo(x, y - r - 6); ctx.lineTo(x, y - r);
        ctx.moveTo(x, y + r); ctx.lineTo(x, y + r + 6);
        ctx.stroke();
      }
      if (style === 'selected') {
        ctx.setLineDash([3, 3]); ctx.lineWidth = 1.5; ctx.strokeStyle = '#fff';
        ctx.beginPath(); ctx.arc(x, y, r + 10, 0, Math.PI * 2); ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.font = 'bold 16px system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(0,0,0,0.9)';
      ctx.strokeText(String(idx + 1), x + r + 6, y - r - 6);
      ctx.fillStyle = color;
      ctx.fillText(String(idx + 1), x + r + 6, y - r - 6);
      ctx.restore();
    }

    _loupeRect() {
      const ses = this.session;
      const m = 10;
      const D = Math.max(80, Math.min(CFG.loupe.sizePx, this.cssW - 2 * m, this.cssH - 2 * m));
      const ptr = this.pointers.get(ses.id) || this.imageToScreen(ses.point.x, ses.point.y);
      // วางแว่นขยายมุมที่ไกลจากนิ้ว (นิ้วไม่บัง)
      const cx = ptr.x < this.cssW / 2 ? this.cssW - m - D / 2 : m + D / 2;
      const cy = ptr.y > D + 3 * m ? m + D / 2 : this.cssH - m - D / 2 - 22;
      return { cx, cy, D };
    }

    _drawLoupe(ctx, kx, ky) {
      const ses = this.session;
      const { cx, cy, D } = this._loupeRect();
      const sL = ses.sL, pu = ses.point.x, pv = ses.point.y;
      const color = CFG.marks.colors[ses.idx] || '#fff';
      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, D / 2, 0, Math.PI * 2); ctx.clip();
      ctx.fillStyle = '#000'; ctx.fillRect(cx - D / 2, cy - D / 2, D, D);
      ctx.imageSmoothingEnabled = false;
      ctx.setTransform(kx * sL, 0, 0, ky * sL, kx * (cx - pu * sL), ky * (cy - pv * sL));
      ctx.drawImage(this._source(), 0, 0, this.W, this.H);
      ctx.setTransform(kx, 0, 0, ky, 0, 0);
      // จุดอื่นที่อยู่ในแว่น
      for (const p of this._points()) {
        if (ses.mode === 'move' && p.idx === ses.idx) continue;
        const x = cx + (p.x - pu) * sL, y = cy + (p.y - pv) * sL;
        if (Math.hypot(x - cx, y - cy) < D / 2 + 20) this._drawMark(ctx, x, y, p.idx, 'normal');
      }
      // กากบาทกลางแว่น = ตำแหน่งจุดที่จะบันทึก
      const arm = D / 2, gap = 6;
      // _testHideLoupeCross: ให้สคริปต์ทดสอบซ่อนกากบาทชั่วคราว เพื่อตรวจพิกเซลของภาพในแว่น
      for (const [w, col] of (this._testHideLoupeCross ? [] : [[3, 'rgba(0,0,0,0.8)'], [1, color]])) {
        ctx.lineWidth = w; ctx.strokeStyle = col;
        ctx.beginPath();
        ctx.moveTo(cx - arm, cy); ctx.lineTo(cx - gap, cy);
        ctx.moveTo(cx + gap, cy); ctx.lineTo(cx + arm, cy);
        ctx.moveTo(cx, cy - arm); ctx.lineTo(cx, cy - gap);
        ctx.moveTo(cx, cy + gap); ctx.lineTo(cx, cy + arm);
        ctx.stroke();
      }
      ctx.restore();
      ctx.lineWidth = 3; ctx.strokeStyle = color;
      ctx.beginPath(); ctx.arc(cx, cy, D / 2, 0, Math.PI * 2); ctx.stroke();
      const label = `จุด ${ses.idx + 1}  (${pu.toFixed(1)}, ${pv.toFixed(1)})  ×${sL.toFixed(1)}`;
      ctx.font = '13px system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(0,0,0,0.9)';
      ctx.strokeText(label, cx, cy + D / 2 + 4);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, cx, cy + D / 2 + 4);
    }

    _emit() {
      if (this.opts.onInfo) {
        this.opts.onInfo({
          hover: this.hover, zoom: this.img ? this.zoom : null, W: this.W, H: this.H,
          session: this.session ? { idx: this.session.idx, x: this.session.point.x, y: this.session.point.y } : null,
        });
      }
    }

    // ---------- อินพุต ----------
    _bindEvents() {
      const c = this.canvas;
      c.addEventListener('pointerdown', (e) => this._onDown(e));
      c.addEventListener('pointermove', (e) => this._onMove(e));
      c.addEventListener('pointerup', (e) => this._onUp(e, false));
      c.addEventListener('pointercancel', (e) => this._onUp(e, true));
      c.addEventListener('pointerleave', (e) => {
        if (!this.pointers.has(e.pointerId) && this.hover) { this.hover = null; this._emit(); }
      });
      c.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });
      c.addEventListener('contextmenu', (e) => e.preventDefault());
    }

    _hitTest(p) {
      let best = null, bestD = CFG.marks.hitRadiusPx;
      for (const pt of this._points()) {
        const q = this.imageToScreen(pt.x, pt.y);
        const d = Math.hypot(q.x - p.x, q.y - p.y);
        if (d <= bestD) { best = pt.idx; bestD = d; }
      }
      return best;
    }

    _onDown(e) {
      if (!this.img) return;
      e.preventDefault();
      try { this.canvas.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      const p = this._local(e);
      this.pointers.set(e.pointerId, { x: p.x, y: p.y, cx: e.clientX, cy: e.clientY, type: e.pointerType });

      if (this.pointers.size === 2) {
        // นิ้วที่สองแตะ -> ยกเลิกการวางจุด แล้ว pinch
        this._clearTimer();
        if (this.session) this.cancelSession();
        this._startPinch();
        return;
      }
      if (this.pointers.size > 2) return;

      const type = e.pointerType;
      const base = { id: e.pointerId, x0: p.x, y0: p.y, tx0: this.tx, ty0: this.ty, t0: performance.now(), pointerType: type };
      if (type === 'mouse' && e.button !== 0) { this.gesture = Object.assign({ type: 'pan' }, base); return; }

      const hit = this._hitTest(p);
      if (type === 'pen' || (type === 'mouse' && hit != null)) {
        // ปากกา: วาง/ลากทันที · เมาส์บนจุดเดิม: ลากทันที
        const client = { x: e.clientX, y: e.clientY };
        if (hit != null) this._startSession('move', hit, e.pointerId, p, client);
        else this._tryStartNew(e.pointerId, p, client);
        return;
      }

      const fingerMode = this.opts.isFingerMode ? this.opts.isFingerMode() : false;
      const canHold = type === 'mouse' || hit != null || fingerMode;
      const holdMs = type === 'mouse' ? CFG.input.mouseHoldMs
        : hit != null ? CFG.input.touchHoldPointMs : CFG.input.touchHoldPlaceMs;
      this.gesture = Object.assign({ type: 'pending', hit }, base);
      if (canHold) this.gesture.timer = setTimeout(() => this._onHold(), holdMs);
    }

    _onHold() {
      const g = this.gesture;
      if (!g || g.type !== 'pending') return;
      g.timer = 0;
      const ptr = this.pointers.get(g.id);
      if (!ptr) return;
      const press = { x: g.x0, y: g.y0 }, now = { x: ptr.cx, y: ptr.cy };   // now = พิกัดหน้าจอ (client)
      if (g.hit != null) this._startSession('move', g.hit, g.id, press, now);
      else this._tryStartNew(g.id, press, now);
    }

    _tryStartNew(id, press, anchor) {
      const idx = this.opts.nextIndex ? this.opts.nextIndex() : null;
      if (idx == null) {
        this.gesture = { type: 'idle', id };
        if (this.opts.onBlocked) this.opts.onBlocked();
        return;
      }
      this._startSession('new', idx, id, press, anchor);
    }

    // press = จุดที่กด (พิกัดใน canvas) · anchor = ตำแหน่งนิ้วตอนเริ่ม (พิกัดหน้าจอ clientX/Y)
    _startSession(mode, idx, id, press, anchor) {
      let start;
      if (mode === 'move') {
        const pt = this._points().find((q) => q.idx === idx);
        if (!pt) { this.gesture = { type: 'idle', id }; return; }
        start = { x: pt.x, y: pt.y };
      } else {
        start = this.clampToImage(this.screenToImage(press.x, press.y));
      }
      this.session = { mode, idx, id, start, anchor: { x: anchor.x, y: anchor.y }, point: { x: start.x, y: start.y }, sL: this.loupeScale() };
      this.gesture = { type: 'session', id };
      if (this.opts.onSessionStart) this.opts.onSessionStart(mode, idx);
      if (navigator.vibrate) { try { navigator.vibrate(10); } catch (_) { /* ignore */ } }
      this._emit(); this.requestRender();
    }

    cancelSession() {
      if (!this.session) return;
      this.session = null;
      if (this.gesture && this.gesture.type === 'session') this.gesture.type = 'idle';
      this._emit(); this.requestRender();
    }

    _commitSession() {
      const s = this.session;
      this.session = null;
      this._emit(); this.requestRender();
      if (this.opts.onCommit) this.opts.onCommit({ mode: s.mode, idx: s.idx, x: s.point.x, y: s.point.y, ipp: 1 / s.sL });
    }

    _clearTimer() {
      const g = this.gesture;
      if (g && g.timer) { clearTimeout(g.timer); g.timer = 0; }
    }

    _abortGesture() {
      this._clearTimer();
      this.session = null;
      this.gesture = null;
      this.pointers.clear();
    }

    _onMove(e) {
      const p = this._local(e);
      if ((e.pointerType === 'mouse' || e.pointerType === 'pen') && this.img) {
        this.hover = this.screenToImage(p.x, p.y);
        this._emit();
      }
      const ptr = this.pointers.get(e.pointerId);
      if (!ptr) return;
      e.preventDefault();
      ptr.x = p.x; ptr.y = p.y; ptr.cx = e.clientX; ptr.cy = e.clientY;
      const g = this.gesture;
      if (!g) return;
      if (g.type === 'pinch') { this._updatePinch(); return; }
      if (g.id !== e.pointerId) return;

      if (g.type === 'session' && this.session) {
        const s = this.session;
        // ใช้ระยะที่นิ้วขยับบนหน้าจอ (client) -> ถ้าช่องขยับ/เปลี่ยนขนาดระหว่างวาง จุดไม่กระโดด
        s.point = this.clampToImage({
          x: s.start.x + (e.clientX - s.anchor.x) / s.sL,
          y: s.start.y + (e.clientY - s.anchor.y) / s.sL,
        });
        this._emit(); this.requestRender();
        return;
      }
      if (g.type === 'pending' && Math.hypot(p.x - g.x0, p.y - g.y0) > CFG.input.tapSlopPx) {
        this._clearTimer();
        g.type = 'pan';
      }
      if (g.type === 'pan') {
        this.tx = g.tx0 + (p.x - g.x0);
        this.ty = g.ty0 + (p.y - g.y0);
        this._userView();
        this._emit(); this.requestRender();
      }
    }

    _onUp(e, cancelled) {
      if (!this.pointers.has(e.pointerId)) return;
      this.pointers.delete(e.pointerId);
      const g = this.gesture;

      if (g && g.id === e.pointerId) {
        if (g.type === 'session' && this.session) {
          if (cancelled) this.cancelSession(); else this._commitSession();
        } else if (g.type === 'pending') {
          this._clearTimer();
          const quick = g.pointerType === 'mouse' || performance.now() - g.t0 <= CFG.input.tapMaxMs;
          if (!cancelled && quick && this.opts.onTap) this.opts.onTap(g.pointerType, g.hit);
        }
      }

      if (g && g.type === 'pinch' && this.pointers.size === 1) {
        const [id, rest] = [...this.pointers.entries()][0];
        this.gesture = { type: 'pan', id, x0: rest.x, y0: rest.y, tx0: this.tx, ty0: this.ty };
      } else if (this.pointers.size === 0) {
        this.gesture = null;
      }
    }

    _startPinch() {
      const [a, b] = [...this.pointers.values()];
      const m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      this.gesture = {
        type: 'pinch',
        d0: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
        s0: this.s,
        p0: this.screenToImage(m.x, m.y),
      };
    }

    _updatePinch() {
      const g = this.gesture;
      const [a, b] = [...this.pointers.values()];
      if (!a || !b) return;
      const m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const d = Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
      this.s = this._clampScale(g.s0 * d / g.d0);
      this.tx = m.x - g.p0.x * this.s;
      this.ty = m.y - g.p0.y * this.s;
      this._userView();
      this._emit(); this.requestRender();
    }

    _onWheel(e) {
      if (!this.img) return;
      e.preventDefault();
      if (this.session) return;            // ระหว่างวางจุด ห้ามซูม (สเกลแว่นต้องคงที่)
      const p = this._local(e);
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? this.cssH : 1;
      const speed = e.ctrlKey ? CFG.view.pinchWheelZoomSpeed : CFG.view.wheelZoomSpeed;
      this.zoomAt(p.x, p.y, this.s * Math.exp(-e.deltaY * unit * speed));
      this._userView();
    }
  }

  window.ImageViewer = ImageViewer;
})();
