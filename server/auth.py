"""รหัสผ่าน (scrypt) · session ฝั่งเซิร์ฟเวอร์ · จำกัดการลองรหัสผิด"""

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


def new_session(con, user_id: int, days: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen) VALUES (?,?,?,?,?)",
                (token_hash(token), user_id, now_iso(),
                 (now + timedelta(days=days)).isoformat(timespec="seconds"), now_iso()))
    return token


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
