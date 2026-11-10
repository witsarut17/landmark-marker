"""ตรวจโครงสร้าง instances_clean.json ทุกราย (อ่านอย่างเดียว ไม่แก้ไฟล์ ไม่พิมพ์ชื่อไฟล์ภาพ)

ตอบคำถาม Q2: กรอบใน CVAT หมุนหรือไม่ (annotations[].attributes.rotation)

วิธีใช้:
    python tools/inspect_coco.py                       # ใช้ path จาก tools/data_root.txt
    python tools/inspect_coco.py "<โฟลเดอร์ข้อมูล>"
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import require_data_root  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_root", type=Path, nargs="?", help="โฟลเดอร์ข้อมูล (ไม่ใส่ = อ่านจาก tools/data_root.txt)")
    args = ap.parse_args()
    args.data_root = require_data_root(args.data_root)

    files = sorted(args.data_root.glob("case_*/instances_clean.json"))
    if not files:
        raise SystemExit(f"ไม่พบ case_*/instances_clean.json ใน {args.data_root}")

    n_img = n_ann = 0
    ann_keys, attr_keys, img_keys, cats = Counter(), Counter(), Counter(), Counter()
    rot_missing = rot_zero = 0
    rotated: list[tuple[str, object, float]] = []
    img_no_size = 0
    bad_bbox = 0

    for f in files:
        case = f.parent.name
        data = json.loads(f.read_text(encoding="utf-8"))
        cat_names = {c.get("id"): c.get("name") for c in data.get("categories", [])}
        for im in data.get("images", []):
            n_img += 1
            img_keys.update(im.keys())
            if not im.get("width") or not im.get("height"):
                img_no_size += 1
        for a in data.get("annotations", []):
            n_ann += 1
            ann_keys.update(a.keys())
            cats[cat_names.get(a.get("category_id"), a.get("category_id"))] += 1
            attrs = a.get("attributes") or {}
            attr_keys.update(attrs.keys())
            rot = attrs.get("rotation", a.get("rotation"))
            if rot is None:
                rot_missing += 1
            elif abs(float(rot)) < 1e-9:
                rot_zero += 1
            else:
                rotated.append((case, a.get("id"), float(rot)))
            bb = a.get("bbox")
            if not (isinstance(bb, list) and len(bb) == 4 and bb[2] > 0 and bb[3] > 0):
                bad_bbox += 1

    print(f"จำนวนราย (ไฟล์): {len(files)}")
    print(f"images ทั้งหมด: {n_img}   (ไม่มี width/height: {img_no_size})")
    print(f"annotations ทั้งหมด: {n_ann}   (bbox ผิดรูป: {bad_bbox})")
    print(f"คีย์ใน images[]: {dict(img_keys)}")
    print(f"คีย์ใน annotations[]: {dict(ann_keys)}")
    print(f"คีย์ใน attributes: {dict(attr_keys) or '(ไม่มี)'}")
    print(f"หมวดหมู่: {dict(cats)}")
    print("--- rotation ---")
    print(f"ไม่มีค่า rotation: {rot_missing}")
    print(f"rotation = 0     : {rot_zero}")
    print(f"rotation ≠ 0     : {len(rotated)}")
    if rotated:
        vals = [r for _, _, r in rotated]
        print(f"  ช่วงค่า: {min(vals):.2f} ถึง {max(vals):.2f} องศา")
        print("  ตัวอย่าง (ราย, annotation id, องศา):")
        for row in rotated[:20]:
            print("   ", row)
        print("=> ต้องเพิ่มช่อง rotation ใน manifest")
    else:
        print("=> ไม่มีกรอบหมุน ใช้ box_xyxy ได้")


if __name__ == "__main__":
    main()
