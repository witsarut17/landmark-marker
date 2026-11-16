"""ทดสอบเซิร์ฟเวอร์ด้วยภาพทดสอบสังเคราะห์ — ไม่ใช้เบราว์เซอร์ ไม่แตะข้อมูลจริง
S = เซิร์ฟเวอร์ทั่วไป · L = ลิงก์ส่วนตัวของหมอ · N = รับเฉพาะเครือข่ายภายใน · C = คำสั่ง manage

รัน:  .venv\\Scripts\\python tests/test_server.py
ใช้โฟลเดอร์ชั่วคราว (ลบเองเมื่อจบ) · แพ็กเกจ tests/generated/test_package
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import auth  # noqa: E402
from server.app import Config, create_app  # noqa: E402
from server.backup import backup_now, rotate  # noqa: E402
from server.db import connect, init_db, now_iso  # noqa: E402
from server import manage  # noqa: E402
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
    pw, tok = {}, {}
    # บัญชีหมอในเทสต์นี้มีรหัสผ่านจริงด้วย (เหมือนบัญชีที่สร้างก่อน v1.1) เพื่อตรวจว่าหมอเข้าด้วยรหัสผ่านไม่ได้แล้ว
    for name, role in (("doc1", "doctor"), ("doc2", "doctor"), ("team1", "team"), ("doc3", "doctor"), ("team2", "team")):
        pw[name] = auth.generate_password()
        con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                    (name, role, auth.hash_password(pw[name]), now_iso()))
        if role == "doctor":
            uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
            tok[name] = auth.new_link(con, uid, datetime.now(timezone.utc) + timedelta(days=30))
    for name in ("doc1", "doc3"):
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        con.execute("INSERT INTO assignments VALUES (?,?)", (uid, m["package_id"]))
    con.close()
    return cfg, m, pw, tok


def login(c, user, pw):
    return c.post("/api/login", json={"username": user, "password": pw}, headers=H)


_ip = iter(range(1, 60000))


def link_login(c, token, **kw):
    """แต่ละครั้งใช้ IP ภายในคนละเลข (ไม่ให้การลองผิดในเทสต์อื่นนับรวมกัน) ยกเว้นระบุ environ_base เอง"""
    if "environ_base" not in kw:
        n = next(_ip)
        kw["environ_base"] = {"REMOTE_ADDR": f"10.50.{n // 250}.{n % 250 + 1}"}
    return c.post("/api/link-login", json={"token": token}, headers=H, **kw)


def max_age(resp) -> int:
    m = re.search(r"Max-Age=(\d+)", resp.headers.get("Set-Cookie", ""))
    return int(m.group(1)) if m else -1


def uid_of(cfg, name):
    con = connect(cfg.db)
    r = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
    con.close()
    return r


def close_logs():
    for h in list(logging.getLogger("pelnav").handlers):
        h.close()
        logging.getLogger("pelnav").removeHandler(h)


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
    cfg, m, pw, tok = make_env(tmp)
    app = create_app(cfg)
    pid = m["package_id"]

    c = app.test_client()
    check(c.get("/api/health").get_json()["ok"], "S เซิร์ฟเวอร์ทำงาน (health)")
    check(c.get("/api/package").status_code == 401 and c.get("/api/image/T001/xray").status_code == 401
          and c.get("/api/state").status_code == 401, "S ยังไม่เข้าสู่ระบบ → ดู manifest/ภาพ/งาน ไม่ได้ (401)")

    # เข้าสู่ระบบ + คุกกี้ปลอดภัย + CSRF
    check(login(c, "team1", "wrong-password").status_code == 401, "S บัญชีทีม รหัสผิด → 401")
    check(c.post("/api/link-login", json={"token": tok["doc1"]}).status_code == 403
          and c.post("/api/login", json={"username": "team2", "password": pw["team2"]}).status_code == 403,
          "S คำขอที่ไม่มี header ของหน้าเว็บ (กัน CSRF) → 403")
    check(c.post("/api/link-login", json={"token": tok["doc1"]},
                 headers={**H, "Origin": "https://evil.example"}).status_code == 403, "S Origin จากเว็บอื่น → 403")
    r = login(c, "doc1", pw["doc1"])
    check(r.status_code == 403 and "ลิงก์" in r.get_json()["error"] and "Set-Cookie" not in r.headers,
          "L บัญชีหมอใส่รหัสผ่านถูก ก็เข้าไม่ได้ → บอกให้ใช้ลิงก์ส่วนตัว", r.get_json())
    r = link_login(c, tok["doc1"])
    sc = r.headers.get("Set-Cookie", "")
    check(r.status_code == 200 and "HttpOnly" in sc and "SameSite=Strict" in sc and abs(max_age(r) - 30 * 86400) < 120,
          "L แตะลิงก์ → เข้าสู่ระบบ · คุกกี้ HttpOnly + SameSite=Strict · อายุถึงวันหมดอายุของลิงก์", sc[:120])
    check(r.get_json()["username"] == "doc1" and c.get("/api/me").get_json()["role"] == "doctor", "L เข้าเป็นบัญชีของลิงก์นั้น")

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
    link_login(c2, tok["doc2"])
    check(c2.get("/api/package").status_code == 409, "S แพทย์ที่ยังไม่ได้กำหนดแพ็กเกจ → แจ้งให้ติดต่อทีม (409)")
    c3 = app.test_client()
    link_login(c3, tok["doc3"])
    check(c3.get("/api/state").get_json()["tasks"] == {}, "S แพทย์อีกคนในแพ็กเกจเดียวกัน ไม่เห็นงานของคนอื่น")

    # ทีม
    ct = app.test_client()
    r = login(ct, "team1", pw["team1"])
    check(r.status_code == 200 and abs(max_age(r) - 30 * 86400) < 120, "S บัญชีทีมเข้าด้วยรหัสผ่านเหมือนเดิม (30 วัน)", max_age(r))
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
    lg = lambda p: cx.post("/api/login", json={"username": "team2", "password": p}, headers=H, environ_base=ip)  # noqa: E731
    codes = [lg("nope").status_code for _ in range(10)]
    after = lg(pw["team2"]).status_code
    check(codes.count(401) == 10 and after == 429, "S ลองรหัสผิด 10 ครั้ง → ระงับชั่วคราว แม้รหัสถูก (429)", (codes[-1], after))

    run_links(app, cfg, m, tok)

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
          and "เข้าสู่ระบบไม่สำเร็จ" in logtxt and not any(t in logtxt for t in tok.values())
          and "เข้าด้วยลิงก์ส่วนตัว" in logtxt,
          "S log บันทึกการใช้งาน แต่ไม่มีรหัสผ่าน โทเคนของลิงก์ หรือข้อความที่หมอพิมพ์")

    run_manage(tmp, cfg, app, m)
    close_logs()
    run_networks(tmp)
    run_fluoro_area(tmp)


def run_fluoro_area(tmp: Path):
    """F: fluoro_area ใน manifest (แพ็กเกจภาพต้นฉบับ) — ไม่บังคับ · ค่าผิด = ไม่รับแพ็กเกจ · ส่งต่อให้หน้าเว็บ"""
    from server.validate import Invalid, public_manifest
    d = tmp / "pkg_area"
    shutil.copytree(PKG, d)
    base = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))

    def with_area(v):
        m = json.loads(json.dumps(base))
        m["items"][0]["fluoro_area"] = v
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        try:
            return load_manifest(d)[0]
        except Invalid:
            return None
    W, H = base["items"][0]["fluoro_size"]
    good = with_area(int(W * H * 0.6))
    check(good is not None and public_manifest(good)["items"][0]["fluoro_area"] == int(W * H * 0.6)
          and "fluoro_area" not in public_manifest(load_manifest(PKG)[0])["items"][0],
          "F fluoro_area ถูกต้อง → รับ และส่งให้หน้าเว็บ · แพ็กเกจที่ไม่มีค่านี้ใช้ได้เหมือนเดิม")
    check(all(with_area(v) is None for v in (0, -5, W * H + 1, "x", True)),
          "F fluoro_area ผิด (0, ติดลบ, เกินพื้นที่ภาพ, ไม่ใช่ตัวเลข) → ไม่รับแพ็กเกจ")


def run_links(app, cfg, m, tok):
    """L: ลิงก์ส่วนตัว — ผิด หมดอายุ ยกเลิก สร้างใหม่ ครั้งเดียว บัญชีทีม บัญชีที่ปิด จำกัดการลองผิด"""
    now = datetime.now(timezone.utc)
    check(link_login(app.test_client(), "x" * 43).status_code == 401 and link_login(app.test_client(), "").status_code == 401
          and link_login(app.test_client(), "ก" * 10).status_code == 401, "L ลิงก์ผิด/ว่าง → 401")
    con = connect(cfg.db)
    exp_link = con.execute("SELECT expires_at FROM login_links WHERE token_hash = ?", (auth.token_hash(tok["doc3"]),)).fetchone()[0]
    con.close()
    c = app.test_client()
    link_login(c, tok["doc3"])
    con = connect(cfg.db)
    exp_sess = con.execute("SELECT MAX(expires_at) FROM sessions WHERE user_id = ?", (uid_of(cfg, "doc3"),)).fetchone()[0]
    con.close()
    check(exp_sess == exp_link, "L การเข้าสู่ระบบจากลิงก์หมดอายุพร้อมลิงก์ (ไม่ใช่ 30 วันตายตัว)", (exp_sess, exp_link))
    c2 = app.test_client()
    check(link_login(c2, tok["doc3"]).status_code == 200 and c.get("/api/me").status_code == 200,
          "L ลิงก์เดิมแตะซ้ำ/ใช้อีกเครื่องได้ · เครื่องแรกยังเข้าอยู่")

    # สร้างลิงก์ใหม่ (ลิงก์หลุด) -> ลิงก์เก่าใช้ไม่ได้ + ทุกเครื่องออกจากระบบ
    con = connect(cfg.db)
    new = auth.new_link(con, uid_of(cfg, "doc3"), now + timedelta(days=10))
    con.close()
    check(c.get("/api/me").status_code == 401 and c2.get("/api/me").status_code == 401,
          "L สร้างลิงก์ใหม่ → ทุกเครื่องที่เข้าด้วยลิงก์เก่าต้องเข้าใหม่")
    check(link_login(app.test_client(), tok["doc3"]).status_code == 401, "L สร้างลิงก์ใหม่ → ลิงก์เก่าใช้ไม่ได้")
    r = link_login(c, new)
    check(r.status_code == 200 and abs(max_age(r) - 10 * 86400) < 120, "L ลิงก์ใหม่ใช้ได้ (อายุตามที่กำหนดใหม่)", max_age(r))

    # ยกเลิกลิงก์
    con = connect(cfg.db)
    auth.revoke_links(con, uid_of(cfg, "doc3"))
    con.close()
    check(c.get("/api/me").status_code == 401 and link_login(app.test_client(), new).status_code == 401,
          "L ยกเลิกลิงก์ → ใช้ลิงก์ไม่ได้ และเครื่องที่เข้าอยู่ถูกออกจากระบบทันที")

    # หมดอายุ
    con = connect(cfg.db)
    exp_tok = auth.new_link(con, uid_of(cfg, "doc3"), now + timedelta(days=1))
    con.close()
    c = app.test_client()
    link_login(c, exp_tok)
    con = connect(cfg.db)
    con.execute("UPDATE login_links SET expires_at = '2000-01-01T00:00:00+00:00' WHERE token_hash = ?", (auth.token_hash(exp_tok),))
    con.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE user_id = ?", (uid_of(cfg, "doc3"),))
    con.close()
    check(link_login(app.test_client(), exp_tok).status_code == 401 and c.get("/api/me").status_code == 401,
          "L ลิงก์หมดอายุ → ใช้ไม่ได้ · การเข้าสู่ระบบจากลิงก์นั้นก็หมดด้วย")

    # ครั้งเดียว
    con = connect(cfg.db)
    once = auth.new_link(con, uid_of(cfg, "doc3"), now + timedelta(days=5), once=True)
    con.close()
    check(link_login(app.test_client(), once).status_code == 200 and link_login(app.test_client(), once).status_code == 401,
          "L ลิงก์ครั้งเดียว (--once) → แตะครั้งที่สองใช้ไม่ได้")

    # บัญชีทีมใช้ลิงก์ไม่ได้ · บัญชีที่ปิดใช้ลิงก์ไม่ได้
    con = connect(cfg.db)
    team_tok = auth.new_link(con, uid_of(cfg, "team2"), now + timedelta(days=5))
    d_tok = auth.new_link(con, uid_of(cfg, "doc3"), now + timedelta(days=5))
    con.execute("UPDATE users SET active = 0 WHERE username = 'doc3'")
    con.close()
    check(link_login(app.test_client(), team_tok).status_code == 401, "L ลิงก์ใช้กับบัญชีทีมไม่ได้ (ทีมใช้รหัสผ่าน)")
    check(link_login(app.test_client(), d_tok).status_code == 401, "L บัญชีหมอที่ถูกปิด → ลิงก์ใช้ไม่ได้")

    # จำกัดการลองลิงก์ผิด
    cx = app.test_client()
    ip = {"REMOTE_ADDR": "10.7.7.7"}
    codes = [link_login(cx, "bad" + str(i), environ_base=ip).status_code for i in range(30)]
    after = link_login(cx, tok["doc1"], environ_base=ip).status_code
    other = link_login(app.test_client(), tok["doc1"]).status_code
    check(codes.count(401) == 30 and after == 429 and other == 200,
          "L ลองลิงก์ผิด 30 ครั้งจาก IP เดียว → IP นั้นถูกระงับชั่วคราว (429) · IP อื่นยังเข้าได้", (codes[-1], after, other))


def run_networks(tmp: Path):
    """N: รับเฉพาะคำขอจากเครือข่ายที่อนุญาต (ค่าเริ่มต้น 10.x + เครื่องตัวเอง)"""
    def app_with(extra: str, sub: str):
        close_logs()
        d = tmp / sub
        d.mkdir()
        (d / "config.toml").write_text('[server]\n' + extra + '[paths]\ndb = "db/marks.sqlite"\nbackups = "b"\nlogs = "logs"\n',
                                       encoding="utf-8")
        cfg = Config.load(d / "config.toml")
        init_db(cfg.db)
        return create_app(cfg), cfg

    app, cfg = app_with("", "net_default")
    c = app.test_client()
    code = lambda ip, path="/api/health": c.get(path, environ_base={"REMOTE_ADDR": ip}).status_code  # noqa: E731
    check(cfg.allowed_networks == ["10.0.0.0/8", "127.0.0.0/8", "::1/128"], "N ค่าเริ่มต้น: 10.x + เครื่องตัวเอง", cfg.allowed_networks)
    check(code("10.20.30.40") == 200 and code("10.0.0.1") == 200 and code("127.0.0.1") == 200 and code("::1") == 200,
          "N เครือข่ายภายใน (10.x) และเครื่องตัวเอง → เข้าได้")
    blocked = [code(ip) for ip in ("192.168.1.5", "172.16.0.9", "8.8.8.8", "11.0.0.1", "::ffff:8.8.8.8", "2001:db8::1")]
    check(all(x == 403 for x in blocked), "N ที่อื่น (Wi-Fi บ้าน 192.168.x, อินเทอร์เน็ต, IPv6) → 403", blocked)
    r = c.get("/api/health", environ_base={"REMOTE_ADDR": "192.168.1.5"})
    check("VPN" in r.get_json()["error"] and code("192.168.1.5", "/") == 403 and code("192.168.1.5", "/admin.html") == 403
          and c.post("/api/link-login", json={"token": "x"}, headers=H, environ_base={"REMOTE_ADDR": "192.168.1.5"}).status_code == 403,
          "N ที่อื่นเปิดหน้าเว็บ/หน้าทีม/ลิงก์ไม่ได้ · ข้อความบอกให้ต่อ VPN", r.get_json())
    check(code("::ffff:10.1.1.1") == 200, "N 10.x ในรูป IPv6 (::ffff:10.x) → เข้าได้")
    for h in logging.getLogger("pelnav").handlers:
        h.flush()
    check("ปฏิเสธคำขอจากนอกเครือข่าย" in (cfg.logs / "app.log").read_text(encoding="utf-8"),
          "N log บันทึก IP ที่ถูกปฏิเสธ (ไว้ตรวจปัญหา VPN)")
    app2, _ = app_with('allowed_networks = ["10.0.0.0/8", "192.168.0.0/16"]\n', "net_home")
    check(app2.test_client().get("/api/health", environ_base={"REMOTE_ADDR": "192.168.1.5"}).status_code == 200,
          "N เพิ่มช่วง IP ใน config.toml ได้ (เช่น ทดสอบ iPad ผ่าน Wi-Fi บ้าน)")
    try:
        app_with('allowed_networks = ["10.0.0.0/33"]\n', "net_bad")
        bad_ok = False
    except SystemExit as e:
        bad_ok = "allowed_networks" in str(e)
    check(bad_ok, "N ค่า allowed_networks ผิด → เซิร์ฟเวอร์ไม่เปิด และบอกว่าผิดที่ไหน")
    close_logs()


def run_manage(tmp: Path, cfg, app, m):
    """C: คำสั่ง add-user (หมอไม่มีรหัสผ่าน) · make-link · revoke-link · list · reset-password ของหมอ"""
    conf = str(tmp / "config.toml")

    def call(fn, **kw):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out):
            try:
                fn(argparse.Namespace(config=conf, **kw))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                out.write(str(e.code))
        return code, out.getvalue()

    code, out = call(manage.cmd_add_user, username="doc9", role="doctor")
    check(code == 0 and "รหัสผ่าน" not in out and "make-link" in out, "C add-user หมอ → ไม่มีรหัสผ่าน บอกขั้นต่อไปเป็น make-link", out)
    check(login(app.test_client(), "doc9", "").status_code == 401, "C บัญชีหมอใหม่เข้าด้วยรหัสผ่านไม่ได้เลย")
    call(manage.cmd_assign, username="doc9", package_id=m["package_id"])
    code, out = call(manage.cmd_reset_password, username="doc9")
    check(code != 0 and "make-link" in out, "C reset-password กับบัญชีหมอ → ปฏิเสธ บอกให้ใช้ make-link", out)
    until = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
    code, out = call(manage.cmd_make_link, username="doc9", until=until, once=False, base="http://10.1.2.3:8090")
    mm = re.search(r"(http://10\.1\.2\.3:8090/)#t=([A-Za-z0-9_-]{40,})", out)
    check(code == 0 and mm is not None and "แสดงครั้งเดียว" in out, "C make-link → พิมพ์ลิงก์ http://<IP>:8090/#t=<โทเคน> ครั้งเดียว", out[:200])
    token = mm.group(2) if mm else ""
    con = connect(cfg.db)
    stored = con.execute("SELECT token_hash, expires_at FROM login_links WHERE user_id = ? AND revoked_at IS NULL",
                         (uid_of(cfg, "doc9"),)).fetchone()
    in_db = token in json.dumps([dict(r) for r in con.execute("SELECT * FROM login_links")])
    con.close()
    check(stored and stored[0] == auth.token_hash(token) and not in_db
          and datetime.fromisoformat(stored[1]).astimezone(auth.TH).strftime("%Y-%m-%d %H:%M") == f"{until} 23:59",
          "C ฐานข้อมูลเก็บเฉพาะ hash ของโทเคน · หมดอายุสิ้นวันที่กำหนด (เวลาไทย)", stored and stored[1])
    c = app.test_client()
    check(link_login(c, token).status_code == 200 and c.get("/api/package").status_code == 200, "C ลิงก์จาก make-link ใช้เข้าและเปิดงานได้")
    code, out = call(manage.cmd_list)
    check(f"ลิงก์ใช้ได้ถึง {until}" in out and "แตะแล้ว 1 ครั้ง" in out, "C list แสดงสถานะลิงก์ของหมอ (ถึงวันไหน แตะกี่ครั้ง)",
          [ln for ln in out.splitlines() if "doc9" in ln])
    for kw, label in (({"until": "2000-01-01"}, "วันที่ผ่านมาแล้ว"), ({"until": "31/12/2027"}, "รูปแบบวันที่ผิด"),
                      ({"until": (datetime.now() + timedelta(days=4 * 366)).strftime("%Y-%m-%d")}, "ไกลเกิน 3 ปี"),
                      ({"until": until, "base": "10.1.2.3:8090"}, "ที่อยู่ไม่มี http://"),
                      ({"until": until, "base": None}, "ไม่มีที่อยู่เว็บ (ไม่มี public_url)")):
        code, out = call(manage.cmd_make_link, username="doc9", once=False, **{"base": "http://10.1.2.3:8090/", **kw})
        check(code != 0, f"C make-link {label} → ไม่สร้าง บอกเหตุผล", out)
    code, out = call(manage.cmd_make_link, username="team1", until=until, once=False, base=None)
    check(code != 0 and "บัญชีทีม" in out, "C make-link กับบัญชีทีม → ปฏิเสธ", out)
    check(link_login(app.test_client(), token).status_code == 200, "C make-link ที่ไม่สำเร็จ ไม่ยกเลิกลิงก์เดิม")
    code, out = call(manage.cmd_revoke_link, username="doc9")
    check(code == 0 and c.get("/api/me").status_code == 401 and link_login(app.test_client(), token).status_code == 401,
          "C revoke-link → ลิงก์ใช้ไม่ได้ ทุกเครื่องออกจากระบบ", out)
    code, out = call(manage.cmd_make_link, username="doc9", until=until, once=True, base="http://10.1.2.3:8090/")
    check(code == 0 and "ครั้งเดียว" in out, "C make-link --once", out[:120])


if __name__ == "__main__":
    main()
