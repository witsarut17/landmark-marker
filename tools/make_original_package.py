"""สร้างแพ็กเกจภาพต้นฉบับ (ORIGINAL_PACKAGE_PLAN.md) จากแพ็กเกจเดิม 222 งาน — งานเดิม ลำดับเดิม กรอบเดิม

ภาพในแพ็กเกจ = ภาพต้นฉบับที่หมุนตาม EXIF แบบเดียวกับภาพคลีน → ตารางพิกเซลเท่าภาพคลีน → พิกัดที่หมอมาร์กใช้กับภาพคลีนได้ตรง ๆ
หาต้นฉบับไม่เจอ / ไม่ผ่านการตรวจ → ใช้ภาพคลีนแทน และบันทึกใน orig_key.csv ว่างานไหนใช้ภาพคลีน

อ่านอย่างเดียว: แพ็กเกจเดิม (manifest) + key.csv ในโปรเจกต์ · ภาพคลีน (tools/data_root.txt) · ภาพต้นฉบับ (tools/orig_root.txt)
เขียน: เฉพาะ --out (ค่าเริ่มต้น C:\\PelNav_private) — นอกโปรเจกต์ นอก G: นอกโฟลเดอร์ซิงก์ (ภาพมีชื่อ/HN → ห้ามขึ้น GitHub)
หน้าจอ: แสดงเฉพาะจำนวน ไม่แสดงชื่อไฟล์ต้นฉบับ

    .venv\\Scripts\\python -I -X utf8 -B tools/make_original_package.py            # dry-run: ตรวจทุกภาพ ไม่เขียนอะไร
    .venv\\Scripts\\python -I -X utf8 -B tools/make_original_package.py --write    # สร้างจริง

ต่อภาพ: ต้นฉบับชื่อหลักเดียวกัน (ไม่สนตัวพิมพ์/นามสกุล) 1 ไฟล์พอดี ในโฟลเดอร์เคส/ฝั่งเดียวกัน
  - EXIF Orientation ไม่มี/= 1: JPEG/PNG = ไบต์เดิมตัด metadata (ไม่เข้ารหัสใหม่) · BMP = PNG ไม่สูญเสีย
  - Orientation 2–8: หมุน/พลิกตาม EXIF (exif_transpose) แล้วบันทึก PNG ไม่สูญเสีย
  - ทุกกรณีตรวจ: พิกเซลในแพ็กเกจ = ที่ตั้งใจทุกจุด · ไม่มี EXIF เหลือ · ขนาด = ภาพคลีน
  - เทียบภาพคลีน (นอกบริเวณที่ภาพคลีนทาดำ): ต่างเฉลี่ย ≤ 2 · 99% ต่าง ≤ 8 · เอกซเรย์: ภาพในกรอบเหมือนกัน (สหสัมพันธ์ ≥ 0.99)
fluoro_area ใน manifest = พื้นที่วงกลมฟลู (พิกเซลไม่ดำของภาพคลีน แบบเดียวกับที่เว็บประมาณ) — ต้นฉบับไม่ได้ทาดำรอบวงกลม
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import data_root_or_none  # noqa: E402
from make_study_package import bmp_to_png, exif_orientation, kind_of, make_check_image, pixels_digest, strip_metadata, strip_png  # noqa: E402
from survey_originals import ORIG_ROOT_FILE, SHORTCUT_EXT, SIDE_DIR, read_root, safe_out_dir  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from server.validate import load_manifest  # noqa: E402

Image.MAX_IMAGE_PIXELS = 200_000_000
OK_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
OTHER_IMG = {".heic", ".heif", ".tif", ".tiff", ".webp", ".gif"}
MAX_MEAN, MAX_P99, MIN_BOX_CORR = 2.0, 8, 0.99
BLACK = 2                 # ภาพคลีนค่า ≤ 2 = บริเวณที่ทาดำ (ไม่นับตอนเทียบ)


class Fallback(Exception):
    """ใช้ต้นฉบับไม่ได้ → ใช้ภาพคลีนแทน (ข้อความ = เหตุผล)"""


def gray(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("L"), dtype=np.int16)


def fluoro_area(clean_bytes: bytes) -> int:
    """พื้นที่วงกลมฟลู = จำนวนพิกเซลที่ r+g+b > 36 ของภาพคลีน (เกณฑ์เดียวกับ estimateFilledArea ในเว็บ)"""
    with Image.open(io.BytesIO(clean_bytes)) as im:
        a = np.asarray(im.convert("RGB"), dtype=np.int32)
    return int((a.sum(axis=2) > 36).sum())


def clean_package_bytes(raw: bytes, ext: str) -> tuple[bytes, str, str]:
    """ภาพคลีน → ไฟล์ในแพ็กเกจ (แบบเดียวกับแพ็กเกจเดิม)"""
    out, oext, how = (bmp_to_png(raw), ".png", "clean bmp->png lossless") if ext == ".bmp" else \
        (strip_metadata(raw, ext), ext, "clean bytes, metadata removed")
    if pixels_digest(raw) != pixels_digest(out):
        sys.exit("หยุด: แปลงภาพคลีนแล้วพิกเซลเปลี่ยน — ไม่สร้างแพ็กเกจ")
    return out, oext, how


def original_package_bytes(raw: bytes, ext: str) -> tuple[bytes, str, str, int | None]:
    """ภาพต้นฉบับ → ไฟล์ในแพ็กเกจ (หมุนตาม EXIF แบบภาพคลีน) · ตรวจพิกเซลทุกจุด
    ใช้ชนิดไฟล์จริงจากเนื้อไฟล์ (บางไฟล์นามสกุลไม่ตรงชนิดจริง เช่น ชื่อ .png แต่เป็น JPEG) → นามสกุลในแพ็กเกจตามชนิดจริง"""
    real = kind_of(raw) or ("bmp" if raw[:2] == b"BM" else None)
    if real is None:
        raise Fallback("ไม่ใช่ไฟล์ JPEG/PNG/BMP จริง")
    ext = {"jpeg": ".jpg", "png": ".png", "bmp": ".bmp"}[real]
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        ori = exif_orientation(im)
        if ori not in (None, 1, 2, 3, 4, 5, 6, 7, 8):
            raise Fallback(f"EXIF Orientation แปลก ({ori})")
        if ori in (None, 1):
            if ext == ".bmp":
                out, oext, how = bmp_to_png(raw), ".png", "original bmp->png lossless"
            else:
                try:
                    out, oext, how = strip_metadata(raw, ext), ext, "original bytes, metadata removed"
                except ValueError as e:
                    raise Fallback(f"ตัด metadata ไม่ได้ ({e})")
            if pixels_digest(raw) != pixels_digest(out):
                raise Fallback("ตัด metadata แล้วพิกเซลเปลี่ยน")
        else:
            rot = ImageOps.exif_transpose(im)
            buf = io.BytesIO()
            rot.save(buf, "PNG", optimize=False)
            out, oext, how = strip_png(buf.getvalue()), ".png", f"original exif {ori} applied -> png lossless"
            with Image.open(io.BytesIO(out)) as chk:
                chk.load()
                if chk.size != rot.size or chk.mode != rot.mode or chk.tobytes() != rot.tobytes():
                    raise Fallback("หมุนแล้วบันทึก PNG พิกเซลไม่ตรง")
    with Image.open(io.BytesIO(out)) as chk:
        if len(chk.getexif()):
            raise Fallback("ตัด EXIF ไม่หมด")
    return out, oext, how, ori


def compare(clean: bytes, pkg: bytes, box=None) -> dict:
    a, b = gray(clean), gray(pkg)
    if a.shape != b.shape:
        raise Fallback(f"ขนาดไม่เท่าภาพคลีน ({b.shape[1]}x{b.shape[0]} vs {a.shape[1]}x{a.shape[0]})")
    keep = a > BLACK
    if keep.mean() < 0.2:
        raise Fallback("ภาพคลีนดำเกือบทั้งภาพ เทียบไม่ได้")
    d = np.abs(a - b)[keep]
    st = {"diff_mean": round(float(d.mean()), 3), "diff_p99": int(np.percentile(d, 99)),
          "masked_frac": round(float(((~keep) & (b > 20)).mean()), 4)}
    if st["diff_mean"] > MAX_MEAN or st["diff_p99"] > MAX_P99:
        raise Fallback(f"ต่างจากภาพคลีนเกินเกณฑ์ (เฉลี่ย {st['diff_mean']}, p99 {st['diff_p99']})")
    if box is not None:
        x0, y0, x1, y1 = (int(np.floor(box[0])), int(np.floor(box[1])), int(np.ceil(box[2])), int(np.ceil(box[3])))
        ca, cb, ck = a[y0:y1, x0:x1].astype(np.float64), b[y0:y1, x0:x1].astype(np.float64), keep[y0:y1, x0:x1]
        if ck.sum() > 100:
            x, y = ca[ck] - ca[ck].mean(), cb[ck] - cb[ck].mean()
            den = float(np.sqrt((x * x).sum() * (y * y).sum()))
            r = float((x * y).sum() / den) if den > 0 else 1.0
            st["box_corr"] = round(r, 5)
            if r < MIN_BOX_CORR:
                raise Fallback(f"ภาพในกรอบไม่เหมือนภาพคลีน ({r:.4f})")
    return st


def find_original(folder: Path, clean_name: str) -> Path:
    if not folder.is_dir():
        raise Fallback("ไม่มีโฟลเดอร์ต้นฉบับ (หรือเป็นทางลัด)")
    stem = Path(clean_name).stem.lower()
    same = [f for f in folder.iterdir() if f.stem.lower() == stem and f.suffix.lower() not in SHORTCUT_EXT]
    imgs = [f for f in same if f.is_file() and f.suffix.lower() in OK_EXT | OTHER_IMG]
    if not imgs:
        if any(f.suffix.lower() in SHORTCUT_EXT and Path(f.stem).stem.lower() == stem for f in folder.iterdir()):
            raise Fallback("ต้นฉบับเป็นไฟล์ทางลัด")
        raise Fallback("ไม่พบต้นฉบับชื่อเดียวกัน")
    if len(imgs) > 1:
        raise Fallback(f"พบต้นฉบับชื่อเดียวกัน {len(imgs)} ไฟล์")
    if imgs[0].suffix.lower() in OTHER_IMG:
        raise Fallback(f"ชนิดไฟล์ {imgs[0].suffix.lower()} ยังไม่รองรับ")
    return imgs[0]


def build_image(clean_root: Path, orig_root: Path, case: str, side: str, clean_name: str, expect_sha: str,
                expect_size: list, box) -> dict:
    cpath = clean_root / case / SIDE_DIR[side] / clean_name
    craw = cpath.read_bytes()                                              # อ่านอย่างเดียว
    if hashlib.sha256(craw).hexdigest() != expect_sha:
        sys.exit("หยุด: ภาพคลีนเปลี่ยนไปจากตอนสร้างแพ็กเกจเดิม (sha256 ไม่ตรง key.csv) — ไม่สร้างแพ็กเกจ")
    with Image.open(io.BytesIO(craw)) as im:
        if list(im.size) != list(expect_size):
            sys.exit("หยุด: ขนาดภาพคลีนไม่ตรง manifest เดิม — ไม่สร้างแพ็กเกจ")
    rec = {"clean_file": clean_name, "clean_sha256": expect_sha}
    try:
        opath = find_original(orig_root / case / SIDE_DIR[side], clean_name)
        oraw = opath.read_bytes()                                          # อ่านอย่างเดียว
        out, oext, how, ori = original_package_bytes(oraw, opath.suffix.lower())
        rec.update(compare(craw, out, box if side == "xray" else None))
        rec.update(source="original", orig_file=opath.name, orig_sha256=hashlib.sha256(oraw).hexdigest(),
                   exif_orientation=ori or "", conversion=how)
        real_ext = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".bmp": ".bmp"}[opath.suffix.lower()]
        if (kind_of(oraw) or ("bmp" if oraw[:2] == b"BM" else "")) != {".jpg": "jpeg", ".png": "png", ".bmp": "bmp"}[real_ext]:
            rec["conversion"] += " (นามสกุลเดิมไม่ตรงชนิดจริง)"
    except Fallback as e:
        out, oext, how = clean_package_bytes(craw, cpath.suffix.lower())
        rec.update(source="clean", fallback_reason=str(e), conversion=how)
    rec.update(data=out, ext=".jpg" if oext == ".jpeg" else oext, package_sha256=hashlib.sha256(out).hexdigest(),
               transform="identity", clean_bytes=craw)
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-package", default=str(PROJECT / "study_package"))
    ap.add_argument("--key", default=str(PROJECT / "key.csv"))
    ap.add_argument("--clean-root")
    ap.add_argument("--orig-root")
    ap.add_argument("--out", default=r"C:\PelNav_private")
    ap.add_argument("--name", default="orig")
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    clean_root = Path(args.clean_root) if args.clean_root else data_root_or_none()
    orig_root = Path(args.orig_root) if args.orig_root else read_root(ORIG_ROOT_FILE)
    if not clean_root or not clean_root.is_dir() or not orig_root or not orig_root.is_dir():
        sys.exit("ไม่รู้ที่อยู่ภาพคลีน/ต้นฉบับ: ใส่ --clean-root/--orig-root หรือไฟล์ tools/data_root.txt, tools/orig_root.txt")
    out = safe_out_dir(Path(args.out))
    for r in (clean_root, orig_root):
        if out == r.resolve() or r.resolve() in out.parents:
            sys.exit("หยุด: ปลายทางอยู่ในโฟลเดอร์ข้อมูลจริง")

    base = json.loads((Path(args.base_package) / "manifest.json").read_text(encoding="utf-8"))
    key = {r["task_id"]: r for r in csv.DictReader(Path(args.key).open(encoding="utf-8-sig"))}
    items = base["items"]
    tids = [it["task_id"] for it in items]
    if len(tids) != len(key) or set(tids) != set(key):
        sys.exit("หยุด: งานใน key.csv ไม่ตรงกับ manifest ของแพ็กเกจเดิม")
    for it in items:
        k = key[it["task_id"]]
        if json.loads(k["box_xyxy"]) != it["box_xyxy"] or (k["is_repeat_of"] or None) != it.get("is_repeat_of"):
            sys.exit(f"หยุด: กรอบ/งานซ้ำของ {it['task_id']} ใน key.csv ไม่ตรง manifest เดิม")

    name = args.name
    pkg_dir, key_csv = out / f"{name}_package", out / f"{name}_key.csv"
    report_csv, check_dir = out / f"{name}_report.csv", out / f"{name}_check"
    if args.write:
        existing = [p for p in (pkg_dir, key_csv, report_csv, check_dir) if p.exists()]
        if existing and not args.overwrite:
            sys.exit(f"มีผลเดิมอยู่แล้ว {len(existing)} รายการ — ใส่ --overwrite ถ้าจะสร้างใหม่")

    cache, entries = {}, []
    for n, it in enumerate(items, 1):
        if n % 25 == 0:
            print(f"  … {n}/{len(items)}", flush=True)
        k = key[it["task_id"]]
        per = {}
        for side in ("xray", "fluoro"):
            ck = (k["case"], side, k[f"{side}_file"])
            if ck not in cache:
                cache[ck] = build_image(clean_root, orig_root, k["case"], side, k[f"{side}_file"],
                                        k[f"{side}_sha256_source"], it[f"{side}_size"], it["box_xyxy"])
                if side == "fluoro":
                    cache[ck]["fluoro_area"] = fluoro_area(cache[ck]["clean_bytes"])
            per[side] = cache[ck]
        entries.append((it, k, per))

    # ---------- สรุป (ไม่มีชื่อไฟล์) ----------
    imgs = list(cache.items())
    print(f"งาน {len(items)} · ภาพไม่ซ้ำ {len(imgs)}")
    for side in ("xray", "fluoro"):
        rs = [r for (c, s, f), r in imgs if s == side]
        print(f"[{side}] {len(rs)} ภาพ · แหล่ง {dict(Counter(r['source'] for r in rs))} · วิธี {dict(Counter(r['conversion'] for r in rs))}")
        fb = Counter(r.get("fallback_reason") for r in rs if r["source"] == "clean")
        if fb:
            print(f"   ใช้ภาพคลีนเพราะ: {dict(fb)}")
        dm = [r["diff_mean"] for r in rs if "diff_mean" in r]
        if dm:
            print(f"   เทียบภาพคลีน: ต่างเฉลี่ยสูงสุด {max(dm)} · p99 สูงสุด {max(r['diff_p99'] for r in rs if 'diff_p99' in r)}"
                  + (f" · สหสัมพันธ์ในกรอบต่ำสุด {min(r['box_corr'] for r in rs if 'box_corr' in r)}" if side == "xray" else ""))
    uses_clean = [it["task_id"] for it, k, per in entries if any(per[s]["source"] == "clean" for s in per)]
    total = sum(len(r["data"]) for _, r in imgs)
    print(f"งานที่ใช้ภาพคลีนอย่างน้อย 1 ภาพ: {len(uses_clean)} · ขนาดแพ็กเกจประมาณ {total / 1e6:.0f} MB")
    if not args.write:
        print("\n(dry-run: ยังไม่เขียนไฟล์ · ใส่ --write เพื่อสร้างจริง)")
        return

    for p in (pkg_dir, key_csv, report_csv, check_dir):
        if p.exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    pkg_dir.mkdir(parents=True)
    check_dir.mkdir(parents=True)
    m_items, key_rows = [], []
    for it, k, per in entries:
        tid = it["task_id"]
        names = {}
        for side, suf in (("xray", "X"), ("fluoro", "F")):
            r = per[side]
            names[side] = f"{tid}_{suf}{r['ext']}"
            (pkg_dir / names[side]).write_bytes(r["data"])
        m_items.append({"task_id": tid, "xray": names["xray"], "fluoro": names["fluoro"],
                        "xray_size": it["xray_size"], "fluoro_size": it["fluoro_size"], "box_xyxy": it["box_xyxy"],
                        "is_repeat_of": it.get("is_repeat_of"), "fluoro_area": per["fluoro"]["fluoro_area"]})
        src = [s for s in ("xray", "fluoro") if per[s]["source"] == "clean"]
        row = {"task_id": tid, "case": k["case"], "annotation_id": k["annotation_id"], "image_id": k["image_id"],
               "uses_clean_image": "+".join(src), "box_xyxy": k["box_xyxy"], "is_repeat_of": k["is_repeat_of"],
               "fluo_id": k["fluo_id"], "fluo_flag": k["fluo_flag"], "fluoro_area": per["fluoro"]["fluoro_area"]}
        for side in ("xray", "fluoro"):
            r = per[side]
            for col in ("source", "clean_file", "orig_file", "exif_orientation", "conversion", "transform", "diff_mean",
                        "diff_p99", "box_corr", "fallback_reason", "clean_sha256", "orig_sha256", "package_sha256"):
                row[f"{side}_{col}"] = r.get(col, "")
        key_rows.append(row)
        make_check_image(tid, per["xray"]["data"], per["fluoro"]["data"], it["box_xyxy"],
                         check_dir / f"{tid}{'_CLEAN-' + '+'.join(src) if src else ''}.jpg", it.get("is_repeat_of"))
    manifest = {"package_id": f"pkg-orig-{args.date}", "based_on": base["package_id"],
                "image_source": "original images, EXIF-rotated like the clean images (pixel grid = clean); clean image where original unavailable",
                "coords": "same as clean images (identity transform)", "seed": base.get("seed"), "k": base.get("k"),
                "created_at": datetime.now().isoformat(timespec="seconds"), "items": m_items}
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with key_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key_rows[0]))
        w.writeheader()
        w.writerows(key_rows)
    with report_csv.open("w", newline="", encoding="utf-8-sig") as f:
        cols = ["case", "side", "clean_file", "source", "orig_file", "exif_orientation", "conversion", "transform",
                "diff_mean", "diff_p99", "masked_frac", "box_corr", "fallback_reason", "fluoro_area"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for (c, s, fn), r in imgs:
            w.writerow({"case": c, "side": s, **r})

    # ตรวจผลที่เขียนแล้ว: manifest ผ่านตัวตรวจของเซิร์ฟเวอร์ · ไฟล์ตรง sha256 · ขนาดตรง
    load_manifest(pkg_dir)
    for row in key_rows:
        for side, suf in (("xray", "X"), ("fluoro", "F")):
            fn = next(pkg_dir.glob(f"{row['task_id']}_{suf}.*"))
            if hashlib.sha256(fn.read_bytes()).hexdigest() != row[f"{side}_package_sha256"]:
                sys.exit(f"หยุด: ไฟล์ {fn.name} ไม่ตรง sha256 หลังเขียน")
    print(f"\nสร้างแล้ว: {manifest['package_id']} ({len(m_items)} งาน) ที่ {out}")
    print(f"  {pkg_dir.name}/ · {key_csv.name} (งานไหนใช้ภาพคลีน: คอลัมน์ uses_clean_image) · {report_csv.name} · {check_dir.name}/")
    print("  ภาพมีชื่อ/HN: อยู่ในโฟลเดอร์ส่วนตัวนี้เท่านั้น ห้ามคัดลอกเข้าโปรเจกต์หรือโฟลเดอร์ที่ซิงก์")


if __name__ == "__main__":
    main()
