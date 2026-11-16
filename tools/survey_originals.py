"""ขั้น 0 ของแผนภาพต้นฉบับ (ORIGINAL_PACKAGE_PLAN.md): สำรวจความสัมพันธ์ ภาพคลีน ↔ ภาพต้นฉบับ ของงานใน key.csv

อ่านอย่างเดียว: key.csv (ในโปรเจกต์) · ภาพคลีนของงานเหล่านั้น (data_root.txt) · โฟลเดอร์เคสเดียวกันในภาพต้นฉบับ (orig_root.txt)
เขียน: เฉพาะโฟลเดอร์ส่วนตัว --out (ค่าเริ่มต้น C:\\PelNav_private\\survey) — ต้องอยู่นอกโปรเจกต์ นอก G: และนอกโฟลเดอร์ซิงก์
หน้าจอ: แสดงเฉพาะจำนวน ไม่แสดงชื่อไฟล์ต้นฉบับ (อาจมีชื่อผู้ป่วย) · รายละเอียดต่อภาพอยู่ใน CSV ในโฟลเดอร์ส่วนตัว

    .venv\\Scripts\\python -I -X utf8 -B tools/survey_originals.py

ต่อภาพคลีน 1 ภาพ (เอกซเรย์/ฟลู ไม่ซ้ำ):
  1. ตรวจ sha256 ตรงกับ key.csv (ภาพคลีนยังเป็นไฟล์เดิม)
  2. หาภาพต้นฉบับ: ชื่อหลักเดียวกัน (ไม่สนตัวพิมพ์/นามสกุล) ในโฟลเดอร์เคสเดียวกัน · ไม่เจอ = เทียบความเหมือนกับทุกภาพในโฟลเดอร์นั้น
  3. เปิดต้นฉบับ (JPEG/PNG/BMP/HEIC) · ค่า EXIF Orientation · ขนาด
  4. หาทิศ (8 แบบ: หมุน/พลิก) ที่ทำให้ต้นฉบับเหมือนภาพคลีนที่สุด (ภาพย่อ) แล้วเทียบเต็มขนาดถ้าขนาดเท่ากัน
     (ไม่นับบริเวณที่ภาพคลีนทาดำ) → กลุ่ม: same / dihedral / scaled / other / not_found
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import data_root_or_none  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pillow_heif = None

PROJECT = Path(__file__).resolve().parents[1]
ORIG_ROOT_FILE = Path(__file__).with_name("orig_root.txt")
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
SHORTCUT_EXT = {".lnk", ".gshortcut", ".url"}
SIDE_DIR = {"xray": "xray", "fluoro": "fluoroscopy"}
THUMB = 384
Image.MAX_IMAGE_PIXELS = 400_000_000

# ทิศ 8 แบบ (ทำกับภาพต้นฉบับ) · EXIF Orientation n → ทิศที่ exif_transpose ใช้
OPS = {"none": None, "flip_lr": Image.Transpose.FLIP_LEFT_RIGHT, "rot180": Image.Transpose.ROTATE_180,
       "flip_tb": Image.Transpose.FLIP_TOP_BOTTOM, "transpose": Image.Transpose.TRANSPOSE,
       "rot90cw": Image.Transpose.ROTATE_270, "transverse": Image.Transpose.TRANSVERSE, "rot90ccw": Image.Transpose.ROTATE_90}
EXIF_OP = {1: "none", 2: "flip_lr", 3: "rot180", 4: "flip_tb", 5: "transpose", 6: "rot90cw", 7: "transverse", 8: "rot90ccw"}


def read_root(file: Path) -> Path | None:
    if not file.exists():
        return None
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().strip('"')
        if line and not line.startswith("#"):
            return Path(line)
    return None


def safe_out_dir(out: Path) -> Path:
    """โฟลเดอร์ผลต้องอยู่นอกโปรเจกต์ นอก G: และนอกโฟลเดอร์ที่ซิงก์ (มีภาพ/ชื่อไฟล์ที่ระบุตัวผู้ป่วยได้)"""
    o = out.resolve()
    bad = [PROJECT.resolve()]
    for env in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        if os.environ.get(env):
            bad.append(Path(os.environ[env]).resolve())
    if o.drive.upper() == "G:" or any(o == b or b in o.parents for b in bad) \
            or any(k in str(o).lower() for k in ("google drive", "onedrive", "dropbox")):
        sys.exit(f"หยุด: โฟลเดอร์ผล {o} ต้องอยู่นอกโปรเจกต์ นอก G: และนอกโฟลเดอร์ที่ซิงก์")
    return o


def gray_thumb(im: Image.Image, size=THUMB) -> np.ndarray:
    g = im.convert("L")
    g.thumbnail((size, size), Image.Resampling.BILINEAR)
    return np.asarray(g, dtype=np.float32)


def corr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    if mask.sum() < 50:
        return float("nan")
    x, y = a[mask], b[mask]
    x, y = x - x.mean(), y - y.mean()
    d = float(np.sqrt((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / d) if d > 0 else float("nan")


def open_image(path: Path) -> tuple[Image.Image, int | None, str]:
    data = path.read_bytes()                                   # อ่านอย่างเดียว
    im = Image.open(io.BytesIO(data))
    im.load()
    ori = None
    try:
        ori = im.getexif().get(0x0112)
    except Exception:
        pass
    return im, ori, hashlib.sha256(data).hexdigest()


def best_orientation(clean_t: np.ndarray, clean_size, orig: Image.Image):
    """ลองทั้ง 8 ทิศกับภาพย่อ → (ทิศที่ดีที่สุด, ค่าความเหมือน, ค่าที่ดีอันดับสอง)"""
    cw, ch = clean_size
    base = orig.convert("L")
    base.thumbnail((THUMB * 2, THUMB * 2), Image.Resampling.BILINEAR)
    mask = clean_t > 12                                        # ไม่นับบริเวณที่ภาพคลีนทาดำ
    scores = {}
    for name, op in OPS.items():
        t = base if op is None else base.transpose(op)
        if abs(t.width / t.height - cw / ch) > 0.02 * (cw / ch):   # สัดส่วนต่างเกิน 2% = คนละกรอบภาพ
            continue
        r = np.asarray(t.resize((clean_t.shape[1], clean_t.shape[0]), Image.Resampling.BILINEAR), dtype=np.float32)
        scores[name] = corr(clean_t, r, mask)
    if not scores:
        return None, float("nan"), float("nan")
    ranked = sorted(scores.items(), key=lambda kv: -np.nan_to_num(kv[1], nan=-2))
    return ranked[0][0], ranked[0][1], (ranked[1][1] if len(ranked) > 1 else float("nan"))


def full_compare(clean: Image.Image, orig: Image.Image, op: str) -> dict:
    """ขนาดเท่ากันหลังหมุน → เทียบทุกพิกเซล (ไม่นับบริเวณที่ภาพคลีนทาดำ)"""
    o = orig if OPS[op] is None else orig.transpose(OPS[op])
    a = np.asarray(clean.convert("L"), dtype=np.int16)
    b = np.asarray(o.convert("L"), dtype=np.int16)
    black = a <= 2
    masked = black & (b > 20)                                 # คลีนดำแต่ต้นฉบับไม่ดำ = บริเวณที่ถูกทาดำ
    keep = ~black
    d = np.abs(a - b)[keep]
    return {"masked_frac": round(float(masked.mean()), 4),
            "diff_mean": round(float(d.mean()), 3) if d.size else "",
            "diff_p99": int(np.percentile(d, 99)) if d.size else "",
            "diff_max": int(d.max()) if d.size else "",
            "exact_outside_mask": bool(d.size and d.max() == 0)}


def list_folder(folder: Path):
    files, shortcuts = [], 0
    if not folder.exists():
        return files, shortcuts, "missing"
    if folder.suffix.lower() in SHORTCUT_EXT or not folder.is_dir():
        return files, shortcuts, "shortcut_folder"
    for f in folder.iterdir():
        ext = f.suffix.lower()
        if ext in SHORTCUT_EXT:
            shortcuts += 1
        elif ext in IMG_EXT and f.is_file():
            files.append(f)
    return files, shortcuts, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=str(PROJECT / "key.csv"))
    ap.add_argument("--clean-root")
    ap.add_argument("--orig-root")
    ap.add_argument("--out", default=r"C:\PelNav_private\survey")
    args = ap.parse_args()
    if pillow_heif is None:
        sys.exit("ต้องติดตั้ง pillow-heif ก่อน")
    clean_root = Path(args.clean_root) if args.clean_root else data_root_or_none()
    orig_root = Path(args.orig_root) if args.orig_root else read_root(ORIG_ROOT_FILE)
    if not clean_root or not orig_root or not orig_root.is_dir():
        sys.exit("ไม่รู้ที่อยู่ภาพคลีน/ต้นฉบับ: ใส่ --clean-root/--orig-root หรือไฟล์ tools/data_root.txt, tools/orig_root.txt")
    out = safe_out_dir(Path(args.out))
    out.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(Path(args.key).open(encoding="utf-8-sig")))
    images = defaultdict(lambda: {"tasks": [], "sha": None})
    for r in rows:
        for side in ("xray", "fluoro"):
            k = (r["case"], side, r[f"{side}_file"])
            images[k]["tasks"].append(r["task_id"])
            images[k]["sha"] = r[f"{side}_sha256_source"]
    print(f"งาน {len(rows)} · ภาพไม่ซ้ำ {len(images)} (เอกซเรย์ {sum(k[1] == 'xray' for k in images)} ฟลู {sum(k[1] == 'fluoro' for k in images)})")

    out_rows, n = [], 0
    folder_cache = {}
    for (case, side, cfile), info in sorted(images.items()):
        n += 1
        if n % 25 == 0:
            print(f"  … {n}/{len(images)}", flush=True)
        rec = {"case": case, "side": side, "clean_file": cfile, "tasks": " ".join(info["tasks"])}
        cpath = clean_root / case / SIDE_DIR[side] / cfile
        try:
            cim, cori, csha = open_image(cpath)
        except Exception as e:
            rec.update(category="clean_error", note=type(e).__name__)
            out_rows.append(rec)
            continue
        rec.update(clean_size=f"{cim.width}x{cim.height}", clean_sha_ok=csha == info["sha"], clean_exif=cori or "")
        fkey = (case, side)
        if fkey not in folder_cache:
            folder_cache[fkey] = list_folder(orig_root / case / SIDE_DIR[side])
        files, shortcuts, fstate = folder_cache[fkey]
        rec.update(orig_folder=fstate, orig_folder_shortcuts=shortcuts, orig_folder_images=len(files))
        stem = Path(cfile).stem.lower()
        cands = [f for f in files if f.stem.lower() == stem]
        how = "same_name"
        clean_t = gray_thumb(cim)
        if len(cands) != 1:
            how = "by_similarity" if not cands else "by_similarity_multi_name"
            pool = cands or files
            best = []
            for f in pool:
                try:
                    oim, _, _ = open_image(f)
                except Exception:
                    continue
                op, s1, _ = best_orientation(clean_t, cim.size, oim)
                if op:
                    best.append((np.nan_to_num(s1, nan=-2), f))
            best.sort(key=lambda t: -t[0])
            if best and best[0][0] >= 0.9 and (len(best) == 1 or best[0][0] - best[1][0] >= 0.02):
                cands = [best[0][1]]
                rec["similarity_margin"] = round(best[0][0] - (best[1][0] if len(best) > 1 else 0), 4)
            else:
                cands = []
                rec["similarity_best"] = round(best[0][0], 4) if best else ""
        if not cands:
            rec.update(category="not_found", match=how)
            out_rows.append(rec)
            continue
        opath = cands[0]
        try:
            oim, oori, osha = open_image(opath)
        except Exception as e:
            rec.update(category="orig_error", match=how, note=type(e).__name__)
            out_rows.append(rec)
            continue
        op, s1, s2 = best_orientation(clean_t, cim.size, oim)
        rec.update(match=how, orig_file=opath.name, orig_ext=opath.suffix.lower(), orig_mode=oim.mode,
                   orig_size=f"{oim.width}x{oim.height}", orig_mp=round(oim.width * oim.height / 1e6, 1),
                   orig_exif=oori or "", exif_says=EXIF_OP.get(oori, "none") if oori else "none",
                   best_op=op or "", score=round(s1, 4) if op else "", second=round(s2, 4) if op and s2 == s2 else "",
                   clean_identical_bytes=osha == csha)
        if not op:
            rec["category"] = "other_aspect"
        else:
            o_w, o_h = (oim.height, oim.width) if op in ("transpose", "rot90cw", "transverse", "rot90ccw") else oim.size
            rec["op_matches_exif"] = op == rec["exif_says"]
            if (o_w, o_h) == cim.size:
                fc = full_compare(cim, oim, op)
                rec.update(fc)
                rec["category"] = ("same" if op == "none" else "dihedral") if s1 >= 0.98 else "same_size_low_score"
            else:
                sx, sy = cim.width / o_w, cim.height / o_h
                rec.update(scale_x=round(sx, 5), scale_y=round(sy, 5))
                rec["category"] = "scaled" if abs(sx - sy) < 0.002 * sx and s1 >= 0.98 else "other_size"
        out_rows.append(rec)

    cols = sorted({k for r in out_rows for k in r}, key=lambda c: (c not in ("case", "side", "clean_file", "tasks", "category"), c))
    with (out / "survey_images.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)

    # ---------- สรุป (ไม่มีชื่อไฟล์) ----------
    lines = []
    for side in ("xray", "fluoro"):
        rs = [r for r in out_rows if r["side"] == side]
        lines.append(f"[{side}] ภาพ {len(rs)}")
        for key in ("category", "match", "orig_ext", "orig_exif", "best_op", "op_matches_exif", "clean_sha_ok",
                    "exact_outside_mask", "orig_folder", "clean_identical_bytes"):
            c = Counter(str(r.get(key, "")) for r in rs)
            lines.append(f"  {key}: {dict(c)}")
        sc = [r["score"] for r in rs if isinstance(r.get("score"), float)]
        if sc:
            lines.append(f"  score: min {min(sc):.4f} · มัธยฐาน {float(np.median(sc)):.4f}")
        mp = [r["orig_mp"] for r in rs if r.get("orig_mp") != "" and "orig_mp" in r]
        if mp:
            lines.append(f"  ขนาดต้นฉบับ (ล้านพิกเซล): สูงสุด {max(mp)} · >16.7: {sum(m > 16.7 for m in mp)}")
        dm = [r["diff_mean"] for r in rs if isinstance(r.get("diff_mean"), float)]
        if dm:
            lines.append(f"  ต่างเฉลี่ยนอกบริเวณทาดำ (0–255): สูงสุด {max(dm)} · มัธยฐาน {float(np.median(dm))}")
        sh = sum(r.get("orig_folder_shortcuts", 0) or 0 for r in rs)
        lines.append(f"  ทางลัดในโฟลเดอร์ต้นฉบับ (นับต่อภาพที่ตรวจ): {sh}")
        by_tasks = sum(len(r["tasks"].split()) for r in rs if r.get("category") in ("not_found", "orig_error", "other_aspect", "other_size", "same_size_low_score", "clean_error"))
        lines.append(f"  งานที่ภาพฝั่งนี้ยังใช้ต้นฉบับไม่ได้ (นับซ้ำ): {by_tasks}")
    text = "\n".join(lines)
    (out / "survey_summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nรายละเอียดต่อภาพ (มีชื่อไฟล์ เก็บเป็นความลับ): {out / 'survey_images.csv'}")


if __name__ == "__main__":
    main()
