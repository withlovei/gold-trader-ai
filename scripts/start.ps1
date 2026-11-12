# Start AI Gold Trader. The page and the API are the same local server.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Url = "http://127.0.0.1:8787/"

if (-not (Test-Path $Python)) {
    Write-Host "Chua co moi truong Python. Trong thu muc du an chay: py -3 -m venv .venv"
    exit 1
}

$listening = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Server da chay. Mo $Url"
    Start-Process $Url
    exit 0
}

Write-Host "Dang bat backend va trang web tai $Url"
Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8787"
) -WorkingDirectory $Root

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8787/api/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Host "Server chua san sang. Xem cua so Python vua mo."
    exit 1
}

Start-Process $Url
Write-Host "Da mo $Url"
