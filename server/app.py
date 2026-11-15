"""เว็บแอป Flask: หน้าเว็บมาร์กจุด + API (เข้าสู่ระบบ, manifest, ภาพ, บันทึกจุด, ข้อมูลสำหรับทีม)

ความปลอดภัย: รับเฉพาะคำขอจากเครือข่ายที่อนุญาต (allowed_networks ค่าเริ่มต้น 10.x + เครื่องตัวเอง),
หมอเข้าด้วยลิงก์ส่วนตัว (POST /api/link-login) · ทีมเข้าด้วยรหัสผ่าน (POST /api/login),
session ฝั่งเซิร์ฟเวอร์ (คุกกี้ HttpOnly + SameSite=Strict + Secure เมื่อใช้ HTTPS),
คำขอที่เปลี่ยนข้อมูลต้องมี header X-Requested-With: pelnav และ Origin ตรงกับเว็บนี้,
ภาพส่งตามรหัสงานเท่านั้น (ผู้ใช้ส่ง path ไม่ได้) และไม่ให้เบราว์เซอร์เก็บแคช, log ไม่มีภาพ ข้อมูลผู้ป่วย หรือโทเคน
"""

from __future__ import annotations

import ipaddress
import json
import logging
import logging.handlers
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory

from . import auth
from .backup import last_backup
from .db import connect, now_iso
from .validate import FINAL, IMG_EXT, Invalid, clean_task, load_manifest, public_manifest

COOKIE = "pelnav_session"
CSRF_HEADER = ("X-Requested-With", "pelnav")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORKS = ["10.0.0.0/8", "127.0.0.0/8", "::1/128"]     # เครือข่ายภายในมหาวิทยาลัย/VPN (10.x) + เครื่องตัวเอง


@dataclass
class Config:
    data_dir: Path
    db: Path
    backups: Path
    logs: Path
    web: Path
    host: str = "127.0.0.1"
    port: int = 8090
    secure_cookies: bool = False      # true เฉพาะเมื่อใช้ผ่าน HTTPS (เครื่องแล็บใช้ http ผ่าน VPN -> false)
    trusted_proxy: bool = False       # true เฉพาะเมื่ออยู่หลัง reverse proxy บนเครื่องเดียวกัน
    session_days: int = 30            # อายุการเข้าสู่ระบบของบัญชีทีม (ของหมอหมดพร้อมลิงก์)
    allowed_networks: list = field(default_factory=lambda: list(DEFAULT_NETWORKS))   # ว่าง [] = รับทุกที่ (ไม่แนะนำ)
    public_url: str = ""              # ที่อยู่ที่หมอเปิด เช่น http://<IP เครื่องแล็บ>:8090/ (ใช้ตอนสร้างลิงก์)
    backup_every_minutes: int = 60
    keep_hourly: int = 48
    keep_daily: int = 30
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Config":
        d = tomllib.loads(path.read_text(encoding="utf-8-sig"))      # utf-8-sig: ไฟล์ที่ PowerShell 5.1 เขียนมี BOM
        base = path.parent.resolve()
        p = d.get("paths", {})
        s = d.get("server", {})
        b = d.get("backup", {})
        rel = lambda v, dflt: (base / v if not Path(v).is_absolute() else Path(v)).resolve() if v else dflt  # noqa: E731
        return cls(
            data_dir=base,
            db=rel(p.get("db", "db/marks.sqlite"), None),
            backups=rel(p.get("backups", "backups"), None),
            logs=rel(p.get("logs", "logs"), None),
            web=rel(p.get("web", ""), ROOT / "marker"),
            host=s.get("host", "127.0.0.1"), port=int(s.get("port", 8090)),
            secure_cookies=bool(s.get("secure_cookies", False)), trusted_proxy=bool(s.get("trusted_proxy", False)),
            session_days=int(s.get("session_days", 30)),
            allowed_networks=list(s.get("allowed_networks", DEFAULT_NETWORKS)), public_url=str(s.get("public_url", "")),
            backup_every_minutes=int(b.get("every_minutes", 60)),
            keep_hourly=int(b.get("keep_hourly", 48)), keep_daily=int(b.get("keep_daily", 30)),
        )


def setup_logging(logs_dir: Path) -> logging.Logger:
    log = logging.getLogger("pelnav")
    if log.handlers:
        return log
    logs_dir.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fh = logging.handlers.TimedRotatingFileHandler(logs_dir / "app.log", when="midnight", backupCount=180, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    return log


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024          # ข้อมูลงาน 1 งานเล็กมาก
    log = setup_logging(cfg.logs)
    limiter = auth.LoginLimiter()                          # รหัสผ่านผิด (บัญชีทีม): 10 ครั้ง/15 นาที ต่อ IP และต่อชื่อ
    link_limiter = auth.LoginLimiter(max_fail=30)          # ลิงก์ผิด/หมดอายุ: 30 ครั้ง/15 นาที ต่อ IP (VPN อาจให้หลายคนใช้ IP เดียว)
    try:
        networks = [ipaddress.ip_network(n, strict=False) for n in cfg.allowed_networks]
    except ValueError as e:
        raise SystemExit(f"allowed_networks ใน config.toml ผิด: {e}")
    manifests: dict[str, tuple[float, dict]] = {}

    # ---------- ฐานข้อมูลต่อคำขอ ----------
    def db():
        if "db" not in g:
            g.db = connect(cfg.db)
        return g.db

    @app.teardown_appcontext
    def _close(_exc):
        con = g.pop("db", None)
        if con is not None:
            con.close()

    def client_ip() -> str:
        return request.remote_addr or "?"            # หลัง proxy: waitress แทนค่าให้จาก X-Forwarded-For (trusted_proxy)

    def manifest_of(package_id: str) -> tuple[dict, Path]:
        row = db().execute("SELECT path FROM packages WHERE package_id = ?", (package_id,)).fetchone()
        if not row:
            abort(404)
        pkg_dir = Path(row["path"])
        try:
            mtime = (pkg_dir / "manifest.json").stat().st_mtime
        except OSError:
            abort(500, description="ไม่พบ manifest ของแพ็กเกจบนเซิร์ฟเวอร์")
        cached = manifests.get(package_id)
        if not cached or cached[0] != mtime:
            try:
                m, _ = load_manifest(pkg_dir)
            except (Invalid, OSError, ValueError) as e:
                log.error("เปิดแพ็กเกจ %s ไม่ได้: %s", package_id, e)
                abort(500, description=f"เปิดแพ็กเกจไม่ได้: {e}")
            if m["package_id"] != package_id:
                abort(500, description="package_id ใน manifest ไม่ตรงกับที่ลงทะเบียน")
            manifests[package_id] = (mtime, m)
        return manifests[package_id][1], pkg_dir

    # ---------- ผู้ใช้ ----------
    def current_user():
        if "user" not in g:
            g.user = auth.session_user(db(), request.cookies.get(COOKIE))
        return g.user

    def require_user(role: str | None = None):
        u = current_user()
        if not u:
            abort(401)
        if role and u["role"] != role:
            abort(403)
        return u

    def assigned_package(u) -> str:
        rows = [r["package_id"] for r in db().execute(
            "SELECT package_id FROM assignments WHERE user_id = ? ORDER BY package_id", (u["id"],))]
        want = request.args.get("package")
        if want:
            if want not in rows:
                abort(403)
            return want
        if len(rows) != 1:
            abort(409, description="ยังไม่ได้กำหนดแพ็กเกจ หรือมีหลายแพ็กเกจ — ติดต่อทีม")
        return rows[0]

    def ip_allowed(ip: str) -> bool:
        if not networks:
            return True
        try:
            a = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        if getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        return any(a in n for n in networks if n.version == a.version)

    # ---------- ตรวจทุกคำขอ ----------
    @app.before_request
    def _before():
        g.t0 = time.perf_counter()
        if not ip_allowed(client_ip()):
            log.warning("ปฏิเสธคำขอจากนอกเครือข่ายที่อนุญาต ip=%s", client_ip())
            abort(403, description="เข้าได้เฉพาะจากเครือข่ายภายในของมหาวิทยาลัย — ต่อ VPN ก่อน")
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get(CSRF_HEADER[0]) != CSRF_HEADER[1]:
                abort(403, description="คำขอไม่ได้มาจากหน้าเว็บนี้")
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                abort(403, description="Origin ไม่ตรง")

    @app.after_request
    def _after(resp):
        h = resp.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if cfg.secure_cookies:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        u = g.get("user")
        log.info("%s %s %s %s %d %.0fms", client_ip(), u["username"] if u else "-", request.method, request.path,
                 resp.status_code, (time.perf_counter() - g.get("t0", time.perf_counter())) * 1000)
        return resp

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    @app.errorhandler(500)
    def _err(e):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(e, "description", str(e)), status=e.code), e.code
        return e

    # ---------- เข้าสู่ระบบ ----------
    @app.post("/api/login")
    def login():
        d = request.get_json(silent=True) or {}
        username = str(d.get("username", ""))[:80].strip().lower()
        password = str(d.get("password", ""))[:200]
        ip = client_ip()
        if limiter.blocked(f"ip:{ip}", f"user:{username}"):
            log.warning("เข้าสู่ระบบถูกระงับชั่วคราว (ลองผิดหลายครั้ง) ip=%s user=%s", ip, username)
            abort(429, description="ลองรหัสผิดหลายครั้ง — รอ 15 นาทีแล้วลองใหม่")
        row = db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = auth.verify_password(password, row["pw_hash"] if row else auth.DUMMY_HASH) and bool(row) and bool(row["active"])
        if not ok:
            limiter.fail(f"ip:{ip}", f"user:{username}")
            log.warning("เข้าสู่ระบบไม่สำเร็จ ip=%s user=%s", ip, username)
            abort(401, description="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        limiter.reset(f"user:{username}")
        if row["role"] == "doctor":            # หมอเข้าด้วยลิงก์ส่วนตัวเท่านั้น
            abort(403, description="บัญชีแพทย์เข้าด้วยลิงก์ส่วนตัวที่ทีมวิจัยส่งให้ ไม่ใช้รหัสผ่าน")
        return start_session(row, *auth.new_session(db(), row["id"], cfg.session_days))

    def start_session(row, token: str, expires):
        auth.end_session(db(), request.cookies.get(COOKIE))       # session เดิมของเบราว์เซอร์นี้ (ถ้ามี) ไม่ใช้แล้ว
        g.user = row
        resp = jsonify(username=row["username"], role=row["role"], expires_at=expires.isoformat(timespec="seconds"))
        max_age = max(60, int((expires - datetime.now(timezone.utc)).total_seconds()))
        resp.set_cookie(COOKIE, token, max_age=max_age, httponly=True, secure=cfg.secure_cookies,
                        samesite="Strict", path="/")
        return resp

    @app.post("/api/link-login")
    def link_login():
        d = request.get_json(silent=True) or {}
        ip = client_ip()
        if link_limiter.blocked(f"ip:{ip}"):
            log.warning("เข้าด้วยลิงก์ถูกระงับชั่วคราว (ลิงก์ผิดหลายครั้ง) ip=%s", ip)
            abort(429, description="ลองลิงก์ที่ใช้ไม่ได้หลายครั้ง — รอ 15 นาทีแล้วลองใหม่")
        con = db()
        con.execute("BEGIN IMMEDIATE")              # ลิงก์ครั้งเดียว: กันสองคำขอพร้อมกันใช้ซ้ำ
        try:
            got = auth.use_link(con, str(d.get("token", ""))[:200])
            if got:
                row, exp = got
                token, exp = auth.new_session(con, row["id"], expires=exp)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if not got:
            link_limiter.fail(f"ip:{ip}")
            log.warning("เข้าด้วยลิงก์ไม่สำเร็จ (ไม่มี/หมดอายุ/ยกเลิก/ใช้แล้ว) ip=%s", ip)
            abort(401, description="ลิงก์นี้ใช้ไม่ได้แล้ว (หมดอายุหรือถูกยกเลิก) — ขอลิงก์ใหม่จากทีมวิจัย")
        log.info("เข้าด้วยลิงก์ส่วนตัว ip=%s user=%s", ip, row["username"])
        return start_session(row, token, exp)

    @app.post("/api/logout")
    def logout():
        auth.end_session(db(), request.cookies.get(COOKIE))
        resp = jsonify(ok=True)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/me")
    def me():
        u = require_user()
        pk = [r["package_id"] for r in db().execute("SELECT package_id FROM assignments WHERE user_id = ?", (u["id"],))]
        return jsonify(username=u["username"], role=u["role"], packages=pk)

    @app.get("/api/health")
    def health():
        db().execute("SELECT 1")
        return jsonify(ok=True, time=now_iso())

    # ---------- งานของหมอ ----------
    @app.get("/api/package")
    def package():
        u = require_user()
        m, _ = manifest_of(assigned_package(u))
        return jsonify(public_manifest(m))

    @app.get("/api/image/<task_id>/<side>")
    def image(task_id: str, side: str):
        u = require_user()
        if side not in ("xray", "fluoro"):
            abort(404)
        pkg = assigned_package(u) if u["role"] == "doctor" else request.args.get("package") or abort(400)
        m, pkg_dir = manifest_of(pkg)
        item = next((it for it in m["items"] if it["task_id"] == task_id), None)
        if not item:
            abort(404)
        path = (pkg_dir / item[side]).resolve()
        if pkg_dir.resolve() not in path.parents or not path.is_file():
            abort(404)
        resp = send_file(path, mimetype=IMG_EXT[path.suffix.lower()], conditional=False, etag=False, max_age=0)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def state_of(user_id: int, pkg: str) -> dict:
        tasks, revs = {}, {}
        for r in db().execute("SELECT task_id, rev, data FROM tasks_latest WHERE user_id = ? AND package_id = ?",
                              (user_id, pkg)):
            tasks[r["task_id"]] = json.loads(r["data"])
            revs[r["task_id"]] = r["rev"]
        meta = db().execute("SELECT current_index FROM user_meta WHERE user_id = ? AND package_id = ?",
                            (user_id, pkg)).fetchone()
        return {"package_id": pkg, "tasks": tasks, "revs": revs, "current_index": meta["current_index"] if meta else 0}

    @app.get("/api/state")
    def state():
        u = require_user()
        return jsonify(state_of(u["id"], assigned_package(u)))

    @app.put("/api/tasks/<task_id>")
    def save_task(task_id: str):
        u = require_user("doctor")
        pkg = assigned_package(u)
        m, _ = manifest_of(pkg)
        item = next((it for it in m["items"] if it["task_id"] == task_id), None)
        if not item:
            abort(404)
        d = request.get_json(silent=True)
        if not isinstance(d, dict) or not isinstance(d.get("base_rev"), int):
            abort(400, description="ต้องมี task และ base_rev")
        try:
            task = clean_task(d.get("task"), item)
        except Invalid as e:
            log.warning("ข้อมูลงานไม่ถูกต้อง user=%s task=%s: %s", u["username"], task_id, e)
            abort(400, description=f"ข้อมูลงานไม่ถูกต้อง: {e}")
        con = db()
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute("SELECT rev, data FROM tasks_latest WHERE user_id = ? AND package_id = ? AND task_id = ?",
                              (u["id"], pkg, task_id)).fetchone()
            cur = row["rev"] if row else 0
            if d["base_rev"] != cur:              # มีการบันทึกที่ใหม่กว่าจากอีกเครื่อง/อีกแท็บ
                con.execute("ROLLBACK")
                return jsonify(error="conflict", rev=cur, task=json.loads(row["data"]) if row else None), 409
            new_rev, saved = cur + 1, now_iso()
            data = json.dumps(task, ensure_ascii=False, separators=(",", ":"))
            con.execute("""INSERT INTO tasks_latest (user_id, package_id, task_id, rev, data, updated_at, saved_at)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT (user_id, package_id, task_id)
                           DO UPDATE SET rev = excluded.rev, data = excluded.data, updated_at = excluded.updated_at,
                                         saved_at = excluded.saved_at""",
                        (u["id"], pkg, task_id, new_rev, data, task.get("updated_at"), saved))
            con.execute("INSERT INTO task_events (user_id, package_id, task_id, rev, data, saved_at) VALUES (?,?,?,?,?,?)",
                        (u["id"], pkg, task_id, new_rev, data, saved))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return jsonify(rev=new_rev, saved_at=saved)

    @app.put("/api/meta")
    def save_meta():
        u = require_user("doctor")
        pkg = assigned_package(u)
        d = request.get_json(silent=True) or {}
        idx = d.get("current_index")
        m, _ = manifest_of(pkg)
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < len(m["items"])):
            abort(400, description="current_index ผิด")
        db().execute("""INSERT INTO user_meta (user_id, package_id, current_index, updated_at) VALUES (?,?,?,?)
                        ON CONFLICT (user_id, package_id) DO UPDATE SET current_index = excluded.current_index,
                        updated_at = excluded.updated_at""", (u["id"], pkg, idx, now_iso()))
        return jsonify(ok=True)

    # ---------- สำหรับทีม ----------
    @app.get("/api/admin/overview")
    def admin_overview():
        require_user("team")
        out = []
        for r in db().execute("""SELECT u.id, u.username, a.package_id FROM users u
                                 JOIN assignments a ON a.user_id = u.id WHERE u.role = 'doctor' ORDER BY u.username"""):
            m, _ = manifest_of(r["package_id"])
            rows = db().execute("SELECT data, saved_at FROM tasks_latest WHERE user_id = ? AND package_id = ?",
                                (r["id"], r["package_id"])).fetchall()
            sts = [json.loads(x["data"])["status"] for x in rows]
            out.append({"username": r["username"], "package_id": r["package_id"], "total": len(m["items"]),
                        "done": sum(s in FINAL for s in sts), "skipped": sum(s == "skipped" for s in sts),
                        "last_saved": max((x["saved_at"] for x in rows), default=None)})
        return jsonify(doctors=out, last_backup=last_backup(cfg.backups))

    @app.get("/api/admin/data")
    def admin_data():
        require_user("team")
        username, pkg = request.args.get("user", ""), request.args.get("package", "")
        u = db().execute("SELECT u.id FROM users u JOIN assignments a ON a.user_id = u.id "
                         "WHERE u.username = ? AND a.package_id = ?", (username, pkg)).fetchone()
        if not u:
            abort(404)
        m, _ = manifest_of(pkg)
        st = state_of(u["id"], pkg)
        return jsonify(username=username, items=public_manifest(m)["items"], **st)

    # ---------- หน้าเว็บ ----------
    @app.get("/")
    def index():
        return send_from_directory(cfg.web, "index.html")

    @app.get("/<path:name>")
    def static_file(name: str):
        if name.startswith("api/"):
            abort(404)
        return send_from_directory(cfg.web, name)       # send_from_directory กัน ../ ออกนอกโฟลเดอร์ให้แล้ว

    return app
