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

# 4. Instalar PyTorch com suporte a CUDA (Versão Estável)
Write-Host "Instalando PyTorch com CUDA..." -ForegroundColor Yellow
& $Pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Nota: Caso prefira PyTorch CPU (sem placa NVIDIA), comente a linha acima e use a linha abaixo:
# & $Pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

Write-Host "Testando suporte a GPU (CUDA)..." -ForegroundColor Yellow
& $Python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA disponível:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NENHUMA')"

# 5. Instalar dependências do projeto
Write-Host "Instalando dependências do requirements.txt..." -ForegroundColor Yellow
& $Pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

# 6. Testar o Kokoro TTS
Write-Host "Testando Kokoro TTS..." -ForegroundColor Yellow
& $Python -c "from kokoro import KModel, KPipeline; import torch; d='cuda' if torch.cuda.is_available() else 'cpu'; m=KModel().to(d).eval(); p=KPipeline(lang_code='p', model=m); print('Kokoro OK no dispositivo:', d)"

# 7. Instalação opcional do eSpeak NG
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Verificando/Instalando eSpeak NG via winget..." -ForegroundColor Yellow
    try {
        winget install --id eSpeak-NG.eSpeak-NG --exact --accept-source-agreements --accept-package-agreements --no-upgrade
    } catch {
        Write-Host "eSpeak NG já instalado ou processo ignorado." -ForegroundColor Gray
    }
} else {
    Write-Warning "winget não encontrado. Certifique-se de instalar o eSpeak NG manualmente caso o Kokoro exija."
}

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Instalação concluída com sucesso!" -ForegroundColor Green

# Criar atalhos na pasta do Inicializar (Startup) do Windows
Write-Host "Criando atalhos na pasta de Inicialização do Windows..." -ForegroundColor Yellow

$StartupFolder = [Environment]::GetFolderPath("Startup")
$WshShell = New-Object -ComObject WScript.Shell

# Mapeia os arquivos que você quer colocar na inicialização
$FilesToShortcut = @("startup\piaTTSServer.vbs", "startup\piaTTS.ahk")

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
Write-Host "Pressione Ctrl + Alt + T para utilizar a síntese de voz." -ForegroundColor Yellow