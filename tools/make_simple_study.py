"""สร้างนิยามการศึกษาแบบง่าย (ชั่วคราว): ภาพ 1 คู่ = 1 เคส — ใช้ตอนยังไม่มี orig_key.csv / team_marks.json
    python -I -X utf8 -B tools/make_simple_study.py <โฟลเดอร์แพ็กเกจ> --out <ไฟล์ study.json>
แล้วตั้งบนเครื่องที่ใช้งาน:  m set-study <path เต็มของ study.json>

กติกา: ใช้เฉพาะงานที่ไม่ใช่งานซ้ำ (is_repeat_of ว่าง) เรียงตาม task_id · เลขเคส 1..N
  ผู้มาร์กแบ่งครึ่ง (ค่าเริ่มต้น team1 = ครึ่งแรก, team2 = ครึ่งหลัง) · ไม่มีคู่วัดความตรงกันระหว่างผู้มาร์ก
  ไฟล์ที่ได้ไม่มีชื่อไฟล์ภาพหรือข้อมูลผู้ป่วย (มีแค่ task_id)
เมื่อได้การศึกษาจริงของทีม: m import-marks <team_marks.json> จะตั้งการศึกษาแทนชุดนี้ (จุดที่บันทึกไว้แล้วยังอยู่ตาม task_id)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from server.study import FORMAT, StudyError, validate_study  # noqa: E402


def build(manifest: dict, markers: list[str]) -> dict:
    tasks = sorted(it["task_id"] for it in manifest["items"] if not it.get("is_repeat_of"))
    if not tasks:
        raise SystemExit("หยุด: แพ็กเกจไม่มีงานที่ใช้ได้")
    per = -(-len(tasks) // len(markers))                     # หารปัดขึ้น
    cases = [{"no": i + 1, "tasks": [t], "marker": markers[min(i // per, len(markers) - 1)]} for i, t in enumerate(tasks)]
    return {
        "format": FORMAT, "version": 1, "package_id": manifest["package_id"], "seed": 0,
        "cases": cases, "extra": [],
        "order": {mk: [c["no"] for c in cases if c["marker"] == mk] for mk in markers},
        "note": "simple study: 1 image pair = 1 case, no inter-rater pairs (temporary until the team study is imported)",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", help="โฟลเดอร์แพ็กเกจที่มี manifest.json")
    ap.add_argument("--out", required=True, help="ไฟล์ study.json ที่จะเขียน")
    ap.add_argument("--markers", default="team1,team2", help="บัญชีทีมที่เป็นผู้มาร์ก คั่นด้วยจุลภาค (ค่าเริ่มต้น team1,team2)")
    a = ap.parse_args()
    manifest = json.loads((Path(a.package) / "manifest.json").read_text(encoding="utf-8"))
    markers = [m.strip() for m in a.markers.split(",") if m.strip()]
    if not markers:
        raise SystemExit("หยุด: ต้องมีผู้มาร์กอย่างน้อย 1 บัญชี")
    study = build(manifest, markers)
    try:
        warn = validate_study(study, manifest)
    except StudyError as e:
        raise SystemExit(f"หยุด: {e}")
    out = Path(a.out)
    out.write_text(json.dumps(study, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = " · ".join(f"{mk} {len(study['order'][mk])} เคส" for mk in markers)
    print(f"เขียน {out} · {study['package_id']} · เคส {len(study['cases'])} ({counts})")
    for w in warn:
        print("  " + w)


if __name__ == "__main__":
    main()
