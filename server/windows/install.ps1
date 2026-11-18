# ติดตั้งเซิร์ฟเวอร์ PelNav บนเครื่อง Windows ของแล็บ (รันครั้งเดียว ด้วย PowerShell แบบ "Run as administrator")
#
#   powershell -ExecutionPolicy Bypass -File C:\PelNav\app\server\windows\install.ps1
#
# แบบเดียวกับ CVAT ของแล็บ: หมอต่อ VPN ของมหาวิทยาลัย แล้วเปิด http://<IP เครื่องแล็บ>:8090/ (CVAT อยู่ที่พอร์ต 8080)
# ทำให้: สร้าง venv + ติดตั้งโปรแกรมเสริม · สร้างโฟลเดอร์ข้อมูลและฐานข้อมูล · ตั้งค่าให้รับคำขอที่พอร์ต 8090
#        เฉพาะจากเครือข่ายภายใน 10.x, 172.16–31.x, 192.168.x (ทั้งไฟร์วอลล์ของ Windows และในตัวโปรแกรม) · ไม่ให้เครื่องหลับ
#        ตั้งให้เริ่มเองเมื่อเปิดเครื่องและเปิดใหม่เองถ้าดับ
# ไม่ทำ: ไม่แตะ CVAT (พอร์ต 8080) · ไม่สร้างบัญชีผู้ใช้ (ใช้คำสั่ง add-user / make-link ภายหลัง)
param(
    [string]$Root = "C:\PelNav",
    [int]$Port = 8090,                          # พอร์ตที่หมอเปิด (8080 = CVAT)
    [string]$AllowedNetworks = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",   # เครือข่ายที่เข้าได้ (คั่นด้วยจุลภาค) · ค่าเริ่มต้น = เครือข่ายภายในทุกช่วง
    [string]$LabIp = ""                         # IP ของเครื่องนี้ที่หมอใช้ (ว่าง = หาเองจาก IP ที่ขึ้นต้นด้วย 10.)
)
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

# ---- ตรวจสิทธิ์และโปรแกรมที่ต้องมี
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "ต้องเปิด PowerShell แบบ Run as administrator" }
$AppDir = Join-Path $Root "app"
$DataDir = Join-Path $Root "data"
if (-not (Test-Path (Join-Path $AppDir "server\manage.py"))) { throw "ไม่พบโปรแกรมที่ $AppDir (คัดลอกโฟลเดอร์โปรเจกต์ไปไว้ที่นี่ก่อน)" }
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { throw "ไม่พบ Python (ติดตั้ง Python 3.12 จาก python.org และติ๊ก Add python.exe to PATH)" }
$nets = @($AllowedNetworks -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($nets.Count -eq 0) { throw "ต้องระบุ -AllowedNetworks อย่างน้อย 1 ช่วง" }

# ---- IP ของเครื่องนี้ (ใช้ทำลิงก์ให้หมอ)
if (-not $LabIp) {
    $LabIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
              Where-Object { $_.IPAddress -like "10.*" } | Select-Object -First 1).IPAddress
}
if (-not $LabIp) { Write-Host "หา IP ที่ขึ้นต้นด้วย 10. ไม่พบ — ใส่เองภายหลังใน config.toml (public_url) หรือรันใหม่ด้วย -LabIp <IP>" -ForegroundColor Yellow }

# ---- พอร์ตต้องว่าง (ติดตั้งซ้ำ: หยุดตัวเดิมก่อน)
Step "ตรวจพอร์ต $Port"
Stop-ScheduledTask -TaskName "PelNav Server" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$used = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($used) { throw "พอร์ต $Port ถูกใช้อยู่แล้ว (PID $($used[0].OwningProcess)) — เลือกพอร์ตอื่นด้วย -Port" }
Write-Host "พอร์ต $Port ว่าง"

# ---- venv + โปรแกรมเสริม
Step "ติดตั้ง Python venv และโปรแกรมเสริม"
Set-Location $AppDir
if (-not (Test-Path ".venv\Scripts\python.exe")) { & py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r server\requirements.txt

# ---- ข้อมูล + ตั้งค่า
Step "สร้างโฟลเดอร์ข้อมูลและฐานข้อมูลที่ $DataDir"
$Config = Join-Path $DataDir "config.toml"
& .\.venv\Scripts\python.exe -X utf8 -m server.manage --config $Config init
$netList = ($nets | ForEach-Object { "`"$_`"" }) -join ", "
$cfg = Get-Content $Config -Raw -Encoding utf8
$cfg = $cfg -replace '(?m)^host = "[^"]*"', 'host = "0.0.0.0"'
$cfg = $cfg -replace '(?m)^port = \d+', "port = $Port"
$cfg = $cfg -replace '(?m)^secure_cookies = \w+', 'secure_cookies = false'
$cfg = $cfg -replace '(?m)^trusted_proxy = \w+', 'trusted_proxy = false'
$cfg = $cfg -replace '(?m)^allowed_networks = \[[^\]]*\]', "allowed_networks = [$netList, `"127.0.0.0/8`", `"::1/128`"]"
if ($LabIp) { $cfg = $cfg -replace '(?m)^public_url = "[^"]*"', "public_url = `"http://${LabIp}:$Port/`"" }
Set-Content -Path $Config -Value $cfg -Encoding utf8
# โฟลเดอร์ข้อมูลให้เฉพาะผู้ดูแลเครื่องและระบบอ่านได้ (มีฐานข้อมูลและ log)
icacls $DataDir /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null

# ---- ไฟร์วอลล์: เปิดพอร์ตเดียว รับเฉพาะเครือข่ายภายใน
Step "ไฟร์วอลล์: เปิด TCP $Port เฉพาะจาก $($nets -join ', ')"
Get-NetFirewallRule -DisplayName "PelNav*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "PelNav $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow `
    -Profile Domain,Private,Public -RemoteAddress $nets | Out-Null
Write-Host "เปิดพอร์ต $Port แล้ว (เฉพาะ $($nets -join ', '))"

# ---- ไม่ให้เครื่องหลับ (ตอนเสียบไฟ)
Step "ตั้งค่าพลังงาน: ไม่หลับ ไม่จำศีล"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0

# ---- เริ่มเองเมื่อเปิดเครื่อง + เปิดใหม่เองถ้าดับ (Task Scheduler รันในนามระบบ ไม่ต้องล็อกอิน)
Step "ตั้งให้เริ่มเองเมื่อเปิดเครื่อง"
Unregister-ScheduledTask -TaskName "PelNav HTTPS" -Confirm:$false -ErrorAction SilentlyContinue   # งานเก่าจาก v1.0 (ไม่ใช้แล้ว)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup
$appAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AppDir\server\windows\run_forever.ps1`" -AppDir `"$AppDir`" -Config `"$Config`""
Register-ScheduledTask -TaskName "PelNav Server" -Action $appAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "PelNav Server"

Step "เสร็จ"
Write-Host "ทดสอบบนเครื่องนี้: เปิด http://127.0.0.1:$Port/api/health (รอ 10-20 วินาทีหลังติดตั้ง)"
if ($LabIp) { Write-Host "หมอเปิดผ่าน VPN ที่: http://${LabIp}:$Port/ (ลิงก์ส่วนตัวจะขึ้นต้นด้วยที่อยู่นี้)" }
Write-Host "ขั้นต่อไป: เพิ่มแพ็กเกจ บัญชี และลิงก์ส่วนตัวของหมอ ตาม LAB_INSTALL.md ขั้นที่ 5"
