"""คำสั่งดูแลเซิร์ฟเวอร์ (รันจากโฟลเดอร์โปรเจกต์ด้วย python -m server.manage ...)

  init                         สร้างโฟลเดอร์ข้อมูล + config.toml + ฐานข้อมูล (ค่าเริ่มต้น server_data/)
  add-package <โฟลเดอร์>        ลงทะเบียนแพ็กเกจ (ตรวจ manifest และภาพครบ)
  add-user <ชื่อ> --role doctor|team   สร้างบัญชี (ทีม: แสดงรหัสผ่านครั้งเดียว · หมอ: ไม่มีรหัสผ่าน ใช้ make-link)
  make-link <ชื่อ> --until YYYY-MM-DD [--once] [--base URL]
                               สร้างลิงก์ส่วนตัวให้หมอ (แสดงครั้งเดียว) · ลิงก์เดิมถูกยกเลิกและทุกเครื่องต้องแตะลิงก์ใหม่
  revoke-link <ชื่อ>            ยกเลิกลิงก์ของหมอ (ออกจากระบบทุกเครื่อง) เช่น เมื่อลิงก์หลุด
  reset-password <ชื่อ>         ตั้งรหัสผ่านใหม่ของบัญชีทีม (ออกจากระบบทุกเครื่อง)
  disable-user <ชื่อ>           ปิดบัญชี (ออกจากระบบทุกเครื่อง)
  assign <ชื่อ> <package_id>    ให้หมอทำแพ็กเกจนี้
  list                         ดูผู้ใช้ แพ็กเกจ ความคืบหน้า
  run                          เปิดเซิร์ฟเวอร์ (waitress) + สำรองฐานข้อมูลอัตโนมัติ
  backup-now                   สำรองฐานข้อมูลทันที
  export-json <ชื่อ> <package_id> <ไฟล์>   ส่งออกผลรูปแบบเดียวกับไฟล์สำรองของเว็บ

การศึกษาแบบ ทีมมาร์ก-หมอตรวจ (v1.3):
  set-study <study.json>       ตั้งนิยามการศึกษา (เคส 1–70, ผู้มาร์ก, คู่วัดความตรงกัน) — สร้างด้วย tools/make_study_plan.py
  study                        ดูนิยามและความคืบหน้า (ทีมมาร์ก / หมอตรวจ)
  export-marks <ไฟล์>           ส่งออกจุดของทีม (ผู้มาร์กทุกคน + ประวัติ + นิยามการศึกษา) ไว้ย้ายไปเครื่องแล็บ
  import-marks <ไฟล์> [--replace]  นำเข้าจุดของทีม + ตั้งนิยามการศึกษา (สร้างบัญชีทีมที่ยังไม่มีให้)
  export-study <ไฟล์.csv|.json>  ไฟล์วิเคราะห์ (จุดของทีม จุดสุดท้ายของหมอ สถานะการตรวจ ระยะที่แก้ต่อจุด)

ทุกคำสั่งรับ --config <ไฟล์> (ค่าเริ่มต้น server_data/config.toml)
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import auth
from . import study as studymod
from .app import ROOT, Config, create_app, setup_logging
from .backup import BackupThread, backup_now, rotate
from .db import connect, init_db, now_iso
from .validate import FINAL, Invalid, clean_task, load_manifest

DEFAULT_CONFIG = ROOT / "server_data" / "config.toml"
CONFIG_TEMPLATE = """# ตั้งค่าเซิร์ฟเวอร์เว็บมาร์กจุด — ไฟล์นี้ห้ามขึ้น GitHub (อยู่ในโฟลเดอร์ข้อมูล)
[server]
host = "127.0.0.1"        # เครื่องแล็บ: "0.0.0.0" (ตัวติดตั้งตั้งให้) · โน้ตบุ๊ก: "127.0.0.1" ยกเว้นตอนทดสอบกับ iPad
port = 8090                # 8080 ใช้กับ CVAT บนเครื่องแล็บแล้ว
public_url = "http://127.0.0.1:8090/"   # ที่อยู่ที่หมอเปิด ใช้ตอนสร้างลิงก์ส่วนตัว · เครื่องแล็บ: http://<IP เครื่องแล็บ>:8090/
# รับคำขอเฉพาะจากเครือข่ายเหล่านี้: เครือข่ายภายใน (private) ทุกช่วง 10.x, 172.16–31.x, 192.168.x · 127.x และ ::1 = เครื่องนี้เอง
# IP ที่ถูกปฏิเสธบันทึกใน logs/app.log ("ปฏิเสธคำขอ… ip=…")
allowed_networks = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128"]
secure_cookies = false    # true เฉพาะเมื่อใช้ผ่าน HTTPS (เครื่องแล็บใช้ http ผ่าน VPN แบบเดียวกับ CVAT)
trusted_proxy = false     # true เฉพาะเมื่ออยู่หลัง reverse proxy บนเครื่องเดียวกัน
session_days = 30         # อายุการเข้าสู่ระบบของบัญชีทีม (ของหมอหมดพร้อมลิงก์)

[paths]                   # ทางเทียบกับโฟลเดอร์ของไฟล์นี้
db = "db/marks.sqlite"
backups = "backups"
logs = "logs"

[backup]
every_minutes = 60
keep_hourly = 48
keep_daily = 30
"""
FORMAT, FORMAT_VERSION = "pelnav-marks", 1
COORD_CONVENTION = ("COCO pixel coordinates; origin (0,0) = top-left corner of the top-left pixel; "
                    "pixel (i,j) center = (i+0.5, j+0.5); x to the right, y down; units = pixels of the original image file")


def load(args) -> Config:
    path = Path(args.config)
    if not path.exists():
        sys.exit(f"ไม่พบ {path} — รัน: python -m server.manage init")
    cfg = Config.load(path)
    init_db(cfg.db)               # เพิ่มตารางใหม่ (ถ้ามี) ให้ฐานข้อมูลเดิม โดยไม่แตะข้อมูลเดิม
    return cfg


def user_row(con, name: str):
    row = con.execute("SELECT * FROM users WHERE username = ?", (name.strip().lower(),)).fetchone()
    if not row:
        sys.exit(f"ไม่มีผู้ใช้ {name}")
    return row


def cmd_init(args):
    path = Path(args.config)
    if path.exists():
        print(f"มี {path} อยู่แล้ว — ไม่เขียนทับ")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        print(f"สร้าง {path}")
    cfg = Config.load(path)
    init_db(cfg.db)
    for d in (cfg.backups, cfg.logs):
        d.mkdir(parents=True, exist_ok=True)
    print(f"ฐานข้อมูล: {cfg.db}")


def cmd_add_package(args):
    cfg = load(args)
    pkg_dir = Path(args.folder).resolve()
    try:
        m, sha = load_manifest(pkg_dir)
    except (Invalid, OSError, ValueError) as e:
        sys.exit(f"หยุด: แพ็กเกจไม่ถูกต้อง — {e}")
    con = connect(cfg.db)
    con.execute("""INSERT INTO packages (package_id, path, manifest_sha256, added_at) VALUES (?,?,?,?)
                   ON CONFLICT (package_id) DO UPDATE SET path = excluded.path, manifest_sha256 = excluded.manifest_sha256""",
                (m["package_id"], str(pkg_dir), sha, now_iso()))
    print(f"ลงทะเบียน {m['package_id']} ({len(m['items'])} งาน) จาก {pkg_dir}")


def cmd_add_user(args):
    cfg = load(args)
    con = connect(cfg.db)
    name = args.username.strip().lower()
    if con.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
        sys.exit(f"มีผู้ใช้ {name} อยู่แล้ว (ใช้ reset-password)")
    if args.role == "doctor":
        # หมอไม่มีรหัสผ่าน (เก็บค่าที่ไม่ใช่ hash -> เข้าด้วยรหัสผ่านไม่ได้แน่นอน) · เข้าด้วยลิงก์ส่วนตัว
        con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                    (name, "doctor", "link-only$" + secrets.token_hex(8), now_iso()))
        print(f"สร้างผู้ใช้ {name} (doctor) — ขั้นต่อไป: assign แล้ว make-link {name} --until YYYY-MM-DD")
        return
    pw = auth.generate_password()
    con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                (name, args.role, auth.hash_password(pw), now_iso()))
    print(f"สร้างผู้ใช้ {name} ({args.role})\nรหัสผ่าน (แสดงครั้งเดียว จดแล้วส่งให้ด้วยตัวเอง): {pw}")


def cmd_reset_password(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    if u["role"] == "doctor":
        sys.exit(f"{u['username']} เป็นบัญชีหมอ ไม่ใช้รหัสผ่าน — ใช้ make-link {u['username']} --until YYYY-MM-DD")
    pw = auth.generate_password()
    con.execute("UPDATE users SET pw_hash = ?, active = 1 WHERE id = ?", (auth.hash_password(pw), u["id"]))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
    print(f"รหัสผ่านใหม่ของ {u['username']} (แสดงครั้งเดียว): {pw}")


def cmd_disable_user(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    con.execute("UPDATE users SET active = 0 WHERE id = ?", (u["id"],))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
    print(f"ปิดบัญชี {u['username']} แล้ว")


def cmd_make_link(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    if u["role"] != "doctor":
        sys.exit(f"{u['username']} เป็นบัญชีทีม — บัญชีทีมใช้รหัสผ่าน (ลิงก์ส่วนตัวใช้กับบัญชีหมอเท่านั้น)")
    if not u["active"]:
        sys.exit(f"{u['username']} ถูกปิดบัญชีอยู่")
    try:
        exp = auth.end_of_day_th(args.until)
    except ValueError:
        sys.exit("--until ต้องเป็นวันที่แบบ YYYY-MM-DD เช่น 2027-06-30")
    now = datetime.now(timezone.utc)
    if exp <= now:
        sys.exit("--until ต้องเป็นวันในอนาคต")
    if exp > now + timedelta(days=3 * 366):
        sys.exit("--until ไกลเกิน 3 ปี — ตั้งเป็นวันจบโครงการ")
    base = (args.base or cfg.public_url or "").strip()
    if not base:
        sys.exit("ไม่รู้ที่อยู่เว็บ — ใส่ public_url ใน config.toml หรือใส่ --base http://<IP เครื่องแล็บ>:8090/")
    if not base.startswith(("http://", "https://")):
        sys.exit("--base ต้องขึ้นต้นด้วย http:// หรือ https://")
    base = base.split("#")[0]
    if not base.endswith("/") and "?" not in base:
        base += "/"
    pk = [r[0] for r in con.execute("SELECT package_id FROM assignments WHERE user_id = ?", (u["id"],))]
    token = auth.new_link(con, u["id"], exp, once=args.once)
    print(f"ลิงก์ส่วนตัวของ {u['username']} — ใช้ได้ถึงสิ้นวันที่ {args.until}"
          f"{' (ใช้ได้ครั้งเดียว)' if args.once else ' (แตะซ้ำได้ ใช้ได้หลายเครื่อง)'} · แสดงครั้งเดียว:")
    print(f"\n{base}#t={token}\n")
    print("ส่งให้หมอทางช่องทางส่วนตัว (แชตส่วนตัวหรืออีเมลมหาวิทยาลัย) ห้ามโพสต์ในกลุ่ม — ใครได้ลิงก์นี้ไปก็เข้าบัญชีนี้ได้เมื่อต่อ VPN")
    print("ลิงก์เดิม (ถ้ามี) ใช้ไม่ได้แล้ว และทุกเครื่องที่เข้าอยู่ต้องแตะลิงก์ใหม่ · ลิงก์หลุด: revoke-link หรือ make-link ใหม่")
    if not pk:
        print(f"คำเตือน: {u['username']} ยังไม่ได้กำหนดแพ็กเกจ (assign {u['username']} <package_id>)")


def cmd_revoke_link(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    n = auth.revoke_links(con, u["id"])
    print(f"ยกเลิกลิงก์ของ {u['username']} {n} ลิงก์ และออกจากระบบทุกเครื่องแล้ว — สร้างลิงก์ใหม่: make-link {u['username']} --until YYYY-MM-DD")


def link_status(con, user_id: int) -> str:
    r = con.execute("SELECT * FROM login_links WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    if not r:
        return "ยังไม่มีลิงก์"
    until = datetime.fromisoformat(r["expires_at"]).astimezone(auth.TH).strftime("%Y-%m-%d")
    used = f"แตะแล้ว {r['use_count']} ครั้ง" + (f" ล่าสุด {r['last_used_at'][:16].replace('T', ' ')} UTC" if r["last_used_at"] else "")
    if r["revoked_at"]:
        return f"ลิงก์ถูกยกเลิก ({used})"
    if datetime.fromisoformat(r["expires_at"]) < datetime.now(timezone.utc):
        return f"ลิงก์หมดอายุ {until} ({used})"
    if r["once"] and r["use_count"]:
        return f"ลิงก์ครั้งเดียวถูกใช้แล้ว ({used})"
    return f"ลิงก์ใช้ได้ถึง {until} ({used})"


def cmd_assign(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    if not con.execute("SELECT 1 FROM packages WHERE package_id = ?", (args.package_id,)).fetchone():
        sys.exit(f"ไม่มีแพ็กเกจ {args.package_id} (ใช้ add-package ก่อน)")
    con.execute("INSERT OR IGNORE INTO assignments (user_id, package_id) VALUES (?,?)", (u["id"], args.package_id))
    print(f"{u['username']} → {args.package_id}")


def cmd_list(args):
    cfg = load(args)
    con = connect(cfg.db)
    print("แพ็กเกจ:")
    for r in con.execute("SELECT * FROM packages ORDER BY package_id"):
        print(f"  {r['package_id']}  {r['path']}")
    print("ผู้ใช้:")
    for u in con.execute("SELECT * FROM users ORDER BY role, username"):
        pk = [r[0] for r in con.execute("SELECT package_id FROM assignments WHERE user_id = ?", (u["id"],))]
        line = f"  {u['username']:<14} {u['role']:<7} {'ใช้งาน' if u['active'] else 'ปิด'}  {', '.join(pk) or '-'}"
        for p in pk:
            sts = [json.loads(r[0])["status"] for r in con.execute(
                "SELECT data FROM tasks_latest WHERE user_id = ? AND package_id = ?", (u["id"], p))]
            line += f"  [{p}: ทำแล้ว {sum(s in FINAL for s in sts)} ข้ามไว้ {sum(s == 'skipped' for s in sts)}]"
        if u["role"] == "doctor":
            line += f"  · {link_status(con, u['id'])}"
        print(line)


def cmd_backup_now(args):
    cfg = load(args)
    dest = backup_now(cfg.db, cfg.backups)
    rotate(cfg.backups, cfg.keep_hourly, cfg.keep_daily)
    print(f"สำรองแล้ว: {dest}")


def export_doc(con, user_id: int, package_id: str, total: int) -> dict:
    tasks, idx = {}, 0
    for r in con.execute("SELECT task_id, data FROM tasks_latest WHERE user_id = ? AND package_id = ?", (user_id, package_id)):
        tasks[r["task_id"]] = json.loads(r["data"])
    meta = con.execute("SELECT current_index FROM user_meta WHERE user_id = ? AND package_id = ?", (user_id, package_id)).fetchone()
    if meta:
        idx = meta["current_index"]
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "package_id": package_id, "app_version": "server",
            "exported_at": now_iso(), "coord_convention": COORD_CONVENTION, "total_tasks": total,
            "completed_tasks": sum(t["status"] in FINAL for t in tasks.values()), "current_index": idx, "tasks": tasks}


def cmd_export_json(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
    row = con.execute("SELECT path FROM packages WHERE package_id = ?", (args.package_id,)).fetchone()
    if not row:
        sys.exit(f"ไม่มีแพ็กเกจ {args.package_id}")
    m, _ = load_manifest(Path(row["path"]))
    doc = export_doc(con, u["id"], args.package_id, len(m["items"]))
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ส่งออก {doc['completed_tasks']}/{doc['total_tasks']} งาน → {args.out}")


# ---------------------------------------------------------------- การศึกษา ทีมมาร์ก-หมอตรวจ
MARKS_FORMAT = "pelnav-team-marks"


def package_manifest(con, package_id: str) -> dict:
    row = con.execute("SELECT path FROM packages WHERE package_id = ?", (package_id,)).fetchone()
    if not row:
        sys.exit(f"ยังไม่ได้ลงทะเบียนแพ็กเกจ {package_id} (ใช้ add-package ก่อน)")
    try:
        return load_manifest(Path(row["path"]))[0]
    except (Invalid, OSError, ValueError) as e:
        sys.exit(f"เปิดแพ็กเกจ {package_id} ไม่ได้: {e}")


def apply_study(con, st: dict) -> list[str]:
    m = package_manifest(con, st.get("package_id", ""))
    try:
        warn = studymod.validate_study(st, m)
    except studymod.StudyError as e:
        sys.exit(f"หยุด: นิยามการศึกษาไม่ถูกต้อง — {e}")
    studymod.save_study(con, st)
    return warn


def cmd_set_study(args):
    cfg = load(args)
    con = connect(cfg.db)
    st = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    warn = apply_study(con, st)
    n = sum(len(c["tasks"]) for c in st["cases"])
    print(f"ตั้งการศึกษาแล้ว: {st['package_id']} · เคส {len(st['cases'])} · งาน {n} · คู่วัดความตรงกัน {len(st.get('extra') or [])}")
    for w in warn:
        print("  " + w)
    for mk in sorted(studymod.markers(st)):
        u = con.execute("SELECT role FROM users WHERE username = ?", (mk,)).fetchone()
        if not u:
            print(f"  คำเตือน: ยังไม่มีบัญชี {mk} (add-user {mk} --role team)")
        elif u["role"] != "team":
            print(f"  คำเตือน: {mk} ไม่ใช่บัญชีทีม — ผู้มาร์กต้องเป็นบัญชีทีม")


def cmd_study(args):
    cfg = load(args)
    con = connect(cfg.db)
    st = studymod.load_study(con)
    if not st:
        sys.exit("ยังไม่ได้ตั้งการศึกษา (set-study หรือ import-marks)")
    p = studymod.progress(con, st, package_manifest(con, st["package_id"]))
    print(f"การศึกษา {st['package_id']} · เคส {len(st['cases'])} · คู่วัดความตรงกัน {len(st.get('extra') or [])}")
    for mk, t in p["team"].items():
        print(f"  ผู้มาร์ก {mk}: เคส {t['cases']} + คู่พิเศษ · งาน {t['tasks']} · เสร็จ {t['done']}")
    for d in p["doctors"]:
        s = p["summary"][d]
        print(f"  หมอ {d}: ยืนยันไม่แก้ {s['confirmed']} · แก้ {s['edited']} · มาร์กไม่ได้ {s['unmarkable']} · "
              f"ข้าม {s['skipped']} · กำลังทำ {s['in_progress']} · ยังไม่เริ่ม {s['not_started']}")


def cmd_export_marks(args):
    cfg = load(args)
    con = connect(cfg.db)
    st = studymod.load_study(con)
    if not st:
        sys.exit("ยังไม่ได้ตั้งการศึกษา")
    pkg, out_users, latest, events, meta = st["package_id"], [], [], [], []
    for mk in sorted(studymod.markers(st)):
        u = con.execute("SELECT id, username, role FROM users WHERE username = ?", (mk,)).fetchone()
        if not u:
            continue
        out_users.append({"username": u["username"], "role": u["role"]})
        for r in con.execute("SELECT task_id, rev, data, updated_at, saved_at FROM tasks_latest WHERE user_id = ? AND package_id = ?",
                             (u["id"], pkg)):
            latest.append({"username": mk, **dict(r)})
        for r in con.execute("SELECT task_id, rev, data, saved_at FROM task_events WHERE user_id = ? AND package_id = ? ORDER BY id",
                             (u["id"], pkg)):
            events.append({"username": mk, **dict(r)})
        r = con.execute("SELECT current_index, updated_at FROM user_meta WHERE user_id = ? AND package_id = ?", (u["id"], pkg)).fetchone()
        if r:
            meta.append({"username": mk, **dict(r)})
    doc = {"format": MARKS_FORMAT, "version": 1, "exported_at": now_iso(), "package_id": pkg, "study": st,
           "users": out_users, "tasks_latest": latest, "task_events": events, "user_meta": meta}
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    done = sum(1 for r in latest if json.loads(r["data"]).get("status") in FINAL)
    print(f"ส่งออกจุดของทีม {len(out_users)} คน · งาน {len(latest)} (เสร็จ {done}) · ประวัติ {len(events)} รายการ → {args.out}")
    print("ไฟล์นี้ไม่มีภาพ แต่เป็นข้อมูลวิจัย — ส่งทางช่องทางเดียวกับแพ็กเกจ ห้ามขึ้น GitHub")


def cmd_import_marks(args):
    cfg = load(args)
    con = connect(cfg.db)
    doc = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    if doc.get("format") != MARKS_FORMAT or doc.get("version") != 1:
        sys.exit("ไม่ใช่ไฟล์จุดของทีม (export-marks)")
    st, pkg = doc["study"], doc["package_id"]
    m = package_manifest(con, pkg)
    try:
        studymod.validate_study(st, m)
    except studymod.StudyError as e:
        sys.exit(f"หยุด: นิยามการศึกษาในไฟล์ไม่ถูกต้อง — {e}")
    items = {it["task_id"]: it for it in m["items"]}
    allowed = {mk: set(studymod.view_for(st, mk, "team")["tasks"]) for mk in studymod.markers(st)}
    for r in doc["tasks_latest"] + doc["task_events"]:
        if r["username"] not in allowed or r["task_id"] not in allowed[r["username"]]:
            sys.exit(f"หยุด: ไฟล์มีงาน {r['task_id']} ของ {r['username']} ที่ไม่อยู่ในการศึกษา")
        try:
            clean_task(json.loads(r["data"]), items[r["task_id"]])
        except Invalid as e:
            sys.exit(f"หยุด: ข้อมูลงาน {r['task_id']} ของ {r['username']} ไม่ถูกต้อง — {e}")
    con.execute("BEGIN IMMEDIATE")
    created = []
    try:
        ids = {}
        for u in doc["users"]:
            row = con.execute("SELECT id, role FROM users WHERE username = ?", (u["username"],)).fetchone()
            if row and row["role"] != "team":
                raise SystemExit(f"หยุด: บัญชี {u['username']} บนเครื่องนี้ไม่ใช่บัญชีทีม")
            if not row:
                pw = auth.generate_password()
                con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                            (u["username"], "team", auth.hash_password(pw), now_iso()))
                row = con.execute("SELECT id, role FROM users WHERE username = ?", (u["username"],)).fetchone()
                created.append((u["username"], pw))
            ids[u["username"]] = row["id"]
            have = con.execute("SELECT COUNT(*) FROM tasks_latest WHERE user_id = ? AND package_id = ?", (row["id"], pkg)).fetchone()[0]
            if have and not args.replace:
                raise SystemExit(f"หยุด: {u['username']} มีจุดบนเครื่องนี้อยู่แล้ว {have} งาน — ใส่ --replace ถ้าจะแทนที่ด้วยไฟล์นี้")
            if have:
                for t in ("tasks_latest", "task_events", "user_meta"):
                    con.execute(f"DELETE FROM {t} WHERE user_id = ? AND package_id = ?", (row["id"], pkg))
        for r in doc["tasks_latest"]:
            con.execute("INSERT INTO tasks_latest (user_id, package_id, task_id, rev, data, updated_at, saved_at) VALUES (?,?,?,?,?,?,?)",
                        (ids[r["username"]], pkg, r["task_id"], r["rev"], r["data"], r["updated_at"], r["saved_at"]))
        for r in doc["task_events"]:
            con.execute("INSERT INTO task_events (user_id, package_id, task_id, rev, data, saved_at) VALUES (?,?,?,?,?,?)",
                        (ids[r["username"]], pkg, r["task_id"], r["rev"], r["data"], r["saved_at"]))
        for r in doc["user_meta"]:
            con.execute("INSERT INTO user_meta (user_id, package_id, current_index, updated_at) VALUES (?,?,?,?)",
                        (ids[r["username"]], pkg, r["current_index"], r["updated_at"]))
        studymod.save_study(con, st)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    done = sum(1 for r in doc["tasks_latest"] if json.loads(r["data"]).get("status") in FINAL)
    print(f"นำเข้าแล้ว: ผู้มาร์ก {len(ids)} คน · งาน {len(doc['tasks_latest'])} (เสร็จ {done}) · ประวัติ {len(doc['task_events'])} รายการ")
    print(f"ตั้งการศึกษาแล้ว: {pkg} · เคส {len(st['cases'])}")
    for name, pw in created:
        print(f"สร้างบัญชีทีม {name} — รหัสผ่าน (แสดงครั้งเดียว ส่งให้เจ้าของด้วยตัวเอง): {pw}")


def cmd_export_study(args):
    cfg = load(args)
    con = connect(cfg.db)
    st = studymod.load_study(con)
    if not st:
        sys.exit("ยังไม่ได้ตั้งการศึกษา")
    doc = studymod.export_study(con, st, package_manifest(con, st["package_id"]))
    out = Path(args.out)
    if out.suffix.lower() == ".csv":
        import csv
        head, rows = studymod.export_rows(doc)
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            f.write("# " + doc["coord_convention"] + "\n")
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
    else:
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ส่งออกการศึกษา {doc['n_tasks']} งาน · หมอ {len(doc['doctors'])} คน → {out}")


def cmd_run(args):
    from waitress import serve
    cfg = load(args)
    init_db(cfg.db)
    log = setup_logging(cfg.logs)
    app = create_app(cfg)
    bk = BackupThread(cfg.db, cfg.backups, cfg.backup_every_minutes, cfg.keep_hourly, cfg.keep_daily)
    bk.start()
    nets = ", ".join(cfg.allowed_networks) or "ทุกที่ (ไม่แนะนำ)"
    log.info("เปิดเซิร์ฟเวอร์ http://%s:%d (รับจาก %s, secure_cookies=%s, trusted_proxy=%s)", cfg.host, cfg.port, nets,
             cfg.secure_cookies, cfg.trusted_proxy)
    print(f"เปิดเซิร์ฟเวอร์แล้ว: http://{cfg.host}:{cfg.port}/  (กด Ctrl+C เพื่อปิด)\nรับคำขอเฉพาะจาก: {nets}")
    kw = {}
    if cfg.trusted_proxy:
        kw = {"trusted_proxy": "127.0.0.1", "trusted_proxy_headers": {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}}
    try:
        serve(app, host=cfg.host, port=cfg.port, threads=8, ident="pelnav", **kw)
    finally:
        bk.stop_event.set()
        bk.run_once()                 # สำรองครั้งสุดท้ายตอนปิด


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m server.manage", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("add-package"); s.add_argument("folder")
    s = sub.add_parser("add-user"); s.add_argument("username"); s.add_argument("--role", choices=["doctor", "team"], required=True)
    s = sub.add_parser("make-link"); s.add_argument("username"); s.add_argument("--until", required=True)
    s.add_argument("--once", action="store_true"); s.add_argument("--base")
    s = sub.add_parser("revoke-link"); s.add_argument("username")
    s = sub.add_parser("reset-password"); s.add_argument("username")
    s = sub.add_parser("disable-user"); s.add_argument("username")
    s = sub.add_parser("assign"); s.add_argument("username"); s.add_argument("package_id")
    sub.add_parser("list")
    sub.add_parser("run")
    sub.add_parser("backup-now")
    s = sub.add_parser("export-json"); s.add_argument("username"); s.add_argument("package_id"); s.add_argument("out")
    s = sub.add_parser("set-study"); s.add_argument("file")
    sub.add_parser("study")
    s = sub.add_parser("export-marks"); s.add_argument("out")
    s = sub.add_parser("import-marks"); s.add_argument("file"); s.add_argument("--replace", action="store_true")
    s = sub.add_parser("export-study"); s.add_argument("out")
    args = ap.parse_args()
    {"init": cmd_init, "add-package": cmd_add_package, "add-user": cmd_add_user, "make-link": cmd_make_link,
     "revoke-link": cmd_revoke_link, "reset-password": cmd_reset_password,
     "disable-user": cmd_disable_user, "assign": cmd_assign, "list": cmd_list, "run": cmd_run,
     "backup-now": cmd_backup_now, "export-json": cmd_export_json, "set-study": cmd_set_study, "study": cmd_study,
     "export-marks": cmd_export_marks, "import-marks": cmd_import_marks, "export-study": cmd_export_study}[args.cmd](args)


if __name__ == "__main__":
    main()
