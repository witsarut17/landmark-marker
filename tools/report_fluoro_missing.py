"""หาเคสที่ใช้ภาพฟลูไม่ได้เลย (อ่านอย่างเดียว: ชื่อไฟล์ + instances_clean.json · ไม่เปิดภาพ)

วิธีใช้:
    python -I -X utf8 -B tools/report_fluoro_missing.py            # ทุกเคสในโฟลเดอร์ข้อมูล + ชุดจาก splits.csv
    python -I -X utf8 -B tools/report_fluoro_missing.py --all-rows # เขียนทุกเคสลง CSV (ไม่ใช่เฉพาะเคสที่มีปัญหา)

สาเหตุ (เคสที่ไม่มีกรอบไหนจับคู่ภาพฟลูได้เลย ตามกติกาเดียวกับ make_study_package):
  no_folder      ไม่มีโฟลเดอร์ fluoroscopy
  empty_folder   มีโฟลเดอร์แต่ไม่มีไฟล์ภาพ (นับไฟล์อื่นแยกไว้)
  name_mismatch  มีไฟล์ภาพ แต่ชื่อไม่ตรง fluo_id ของกรอบไหนเลย
ผล: fluoro_missing_report.csv ที่รากโปรเจกต์ (มีรหัสเคส → อยู่ใน .gitignore)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import require_data_root  # noqa: E402
from make_study_package import IMG_EXT, PROJECT, SUFFIXED, gitignored, match_fluo  # noqa: E402
from check_splits import DEFAULT_SPLITS, read_splits  # noqa: E402

OUT = PROJECT / "fluoro_missing_report.csv"
CAUSE_TH = {"shortcut": "fluoroscopy เป็นทางลัด (ไม่ใช่โฟลเดอร์จริง)", "no_folder": "ไม่มีโฟลเดอร์ fluoroscopy",
            "empty_folder": "มีโฟลเดอร์แต่ว่าง", "name_mismatch": "มีไฟล์แต่ชื่อไม่ตรง fluo_id"}
SHORTCUT_EXT = {".lnk", ".gshortcut", ".url"}


def find_shortcuts(case_dir: Path) -> list[str]:
    """ทางลัดทุกแบบในเคส (ไม่ตามเข้าไปในทางลัด): ไฟล์ .lnk/.gshortcut/.url, symlink, junction · คืนเป็น path สัมพัทธ์"""
    found = []
    for dirpath, dirnames, filenames in os.walk(case_dir, followlinks=False):
        base = Path(dirpath)
        for name in dirnames + filenames:
            q = base / name
            is_junction = getattr(os.path, "isjunction", lambda _p: False)(q)
            if q.is_symlink() or is_junction or q.suffix.lower() in SHORTCUT_EXT:
                found.append(q.relative_to(case_dir).as_posix())
        dirnames[:] = [n for n in dirnames if not ((base / n).is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(base / n))]
    return sorted(found)


def inspect_case(case_dir: Path) -> dict:
    d = json.loads((case_dir / "instances_clean.json").read_text(encoding="utf-8"))
    fids = [str((a.get("attributes") or {}).get("fluo_id", "")).strip() for a in d.get("annotations", [])]
    fd = case_dir / "fluoroscopy"
    shortcuts = find_shortcuts(case_dir)
    fluoro_link = fd.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(fd) or any(
        "/" not in s and s.lower().startswith("fluoroscopy") and Path(s).suffix.lower() in SHORTCUT_EXT for s in shortcuts)
    files = [p for p in fd.iterdir() if p.is_file() and p.name.lower() != "desktop.ini"] if fd.is_dir() and not fluoro_link else []
    imgs = [p for p in files if p.suffix.lower() in IMG_EXT]
    other = Counter(p.suffix.lower() or "(ไม่มีนามสกุล)" for p in files if p.suffix.lower() not in IMG_EXT)
    matched = sum(1 for f in fids if f and match_fluo(f, imgs)[0] is not None)
    if fluoro_link:
        cause = "shortcut"
    elif not fd.is_dir():
        cause = "no_folder"
    elif not imgs:
        cause = "empty_folder"
    elif matched == 0:
        cause = "name_mismatch"
    else:
        cause = ""
    return {"case": case_dir.name, "boxes": len(fids), "fluoro_images": len(imgs),
            "image_types": " ".join(f"{k}:{v}" for k, v in sorted(Counter(p.suffix.lower() for p in imgs).items())),
            "other_files": " ".join(f"{k}:{v}" for k, v in sorted(other.items())),
            "boxes_matched": matched, "boxes_with_suffix": sum(1 for f in fids if SUFFIXED.fullmatch(f)),
            "shortcuts": " ".join(shortcuts), "cause": cause}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--splits", type=Path, default=DEFAULT_SPLITS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--all-rows", action="store_true")
    args = ap.parse_args()
    root = require_data_root(args.data_root)
    out = args.out.resolve()
    if root.resolve() in out.parents or not gitignored(out):
        sys.exit(f"หยุด: {out} ต้องอยู่นอกโฟลเดอร์ข้อมูลและอยู่ใน .gitignore")
    split_of = read_splits(args.splits)[0] if args.splits.is_file() else {}

    rows = []
    for j in sorted(root.glob("*/instances_clean.json")):
        r = inspect_case(j.parent)
        r["split"] = split_of.get(r["case"], "?")
        rows.append(r)
    bad = [r for r in rows if r["cause"]]
    linked = [r for r in rows if r["shortcuts"]]
    print(f"ทางลัด (shortcut/symlink/junction) ในเคส: {len(linked)} เคส" + ("" if linked else " — ไม่พบ"))
    for r in linked:
        print(f"    {r['case']:<12} [{r['split']}] {r['shortcuts']}")
    print(f"อ่าน (อ่านอย่างเดียว): {len(rows)} เคส · ใช้ภาพฟลูไม่ได้เลย {len(bad)} เคส")
    for cause, th in CAUSE_TH.items():
        rs = [r for r in bad if r["cause"] == cause]
        if rs:
            print(f"  {th}: {len(rs)} เคส (test {sum(r['split'] == 'test' for r in rs)})")
            for r in rs:
                extra = f" · ภาพ {r['fluoro_images']} ({r['image_types']})" if r["fluoro_images"] else ""
                extra += f" · ไฟล์อื่น {r['other_files']}" if r["other_files"] else ""
                extra += f" · fluo_id มีคำต่อท้าย {r['boxes_with_suffix']}/{r['boxes']}" if r["boxes_with_suffix"] else ""
                print(f"    {r['case']:<12} [{r['split']}] กรอบ {r['boxes']}{extra}")
    print(f"รวมชุด test: {sum(r['split'] == 'test' for r in bad)} เคส")
    cols = ["case", "split", "cause", "cause_th", "boxes", "boxes_matched", "boxes_with_suffix", "shortcuts", "fluoro_images", "image_types", "other_files"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in (rows if args.all_rows else [r for r in rows if r["cause"] or r["shortcuts"]]):
            w.writerow({**{k: r[k] for k in cols if k in r}, "cause_th": CAUSE_TH.get(r["cause"], "")})
    print(f"เขียน {out.name} แล้ว (อยู่ใน .gitignore)")


if __name__ == "__main__":
    main()
