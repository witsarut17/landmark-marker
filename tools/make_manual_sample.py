"""แพ็กเกจตัวอย่างภาพจริงขนาดเล็กสำหรับคู่มือ (เฉพาะเคสชุด train — ห้ามใช้ชุด test)

อ่านข้อมูลจริงแบบอ่านอย่างเดียว · เขียนเฉพาะใน manual_out/ (อยู่ใน .gitignore)
  T001, T002 = เคสหลัก (--case) จำนวน 2 คู่ (ปกติ)
  T003       = 1 คู่ที่ fluo_flag = flip จากเคส train (ไม่ใช้เคสที่อาจเป็นผู้ป่วยคนเดียวกับเคสหลัก)
ผล: manual_out/sample_package/ (manifest + ภาพ) · manual_out/sample_key.csv (ทีมเท่านั้น) · manual_out/sample_check/ (ภาพตรวจ)

วิธีใช้:  .venv\\Scripts\\python -I -X utf8 -B tools/make_manual_sample.py --case <รหัสเคสชุด train>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_study_package as M  # noqa: E402
from check_splits import DEFAULT_SPLITS, read_groups, read_splits  # noqa: E402
from local_paths import require_data_root  # noqa: E402

OUT = M.PROJECT / "manual_out"
PKG = OUT / "sample_package"
KEY = OUT / "sample_key.csv"
CHECK = OUT / "sample_check"
SEED = 2569


def ok_pairs(case_dir: Path, want_flag: str | None):
    ps = [p for p in M.collect_pairs(case_dir) if p.ok and (want_flag is None or p.flag == want_flag)]
    for p in ps:
        M.check_images(p)
    return sorted((p for p in ps if p.ok), key=lambda p: p.ann_id)


def write_image(src: Path, size, dest_stem: Path):
    raw = src.read_bytes()
    ext = src.suffix.lower()
    if ext == ".bmp":
        clean, ext = M.bmp_to_png(raw), ".png"
    else:
        clean = M.strip_metadata(raw, ext)
    if M.pixels_digest(raw) != M.pixels_digest(clean) or tuple(M.pixels_digest(clean)[0]) != tuple(size):
        sys.exit(f"หยุด: พิกเซลเปลี่ยนหลังลบ metadata ({src.name})")
    name = dest_stem.name + (".jpg" if ext == ".jpeg" else ext)
    (dest_stem.parent / name).write_bytes(clean)
    return name, clean, hashlib.sha256(raw).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", required=True, help="เคสหลัก (ต้องอยู่ชุด train)")
    MAIN_CASE = ap.parse_args().case
    root = require_data_root(None)
    split = read_splits(DEFAULT_SPLITS)[0]
    if split.get(MAIN_CASE) != "train":
        sys.exit(f"หยุด: {MAIN_CASE} ไม่ได้อยู่ชุด train")
    for pth in (PKG, KEY, CHECK):
        M.safe_out(pth, root)
        if not M.gitignored(pth):
            sys.exit(f"หยุด: {pth} ต้องอยู่ใน .gitignore")

    rnd = random.Random(SEED)
    main_ok = ok_pairs(root / MAIN_CASE, None)
    chosen = [(p, "") for p in rnd.sample(main_ok, 2)]
    same_patient = {c for g in read_groups() if MAIN_CASE in g for c in g}
    for c in sorted(k for k, s in split.items() if s == "train" and k not in same_patient):
        flips = ok_pairs(root / c, "flip")
        if flips:
            chosen.append((rnd.choice(flips), "flip"))
            break
    else:
        print("ไม่พบคู่ flip ที่ใช้ได้ในชุด train — แพ็กเกจมีแค่ 2 งาน")

    for pth in (PKG, CHECK):
        if pth.exists():
            shutil.rmtree(pth)
        pth.mkdir(parents=True)
    items, rows = [], []
    for i, (p, _) in enumerate(chosen, 1):
        tid = f"T{i:03d}"
        xn, xb, xs = write_image(p.xray_path, p.xray_size, PKG / f"{tid}_X")
        fn, fb, fs = write_image(p.fluoro_path, p.fluoro_size, PKG / f"{tid}_F")
        items.append({"task_id": tid, "xray": xn, "fluoro": fn, "xray_size": list(p.xray_size),
                      "fluoro_size": list(p.fluoro_size), "box_xyxy": p.box_xyxy, "is_repeat_of": None})
        rows.append({"task_id": tid, "case": p.case, "split": split.get(p.case), "annotation_id": p.ann_id,
                     "xray_file": p.xray_path.name, "fluoro_file": p.fluoro_path.name, "fluo_id": p.fluo_id,
                     "fluo_match": p.match, "fluo_flag": p.flag, "box_xyxy": json.dumps(p.box_xyxy),
                     "xray_sha256_source": xs, "fluoro_sha256_source": fs})
        M.make_check_image(tid, xb, fb, p.box_xyxy, CHECK / f"{tid}.jpg", None, None)
    manifest = {"package_id": "pkg-manual-sample", "seed": SEED, "k": 0, "repeat_frac": 0, "min_gap": 0,
                "created_at": M.datetime.now().isoformat(timespec="seconds"), "items": items}
    (PKG / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with KEY.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['task_id']}: {r['case']} ({r['split']}) fluo_flag={r['fluo_flag'] or '-'}")
    print(f"สร้างแล้ว: {PKG} ({len(items)} งาน) · ภาพตรวจ {CHECK}")


if __name__ == "__main__":
    main()
