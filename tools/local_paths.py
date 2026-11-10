"""ตำแหน่งข้อมูลจริงในเครื่องนี้ — อ่านจาก tools/data_root.txt (ไฟล์อยู่ใน .gitignore ไม่ขึ้น git)

ไฟล์ data_root.txt มี 1 บรรทัด = path ของโฟลเดอร์ข้อมูล (ที่มีโฟลเดอร์ย่อยรายเคส)
ตั้งครั้งแรก: สร้างไฟล์นี้เอง หรือใส่ --data-root ทุกครั้งที่รันสคริปต์
"""

from __future__ import annotations

from pathlib import Path

DATA_ROOT_FILE = Path(__file__).with_name("data_root.txt")


def data_root_or_none() -> Path | None:
    if not DATA_ROOT_FILE.exists():
        return None
    for line in DATA_ROOT_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().strip('"')
        if line and not line.startswith("#"):
            return Path(line)
    return None


def require_data_root(given: Path | None) -> Path:
    """ใช้ --data-root ถ้าใส่มา ไม่งั้นอ่านจาก data_root.txt · ไม่มีทั้งคู่ = หยุดพร้อมคำแนะนำ"""
    root = given or data_root_or_none()
    if root is None:
        raise SystemExit("ไม่รู้ว่าข้อมูลอยู่ที่ไหน: ใส่ --data-root \"<โฟลเดอร์ข้อมูล>\" "
                         "หรือสร้างไฟล์ tools/data_root.txt ที่มี path โฟลเดอร์ข้อมูล 1 บรรทัด")
    return root
