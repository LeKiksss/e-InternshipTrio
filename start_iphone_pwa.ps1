[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExpectedVenv = Join-Path $RepositoryRoot ".venv"

if ([string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)) {
    throw "No Python virtual environment is active. Run: & `".\.venv\Scripts\Activate.ps1`""
}

$ActiveVenv = [System.IO.Path]::GetFullPath($env:VIRTUAL_ENV)
$ExpectedVenvPath = [System.IO.Path]::GetFullPath($ExpectedVenv)
if ($ActiveVenv -ne $ExpectedVenvPath) {
    Write-Warning "The active environment is '$ActiveVenv', not this repository's .venv."
}

$Python = Get-Command python -ErrorAction Stop
$Cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $Cloudflared) {
    throw "cloudflared is not available in PATH. Rename the download to cloudflared.exe, add its folder to PATH, reopen PowerShell, and run cloudflared --version."
}

Push-Location -LiteralPath $RepositoryRoot
$ServerProcess = $null
$StandardOutput = Join-Path $env:TEMP "ecare-waitress-$PID.out.log"
$StandardError = Join-Path $env:TEMP "ecare-waitress-$PID.err.log"
$PreviousPort = $env:APP_PORT
$PreviousPublicMode = $env:PUBLIC_HTTPS_MODE

try {
    & $Python.Source -c "import argon2, dotenv, email_validator, flask, flask_login, flask_sqlalchemy, flask_wtf, google.genai, pydantic, waitress, wtforms" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Required Python packages are missing. Run: python -m pip install -r requirements.txt"
    }

    $ExistingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($ExistingListener) {
        throw "Port $Port is already in use. Stop the existing server or rerun this script with -Port followed by another port."
    }

    Write-Host "cloudflared detected:" -ForegroundColor Cyan
    & $Cloudflared.Source --version

    $env:APP_PORT = [string]$Port
    $env:PUBLIC_HTTPS_MODE = "true"
    $ServerProcess = Start-Process `
        -FilePath $Python.Source `
        -ArgumentList @("-u", "serve_public.py") `
        -WorkingDirectory $RepositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StandardOutput `
        -RedirectStandardError $StandardError `
        -PassThru

    Start-Sleep -Seconds 2
    $ServerProcess.Refresh()
    if ($ServerProcess.HasExited) {
        $Failure = if (Test-Path -LiteralPath $StandardError) {
            Get-Content -LiteralPath $StandardError -Raw
        } else {
            "The public server exited before it could accept connections."
        }
        throw $Failure.Trim()
    }

    Write-Host ""
    Write-Host "Waitress is running privately on http://127.0.0.1:$Port." -ForegroundColor Green
    Write-Host "cloudflared will print a temporary HTTPS trycloudflare.com URL below." -ForegroundColor Cyan
    Write-Host "Open that HTTPS URL in Safari on the iPhone, then use Share > Add to Home Screen."
    Write-Host "Press Ctrl+C to stop the tunnel; this script will also stop Waitress."
    Write-Host ""

    & $Cloudflared.Source tunnel --url "http://127.0.0.1:$Port"
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared exited with code $LASTEXITCODE. Review its output above, confirm internet access, and try again."
    }
}
finally {
    if ($ServerProcess) {
        $ServerProcess.Refresh()
        if (-not $ServerProcess.HasExited) {
            Stop-Process -Id $ServerProcess.Id -ErrorAction SilentlyContinue
            $ServerProcess.WaitForExit(5000) | Out-Null
        }
    }
    if ($null -eq $PreviousPort) { Remove-Item Env:APP_PORT -ErrorAction SilentlyContinue } else { $env:APP_PORT = $PreviousPort }
    if ($null -eq $PreviousPublicMode) { Remove-Item Env:PUBLIC_HTTPS_MODE -ErrorAction SilentlyContinue } else { $env:PUBLIC_HTTPS_MODE = $PreviousPublicMode }
    Remove-Item -LiteralPath $StandardOutput, $StandardError -ErrorAction SilentlyContinue
    Pop-Location
    Write-Host "Waitress and the tunnel have stopped." -ForegroundColor Yellow
}
