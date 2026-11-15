"""Catalog, CRUD, and execution for built-in and custom PIA skills."""

from __future__ import annotations

import re
import shlex
import subprocess
import tomllib
import uuid
from pathlib import Path
from typing import Any

from .config_paths import BASE_DIR
from .skills_runtime import normalize
from .user_paths import user_path
from .workspace_store import WorkspaceStore

CUSTOM_KEY = "skills:custom"
OVERRIDES_KEY = "skills:overrides"

_BUILTIN_FRIENDLY: dict[str, dict[str, Any]] = {
    "abrir_bloco_de_notas": {
        "name": "Iniciar Bloco de Notas",
        "description": "Abre o Bloco de Notas do Windows (notepad.exe)",
        "category": "sistema",
        "triggers": ["iniciar bloco de notas", "abrir bloco de notas", "notepad"],
        "action_type": "command",
        "command": "notepad.exe",
    },
    "abrir_navegador": {
        "name": "Abrir Navegador",
        "description": "Abre o navegador padrão do sistema.",
        "category": "sistema",
        "triggers": ["abrir navegador", "abrir browser"],
        "action_type": "command",
        "command": "",
    },
    "modo_ditado": {
        "name": "Modo Ditado",
        "description": "Ativa o ditado contínuo de voz para inserir texto.",
        "category": "voz",
        "triggers": ["modo ditado", "ativar modo ditado"],
        "action_type": "tool",
    },
    "previsao_do_tempo": {
        "name": "Previsão do Tempo",
        "description": "Consulta a previsão do tempo atual.",
        "category": "utilidades",
        "triggers": ["previsão do tempo", "clima"],
        "action_type": "tool",
    },
    "aprender_novo_comando": {
        "name": "Aprender Novo Comando",
        "description": "Ensina um novo comando de voz para a PIA.",
        "category": "voz",
        "triggers": ["aprender comando", "novo comando"],
        "action_type": "tool",
    },
}

_NATIVE_SYSTEM_SKILLS: list[dict[str, Any]] = [
    {
        "id": "tirar_screenshot",
        "name": "Tirar Screenshot",
        "description": "Captura um print da tela atual do computador.",
        "category": "sistema",
        "triggers": ["tirar screenshot", "tirar print", "capturar tela"],
        "action_type": "tool",
        "tool_name": "pia_screenshot",
        "tool_args": {},
        "command": "",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "abrir_calculadora",
        "name": "Abrir Calculadora",
        "description": "Abre a Calculadora do Windows (calc.exe).",
        "category": "sistema",
        "triggers": ["abrir calculadora", "iniciar calculadora", "calculadora"],
        "action_type": "command",
        "command": "calc.exe",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "abrir_explorador",
        "name": "Abrir Explorador de Arquivos",
        "description": "Abre o Explorador de Arquivos do Windows (explorer.exe).",
        "category": "sistema",
        "triggers": [
            "abrir explorador",
            "abrir explorador de arquivos",
            "windows explorer",
        ],
        "action_type": "command",
        "command": "explorer.exe",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "consultar_sessoes_rpg",
        "name": "Consultar Sessões de RPG",
        "description": "Lista ou consulta a última sessão e transcrições de RPG nos buckets.",
        "category": "rpg",
        "triggers": [
            "consultar sessoes de rpg",
            "ultima sessao de rpg",
            "sessoes de rpg",
        ],
        "action_type": "tool",
        "tool_name": "pia_rpg_sessions",
        "tool_args": {"action": "list"},
        "command": "",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "gerar_musica_suno",
        "name": "Gerar Música (Suno)",
        "description": "Cria uma música usando o provedor Suno (MCP) ou configurado.",
        "category": "midia",
        "triggers": ["gerar musica", "criar musica", "suno"],
        "action_type": "tool",
        "tool_name": "pia_music",
        "tool_args": {"provider": "suno_mcp", "prompt": "Música instrumental épica"},
        "command": "",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "listar_arquivos_bucket",
        "name": "Listar Arquivos no Bucket",
        "description": "Lista buckets e objetos no conector Object Storage.",
        "category": "armazenamento",
        "triggers": [
            "listar arquivos no bucket",
            "listar buckets",
            "arquivos do bucket",
        ],
        "action_type": "tool",
        "tool_name": "pia_storage_list",
        "tool_args": {},
        "command": "",
        "enabled": True,
        "builtin": True,
    },
]


def _normalize_triggers(triggers: Any) -> list[str]:
    if isinstance(triggers, str):
        return [t.strip() for t in triggers.split(",") if t.strip()]
    if isinstance(triggers, list):
        return [str(t).strip() for t in triggers if str(t).strip()]
    return []


class SkillsCatalog:
    def __init__(self, root: Path | None = None, store: WorkspaceStore | None = None):
        self.root = Path(root or BASE_DIR / "Plugins" / "Skills")
        self.store = store or WorkspaceStore(user_path("workspace.sqlite3"))

    def _overrides(self) -> dict[str, dict[str, Any]]:
        raw = self.store.get(OVERRIDES_KEY, {})
        return raw if isinstance(raw, dict) else {}

    def _custom(self) -> list[dict[str, Any]]:
        raw = self.store.get(CUSTOM_KEY, [])
        return raw if isinstance(raw, list) else []

    def _builtin_skills(self) -> list[dict[str, Any]]:
        overrides = self._overrides()
        skills: list[dict[str, Any]] = []
        seen: set[str] = set()

        if self.root.is_dir():
            for manifest in sorted(self.root.glob("*/plugin.toml")):
                try:
                    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                skill_id = str(data.get("id") or manifest.parent.name).strip()
                if not skill_id or skill_id == "exemplo" or skill_id in seen:
                    continue
                seen.add(skill_id)
                friendly = _BUILTIN_FRIENDLY.get(skill_id, {})
                triggers = friendly.get("triggers") or list(data.get("commands") or [])
                ov = overrides.get(skill_id, {})
                skills.append(
                    {
                        "id": skill_id,
                        "name": str(
                            ov.get("name")
                            or friendly.get("name")
                            or skill_id.replace("_", " ").title()
                        ),
                        "description": str(
                            ov.get("description")
                            or friendly.get("description")
                            or data.get("description")
                            or f"Skill nativa {skill_id}"
                        ),
                        "category": str(
                            ov.get("category") or friendly.get("category") or "geral"
                        ),
                        "triggers": _normalize_triggers(ov.get("triggers") or triggers),
                        "action_type": str(friendly.get("action_type") or "command"),
                        "command": str(friendly.get("command") or ""),
                        "enabled": bool(ov.get("enabled", data.get("enabled", True))),
                        "builtin": True,
                    }
                )

        for native in _NATIVE_SYSTEM_SKILLS:
            sid = native["id"]
            if sid in seen:
                continue
            seen.add(sid)
            ov = overrides.get(sid, {})
            item = dict(native)
            if "enabled" in ov:
                item["enabled"] = bool(ov["enabled"])
            if "triggers" in ov:
                item["triggers"] = _normalize_triggers(ov["triggers"])
            skills.append(item)

        return skills

    def list_skills(self) -> list[dict[str, Any]]:
        return [*self._builtin_skills(), *self._custom()]

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        for s in self.list_skills():
            if s["id"] == skill_id:
                return s
        raise KeyError(f"Skill '{skill_id}' não encontrada.")

    def create_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload inválido.")
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("Nome da skill é obrigatório.")
        skill_id = str(payload.get("id") or "").strip()
        if not skill_id:
            base = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.lower()).strip("_") or "skill"
            skill_id = f"{base[:32]}_{uuid.uuid4().hex[:6]}"
        elif not re.fullmatch(r"[a-zA-Z0-9_-]+", skill_id):
            raise ValueError("ID da skill inválido.")

        existing_ids = {s["id"] for s in self.list_skills()}
        if skill_id in existing_ids:
            raise ValueError(f"Skill '{skill_id}' já existe.")

        action_type = str(payload.get("action_type") or "command").strip()
        if action_type not in ("command", "tool", "prompt"):
            raise ValueError("action_type deve ser 'command', 'tool' ou 'prompt'.")

        skill = {
            "id": skill_id,
            "name": name,
            "description": str(payload.get("description") or "").strip(),
            "category": str(payload.get("category") or "personalizada").strip(),
            "triggers": _normalize_triggers(payload.get("triggers") or [name.lower()]),
            "action_type": action_type,
            "command": str(payload.get("command") or "").strip(),
            "tool_name": str(payload.get("tool_name") or "").strip(),
            "tool_args": payload.get("tool_args")
            if isinstance(payload.get("tool_args"), dict)
            else {},
            "prompt": str(payload.get("prompt") or "").strip(),
            "enabled": bool(payload.get("enabled", True)),
            "builtin": False,
        }
        custom = self._custom()
        custom.append(skill)
        self.store.set(CUSTOM_KEY, custom)
        return skill

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload inválido.")
        custom = self._custom()
        for idx, item in enumerate(custom):
            if item["id"] == skill_id:
                updated = {**item}
                for key in (
                    "name",
                    "description",
                    "category",
                    "command",
                    "tool_name",
                    "prompt",
                ):
                    if key in payload:
                        updated[key] = str(payload[key] or "").strip()
                if "triggers" in payload:
                    updated["triggers"] = _normalize_triggers(payload["triggers"])
                if "action_type" in payload and payload["action_type"] in (
                    "command",
                    "tool",
                    "prompt",
                ):
                    updated["action_type"] = payload["action_type"]
                if "tool_args" in payload and isinstance(payload["tool_args"], dict):
                    updated["tool_args"] = payload["tool_args"]
                if "enabled" in payload:
                    updated["enabled"] = bool(payload["enabled"])
                custom[idx] = updated
                self.store.set(CUSTOM_KEY, custom)
                return updated

        builtin = next((s for s in self._builtin_skills() if s["id"] == skill_id), None)
        if builtin is None:
            raise KeyError(f"Skill '{skill_id}' não encontrada.")
        overrides = self._overrides()
        ov = dict(overrides.get(skill_id, {}))
        if "enabled" in payload:
            ov["enabled"] = bool(payload["enabled"])
        if "triggers" in payload:
            ov["triggers"] = _normalize_triggers(payload["triggers"])
        overrides[skill_id] = ov
        self.store.set(OVERRIDES_KEY, overrides)
        return self.get_skill(skill_id)

    def toggle_skill(
        self, skill_id: str, enabled: bool | None = None
    ) -> dict[str, Any]:
        current = self.get_skill(skill_id)
        new_enabled = (not current["enabled"]) if enabled is None else bool(enabled)
        return self.update_skill(skill_id, {"enabled": new_enabled})

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        custom = self._custom()
        filtered = [s for s in custom if s["id"] != skill_id]
        if len(filtered) == len(custom):
            if any(s["id"] == skill_id for s in self._builtin_skills()):
                raise ValueError(
                    "Skills nativas não podem ser excluídas; desative-a se desejar."
                )
            raise KeyError(f"Skill '{skill_id}' não encontrada.")
        self.store.set(CUSTOM_KEY, filtered)
        return {"ok": True, "deleted": skill_id}

    def execute_skill(
        self, skill_id: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        skill = self.get_skill(skill_id)
        if not skill.get("enabled", True):
            raise RuntimeError(f"Skill '{skill['name']}' está desabilitada.")

        action_type = skill.get("action_type", "command")
        if action_type == "command":
            cmd = str(skill.get("command") or "").strip()
            if not cmd:
                # Fallback to voice skill plugin if available
                manifest = self.root / skill_id / "plugin.py"
                if manifest.is_file():
                    from .commands_loader import COMMAND_ACTIONS, load_commands
                    from .skills_runtime import get_runtime

                    if not COMMAND_ACTIONS:
                        load_commands()
                    for trig in skill.get("triggers") or []:
                        fn = COMMAND_ACTIONS.get(normalize(trig))
                        if fn:
                            get_runtime().activate(trig, fn)
                            return {
                                "ok": True,
                                "skill": skill,
                                "message": f"Skill '{skill['name']}' iniciada.",
                            }
                raise RuntimeError(
                    f"Skill '{skill['name']}' não possui comando configurado."
                )
            args = shlex.split(cmd, posix=False)
            subprocess.Popen(args)
            return {"ok": True, "skill": skill, "message": f"Comando '{cmd}' iniciado."}

        if action_type == "tool":
            tool_name = str(skill.get("tool_name") or "").strip()
            if not tool_name:
                raise RuntimeError(
                    f"Skill '{skill['name']}' não possui tool associada."
                )
            from .tool_registry import call

            tool_args = dict(skill.get("tool_args") or {})
            if isinstance(params, dict):
                tool_args.update(params)
            result = call(tool_name, tool_args)
            return {"ok": True, "skill": skill, "result": result}

        return {
            "ok": True,
            "skill": skill,
            "prompt": skill.get("prompt", ""),
        }

    def match_by_text(self, text: str) -> dict[str, Any] | None:
        norm = normalize(text).strip()
        if not norm:
            return None
        for skill in self.list_skills():
            if not skill.get("enabled", True):
                continue
            for trig in skill.get("triggers") or []:
                nt = normalize(trig).strip()
                if nt and (nt == norm or nt in norm):
                    return skill
        return None


_skills_catalog: SkillsCatalog | None = None


def get_skills_catalog() -> SkillsCatalog:
    global _skills_catalog
    if _skills_catalog is None:
        _skills_catalog = SkillsCatalog()
    return _skills_catalog
