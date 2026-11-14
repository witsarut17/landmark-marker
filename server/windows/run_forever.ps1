# เปิดโปรแกรมเซิร์ฟเวอร์ PelNav แล้วเปิดใหม่เองถ้าดับ (Task Scheduler เรียกไฟล์นี้ตอนเปิดเครื่อง)
# ใช้:  powershell -ExecutionPolicy Bypass -File run_forever.ps1 -AppDir C:\PelNav\app -Config C:\PelNav\data\config.toml
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [Parameter(Mandatory = $true)][string]$Config
)
$ErrorActionPreference = "Continue"
$python = Join-Path $AppDir ".venv\Scripts\python.exe"
$logDir = Join-Path (Split-Path $Config -Parent) "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "service.log"
Set-Location $AppDir
while ($true) {
    Add-Content -Path $runLog -Encoding utf8 -Value "$(Get-Date -Format s) เริ่มเซิร์ฟเวอร์"
    & $python -X utf8 -m server.manage --config $Config run *>> $runLog
    Add-Content -Path $runLog -Encoding utf8 -Value "$(Get-Date -Format s) เซิร์ฟเวอร์หยุด (รหัส $LASTEXITCODE) — เปิดใหม่ใน 10 วินาที"
    Start-Sleep -Seconds 10
}
