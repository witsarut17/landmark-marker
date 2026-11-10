"""สร้าง "แพ็กเกจทดสอบ" จากภาพสังเคราะห์ (ไม่มีข้อมูลผู้ป่วย) ใช้ทดสอบความถูกต้องของพิกัด

วิธีใช้ (จากโฟลเดอร์โปรเจกต์):
    python tests/make_test_images.py

ผลลัพธ์อยู่ใน tests/generated/
    test_package/        แพ็กเกจปกติ 5 งาน (ภาพแนวนอน/แนวตั้ง, 4032x3024, 800x600, ฟลูวงกลม, งานซ้ำ)
        targets.json     ตำแหน่งกากบาทที่ถูกต้องของทุกภาพ (ใช้เทียบตอนทดสอบ)
    bad_size_package/    manifest ระบุขนาดผิด      -> เว็บต้อง "หยุดและแจ้งเตือน"
    bad_exif_package/    ภาพมี EXIF Orientation=6  -> เว็บต้อง "หยุดและแจ้งเตือน"

มาตรฐานพิกัด: origin = มุมซ้ายบนของพิกเซลซ้ายบน, กึ่งกลางพิกเซล (i, j) = (i+0.5, j+0.5)
กากบาทที่ (u, v) วาดเป็นเส้นหนา 2 พิกเซล ครอบคอลัมน์ u-1 และ u -> เส้นกึ่งกลางอยู่ที่ x = u.0 พอดี
ตรงกลางเว้นช่องว่างเล็ก ๆ ให้เห็นจุดศูนย์กลางชัด
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "generated"


def get_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow เก่า
        return ImageFont.load_default()


def general_targets(w: int, h: int) -> list[tuple[int, int]]:
    return [(100, 200), (w // 2, h // 2), (w - 150, h - 120), (250, h - 300), (w - 300, 150)]


def circle_targets(cx: int, cy: int, r: int) -> list[tuple[int, int]]:
    d = int(r * 0.6)
    q = int(r * 0.42)
    return [(cx, cy), (cx - d, cy), (cx + d, cy), (cx, cy - d), (cx + q, cy + q)]


def draw_image(w: int, h: int, targets, mode: str = "L", circle=None) -> Image.Image:
    bg = 70 if mode == "L" else (70, 70, 80)
    img = Image.new(mode, (w, h), bg)
    d = ImageDraw.Draw(img)
    grid = 110 if mode == "L" else (110, 110, 125)
    major = 150 if mode == "L" else (150, 150, 170)
    white = 255 if mode == "L" else (255, 255, 255)
    edge = 220 if mode == "L" else (230, 60, 60)
    fs = max(14, min(w, h) // 60)
    font = get_font(fs)

    # เส้นกริดทุก 100 px (วาดที่คอลัมน์/แถว 100k) เส้นหลักทุก 500 px พร้อมเลข
    for x in range(100, w, 100):
        d.line([(x, 0), (x, h - 1)], fill=major if x % 500 == 0 else grid)
        if x % 500 == 0:
            d.text((x + 3, 3), str(x), fill=major, font=font)
    for y in range(100, h, 100):
        d.line([(0, y), (w - 1, y)], fill=major if y % 500 == 0 else grid)
        if y % 500 == 0:
            d.text((3, y + 3), str(y), fill=major, font=font)

    # ขอบภาพ: คอลัมน์/แถวแรกและสุดท้าย (ใช้ตรวจว่าขอบซ้าย ≈ 0 และขอบขวา ≈ W)
    d.rectangle([0, 0, w - 1, h - 1], outline=edge)

    if circle is not None:
        cx, cy, r = circle
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        black = Image.new(mode, (w, h), 0)
        img = Image.composite(img, black, mask)
        d = ImageDraw.Draw(img)

    arm = max(30, min(w, h) // 25)
    gap = 4
    for i, (u, v) in enumerate(targets, start=1):
        # แนวตั้ง: คอลัมน์ u-1..u (Pillow รวมจุดปลายทั้งสอง)
        d.rectangle([u - 1, v - arm, u, v - gap], fill=white)
        d.rectangle([u - 1, v + gap - 1, u, v + arm], fill=white)
        # แนวนอน: แถว v-1..v
        d.rectangle([u - arm, v - 1, u - gap, v], fill=white)
        d.rectangle([u + gap - 1, v - 1, u + arm, v], fill=white)
        d.text((u + 10, v + 10), f"{i} ({u},{v})", fill=white, font=font)
    return img


def save(img: Image.Image, path: Path, exif_orientation: int | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        kwargs = {"quality": 95}
        if exif_orientation is not None:
            exif = Image.Exif()
            exif[0x0112] = exif_orientation
            kwargs["exif"] = exif.tobytes()
        img.convert("RGB" if img.mode not in ("L", "RGB") else img.mode).save(path, "JPEG", **kwargs)
    else:
        img.save(path, "PNG")


# (task, X size, X ext, F size, F ext, F has circle)
SPECS = [
    ("T001", (4032, 3024), ".png", (800, 600), ".jpg", False),
    ("T002", (800, 600), ".jpg", (4032, 3024), ".jpg", False),
    ("T003", (3024, 4032), ".png", (600, 800), ".jpg", False),
    ("T004", (1500, 2000), ".jpg", (1024, 1024), ".jpg", True),
]


def draw_cross(d: ImageDraw.ImageDraw, u: int, v: int, arm: int, gap: int = 4, outline=True):
    """กากบาทที่ (u, v) เส้นหนา 2 px ครอบคอลัมน์ u-1..u (กึ่งกลาง = u.0) มีขอบดำให้เห็นบนพื้นสว่าง"""
    if outline:
        for (x0, y0, x1, y1) in ((u - 3, v - arm - 2, u + 2, v - gap + 2), (u - 3, v + gap - 3, u + 2, v + arm + 2),
                                 (u - arm - 2, v - 3, u - gap + 2, v + 2), (u + gap - 3, v - 3, u + arm + 2, v + 2)):
            d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0) if d.im.mode == "RGB" else 0)
    white = (255, 255, 255) if d.im.mode == "RGB" else 255
    d.rectangle([u - 1, v - arm, u, v - gap], fill=white)
    d.rectangle([u - 1, v + gap - 1, u, v + arm], fill=white)
    d.rectangle([u - arm, v - 1, u - gap, v], fill=white)
    d.rectangle([u + gap - 1, v - 1, u + arm, v], fill=white)


def build_realistic(root: Path):
    """งานสมจริง T006: กากบาทบนเอกซเรย์อยู่ในกรอบ, ฟลู = บริเวณกรอบที่ขยาย+หมุนเล็กน้อย+กลับสี+วงกลม
    ความสัมพันธ์: F = Fc + k·R(θ)·(X − Xc)  (บันทึกไว้ใน targets.json -> realistic)"""
    import math
    import random
    from PIL import ImageFilter

    rnd = random.Random(2569)
    W, H = 3000, 2400
    base = Image.new("L", (W, H), 35)
    d = ImageDraw.Draw(base)
    for _ in range(260):                     # "กระดูก/เนื้อเยื่อ" แบบสุ่ม
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        rx, ry = rnd.randint(20, 260), rnd.randint(20, 160)
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=rnd.randint(60, 200))
    base = base.filter(ImageFilter.GaussianBlur(6))
    box = [1100.0, 700.0, 2000.0, 1500.0]
    Xc = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    FW = FH = 1024
    Fc = (FW / 2, FH / 2)
    k = FW / (box[2] - box[0])               # ขยาย ~1.14 เท่า
    th = math.radians(8.0)
    c, s = math.cos(th), math.sin(th)
    # ฟลู: สำหรับพิกเซล F หา X = Xc + R(-θ)(F − Fc)/k  (Pillow AFFINE ใช้ output -> input)
    a, b = c / k, s / k
    dd, e = -s / k, c / k
    cx0 = Xc[0] - a * Fc[0] - b * Fc[1]
    cy0 = Xc[1] - dd * Fc[0] - e * Fc[1]
    f = base.transform((FW, FH), Image.AFFINE, (a, b, cx0, dd, e, cy0), resample=Image.BICUBIC)
    f = Image.eval(f, lambda v: 255 - int(v * 0.8))          # กลับสี + ลดคอนทราสต์ (ฟลูดูต่างจากเอกซเรย์)
    f = f.convert("RGB")
    r = FW // 2 - 12
    mask = Image.new("L", (FW, FH), 0)
    ImageDraw.Draw(mask).ellipse([Fc[0] - r, Fc[1] - r, Fc[0] + r, Fc[1] + r], fill=255)
    f = Image.composite(f, Image.new("RGB", (FW, FH), (0, 0, 0)), mask)

    xt = [(1350, 900), (1780, 960), (1720, 1330), (1380, 1300), (1560, 1100)]   # อยู่ในกรอบ
    def to_f(p):
        dx, dy = p[0] - Xc[0], p[1] - Xc[1]
        return (Fc[0] + k * (c * dx - s * dy), Fc[1] + k * (s * dx + c * dy))
    ft_exact = [to_f(p) for p in xt]
    ft = [(round(x), round(y)) for x, y in ft_exact]
    x_img = base.convert("RGB")
    dx_ = ImageDraw.Draw(x_img)
    for u, v in xt:
        draw_cross(dx_, u, v, 30)
    df = ImageDraw.Draw(f)
    for u, v in ft:
        draw_cross(df, u, v, 30)
    x_img.convert("L").save(root / "T006_X.png")
    f.save(root / "T006_F.jpg", "JPEG", quality=95)
    item = {"task_id": "T006", "xray": "T006_X.png", "fluoro": "T006_F.jpg", "xray_size": [W, H],
            "fluoro_size": [FW, FH], "box_xyxy": box, "is_repeat_of": None}
    info = {"xray_targets": xt, "fluoro_targets": ft, "fluoro_targets_exact": ft_exact,
            "model": "F = Fc + k*R(theta)*(X - Xc)", "Xc": Xc, "Fc": Fc, "k": k, "theta_deg": 8.0}
    return item, info


def build_big(root: Path, n: int = 12):
    """แพ็กเกจ 12 งานภาพเล็ก ใช้ทดสอบการบังคับสำรองทุก 10 งาน"""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    xs = (800, 600)
    save(draw_image(*xs, general_targets(*xs), "L"), root / "_x.jpg")
    save(draw_image(*xs, general_targets(*xs), "RGB"), root / "_f.jpg")
    items = []
    for i in range(1, n + 1):
        tid = f"T{i:03d}"
        shutil.copyfile(root / "_x.jpg", root / f"{tid}_X.jpg")
        shutil.copyfile(root / "_f.jpg", root / f"{tid}_F.jpg")
        items.append({"task_id": tid, "xray": f"{tid}_X.jpg", "fluoro": f"{tid}_F.jpg", "xray_size": list(xs),
                      "fluoro_size": list(xs), "box_xyxy": box_for(*xs), "is_repeat_of": None})
    (root / "_x.jpg").unlink()
    (root / "_f.jpg").unlink()
    (root / "manifest.json").write_text(json.dumps(
        {"package_id": "pkg-test-big", "seed": 0, "k": 0, "items": items}, indent=2), encoding="utf-8")
    t = general_targets(*xs)
    (root / "targets.json").write_text(json.dumps(
        {"targets": {**{it["xray"]: t for it in items}, **{it["fluoro"]: t for it in items}}}, indent=2), encoding="utf-8")


def box_for(w: int, h: int) -> list[float]:
    return [round(w * 0.20, 1), round(h * 0.25, 1), round(w * 0.75, 1), round(h * 0.80, 1)]


def build_test_package(root: Path):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    items, targets = [], {}
    for task, xs, xext, fs, fext, circ in SPECS:
        xname, fname = f"{task}_X{xext}", f"{task}_F{fext}"
        xt = general_targets(*xs)
        save(draw_image(*xs, xt, "L"), root / xname)
        if circ:
            cx, cy, r = fs[0] // 2, fs[1] // 2, min(fs) // 2 - 10
            ft = circle_targets(cx, cy, r)
            fimg = draw_image(*fs, ft, "RGB", circle=(cx, cy, r))
        else:
            ft = general_targets(*fs)
            fimg = draw_image(*fs, ft, "RGB")
        save(fimg, root / fname)
        targets[xname] = xt
        targets[fname] = ft
        items.append({
            "task_id": task, "xray": xname, "fluoro": fname,
            "xray_size": list(xs), "fluoro_size": list(fs),
            "box_xyxy": box_for(*xs), "is_repeat_of": None,
        })

    # งานซ้ำ: T005 = ภาพชุดเดียวกับ T001 แต่ไฟล์และรหัสใหม่
    src = items[0]
    for kind in ("xray", "fluoro"):
        new = src[kind].replace("T001", "T005")
        shutil.copyfile(root / src[kind], root / new)
        targets[new] = targets[src[kind]]
    rep = dict(src, task_id="T005", xray=src["xray"].replace("T001", "T005"),
               fluoro=src["fluoro"].replace("T001", "T005"), is_repeat_of="T001")
    items.append(rep)

    # งานสมจริง: ฟลู = บริเวณในกรอบของเอกซเรย์ที่ขยาย
    real_item, real_info = build_realistic(root)
    items.append(real_item)
    targets[real_item["xray"]] = real_info["xray_targets"]
    targets[real_item["fluoro"]] = real_info["fluoro_targets"]

    manifest = {"package_id": "pkg-test-20261108", "seed": 0, "k": 0, "items": items}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (root / "targets.json").write_text(json.dumps(
        {"note": "ตำแหน่งกากบาท (x, y) หน่วยพิกเซลต้นฉบับ origin มุมซ้ายบน", "targets": targets,
         "realistic": {real_item["task_id"]: real_info}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def build_reversed(root: Path, good: Path, manifest: dict):
    """แพ็กเกจเดิมแต่สลับลำดับงาน: งานแรกเป็นเอกซเรย์ 1500x2000 (ไม่ใช่ 4032) ใช้แยกว่าปัญหาเกิดจาก 'งานแรก' หรือ 'ภาพ 4032'"""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    items = [it for it in manifest["items"] if it["is_repeat_of"] is None][::-1]
    for it in items:
        for k in ("xray", "fluoro"):
            shutil.copyfile(good / it[k], root / it[k])
    m = dict(manifest, package_id="pkg-test-reversed", items=items)
    (root / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(good / "targets.json", root / "targets.json")


def build_bad_size(root: Path, good: Path):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for n in ("T002_X.jpg", "T002_F.jpg"):
        shutil.copyfile(good / n, root / n)
    item = {"task_id": "T001", "xray": "T002_X.jpg", "fluoro": "T002_F.jpg",
            "xray_size": [801, 600],  # ผิดโดยตั้งใจ (จริง 800x600)
            "fluoro_size": [4032, 3024], "box_xyxy": box_for(800, 600), "is_repeat_of": None}
    (root / "manifest.json").write_text(json.dumps(
        {"package_id": "pkg-bad-size", "seed": 0, "k": 0, "items": [item]}, indent=2), encoding="utf-8")


def build_bad_exif(root: Path):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    xs, fs = (800, 600), (800, 600)
    save(draw_image(*xs, general_targets(*xs), "L"), root / "T001_X.jpg")
    save(draw_image(*fs, general_targets(*fs), "RGB"), root / "T001_F.jpg", exif_orientation=6)
    item = {"task_id": "T001", "xray": "T001_X.jpg", "fluoro": "T001_F.jpg",
            "xray_size": list(xs), "fluoro_size": list(fs), "box_xyxy": box_for(*xs), "is_repeat_of": None}
    (root / "manifest.json").write_text(json.dumps(
        {"package_id": "pkg-bad-exif", "seed": 0, "k": 0, "items": [item]}, indent=2), encoding="utf-8")


def main():
    good = OUT / "test_package"
    m = build_test_package(good)
    build_reversed(OUT / "test_package_reversed", good, m)
    build_big(OUT / "test_package_big")
    build_bad_size(OUT / "bad_size_package", good)
    build_bad_exif(OUT / "bad_exif_package")
    print(f"สร้างแล้ว: {good}  ({len(m['items'])} งาน)")
    print(f"สร้างแล้ว: {OUT / 'bad_size_package'}")
    print(f"สร้างแล้ว: {OUT / 'bad_exif_package'}")
    print("ตำแหน่งกากบาทที่ถูกต้องดูได้ใน test_package/targets.json")


if __name__ == "__main__":
    main()
