# uv run pyinstaller --onefile --noconsole --name "PIA Server Python" --icon "pia.ico" --add-data "pia.png;." pia_launcher.py

import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pystray
from PIL import Image

PROJECT_DIR = Path(r"D:\codes\pia")
LOGS_DIR = PROJECT_DIR / "logs"

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

        text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.notebook.add(frame, text=log_file.stem)

        self.tabs[log_file.name] = {
            "file": log_file,
            "text": text,
            "frame": frame,
        }

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

                        if should_scroll:
                            text.see("end")

            except (FileNotFoundError, PermissionError, OSError):
                pass

        self.root.after(POLL_INTERVAL, self.update_logs)

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

    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def main():
    server = subprocess.Popen(
        ["uv", "run", "python", "-m", "server"],
        cwd=PROJECT_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    root = tk.Tk()
    root.withdraw()

    LogViewer(root)

    def show_viewer(icon, item):
        commands.put("show")

    def quit_application(icon, item):
        terminate_server(server)

        icon.stop()

        commands.put("quit")

    tray_menu = pystray.Menu(
        pystray.MenuItem(
            "Abrir inspeção",
            show_viewer,
            default=True,
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

    tray_icon.run_detached()

    root.mainloop()


if __name__ == "__main__":
    main()
