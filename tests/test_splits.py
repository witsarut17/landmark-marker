"""ทดสอบ tools/check_splits.py และ make_study_package.py --splits ด้วยข้อมูลปลอม — ไม่แตะข้อมูลจริง

รัน:  .venv\\Scripts\\python tests/test_splits.py   (ต้องรัน tests/test_make_package.py ก่อน 1 ครั้ง เพื่อสร้าง fake_data)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tests" / "generated"
FAKE = GEN / "fake_splits"
PKG_FAKE = GEN / "fake_data"            # สร้างโดย test_make_package.py (มี case_demo1, case_demo2 พร้อมภาพ)
OUT = GEN / "_splitstest"
sys.path.insert(0, str(ROOT / "tools"))
import check_splits as C  # noqa: E402

results = []


def check(ok, label, detail=""):
    results.append((bool(ok), label, detail))


def build():
    if FAKE.exists():
        shutil.rmtree(FAKE)
    boxes = {"case_demo11": 5, "case_demo12": 2, "case_demo13": 4, "case_demo14": 3, "case_demo15": 6, "case_demo16": 0}
    for c, n in boxes.items():
        (FAKE / c).mkdir(parents=True)
        (FAKE / c / "instances_clean.json").write_text(json.dumps({"annotations": [{"id": i} for i in range(n)]}), encoding="utf-8")
    (FAKE / "desktop.ini").write_text("x", encoding="utf-8")
    (FAKE / "groups.txt").write_text("# test\ncase_demo11,case_demo12\n", encoding="utf-8")


def write(name, text):
    p = FAKE / name
    p.write_text(text, encoding="utf-8")
    return p


EXP = {"train": 2, "val": 1, "test": 3}
GOOD = "case_id,split\ncase_demo11,test\ncase_demo12,test\ncase_demo13,test\ncase_demo14,train\ncase_demo15,train\ncase_demo16,val\n"


def v(text, exp=EXP, groups="groups.txt"):
    return C.validate(write("s.csv", text), FAKE, exp, FAKE / groups)


def main():
    build()
    i = v(GOOD)
    check(not i["errors"] and i["counts"]["test"] == 3 and i["test_boxes"] == {"case_demo11": 5, "case_demo12": 2, "case_demo13": 4},
          "ไฟล์ถูกต้อง: ไม่มี ERROR + นับกรอบชุด test", str(i["errors"]))
    check(all(ok for _, _, ok in i["groups"]), "กลุ่มผู้ป่วยเดียวกันอยู่ชุดเดียวกัน = ผ่าน", "")
    i = v("﻿Case_ID , Split\n" + GOOD.split("\n", 1)[1].replace("test", " TEST "))
    check(not i["errors"], "อ่านได้แม้มี BOM / ตัวพิมพ์ใหญ่ / ช่องว่าง (ไฟล์จาก Excel)", str(i["errors"]))

    cases = [
        (GOOD.replace("case_demo16,val\n", ""), "ไม่มีใน splits.csv", "ขาดเคสที่มีในโฟลเดอร์ข้อมูล"),
        (GOOD + "case_demo99,train\n", "ไม่มีในโฟลเดอร์ข้อมูล", "มีเคสที่ไม่มีในโฟลเดอร์ข้อมูล"),
        (GOOD + "case_demo14,test\n", "ซ้ำ", "รหัสเคสซ้ำ"),
        (GOOD.replace("case_demo16,val", "case_demo16,validation"), "ไม่ใช่ train/val/test", "ชื่อชุดผิด"),
        (GOOD.replace("case_demo12,test", "case_demo12,train"), "ชุด test มี 2", "จำนวน test ไม่ตรง = ERROR"),
        (GOOD.replace("case_demo13,test", "case_demo13,val").replace("case_demo16,val", "case_demo16,test"),
         "ไม่มีกรอบ", "เคส test ที่ไม่มีกรอบ"),
        (GOOD.replace("case_demo12,test", "case_demo12,train").replace("case_demo14,train", "case_demo14,test"),
         "คนละชุด", "กลุ่มผู้ป่วยเดียวกันอยู่คนละชุด"),
        ("case_id,split,name\n" + "\n".join(l + ",ชื่อ" for l in GOOD.strip().split("\n")[1:]) + "\n", "ตัวอักษรไทย", "มีชื่อภาษาไทย"),
        (GOOD + "H" + "N 1234567,train\n", "HN", "มีรูปแบบ HN"),  # ต่อสตริง เพื่อไม่ให้ check_publish จับไฟล์เทสต์นี้
        ("id,set\n", "case_id และ split", "หัวคอลัมน์ผิด"),
    ]
    for text, want, label in cases:
        i = v(text)
        check(any(want in e for e in i["errors"]), f"ERROR: {label}", str(i["errors"])[:200])

    i = v(GOOD, exp={"train": 5, "val": 1, "test": 3})
    check(not i["errors"] and any("train" in w for w in i["warns"]), "จำนวน train ไม่ตรง = WARN (ไม่หยุด)", str(i["warns"]))
    i = v(GOOD, groups="nope.txt")
    check(any("same_patient" in w or "nope" in w for w in i["warns"]), "ไม่มีไฟล์กลุ่ม = WARN", str(i["warns"]))
    i = v(GOOD.replace("case_id,split", "case_id,split,age").replace("\n", ",30\n").replace("case_id,split,age,30", "case_id,split,age"))
    check(not i["errors"] and any("คอลัมน์อื่น" in w for w in i["warns"]), "คอลัมน์อื่น = WARN ไม่พิมพ์ค่า", str(i["warns"]))

    # สคริปต์ check_splits ทั้งไฟล์: exit code + ไม่เขียนอะไรลงโฟลเดอร์ข้อมูล
    before = sorted(p.as_posix() for p in FAKE.rglob("*"))
    good = write("splits.csv", GOOD)
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools/check_splits.py"), str(good), "--data-root", str(FAKE),
                        "--expect", "train=2,val=1,test=3", "--groups", str(FAKE / "groups.txt")], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0 and "ไม่พบ ERROR" in r.stdout and "กรอบรวม 11" in r.stdout and "≤ 8" in r.stdout,
          "check_splits.py: ผ่าน + สรุปกรอบชุด test + ประมาณจำนวนงาน", r.stdout[-300:])
    bad = write("bad.csv", GOOD.replace("case_demo12,test", "case_demo12,train"))
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools/check_splits.py"), str(bad), "--data-root", str(FAKE),
                        "--expect", "test=3"], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 1 and "ERROR" in r.stdout, "check_splits.py: มี ERROR → exit 1", r.stdout[-200:])
    after = sorted(p.as_posix() for p in FAKE.rglob("*"))
    check(before + [good.as_posix(), bad.as_posix()] == sorted(set(after)) or set(after) - set(before) <= {good.as_posix(), bad.as_posix()},
          "check_splits ไม่เขียนไฟล์ใด ๆ ลงโฟลเดอร์ข้อมูล", "")

    # report_fluoro_missing: ไม่มีโฟลเดอร์ / โฟลเดอร์ว่าง / ชื่อไม่ตรง / ปกติ
    ann = lambda fid: {"id": 1, "image_id": 1, "bbox": [1, 1, 5, 5], "attributes": {"fluo_id": fid}}
    for c, setup in (("case_demo12", "empty"), ("case_demo13", "mismatch"), ("case_demo14", "ok")):
        fd = FAKE / c / "fluoroscopy"
        fd.mkdir(exist_ok=True)
        (fd / "desktop.ini").write_text("x", encoding="utf-8")
        if setup == "empty":
            (fd / "notes.txt").write_text("x", encoding="utf-8")
        else:
            (fd / "IMG_1.jpg").write_bytes(b"x")
        (FAKE / c / "instances_clean.json").write_text(json.dumps({"annotations": [ann("IMG_9" if setup == "mismatch" else "IMG_1")]}), encoding="utf-8")
    (FAKE / "case_demo15" / "fluoroscopy.lnk").write_bytes(b"L\x00\x00\x00")         # โฟลเดอร์ฟลูเป็นทางลัด
    (FAKE / "case_demo14" / "fluoroscopy" / "old.lnk").write_bytes(b"L\x00\x00\x00")   # ทางลัดอื่นในเคสปกติ
    rp = OUT.parent / "_fluoro_missing_report.csv"
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools/report_fluoro_missing.py"), "--data-root", str(FAKE),
                        "--splits", str(good), "--out", str(rp)], capture_output=True, text=True, encoding="utf-8")
    import csv as _csv
    rows_ = list(_csv.DictReader(rp.open(encoding="utf-8-sig"))) if r.returncode == 0 else []
    got = {row["case"]: (row["cause"], row["split"]) for row in rows_}
    sc = {row["case"]: row["shortcuts"] for row in rows_}
    check(got.get("case_demo11", ("",))[0] == "no_folder" and got.get("case_demo12") == ("empty_folder", "test")
          and got.get("case_demo13") == ("name_mismatch", "test") and "รวมชุด test: 3" in r.stdout,
          "report_fluoro_missing: แยกสาเหตุ ไม่มีโฟลเดอร์ / ว่าง / ชื่อไม่ตรง + นับชุด test", f"{got} {r.stdout[-200:]}{r.stderr[-200:]}")
    check(got.get("case_demo15", ("",))[0] == "shortcut" and got.get("case_demo14", ("x",))[0] == ""
          and sc.get("case_demo14") == "fluoroscopy/old.lnk" and "ทางลัด" in r.stdout,
          "report_fluoro_missing: เจอโฟลเดอร์ฟลูที่เป็นทางลัด + ทางลัดอื่นในเคส", f"{got} {sc}")
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools/report_fluoro_missing.py"), "--data-root", str(FAKE),
                        "--splits", str(good), "--out", str(FAKE / "x_report.csv")], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode != 0 and not (FAKE / "x_report.csv").exists(), "report_fluoro_missing: ห้ามเขียนลงโฟลเดอร์ข้อมูล", "")

    # make_study_package --splits (ใช้ข้อมูลปลอมพร้อมภาพจาก test_make_package)
    if not PKG_FAKE.exists():
        check(False, "ต้องรัน tests/test_make_package.py ก่อน (สร้าง fake_data)")
    else:
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        sp = OUT.parent / "_splits_pkg.csv"
        sp.write_text("case_id,split\ncase_demo1,test\ncase_demo2,train\ncase_demo3,train\n", encoding="utf-8")
        cmd = [sys.executable, "-X", "utf8", "-B", str(ROOT / "tools/make_study_package.py"), "--data-root", str(PKG_FAKE),
               "--out-root", str(OUT), "--splits", str(sp), "--expect", "train=2,val=0,test=1", "--name", "synth", "--k", "3"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        out = r.stdout + r.stderr
        check(r.returncode == 0 and "ใช้ 1 เคสจากชุด test" in out and "case_demo1" in out and "case_demo2" not in out.split("ใช้ 1 เคส")[1],
              "make_study_package --splits: ใช้เฉพาะเคสชุด test", out[-300:])
        sp.write_text("case_id,split\ncase_demo1,test\ncase_demo3,train\n", encoding="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        check(r.returncode != 0 and "ไม่ผ่านการตรวจ" in (r.stdout + r.stderr), "make_study_package --splits: splits ผิด → หยุดก่อนอ่านภาพ",
              (r.stdout + r.stderr)[-200:])

    for ok, label, detail in results:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  -> {detail}"))
    n = sum(r[0] for r in results)
    print(f"\nผ่าน {n} / {len(results)} รายการ")
    sys.exit(0 if n == len(results) else 1)


if __name__ == "__main__":
    main()
