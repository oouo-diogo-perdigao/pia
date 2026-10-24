$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PIA SAT ===" -ForegroundColor Cyan

# ============================================================
# 0. Identificar o Sistema Operacional
# ============================================================

$IsLinuxOS = $IsLinux -or ([System.Environment]::OSVersion.Platform -eq "Unix")
$IsWindowsOS = $IsWindows -or ($env:OS -like "*Windows*")

if ($IsLinuxOS) {
    Write-Host "Sistema operacional detectado: Linux" -ForegroundColor Gray
} elseif ($IsWindowsOS) {
    Write-Host "Sistema operacional detectado: Windows" -ForegroundColor Gray
}

# ============================================================
# 1. Verificar instalação do uv
# ============================================================

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if ($IsLinuxOS) {
        $InstallCmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"
    } else {
        $InstallCmd = 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'
    }
    throw "O 'uv' não foi encontrado no PATH. Instale-o antes de continuar (ex: $InstallCmd)."
}

Write-Host "Ferramenta uv detectada com sucesso." -ForegroundColor Green

# ============================================================
# 2. Instalar dependências do sistema no Linux (PortAudio / Build tools)
# ============================================================

if ($IsLinuxOS) {
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Write-Host "Verificando dependências do sistema para o PyAudio e compilação no Linux..." -ForegroundColor Yellow

    if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
        Write-Host "Instalando dependências nativas via gerenciador de pacotes do sistema..." -ForegroundColor Yellow
        if (Get-Command apt -ErrorAction SilentlyContinue) {
            sudo apt update
            sudo apt install -y portaudio19-dev python3-dev build-essential sox libsox-fmt-all
        } elseif (Get-Command dnf -ErrorAction SilentlyContinue) {
            sudo dnf install -y portaudio-devel python3-devel gcc sox
        } elseif (Get-Command pacman -ErrorAction SilentlyContinue) {
            sudo pacman -S --needed --noconfirm portaudio base-devel sox
        } else {
            Write-Warning "Gerenciador de pacotes não identificado. Certifique-se de ter 'portaudio' e 'build-essential' instalados."
        }
    }

    # Ícone na bandeja (pystray via AppIndicator) precisa do PyGObject e da lib AppIndicator
    Write-Host "Instalando dependências do ícone da bandeja (AppIndicator / PyGObject)..." -ForegroundColor Yellow
    if (Get-Command apt -ErrorAction SilentlyContinue) {
        sudo apt install -y pkg-config libcairo2-dev libgirepository-2.0-dev gir1.2-ayatanaappindicator3-0.1 wl-clipboard
    } elseif (Get-Command dnf -ErrorAction SilentlyContinue) {
        sudo dnf install -y pkgconf-pkg-config cairo-devel gobject-introspection-devel libayatana-appindicator-gtk3 wl-clipboard
    } elseif (Get-Command pacman -ErrorAction SilentlyContinue) {
        sudo pacman -S --needed --noconfirm pkgconf cairo gobject-introspection libayatana-appindicator wl-clipboard
    }
}

# ============================================================
# 3. Criar ambiente virtual
# ============================================================

if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual (.venv) com uv..." -ForegroundColor Yellow
    uv venv
}

# ============================================================
# 4. Instalar dependências
# ============================================================

Write-Host "Instalando dependências com uv..." -ForegroundColor Yellow
uv sync

# ============================================================
# 5. Arquivo .env
# ============================================================

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Arquivo .env criado a partir do .env.example." -ForegroundColor Green
    } else {
        Write-Warning "Arquivo .env.example não encontrado."
    }
}

if (-not (Test-Path "keywords.txt")) {
    if (Test-Path "keywords.example.txt") {
        Copy-Item "keywords.example.txt" "keywords.txt"
        Write-Host "Arquivo keywords.txt criado a partir do keywords.example.txt" -ForegroundColor Green
    } else {
        Write-Warning "Arquivo keywords.example.txt não encontrado."
    }
}

if (-not (Test-Path "shortcuts.yaml")) {
    if (Test-Path "shortcuts.example.yaml") {
        Copy-Item "shortcuts.example.yaml" "shortcuts.yaml"
        Write-Host "Arquivo shortcuts.yaml criado a partir do shortcuts.example.yaml" -ForegroundColor Green
    } else {
        Write-Warning "Arquivo shortcuts.example.yaml não encontrado."
    }
}

if (-not (Test-Path "models.yaml")) {
    if (Test-Path "models.example.yaml") {
        Copy-Item "models.example.yaml" "models.yaml"
        Write-Host "Arquivo models.yaml criado a partir do models.example.yaml" -ForegroundColor Green
    } else {
        Write-Warning "Arquivo models.example.yaml não encontrado."
    }
}

# ============================================================
# 6. Instalar SoX
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Verificando SoX..." -ForegroundColor Yellow

if (Get-Command sox -ErrorAction SilentlyContinue) {
    Write-Host "SoX já está instalado." -ForegroundColor Green
} else {
    if ($IsWindowsOS) {
        Write-Host "SoX não encontrado. Instalando via winget..." -ForegroundColor Yellow
        winget install --id ChrisBagwell.SoX --source winget --accept-source-agreements --accept-package-agreements
        Write-Host "SoX instalado. Um novo terminal pode ser necessário para atualizar o PATH." -ForegroundColor Green
    } elseif ($IsLinuxOS) {
        Write-Host "Instalando SoX via gerenciador de pacotes..." -ForegroundColor Yellow
        if (Get-Command apt -ErrorAction SilentlyContinue) {
            sudo apt install -y sox libsox-fmt-all
        } elseif (Get-Command dnf -ErrorAction SilentlyContinue) {
            sudo dnf install -y sox
        } elseif (Get-Command pacman -ErrorAction SilentlyContinue) {
            sudo pacman -S --needed --noconfirm sox
        }
    }
}

# ============================================================
# 7. Verificar CUDA Toolkit / nvcc
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Verificando CUDA Toolkit..." -ForegroundColor Yellow

$CudaHome = $null

if ($IsWindowsOS) {
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
} elseif ($IsLinuxOS) {
    $CudaCandidates = @(
        "/usr/local/cuda-12.1",
        "/usr/local/cuda",
        "/usr/cuda"
    )
    foreach ($Candidate in $CudaCandidates) {
        if (Test-Path (Join-Path $Candidate "bin/nvcc")) {
            $CudaHome = $Candidate
            break
        }
    }
}

if (-not $CudaHome -and (Get-Command nvcc -ErrorAction SilentlyContinue)) {
    $NvccPath = (Get-Command nvcc).Source
    $CudaHome = Split-Path -Parent (Split-Path -Parent $NvccPath)
}

if ($CudaHome) {
    Write-Host "CUDA Toolkit encontrado: $CudaHome" -ForegroundColor Green

    $env:CUDA_HOME = $CudaHome
    $env:CUDA_PATH = $CudaHome

    $CudaBin = Join-Path $CudaHome "bin"
    $PathSeparator = if ($IsWindowsOS) { ";" } else { ":" }

    if (-not (($env:PATH -split $PathSeparator) -contains $CudaBin)) {
        $env:PATH = "$CudaBin$PathSeparator$env:PATH"
    }

    Write-Host "CUDA_HOME configurado: $env:CUDA_HOME" -ForegroundColor Green

    $NvccExe = if ($IsWindowsOS) { Join-Path $CudaBin "nvcc.exe" } else { Join-Path $CudaBin "nvcc" }
    $NvccVersion = & $NvccExe --version 2>&1

    Write-Host "nvcc detectado:" -ForegroundColor Cyan
    Write-Host $NvccVersion

    if ($IsWindowsOS) {
        [Environment]::SetEnvironmentVariable("CUDA_HOME", $CudaHome, "User")
        [Environment]::SetEnvironmentVariable("CUDA_PATH", $CudaHome, "User")
    }
} else {
    Write-Warning "CUDA Toolkit 12.1 não foi encontrado."
    Write-Host "O flash-attn precisa do CUDA Toolkit para ser compilado." -ForegroundColor Yellow
    Write-Host "Abrindo a página oficial para instalação do CUDA Toolkit 12.1.1..." -ForegroundColor Yellow

    if ($IsWindowsOS) {
        Start-Process "https://developer.nvidia.com/cuda-12-1-1-download-archive"
    } elseif ($IsLinuxOS) {
        if (Get-Command xdg-open -ErrorAction SilentlyContinue) {
            xdg-open "https://developer.nvidia.com/cuda-12-1-1-download-archive"
        } else {
            Write-Host "Acesse: https://developer.nvidia.com/cuda-12-1-1-download-archive" -ForegroundColor Yellow
        }
    }

    Write-Warning "Instale o CUDA Toolkit 12.1.1 e execute este instalador novamente."
}

# ============================================================
# 8. Criar atalhos na Inicialização do Sistema
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan

if ($IsWindowsOS) {
    Write-Host "Marcando a PIA para iniciar com o Windows (atalho para o .exe)..." -ForegroundColor Yellow
    uv run python -c "import autostart, sys; sys.exit(0 if autostart.set_enabled(True) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "A inicialização com o Windows não foi marcada. Gere dist\PIA Server Python.exe e use o item Inicializar no menu."
    }
} elseif ($IsLinuxOS) {
    Write-Host "Marcando a PIA para iniciar com o Linux..." -ForegroundColor Yellow
    & (Join-Path $Root ".venv/bin/python") -c "import autostart, sys; sys.exit(0 if autostart.set_enabled(True) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Não foi possível gravar ~/.config/autostart/piaSAT.desktop."
    } else {
        Write-Host "Autostart gravado em ~/.config/autostart/piaSAT.desktop" -ForegroundColor Green
    }
}

# ============================================================
# 9. Inicializar os serviços imediatamente
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Iniciando os serviços do PIA SAT em segundo plano..." -ForegroundColor Yellow

if ($IsWindowsOS) {
    $Exe = Join-Path $Root "dist\PIA Server Python.exe"
    if (Test-Path $Exe) {
        Start-Process -FilePath $Exe -WorkingDirectory $Root
        Write-Host "PIA iniciada: $Exe" -ForegroundColor Cyan
    } else {
        Write-Warning "Executável não encontrado: $Exe"
    }
} elseif ($IsLinuxOS) {
    $LinuxStartupScript = Join-Path $Root "startup/piaSATServer.sh"
    if (Test-Path $LinuxStartupScript) {
        Start-Process "bash" -ArgumentList $LinuxStartupScript -WorkingDirectory $Root
        Write-Host "Serviço iniciado: $LinuxStartupScript" -ForegroundColor Cyan
    } else {
        Write-Warning "Script de inicialização do Linux não encontrado: startup/piaSATServer.sh"
    }
}

# ============================================================
# 10. Finalização
# ============================================================

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "Instalação concluída e serviços em execução!" -ForegroundColor Green
Write-Host "Pressione a atalho configurado para utilizar a transcrição." -ForegroundColor Yellow