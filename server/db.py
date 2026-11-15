"""ฐานข้อมูล SQLite (โหมด WAL) — โครงสร้างตารางและการเชื่อมต่อ

tasks_latest = สถานะล่าสุดต่องาน · task_events = ทุกการบันทึก (ไม่ลบ ไม่ทับ ใช้ตรวจย้อนหลัง/กู้คืน)
login_links = ลิงก์ส่วนตัวของหมอ (เก็บเฉพาะ hash ของโทเคน) · ตารางใหม่ถูกเพิ่มเองเมื่อเปิดเซิร์ฟเวอร์ (CREATE IF NOT EXISTS)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('doctor', 'team')),
  pw_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packages (
  package_id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
  user_id INTEGER NOT NULL REFERENCES users(id),
  package_id TEXT NOT NULL REFERENCES packages(package_id),
  PRIMARY KEY (user_id, package_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks_latest (
  user_id INTEGER NOT NULL REFERENCES users(id),
  package_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  rev INTEGER NOT NULL,
  data TEXT NOT NULL,
  updated_at TEXT,
  saved_at TEXT NOT NULL,
  PRIMARY KEY (user_id, package_id, task_id)
);
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  package_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  rev INTEGER NOT NULL,
  data TEXT NOT NULL,
  saved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events (user_id, package_id, task_id);
CREATE TABLE IF NOT EXISTS login_links (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  once INTEGER NOT NULL DEFAULT 0,
  revoked_at TEXT,
  use_count INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_links_user ON login_links (user_id);
CREATE TABLE IF NOT EXISTS user_meta (
  user_id INTEGER NOT NULL REFERENCES users(id),
  package_id TEXT NOT NULL,
  current_index INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  PRIMARY KEY (user_id, package_id)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=15, isolation_level=None)   # autocommit · เปิด transaction เองด้วย BEGIN
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 15000")
    return con


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path)
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            con.execute("INSERT INTO schema_version (v) VALUES (?)", (SCHEMA_VERSION,))
    finally:
        con.close()
