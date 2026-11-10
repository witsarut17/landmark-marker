// Store: บันทึกงานลง IndexedDB ในเครื่อง (ไม่มีอะไรส่งออกนอกเครื่อง)
//   packages  : 1 record ต่อแพ็กเกจ (key = package_id) — สถานะงานทั้งหมด
//   snapshots : สำเนาข้อมูลก่อนนำเข้าไฟล์สำรอง (กันพลาด)
(function () {
  'use strict';
  const DB_NAME = 'pelnav-marker';
  const DB_VERSION = 1;
  let dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      let req;
      try { req = indexedDB.open(DB_NAME, DB_VERSION); } catch (e) { reject(e); return; }
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('packages')) db.createObjectStore('packages', { keyPath: 'package_id' });
        if (!db.objectStoreNames.contains('snapshots')) db.createObjectStore('snapshots', { keyPath: 'id' });
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => { db.close(); dbPromise = null; };
        // iOS ตัดการเชื่อมต่อตอนแอปถูกพักไว้เบื้องหลัง -> ครั้งหน้าเปิดใหม่
        db.onclose = () => { dbPromise = null; };
        resolve(db);
      };
      req.onerror = () => reject(req.error || new Error('เปิด IndexedDB ไม่ได้'));
      req.onblocked = () => reject(new Error('IndexedDB ถูกบล็อก (มีแท็บอื่นเปิดอยู่?)'));
    });
    dbPromise.catch(() => { dbPromise = null; });
    return dbPromise;
  }

  function resetDb() {
    const p = dbPromise;
    dbPromise = null;
    if (p) p.then((db) => { try { db.close(); } catch (_) { /* ignore */ } }).catch(() => {});
  }

  function txOnce(store, mode, fn) {
    return open().then((db) => new Promise((resolve, reject) => {
      let t, result;
      try { t = db.transaction(store, mode); } catch (e) { reject(e); return; }
      t.oncomplete = () => resolve(result);
      // Safari บางครั้งให้ error = null (เช่น การเชื่อมต่อถูกตัด) -> ใส่ข้อความแทน ไม่ให้เป็น "null"
      t.onerror = (ev) => reject((ev && ev.target && ev.target.error) || t.error ||
        new Error('IndexedDB ผิดพลาด (ไม่มีรายละเอียด — อาจเพราะแอปถูกพักไว้เบื้องหลัง)'));
      t.onabort = () => reject(t.error || new Error('การบันทึกถูกยกเลิก (อาจเพราะแอปถูกพักไว้เบื้องหลัง)'));
      try {
        const r = fn(t.objectStore(store));
        if (r) r.onsuccess = () => { result = r.result; };
      } catch (e) { reject(e); }
    }));
  }

  // ล้มครั้งแรก -> ทิ้งการเชื่อมต่อเดิม เปิดใหม่ แล้วลองอีกครั้ง
  function tx(store, mode, fn) {
    return txOnce(store, mode, fn).catch((err) => {
      resetDb();
      return txOnce(store, mode, fn).catch((err2) => { resetDb(); throw err2 || err; });
    });
  }

  const Store = {
    _resetDb: resetDb,
    _db: () => dbPromise,
    get: (id) => tx('packages', 'readonly', (s) => s.get(id)),
    put: (rec) => tx('packages', 'readwrite', (s) => s.put(rec)),
    list: () => tx('packages', 'readonly', (s) => s.getAll()),
    remove: (id) => tx('packages', 'readwrite', (s) => s.delete(id)),
    snapshot: (rec, why) => tx('snapshots', 'readwrite', (s) => s.put({
      id: `${rec.package_id}@${new Date().toISOString()}`, why, record: rec,
    })),

    // ตรวจว่าบันทึกลงเครื่องได้จริงไหม (โหมดส่วนตัวบางเบราว์เซอร์จะล้มตรงนี้)
    async check() {
      const out = { ok: true, reason: '', persisted: null, quotaMB: null };
      try {
        localStorage.setItem('__probe__', '1');
        localStorage.removeItem('__probe__');
      } catch (e) {
        return { ok: false, reason: `localStorage ใช้ไม่ได้ (${e.name || e})` };
      }
      try {
        const probe = { package_id: '__probe__', t: Date.now() };
        await Store.put(probe);
        const back = await Store.get('__probe__');
        await Store.remove('__probe__');
        if (!back || back.t !== probe.t) return { ok: false, reason: 'เขียน/อ่าน IndexedDB ไม่ตรงกัน' };
      } catch (e) {
        return { ok: false, reason: `IndexedDB ใช้ไม่ได้ (${e && (e.message || e.name) || e})` };
      }
      try {
        if (navigator.storage && navigator.storage.estimate) {
          const est = await navigator.storage.estimate();
          out.quotaMB = Math.round((est.quota || 0) / 1e6);
        }
      } catch (_) { /* ignore */ }
      return out;
    },

    // ขอให้เบราว์เซอร์ไม่ลบข้อมูลเอง (ถ้ารองรับ)
    async persist() {
      try {
        if (!navigator.storage || !navigator.storage.persist) return null;
        if (await navigator.storage.persisted()) return true;
        return await navigator.storage.persist();
      } catch (_) { return null; }
    },
  };

  window.Store = Store;
})();
