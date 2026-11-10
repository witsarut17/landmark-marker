"""ตรวจไฟล์แบ่งชุดข้อมูล splits.csv ก่อนสร้างแพ็กเกจจริง (อ่านอย่างเดียว ไม่เขียนอะไร)

วิธีใช้:
    python -I -X utf8 -B tools/check_splits.py                  # อ่าน splits.csv ที่รากโปรเจกต์
    python -I -X utf8 -B tools/check_splits.py path/to/splits.csv

รูปแบบไฟล์ (UTF-8, มีหัวคอลัมน์):
    case_id,split
    <รหัสเคส>,train | val | test

ตรวจ (ERROR = ห้ามใช้สร้างแพ็กเกจ · WARN = ให้คนตัดสินใจ):
  - มีคอลัมน์ case_id และ split · split เป็น train / val / test เท่านั้น · รหัสเคสไม่ซ้ำ ไม่ว่าง
  - ครบทุกเคสในโฟลเดอร์ข้อมูล และไม่มีเคสที่ไม่มีในโฟลเดอร์ข้อมูล
  - จำนวนต่อชุดตรงที่คาด (ค่าเริ่ม train=169 val=30 test=70; test ไม่ตรง = ERROR, ชุดอื่น = WARN)
  - ไม่มีข้อมูลส่วนตัว: คอลัมน์อื่นนอกจาก case_id/split = WARN · ตัวอักษรไทยหรือรูปแบบ HN ในไฟล์ = ERROR
  - เคสที่สงสัยว่าเป็นผู้ป่วยคนเดียวกัน (ไฟล์ tools/same_patient_groups.txt) ต้องอยู่ชุดเดียวกัน
  - ทุกเคสในชุด test มี instances_clean.json และมีกรอบอย่างน้อย 1 กรอบ (ใช้ instances_clean.json เท่านั้น)
ไฟล์ splits.csv และ same_patient_groups.txt มีรหัสเคส → อยู่ใน .gitignore ไม่ขึ้น git
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import require_data_root  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_SPLITS = PROJECT / "splits.csv"
GROUPS_FILE = Path(__file__).with_name("same_patient_groups.txt")
SPLITS = ("train", "val", "test")
DEFAULT_EXPECT = {"train": 169, "val": 30, "test": 70}
THAI = re.compile(r"[฀-๿]")
HN = re.compile(r"\bHN\s*[:：]?\s*\d{4,}", re.I)


def read_splits(path: Path) -> tuple[dict[str, str], list[str], list[str]]:
    """คืน (case -> split, errors, warns) · ไม่พิมพ์ค่าในคอลัมน์อื่น (อาจเป็นข้อมูลส่วนตัว)"""
    errors, warns = [], []
    if not path.is_file():
        return {}, [f"ไม่พบไฟล์ {path}"], []
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}, ["ไฟล์ไม่ใช่ UTF-8 (ใน Excel ให้ บันทึกเป็น → CSV UTF-8)"], []
    if THAI.search(text):
        errors.append("มีตัวอักษรไทยในไฟล์ (อาจเป็นชื่อผู้ป่วย) — ควรมีแค่รหัสเคสและชื่อชุด")
    if HN.search(text):
        errors.append("มีรูปแบบคล้าย HN + เลข ในไฟล์")
    rows = list(csv.reader(text.splitlines()))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return {}, errors + ["ไฟล์ว่าง"], warns
    header = [h.strip().lower() for h in rows[0]]
    if "case_id" not in header or "split" not in header:
        return {}, errors + [f"หัวคอลัมน์ต้องมี case_id และ split (เจอ {len(header)} คอลัมน์)"], warns
    extra = [h for h in header if h not in ("case_id", "split")]
    if extra:
        warns.append(f"มีคอลัมน์อื่น {extra} — ตรวจว่าไม่ใช่ข้อมูลส่วนตัว (แนะนำให้มีแค่ case_id,split)")
    ic, is_ = header.index("case_id"), header.index("split")
    out, dup = {}, []
    for n, r in enumerate(rows[1:], start=2):
        case = r[ic].strip() if ic < len(r) else ""
        split = (r[is_].strip().lower() if is_ < len(r) else "")
        if not case:
            errors.append(f"แถว {n}: case_id ว่าง")
            continue
        if split not in SPLITS:
            errors.append(f"แถว {n} ({case}): split '{split}' ไม่ใช่ train/val/test")
            continue
        if case in out:
            dup.append(case)
            continue
        out[case] = split
    if dup:
        errors.append(f"case_id ซ้ำ {len(dup)} เคส: {', '.join(sorted(set(dup))[:10])}")
    return out, errors, warns


def read_groups(path: Path = GROUPS_FILE) -> list[list[str]]:
    """บรรทัดละกลุ่ม คั่นด้วย , หรือช่องว่าง · # = หมายเหตุ"""
    if not path.is_file():
        return []
    groups = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        ids = [x for x in re.split(r"[,\s]+", line) if x]
        if len(ids) >= 2:
            groups.append(ids)
    return groups


def data_cases(data_root: Path) -> dict[str, Path]:
    return {p.parent.name: p for p in sorted(data_root.glob("*/instances_clean.json"))}


def count_boxes(json_path: Path) -> int:
    d = json.loads(json_path.read_text(encoding="utf-8"))
    return len(d.get("annotations") or [])


def validate(splits_path: Path, data_root: Path, expect: dict[str, int], groups_path: Path = GROUPS_FILE) -> dict:
    split_of, errors, warns = read_splits(splits_path)
    info = {"split_of": split_of, "errors": errors, "warns": warns, "counts": Counter(split_of.values()),
            "test_boxes": {}, "groups": []}
    if not split_of:
        return info
    have = data_cases(data_root)
    missing_in_csv = sorted(set(have) - set(split_of))
    not_in_data = sorted(set(split_of) - set(have))
    if missing_in_csv:
        errors.append(f"เคสในโฟลเดอร์ข้อมูลที่ไม่มีใน splits.csv {len(missing_in_csv)} เคส: {', '.join(missing_in_csv[:10])}")
    if not_in_data:
        errors.append(f"เคสใน splits.csv ที่ไม่มีในโฟลเดอร์ข้อมูล (หรือไม่มี instances_clean.json) {len(not_in_data)} เคส: "
                      f"{', '.join(not_in_data[:10])}")
    for s in SPLITS:
        got, want = info["counts"].get(s, 0), expect.get(s)
        if want is not None and got != want:
            (errors if s == "test" else warns).append(f"ชุด {s} มี {got} เคส (คาดไว้ {want})")
    groups = read_groups(groups_path)
    if not groups_path.is_file():
        warns.append(f"ไม่มีไฟล์ {groups_path.name} — ไม่ได้ตรวจเคสที่อาจเป็นผู้ป่วยคนเดียวกัน")
    for g in groups:
        where = {c: split_of.get(c, "ไม่มีในไฟล์") for c in g}
        ok = len(set(where.values())) == 1
        info["groups"].append((g, where, ok))
        if not ok:
            errors.append("เคสที่อาจเป็นผู้ป่วยคนเดียวกันอยู่คนละชุด: " + ", ".join(f"{c}={s}" for c, s in where.items()))
    for c, s in sorted(split_of.items()):
        if s == "test" and c in have:
            n = count_boxes(have[c])
            info["test_boxes"][c] = n
            if n == 0:
                errors.append(f"{c} (test): ไม่มีกรอบใน instances_clean.json")
    return info


def parse_expect(text: str) -> dict[str, int]:
    out = dict(DEFAULT_EXPECT)
    for part in filter(None, (x.strip() for x in text.split(","))):
        k, _, v = part.partition("=")
        out[k.strip()] = int(v)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("splits", type=Path, nargs="?", default=DEFAULT_SPLITS)
    ap.add_argument("--data-root", type=Path, default=None, help="โฟลเดอร์ข้อมูล (ไม่ใส่ = อ่านจาก tools/data_root.txt)")
    ap.add_argument("--expect", default="", help="จำนวนที่คาด เช่น train=169,val=30,test=70")
    ap.add_argument("--groups", type=Path, default=GROUPS_FILE)
    ap.add_argument("--k", type=int, default=3, help="คู่ต่อเคสที่จะสุ่ม (ใช้แค่ประมาณจำนวนงาน)")
    args = ap.parse_args()
    data_root = require_data_root(args.data_root)
    print(f"อ่าน (อ่านอย่างเดียว): {args.splits.name} + instances_clean.json ในโฟลเดอร์ข้อมูล")

    info = validate(args.splits, data_root, parse_expect(args.expect), args.groups)
    c = info["counts"]
    print(f"เคสทั้งหมด {sum(c.values())} · train {c.get('train', 0)} · val {c.get('val', 0)} · test {c.get('test', 0)}")
    for g, where, ok in info["groups"]:
        print(f"  กลุ่มผู้ป่วยเดียวกัน(สงสัย) {'/'.join(g)}: {'อยู่ชุดเดียวกัน ✓' if ok else 'คนละชุด ✗'} ({', '.join(sorted(set(where.values())))})")
    tb = info["test_boxes"]
    if tb:
        vals = sorted(tb.values())
        few = [k for k, v in tb.items() if v < args.k]
        print(f"ชุด test: กรอบรวม {sum(vals)} (ก่อนตรวจคุณภาพ) · ต่อเคส น้อยสุด {vals[0]} มากสุด {vals[-1]}"
              f" · เคสที่มีกรอบ < {args.k}: {len(few)}" + (f" ({', '.join(sorted(few))})" if few else ""))
        est = sum(min(v, args.k) for v in vals)
        print(f"ประมาณงาน (k={args.k}): ≤ {est} + งานซ้ำ 10% ≈ {est + round(est * 0.10)} (ตัวเลขจริงดูจาก make_study_package dry-run)")
    for e in info["errors"]:
        print(f"ERROR  {e}")
    for w in info["warns"]:
        print(f"WARN   {w}")
    if not info["errors"]:
        print("ไม่พบ ERROR — ใช้สร้างแพ็กเกจได้: python -I -X utf8 -B tools/make_study_package.py --splits splits.csv --k 3")
    sys.exit(1 if info["errors"] else 0)


if __name__ == "__main__":
    main()
