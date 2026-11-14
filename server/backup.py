"""สำรองฐานข้อมูล SQLite อัตโนมัติ (ใช้คำสั่งสำรองของ SQLite เอง ทำระหว่างใช้งานได้)

เก็บรายชั่วโมงล่าสุด keep_hourly ไฟล์ + วันละ 1 ไฟล์ย้อนหลัง keep_daily วัน · ตรวจไฟล์สำรองทุกครั้ง (integrity_check)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("pelnav")
PREFIX = "marks-"


def backup_now(db_path: Path, backups_dir: Path) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest = backups_dir / f"{PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite"
    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if ok != "ok":
        dest.rename(dest.with_suffix(".broken"))
        raise RuntimeError(f"ไฟล์สำรองเสีย: {ok}")
    return dest


def rotate(backups_dir: Path, keep_hourly: int, keep_daily: int) -> list[Path]:
    files = sorted(backups_dir.glob(f"{PREFIX}*.sqlite"))          # ชื่อเรียงตามเวลา
    keep = set(files[-keep_hourly:])
    days_seen: list[str] = []
    for f in reversed(files):                                        # ใหม่ -> เก่า: เก็บไฟล์ล่าสุดของแต่ละวัน
        day = f.stem[len(PREFIX):len(PREFIX) + 8]
        if day not in days_seen:
            days_seen.append(day)
            if len(days_seen) <= keep_daily:
                keep.add(f)
    removed = [f for f in files if f not in keep]
    for f in removed:
        f.unlink()
    return removed


def last_backup(backups_dir: Path) -> str | None:
    files = sorted(backups_dir.glob(f"{PREFIX}*.sqlite")) if backups_dir.exists() else []
    if not files:
        return None
    return datetime.fromtimestamp(files[-1].stat().st_mtime).isoformat(timespec="seconds")


class BackupThread(threading.Thread):
    def __init__(self, db_path: Path, backups_dir: Path, every_minutes: int, keep_hourly: int, keep_daily: int):
        super().__init__(daemon=True, name="pelnav-backup")
        self.db_path, self.backups_dir = db_path, backups_dir
        self.every = max(1, every_minutes) * 60
        self.keep_hourly, self.keep_daily = keep_hourly, keep_daily
        self.stop_event = threading.Event()

    def run_once(self) -> None:
        try:
            dest = backup_now(self.db_path, self.backups_dir)
            removed = rotate(self.backups_dir, self.keep_hourly, self.keep_daily)
            log.info("สำรองฐานข้อมูล %s (ลบไฟล์เก่า %d)", dest.name, len(removed))
        except Exception as e:            # สำรองล้มต้องไม่ทำให้เซิร์ฟเวอร์ล้ม แต่ต้องเห็นใน log
            log.error("สำรองฐานข้อมูลไม่สำเร็จ: %s", e)

    def run(self) -> None:
        self.run_once()
        while not self.stop_event.wait(self.every):
            self.run_once()
