"""ตรวจไฟล์ CSV วิเคราะห์ (ดาวน์โหลดจากหน้าทีม) ก่อนมาร์กจริง — อ่านอย่างเดียว เขียนรายงานเฉพาะในโฟลเดอร์ส่วนตัว

    .venv\\Scripts\\python -I -X utf8 -B tools/check_pilot.py                  # ใช้ CSV ล่าสุดใน C:\\PelNav_private\\pilot\\
    .venv\\Scripts\\python -I -X utf8 -B tools/check_pilot.py <ไฟล์.csv>

ตรวจ:
  1. อ่านไฟล์ได้ (บรรทัดแรกเป็น "# COCO …") มีคอลัมน์ครบ
  2. task_id ทุกแถวอยู่ใน manifest ของแพ็กเกจ, orig_key.csv และ study_key.csv · เลขเคสในไฟล์ตรงกับ study_key.csv
  3. พิกัดทุกจุด (ผู้มาร์ก / ผู้มาร์กคนที่สอง / หมอ) อยู่ในขนาดภาพ: 0 ≤ x ≤ W และ 0 ≤ y ≤ H (เอกซเรย์และฟลูแยกกัน)
  4. TRE ทดลอง (ไม่ต้องมีผลโมเดล): งานที่มีครบ 4 คู่ ทายจุดเอกซเรย์แต่ละจุดจากอีก 3 คู่ด้วย affine (ฟลู → เอกซเรย์)
     ระยะคลาด = TRE แบบ leave-one-out (พิกเซลเอกซเรย์) และ nTRE (% ของเส้นทแยงกรอบ) — ใช้ยืนยันว่าทั้งสายข้อมูลคำนวณได้
     และพิกัดไม่สลับแกน/ไม่สลับภาพ (ค่าที่ได้ควรเป็นหลักหน่วยถึงหลักสิบ % ไม่ใช่หลักร้อย)
รายงาน: <โฟลเดอร์ของ CSV>/pilot_check_report.csv · หน้าจอแสดงเฉพาะ task_id/เลขเคส ไม่แสดงรหัสเคสจริง
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

N = 4
PRIVATE = Path(r"C:\PelNav_private")
SETS = (("m", "ผู้มาร์ก"), ("m2", "ผู้มาร์กคนที่สอง"), ("d", "หมอ"))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def points(row: dict, prefix: str, side: str) -> list:
    s = "x" if side == "xray" else "f"
    out = []
    for i in range(1, N + 1):
        x, y = num(row.get(f"{prefix}_{s}{i}_x")), num(row.get(f"{prefix}_{s}{i}_y"))
        out.append((x, y) if x is not None and y is not None else None)
    return out


def affine3(src, dst):
    """affine ที่ส่ง 3 จุด src → dst พอดี (คืนฟังก์ชัน) · 3 จุดเกือบแนวเดียวกัน = None"""
    (x1, y1), (x2, y2), (x3, y3) = src
    det = x1 * (y2 - y3) - x2 * (y1 - y3) + x3 * (y1 - y2)
    span = max(math.dist(src[0], src[1]), math.dist(src[0], src[2]), 1.0)
    if abs(det) < 1e-3 * span * span:
        return None

    def solve(vals):
        a, b, c = vals
        return ((a * (y2 - y3) - b * (y1 - y3) + c * (y1 - y2)) / det,
                (x1 * (b - c) - x2 * (a - c) + x3 * (a - b)) / det,
                (x1 * (y2 * c - y3 * b) - x2 * (y1 * c - y3 * a) + x3 * (y1 * b - y2 * a)) / det)
    ax, ay = solve([p[0] for p in dst]), solve([p[1] for p in dst])
    return lambda p: (ax[0] * p[0] + ax[1] * p[1] + ax[2], ay[0] * p[0] + ay[1] * p[1] + ay[2])


def loo_tre(xr, fl, box):
    """TRE leave-one-out: แต่ละจุด ทายตำแหน่งเอกซเรย์จากอีก 3 คู่ → (ค่าเฉลี่ย px, สูงสุด px, ค่าเฉลี่ย %, สูงสุด %)"""
    diag = math.dist(box[:2], box[2:]) or 1.0
    errs = []
    for i in range(N):
        o = [j for j in range(N) if j != i]
        f = affine3([fl[j] for j in o], [xr[j] for j in o])
        if f is None:
            return None
        errs.append(math.dist(f(fl[i]), xr[i]))
    return (sum(errs) / N, max(errs), 100 * sum(errs) / N / diag, 100 * max(errs) / diag)


def read_export(path: Path) -> tuple[list[str], list[dict]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or not lines[0].startswith("# COCO"):
        sys.exit("หยุด: ไม่ใช่ไฟล์ CSV วิเคราะห์จากหน้าทีม (บรรทัดแรกต้องเป็น # COCO …)")
    rd = csv.DictReader(lines[1:])
    return lines[0], list(rd)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="ไฟล์ CSV (ไม่ใส่ = ไฟล์ล่าสุดใน C:\\PelNav_private\\pilot\\)")
    ap.add_argument("--manifest", default=str(PRIVATE / "orig_package" / "manifest.json"))
    ap.add_argument("--orig-key", default=str(PRIVATE / "orig_key.csv"))
    ap.add_argument("--study-key", default=str(PRIVATE / "study_key.csv"))
    args = ap.parse_args()
    if args.csv:
        path = Path(args.csv)
    else:
        found = sorted((PRIVATE / "pilot").glob("*.csv"), key=lambda p: p.stat().st_mtime)
        found = [p for p in found if p.name != "pilot_check_report.csv"]
        if not found:
            sys.exit(r"ไม่พบไฟล์ CSV — วางไฟล์ที่ดาวน์โหลดจากหน้าทีมไว้ที่ C:\PelNav_private\pilot\ แล้วรันใหม่")
        path = found[-1]
    head, rows = read_export(path)
    need = {"case_no", "task_id", "marker", "marker_status", "m_x1_x", "m_f4_y", "review_status"}
    if need - set(rows[0] if rows else {}):
        sys.exit(f"หยุด: คอลัมน์ไม่ครบ {sorted(need - set(rows[0] if rows else {}))}")
    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    items = {it["task_id"]: it for it in man["items"]}
    okey = {r["task_id"]: r for r in csv.DictReader(Path(args.orig_key).open(encoding="utf-8-sig"))}
    skey = {}
    for r in csv.DictReader(Path(args.study_key).open(encoding="utf-8-sig")):
        if r["kind"] == "case":
            for t in r["tasks"].split():
                skey[t] = r
    print(f"ไฟล์: {path.name} · {len(rows)} แถว · แพ็กเกจ {man['package_id']}")

    problems, report, marked = [], [], 0
    for r in rows:
        tid, cno = r["task_id"], r["case_no"]
        it = items.get(tid)
        if not it:
            problems.append(f"{tid}: ไม่มีในแพ็กเกจ")
            continue
        if tid not in okey:
            problems.append(f"{tid}: ไม่มีใน orig_key.csv")
        if tid not in skey:
            problems.append(f"{tid}: ไม่มีใน study_key.csv")
        elif skey[tid]["case_no"] != cno:
            problems.append(f"{tid}: เลขเคสในไฟล์ ({cno}) ไม่ตรง study_key.csv ({skey[tid]['case_no']}) — เครื่องแล็บใช้การศึกษาคนละชุด?")
        box = [num(v) for v in (r["box_x1"], r["box_y1"], r["box_x2"], r["box_y2"])]
        if any(abs(a - b) > 0.01 for a, b in zip(box, it["box_xyxy"])):
            problems.append(f"{tid}: กรอบในไฟล์ไม่ตรง manifest")
        rec = {"case_no": cno, "task_id": tid, "marker": r["marker"], "marker_status": r["marker_status"],
               "doctor": r.get("doctor", ""), "review_status": r.get("review_status", "")}
        for prefix, label in SETS:
            for side, size in (("xray", it["xray_size"]), ("fluoro", it["fluoro_size"])):
                for i, p in enumerate(points(r, prefix, side), 1):
                    if p and not (0 <= p[0] <= size[0] and 0 <= p[1] <= size[1]):
                        problems.append(f"{tid}: จุด {i} {side} ของ{label} ({p[0]}, {p[1]}) อยู่นอกภาพ {size[0]}×{size[1]}")
        xr, fl = points(r, "m", "xray"), points(r, "m", "fluoro")
        rec["pairs"] = sum(1 for a, b in zip(xr, fl) if a and b)
        if rec["pairs"]:
            marked += 1
        t = loo_tre(xr, fl, it["box_xyxy"]) if rec["pairs"] == N else None
        if t:
            rec.update(loo_tre_mean_px=round(t[0], 2), loo_tre_max_px=round(t[1], 2),
                       loo_ntre_mean_pct=round(t[2], 3), loo_ntre_max_pct=round(t[3], 3))
        report.append(rec)

    out = path.parent / "pilot_check_report.csv"
    cols = ["case_no", "task_id", "marker", "marker_status", "pairs", "loo_tre_mean_px", "loo_tre_max_px",
            "loo_ntre_mean_pct", "loo_ntre_max_pct", "doctor", "review_status"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(report)

    print(f"งานที่ทีมวางจุดแล้ว: {marked} · ครบ 4 คู่: {sum(1 for x in report if x.get('pairs') == N)}")
    for x in report:
        if x.get("pairs"):
            tre = (f"TRE ทดลอง (ทายจากอีก 3 คู่) เฉลี่ย {x['loo_tre_mean_px']} px = {x['loo_ntre_mean_pct']}% ของกรอบ "
                   f"(สูงสุด {x['loo_tre_max_px']} px)" if "loo_tre_mean_px" in x else "ยังไม่ครบ 4 คู่ — คำนวณ TRE ทดลองไม่ได้")
            print(f"  เคส {x['case_no']} {x['task_id']} ({x['marker']}, {x['marker_status']}, {x['pairs']} คู่): {tre}")
    if problems:
        print(f"\nพบปัญหา {len(problems)} ข้อ:")
        for p in problems[:30]:
            print("  - " + p)
        sys.exit(1)
    print("\nผ่าน: ทุก task_id จับคู่กับ manifest/orig_key/study_key ได้ · เลขเคสตรง · ทุกจุดอยู่ในขนาดภาพ · คำนวณ TRE ทดลองได้")
    print(f"รายงาน: {out}")


if __name__ == "__main__":
    main()
