"""ตรวจข้อมูลที่หน้าเว็บส่งมา และอ่าน manifest ของแพ็กเกจ

เก็บเฉพาะฟิลด์ที่รู้จัก (ฟิลด์อื่นทิ้ง) · พิกัดต้องอยู่ในภาพ · สถานะ/เหตุผลต้องเป็นค่าที่กำหนด
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

N_POINTS = 4
STATUSES = {"todo", "in_progress", "skipped", "done", "partial", "unmarkable"}
FINAL = {"done", "partial", "unmarkable"}
REASONS = {"unclear", "no_overlap", "view_angle", "no_4th_point", "other"}
TASK_ID_RE = re.compile(r"^T\d{3,}$")
IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
NOTE_MAX, REASON_TEXT_MAX, TIME_MAX = 300, 200, 40


class Invalid(ValueError):
    pass


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _opt_str(t: dict, key: str, max_len: int):
    v = t.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > max_len:
        raise Invalid(f"{key} ผิดรูปแบบ")
    return v


def clean_point(p, size, where: str):
    if p is None:
        return None
    if not isinstance(p, dict) or not _num(p.get("x")) or not _num(p.get("y")):
        raise Invalid(f"{where}: พิกัดผิดรูปแบบ")
    W, H = size
    if not (0 <= p["x"] <= W and 0 <= p["y"] <= H):
        raise Invalid(f"{where}: จุดอยู่นอกภาพ")
    out = {"x": float(p["x"]), "y": float(p["y"])}
    ipp = p.get("image_px_per_screen_px")
    if ipp is not None:
        if not _num(ipp) or not (0 < ipp <= 10):
            raise Invalid(f"{where}: image_px_per_screen_px ผิด")
        out["image_px_per_screen_px"] = float(ipp)
    at = p.get("at")
    if at is not None:
        if not isinstance(at, str) or len(at) > TIME_MAX:
            raise Invalid(f"{where}: เวลาไม่ถูกต้อง")
        out["at"] = at
    return out


def clean_task(task, item: dict) -> dict:
    """คืนงานที่ตรวจแล้ว (เฉพาะฟิลด์ที่รู้จัก) หรือ raise Invalid"""
    if not isinstance(task, dict):
        raise Invalid("ข้อมูลงานไม่ใช่ object")
    out = {}
    for side, size_key in (("xray", "xray_size"), ("fluoro", "fluoro_size")):
        pts = task.get(side)
        if not isinstance(pts, list) or len(pts) != N_POINTS:
            raise Invalid(f"{side} ต้องมี {N_POINTS} ช่อง")
        out[side] = [clean_point(p, item[size_key], f"{side} จุด {i + 1}") for i, p in enumerate(pts)]
    st = task.get("status")
    if st not in STATUSES:
        raise Invalid("สถานะไม่รู้จัก")
    out["status"] = st
    reason = task.get("reason")
    if reason is not None and reason not in REASONS:
        raise Invalid("เหตุผลไม่รู้จัก")
    out["reason"] = reason
    out["reason_text"] = _opt_str(task, "reason_text", REASON_TEXT_MAX)
    out["note"] = _opt_str(task, "note", NOTE_MAX)
    for k in ("started_at", "finished_at", "updated_at"):
        out[k] = _opt_str(task, k, TIME_MAX)
    d = task.get("duration_ms", 0)
    if not isinstance(d, int) or isinstance(d, bool) or not (0 <= d <= 10 ** 9):
        raise Invalid("duration_ms ผิด")
    out["duration_ms"] = d
    return out


def load_manifest(pkg_dir: Path) -> tuple[dict, str]:
    """อ่านและตรวจ manifest.json · คืน (manifest, sha256) · ภาพทุกไฟล์ต้องมีอยู่ในโฟลเดอร์"""
    raw = (pkg_dir / "manifest.json").read_bytes()
    m = json.loads(raw.decode("utf-8"))
    if not isinstance(m, dict) or not isinstance(m.get("package_id"), str) or not m["package_id"]:
        raise Invalid("manifest ไม่มี package_id")
    items = m.get("items")
    if not isinstance(items, list) or not items:
        raise Invalid("manifest ไม่มี items")
    seen = set()
    for it in items:
        tid = it.get("task_id")
        if not isinstance(tid, str) or not TASK_ID_RE.match(tid) or tid in seen:
            raise Invalid(f"task_id ผิดหรือซ้ำ: {tid}")
        seen.add(tid)
        for side in ("xray", "fluoro"):
            name = it.get(side)
            if not isinstance(name, str) or "/" in name or "\\" in name or Path(name).suffix.lower() not in IMG_EXT:
                raise Invalid(f"{tid}: ชื่อไฟล์ {side} ไม่ถูกต้อง")
            if not (pkg_dir / name).is_file():
                raise Invalid(f"{tid}: ไม่พบไฟล์ภาพ {side}")
            s = it.get(f"{side}_size")
            if not (isinstance(s, list) and len(s) == 2 and all(isinstance(v, int) and v > 0 for v in s)):
                raise Invalid(f"{tid}: {side}_size ผิด")
        b = it.get("box_xyxy")
        if not (isinstance(b, list) and len(b) == 4 and all(_num(v) for v in b)):
            raise Invalid(f"{tid}: box_xyxy ผิด")
        fa = it.get("fluoro_area")          # ไม่บังคับ: พื้นที่วงกลมฟลู (แพ็กเกจภาพต้นฉบับ ซึ่งไม่ได้ทาดำรอบวงกลม)
        if fa is not None and not (_num(fa) and 0 < fa <= it["fluoro_size"][0] * it["fluoro_size"][1]):
            raise Invalid(f"{tid}: fluoro_area ผิด")
    return m, hashlib.sha256(raw).hexdigest()


def public_manifest(m: dict) -> dict:
    """manifest ที่ส่งให้หน้าเว็บ: ไม่ส่งชื่อไฟล์จริง (อาจมีข้อมูลผู้ป่วย) ใช้ชื่อตามรหัสงาน + นามสกุลเดิมแทน"""
    items = []
    for it in m["items"]:
        items.append({
            "task_id": it["task_id"],
            "xray": f"{it['task_id']}_X{Path(it['xray']).suffix.lower()}",
            "fluoro": f"{it['task_id']}_F{Path(it['fluoro']).suffix.lower()}",
            "xray_size": it["xray_size"], "fluoro_size": it["fluoro_size"],
            "box_xyxy": it["box_xyxy"], "is_repeat_of": it.get("is_repeat_of"),
            **({"rotation": it["rotation"]} if "rotation" in it else {}),
            **({"fluoro_area": it["fluoro_area"]} if it.get("fluoro_area") is not None else {}),
        })
    return {"package_id": m["package_id"], "items": items}
