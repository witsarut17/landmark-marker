// app.js: เชื่อมหน้าจอ + Loader + ImageViewer + การมาร์ก + บันทึก/สำรอง
// ขั้น 4: นำทาง, มาร์กไม่ได้/partial, เวลา, กรอบ, ปรับภาพ, เตือนจุดกระจุก
// ขั้น 5: บันทึกอัตโนมัติ (IndexedDB), บังคับสำรอง, ส่งออก/นำเข้า
(function () {
  'use strict';
  const CFG = window.MARKER_CONFIG;
  const N = CFG.marks.count;
  const SIDES = ['xray', 'fluoro'];
  const SIDE_NAME = { xray: 'เอกซเรย์', fluoro: 'ฟลู' };
  const FINAL = new Set(['done', 'partial', 'unmarkable']);
  const STATUS_NAME = { todo: 'ยังไม่ทำ', in_progress: 'กำลังทำ', done: 'เสร็จ 4 คู่', partial: 'เสร็จ 3 คู่', unmarkable: 'มาร์กไม่ได้' };
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
  };
  try {
    state.fingerMode = localStorage.getItem('fingerMode') === '1';
    state.showBox = localStorage.getItem('showBox') !== '0';
  } catch (_) { /* ignore */ }

  const currentItem = () => (state.manifest ? state.manifest.items[state.index] : null);
  const newTask = () => ({
    xray: new Array(N).fill(null), fluoro: new Array(N).fill(null),
    status: 'todo', reason: null, reason_text: null, note: null,
    started_at: null, finished_at: null, duration_ms: 0, updated_at: null,
  });
  function task() {
    const it = currentItem();
    if (!it) return null;
    if (!state.tasks[it.task_id]) state.tasks[it.task_id] = newTask();
    return state.tasks[it.task_id];
  }
  const pairCount = (t) => [...Array(N).keys()].filter((i) => t.xray[i] && t.fluoro[i]).length;
  const hasOrphans = (t) => [...Array(N).keys()].some((i) => !!t.xray[i] !== !!t.fluoro[i]);
  const completedCount = () => Object.values(state.tasks).filter((t) => FINAL.has(t.status)).length;
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
      emptyMessage: 'ยังไม่ได้เปิดแพ็กเกจ',
      getPoints: () => pointsFor(side),
      nextIndex: () => nextIndexFor(side),
      isFingerMode: () => state.fingerMode,
      onOverlay: side === 'xray' ? drawBox : null,
      onUserView: side === 'xray' ? () => setXView('custom') : null,
      onInfo: (i) => { info[side] = i; readoutEl.textContent = readoutText(side); },
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
        else toast('กดเมาส์ค้างไว้ครู่หนึ่ง แว่นขยายจะขึ้น แล้วขยับให้ตรง แล้วปล่อย');
      },
    });
  }
  const viewers = {
    xray: makeViewer('xray', $('viewerX'), $('readoutX')),
    fluoro: makeViewer('fluoro', $('viewerF'), $('readoutF')),
  };
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
      chip.textContent = ''; $('hintText').textContent = 'เปิดแพ็กเกจเพื่อเริ่ม'; $('pairCount').textContent = '';
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
        $('hintText').textContent = 'ครบ 4 คู่แล้ว — กด ถัดไป (ลากจุดเพื่อปรับได้)';
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
      }
      warn = SIDES.map(spreadWarning).filter(Boolean).join(' · ');
      if (warn) warn = '⚠ ' + warn + ' — ควรกระจายให้ทั่ว';
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
    $('taskLabel').textContent = m ? `${m.items[state.index].task_id} / ${n}` : '— / —';
    $('progress').textContent = m ? `เสร็จ ${completedCount()}/${n}` : '';
    $('btnPrev').disabled = !m || state.index <= 0;
    $('btnNext').disabled = !m;
    $('btnUnmarkable').disabled = !m;
    $('btnExport').disabled = !m;
    $('btnFinish').disabled = !m;
  }

  function refreshFingerButton() {
    const b = $('btnFinger');
    b.setAttribute('aria-pressed', String(state.fingerMode));
    b.textContent = `นิ้ววางจุด: ${state.fingerMode ? 'เปิด' : 'ปิด'}`;
    const touch = navigator.maxTouchPoints > 0;
    $('howTo').textContent = !touch
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

  // ---------- บันทึกลงเครื่อง ----------
  let saveChain = Promise.resolve();
  let saveFailures = 0, retryTimer = 0;
  function buildRecord() {
    return {
      package_id: state.manifest.package_id,
      app_version: CFG.APP_VERSION,
      saved_at: nowISO(),
      total_tasks: totalTasks(),
      current_index: state.index,
      last_backup_at: state.meta.last_backup_at,
      last_backup_completed: state.meta.last_backup_completed,
      backup_snoozed: state.meta.backup_snoozed,
      snooze_until: state.meta.snooze_until,
      tasks: JSON.parse(JSON.stringify(state.tasks)),
    };
  }
  function save() {
    if (!state.manifest || !state.storage.ok) return saveChain;
    const rec = buildRecord();
    // ข้อมูลทั้งหมดอยู่ในหน่วยความจำเสมอ ถ้าบันทึกครั้งนี้ไม่สำเร็จ ครั้งถัดไปจะบันทึกทั้งหมดซ้ำ (ไม่มีจุดหาย)
    saveChain = saveChain
      .then(() => Store.put(rec))
      .then(() => {
        if (state.saveError) Debug.log('บันทึกสำเร็จอีกครั้ง (ข้อมูลครบ)');
        state.meta.saved_at = rec.saved_at; state.saveError = null; saveFailures = 0; updateSaveLabel();
      })
      .catch((e) => {
        saveFailures++;
        state.saveError = (e && (e.message || e.name)) || 'ไม่ทราบสาเหตุ';
        Debug.error(`บันทึกไม่สำเร็จ (ครั้งที่ ${saveFailures}, จะลองใหม่): ${state.saveError}`);
        clearTimeout(retryTimer);
        retryTimer = setTimeout(save, 2000);       // ลองใหม่เอง
        updateSaveLabel();
        if (saveFailures >= 3 && document.visibilityState === 'visible') {
          toast('บันทึกลงเครื่องไม่สำเร็จ! กด ส่งออก เพื่อสำรองทันที', 6000);
        }
      });
    return saveChain;
  }
  function updateSaveLabel() {
    const l = $('saveLabel');
    if (state.saveError && saveFailures >= 2) { l.textContent = 'บันทึกไม่สำเร็จ!'; l.className = 'small err'; return; }
    if (state.saveError) { l.textContent = 'กำลังบันทึกใหม่…'; l.className = 'muted small'; return; }
    l.className = 'muted small';
    l.textContent = state.meta.saved_at ? `บันทึก ${new Date(state.meta.saved_at).toLocaleTimeString('th-TH')}` : '';
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') save();
    else onReturn();
  });
  window.addEventListener('pagehide', () => save());
  window.addEventListener('pageshow', () => onReturn());
  window.addEventListener('focus', () => onReturn());

  // กลับมาที่เว็บ (เช่น หลังดาวน์โหลดไฟล์สำรอง): บันทึกซ้ำ + ตรวจว่ายังอ่านไฟล์ภาพได้ไหม
  let returnBusy = false;
  async function onReturn() {
    if (!state.manifest || returnBusy) return;
    returnBusy = true;
    try {
      save();
      const it = currentItem();
      const f = it && state.byName && state.byName.get(it.xray);
      if (f && !(await Loader.probeReadable(f))) await filesLost();
    } finally { returnBusy = false; }
  }

  let filesLostOpen = false;
  async function filesLost() {
    if (filesLostOpen) return;
    filesLostOpen = true;
    await save();
    const it = currentItem();
    Debug.error('อ่านไฟล์ภาพที่เลือกไว้ไม่ได้แล้ว (iPad ปล่อยไฟล์) — ต้องเลือกไฟล์ใหม่');
    viewers.xray.clear('ต้องเลือกไฟล์แพ็กเกจอีกครั้ง');
    viewers.fluoro.clear('ต้องเลือกไฟล์แพ็กเกจอีกครั้ง');
    state.imagesReady = false;
    state.byName = null;
    const body = el('div', {}, [
      el('p', {}, [el('b', { text: 'งานที่ทำไว้บันทึกครบ ไม่หาย' })]),
      el('p', { text: 'iPad ปิดการเข้าถึงไฟล์ภาพที่เลือกไว้ (มักเกิดหลังดาวน์โหลดไฟล์สำรองหรือสลับไปแอปอื่น) จึงต้องเลือกไฟล์แพ็กเกจอีกครั้ง' }),
      el('p', { text: `กดปุ่มด้านล่าง → เข้าโฟลเดอร์แพ็กเกจเดิม → "เลือก" → "เลือกทั้งหมด" → "เปิด" แล้วจะกลับมาที่งาน ${it ? it.task_id : ''}` }),
    ]);
    const a = await dialog('ต้องเลือกไฟล์แพ็กเกจอีกครั้ง', body, [
      { label: 'เลือกไฟล์แพ็กเกจอีกครั้ง', value: 'pick', primary: true, id: 'btnRepick', onClick: () => $('inputFiles').click() },
      { label: 'ไปหน้าแรก', value: 'home', id: 'btnRepickHome' },
    ]);
    filesLostOpen = false;
    if (a === 'home') { $('startCloseRow').hidden = true; $('startScreen').hidden = false; renderStart(); }
  }

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
    if (++ticks % 10 === 0) save();
  }, 1000);

  // ---------- หน้าแรก ----------
  async function renderStart() {
    const st = state.storage;
    const ss = $('storageStatus');
    ss.innerHTML = '';
    const blocked = !st.ok;
    for (const l of [$('filesLabel'), $('folderLabel'), $('backupLabel')]) l.classList.toggle('disabled', blocked);
    document.querySelectorAll('#startScreen input[type=file]').forEach((i) => { i.disabled = blocked; });
    if (blocked) {
      ss.append(el('div', { class: 'box-err' }, [
        el('b', { text: 'เบราว์เซอร์นี้บันทึกงานลงเครื่องไม่ได้ — ห้ามเริ่มงาน' }), el('br'),
        `สาเหตุ: ${st.reason}`, el('br'),
        'อาจเป็นโหมดส่วนตัว (Private) ให้เปิดเว็บแบบปกติ หรือเปิดจากไอคอนบนหน้าจอโฮม',
      ]));
      $('savedList').innerHTML = '';
      $('noDataBox').hidden = true;
      return;
    }
    ss.append(el('div', { class: 'small' }, [
      'ที่เก็บข้อมูลในเครื่อง: ', el('span', { class: 'ok-text', text: 'ใช้ได้' }),
      ' · เบราว์เซอร์รับปากไม่ลบเอง: ',
      st.persisted ? el('span', { class: 'ok-text', text: 'ได้' })
        : el('span', { class: 'err-text', text: st.persisted === false ? 'ไม่ได้ (สำรองบ่อย ๆ)' : 'ไม่ทราบ (สำรองบ่อย ๆ)' }),
    ]));
    let recs = [];
    try { recs = (await Store.list()).filter((r) => r.package_id !== '__probe__'); } catch (e) { Debug.error(e); }
    const list = $('savedList');
    list.innerHTML = '';
    for (const r of recs) {
      const done = Exporter.countFinal(r.tasks);
      list.append(el('div', { class: 'saved-item', 'data-pkg': r.package_id }, [
        el('b', { text: `งานในเครื่อง: ${r.package_id}` }), el('br'),
        `ทำแล้ว ${done}/${r.total_tasks || '?'} งาน`, el('br'),
        `บันทึกล่าสุด: ${timeTH(r.saved_at)}`, el('br'),
        'สำรองล่าสุด: ',
        r.last_backup_at ? el('span', { text: timeTH(r.last_backup_at) }) : el('span', { class: 'err-text', text: 'ยังไม่เคยสำรอง' }),
      ]));
    }
    $('noDataBox').hidden = recs.length > 0;
  }

  // ---------- เปิดแพ็กเกจ ----------
  async function handleFiles(fileList) {
    await storageReady;
    if (!state.storage.ok) { toast('บันทึกลงเครื่องไม่ได้ — ห้ามเริ่มงาน'); return; }
    const status = $('loadStatus');
    status.className = 'status';
    status.textContent = `กำลังตรวจไฟล์ ${fileList.length} ไฟล์...`;
    try {
      const { manifest, byName, extra } = await Loader.openPackage(fileList);
      if (state.manifest) await save();
      let rec = null;
      try { rec = await Store.get(manifest.package_id); } catch (e) { Debug.error(e); }
      const ids = new Set(manifest.items.map((it) => it.task_id));
      const tasks = {};
      if (rec && rec.tasks) {
        for (const [id, t] of Object.entries(rec.tasks)) if (ids.has(id)) tasks[id]= t; else Debug.error(`งาน ${id} ในเครื่องไม่มีในแพ็กเกจ — ข้าม`);
      }
      state.manifest = manifest;
      state.byName = byName;
      state.tasks = tasks;
      state.undo = {};
      state.meta = {
        last_backup_at: rec ? rec.last_backup_at : null,
        last_backup_completed: rec ? rec.last_backup_completed || 0 : 0,
        backup_snoozed: rec ? !!rec.backup_snoozed : false,
        snooze_until: rec ? rec.snooze_until || 0 : 0,
        saved_at: rec ? rec.saved_at : null,
      };
      const idx = rec ? Math.max(0, Math.min(manifest.items.length - 1, rec.current_index || 0)) : 0;
      Debug.log(`เปิดแพ็กเกจ ${manifest.package_id}: ${manifest.items.length} งาน, ไฟล์เกิน ${extra.length}, งานที่บันทึกไว้ ${Object.keys(tasks).length}`);
      Store.persist().then((p) => { state.storage.persisted = p; });
      $('startScreen').hidden = true;
      status.textContent = '';
      if (rec) toast(`ทำต่อจากที่บันทึกไว้ (เสร็จ ${completedCount()}/${manifest.items.length})`);
      await showTask(idx);
    } catch (err) {
      status.className = 'status err';
      status.textContent = err.message;
      showError(err);
    }
  }

  // คัดลอก FileList เป็น array ก่อน: การล้าง input.value จะทำให้ FileList เดิมว่าง
  $('inputFiles').addEventListener('change', (e) => { const f = Array.from(e.target.files); e.target.value = ''; if (f.length) handleFiles(f); });
  $('inputFolder').addEventListener('change', (e) => { const f = Array.from(e.target.files); e.target.value = ''; if (f.length) handleFiles(f); });
  document.querySelectorAll('.inputBackup').forEach((inp) => inp.addEventListener('change', (e) => {
    const f = e.target.files[0];
    e.target.value = '';
    if (f) importBackup(f);
  }));
  $('btnOpen').addEventListener('click', async () => {
    await save();
    $('startCloseRow').hidden = !state.manifest;
    $('startScreen').hidden = false;
    renderStart();
  });
  $('btnStartClose').addEventListener('click', () => { $('startScreen').hidden = true; });

  const isIOS = /iP(ad|hone|od)/.test(navigator.userAgent) ||
    (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);
  if (isIOS || !('webkitdirectory' in document.createElement('input'))) $('folderLabel').hidden = true;
  if (!isIOS) $('ipadHint').hidden = true;

  // ---------- แสดงงาน ----------
  function releaseUrls() {
    for (const u of state.urls) URL.revokeObjectURL(u);
    state.urls = [];
  }

  async function showTask(i) {
    const m = state.manifest;
    if (!m) return;
    i = Math.max(0, Math.min(m.items.length - 1, i));
    state.index = i;
    state.selected = null;
    state.imagesReady = false;
    state.fluoroArea = null;
    const item = m.items[i];
    const t = task();
    if (!t.started_at) t.started_at = nowISO();
    save();
    const token = ++state.loadToken;
    viewers.xray.clear('กำลังโหลด...');
    viewers.fluoro.clear('กำลังโหลด...');
    refreshMarks();
    releaseUrls();
    try {
      const [x, f] = await Promise.all([
        Loader.loadImage(state.byName.get(item.xray), item.xray_size, `${item.task_id} เอกซเรย์`),
        Loader.loadImage(state.byName.get(item.fluoro), item.fluoro_size, `${item.task_id} ฟลู`),
      ]);
      if (token !== state.loadToken) { URL.revokeObjectURL(x.url); URL.revokeObjectURL(f.url); return; }
      state.urls.push(x.url, f.url);
      viewers.xray.setImage(x.img, x.W, x.H);
      viewers.fluoro.setImage(f.img, f.W, f.H);
      fitXrayToBox();
      state.fluoroArea = estimateFilledArea(f.img, f.W, f.H);
      state.imagesReady = true;
      refreshMarks();
      if (x.hasExif || f.hasExif) Debug.log(`${item.task_id}: มี EXIF แต่ Orientation = 1 (ไม่หมุน)`);
    } catch (err) {
      if (token !== state.loadToken) return;
      if (err instanceof Loader.FileAccessError) { await filesLost(); return; }
      viewers.xray.clear('หยุด: ดูข้อความแจ้งเตือน');
      viewers.fluoro.clear('หยุด: ดูข้อความแจ้งเตือน');
      showError(err);
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
      toast(`ยังไม่ครบ (${pc}/4 คู่) — ต้องครบ 4 คู่ หรือ 3 คู่พร้อมเหตุผล หรือกด "มาร์กไม่ได้"`, 3500);
      return;
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

  async function advance() {
    state.busy = true;
    try {
      refreshMarks();
      await maybeForceBackup('ทำครบอีก 10 งาน');
      const n = totalTasks();
      if (state.index < n - 1) { await showTask(state.index + 1); return; }
      const left = state.manifest.items.findIndex((it) => !FINAL.has((state.tasks[it.task_id] || {}).status));
      const btns = [];
      if (left >= 0) btns.push({ label: `ไปงานที่ยังไม่เสร็จ (${state.manifest.items[left].task_id})`, value: 'left', primary: true });
      btns.push({ label: 'จบการทำงาน', value: 'finish', primary: left < 0 }, { label: 'อยู่ที่งานนี้', value: 'stay' });
      const a = await dialog('ถึงงานสุดท้ายแล้ว', `เสร็จ ${completedCount()}/${n} งาน`, btns);
      if (a === 'left') await showTask(left);
      else if (a === 'finish') { state.busy = false; await finish(); }
    } finally { state.busy = false; }
  }

  // ---------- สำรอง / ส่งออก ----------
  function exportCtx() {
    return {
      package_id: state.manifest.package_id, app_version: CFG.APP_VERSION, total_tasks: totalTasks(),
      current_index: state.index, tasks: JSON.parse(JSON.stringify(state.tasks)), items: state.manifest.items,
    };
  }
  function backupDue() {
    const c = completedCount();
    if (c - state.meta.last_backup_completed < CFG.backup.everyNTasks) return false;
    return !state.meta.backup_snoozed || c >= state.meta.snooze_until;
  }
  async function maybeForceBackup(why) {
    if (backupDue()) await openExport({ forced: true, why });
  }

  function recordBackup() {
    state.meta.last_backup_at = nowISO();
    state.meta.last_backup_completed = completedCount();
    state.meta.backup_snoozed = false;
    state.meta.snooze_until = 0;
    save();
  }

  // forced: ต้องดาวน์โหลด (หรือเลื่อนได้ 1 ครั้ง) จึงจะปิดได้
  function openExport({ forced, why }) {
    return new Promise((resolve) => {
      const ctx = exportCtx();
      const done = Exporter.countFinal(ctx.tasks);
      const body = el('div', { class: 'summary' });
      if (forced) body.append(el('p', {}, [el('b', { text: `ถึงเวลาสำรองข้อมูล (${why})` }), el('br'),
        'ดาวน์โหลดไฟล์สำรองเก็บไว้ แล้วส่งให้ทีมหลังทำแต่ละรอบ']));
      body.append(el('table', {}, [
        el('tr', {}, [el('td', { text: 'แพ็กเกจ' }), el('td', { text: ctx.package_id })]),
        el('tr', {}, [el('td', { text: 'ทำแล้ว' }), el('td', { text: `${done}/${ctx.total_tasks} งาน` })]),
        el('tr', {}, [el('td', { text: 'สำรองล่าสุด' }), el('td', { text: state.meta.last_backup_at ? timeTH(state.meta.last_backup_at) : 'ยังไม่เคยสำรอง' })]),
      ]));
      const note = el('p', { class: 'ok-text', id: 'exportNote' });
      body.append(note);
      const jsonName = Exporter.jsonFilename(ctx.package_id, done, ctx.total_tasks);
      const btns = [];
      const close = (v) => { $('dialog').hidden = true; resolve(v); };
      const doJSON = () => {
        Exporter.download(Exporter.buildJSON(ctx), jsonName, 'application/json');
        recordBackup();
        Debug.log(`สำรอง ${jsonName}`);
        return 'downloaded';
      };
      $('dialogTitle').textContent = forced ? 'สำรองข้อมูล' : 'ส่งออก / สำรองข้อมูล';
      $('dialogBody').innerHTML = '';
      $('dialogBody').append(body);
      const row = $('dialogButtons');
      row.innerHTML = '';
      const mk = (label, id, primary, fn) => {
        const b = el('button', { class: `btn btn-big ${primary ? 'btn-primary' : ''}`, text: label, id });
        b.addEventListener('click', fn);
        row.append(b);
        btns.push(b);
      };
      // iPad + https: ปุ่มแชร์ (ไม่ออกจากหน้าเว็บ) เป็นปุ่มหลัก · ไม่มีแชร์: ดาวน์โหลด + คำแนะนำ
      const share = Exporter.canShareFiles();
      if (share) {
        mk(isIOS ? 'บันทึกไฟล์สำรองลงแอปไฟล์' : 'แชร์ไฟล์สำรอง', 'btnShareJson', isIOS, async () => {
          try {
            await Exporter.share(Exporter.buildJSON(ctx), jsonName, 'application/json');
            recordBackup();
            Debug.log(`สำรอง (แชร์) ${jsonName}`);
            if (forced) close('shared'); else note.textContent = `บันทึกแล้ว: ${jsonName}`;
          } catch (e) {
            if (e && e.name === 'AbortError') toast('ยกเลิกแล้ว — ยังไม่ได้สำรอง');
            else toast(`แชร์ไม่ได้: ${(e && e.message) || e} — ลองปุ่มดาวน์โหลด`, 5000);
          }
        });
      }
      mk('ดาวน์โหลดไฟล์สำรอง (JSON)', 'btnDlJson', !(share && isIOS), () => {
        doJSON();
        if (forced) close('downloaded'); else note.textContent = `ดาวน์โหลดแล้ว: ${jsonName}`;
      });
      if (isIOS) {
        body.append(el('p', { class: 'small muted' }, [
          share ? 'กด "บันทึกไฟล์สำรองลงแอปไฟล์" → "บันทึกไปยังไฟล์" → "บันทึก"'
            : 'หลังกดดาวน์โหลด ถ้าขึ้นหน้าแสดงไฟล์: กดปุ่มแชร์ (สี่เหลี่ยมมีลูกศรขึ้น) → "บันทึกไปยังไฟล์" → "บันทึก" → กด "เสร็จสิ้น" เพื่อกลับมา',
          el('br'), 'ถ้ากลับมาแล้วเว็บขอให้เลือกไฟล์ภาพอีกครั้ง ให้เลือกตามเดิม — งานไม่หาย',
        ]));
      }
      if (!forced) {
        mk('ดาวน์โหลด CSV (ผลมาร์ก)', 'btnDlCsv', false, () => {
          const name = Exporter.csvFilename(ctx.package_id);
          Exporter.download(Exporter.buildCSV(ctx), name, 'text/csv');
          note.textContent = `ดาวน์โหลดแล้ว: ${name}`;
        });
        mk('ปิด', 'btnExportClose', false, () => close('closed'));
      } else if (!state.meta.backup_snoozed) {
        mk('เลื่อนไปก่อน (ได้ 1 ครั้ง)', 'btnSnooze', false, () => {
          state.meta.backup_snoozed = true;
          state.meta.snooze_until = completedCount() + 1;
          save();
          toast('เลื่อนแล้ว — จะถามอีกครั้งหลังทำเสร็จอีก 1 งาน และเลื่อนไม่ได้อีก', 3500);
          close('snoozed');
        });
      }
      $('dialog').hidden = false;
    });
  }

  async function finish() {
    await save();
    await openExport({ forced: true, why: 'จบการทำงาน' });
    await save();
    $('startCloseRow').hidden = false;
    $('startScreen').hidden = false;
    renderStart();
    toast('บันทึกแล้ว ปิดเว็บได้ · อย่าลืมส่งไฟล์สำรองให้ทีม', 5000);
  }

  // ---------- นำเข้าไฟล์สำรอง ----------
  async function importBackup(file) {
    await storageReady;
    if (!state.storage.ok) { toast('บันทึกลงเครื่องไม่ได้ — นำเข้าไม่ได้'); return; }
    let d;
    try { d = Exporter.parseBackup(await file.text(), state.manifest); } catch (e) { showError(e); return; }
    if (state.manifest && state.manifest.package_id === d.package_id) await save();
    let local = null;
    try { local = await Store.get(d.package_id); } catch (e) { Debug.error(e); }
    const fileDone = Exporter.countFinal(d.tasks);
    const body = el('div', { class: 'summary' });
    body.append(el('p', {}, [`ไฟล์: ${file.name}`, el('br'), `แพ็กเกจ: ${d.package_id}`, el('br'),
      `ส่งออกเมื่อ: ${timeTH(d.exported_at)}`]));
    const rows = [['', 'ในไฟล์', 'ในเครื่อง'],
      ['งานที่มีข้อมูล', Object.keys(d.tasks).length, local ? Object.keys(local.tasks || {}).length : '—'],
      ['งานที่เสร็จ', fileDone, local ? Exporter.countFinal(local.tasks) : '—'],
      ['บันทึก/ส่งออกล่าสุด', timeTH(d.exported_at), local ? timeTH(local.saved_at) : '—']];
    body.append(el('table', {}, rows.map((r) => el('tr', {}, r.map((c) => el('td', { text: String(c) }))))));
    let choice;
    let merged = null;
    if (!local || !Object.keys(local.tasks || {}).length) {
      body.append(el('p', { text: 'ในเครื่องยังไม่มีงานของแพ็กเกจนี้ จะนำข้อมูลจากไฟล์เข้ามาทั้งหมด' }));
      choice = await dialog('นำเข้าไฟล์สำรอง', body, [
        { label: 'นำเข้า', value: 'replace', primary: true, id: 'btnImportReplace' },
        { label: 'ยกเลิก', value: null, id: 'btnImportCancel' }]);
    } else {
      merged = Exporter.merge(local.tasks, d.tasks);
      const s = merged.stats;
      body.append(el('p', {}, [
        el('b', { text: 'รวม' }), ` (ยึดงานที่แก้ล่าสุด): เพิ่มจากไฟล์ ${s.added} งาน · ใช้ของไฟล์ที่ใหม่กว่า ${s.fromFile} งาน · คงของในเครื่องที่ใหม่กว่า ${s.localNewer} งาน · เหมือนกัน ${s.same} งาน`,
        el('br'), el('b', { text: 'แทนที่' }), ': ข้อมูลในเครื่องของแพ็กเกจนี้ทั้งหมดจะถูกแทนด้วยไฟล์',
        el('br'), el('span', { class: 'muted', text: 'ข้อมูลในเครื่องก่อนนำเข้าจะถูกเก็บสำเนาไว้ในเครื่องอีกชุด' }),
      ]));
      choice = await dialog('นำเข้าไฟล์สำรอง — มีข้อมูลในเครื่องอยู่แล้ว', body, [
        { label: 'รวม (แนะนำ)', value: 'merge', primary: true, id: 'btnImportMerge' },
        { label: 'แทนที่', value: 'replace', id: 'btnImportReplace' },
        { label: 'ยกเลิก', value: null, id: 'btnImportCancel' }]);
    }
    if (!choice) return;
    try {
      if (local) await Store.snapshot(local, `before import (${choice})`);
      const tasks = choice === 'merge' ? merged.tasks : d.tasks;
      const later = (a, b) => ((a || '') > (b || '') ? a : b);
      const rec = Object.assign({}, local || {}, {
        package_id: d.package_id,
        app_version: CFG.APP_VERSION,
        saved_at: nowISO(),
        total_tasks: (local && local.total_tasks) || d.total_tasks,
        current_index: choice === 'replace' ? d.current_index || 0 : (local ? local.current_index : 0),
        tasks,
        last_backup_at: choice === 'replace' ? d.exported_at : later(local && local.last_backup_at, d.exported_at),
        last_backup_completed: Exporter.countFinal(tasks),
        backup_snoozed: false, snooze_until: 0,
      });
      await Store.put(rec);
      Debug.log(`นำเข้า ${file.name} (${choice})`);
      if (state.manifest && state.manifest.package_id === d.package_id) {
        state.tasks = JSON.parse(JSON.stringify(tasks));
        state.undo = {};
        state.meta.last_backup_at = rec.last_backup_at;
        state.meta.last_backup_completed = rec.last_backup_completed;
        state.meta.backup_snoozed = false;
        state.meta.snooze_until = 0;
        await showTask(Math.min(state.index, totalTasks() - 1));
      }
      toast(`นำเข้าแล้ว (${choice === 'merge' ? 'รวม' : 'แทนที่'}) — งานเสร็จ ${Exporter.countFinal(tasks)} งาน`, 4000);
      renderStart();
    } catch (e) { showError(e); }
  }

  // ---------- ปุ่ม / คีย์ลัด ----------
  $('btnPrev').addEventListener('click', () => { if (!state.busy) showTask(state.index - 1); });
  $('btnNext').addEventListener('click', goNext);
  $('btnUnmarkable').addEventListener('click', markUnmarkable);
  $('btnNote').addEventListener('click', editNote);
  $('btnExport').addEventListener('click', () => openExport({ forced: false }));
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
    if (!$('dialog').hidden || !$('startScreen').hidden) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
    else if (e.key === 'Escape') { for (const v of Object.values(viewers)) v.cancelSession(); }
    else if (e.key === 'ArrowLeft') { if (!state.busy) showTask(state.index - 1); }
    else if (e.key === 'ArrowRight') goNext();
  });
  window.addEventListener('blur', () => { for (const v of Object.values(viewers)) v.cancelSession(); });
  for (const ev of ['gesturestart', 'gesturechange', 'gestureend']) {
    document.addEventListener(ev, (e) => e.preventDefault(), { passive: false });
  }

  // ---------- แผงดีบัก ----------
  function deviceInfo() {
    const lines = [
      `app ${CFG.APP_VERSION} · storage ${state.storage.ok ? 'ok' : 'BLOCKED'} persisted=${state.storage.persisted} quota=${state.storage.quotaMB}MB`,
      `viewport ${window.innerWidth}×${window.innerHeight} CSS px · dpr ${window.devicePixelRatio}`,
      `pointer types: ${[...pointerTypesSeen].join(', ') || '-'} · นิ้ววางจุด: ${state.fingerMode ? 'เปิด' : 'ปิด'}`,
      `UA: ${navigator.userAgent}`,
    ];
    for (const [k, v] of Object.entries(viewers)) {
      if (v.img) lines.push(`${k}: ${v.W}×${v.H} s=${v.s.toFixed(4)} zoom=${v.zoom.toFixed(2)}× loupe×${v.loupeScale().toFixed(1)} t=(${v.tx.toFixed(1)}, ${v.ty.toFixed(1)}) css=${v.cssW}×${v.cssH}`);
    }
    const t = task();
    if (t) {
      lines.push(`${currentItem().task_id}: ${t.status} · ${Math.round(t.duration_ms / 1000)} s`);
      for (const s of SIDES) lines.push(`${s}: ` + t[s].map((p, i) => (p ? `${i + 1}(${p.x},${p.y})` : `${i + 1}-`)).join(' '));
    }
    return lines.join('\n');
  }
  let debugTimer = 0;
  $('btnDebug').addEventListener('click', () => {
    const p = $('debugPanel');
    p.hidden = !p.hidden;
    clearInterval(debugTimer);
    if (!p.hidden) { Debug.render(); $('debugInfo').textContent = deviceInfo(); debugTimer = setInterval(() => { $('debugInfo').textContent = deviceInfo(); }, 500); }
  });
  $('btnDebugClose').addEventListener('click', () => { $('debugPanel').hidden = true; clearInterval(debugTimer); });
  $('btnDebugClear').addEventListener('click', () => Debug.clear());

  // ---------- เริ่ม ----------
  refreshFingerButton();
  setXView('box');
  refreshMarks();
  const storageReady = (async () => {
    try {
      state.storage = await Store.check();
      if (state.storage.ok) state.storage.persisted = await Store.persist();
    } catch (e) {
      state.storage = { ok: false, reason: String(e && (e.message || e)) };
    }
    Debug.log(`เริ่มแอป v${CFG.APP_VERSION} · storage ${state.storage.ok ? 'ok' : 'BLOCKED: ' + state.storage.reason}`);
    await renderStart();
    document.body.dataset.ready = '1';
  })();

  // ให้สคริปต์ทดสอบอัตโนมัติเข้าถึงได้
  window.__marker = {
    state, viewers, showTask, Debug, setFingerMode, undo, deleteSelected, goNext, save, editNote,
    flushSave: () => saveChain,
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
