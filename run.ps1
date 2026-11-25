$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    & $venvPy -m audiobook_studio.app @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m audiobook_studio.app @args
} else {
    python -m audiobook_studio.app @args
}
