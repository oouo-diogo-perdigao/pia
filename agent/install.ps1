$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PIA AGENT ===" -ForegroundColor Cyan

# 1. Verificar instalação do Python no sistema
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python não encontrado no PATH. Instale Python 3.11 ou 3.12 e marque 'Add Python to PATH'."
}

$PyVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Python detectado: $PyVersion"

# Definir caminhos do ambiente virtual
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pip = Join-Path $Root ".venv\Scripts\pip.exe"

Write-Host "Iniciando a instalação do projeto..." -ForegroundColor Green

# 2. Criar ambiente virtual se não existir
If (-Not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
}

# 3. Atualizar o pip e ferramentas base
Write-Host "Atualizando pip e utilitários..." -ForegroundColor Yellow
& $Python -m pip install --upgrade pip setuptools wheel

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Arquivo .env criado." -ForegroundColor Yellow
}

# 5. Instalar dependências do projeto
Write-Host "Instalando dependências do requirements.txt..." -ForegroundColor Yellow
& $Pip install -r requirements.txt

Write-Host "" 
Write-Host "Instalação concluída." -ForegroundColor Green
Write-Host "1. Abra .env e informe GEMINI_API_KEY." -ForegroundColor Cyan
Write-Host "2. Execute stt.ahk com AutoHotkey v2." -ForegroundColor Cyan
Write-Host "3. Segure Ctrl+Alt+D para falar e solte para enviar." -ForegroundColor Cyan
