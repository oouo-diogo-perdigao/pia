from pathlib import Path

from src.memory import MemoryStore, normalize_text


def test_normalize_text_removes_accents_and_punctuation():
    assert normalize_text("  ABRIR o YouTube! ") == "abrir o youtube"
    assert normalize_text("Já copiei.") == "ja copiei"


def test_learned_action_roundtrip(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.json")
    item = store.add_learned_action(
        trigger="abre o jogo do roque no youtube",
        description="Jogo do Roque",
        action_type="open_url",
        value="https://www.youtube.com/@nossamesanossalendas",
    )

    matched = store.match_learned_action(
        "Abre o jogo do Roque no YouTube"
    )

    assert matched is not None
    assert matched["id"] == item["id"]
    assert matched["action"]["value"] == (
        "https://www.youtube.com/@nossamesanossalendas"
    )
