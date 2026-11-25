<#
.SYNOPSIS
    Install Kokoro Audiobook Studio on Windows 11.
.DESCRIPTION
    Checks Python 3.10-3.12 and ffmpeg (installable via winget), creates .venv,
    installs the package + dependencies, and creates a convenient run.ps1 launcher.
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ffmpeg not found. Installing via winget (Gyan.FFmpeg)..." -ForegroundColor Cyan
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "Install ffmpeg manually from https://www.gyan.dev/ffmpeg/builds/ and add to PATH." -ForegroundColor Yellow
    }
}

$py = (Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
if (-not $py) {
    throw "Python 3.10-3.12 required. Install via: winget install Python.Python.3.12"
}

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    if ($py -like "*py.exe") {
        & $py -3.12 -m venv .venv 2>$null
        if (-not (Test-Path $venvPy)) { & $py -3 -m venv .venv }
    } else {
        & $py -m venv .venv
    }
}

& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -e .

$localBin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $localBin | Out-Null
$scripts = Join-Path $PSScriptRoot ".venv\Scripts"
@"
@echo off
"$scripts\audiobook-studio.exe" %*
"@ | Set-Content -Path (Join-Path $localBin "audiobook-studio.cmd") -Encoding Ascii

Write-Host ""
Write-Host "Kokoro Audiobook Studio installed! Run .\run.ps1 (or .\run.ps1 --doctor)." -ForegroundColor Green
