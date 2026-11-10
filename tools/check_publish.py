"""ตรวจก่อนเผยแพร่ (GitHub / GitHub Pages) ว่าไม่มีข้อมูลผู้ป่วยหรือข้อมูลส่วนตัวหลุดออกไป

วิธีใช้:
    python tools/check_publish.py               # ตรวจทั้งโปรเจกต์ (ไฟล์ที่จะขึ้น git)
    python tools/check_publish.py --pages-only  # ตรวจเฉพาะ marker/ (สิ่งที่ GitHub Pages จะเผยแพร่)

ผล: ERROR = ห้ามเผยแพร่ · WARN = ให้คนตรวจ/ตัดสินใจ · ออกด้วย exit code 1 ถ้ามี ERROR
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "marker"
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".vscode"}
WEB_ALLOWED = {".html", ".js", ".css", ".png", ".webmanifest"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".dcm", ".tif", ".tiff", ".bmp"}
# รหัสเคสแบบ case_ + ตัวอักษร 0–1 ตัว + เลข ≥ 2 หลัก (ชื่อเคสสมมติในเทสต์ เช่น case_demo1 ไม่เข้า)
CASE_ID = re.compile(r"\bcase_[a-z]?\d{2,}", re.I)
BAD_NAMES = [
    (re.compile(r"(^|/)study_package(/|$)"), "โฟลเดอร์ study_package (ภาพผู้ป่วย)"),
    (re.compile(r"(^|/)key\.csv$"), "key.csv (ตารางจับคู่รหัสกับผู้ป่วย)"),
    (re.compile(r"all_case\.xlsx$", re.I), "all_case.xlsx (มีชื่อ/HN)"),
    (re.compile(r"\.xlsx?$", re.I), "ไฟล์ Excel"),
    (CASE_ID, "ชื่อมีรหัสเคส"),
    (re.compile(r"(^|/)marks_.*\.(json|csv)$"), "ผลมาร์กของจริง (marks_*.json/csv)"),
    (re.compile(r"instances(_clean)?\.json$"), "COCO annotation ของจริง"),
    (re.compile(r"(^|/)data_root\.txt$"), "ตำแหน่งข้อมูลจริง (ต้องอยู่ในเครื่องเท่านั้น)"),
    (re.compile(r"(^|/)same_patient_groups\.txt$"), "กลุ่มเคสผู้ป่วยเดียวกัน (มีรหัสเคส)"),
    (re.compile(r"(^|/)splits[^/]*\.csv$", re.I), "ตารางแบ่งชุด (splits)"),
    (re.compile(r"(^|/)PROJECT_BRIEF\.md$"), "เอกสารโครงการภายใน (ชื่อ/รหัสนักศึกษา/โรงพยาบาล)"),
    (re.compile(r"(^|/)private_terms\.txt$"), "รายการคำต้องห้าม (ต้องอยู่ในเครื่องเท่านั้น)"),
    (re.compile(r"_(package|check)(/|$)"), "โฟลเดอร์แพ็กเกจ/ภาพตรวจ (ภาพผู้ป่วย)"),
    (re.compile(r"(^|/)backup_.*\.json$"), "ไฟล์สำรองผลมาร์ก"),
]
PRIVATE_TERMS_FILE = ROOT / "tools" / "private_terms.txt"


def private_terms() -> list[str]:
    """คำต้องห้าม: tools/private_terms.txt + ตำแหน่งข้อมูลจริงจาก tools/data_root.txt (ทั้งสองไฟล์อยู่ในเครื่องเท่านั้น)"""
    out = []
    sys.path.insert(0, str(ROOT / "tools"))
    from local_paths import data_root_or_none
    dr = data_root_or_none()
    if dr is not None:
        out += [str(dr), str(dr).replace("\\", "/"), dr.name]
    if not PRIVATE_TERMS_FILE.exists():
        return out
    for line in PRIVATE_TERMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out
STUDENT_ID = re.compile(r"\b\d{9}-\d\b")
HN = re.compile(r"\bHN\s*[:：]?\s*\d{5,}", re.I)


def git_files() -> list[str] | None:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, text=True, check=True)
        return [l for l in out.stdout.splitlines() if l]
    except Exception:
        return None


def walk(base: Path, honor_gitignore: bool = True) -> list[str]:
    """ไม่มี git: เดินไฟล์เอง และข้ามไฟล์ที่ .gitignore กันไว้ (แบบเดียวกับที่ git จะทำ)"""
    gitignored = lambda _p: False
    if honor_gitignore:                  # import เฉพาะตอนต้องใช้ (บน GitHub Actions ไม่มี Pillow)
        sys.path.insert(0, str(ROOT / "tools"))
        from make_study_package import gitignored
    files = []
    for p in base.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and not (honor_gitignore and gitignored(p)):
            files.append(rel)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-only", action="store_true")
    ap.add_argument("--list", action="store_true", help="แสดงรายชื่อไฟล์ทั้งหมดที่ตรวจ")
    args = ap.parse_args()

    errors, warns = [], []
    terms = private_terms()
    if not terms:
        warns.append("ไม่มี tools/private_terms.txt — ไม่ได้ตรวจชื่อคน/โรงพยาบาลในเนื้อหาไฟล์")
    if args.pages_only:
        files = walk(WEB, honor_gitignore=False)       # Pages เผยแพร่ทุกไฟล์ใน marker/ ไม่สน .gitignore
        src = "marker/ (GitHub Pages)"
    else:
        files = git_files()
        src = "ไฟล์ที่ git จะเห็น"
        if files is None:
            files = walk(ROOT)
            src = "ไฟล์ในโปรเจกต์ที่ไม่ถูก .gitignore กัน (ยังไม่มี git)"

    for rel in files:
        path = ROOT / rel
        ext = path.suffix.lower()
        for rx, why in BAD_NAMES:
            if rx.search(rel):
                errors.append(f"{rel}: {why}")
        if ext in IMAGE_EXT and not re.fullmatch(r"marker/icon[-\w]*\.png", rel):
            errors.append(f"{rel}: ไฟล์ภาพ (อาจเป็นภาพผู้ป่วย)")
        if rel.startswith("marker/") and ext not in WEB_ALLOWED:
            errors.append(f"{rel}: ชนิดไฟล์ไม่ควรอยู่ในเว็บ ({ext})")
        if ext in {".md", ".txt", ".js", ".html", ".py", ".json", ".csv", ".css", ".yml", ".yaml"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if HN.search(text):
                errors.append(f"{rel}: มีรูปแบบคล้าย HN + เลข")
            low = text.lower()
            if CASE_ID.search(text):
                errors.append(f"{rel}: มีรหัสเคสในเนื้อหา ('{CASE_ID.search(text).group(0)[:6]}…')")
            for term in terms:
                if term.lower() in low:
                    errors.append(f"{rel}: มีคำต้องห้ามจาก private_terms.txt ('{term[:2]}…')")
            if STUDENT_ID.search(text):
                warns.append(f"{rel}: มีเลขรหัสนักศึกษา/ชื่อจริง (ข้อมูลส่วนตัวของทีม) — ถ้า repo เป็น public ให้ตัดสินใจก่อน")

    print(f"ตรวจ {len(files)} ไฟล์ จาก {src}")
    if args.list:
        for rel in sorted(files):
            print(f"  {rel}  ({(ROOT / rel).stat().st_size:,} ไบต์)")
    for e in errors:
        print(f"ERROR  {e}")
    for w in warns:
        print(f"WARN   {w}")
    if not errors and not warns:
        print("ไม่พบปัญหา")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
