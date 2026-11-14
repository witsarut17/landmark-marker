"""เซิร์ฟเวอร์จริงสำหรับเทสต์เบราว์เซอร์ (ข้อมูลชั่วคราว ภาพทดสอบสังเคราะห์เท่านั้น)

TestServer() -> เปิด Flask app บนพอร์ตสุ่ม 127.0.0.1 · ลงทะเบียนแพ็กเกจทดสอบทุกชุดใน tests/generated
server.open(page, "test_package") -> สร้างบัญชีแพทย์ใหม่ (งานว่าง) เข้าสู่ระบบ แล้วเปิดหน้าเว็บที่แพ็กเกจนั้น
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
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
    def __init__(self, packages=PACKAGES):
        self.tmp = Path(tempfile.mkdtemp(prefix="pelnav_test_"))
        (self.tmp / "config.toml").write_text('[server]\n[paths]\ndb = "db/marks.sqlite"\nbackups = "backups"\nlogs = "logs"\n',
                                              encoding="utf-8")
        self.cfg = Config.load(self.tmp / "config.toml")
        init_db(self.cfg.db)
        self.pkg_ids: dict[str, str] = {}
        for name in packages:
            if (GEN / name / "manifest.json").exists():
                self.register(name, GEN / name)
        self.app = create_app(self.cfg)
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True, request_handler=_Quiet)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
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

    def add_user(self, packages=None, role: str = "doctor", name: str | None = None) -> tuple[str, str]:
        self._n += 1
        name = name or f"u{self._n:04d}"
        pw = auth.generate_password()
        con = self.con()
        con.execute("INSERT INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                    (name, role, auth.hash_password(pw), now_iso()))
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
        for p in packages or []:
            con.execute("INSERT OR IGNORE INTO assignments VALUES (?,?)", (uid, self.pkg_ids.get(p, p)))
        con.close()
        return name, pw

    # ---------- เบราว์เซอร์ ----------
    def login(self, context, name: str, pw: str) -> None:
        r = context.request.post(f"{self.base}/api/login", data=json.dumps({"username": name, "password": pw}),
                                 headers={**H, "Content-Type": "application/json"})
        assert r.ok, f"login {name}: {r.status}"

    def url(self, pkg: str | None = None) -> str:
        return f"{self.base}/" + (f"?package={self.pkg_ids.get(pkg, pkg)}" if pkg else "")

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
