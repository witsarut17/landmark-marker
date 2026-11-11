// ImageStore: เก็บภาพของแพ็กเกจไว้ในเครื่อง (IndexedDB "pelnav-images" แยกจากฐานข้อมูลจุด "pelnav-marker")
//   ลบภาพทั้งหมดได้โดยไม่แตะจุดที่มาร์กไว้ · ภาพไม่ถูกส่งไปไหน
//   packages : 1 record ต่อแพ็กเกจ (key = package_id) — manifest, รายชื่อไฟล์ ขนาด และ SHA-256 ของแต่ละไฟล์, complete
//   files    : 1 record ต่อไฟล์ภาพ (key = "<package_id>/<ชื่อไฟล์>") — blob
(function () {
  'use strict';
  const DB_NAME = 'pelnav-images';
  const DB_VERSION = 1;
  const FLAG = 'localImages';          // localStorage: package_id ที่เก็บภาพครบแล้ว (ใช้แยก "ภาพหาย" ออกจาก "ไม่เคยเก็บ")
  let dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      let req;
      try { req = indexedDB.open(DB_NAME, DB_VERSION); } catch (e) { reject(e); return; }
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('packages')) db.createObjectStore('packages', { keyPath: 'package_id' });
        if (!db.objectStoreNames.contains('files')) db.createObjectStore('files', { keyPath: 'key' });
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => { db.close(); dbPromise = null; };
        db.onclose = () => { dbPromise = null; };
        resolve(db);
      };
      req.onerror = () => reject(req.error || new Error('เปิดที่เก็บภาพในเครื่องไม่ได้'));
      req.onblocked = () => reject(new Error('ที่เก็บภาพถูกบล็อก (มีแท็บอื่นเปิดอยู่?)'));
    });
    dbPromise.catch(() => { dbPromise = null; });
    return dbPromise;
  }

  function closeDb() {
    const p = dbPromise;
    dbPromise = null;
    if (p) return p.then((db) => { try { db.close(); } catch (_) { /* ignore */ } }).catch(() => {});
    return Promise.resolve();
  }

  // stores = ชื่อ store หรือ array · fn(t) คืน IDBRequest (ผลลัพธ์) หรือไม่คืนก็ได้
  function tx(stores, mode, fn) {
    return open().then((db) => new Promise((resolve, reject) => {
      let t, result;
      try { t = db.transaction(stores, mode); } catch (e) { reject(e); return; }
      t.oncomplete = () => resolve(result);
      t.onerror = (ev) => reject((ev && ev.target && ev.target.error) || t.error ||
        new Error('ที่เก็บภาพผิดพลาด (อาจเพราะแอปถูกพักไว้เบื้องหลัง)'));
      t.onabort = () => reject(t.error || new Error('การเก็บภาพถูกยกเลิก (อาจเพราะแอปถูกพักไว้เบื้องหลัง หรือพื้นที่ไม่พอ)'));
      try {
        const r = fn(t);
        if (r) r.onsuccess = () => { result = r.result; };
      } catch (e) { reject(e); }
    }));
  }

  const fileKey = (pkg, name) => `${pkg}/${name}`;
  const pkgRange = (pkg) => IDBKeyRange.bound(`${pkg}/`, `${pkg}/￿`);
  const neededNames = (manifest) => manifest.items.flatMap((it) => [it.xray, it.fluoro]);
  const mimeOf = (name) => (/\.png$/i.test(name) ? 'image/png' : 'image/jpeg');

  async function sha256(buf) {
    try {
      if (!(window.crypto && crypto.subtle)) return null;      // http ที่ไม่ใช่ localhost ไม่มี crypto.subtle
      const h = new Uint8Array(await crypto.subtle.digest('SHA-256', buf));
      return Array.from(h, (b) => b.toString(16).padStart(2, '0')).join('');
    } catch (_) { return null; }
  }

  function setFlag(pkg) { try { if (pkg) localStorage.setItem(FLAG, pkg); else localStorage.removeItem(FLAG); } catch (_) { /* ignore */ } }
  function getFlag() { try { return localStorage.getItem(FLAG); } catch (_) { return null; } }

  const ImageStore = {
    DB_NAME,
    _close: closeDb,
    flag: getFlag,

    getRecord: (pkg) => tx('packages', 'readonly', (t) => t.objectStore('packages').get(pkg)),
    listRecords: () => tx('packages', 'readonly', (t) => t.objectStore('packages').getAll()),
    storedNames: (pkg) => tx('files', 'readonly', (t) => t.objectStore('files').getAllKeys(pkgRange(pkg)))
      .then((keys) => (keys || []).map((k) => String(k).slice(pkg.length + 1))),

    // ตรวจความครบ (ไม่อ่านภาพ): record ต้อง complete และมีไฟล์ครบทุกชื่อใน manifest
    async check(pkg) {
      const rec = await ImageStore.getRecord(pkg);
      if (!rec) return { ok: false, rec: null, missing: [], need: 0 };
      let manifest;
      try { manifest = JSON.parse(rec.manifest_text); } catch (_) { return { ok: false, rec, missing: ['manifest'], need: 0 }; }
      const need = neededNames(manifest);
      const have = new Set(await ImageStore.storedNames(pkg));
      const missing = need.filter((n) => !have.has(n) || !rec.files || !rec.files[n]);
      return { ok: !!rec.complete && missing.length === 0, rec, manifest, missing, need: need.length };
    },

    // คัดลอกภาพจาก File ที่หมอเลือกเข้าเครื่อง ทีละไฟล์ (ไม่โหลดทั้งหมดเข้าหน่วยความจำ)
    // ไฟล์ที่เก็บไว้แล้วและขนาดเท่าเดิมจะข้าม (เก็บต่อจากที่ค้างได้) · onProgress({done, total, bytes})
    async save(manifest, manifestText, byName, onProgress) {
      const pkg = manifest.package_id;
      const names = neededNames(manifest);
      let rec = await ImageStore.getRecord(pkg);
      if (rec && rec.manifest_text !== manifestText) {      // แพ็กเกจชื่อเดิมแต่เนื้อหาเปลี่ยน -> ล้างของเก่าก่อน
        await ImageStore.removePackage(pkg);
        rec = null;
      }
      rec = rec || { package_id: pkg, manifest_text: manifestText, files: {}, total_files: names.length, bytes: 0 };
      rec.complete = false;
      rec.app_version = window.MARKER_CONFIG.APP_VERSION;
      setFlag(null);
      await tx('packages', 'readwrite', (t) => t.objectStore('packages').put(rec));
      const have = new Set(await ImageStore.storedNames(pkg));
      let done = 0;
      for (const name of names) {
        const f = byName.get(name);
        const old = rec.files[name];
        if (!(have.has(name) && old && old.size === f.size)) {
          let buf;
          try { buf = await f.arrayBuffer(); } catch (e) { throw new Loader.FileAccessError(name, e); }
          const entry = { size: buf.byteLength, sha256: await sha256(buf) };
          const blob = new Blob([buf], { type: mimeOf(name) });
          rec.files[name] = entry;
          rec.bytes = Object.values(rec.files).reduce((a, b) => a + b.size, 0);
          // ไฟล์ + รายการไฟล์ใน transaction เดียว -> ถ้าถูกขัดจังหวะ ไม่มีไฟล์ที่ไม่มีรายการ
          await tx(['files', 'packages'], 'readwrite', (t) => {
            t.objectStore('files').put({ key: fileKey(pkg, name), package_id: pkg, name, blob, size: entry.size });
            t.objectStore('packages').put(rec);
          });
        }
        done++;
        if (onProgress) onProgress({ done, total: names.length, bytes: rec.bytes });
      }
      const chk = await ImageStore.check(pkg);
      if (chk.missing.length) throw new Error(`เก็บภาพไม่ครบ ขาด ${chk.missing.length} ไฟล์`);
      rec.complete = true;
      rec.stored_at = new Date().toISOString();
      await tx('packages', 'readwrite', (t) => t.objectStore('packages').put(rec));
      setFlag(pkg);
      return rec;
    },

    // คืน File ของภาพ (null = ไม่มีในเครื่อง หรือไม่ตรงกับตอนเก็บ)
    async getFile(pkg, name, rec, verify = true) {
      const e = await tx('files', 'readonly', (t) => t.objectStore('files').get(fileKey(pkg, name)));
      const meta = rec && rec.files && rec.files[name];
      if (!e || !e.blob || !meta || e.blob.size !== meta.size) return null;
      if (verify && meta.sha256) {
        const h = await sha256(await e.blob.arrayBuffer());
        if (h && h !== meta.sha256) return null;
      }
      return new File([e.blob], name, { type: mimeOf(name) });
    },

    // ลบภาพไฟล์เดียวที่เสีย/ไม่ตรง -> แพ็กเกจกลายเป็น "ไม่ครบ" และเลือกไฟล์ใหม่แล้วจะเก็บไฟล์นี้ซ้ำ
    async removeFile(pkg, name) {
      const rec = await ImageStore.getRecord(pkg);
      await tx(['files', 'packages'], 'readwrite', (t) => {
        t.objectStore('files').delete(fileKey(pkg, name));
        if (rec) {
          delete rec.files[name];
          rec.complete = false;
          rec.bytes = Object.values(rec.files).reduce((a, b) => a + b.size, 0);
          t.objectStore('packages').put(rec);
        }
      });
      setFlag(null);
    },

    removePackage: (pkg) => tx(['files', 'packages'], 'readwrite', (t) => {
      t.objectStore('files').delete(pkgRange(pkg));
      t.objectStore('packages').delete(pkg);
    }),

    // ลบภาพทั้งหมดออกจากเครื่อง: ล้าง store ก่อน (ได้ผลแม้มีแท็บอื่นเปิด) แล้วลบทั้งฐานข้อมูลเพื่อคืนพื้นที่
    // ไม่แตะฐานข้อมูลจุด (pelnav-marker)
    async removeAll() {
      try {
        await tx(['files', 'packages'], 'readwrite', (t) => { t.objectStore('files').clear(); t.objectStore('packages').clear(); });
      } catch (_) { /* ลบทั้งฐานข้อมูลต่อ */ }
      await closeDb();
      setFlag(null);
      return new Promise((resolve) => {
        let r;
        try { r = indexedDB.deleteDatabase(DB_NAME); } catch (_) { resolve(false); return; }
        r.onsuccess = () => resolve(true);
        r.onerror = () => resolve(false);
        r.onblocked = () => resolve(false);      // แท็บอื่นยังเปิดอยู่: ภาพถูกล้างแล้ว พื้นที่จะคืนเมื่อปิดแท็บนั้น
      });
    },
  };

  window.ImageStore = ImageStore;
})();
