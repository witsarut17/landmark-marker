"""สร้าง study package (ภาพ + manifest.json) สำหรับเว็บมาร์กจุด จากข้อมูลจริง

ข้อมูลจริงอ่านอย่างเดียว: ไม่เขียน/แก้/ลบ/ย้ายอะไรใน data root (ตรวจซ้ำในโค้ด)
ตำแหน่งข้อมูล: --data-root หรือไฟล์ tools/data_root.txt (อยู่ในเครื่องเท่านั้น ไม่ขึ้น git)
ค่าเริ่มต้นคือ dry-run (แสดงสรุปเฉย ๆ) ต้องใส่ --write จึงจะสร้างไฟล์

ตัวอย่าง
  # pilot: 3 เคส เคสละ 2 คู่ ไม่มีงานซ้ำ -> pilot_package/, pilot_key.csv, pilot_report.csv, pilot_check/
  python -I -X utf8 -B tools/make_study_package.py --pilot --cases เคสตัวอย่าง1,เคสตัวอย่าง2,เคสตัวอย่าง3 --k 2
  python -I -X utf8 -B tools/make_study_package.py --pilot --cases เคสตัวอย่าง1,เคสตัวอย่าง2,เคสตัวอย่าง3 --k 2 --write

  # ชุดทดสอบจริง 70 ราย จาก splits.csv (ตรวจด้วย tools/check_splits.py ก่อน): k=3, งานซ้ำ 10% ห่างกัน ≥ 30 งาน
  # -> study_package/, key.csv, study_report.csv, study_check/
  python -I -X utf8 -B tools/make_study_package.py --splits splits.csv --k 3
  python -I -X utf8 -B tools/make_study_package.py --splits splits.csv --k 3 --write

หน่วย = คู่ภาพ = 1 annotation (กรอบบนเอกซเรย์) + ภาพฟลูที่ fluo_id ชี้ไป
ตรวจทุกคู่ (ไม่ผ่าน = ไม่เข้าแพ็กเกจ + เขียนเหตุผลในรายงาน):
  - หาไฟล์เอกซเรย์ตาม images[].file_name (ไม่สนตัวพิมพ์ใหญ่/เล็ก ถ้าไม่ซ้ำกัน)
  - ขนาดไฟล์เอกซเรย์จริง == width/height ใน COCO
  - fluo_id ชี้ไปภาพฟลูได้ 1 ภาพพอดี: ตรงชื่อ (ไม่สนตัวพิมพ์) หรือ "หลวม" = เลขตรงกันและไม่ซ้ำ (เช่น '0042' -> IMG_0042)
    fluo_id ที่มีคำต่อท้าย (เช่น 'rotate') = ไม่ผ่าน · fluo_id เดียวกันหลายกรอบ = ไม่ผ่านทั้งหมด
  - กรอบ: rotation = 0, w,h > 0, อยู่ในภาพ (เผื่อ 1 px แล้วตัดให้พอดี)
  - EXIF Orientation ต้องไม่มีหรือ = 1 ทั้งสองภาพ (ไม่รู้ว่า CVAT หมุนภาพตอนตีกรอบหรือไม่)
  - ภาพเปิดได้ · หลังลบ EXIF แล้วพิกเซลต้องเหมือนเดิมทุกจุด (ลบแบบไม่เข้ารหัสภาพใหม่)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import require_data_root  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
IMG_EXT = {".jpg", ".jpeg", ".png"}


# ------------------------------------------------------------------ ลบ metadata แบบไม่เข้ารหัสภาพใหม่
def strip_jpeg(data: bytes) -> bytes:
    """ตัด APP1 (EXIF/XMP), APP3–APP13, APP15, COM ออก · เก็บ APP0 (JFIF), APP2 (ICC สี), APP14 (Adobe สี) และข้อมูลภาพเดิมทุกไบต์"""
    if data[:2] != b"\xff\xd8":
        raise ValueError("ไม่ใช่ JPEG")
    out = bytearray(b"\xff\xd8")
    i = 2
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError("โครงสร้าง JPEG ผิด")
        while i + 1 < n and data[i + 1] == 0xFF:      # fill bytes
            i += 1
        m = data[i + 1]
        if m == 0xDA:                                  # SOS: ที่เหลือคือข้อมูลภาพ คัดลอกทั้งหมด
            out += data[i:]
            break
        if m == 0x01 or 0xD0 <= m <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + length]
        drop = (0xE1 <= m <= 0xEF and m not in (0xE2, 0xEE)) or m == 0xFE
        if not drop:
            out += seg
        i += 2 + length
    return bytes(out)


PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def strip_png(data: bytes) -> bytes:
    if data[:8] != PNG_SIG:
        raise ValueError("ไม่ใช่ PNG")
    out = bytearray(PNG_SIG)
    i = 8
    while i < len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        ctype = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        if ctype not in PNG_DROP:
            out += chunk
        i += 12 + length
        if ctype == b"IEND":
            break
    return bytes(out)


def strip_metadata(data: bytes, ext: str) -> bytes:
    return strip_png(data) if ext == ".png" else strip_jpeg(data)


def kind_of(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == PNG_SIG:
        return "png"
    return None


def pixels_digest(data: bytes) -> tuple[tuple[int, int], str]:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return im.size, hashlib.sha256(im.tobytes() + im.mode.encode()).hexdigest()


def exif_orientation(im: Image.Image) -> int | None:
    try:
        return im.getexif().get(0x0112)
    except Exception:
        return None


# ------------------------------------------------------------------ โครงสร้างข้อมูล
@dataclass
class Pair:
    case: str
    ann_id: int
    image_id: int
    xray_name_coco: str
    fluo_id: str
    bbox_xywh: list
    rotation: float
    coco_size: tuple
    xray_path: Path | None = None
    fluoro_path: Path | None = None
    xray_size: tuple | None = None
    fluoro_size: tuple | None = None
    box_xyxy: list | None = None
    match: str = ""
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems


def find_case_dirs(data_root: Path, cases: list[str]) -> list[Path]:
    dirs = []
    for c in cases:
        d = data_root / c
        if not (d / "instances_clean.json").is_file():
            sys.exit(f"ไม่พบ {c}\\instances_clean.json ใน {data_root}")
        dirs.append(d)
    return dirs


def list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)


def match_fluo(fid: str, fluoros: list[Path]):
    """คืน (path, ชนิดการจับคู่, ปัญหา)"""
    by_lower = defaultdict(list)
    for p in fluoros:
        by_lower[p.stem.lower()].append(p)
    key = fid.strip().lower()
    if len(by_lower.get(key, [])) == 1:
        return by_lower[key][0], ("exact" if by_lower[key][0].stem == fid.strip() else "case"), None
    if len(by_lower.get(key, [])) > 1:
        return None, "", f"fluo_id {fid} ตรงกับภาพฟลูหลายไฟล์"
    if re.fullmatch(r"\d+", key):                    # เช่น '3602' -> IMG_3602
        cands = [p for p in fluoros if re.sub(r"\D", "", p.stem) == key]
        if len(cands) == 1:                          # ใช้ได้เฉพาะเมื่อตรงได้ภาพเดียวในเคสนั้น
            return cands[0], "loose_digits", None
        if not cands:
            return None, "", f"ไม่พบภาพฟลูของ fluo_id {fid} (เลขล้วน)"
        return None, "", f"fluo_id {fid} (เลขล้วน) จับคู่หลวมได้ {len(cands)} ภาพ — ไม่รู้ว่าภาพไหน"
    m = re.fullmatch(r"(.*?\d+)([a-z_\- ]+)", key)
    if m and m.group(1) in by_lower:
        return None, "", f"fluo_id {fid} มีคำต่อท้าย '{m.group(2).strip()}' (อาจเป็นภาพที่ถูกหมุน/แก้) — ไม่ใช้"
    return None, "", f"ไม่พบภาพฟลูของ fluo_id {fid}"


def collect_pairs(case_dir: Path) -> list[Pair]:
    case = case_dir.name
    d = json.loads((case_dir / "instances_clean.json").read_text(encoding="utf-8"))
    images = {im["id"]: im for im in d.get("images", [])}
    xrays = list_images(case_dir / "xray")
    fluoros = list_images(case_dir / "fluoroscopy")
    x_by_lower = defaultdict(list)
    for p in xrays:
        x_by_lower[p.name.lower()].append(p)
    fid_count = Counter(str((a.get("attributes") or {}).get("fluo_id", "")).strip().lower() for a in d.get("annotations", []))

    pairs = []
    for a in d.get("annotations", []):
        attrs = a.get("attributes") or {}
        im = images.get(a.get("image_id"), {})
        p = Pair(case=case, ann_id=a.get("id"), image_id=a.get("image_id"),
                 xray_name_coco=im.get("file_name", ""), fluo_id=str(attrs.get("fluo_id", "")).strip(),
                 bbox_xywh=a.get("bbox"), rotation=float(attrs.get("rotation", 0) or 0),
                 coco_size=(im.get("width"), im.get("height")))
        if not im:
            p.problems.append("annotation ไม่มี image ที่อ้างถึง")
        # เอกซเรย์
        cand = x_by_lower.get(p.xray_name_coco.lower(), [])
        if len(cand) == 1:
            p.xray_path = cand[0]
            if cand[0].name != p.xray_name_coco:
                p.notes.append("ชื่อเอกซเรย์ต่างตัวพิมพ์ใหญ่/เล็ก")
        elif len(cand) > 1:
            p.problems.append("ชื่อเอกซเรย์ตรงกับหลายไฟล์")
        else:
            p.problems.append(f"ไม่พบไฟล์เอกซเรย์ {p.xray_name_coco}")
        # ฟลู
        if not p.fluo_id:
            p.problems.append("ไม่มี fluo_id")
        elif fid_count[p.fluo_id.lower()] > 1:
            p.problems.append(f"fluo_id {p.fluo_id} ซ้ำ {fid_count[p.fluo_id.lower()]} กรอบ — ไม่รู้ว่ากรอบไหนถูก")
        else:
            path, how, prob = match_fluo(p.fluo_id, fluoros)
            p.fluoro_path, p.match = path, how
            if prob:
                p.problems.append(prob)
            elif how == "loose_digits":
                p.notes.append(f"fluo_id '{p.fluo_id}' จับคู่แบบหลวมกับ {path.stem}")
        # ฟลูภาพเดียวกันถูกใช้โดยหลาย annotation (ผ่าน match หลวม)
        pairs.append(p)
    used = Counter(p.fluoro_path for p in pairs if p.fluoro_path and not p.problems)
    for p in pairs:
        if p.fluoro_path and not p.problems and used[p.fluoro_path] > 1:
            p.problems.append(f"ภาพฟลู {p.fluoro_path.name} ถูกใช้โดย {used[p.fluoro_path]} กรอบ")
    # กรอบ
    for p in pairs:
        b = p.bbox_xywh
        if p.rotation != 0:
            p.problems.append(f"กรอบหมุน {p.rotation}°")
        if not (isinstance(b, list) and len(b) == 4 and b[2] > 0 and b[3] > 0):
            p.problems.append("bbox ผิดรูป")
    return pairs


def check_images(p: Pair):
    """อ่านหัวภาพ (ไม่ถอดรหัสทั้งภาพ): ขนาด, EXIF Orientation, กรอบอยู่ในภาพ"""
    if p.problems:
        return
    for side, path in (("xray", p.xray_path), ("fluoro", p.fluoro_path)):
        try:
            with Image.open(path) as im:
                size = im.size
                fmt = (im.format or "").lower()
                ori = exif_orientation(im)
        except Exception as e:
            p.problems.append(f"เปิดภาพ{side}ไม่ได้ ({e.__class__.__name__})")
            continue
        ext = path.suffix.lower()
        if (fmt == "png") != (ext == ".png") or fmt not in ("jpeg", "png"):
            p.problems.append(f"{side}: ชนิดไฟล์จริง {fmt} ไม่ตรงนามสกุล {ext}")
        if ori not in (None, 1):
            p.problems.append(f"{side}: EXIF Orientation = {ori} (ไม่รู้ว่าตอนตีกรอบภาพถูกหมุนหรือไม่)")
        if side == "xray":
            p.xray_size = size
            if tuple(size) != tuple(p.coco_size):
                p.problems.append(f"ขนาดเอกซเรย์จริง {size[0]}×{size[1]} ≠ COCO {p.coco_size[0]}×{p.coco_size[1]}")
        else:
            p.fluoro_size = size
    if p.problems:
        return
    x, y, w, h = p.bbox_xywh
    W, H = p.xray_size
    x1, y1, x2, y2 = x, y, x + w, y + h
    if x1 < -1 or y1 < -1 or x2 > W + 1 or y2 > H + 1:
        p.problems.append(f"กรอบเกินภาพ ({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}) ภาพ {W}×{H}")
        return
    if x1 < 0 or y1 < 0 or x2 > W or y2 > H:
        p.notes.append("กรอบเกินขอบ ≤ 1 px — ตัดให้พอดีภาพ")
    p.box_xyxy = [round(max(0.0, x1), 2), round(max(0.0, y1), 2), round(min(float(W), x2), 2), round(min(float(H), y2), 2)]


# ------------------------------------------------------------------ สรุปสาเหตุรายเคส
CATEGORIES = [   # (รหัสคอลัมน์, ชื่อไทย, regex ของข้อความปัญหา)
    ("dup_fluo_id", "fluo_id ซ้ำ", r"ซ้ำ \d+ กรอบ"),
    ("suffix_rotate", "fluo_id มีคำต่อท้าย (rotate ฯลฯ)", r"คำต่อท้าย"),
    ("fluo_not_found", "หาภาพฟลูไม่เจอ", r"ไม่พบภาพฟลู|ไม่มี fluo_id"),
    ("loose_ambiguous", "หลวม แต่ตรงหลายภาพ", r"จับคู่หลวมได้|ตรงกับภาพฟลูหลายไฟล์"),
    ("fluo_reused", "ภาพฟลูถูกใช้หลายกรอบ", r"ถูกใช้โดย"),
    ("xray_not_found", "หาภาพเอกซเรย์ไม่เจอ", r"ไม่พบไฟล์เอกซเรย์|ชื่อเอกซเรย์ตรงกับหลายไฟล์|ไม่มี image"),
    ("size_mismatch", "ขนาดเอกซเรย์ไม่ตรง COCO", r"ขนาดเอกซเรย์จริง"),
    ("exif_orientation", "EXIF ให้หมุนภาพ", r"EXIF Orientation"),
    ("box_rotated", "กรอบหมุน", r"กรอบหมุน"),
    ("box_bad", "กรอบผิดรูป/เกินภาพ", r"bbox ผิดรูป|กรอบเกินภาพ"),
    ("image_error", "เปิดภาพไม่ได้/ชนิดไฟล์ผิด", r"เปิดภาพ|ชนิดไฟล์จริง"),
]


def categorize(problem: str) -> str:
    for code, _, rx in CATEGORIES:
        if re.search(rx, problem):
            return code
    return "other"


def summary_by_case(cases, all_pairs, ok_by_case, chosen):
    """นับกรอบที่ตัดออกแยกตามสาเหตุ (ใช้ปัญหาแรกของแต่ละกรอบ) แยกรายเคส"""
    rows = []
    for c in cases:
        ps = [p for p in all_pairs if p.case == c]
        row = {"case": c, "boxes": len(ps), "ok": len(ok_by_case.get(c, []))}
        cnt = Counter(categorize(p.problems[0]) for p in ps if p.problems)
        for code, _, _ in CATEGORIES:
            row[code] = cnt.get(code, 0)
        row["other"] = cnt.get("other", 0)
        row["excluded"] = sum(1 for p in ps if p.problems)
        row["loose_used"] = sum(1 for p in ps if p.ok and p.match == "loose_digits")
        row["selected"] = sum(1 for p in chosen if p.case == c)
        row["selected_loose"] = sum(1 for p in chosen if p.case == c and p.match == "loose_digits")
        rows.append(row)
    return rows


# ------------------------------------------------------------------ เลือก/สับ/งานซ้ำ
def plan_tasks(pairs_ok: dict[str, list[Pair]], k: int, seed: int, repeat_frac: float, min_gap: int):
    rnd = random.Random(seed)
    chosen = []
    for case in sorted(pairs_ok):
        pool = sorted(pairs_ok[case], key=lambda p: p.ann_id)
        chosen += pool if len(pool) <= k else rnd.sample(pool, k)
    order = chosen[:]
    rnd.shuffle(order)
    entries = [{"pair": p, "repeat_of": None} for p in order]
    n_rep = round(repeat_frac * len(order))
    if n_rep:
        originals = order[:]
        rnd.shuffle(originals)
        added = 0
        for o in originals:
            if added >= n_rep:
                break
            pos = next(i for i, e in enumerate(entries) if e["pair"] is o and e["repeat_of"] is None)
            lo = pos + min_gap + 1
            if lo > len(entries):
                continue
            ins = rnd.randint(lo, len(entries))
            entries.insert(ins, {"pair": o, "repeat_of": o})
            added += 1
        if added < n_rep:
            print(f"คำเตือน: ใส่งานซ้ำได้ {added}/{n_rep} (ระยะห่าง ≥ {min_gap} งาน)")
    # ตั้งรหัส T001...
    width = max(3, len(str(len(entries))))
    first_task = {}
    for i, e in enumerate(entries, 1):
        e["task_id"] = f"T{i:0{width}d}"
        if e["repeat_of"] is None:
            first_task[id(e["pair"])] = e["task_id"]
    for e in entries:
        e["is_repeat_of"] = first_task[id(e["pair"])] if e["repeat_of"] is not None else None
    # ตรวจระยะห่างงานซ้ำ
    idx = {e["task_id"]: i for i, e in enumerate(entries)}
    for e in entries:
        if e["is_repeat_of"]:
            assert idx[e["task_id"]] - idx[e["is_repeat_of"]] > min_gap, "ระยะห่างงานซ้ำไม่พอ"
    return chosen, entries


# ------------------------------------------------------------------ เขียนผล
def safe_out(path: Path, data_root: Path) -> Path:
    path = path.resolve()
    dr = data_root.resolve()
    if path == dr or dr in path.parents:
        sys.exit(f"หยุด: ปลายทาง {path} อยู่ในโฟลเดอร์ข้อมูลจริง — ห้ามเขียน")
    if PROJECT not in path.parents and path != PROJECT:
        sys.exit(f"หยุด: ปลายทาง {path} อยู่นอกโปรเจกต์ {PROJECT}")
    return path


def gitignored(path: Path) -> bool:
    """path (ในโปรเจกต์) หรือโฟลเดอร์แม่ของมัน ตรงกับรูปแบบใน .gitignore (เทียบแบบง่าย: ชื่อตรง / *_xxx / โฟลเดอร์)"""
    import fnmatch
    gi = (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
    pats = [l.strip().rstrip("/").lstrip("*").lstrip("/") if l.strip().startswith("**/") else l.strip().rstrip("/")
            for l in gi if l.strip() and not l.strip().startswith("#")]
    rel = path.resolve().relative_to(PROJECT).as_posix()
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return any(fnmatch.fnmatch(pref, pat) or fnmatch.fnmatch(pref.split("/")[-1], pat) for pref in prefixes for pat in pats)


def get_font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_check_image(task_id: str, x_bytes: bytes, f_bytes: bytes, box, out: Path, repeat_of=None, loose=None):
    H = 600
    with Image.open(io.BytesIO(x_bytes)) as xi:
        xi = xi.convert("RGB")
        sx = H / xi.height
        xs = xi.resize((max(1, round(xi.width * sx)), H))
    d = ImageDraw.Draw(xs)
    b = [v * sx for v in box]
    for o in range(3):
        d.rectangle([b[0] - o, b[1] - o, b[2] + o, b[3] + o], outline=(0, 229, 255))
    with Image.open(io.BytesIO(f_bytes)) as fi:
        fi = fi.convert("RGB")
        sf = H / fi.height
        fs = fi.resize((max(1, round(fi.width * sf)), H))
    pad = 12
    canvas = Image.new("RGB", (xs.width + fs.width + pad * 3, H + 50), (25, 25, 25))
    canvas.paste(xs, (pad, 40))
    canvas.paste(fs, (xs.width + pad * 2, 40))
    title = f"{task_id}  (repeat of {repeat_of})" if repeat_of else task_id   # ฟอนต์ในตัวไม่มีอักษรไทย
    dr = ImageDraw.Draw(canvas)
    dr.text((pad, 8), title + "    left: X-ray + box_xyxy    right: fluoro", fill=(255, 255, 255), font=get_font(22))
    if loose:
        dr.rectangle([0, 0, canvas.width - 1, canvas.height - 1], outline=(255, 170, 0), width=6)
        dr.text((max(pad, canvas.width - 560), 8), f"LOOSE fluo_id match: '{loose}' - CHECK BY EYE",
                fill=(255, 170, 0), font=get_font(22))
    canvas.save(out, "JPEG", quality=85)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", type=Path, default=None, help="โฟลเดอร์ข้อมูล (ไม่ใส่ = อ่านจาก tools/data_root.txt)")
    ap.add_argument("--cases", default="", help="รายชื่อเคส (ชื่อโฟลเดอร์) คั่นด้วย , เช่น เคสตัวอย่าง1,เคสตัวอย่าง2")
    ap.add_argument("--cases-file", type=Path, help="ไฟล์รายชื่อเคส บรรทัดละ 1 เคส")
    ap.add_argument("--splits", type=Path, help="splits.csv (case_id,split) — ใช้เคสในชุด --split และต้องผ่าน check_splits")
    ap.add_argument("--split", default="test", help="ชุดที่ใช้จาก --splits (ค่าเริ่ม test)")
    ap.add_argument("--expect", default="", help="จำนวนเคสต่อชุดที่คาด ส่งต่อให้ check_splits เช่น test=70")
    ap.add_argument("--k", type=int, default=3, help="จำนวนคู่ต่อเคส (ค่าเริ่ม 3)")
    ap.add_argument("--seed", type=int, default=2569)
    ap.add_argument("--repeat-frac", type=float, default=0.10, help="สัดส่วนงานซ้ำ (ค่าเริ่ม 0.10)")
    ap.add_argument("--min-gap", type=int, default=30, help="งานซ้ำต้องห่างงานต้นฉบับอย่างน้อยกี่งาน")
    ap.add_argument("--name", default="study", help="ชื่อชุด: study -> study_package/ key.csv ...")
    ap.add_argument("--pilot", action="store_true", help="โหมดทดลอง: ชื่อชุด pilot, ไม่มีงานซ้ำ, k เริ่ม 2")
    ap.add_argument("--write", action="store_true", help="สร้างไฟล์จริง (ไม่ใส่ = dry-run)")
    ap.add_argument("--overwrite", action="store_true", help="ลบผลเดิมของชุดนี้แล้วสร้างใหม่")
    ap.add_argument("--out-root", type=Path, default=PROJECT, help="โฟลเดอร์ที่จะเขียนผล (ต้องอยู่ในโปรเจกต์และอยู่ใน .gitignore)")
    args = ap.parse_args()
    args.data_root = require_data_root(args.data_root)

    if args.pilot:
        args.name = "pilot"
        args.repeat_frac = 0.0
        if "--k" not in sys.argv:
            args.k = 2
    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    if args.cases_file:
        cases += [l.strip() for l in args.cases_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    if args.splits:
        from check_splits import parse_expect, validate
        info = validate(args.splits, args.data_root, parse_expect(args.expect))
        if info["errors"]:
            for e in info["errors"]:
                print(f"ERROR  {e}")
            sys.exit("หยุด: splits.csv ไม่ผ่านการตรวจ (ดูรายละเอียด: python -I -X utf8 -B tools/check_splits.py)")
        for w in info["warns"]:
            print(f"WARN   {w}")
        picked = sorted(c for c, s in info["split_of"].items() if s == args.split)
        if not picked:
            sys.exit(f"หยุด: ไม่มีเคสในชุด {args.split}")
        print(f"ใช้ {len(picked)} เคสจากชุด {args.split} ใน {args.splits.name}")
        cases += picked
    cases = list(dict.fromkeys(cases))
    if not cases:
        sys.exit("ต้องระบุ --splits หรือ --cases หรือ --cases-file")

    name = args.name
    root = safe_out(args.out_root, args.data_root)
    pkg_dir = safe_out(root / f"{name}_package", args.data_root)
    key_csv = safe_out(root / ("key.csv" if name == "study" else f"{name}_key.csv"), args.data_root)
    report_csv = safe_out(root / f"{name}_report.csv", args.data_root)
    check_dir = safe_out(root / f"{name}_check", args.data_root)
    summary_csv = safe_out(root / f"{name}_summary_by_case.csv", args.data_root)
    for pth in (pkg_dir, key_csv, report_csv, check_dir, summary_csv):
        if not gitignored(pth):
            sys.exit(f"หยุด: {pth.relative_to(PROJECT)} ยังไม่อยู่ใน .gitignore — เพิ่มก่อนสร้าง")

    # ---------- อ่าน + ตรวจ (อ่านอย่างเดียว)
    all_pairs = []
    for cd in find_case_dirs(args.data_root, cases):
        ps = collect_pairs(cd)
        for p in ps:
            check_images(p)
        all_pairs += ps
    ok_by_case = defaultdict(list)
    for p in all_pairs:
        if p.ok:
            ok_by_case[p.case].append(p)
    chosen, entries = plan_tasks(ok_by_case, args.k, args.seed, args.repeat_frac, args.min_gap)
    date = datetime.now().strftime("%Y%m%d")
    package_id = f"pkg-{name}-{date}"

    # ---------- สรุป
    reasons = Counter()
    for p in all_pairs:
        for pr in p.problems:
            reasons[re.sub(r"\b(IMG_\S+|\d+(\.\d+)?)", "…", pr)] += 1
    notes = Counter(re.sub(r"'[^']*'|IMG_\S+", "…", n) for p in all_pairs for n in p.notes)
    print("=" * 70)
    print(f"โหมด: {'pilot (ทดลอง)' if args.pilot else name} · {'สร้างจริง' if args.write else 'DRY-RUN (ยังไม่เขียนอะไร)'}")
    print(f"อ่านจาก (อ่านอย่างเดียว): {args.data_root}")
    print(f"เคส {len(cases)} · กรอบทั้งหมด {len(all_pairs)} · ผ่านตรวจ {sum(p.ok for p in all_pairs)} · ไม่ผ่าน {sum(not p.ok for p in all_pairs)}")
    for r, n in reasons.most_common():
        print(f"   ไม่ผ่าน {n:4d} × {r}")
    for r, n in notes.most_common():
        print(f"   หมายเหตุ {n:3d} × {r}")
    print(f"สุ่ม k={args.k} คู่/เคส seed={args.seed} → คู่ {len(chosen)} · งานซ้ำ {sum(1 for e in entries if e['is_repeat_of'])} · รวม {len(entries)} งาน")
    summ = summary_by_case(cases, all_pairs, ok_by_case, chosen)
    cols = [code for code, _, _ in CATEGORIES if any(r[code] for r in summ)] + (["other"] if any(r["other"] for r in summ) else [])
    th = {code: name for code, name, _ in CATEGORIES}
    print("รายเคส: ตัดออกแยกตามสาเหตุ · หลวมใช้ = จับคู่หลวมที่ผ่านตรวจ · เลือก(หลวม) = งานที่เลือก (ในนั้นจับคู่หลวม)")
    for code in cols:
        print(f"   {code} = {th.get(code, 'อื่น ๆ')}")
    head = f"{'เคส':<12}{'กรอบ':>6}{'ผ่าน':>6}" + "".join(f"{c:>18}" for c in cols) + f"{'หลวมใช้':>9}{'เลือก(หลวม)':>13}"
    print(head)

    def line(label, r):
        sel = f"{r['selected']}({r['selected_loose']})"
        return f"{label:<12}{r['boxes']:>6}{r['ok']:>6}" + "".join(f"{r[c]:>18}" for c in cols) + f"{r['loose_used']:>9}{sel:>13}"
    for r in summ:
        print(line(r["case"], r) + ("  ← ได้น้อยกว่า k" if r["selected"] < args.k else ""))
    if len(summ) > 1:
        print(line("รวม", {k: sum(r[k] for r in summ) for k in summ[0] if k != "case"}))
    print(f"package_id: {package_id}")
    print("จะเขียน (ในโปรเจกต์ ทั้งหมดอยู่ใน .gitignore):")
    print(f"   {pkg_dir}\\  (manifest.json + {2 * len(entries)} ภาพ)")
    print(f"   {key_csv}  (ตารางจับคู่รหัส — เก็บกับทีมเท่านั้น ห้ามส่งให้แพทย์)")
    print(f"   {report_csv}  (ผลตรวจทุกกรอบ)")
    print(f"   {check_dir}\\  ({len(entries)} ภาพตรวจ · งานจับคู่หลวมมี _LOOSE ท้ายชื่อ)")
    print(f"   {summary_csv}  (สรุปสาเหตุที่ตัดออก แยกรายเคส)")
    existing = [p for p in (pkg_dir, key_csv, report_csv, check_dir, summary_csv) if p.exists()]
    if existing:
        print(f"มีผลเดิมอยู่แล้ว: {[e.name for e in existing]}" + ("" if args.overwrite else " — ต้องใส่ --overwrite ถึงจะสร้างทับ"))
    print("=" * 70)
    if not args.write:
        print("dry-run: ยังไม่ได้เขียนอะไร · ถ้าถูกต้อง รันคำสั่งเดิมเพิ่ม --write")
        return
    if existing and not args.overwrite:
        sys.exit("หยุด: มีผลเดิมอยู่แล้ว")

    # ---------- เขียน
    import shutil
    for p in existing:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    pkg_dir.mkdir(parents=True)
    check_dir.mkdir(parents=True)
    items, key_rows = [], []
    cache = {}
    for e in entries:
        p, tid = e["pair"], e["task_id"]
        out = {}
        for side, src, suffix, size in (("xray", p.xray_path, "X", p.xray_size), ("fluoro", p.fluoro_path, "F", p.fluoro_size)):
            if src not in cache:
                raw = src.read_bytes()                        # อ่านอย่างเดียว
                ext = src.suffix.lower()
                clean = strip_metadata(raw, ext)
                s0, h0 = pixels_digest(raw)
                s1, h1 = pixels_digest(clean)
                if s0 != s1 or h0 != h1 or tuple(s1) != tuple(size):
                    sys.exit(f"หยุด: ลบ EXIF แล้วภาพเปลี่ยน ({p.case} {side}) — ไม่สร้างแพ็กเกจ")
                with Image.open(io.BytesIO(clean)) as im:
                    if exif_orientation(im) not in (None, 1) or len(im.getexif()):
                        sys.exit(f"หยุด: ลบ EXIF ไม่หมด ({p.case} {side})")
                cache[src] = (clean, ext, hashlib.sha256(raw).hexdigest(), hashlib.sha256(clean).hexdigest())
            clean, ext, sha_src, sha_out = cache[src]
            fname = f"{tid}_{suffix}{'.jpg' if ext == '.jpeg' else ext}"
            (pkg_dir / fname).write_bytes(clean)
            out[side] = (fname, sha_src, sha_out, src)
        items.append({
            "task_id": tid, "xray": out["xray"][0], "fluoro": out["fluoro"][0],
            "xray_size": list(p.xray_size), "fluoro_size": list(p.fluoro_size),
            "box_xyxy": p.box_xyxy, "is_repeat_of": e["is_repeat_of"],
        })
        key_rows.append({
            "task_id": tid, "case": p.case, "annotation_id": p.ann_id, "image_id": p.image_id,
            "xray_file": out["xray"][3].name, "fluoro_file": out["fluoro"][3].name, "fluo_id": p.fluo_id,
            "fluo_match": p.match, "box_xyxy": json.dumps(p.box_xyxy), "is_repeat_of": e["is_repeat_of"] or "",
            "xray_sha256_source": out["xray"][1], "fluoro_sha256_source": out["fluoro"][1],
            "xray_sha256_package": out["xray"][2], "fluoro_sha256_package": out["fluoro"][2],
            "notes": "; ".join(p.notes),
        })
        loose = p.fluo_id if p.match == "loose_digits" else None
        make_check_image(tid, cache[p.xray_path][0], cache[p.fluoro_path][0], p.box_xyxy,
                         check_dir / f"{tid}{'_LOOSE' if loose else ''}.jpg", e["is_repeat_of"], loose)
    manifest = {"package_id": package_id, "seed": args.seed, "k": args.k,
                "repeat_frac": args.repeat_frac, "min_gap": args.min_gap,
                "created_at": datetime.now().isoformat(timespec="seconds"), "items": items}
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with key_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key_rows[0].keys()))
        w.writeheader()
        w.writerows(key_rows)
    with report_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["case", "annotation_id", "image_id", "xray_file_coco", "fluo_id", "fluo_match", "status", "category", "problems", "notes", "chosen_task"])
        chosen_task = {}
        for e in entries:
            chosen_task.setdefault(id(e["pair"]), e["task_id"])
        for p in all_pairs:
            w.writerow([p.case, p.ann_id, p.image_id, p.xray_name_coco, p.fluo_id, p.match,
                        "ok" if p.ok else "excluded", categorize(p.problems[0]) if p.problems else "",
                        "; ".join(p.problems), "; ".join(p.notes), chosen_task.get(id(p), "")])
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)
    print(f"สร้างแล้ว: {len(items)} งาน · {pkg_dir}")
    print("ภาพตรวจ: เปิดโฟลเดอร์", check_dir)


if __name__ == "__main__":
    main()
