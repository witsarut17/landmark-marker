"""คำสั่งดูแลเซิร์ฟเวอร์ (รันจากโฟลเดอร์โปรเจกต์ด้วย python -m server.manage ...)

  init                         สร้างโฟลเดอร์ข้อมูล + config.toml + ฐานข้อมูล (ค่าเริ่มต้น server_data/)
  add-package <โฟลเดอร์>        ลงทะเบียนแพ็กเกจ (ตรวจ manifest และภาพครบ)
  add-user <ชื่อ> --role doctor|team   สร้างบัญชี แสดงรหัสผ่านครั้งเดียว
  reset-password <ชื่อ>         ตั้งรหัสผ่านใหม่ (ออกจากระบบทุกเครื่อง)
  disable-user <ชื่อ>           ปิดบัญชี (ออกจากระบบทุกเครื่อง)
  assign <ชื่อ> <package_id>    ให้หมอทำแพ็กเกจนี้
  list                         ดูผู้ใช้ แพ็กเกจ ความคืบหน้า
  run                          เปิดเซิร์ฟเวอร์ (waitress) + สำรองฐานข้อมูลอัตโนมัติ
  backup-now                   สำรองฐานข้อมูลทันที
  export-json <ชื่อ> <package_id> <ไฟล์>   ส่งออกผลรูปแบบเดียวกับไฟล์สำรองของเว็บ

ทุกคำสั่งรับ --config <ไฟล์> (ค่าเริ่มต้น server_data/config.toml)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import auth
from .app import ROOT, Config, create_app, setup_logging
from .backup import BackupThread, backup_now, rotate
from .db import connect, init_db, now_iso
from .validate import FINAL, Invalid, load_manifest

DEFAULT_CONFIG = ROOT / "server_data" / "config.toml"
CONFIG_TEMPLATE = """# ตั้งค่าเซิร์ฟเวอร์เว็บมาร์กจุด — ไฟล์นี้ห้ามขึ้น GitHub (อยู่ในโฟลเดอร์ข้อมูล)
[server]
host = "127.0.0.1"        # บนเครื่องแล็บ: ให้ reverse proxy (HTTPS) ส่งต่อมาที่นี่ ไม่เปิดตรงออกเครือข่าย
port = 8080
secure_cookies = false    # ต้องเป็น true เมื่อใช้ผ่าน HTTPS
trusted_proxy = false     # true เมื่ออยู่หลัง reverse proxy บนเครื่องเดียวกัน
session_days = 30

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
    return Config.load(path)


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
    pw = auth.generate_password()
    con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                (name, args.role, auth.hash_password(pw), now_iso()))
    print(f"สร้างผู้ใช้ {name} ({args.role})\nรหัสผ่าน (แสดงครั้งเดียว จดแล้วส่งให้ด้วยตัวเอง): {pw}")


def cmd_reset_password(args):
    cfg = load(args)
    con = connect(cfg.db)
    u = user_row(con, args.username)
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


def cmd_run(args):
    from waitress import serve
    cfg = load(args)
    init_db(cfg.db)
    log = setup_logging(cfg.logs)
    app = create_app(cfg)
    bk = BackupThread(cfg.db, cfg.backups, cfg.backup_every_minutes, cfg.keep_hourly, cfg.keep_daily)
    bk.start()
    log.info("เปิดเซิร์ฟเวอร์ http://%s:%d (secure_cookies=%s, trusted_proxy=%s)", cfg.host, cfg.port,
             cfg.secure_cookies, cfg.trusted_proxy)
    print(f"เปิดเซิร์ฟเวอร์แล้ว: http://{cfg.host}:{cfg.port}/  (กด Ctrl+C เพื่อปิด)")
    if not cfg.secure_cookies and cfg.host not in ("127.0.0.1", "localhost"):
        print("คำเตือน: ใช้ http และเปิดให้เครื่องอื่นเข้าได้ — ใช้ทดสอบภาพทดสอบเท่านั้น ห้ามใช้กับภาพผู้ป่วย")
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
    s = sub.add_parser("reset-password"); s.add_argument("username")
    s = sub.add_parser("disable-user"); s.add_argument("username")
    s = sub.add_parser("assign"); s.add_argument("username"); s.add_argument("package_id")
    sub.add_parser("list")
    sub.add_parser("run")
    sub.add_parser("backup-now")
    s = sub.add_parser("export-json"); s.add_argument("username"); s.add_argument("package_id"); s.add_argument("out")
    args = ap.parse_args()
    {"init": cmd_init, "add-package": cmd_add_package, "add-user": cmd_add_user, "reset-password": cmd_reset_password,
     "disable-user": cmd_disable_user, "assign": cmd_assign, "list": cmd_list, "run": cmd_run,
     "backup-now": cmd_backup_now, "export-json": cmd_export_json}[args.cmd](args)


if __name__ == "__main__":
    main()
