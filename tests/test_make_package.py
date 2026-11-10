"""ทดสอบ tools/make_study_package.py ด้วยข้อมูลปลอม (จำลองทุกกรณีที่พบในข้อมูลจริง) — ไม่แตะข้อมูลจริง

รัน:  .venv\\Scripts\\python tests/test_make_package.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tests" / "generated"
FAKE = GEN / "fake_data"
OUT = GEN / "_pkgtest"
SCRIPT = ROOT / "tools" / "make_study_package.py"
sys.path.insert(0, str(ROOT / "tools"))
import make_study_package as M  # noqa: E402

results = []


def check(ok, label, detail=""):
    results.append((bool(ok), label, detail))


def img(w, h, seed, mode="RGB"):
    im = Image.new(mode, (w, h), (40, 40, 40) if mode == "RGB" else 40)
    d = ImageDraw.Draw(im)
    for i in range(30):
        x, y = (seed * 37 + i * 91) % w, (seed * 53 + i * 67) % h
        d.ellipse([x - 30, y - 20, x + 30, y + 20], fill=(150 + i * 3, 120, 90) if mode == "RGB" else 150 + i * 3)
    return im


def save_jpg(im, path, orientation=None, extra_exif=True):
    ex = Image.Exif()
    if extra_exif:
        ex[0x010F] = "FakeCam"           # Make
        ex[0x9003] = "2020:01:01 10:00:00"
    if orientation is not None:
        ex[0x0112] = orientation
    im.save(path, "JPEG", quality=92, exif=ex.tobytes())


def build_fake():
    if FAKE.exists():
        shutil.rmtree(FAKE)
    c1 = FAKE / "case_demo1"
    c2 = FAKE / "case_demo2"
    for c in (c1, c2):
        (c / "xray").mkdir(parents=True)
        (c / "fluoroscopy").mkdir(parents=True)
        (c / "fluoroscopy" / "desktop.ini").write_text("x")
    # case 1: เอกซเรย์
    save_jpg(img(1000, 800, 1), c1 / "xray" / "SCREENHUNTER 1.jpg")           # ชื่อใน COCO ตัวพิมพ์ต่าง
    pn = img(900, 700, 2, "L")
    from PIL import PngImagePlugin
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "patient-like text")
    pn.save(c1 / "xray" / "B.png", pnginfo=meta)
    save_jpg(img(1000, 800, 3), c1 / "xray" / "C.jpg")                        # COCO บอกขนาดผิด
    save_jpg(img(1000, 800, 4), c1 / "xray" / "D.jpg", orientation=6)         # EXIF หมุน
    # case 1: ฟลู
    for i in range(1, 13):
        save_jpg(img(640, 480, 10 + i), c1 / "fluoroscopy" / f"IMG_{i:04d}.JPG", orientation=3 if i == 12 else 1)
    save_jpg(img(640, 480, 77), c1 / "fluoroscopy" / "IMG_0042.JPG")          # เลข 0042 ตรงได้ 2 ภาพ
    save_jpg(img(640, 480, 78), c1 / "fluoroscopy" / "DSC_0042.JPG")
    images = [
        {"id": 1, "width": 1000, "height": 800, "file_name": "ScreenHunter 1.jpg"},
        {"id": 2, "width": 900, "height": 700, "file_name": "B.png"},
        {"id": 3, "width": 1001, "height": 800, "file_name": "C.jpg"},
        {"id": 4, "width": 1000, "height": 800, "file_name": "D.jpg"},
    ]

    def ann(aid, iid, fid, bbox=(100, 100, 300, 200), rot=0.0):
        return {"id": aid, "image_id": iid, "category_id": 1, "bbox": list(bbox), "segmentation": [], "area": 1, "iscrowd": 0,
                "attributes": {"fluo_id": fid, "occluded": False, "rotation": rot}}
    anns = [ann(1, 1, "IMG_0001"), ann(2, 1, "0002"), ann(3, 2, "IMG_0003", (50.5, 60.25, 400, 300)),
            ann(4, 1, "IMG_0004rotate"), ann(5, 1, "IMG_0005"), ann(6, 1, "IMG_0005"), ann(7, 3, "IMG_0007"),
            ann(8, 4, "IMG_0008"), ann(9, 1, "IMG_0099"), ann(10, 1, "IMG_0010", rot=15.0),
            ann(11, 1, "IMG_0011", (900, 700, 300, 200)), ann(12, 1, "IMG_0012"),
            ann(13, 1, "IMG_0006", (-0.5, 0, 1000.4, 800)),                    # เกินขอบ ≤ 1 px -> ตัดให้พอดี
            ann(14, 1, "0042")]                                                   # หลวมแต่ตรงหลายภาพ -> ตัด                   # เกินขอบ ≤ 1 px -> ตัดให้พอดี
    (c1 / "instances_clean.json").write_text(json.dumps({"images": images, "annotations": anns,
                                                         "categories": [{"id": 1, "name": "fluo_area"}]}), encoding="utf-8")
    # case 2: 5 คู่ปกติ
    save_jpg(img(1200, 900, 20), c2 / "xray" / "IMG_5000.jpg")
    for i in range(1, 6):
        save_jpg(img(700, 700, 30 + i), c2 / "fluoroscopy" / f"IMG_{6000 + i}.JPG")
    anns2 = [ann(100 + i, 1, f"IMG_{6000 + i}", (100 + i * 10, 100, 500, 400)) for i in range(1, 6)]
    (c2 / "instances_clean.json").write_text(json.dumps({"images": [{"id": 1, "width": 1200, "height": 900, "file_name": "IMG_5000.jpg"}],
                                                         "annotations": anns2}), encoding="utf-8")
    # case 3: ภาพ BMP + fluo_id มีคำต่อท้าย (flip)
    c3 = FAKE / "case_demo3"
    (c3 / "xray").mkdir(parents=True)
    (c3 / "fluoroscopy").mkdir(parents=True)
    img(1100, 850, 40).save(c3 / "xray" / "X1.bmp")                                  # เอกซเรย์ BMP
    save_jpg(img(1000, 800, 41), c3 / "xray" / "X2.jpg")
    img(600, 600, 50).save(c3 / "fluoroscopy" / "IMG_7001.bmp")                      # RGB BMP
    img(600, 600, 51, "L").save(c3 / "fluoroscopy" / "IMG_7002.BMP")                 # เทา BMP
    img(600, 600, 52).convert("P", palette=Image.ADAPTIVE, colors=64).save(c3 / "fluoroscopy" / "IMG_7003.bmp")   # palette BMP
    save_jpg(img(600, 600, 53), c3 / "fluoroscopy" / "IMG_7004FLIP.jpg")             # มีแต่ไฟล์ชื่อมีคำต่อท้าย -> ใช้
    save_jpg(img(600, 600, 54), c3 / "fluoroscopy" / "IMG_7005.jpg")                 # มีแต่ไฟล์ชื่อหลัก -> ใช้ (flip เป็นหมายเหตุหมอ)
    save_jpg(img(600, 600, 55), c3 / "fluoroscopy" / "IMG_7006flip.jpg")             # ชื่อมีคำต่อท้ายตรง 2 ไฟล์ -> ตัด
    img(600, 600, 56).save(c3 / "fluoroscopy" / "IMG_7006FLIP.bmp")
    img(600, 600, 57).save(c3 / "fluoroscopy" / "IMG_7007rotate.bmp")                # rotate + BMP -> ใช้
    save_jpg(img(600, 600, 58), c3 / "fluoroscopy" / "IMG_7009.jpg")                 # ชื่อหลักมีกรอบอื่นด้วย -> ตัดทั้งคู่
    save_jpg(img(600, 600, 59), c3 / "fluoroscopy" / "IMG_7010.jpg")                 # สะกด 'fip' -> ถือเป็น flip
    save_jpg(img(600, 600, 60), c3 / "fluoroscopy" / "IMG_7011.jpg")                 # มีทั้งชื่อหลักและชื่อมีคำต่อท้าย -> ตัด
    save_jpg(img(600, 600, 61), c3 / "fluoroscopy" / "IMG_7011FLIP.jpg")
    save_jpg(img(600, 600, 62), c3 / "fluoroscopy" / "IMG_7012.jpg")                 # fluo_id flip ซ้ำ 2 กรอบ -> ตัด แต่ยังนับเป็น flip
    imgs3 = [{"id": 1, "width": 1100, "height": 850, "file_name": "X1.bmp"}, {"id": 2, "width": 1000, "height": 800, "file_name": "X2.jpg"}]
    anns3 = [ann(201, 2, "IMG_7001"), ann(202, 2, "IMG_7002"), ann(203, 2, "IMG_7003"), ann(204, 1, "IMG_7004flip"),
             ann(205, 2, "IMG_7005flip"), ann(206, 2, "IMG_7006flip"), ann(207, 2, "IMG_7007rotate"), ann(208, 2, "IMG_7008flip"),
             ann(209, 2, "IMG_7009"), ann(210, 2, "IMG_7009flip"), ann(211, 2, "IMG_7010fip"), ann(212, 2, "IMG_7011flip"),
             ann(213, 2, "IMG_7012flip"), ann(214, 2, "IMG_7012flip")]
    (c3 / "instances_clean.json").write_text(json.dumps({"images": imgs3, "annotations": anns3}), encoding="utf-8")


def snapshot(root: Path):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*")) if p.is_file()}


def run(*extra):
    cmd = [sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--data-root", str(FAKE), "--out-root", str(OUT),
           "--cases", "case_demo1,case_demo2", "--name", "synth", "--k", "3", "--repeat-frac", "0.5", "--min-gap", "1", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def main():
    build_fake()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    before = snapshot(FAKE)

    code, out = run()
    check(code == 0 and "DRY-RUN" in out and not any(OUT.iterdir()), "dry-run ไม่เขียนอะไร", out[-300:] if code else "")
    check("กรอบทั้งหมด 19" in out and "ผ่านตรวจ 10" in out and "loose_ambiguous" in out, "dry-run สรุปจำนวนถูก (19 กรอบ ผ่าน 10) + ตารางรายเคส", [l for l in out.splitlines() if "กรอบทั้งหมด" in l])

    code, out = run("--write")
    check(code == 0, "สร้างแพ็กเกจได้", out[-500:])
    pkg = OUT / "synth_package"
    man = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    items = man["items"]
    rep = list(csv.DictReader((OUT / "synth_report.csv").open(encoding="utf-8-sig")))
    status = {int(r["annotation_id"]): (r["status"], r["problems"], r["notes"]) for r in rep}

    exp_ok = {1, 2, 3, 4, 13, 101, 102, 103, 104, 105}     # 4 = rotate → ใช้ไฟล์ชื่อหลัก
    got_ok = {a for a, s in status.items() if s[0] == "ok"}
    check(got_ok == exp_ok, "คู่ที่ผ่านตรวจถูกต้อง", f"ได้ {sorted(got_ok)} ควร {sorted(exp_ok)}")
    why = {
        5: "ซ้ำ", 6: "ซ้ำ", 7: "ขนาดเอกซเรย์จริง", 8: "EXIF Orientation = 6",
        9: "ไม่พบภาพฟลู", 10: "กรอบหมุน", 11: "กรอบเกินภาพ", 12: "EXIF Orientation = 3",
        14: "จับคู่หลวมได้ 2 ภาพ",
    }
    for a, w in why.items():
        check(w in status[a][1], f"ไม่ผ่านด้วยเหตุผลถูก: annotation {a} ({w})", status[a][1])
    check("ตัวพิมพ์" in status[1][2] and "หลวม" in status[2][2] and "ตัดให้พอดี" in status[13][2],
          "หมายเหตุ: ชื่อต่างตัวพิมพ์ / จับคู่หลวม / กรอบเกินขอบเล็กน้อย", f"{status[1][2]} | {status[2][2]} | {status[13][2]}")

    n_orig = sum(1 for it in items if not it["is_repeat_of"])
    n_rep = sum(1 for it in items if it["is_repeat_of"])
    check(n_orig == 6 and n_rep == 3, "k=3 ต่อเคส + งานซ้ำ 50%", f"ต้นฉบับ {n_orig} ซ้ำ {n_rep}")
    ids = [it["task_id"] for it in items]
    check(ids == [f"T{i:03d}" for i in range(1, len(ids) + 1)], "รหัสงาน T001.. ต่อเนื่อง", str(ids))
    pos = {t: i for i, t in enumerate(ids)}
    check(all(pos[it["task_id"]] - pos[it["is_repeat_of"]] > 1 for it in items if it["is_repeat_of"]), "งานซ้ำห่างงานต้นฉบับ > min-gap", "")

    keyrows = {r["task_id"]: r for r in csv.DictReader((OUT / "synth_key.csv").open(encoding="utf-8-sig"))}
    allok = True
    for it in items:
        for side in ("xray", "fluoro"):
            data = (pkg / it[side]).read_bytes()
            with Image.open(io.BytesIO(data)) as im:
                if len(im.getexif()) or tuple(im.size) != tuple(it[f"{side}_size"]) or "Comment" in im.info:
                    allok = False
            if data[:2] == b"\xff\xd8" and b"Exif\x00\x00" in data[:4096]:
                allok = False
            src_case = keyrows[it["task_id"]]["case"]
            src = FAKE / src_case / ("xray" if side == "xray" else "fluoroscopy") / keyrows[it["task_id"]][f"{side}_file"]
            if M.pixels_digest(src.read_bytes()) != M.pixels_digest(data):
                allok = False
    check(allok, "ภาพในแพ็กเกจ: ไม่มี EXIF/ข้อความ, ขนาดตรง manifest, พิกเซลเหมือนต้นฉบับทุกจุด", "")
    ann3 = next(it for it in items if keyrows[it["task_id"]]["annotation_id"] == "3")
    check(ann3["box_xyxy"] == [50.5, 60.25, 450.5, 360.25] and ann3["xray"].endswith(".png"),
          "กรอบแปลง xywh → xyxy ถูก + นามสกุลเดิม (.png)", str(ann3))
    ann13 = next((it for it in items if keyrows[it["task_id"]]["annotation_id"] == "13"), None)
    check(ann13 is None or ann13["box_xyxy"] == [0.0, 0.0, 999.9, 800.0], "กรอบเกินขอบ ≤ 1 px ถูกตัดให้อยู่ในภาพ", str(ann13))

    leak = [f.name for f in pkg.iterdir() if "case" in f.name.lower() or "IMG_" in f.name or "SCREEN" in f.name.upper()]
    mtext = (pkg / "manifest.json").read_text(encoding="utf-8")
    check(not leak and "case_demo" not in mtext and "IMG_" not in mtext, "แพ็กเกจไม่มีรหัสเคส/ชื่อไฟล์เดิม", str(leak))
    check(len(list((OUT / "synth_check").glob("T*.jpg"))) == len(items), "ภาพตรวจครบทุกงาน", "")
    check(snapshot(FAKE) == before, "ข้อมูลต้นฉบับไม่ถูกแก้ไข (mtime + sha256 เท่าเดิม)", "")

    # สร้างซ้ำด้วย seed เดิม -> ผลเหมือนเดิม
    first = [(it["task_id"], keyrows[it["task_id"]]["annotation_id"], it["is_repeat_of"]) for it in items]
    code, out = run("--write")
    check(code != 0 and "--overwrite" in out, "มีผลเดิมแล้ว ไม่ใส่ --overwrite = ไม่ทับ", "")
    code, out = run("--write", "--overwrite")
    items2 = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))["items"]
    key2 = {r["task_id"]: r for r in csv.DictReader((OUT / "synth_key.csv").open(encoding="utf-8-sig"))}
    second = [(it["task_id"], key2[it["task_id"]]["annotation_id"], it["is_repeat_of"]) for it in items2]
    check(first == second, "seed เดิม = แพ็กเกจเดิมทุกงาน", "")

    # เลือกทุกคู่ (k ใหญ่) -> ตรวจป้ายจับคู่หลวม + สรุปรายเคส
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--data-root", str(FAKE), "--out-root", str(OUT),
                        "--cases", "case_demo1,case_demo2", "--name", "all", "--k", "50", "--repeat-frac", "0", "--write"],
                       capture_output=True, text=True, encoding="utf-8")
    keyall = list(csv.DictReader((OUT / "all_key.csv").open(encoding="utf-8-sig")))
    loose_tasks = [k["task_id"] for k in keyall if k["fluo_match"] == "loose_digits"]
    loose_imgs = sorted(f.name for f in (OUT / "all_check").glob("*_LOOSE.jpg"))
    check(r.returncode == 0 and len(loose_tasks) == 1 and loose_imgs == [f"{loose_tasks[0]}_LOOSE.jpg"],
          "ภาพตรวจของงานจับคู่หลวมมี _LOOSE ท้ายชื่อ (เฉพาะงานนั้น)", f"{loose_tasks} {loose_imgs}")
    summ = {row["case"]: row for row in csv.DictReader((OUT / "all_summary_by_case.csv").open(encoding="utf-8-sig"))}
    exp = {"boxes": 14, "ok": 5, "dup_fluo_id": 2, "fluo_not_found": 1, "loose_ambiguous": 1,
           "size_mismatch": 1, "exif_orientation": 2, "box_rotated": 1, "box_bad": 1, "excluded": 9, "loose_used": 1,
           "rotate_used": 1, "selected": 5, "selected_loose": 1}
    got = {k: int(summ["case_demo1"][k]) for k in exp}
    check(got == exp and int(summ["case_demo2"]["ok"]) == 5, "สรุปรายเคส: จำนวนตัดออกแยกตามสาเหตุถูก", f"{got}")
    rep_all = list(csv.DictReader((OUT / "all_report.csv").open(encoding="utf-8-sig")))
    check(all(r_["category"] for r_ in rep_all if r_["status"] == "excluded") and
          any(r_["fluo_match"] == "loose_digits" and "หลวม" in r_["notes"] for r_ in rep_all),
          "รายงาน: ทุกกรอบที่ตัดมีสาเหตุ + กรอบจับคู่หลวมถูกบันทึก", "")

    # BMP → PNG แบบไม่เสียคุณภาพ + กติกาคำต่อท้าย (flip/rotate)
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--data-root", str(FAKE), "--out-root", str(OUT),
                        "--cases", "case_demo3", "--name", "bmp", "--k", "50", "--repeat-frac", "0", "--write"],
                       capture_output=True, text=True, encoding="utf-8")
    rep3 = {int(r_["annotation_id"]): r_ for r_ in csv.DictReader((OUT / "bmp_report.csv").open(encoding="utf-8-sig"))} if r.returncode == 0 else {}
    ok3 = {a for a, r_ in rep3.items() if r_["status"] == "ok"}
    check(ok3 == {201, 202, 203, 204, 205, 207, 211},
          "flip/rotate: ใช้ไฟล์ชื่อหลักหรือชื่อมีคำต่อท้ายได้ ถ้ารวมกันเจอภาพเดียว · BMP ทุกโหมดสีผ่าน",
          f"{sorted(ok3)} {r.stdout[-300:]}{r.stderr[-300:]}")
    match3 = {a: (rep3.get(a, {}).get("fluo_match"), rep3.get(a, {}).get("fluo_flag")) for a in (204, 205, 207, 211)}
    check(match3 == {204: ("suffix_exact", "flip"), 205: ("suffix_base", "flip"), 207: ("suffix_exact", "rotate"), 211: ("suffix_base", "flip")},
          "รายงาน: บอกว่าใช้ไฟล์ชื่อหลัก/ชื่อมีคำต่อท้าย + flip/rotate แยกกัน (สะกด fip = flip)", str(match3))
    why3 = {206: ("หลายไฟล์", "loose_ambiguous"), 208: ("ไม่พบไฟล์ฟลูทั้งชื่อหลัก", "flag_no_file"),
            209: ("มีกรอบอื่นด้วย", "fluo_reused"), 210: ("มีกรอบอื่นด้วย", "flag_shared"), 212: ("หลายไฟล์", "loose_ambiguous")}
    got3 = {a: (rep3.get(a, {}).get("problems", ""), rep3.get(a, {}).get("category")) for a in why3}
    check(all(w in got3[a][0] and got3[a][1] == c for a, (w, c) in why3.items()),
          "flip/rotate ตัดออก: ไม่พบไฟล์ / ตรงหลายไฟล์ / ภาพเดียวมี 2 กรอบ (ตัดทั้งคู่) + สาเหตุแยกหมวด", str(got3))
    check("BMP" in rep3.get(201, {}).get("notes", "") and "หมอระบุ flip" in rep3.get(205, {}).get("notes", "")
          and "fip" in rep3.get(211, {}).get("notes", ""), "รายงาน: หมายเหตุแปลง BMP / หมอระบุ flip / คำสะกดที่เขียนจริง",
          str({a: rep3.get(a, {}).get("notes") for a in (201, 205, 211)}))
    check("flip (หมอระบุใน fluo_id): 9 กรอบ · ใช้ได้ 3" in r.stdout and "rotate (หมอระบุใน fluo_id): 1 กรอบ · ใช้ได้ 1" in r.stdout,
          "dry-run/สร้าง: สรุปจำนวน flip/rotate ที่ใช้ได้และที่ตัด", [l for l in r.stdout.splitlines() if "หมอระบุใน" in l])
    if r.returncode == 0:
        pk3 = OUT / "bmp_package"
        it3 = json.loads((pk3 / "manifest.json").read_text(encoding="utf-8"))["items"]
        k3 = {r_["task_id"]: r_ for r_ in csv.DictReader((OUT / "bmp_key.csv").open(encoding="utf-8-sig"))}
        pix_ok = conv_ok = True
        for it in it3:
            kr = k3[it["task_id"]]
            for side, folder in (("xray", "xray"), ("fluoro", "fluoroscopy")):
                src = FAKE / "case_demo3" / folder / kr[f"{side}_file"]
                data = (pk3 / it[side]).read_bytes()
                if src.suffix.lower() == ".bmp":
                    conv_ok &= it[side].endswith(".png") and data[:8] == M.PNG_SIG and "lossless" in kr[f"{side}_converted"]
                else:
                    conv_ok &= not kr[f"{side}_converted"]
                pix_ok &= M.pixels_digest(src.read_bytes()) == M.pixels_digest(data)
        check(conv_ok, "BMP → ไฟล์ .png ในแพ็กเกจ + key.csv บันทึกการแปลง (เอกซเรย์และฟลู)", "")
        check(pix_ok, "BMP → PNG: พิกเซลเหมือนต้นฉบับทุกจุด (RGB / เทา / palette)", "")
        check("flip" not in (pk3 / "manifest.json").read_text(encoding="utf-8").lower()
              and "rotate" not in (pk3 / "manifest.json").read_text(encoding="utf-8").lower(), "manifest ไม่บอกหมอว่าภาพกลับด้าน/หมุน", "")
        flags = {kr["annotation_id"]: kr["fluo_flag"] for kr in k3.values()}
        check(flags.get("205") == "flip" and flags.get("207") == "rotate" and flags.get("201") == ""
              and rep3.get(213, {}).get("fluo_flag") == "flip" and "ซ้ำ" in rep3.get(213, {}).get("problems", ""),
              "key.csv: บันทึก fluo_flag (flip / rotate) ของคู่ที่หมอระบุ", str(flags))
        sm3 = next(csv.DictReader((OUT / "bmp_summary_by_case.csv").open(encoding="utf-8-sig")))
        want = {"flip_used": "3", "rotate_used": "1", "bmp_used": "4", "flag_no_file": "1", "flag_shared": "1", "fluo_reused": "1", "loose_ambiguous": "2"}
        check({k: sm3[k] for k in want} == want, "สรุปรายเคส: flip/rotate ใช้ · bmp ใช้ · สาเหตุที่ตัดแยกหมวด", str({k: sm3[k] for k in want}))

    # ป้องกันเขียนลงข้อมูลจริง / นอก .gitignore
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--data-root", str(FAKE), "--out-root", str(FAKE),
                        "--cases", "case_demo2", "--name", "synth"], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode != 0 and "ข้อมูลจริง" in (r.stdout + r.stderr), "ห้ามเขียนลงโฟลเดอร์ข้อมูล", "")
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--data-root", str(FAKE), "--out-root", str(ROOT / "tools"),
                        "--cases", "case_demo2", "--name", "synth"], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode != 0 and ".gitignore" in (r.stdout + r.stderr), "ห้ามเขียนลงที่ที่ไม่อยู่ใน .gitignore", "")

    for ok, label, detail in results:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  -> {detail}"))
    n = sum(r[0] for r in results)
    print(f"\nผ่าน {n} / {len(results)} รายการ")
    sys.exit(0 if n == len(results) else 1)


if __name__ == "__main__":
    main()
