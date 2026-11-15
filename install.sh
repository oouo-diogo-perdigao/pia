#!/usr/bin/env bash
# The single installer for Linux and Windows (run in Git Bash on Windows).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# A Windows drive opened by PowerShell's bash.exe is still a native Windows
# installation. Hand off before selecting Python or installing dependencies.
if [[ "$ROOT" =~ ^/mnt/[a-zA-Z]/ ]] && {
  [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" || -e /proc/sys/fs/binfmt_misc/WSLInterop ]] ||
    grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null ||
    command -v powershell.exe >/dev/null 2>&1
}; then
  GIT_BASH=""
  for candidate in "/mnt/c/Program Files/Git/bin/bash.exe" "/mnt/c/Program Files (x86)/Git/bin/bash.exe"; do
    if [[ -x "$candidate" ]]; then GIT_BASH="$candidate"; break; fi
  done
  if [[ -z "$GIT_BASH" ]] && command -v powershell.exe >/dev/null 2>&1; then
    git_bash_win="$(powershell.exe -NoProfile -Command '
      $git = Get-Command git.exe -ErrorAction SilentlyContinue
      if ($git) {
        $base = Split-Path (Split-Path $git.Source)
        $candidate = Join-Path $base "bin\bash.exe"
        if (Test-Path -LiteralPath $candidate) { $candidate }
      }
    ' | tr -d '\r' || true)"
    if [[ -n "$git_bash_win" ]]; then GIT_BASH="$(wslpath -u "$git_bash_win")"; fi
  fi
  if [[ -z "$GIT_BASH" || ! -x "$GIT_BASH" ]]; then
    printf 'PIA: diretório Windows acessado pelo WSL. Instale o Git for Windows e execute novamente; nenhuma dependência Linux foi instalada.\n' >&2
    exit 1
  fi
  WIN_ROOT="$(wslpath -w "$ROOT")"
  exec "$GIT_BASH" -c 'cd -- "$1" && shift && exec bash "./$1" "${@:2}"' pia-windows "$WIN_ROOT" "${BASH_SOURCE[0]##*/}" "$@"
fi
SYSTEM=1; AUTOSTART=1; PODCAST=1; DRY_RUN=0; START=1
for arg in "$@"; do
  case "$arg" in
    --no-system) SYSTEM=0 ;;
    --no-autostart) AUTOSTART=0 ;;
    --no-podcast) PODCAST=0 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-start) START=0 ;;
    --help) printf '%s\n' 'bash install.sh [--no-system] [--no-autostart] [--no-podcast] [--dry-run] [--no-start]'; exit 0 ;;
    *) printf 'Opção desconhecida: %s\n' "$arg" >&2; exit 2 ;;
  esac
done
case "${OSTYPE:-$(uname -s)}" in
  msys*|cygwin*|MINGW*) PLATFORM=windows ;;
  linux*|Linux*) PLATFORM=linux ;;
  *) printf 'Sistema não suportado: %s\n' "${OSTYPE:-unknown}" >&2; exit 1 ;;
esac
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; if (( ! DRY_RUN )); then "$@"; fi; }
printf 'PIA · instalando para %s em %s\n' "$PLATFORM" "$ROOT"
if [[ "$PLATFORM" == windows ]]; then
  # Native Windows Python/uv; this is not a WSL installation.
  if ! command -v uv >/dev/null 2>&1; then
    run powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
      'Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression'
    if command -v cygpath >/dev/null 2>&1; then
      WIN_HOME="$(powershell.exe -NoProfile -Command '[Environment]::GetFolderPath("UserProfile")' | tr -d '\r' || true)"
      export PATH="$(cygpath -u "$WIN_HOME")/.local/bin:$PATH"
    fi
  fi
  if (( SYSTEM )); then
    for pair in 'sox ChrisBagwell.SoX' 'ffmpeg Gyan.FFmpeg'; do
      read -r binary package <<< "$pair"
      if ! command -v "$binary" >/dev/null 2>&1; then
        if ! command -v winget.exe >/dev/null 2>&1; then
          printf 'Instale o App Installer/winget ou %s e tente novamente.\n' "$binary" >&2; exit 1
        fi
        run winget.exe install --id "$package" --exact --source winget --accept-package-agreements --accept-source-agreements
      fi
    done
  fi
else
  if (( SYSTEM )); then
    SUDO=(); if (( EUID != 0 )); then SUDO=(sudo); fi
    if command -v apt-get >/dev/null 2>&1; then
      run "${SUDO[@]}" apt-get update
      run "${SUDO[@]}" apt-get install -y build-essential python3-dev python3-tk portaudio19-dev \
        sox libsox-fmt-all ffmpeg libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
        libegl1 libnss3 libasound2-dev wl-clipboard xclip xdotool libsecret-1-0 gnome-keyring dbus-x11
    elif command -v dnf >/dev/null 2>&1; then
      run "${SUDO[@]}" dnf install -y gcc gcc-c++ python3-devel python3-tkinter portaudio-devel \
        sox ffmpeg xcb-util-cursor libxkbcommon-x11 mesa-libEGL nss alsa-lib wl-clipboard xclip xdotool libsecret gnome-keyring
    elif command -v pacman >/dev/null 2>&1; then
      run "${SUDO[@]}" pacman -S --needed --noconfirm base-devel tk portaudio sox ffmpeg \
        xcb-util-cursor libxkbcommon-x11 mesa nss alsa-lib wl-clipboard xclip xdotool libsecret gnome-keyring
    else
      printf 'Gerenciador não suportado. Instale dependências nativas descritas em docs/DESKTOP.md e use --no-system.\n' >&2; exit 1
    fi
  fi
  if ! command -v uv >/dev/null 2>&1; then
    if (( DRY_RUN )); then
      printf '+ baixar e executar o instalador oficial do uv\n'
    else
      UV_SETUP="$(mktemp)"
      trap 'rm -f -- "$UV_SETUP"' EXIT
      curl -LsSf https://astral.sh/uv/install.sh -o "$UV_SETUP"
      sh "$UV_SETUP"
    fi
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
run uv python install 3.12
SYNC=(uv sync --python 3.12)
if (( PODCAST )); then SYNC+=(--extra podcast); fi
run "${SYNC[@]}"
run uv run --no-sync python -m src.config_paths
if (( AUTOSTART )); then
  run uv run --no-sync python -c 'from src import autostart; autostart.set_enabled(True)'
fi
printf '\nInstalação concluída. Para reabrir a PIA: bash start.sh\n'
printf 'Configurações: config/ · Plugins: Plugins/ · Ajuda: docs/DESKTOP.md\n'
if [[ "$PLATFORM" == windows ]] && (( ! DRY_RUN )); then
  # winget can update the registry PATH without updating the current Git Bash.
  WIN_PATH="$(powershell.exe -NoProfile -Command '[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User")' | tr -d '\r' || true)"
  export PATH="$(cygpath -u -p "$WIN_PATH"):$PATH"
fi
if (( START )); then
  run bash "$ROOT/start.sh"
fi
