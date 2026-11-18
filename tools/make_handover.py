"""สร้าง "ชุดส่งมอบ" สำหรับคนที่ติดตั้งเครื่องแล็บ (ไม่รู้จักโปรเจกต์) — ทุกไฟล์อยู่ในโฟลเดอร์ส่วนตัว ไม่ขึ้น git

    .venv\\Scripts\\python -I -X utf8 -B tools/make_handover.py --lab-url http://<IP เครื่องแล็บ>:8090/ --cvat-url http://<IP>:8080/

ได้ใน --out (ค่าเริ่มต้น C:\\PelNav_private\\handover):
  orig_package.zip  แพ็กเกจภาพต้นฉบับ ไม่มีรหัส (ทีมตัดสิน: ส่งผ่าน Google Drive บัญชีมหาวิทยาลัย แชร์ให้ผู้ติดตั้งคนเดียว)
                    มีชื่อ/HN → ห้ามส่งช่องทางอื่น ลบหลังแตก · Windows แตกได้เอง (Extract All) ไม่ต้องลงโปรแกรมเพิ่ม
  test_package.zip  ภาพทดสอบสังเคราะห์ (ไม่ใช่ภาพผู้ป่วย) ใช้ทดสอบหลังติดตั้ง
  คู่มือติดตั้ง.pdf (+ .html, .md) 2 หน้า: ติดตั้ง · แตกแพ็กเกจ · ลงทะเบียน · บัญชี/ลิงก์ · ทดสอบผ่าน VPN
ตรวจหลังสร้าง: แตก zip ชั่วคราว (นอกโฟลเดอร์ส่งมอบ) เทียบ sha256 ทุกไฟล์กับแพ็กเกจ แล้วลบไฟล์ชั่วคราว
โค้ดให้ดาวน์โหลดจาก GitHub ตาม commit ล่าสุดบน origin/main (server/ และ marker/ ในเครื่องต้องตรงกับบน GitHub) → ไม่มีข้อมูลจริงติดไป
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_originals import safe_out_dir  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from server.validate import load_manifest  # noqa: E402
from print_guide import CSS, convert_page  # noqa: E402

REPO = "https://github.com/witsarut17/landmark-marker"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=PROJECT, capture_output=True, text=True, check=True).stdout.strip()


def mb(n: int) -> str:
    return f"{n / 1e6:,.0f} MB" if n >= 1e6 else f"{n / 1e3:,.0f} KB"


GUIDE = r"""# คู่มือติดตั้งเว็บมาร์กจุด PelNav บนเครื่องแล็บ (Windows) — หน้า 1: ติดตั้ง

**คืออะไร:** เว็บให้แพทย์มาร์กจุดบนภาพเอกซเรย์ ทำงานบนเครื่องเดียวกับ CVAT แต่คนละพอร์ต (CVAT {cvat} · PelNav **{port}**) · แพทย์เปิดผ่าน VPN ที่ `{lab}`
**ข้อห้าม:** ภาพในแพ็กเกจมี**ชื่อ/HN ผู้ป่วย** (ไฟล์ zip ไม่มีรหัส) — แตกไว้ที่ `C:\PelNav\packages` เท่านั้น ห้ามคัดลอกหรือส่งต่อ · ลบ zip ทันทีหลังแตก · รหัสผ่านและลิงก์ที่ระบบแสดง ห้ามส่งในกลุ่มแชต
**ต้องมี:** สิทธิ์ Administrator · อินเทอร์เน็ต · ดิสก์ว่าง ≥ 5 GB · ไฟล์จากทีม 2 ไฟล์ (ทีมแชร์ผ่าน Google Drive บัญชีมหาวิทยาลัยให้ผู้ติดตั้งคนเดียว): `orig_package.zip` ({size_orig}) และ `test_package.zip` ({size_test}) · ใช้เวลาประมาณ 1 ชั่วโมง

## ขั้นที่ 1: ติดตั้ง Python
1. python.org/downloads/windows → **Python 3.12** (Windows installer 64-bit) → ติ๊ก **Add python.exe to PATH** → Install Now
- ✔ **ตรวจ:** เปิด PowerShell พิมพ์ `py --version` → ขึ้น `Python 3.12.x`

## ขั้นที่ 2: เอาโค้ดลงเครื่อง (โค้ดอย่างเดียว ไม่มีข้อมูลผู้ป่วย)
1. เปิดลิงก์นี้ในเบราว์เซอร์ → ได้ไฟล์ zip: `{code_url}`
2. คลิกขวาไฟล์ → **Extract All** → ข้างในมีโฟลเดอร์ `landmark-marker-…` → ย้ายโฟลเดอร์ชั้นที่มี `server` และ `marker` ไปเป็น `C:\PelNav\app`
- ✔ **ตรวจ:** มี `C:\PelNav\app\server\manage.py` และ `C:\PelNav\app\marker\index.html`

## ขั้นที่ 3: รันตัวติดตั้ง
1. คลิกขวาปุ่ม Start → **Terminal (Admin)** แล้วพิมพ์: `powershell -ExecutionPolicy Bypass -File C:\PelNav\app\server\windows\install.ps1 -LabIp {ip}`
2. ตัวติดตั้งทำเอง: ตรวจพอร์ต {port} ว่าง · ติดตั้งโปรแกรมเสริม · สร้างฐานข้อมูล `C:\PelNav\data` · ไฟร์วอลล์รับเฉพาะเครือข่าย 10.x · ไม่ให้เครื่องหลับ · เริ่มเองเมื่อเปิดเครื่อง (ไม่แตะ CVAT)
- ✔ **ตรวจ:** บรรทัดท้ายขึ้น `หมอเปิดผ่าน VPN ที่: {lab}` · รอ 20 วินาที แล้วเปิด `http://127.0.0.1:{port}/api/health` ในเครื่องนี้ → ขึ้น `"ok": true`
- ข้อความสีแดง / ไม่ขึ้น ok → ถ่ายภาพหน้าจอส่งทีม (ดู `C:\PelNav\data\logs\service.log`)

## ขั้นที่ 4: แตกแพ็กเกจภาพ (ใช้ Windows ได้เลย ไม่ต้องลงโปรแกรมเพิ่ม)
1. ตรวจว่าไฟล์ไม่เสียระหว่างส่ง: `Get-FileHash <โฟลเดอร์ที่ดาวน์โหลด>\orig_package.zip` → ค่า Hash ต้องตรงกับ (เว้นวรรคไว้ให้อ่านง่าย): `{sha_groups}`
2. คลิกขวา `orig_package.zip` → **Extract All** → ช่องปลายทางลบข้อความเดิมแล้วพิมพ์ `C:\PelNav\packages` → **Extract**
3. คลิกขวา `test_package.zip` → **Extract All** → ปลายทาง `C:\PelNav\packages` → **Extract**
- ✔ **ตรวจ:** มี `C:\PelNav\packages\orig_package` ({nfiles} ไฟล์ · ไม่ซ้อนเป็น `orig_package\orig_package`) และ `C:\PelNav\packages\test_package`
- **แล้วลบ** `orig_package.zip` และ `test_package.zip` ที่ดาวน์โหลดมา และล้างถังขยะ

<!-- pagebreak -->

# หน้า 2: ลงทะเบียน บัญชี และทดสอบ

ทุกขั้นพิมพ์ใน **Terminal (Admin)** · เริ่มด้วย 2 บรรทัดนี้ทุกครั้งที่เปิดหน้าต่างใหม่ (ทำให้คำสั่งสั้นลงเป็น `m …`):
- `cd C:\PelNav\app`
- `function m {{ & .\.venv\Scripts\python.exe -X utf8 -m server.manage --config C:\PelNav\data\config.toml @args }}`

## ขั้นที่ 5: ลงทะเบียนแพ็กเกจ + บัญชีทีม (ผู้ติดตั้งทำ)
1. `m add-package C:\PelNav\packages\orig_package` → ✔ ขึ้น `ลงทะเบียน {pkg_id} ({ntasks} งาน)`
2. `m add-package C:\PelNav\packages\test_package` → ✔ ขึ้น `ลงทะเบียน {test_id} ({ntest} งาน)`
3. `m add-user team1 --role team` → **รหัสผ่านแสดงครั้งเดียว** → จดแล้วส่งให้ทีมทางช่องทางส่วนตัว
- ✔ **ตรวจ:** `m list` แสดงแพ็กเกจ 2 รายการ และผู้ใช้ team1

## ขั้นที่ 6: ทดสอบผ่าน VPN จากเครื่องอื่น (ใช้ภาพทดสอบ ไม่ใช่ภาพผู้ป่วย)
1. `m add-user test1 --role doctor` · `m assign test1 {test_id}` · `m make-link test1 --until {test_until} --base {lab}` → คัดลอกลิงก์ที่ได้
2. อีกเครื่อง (โน้ตบุ๊กหรือ iPad) ต่อ VPN → เปิด `{lab}api/health` → ✔ ขึ้น `"ok": true`
3. เปิดลิงก์ของ test1 → ✔ เว็บเปิดงาน T001 เอง (ภาพทดสอบมีกากบาท) · วางจุด 1 จุด → มุมขวาบนขึ้น "บันทึกแล้ว"
4. เปิด `{lab}admin.html` → เข้าด้วย team1 + รหัส → ✔ มีแถว test1
5. ปิดบัญชีทดสอบ: `m disable-user test1`
- ข้อ 2 เปิดไม่ได้ ทั้งที่ CVAT (`{cvat_url}`) เปิดได้ → ส่งบรรทัด "ปฏิเสธคำขอ" ใน `C:\PelNav\data\logs\app.log` ให้ทีม (VPN อาจให้ IP ที่ไม่ขึ้นต้นด้วย 10.)

## ขั้นที่ 7: บัญชีแพทย์จริง (ทีมทำผ่านรีโมต หรือผู้ติดตั้งรันแล้วส่งลิงก์ให้ทีมทางช่องทางส่วนตัว)
ต่อแพทย์ 1 คน (เปลี่ยน `doc1` เป็นชื่อบัญชีที่ทีมกำหนด):
1. `m add-user doc1 --role doctor` · `m assign doc1 {pkg_id}`
2. `m make-link doc1 --until <วันจบโครงการ เช่น 2027-06-30> --base {lab}` → **ลิงก์แสดงครั้งเดียว** → ส่งให้แพทย์คนนั้นทางแชตส่วนตัว
- ✔ **ตรวจ:** `m list` แถว doc1 ขึ้น "ลิงก์ใช้ได้ถึง …" · ลิงก์หลุด: `m revoke-link doc1` แล้ว make-link ใหม่

## หลังติดตั้ง
- เครื่องเปิดเว็บเองเมื่อเปิดเครื่องและไม่หลับ · สำรองฐานข้อมูลอัตโนมัติทุกชั่วโมงที่ `C:\PelNav\data\backups`
- คู่มือละเอียด (ปัญหาที่พบบ่อย อัปเดตโปรแกรม เลิกใช้): `C:\PelNav\app\LAB_INSTALL.md` · ติดต่อทีม: ______________________
"""


def render_pdf(md: str, out_html: Path, out_pdf: Path) -> int:
    pages = [convert_page(part) for part in md.split("<!-- pagebreak -->") if part.strip()]
    body = "\n".join(f'<div class="page">{b}</div>' for _, b in pages)
    out_html.write_text(f'<!doctype html><html lang="th"><head><meta charset="utf-8"><title>{html.escape("คู่มือติดตั้ง PelNav")}</title>'
                        f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        p = br.new_page()
        p.goto(out_html.as_uri())
        p.pdf(path=str(out_pdf), format="A4", prefer_css_page_size=True)
        br.close()
    return len(re.findall(rb"/Type\s*/Page[^s]", out_pdf.read_bytes()))


def zip_folder(src: Path, dest: Path, method) -> list[Path]:
    files = sorted(p for p in src.iterdir() if p.is_file())
    with zipfile.ZipFile(dest, "w", method, allowZip64=True) as z:
        for p in files:
            z.write(p, f"{src.name}/{p.name}")
    return files


def verify_zip(zpath: Path, files: list[Path], tmp: Path) -> tuple[int, list[str]]:
    """แตกชั่วคราว → (จำนวนไฟล์ที่ได้, ไฟล์ที่ sha256 ไม่ตรง) · ลบไฟล์ชั่วคราวเสมอ"""
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None:
                return 0, ["zip เสีย"]
            z.extractall(tmp)
        folder = tmp / files[0].parent.name
        bad = [p.name for p in files if sha256_file(folder / p.name) != sha256_file(p)]
        return sum(1 for _ in folder.iterdir()), bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab-url", required=True, help="เช่น http://<IP เครื่องแล็บ>:8090/")
    ap.add_argument("--cvat-url", default="", help="ที่อยู่ CVAT ของแล็บ (ใช้ในคู่มือเพื่อเทียบตอนทดสอบ)")
    ap.add_argument("--package", default=r"C:\PelNav_private\orig_package")
    ap.add_argument("--test-package", default=str(PROJECT / "tests" / "generated" / "test_package"))
    ap.add_argument("--out", default=r"C:\PelNav_private\handover")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    m = re.fullmatch(r"http://(10\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)/?", args.lab_url.strip())
    if not m:
        sys.exit("--lab-url ต้องเป็น http://10.x.x.x:พอร์ต/ (เครือข่ายภายใน)")
    ip, port = m.group(1), m.group(2)
    lab = f"http://{ip}:{port}/"
    out = safe_out_dir(Path(args.out))
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        sys.exit(f"มี {out} อยู่แล้ว — ใส่ --overwrite ถ้าจะสร้างใหม่")

    # โค้ด: commit ล่าสุดบน GitHub · โปรแกรมที่ใช้บนเครื่องแล็บ (server/, marker/) ในเครื่องนี้ต้องตรงกับบน GitHub
    git("fetch", "-q", "origin")
    head = git("rev-parse", "origin/main")
    if git("diff", "--name-only", head, "--", "server", "marker"):
        sys.exit("หยุด: server/ หรือ marker/ ในเครื่องต่างจากบน GitHub — commit + push ก่อน (ชุดส่งมอบต้องตรงกับโค้ดบน GitHub)")
    code_url = f"{REPO}/archive/{head}.zip"

    pkg, tpkg = Path(args.package), Path(args.test_package)
    man, _ = load_manifest(pkg)
    tman, _ = load_manifest(tpkg)
    if pkg.name != "orig_package" or tpkg.name != "test_package":
        sys.exit("ชื่อโฟลเดอร์แพ็กเกจต้องเป็น orig_package และ test_package (คู่มืออ้างชื่อนี้)")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tmp = out.parent / "_handover_verify"

    # test_package.zip (ภาพสังเคราะห์) · orig_package.zip (ไม่มีรหัส · ไม่บีบอัด เพราะภาพ JPEG/PNG บีบอัดอยู่แล้ว)
    tpath = out / "test_package.zip"
    tfiles = zip_folder(tpkg, tpath, zipfile.ZIP_DEFLATED)
    opath = out / "orig_package.zip"
    print("กำลังสร้าง orig_package.zip …", flush=True)
    files = zip_folder(pkg, opath, zipfile.ZIP_STORED)
    for zp, fl in ((tpath, tfiles), (opath, files)):
        n_out, bad = verify_zip(zp, fl, tmp)
        if bad or n_out != len(fl):
            zp.unlink(missing_ok=True)
            sys.exit(f"หยุด: ตรวจ {zp.name} ไม่ผ่าน (ไม่ตรง {len(bad)}, จำนวน {n_out}/{len(fl)})")

    sha = sha256_file(opath).upper()
    md = GUIDE.format(cvat=(re.search(r":(\d+)", args.cvat_url).group(1) if args.cvat_url else "8080"), port=port, lab=lab, ip=ip,
                      size_orig=mb(opath.stat().st_size), size_test=mb(tpath.stat().st_size), code_url=code_url,
                      sha_groups=" ".join(sha[i:i + 8] for i in range(0, 64, 8)),
                      nfiles=len(files), pkg_id=man["package_id"], ntasks=len(man["items"]), test_id=tman["package_id"],
                      ntest=len(tman["items"]), test_until=(date.today() + timedelta(days=14)).isoformat(),
                      cvat_url=args.cvat_url or "CVAT ของแล็บ")
    (out / "คู่มือติดตั้ง.md").write_text(md, encoding="utf-8")
    pages = render_pdf(md, out / "คู่มือติดตั้ง.html", out / "คู่มือติดตั้ง.pdf")
    (out / "ข้อมูลชุดส่งมอบ.json").write_text(json.dumps({
        "package_id": man["package_id"], "tasks": len(man["items"]), "files": len(files), "orig_package_zip_sha256": sha,
        "orig_package_zip_bytes": opath.stat().st_size, "test_package_zip_bytes": tpath.stat().st_size,
        "code_commit": head, "code_url": code_url, "lab_url": lab}, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"ชุดส่งมอบ: {out}")
    for p in sorted(out.iterdir()):
        print(f"  {p.name:<26} {mb(p.stat().st_size):>10}")
    print(f"คู่มือ PDF {pages} หน้า · โค้ด commit {head[:7]} · sha256 ของ orig_package.zip = {sha[:16]}…")
    print(f"ตรวจ zip: แตกได้ครบ {len(files)} ไฟล์ และ sha256 ตรงกับแพ็กเกจทุกไฟล์ (test_package {len(tfiles)} ไฟล์ ตรงทุกไฟล์)")


if __name__ == "__main__":
    main()
