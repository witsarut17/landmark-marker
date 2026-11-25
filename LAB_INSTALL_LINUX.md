# ติดตั้งเว็บมาร์กจุดบนเครื่องแล็บที่เป็น Linux (docker)

ใช้แทน [LAB_INSTALL.md](LAB_INSTALL.md) (Windows) เมื่อเครื่องแล็บเป็น Linux เช่น Ubuntu ที่มี CVAT อยู่แล้ว · ไม่ต้องใช้ sudo ถ้าบัญชีอยู่ในกลุ่ม `docker` · ไม่ต้องมี Python 3.11+ บนเครื่อง (ใช้ image `python:3.12-slim`)

> **ข้อห้าม:** ภาพผู้ป่วย ฐานข้อมูล `config.toml` รหัสผ่าน และลิงก์ส่วนตัว อยู่บนเครื่องแล็บเท่านั้น ห้ามขึ้น GitHub · คู่มือนี้ใช้ `<IP เครื่องแล็บ>` แทนเลข IP จริง

## โครงสร้างบนเครื่อง

```
<ROOT>/            เช่น /media/<ดิสก์ข้อมูล>/<user>/PelNav  (chmod 700 · อย่าใช้ดิสก์ / ถ้าใกล้เต็ม)
  app/             โค้ดจาก GitHub (มี server/ และ marker/)
  data/            config.toml, db/, backups/, logs/  (สร้างเองตอน init)
  packages/        แพ็กเกจภาพ เช่น orig_package/ และ test_package/
  m                คัดลอกจาก app/server/linux/m
  run.sh           คัดลอกจาก app/server/linux/run.sh
```

## ติดตั้งครั้งแรก

1. `mkdir -p <ROOT>/packages && chmod 700 <ROOT>`
2. เอาโค้ดลงเครื่องที่ `<ROOT>/app` — `git clone https://github.com/witsarut17/landmark-marker.git <ROOT>/app` (หรือแตก zip ของเวอร์ชันที่ทีมกำหนด เช่น tag `v1.3.2`)
3. คัดลอกแพ็กเกจภาพไว้ที่ `<ROOT>/packages` ทางที่ทีมกำหนด · เช็ก `sha256sum` ของ zip ให้ตรงกับที่ทีมแจ้ง · แตกแล้ว**ลบ zip ทิ้งทุกที่**
4. build image (ครั้งเดียว หรือเมื่อ `server/requirements.txt` เปลี่ยน)
   ```
   docker build -f <ROOT>/app/server/linux/Dockerfile -t pelnav-py312 <ROOT>/app/server
   ```
5. `cp <ROOT>/app/server/linux/m <ROOT>/app/server/linux/run.sh <ROOT>/ && chmod 700 <ROOT>/m <ROOT>/run.sh`
6. `<ROOT>/m init` แล้วแก้ `<ROOT>/data/config.toml` ส่วน `[server]`
   ```
   host = "0.0.0.0"
   port = 8090
   public_url = "http://<IP เครื่องแล็บ>:8090/"
   ```
   - ถ้าพอร์ต 8090 ถูกใช้อยู่แล้ว (เช่น traefik ของ CVAT จอง 8080 และ 8090) ให้ใช้พอร์ตอื่น เช่น 8091 ทั้งใน `port` และ `public_url` · ตรวจด้วย `ss -ltn | grep -E ':(8090|8091)\b'`
7. `<ROOT>/run.sh` แล้วตรวจ `curl http://127.0.0.1:<พอร์ต>/api/health` ต้องได้ `"ok": true` · จากเครื่องอื่นที่ต่อ VPN เปิด `http://<IP เครื่องแล็บ>:<พอร์ต>/api/health` ต้องได้เหมือนกัน
   - container ชื่อ `pelnav` เปิดเองหลังรีบูต และเปิดใหม่เองถ้าดับ (`--restart unless-stopped`)

## แพ็กเกจ บัญชี และลิงก์ส่วนตัว

**ไฟล์ที่ส่งให้คำสั่ง `m` ต้องเป็น path เต็ม** (คำสั่งรันในโฟลเดอร์ `<ROOT>/app`)

```
<ROOT>/m add-package <ROOT>/packages/orig_package
<ROOT>/m add-user team1 --role team            # รหัสผ่านแสดงครั้งเดียว — เก็บเอง
<ROOT>/m add-user team2 --role team
<ROOT>/m add-user doc1 --role doctor
<ROOT>/m assign doc1 <package_id>
<ROOT>/m make-link doc1 --until <วันจบโครงการ>  # ลิงก์แสดงครั้งเดียว — ส่งให้หมอทางแชตส่วนตัว
<ROOT>/m list
```

## การศึกษา: หน้ารายการเคส (v1.3)

หมอจะเห็นหน้ารายการเคสก็ต่อเมื่อตั้ง "การศึกษา" แล้ว (ถ้ายังไม่ตั้ง เว็บทำงานแบบเดิม: มาร์กทีละงาน T001…)

- **แบบของทีม (แนะนำ):** ทีมส่งออกจุดจากโน้ตบุ๊ก (`export-marks`) แล้วนำเข้าที่เครื่องแล็บ — `<ROOT>/m import-marks <path เต็มของ team_marks.json>` แล้ว `<ROOT>/m study` · ได้เคสตามที่ออกแบบ พร้อมจุดของทีมให้หมอตรวจ
- **แบบง่าย (ชั่วคราว) เมื่อยังไม่มีไฟล์ของทีม:** ภาพ 1 คู่ = 1 เคส ไม่มีจุดของทีม (หมอวางจุดเอง) · ทีมมาร์กก่อนได้ที่หน้าทีม (`admin.html` แล้วกด มาร์กจุด (โหมดทีม))
  ```
  docker run --rm --user "$(id -u):$(id -g)" -v <ROOT>:<ROOT> -w <ROOT>/app pelnav-py312 \
    python -I -X utf8 -B tools/make_simple_study.py <ROOT>/packages/orig_package --out <ROOT>/data/study-simple.json
  <ROOT>/m set-study <ROOT>/data/study-simple.json
  <ROOT>/m study
  ```
  เมื่อได้ `team_marks.json` ภายหลัง ใช้ `import-marks` ตั้งการศึกษาแทนได้ (จุดที่บันทึกไว้แล้วยังอยู่ตาม task_id)

## รีเซ็ตรหัสบัญชีทีม (team1, team2)

รหัสใหม่แสดงครั้งเดียว (ออกจากระบบทุกเครื่องของบัญชีนั้น) → ส่งให้เจ้าของทางช่องทางส่วนตัว · แก้ `<ROOT>` เป็นโฟลเดอร์ที่ติดตั้ง แล้วคัดลอกทั้ง 2 บรรทัด:
```
<ROOT>/m reset-password team1
<ROOT>/m reset-password team2
```
- ถ้าขึ้น "ไม่มีผู้ใช้ …" ให้สร้างแทน: `<ROOT>/m add-user team2 --role team`

## ที่อยู่ที่ทีมและหมอใช้ (ต้องเป็นเซิร์ฟเวอร์เดียวกัน)

ตรวจว่าแอปฟังพอร์ตไหน และลิงก์ของหมอชี้ไปที่ไหน:
```
grep -E '^(port|public_url)' <ROOT>/data/config.toml
docker ps --filter name=pelnav
ss -ltnp | grep -E ':(8091|8099)\b'
```
- หน้าทีม = `http://<IP เครื่องแล็บ>:<port>/admin.html` (พอร์ตเดียวกับ `public_url`) · ถ้ามีพอร์ตอื่น (เช่น :8099) ที่ส่งต่อไป container `pelnav` เดียวกัน ใช้ได้เหมือนกัน แต่ถ้าเป็นอีก container จุดจะไปอยู่คนละฐานข้อมูล

## ดูแลประจำ

- สถานะ: `docker ps --filter name=pelnav` · log เปิด/ปิด: `docker logs --tail 50 pelnav` · log การใช้งาน: `<ROOT>/data/logs/app.log`
- ปิด/เปิด: `docker stop pelnav` / `docker start pelnav` (ปิดแล้วจะไม่เปิดเองตอนรีบูตจนกว่าจะ start)
- สำรองข้อมูล: อัตโนมัติทุกชั่วโมงที่ `<ROOT>/data/backups` · สำรองทันที: `<ROOT>/m backup-now`
- อัปเดตโค้ด: `<ROOT>/m backup-now` → อัปเดต `<ROOT>/app` (git pull หรือแตก zip ทับ) → ถ้า `server/requirements.txt` เปลี่ยน ให้ build image ใหม่แล้ว `docker rm -f pelnav && <ROOT>/run.sh` · ถ้าเปลี่ยนแค่หน้าเว็บ (`marker/`) ไม่ต้องรีสตาร์ท หน้าเว็บของผู้ใช้โหลดรุ่นใหม่เอง

## ถ้า git pull ขึ้นว่า "diverged" / "refusing to merge unrelated histories" (ประวัติ git ถูกเขียนใหม่ 2026-11-26)

ทีมเขียนข้อความ commit เก่าใหม่ (เนื้อหาไฟล์เหมือนเดิมทุกไฟล์) → รหัส commit เปลี่ยนหมด ให้ตั้งโค้ดใน `<ROOT>/app` ให้ตรง GitHub ครั้งเดียว — **ไม่แตะ `<ROOT>/data` (ฐานข้อมูล แพ็กเกจ log)** เพราะอยู่นอกโฟลเดอร์โค้ด:
```
<ROOT>/m backup-now
cd <ROOT>/app
git status --short
git fetch origin --tags --force
git reset --hard origin/main
git log -1 --oneline
```
- `git status --short` ควรว่าง · ถ้ามีไฟล์ที่แก้เองบนเครื่องนี้ ให้ `git stash` ก่อน reset (ห้ามใช้ `git clean`)
- ไม่ต้องรีสตาร์ท container เพราะไฟล์โค้ดเหมือนเดิม (ถ้าอยากชัวร์: `docker restart pelnav`)
- ติดตั้งแบบแตก zip (ไม่มีโฟลเดอร์ `.git`) = ไม่ต้องทำอะไร
- ไม่มีไฟร์วอลล์ของเครื่องตั้งให้ (ไม่ใช้ sudo) — แอปกรองเครือข่ายเองตาม `allowed_networks` ใน `config.toml`
