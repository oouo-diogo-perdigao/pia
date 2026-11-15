#!/usr/bin/env bash
# Reopen the installed PIA on Linux or native Windows (Git Bash).
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
case "${OSTYPE:-$(uname -s)}" in
  msys*|cygwin*|MINGW*) PLATFORM=windows; PYTHON="$ROOT/.venv/Scripts/python.exe" ;;
  linux*|Linux*) PLATFORM=linux; PYTHON="$ROOT/.venv/bin/python" ;;
  *) printf 'Sistema não suportado.\n' >&2; exit 1 ;;
esac
# Inspect the selected command without launching the desktop or requiring a venv.
if [[ "${1:-}" == --dry-run ]]; then
  shift
  printf 'PIA · iniciando para %s em %s\n' "$PLATFORM" "$ROOT"
  printf '+ '; printf '%q ' "$PYTHON" -m src.launcher "$@"; printf '\n'
  exit 0
fi
if [[ ! -f "$PYTHON" ]]; then
  printf 'PIA ainda não instalada. Execute: bash install.sh\n' >&2
  exit 1
fi

# sudo zera XAUTHORITY e o runtime do PipeWire. A sessão gráfica é do usuário.
if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
  session_uid="$(id -u "$SUDO_USER")"
  runtime="/run/user/${session_uid}"
  if [[ -d "$runtime" ]]; then
    session_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    if [[ -z "${XAUTHORITY:-}" || ! -r "${XAUTHORITY}" ]]; then
      cookie="$(find "$runtime" -maxdepth 1 -name '.mutter-Xwaylandauth.*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}')"
      [[ -n "$cookie" ]] && export XAUTHORITY="$cookie"
    fi
    if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
      wayland_sock="$(find "$runtime" -maxdepth 1 -name 'wayland-*' ! -name '*.lock' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}')"
      [[ -n "$wayland_sock" ]] && export WAYLAND_DISPLAY="$(basename "$wayland_sock")"
    fi
    export XDG_RUNTIME_DIR="$runtime"
    export DISPLAY="${DISPLAY:-:0}"
    if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "$runtime/bus" ]]; then
      export DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime}/bus"
    fi
    exec runuser -u "$SUDO_USER" -- env \
      HOME="$session_home" \
      USER="$SUDO_USER" \
      LOGNAME="$SUDO_USER" \
      PATH="$PATH" \
      DISPLAY="$DISPLAY" \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      ${XAUTHORITY:+XAUTHORITY="$XAUTHORITY"} \
      ${WAYLAND_DISPLAY:+WAYLAND_DISPLAY="$WAYLAND_DISPLAY"} \
      ${DBUS_SESSION_BUS_ADDRESS:+DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"} \
      ${XDG_CURRENT_DESKTOP:+XDG_CURRENT_DESKTOP="$XDG_CURRENT_DESKTOP"} \
      ${XDG_SESSION_TYPE:+XDG_SESSION_TYPE="$XDG_SESSION_TYPE"} \
      bash "$ROOT/start.sh" "$@"
  fi
fi

exec "$PYTHON" -m src.launcher "$@"
