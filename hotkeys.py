"""Atalhos globais da PIA.

No GNOME (Wayland) um processo comum não lê o teclado do sistema. Este
arquivo registra os atalhos em shortcuts.yaml no próprio GNOME, e cada
tecla dispara `hotkeys.py <ação>`, que chama o servidor.

Fora do GNOME (Windows e outros desktops em X11) o mesmo arquivo fica
escutando o teclado com pynput. O launcher sobe esse listener junto com a API.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = PROJECT_DIR / "logs" / "hotkeys.log"
EXAMPLE_FILE = PROJECT_DIR / "shortcuts.example.yaml"
CONFIG_FILE = PROJECT_DIR / "shortcuts.yaml"

GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH_ROOT = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
GNOME_BINDING_SCHEMA = f"{GNOME_SCHEMA}.custom-keybinding"

ACTIONS = ("voice", "dictation", "speak", "storytelling")
ACTION_LABELS = {
    "voice": "PIA: sessão de voz",
    "dictation": "PIA: ditado",
    "speak": "PIA: ler área de transferência",
    "storytelling": "PIA: ler em modo história",
}

DEFAULT_SHORTCUTS = {
    "voice": {"windows": "ctrl+alt+p", "linux": "ctrl+alt+p"},
    "dictation": {"windows": "ctrl+alt+d", "linux": "ctrl+alt+shift+d"},
    "speak": {"windows": "ctrl+alt+t", "linux": "ctrl+alt+shift+t"},
    "storytelling": {"windows": "ctrl+alt+l", "linux": "ctrl+alt+l"},
}

GNOME_MODIFIERS = {
    "ctrl": "Primary",
    "control": "Primary",
    "alt": "Alt",
    "shift": "Shift",
    "super": "Super",
    "win": "Super",
    "meta": "Super",
}
PYNPUT_MODIFIERS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "super": "<cmd>",
    "win": "<cmd>",
    "meta": "<cmd>",
}


def current_os() -> str:
    if sys.platform == "win32":
        return "windows"
    return "linux"


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {message}"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def notify(message: str) -> None:
    log(message)
    if not shutil.which("notify-send"):
        return
    subprocess.run(
        ["notify-send", "--app-name=PIA", "--expire-time=1800", "PIA", message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def normalize_server(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _shortcut_value(item: dict, system: str, fallback: str) -> str:
    if system in item and item[system] is not None:
        return str(item[system]).strip()
    return fallback


def load_config(path: Path | None = None) -> dict:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_DIR / ".env")
    except ImportError:
        pass

    source = path
    if source is None:
        source = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_FILE

    raw = {}
    if source is not None and source.exists():
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{source} precisa ser um mapa YAML.")
        raw = loaded

    shortcuts_raw = raw.get("shortcuts") or {}
    if not isinstance(shortcuts_raw, dict):
        raise ValueError("A chave 'shortcuts' precisa ser um mapa.")

    shortcuts = {}
    for name, fallback in DEFAULT_SHORTCUTS.items():
        item = shortcuts_raw.get(name) or {}
        if not isinstance(item, dict):
            raise ValueError(f"O atalho '{name}' precisa ser um mapa com windows e linux.")
        shortcuts[name] = {
            "windows": _shortcut_value(item, "windows", fallback["windows"]),
            "linux": _shortcut_value(item, "linux", fallback["linux"]),
        }

    server = str(raw.get("server") or os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8762")
    voice = str(raw.get("voice") or os.getenv("TTS_DEFAULT_VOICE") or "pm_santa")
    speed = float(raw.get("speed") if raw.get("speed") is not None else os.getenv("TTS_DEFAULT_SPEED") or 0.95)
    return {
        "server": normalize_server(server),
        "voice": voice,
        "speed": speed,
        "shortcuts": shortcuts,
    }


def split_shortcut(shortcut: str) -> tuple[list[str], str]:
    parts = [part.strip().lower() for part in shortcut.split("+")]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        raise ValueError(
            f"Atalho inválido '{shortcut}'. Use modificador+tecla, por exemplo ctrl+alt+p."
        )
    modifiers, key = parts[:-1], parts[-1]
    unknown = [item for item in modifiers if item not in GNOME_MODIFIERS]
    if unknown:
        raise ValueError(f"Modificador desconhecido '{unknown[0]}' em '{shortcut}'.")
    return modifiers, key


def to_gnome(shortcut: str) -> str:
    modifiers, key = split_shortcut(shortcut)
    tokens = [f"<{GNOME_MODIFIERS[item]}>" for item in modifiers]
    tokens.append(key if len(key) == 1 else key.capitalize())
    return "".join(tokens)


def to_pynput(shortcut: str) -> str:
    modifiers, key = split_shortcut(shortcut)
    tokens = [PYNPUT_MODIFIERS[item] for item in modifiers]
    tokens.append(key if len(key) == 1 else f"<{key}>")
    return "+".join(tokens)


def normalize_binding(binding: str) -> str:
    return binding.replace("<Primary>", "<Control>").replace("<Super>", "<Super>").lower()


def parse_gsettings_list(raw: str) -> list[str]:
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        parsed = ast.literal_eval(raw[start : end + 1])
    except (SyntaxError, ValueError):
        return re.findall(r"'([^']*)'", raw)
    if not isinstance(parsed, (list, tuple)):
        return []
    return [str(item) for item in parsed]


def merge_custom_paths(existing: list[str], enabled: list[str]) -> list[str]:
    kept = [path for path in existing if "/pia-" not in path]
    return kept + enabled


def binding_conflicts(binding: str, dumped: str) -> list[str]:
    wanted = normalize_binding(binding)
    found = []
    for line in dumped.splitlines():
        if "/pia-" in line or "custom-keybindings/pia-" in line:
            continue
        for candidate in parse_gsettings_list(line):
            if candidate and normalize_binding(candidate) == wanted:
                key_name = line.split(" ", 2)[1] if line.count(" ") >= 2 else line
                found.append(key_name)
    return found


def gnome_path(action: str) -> str:
    return f"{GNOME_PATH_ROOT}/pia-{action}/"


def action_command(action: str) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} {action}"


def _gsettings(*args: str) -> str:
    result = subprocess.run(
        ["gsettings", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _gsettings_set(schema: str, key: str, value: str, path: str | None = None) -> None:
    target = schema if path is None else f"{schema}:{path}"
    subprocess.run(["gsettings", "set", target, key, value], check=True)


def install_gnome(config: dict) -> None:
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings não está disponível; não dá para registrar atalhos no GNOME.")

    existing = parse_gsettings_list(_gsettings("get", GNOME_SCHEMA, "custom-keybindings"))
    desktop_bindings = ""
    for schema in (GNOME_SCHEMA, "org.gnome.desktop.wm.keybindings"):
        try:
            desktop_bindings += subprocess.run(
                ["gsettings", "list-recursively", schema],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    enabled_paths = []
    registered = []
    for action in ACTIONS:
        shortcut = config["shortcuts"][action]["linux"].strip()
        path = gnome_path(action)
        if not shortcut:
            _gsettings_set(GNOME_BINDING_SCHEMA, "binding", "''", path)
            continue

        binding = to_gnome(shortcut)
        conflicts = binding_conflicts(binding, desktop_bindings)
        if conflicts:
            notify(
                f"{shortcut} ({ACTION_LABELS[action]}) já é usado pelo sistema "
                f"({', '.join(conflicts)}). Troque 'linux' em shortcuts.yaml."
            )

        _gsettings_set(GNOME_BINDING_SCHEMA, "name", ACTION_LABELS[action], path)
        _gsettings_set(GNOME_BINDING_SCHEMA, "command", action_command(action), path)
        _gsettings_set(GNOME_BINDING_SCHEMA, "binding", binding, path)
        enabled_paths.append(path)
        registered.append(f"{shortcut} -> {action}")

    merged = merge_custom_paths(existing, enabled_paths)
    rendered = "[" + ", ".join(f"'{path}'" for path in merged) + "]"
    _gsettings_set(GNOME_SCHEMA, "custom-keybindings", rendered)
    log("Atalhos do GNOME atualizados: " + "; ".join(registered))


def read_clipboard() -> str:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        result = subprocess.run(
            ["wl-paste", "--no-newline", "--type", "text"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return ""

    try:
        import pyperclip

        text = pyperclip.paste() or ""
        if text:
            return text
    except Exception:
        pass

    return _read_clipboard_tk()


def _read_clipboard_tk() -> str:
    try:
        import tkinter as tk
    except ImportError:
        return ""
    try:
        root = tk.Tk()
    except tk.TclError:
        return ""
    try:
        root.withdraw()
        return root.clipboard_get()
    except tk.TclError:
        return ""
    finally:
        root.destroy()


def request(method: str, url: str, payload: dict | None = None) -> tuple[int | None, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, {}


def run_action(action: str, config: dict) -> None:
    base = config["server"]
    if action == "voice":
        status, _payload = request("POST", f"{base}/ove/start", {})
        if status == 200:
            notify("Sessão de voz iniciada")
        else:
            notify("Servidor PIA não está rodando")
        return

    if action == "dictation":
        status, payload = request("GET", f"{base}/action/local-record")
        if status is None:
            notify("Servidor PIA não está rodando")
            return
        if str(payload.get("status", "")).upper() in {"RECORDING", "STOPPING"}:
            request("DELETE", f"{base}/action/local-record")
            notify("Finalizando...")
            return
        request("POST", f"{base}/action/local-record", {"insert_at_cursor": True})
        notify("Escutando")
        return

    if action in {"speak", "storytelling"}:
        status, payload = request("GET", f"{base}/tts/status")
        if status is None:
            notify("Servidor PIA não está rodando")
            return
        if payload.get("status") in {"generating", "playing", "paused"}:
            request("POST", f"{base}/tts/stop", {})
            notify("Leitura parada")
            return
        text = read_clipboard().strip()
        if not text:
            notify("Área de transferência vazia")
            return
        route = "/tts/storytelling" if action == "storytelling" else "/tts/speak"
        request(
            "POST",
            f"{base}{route}",
            {"text": text, "voice": config["voice"], "speed": config["speed"]},
        )
        notify("Enviado para leitura...")
        return

    raise ValueError(f"Ação desconhecida: {action}")


def is_gnome() -> bool:
    desktop = " ".join(
        os.environ.get(name, "")
        for name in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "XDG_SESSION_DESKTOP")
    ).lower()
    return "gnome" in desktop or desktop.strip() == "ubuntu"


def listen(config: dict) -> None:
    try:
        from pynput.keyboard import GlobalHotKeys
    except ImportError:
        log("pynput não está instalado. Rode uv sync para escutar atalhos fora do GNOME.")
        return

    system = current_os()
    mapping = {}
    for action in ACTIONS:
        shortcut = config["shortcuts"][action][system].strip()
        if not shortcut:
            continue
        mapping[to_pynput(shortcut)] = lambda action=action: run_action(action, config)

    if not mapping:
        log(f"Nenhum atalho configurado para {system}.")
        return

    log("Escutando atalhos: " + ", ".join(f"{combo}" for combo in mapping))
    with GlobalHotKeys(mapping) as hotkeys:
        hotkeys.join()


def main() -> None:
    config = load_config()
    argument = sys.argv[1] if len(sys.argv) > 1 else ""

    if argument in ACTION_LABELS:
        run_action(argument, config)
        return
    if argument == "listen":
        listen(config)
        return
    if argument in {"", "install"}:
        if current_os() == "linux" and is_gnome():
            install_gnome(config)
            return
        listen(config)
        return

    print(
        "Uso: hotkeys.py [install|listen|voice|dictation|speak|storytelling]",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
