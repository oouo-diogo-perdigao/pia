"""Regressão do CI: importar o AudioRecorder não pode carregar o sounddevice.

O sounddevice inicializa o PortAudio na importação; em runners sem servidor de
áudio isso derrubava a coleta de testes (PortAudioError do PulseAudio).
"""

import importlib
import sys


def test_import_does_not_load_sounddevice(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # import falharia
    monkeypatch.delitem(sys.modules, "src.AudioRecorder", raising=False)
    module = importlib.import_module("src.AudioRecorder")
    assert hasattr(module, "AudioRecorder")
