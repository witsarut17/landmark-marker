# ขึ้นเว็บบน GitHub Pages (ทีละขั้น สำหรับมือใหม่)

เป้าหมาย: ได้ลิงก์ `https://<ชื่อบัญชี>.github.io/landmark-marker/` ให้หมอเปิดบน iPad (HTTPS → ปุ่มบันทึกไฟล์สำรองลงแอปไฟล์ใช้ได้)

> สิ่งที่ขึ้น GitHub = โค้ดเว็บ + สคริปต์ + เอกสาร **เท่านั้น** · ไม่มีภาพ/แพ็กเกจ/key.csv/ไฟล์ส่งออก (กันด้วย `.gitignore` และตรวจด้วย `python tools/check_publish.py --list`)
> repo ต้องเป็น **public** (GitHub Pages ฟรี) → ทุกคนเห็นโค้ดได้ แต่ไม่มีข้อมูลผู้ป่วยในนั้น

## ส่วนที่ 1: ทำเองบนเว็บ github.com (ครั้งเดียว)

1. **สร้างบัญชี:** เปิด https://github.com/signup
   - อีเมล: ใช้อีเมลของคุณได้ (ไม่แสดงต่อสาธารณะ ถ้าทำข้อ 3)
   - **ชื่อบัญชี (username): จะเป็นส่วนหนึ่งของลิงก์** → ห้ามมีชื่อโรงพยาบาลหรือชื่อโครงการที่บอกสถานที่ เช่น ใช้ชื่อเล่นภาษาอังกฤษ + ตัวเลข
   - ยืนยันอีเมลตามที่ GitHub ส่งมา
2. **เปิดการยืนยันสองชั้น (2FA):** มุมขวาบน รูปโปรไฟล์ → **Settings** → **Password and authentication** → **Enable two-factor authentication** → ใช้แอปบนมือถือ (เช่น Google Authenticator) สแกน QR → **เก็บ recovery codes ไว้ให้ดี**
3. **ซ่อนอีเมล:** Settings → **Emails** → ติ๊ก **Keep my email addresses private** และ **Block command line pushes that expose my email**
   - จดอีเมลแบบ `12345678+ชื่อบัญชี@users.noreply.github.com` ที่ขึ้นในหน้านั้น (ใช้แทนอีเมลจริงตอน push)
4. **สร้าง repo:** มุมขวาบน **+** → **New repository**
   - Repository name: **`landmark-marker`**
   - Description: เว้นว่าง (หรือ "Landmark marking web tool")
   - เลือก **Public**
   - **ไม่ต้อง**ติ๊ก Add a README / .gitignore / license (มีในโปรเจกต์แล้ว)
   - กด **Create repository**
5. **เปิด Pages ไว้ก่อน:** ในหน้า repo → **Settings** → เมนูซ้าย **Pages** → หัวข้อ **Build and deployment** → Source: เลือก **GitHub Actions**
6. **ส่งให้ Claude:** ลิงก์ repo (เช่น `https://github.com/ชื่อบัญชี/landmark-marker`) + อีเมล noreply จากข้อ 3
   แล้ว **รอ** — Claude จะแสดงรายชื่อไฟล์ให้ดูอีกครั้งก่อน และจะ push **หลังคุณพิมพ์ยืนยัน** เท่านั้น

## ส่วนที่ 2: Claude ทำให้ (หลังคุณยืนยัน)

```powershell
git init -b main
git config user.name "<ชื่อบัญชี>"
git config user.email "<อีเมล noreply>"
python tools/check_publish.py --list      # ต้องขึ้น "ไม่พบปัญหา"
git add .
git status                                # รายชื่อไฟล์ = รายการที่คุณยืนยันแล้ว
git commit -m "Landmark marker web app"
git remote add origin https://github.com/<ชื่อบัญชี>/landmark-marker.git
git push -u origin main
```
ตอน push ครั้งแรก Windows จะเปิดหน้าต่าง **เข้าสู่ระบบ GitHub** → กด **Sign in with your browser** → ล็อกอิน → **Authorize** (ทำครั้งเดียว)

## ส่วนที่ 3: ดูว่าเว็บขึ้นแล้ว (ทำเองบนเว็บ)

1. ในหน้า repo → แท็บ **Actions** → รอรายการ "Deploy marker to GitHub Pages" เป็น **✓ สีเขียว** (1–2 นาที)
   - ถ้าเป็น ✗ สีแดง เพราะลืมข้อ 5 ของส่วนที่ 1: ทำข้อ 5 แล้วกดเข้ารายการนั้น → **Re-run all jobs**
   - ถ้าแดงเพราะอย่างอื่น: ถ่ายภาพหน้าจอส่ง Claude (ขั้นตรวจข้อมูลส่วนตัวจะหยุดการเผยแพร่ถ้าพบไฟล์ต้องห้าม)
2. Settings → Pages จะมีลิงก์ `https://<ชื่อบัญชี>.github.io/landmark-marker/` → เปิดใน Safari บน iPad ทดสอบ
3. เขียนลิงก์ลงใน `DOCTOR_GUIDE.md` บรรทัด "ลิงก์เว็บ" แล้วพิมพ์ (`python tools/print_guide.py` → เปิด `DOCTOR_GUIDE_print.html` ใน Edge → Ctrl+P)

## ทุกครั้งที่แก้เว็บภายหลัง
Claude จะรัน `python tools/check_publish.py` ก่อน แล้ว commit + push · หน้าเว็บอัปเดตเองใน 1–2 นาที
หมอเปิดไอคอนใหม่ (ปัดปิดแอปแล้วเปิด) เพื่อได้เวอร์ชันล่าสุด · งานที่ทำไว้ไม่หาย (เก็บใน iPad)
