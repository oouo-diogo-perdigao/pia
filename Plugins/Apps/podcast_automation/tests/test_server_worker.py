"""Testes offline com fixtures para o worker Python em duas fases (C3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from podcast_automation import notification, server_worker


def _sample_account(*, bucket="bucket-teste", with_campaign=True):
    campaigns = (
        {
            "Mestre": {
                "Campanha": "Crônicas de Eldoria",
                "rss_key": "eldoria/rss.xml",
                "players": {"Alice": "Lyra", "Bruno": "Thorin"},
                "closed": False,
            }
        }
        if with_campaign
        else {}
    )
    return {
        "id": "acc-42",
        "config": {
            "nomes_reais": {"mestre_disc": "Mestre", "alice_disc": "Alice", "bruno_disc": "Bruno"},
            "campaign_details": campaigns,
            "publication": {
                "brand": "TravelRPG",
                "language": "pt-BR",
                "unpublished_prefix": "nao-publicados",
            },
            "audio": {},
            "processing": {
                "minimum_session_seconds": 60,
                "duplicate_max_bytes": 100000,
                "duplicate_max_seconds": 3600,
            },
            "outputs": {
                "mp3": True,
                "srt": True,
                "vtt": True,
                "txt": True,
                "resumo.json": True,
            },
            "discord_users": {
                "Alice": "111111111111111111",
                "Bruno": "222222222222222222",
                "Invalido": "nao-e-snowflake",
            },
        },
        "storage": {
            "bucket": bucket,
            "publicUrl": "https://cdn.example.test",
            "endpoint": "https://s3.example.test",
            "accountId": "storage-acc-42",
            "accessKeyId": "AKIAFAKEKEY1234567890",
            "secretAccessKey": "super-secret-value-never-persist",
        },
    }


def _create_recording_zip(tmp_path: Path, name="Guild-20261119-voz.aup.zip", members=None) -> Path:
    archive = tmp_path / name
    files = members or {
        "pia.aup": "<project/>",
        "pia_data/mestre_disc.flac": "fake-flac",
        "pia-session.json": json.dumps(
            {
                "version": 1,
                "source": "pia-server-discord",
                "sessionTitle": "Nome Inicial da Mesa",
            }
        ),
    }
    with zipfile.ZipFile(archive, "w") as zf:
        for member_name, content in files.items():
            zf.writestr(member_name, content)
    return archive


class FakeStorage:
    def __init__(self, public_base="https://cdn.example.test"):
        self.public_base = public_base.rstrip("/")
        self.uploads: list[tuple[str, str, str]] = []
        self.puts: list[tuple[str, bytes | str]] = []
        self.identity = {"bucket": "bucket-teste", "url": self.public_base}

    def getObjectIfExists(self, _key: str):
        return None

    def sendObject(self, path: str, key: str, content_type: str = "application/octet-stream"):
        assert Path(path).is_file()
        self.uploads.append((str(path), key, content_type))

    def putObject(self, key: str, data, content_type: str = "application/octet-stream"):
        self.puts.append((key, data))

    def list_objects(self, _prefix: str):
        return []

    def public_url(self, key: str) -> str:
        return f"{self.public_base}/{key.lstrip('/')}"


def _make_fake_audio_factory(calls: list[str]):
    class FakeAudio:
        def __init__(self, name, pasta_extraida, nomes_reais, campaigns, obj_storage, recording_metadata=None):
            calls.append("audio_init")
            self.pasta_extraida = Path(pasta_extraida)
            self.arquivos_participantes = [str(self.pasta_extraida / "pia_data/mestre_disc.flac")]
            self.edit_timeline = []
            self.grupos_transcricao = {}
            self.campanha = "Crônicas de Eldoria"
            self.narrador = "Mestre"
            self.personagens = ["Lyra", "Thorin"]
            self.jogadores = ["Alice", "Bruno"]
            self.ouvintes = []
            self.session = 2
            self.episode = 7
            self.rss = "eldoria/rss.xml"
            self.recording_metadata = recording_metadata or {}

        def mix(self):
            calls.append("audio_mix")
            mix = self.pasta_extraida / "mix.wav"
            mix.write_bytes(b"RIFF-mix")
            return str(mix)

        def build(self):
            calls.append("audio_build")
            mp3 = self.pasta_extraida / "episodio-temp.mp3"
            mp3.write_bytes(b"ID3-fake-mp3")
            return str(mp3)

    return FakeAudio


def _make_fake_whisper_factory(calls: list[str]):
    class FakeWhisper:
        def __init__(self, _nomes, _campaigns):
            self.folder = None

        def carregar_pasta(self, item):
            calls.append("whisper_load")
            self.folder = Path(item["pasta_extraida"])

        def build(self):
            calls.append("whisper_build")

        def gravar_srt(self):
            p = self.folder / "temp.srt"
            p.write_text("1\n00:00:00,000 --> 00:00:02,000\nOlá\n", encoding="utf-8")
            return str(p)

        def gravar_vtt(self):
            p = self.folder / "temp.vtt"
            p.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOlá\n", encoding="utf-8")
            return str(p)

        def gravar_roteiro(self):
            p = self.folder / "temp.txt"
            p.write_text("[00:00:00] Alice: Entramos na taverna.\n", encoding="utf-8")
            return str(p)

        def descarregar_modelo(self):
            calls.append("whisper_unload")

    return FakeWhisper


def _make_fake_summary_factory(calls: list[str]):
    class FakeSummary:
        def __init__(self, *, roteiro_path, **_kwargs):
            self.roteiro_path = Path(roteiro_path)
            self.resumo_json_path = str(self.roteiro_path.with_suffix(".resumo.json"))
            self.sugestoes_titulo = [
                "A Chama da Torre",
                "Nome Inicial da Mesa",
                "Ecos da Ponte",
                "O Juramento Quebrado",
            ]

        def gerar_resumo(self):
            calls.append("summary_generate")
            Path(self.resumo_json_path).write_text(
                json.dumps(
                    {
                        "nome_sessao": "A Chama da Torre",
                        "resumo_rapido": "Resumo curto da sessão.",
                        "resumo_completo": "Parágrafo completo da sessão.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return ("A Chama da Torre", "Resumo curto da sessão.", "Parágrafo completo da sessão.")

        def incluir_resumo_no_roteiro(self, item):
            calls.append("summary_inject_txt")
            body = self.roteiro_path.read_text(encoding="utf-8")
            self.roteiro_path.write_text(
                f"<!-- INICIO_RESUMO_SESSAO -->\nCampanha: {item['campanha']}\n\nNome da Sessão: {item['nome_sessao']}\n<!-- FIM_RESUMO_SESSAO -->\n\n{body}",
                encoding="utf-8",
            )

    return FakeSummary


def test_prepare_retains_without_publishing_persists_no_secrets_and_is_idempotent(tmp_path):
    archive = _create_recording_zip(tmp_path)
    work_dir = tmp_path / "work" / "acc-42" / "rec-001"
    storage = FakeStorage()
    calls: list[str] = []
    events: list[dict] = []

    payload = {
        "action": "prepare",
        "recordingId": "rec-001",
        "archive": str(archive),
        "workDir": str(work_dir),
        "account": _sample_account(),
        "suggestionCount": 3,
    }

    result = server_worker.prepare_session(
        payload,
        emit=events.append,
        storage_adapter=storage,
        audio_factory=_make_fake_audio_factory(calls),
        whisper_factory=_make_fake_whisper_factory(calls),
        summary_factory=_make_fake_summary_factory(calls),
        duration_fn=lambda _files: 3600.0,
    )

    assert result["status"] == "prepared"
    assert result["skipped"] is False
    assert result["artifactId"].startswith("prep-")
    assert result["campaign"] == "Crônicas de Eldoria"
    assert result["season"] == 2
    assert result["episode"] == 7
    assert result["initialTitle"] == "Nome Inicial da Mesa"
    assert result["suggestions"] == [
        "A Chama da Torre",
        "Ecos da Ponte",
        "O Juramento Quebrado",
    ]
    assert result["checkpoints"] == [
        "extracted",
        "audio_built",
        "transcribed",
        "summarized",
        "prepared",
    ]

    # Retencao absoluta (CA-05 / RN-06): prepare NUNCA envia nada para o Object Storage.
    assert storage.uploads == []
    assert storage.puts == []

    # Seguranca: state.json jamais persiste credenciais da conta.
    state_raw = Path(result["statePath"]).read_text(encoding="utf-8")
    assert "AKIAFAKEKEY1234567890" not in state_raw
    assert "super-secret-value-never-persist" not in state_raw

    # Idempotencia: segunda execucao retorna estado preparado sem reprocessar.
    calls_before = list(calls)
    again = server_worker.prepare_session(
        payload,
        storage_adapter=storage,
        audio_factory=_make_fake_audio_factory(calls),
        whisper_factory=_make_fake_whisper_factory(calls),
        summary_factory=_make_fake_summary_factory(calls),
        duration_fn=lambda _files: 3600.0,
    )
    assert again["artifactId"] == result["artifactId"]
    assert calls == calls_before


def test_publish_applies_winner_title_rebuilds_feed_matches_notification_text_and_is_idempotent(tmp_path):
    archive = _create_recording_zip(tmp_path)
    work_dir = tmp_path / "work" / "acc-42" / "rec-002"
    storage = FakeStorage()
    calls: list[str] = []

    prep = server_worker.prepare_session(
        {
            "action": "prepare",
            "recordingId": "rec-002",
            "archive": str(archive),
            "workDir": str(work_dir),
            "account": _sample_account(),
        },
        storage_adapter=storage,
        audio_factory=_make_fake_audio_factory(calls),
        whisper_factory=_make_fake_whisper_factory(calls),
        summary_factory=_make_fake_summary_factory(calls),
        duration_fn=lambda _files: 3600.0,
    )

    tagged: list[tuple[str, str]] = []
    updated_folders: list[str] = []

    class FakeRssUpdater:
        def __init__(self, _storage):
            pass

        def updateRssTranscriptionFiles(self, folder=None):
            updated_folders.append(folder)
            return {
                "success": True,
                "folders": [{"folder": folder, "rss_updated": True, "transcripts_updated": True}],
                "errors": [],
            }

    winner = "Vitória na Ponte de Ferro"
    pub = server_worker.publish_session(
        {
            "action": "publish",
            "recordingId": "rec-002",
            "statePath": prep["statePath"],
            "artifactId": prep["artifactId"],
            "winnerTitle": winner,
            "account": _sample_account(),
            "publishDirect": True,
        },
        storage_adapter=storage,
        rss_updater_factory=FakeRssUpdater,
        update_audio_tag=lambda path, title: tagged.append((path.name, title)),
    )

    assert pub["published"] is True
    assert pub["alreadyPublished"] is False
    assert pub["winnerTitle"] == winner
    assert updated_folders == ["eldoria"]
    assert tagged == [(f"Crônicas de Eldoria - S02E07 - {winner}.mp3", winner)]

    uploaded_keys = [key for _, key, _ in storage.uploads]
    assert f"eldoria/Crônicas de Eldoria - S02E07 - {winner}.mp3" in uploaded_keys
    assert f"eldoria/Crônicas de Eldoria - S02E07 - {winner}.txt" in uploaded_keys
    assert f"eldoria/Crônicas de Eldoria - S02E07 - {winner}.resumo.json" in uploaded_keys

    # Verifica que resumo.json e roteiro.txt receberam o titulo vencedor.
    state = json.loads(Path(prep["statePath"]).read_text(encoding="utf-8"))
    resumo_data = json.loads(Path(state["artifacts"]["resumo_json_path"]).read_text(encoding="utf-8"))
    assert resumo_data["nome_sessao"] == winner
    roteiro_text = Path(state["artifacts"]["roteiro_path"]).read_text(encoding="utf-8")
    assert f"Nome da Sessão: {winner}" in roteiro_text

    # Anuncio reproduz fielmente notification.publication_text + mencoes validas.
    expected_base = notification.publication_text(
        winner,
        "Crônicas de Eldoria",
        pub["links"],
        2,
        7,
    )
    assert pub["announcement"]["text"] == expected_base + "\n<@111111111111111111> <@222222222222222222>"
    assert pub["announcement"]["mentions"] == ["111111111111111111", "222222222222222222"]
    assert pub["announcement"]["parts"] == [pub["announcement"]["text"]]

    # Idempotencia: segunda chamada nao reenvia nem reexecuta updater.
    uploads_before = len(storage.uploads)
    pub_again = server_worker.publish_session(
        {
            "action": "publish",
            "recordingId": "rec-002",
            "statePath": prep["statePath"],
            "artifactId": prep["artifactId"],
            "winnerTitle": winner,
            "account": _sample_account(),
        },
        storage_adapter=storage,
        rss_updater_factory=FakeRssUpdater,
    )
    assert pub_again["alreadyPublished"] is True
    assert len(storage.uploads) == uploads_before
    assert len(updated_folders) == 1


def test_publish_preserves_winner_on_rss_failure_and_allows_retry(tmp_path):
    archive = _create_recording_zip(tmp_path)
    work_dir = tmp_path / "work" / "acc-42" / "rec-003"
    storage = FakeStorage()
    calls: list[str] = []

    prep = server_worker.prepare_session(
        {
            "action": "prepare",
            "recordingId": "rec-003",
            "archive": str(archive),
            "workDir": str(work_dir),
            "account": _sample_account(),
        },
        storage_adapter=storage,
        audio_factory=_make_fake_audio_factory(calls),
        whisper_factory=_make_fake_whisper_factory(calls),
        summary_factory=_make_fake_summary_factory(calls),
        duration_fn=lambda _files: 3600.0,
    )

    class FailingUpdater:
        def __init__(self, _storage):
            pass

        def updateRssTranscriptionFiles(self, folder=None):
            return {"success": False, "folders": [], "errors": [{"erro": "timeout storage"}]}

    with pytest.raises(server_worker.WorkerError, match="título vencedor foi mantido"):
        server_worker.publish_session(
            {
                "action": "publish",
                "recordingId": "rec-003",
                "statePath": prep["statePath"],
                "artifactId": prep["artifactId"],
                "winnerTitle": "Título Preservado",
                "account": _sample_account(),
            },
            storage_adapter=storage,
            rss_updater_factory=FailingUpdater,
            update_audio_tag=lambda _p, _t: None,
        )

    state = json.loads(Path(prep["statePath"]).read_text(encoding="utf-8"))
    assert state["published"] is False
    assert state["winnerTitle"] == "Título Preservado"


def test_validation_missing_config_short_session_and_zip_slip(tmp_path):
    archive = _create_recording_zip(tmp_path)

    # Falta bucket e campanha
    with pytest.raises(server_worker.WorkerError) as exc_info:
        server_worker.prepare_session(
            {
                "action": "prepare",
                "recordingId": "rec-missing",
                "archive": str(archive),
                "workDir": str(tmp_path / "w1"),
                "account": _sample_account(bucket="", with_campaign=False),
            }
        )
    assert exc_info.value.code == "missing_config"
    assert exc_info.value.missing_config == ["bucket", "campanha"]

    # Sessao curta -> skipped
    calls: list[str] = []
    skipped = server_worker.prepare_session(
        {
            "action": "prepare",
            "recordingId": "rec-short",
            "archive": str(archive),
            "workDir": str(tmp_path / "w2"),
            "account": _sample_account(),
        },
        storage_adapter=FakeStorage(),
        audio_factory=_make_fake_audio_factory(calls),
        duration_fn=lambda _files: 12.0,
    )
    assert skipped["skipped"] is True
    assert skipped["status"] == "skipped"

    # Zip Slip bloqueado
    bad_zip = _create_recording_zip(tmp_path, name="evil.zip", members={"../escape.txt": "boom"})
    with pytest.raises(server_worker.WorkerError, match="fora da pasta"):
        server_worker.prepare_session(
            {
                "action": "prepare",
                "recordingId": "rec-evil",
                "archive": str(bad_zip),
                "workDir": str(tmp_path / "w3"),
                "account": _sample_account(),
            },
            storage_adapter=FakeStorage(),
        )


def test_cli_subprocess_ndjson_protocol_and_secret_redaction(tmp_path):
    repo_root = Path(__file__).resolve().parents[4]
    src_root = Path(__file__).resolve().parents[1] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(src_root), str(repo_root)]),
    }
    payload = {
        "action": "prepare",
        "recordingId": "rec-cli",
        "archive": str(tmp_path / "missing.zip"),
        "workDir": str(tmp_path / "work"),
        "account": _sample_account(bucket="", with_campaign=False),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "podcast_automation.server_worker"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 1
    lines = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["event"] == "error"
    assert lines[0]["ok"] is False
    assert lines[0]["code"] == "missing_config"
    assert lines[0]["missingConfig"] == ["bucket", "campanha"]
    assert "super-secret-value-never-persist" not in proc.stdout
    assert "AKIAFAKEKEY1234567890" not in proc.stdout
