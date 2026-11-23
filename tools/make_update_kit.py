"""สร้าง "ชุดอัปเดต" เครื่องแล็บ (ติดตั้ง v1.2 ไว้แล้ว) เป็นเวอร์ชันปัจจุบัน + นำเข้าจุดของทีม — อยู่ในโฟลเดอร์ส่วนตัว ไม่ขึ้น git

    .venv\\Scripts\\python -I -X utf8 -B tools/make_update_kit.py --lab-url http://<IP เครื่องแล็บ>:8090/

ได้ใน --out (ค่าเริ่มต้น C:\\PelNav_private\\update): คู่มืออัปเดต.pdf (+ .md, .html) 1 หน้า
  หยุดบริการ → สำรองฐานข้อมูล → อัปโค้ด (zip จาก GitHub ตาม commit ล่าสุด ไม่มีข้อมูลจริง) → ปรับฐานข้อมูล (อัตโนมัติ)
  → นำเข้าจุดของทีม (team_marks.json จาก export-marks บนโน้ตบุ๊ก) → เริ่มบริการ → ตรวจ → บัญชีหมอ + ลิงก์
แพ็กเกจภาพบนเครื่องแล็บใช้ของเดิม (ไม่เปลี่ยน) · ถ้ามี team_marks.json แล้ว ใส่ --marks เพื่อพิมพ์จำนวนงานและ sha256 ลงคู่มือ
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_handover import REPO, git, mb, render_pdf  # noqa: E402
from survey_originals import safe_out_dir  # noqa: E402

GUIDE = r"""# คู่มืออัปเดตเครื่องแล็บ PelNav เป็นเวอร์ชัน {version} (1 หน้า)

**สำหรับ:** เครื่องที่ติดตั้งตามชุดส่งมอบเดิมแล้ว · **แพ็กเกจภาพใช้ของเดิม ไม่ต้องส่งใหม่** · ต้องมี: สิทธิ์ Administrator · อินเทอร์เน็ต · ไฟล์ `team_marks.json` จากทีม{marks_info} (ทีมแชร์ผ่าน Google Drive บัญชีมหาวิทยาลัยให้ผู้อัปเดตคนเดียว · เป็นข้อมูลวิจัย ห้ามส่งต่อ) · ใช้เวลาประมาณ 20 นาที
ทุกคำสั่งพิมพ์ใน **Terminal (Admin)** หลัง 2 บรรทัดนี้: `cd C:\PelNav\app` และ `function m {{ & .\.venv\Scripts\python.exe -X utf8 -m server.manage --config C:\PelNav\data\config.toml @args }}`

## 1. หยุดบริการและสำรองฐานข้อมูล
1. Task Scheduler → Task Scheduler Library → คลิกขวา **PelNav Server** → **End**
2. `m backup-now` → ✔ ขึ้น `สำรองแล้ว: C:\PelNav\data\backups\…` (ถ้าอัปเดตไม่สำเร็จ ทีมใช้ไฟล์นี้กู้คืนได้)

## 2. อัปโค้ด (โค้ดอย่างเดียว ไม่มีข้อมูลผู้ป่วย)
1. เปิด `{code_url}` → ได้ไฟล์ zip → คลิกขวา **Extract All**
2. เปิดโฟลเดอร์ `landmark-marker-…` ชั้นที่มี `server` และ `marker` → เลือกทุกอย่าง (Ctrl+A) → คัดลอกไปวางใน `C:\PelNav\app` → **Replace** ทั้งหมด (ไม่ต้องลบ `.venv`)
3. `.venv\Scripts\python -m pip install -r server\requirements.txt`
- ✔ **ตรวจ:** มีไฟล์ `C:\PelNav\app\server\study.py`

## 3. ปรับฐานข้อมูล + นำเข้าจุดของทีม
1. `m list` → ตารางใหม่ถูกเพิ่มเอง ข้อมูลเดิมไม่หาย · ✔ ขึ้นแพ็กเกจ `{pkg_id}` และบัญชีเดิม
2. บันทึก `team_marks.json` ไว้ที่ `C:\PelNav\import\` แล้ว `m import-marks C:\PelNav\import\team_marks.json`
- ✔ **ตรวจ:** ขึ้น `นำเข้าแล้ว: ผู้มาร์ก 2 คน · งาน …` และ `ตั้งการศึกษาแล้ว: {pkg_id} · เคส {n_cases}` · ถ้าสร้างบัญชีทีมใหม่ จะแสดงรหัสผ่านครั้งเดียว → ส่งให้เจ้าของทางช่องทางส่วนตัว
- `m study` → ✔ ผู้มาร์กแต่ละคนขึ้นจำนวนงานที่เสร็จ (ควรครบ)
3. ลบ `team_marks.json` ที่ดาวน์โหลดมา (และในถังขยะ) หลังนำเข้าสำเร็จ

## 4. เริ่มบริการและตรวจ
1. Task Scheduler → คลิกขวา **PelNav Server** → **Run** → รอ 20 วินาที → ✔ `http://127.0.0.1:8090/api/health` ขึ้น `"ok": true`
2. จากเครื่องที่ต่อ VPN เปิด `{lab}admin.html` → เข้าด้วยบัญชีทีม → ✔ มีตาราง "การศึกษา: ทีมมาร์กก่อน · หมอตรวจ" {n_cases} เคส ช่อง "ทีมมาร์ก" ครบ
3. ตรวจมุมมองของแพทย์ด้วยบัญชีชั่วคราว: `m add-user check1 --role doctor` · `m assign check1 {pkg_id}` · `m make-link check1 --until {check_until} --base {lab}` → เปิดลิงก์จากเครื่องที่ต่อ VPN → ✔ ขึ้นรายการเคส 1–{n_cases} · แตะเคส 1 เห็นจุด 4 คู่ของทีม (**ไม่ต้องกดยืนยัน**) → ปิดบัญชี: `m disable-user check1` (บัญชีที่ปิดแล้วไม่ถูกนับในผล)

## 5. บัญชีแพทย์ (ทีมทำผ่านรีโมต หรือผู้อัปเดตรันแล้วส่งลิงก์ให้ทีมทางช่องทางส่วนตัว)
- ต่อแพทย์ 1 คน: `m add-user doc1 --role doctor` · `m assign doc1 {pkg_id}` · `m make-link doc1 --until <วันจบโครงการ> --base {lab}` → ลิงก์แสดงครั้งเดียว → ส่งให้แพทย์คนนั้นทางแชตส่วนตัว
- มีปัญหา: ถ่ายภาพหน้าจอส่งทีม · ไฟล์ log อยู่ที่ `C:\PelNav\data\logs\` · คู่มือละเอียด `C:\PelNav\app\LAB_INSTALL.md`
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab-url", required=True)
    ap.add_argument("--study", default=r"C:\PelNav_private\study.json")
    ap.add_argument("--marks", default="", help="team_marks.json (ถ้ามีแล้ว) เพื่อพิมพ์จำนวนงานและ sha256 ลงคู่มือ")
    ap.add_argument("--check-until", default="", help="วันหมดอายุลิงก์ของบัญชีตรวจระบบ (ค่าเริ่มต้น 7 วันจากวันนี้)")
    ap.add_argument("--out", default=r"C:\PelNav_private\update")
    args = ap.parse_args()
    m = re.fullmatch(r"http://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)/?", args.lab_url.strip())
    if not m or not ipaddress.ip_address(m.group(1)).is_private:
        sys.exit("--lab-url ต้องเป็น http://<IP ภายใน>:พอร์ต/")
    lab = f"http://{m.group(1)}:{m.group(2)}/"
    out = safe_out_dir(Path(args.out))
    git("fetch", "-q", "origin")
    head = git("rev-parse", "origin/main")
    if git("diff", "--name-only", head, "--", "server", "marker"):
        sys.exit("หยุด: server/ หรือ marker/ ในเครื่องต่างจากบน GitHub — commit + push ก่อน")
    root = Path(__file__).resolve().parents[1]
    version = re.search(r"PELNAV_VERSION = '([^']+)'", (root / "marker" / "version.js").read_text(encoding="utf-8")).group(1)
    st = json.loads(Path(args.study).read_text(encoding="utf-8"))
    marks_info = ""
    if args.marks:
        doc = json.loads(Path(args.marks).read_text(encoding="utf-8"))
        if doc.get("package_id") != st["package_id"]:
            sys.exit("team_marks.json เป็นของแพ็กเกจอื่น")
        sha = hashlib.sha256(Path(args.marks).read_bytes()).hexdigest().upper()
        marks_info = f" (งาน {len(doc['tasks_latest'])} · sha256 ขึ้นต้น `{sha[:16]}`)"
    from datetime import date, timedelta
    md = GUIDE.format(version=version, code_url=f"{REPO}/archive/{head}.zip", lab=lab, pkg_id=st["package_id"],
                      n_cases=len(st["cases"]), marks_info=marks_info,
                      check_until=args.check_until or (date.today() + timedelta(days=7)).isoformat())
    out.mkdir(parents=True, exist_ok=True)
    (out / "คู่มืออัปเดต.md").write_text(md, encoding="utf-8")
    pages = render_pdf(md, out / "คู่มืออัปเดต.html", out / "คู่มืออัปเดต.pdf")
    print(f"คู่มืออัปเดต {pages} หน้า · โค้ด commit {head[:7]} · เวอร์ชัน {version} → {out}")
    for p in sorted(out.iterdir()):
        print(f"  {p.name:<24} {mb(p.stat().st_size):>8}")
    if pages > 1:
        print("คำเตือน: เกิน 1 หน้า")


if __name__ == "__main__":
    main()
