#!/usr/bin/env bash
# Reopen the installed PIA on Linux or native Windows (Git Bash).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
case "${OSTYPE:-$(uname -s)}" in
  msys*|cygwin*|MINGW*) PYTHON="$ROOT/.venv/Scripts/python.exe" ;;
  linux*|Linux*) PYTHON="$ROOT/.venv/bin/python" ;;
  *) printf 'Sistema não suportado.\n' >&2; exit 1 ;;
esac
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
