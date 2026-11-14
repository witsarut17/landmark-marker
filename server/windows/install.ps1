# ติดตั้งเซิร์ฟเวอร์ PelNav บนเครื่อง Windows ของแล็บ (รันครั้งเดียว ด้วย PowerShell แบบ "Run as administrator")
#
#   powershell -ExecutionPolicy Bypass -File C:\PelNav\app\server\windows\install.ps1
#
# ทำให้: สร้าง venv + ติดตั้งโปรแกรมเสริม · สร้างโฟลเดอร์ข้อมูลและฐานข้อมูล · ตั้งค่าให้ฟังเฉพาะในเครื่อง (127.0.0.1:8091)
#        เปิดไฟร์วอลล์เฉพาะพอร์ต 8090 (HTTPS ผ่าน Caddy) · ไม่ให้เครื่องหลับ · ตั้งให้เริ่มเองเมื่อเปิดเครื่องและเปิดใหม่เองถ้าดับ
# ไม่ทำ: ไม่แตะ CVAT (พอร์ต 8080) · ไม่สร้างบัญชีผู้ใช้ (ใช้คำสั่ง add-user ภายหลัง) · ไม่ติดตั้งใบรับรอง HTTPS (ดู LAB_INSTALL.md)
param(
    [string]$Root = "C:\PelNav",
    [int]$PublicPort = 8090,              # พอร์ตที่หมอเปิด (HTTPS โดย Caddy)
    [int]$AppPort = 8091,                 # พอร์ตของโปรแกรม PelNav (ฟังเฉพาะในเครื่อง)
    [string]$VpnSubnet = ""               # เช่น "10.8.0.0/16" ถ้าฝ่ายไอทีให้ช่วง IP ของ VPN -> ไฟร์วอลล์รับเฉพาะช่วงนี้
)
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

# ---- ตรวจสิทธิ์และโปรแกรมที่ต้องมี
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "ต้องเปิด PowerShell แบบ Run as administrator" }
$AppDir = Join-Path $Root "app"
$DataDir = Join-Path $Root "data"
$CaddyDir = Join-Path $Root "caddy"
if (-not (Test-Path (Join-Path $AppDir "server\manage.py"))) { throw "ไม่พบโปรแกรมที่ $AppDir (คัดลอกโฟลเดอร์โปรเจกต์ไปไว้ที่นี่ก่อน)" }
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { throw "ไม่พบ Python (ติดตั้ง Python 3.12 จาก python.org และติ๊ก Add python.exe to PATH)" }

# ---- พอร์ตต้องว่าง
Step "ตรวจพอร์ต $PublicPort และ $AppPort"
foreach ($p in @($PublicPort, $AppPort)) {
    $used = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($used) { throw "พอร์ต $p ถูกใช้อยู่แล้ว (PID $($used[0].OwningProcess)) — เลือกพอร์ตอื่นด้วย -PublicPort / -AppPort" }
}
Write-Host "ว่างทั้งสองพอร์ต"

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
$cfg = Get-Content $Config -Raw -Encoding utf8
$cfg = $cfg -replace 'host = "[^"]*"', 'host = "127.0.0.1"'
$cfg = $cfg -replace 'port = \d+', "port = $AppPort"
$cfg = $cfg -replace 'secure_cookies = \w+', 'secure_cookies = true'
$cfg = $cfg -replace 'trusted_proxy = \w+', 'trusted_proxy = true'
Set-Content -Path $Config -Value $cfg -Encoding utf8
# โฟลเดอร์ข้อมูลให้เฉพาะผู้ดูแลเครื่องและระบบอ่านได้ (มีฐานข้อมูลและ log)
icacls $DataDir /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
New-Item -ItemType Directory -Force -Path $CaddyDir, (Join-Path $CaddyDir "logs"), (Join-Path $Root "certs") | Out-Null

# ---- ไฟร์วอลล์: เปิดเฉพาะพอร์ตที่หมอใช้ (HTTPS) · พอร์ตโปรแกรมไม่เปิดออกนอกเครื่อง
Step "ไฟร์วอลล์: เปิดเฉพาะ TCP $PublicPort"
Get-NetFirewallRule -DisplayName "PelNav HTTPS*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$rule = @{ DisplayName = "PelNav HTTPS $PublicPort"; Direction = "Inbound"; Protocol = "TCP"; LocalPort = $PublicPort; Action = "Allow"; Profile = "Domain,Private" }
if ($VpnSubnet) { $rule.RemoteAddress = $VpnSubnet }
New-NetFirewallRule @rule | Out-Null
Write-Host "เปิดพอร์ต $PublicPort แล้ว$(if ($VpnSubnet) { " (เฉพาะ $VpnSubnet)" })"

# ---- ไม่ให้เครื่องหลับ (ตอนเสียบไฟ)
Step "ตั้งค่าพลังงาน: ไม่หลับ ไม่จำศีล"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0

# ---- เริ่มเองเมื่อเปิดเครื่อง + เปิดใหม่เองถ้าดับ (Task Scheduler รันในนามระบบ ไม่ต้องล็อกอิน)
Step "ตั้งให้เริ่มเองเมื่อเปิดเครื่อง"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup
$appAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AppDir\server\windows\run_forever.ps1`" -AppDir `"$AppDir`" -Config `"$Config`""
Register-ScheduledTask -TaskName "PelNav Server" -Action $appAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$caddyExe = Join-Path $CaddyDir "caddy.exe"
$caddyFile = Join-Path $CaddyDir "Caddyfile"
$caddyAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AppDir\server\windows\run_caddy_forever.ps1`" -CaddyExe `"$caddyExe`" -Caddyfile `"$caddyFile`""
Register-ScheduledTask -TaskName "PelNav HTTPS" -Action $caddyAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "PelNav Server"
if ((Test-Path $caddyExe) -and (Test-Path $caddyFile)) { Start-ScheduledTask -TaskName "PelNav HTTPS"; $c = "เริ่มแล้ว" } else { $c = "ยังไม่เริ่ม (ยังไม่มี caddy.exe หรือ Caddyfile — ดู LAB_INSTALL.md ขั้นที่ 5)" }

Step "เสร็จ"
Write-Host "โปรแกรม PelNav: ทำงานที่ http://127.0.0.1:$AppPort (เฉพาะในเครื่อง) · ทดสอบ: เปิด http://127.0.0.1:$AppPort/api/health ในเครื่องนี้"
Write-Host "HTTPS (Caddy): $c"
Write-Host "ขั้นต่อไป: เพิ่มแพ็กเกจและบัญชีหมอ ตาม LAB_INSTALL.md ขั้นที่ 6"
