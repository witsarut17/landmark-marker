"""ทดสอบ tools/check_team_marks.py ด้วยข้อมูลสังเคราะห์ (ไม่แตะข้อมูลจริง)

    .venv\\Scripts\\python -X utf8 -B tests/test_team_marks.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_study import H, PKG, TestServer, client_login, put, setup, targets, task_with  # noqa: E402

rows: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    rows.append((bool(ok), label, str(detail)))


def run(csv_path, study_path):
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", str(ROOT / "tools" / "check_team_marks.py"), str(csv_path),
                        "--study", str(study_path), "--manifest", str(ROOT / "tests" / "generated" / PKG / "manifest.json")],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    S = TestServer(packages=(PKG,))
    try:
        st, users = setup(S)
        T = targets()
        t1 = client_login(S, "team1", users["team1"][1])
        good = list(zip(T["T001_X.png"][:4], T["T001_F.jpg"][:4]))
        put(t1, "T001", task_with(good))
        line = [((100 + 40 * i, 200 + 2 * i), f) for i, (_, f) in enumerate(good)]        # เอกซเรย์ 4 จุดเรียงแนวเดียว
        put(t1, "T002", task_with(line))
        put(t1, "T006", task_with(list(zip(T["T006_X.png"][:4], T["T006_F.jpg"][:4]))))
        t2 = client_login(S, "team2", users["team2"][1])                     # คู่พิเศษ: team2 มาร์ก T006 (งานของ team1) ซ้ำ
        put(t2, "T006", task_with(list(zip(T["T006_X.png"][1:5], T["T006_F.jpg"][1:5]))))
        tc = S.app.test_client()
        tc.post("/api/login", json={"username": "team1", "password": users["team1"][1]}, headers=H)
        text = tc.get("/api/admin/study-export?format=csv").data.decode("utf-8")
        d = S.tmp / "pilot"
        d.mkdir()
        f = d / f"study_{PKG}_test.csv"
        f.write_text(text, encoding="utf-8")
        sp = d / "study.json"
        sp.write_text(json.dumps(st), encoding="utf-8")
        code, out = run(f, sp)
        check(code != 0 and "team1: เสร็จ 3/" in out and "team2: เสร็จ 1/" in out,
              "ความครบ: นับงานที่เสร็จต่อผู้มาร์ก · ยังไม่ครบ → exit ≠ 0", out[:400])
        check("หมอต้องวางเอง" in out, "บอกจำนวนงานที่หมอไม่เห็นจุดของทีม")
        rep = {r["task_id"]: r for r in csv.DictReader((d / "team_marks_check.csv").open(encoding="utf-8-sig"))}
        check("แนวเดียว" in rep["T002"]["flags"] and float(rep["T002"]["score"]) > 0,
              "จุดเอกซเรย์เรียงแนวเดียว → ติดธง แนวเดียว", rep["T002"]["flags"])
        check(rep["T006"]["flags"] == "", "ภาพสัมพันธ์กันแบบ affine (T006) จุดกระจายดี → ไม่ติดธง", rep["T006"]["flags"])
        lines = [ln for ln in out.splitlines() if "T00" in ln and "—" in ln]
        check(lines and "T002" in lines[0], "เรียงจากแย่สุด: T002 อยู่บนสุด · บอกเลขเคส + คู่ที่", lines[:2])
        check("เคส 1 คู่ 2/2" in out, "ตำแหน่งบนเว็บ: เคส 1 คู่ 2/2 (T002 เป็นคู่ที่ 2 ของเคส 1)")
        line6 = next((ln for ln in out.splitlines() if "คู่พิเศษ เคส 6 (T006" in ln), "")
        check("affine 0.0%" in line6,
              "คู่วัดความตรงกัน: สองคนเลือกจุดต่างกันแต่วางภาพเหมือนกัน (T006 สัมพันธ์แบบ affine) → ต่างกัน 0.0% (เทียบการวางภาพ ไม่ใช่จุดต่อจุด)", line6)
    finally:
        S.stop()
    for ok, label, detail in rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n = sum(1 for r in rows if r[0])
    print(f"\nผ่าน {n} / {len(rows)} รายการ")
    sys.exit(0 if n == len(rows) else 1)


if __name__ == "__main__":
    main()
