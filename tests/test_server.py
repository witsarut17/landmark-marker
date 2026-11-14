"""ทดสอบเซิร์ฟเวอร์ (ขั้น A) ด้วยภาพทดสอบสังเคราะห์ — ไม่ใช้เบราว์เซอร์ ไม่แตะข้อมูลจริง

รัน:  .venv\\Scripts\\python tests/test_server.py
ใช้โฟลเดอร์ชั่วคราว (ลบเองเมื่อจบ) · แพ็กเกจ tests/generated/test_package
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import auth  # noqa: E402
from server.app import Config, create_app  # noqa: E402
from server.backup import backup_now, rotate  # noqa: E402
from server.db import connect, init_db, now_iso  # noqa: E402
from server.manage import export_doc  # noqa: E402
from server.validate import load_manifest  # noqa: E402

PKG = ROOT / "tests" / "generated" / "test_package"
H = {"X-Requested-With": "pelnav"}
rows: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    rows.append((bool(ok), label, str(detail)))


def make_env(tmp: Path):
    (tmp / "config.toml").write_text('[server]\nport = 8080\n[paths]\ndb = "db/marks.sqlite"\nbackups = "backups"\nlogs = "logs"\n',
                                     encoding="utf-8")
    cfg = Config.load(tmp / "config.toml")
    init_db(cfg.db)
    con = connect(cfg.db)
    m, sha = load_manifest(PKG)
    con.execute("INSERT INTO packages VALUES (?,?,?,?)", (m["package_id"], str(PKG.resolve()), sha, now_iso()))
    pw = {}
    for name, role in (("doc1", "doctor"), ("doc2", "doctor"), ("team1", "team"), ("doc3", "doctor")):
        pw[name] = auth.generate_password()
        con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                    (name, role, auth.hash_password(pw[name]), now_iso()))
    for name in ("doc1", "doc3"):
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        con.execute("INSERT INTO assignments VALUES (?,?)", (uid, m["package_id"]))
    con.close()
    return cfg, m, pw


def login(c, user, pw):
    return c.post("/api/login", json={"username": user, "password": pw}, headers=H)


def task(m, status="in_progress", x=(100.0, 200.0), note=None, **extra):
    it = m["items"][0]
    t = {"xray": [{"x": x[0], "y": x[1], "image_px_per_screen_px": 0.25, "at": now_iso()}, None, None, None],
         "fluoro": [{"x": 10.0, "y": 20.0, "image_px_per_screen_px": 0.1, "at": now_iso()}, None, None, None],
         "status": status, "reason": None, "reason_text": None, "note": note,
         "started_at": now_iso(), "finished_at": None, "updated_at": now_iso(), "duration_ms": 1234}
    t.update(extra)
    return t, it["task_id"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not (PKG / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    tmp = Path(tempfile.mkdtemp(prefix="pelnav_srv_"))
    try:
        run(tmp)
    finally:
        import logging
        for h in list(logging.getLogger("pelnav").handlers):
            h.close()
            logging.getLogger("pelnav").removeHandler(h)
        shutil.rmtree(tmp, ignore_errors=True)
    for ok, label, detail in rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n = sum(1 for r in rows if r[0])
    print(f"\nผ่าน {n} / {len(rows)} รายการ")
    sys.exit(0 if n == len(rows) else 1)


def run(tmp: Path):
    cfg, m, pw = make_env(tmp)
    app = create_app(cfg)
    pid = m["package_id"]

    c = app.test_client()
    check(c.get("/api/health").get_json()["ok"], "S เซิร์ฟเวอร์ทำงาน (health)")
    check(c.get("/api/package").status_code == 401 and c.get("/api/image/T001/xray").status_code == 401
          and c.get("/api/state").status_code == 401, "S ยังไม่เข้าสู่ระบบ → ดู manifest/ภาพ/งาน ไม่ได้ (401)")

    # เข้าสู่ระบบ + คุกกี้ปลอดภัย + CSRF
    check(login(c, "doc1", "wrong-password").status_code == 401, "S รหัสผิด → 401")
    check(c.post("/api/login", json={"username": "doc1", "password": pw["doc1"]}).status_code == 403,
          "S คำขอที่ไม่มี header ของหน้าเว็บ (กัน CSRF) → 403")
    check(c.post("/api/login", json={"username": "doc1", "password": pw["doc1"]},
                 headers={**H, "Origin": "https://evil.example"}).status_code == 403, "S Origin จากเว็บอื่น → 403")
    r = login(c, "doc1", pw["doc1"])
    sc = r.headers.get("Set-Cookie", "")
    check(r.status_code == 200 and "HttpOnly" in sc and "SameSite=Strict" in sc and "Max-Age=2592000" in sc,
          "S เข้าสู่ระบบได้ · คุกกี้ HttpOnly + SameSite=Strict · อายุ 30 วัน", sc[:120])

    # manifest (ไม่ส่งชื่อไฟล์จริง) + ภาพ
    pm = c.get("/api/package").get_json()
    names_ok = all(it["xray"].startswith(f"{it['task_id']}_X.") and it["fluoro"].startswith(f"{it['task_id']}_F.") for it in pm["items"])
    check(pm["package_id"] == pid and len(pm["items"]) == len(m["items"]) and names_ok,
          "S manifest ส่งให้หน้าเว็บ: ชื่อไฟล์เป็นรหัสงาน ไม่ใช่ชื่อจริง", pm["items"][0])
    it0 = m["items"][0]
    r = c.get(f"/api/image/{it0['task_id']}/xray")
    check(r.status_code == 200 and r.data == (PKG / it0["xray"]).read_bytes() and r.headers["Cache-Control"] == "no-store"
          and r.mimetype in ("image/png", "image/jpeg"), "S ส่งภาพตามรหัสงาน ไบต์ตรงไฟล์ · Cache-Control: no-store", r.headers.get("Cache-Control"))
    bad = [c.get(u).status_code for u in ("/api/image/T999/xray", "/api/image/T001/other",
                                          "/api/image/..%2fmanifest.json/xray", "/api/image/T001/..%2F..%2Fapp.py")]
    check(all(s == 404 for s in bad), "S รหัสงานผิด/ฝั่งผิด/พยายามเข้าถึงไฟล์อื่น → 404", bad)

    # บันทึกงาน + เลขรุ่น + ประวัติ
    t, tid = task(m, note="จุด 2 ไม่แน่ใจ", evil="<script>")
    r = c.put(f"/api/tasks/{tid}", json={"task": t, "base_rev": 0}, headers=H)
    check(r.status_code == 200 and r.get_json()["rev"] == 1, "S บันทึกงานได้ (rev 1)", r.get_json())
    st = c.get("/api/state").get_json()
    check(st["tasks"][tid]["xray"][0]["x"] == 100.0 and st["revs"][tid] == 1 and "evil" not in st["tasks"][tid],
          "S ดึงงานกลับได้ตรง · ฟิลด์ที่ไม่รู้จักถูกทิ้ง", st["tasks"][tid].keys())
    r = c.put(f"/api/tasks/{tid}", json={"task": t, "base_rev": 0}, headers=H)
    check(r.status_code == 409 and r.get_json()["rev"] == 1, "S บันทึกด้วยเลขรุ่นเก่า (อีกเครื่องบันทึกไปก่อน) → 409 พร้อมข้อมูลล่าสุด")
    t2, _ = task(m, status="done", x=(150.5, 250.5))
    r = c.put(f"/api/tasks/{tid}", json={"task": t2, "base_rev": 1}, headers=H)
    con = sqlite3.connect(str(cfg.db))
    n_ev = con.execute("SELECT COUNT(*) FROM task_events WHERE task_id = ?", (tid,)).fetchone()[0]
    con.close()
    check(r.status_code == 200 and r.get_json()["rev"] == 2 and n_ev == 2, "S บันทึกต่อ (rev 2) · ประวัติเก็บทุกครั้ง ไม่ทับ", n_ev)
    for label, bad_t in (("จุดอยู่นอกภาพ", task(m, x=(it0["xray_size"][0] + 5, 10))[0]),
                         ("สถานะไม่รู้จัก", task(m, status="hacked")[0]),
                         ("หมายเหตุยาวเกิน", task(m, note="ก" * 400)[0]),
                         ("จำนวนจุดผิด", {**task(m)[0], "xray": [None] * 3})):
        r = c.put(f"/api/tasks/{tid}", json={"task": bad_t, "base_rev": 2}, headers=H)
        check(r.status_code == 400, f"S ข้อมูลผิด ({label}) → 400 ไม่บันทึก", r.status_code)
    check(c.put("/api/tasks/T999", json={"task": t, "base_rev": 0}, headers=H).status_code == 404, "S รหัสงานที่ไม่มีในแพ็กเกจ → 404")
    check(c.put("/api/meta", json={"current_index": 3}, headers=H).status_code == 200
          and c.get("/api/state").get_json()["current_index"] == 3
          and c.put("/api/meta", json={"current_index": 99}, headers=H).status_code == 400,
          "S จำงานล่าสุด (current_index) · ค่าผิด → 400")
    check(c.get("/api/admin/overview").status_code == 403, "S บัญชีแพทย์เข้าข้อมูลทีมไม่ได้ (403)")

    # แพทย์คนอื่น
    c2 = app.test_client()
    login(c2, "doc2", pw["doc2"])
    check(c2.get("/api/package").status_code == 409, "S แพทย์ที่ยังไม่ได้กำหนดแพ็กเกจ → แจ้งให้ติดต่อทีม (409)")
    c3 = app.test_client()
    login(c3, "doc3", pw["doc3"])
    check(c3.get("/api/state").get_json()["tasks"] == {}, "S แพทย์อีกคนในแพ็กเกจเดียวกัน ไม่เห็นงานของคนอื่น")

    # ทีม
    ct = app.test_client()
    login(ct, "team1", pw["team1"])
    ov = ct.get("/api/admin/overview").get_json()
    d1 = next(d for d in ov["doctors"] if d["username"] == "doc1")
    check(d1["done"] == 1 and d1["total"] == len(m["items"]), "S ทีมเห็นความคืบหน้าของแพทย์", d1)
    ad = ct.get(f"/api/admin/data?user=doc1&package={pid}").get_json()
    check(ad["tasks"][tid]["status"] == "done" and len(ad["items"]) == len(m["items"]), "S ทีมดึงข้อมูลสำหรับส่งออก JSON/CSV ได้")
    ri = ct.get(f"/api/image/{tid}/fluoro?package={pid}")
    check(ri.status_code == 200, "S ทีมดูภาพได้ (ระบุแพ็กเกจ)")
    con = connect(cfg.db)
    doc = export_doc(con, con.execute("SELECT id FROM users WHERE username='doc1'").fetchone()[0], pid, len(m["items"]))
    con.close()
    check(doc["format"] == "pelnav-marks" and doc["completed_tasks"] == 1 and "COCO" in doc["coord_convention"],
          "S ส่งออก JSON จากคำสั่ง (รูปแบบเดียวกับไฟล์สำรองของเว็บ)")

    # ออกจากระบบ / หมดอายุ / ปิดบัญชี
    c.post("/api/logout", headers=H)
    check(c.get("/api/me").status_code == 401, "S ออกจากระบบแล้วใช้คุกกี้เดิมไม่ได้")
    con = connect(cfg.db)
    con.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE user_id = (SELECT id FROM users WHERE username='doc3')")
    con.close()
    check(c3.get("/api/me").status_code == 401, "S session หมดอายุ → ต้องเข้าสู่ระบบใหม่")
    con = connect(cfg.db)
    con.execute("UPDATE users SET active = 0 WHERE username = 'team1'")
    con.close()
    check(ct.get("/api/me").status_code == 401 and login(app.test_client(), "team1", pw["team1"]).status_code == 401,
          "S ปิดบัญชี → ใช้ไม่ได้ทันที")

    # จำกัดการลองรหัสผิด
    cx = app.test_client()
    ip = {"REMOTE_ADDR": "10.9.9.9"}           # IP ใหม่ (การลองผิดก่อนหน้าในเทสต์นี้นับจาก 127.0.0.1)
    lg = lambda p: cx.post("/api/login", json={"username": "doc2", "password": p}, headers=H, environ_base=ip)  # noqa: E731
    codes = [lg("nope").status_code for _ in range(10)]
    after = lg(pw["doc2"]).status_code
    check(codes.count(401) == 10 and after == 429, "S ลองรหัสผิด 10 ครั้ง → ระงับชั่วคราว แม้รหัสถูก (429)", (codes[-1], after))

    # หน้าเว็บ + header ความปลอดภัย
    r = c.get("/")
    check(r.status_code == 200 and b"<html" in r.data and r.headers.get("X-Frame-Options") == "DENY"
          and r.headers.get("X-Content-Type-Options") == "nosniff", "S ส่งหน้าเว็บ + header ความปลอดภัย")
    check(c.get("/../server/app.py").status_code == 404 and c.get("/%2e%2e/server/app.py").status_code == 404,
          "S ขอไฟล์นอกโฟลเดอร์หน้าเว็บไม่ได้")
    check(c.get("/admin.html").status_code == 200, "S หน้าทีมวิจัย (admin.html)")

    # สำรองฐานข้อมูล
    b1 = backup_now(cfg.db, cfg.backups)
    con = sqlite3.connect(str(b1))
    ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and con.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 2
    con.close()
    for i in range(5):
        (cfg.backups / f"marks-2000010{i + 1}-000000.sqlite").write_bytes(b1.read_bytes())
    removed = rotate(cfg.backups, keep_hourly=2, keep_daily=3)
    check(ok and len(removed) == 3, "S สำรองฐานข้อมูล (ไฟล์สมบูรณ์ ข้อมูลครบ) · ลบไฟล์เก่าตามกำหนด", len(removed))

    # log ไม่มีรหัสผ่านหรือข้อความผู้ใช้
    import logging
    for h in logging.getLogger("pelnav").handlers:
        h.flush()
    logtxt = (cfg.logs / "app.log").read_text(encoding="utf-8")
    check("PUT /api/tasks/" in logtxt and pw["doc1"] not in logtxt and "จุด 2 ไม่แน่ใจ" not in logtxt
          and "เข้าสู่ระบบไม่สำเร็จ" in logtxt, "S log บันทึกการใช้งาน แต่ไม่มีรหัสผ่านหรือข้อความที่หมอพิมพ์")


if __name__ == "__main__":
    main()
