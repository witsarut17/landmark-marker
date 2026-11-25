"""ทดสอบ tools/check_pilot.py ด้วยข้อมูลสังเคราะห์ (ไม่แตะข้อมูลจริง)

    .venv\\Scripts\\python -X utf8 -B tests/test_pilot_check.py
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_study import H, PKG, TestServer, client_login, put, setup, targets, task_with  # noqa: E402

rows: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    rows.append((bool(ok), label, str(detail)))


def run(csv_path, S, okey, skey):
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", str(ROOT / "tools" / "check_pilot.py"), str(csv_path),
                        "--manifest", str(ROOT / "tests" / "generated" / PKG / "manifest.json"),
                        "--orig-key", str(okey), "--study-key", str(skey)], capture_output=True, text=True, encoding="utf-8")
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
        put(t1, "T001", task_with(list(zip(T["T001_X.png"][:4], T["T001_F.jpg"][:4]))))
        put(t1, "T006", task_with(list(zip(T["T006_X.png"][:4], T["T006_F.jpg"][:4]))))
        put(t1, "T002", task_with([], "unmarkable", "no_overlap"))
        tc = S.app.test_client()
        tc.post("/api/login", json={"username": "team1", "password": users["team1"][1]}, headers=H)
        text = tc.get("/api/admin/study-export?format=csv").data.decode("utf-8")
        d = S.tmp / "pilot"
        d.mkdir()
        good = d / "study.csv"
        good.write_text(text, encoding="utf-8")
        okey, skey = d / "orig_key.csv", d / "study_key.csv"
        with okey.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["task_id", "case"])
            w.writerows([[t, f"real_{c['no']}"] for c in st["cases"] for t in c["tasks"]])
        with skey.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["kind", "case_no", "real_case", "marker", "tasks", "extra_of_case_no"])
            w.writeheader()
            w.writerows([{"kind": "case", "case_no": c["no"], "real_case": f"real_{c['no']}", "marker": c["marker"],
                          "tasks": " ".join(c["tasks"]), "extra_of_case_no": ""} for c in st["cases"]])
        code, out = run(good, S, okey, skey)
        check(code == 0 and "ผ่าน:" in out and (d / "pilot_check_report.csv").exists(), "ไฟล์ถูกต้อง → ผ่าน และเขียนรายงาน", out[-300:])
        rep = {r["task_id"]: r for r in csv.DictReader((d / "pilot_check_report.csv").open(encoding="utf-8-sig"))}
        check(float(rep["T006"]["loo_tre_mean_px"]) < 1.0 and rep["T001"]["loo_tre_mean_px"] != "" and rep["T002"]["pairs"] == "0",
              "TRE ทดลอง: ภาพที่สัมพันธ์กันแบบ affine (T006) คลาด < 1 px · งานที่มาร์กไม่ได้ไม่คำนวณ", rep["T006"])
        check("real_" not in out, "หน้าจอไม่แสดงรหัสเคสจริง")

        lines = text.splitlines()
        hdr = lines[1].split(",")
        bad = list(lines)
        i6 = next(k for k, ln in enumerate(lines) if ",T006," in ln)
        cells = next(csv.reader([lines[i6]]))
        cells[hdr.index("m_x1_x")] = "999999"
        bad[i6] = ",".join(cells)
        (d / "bad_point.csv").write_text("\n".join(bad), encoding="utf-8")
        code, out = run(d / "bad_point.csv", S, okey, skey)
        check(code != 0 and "อยู่นอกภาพ" in out, "จุดอยู่นอกขนาดภาพ → ไม่ผ่าน บอกงานและจุด", out[-200:])

        cells = next(csv.reader([lines[i6]]))
        cells[hdr.index("case_no")] = "4"
        bad = list(lines)
        bad[i6] = ",".join(cells)
        (d / "bad_case.csv").write_text("\n".join(bad), encoding="utf-8")
        code, out = run(d / "bad_case.csv", S, okey, skey)
        check(code != 0 and "ไม่ตรง study_key" in out, "เลขเคสไม่ตรง study_key → ไม่ผ่าน (เครื่องแล็บใช้การศึกษาคนละชุด)", out[-200:])

        (d / "not_export.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        code, out = run(d / "not_export.csv", S, okey, skey)
        check(code != 0 and "ไม่ใช่ไฟล์ CSV วิเคราะห์" in out, "ไฟล์อื่นที่ไม่ใช่ CSV วิเคราะห์ → แจ้งชัด", out[-150:])
    finally:
        S.stop()
    for ok, label, detail in rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n = sum(1 for r in rows if r[0])
    print(f"\nผ่าน {n} / {len(rows)} รายการ")
    sys.exit(0 if n == len(rows) else 1)


if __name__ == "__main__":
    main()
