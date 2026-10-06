from __future__ import annotations

import ctypes
import io
import mimetypes
import queue
import tempfile
import threading
import time
import uuid
import webbrowser
from collections import deque
from pathlib import Path

import pygame
import pyautogui
import pyperclip
from PIL import Image, ImageGrab

from .config import BASE_DIR, logging


class LocalActions:
    """Local desktop actions exposed through the HTTP action API."""

    def __init__(self, stt_manager):
        self.stt_manager = stt_manager

        self._dictation_queue: queue.Queue | None = None
        self._dictation_thread: threading.Thread | None = None
        self._dictation_stop = threading.Event()

        # Sequential queue audio owns channel 0 exclusively.
        self._queued_audio_items = deque()
        self._queued_audio_condition = threading.Condition()
        self._queued_audio_playing = False
        self._queued_audio_current_id: str | None = None
        self._queued_audio_cancel_current = threading.Event()

        # Immediate audio uses independent channels and may overlap freely.
        self._immediate_lock = threading.RLock()
        self._immediate_pending: set[str] = set()
        self._immediate_cancelled: set[str] = set()
        self._immediate_channels: dict[str, pygame.mixer.Channel] = {}
        self._immediate_sounds: dict[str, pygame.mixer.Sound] = {}

        self._ensure_audio_mixer()
        self._queue_channel = pygame.mixer.Channel(0)

        self._queued_audio_thread = threading.Thread(
            target=self._queued_audio_worker_loop,
            daemon=True,
            name="LocalActionsAudioQueue",
        )
        self._queued_audio_thread.start()

        self._output_dir = BASE_DIR / "cache" / "local_actions"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Cursor / clipboard
    # ------------------------------------------------------------------
    def insert_text_at_cursor(self, text: str) -> None:
        if not isinstance(text, str) or not text:
            raise ValueError("Texto vazio.")

        previous_clipboard = pyperclip.paste()
        try:
            pyperclip.copy(text)
            time.sleep(0.02)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.03)
        finally:
            pyperclip.copy(previous_clipboard)

    def insert_image_at_cursor(self, image_bytes: bytes) -> None:
        if not image_bytes:
            raise ValueError("Imagem vazia.")

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        bmp_buffer = io.BytesIO()
        image.save(bmp_buffer, format="BMP")

        dib = bmp_buffer.getvalue()[14:]
        self._set_windows_clipboard_dib(dib)
        time.sleep(0.03)
        pyautogui.hotkey("ctrl", "v")

    @staticmethod
    def _set_windows_clipboard_dib(dib: bytes) -> None:
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("Inserção de imagem no clipboard requer Windows.")

        GMEM_MOVEABLE = 0x0002
        CF_DIB = 8

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            raise RuntimeError("Falha ao alocar memória para o clipboard.")

        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise RuntimeError("Falha ao bloquear memória do clipboard.")

        try:
            ctypes.memmove(pointer, dib, len(dib))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise RuntimeError("Não foi possível abrir o clipboard.")

        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_DIB, handle):
                kernel32.GlobalFree(handle)
                raise RuntimeError("Não foi possível gravar a imagem no clipboard.")
            handle = None
        finally:
            user32.CloseClipboard()

    def read_text_at_cursor(self) -> str:
        previous_clipboard = pyperclip.paste()
        try:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.02)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.05)
            value = pyperclip.paste()
            return value if isinstance(value, str) else str(value or "")
        finally:
            pyperclip.copy(previous_clipboard)

    @staticmethod
    def delete_text_at_cursor() -> None:
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.02)
        pyautogui.press("backspace")

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------
    @staticmethod
    def screenshot_all() -> bytes:
        image = ImageGrab.grab(all_screens=True)
        return LocalActions._image_to_png(image)

    @staticmethod
    def screenshot_current_monitor() -> bytes:
        if not hasattr(ctypes, "windll"):
            return LocalActions.screenshot_all()

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        user32 = ctypes.windll.user32
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return LocalActions.screenshot_all()

        MONITOR_DEFAULTTONEAREST = 2
        monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)

        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return LocalActions.screenshot_all()

        rect = info.rcMonitor
        image = ImageGrab.grab(
            bbox=(rect.left, rect.top, rect.right, rect.bottom),
            all_screens=True,
        )
        return LocalActions._image_to_png(image)

    @staticmethod
    def _image_to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    # ------------------------------------------------------------------
    # Audio playback
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_audio_mixer() -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init(buffer=512)

        # Channel 0 is reserved for the ordered queue. Other channels are
        # exclusively available to immediate/overlapping audio.
        if pygame.mixer.get_num_channels() < 16:
            pygame.mixer.set_num_channels(16)
        pygame.mixer.set_reserved(1)

    @staticmethod
    def _validate_audio_path(path: str) -> Path:
        value = Path(path).expanduser()
        if not value.is_absolute():
            raise ValueError("O parâmetro 'path' deve ser um caminho absoluto.")
        if not value.is_file():
            raise ValueError(f"Arquivo de áudio não encontrado: {value}")
        return value

    @staticmethod
    def _audio_item(
        *,
        audio_bytes: bytes | None = None,
        content_type: str | None = None,
        path: str | None = None,
    ) -> dict:
        if path:
            return {
                "id": uuid.uuid4().hex,
                "path": LocalActions._validate_audio_path(path),
                "data": None,
                "suffix": None,
            }

        if not audio_bytes:
            raise ValueError("Áudio vazio.")

        suffix = (
            mimetypes.guess_extension((content_type or "").split(";", 1)[0])
            or ".audio"
        )
        return {
            "id": uuid.uuid4().hex,
            "path": None,
            "data": bytes(audio_bytes),
            "suffix": suffix,
        }

    @staticmethod
    def _load_sound(item: dict) -> pygame.mixer.Sound:
        path = item.get("path")
        if path is not None:
            return pygame.mixer.Sound(str(path))

        data = item["data"]
        suffix = (item.get("suffix") or "").lower()

        # WAV/OGG can be decoded directly from an in-memory file object, avoiding
        # the temporary-file round trip on the latency-sensitive route.
        if suffix in {".wav", ".ogg", ".oga"}:
            return pygame.mixer.Sound(file=io.BytesIO(data))

        # SDL_mixer relies on filename/extension for some compressed formats
        # such as MP3, so use a short-lived temp file for those.
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                temp_path = Path(tmp.name)
            return pygame.mixer.Sound(str(temp_path))
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _acquire_immediate_channel(self) -> pygame.mixer.Channel:
        with self._immediate_lock:
            channel_count = pygame.mixer.get_num_channels()

            for index in range(1, channel_count):
                channel = pygame.mixer.Channel(index)
                if not channel.get_busy():
                    return channel

            # Grow instead of stealing another immediate sound or the queue.
            new_count = channel_count + 8
            pygame.mixer.set_num_channels(new_count)
            pygame.mixer.set_reserved(1)
            return pygame.mixer.Channel(channel_count)

    def play_audio(
        self,
        audio_bytes: bytes | None = None,
        content_type: str | None = None,
        *,
        path: str | None = None,
    ) -> str:
        """Play immediately on its own mixer channel.

        Consecutive calls overlap and never interfere with the sequential queue.
        """
        item = self._audio_item(
            audio_bytes=audio_bytes,
            content_type=content_type,
            path=path,
        )
        action_id = item["id"]
        with self._immediate_lock:
            self._immediate_pending.add(action_id)

        threading.Thread(
            target=self._play_immediate_audio,
            args=(item,),
            daemon=True,
            name=f"LocalActionImmediate-{action_id[:8]}",
        ).start()
        return action_id

    def _play_immediate_audio(self, item: dict) -> None:
        action_id = item["id"]
        try:
            with self._immediate_lock:
                if action_id in self._immediate_cancelled:
                    return

            sound = self._load_sound(item)

            with self._immediate_lock:
                if action_id in self._immediate_cancelled:
                    return

            channel = self._acquire_immediate_channel()

            with self._immediate_lock:
                if action_id in self._immediate_cancelled:
                    return
                self._immediate_sounds[action_id] = sound
                self._immediate_channels[action_id] = channel

            channel.play(sound)
            logging.info("[ACTION AUDIO] imediato iniciado id=%s", action_id)

            while channel.get_busy():
                time.sleep(0.02)
        except Exception:
            logging.exception(
                "[ACTION AUDIO] Falha ao reproduzir áudio imediato id=%s",
                action_id,
            )
        finally:
            with self._immediate_lock:
                self._immediate_pending.discard(action_id)
                self._immediate_cancelled.discard(action_id)
                self._immediate_channels.pop(action_id, None)
                self._immediate_sounds.pop(action_id, None)

    def stop_immediate_audio(self, action_id: str | None = None) -> int:
        """Stop one immediate audio by id, or every immediate audio when id is absent."""
        with self._immediate_lock:
            if action_id:
                channel = self._immediate_channels.get(action_id)
                pending = action_id in self._immediate_pending

                if not channel and not pending:
                    return 0

                self._immediate_cancelled.add(action_id)
                if channel:
                    channel.stop()
                return 1

            targets = set(self._immediate_pending) | set(self._immediate_channels)
            self._immediate_cancelled.update(targets)

            for channel in list(self._immediate_channels.values()):
                channel.stop()

            return len(targets)

    def queue_audio(
        self,
        audio_bytes: bytes | None = None,
        content_type: str | None = None,
        *,
        path: str | None = None,
    ) -> str:
        """Append audio to the non-overlapping sequential queue."""
        item = self._audio_item(
            audio_bytes=audio_bytes,
            content_type=content_type,
            path=path,
        )

        with self._queued_audio_condition:
            self._queued_audio_items.append(item)
            self._queued_audio_condition.notify()

        return item["id"]

    def _queued_audio_worker_loop(self) -> None:
        while True:
            with self._queued_audio_condition:
                while not self._queued_audio_items:
                    self._queued_audio_condition.wait()

                item = self._queued_audio_items.popleft()
                self._queued_audio_playing = True
                self._queued_audio_current_id = item["id"]
                self._queued_audio_cancel_current.clear()

            try:
                sound = self._load_sound(item)

                if self._queued_audio_cancel_current.is_set():
                    continue

                self._queue_channel.play(sound)
                logging.info(
                    "[ACTION AUDIO QUEUE] iniciado id=%s restantes=%d",
                    item["id"],
                    len(self._queued_audio_items),
                )

                while self._queue_channel.get_busy():
                    time.sleep(0.02)
            except Exception:
                logging.exception(
                    "[ACTION AUDIO QUEUE] Falha ao reproduzir id=%s",
                    item["id"],
                )
            finally:
                with self._queued_audio_condition:
                    self._queued_audio_playing = False
                    self._queued_audio_current_id = None
                    self._queued_audio_cancel_current.clear()

    def stop_audio_queue(self, *, next_only: bool = False) -> dict:
        """Skip current queue item or stop current and clear every pending item."""
        with self._queued_audio_condition:
            was_playing = self._queued_audio_playing
            current_id = self._queued_audio_current_id
            cleared = 0

            if not next_only:
                cleared = len(self._queued_audio_items)
                self._queued_audio_items.clear()

            if was_playing:
                self._queued_audio_cancel_current.set()
                self._queue_channel.stop()

            self._queued_audio_condition.notify_all()

        return {
            "stopped": bool(was_playing),
            "current_id": current_id,
            "cleared": cleared,
            "next": bool(next_only),
        }

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def save_and_open_image(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> Path:
        if not image_bytes:
            raise ValueError("Imagem vazia.")

        image = Image.open(io.BytesIO(image_bytes))
        suffix = mimetypes.guess_extension((content_type or "").split(";", 1)[0])
        if not suffix:
            suffix = ".png"

        output = self._output_dir / f"image-{uuid.uuid4().hex}{suffix}"

        format_name = Image.registered_extensions().get(suffix.lower()) or "PNG"
        try:
            image.save(output, format=format_name)
        except Exception:
            output = output.with_suffix(".png")
            image.save(output, format="PNG")

        webbrowser.open(output.resolve().as_uri(), new=2)
        return output

    # ------------------------------------------------------------------
    # Local recording orchestration
    # ------------------------------------------------------------------
    def start_local_record(self, *, insert_at_cursor: bool = False) -> dict:
        if insert_at_cursor:
            self._start_dictation_bridge()
        else:
            self._stop_dictation_bridge()

        self.stt_manager.start()
        payload = self.stt_manager.get_status_payload()
        payload["insert_at_cursor"] = bool(insert_at_cursor)
        return payload

    def stop_local_record(self) -> dict:
        self.stt_manager.stop()
        self._stop_dictation_bridge()
        payload = self.stt_manager.get_status_payload()
        payload["insert_at_cursor"] = False
        return payload

    def get_local_record_status(self) -> dict:
        payload = self.stt_manager.get_status_payload()
        payload["insert_at_cursor"] = bool(
            self._dictation_thread and self._dictation_thread.is_alive()
        )
        payload["text_chunks"] = self.stt_manager.get_status_queue()
        return payload

    def add_record_stream(self) -> queue.Queue:
        return self.stt_manager.add_stream_queue()

    def remove_record_stream(self, client_queue: queue.Queue) -> None:
        self.stt_manager.remove_stream_queue(client_queue)

    def get_record_stream_chunks(self, client_queue: queue.Queue) -> list[str]:
        return self.stt_manager.get_stream_queue(client_queue)

    def _start_dictation_bridge(self) -> None:
        if self._dictation_thread and self._dictation_thread.is_alive():
            self._dictation_stop.set()
            if threading.current_thread() is not self._dictation_thread:
                self._dictation_thread.join(timeout=0.5)

        self._dictation_stop.clear()
        client_queue = self.stt_manager.add_stream_queue()
        self._dictation_queue = client_queue

        def worker() -> None:
            try:
                while not self._dictation_stop.is_set() or not client_queue.empty():
                    try:
                        text = client_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if text and text.strip():
                        self.insert_text_at_cursor(text.strip() + " ")
            finally:
                self.stt_manager.remove_stream_queue(client_queue)
                self._dictation_queue = None

        self._dictation_thread = threading.Thread(
            target=worker,
            daemon=True,
            name="LocalActionDictation",
        )
        self._dictation_thread.start()

    def _stop_dictation_bridge(self) -> None:
        self._dictation_stop.set()
        thread = self._dictation_thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=0.5)
        if thread and not thread.is_alive():
            self._dictation_thread = None
