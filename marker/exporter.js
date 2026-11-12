// Exporter: สร้างไฟล์ CSV/JSON, ดาวน์โหลด/แชร์, อ่านและรวมไฟล์สำรอง
// ไม่มีข้อมูลระบุตัวผู้ป่วย: มีแค่ task_id (T001...), พิกัด, สถานะ, เวลา
(function () {
  'use strict';
  const FORMAT = 'pelnav-marks';
  const FORMAT_VERSION = 1;
  const FINAL = new Set(['done', 'partial', 'unmarkable']);
  const STATUSES = new Set(['todo', 'in_progress', 'skipped', 'done', 'partial', 'unmarkable']);   // skipped = ข้ามไว้ (ยังไม่เสร็จ)
  const COORD_CONVENTION = 'COCO pixel coordinates; origin (0,0) = top-left corner of the top-left pixel; '
    + 'pixel (i,j) center = (i+0.5, j+0.5); x to the right, y down; units = pixels of the original image file';

  const pad = (n, w = 2) => String(n).padStart(w, '0');
  function stamp(d = new Date()) {
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  }
  const countFinal = (tasks) => Object.values(tasks || {}).filter((t) => FINAL.has(t.status)).length;

  function jsonFilename(pkg, done, total) { return `marks_${pkg}_${stamp()}_${done}of${total}.json`; }
  function csvFilename(pkg) { return `marks_${pkg}_${stamp()}.csv`; }

  function buildJSON(ctx) {
    return JSON.stringify({
      format: FORMAT,
      format_version: FORMAT_VERSION,
      package_id: ctx.package_id,
      app_version: ctx.app_version,
      exported_at: new Date().toISOString(),
      coord_convention: COORD_CONVENTION,
      total_tasks: ctx.total_tasks,
      completed_tasks: countFinal(ctx.tasks),
      current_index: ctx.current_index,
      tasks: ctx.tasks,
    }, null, 1);
  }

  function csvCell(v) {
    if (v == null) return '';
    let s = String(v);
    if (/[",\r\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
    return s;
  }
  // ข้อความอิสระ: ตัด # และขึ้นบรรทัดใหม่ เพื่อให้อ่านด้วย pandas comment='#' ได้ปลอดภัย
  const cleanText = (s) => (s == null ? '' : String(s).replace(/[\r\n]+/g, ' ').replace(/#/g, '＃'));

  const CSV_COLUMNS = ['task_id', 'point_id', 'xray_x', 'xray_y', 'fluoro_x', 'fluoro_y',
    'xray_image_px_per_screen_px', 'fluoro_image_px_per_screen_px',
    'status', 'reason', 'reason_text', 'note', 'started_at', 'finished_at', 'duration_s',
    'is_repeat_of', 'app_version', 'package_id'];

  // items = manifest.items (ลำดับตาม manifest) · tasks = สถานะงาน
  function buildCSV(ctx) {
    const lines = [
      '# PelNavPlan landmark marks',
      `# package_id: ${ctx.package_id}`,
      `# app_version: ${ctx.app_version}`,
      `# exported_at: ${new Date().toISOString()}`,
      `# coord_convention: ${COORD_CONVENTION}`,
      '# reason codes: unclear, no_overlap, view_angle (large view-angle difference), no_4th_point, other; note = optional free text per task',
      '# to OpenCV convention (pixel centers at integers): subtract 0.5 from every x and y',
      "# read with pandas: pd.read_csv(path, comment='#', encoding='utf-8-sig')",
      '# one row per complete point pair; unmarkable tasks have one row with empty point_id/coordinates',
      CSV_COLUMNS.join(','),
    ];
    const f1 = (v) => (v == null ? '' : Number(v).toFixed(1));
    for (const it of ctx.items) {
      const t = ctx.tasks[it.task_id];
      if (!t || (t.status === 'todo' && !t.note)) continue;
      const common = {
        status: t.status, reason: t.reason || '', reason_text: cleanText(t.reason_text), note: cleanText(t.note),
        started_at: t.started_at || '', finished_at: t.finished_at || '',
        duration_s: Math.round((t.duration_ms || 0) / 1000),
        is_repeat_of: it.is_repeat_of || '', app_version: ctx.app_version, package_id: ctx.package_id,
      };
      const rows = [];
      if (t.status !== 'unmarkable') {
        for (let i = 0; i < t.xray.length; i++) {
          const a = t.xray[i], b = t.fluoro[i];
          if (!a || !b) continue;
          rows.push(Object.assign({
            task_id: it.task_id, point_id: i + 1,
            xray_x: f1(a.x), xray_y: f1(a.y), fluoro_x: f1(b.x), fluoro_y: f1(b.y),
            xray_image_px_per_screen_px: a.image_px_per_screen_px, fluoro_image_px_per_screen_px: b.image_px_per_screen_px,
          }, common));
        }
      }
      if (t.status === 'unmarkable' || rows.length === 0) rows.push(Object.assign({ task_id: it.task_id }, common));
      for (const r of rows) lines.push(CSV_COLUMNS.map((c) => csvCell(r[c])).join(','));
    }
    return '﻿' + lines.join('\r\n') + '\r\n';
  }

  // ---------- ดาวน์โหลด / แชร์ ----------
  function download(text, name, type) {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  function canShareFiles() {
    try {
      return !!(navigator.canShare && navigator.share &&
        navigator.canShare({ files: [new File(['x'], 'x.json', { type: 'application/json' })] }));
    } catch (_) { return false; }
  }

  // ส่งเฉพาะไฟล์: ถ้าใส่ title/text ด้วย แอปไฟล์ของ iOS จะบันทึกข้อความนั้นเป็นไฟล์แยกอีก 1 ไฟล์
  async function share(text, name, type) {
    const file = new File([text], name, { type });
    await navigator.share({ files: [file] });
  }

  // ---------- อ่านไฟล์สำรอง ----------
  function validPoint(p) {
    return p === null || (p && typeof p === 'object' && Number.isFinite(p.x) && Number.isFinite(p.y));
  }

  function parseBackup(text, manifest) {
    let d;
    try { d = JSON.parse(text.replace(/^﻿/, '')); } catch (e) { throw new Error(`ไฟล์ไม่ใช่ JSON (${e.message})`); }
    if (!d || d.format !== FORMAT) throw new Error('ไม่ใช่ไฟล์สำรองของเว็บนี้ (format ไม่ตรง)');
    if (d.format_version !== FORMAT_VERSION) throw new Error(`ไม่รองรับ format_version ${d.format_version}`);
    if (typeof d.package_id !== 'string' || !d.package_id) throw new Error('ไฟล์ไม่มี package_id');
    if (!d.tasks || typeof d.tasks !== 'object') throw new Error('ไฟล์ไม่มีข้อมูลงาน');
    const sizes = {};
    if (manifest && manifest.package_id === d.package_id) {
      for (const it of manifest.items) sizes[it.task_id] = { xray: it.xray_size, fluoro: it.fluoro_size };
    }
    const problems = [];
    for (const [id, t] of Object.entries(d.tasks)) {
      if (!/^T\d{3,}$/.test(id)) { problems.push(`${id}: รหัสงานไม่ถูกต้อง`); continue; }
      if (!t || !Array.isArray(t.xray) || !Array.isArray(t.fluoro) || t.xray.length !== t.fluoro.length) { problems.push(`${id}: โครงสร้างผิด`); continue; }
      if (!t.xray.every(validPoint) || !t.fluoro.every(validPoint)) problems.push(`${id}: พิกัดผิดรูปแบบ`);
      if (!STATUSES.has(t.status)) problems.push(`${id}: สถานะ ${t.status} ไม่รู้จัก`);
      if (t.note != null && typeof t.note !== 'string') problems.push(`${id}: หมายเหตุผิดรูปแบบ`);
      const sz = sizes[id];
      if (manifest && manifest.package_id === d.package_id && !sz) problems.push(`${id}: ไม่มีในแพ็กเกจที่เปิดอยู่`);
      if (sz) {
        for (const side of ['xray', 'fluoro']) {
          const [W, H] = sz[side];
          t[side].forEach((p, i) => {
            if (p && (p.x < 0 || p.y < 0 || p.x > W || p.y > H)) problems.push(`${id} จุด ${i + 1} ${side}: อยู่นอกภาพ`);
          });
        }
      }
    }
    if (problems.length) {
      const e = new Error('ไฟล์สำรองมีข้อมูลผิด — ไม่นำเข้า');
      e.details = problems.slice(0, 20);
      throw e;
    }
    return d;
  }

  // รวม: งานไหนมีทั้งสองฝั่ง ยึดอันที่แก้ล่าสุด (updated_at) ถ้าเท่ากันยึดของในเครื่อง
  function merge(localTasks, fileTasks) {
    const out = {};
    const stats = { fromFile: 0, added: 0, keptLocal: 0, localNewer: 0, same: 0 };
    const ids = new Set([...Object.keys(localTasks || {}), ...Object.keys(fileTasks || {})]);
    for (const id of ids) {
      const a = localTasks && localTasks[id], b = fileTasks && fileTasks[id];
      if (a && !b) { out[id] = a; stats.keptLocal++; continue; }
      if (b && !a) { out[id] = b; stats.added++; continue; }
      const ta = a.updated_at || '', tb = b.updated_at || '';
      if (JSON.stringify(a) === JSON.stringify(b)) { out[id] = a; stats.same++; }
      else if (tb > ta) { out[id] = b; stats.fromFile++; }
      else { out[id] = a; stats.localNewer++; }
    }
    return { tasks: out, stats };
  }

  window.Exporter = {
    FORMAT, COORD_CONVENTION, CSV_COLUMNS, countFinal, stamp,
    jsonFilename, csvFilename, buildJSON, buildCSV, download, canShareFiles, share, parseBackup, merge,
  };
})();
