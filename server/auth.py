"""รหัสผ่าน (scrypt, บัญชีทีม) · ลิงก์ส่วนตัว (บัญชีหมอ) · session ฝั่งเซิร์ฟเวอร์ · จำกัดการลองผิด

ลิงก์ส่วนตัว: http://<เครื่องแล็บ>:8090/#t=<โทเคนสุ่ม 256 บิต>
- โทเคนอยู่หลัง # จึงไม่ถูกส่งไปกับคำขอหน้าเว็บ ไม่อยู่ใน log ของเซิร์ฟเวอร์ · หน้าเว็บส่งให้ POST /api/link-login แล้วลบออกจากแถบที่อยู่
- ฐานข้อมูลเก็บเฉพาะ sha256 ของโทเคน · ลิงก์ใช้ซ้ำได้จนถึงวันหมดอายุ (หรือครั้งเดียวถ้าสร้างด้วย --once)
- สร้างลิงก์ใหม่หรือยกเลิกลิงก์ = ลิงก์เก่าใช้ไม่ได้ + ทุกเครื่องที่เข้าอยู่ต้องแตะลิงก์ใหม่
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from .db import now_iso

SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
PW_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"          # ไม่มี l 1 o 0 i ที่อ่านสับสน


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")   # ผู้ใช้ไม่มีอยู่ -> ยังคำนวณ scrypt ให้เวลาเท่ากัน


def generate_password() -> str:
    """รหัสผ่านสุ่ม 4 กลุ่ม กลุ่มละ 4 ตัว (~80 บิต) เช่น xxxx-xxxx-xxxx-xxxx"""
    return "-".join("".join(secrets.choice(PW_ALPHABET) for _ in range(4)) for _ in range(4))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_session(con, user_id: int, days: int = 30, expires: datetime | None = None) -> tuple[str, datetime]:
    """สร้าง session · คืน (โทเคนสำหรับคุกกี้, เวลาหมดอายุ) · expires = กำหนดเอง (session จากลิงก์หมดพร้อมลิงก์)"""
    token = secrets.token_urlsafe(32)
    exp = expires or (datetime.now(timezone.utc) + timedelta(days=days))
    con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen) VALUES (?,?,?,?,?)",
                (token_hash(token), user_id, now_iso(), exp.isoformat(timespec="seconds"), now_iso()))
    return token, exp


# ---------- ลิงก์ส่วนตัวของหมอ ----------
TH = timezone(timedelta(hours=7))          # เวลาประเทศไทย (ไม่มีเวลาออมแสง)


def end_of_day_th(day: str) -> datetime:
    """'2027-06-30' -> สิ้นวันนั้นตามเวลาประเทศไทย (23:59:59 +07:00) เป็น UTC"""
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=23, minute=59, second=59, tzinfo=TH).astimezone(timezone.utc)


def revoke_links(con, user_id: int) -> int:
    """ยกเลิกทุกลิงก์ของผู้ใช้ + ออกจากระบบทุกเครื่อง · คืนจำนวนลิงก์ที่ยกเลิก"""
    n = con.execute("UPDATE login_links SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now_iso(), user_id)).rowcount
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return n


def new_link(con, user_id: int, expires: datetime, once: bool = False) -> str:
    """ยกเลิกลิงก์เดิม (และ session เดิม) แล้วสร้างลิงก์ใหม่ · คืนโทเคน (แสดงครั้งเดียว ไม่เก็บตัวจริง)"""
    token = secrets.token_urlsafe(32)
    con.execute("BEGIN IMMEDIATE")
    try:
        revoke_links(con, user_id)
        con.execute("INSERT INTO login_links (user_id, token_hash, created_at, expires_at, once) VALUES (?,?,?,?,?)",
                    (user_id, token_hash(token), now_iso(), expires.isoformat(timespec="seconds"), int(once)))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return token


def use_link(con, token: str | None):
    """ตรวจโทเคนจากลิงก์ · ใช้ได้ -> คืน (row ผู้ใช้, เวลาหมดอายุของลิงก์) · ใช้ไม่ได้ -> None
    ใช้ได้เมื่อ: มีอยู่ ไม่ถูกยกเลิก ไม่หมดอายุ (ลิงก์ครั้งเดียวต้องยังไม่ถูกใช้) และบัญชีเป็นหมอที่ยังใช้งาน"""
    if not token or len(token) > 200 or not token.isascii():
        return None
    row = con.execute("""SELECT l.id AS link_id, l.expires_at AS link_expires, l.once, l.use_count, l.revoked_at, u.*
                         FROM login_links l JOIN users u ON u.id = l.user_id WHERE l.token_hash = ?""",
                      (token_hash(token),)).fetchone()
    if not row or row["revoked_at"] or not row["active"] or row["role"] != "doctor":
        return None
    exp = datetime.fromisoformat(row["link_expires"])
    if exp < datetime.now(timezone.utc) or (row["once"] and row["use_count"] > 0):
        return None
    con.execute("UPDATE login_links SET use_count = use_count + 1, last_used_at = ? WHERE id = ?", (now_iso(), row["link_id"]))
    return row, exp


def session_user(con, token: str | None):
    """คืน row ผู้ใช้ (active) ของ session ที่ยังไม่หมดอายุ หรือ None"""
    if not token or len(token) > 200:
        return None
    row = con.execute(
        "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (token_hash(token),)).fetchone()
    if not row or not row["active"]:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        return None
    con.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now_iso(), token_hash(token)))
    return row


def end_session(con, token: str | None) -> None:
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))


class LoginLimiter:
    """ลองรหัสผิดเกิน max_fail ครั้งใน window วินาที (ต่อ IP หรือต่อชื่อผู้ใช้) -> ปฏิเสธชั่วคราว"""

    def __init__(self, max_fail: int = 10, window: int = 15 * 60):
        self.max_fail, self.window = max_fail, window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cut = time.monotonic() - self.window
        lst = [t for t in self._fails.get(key, []) if t > cut]
        self._fails[key] = lst
        return lst

    def blocked(self, *keys: str) -> bool:
        with self._lock:
            return any(len(self._recent(k)) >= self.max_fail for k in keys)

    def fail(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._recent(k).append(time.monotonic())

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)
