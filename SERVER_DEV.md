# ทดสอบเซิร์ฟเวอร์บนโน้ตบุ๊ก (ภาพทดสอบเท่านั้น)

แผนรวมอยู่ใน [SERVER_PLAN.md](SERVER_PLAN.md) · เอกสารนี้คือขั้นตอนลองแต่ละขั้นบนโน้ตบุ๊ก
**ห้ามใช้ภาพผู้ป่วยบนโน้ตบุ๊กในขั้นนี้** (ยังเป็น http ไม่เข้ารหัส) · ข้อมูลทั้งหมดอยู่ใน `server_data/` ซึ่งไม่ขึ้น git

## ขั้น A: ตัวเซิร์ฟเวอร์ (เข้าสู่ระบบ ส่งภาพ บันทึกจุด หน้าทีม สำรอง log)

หน้ามาร์กจุดของหมอยังเป็นแบบเลือกไฟล์อยู่ (เปลี่ยนในขั้น B) · ขั้นนี้ลองฝั่งเซิร์ฟเวอร์และหน้าทีมวิจัย

### 1. ตั้งค่าครั้งแรก (เปิด Terminal ใน VS Code ที่โฟลเดอร์โปรเจกต์ แล้วพิมพ์ทีละบรรทัด)
```
.venv\Scripts\python -m server.manage init
.venv\Scripts\python -m server.manage add-package tests\generated\test_package
.venv\Scripts\python -m server.manage add-user team1 --role team
.venv\Scripts\python -m server.manage add-user doc1 --role doctor
.venv\Scripts\python -m server.manage assign doc1 pkg-test-20261108
.venv\Scripts\python -m server.manage list
```
- คำสั่ง `add-user` จะแสดง **รหัสผ่านครั้งเดียว** (เช่น `xxxx-xxxx-xxxx-xxxx`) ให้จดไว้ · ลืมให้ใช้ `reset-password team1`
- ถ้าเครื่องใหม่ยังไม่มีโปรแกรมเสริม: `.venv\Scripts\python -m pip install -r server/requirements.txt`

### 2. เปิดเซิร์ฟเวอร์
```
.venv\Scripts\python -m server.manage run
```
ขึ้น "เปิดเซิร์ฟเวอร์แล้ว: http://127.0.0.1:8080/" · ปล่อยหน้าต่างนี้ไว้ · ปิดด้วย Ctrl+C (จะสำรองฐานข้อมูลครั้งสุดท้ายให้)

### 3. ลอง (ใน Edge บนโน้ตบุ๊กเครื่องเดียวกัน)
- [ ] เปิด `http://127.0.0.1:8080/api/package` → ต้องขึ้นข้อความ error 401 (ยังไม่เข้าสู่ระบบ ดูข้อมูลไม่ได้)
- [ ] เปิด `http://127.0.0.1:8080/admin.html` → ใส่ `team1` กับรหัสผิด → ขึ้น "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
- [ ] ใส่รหัสที่ถูก → เห็นตาราง: doc1 · pkg-test-20261108 · ทำแล้ว 0/6
- [ ] กด **JSON** และ **CSV** → ได้ไฟล์ใน Downloads (ยังไม่มีจุด เพราะหมอยังไม่ได้มาร์ก)
- [ ] กด **ออกจากระบบ** → กลับมาหน้าใส่รหัส
- [ ] เปิดโฟลเดอร์ `server_data\backups` → มีไฟล์ `marks-วันที่-เวลา.sqlite` (สำรองตอนเปิดเซิร์ฟเวอร์ และทุกชั่วโมง)
- [ ] เปิด `server_data\logs\app.log` → เห็นบรรทัดการเข้าใช้ (เวลา ผู้ใช้ หน้า ผลลัพธ์) ไม่มีรหัสผ่าน
- [ ] กลับไปหน้าต่าง Terminal กด Ctrl+C → ปิดได้ · มีไฟล์สำรองเพิ่มอีก 1 ไฟล์

### ถ้ามีปัญหา
- "ไม่พบ server_data\config.toml" → ยังไม่ได้รันคำสั่ง `init`
- พอร์ต 8080 ถูกใช้แล้ว → แก้ `port` ใน `server_data\config.toml`
- เริ่มใหม่ทั้งหมด: ปิดเซิร์ฟเวอร์ แล้วลบโฟลเดอร์ `server_data` ทั้งโฟลเดอร์ (เป็นข้อมูลทดสอบเท่านั้น)

## ขั้น B–D: (ยังไม่เสร็จ)
