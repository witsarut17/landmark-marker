"""เซิร์ฟเวอร์จริงสำหรับเทสต์เบราว์เซอร์ (ข้อมูลชั่วคราว ภาพทดสอบสังเคราะห์เท่านั้น)

TestServer() -> เปิด Flask app บนพอร์ตสุ่ม 127.0.0.1 · ลงทะเบียนแพ็กเกจทดสอบทุกชุดใน tests/generated
server.open(page, "test_package") -> สร้างบัญชีแพทย์ใหม่ (งานว่าง) เข้าสู่ระบบ แล้วเปิดหน้าเว็บที่แพ็กเกจนั้น
add_user() คืน (ชื่อ, ความลับ): หมอ = โทเคนของลิงก์ส่วนตัว · ทีม = รหัสผ่าน
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
from server import auth  # noqa: E402
from server.app import Config, create_app  # noqa: E402
from server.db import connect, init_db, now_iso  # noqa: E402
from server.validate import load_manifest  # noqa: E402

GEN = ROOT / "tests" / "generated"
H = {"X-Requested-With": "pelnav"}
PACKAGES = ("test_package", "test_package_reversed", "test_package_big", "bad_size_package", "bad_exif_package")


class _Quiet(WSGIRequestHandler):
    def log_request(self, *a, **k):
        pass


class TestServer:
    def __init__(self, packages=PACKAGES, host="127.0.0.1", networks=None):
        """host="0.0.0.0" + networks ใช้ทดสอบเปิดผ่านเลข IP ของเครื่อง (http ที่ไม่ใช่ localhost = แบบเดียวกับเครื่องแล็บ)"""
        self.tmp = Path(tempfile.mkdtemp(prefix="pelnav_test_"))
        nets = "" if networks is None else "allowed_networks = " + json.dumps(networks) + "\n"
        (self.tmp / "config.toml").write_text('[server]\n' + nets + '[paths]\ndb = "db/marks.sqlite"\nbackups = "backups"\nlogs = "logs"\n',
                                              encoding="utf-8")
        self.cfg = Config.load(self.tmp / "config.toml")
        init_db(self.cfg.db)
        self.pkg_ids: dict[str, str] = {}
        for name in packages:
            if (GEN / name / "manifest.json").exists():
                self.register(name, GEN / name)
        self.app = create_app(self.cfg)
        self.srv = make_server(host, 0, self.app, threaded=True, request_handler=_Quiet)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.port = self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self._n = 0

    # ---------- ข้อมูล ----------
    def con(self):
        return connect(self.cfg.db)

    def register(self, name: str, folder: Path, validate: bool = True) -> str:
        """ลงทะเบียนแพ็กเกจ · validate=False ใช้จำลองแพ็กเกจที่เสียหลังลงทะเบียน"""
        if validate:
            m, sha = load_manifest(folder)
            pid = m["package_id"]
        else:
            pid = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["package_id"] + f"-{name}"
            sha = "-"
        con = self.con()
        con.execute("INSERT OR REPLACE INTO packages VALUES (?,?,?,?)", (pid, str(folder.resolve()), sha, now_iso()))
        con.close()
        self.pkg_ids[name] = pid
        return pid

    def broken_copy(self, name: str, src: str = "test_package", drop: str | None = None, corrupt_manifest=False) -> str:
        """สำเนาแพ็กเกจทดสอบที่เสีย (ลบไฟล์ภาพ 1 ไฟล์ หรือ manifest เสีย) แล้วลงทะเบียนแบบไม่ตรวจ"""
        dst = self.tmp / "pkgs" / name
        shutil.copytree(GEN / src, dst)
        pid = self.register(name, dst, validate=False)
        if drop:
            (dst / drop).unlink()
        if corrupt_manifest:
            m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
            m["items"][0]["task_id"] = "BAD"
            m["package_id"] = pid
            (dst / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        else:
            m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
            m["package_id"] = pid
            (dst / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        return pid

    def add_user(self, packages=None, role: str = "doctor", name: str | None = None, days: float = 30,
                 once: bool = False) -> tuple[str, str]:
        """หมอ: ไม่มีรหัสผ่าน สร้างลิงก์ส่วนตัวให้ (คืนโทเคน) · ทีม: คืนรหัสผ่าน"""
        self._n += 1
        name = name or f"u{self._n:04d}"
        pw = auth.generate_password()
        con = self.con()
        con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                    (name, role, auth.hash_password(pw) if role == "team" else "link-only$test", now_iso()))
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        for p in packages or []:
            con.execute("INSERT OR IGNORE INTO assignments VALUES (?,?)", (uid, self.pkg_ids.get(p, p)))
        secret = pw
        if role == "doctor":
            secret = auth.new_link(con, uid, datetime.now(timezone.utc) + timedelta(days=days), once=once)
        con.close()
        return name, secret

    def new_link(self, name: str, days: float = 30, once: bool = False) -> str:
        """เหมือน make-link: ยกเลิกลิงก์เดิม + ออกจากระบบทุกเครื่อง แล้วคืนโทเคนใหม่"""
        con = self.con()
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        tok = auth.new_link(con, uid, datetime.now(timezone.utc) + timedelta(days=days), once=once)
        con.close()
        return tok

    def revoke(self, name: str) -> None:
        con = self.con()
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        auth.revoke_links(con, uid)
        con.close()

    def role_of(self, name: str) -> str:
        con = self.con()
        r = con.execute("SELECT role FROM users WHERE username = ?", (name,)).fetchone()[0]
        con.close()
        return r

    # ---------- เบราว์เซอร์ ----------
    def login(self, context, name: str, secret: str) -> None:
        """เข้าสู่ระบบผ่าน API (เร็ว): หมอใช้โทเคนของลิงก์ · ทีมใช้รหัสผ่าน"""
        if self.role_of(name) == "doctor":
            r = context.request.post(f"{self.base}/api/link-login", data=json.dumps({"token": secret}),
                                     headers={**H, "Content-Type": "application/json"})
        else:
            r = context.request.post(f"{self.base}/api/login", data=json.dumps({"username": name, "password": secret}),
                                     headers={**H, "Content-Type": "application/json"})
        assert r.ok, f"login {name}: {r.status}"

    def url(self, pkg: str | None = None, base: str | None = None) -> str:
        return f"{base or self.base}/" + (f"?package={self.pkg_ids.get(pkg, pkg)}" if pkg else "")

    def link(self, token: str, pkg: str | None = None, base: str | None = None) -> str:
        """ลิงก์ส่วนตัวแบบที่ make-link พิมพ์ (โทเคนหลัง #)"""
        return f"{self.url(pkg, base)}#t={token}"

    def open(self, page, pkg: str, user: tuple[str, str] | None = None, wait_ready=True):
        """เข้าสู่ระบบ (บัญชีใหม่ถ้าไม่ระบุ) แล้วเปิดหน้าเว็บที่แพ็กเกจ pkg · คืน (ชื่อ, รหัส)"""
        user = user or self.add_user([pkg])
        self.login(page.context, *user)
        page.goto(self.url(pkg))
        if wait_ready:
            page.wait_for_selector("body[data-ready='1']")
        return user

    def task_row(self, user: str, pkg: str, task_id: str):
        con = self.con()
        r = con.execute("""SELECT t.rev, t.data FROM tasks_latest t JOIN users u ON u.id = t.user_id
                           WHERE u.username = ? AND t.package_id = ? AND t.task_id = ?""",
                        (user, self.pkg_ids.get(pkg, pkg), task_id)).fetchone()
        con.close()
        return (r[0], json.loads(r[1])) if r else (0, None)

    def stop(self):
        self.srv.shutdown()
        for h in list(logging.getLogger("pelnav").handlers):
            h.close()
            logging.getLogger("pelnav").removeHandler(h)
        shutil.rmtree(self.tmp, ignore_errors=True)
