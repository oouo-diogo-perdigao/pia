# uv run pyinstaller --onefile --noconsole --name "PIA Server Python" --icon "pia.ico" --add-data "pia.png;." pia_launcher.py

import os
import queue
import json
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import autostart
import pystray
from PIL import Image

IS_WINDOWS = sys.platform == "win32"

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(os.environ.get("PIA_DIR", r"D:\codes\pia"))
else:
    PROJECT_DIR = Path(__file__).resolve().parent

LOGS_DIR = PROJECT_DIR / "logs"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import hotkeys

APP_NAME = "PIA Server Python"
POLL_INTERVAL = 500

commands = queue.Queue()


def resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / filename

    return Path(__file__).resolve().parent / filename


class LogViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("PIA Server - Log Inspector")
        self.root.geometry("1100x700")
        self.root.minsize(700, 400)

        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tabs = {}
        self.positions = {}

        self.status = ttk.Label(
            root,
            text="Monitorando logs...",
            anchor="w",
        )
        self.status.pack(fill="x", padx=8, pady=(0, 8))

        self.scan_logs()
        self.update_logs()
        self.process_commands()

    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def scan_logs(self):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        for log_file in sorted(LOGS_DIR.glob("*.log")):
            if log_file.name not in self.tabs:
                self.create_tab(log_file)

        self.root.after(1000, self.scan_logs)

    def create_tab(self, log_file: Path):
        frame = ttk.Frame(self.notebook)

        text = tk.Text(
            frame,
            wrap="none",
            bg="#111111",
            fg="#dddddd",
            insertbackground="#ffffff",
            selectbackground="#444444",
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )

        vertical = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=text.yview,
        )

        horizontal = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=text.xview,
        )

        text.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        if log_file.stem.lower() == 'stt':
            progress_frame = ttk.Frame(frame)
            progress_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=8)
            progress_label = ttk.Label(progress_frame, text='Transcrição local: aguardando')
            progress_label.pack(anchor='w')
            progress_bar = ttk.Progressbar(progress_frame, maximum=100, mode='determinate')
            progress_bar.pack(fill='x', pady=(4, 0))
        text.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")

        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.notebook.add(frame, text=log_file.stem)

        self.tabs[log_file.name] = {
            "file": log_file,
            "text": text,
            "frame": frame,
        }

        if log_file.stem.lower() == 'stt':
            self.tabs[log_file.name].update(progress_label=progress_label, progress_bar=progress_bar, progress_buffer='')
        self.positions[log_file.name] = 0

        self.load_initial_content(log_file.name)

    def load_initial_content(self, filename):
        info = self.tabs[filename]
        log_file = info["file"]
        text = info["text"]

        try:
            with log_file.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as file:
                content = file.read()

                text.insert("end", content)
                self.update_stt_progress(info, content)
                text.see("end")

                self.positions[filename] = file.tell()

        except (FileNotFoundError, PermissionError, OSError):
            pass

    def update_logs(self):
        for filename, info in list(self.tabs.items()):
            log_file = info["file"]
            text = info["text"]

            try:
                if not log_file.exists():
                    continue

                size = log_file.stat().st_size
                position = self.positions.get(filename, 0)

                if size < position:
                    position = 0
                    text.delete("1.0", "end")

                if size > position:
                    with log_file.open(
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    ) as file:
                        file.seek(position)
                        new_content = file.read()
                        self.positions[filename] = file.tell()

                    if new_content:
                        should_scroll = text.yview()[1] >= 0.98

                        text.insert("end", new_content)
                        self.update_stt_progress(info, new_content)

                        if should_scroll:
                            text.see("end")

            except (FileNotFoundError, PermissionError, OSError):
                pass

        self.root.after(POLL_INTERVAL, self.update_logs)

    def update_stt_progress(self, info, content):
        if 'progress_bar' not in info:
            return
        content = info.get('progress_buffer', '') + content
        lines = content.split('\n')
        info['progress_buffer'] = lines.pop()
        for line in lines:
            if '[STT_PROGRESS] ' not in line:
                continue
            try:
                data = json.loads(line.split('[STT_PROGRESS] ', 1)[1])
                state = data['state']
                bar = info['progress_bar']
                bar.stop()
                if state == 'preparing':
                    bar.configure(mode='indeterminate', value=0)
                    bar.start(15)
                    label = 'Local: carregando modelo / preparando áudio...'
                elif state == 'transcribing':
                    percent = max(0, min(99.9, float(data['percent'])))
                    bar.configure(mode='determinate', value=percent)
                    processed, duration = float(data['processed']), float(data['duration'])
                    label = f'Local: {percent:.1f}% — {self.audio_time(processed)} / {self.audio_time(duration)}'
                elif state == 'completed':
                    bar.configure(mode='determinate', value=100)
                    label = 'Local: transcrição concluída — 100%'
                elif state == 'error':
                    bar.configure(mode='determinate')
                    label = 'Local: falha na transcrição; consulte o log'
                else:
                    continue
                info['progress_label'].configure(text=label)
            except (ValueError, TypeError, KeyError):
                continue

    @staticmethod
    def audio_time(seconds):
        seconds = max(0, int(seconds))
        return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'

    def process_commands(self):
        try:
            while True:
                command = commands.get_nowait()

                if command == "show":
                    self.show()

                elif command == "quit":
                    self.root.destroy()
                    return

        except queue.Empty:
            pass

        self.root.after(100, self.process_commands)


def create_tray_image():
    return Image.open(resource_path("pia.png")).convert("RGBA")


def terminate_server(server):
    if server.poll() is not None:
        return

    if IS_WINDOWS:
        subprocess.run(
            [
                "taskkill",
                "/PID",
                str(server.pid),
                "/T",
                "/F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if not IS_WINDOWS:
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def start_server():
    if IS_WINDOWS:
        return subprocess.Popen(
            ["uv", "run", "python", "-m", "server"],
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    python = sys.executable if not getattr(sys, "frozen", False) else "python3"
    return subprocess.Popen(
        [python, "-m", "server"],
        cwd=PROJECT_DIR,
        start_new_session=True,
        preexec_fn=_die_with_parent,
    )


def _die_with_parent():
    import ctypes

    PR_SET_PDEATHSIG = 1
    try:
        ctypes.CDLL("libc.so.6").prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except OSError:
        pass


def start_hotkeys():
    script = PROJECT_DIR / "hotkeys.py"
    if not script.exists():
        return None

    if IS_WINDOWS:
        command = ["uv", "run", "python", str(script)]
        flags = subprocess.CREATE_NO_WINDOW
    else:
        python = sys.executable if not getattr(sys, "frozen", False) else "python3"
        command = [python, str(script)]
        flags = 0

    try:
        return subprocess.Popen(command, cwd=PROJECT_DIR, creationflags=flags)
    except OSError:
        return None


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


def main():
    server = start_server()
    hotkeys_process = start_hotkeys()

    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, lambda *_: commands.put("quit"))
        signal.signal(signal.SIGHUP, lambda *_: commands.put("quit"))

    root = tk.Tk()
    root.withdraw()

    LogViewer(root)

    def show_viewer(icon, item):
        commands.put("show")

    def quit_application(icon, item):
        stop_process(hotkeys_process)
        terminate_server(server)

        icon.stop()

        commands.put("quit")

    def tray_action(action):
        def handler(icon, item):
            if IS_WINDOWS:
                threading.Thread(
                    target=hotkeys.run_action,
                    args=(action, hotkeys.load_config()),
                    daemon=True,
                ).start()
                return
            # Runs out of process so its clipboard Tk instance doesn't clash with the log viewer's.
            subprocess.Popen(
                [sys.executable, str(PROJECT_DIR / "hotkeys.py"), action],
                cwd=PROJECT_DIR,
            )

        return handler

    def toggle_autostart(icon, item):
        autostart.set_enabled(not autostart.is_enabled())

    tray_menu = pystray.Menu(
        pystray.MenuItem(
            "Abrir inspeção",
            show_viewer,
            default=True,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ditado (STT)", tray_action("dictation")),
        pystray.MenuItem("Ler área de transferência (TTS)", tray_action("speak")),
        pystray.MenuItem("Ler em modo história (TTS)", tray_action("storytelling")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Inicializar",
            toggle_autostart,
            checked=lambda item: autostart.is_enabled(),
        ),
        pystray.MenuItem(
            "Encerrar PIA",
            quit_application,
        ),
    )

    tray_icon = pystray.Icon(
        APP_NAME,
        create_tray_image(),
        APP_NAME,
        tray_menu,
    )

    if IS_WINDOWS:
        tray_icon.run_detached()
    else:
        # The GTK/AppIndicator backends need their own GLib loop, which tkinter doesn't run.
        threading.Thread(target=tray_icon.run, daemon=True).start()

    try:
        root.mainloop()
    finally:
        stop_process(hotkeys_process)
        terminate_server(server)


if __name__ == "__main__":
    main()
