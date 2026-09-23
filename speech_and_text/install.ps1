$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PIA SAT ===" -ForegroundColor Cyan

# ============================================================
# 1. Verificar instalação do uv
# ============================================================

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "O 'uv' não foi encontrado no PATH. Instale-o antes de continuar (ex: powershell -c ""irm https://astral.sh/uv/install.ps1 | iex"")."
}

Write-Host "Ferramenta uv detectada com sucesso." -ForegroundColor Green

# ============================================================
# 2. Criar ambiente virtual
# ============================================================

if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual (.venv) com uv..." -ForegroundColor Yellow
    uv venv
}

# ============================================================
# 3. Instalar dependências
# ============================================================

Write-Host "Instalando dependências com uv..." -ForegroundColor Yellow
uv sync

# ============================================================
# 4. Arquivo .env
# ============================================================

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Arquivo .env criado a partir do .env.example." -ForegroundColor Green
    }
    else {
        Write-Warning "Arquivo .env.example não encontrado."
    }
}

# ============================================================
# 5. Instalar SoX
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Verificando SoX..." -ForegroundColor Yellow

if (Get-Command sox -ErrorAction SilentlyContinue) {
    Write-Host "SoX já está instalado." -ForegroundColor Green
}
else {
    Write-Host "SoX não encontrado. Instalando via winget..." -ForegroundColor Yellow

    winget install `
        --id ChrisBagwell.SoX `
        --source winget `
        --accept-source-agreements `
        --accept-package-agreements

    Write-Host "SoX instalado. Um novo terminal pode ser necessário para atualizar o PATH." -ForegroundColor Green
}

# ============================================================
# 6. Verificar CUDA Toolkit / nvcc
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Verificando CUDA Toolkit 12.1..." -ForegroundColor Yellow

$CudaHome = $null

$CudaCandidates = @(
    "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1",
    "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1.1"
)

foreach ($Candidate in $CudaCandidates) {
    if (Test-Path (Join-Path $Candidate "bin\nvcc.exe")) {
        $CudaHome = $Candidate
        break
    }
}

if ($CudaHome) {
    Write-Host "CUDA Toolkit encontrado: $CudaHome" -ForegroundColor Green

    $env:CUDA_HOME = $CudaHome
    $env:CUDA_PATH = $CudaHome

    $CudaBin = Join-Path $CudaHome "bin"

    if (-not (($env:PATH -split ";") -contains $CudaBin)) {
        $env:PATH = "$CudaBin;$env:PATH"
    }

    Write-Host "CUDA_HOME configurado: $env:CUDA_HOME" -ForegroundColor Green

    $NvccVersion = & (Join-Path $CudaBin "nvcc.exe") --version 2>&1

    Write-Host "nvcc detectado:" -ForegroundColor Cyan
    Write-Host $NvccVersion

    # Persistir CUDA_HOME para os próximos terminais
    [Environment]::SetEnvironmentVariable(
        "CUDA_HOME",
        $CudaHome,
        "User"
    )

    [Environment]::SetEnvironmentVariable(
        "CUDA_PATH",
        $CudaHome,
        "User"
    )
}
else {
    Write-Warning "CUDA Toolkit 12.1 não foi encontrado."

    Write-Host "O flash-attn precisa do CUDA Toolkit para ser compilado." -ForegroundColor Yellow
    Write-Host "Abrindo a página oficial para instalação do CUDA Toolkit 12.1.1..." -ForegroundColor Yellow

    Start-Process "https://developer.nvidia.com/cuda-12-1-1-download-archive"

    Write-Warning "Instale o CUDA Toolkit 12.1.1 e execute este instalador novamente."
}

# ============================================================
# 7. Criar atalhos na pasta Startup do Windows
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Criando atalhos na pasta de Inicialização do Windows..." -ForegroundColor Yellow

$StartupFolder = [Environment]::GetFolderPath("Startup")
$WshShell = New-Object -ComObject WScript.Shell

$FilesToShortcut = @(
    "startup\piaSATServer.vbs",
    "startup\piaSAT.ahk"
)

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
    }
    else {
        Write-Warning "Arquivo não encontrado para criar atalho: $SourcePath"
    }
}

# ============================================================
# 8. Arquivos que serão iniciados
# ============================================================

$FilesToStartup = @(
    "startup\piaSATServer.vbs",
    "startup\piaSAT.ahk"
)

# ============================================================
# 9. Inicializar os serviços imediatamente
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Iniciando os serviços do PIA SAT em segundo plano..." -ForegroundColor Yellow

foreach ($File in $FilesToStartup) {
    $SourcePath = Join-Path $Root $File

    if (Test-Path $SourcePath) {
        Start-Process `
            -FilePath $SourcePath `
            -WorkingDirectory $Root

        Write-Host "Serviço iniciado: $File" -ForegroundColor Cyan
    }
    else {
        Write-Warning "Arquivo não encontrado: $SourcePath"
    }
}

# ============================================================
# 10. Finalização
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Instalação concluída e serviços em execução!" -ForegroundColor Green
Write-Host "Pressione Ctrl + Alt + D para utilizar a transcrição." -ForegroundColor Yellow