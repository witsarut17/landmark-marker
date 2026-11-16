"""ทดสอบ tools/make_original_package.py ด้วยภาพสังเคราะห์ (ไม่แตะข้อมูลจริง)

    .venv\\Scripts\\python -X utf8 -B tests/test_original_package.py

จำลองทุกกรณี: ต้นฉบับไม่มี EXIF (ภาพคลีนทาดำชื่อ + บันทึก JPEG ใหม่) · EXIF 2–8 (ภาพคลีนหมุนแล้ว) · BMP · ไม่มีต้นฉบับ
ต้นฉบับชื่อซ้ำ 2 ไฟล์ · ขนาดไม่เท่า · คนละภาพ · HEIC · งานซ้ำ · ป้องกันการเขียนในโปรเจกต์/G: · ภาพคลีนเปลี่ยน
แล้วเปิดแพ็กเกจที่ได้ในเว็บจริงครบทุกงาน (ตรวจชนิดไฟล์ EXIF ขนาด และใช้ fluoro_area จาก manifest)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from server.validate import load_manifest, public_manifest  # noqa: E402

SCRIPT = ROOT / "tools" / "make_original_package.py"
rows: list[tuple[bool, str, str]] = []
rng = np.random.default_rng(7)


def check(ok, label, detail=""):
    rows.append((bool(ok), label, str(detail)))


def scene(w, h, seed=0):
    r = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    a = 120 + 50 * np.sin(x / (23.0 + seed)) * np.cos(y / 17.0) + r.normal(0, 6, (h, w))
    a[h // 4:h // 4 + 30, w // 5:w // 5 + 70] = 235
    a[(x - w * 0.65) ** 2 + (y - h * 0.55) ** 2 < 600] = 40
    return Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert("RGB")


def to_bytes(im, fmt, **kw):
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


def exif_bytes(ori):
    ex = Image.Exif()
    ex[0x0112] = ori
    return ex.tobytes()


INV = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
       5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_90, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_270}


def stored_for(upright: Image.Image, ori: int) -> Image.Image:
    """ภาพที่กล้องเก็บไว้ (ยังไม่หมุน) ซึ่งเมื่อหมุนตาม EXIF ori แล้วได้ upright"""
    for cand in (upright.transpose(INV[ori]),) + tuple(upright.transpose(t) for t in Image.Transpose):
        im = Image.open(io.BytesIO(to_bytes(cand, "PNG", exif=exif_bytes(ori))))
        if ImageOps.exif_transpose(im).tobytes() == upright.tobytes():
            return cand
    raise AssertionError("หาทิศไม่ได้")


def mask_name(im: Image.Image) -> Image.Image:
    a = np.asarray(im).copy()
    a[5:30, 5:120] = 0
    return Image.fromarray(a)


def mask_circle(im: Image.Image) -> Image.Image:
    a = np.asarray(im).copy()
    h, w = a.shape[:2]
    y, x = np.mgrid[0:h, 0:w]
    a[(x - w / 2) ** 2 + (y - h / 2) ** 2 > (min(w, h) * 0.45) ** 2] = 0
    return Image.fromarray(a)


class Data:
    def __init__(self, tmp: Path):
        self.clean, self.orig, self.base = tmp / "clean", tmp / "orig", tmp / "base_package"
        self.base.mkdir(parents=True)
        self.items, self.key = [], []
        self.expect = {}                      # (task, side) -> (source, expected upright pixels or None)

    def put(self, case, side, name, clean_img: Image.Image, clean_fmt="JPEG", orig: list | None = None):
        """orig = [(ชื่อไฟล์, bytes)] · คืน (ชื่อไฟล์คลีน, sha, ขนาด)"""
        sd = "xray" if side == "xray" else "fluoroscopy"
        (self.clean / case / sd).mkdir(parents=True, exist_ok=True)
        (self.orig / case / sd).mkdir(parents=True, exist_ok=True)
        data = to_bytes(clean_img, clean_fmt, **({"quality": 95} if clean_fmt == "JPEG" else {}))
        (self.clean / case / sd / name).write_bytes(data)
        for oname, ob in orig or []:
            (self.orig / case / sd / oname).write_bytes(ob)
        return name, hashlib.sha256(data).hexdigest(), list(clean_img.size)

    def task(self, tid, case, x, f, box, repeat_of=None):
        self.items.append({"task_id": tid, "xray": f"{tid}_X.jpg", "fluoro": f"{tid}_F.jpg", "xray_size": x[2],
                           "fluoro_size": f[2], "box_xyxy": box, "is_repeat_of": repeat_of})
        self.key.append({"task_id": tid, "case": case, "annotation_id": "1", "image_id": "1", "xray_file": x[0],
                         "fluoro_file": f[0], "fluo_id": Path(f[0]).stem, "fluo_match": "exact", "fluo_flag": "",
                         "box_xyxy": json.dumps(box), "is_repeat_of": repeat_of or "",
                         "xray_sha256_source": x[1], "fluoro_sha256_source": f[1]})

    def save(self):
        (self.base / "manifest.json").write_text(json.dumps({"package_id": "pkg-base", "seed": 1, "k": 1, "items": self.items}),
                                                 encoding="utf-8")
        with (self.base.parent / "key.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(self.key[0]))
            w.writeheader()
            w.writerows(self.key)


def build(tmp: Path) -> Data:
    d = Data(tmp)
    W, H = 400, 300
    box = [40.5, 30.25, 360.0, 270.75]
    fl = mask_circle(scene(320, 320, 9))
    # T001: เอกซเรย์ไม่มี EXIF (คลีน = ทาดำชื่อ + JPEG ใหม่) · ฟลู EXIF 6 (คลีน = หมุนแล้ว + ทาดำนอกวงกลม)
    x1 = scene(W, H, 1)
    xo = to_bytes(x1, "JPEG", quality=92)
    x1_dec = Image.open(io.BytesIO(xo)).convert("RGB")
    f1 = scene(240, 320, 2)
    f1o = to_bytes(stored_for(f1, 6), "JPEG", quality=92, exif=exif_bytes(6))
    f1_up = ImageOps.exif_transpose(Image.open(io.BytesIO(f1o))).convert("RGB")
    X1 = d.put("case_a", "xray", "IMG_0001.jpg", mask_name(x1_dec), orig=[("IMG_0001.JPG", xo)])
    F1 = d.put("case_a", "fluoro", "IMG_0101.jpg", mask_circle(f1_up), orig=[("img_0101.jpg", f1o)])
    d.task("T001", "case_a", X1, F1, box)
    d.expect[("T001", "xray")] = ("original", x1_dec)
    d.expect[("T001", "fluoro")] = ("original", f1_up)
    # T002: เอกซเรย์ PNG ตรงกันทุกพิกเซล · ฟลู BMP (คลีน BMP ทาดำนอกวงกลม)
    x2 = scene(W, H, 3)
    X2 = d.put("case_a", "xray", "IMG_0002.png", x2, "PNG", orig=[("IMG_0002.png", to_bytes(x2, "PNG"))])
    f2 = scene(320, 320, 4)
    F2 = d.put("case_a", "fluoro", "F_0002.bmp", mask_circle(f2), "BMP", orig=[("F_0002.bmp", to_bytes(f2, "BMP"))])
    d.task("T002", "case_a", X2, F2, box)
    d.expect[("T002", "xray")] = ("original", x2)
    d.expect[("T002", "fluoro")] = ("original", f2)
    # T003: เอกซเรย์ EXIF 3 · ฟลูไม่มีต้นฉบับ
    x3 = scene(W, H, 5)
    x3o = to_bytes(stored_for(x3, 3), "JPEG", quality=92, exif=exif_bytes(3))
    x3_up = ImageOps.exif_transpose(Image.open(io.BytesIO(x3o))).convert("RGB")
    X3 = d.put("case_b", "xray", "IMG_0003.jpg", mask_name(x3_up), orig=[("IMG_0003.jpg", x3o)])
    F3 = d.put("case_b", "fluoro", "IMG_0103.jpg", fl, orig=[])
    d.task("T003", "case_b", X3, F3, box)
    d.expect[("T003", "xray")] = ("original", x3_up)
    d.expect[("T003", "fluoro")] = ("clean", None)
    # T004: เอกซเรย์ต้นฉบับขนาดต่าง (ย่อ) · ฟลูต้นฉบับชื่อซ้ำ 2 ไฟล์
    x4 = scene(W, H, 6)
    X4 = d.put("case_b", "xray", "IMG_0004.jpg", x4, orig=[("IMG_0004.jpg", to_bytes(x4.resize((800, 600)), "JPEG"))])
    F4 = d.put("case_b", "fluoro", "IMG_0104.jpg", fl, orig=[("IMG_0104.jpg", to_bytes(fl, "JPEG")), ("IMG_0104.png", to_bytes(fl, "PNG"))])
    d.task("T004", "case_b", X4, F4, box)
    d.expect[("T004", "xray")] = ("clean", None)
    d.expect[("T004", "fluoro")] = ("clean", None)
    # T014: เอกซเรย์ต้นฉบับชื่อ .png แต่เนื้อไฟล์เป็น JPEG (พบในข้อมูลจริง) → ใช้ได้ ไฟล์ในแพ็กเกจเป็น .jpg
    x14 = scene(W, H, 30)
    x14o = to_bytes(x14, "JPEG", quality=92)
    X14 = d.put("case_a", "xray", "IMG_0014.png", Image.open(io.BytesIO(x14o)).convert("RGB"), "PNG", orig=[("IMG_0014.png", x14o)])
    d.task("T014", "case_a", X14, F1, box)
    d.expect[("T014", "xray")] = ("original", Image.open(io.BytesIO(x14o)).convert("RGB"))
    d.expect[("T014", "fluoro")] = d.expect[("T001", "fluoro")]
    # T005: งานซ้ำของ T001
    d.task("T005", "case_a", X1, F1, box, repeat_of="T001")
    d.expect[("T005", "xray")] = d.expect[("T001", "xray")]
    d.expect[("T005", "fluoro")] = d.expect[("T001", "fluoro")]
    # T006: เอกซเรย์ต้นฉบับคนละภาพ (ขนาดเท่ากัน) · ฟลูต้นฉบับ HEIC (ยังไม่รองรับ)
    x6 = scene(W, H, 7)
    X6 = d.put("case_c", "xray", "IMG_0006.jpg", x6, orig=[("IMG_0006.jpg", to_bytes(scene(W, H, 8), "JPEG"))])
    F6 = d.put("case_c", "fluoro", "IMG_0106.jpg", fl, orig=[("IMG_0106.HEIC", b"not really heic")])
    d.task("T006", "case_c", X6, F6, box)
    d.expect[("T006", "xray")] = ("clean", None)
    d.expect[("T006", "fluoro")] = ("clean", None)
    # T007–T013: เอกซเรย์ EXIF 2..8 ทุกแบบ (ภาพคลีนหมุนตาม EXIF แล้ว) · ฟลูใช้ภาพ T002
    for i, ori in enumerate(range(2, 9)):
        tid = f"T{7 + i:03d}"
        up = scene(W, H, 20 + ori) if ori in (2, 3, 4) else scene(H, W, 20 + ori)
        ob = to_bytes(stored_for(up, ori), "JPEG", quality=92, exif=exif_bytes(ori))
        upd = ImageOps.exif_transpose(Image.open(io.BytesIO(ob))).convert("RGB")
        X = d.put("case_c", "xray", f"IMG_07{ori}.jpg", mask_name(upd), orig=[(f"IMG_07{ori}.jpg", ob)])
        b = [10.0, 10.0, float(upd.width - 10), float(upd.height - 10)]
        d.items.append({"task_id": tid, "xray": f"{tid}_X.jpg", "fluoro": f"{tid}_F.bmp", "xray_size": list(upd.size),
                        "fluoro_size": F2[2], "box_xyxy": b, "is_repeat_of": None})
        d.key.append({**d.key[1], "task_id": tid, "case": "case_c", "xray_file": X[0], "xray_sha256_source": X[1],
                      "box_xyxy": json.dumps(b), "is_repeat_of": "", "fluoro_file": F2[0], "fluoro_sha256_source": F2[1]})
        # ฟลูของ T002 อยู่ในเคส case_a → คัดลอกโครงไปเคส case_c ด้วย (คลีนและต้นฉบับ)
        for root, sub in ((d.clean, "fluoroscopy"), (d.orig, "fluoroscopy")):
            (root / "case_c" / sub).mkdir(parents=True, exist_ok=True)
            shutil.copy(root / "case_a" / sub / "F_0002.bmp", root / "case_c" / sub / "F_0002.bmp")
        d.expect[(tid, "xray")] = ("original", upd)
        d.expect[(tid, "fluoro")] = ("original", f2)
    d.save()
    return d


def run(d: Data, out: Path, *extra, key=None):
    cmd = [sys.executable, "-I", "-X", "utf8", "-B", str(SCRIPT), "--base-package", str(d.base),
           "--key", str(key or d.base.parent / "key.csv"), "--clean-root", str(d.clean), "--orig-root", str(d.orig),
           "--out", str(out), "--date", "20990101", *extra]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    tmp = Path(tempfile.mkdtemp(prefix="pelnav_orig_"))
    try:
        body(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for ok, label, detail in rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n = sum(1 for r in rows if r[0])
    print(f"\nผ่าน {n} / {len(rows)} รายการ")
    sys.exit(0 if n == len(rows) else 1)


def body(tmp: Path):
    d = build(tmp / "data")
    out = tmp / "private"

    r = run(d, out)
    check(r.returncode == 0 and (not out.exists() or not any(out.iterdir())),
          "dry-run: ตรวจทุกภาพแต่ไม่เขียนไฟล์", r.stderr[-400:] or r.stdout[-400:])
    check("งาน 14" in r.stdout and "ใช้ภาพคลีนเพราะ" in r.stdout and "IMG_0001" not in r.stdout and "img_0101" not in r.stdout,
          "dry-run: สรุปเป็นจำนวน ไม่แสดงชื่อไฟล์ต้นฉบับ", r.stdout[-600:])

    for bad, label in ((ROOT / "orig_test_out", "ในโฟลเดอร์โปรเจกต์"), (Path("G:/orig_test_out"), "ใน G:")):
        rb = run(d, bad, "--write")
        check(rb.returncode != 0 and not bad.exists(), f"ป้องกัน: ไม่ยอมเขียน{label}", rb.stdout[-200:] + rb.stderr[-200:])

    r = run(d, out, "--write")
    check(r.returncode == 0, "--write สร้างแพ็กเกจได้", r.stderr[-800:] or r.stdout[-800:])
    if r.returncode != 0:
        return
    pkg = out / "orig_package"
    m, _ = load_manifest(pkg)
    base = json.loads((d.base / "manifest.json").read_text(encoding="utf-8"))
    same = [(a["task_id"], a["box_xyxy"], a["xray_size"], a["fluoro_size"], a.get("is_repeat_of")) for a in m["items"]] == \
           [(b["task_id"], b["box_xyxy"], b["xray_size"], b["fluoro_size"], b.get("is_repeat_of")) for b in base["items"]]
    check(same and m["package_id"] == "pkg-orig-20990101" and m["based_on"] == "pkg-base",
          "manifest: งาน ลำดับ กรอบ ขนาด งานซ้ำ เหมือนแพ็กเกจเดิมทุกตัว · package_id ใหม่")
    txt = (pkg / "manifest.json").read_text(encoding="utf-8")
    check("IMG_0" not in txt and "case_" not in txt and "F_0002" not in txt, "manifest ไม่มีชื่อไฟล์ต้นฉบับหรือรหัสเคส")

    key = {r["task_id"]: r for r in csv.DictReader((out / "orig_key.csv").open(encoding="utf-8-sig"))}
    exp_clean = {t: "+".join(s for s in ("xray", "fluoro") if d.expect[(t, s)][0] == "clean") for t in key}
    check(all(key[t]["uses_clean_image"] == exp_clean[t] for t in key),
          "orig_key.csv บอกว่างานไหนใช้ภาพคลีน (ฝั่งไหน) ถูกทุกงาน", {t: (key[t]["uses_clean_image"], exp_clean[t]) for t in key})
    reasons = {key[t]["xray_fallback_reason"] for t in ("T004", "T006")} | {key[t]["fluoro_fallback_reason"] for t in ("T003", "T004", "T006")}
    check(any("ขนาด" in x for x in reasons) and any("ต่างจากภาพคลีน" in x or "กรอบ" in x for x in reasons)
          and any("ไม่พบ" in x for x in reasons) and any("2 ไฟล์" in x for x in reasons) and any(".heic" in x for x in reasons),
          "เหตุผลที่ใช้ภาพคลีน: ไม่พบ · ชื่อซ้ำ 2 ไฟล์ · ขนาดไม่เท่า · คนละภาพ · HEIC ยังไม่รองรับ", reasons)
    check(all(key[t]["xray_transform"] == "identity" and key[t]["fluoro_transform"] == "identity" for t in key),
          "การแปลงพิกัดเป็นเอกลักษณ์ทุกภาพ (พิกัดใช้กับภาพคลีนได้ตรง ๆ)")

    # พิกเซลในแพ็กเกจ
    bad_px, exif_left, size_bad = [], [], []
    for it in m["items"]:
        for side in ("xray", "fluoro"):
            data = (pkg / it[side]).read_bytes()
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                if len(im.getexif()):
                    exif_left.append(it[side])
                if list(im.size) != it[f"{side}_size"]:
                    size_bad.append(it[side])
                src, want = d.expect[(it["task_id"], side)]
                if src == "original":
                    if im.convert("RGB").tobytes() != want.convert("RGB").tobytes():
                        bad_px.append(it[side])
                else:
                    cl = key[it["task_id"]][f"{side}_clean_file"]
                    sd = "xray" if side == "xray" else "fluoroscopy"
                    case = key[it["task_id"]]["case"]
                    ref = Image.open(d.clean / case / sd / cl).convert("RGB")
                    if im.convert("RGB").tobytes() != ref.tobytes():
                        bad_px.append(it[side])
    check(not bad_px, "พิกเซลในแพ็กเกจ = ต้นฉบับที่หมุนตาม EXIF (EXIF 2–8 ทุกแบบ, BMP, ไม่มี EXIF) หรือ = ภาพคลีนเมื่อใช้ภาพคลีน", bad_px)
    check(not exif_left and not size_bad, "ไม่มี EXIF เหลือ · ขนาดทุกภาพเท่า manifest (= ภาพคลีน)", (exif_left, size_bad))
    t14 = next(it for it in m["items"] if it["task_id"] == "T014")
    check(t14["xray"].endswith(".jpg") and (pkg / t14["xray"]).read_bytes()[:2] == bytes([0xFF, 0xD8])
          and "ไม่ตรงชนิดจริง" in key["T014"]["xray_conversion"],
          "ต้นฉบับนามสกุล .png แต่เป็น JPEG จริง → ใช้ได้ ไฟล์ในแพ็กเกจเป็น .jpg และบันทึกใน key")
    check(m["items"][1]["fluoro"].endswith(".png") and any(it["xray"].endswith(".png") for it in m["items"][6:]),
          "BMP และภาพที่ต้องหมุน → PNG ไม่สูญเสีย")
    t1 = next(it for it in m["items"] if it["task_id"] == "T001")
    x1_pkg = (pkg / t1["xray"]).read_bytes()
    x1_src = (d.orig / "case_a" / "xray" / "IMG_0001.JPG").read_bytes()
    check(x1_pkg[:2] == b"\xff\xd8" and len(x1_pkg) <= len(x1_src) and x1_pkg[-2000:] == x1_src[-2000:],
          "JPEG ไม่หมุน: ใช้ไบต์เดิม (ตัด metadata) ไม่เข้ารหัสใหม่")
    a = np.asarray(Image.open(d.clean / "case_a" / "fluoroscopy" / "IMG_0101.jpg").convert("RGB"), dtype=np.int32)
    check(all(isinstance(it["fluoro_area"], int) for it in m["items"]) and t1["fluoro_area"] == int((a.sum(axis=2) > 36).sum()),
          "fluoro_area = พื้นที่ไม่ดำของภาพคลีน (เกณฑ์เดียวกับเว็บ)", t1["fluoro_area"])
    pm = public_manifest(m)
    check(all("fluoro_area" in it for it in pm["items"]), "เซิร์ฟเวอร์ส่ง fluoro_area ให้หน้าเว็บ")
    checks = sorted(p.name for p in (out / "orig_check").iterdir())
    check(len(checks) == 14 and any("_CLEAN-" in c for c in checks), "ภาพตรวจของทีมครบทุกงาน · งานที่ใช้ภาพคลีนมีป้าย _CLEAN", checks[:4])

    r2 = run(d, out, "--write")
    check(r2.returncode != 0 and "--overwrite" in r2.stdout + r2.stderr, "มีผลเดิม → ไม่เขียนทับถ้าไม่ใส่ --overwrite")

    # ภาพคลีนเปลี่ยน → หยุด
    k2 = d.base.parent / "key_bad.csv"
    rows_k = list(csv.DictReader((d.base.parent / "key.csv").open(encoding="utf-8-sig")))
    rows_k[0]["xray_sha256_source"] = "0" * 64
    with k2.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_k[0]))
        w.writeheader()
        w.writerows(rows_k)
    r3 = run(d, tmp / "private2", key=k2)
    check(r3.returncode != 0 and "sha256" in r3.stdout + r3.stderr, "ภาพคลีนไม่ตรง key.csv เดิม → หยุด")

    web_check(pkg)


def web_check(pkg: Path):
    """เปิดแพ็กเกจในเว็บจริง: ทุกงานโหลดภาพผ่านการตรวจของเว็บ และใช้ fluoro_area จาก manifest"""
    from playwright.sync_api import sync_playwright
    from server_fixture import TestServer
    srv = TestServer(packages=())
    try:
        srv.register("orig", pkg)
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="msedge")
            p = br.new_page()
            srv.open(p, "orig")
            p.wait_for_function("() => window.__marker.state.imagesReady", timeout=20000)
            n = p.evaluate("() => window.__marker.state.manifest.items.length")
            bad = []
            for i in range(n):
                p.evaluate(f"() => window.__marker.showTask({i})")
                p.wait_for_function(f"() => window.__marker.state.index === {i} && window.__marker.state.imagesReady", timeout=20000)
                area = p.evaluate("() => window.__marker.state.fluoroArea")
                want = p.evaluate(f"() => window.__marker.state.manifest.items[{i}].fluoro_area")
                if not p.is_hidden("#errorModal") or area != want:
                    bad.append((i, area, want))
            br.close()
        check(n == 14 and not bad, "เปิดในเว็บครบทุกงาน ไม่มีหน้าต่างหยุด · เว็บใช้ fluoro_area จาก manifest", bad)
    finally:
        srv.stop()


if __name__ == "__main__":
    main()
