"""ตรวจจุดของทีมก่อนส่งให้หมอตรวจ — อ่าน CSV วิเคราะห์ (ดาวน์โหลดจากหน้าทีม) อย่างเดียว เขียนรายงานในโฟลเดอร์ส่วนตัว

    .venv\\Scripts\\python -I -X utf8 -B tools/check_team_marks.py                 # CSV ล่าสุดใน C:\\PelNav_private\\pilot\\
    .venv\\Scripts\\python -I -X utf8 -B tools/check_team_marks.py <ไฟล์.csv> --study <study.json>

1. ครบไหม: งานของผู้มาร์กแต่ละคน (เคส + คู่พิเศษ) ที่เสร็จแล้ว (done / partial / unmarkable) เทียบกับ study.json
   งานที่ยังข้ามไว้หรือยังไม่ทำ = หมอต้องวางจุดเอง (นับแยก)
2. งานที่น่าจะผิด (ใช้เกณฑ์เดียวกับคำเตือนบนหน้าเว็บ marker/config.js):
   - แนวเดียว: มุมเล็กสุดของรูปหลายเหลี่ยมที่ล้อมจุด < 15°
   - กระจุก: พื้นที่รูปหลายเหลี่ยมที่ล้อมจุด < 5% ของกรอบ (เอกซเรย์) / วงกลมภาพ (ฟลู) · จุด 2 จุดห่างกัน < 2% ของขนาดอ้างอิง
   - ไม่สอดคล้อง: ทายจุดเอกซเรย์แต่ละจุดจากอีก 3 คู่ (affine) — ทุกจุดคลาด > 10% ของเส้นทแยงกรอบ = เว็บเตือน "อาจไม่ตรงคู่"
   เรียงจากแย่สุด: คะแนน = ผลรวมของ (ค่าที่วัด / เกณฑ์) ที่เกินเกณฑ์
3. คู่วัดความตรงกัน (คู่พิเศษ): ผู้มาร์กสองคนเลือกจุดคนละตำแหน่งได้ จึงเทียบ "การวางภาพ" ไม่ใช่จุดต่อจุด (DECISIONS:
   วิธีวัดความสม่ำเสมอ) — แต่ละคนให้การแปลง ฟลู → เอกซเรย์ (affine least squares และ homography จาก 4 คู่)
   ย้ายตารางจุดในวงกลมฟลู (95% ของรัศมี) ด้วยการแปลงของสองคน ระยะเฉลี่ย ÷ เส้นทแยงกรอบ × 100%
   (ศูนย์กลางวงกลมประมาณจากกลางภาพ รัศมีจาก fluoro_area — ไม่เปิดภาพ)
รายงาน: <โฟลเดอร์ของ CSV>/team_marks_check.csv · หน้าจอแสดงเฉพาะเลขเคส/คู่ที่/task_id ไม่แสดงรหัสเคสจริง
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_pilot import affine3, points, read_export  # noqa: E402

N = 4
PRIVATE = Path(r"C:\PelNav_private")
FINAL = {"done", "partial", "unmarkable"}
COLLINEAR_DEG = 15.0        # = CFG.quality.collinearMinAngleDeg
MIN_HULL_FRAC = 0.05        # = CFG.quality.minHullAreaFraction
MIN_PAIR_FRAC = 0.02        # จุดสองจุดห่างกันน้อยกว่านี้ (สัดส่วนของขนาดอ้างอิง) = เกือบทับกัน
MISMATCH_PCT = 10.0         # = CFG.teamAssist.mismatchPct


def hull(pts):
    p = sorted(set(pts))
    if len(p) < 3:
        return p

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def area(h):
    return abs(sum(h[i][0] * h[(i + 1) % len(h)][1] - h[(i + 1) % len(h)][0] * h[i][1] for i in range(len(h)))) / 2


def min_angle(h):
    if len(h) < 3:
        return 0.0
    m = 180.0
    for i in range(len(h)):
        a, b, c = h[i - 1], h[i], h[(i + 1) % len(h)]
        v1, v2 = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
        cos = (v1[0] * v2[0] + v1[1] * v2[1]) / ((math.hypot(*v1) * math.hypot(*v2)) or 1)
        m = min(m, math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    return m


def geometry(pts, ref_area, ref_len):
    """คืน (มุมเล็กสุด°, พื้นที่/อ้างอิง, ระยะคู่ใกล้สุด/อ้างอิง)"""
    h = hull(pts)
    dmin = min(math.dist(a, b) for i, a in enumerate(pts) for b in pts[i + 1:])
    return min_angle(h), (area(h) / ref_area if len(h) >= 3 else 0.0), dmin / ref_len


def mismatch(xr, fl, box):
    """ทายจุดเอกซเรย์แต่ละจุดจากอีก 3 คู่ → ระยะคลาด % ของเส้นทแยงกรอบ (None = 3 จุดเกือบแนวเดียว)"""
    diag = math.dist(box[:2], box[2:]) or 1.0
    errs = []
    for i in range(N):
        o = [j for j in range(N) if j != i]
        f = affine3([fl[j] for j in o], [xr[j] for j in o])
        if f is None:
            return None
        errs.append(100 * math.dist(f(fl[i]), xr[i]) / diag)
    return errs


def fit_affine(src, dst):
    import numpy as np
    A = np.array([[x, y, 1.0] for x, y in src])
    sol, *_ = np.linalg.lstsq(A, np.array(dst, dtype=float), rcond=None)       # 3x2
    return lambda P: np.hstack([P, np.ones((len(P), 1))]) @ sol


def fit_homography(src, dst):
    import numpy as np
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, s, vt = np.linalg.svd(np.array(rows, dtype=float))
    if s[-2] < 1e-9 * s[0]:
        return None
    Hm = vt[-1].reshape(3, 3)

    def f(P):
        q = np.hstack([P, np.ones((len(P), 1))]) @ Hm.T
        return q[:, :2] / q[:, 2:3]
    return f


def fluoro_grid(it, step_frac=0.05, keep=0.95):
    """ตารางจุดในวงกลมฟลู: ศูนย์กลาง = กลางภาพ (ประมาณ) · รัศมี = sqrt(fluoro_area/π) × keep"""
    import numpy as np
    W, Hh = it["fluoro_size"]
    r = math.sqrt((it.get("fluoro_area") or W * Hh * math.pi / 4) / math.pi) * keep
    cx, cy, step = W / 2, Hh / 2, 2 * r * step_frac
    g = np.arange(-r, r + 1e-9, step)
    P = np.array([(cx + x, cy + y) for x in g for y in g if x * x + y * y <= r * r])
    return P


def agreement(r, it):
    """คืน (affine %, homography % หรือ None) — ระยะเฉลี่ยระหว่างการวางภาพของสองคน เป็น % ของเส้นทแยงกรอบ"""
    import numpy as np
    box = [float(r[k]) for k in ("box_x1", "box_y1", "box_x2", "box_y2")]
    diag = math.dist(box[:2], box[2:])
    sets = []
    for prefix in ("m", "m2"):
        xr, fl = points(r, prefix, "xray"), points(r, prefix, "fluoro")
        pairs = [(f, x) for x, f in zip(xr, fl) if x and f]
        if len(pairs) < 3:
            return None
        sets.append(pairs)
    P = fluoro_grid(it)
    out = []
    for fit in (fit_affine, fit_homography):
        if fit is fit_homography and any(len(s) < 4 for s in sets):
            out.append(None)
            continue
        f1, f2 = (fit([p[0] for p in s], [p[1] for p in s]) for s in sets)
        if f1 is None or f2 is None:
            out.append(None)
            continue
        out.append(float(100 * np.mean(np.linalg.norm(f1(P) - f2(P), axis=1)) / diag))
    return out


def assess(r: dict, prefix: str, it: dict) -> dict:
    """ประเมินจุดชุดหนึ่ง (m = ผู้มาร์ก, m2 = ผู้มาร์กคนที่สอง)"""
    box = [float(r[k]) for k in ("box_x1", "box_y1", "box_x2", "box_y2")]
    xr, fl = points(r, prefix, "xray"), points(r, prefix, "fluoro")
    out = {"pairs": sum(1 for a, b in zip(xr, fl) if a and b), "flags": [], "score": 0.0}
    box_area = (box[2] - box[0]) * (box[3] - box[1])
    fw, fh = it["fluoro_size"]
    f_area = it.get("fluoro_area") or fw * fh
    refs = {"xray": (box_area, math.sqrt(box_area)), "fluoro": (f_area, math.sqrt(f_area))}
    names = {"xray": "เอกซเรย์", "fluoro": "ฟลู"}
    for side, pts in (("xray", xr), ("fluoro", fl)):
        pts = [p for p in pts if p]
        if len(pts) < 3:
            continue
        ang, frac, dmin = geometry(pts, *refs[side])
        out[f"{side}_min_angle_deg"] = round(ang, 1)
        out[f"{side}_hull_pct"] = round(100 * frac, 2)
        out[f"{side}_closest_pct"] = round(100 * dmin, 2)
        if ang < COLLINEAR_DEG:
            out["flags"].append(f"{names[side]}แนวเดียว ({ang:.0f}°)")
            out["score"] += COLLINEAR_DEG / max(ang, 1.0)
        if frac < MIN_HULL_FRAC:
            out["flags"].append(f"{names[side]}กระจุก ({100 * frac:.1f}%)")
            out["score"] += MIN_HULL_FRAC / max(frac, 0.002)
        if dmin < MIN_PAIR_FRAC:
            out["flags"].append(f"{names[side]}มีจุดเกือบทับกัน")
            out["score"] += MIN_PAIR_FRAC / max(dmin, 0.002)
    if out["pairs"] == N:
        e = mismatch(xr, fl, box)
        if e:
            worst = max(range(N), key=lambda i: e[i])
            out["mismatch_min_pct"] = round(min(e), 1)
            out["mismatch_worst_point"] = worst + 1
            if min(e) > MISMATCH_PCT:
                out["flags"].append(f"ไม่สอดคล้อง (ทุกจุดคลาด > {min(e):.0f}% · แย่สุดจุด {worst + 1})")
                out["score"] += min(e) / MISMATCH_PCT
    out["score"] = round(out["score"], 2)
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--study", default=str(PRIVATE / "study.json"))
    ap.add_argument("--manifest", default=str(PRIVATE / "orig_package" / "manifest.json"))
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    if a.csv:
        path = Path(a.csv)
    else:
        found = [p for p in sorted((PRIVATE / "pilot").glob("study_*.csv"), key=lambda p: p.stat().st_mtime)]
        if not found:
            sys.exit(r"ไม่พบไฟล์ CSV — วางไฟล์ที่ดาวน์โหลดจากหน้าทีมไว้ที่ C:\PelNav_private\pilot\ แล้วรันใหม่")
        path = found[-1]
    _, rows = read_export(path)
    st = json.loads(Path(a.study).read_text(encoding="utf-8"))
    items = {it["task_id"]: it for it in json.loads(Path(a.manifest).read_text(encoding="utf-8"))["items"]}
    if st["package_id"] not in path.name:
        print(f"คำเตือน: ชื่อไฟล์ไม่มี {st['package_id']}")
    pair_no = {t: (c["no"], k + 1, len(c["tasks"])) for c in st["cases"] for k, t in enumerate(c["tasks"])}
    by_task = {r["task_id"]: r for r in rows}
    print(f"ไฟล์: {path.name} · {len(rows)} แถว")

    # ---- 1. ครบไหม
    print("\n== 1. ความครบ ==")
    all_ok = True
    for mk in sorted({c["marker"] for c in st["cases"]}):
        case_tasks = [t for c in st["cases"] if c["marker"] == mk for t in c["tasks"]]
        extras = [e for e in st.get("extra") or [] if e["marker"] == mk]
        sts = [(by_task.get(t) or {}).get("marker_status", "") if (by_task.get(t) or {}).get("marker") == mk else "ไม่มีในไฟล์"
               for t in case_tasks]
        ests = [(by_task.get(e["task"]) or {}).get("marker2_status", "") if (by_task.get(e["task"]) or {}).get("marker2") == mk
                else "ไม่มีในไฟล์" for e in extras]
        done = sum(s in FINAL for s in sts) + sum(s in FINAL for s in ests)
        total = len(case_tasks) + len(extras)
        cnt = {}
        for s in sts + ests:
            cnt[s or "ยังไม่ทำ"] = cnt.get(s or "ยังไม่ทำ", 0) + 1
        print(f"  {mk}: เสร็จ {done}/{total} งาน (เคส {len(case_tasks)} + คู่พิเศษ {len(extras)}) · สถานะ {cnt}")
        all_ok &= done == total
    ex_done = sum(1 for e in st.get("extra") or [] if (by_task.get(e["task"]) or {}).get("marker2_status") in FINAL)
    print(f"  คู่วัดความตรงกัน: เสร็จ {ex_done}/{len(st.get('extra') or [])}")
    no_pts = [(pair_no[t][0], pair_no[t][1], t, by_task[t].get("marker_status") or "ยังไม่ทำ") for t in pair_no
              if t in by_task and by_task[t].get("marker_status") not in ("done", "partial", "unmarkable")]
    unm = [(pair_no[t][0], pair_no[t][1], t) for t in pair_no if (by_task.get(t) or {}).get("marker_status") == "unmarkable"]
    shown = sorted(no_pts)[:25]
    print(f"  งานที่หมอจะไม่เห็นจุดของทีม (ข้ามไว้/ยังไม่ทำ — หมอต้องวางเอง): {len(no_pts)}"
          + ("" if not no_pts else " · " + ", ".join(f"เคส {c} คู่ {k} ({s})" for c, k, _, s in shown))
          + (f" … และอีก {len(no_pts) - len(shown)} งาน" if len(no_pts) > len(shown) else ""))
    print(f"  งานที่ทีมระบุ มาร์กไม่ได้ (หมอเห็นเหตุผล): {len(unm)}")

    # ---- 2. งานที่น่าจะผิด
    report = []
    for t, r in by_task.items():
        if t not in items:
            continue
        cno, k, n = pair_no.get(t, (r["case_no"], "?", "?"))
        for prefix, who, stcol in (("m", r["marker"], "marker_status"), ("m2", r.get("marker2", ""), "marker2_status")):
            if not who or r.get(stcol) not in ("done", "partial"):
                continue
            res = assess(r, prefix, items[t])
            report.append({"case_no": cno if prefix == "m" else r.get("marker2_case_no", ""), "pair_no": k if prefix == "m" else 1,
                           "pairs_in_case": n if prefix == "m" else 1, "task_id": t, "marker": who,
                           "set": "เคสหลัก (หมอเห็น)" if prefix == "m" else "คู่พิเศษ (หมอไม่เห็น)", "status": r[stcol],
                           **{kk: v for kk, v in res.items() if kk != "flags"}, "flags": " · ".join(res["flags"])})
    flagged = sorted((x for x in report if x["flags"]), key=lambda x: -x["score"])
    print(f"\n== 2. งานที่น่าจะผิด: {len(flagged)} จาก {len(report)} ชุดจุด (เรียงจากแย่สุด · แสดง {min(a.top, len(flagged))}) ==")
    for x in flagged[:a.top]:
        where = (f"เคส {x['case_no']} คู่ {x['pair_no']}/{x['pairs_in_case']}" if x["set"].startswith("เคสหลัก")
                 else f"คู่พิเศษ เคส {x['case_no']}")
        print(f"  {x['score']:6.1f}  {where:<18} {x['task_id']} ({x['marker']}) — {x['flags']}")

    # ---- 3. คู่วัดความตรงกัน
    agree = []
    for e in st.get("extra") or []:
        r = by_task.get(e["task"])
        if not r or r.get("marker_status") not in ("done", "partial") or r.get("marker2_status") not in ("done", "partial"):
            continue
        g = agreement(r, items[e["task"]])
        if g:
            main = pair_no.get(e["task"], ("?", "?", "?"))
            agree.append((g[0], g[1], e["no"], e["task"], f"เคส {main[0]} คู่ {main[1]}/{main[2]}", r["marker"], r["marker2"]))
    if agree:
        aff = sorted(x[0] for x in agree)
        q = lambda f: aff[min(len(aff) - 1, int(f * (len(aff) - 1) + 0.5))]  # noqa: E731
        print(f"\n== 3. คู่วัดความตรงกัน {len(agree)} คู่: การวางภาพของผู้มาร์กสองคนต่างกันเฉลี่ยกี่ % ของเส้นทแยงกรอบ ==")
        print(f"  affine: ค่ากลาง {q(0.5):.1f}% · IQR {q(0.25):.1f}–{q(0.75):.1f}% · สูงสุด {aff[-1]:.1f}%"
              f" · homography ใช้ได้ {sum(1 for x in agree if x[1] is not None)} คู่")
        for a_, h_, no, t, main, m1, m2 in sorted(agree, reverse=True):
            print(f"  คู่พิเศษ เคส {no} ({t} = {main}, {m1} กับ {m2}): affine {a_:.1f}%"
                  f" · homography {'-' if h_ is None else f'{h_:.1f}%'}{'  <-- ต่างมาก' if a_ > 10 else ''}")

    out = path.parent / "team_marks_check.csv"
    cols = ["score", "case_no", "pair_no", "pairs_in_case", "task_id", "marker", "set", "status", "flags", "pairs",
            "xray_min_angle_deg", "xray_hull_pct", "xray_closest_pct", "fluoro_min_angle_deg", "fluoro_hull_pct",
            "fluoro_closest_pct", "mismatch_min_pct", "mismatch_worst_point"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(report, key=lambda x: -x["score"]))
    print(f"\nรายงาน: {out}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
