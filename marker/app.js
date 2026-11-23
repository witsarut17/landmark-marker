// app.js: เชื่อมหน้าจอ + Loader + ImageViewer + การมาร์ก + บันทึกขึ้นเซิร์ฟเวอร์ (v1.0: ภาพและจุดอยู่บนเซิร์ฟเวอร์)
// ขั้น 4: นำทาง, มาร์กไม่ได้/partial, เวลา, กรอบ, ปรับภาพ, เตือนจุดกระจุก
// ขั้น 5: บันทึกอัตโนมัติ (IndexedDB), บังคับสำรอง, ส่งออก/นำเข้า
(function () {
  'use strict';
  const CFG = window.MARKER_CONFIG;
  const N = CFG.marks.count;
  const SIDES = ['xray', 'fluoro'];
  const SIDE_NAME = { xray: 'เอกซเรย์', fluoro: 'ฟลู' };
  const FINAL = new Set(['done', 'partial', 'unmarkable']);
  // skipped = หมอกด "ข้ามไปก่อน" (ยังไม่เสร็จ) — คงสถานะนี้ไว้จนกว่างานจะเสร็จ (done/partial/unmarkable)
  const STATUS_NAME = { todo: 'ยังไม่ทำ', in_progress: 'กำลังทำ', skipped: 'ข้ามไว้', done: 'เสร็จ 4 คู่', partial: 'เสร็จ 3 คู่', unmarkable: 'มาร์กไม่ได้' };
  const REASONS = {
    unmarkable: [['unclear', 'ภาพไม่ชัด'], ['no_overlap', 'ไม่มีบริเวณร่วมกัน'], ['view_angle', 'มุมถ่ายต่างกันมาก'], ['other', 'อื่น ๆ (พิมพ์เหตุผล)']],
    partial: [['no_4th_point', 'หาจุดที่ 4 ที่เห็นชัดทั้งสองภาพไม่ได้'], ['unclear', 'ภาพไม่ชัด'], ['view_angle', 'มุมถ่ายต่างกันมาก'], ['other', 'อื่น ๆ (พิมพ์เหตุผล)']],
  };
  // คำแนะนำการเลือกจุด (ใช้ทั้งแถบคำแนะนำและหน้าแรก)
  const POINT_TIP = 'เลือกจุดที่ชัดและไม่เปลี่ยนรูปตามมุมถ่าย เช่น ขอบรูกระดูก ปลายสกรู มุมแผ่นโลหะ';
  const NOTE_MAX = 300;
  const REASON_NAME = Object.fromEntries([...REASONS.unmarkable, ...REASONS.partial]);
  const $ = (id) => document.getElementById(id);
  const r1 = (v) => Math.round(v * 10) / 10;
  const fmt = (v) => r1(v).toFixed(1);
  const nowISO = () => new Date().toISOString();
  const timeTH = (iso) => (iso ? new Date(iso).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'medium' }) : '—');
  const el = (tag, props = {}, kids = []) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
    }
    for (const k of [].concat(kids)) if (k != null) e.append(k);
    return e;
  };

  // ---------- ดีบัก ----------
  const Debug = (() => {
    const lines = [];
    const logEl = $('debugLog');
    function add(msg, isErr) {
      lines.push({ t: new Date().toLocaleTimeString(), msg: String(msg), isErr });
      if (lines.length > 300) lines.shift();
      if (!$('debugPanel').hidden) render();
    }
    function render() {
      logEl.innerHTML = '';
      for (const l of lines) logEl.appendChild(el('div', { class: l.isErr ? 'e' : '', text: `[${l.t}] ${l.msg}` }));
      logEl.scrollTop = logEl.scrollHeight;
    }
    return { log: (m) => add(m, false), error: (m) => add(m, true), render, clear: () => { lines.length = 0; render(); },
      entries: () => lines.slice() };
  })();
  window.addEventListener('error', (e) => {
    // "Script error." ไม่มีชื่อไฟล์ = มาจากสคริปต์นอกเว็บนี้ (ระบบ/ส่วนขยายของเบราว์เซอร์)
    // สคริปต์ของเว็บนี้อยู่โดเมนเดียวกันทั้งหมด ถ้าผิดจะมีชื่อไฟล์และบรรทัดเสมอ
    if (!e.filename && /^Script error\.?$/i.test(e.message || '')) {
      Debug.log('ข้อผิดพลาดจากสคริปต์นอกเว็บนี้ (ระบบ/ส่วนขยายของ Safari) — ไม่มีผลกับงาน');
      return;
    }
    Debug.error(`${e.message} @ ${e.filename}:${e.lineno}${e.error && e.error.stack ? ' | ' + e.error.stack.split('\n')[0] : ''}`);
  });
  document.addEventListener('securitypolicyviolation', (e) =>
    Debug.log(`CSP บล็อก: ${e.violatedDirective} ${e.blockedURI || ''} (${e.sourceFile || 'ไม่ทราบที่มา'})`));
  window.addEventListener('unhandledrejection', (e) => Debug.error(`Promise: ${e.reason && (e.reason.stack || e.reason)}`));
  const pointerTypesSeen = new Set();
  window.addEventListener('pointerdown', (e) => pointerTypesSeen.add(e.pointerType), true);

  // ---------- สถานะ ----------
  const state = {
    manifest: null, byName: null, index: 0, loadToken: 0, urls: [],
    tasks: {},            // task_id -> งาน (บันทึกลงเครื่อง)
    undo: {},             // task_id -> [snapshot] (ไม่บันทึก)
    meta: { last_backup_at: null, last_backup_completed: 0, backup_snoozed: false, snooze_until: 0, saved_at: null },
    selected: null, fingerMode: false, showBox: true, xView: 'box',
    storage: { ok: false, reason: 'ยังไม่ได้ตรวจ', persisted: null },
    imagesReady: false, fluoroArea: null,
    lastInteraction: Date.now(), saveError: null, busy: false,
    // การศึกษา ทีมมาร์ก-หมอตรวจ (v1.3): manifest มี cases -> หน้ารายการเคส · mode 'mark' (ทีม) / 'review' (หมอ)
    mode: null, cases: null, caseOfIndex: [], seeds: {},
  };
  try {
    state.fingerMode = localStorage.getItem('fingerMode') === '1';
    state.showBox = localStorage.getItem('showBox') !== '0';
  } catch (_) { /* ignore */ }

  const currentItem = () => (state.manifest ? state.manifest.items[state.index] : null);
  const VIEW_KEY = 'pelnavInTask';                 // อยู่ในงาน (ไม่ใช่หน้ารายการ) — ใช้ตอนโหลดหน้าใหม่ (อัปเดตเอง)
  const caseMode = () => !!state.cases;
  const newTask = () => ({
    xray: new Array(N).fill(null), fluoro: new Array(N).fill(null),
    status: 'todo', reason: null, reason_text: null, note: null,
    started_at: null, finished_at: null, duration_ms: 0, updated_at: null,
  });
  function task() {
    const it = currentItem();
    if (!it) return null;
    if (!state.tasks[it.task_id]) state.tasks[it.task_id] = seededTask(it.task_id);
    return state.tasks[it.task_id];
  }
  // หมอตรวจ: งานเริ่มจากจุดของทีม (สำเนา) · จุดของทีมบนเซิร์ฟเวอร์ไม่ถูกแก้
  function seededTask(tid) {
    const t = newTask();
    const s = state.mode === 'review' ? state.seeds[tid] : null;
    if (s) {
      for (const side of ['xray', 'fluoro']) {
        const src = Array.isArray(s[side]) ? s[side] : [];
        t[side] = [...Array(N).keys()].map((i) => (src[i] ? { x: src[i].x, y: src[i].y,
          image_px_per_screen_px: src[i].image_px_per_screen_px, at: src[i].at } : null));
      }
    }
    return t;
  }
  // จำนวนจุดที่หมอแก้ (ย้าย/เพิ่ม/ลบ) เทียบกับจุดของทีม
  function reviewEdits(tid, t) {
    const s = state.seeds[tid];
    let n = 0;
    for (const side of ['xray', 'fluoro']) {
      for (let i = 0; i < N; i++) {
        const a = s && s[side] ? s[side][i] : null, b = t[side][i];
        if (!!a !== !!b) n++;
        else if (a && b && Math.hypot(a.x - b.x, a.y - b.y) > 0.05) n++;
      }
    }
    return n;
  }
  const pairCount = (t) => [...Array(N).keys()].filter((i) => t.xray[i] && t.fluoro[i]).length;
  const hasOrphans = (t) => [...Array(N).keys()].some((i) => !!t.xray[i] !== !!t.fluoro[i]);
  const completedCount = () => Object.values(state.tasks).filter((t) => FINAL.has(t.status)).length;
  const skippedCount = () => Object.values(state.tasks).filter((t) => t.status === 'skipped').length;
  const statusAt = (i) => ((state.tasks[state.manifest.items[i].task_id] || {}).status || 'todo');
  const totalTasks = () => (state.manifest ? state.manifest.items.length : 0);

  function activeIndex(t) {
    for (let i = 0; i < N; i++) if (!t.xray[i] || !t.fluoro[i]) return i;
    return null;
  }
  function nextIndexFor(side) {
    const t = task();
    if (!t) return null;
    const k = activeIndex(t);
    if (k == null || t[side][k]) return null;
    return k;
  }
  function blockedMessage(side) {
    const k = activeIndex(task());
    if (k == null) return 'ครบ 4 คู่แล้ว — ถ้าจะปรับ ให้ลากจุดเดิม';
    const other = side === 'xray' ? 'fluoro' : 'xray';
    return `จุด ${k + 1} วางบน${SIDE_NAME[side]}แล้ว — ต่อไปวางจุด ${k + 1} บน${SIDE_NAME[other]}`;
  }

  // งานถูกแก้ -> ปรับสถานะให้สอดคล้อง + บันทึก
  function touchTask(t) {
    t.updated_at = nowISO();
    if (t.status === 'todo') t.status = 'in_progress';
    const pc = pairCount(t);
    if (t.status === 'done' && pc < N) t.status = 'in_progress';
    if (t.status === 'partial' && !(pc === N - 1 && !hasOrphans(t))) t.status = 'in_progress';
    if (FINAL.has(t.status)) t.finished_at = t.updated_at;   // Q7: แก้ครั้งล่าสุด
    save();
  }

  function pushUndo(t) {
    const id = currentItem().task_id;
    const u = state.undo[id] || (state.undo[id] = []);
    u.push(JSON.stringify({ xray: t.xray, fluoro: t.fluoro }));
    if (u.length > CFG.marks.undoLimit) u.shift();
  }

  function commitPoint(side, c) {
    const t = task();
    if (!t) return;
    if (c.mode === 'new') {
      const k = nextIndexFor(side);
      if (k == null || k !== c.idx) { toast(blockedMessage(side)); return; }
    } else if (!t[side][c.idx]) return;
    pushUndo(t);
    t[side][c.idx] = { x: r1(c.x), y: r1(c.y), image_px_per_screen_px: Math.round(c.ipp * 10000) / 10000, at: nowISO() };
    state.selected = { side, idx: c.idx };
    Debug.log(`${currentItem().task_id} ${c.mode === 'new' ? 'วาง' : 'ย้าย'} จุด ${c.idx + 1} ${SIDE_NAME[side]} (${fmt(c.x)}, ${fmt(c.y)})`);
    touchTask(t);
    refreshMarks();
  }

  function deleteSelected() {
    const t = task();
    const sel = state.selected;
    if (!t || !sel || !t[sel.side][sel.idx]) return;
    pushUndo(t);
    t[sel.side][sel.idx] = null;
    toast(`ลบจุด ${sel.idx + 1} บน${SIDE_NAME[sel.side]}แล้ว`);
    state.selected = null;
    touchTask(t);
    refreshMarks();
  }

  function undo() {
    const t = task();
    const u = t && state.undo[currentItem().task_id];
    if (!u || !u.length) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    const prev = JSON.parse(u.pop());
    t.xray = prev.xray; t.fluoro = prev.fluoro;
    state.selected = null;
    toast('ย้อนแล้ว');
    touchTask(t);
    refreshMarks();
  }

  function pointsFor(side) {
    const t = task();
    if (!t) return [];
    const out = [];
    t[side].forEach((p, idx) => {
      if (p) out.push({ idx, x: p.x, y: p.y, selected: !!(state.selected && state.selected.side === side && state.selected.idx === idx) });
    });
    return out;
  }

  // ---------- ตัวช่วยของทีม (โหมดมาร์ก): คาดตำแหน่งจุดที่ 4 + เตือนจุดที่อาจไม่ตรงคู่ ----------
  // ใช้การแปลงแบบ affine จาก 3 คู่ (พอดีเป๊ะ) · ไม่แสดงให้หมอ
  const assistOn = () => state.mode === 'mark' && !!(CFG.teamAssist && CFG.teamAssist.enabled);
  function affineFit(src, dst) {
    const [p1, p2, p3] = src;
    const det = p1.x * (p2.y - p3.y) - p2.x * (p1.y - p3.y) + p3.x * (p1.y - p2.y);
    const span = Math.max(Math.hypot(p2.x - p1.x, p2.y - p1.y), Math.hypot(p3.x - p1.x, p3.y - p1.y), 1);
    if (Math.abs(det) < 1e-3 * span * span) return null;            // 3 จุดเกือบอยู่แนวเดียวกัน
    const solve = (k) => {
      const [a, b, c] = dst.map((q) => q[k]);
      return [
        (a * (p2.y - p3.y) - b * (p1.y - p3.y) + c * (p1.y - p2.y)) / det,
        (p1.x * (b - c) - p2.x * (a - c) + p3.x * (a - b)) / det,
        (p1.x * (p2.y * c - p3.y * b) - p2.x * (p1.y * c - p3.y * a) + p3.x * (p1.y * b - p2.y * a)) / det,
      ];
    };
    return { x: solve('x'), y: solve('y') };
  }
  const applyAff = (A, p) => ({ x: A.x[0] * p.x + A.x[1] * p.y + A.x[2], y: A.y[0] * p.x + A.y[1] * p.y + A.y[2] });
  // ตำแหน่งที่คาดของจุด k บน side (เมื่ออีกภาพมีจุด k แล้ว หรือกำลังวางอยู่ และมีคู่ครบอย่างน้อย 3 คู่)
  function ghostFor(side) {
    if (!assistOn() || !CFG.teamAssist.showPrediction) return null;
    const t = task();
    if (!t) return null;
    const k = activeIndex(t);
    if (k == null || t[side][k]) return null;
    const other = side === 'xray' ? 'fluoro' : 'xray';
    let src = t[other][k];
    const ses = info[other] && info[other].session;
    if (ses && ses.idx === k) src = { x: ses.x, y: ses.y };
    if (!src) return null;
    const pairs = [...Array(N).keys()].filter((i) => i !== k && t.xray[i] && t.fluoro[i]).slice(0, 3);
    if (pairs.length < 3) return null;
    const A = affineFit(pairs.map((i) => t[other][i]), pairs.map((i) => t[side][i]));
    return A ? { k, ...applyAff(A, src) } : null;
  }
  function drawGhost(ctx, v, side) {
    const g = ghostFor(side);
    if (!g) return;
    const q = v.imageToScreen(g.x, g.y);
    ctx.save();
    ctx.globalAlpha = 0.6;
    ctx.strokeStyle = CFG.marks.colors[g.k] || '#fff';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath(); ctx.arc(q.x, q.y, 18, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(q.x - 6, q.y); ctx.lineTo(q.x + 6, q.y); ctx.moveTo(q.x, q.y - 6); ctx.lineTo(q.x, q.y + 6); ctx.stroke();
    ctx.font = '12px system-ui, sans-serif'; ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(`คาด ${g.k + 1}`, q.x + 21, q.y - 8);
    ctx.restore();
  }
  // ครบ 4 คู่: ทายแต่ละจุดเอกซเรย์จากอีก 3 คู่ (ต่างกันเท่าไร = ต้องย้ายจุดนั้นเท่าไรให้สอดคล้อง)
  // 4 คู่ระบุไม่ได้ทางคณิตศาสตร์ว่าจุดไหนผิด (ย้ายจุดใดจุดหนึ่งก็แก้ได้) จึง: เตือนเมื่อแม้แก้จุดที่แก้ง่ายที่สุดก็ยังเกินเกณฑ์
  // และชี้คู่ที่วาง/ย้ายล่าสุด (มักเป็นคู่ที่เพิ่งวางผิด)
  function mismatchWarning() {
    if (!assistOn()) return '';
    const t = task(), it = currentItem();
    if (!t || !it || pairCount(t) < N) return '';
    const b = it.box_xyxy;
    const diag = Math.hypot(b[2] - b[0], b[3] - b[1]) || 1;
    const err = [];
    for (let i = 0; i < N; i++) {
      const o = [...Array(N).keys()].filter((j) => j !== i);
      const A = affineFit(o.map((j) => t.fluoro[j]), o.map((j) => t.xray[j]));
      if (!A) return '';                                  // 3 จุดเกือบแนวเดียวกัน — มีคำเตือนการกระจายอยู่แล้ว
      const p = applyAff(A, t.fluoro[i]);
      err.push((100 * Math.hypot(p.x - t.xray[i].x, p.y - t.xray[i].y)) / diag);
    }
    if (Math.min(...err) <= CFG.teamAssist.mismatchPct) return '';
    const last = (i) => [t.xray[i].at || '', t.fluoro[i].at || ''].sort().pop();
    let k = 0;
    for (let i = 1; i < N; i++) if (last(i) > last(k)) k = i;
    return `จุด ${k + 1} อาจไม่ตรงคู่ (ไม่สอดคล้องกับอีก 3 คู่ ~${Math.round(err[k])}% ของกรอบ) — ตรวจคู่นี้ก่อน`;
  }

  // ---------- ตรวจการกระจายของจุด (เตือน ไม่บล็อก) ----------
  function convexHull(pts) {
    const p = pts.map((q) => [q.x, q.y]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return p;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (const q of p.slice().reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }
  function polyArea(h) {
    let a = 0;
    for (let i = 0; i < h.length; i++) { const [x1, y1] = h[i], [x2, y2] = h[(i + 1) % h.length]; a += x1 * y2 - x2 * y1; }
    return Math.abs(a) / 2;
  }
  function minAngleDeg(h) {
    let m = 180;
    for (let i = 0; i < h.length; i++) {
      const a = h[(i + h.length - 1) % h.length], b = h[i], c = h[(i + 1) % h.length];
      const v1 = [a[0] - b[0], a[1] - b[1]], v2 = [c[0] - b[0], c[1] - b[1]];
      const cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (Math.hypot(...v1) * Math.hypot(...v2) || 1);
      m = Math.min(m, Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI);
    }
    return m;
  }
  function refArea(side) {
    const it = currentItem();
    if (side === 'xray') { const b = it.box_xyxy; return (b[2] - b[0]) * (b[3] - b[1]); }
    return state.fluoroArea || it.fluoro_size[0] * it.fluoro_size[1];
  }
  function spreadWarning(side) {
    const t = task();
    const pts = t[side].filter(Boolean);
    if (pts.length < 3) return null;
    const h = convexHull(pts);
    const q = CFG.quality;
    if (h.length < 3 || minAngleDeg(h) < q.collinearMinAngleDeg) return `จุดบน${SIDE_NAME[side]}เกือบอยู่แนวเดียวกัน`;
    if (polyArea(h) < q.minHullAreaFraction * refArea(side)) {
      return `จุดบน${SIDE_NAME[side]}กระจุกตัว (เทียบ${side === 'xray' ? 'กรอบ' : 'วงกลมภาพ'})`;
    }
    return null;
  }

  // ฟลู: พื้นที่วงกลม ≈ พื้นที่ส่วนที่ไม่ดำ (นอกวงกลมถูกทาดำ)
  function estimateFilledArea(img, W, H) {
    try {
      const k = Math.min(1, 256 / Math.max(W, H));
      const w = Math.max(1, Math.round(W * k)), h = Math.max(1, Math.round(H * k));
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, w, h);
      const d = ctx.getImageData(0, 0, w, h).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] + d[i + 1] + d[i + 2] > 36) n++;
      return (n / (w * h)) * W * H;
    } catch (_) { return W * H; }
  }

  // ---------- ข้อความแจ้ง ----------
  let toastTimer = 0;
  function toast(msg, ms = 2400) {
    const t = $('toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms);
  }

  // หน้าต่างถาม: buttons = [{label, value, primary}] -> Promise(value)
  function dialog(title, body, buttons) {
    return new Promise((resolve) => {
      $('dialogTitle').textContent = title;
      const b = $('dialogBody');
      b.innerHTML = '';
      if (typeof body === 'string') b.append(el('p', { text: body })); else if (body) b.append(body);
      const row = $('dialogButtons');
      row.innerHTML = '';
      for (const bt of buttons) {
        const btn = el('button', { class: `btn btn-big ${bt.primary ? 'btn-primary' : ''}`, text: bt.label });
        if (bt.id) btn.id = bt.id;
        btn.addEventListener('click', () => {
          if (bt.validate && !bt.validate()) return;
          if (bt.onClick) bt.onClick();     // เรียกทันทีใน handler ของการแตะ (จำเป็นสำหรับเปิดตัวเลือกไฟล์บน iOS)
          $('dialog').hidden = true;
          resolve(typeof bt.value === 'function' ? bt.value() : bt.value);
        });
        row.append(btn);
      }
      $('dialog').hidden = false;
    });
  }

  async function askReason(kind, title, intro) {
    const box = el('div');
    box.append(el('p', { text: intro }));
    const list = el('div', { class: 'reasons' });
    for (const [code, label] of REASONS[kind]) {
      const r = el('input', { type: 'radio', name: 'reason', value: code });
      list.append(el('label', {}, [r, el('span', { text: label })]));
    }
    const other = el('input', { type: 'text', class: 'text-input', placeholder: 'พิมพ์เหตุผล (ถ้าเลือก อื่น ๆ)', maxlength: '200' });
    const err = el('p', { class: 'err-text' });
    box.append(list, other, err);
    const pick = () => {
      const r = box.querySelector('input[name=reason]:checked');
      return r ? { code: r.value, text: other.value.trim() || null } : null;
    };
    return dialog(title, box, [
      { label: 'ยืนยัน', primary: true, value: pick, id: 'btnReasonOk',
        validate: () => {
          const p = pick();
          if (!p) { err.textContent = 'กรุณาเลือกเหตุผล'; return false; }
          if (p.code === 'other' && !p.text) { err.textContent = 'กรุณาพิมพ์เหตุผล'; return false; }
          return true;
        } },
      { label: 'ยกเลิก', value: null, id: 'btnReasonCancel' },
    ]);
  }

  // ---------- viewers ----------
  const info = { xray: null, fluoro: null };
  function readoutText(side) {
    const i = info[side];
    if (!i || i.zoom == null) return '—';
    const parts = [`ซูม ${i.zoom.toFixed(2)}×`];
    if (i.session) parts.push(`กำลังวางจุด ${i.session.idx + 1} (${fmt(i.session.x)}, ${fmt(i.session.y)})`);
    else if (i.hover) parts.push(`ชี้ (${fmt(i.hover.x)}, ${fmt(i.hover.y)})`);
    const sel = state.selected, t = task();
    if (!i.session && sel && sel.side === side && t && t[side][sel.idx]) {
      const p = t[side][sel.idx];
      parts.push(`เลือกจุด ${sel.idx + 1} (${p.x.toFixed(1)}, ${p.y.toFixed(1)})`);
    }
    return parts.join(' · ');
  }

  function drawBox(ctx, v) {
    const it = currentItem();
    if (!state.showBox || !it || !it.box_xyxy) return;
    const b = it.box_xyxy;
    const p = v.imageToScreen(b[0], b[1]), q = v.imageToScreen(b[2], b[3]);
    ctx.save();
    ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.setLineDash([10, 6]);
    ctx.strokeRect(p.x, p.y, q.x - p.x, q.y - p.y);
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#00e5ff';
    ctx.strokeRect(p.x, p.y, q.x - p.x, q.y - p.y);
    ctx.restore();
  }

  function makeViewer(side, elv, readoutEl) {
    return new ImageViewer(elv, {
      emptyMessage: 'รอเปิดงาน…',
      getPoints: () => pointsFor(side),
      nextIndex: () => nextIndexFor(side),
      isFingerMode: () => state.fingerMode,
      onOverlay: (ctx, v) => { if (side === 'xray') drawBox(ctx, v); drawGhost(ctx, v, side); },
      onUserView: side === 'xray' ? () => setXView('custom') : null,
      onInfo: (i) => {
        const had = !!(info[side] && info[side].session);
        info[side] = i;
        readoutEl.textContent = readoutText(side);
        if (assistOn() && viewersRef && (had || i.session)) viewersRef[side === 'xray' ? 'fluoro' : 'xray'].requestRender();
      },
      onCommit: (c) => commitPoint(side, c),
      onSessionStart: (mode, idx) => {
        if (mode === 'move') state.selected = { side, idx };
        for (const s of SIDES) if (s !== side) viewers[s].cancelSession();
      },
      onBlocked: () => toast(blockedMessage(side)),
      onTap: (pointerType, hit) => {
        if (hit != null) { state.selected = { side, idx: hit }; refreshMarks(); return; }
        if (nextIndexFor(side) == null) return;
        if (pointerType === 'touch' && !state.fingerMode) toast('ใช้ Apple Pencil แตะเพื่อวางจุด หรือเปิด "นิ้ววางจุด"');
        else if (pointerType === 'touch') toast('กดค้างไว้ครู่หนึ่ง แว่นขยายจะขึ้น แล้วค่อย ๆ ขยับให้ตรง แล้วยกนิ้ว');
        else toast('กดเมาส์หรือกดแทร็กแพดค้างไว้ครู่หนึ่ง แว่นขยายจะขึ้น แล้วขยับให้ตรง แล้วปล่อย');
      },
    });
  }
  let viewersRef = null;
  const viewers = {
    xray: makeViewer('xray', $('viewerX'), $('readoutX')),
    fluoro: makeViewer('fluoro', $('viewerF'), $('readoutF')),
  };
  viewersRef = viewers;
  const panes = { xray: $('paneX'), fluoro: $('paneF') };

  function setXView(mode) {
    state.xView = mode;
    $('btnXView').textContent = mode === 'box' ? 'ดูทั้งภาพ' : 'กลับไปที่กรอบ';
  }
  function fitXrayToBox() {
    const it = currentItem();
    if (it) viewers.xray.fitBox(it.box_xyxy, CFG.view.boxMargin);
    setXView('box');
  }
  $('btnXView').addEventListener('click', () => {
    if (state.xView === 'box') { viewers.xray.resetView(); setXView('whole'); } else fitXrayToBox();
  });

  // ---------- แถบบน / แถบคำแนะนำ ----------
  function refreshMarks() {
    const t = task();
    for (const s of SIDES) {
      viewers[s].requestRender();
      $(s === 'xray' ? 'readoutX' : 'readoutF').textContent = readoutText(s);
    }
    const chip = $('hintChip');
    let warn = '';
    if (!t) {
      chip.textContent = ''; $('hintText').textContent = 'รอเข้าสู่ระบบ…'; $('pairCount').textContent = '';
      for (const s of SIDES) panes[s].style.borderColor = '';
    } else {
      const k = activeIndex(t);
      const pairs = pairCount(t);
      $('pairCount').textContent = `ครบ ${pairs}/${N} คู่`;
      if (t.status === 'unmarkable') {
        chip.textContent = '×'; chip.style.background = '#e5484d';
        $('hintText').textContent = `งานนี้: มาร์กไม่ได้ (${REASON_NAME[t.reason] || t.reason}${t.reason_text ? ': ' + t.reason_text : ''}) — กด ถัดไป`;
        for (const s of SIDES) panes[s].style.borderColor = '';
      } else if (k == null) {
        chip.textContent = '✓'; chip.style.background = '#3ddc84';
        $('hintText').textContent = state.mode === 'review'
          ? (FINAL.has(t.status) ? 'ยืนยันแล้ว — ลากจุดเพื่อแก้ได้ แล้วกด ยืนยัน อีกครั้ง'
            : 'ตรวจจุดของทีม: ถูกต้อง กด ยืนยัน · ไม่ตรง ลากจุดเพื่อแก้ แล้วกด ยืนยัน')
          : 'ครบ 4 คู่แล้ว — กด ถัดไป (ลากจุดเพื่อปรับได้)';
        for (const s of SIDES) panes[s].style.borderColor = '';
      } else {
        const color = CFG.marks.colors[k];
        chip.textContent = String(k + 1); chip.style.background = color;
        const need = SIDES.filter((s) => !t[s][k]);
        $('hintText').textContent = need.length === 2
          ? (k === 0 && pairs === 0
            ? `จุด 1 (ภาพใดก็ได้): ${POINT_TIP}`
            : `วางจุด ${k + 1} บนภาพใดก็ได้ — ชัด ไม่เปลี่ยนรูปตามมุมถ่าย กระจายให้ทั่วกรอบ`)
          : `วางจุด ${k + 1} บน${SIDE_NAME[need[0]]}ให้ตรงกับอีกภาพ`;
        for (const s of SIDES) panes[s].style.borderColor = need.includes(s) ? color : '';
        if (t.status === 'partial') $('hintText').textContent = 'งานนี้: บันทึก 3 คู่ — ' + $('hintText').textContent;
        if (t.status === 'skipped') $('hintText').textContent = 'งานนี้: ข้ามไว้ — ' + $('hintText').textContent;
        const sd = state.mode === 'review' ? state.seeds[currentItem().task_id] : null;
        if (state.mode === 'review' && !FINAL.has(t.status)) {
          if (sd && sd.status === 'unmarkable' && pairs === 0) {
            $('hintText').textContent = `ทีมระบุว่ามาร์กไม่ได้ (${REASON_NAME[sd.reason] || sd.reason || '-'}) — ถ้าเห็นด้วย กด มาร์กไม่ได้ · ถ้ามาร์กได้ ให้วางจุดเอง`;
          } else if (!sd || pairs === 0) {
            $('hintText').textContent = 'งานนี้ไม่มีจุดของทีม — วางจุดเอง หรือกด มาร์กไม่ได้';
          } else {
            $('hintText').textContent = 'ตรวจจุดของทีม: ' + $('hintText').textContent;
          }
        }
      }
      warn = SIDES.map(spreadWarning).filter(Boolean).join(' · ');
      if (warn) warn = '⚠ ' + warn + ' — ควรกระจายให้ทั่ว';
      const mm = mismatchWarning();
      if (mm) warn = (warn ? warn + ' · ' : '') + '⚠ ' + mm;
    }
    $('warnText').textContent = warn;
    $('hintText').title = $('hintText').textContent;   // ข้อความยาวถูกตัด: ชี้/แตะค้างเพื่อดูเต็ม
    $('btnNote').disabled = !t;
    $('btnNote').textContent = t && t.note ? 'หมายเหตุ ✓' : 'หมายเหตุ';
    $('btnNote').classList.toggle('has-note', !!(t && t.note));
    const u = t && state.undo[currentItem().task_id];
    $('btnUndo').disabled = !u || !u.length;
    $('btnDelete').disabled = !t || !state.selected || !t[state.selected.side][state.selected.idx];
    updateTopbar();
  }

  function updateTopbar() {
    const m = state.manifest;
    const n = totalTasks();
    const c = caseMode() ? state.caseOfIndex[state.index] : null;
    $('taskLabel').textContent = !m ? '— / —'
      : c ? `เคส ${c.no} · คู่ ${c.idx.indexOf(state.index) + 1}/${c.idx.length}` : `${m.items[state.index].task_id} / ${n}`;
    $('btnCases').hidden = !caseMode();
    $('btnNext').textContent = state.mode === 'review' ? 'ยืนยัน ▶' : 'ถัดไป ▶';
    const pr = $('progress');
    pr.textContent = m ? `ทำแล้ว ${completedCount()}/${n}` : '';
    const sk = m ? skippedCount() : 0;
    if (sk) pr.append(' · ', el('span', { class: 'skip-count', text: `ข้ามไว้ ${sk}` }));
    $('btnPrev').disabled = !m || prevIndex() < 0;
    $('btnNext').disabled = !m;
    const cur = m ? state.tasks[m.items[state.index].task_id] : null;
    $('btnSkip').disabled = !m || !!(cur && FINAL.has(cur.status));
    $('btnUnmarkable').disabled = !m;
    $('jumpInput').disabled = !m;
    $('btnJump').disabled = !m;
    $('btnFinish').disabled = !m;
  }

  function refreshFingerButton() {
    const b = $('btnFinger');
    b.setAttribute('aria-pressed', String(state.fingerMode));
    b.textContent = `นิ้ววางจุด: ${state.fingerMode ? 'เปิด' : 'ปิด'}`;
    const touch = navigator.maxTouchPoints > 0;
    const mac = /Mac/i.test(navigator.platform || navigator.userAgent) && !touch;
    $('howTo').textContent = mac
      ? 'แทร็กแพด: กดค้าง = วางจุด · เลื่อนสองนิ้ว = เลื่อนภาพ · บีบสองนิ้ว = ซูม'
      : !touch
      ? 'เมาส์: กดค้าง = วางจุด · ลาก = เลื่อน · ล้อ = ซูม'
      : state.fingerMode ? 'นิ้ว: กดค้าง = วางจุด · ลาก = เลื่อน · สองนิ้ว = ซูม'
        : 'Pencil: แตะ/ลาก = วางจุด · นิ้ว: เลื่อน/ซูม';
  }
  function setFingerMode(on) {
    state.fingerMode = !!on;
    try { localStorage.setItem('fingerMode', on ? '1' : '0'); } catch (_) { /* ignore */ }
    refreshFingerButton();
  }

  // ---------- ปรับภาพ ----------
  const adjustPanels = { xray: $('adjustX'), fluoro: $('adjustF') };
  function loadAdjust(side) {
    try { return JSON.parse(localStorage.getItem(`adjust_${side}`)) || null; } catch (_) { return null; }
  }
  function applyAdjustUI(side, a) {
    const p = adjustPanels[side];
    p.querySelectorAll('input[data-k]').forEach((inp) => {
      if (inp.type === 'checkbox') inp.checked = !!a[inp.dataset.k]; else inp.value = a[inp.dataset.k];
    });
  }
  for (const side of SIDES) {
    const p = adjustPanels[side];
    const saved = loadAdjust(side);
    if (saved) { viewers[side].adjust = Object.assign({}, viewers[side].adjust, saved); applyAdjustUI(side, viewers[side].adjust); }
    p.querySelectorAll('input[data-k]').forEach((inp) => {
      inp.addEventListener('input', () => {
        const v = inp.type === 'checkbox' ? inp.checked : parseFloat(inp.value);
        viewers[side].setAdjust({ [inp.dataset.k]: v });
        try { localStorage.setItem(`adjust_${side}`, JSON.stringify(viewers[side].adjust)); } catch (_) { /* ignore */ }
      });
    });
    p.querySelector('[data-adjust-reset]').addEventListener('click', () => {
      const d = { brightness: 1, contrast: 1, invert: false };
      viewers[side].setAdjust(d);
      applyAdjustUI(side, d);
      try { localStorage.removeItem(`adjust_${side}`); } catch (_) { /* ignore */ }
    });
    p.querySelector('[data-adjust-close]').addEventListener('click', () => { p.hidden = true; });
  }
  document.querySelectorAll('[data-adjust]').forEach((b) => b.addEventListener('click', () => {
    const p = adjustPanels[b.dataset.adjust];
    p.hidden = !p.hidden;
  }));
  $('chkBox').checked = state.showBox;
  $('chkBox').addEventListener('change', () => {
    state.showBox = $('chkBox').checked;
    try { localStorage.setItem('showBox', state.showBox ? '1' : '0'); } catch (_) { /* ignore */ }
    viewers.xray.requestRender();
  });

  // ---------- ข้อผิดพลาด ----------
  function showError(err) {
    const isBlocking = err instanceof Loader.BlockingError;
    $('errorTitle').textContent = isBlocking ? `หยุด: ${err.message}` : `เกิดข้อผิดพลาด: ${err.message || err}`;
    const ul = $('errorList');
    ul.innerHTML = '';
    for (const d of (err.details || [])) ul.append(el('li', { text: d }));
    $('errorModal').hidden = false;
    Debug.error(`${err.message}${err.details ? ' | ' + err.details.join(' | ') : ''}`);
  }
  $('btnErrorClose').addEventListener('click', () => { $('errorModal').hidden = true; });

  // ---------- ลิงก์ส่วนตัว (#t=<โทเคน>) ----------
  // โทเคนอยู่หลัง # จึงไม่ถูกส่งไปกับคำขอหน้าเว็บและไม่อยู่ใน log · อ่านแล้วลบออกจากแถบที่อยู่ทันที (ไม่ค้างในประวัติ/บุ๊กมาร์ก)
  // เก็บไว้ในหน่วยความจำเท่านั้นจนเข้าสู่ระบบสำเร็จ (ถ้า VPN ยังไม่ต่อ กด ลองใหม่ ได้โดยไม่ต้องแตะลิงก์ใหม่)
  const TOKEN_RE = /^[A-Za-z0-9_-]{20,200}$/;
  function takeLinkToken() {
    const m = /^#(?:.*&)?t=([^&]*)/.exec(location.hash || '');
    if (!m) return null;
    try { history.replaceState(null, '', location.pathname + location.search); } catch (_) { location.hash = ''; }
    return TOKEN_RE.test(m[1]) ? m[1] : '';
  }
  function tokenFromText(s) {
    s = String(s || '').trim();
    const m = /[#&]t=([A-Za-z0-9_-]{20,200})/.exec(s);
    if (m) return m[1];
    return TOKEN_RE.test(s) && s.length >= 40 ? s : null;
  }
  let linkToken = takeLinkToken();

  // ---------- เซิร์ฟเวอร์ (API ในเว็บเดียวกัน) ----------
  // ?package=<id> ใน URL ใช้เมื่อบัญชีมีหลายแพ็กเกจ (เช่น ตอนทดสอบ) · หมอมีแพ็กเกจเดียว ไม่ต้องใส่
  const PKG_PARAM = new URLSearchParams(location.search).get('package');
  const withPkg = (path) => (PKG_PARAM ? `${path}${path.includes('?') ? '&' : '?'}package=${encodeURIComponent(PKG_PARAM)}` : path);
  class ApiError extends Error {
    constructor(status, msg, body) { super(msg); this.name = 'ApiError'; this.status = status; this.body = body; }
  }
  async function api(path, opts = {}) {
    let r;
    try {
      r = await fetch(path, Object.assign({
        credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'pelnav' },
      }, opts));
    } catch (_) {
      throw new ApiError(0, 'ติดต่อเซิร์ฟเวอร์ไม่ได้ (เน็ตหรือ VPN หลุด?)');
    }
    let body = null;
    try { body = await r.json(); } catch (_) { /* ไม่ใช่ JSON */ }
    if (!r.ok) throw new ApiError(r.status, (body && body.error) || `เซิร์ฟเวอร์ตอบ ${r.status}`, body);
    return body;
  }

  // ---------- บันทึกขึ้นเซิร์ฟเวอร์ + คิวรอส่ง ----------
  // ทุกครั้งที่งานเปลี่ยน (save()) -> ใส่งานนั้นลงคิว -> เก็บคิวใน IndexedDB ของเครื่อง (เฉพาะจุด ไม่มีภาพ) -> ส่งทันที
  // ส่งไม่ได้ (เน็ตหลุด) -> ลองใหม่เอง (ถี่ก่อนแล้วห่างขึ้น) และเมื่อเน็ตกลับมา/กลับมาที่หน้าจอ · ปิดเว็บไปก่อน คิวก็ยังอยู่
  // เลขรุ่น (rev) กันข้อมูลเก่าทับข้อมูลใหม่: ถ้าอีกเครื่องบันทึกงานเดียวกันไปก่อน -> ยึดอันที่แก้ล่าสุด (updated_at)
  const sync = {
    user: null, pending: new Map(), sent: {}, revs: {}, failed: new Set(),
    sending: false, timer: 0, backoff: 0, lastOk: null, lastErr: null, needLogin: false, metaDirty: false,
  };
  const outboxKey = () => `outbox:${sync.user}:${state.manifest.package_id}`;
  async function persistOutbox() {
    if (!state.storage.ok || !state.manifest || !sync.user) return;
    const rec = { package_id: outboxKey(), saved_at: nowISO(), tasks: Object.fromEntries(sync.pending) };
    try {
      if (sync.pending.size) await Store.put(rec); else await Store.remove(rec.package_id);
    } catch (e) { Debug.error(`เก็บคิวรอส่งในเครื่องไม่ได้: ${e && (e.message || e)}`); }
  }
  async function loadOutbox() {
    if (!state.storage.ok) return {};
    try { const r = await Store.get(outboxKey()); return (r && r.tasks) || {}; } catch (_) { return {}; }
  }
  function queueTask(tid, t) {
    const js = JSON.stringify(t);
    if (!sync.pending.has(tid) && sync.sent[tid] === js) return false;       // ไม่มีอะไรเปลี่ยน
    sync.pending.set(tid, js);
    sync.failed.delete(tid);
    return true;
  }
  // ชื่อเดิม: ทุกที่ที่แก้งานเรียก save() — ใส่งานปัจจุบันลงคิวแล้วส่ง
  function save() {
    if (!state.manifest || !sync.user) return Promise.resolve();
    const it = currentItem();
    const t = it && state.tasks[it.task_id];
    if (t && queueTask(it.task_id, t)) persistOutbox();
    flushSoon(0);
    return Promise.resolve();
  }
  function queueMeta() { sync.metaDirty = true; flushSoon(0); }
  function flushSoon(ms) {
    clearTimeout(sync.timer);
    sync.timer = setTimeout(flush, ms);
  }
  async function sendTask(tid, js, retry = true) {
    const body = { task: JSON.parse(js), base_rev: sync.revs[tid] || 0 };
    try {
      const r = await api(withPkg(`/api/tasks/${encodeURIComponent(tid)}`), { method: 'PUT', body: JSON.stringify(body) });
      sync.revs[tid] = r.rev;
      sync.sent[tid] = js;
      if (sync.pending.get(tid) === js) sync.pending.delete(tid);            // แก้ต่อระหว่างส่ง -> ยังค้างไว้ส่งรอบถัดไป
      sync.lastOk = r.saved_at;
    } catch (e) {
      if (e.status === 409 && e.body) {
        const srv = e.body.task, local = JSON.parse(js);
        sync.revs[tid] = e.body.rev;
        if (srv && (srv.updated_at || '') > (local.updated_at || '')) {      // อีกเครื่องแก้ล่าสุด -> ใช้ของเซิร์ฟเวอร์
          state.tasks[tid] = srv;
          sync.sent[tid] = JSON.stringify(srv);
          if (sync.pending.get(tid) === js) sync.pending.delete(tid);
          delete state.undo[tid];
          Debug.log(`${tid}: มีการแก้จากอีกเครื่องที่ใหม่กว่า — ใช้ข้อมูลจากเซิร์ฟเวอร์`);
          if (currentItem() && currentItem().task_id === tid) {
            state.selected = null;
            refreshMarks();
            toast('งานนี้ถูกแก้จากอีกเครื่อง — ใช้ข้อมูลล่าสุดจากเซิร์ฟเวอร์', 4000);
          }
        } else if (retry) {
          Debug.log(`${tid}: ข้อมูลในเครื่องใหม่กว่า — ส่งทับรุ่น ${e.body.rev} (รุ่นก่อนหน้าเก็บไว้ในประวัติบนเซิร์ฟเวอร์)`);
          if (srv) toast(`งาน ${tid} ถูกแก้จากอีกเครื่องด้วย — ใช้ของเครื่องนี้ (ฉบับก่อนหน้าเก็บไว้บนเซิร์ฟเวอร์) ควรใช้เครื่องเดียว`, 5000);
          await sendTask(tid, js, false);
        }
        return;
      }
      if (e.status === 400 || e.status === 404) {                            // ข้อมูลผิด: ไม่วนส่งซ้ำ แต่เก็บไว้ในคิว (ทีมดูได้)
        sync.failed.add(tid);
        Debug.error(`บันทึก ${tid} ไม่ได้: ${e.message}`);
        toast(`บันทึกงาน ${tid} ไม่ได้: ${e.message} — แจ้งทีม`, 6000);
        return;
      }
      throw e;
    }
  }
  async function flush() {
    if (sync.sending || !state.manifest || sync.needLogin) return;
    sync.sending = true;
    updateSaveLabel();
    try {
      for (const [tid, js] of [...sync.pending]) {
        if (sync.failed.has(tid)) continue;
        await sendTask(tid, js);
      }
      if (sync.metaDirty) {
        sync.metaDirty = false;
        await api(withPkg('/api/meta'), { method: 'PUT', body: JSON.stringify({ current_index: state.index }) });
      }
      if (sync.lastErr) Debug.log('ส่งขึ้นเซิร์ฟเวอร์ได้อีกครั้ง');
      sync.lastErr = null;
      sync.backoff = 0;
    } catch (e) {
      if (e.status === 401) {
        sync.needLogin = true;
        Debug.error('ต้องเข้าสู่ระบบอีกครั้ง — แตะลิงก์ส่วนตัว (งานที่ยังไม่ส่งอยู่ในคิว)');
        showLogin(RELOGIN_MSG);
      } else {
        if (!sync.lastErr) Debug.error(`ส่งขึ้นเซิร์ฟเวอร์ไม่ได้ (จะลองใหม่เอง): ${e.message}`);
        sync.lastErr = e.message;
        sync.backoff = Math.min(30000, sync.backoff ? sync.backoff * 2 : 2000);
        clearTimeout(sync.timer);
        sync.timer = setTimeout(flush, sync.backoff);
      }
    } finally {
      sync.sending = false;
      persistOutbox();
      updateSaveLabel();
    }
    if (sync.pending.size && !sync.lastErr && !sync.needLogin && [...sync.pending.keys()].some((k) => !sync.failed.has(k))) flushSoon(0);
  }
  // รอจนคิวว่าง (หรือส่งไม่ได้/หมดเวลา) — ใช้ตอนพักงานและในเทสต์
  async function flushAll(timeoutMs = 10000) {
    const t0 = Date.now();
    for (;;) {
      if (!sync.sending) await flush();
      const left = [...sync.pending.keys()].filter((k) => !sync.failed.has(k)).length;
      if (!left || sync.lastErr || sync.needLogin || Date.now() - t0 > timeoutMs) return left;
      await new Promise((r) => setTimeout(r, 100));
    }
  }
  function updateSaveLabel() {
    const l = $('saveLabel');
    const n = sync.pending.size;
    if (sync.needLogin) { l.textContent = `ต้องเข้าสู่ระบบ · ค้าง ${n}`; l.className = 'small err'; }
    else if (n && sync.lastErr) { l.textContent = `ยังไม่ได้ส่ง ${n} งาน`; l.className = 'small err'; }
    else if (n || sync.sending) { l.textContent = 'กำลังบันทึก…'; l.className = 'muted small'; }
    else { l.className = 'muted small'; l.textContent = sync.lastOk ? `บันทึกแล้ว ${new Date(sync.lastOk).toLocaleTimeString('th-TH')}` : ''; }
    l.title = sync.lastErr ? `ส่งขึ้นเซิร์ฟเวอร์ไม่ได้: ${sync.lastErr} — เว็บจะลองใหม่เอง` : 'บันทึกบนเซิร์ฟเวอร์อัตโนมัติ';
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') save();
    else { flushSoon(0); checkUpdate('resume'); }
  });
  window.addEventListener('pagehide', () => { save(); persistOutbox(); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) { flushSoon(0); checkUpdate('resume'); } });
  window.addEventListener('online', () => { Debug.log('เน็ตกลับมา — ส่งงานที่ค้าง'); sync.backoff = 0; flushSoon(0); });
  window.addEventListener('beforeunload', (e) => {
    if (sync.pending.size) { e.preventDefault(); e.returnValue = ''; }      // ยังมีงานรอส่ง -> เบราว์เซอร์ถามก่อนปิด
  });

  // เปิดเว็บหลายแท็บพร้อมกัน -> เตือนให้ใช้แท็บเดียว
  try {
    const bc = new BroadcastChannel('pelnav-tabs');
    const me = Math.random().toString(36).slice(2);
    bc.onmessage = (ev) => {
      const d = ev.data || {};
      if (d.from === me) return;
      if (d.type === 'hello') bc.postMessage({ type: 'here', from: me });
      if (d.type === 'hello' || d.type === 'here') toast('เว็บนี้เปิดอยู่อีกแท็บหนึ่ง — ใช้แท็บเดียว เพื่อไม่ให้จุดบันทึกทับกัน', 6000);
    };
    bc.postMessage({ type: 'hello', from: me });
  } catch (_) { /* เบราว์เซอร์เก่า */ }

  // ---------- จับเวลา (Q7: รวมทุกครั้งที่เปิดงาน, ไม่นับตอนซ่อนแท็บ/ไม่ได้ใช้งานเกิน idleCutoff) ----------
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel']) {
    window.addEventListener(ev, () => { state.lastInteraction = Date.now(); }, { passive: true, capture: true });
  }
  let ticks = 0;
  setInterval(() => {
    const t = task();
    if (!t || !state.imagesReady || document.visibilityState !== 'visible') return;
    if (Date.now() - state.lastInteraction > CFG.timing.idleCutoffSec * 1000) return;
    if (!$('startScreen').hidden) return;
    t.duration_ms += 1000;
    if (++ticks % 30 === 0) save();
  }, 1000);

  // พื้นที่ที่เว็บใช้ในเครื่อง (แผงดีบัก)
  async function refreshUsage() {
    try {
      if (navigator.storage && navigator.storage.estimate) {
        const est = await navigator.storage.estimate();
        state.storage.usageMB = Math.round((est.usage || 0) / 1e6);
        state.storage.quotaMB = Math.round((est.quota || 0) / 1e6);
      }
      if (navigator.storage && navigator.storage.persisted) state.storage.persisted = await navigator.storage.persisted();
    } catch (_) { /* ignore */ }
  }

  // ---------- เข้าสู่ระบบ / เปิดงานจากเซิร์ฟเวอร์ ----------
  function showStart(which, msg = '') {
    $('loginCard').hidden = which !== 'login';
    $('startMsgBox').hidden = which !== 'msg';
    $('startMsg').textContent = msg;
    $('btnRetry').hidden = which !== 'msg';
    $('startScreen').hidden = false;
  }
  const RELOGIN_MSG = 'ต้องเข้าสู่ระบบอีกครั้ง (ลิงก์ถูกเปลี่ยนหรือหมดอายุ) — แตะลิงก์ส่วนตัวล่าสุดที่ทีมวิจัยส่งให้ งานที่ยังไม่ส่งไม่หาย';
  function showLogin(msg = '') {
    $('loginErr').textContent = '';
    $('loginMsg').textContent = msg;
    showStart('login');
  }
  async function linkLogin(token) {
    const r = await api('/api/link-login', { method: 'POST', body: JSON.stringify({ token }) });
    linkToken = null;
    Debug.log(`เข้าสู่ระบบด้วยลิงก์ส่วนตัว (${r.username} ถึง ${String(r.expires_at || '').slice(0, 10)})`);
    return r;
  }
  // ได้ลิงก์ใหม่ระหว่างที่เว็บเปิดอยู่ (แตะลิงก์ในแท็บเดิม หรือวางลิงก์ในช่อง)
  async function useLink(token) {
    linkToken = token;
    if (!state.manifest) { await boot(); return; }
    try {
      const r = await linkLogin(token);
      if (r.username !== sync.user) { location.reload(); return; }      // คนละบัญชี -> เริ่มใหม่ทั้งหมด
      if (sync.needLogin) {
        sync.needLogin = false;
        $('startScreen').hidden = true;
        Debug.log('เข้าสู่ระบบอีกครั้งแล้ว — ส่งงานที่ค้าง');
        toast('เข้าสู่ระบบแล้ว งานที่ทำไว้ไม่หาย');
        flushSoon(0);
        if (!state.imagesReady) showTask(state.index);
      }
    } catch (e) {
      if (e.status !== 0) linkToken = null;
      if (sync.needLogin) { showLogin(RELOGIN_MSG); $('loginErr').textContent = e.message; } else toast(e.message, 6000);
    }
  }

  async function boot() {
    showStart('msg', 'กำลังเชื่อมต่อเซิร์ฟเวอร์…');
    $('btnRetry').hidden = true;
    if (linkToken === '') { linkToken = null; showLogin('ลิงก์ไม่ครบ — คัดลอกลิงก์ทั้งหมดจากข้อความ หรือแตะลิงก์อีกครั้ง'); return; }
    if (linkToken) {
      try {
        await linkLogin(linkToken);
      } catch (e) {
        if (e.status === 0) { showStart('msg', `${e.message} — ต่อ VPN แล้วกด ลองใหม่`); return; }   // เก็บโทเคนไว้ลองใหม่
        linkToken = null;
        showLogin();
        $('loginErr').textContent = e.message;
        return;
      }
    }
    let me;
    try {
      me = await api('/api/me');
    } catch (e) {
      if (e.status === 401) { showLogin(); return; }
      showStart('msg', `${e.message} — ตรวจว่าเปิด VPN แล้ว แล้วกด ลองใหม่`);
      return;
    }
    if (me.role !== 'doctor' && !me.study_mode) {
      showStart('msg', `บัญชี ${me.username} เป็นบัญชีทีมวิจัย — ใช้หน้า admin.html`);
      $('btnRetry').hidden = true;
      return;
    }
    sync.user = me.username;
    $('userLabel').textContent = me.username;
    await openFromServer();
  }

  async function openFromServer() {
    showStart('msg', 'กำลังเปิดงาน…');
    $('btnRetry').hidden = true;
    try {
      const [manifest, st] = await Promise.all([api(withPkg('/api/package')), api(withPkg('/api/state'))]);
      const errs = Loader.validateManifest(manifest);
      if (errs.length) throw new Loader.BlockingError('ข้อมูลแพ็กเกจจากเซิร์ฟเวอร์ไม่ถูกต้อง', errs);
      const ids = new Set(manifest.items.map((it) => it.task_id));
      state.manifest = manifest;
      state.mode = manifest.mode || null;
      state.seeds = st.seeds || {};
      setupCases(manifest);
      state.tasks = {};
      sync.sent = {};
      sync.revs = st.revs || {};
      sync.pending.clear();
      sync.failed.clear();
      for (const [tid, t] of Object.entries(st.tasks || {})) {
        if (!ids.has(tid)) continue;
        state.tasks[tid] = t;
        sync.sent[tid] = JSON.stringify(t);
      }
      // คิวที่ค้างจากครั้งก่อน (เน็ตหลุดแล้วปิดเว็บ): ใช้ของในเครื่องถ้าแก้ล่าสุด แล้วส่งขึ้นเซิร์ฟเวอร์
      const ob = await loadOutbox();
      let restored = 0;
      for (const [tid, js] of Object.entries(ob)) {
        if (!ids.has(tid)) continue;
        const local = JSON.parse(js), srv = state.tasks[tid];
        if (!srv || (local.updated_at || '') >= (srv.updated_at || '')) {
          state.tasks[tid] = local;
          sync.pending.set(tid, js);
          restored++;
        }
      }
      state.undo = {};
      const idx = Math.max(0, Math.min(manifest.items.length - 1, st.current_index || 0));
      Debug.log(`เปิดแพ็กเกจ ${manifest.package_id} จากเซิร์ฟเวอร์: ${manifest.items.length} งาน, งานที่บันทึกไว้ ${Object.keys(st.tasks || {}).length}, คิวค้างจากครั้งก่อน ${restored}`);
      $('startScreen').hidden = true;
      if (Object.keys(st.tasks || {}).length) toast(`ทำต่อจากที่บันทึกไว้ (เสร็จ ${completedCount()}/${manifest.items.length})`);
      if (restored) { toast(`ส่งงานที่ค้างจากครั้งก่อน ${restored} งาน`, 4000); persistOutbox(); }
      updateSaveLabel();
      let inTask = false;
      try { inTask = sessionStorage.getItem(VIEW_KEY) === '1'; } catch (_) { /* ignore */ }
      if (caseMode() && !inTask) { state.index = idx; refreshMarks(); showCaseList(); } else await showTask(idx);
      flushSoon(0);
    } catch (e) {
      if (e.status === 401) { showLogin(); return; }
      if (e.status === 409) { showStart('msg', `${e.message}`); $('btnRetry').hidden = false; return; }
      if (e instanceof Loader.BlockingError) { showStart('msg', 'เปิดงานไม่ได้ — ดูข้อความแจ้งเตือน'); showError(e); return; }
      if (e.status >= 500) {
        showStart('msg', 'เปิดงานไม่ได้');
        showError(new Loader.BlockingError('เปิดแพ็กเกจจากเซิร์ฟเวอร์ไม่ได้', [e.message, 'แจ้งทีมวิจัย']));
        return;
      }
      showStart('msg', `${e.message} — ตรวจว่าเปิด VPN แล้ว แล้วกด ลองใหม่`);
    }
  }

  $('linkForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    $('loginErr').textContent = '';
    const t = tokenFromText($('linkInput').value);
    if (!t) { $('loginErr').textContent = 'ไม่พบรหัสในลิงก์ — คัดลอกลิงก์ทั้งหมดจากข้อความแล้ววางใหม่'; return; }
    $('linkInput').value = '';
    $('btnLink').disabled = true;
    try { await useLink(t); } finally { $('btnLink').disabled = false; }
  });
  window.addEventListener('hashchange', () => {        // แตะลิงก์ส่วนตัวขณะที่เว็บเปิดอยู่ในแท็บเดิม
    const t = takeLinkToken();
    if (t === null) return;
    if (!t) { toast('ลิงก์ไม่ครบ — คัดลอกลิงก์ทั้งหมดจากข้อความ', 5000); return; }
    useLink(t);
  });
  $('btnRetry').addEventListener('click', () => { if (sync.user && !state.manifest) openFromServer(); else boot(); });

  async function logout() {
    await flushAll(5000);
    try { await api('/api/logout', { method: 'POST' }); } catch (_) { /* ignore */ }
    location.reload();
  }

  // ---------- แสดงงาน ----------
  // ภาพโหลดจากเซิร์ฟเวอร์ตามรหัสงาน (เซิร์ฟเวอร์ไม่ให้เก็บแคช) แล้วตรวจชนิดไฟล์ EXIF และขนาดกับ manifest เหมือนเดิม
  // โหลดภาพงานถัดไปไว้ล่วงหน้าในหน่วยความจำ (ไม่บันทึกลงเครื่อง)
  class ImageLoadError extends Error {
    constructor(msg, status) { super(msg); this.name = 'ImageLoadError'; this.status = status; }
  }
  const imgCache = new Map();          // `${task_id}/${side}` -> Promise<File>
  function fetchImage(it, side) {
    const key = `${it.task_id}/${side}`;
    if (!imgCache.has(key)) {
      const name = it[side];
      const p = fetch(withPkg(`/api/image/${encodeURIComponent(it.task_id)}/${side}`), { credentials: 'same-origin', cache: 'no-store' })
        .catch(() => { throw new ImageLoadError('โหลดภาพไม่ได้ (เน็ตหรือ VPN หลุด?)', 0); })
        .then(async (r) => {
          if (r.status === 401) throw new ApiError(401, 'หมดเวลาเข้าสู่ระบบ');
          if (!r.ok) throw new ImageLoadError(`ไม่พบภาพ${side === 'xray' ? 'เอกซเรย์' : 'ฟลู'}ของงาน ${it.task_id} บนเซิร์ฟเวอร์ (${r.status})`, r.status);
          const b = await r.blob();
          return new File([b], name, { type: b.type || (/\.png$/i.test(name) ? 'image/png' : 'image/jpeg') });
        });
      p.catch(() => imgCache.delete(key));
      imgCache.set(key, p);
    }
    return imgCache.get(key);
  }
  function prefetchAround(i) {
    const items = state.manifest.items;
    const keep = new Set();
    for (const j of [i, i + 1]) {
      if (j < 0 || j >= items.length) continue;
      keep.add(`${items[j].task_id}/xray`); keep.add(`${items[j].task_id}/fluoro`);
      if (j !== i) { fetchImage(items[j], 'xray').catch(() => {}); fetchImage(items[j], 'fluoro').catch(() => {}); }
    }
    for (const k of [...imgCache.keys()]) if (!keep.has(k)) imgCache.delete(k);
  }

  function releaseUrls() {
    for (const u of state.urls) URL.revokeObjectURL(u);
    state.urls = [];
  }

  async function showTask(i) {
    const m = state.manifest;
    if (!m) return;
    i = Math.max(0, Math.min(m.items.length - 1, i));
    if (caseMode()) {                                 // เปิดงาน = ออกจากหน้ารายการเคส
      $('caseScreen').hidden = true;
      try { sessionStorage.setItem(VIEW_KEY, '1'); } catch (_) { /* ignore */ }
    }
    const changed = i !== state.index;
    state.index = i;
    state.selected = null;
    state.imagesReady = false;
    state.fluoroArea = null;
    const item = m.items[i];
    const t = task();
    if (!t.started_at) t.started_at = nowISO();
    save();
    if (changed || !sync.metaSent) { sync.metaSent = true; queueMeta(); }
    const token = ++state.loadToken;
    viewers.xray.clear('กำลังโหลดภาพ...');
    viewers.fluoro.clear('กำลังโหลดภาพ...');
    refreshMarks();
    releaseUrls();
    try {
      const [xf, ff] = await Promise.all([fetchImage(item, 'xray'), fetchImage(item, 'fluoro')]);
      if (token !== state.loadToken) return;
      const [x, f] = await Promise.all([
        Loader.loadImage(xf, item.xray_size, `${item.task_id} เอกซเรย์`),
        Loader.loadImage(ff, item.fluoro_size, `${item.task_id} ฟลู`),
      ]);
      if (token !== state.loadToken) { URL.revokeObjectURL(x.url); URL.revokeObjectURL(f.url); return; }
      state.urls.push(x.url, f.url);
      viewers.xray.setImage(x.img, x.W, x.H);
      viewers.fluoro.setImage(f.img, f.W, f.H);
      fitXrayToBox();
      // พื้นที่วงกลมฟลู: แพ็กเกจภาพต้นฉบับให้ค่ามาใน manifest (ต้นฉบับไม่ได้ทาดำรอบวงกลม) · ไม่มี = ประมาณจากส่วนที่ไม่ดำ
      state.fluoroArea = (typeof item.fluoro_area === 'number' && item.fluoro_area > 0) ? item.fluoro_area : estimateFilledArea(f.img, f.W, f.H);
      state.imagesReady = true;
      refreshMarks();
      prefetchAround(i);
      if (x.hasExif || f.hasExif) Debug.log(`${item.task_id}: มี EXIF แต่ Orientation = 1 (ไม่หมุน)`);
    } catch (err) {
      if (token !== state.loadToken) return;
      if (err.status === 401) {
        sync.needLogin = true;
        viewers.xray.clear('ต้องเข้าสู่ระบบอีกครั้ง');
        viewers.fluoro.clear('ต้องเข้าสู่ระบบอีกครั้ง');
        showLogin(RELOGIN_MSG);
        return;
      }
      if (err instanceof ImageLoadError && err.status === 0) {          // เน็ตหลุด: ให้ลองใหม่ งานไม่หาย
        viewers.xray.clear('โหลดภาพไม่ได้ — ตรวจเน็ต/VPN');
        viewers.fluoro.clear('โหลดภาพไม่ได้ — ตรวจเน็ต/VPN');
        Debug.error(`${item.task_id}: ${err.message}`);
        const a = await dialog('โหลดภาพไม่ได้', el('div', {}, [
          el('p', {}, [el('b', { text: 'งานที่ทำไว้ไม่หาย' })]),
          el('p', { text: 'ติดต่อเซิร์ฟเวอร์ไม่ได้ ตรวจว่าเปิด VPN และเน็ตใช้ได้ แล้วกด ลองใหม่' }),
        ]), [{ label: 'ลองใหม่', value: 'retry', primary: true, id: 'btnImgRetry' }, { label: 'ปิด', value: null, id: 'btnImgClose' }]);
        if (a === 'retry' && token === state.loadToken) showTask(i);
        return;
      }
      viewers.xray.clear('หยุด: ดูข้อความแจ้งเตือน');
      viewers.fluoro.clear('หยุด: ดูข้อความแจ้งเตือน');
      showError(err instanceof ImageLoadError ? new Loader.BlockingError(err.message, ['ห้ามมาร์กงานนี้ แจ้งทีมวิจัย']) : err);
    }
  }

  function setFinal(t, status, reason) {
    t.status = status;
    t.reason = reason ? reason.code : null;
    t.reason_text = reason ? reason.text : null;
    t.updated_at = nowISO();
    t.finished_at = t.updated_at;
    save();
  }

  // ---------- ถัดไป / มาร์กไม่ได้ ----------
  async function goNext() {
    const t = task();
    if (!t || state.busy) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    const pc = pairCount(t);
    if (pc === N) {
      if (t.status !== 'done') setFinal(t, 'done', null);
    } else if (t.status === 'unmarkable') {
      // ผ่านได้
    } else if (pc === N - 1 && !hasOrphans(t)) {
      if (t.status !== 'partial') {
        const r = await askReason('partial', 'บันทึกแค่ 3 คู่?', 'งานนี้มี 3 คู่ ถ้าหาจุดที่ 4 ไม่ได้ ให้เลือกเหตุผล (หรือกด ยกเลิก เพื่อวางต่อ)');
        if (!r) return;
        setFinal(t, 'partial', r);
      }
    } else if (pc === N - 1) {
      toast('มีจุดที่ยังไม่มีคู่ — วางคู่ให้ครบ หรือลบจุดนั้นก่อน', 3500);
      return;
    } else {
      toast(`ยังไม่ครบ (${pc}/4 คู่) — ต้องครบ 4 คู่ หรือ 3 คู่พร้อมเหตุผล หรือกด "มาร์กไม่ได้" (หรือ "ข้ามไปก่อน")`, 3500);
      return;
    }
    if (state.mode === 'review' && FINAL.has(t.status) && t.status !== 'unmarkable') {
      const e = reviewEdits(currentItem().task_id, t);
      toast(e ? `ยืนยันแล้ว — แก้ ${e} จุด` : 'ยืนยันแล้ว — ไม่ได้แก้', 2500);
    }
    await advance();
  }

  async function markUnmarkable() {
    const t = task();
    if (!t || state.busy) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    const r = await askReason('unmarkable', 'มาร์กไม่ได้', 'เลือกเหตุผลที่มาร์กงานนี้ไม่ได้');
    if (!r) return;
    setFinal(t, 'unmarkable', r);
    refreshMarks();
    await advance();
  }

  // หมายเหตุสั้น ๆ ต่องาน (ไม่บังคับ) — ไม่เปลี่ยนสถานะงาน แต่เปลี่ยน updated_at เพื่อให้การรวมไฟล์สำรองยึดอันล่าสุด
  async function editNote() {
    const t = task();
    if (!t || state.busy) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    const box = el('div');
    box.append(el('p', { class: 'small muted', text: `หมายเหตุของ ${currentItem().task_id} (ไม่บังคับ ไม่เกิน ${NOTE_MAX} ตัวอักษร) — ห้ามใส่ชื่อ/HN ผู้ป่วย` }));
    const ta = el('textarea', { class: 'text-input', id: 'noteInput', rows: '3', maxlength: String(NOTE_MAX),
      placeholder: 'เช่น จุด 2 ไม่แน่ใจ, ภาพฟลูเอียงมาก' });
    ta.value = t.note || '';
    box.append(ta);
    const btns = [{ label: 'บันทึก', primary: true, id: 'btnNoteOk', value: () => ta.value }];
    if (t.note) btns.push({ label: 'ลบหมายเหตุ', id: 'btnNoteClear', value: '' });
    btns.push({ label: 'ยกเลิก', id: 'btnNoteCancel', value: null });
    const p = dialog('หมายเหตุงานนี้', box, btns);
    setTimeout(() => { try { ta.focus(); } catch (_) { /* ignore */ } }, 50);
    const v = await p;
    if (v == null) return;
    const note = String(v).replace(/\s+/g, ' ').trim().slice(0, NOTE_MAX) || null;
    if (note === (t.note || null)) return;
    t.note = note;
    t.updated_at = nowISO();
    save();
    refreshMarks();
    toast(note ? 'บันทึกหมายเหตุแล้ว' : 'ลบหมายเหตุแล้ว');
  }

  // ---------- เลือกงานถัดไป ----------
  // ลำดับ: งานที่ยังไม่เสร็จและไม่ได้ข้าม (ไปข้างหน้า) → งานที่ยังไม่เสร็จที่อยู่ก่อนหน้า → งานที่ข้ามไว้ (วนทีละงาน)
  const isFinalAt = (i) => FINAL.has(statusAt(i));
  // ขอบเขตการเลื่อนงาน: โหมดรายการเคส = งานในเคสเดียวกันเท่านั้น · แบบเดิม = ทุกงาน
  function scope() {
    if (!caseMode()) return [...Array(totalTasks()).keys()];
    const c = state.caseOfIndex[state.index];
    return c ? c.idx : [state.index];
  }
  function findForward(from, pred) {
    const sc = scope();
    for (let k = sc.indexOf(from) + 1; k < sc.length; k++) if (pred(sc[k])) return sc[k];
    return -1;
  }
  function findCyclic(from, pred) {          // หลังงานนี้ไปจนสุด แล้ววนจากต้น (ไม่รวมงานนี้)
    const sc = scope(), n = sc.length, at = sc.indexOf(from);
    for (let k = 1; k < n; k++) { const i = sc[(at + k + n) % n]; if (pred(i)) return i; }
    return -1;
  }
  function prevIndex() {
    if (!state.manifest) return -1;
    const sc = scope(), at = sc.indexOf(state.index);
    return at > 0 ? sc[at - 1] : -1;
  }
  const isOpenNormal = (i) => !isFinalAt(i) && statusAt(i) !== 'skipped';
  const isSkipped = (i) => statusAt(i) === 'skipped';

  async function advance() {
    state.busy = true;
    try {
      refreshMarks();
      if (caseMode()) {                              // ภายในเคส: งานถัดไปที่ยังไม่เสร็จ · ครบแล้วกลับหน้ารายการเคส
        const nx = findForward(state.index, isOpenNormal);
        const left = nx >= 0 ? nx : findCyclic(state.index, isOpenNormal);
        if (left >= 0) { await showTask(left); return; }
        backToCases(caseDoneMessage(state.caseOfIndex[state.index]));
        return;
      }
      const n = totalTasks();
      const fwd = findForward(state.index, isOpenNormal);
      if (fwd >= 0) { await showTask(fwd); return; }
      const left = findCyclic(state.index, isOpenNormal);       // งานที่ยังไม่ทำซึ่งอยู่ก่อนหน้า (เช่น ย้อนกลับไปแก้)
      if (left < 0) {
        const sk = findCyclic(state.index, isSkipped);
        if (sk >= 0) {                                           // งานที่ไม่ได้ข้ามครบแล้ว -> กลับไปงานที่ข้ามทีละงาน
          toast(`ทำงานที่ไม่ได้ข้ามครบแล้ว — กลับไปงานที่ข้ามไว้ (เหลือ ${skippedCount()} งาน)`, 4000);
          Debug.log(`กลับไปงานที่ข้ามไว้ ${state.manifest.items[sk].task_id}`);
          await showTask(sk);
          return;
        }
      }
      const btns = [];
      if (left >= 0) btns.push({ label: `ไปงานที่ยังไม่เสร็จ (${state.manifest.items[left].task_id})`, value: 'left', primary: true });
      btns.push({ label: 'พักงาน', value: 'finish', primary: left < 0 }, { label: 'อยู่ที่งานนี้', value: 'stay' });
      const a = await dialog(left >= 0 ? 'ถึงงานสุดท้ายแล้ว' : 'ทำครบทุกงานแล้ว', `เสร็จ ${completedCount()}/${n} งาน`, btns);
      if (a === 'left') await showTask(left);
      else if (a === 'finish') { state.busy = false; await finish(); }
    } finally { state.busy = false; }
  }

  // ข้ามไปก่อน: งานนี้ = skipped (จุดที่วางไว้ยังอยู่) แล้วไปงานถัดไป
  async function skipTask() {
    const t = task();
    if (!t || state.busy || FINAL.has(t.status)) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    if (t.status !== 'skipped') {
      t.status = 'skipped';
      t.updated_at = nowISO();
      save();
      Debug.log(`${currentItem().task_id} ข้ามไปก่อน`);
    }
    refreshMarks();
    state.busy = true;
    try {
      let nx = findForward(state.index, isOpenNormal);
      if (nx < 0) nx = findCyclic(state.index, isOpenNormal);
      if (nx < 0 && caseMode()) { backToCases(caseDoneMessage(state.caseOfIndex[state.index])); return; }
      if (nx < 0) nx = findCyclic(state.index, isSkipped);
      if (nx < 0) { toast('เหลืองานนี้งานเดียว — วางจุดให้ครบ หรือกด "มาร์กไม่ได้"', 4000); return; }
      if (isSkipped(nx)) toast(`ไปงานที่ข้ามไว้ถัดไป (เหลือ ${skippedCount()} งาน)`, 3000);
      await showTask(nx);
    } finally { state.busy = false; }
  }

  // ไปที่งาน: พิมพ์เลขงาน (เช่น 15 หรือ T015)
  async function jumpTo() {
    const inp = $('jumpInput');
    const raw = inp.value.trim();
    if (!state.manifest || state.busy || !raw) return;
    const mt = /^[Tt]?0*(\d+)$/.exec(raw);
    const num = mt ? parseInt(mt[1], 10) : NaN;
    const items = state.manifest.items;
    let i;
    if (caseMode()) {                                  // ภายในเคส: คู่ที่ 1..n ของเคสนี้
      const sc = scope();
      i = num >= 1 && num <= sc.length ? sc[num - 1] : -1;
      if (i < 0) { toast(`เคสนี้มี ${sc.length} คู่ — พิมพ์เลข 1 ถึง ${sc.length}`, 3500); return; }
    } else {
      i = items.findIndex((it) => parseInt(it.task_id.slice(1), 10) === num);
      if (i < 0 && num >= 1 && num <= items.length) i = num - 1;
      if (i < 0) { toast(`ไม่มีงานเลข "${raw}" — พิมพ์เลข 1 ถึง ${items.length}`, 3500); return; }
    }
    inp.value = '';
    inp.blur();
    for (const v of Object.values(viewers)) v.cancelSession();
    Debug.log(`ไปที่งาน ${items[i].task_id}`);
    await showTask(i);
  }

  // ---------- พักงาน ----------
  // ไม่ต้องสำรองหรือส่งไฟล์: จุดบันทึกบนเซิร์ฟเวอร์ทุกครั้งที่วาง · พักงาน = ส่งคิวที่ค้างให้หมด แล้วสรุปให้เห็นว่าบันทึกครบ
  async function finish() {
    if (!state.manifest) return;
    for (const v of Object.values(viewers)) v.cancelSession();
    const sk = skippedCount();
    if (sk) {                       // กันลืม: ยังมีงานที่ข้ามไว้
      const first = state.manifest.items.findIndex((it) => (state.tasks[it.task_id] || {}).status === 'skipped');
      const a = await dialog(`ยังมีงานที่ข้ามไว้ ${sk} งาน`, el('div', {}, [
        el('p', { text: `งานที่กด "ข้ามไปก่อน" นับว่ายังไม่เสร็จ (ทำแล้ว ${completedCount()}/${totalTasks()} งาน)` }),
        el('p', { text: 'ถ้าจะหยุดวันนี้ กด พักงานไปก่อน ได้ งานที่ข้ามไว้ยังอยู่ และเว็บจะเตือนอีกครั้งครั้งหน้า' }),
      ]), [
        { label: `ไปทำงานที่ข้ามไว้ (${state.manifest.items[first].task_id})`, value: 'go', primary: true, id: 'btnFinishGoSkipped' },
        { label: 'พักงานไปก่อน', value: 'finish', id: 'btnFinishAnyway' },
        { label: 'ยกเลิก', value: null, id: 'btnFinishCancel' },
      ]);
      if (a === 'go') { await showTask(first); return; }
      if (a !== 'finish') return;
    }
    save();
    const left = await flushAll(8000);
    const body = left
      ? el('div', {}, [
        el('p', {}, [el('b', { text: `ยังส่งงานขึ้นเซิร์ฟเวอร์ไม่ได้ ${left} งาน` })]),
        el('p', { text: 'งานเก็บไว้ในเครื่องนี้แล้ว ไม่หาย อย่าล้างข้อมูลของเบราว์เซอร์ เมื่อเน็ตหรือ VPN กลับมา ให้เปิดเว็บนี้อีกครั้ง เว็บจะส่งให้เอง' }),
      ])
      : el('div', {}, [
        el('p', {}, [el('b', { text: 'บันทึกบนเซิร์ฟเวอร์ครบแล้ว' })]),
        el('p', { text: `ทำแล้ว ${completedCount()}/${totalTasks()} งาน${sk ? ` · ข้ามไว้ ${sk} งาน` : ''}` }),
        el('p', { text: 'ปิดเว็บได้เลย ไม่ต้องสำรองหรือส่งไฟล์ ครั้งหน้าเปิดลิงก์เดิมแล้วทำต่อได้ทันที' }),
      ]);
    const a = await dialog(left ? 'ยังส่งไม่ครบ' : 'พักงานได้', body, [
      { label: 'ทำงานต่อ', value: 'stay', primary: true, id: 'btnPauseStay' },
      { label: 'ออกจากระบบ', value: 'logout', id: 'btnLogout' },
    ]);
    if (a === 'logout') await logout();
  }

  // ---------- หน้ารายการเคส ----------
  function setupCases(manifest) {
    state.cases = null;
    state.caseOfIndex = [];
    if (!Array.isArray(manifest.cases)) return;
    const byId = new Map(manifest.items.map((it, i) => [it.task_id, i]));
    const cases = manifest.cases.map((c) => ({ no: c.no, idx: (c.tasks || []).map((t) => byId.get(t)) }));
    if (!cases.length || cases.some((c) => !c.idx.length || c.idx.some((i) => i == null))) {
      throw new Loader.BlockingError('ข้อมูลรายการเคสจากเซิร์ฟเวอร์ไม่ถูกต้อง', ['แจ้งทีมวิจัย']);
    }
    for (const c of cases) for (const i of c.idx) state.caseOfIndex[i] = c;
    state.cases = cases;
  }
  function caseStatus(c) {
    const sts = c.idx.map(statusAt);
    const done = sts.filter((x) => FINAL.has(x)).length;
    if (done === sts.length) return { key: 'done', text: 'เสร็จ' };
    if (sts.includes('skipped')) return { key: 'skip', text: `มีงานข้าม · ${done}/${sts.length}` };
    if (done > 0 || sts.some((x) => x !== 'todo')) return { key: 'part', text: `ทำแล้ว ${done}/${sts.length}` };
    return { key: 'todo', text: 'ยังไม่เริ่ม' };
  }
  function caseDoneMessage(c) {
    if (!c) return '';
    const sk = c.idx.filter((i) => statusAt(i) === 'skipped').length;
    return sk ? `เคส ${c.no}: ข้ามไว้ ${sk} คู่ — แตะเคสนี้เพื่อกลับไปทำ` : `เคส ${c.no} เสร็จแล้ว`;
  }
  function nextOpenCase() {
    const n = state.cases.length;
    const start = Math.max(0, state.cases.indexOf(state.caseOfIndex[state.index]));
    for (const pred of [isOpenNormal, isSkipped]) {
      for (let k = 0; k < n; k++) { const c = state.cases[(start + k) % n]; if (c.idx.some(pred)) return c; }
    }
    return null;
  }
  function renderCaseList() {
    const list = $('caseList');
    list.textContent = '';
    const onlyOpen = $('caseFilter').checked;
    let shown = 0;
    for (const c of state.cases) {
      const s = caseStatus(c);
      if (onlyOpen && s.key === 'done') continue;
      shown++;
      const b = el('button', { class: `case-item st-${s.key}`, 'data-case': String(c.no), type: 'button' },
        [el('b', { text: `เคส ${c.no}` }), el('span', { text: s.text })]);
      b.addEventListener('click', () => openCase(c));
      list.append(b);
    }
    if (!shown) list.append(el('p', { class: 'muted', text: 'ทำครบทุกเคสแล้ว' }));
    const doneCases = state.cases.filter((c) => caseStatus(c).key === 'done').length;
    $('caseTitle').textContent = state.mode === 'review' ? 'ตรวจจุดของทีม — รายการเคส' : 'มาร์กจุด — รายการเคส';
    $('caseSummary').textContent = `เสร็จ ${doneCases}/${state.cases.length} เคส · ${completedCount()}/${totalTasks()} คู่`
      + (skippedCount() ? ` · ข้ามไว้ ${skippedCount()} คู่` : '');
    $('caseUser').textContent = sync.user ? `บัญชี ${sync.user}` : '';
    $('btnContinue').disabled = !nextOpenCase();
  }
  function showCaseList(msg = '') {
    for (const v of Object.values(viewers)) v.cancelSession();
    try { sessionStorage.removeItem(VIEW_KEY); } catch (_) { /* ignore */ }
    renderCaseList();
    $('caseMsg').textContent = msg;
    $('caseScreen').hidden = false;
  }
  function backToCases(msg = '') {
    save();
    flushSoon(0);
    showCaseList(msg);
  }
  async function openCase(c) {
    if (!c || state.busy) return;
    const i = c.idx.find(isOpenNormal) ?? c.idx.find(isSkipped) ?? c.idx[0];
    Debug.log(`เปิดเคส ${c.no}`);
    await showTask(i);
  }
  $('btnContinue').addEventListener('click', () => {
    const c = nextOpenCase();
    if (c) openCase(c); else toast('ทำครบทุกเคสแล้ว');
  });
  $('caseFilter').addEventListener('change', () => {
    try { localStorage.setItem('caseFilter', $('caseFilter').checked ? '1' : '0'); } catch (_) { /* ignore */ }
    renderCaseList();
  });
  try { $('caseFilter').checked = localStorage.getItem('caseFilter') === '1'; } catch (_) { /* ignore */ }
  $('btnCases').addEventListener('click', () => { if (!state.busy) backToCases(); });
  $('btnCasePause').addEventListener('click', finish);

  // ---------- ปุ่ม / คีย์ลัด ----------
  $('btnPrev').addEventListener('click', () => { const i = prevIndex(); if (!state.busy && i >= 0) showTask(i); });
  $('btnNext').addEventListener('click', goNext);
  $('btnUnmarkable').addEventListener('click', markUnmarkable);
  $('btnSkip').addEventListener('click', skipTask);
  $('btnJump').addEventListener('click', jumpTo);
  $('jumpInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); jumpTo(); } });
  $('btnNote').addEventListener('click', editNote);
  $('btnFinish').addEventListener('click', finish);
  $('btnUndo').addEventListener('click', undo);
  $('btnDelete').addEventListener('click', deleteSelected);
  $('btnFinger').addEventListener('click', () => {
    setFingerMode(!state.fingerMode);
    toast(state.fingerMode ? 'เปิด: กดนิ้วค้างเพื่อวางจุด' : 'ปิด: นิ้วใช้เลื่อน/ซูมเท่านั้น');
  });
  document.querySelectorAll('[data-reset]').forEach((b) =>
    b.addEventListener('click', () => viewers[b.dataset.reset].resetView()));

  window.addEventListener('keydown', (e) => {
    if (e.target && /input|textarea/i.test(e.target.tagName)) return;
    if (!$('dialog').hidden || !$('startScreen').hidden || !$('caseScreen').hidden) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
    else if (e.key === 'Escape') { for (const v of Object.values(viewers)) v.cancelSession(); }
    else if (e.key === 'ArrowLeft') { const i = prevIndex(); if (!state.busy && i >= 0) showTask(i); }
    else if (e.key === 'ArrowRight') goNext();
  });
  window.addEventListener('blur', () => { for (const v of Object.values(viewers)) v.cancelSession(); });
  for (const ev of ['gesturestart', 'gesturechange', 'gestureend']) {
    document.addEventListener(ev, (e) => e.preventDefault(), { passive: false });
  }

  // ---------- อัปเดตเป็นเวอร์ชันใหม่เอง ----------
  // ไอคอนบนหน้าจอโฮมของ iPad มักกลับมาจากหน่วยความจำ (ไม่โหลดหน้าใหม่) จึงต้องเช็กเอง:
  // ตอนเปิดและทุกครั้งที่กลับมาที่หน้าจอ โหลด version.js แบบไม่ใช้แคช (script-src 'self' — ไม่ต้องเปิด connect-src)
  // ถ้าใหม่กว่า -> ส่งงานที่ค้าง แล้วโหลดหน้าใหม่ที่ ?v=<เวอร์ชันใหม่> -> เข้างานเดิมเอง (เข้าสู่ระบบค้างไว้)
  const UPD_TRIED = 'pelnavUpdateTried';
  const ss = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) { /* ignore */ } },
    del: (k) => { try { sessionStorage.removeItem(k); } catch (_) { /* ignore */ } },
  };
  function cmpVer(a, b) {
    const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number);
    for (let i = 0; i < 3; i++) { const d = (x[i] || 0) - (y[i] || 0); if (d) return Math.sign(d); }
    return 0;
  }
  function fetchLatestVersion() {
    return new Promise((resolve) => {
      const prev = window.PELNAV_VERSION;
      const s = document.createElement('script');
      let settled = false;
      const done = (v) => {
        if (settled) return;
        settled = true;
        window.PELNAV_VERSION = prev;
        s.remove();
        resolve(v);
      };
      s.onload = () => done(window.PELNAV_VERSION);
      s.onerror = () => done(null);                       // ออฟไลน์ -> ข้าม ใช้เวอร์ชันเดิมต่อ
      setTimeout(() => done(null), 8000);
      s.src = `version.js?check=${Date.now()}`;
      document.head.append(s);
    });
  }
  const upd = { lastCheck: 0, latest: null, checkedAt: null, reloading: false };
  // คืน true ถ้ากำลังโหลดหน้าใหม่
  async function checkUpdate(why, force = false) {
    if (upd.reloading) return true;
    if (!force && why !== 'start' && Date.now() - upd.lastCheck < 30000) return false;
    upd.lastCheck = Date.now();
    const latest = await fetchLatestVersion();
    if (!latest) return false;
    upd.latest = latest; upd.checkedAt = new Date();
    const tried = ss.get(UPD_TRIED);
    if (tried && cmpVer(CFG.APP_VERSION, tried) >= 0) ss.del(UPD_TRIED);
    if (cmpVer(latest, CFG.APP_VERSION) <= 0) return false;
    if (ss.get(UPD_TRIED) === latest) {                     // โหลดใหม่ไปแล้วแต่ยังได้ของเก่า (แคช/เซิร์ฟเวอร์ยังไม่อัปเดต) -> ไม่วนโหลด
      Debug.error(`มีเวอร์ชันใหม่ ${latest} แต่โหลดใหม่แล้วยังได้ ${CFG.APP_VERSION} — ปิดแอปแล้วเปิดใหม่ภายหลัง`);
      return false;
    }
    // อย่าโหลดใหม่ระหว่างวางจุด เก็บภาพ หรือมีหน้าต่างถามค้างอยู่ -> ลองใหม่ภายหลัง
    const midAction = state.busy || !$('dialog').hidden || Object.values(viewers).some((v) => v.session);
    if (midAction) { setTimeout(() => checkUpdate('retry', true), 5000); return false; }
    upd.reloading = true;
    Debug.log(`พบเวอร์ชันใหม่ ${latest} (ตอนนี้ ${CFG.APP_VERSION}) — บันทึกงานแล้วโหลดใหม่`);
    ss.set(UPD_TRIED, latest);
    toast(`มีเวอร์ชันใหม่ (${latest}) — กำลังโหลดใหม่ งานที่ทำไว้ไม่หาย`, 5000);
    try { save(); await flushAll(5000); } catch (_) { /* คิวที่ยังไม่ส่งเก็บในเครื่องแล้ว ส่งต่อหลังโหลดใหม่ */ }
    const u = new URL(location.href);               // คง ?package= ไว้
    u.searchParams.set('v', latest);
    setTimeout(() => { location.replace(u.pathname + u.search + (linkToken ? `#t=${linkToken}` : '')); }, 800);   // ยังไม่ได้ใช้ลิงก์ -> ส่งต่อ
    return true;
  }

  // ---------- แผงดีบัก ----------
  function deviceInfo() {
    const lines = [
      `app ${CFG.APP_VERSION} · ผู้ใช้ ${sync.user || '-'} · แพ็กเกจ ${state.manifest ? state.manifest.package_id : '-'}`,
      `เซิร์ฟเวอร์: คิวรอส่ง ${sync.pending.size} งาน${sync.failed.size ? ` (ส่งไม่ได้เพราะข้อมูลผิด ${sync.failed.size})` : ''} · ส่งล่าสุด ${sync.lastOk ? new Date(sync.lastOk).toLocaleTimeString('th-TH') : '-'}${sync.lastErr ? ` · ผิดพลาด: ${sync.lastErr}` : ''}${sync.needLogin ? ' · ต้องเข้าสู่ระบบ' : ''}`,
      `เก็บคิวในเครื่อง: ${state.storage.ok ? 'ได้' : 'ไม่ได้ (' + state.storage.reason + ')'} · เก็บถาวร (persist)=${state.storage.persisted} · ใช้พื้นที่ ${state.storage.usageMB != null ? state.storage.usageMB : '?'} MB`,
      `เวอร์ชันล่าสุดบนเว็บ: ${upd.latest || 'ยังไม่ได้เช็ก/ออฟไลน์'}${upd.checkedAt ? ` (เช็ก ${upd.checkedAt.toLocaleTimeString('th-TH')})` : ''}`,
      `viewport ${window.innerWidth}×${window.innerHeight} CSS px · dpr ${window.devicePixelRatio}`,
      `pointer types: ${[...pointerTypesSeen].join(', ') || '-'} · นิ้ววางจุด: ${state.fingerMode ? 'เปิด' : 'ปิด'}`,
      `UA: ${navigator.userAgent}`,
    ];
    for (const [k, v] of Object.entries(viewers)) {
      if (v.img) lines.push(`${k}: ${v.W}×${v.H} s=${v.s.toFixed(4)} zoom=${v.zoom.toFixed(2)}× loupe×${v.loupeScale().toFixed(1)} t=(${v.tx.toFixed(1)}, ${v.ty.toFixed(1)}) css=${v.cssW}×${v.cssH}`);
    }
    const t = task();
    if (t) {
      lines.push(`${currentItem().task_id}: ${t.status} · ${Math.round(t.duration_ms / 1000)} s · rev ${sync.revs[currentItem().task_id] || 0}`);
      for (const s of SIDES) lines.push(`${s}: ` + t[s].map((p, i) => (p ? `${i + 1}(${p.x},${p.y})` : `${i + 1}-`)).join(' '));
    }
    return lines.join('\n');
  }
  let debugTimer = 0;
  $('btnDebug').addEventListener('click', () => {
    const p = $('debugPanel');
    p.hidden = !p.hidden;
    clearInterval(debugTimer);
    if (!p.hidden) {
      Debug.render();
      $('debugInfo').textContent = deviceInfo();
      refreshUsage().then(() => { $('debugInfo').textContent = deviceInfo(); });
      debugTimer = setInterval(() => { $('debugInfo').textContent = deviceInfo(); }, 500);
    }
  });
  $('btnDebugClose').addEventListener('click', () => { $('debugPanel').hidden = true; clearInterval(debugTimer); });
  $('btnDebugClear').addEventListener('click', () => Debug.clear());

  // ---------- เริ่ม ----------
  refreshFingerButton();
  setXView('box');
  refreshMarks();
  (async () => {
    try {
      state.storage = await Store.check();
      if (state.storage.ok) state.storage.persisted = await Store.persist();
      await refreshUsage();
    } catch (e) {
      state.storage = { ok: false, reason: String(e && (e.message || e)) };
    }
    Debug.log(`เริ่มแอป v${CFG.APP_VERSION} · เก็บคิวในเครื่อง ${state.storage.ok ? 'ได้' : 'ไม่ได้: ' + state.storage.reason}`);
    if (!state.storage.ok) toast('เบราว์เซอร์นี้เก็บงานสำรองในเครื่องไม่ได้ (โหมดส่วนตัว?) ถ้าเน็ตหลุด อย่าปิดเว็บจนกว่าจะบันทึกครบ', 7000);
    document.body.dataset.ready = '1';
    const reloading = await checkUpdate('start');
    if (!reloading) await boot();
  })();

  // ให้สคริปต์ทดสอบอัตโนมัติเข้าถึงได้
  window.__marker = {
    state, viewers, showTask, Debug, setFingerMode, undo, deleteSelected, goNext, save, editNote, skipTask, checkUpdate,
    sync, api, finish, openCase: (no) => openCase((state.cases || []).find((c) => c.no === no)), showCaseList,
    ghostFor, mismatchWarning, reviewEdits,
    flushSave: () => flushAll(10000),
    marks: () => { const t = task(); return t && { xray: t.xray, fluoro: t.fluoro, undo: (state.undo[currentItem().task_id] || []).length, status: t.status }; },
    task: () => task(),
    clearMarks: () => {
      const it = currentItem();
      if (it) { delete state.tasks[it.task_id]; delete state.undo[it.task_id]; }
      state.selected = null;
      for (const v of Object.values(viewers)) v.cancelSession();
      refreshMarks();
    },
  };
})();
