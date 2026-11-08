<#
.SYNOPSIS
  SCOR 11 dokumendiassistendi käivitamine Windowsis.

.DESCRIPTION
  1. Loob esimesel käivitusel virtuaalkeskkonna .venv ja paigaldab sõltuvused (vajab internetti).
  2. Kontrollib, kas kohalik Ollama vastab (hoiatab, kui ei vasta).
  3. Käivitab Streamliti AINULT aadressil 127.0.0.1.
  Pärast esimest paigaldust töötab skript ilma internetita.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start.ps1 -Install   # sõltuvuste uuesti paigaldamine
#>
param(
    [switch]$Install,
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtuaalkeskkonda .venv ei leitud - loon selle..." -ForegroundColor Cyan
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m venv .venv } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            Write-Host "Pythonit ei leitud. Paigalda Python 3.12 või 3.13 (python.org) ja märgi 'Add python.exe to PATH'." -ForegroundColor Red
            exit 1
        }
        & python -m venv .venv
    }
    $Install = $true
}

if ($Install) {
    Write-Host "Paigaldan sõltuvused (requirements.txt)..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "Sõltuvuste paigaldamine ebaõnnestus." -ForegroundColor Red; exit 1 }
}

# Ollama aadress .env failist või vaikimisi lokaalne
$ollamaUrl = "http://127.0.0.1:11434"
if ($env:SCOR_OLLAMA_URL) { $ollamaUrl = $env:SCOR_OLLAMA_URL }
elseif (Test-Path ".env") {
    $line = Get-Content ".env" | Where-Object { $_ -match '^\s*SCOR_OLLAMA_URL\s*=' } | Select-Object -First 1
    if ($line) { $ollamaUrl = ($line -split '=', 2)[1].Trim().Trim('"') }
}
try {
    $v = Invoke-RestMethod -Uri "$ollamaUrl/api/version" -TimeoutSec 3
    Write-Host "Ollama töötab ($ollamaUrl, versioon $($v.version))." -ForegroundColor Green
} catch {
    Write-Host "HOIATUS: Ollama ei vasta aadressil $ollamaUrl. Käivita Ollama (Start-menüü -> Ollama või 'ollama serve')." -ForegroundColor Yellow
    Write-Host "Rakendus käivitub, kuid indekseerimine ja vastamine ei tööta enne Ollama käivitamist." -ForegroundColor Yellow
}

Write-Host "Käivitan rakenduse: http://localhost:$Port  (peatamiseks Ctrl+C)" -ForegroundColor Cyan
& $venvPython -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
