from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pyperclip

from .actions import ActionExecutor
from .config import Settings
from .gemini_client import GeminiService
from .memory import MemoryStore, normalize_text
from .models import AgentResult
from .tts import Speaker


READY_WORDS = {
    "pronto",
    "feito",
    "copiei",
    "ja copiei",
    "já copiei",
    "esta pronto",
    "está pronto",
}

CANCEL_WORDS = {
    "cancelar",
    "cancela",
    "esquece",
    "deixa pra la",
    "deixa para la",
}


class VoiceAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryStore(settings.memory_file)
        self.gemini = GeminiService(settings)
        self.executor = ActionExecutor(settings, self.memory)
        self.speaker = Speaker(settings)
        self.settings.learning_dir.mkdir(parents=True, exist_ok=True)

    def handle_audio(self, wav_bytes: bytes) -> AgentResult:
        transcription = self.gemini.transcribe(wav_bytes)
        logging.info("Transcrição: %s", transcription)

        if not transcription:
            return AgentResult(
                ok=False,
                transcription="",
                mode="empty",
                error="Nenhuma fala foi reconhecida.",
            )

        result = self.handle_text(transcription)
        result.transcription = transcription
        return result

    def handle_text(self, utterance: str) -> AgentResult:
        pending = self.memory.get_pending_learning()
        if pending:
            return self._handle_pending_learning(utterance, pending)

        learned = self.memory.match_learned_action(utterance)
        if learned is not None:
            detail = self.executor.execute_learned(learned)
            spoken = f"Abrindo, {self.settings.user_name}."
            self.speaker.speak(spoken)
            return AgentResult(
                mode="learned_action",
                spoken_response=spoken,
                details=[detail],
            )

        context = self.memory.context_for_model()
        decision = self.gemini.decide(utterance, context)
        logging.info("Decisão: %s", decision.model_dump_json())

        if decision.mode == "answer":
            spoken = decision.spoken_response.strip()
            self.speaker.speak(spoken)
            return AgentResult(
                mode="answer",
                spoken_response=spoken,
            )

        if decision.mode == "learn_memory":
            return self._start_memory_learning(utterance, decision)

        if decision.mode == "learn_capability":
            return self._start_capability_learning(utterance, decision)

        details: list[dict] = []
        for step in decision.actions:
            details.append(self.executor.execute(step))

        tool_requires_summary = any(
            item.get("action") == "weather"
            for item in details
        )

        if tool_requires_summary:
            spoken = self.gemini.compose_tool_response(
                utterance,
                details,
                self.memory.context_for_model(),
            )
        else:
            spoken = decision.spoken_response.strip()

        if spoken:
            self.speaker.speak(spoken)

        return AgentResult(
            mode="execute",
            spoken_response=spoken,
            details=details,
        )

    def _start_memory_learning(self, utterance, decision) -> AgentResult:
        learning = decision.learning
        if learning is None:
            raise RuntimeError("learn_memory sem bloco learning.")

        if learning.kind not in {"url", "path"}:
            raise RuntimeError(
                f"Tipo de aprendizado de memória inválido: {learning.kind}"
            )

        pending = {
            "mode": "memory",
            "kind": learning.kind,
            "original_utterance": utterance,
            "canonical_trigger": learning.canonical_trigger or utterance,
            "description": learning.description,
            "prompt": learning.prompt,
            "success_message": learning.success_message,
        }
        self.memory.set_pending_learning(pending)

        spoken = learning.prompt.strip() or decision.spoken_response.strip()
        if not spoken:
            spoken = (
                "Eu ainda não conheço esse alvo. Copie a informação correta "
                "para a área de transferência e depois diga pronto."
            )
        self.speaker.speak(spoken)

        return AgentResult(
            mode="learn_memory",
            spoken_response=spoken,
            details=[{"pending_learning": pending}],
        )

    def _handle_pending_learning(self, utterance: str, pending: dict) -> AgentResult:
        normalized = normalize_text(utterance)

        if normalized in {normalize_text(value) for value in CANCEL_WORDS}:
            self.memory.clear_pending_learning()
            spoken = "Aprendizado cancelado."
            self.speaker.speak(spoken)
            return AgentResult(
                mode="learning_cancelled",
                spoken_response=spoken,
            )

        ready = normalized in {normalize_text(value) for value in READY_WORDS}
        if not ready:
            spoken = (
                "Ainda estou aguardando a informação na área de transferência. "
                "Depois de copiar, diga pronto; ou diga cancelar."
            )
            self.speaker.speak(spoken)
            return AgentResult(
                mode="learning_waiting",
                spoken_response=spoken,
            )

        value = (pyperclip.paste() or "").strip()
        kind = pending.get("kind")

        if kind == "url":
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                spoken = (
                    "O conteúdo da área de transferência não parece ser um link HTTP ou HTTPS. "
                    "Copie o link correto e diga pronto novamente."
                )
                self.speaker.speak(spoken)
                return AgentResult(
                    ok=False,
                    mode="learning_invalid_clipboard",
                    spoken_response=spoken,
                    error="Clipboard não contém URL válida.",
                )
            action_type = "open_url"

        elif kind == "path":
            expanded = Path(os.path.expandvars(os.path.expanduser(value)))
            if not expanded.exists():
                spoken = (
                    "O caminho copiado não existe neste computador. "
                    "Copie o caminho correto e diga pronto novamente."
                )
                self.speaker.speak(spoken)
                return AgentResult(
                    ok=False,
                    mode="learning_invalid_clipboard",
                    spoken_response=spoken,
                    error="Clipboard não contém caminho existente.",
                )
            value = str(expanded)
            action_type = "open_path"

        else:
            raise RuntimeError(f"Tipo de aprendizado não suportado: {kind}")

        item = self.memory.add_learned_action(
            trigger=pending.get("canonical_trigger") or pending.get("original_utterance"),
            aliases=[pending.get("original_utterance", "")],
            description=pending.get("description", "Ação ensinada pelo usuário"),
            action_type=action_type,
            value=value,
        )

        spoken = pending.get("success_message") or (
            f"Muito obrigado, {self.settings.user_name}. Agora eu aprendi essa ação."
        )

        details = [{"learned": item}]

        if action_type in {"open_url", "open_path"}:
            details.append(self.executor.execute_learned(item))

        self.speaker.speak(spoken)
        return AgentResult(
            mode="learning_completed",
            spoken_response=spoken,
            details=details,
        )

    def _start_capability_learning(self, utterance, decision) -> AgentResult:
        learning = decision.learning
        if learning is None:
            raise RuntimeError("learn_capability sem bloco learning.")

        prompt_text = self.gemini.build_capability_prompt(
            utterance=utterance,
            description=learning.description,
            proposed_tool_name=learning.proposed_tool_name,
        )

        safe_slug = re.sub(
            r"[^a-z0-9_-]+",
            "_",
            (learning.proposed_tool_name or "nova_capacidade").lower(),
        ).strip("_") or "nova_capacidade"

        filename = (
            datetime.now().strftime("%Y%m%d_%H%M%S")
            + "_"
            + safe_slug
            + ".md"
        )
        proposal_path = self.settings.learning_dir / filename
        proposal_path.write_text(prompt_text, encoding="utf-8")

        spoken = decision.spoken_response.strip() or (
            "Eu não sei executar essa ação, mas preparei o que é necessário "
            "para me ensinar no VS Code."
        )
        self.speaker.speak(spoken)

        # O clipboard só é alterado neste fluxo, propositalmente: fica pronto
        # para Ctrl+V no agente de código dentro do VS Code.
        pyperclip.copy(prompt_text)
        self._open_vscode(proposal_path)

        return AgentResult(
            mode="learn_capability",
            spoken_response=spoken,
            details=[
                {
                    "proposal_file": str(proposal_path),
                    "clipboard_prepared": True,
                }
            ],
        )

    def _open_vscode(self, proposal_path: Path) -> None:
        try:
            subprocess.Popen(
                [
                    self.settings.vscode_command,
                    str(self.settings.root_dir),
                    str(proposal_path),
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            logging.exception("Não foi possível abrir o VS Code pelo CLI.")
            try:
                os.startfile(str(self.settings.root_dir))
            except Exception:
                logging.exception("Também não foi possível abrir a pasta do projeto.")
