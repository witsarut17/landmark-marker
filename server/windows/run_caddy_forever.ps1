# เปิด Caddy (ตัวกลาง HTTPS พอร์ต 8090 -> โปรแกรม PelNav ที่ 127.0.0.1:8091) แล้วเปิดใหม่เองถ้าดับ
# ใช้:  powershell -ExecutionPolicy Bypass -File run_caddy_forever.ps1 -CaddyExe C:\PelNav\caddy\caddy.exe -Caddyfile C:\PelNav\caddy\Caddyfile
param(
    [Parameter(Mandatory = $true)][string]$CaddyExe,
    [Parameter(Mandatory = $true)][string]$Caddyfile
)
$ErrorActionPreference = "Continue"
$logDir = Join-Path (Split-Path $Caddyfile -Parent) "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "caddy-service.log"
while ($true) {
    Add-Content -Path $runLog -Encoding utf8 -Value "$(Get-Date -Format s) เริ่ม Caddy"
    & $CaddyExe run --config $Caddyfile --adapter caddyfile *>> $runLog
    Add-Content -Path $runLog -Encoding utf8 -Value "$(Get-Date -Format s) Caddy หยุด (รหัส $LASTEXITCODE) — เปิดใหม่ใน 10 วินาที"
    Start-Sleep -Seconds 10
}
