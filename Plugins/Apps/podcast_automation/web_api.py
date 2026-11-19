"""Podcast's web API. The PIA host only discovers and dispatches app actions."""

import copy
import json
import math
from pathlib import Path
import re
import secrets
import threading
from src.pia.service import Job
from src.resource_plugins import save_json
from src.settings_store import document, get_store, save_document, values
from src.user_paths import user_path
from .pipeline import initial, apply
from . import power
from .recording_queue import pending_files

ROOT = Path(__file__).resolve().parent
SUPPORTED_LLM_PROVIDERS = {
    "codex",
    "agy",
    "openrouter",
    "gemini",
    "groq",
    "cloudflare",
    "local",
    "free",
    "paid",
}
_latest = None
_tasks = {}
_lock = threading.Lock()

_APP_SETTINGS_DEFAULTS = {
    "POLL_INTERVAL_SECONDS": 600,
    "DRIVE_PROCESS": True,
    "LOCAL_DRIVE_FOLDER": "data/local-drive",
    "PUBLICAR_DIRETO": False,
    "OWNER_EMAIL": "",
    "TRANSCRIPTS_FILE": "transcripts.html",
    "SKIP_CLOSED": True,
    "FEED_CACHE_DIR": "data/cache/feeds",
    "FEED_FORCE_REBUILD": False,
}
_COMPUTED_CONFIG_KEYS = ("app_settings", "app_defaults", "timezone")
_MERGE_OBJECT_KEYS = ("publication", "processing", "audio", "integrations", "outputs")
_REPLACE_OBJECT_KEYS = ("nomes_reais", "discord_users", "campaign_details")
_PROCESSING_INT_KEYS = (
    "minimum_session_seconds",
    "duplicate_max_bytes",
    "duplicate_max_seconds",
)
_AUDIO_NUMERIC_KEYS = (
    "silence_threshold_db",
    "minimum_silence_seconds",
    "keep_silence_seconds",
    "fade_seconds",
    "compressor_threshold_db",
    "compressor_ratio",
    "compressor_attack_ms",
    "compressor_release_ms",
    "loudness_lufs",
    "loudness_range",
    "true_peak_db",
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LANG_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _settings_module():
    import sys

    if "podcast_automation.settings" in sys.modules:
        return sys.modules["podcast_automation.settings"]
    try:
        from podcast_automation import settings as mod

        return mod
    except ImportError:
        from .src.podcast_automation import settings as mod

        return mod


def _load_example_config() -> dict:
    candidate = ROOT / "docs/examples/config.example.json"
    if not candidate.is_file():
        candidate = Path(__file__).resolve().parent / "docs/examples/config.example.json"
    return json.loads(candidate.read_text(encoding="utf-8"))


def _load_campaign_document() -> dict:
    value = document("Apps/podcast_automation/campaigns")
    if value is not None:
        return copy.deepcopy(value)
    return _load_example_config()


def _typed_app_settings() -> dict:
    raw = values("Apps/podcast_automation")
    result = {}
    for key, default in _APP_SETTINGS_DEFAULTS.items():
        val = raw.get(key)
        if isinstance(default, bool):
            result[key] = (
                default
                if val is None or val == ""
                else str(val).strip().lower() in ("true", "1")
            )
        elif isinstance(default, int):
            try:
                result[key] = int(val) if val not in (None, "") else default
            except (TypeError, ValueError):
                result[key] = default
        else:
            result[key] = str(val) if val is not None else default
    return result


def _app_defaults() -> dict:
    example = _load_example_config()
    return {
        **_APP_SETTINGS_DEFAULTS,
        "audio": copy.deepcopy(example.get("audio", {})),
        "processing": copy.deepcopy(example.get("processing", {})),
        "publication": copy.deepcopy(example.get("publication", {})),
    }


def _ensure_json_safe(value, label: str = "Valor"):
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(f"{label} contém tipo não suportado.") from None


def _parse_bool(value, message: str = "Preferência inválida.") -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
    raise ValueError(message)


def _parse_int(value, message: str) -> int:
    if isinstance(value, bool):
        raise ValueError(message)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    raise ValueError(message)


def _parse_number(value, message: str) -> float | int:
    if isinstance(value, bool):
        raise ValueError(message)
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(message)
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            raise ValueError(message)
        try:
            parsed = float(text)
        except ValueError:
            raise ValueError(message) from None
        if not math.isfinite(parsed):
            raise ValueError(message)
        return parsed
    raise ValueError(message)


def _validate_integrations(integrations: dict) -> dict:
    if not isinstance(integrations, dict):
        raise ValueError("Integrações inválidas.")
    cleaned = {}
    for key, value in integrations.items():
        if key == "discord_channels":
            if not isinstance(value, list) or any(
                not isinstance(v, str) or not v.isdigit() for v in value
            ):
                raise ValueError("Canais Discord inválidos.")
            cleaned[key] = list(value)
        elif key == "taverns_channels":
            from Plugins.Connectors.taverns.service import destination_ids

            if not isinstance(value, list):
                raise ValueError("Canais Tav.gg inválidos.")
            for destination in value:
                destination_ids(destination)
            cleaned[key] = list(value)
        elif key in ("announce", "discord_notify", "taverns_notify"):
            if not isinstance(value, bool):
                raise ValueError("Preferência inválida.")
            cleaned[key] = value
        elif key in ("llm_provider", "llm_model"):
            label = "Provedor de modelo" if key == "llm_provider" else "Modelo"
            if not isinstance(value, str):
                raise ValueError(f"{label} inválido.")
            selection = value.strip()
            if key == "llm_provider" and selection and selection not in SUPPORTED_LLM_PROVIDERS:
                raise ValueError("Provedor de modelo inválido.")
            cleaned[key] = selection
        elif key in (
            "google_account",
            "google_folder",
            "google_folder_name",
            "google_folder_path",
            "storage_account",
            "storage_bucket",
            "discord_channel",
        ):
            if not isinstance(value, str):
                raise ValueError("Integração inválida.")
            cleaned[key] = value
        else:
            _ensure_json_safe(value, f"Integração {key}")
            cleaned[key] = copy.deepcopy(value)
    return cleaned


def _validate_outputs(outputs: dict) -> dict:
    if (
        not isinstance(outputs, dict)
        or set(outputs) - {"mp3", "resumo.json", "srt", "vtt", "txt"}
        or any(not isinstance(v, bool) for v in outputs.values())
    ):
        raise ValueError("Formatos de saída inválidos.")
    return dict(outputs)


def _validate_app_settings(app_settings: dict) -> dict:
    if not isinstance(app_settings, dict):
        raise ValueError("Configurações do aplicativo inválidas.")
    serialized = {}
    for key, value in app_settings.items():
        if key == "TZ":
            continue
        if key not in _APP_SETTINGS_DEFAULTS:
            raise ValueError(f"Configuração desconhecida: {key}.")
        default = _APP_SETTINGS_DEFAULTS[key]
        if key == "POLL_INTERVAL_SECONDS":
            num = _parse_int(
                value, "Informe um número inteiro de segundos, a partir de 1."
            )
            if num < 1:
                raise ValueError(
                    "Informe um número inteiro de segundos, a partir de 1."
                )
            serialized[key] = str(num)
        elif key in ("LOCAL_DRIVE_FOLDER", "FEED_CACHE_DIR"):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Informe uma pasta.")
            serialized[key] = value.strip()
        elif key == "OWNER_EMAIL":
            if not isinstance(value, str):
                raise ValueError(
                    "Informe um e-mail válido, como nome@dominio.com, ou deixe em branco."
                )
            text = value.strip()
            if text and not _EMAIL_RE.fullmatch(text):
                raise ValueError(
                    "Informe um e-mail válido, como nome@dominio.com, ou deixe em branco."
                )
            serialized[key] = text
        elif key == "TRANSCRIPTS_FILE":
            if not isinstance(value, str):
                raise ValueError(
                    "Informe o nome de um arquivo .html, como transcripts.html."
                )
            text = value.strip()
            if not text or not text.lower().endswith(".html") or len(text) <= 5:
                raise ValueError(
                    "Informe o nome de um arquivo .html, como transcripts.html."
                )
            serialized[key] = text
        elif isinstance(default, bool):
            flag = _parse_bool(value, f"{key} deve ser verdadeiro ou falso.")
            serialized[key] = "true" if flag else "false"
    return serialized


def _validate_publication(publication: dict) -> dict:
    if not isinstance(publication, dict):
        raise ValueError("Configuração de publicação inválida.")
    cleaned = {}
    for key, value in publication.items():
        if key == "website":
            if not isinstance(value, str):
                raise ValueError(
                    "Informe um endereço que comece com https:// ou http://."
                )
            text = value.strip()
            if text and not _URL_RE.match(text):
                raise ValueError(
                    "Informe um endereço que comece com https:// ou http://."
                )
            cleaned[key] = text
        elif key == "language":
            if not isinstance(value, str) or not _LANG_RE.fullmatch(value.strip()):
                raise ValueError("Use um código de idioma, como pt-BR.")
            cleaned[key] = value.strip()
        else:
            _ensure_json_safe(value, f"publication.{key}")
            cleaned[key] = copy.deepcopy(value)
    return cleaned


def _validate_processing(processing: dict) -> dict:
    if not isinstance(processing, dict):
        raise ValueError("Configuração de processamento inválida.")
    cleaned = {}
    for key, value in processing.items():
        if key in _PROCESSING_INT_KEYS:
            num = _parse_int(
                value, "Informe um número inteiro igual ou maior que zero."
            )
            if num < 0:
                raise ValueError(
                    "Informe um número inteiro igual ou maior que zero."
                )
            cleaned[key] = num
        else:
            _ensure_json_safe(value, f"processing.{key}")
            cleaned[key] = copy.deepcopy(value)
    return cleaned


def _validate_audio(audio: dict) -> dict:
    if not isinstance(audio, dict):
        raise ValueError("Configuração de áudio inválida.")
    cleaned = {}
    for key, value in audio.items():
        if key == "remove_silence":
            cleaned[key] = _parse_bool(
                value, "remove_silence deve ser verdadeiro ou falso."
            )
        elif key in _AUDIO_NUMERIC_KEYS:
            num = _parse_number(
                value, "Informe um número. Use vírgula ou ponto para decimais."
            )
            if key == "compressor_ratio" and num < 1:
                raise ValueError("A razão do compressor deve ser 1 ou maior.")
            if key in ("compressor_attack_ms", "compressor_release_ms") and num <= 0:
                raise ValueError("Informe um tempo maior que zero.")
            cleaned[key] = num
        else:
            _ensure_json_safe(value, f"audio.{key}")
            cleaned[key] = copy.deepcopy(value)
    return cleaned


def _validate_nomes_reais(nomes_reais: dict) -> dict:
    if not isinstance(nomes_reais, dict):
        raise ValueError("Configuração de participantes inválida.")
    cleaned = {}
    for discord_user, real_name in nomes_reais.items():
        if not isinstance(discord_user, str) or not discord_user.strip():
            raise ValueError("Informe o usuário do Discord.")
        if not isinstance(real_name, str) or not real_name.strip():
            raise ValueError("Informe o nome real.")
        cleaned[discord_user] = real_name
    return cleaned


def _validate_discord_users(discord_users: dict) -> dict:
    if not isinstance(discord_users, dict):
        raise ValueError("Configuração de IDs do Discord inválida.")
    cleaned = {}
    for real_name, discord_id in discord_users.items():
        if not isinstance(real_name, str) or not real_name.strip():
            raise ValueError("Informe o nome real.")
        if not isinstance(discord_id, str):
            raise ValueError(
                "O ID do Discord tem só números. Deixe em branco se não quiser menções."
            )
        text = discord_id.strip()
        if text and not text.isdigit():
            raise ValueError(
                "O ID do Discord tem só números. Deixe em branco se não quiser menções."
            )
        cleaned[real_name] = text
    return cleaned


def _validate_campaign_details(campaign_details: dict) -> dict:
    if not isinstance(campaign_details, dict) or not campaign_details:
        raise ValueError("Configure pelo menos uma mesa em campaign_details.")
    folders = set()
    cleaned = {}
    for narrator, table in campaign_details.items():
        if not isinstance(narrator, str) or not narrator.strip():
            raise ValueError("Escolha o narrador.")
        if not isinstance(table, dict):
            raise ValueError(f"Mesa de {narrator} inválida.")
        campanha = table.get("Campanha")
        if not isinstance(campanha, str) or not campanha.strip():
            raise ValueError("Informe o nome da campanha.")
        rss_key = table.get("rss_key")
        if not isinstance(rss_key, str) or not rss_key.endswith("/rss.xml"):
            raise ValueError("O caminho do feed precisa terminar em /rss.xml.")
        if any(part in ("", ".", "..") for part in rss_key.split("/")):
            raise ValueError(
                "O caminho do feed não pode conter barras extras ou caminhos relativos."
            )
        folder = rss_key.rsplit("/", 1)[0]
        if folder in folders:
            raise ValueError(f'Outra campanha já usa a pasta "{folder}".')
        folders.add(folder)
        players = table.get("players")
        if not isinstance(players, dict) or not players:
            raise ValueError("Adicione pelo menos um jogador e o personagem dele.")
        for player, character in players.items():
            if not isinstance(player, str) or not player.strip():
                raise ValueError("Adicione pelo menos um jogador e o personagem dele.")
            if not isinstance(character, str) or not character.strip():
                raise ValueError(f"Informe o personagem de {player}.")
        if "closed" in table and not isinstance(table["closed"], bool):
            raise ValueError(f"Mesa de {narrator}: closed deve ser true ou false.")
        if "explicit" in table and not isinstance(table["explicit"], bool):
            raise ValueError(f"Mesa de {narrator}: explicit deve ser true ou false.")
        if "link" in table and table["link"] not in (None, ""):
            if not isinstance(table["link"], str) or not _URL_RE.match(
                table["link"].strip()
            ):
                raise ValueError(
                    "Informe um endereço que comece com https:// ou http://."
                )
        _ensure_json_safe(table, f"Campanha {narrator}")
        cleaned[narrator] = copy.deepcopy(table)
    return cleaned


def _merge_campaign_document(existing: dict, patch: dict) -> dict:
    merged = copy.deepcopy(existing)
    for computed in _COMPUTED_CONFIG_KEYS:
        merged.pop(computed, None)

    for key, val in patch.items():
        if key in _COMPUTED_CONFIG_KEYS:
            continue
        if key in _MERGE_OBJECT_KEYS:
            base = merged.get(key)
            base_dict = dict(base) if isinstance(base, dict) else {}
            if key == "outputs":
                merged[key] = {
                    **{name: True for name in ("resumo.json", "srt", "txt", "vtt")},
                    **base_dict,
                    **val,
                    "mp3": True,
                }
            else:
                merged[key] = {**base_dict, **val}
        elif key in _REPLACE_OBJECT_KEYS:
            merged[key] = copy.deepcopy(val)
        else:
            _ensure_json_safe(val, key)
            merged[key] = copy.deepcopy(val)
    return merged


def _validate_campaign_patch(payload: dict) -> dict:
    validators = {
        "nomes_reais": _validate_nomes_reais,
        "discord_users": _validate_discord_users,
        "campaign_details": _validate_campaign_details,
        "publication": _validate_publication,
        "processing": _validate_processing,
        "audio": _validate_audio,
        "integrations": _validate_integrations,
        "outputs": _validate_outputs,
    }
    validated = {}
    for key, val in payload.items():
        if key in _COMPUTED_CONFIG_KEYS or key == "app_settings":
            continue
        if key in validators:
            validated[key] = validators[key](val)
        else:
            _ensure_json_safe(val, key)
            validated[key] = copy.deepcopy(val)
    return validated


def handle(action, data, context):
    global _latest
    if action == "pending-preview":
        config = handle("config", {}, context)
        options = {
            **config.get("integrations", {}),
            **{
                key: data[key]
                for key in ("google_account", "google_folder")
                if key in data
            },
        }
        env = values("Apps/podcast_automation")
        if str(env.get("DRIVE_PROCESS", "true")).lower() in ("false", "0"):
            folder = Path(env.get("LOCAL_DRIVE_FOLDER") or "data/local-drive")
            if not folder.is_absolute():
                folder = user_path("apps/podcast_automation") / folder
            files = [
                {"id": str(file), "name": file.name}
                for file in folder.glob("*")
                if file.is_file() and file.suffix.lower() == ".zip"
            ]
            path = str(folder)
        else:
            from Plugins.Connectors.google.drive import Drive

            drive = Drive(context.backend.resources)
            folder = options.get("google_folder") or drive.default_folder
            if not folder or not drive.accounts():
                return {
                    "configured": False,
                    "pending": [],
                    "message": "Selecione a conta e a pasta de gravações.",
                }
            account = drive.account(options.get("google_account"))
            files = []
            cursor = None
            seen = set()
            while True:
                page = drive.list(account, folder, cursor=cursor)
                files.extend(
                    file
                    for file in page.get("files", [])
                    if file["name"].lower().endswith(".zip")
                )
                cursor = page.get("nextPageToken")
                if not cursor:
                    break
                if cursor in seen:
                    raise ValueError(
                        "O Drive retornou uma página repetida ao consultar gravações."
                    )
                seen.add(cursor)
            path = drive.folder_path(folder, account)
        pending = pending_files(files)
        return {
            "configured": True,
            "pending": [{"id": f["id"], "name": f["name"]} for f in pending],
            "total": len(files),
            "processed": len(files) - len(pending),
            "folder_path": path,
            "folder": str(folder),
        }
    if action == "status":
        task = _tasks.get(_latest)
        return {
            "cursor": len(task["job"].events) if task else 0,
            "job": _latest,
            "running": bool(task and task["job"].status == "running"),
            "monitor": task.get("monitor", False) if task else False,
            "shutdown_after": task.get("shutdown_after", False) if task else False,
            "shutdown_pending": task.get("shutdown_pending", False) if task else False,
            "lines": task["lines"][-2500:] if task else [],
            "result": task.get("result") if task else None,
        }
    if action == "clear-log":
        record = _tasks.get(_latest)
        if record:
            record["lines"].clear()
            record["job"].emit("log-clear")
        return {"ok": True}
    if action == "pipeline":
        task = _tasks.get(_latest)
        return task["pipeline"] if task else initial()
    if action == "config":
        doc = _load_campaign_document()
        return {
            **doc,
            "discord_users": copy.deepcopy(doc.get("discord_users", {})),
            "app_settings": _typed_app_settings(),
            "app_defaults": _app_defaults(),
            "timezone": _settings_module().local_timezone_info(),
        }
    if action == "save-options":
        doc = _load_campaign_document()
        patch = {}
        if "outputs" in data:
            patch["outputs"] = _validate_outputs(data["outputs"])
        if "integrations" in data:
            integrations = _validate_integrations(data["integrations"])
            merged_integrations = {**doc.get("integrations", {}), **integrations}
            if "discord_channels" in integrations:
                merged_integrations.pop("discord_channel", None)
            if merged_integrations.get("taverns_notify") and not merged_integrations.get(
                "taverns_channels"
            ):
                raise ValueError(
                    "Selecione pelo menos um canal da Tav.gg para publicar."
                )
            doc["integrations"] = merged_integrations
        if "outputs" in patch:
            doc["outputs"] = {
                **{name: True for name in ("resumo.json", "srt", "txt", "vtt")},
                **doc.get("outputs", {}),
                **patch["outputs"],
                "mp3": True,
            }
        for computed in _COMPUTED_CONFIG_KEYS:
            doc.pop(computed, None)
        save_document("Apps/podcast_automation/campaigns", doc)
        _settings_module().get_config.cache_clear()
        return {"ok": True}
    if action == "save-config":
        value = data.get("value")
        if not isinstance(value, dict) or any(
            not isinstance(value.get(k), dict)
            for k in (
                "nomes_reais",
                "campaign_details",
                "publication",
                "audio",
                "processing",
            )
        ):
            raise ValueError("Configuração de campanhas inválida.")
        existing = _load_campaign_document()
        clean_input = {
            k: v for k, v in value.items() if k not in _COMPUTED_CONFIG_KEYS
        }
        validated = _validate_campaign_patch(clean_input)
        # Preserva seleções mais recentes de integrações/outputs quando save-config é chamado pelo editor legado.
        for preserved_key in ("integrations", "outputs"):
            if preserved_key in existing:
                validated[preserved_key] = {
                    **validated.get(preserved_key, {}),
                    **existing[preserved_key],
                }
        merged = _merge_campaign_document(existing, validated)
        save_document("Apps/podcast_automation/campaigns", merged)
        _settings_module().get_config.cache_clear()
        return {"ok": True}
    if action == "save-settings":
        if not isinstance(data, dict):
            raise ValueError("Payload de configurações inválido.")
        app_settings = data.get("app_settings")
        serialized_app_settings = (
            _validate_app_settings(app_settings) if app_settings is not None else None
        )
        campaign_patch = _validate_campaign_patch(data)
        if campaign_patch:
            existing = _load_campaign_document()
            merged = _merge_campaign_document(existing, campaign_patch)
            if merged.get("integrations", {}).get("taverns_notify") and not merged.get(
                "integrations", {}
            ).get("taverns_channels"):
                raise ValueError(
                    "Selecione pelo menos um canal da Tav.gg para publicar."
                )
            save_document("Apps/podcast_automation/campaigns", merged)
        if serialized_app_settings:
            get_store().save(
                "Apps/podcast_automation",
                serialized_app_settings,
                kinds={"LOCAL_DRIVE_FOLDER": "string", "FEED_CACHE_DIR": "string"},
            )
        _settings_module().get_config.cache_clear()
        return {"ok": True}
    if action == "stop":
        with _lock:
            record = _tasks.get(_latest)
            if record:
                record["job"].cancelled.set()
        context.backend.stop_podcast()
        return {"ok": True}
    if action == "cancel-shutdown":
        with _lock:
            record = _tasks.get(_latest)
            if not record or not record.get("shutdown_pending"):
                raise ValueError("Não há desligamento agendado.")
            power.cancel()
            record["shutdown_pending"] = False
        return {"ok": True}
    if action != "start":
        raise ValueError("Ação desconhecida do podcast.")
    with _lock:
        if _latest and _tasks[_latest]["job"].status == "running":
            raise ValueError("Já há uma tarefa em execução.")
        task = data.get("task")
        monitor = data.get("monitor", False)
        shutdown_after = data.get("shutdown_after", False)
        if not isinstance(monitor, bool) or not isinstance(shutdown_after, bool):
            raise ValueError("Opções de processamento inválidas.")
        if monitor and shutdown_after:
            raise ValueError(
                "Monitoramento automático e desligamento são opções mutuamente exclusivas."
            )
        if shutdown_after and task != "process":
            raise ValueError(
                "Desligamento só pode acompanhar o processamento de sessões."
            )
        if _latest and _tasks[_latest].get("shutdown_pending"):
            raise ValueError(
                "Cancele o desligamento agendado antes de iniciar outra tarefa."
            )
        args = []
        output = None
        if task == "process":
            module = "podcast_automation.main"
            args = [] if data.get("monitor") else ["--once"]
        elif task == "rebuild":
            module = "utilities.rebuild_feeds"
        elif task in ("merge_srt", "merge_vtt"):
            module = "utilities." + task
            kind = task.split("_")[1]
            directory = user_path(
                "apps/podcast_automation/web-tasks"
            ) / secrets.token_hex(8)
            directory.mkdir(parents=True)
            for key in ("first", "second"):
                value = data.get(key)
                if not isinstance(value, str) or len(value) > 5 * 1024 * 1024:
                    raise ValueError(
                        "Selecione duas legendas válidas (até 5 MiB cada)."
                    )
                (directory / (key + "." + kind)).write_text(
                    value, encoding="utf-8-sig" if kind == "srt" else "utf-8"
                )
            output = directory / ("merged." + kind)
            args = [
                directory / ("first." + kind),
                directory / ("second." + kind),
                "-o",
                output,
            ]
        else:
            raise ValueError("Tarefa desconhecida.")
        process = context.backend.start_podcast_task(module, *args)
        job = Job()
        context.jobs[job.id] = job
        _latest = job.id
        record = {
            "job": job,
            "lines": [],
            "result": None,
            "pipeline": initial(),
            "monitor": monitor,
            "shutdown_after": shutdown_after,
            "shutdown_pending": False,
        }
        _tasks[job.id] = record

        def read():
            try:
                with process.stdout:
                    for line in process.stdout:
                        if line.startswith("@@CRAIG "):
                            try:
                                event = json.loads(line[len("@@CRAIG ") :])
                                apply(record["pipeline"], event)
                                job.emit(
                                    "pipeline",
                                    value=json.loads(json.dumps(record["pipeline"])),
                                )
                                continue
                            except (ValueError, KeyError, TypeError):
                                pass
                        if "[STT_PROGRESS]" in line or (
                            "%|" in line and "it/s" in line
                        ):
                            continue
                        record["lines"].append(line.rstrip())
                        from src.plugin_logs import write

                        write("Apps/podcast_automation", line.rstrip())
                        if len(record["lines"]) > 2500:
                            del record["lines"][:500]
                        job.emit("log", text=line.rstrip())
                code = process.wait()
                if code:
                    if not record["pipeline"].get("error"):
                        apply(
                            record["pipeline"],
                            {
                                "kind": "failed",
                                "error": f"Processo encerrou com código {code}.",
                            },
                        )
                    job.emit("pipeline", value=record["pipeline"])
                    job.emit(
                        "error",
                        error=f"A tarefa terminou com código {code}. Consulte a saída.",
                    )
                else:
                    if output:
                        record["result"] = {
                            "name": output.name,
                            "text": output.read_text(encoding="utf-8-sig"),
                        }
                    with _lock:
                        if (
                            shutdown_after
                            and not monitor
                            and not job.cancelled.is_set()
                            and not record["pipeline"].get("error")
                        ):
                            try:
                                power.shutdown()
                            except Exception:
                                raise RuntimeError(
                                    "Os arquivos foram processados, mas o sistema não permitiu agendar o desligamento. Verifique as permissões de energia do usuário."
                                ) from None
                            record["shutdown_pending"] = True
                            message = "Todos os arquivos foram processados. Computador será desligado em 60 segundos."
                            record["lines"].append(message)
                            job.emit("log", text=message)
                        job.emit(
                            "done",
                            result=record["result"],
                            shutdown_pending=record["shutdown_pending"],
                        )
            except Exception as exc:
                apply(record["pipeline"], {"kind": "failed", "error": str(exc)})
                job.emit("pipeline", value=record["pipeline"])
                job.emit("error", error=str(exc))

        threading.Thread(target=read, daemon=True, name="pia-podcast-web").start()
        return {"job": job.id}
