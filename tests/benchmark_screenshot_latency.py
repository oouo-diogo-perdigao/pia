"""Reproducible Before/After latency benchmark for screenshot capture (t0..t3).

Measures t0 (capture trigger), t1 (frame ready), t2 (shell presented), t3 (editor ready)
and optional t4 (window finalize) in offscreen Chromium with a deterministic 1920x1080
synthetic desktop frame (never captures the real screen or plays real audio).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PyQt6.QtCore import QObject, QRect, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
from PyQt6.QtWidgets import QApplication

from src import settings_store, user_paths


def _make_synthetic_frame(width: int = 1920, height: int = 1080) -> Image.Image:
    """Create a deterministic desktop-like 1920x1080 image for realistic PNG cost."""
    img = Image.new("RGB", (width, height), (28, 30, 44))
    draw = ImageDraw.Draw(img)
    for y in range(0, height, 6):
        shade = 24 + (y * 60 // height)
        draw.line([(0, y), (width, y)], fill=(shade, shade + 6, shade + 22))
    for i in range(18):
        x0 = 40 + (i * 97) % (width - 360)
        y0 = 40 + (i * 71) % (height - 220)
        color = ((60 + i * 29) % 240, (90 + i * 43) % 240, (140 + i * 19) % 240)
        draw.rectangle([x0, y0, x0 + 300, y0 + 160], fill=color, outline=(220, 220, 235))
        draw.line([(x0 + 10, y0 + 24), (x0 + 280, y0 + 24)], fill=(245, 245, 250), width=2)
    return img


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(len(ordered) - 1, low + 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _summarize(samples: list[dict]) -> dict:
    keys = ("t1_t0", "t2_t0", "t3_t0")
    summary = {"count": len(samples)}
    for key in keys:
        vals = [s[key] for s in samples if s.get(key) is not None]
        if vals:
            summary[key] = {
                "min": round(min(vals), 1),
                "p50": round(statistics.median(vals), 1),
                "p95": round(_percentile(vals, 95), 1),
                "max": round(max(vals), 1),
            }
    t4_vals = [s["t4_t0"] for s in samples if s.get("t4_t0") is not None]
    if t4_vals:
        summary["t4_t0"] = {
            "min": round(min(t4_vals), 1),
            "p50": round(statistics.median(t4_vals), 1),
            "p95": round(_percentile(t4_vals, 95), 1),
            "max": round(max(t4_vals), 1),
        }
    return summary


def run_benchmark(runs_per_mode: int = 10, label: str = "current") -> dict:
    fixture_profile = tempfile.TemporaryDirectory(
        prefix="pia-bench-profile-", ignore_cleanup_errors=True
    )
    user_paths.USER_DIR = Path(fixture_profile.name)

    class _FixtureVault:
        def __init__(self):
            self.items = {}

        def get(self, name):
            return self.items.get(name)

        def set(self, name, value):
            self.items[name] = value

        def delete(self, name):
            self.items.pop(name, None)

    settings_store._store = settings_store.SettingsStore(
        user_paths.USER_DIR / "workspace.sqlite3", _FixtureVault()
    )

    for optional_mod in ("pyautogui", "pyperclip"):
        if optional_mod not in sys.modules:
            try:
                __import__(optional_mod)
            except ImportError:
                sys.modules[optional_mod] = SimpleNamespace()

    from src.LocalActions import LocalActions
    from src.pia import http
    from src.pia.service import Apps, WorkspaceService
    from src.workspace_store import WorkspaceStore
    from Plugins.Apps.screenshots import native as native_mod

    app = QApplication.instance() or QApplication(["pia-screenshot-bench"])
    app.setQuitOnLastWindowClosed(False)

    synthetic_img = _make_synthetic_frame(1920, 1080)
    active_rect = QRect(120, 90, 960, 640)

    def js(shell, script: str):
        output = []
        shell.view.page().runJavaScript(script, lambda result: output.append(result))
        for _ in range(2000):
            QTest.qWait(2)
            if output:
                return output[0]
        return None

    with tempfile.TemporaryDirectory(
        prefix="pia-bench-work-", ignore_cleanup_errors=True
    ) as work_dir:
        root = Path(work_dir)
        store = WorkspaceStore(root / "workspace.db")
        backend = SimpleNamespace(
            store=store,
            reply=lambda *a, **k: "",
            speak=Mock(),
            resources=Mock(),
            secretary=Mock(),
        )
        service = WorkspaceService(backend=backend, apps=Apps())

        ui = SimpleNamespace(
            url="",
            overlay=Mock(),
            controls=Mock(),
            composer=Mock(),
            main_action=Mock(),
            window=Mock(),
        )
        ui.main_action.isChecked.return_value = False

        native_holder: dict[str, object] = {}
        finalize_times: dict[str, float] = {}

        class _Bridge(QObject):
            requested = pyqtSignal(str, object, object)

            def __init__(self):
                super().__init__()
                self.requested.connect(self._execute)

            def call(self, action, payload):
                from concurrent.futures import Future

                fut = Future()
                self.requested.emit(action, payload, fut)
                return fut

            def _execute(self, action, payload, fut):
                try:
                    if action == "app" and payload.get("id") == "screenshots":
                        sub_action = payload["action"]
                        sub_payload = payload.get("payload", {})
                        res = native_holder["app"].handle(sub_action, sub_payload)
                        if sub_action == "finalize":
                            finalize_times[native_holder.get("current_id", "")] = (
                                time.perf_counter() * 1000.0
                            )
                        from concurrent.futures import Future

                        if isinstance(res, Future):
                            res.add_done_callback(
                                lambda f: fut.set_exception(f.exception())
                                if f.exception()
                                else fut.set_result(f.result())
                            )
                        else:
                            fut.set_result(res)
                    else:
                        fut.set_result({"ok": True})
                except Exception as exc:
                    fut.set_exception(exc)

        bridge = _Bridge()
        service.native_handler = bridge.call

        class BenchHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/action/screen-all":
                    png = LocalActions.screenshot_all()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(png)))
                    self.end_headers()
                    self.wfile.write(png)
                    return
                http.route(self)

            def do_POST(self):
                http.route(self)

        server = ThreadingHTTPServer(("127.0.0.1", 0), BenchHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"http://127.0.0.1:{server.server_port}"
        ui.url = origin

        prefs = {
            "format": "png",
            "quality": 92,
            "prefill_title": True,
            "prefill_url": False,
            "border": False,
            "output_folder": str(root / "saved"),
            "auto_save": True,
            "auto_copy": False,
            "default_tool": "free",
            "default_color": "#ff4278",
            "default_width": 3,
            "smooth": True,
            "bgr": False,
        }

        results = {
            "label": label,
            "resolution": "1920x1080",
            "runs_per_mode": runs_per_mode,
            "modes": {},
        }

        with (
            patch.object(http, "get_service", return_value=service),
            patch("src.config_paths.BASE_DIR", root),
            patch("PIL.ImageGrab.grab", return_value=synthetic_img),
            patch("src.LocalActions.ImageGrab.grab", return_value=synthetic_img),
            patch.object(native_mod, "config", return_value=prefs),
            patch.object(
                native_mod,
                "foreground",
                return_value=("Janela de Teste", "", active_rect),
            ),
            patch.object(
                native_mod.QGuiApplication,
                "screens",
                return_value=[SimpleNamespace(geometry=lambda: QRect(0, 0, 1920, 1080))],
            ),
            patch.object(
                native_mod.QApplication,
                "clipboard",
                return_value=Mock(),
            ),
            patch("Plugins.Connectors.pia_server.media.enqueue", return_value=None),
        ):
            # Also patch play_shutter_sound if present so benchmark is silent.
            sound_patch = (
                patch.object(native_mod, "_play_shutter_sound", return_value=None)
                if hasattr(native_mod, "_play_shutter_sound")
                else None
            )
            if sound_patch:
                sound_patch.start()

            try:
                for mode in ("selection", "window"):
                    # Reset CaptureShell cache before cold start if present.
                    if hasattr(native_mod.CaptureShell, "reset_cache"):
                        native_mod.CaptureShell.reset_cache()

                    native_app = native_mod.NativeApp(ui, None)
                    native_holder["app"] = native_app

                    orig_store = native_app.store_capture
                    orig_create = native_mod.CaptureShell.create
                    marks: dict[str, float] = {}

                    def timed_store(*args, **kwargs):
                        identity = orig_store(*args, **kwargs)
                        marks["t1"] = time.perf_counter() * 1000.0
                        return identity

                    def timed_create(u, url, geom):
                        shell = orig_create(u, url, geom)
                        if not getattr(shell, "_bench_wrapped", False):
                            orig_present = shell.present

                            def timed_present():
                                orig_present()
                                marks["t2"] = time.perf_counter() * 1000.0

                            shell.present = timed_present
                            shell._bench_wrapped = True
                        return shell

                    native_app.store_capture = timed_store
                    samples: list[dict] = []

                    with patch.object(
                        native_mod.CaptureShell, "create", side_effect=timed_create
                    ):
                        total_iters = runs_per_mode + 1  # 1 cold-start + N warm
                        for idx in range(total_iters):
                            marks.clear()
                            finalize_times.clear()
                            t0 = time.perf_counter() * 1000.0
                            fut = native_app.capture(mode)

                            for _ in range(4000):
                                QTest.qWait(2)
                                if fut.done():
                                    break
                            res = fut.result(timeout=10)
                            identity = res["id"]
                            native_holder["current_id"] = identity

                            # Wait for window.piaCapture.ready === true
                            t3 = None
                            t4 = None
                            deadline = time.perf_counter() + 15.0
                            while time.perf_counter() < deadline:
                                QTest.qWait(2)
                                if mode == "window" and identity in finalize_times:
                                    t4 = finalize_times[identity]
                                if native_app.shell is not None:
                                    ready_info = js(
                                        native_app.shell,
                                        "window.piaCapture ? {ready: !!window.piaCapture.ready, id: window.piaCapture.currentId || null} : null",
                                    )
                                    if ready_info and ready_info.get("ready"):
                                        if (
                                            ready_info.get("id") is None
                                            or ready_info.get("id") == identity
                                        ):
                                            if t3 is None:
                                                t3 = time.perf_counter() * 1000.0
                                            if mode == "selection" or t4 is not None:
                                                break
                                if mode == "window" and t4 is not None and t3 is None:
                                    t3 = t4
                                    break

                            if t3 is None:
                                raise RuntimeError(
                                    f"Timeout aguardando piaCapture.ready (mode={mode}, iter={idx})"
                                )

                            # Use internal native t1 if available (more exact before disk write)
                            rec = native_app.records.get(identity) or {}
                            native_timings = (
                                getattr(native_app, "last_timings", None) or {}
                            )
                            t1 = native_timings.get("t1", marks.get("t1", t0))
                            t2 = native_timings.get("t2", marks.get("t2", t1))
                            t0_actual = native_timings.get("t0", t0)

                            sample = {
                                "iter": idx,
                                "kind": "cold" if idx == 0 else "warm",
                                "t1_t0": round(max(0.0, t1 - t0_actual), 2),
                                "t2_t0": round(max(0.0, t2 - t0_actual), 2),
                                "t3_t0": round(max(0.0, t3 - t0_actual), 2),
                            }
                            if mode == "window" and t4 is not None:
                                sample["t4_t0"] = round(max(0.0, t4 - t0_actual), 2)
                            samples.append(sample)

                            if mode == "selection":
                                native_app.handle("cancel", {})
                                QTest.qWait(20)
                            else:
                                QTest.qWait(20)

                    native_app.shutdown()
                    if hasattr(native_mod.CaptureShell, "reset_cache"):
                        native_mod.CaptureShell.reset_cache()

                    cold = [s for s in samples if s["kind"] == "cold"]
                    warm = [s for s in samples if s["kind"] == "warm"]
                    results["modes"][mode] = {
                        "cold": _summarize(cold),
                        "warm": _summarize(warm),
                        "samples": samples,
                    }
            finally:
                if sound_patch:
                    sound_patch.stop()
                server.shutdown()
                server.server_close()

    fixture_profile.cleanup()
    return results


def _format_table(data: dict, before: dict | None = None) -> str:
    lines = [
        f"Benchmark Captura de Tela — {data['label']} ({data['resolution']}, {data['runs_per_mode']} warm + 1 cold por modo)",
        "",
        "| Modo | Tipo | t1-t0 p50 (ms) | t2-t0 p50 (ms) | t3-t0 p50 (ms) | t3-t0 p95 (ms) |"
        + (" Ganho p50 (%) | Ganho p95 (%) |" if before else ""),
        "|---|---|---:|---:|---:|---:|" + ("---:|---:|" if before else ""),
    ]
    for mode in ("selection", "window"):
        for kind in ("cold", "warm"):
            row = data["modes"][mode][kind]
            t1 = row.get("t1_t0", {}).get("p50", 0)
            t2 = row.get("t2_t0", {}).get("p50", 0)
            t3_50 = row.get("t3_t0", {}).get("p50", 0)
            t3_95 = row.get("t3_t0", {}).get("p95", 0)
            extra = ""
            if before:
                b_row = before["modes"][mode][kind]
                b50 = b_row.get("t3_t0", {}).get("p50", 0)
                b95 = b_row.get("t3_t0", {}).get("p95", 0)
                g50 = ((b50 - t3_50) / b50 * 100.0) if b50 > 0 else 0.0
                g95 = ((b95 - t3_95) / b95 * 100.0) if b95 > 0 else 0.0
                extra = f" {g50:+.1f}% | {g95:+.1f}% |"
            lines.append(
                f"| {mode} | {kind} | {t1:.1f} | {t2:.1f} | {t3_50:.1f} | {t3_95:.1f} |{extra}"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Benchmark screenshot latency t0..t3")
    parser.add_argument("--runs", type=int, default=10, help="Warm runs per mode")
    parser.add_argument("--label", default="Depois", help="Label for this run")
    parser.add_argument("--save-json", type=Path, default=None)
    parser.add_argument("--compare", type=Path, default=None)
    args = parser.parse_args()

    result = run_benchmark(runs_per_mode=args.runs, label=args.label)
    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    before = None
    if args.compare and args.compare.is_file():
        before = json.loads(args.compare.read_text(encoding="utf-8"))

    print(_format_table(result, before=before))


if __name__ == "__main__":
    main()
