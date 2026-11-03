# Sets up or updates the exam system on the server. Open PowerShell in the folder that holds docker-compose.yml and run:
#   .\deploy.ps1            first time (asks two questions, then starts everything) and every later update
#   .\deploy.ps1 -Seed      also creates the first accounts (only for an empty database; the passwords are shown once)
#   .\deploy.ps1 -Drill     also runs the safety drill against the judge (must end with: 39 of 39 checks passed)
# It never touches any other app on this server. To go back to an earlier version put OAP_TAG=<version> in .env and run it again.
param([switch]$Seed, [switch]$Drill)
Set-Location $PSScriptRoot

function Fail($message) { Write-Host $message -ForegroundColor Red; exit 1 }

docker version --format "{{.Server.Version}}" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running. Start Docker Desktop, wait until it says it is running, and run this again." }
if (-not (Test-Path docker-compose.yml)) { Fail "docker-compose.yml is not in this folder ($PSScriptRoot)." }

# 1. The settings file, made once: random passwords nobody has to know, plus the Cloudflare token.
if (-not (Test-Path .env)) {
    function New-Secret { $bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); ([BitConverter]::ToString($bytes)).Replace("-", "") }
    $domain = $env:OAP_DOMAIN
    if (-not $domain) { $domain = Read-Host "Address of the exam system [assessment.globx.co.in]" }
    if (-not $domain) { $domain = "assessment.globx.co.in" }
    $token = $env:CLOUDFLARE_API_TOKEN
    if (-not $token) {
        $hidden = Read-Host "Cloudflare API token (what you type is hidden)" -AsSecureString
        $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($hidden))
    }
    if ($token -notmatch '^[A-Za-z0-9_-]{30,}$') { Fail "That does not look like a Cloudflare API token. Nothing was written; run this again." }
    $lines = "DOMAIN=$domain", "DB_PASSWORD=$(New-Secret)", "SECRET_KEY=$(New-Secret)", "CLOUDFLARE_API_TOKEN=$token", "LLM_PROVIDER=none", "LLM_OPENAI_API_KEY=", "LLM_OPENAI_MODEL=gpt-4o-mini"
    [IO.File]::WriteAllText((Join-Path $PWD ".env"), (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
    icacls .env /inheritance:r /grant:r "$($env:USERNAME):F" "Administrators:F" 2>&1 | Out-Null   # only this user and administrators can read it
    Write-Host ".env written (random passwords; the Cloudflare token is in it, keep the file private)." -ForegroundColor Green
}

# 2. Windows Firewall: HTTPS (443) from the office network only.
if (-not (Get-NetFirewallRule -DisplayName "Exam system HTTPS" -ErrorAction SilentlyContinue)) {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) {
        New-NetFirewallRule -DisplayName "Exam system HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -RemoteAddress LocalSubnet -Action Allow | Out-Null
        Write-Host "Firewall: port 443 opened for the office network." -ForegroundColor Green
    } else {
        Write-Host "Could not open port 443 in Windows Firewall: run PowerShell as Administrator once (right-click, Run as administrator)." -ForegroundColor Yellow
    }
}

# 3. Download the images GitHub built and start them.
docker compose pull
if ($LASTEXITCODE -ne 0) { Fail "The images could not be downloaded. First time: sign in once with   docker login ghcr.io -u <GitHub user name>   (the password is the read-only token), then run this again." }
docker compose up -d
if ($LASTEXITCODE -ne 0) { Fail "The system did not start. Run   docker compose logs   and send me the last lines (no passwords are in them)." }

$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    if ((docker inspect -f "{{.State.Health.Status}}" oap-api-1 2>$null) -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 3
}
docker compose ps
if (-not $healthy) { Fail "The exam server is not healthy after 3 minutes. Run   docker compose logs api   and send me the last lines." }

if ($Seed) { docker compose exec -T api python -m app.seed }
if ($Drill) { docker compose run --rm --no-deps judge python -m app.sandbox.hostile }
Write-Host "Running. Open https://$((Select-String -Path .env -Pattern '^DOMAIN=(.*)$').Matches[0].Groups[1].Value) from another computer in the office." -ForegroundColor Green
