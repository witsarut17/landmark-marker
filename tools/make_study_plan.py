"""สร้างนิยามการศึกษา ทีมมาร์ก-หมอตรวจ (v1.3) จากแพ็กเกจต้นฉบับ + orig_key.csv — อ่านอย่างเดียว เขียนเฉพาะโฟลเดอร์ส่วนตัว

    .venv\\Scripts\\python -I -X utf8 -B tools/make_study_plan.py              # ค่าเริ่มต้นใช้ไฟล์ใน C:\\PelNav_private

ได้ใน --out (ค่าเริ่มต้น C:\\PelNav_private):
  study.json       เคส 1–70 (เลขใหม่ สุ่มลำดับด้วย seed) · ผู้มาร์กหลักต่อเคส · คู่วัดความตรงกันระหว่างผู้มาร์ก · ลำดับในรายการ
                   ไม่มีรหัสเคสจริง (ใช้กับ set-study บนเครื่องที่ใช้งาน · แนบไปกับ export-marks)
  study_key.csv    เลขเคสใหม่ ↔ เคสจริง และคู่วัดความตรงกัน — key ของทีม เก็บในโฟลเดอร์ส่วนตัวเท่านั้น ห้ามขึ้น GitHub
กติกา: ใช้เฉพาะงานที่ไม่ใช่งานซ้ำ (is_repeat_of ว่าง) · งานในเคสเรียงตาม task_id
  ผู้มาร์ก 2 คน: คนแรกได้เคส 1..ครึ่งแรก คนที่สองได้ครึ่งหลัง
  คู่วัดความตรงกัน: แต่ละคนได้ --extra คู่ จากเคสของอีกคน (เคสละ 1 คู่ สุ่ม) · เลขเคสพิเศษต่อจากเคสจริง (71–80, 81–90)
  แสดงปนในรายการของผู้มาร์ก (กระจายเท่า ๆ กัน) ไม่บอกว่าเป็นคู่ซ้ำ
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_originals import safe_out_dir  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from server.study import FORMAT, StudyError, validate_study  # noqa: E402


def interleave(own: list[int], extra: list[int]) -> list[int]:
    """แทรกเคสพิเศษกระจายเท่า ๆ กันในรายการเคสของตัวเอง"""
    out, k = list(own), len(extra)
    for j, e in enumerate(extra):
        pos = round((j + 1) * len(own) / (k + 1)) + j
        out.insert(pos, e)
    return out


def build(manifest: dict, key_rows: list[dict], markers: list[str], seed: int, n_extra: int) -> tuple[dict, list[dict]]:
    by_case = defaultdict(list)
    case_of_task = {r["task_id"]: r["case"] for r in key_rows}
    for it in manifest["items"]:
        if it.get("is_repeat_of"):
            continue
        if it["task_id"] not in case_of_task:
            raise SystemExit(f"หยุด: {it['task_id']} ไม่อยู่ใน key")
        by_case[case_of_task[it["task_id"]]].append(it["task_id"])
    real = sorted(by_case)
    rnd = random.Random(seed)
    rnd.shuffle(real)
    per = -(-len(real) // len(markers))
    cases = []
    for i, rc in enumerate(real):
        cases.append({"no": i + 1, "tasks": sorted(by_case[rc]), "marker": markers[min(i // per, len(markers) - 1)]})
    extra, next_no = [], len(cases) + 1
    for mk in markers:
        others = [c for c in cases if c["marker"] != mk]
        if n_extra > len(others):
            raise SystemExit(f"เคสของผู้มาร์กคนอื่นมีไม่ถึง {n_extra} เคส")
        for c in sorted(rnd.sample(others, n_extra), key=lambda c: c["no"]):
            extra.append({"no": next_no, "task": rnd.choice(c["tasks"]), "marker": mk, "_from_case": c["no"]})
            next_no += 1
    order = {mk: interleave([c["no"] for c in cases if c["marker"] == mk], [e["no"] for e in extra if e["marker"] == mk])
             for mk in markers}
    study = {"format": FORMAT, "version": 1, "package_id": manifest["package_id"], "seed": seed,
             "created_at": datetime.now().isoformat(timespec="seconds"),
             "cases": cases, "extra": [{k: v for k, v in e.items() if not k.startswith("_")} for e in extra], "order": order}
    key = [{"kind": "case", "case_no": c["no"], "real_case": real[c["no"] - 1], "marker": c["marker"],
            "tasks": " ".join(c["tasks"]), "extra_of_case_no": ""} for c in cases]
    key += [{"kind": "interrater", "case_no": e["no"], "real_case": real[e["_from_case"] - 1], "marker": e["marker"],
             "tasks": e["task"], "extra_of_case_no": e["_from_case"]} for e in extra]
    return study, key


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=r"C:\PelNav_private\orig_package\manifest.json")
    ap.add_argument("--key", default=r"C:\PelNav_private\orig_key.csv")
    ap.add_argument("--markers", default="team1,team2")
    ap.add_argument("--seed", type=int, default=20261123)
    ap.add_argument("--extra", type=int, default=10, help="คู่วัดความตรงกันต่อผู้มาร์ก")
    ap.add_argument("--out", default=r"C:\PelNav_private")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    out = safe_out_dir(Path(args.out))
    sj, sk = out / "study.json", out / "study_key.csv"
    if (sj.exists() or sk.exists()) and not args.overwrite:
        sys.exit(f"มี {sj.name}/{sk.name} อยู่แล้ว — ใส่ --overwrite ถ้าจะสร้างใหม่ (เลขเคสจะเปลี่ยนถ้า seed เปลี่ยน)")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    key_rows = list(csv.DictReader(Path(args.key).open(encoding="utf-8-sig")))
    markers = [m.strip() for m in args.markers.split(",") if m.strip()]
    if len(markers) < 2 or len(set(markers)) != len(markers):
        sys.exit("--markers ต้องมีอย่างน้อย 2 ชื่อไม่ซ้ำ")
    study, key = build(manifest, key_rows, markers, args.seed, args.extra)
    try:
        for w in validate_study(study, manifest):
            print("  " + w)
    except StudyError as e:
        sys.exit(f"หยุด: {e}")
    out.mkdir(parents=True, exist_ok=True)
    sj.write_text(json.dumps(study, ensure_ascii=False, indent=1), encoding="utf-8")
    with sk.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    n = sum(len(c["tasks"]) for c in study["cases"])
    print(f"เคส {len(study['cases'])} · งาน {n} (ไม่รวมงานซ้ำ) · คู่วัดความตรงกัน {len(study['extra'])} · seed {args.seed}")
    for mk in markers:
        mine = [c for c in study["cases"] if c["marker"] == mk]
        print(f"  {mk}: เคส {mine[0]['no']}–{mine[-1]['no']} ({len(mine)} เคส {sum(len(c['tasks']) for c in mine)} งาน) "
              f"+ คู่พิเศษ {sum(1 for e in study['extra'] if e['marker'] == mk)}")
    print(f"→ {sj}\n→ {sk} (key ของทีม ห้ามขึ้น GitHub)")


if __name__ == "__main__":
    main()
