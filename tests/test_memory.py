from pathlib import Path

from src.memory import MemoryStore, normalize_text


def test_normalize_text_removes_accents_and_punctuation():
    assert normalize_text("  ABRIR o YouTube! ") == "abrir o youtube"
    assert normalize_text("Já copiei.") == "ja copiei"
