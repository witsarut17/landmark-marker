// Loader: รับไฟล์ที่หมอเลือก -> หา manifest.json -> ตรวจความถูกต้อง -> โหลดภาพทีละงาน
// ภาพไม่ถูกส่งไปไหน: อ่านจาก File ในเครื่องผ่าน blob: URL เท่านั้น
(function () {
  'use strict';

  class BlockingError extends Error {
    constructor(title, details = []) { super(title); this.name = 'BlockingError'; this.details = details; }
  }

  // อ่านไฟล์ที่เลือกไว้ไม่ได้แล้ว (iPad ปล่อยไฟล์หลังดาวน์โหลด/สลับแอป) -> ต้องเลือกไฟล์ใหม่ งานไม่หาย
  class FileAccessError extends Error {
    constructor(fileName, cause) {
      super(`อ่านไฟล์ ${fileName} ไม่ได้แล้ว`);
      this.name = 'FileAccessError';
      this.cause = cause;
    }
  }

  async function readSlice(file, end) {
    try {
      return new Uint8Array(await (end == null ? file : file.slice(0, end)).arrayBuffer());
    } catch (e) {
      throw new FileAccessError(file.name, e);
    }
  }

  async function probeReadable(file) {
    try { await file.slice(0, 1).arrayBuffer(); return true; } catch (_) { return false; }
  }

  // ---------- รวบรวมไฟล์ ----------
  function collectFiles(fileList) {
    const byName = new Map();
    const duplicates = [];
    for (const f of fileList) {
      const name = f.name;                 // ชื่อไฟล์อย่างเดียว ไม่มีโฟลเดอร์
      if (name.startsWith('.')) continue;  // ข้ามไฟล์ซ่อน เช่น .DS_Store
      if (byName.has(name)) duplicates.push(name);
      else byName.set(name, f);
    }
    return { byName, duplicates };
  }

  // ---------- manifest ----------
  const isPosInt = (v) => Number.isInteger(v) && v > 0;
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  function validateManifest(m) {
    const errors = [];
    if (!m || typeof m !== 'object') return ['manifest ไม่ใช่ JSON object'];
    if (typeof m.package_id !== 'string' || !m.package_id) errors.push('ไม่มี package_id');
    if (!Array.isArray(m.items) || m.items.length === 0) { errors.push('ไม่มี items'); return errors; }

    const ids = new Set();
    const files = new Set();
    m.items.forEach((it, i) => {
      const at = `items[${i}]` + (it && it.task_id ? ` (${it.task_id})` : '');
      if (!it || typeof it !== 'object') { errors.push(`${at}: ไม่ใช่ object`); return; }
      if (typeof it.task_id !== 'string' || !/^T\d{3,}$/.test(it.task_id)) errors.push(`${at}: task_id ไม่ถูกรูปแบบ`);
      else if (ids.has(it.task_id)) errors.push(`${at}: task_id ซ้ำ`);
      else ids.add(it.task_id);

      for (const k of ['xray', 'fluoro']) {
        const n = it[k];
        if (typeof n !== 'string' || !n || /[\\/]/.test(n)) errors.push(`${at}: ชื่อไฟล์ ${k} ไม่ถูกต้อง`);
        else if (!/\.(jpe?g|png)$/i.test(n)) errors.push(`${at}: ${k} ต้องเป็น .jpg/.jpeg/.png`);
        else if (files.has(n)) errors.push(`${at}: ชื่อไฟล์ ${n} ถูกใช้ซ้ำ`);
        else files.add(n);
      }
      for (const k of ['xray_size', 'fluoro_size']) {
        const s = it[k];
        if (!Array.isArray(s) || s.length !== 2 || !isPosInt(s[0]) || !isPosInt(s[1])) errors.push(`${at}: ${k} ต้องเป็น [W, H] จำนวนเต็มบวก`);
      }
      const b = it.box_xyxy;
      if (!Array.isArray(b) || b.length !== 4 || !b.every(isNum)) errors.push(`${at}: box_xyxy ต้องเป็นตัวเลข 4 ค่า`);
      else if (!(b[0] < b[2] && b[1] < b[3])) errors.push(`${at}: box_xyxy ต้อง x1<x2 และ y1<y2`);
      else if (Array.isArray(it.xray_size)) {
        const [W, H] = it.xray_size;
        if (b[0] < 0 || b[1] < 0 || b[2] > W || b[3] > H) errors.push(`${at}: box_xyxy เกินขอบภาพเอกซเรย์`);
      }
      if (it.rotation !== undefined && !isNum(it.rotation)) errors.push(`${at}: rotation ต้องเป็นตัวเลข`);
    });
    m.items.forEach((it, i) => {
      if (it && it.is_repeat_of != null && !ids.has(it.is_repeat_of)) errors.push(`items[${i}]: is_repeat_of อ้างถึงงานที่ไม่มี`);
    });
    return errors;
  }

  async function openPackage(fileList) {
    const { byName, duplicates } = collectFiles(fileList);
    const mf = byName.get('manifest.json');
    if (!mf) throw new BlockingError('ไม่พบไฟล์ manifest.json', ['ต้องเลือก manifest.json มาพร้อมกับภาพทั้งหมด']);

    let manifest, manifestText;
    try { manifestText = await mf.text(); manifest = JSON.parse(manifestText); }
    catch (e) { throw new BlockingError('อ่าน manifest.json ไม่ได้', [String(e.message || e)]); }

    const errors = validateManifest(manifest);
    if (errors.length) throw new BlockingError('manifest.json ไม่ถูกต้อง', errors);

    const missing = [];
    for (const it of manifest.items) for (const k of ['xray', 'fluoro']) if (!byName.has(it[k])) missing.push(it[k]);
    const dupUsed = duplicates.filter((n) => manifest.items.some((it) => it.xray === n || it.fluoro === n));
    if (dupUsed.length) throw new BlockingError('มีไฟล์ชื่อซ้ำกัน ไม่รู้ว่าจะใช้ไฟล์ไหน', dupUsed);
    if (missing.length) {
      throw new BlockingError(`ขาดไฟล์ภาพ ${missing.length} ไฟล์`,
        missing.slice(0, 30).concat(missing.length > 30 ? [`... และอีก ${missing.length - 30} ไฟล์`] : []));
    }
    const used = new Set(['manifest.json']);
    manifest.items.forEach((it) => { used.add(it.xray); used.add(it.fluoro); });
    const extra = [...byName.keys()].filter((n) => !used.has(n));
    return { manifest, manifestText, byName, extra };
  }

  // manifest ที่เก็บไว้ในเครื่อง (เปิดงานต่อโดยไม่ต้องเลือกไฟล์) — ตรวจแบบเดียวกับตอนเลือกไฟล์
  function parseStoredManifest(text) {
    let manifest;
    try { manifest = JSON.parse(text); } catch (e) { throw new BlockingError('manifest ที่เก็บในเครื่องอ่านไม่ได้', [String(e.message || e)]); }
    const errors = validateManifest(manifest);
    if (errors.length) throw new BlockingError('manifest ที่เก็บในเครื่องไม่ถูกต้อง', errors);
    return manifest;
  }

  // ---------- EXIF Orientation (อ่านจากไบต์เอง) ----------
  function sniff(u8) {
    if (u8.length >= 3 && u8[0] === 0xFF && u8[1] === 0xD8 && u8[2] === 0xFF) return 'jpeg';
    const sig = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
    if (u8.length >= 8 && sig.every((v, i) => u8[i] === v)) return 'png';
    return null;
  }

  // อ่าน Orientation จาก TIFF block (ใช้ทั้ง JPEG APP1 และ PNG eXIf)
  function tiffOrientation(dv, start, end) {
    if (start + 8 > end) return null;
    const bo = dv.getUint16(start);
    const le = bo === 0x4949; if (!le && bo !== 0x4D4D) return null;
    const ifd = start + dv.getUint32(start + 4, le);
    if (ifd + 2 > end) return null;
    const n = dv.getUint16(ifd, le);
    for (let i = 0; i < n; i++) {
      const e = ifd + 2 + i * 12;
      if (e + 12 > end) break;
      if (dv.getUint16(e, le) === 0x0112) return dv.getUint16(e + 8, le);
    }
    return null;
  }

  function jpegExif(u8) {
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    let o = 2;
    while (o + 4 <= u8.length) {
      if (u8[o] !== 0xFF) return { found: false, complete: true };
      const marker = u8[o + 1];
      if (marker === 0xFF) { o++; continue; }               // fill byte
      if (marker === 0xDA || marker === 0xD9) return { found: false, complete: true }; // เริ่มข้อมูลภาพ
      if (marker >= 0xD0 && marker <= 0xD7) { o += 2; continue; }
      const len = dv.getUint16(o + 2);
      if (marker === 0xE1 && o + 10 <= u8.length &&
          u8[o + 4] === 0x45 && u8[o + 5] === 0x78 && u8[o + 6] === 0x69 && u8[o + 7] === 0x66) {
        return { found: true, orientation: tiffOrientation(dv, o + 10, Math.min(u8.length, o + 2 + len)), complete: true };
      }
      o += 2 + len;
    }
    return { found: false, complete: false };              // ยังไม่ถึง SOS -> ต้องอ่านเพิ่ม
  }

  function pngExif(u8) {
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    let o = 8;
    while (o + 8 <= u8.length) {
      const len = dv.getUint32(o);
      const type = String.fromCharCode(u8[o + 4], u8[o + 5], u8[o + 6], u8[o + 7]);
      if (type === 'IDAT' || type === 'IEND') return { found: false, complete: true };
      if (type === 'eXIf') {
        return { found: true, orientation: tiffOrientation(dv, o + 8, Math.min(u8.length, o + 8 + len)), complete: true };
      }
      o += 12 + len;
    }
    return { found: false, complete: false };
  }

  async function checkFileBytes(file, label) {
    let u8 = await readSlice(file, 256 * 1024);
    const kind = sniff(u8);
    const ext = /\.png$/i.test(file.name) ? 'png' : 'jpeg';
    if (!kind) throw new BlockingError(`${label}: ไฟล์ ${file.name} ไม่ใช่ JPEG/PNG`);
    if (kind !== ext) throw new BlockingError(`${label}: นามสกุลไฟล์ ${file.name} ไม่ตรงกับชนิดจริง (${kind})`);
    const parse = kind === 'jpeg' ? jpegExif : pngExif;
    let r = parse(u8);
    if (!r.complete && file.size > u8.length) {
      u8 = await readSlice(file, null);
      r = parse(u8);
    }
    if (r.found && r.orientation != null && r.orientation !== 1) {
      throw new BlockingError(`${label}: ภาพ ${file.name} มีค่า EXIF Orientation = ${r.orientation}`, [
        'เบราว์เซอร์อาจหมุนภาพเองทำให้พิกัดผิด จึงหยุดไว้ก่อน',
        'แจ้งทีม: ให้สร้างแพ็กเกจใหม่ด้วย make_study_package.py (ลบ EXIF)',
      ]);
    }
    return { kind, hasExif: r.found };
  }

  // ---------- โหลดภาพ ----------
  async function loadImage(file, expected, label) {
    const info = await checkFileBytes(file, label);
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    try {
      if (img.decode) await img.decode();
      else await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad; });
    } catch (e) {
      URL.revokeObjectURL(url);
      if (!(await probeReadable(file))) throw new FileAccessError(file.name, e);
      throw new BlockingError(`${label}: เปิดภาพ ${file.name} ไม่ได้ (ไฟล์อาจเสียหรือใหญ่เกินหน่วยความจำ)`);
    }
    const [W, H] = expected;
    if (img.naturalWidth !== W || img.naturalHeight !== H) {
      URL.revokeObjectURL(url);
      throw new BlockingError(`${label}: ขนาดภาพไม่ตรงกับ manifest — หยุดเพื่อป้องกันพิกัดผิด`, [
        `ไฟล์: ${file.name}`,
        `ขนาดจริง ${img.naturalWidth} × ${img.naturalHeight}`,
        `manifest ระบุ ${W} × ${H}`,
        'ห้ามมาร์กงานนี้ แจ้งทีมผู้พัฒนา',
      ]);
    }
    return { img, url, W, H, hasExif: info.hasExif };
  }

  window.Loader = { BlockingError, FileAccessError, probeReadable, openPackage, parseStoredManifest, validateManifest, loadImage, _jpegExif: jpegExif, _pngExif: pngExif };
})();
