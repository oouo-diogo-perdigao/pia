$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PIA TTS ===" -ForegroundColor Cyan

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

# 5. Instalar dependências do projeto
Write-Host "Instalando dependências do requirements.txt..." -ForegroundColor Yellow
& $Pip install -r requirements.txt


if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Instalação concluída com sucesso!" -ForegroundColor Green

# Criar atalhos na pasta do Inicializar (Startup) do Windows
Write-Host "Criando atalhos na pasta de Inicialização do Windows..." -ForegroundColor Yellow

$StartupFolder = [Environment]::GetFolderPath("Startup")
$WshShell = New-Object -ComObject WScript.Shell

# Mapeia os arquivos que você quer colocar na inicialização
$FilesToShortcut = @("startup\piaSTTServer.vbs", "startup\piaSTT.ahk")

foreach ($File in $FilesToShortcut) {
    $SourcePath = Join-Path $Root $File
    
    if (Test-Path $SourcePath) {
        $FileName = [System.IO.Path]::GetFileNameWithoutExtension($File)
        $ShortcutPath = Join-Path $StartupFolder "$FileName.lnk"
        
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $SourcePath
        $Shortcut.WorkingDirectory = $Root
        $Shortcut.Save()
        
        Write-Host "Atalho criado: $ShortcutPath" -ForegroundColor Gray
    } else {
        Write-Warning "Arquivo não encontrado para criar atalho: $SourcePath"
    }
}

# 9. Inicializar os serviços imediatamente
Write-Host "Iniciando os serviços do PIA TTS em segundo plano..." -ForegroundColor Yellow

foreach ($File in $FilesToStartup) {
    $SourcePath = Join-Path $Root $File
    if (Test-Path $SourcePath) {
        Start-Process -FilePath $SourcePath -WorkingDirectory $Root
        Write-Host "Serviço iniciado: $File" -ForegroundColor Cyan
    }
}

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Instalação concluída e serviços em execução!" -ForegroundColor Green
Write-Host "Pressione Ctrl + Alt + D para utilizar a transcrição." -ForegroundColor Yellow