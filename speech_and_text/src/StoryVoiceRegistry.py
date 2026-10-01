import json
import re
import threading
import urllib.request

from .config import (
    BASE_DIR,
    LLM_URL,
    LLM_MODEL,
    logging,
)


class StoryVoiceRegistry:
    """
    Gerencia a associação persistente entre personagens e vozes Qwen.

    Cache:
        logs/selectedVoices.json

    Estrutura:
        {
            "asta": {
                "name": "Asta",
                "voice": "ryan",
                "speech_count": 42
            },
            "raegis": {
                "name": "Raegis",
                "voice": "serena",
                "speech_count": 17
            }
        }
    """

    CACHE_FILE = BASE_DIR / "logs" / "selectedVoices.json"

    # Acima deste número, consideramos que a voz já está
    # razoavelmente consolidada naquele personagem.
    CONSOLIDATED_SPEECH_COUNT = 10

    def __init__(self, voices: dict[str, str]):
        self.voice_genders = {
            str(voice).strip().lower(): str(gender).strip().lower()
            for voice, gender in voices.items()
            if str(voice).strip()
        }

        # Lista das vozes que REALMENTE existem no Qwen.
        self.available_voices = [
            str(voice).strip().lower() for voice in voices if str(voice).strip()
        ]

        self.llm_url = LLM_URL.rstrip("/")
        self.llm_model = LLM_MODEL
        self.lock = threading.RLock()

        # personagem normalizado -> dados persistentes
        self.characters: dict[str, dict] = {}

        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    # ==============================================================
    # PARSER
    # ==============================================================

    def parse_storytelling_text(self, text: str) -> list[dict]:
        """
        Divide uma história em segmentos TTS.

        Regras:
        narração                   -> pm_santa
        "fala sem personagem"      -> pm_alex
        [Personagem] "fala"        -> voz Qwen

        Falas consecutivas do MESMO personagem, sem narração real
        entre elas, são fundidas em um único segmento.
        """

        # Remove o bloco de metadados <t>...</t> quando estiver
        # no início do texto, com ou sem ** de Markdown.
        # Exemplos removidos:
        # <t>Hora: 10:11 | Data: Jun 17</t>
        # **<t>Hora: 10:11 | Data: Jun 17</t>**
        # Espaços e quebras de linha anteriores também são ignorados.
        text = re.sub(
            r"^\s*(?:\*\*\s*)?<t>.*?</t>\s*(?:\*\*)?\s*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

        token_re = re.compile(
            # [Personagem] "fala" {speech manner opcional}
            r'\[([^\[\]\r\n]+)\]\s*"([^"]+)"(?:\s*\{([^{}\r\n]+)\})?' r"|"
            # "fala anônima" {speech manner opcional}
            r'"([^"]+)"(?:\s*\{([^{}\r\n]+)\})?',
            re.MULTILINE,
        )

        raw_segments = []
        cursor = 0

        for match in token_re.finditer(text):

            between = text[cursor : match.start()]

            # ----------------------------------------------------------
            # Existe texto entre o último token e este.
            # ----------------------------------------------------------

            if between:
                narration = between.strip()

                # Markdown ** isolado ao redor do bloco inicial não deve
                # virar narração.
                narration = re.sub(r"^\*{1,2}\s*", "", narration)
                narration = re.sub(r"\s*\*{1,2}$", "", narration)
                narration = narration.strip()

                if narration:
                    raw_segments.append(
                        {
                            "type": "narration",
                            "text": narration,
                            "character": None,
                        }
                    )

            character = match.group(1)

            # ----------------------------------------------------------
            # [Personagem] "fala"
            # ----------------------------------------------------------
            if character is not None:
                speech = match.group(2).strip()
                speech_manner = match.group(3).strip() if match.group(3) else None

                character = self._normalize_character(character)

                if speech:
                    raw_segments.append(
                        {
                            "type": "character",
                            "text": speech,
                            "character": character,
                            "style": speech_manner,
                        }
                    )

            # ----------------------------------------------------------
            # "fala sem personagem"
            # ----------------------------------------------------------
            else:
                speech = match.group(4).strip()
                speech_manner = match.group(5).strip() if match.group(5) else None

                if speech:
                    raw_segments.append(
                        {
                            "type": "anonymous",
                            "text": speech,
                            "character": None,
                            "style": speech_manner,
                        }
                    )

            cursor = match.end()

        # --------------------------------------------------------------
        # Narração final
        # --------------------------------------------------------------

        if cursor < len(text):
            narration = text[cursor:].strip()

            narration = re.sub(r"^\*{1,2}\s*", "", narration)
            narration = re.sub(r"\s*\*{1,2}$", "", narration)
            narration = narration.strip()

            if narration:
                raw_segments.append(
                    {
                        "type": "narration",
                        "text": narration,
                        "character": None,
                    }
                )

        # ==============================================================
        # FUNDE FALAS CONSECUTIVAS DO MESMO PERSONAGEM
        # ==============================================================

        merged_segments = []

        for segment in raw_segments:
            if (
                merged_segments
                and segment["type"] == "character"
                and merged_segments[-1]["type"] == "character"
                and (
                    self._character_key(segment["character"])
                    == self._character_key(merged_segments[-1]["character"])
                )
                and segment.get("style") == merged_segments[-1].get("style")
            ):
                merged_segments[-1]["text"] = (
                    merged_segments[-1]["text"].rstrip()
                    + " "
                    + segment["text"].lstrip()
                )

                continue

            merged_segments.append(segment)

        # ==============================================================
        # RESOLVE AS VOZES SOMENTE DEPOIS DA FUSÃO
        # ==============================================================

        segments = []

        for segment in merged_segments:

            if segment["type"] == "narration":
                segments.append(
                    {
                        "text": segment["text"],
                        "voice": "pm_santa",
                        "character": None,
                        "style": None,
                    }
                )

            elif segment["type"] == "anonymous":
                segments.append(
                    {
                        "text": segment["text"],
                        "voice": "pm_alex",
                        "character": None,
                        "style": None,
                    }
                )

            else:
                character = segment["character"]
                speech = segment["text"]

                voice = self.get_voice(
                    character,
                    speech=speech,
                )

                segments.append(
                    {
                        "text": speech,
                        "voice": voice,
                        "character": character,
                        "style": segment.get("style"),
                    }
                )

        return segments

    # ==============================================================
    # NORMALIZAÇÃO
    # ==============================================================

    @staticmethod
    def _normalize_character(name: str) -> str:
        return re.sub(r"\s+", " ", name.strip())

    @classmethod
    def _character_key(cls, name: str) -> str:
        return cls._normalize_character(name).casefold()

    # ==============================================================
    # CACHE
    # ==============================================================

    def _load_cache(self):
        with self.lock:
            self.characters.clear()

            if not self.CACHE_FILE.exists():
                logging.info(
                    "[STORY VOICE] Cache ainda não existe: %s",
                    self.CACHE_FILE,
                )
                return

            try:
                with self.CACHE_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    raise ValueError("selectedVoices.json deve conter um objeto JSON.")

                for raw_key, raw_entry in data.items():
                    if not isinstance(raw_entry, dict):
                        continue

                    name = self._normalize_character(
                        str(raw_entry.get("name") or raw_key)
                    )

                    voice = str(raw_entry.get("voice") or "").strip().lower()

                    try:
                        speech_count = max(
                            0,
                            int(raw_entry.get("speech_count", 0)),
                        )
                    except (TypeError, ValueError):
                        speech_count = 0

                    # Não aceitamos no cache uma voz que já não exista
                    # no Qwen configurado atualmente.
                    if not name or voice not in self.available_voices:
                        logging.warning(
                            "[STORY VOICE] Entrada inválida ignorada: %s -> %s",
                            name,
                            voice,
                        )
                        continue

                    key = self._character_key(name)

                    self.characters[key] = {
                        "name": name,
                        "voice": voice,
                        "speech_count": speech_count,
                    }

                logging.info(
                    "[STORY VOICE] %d personagem(ns) carregado(s) do cache.",
                    len(self.characters),
                )

            except Exception:
                logging.exception("[STORY VOICE] Erro lendo cache de vozes.")

    def _save_cache(self):
        """
        Salva atomicamente o JSON.

        Primeiro escreve em .tmp e depois substitui o arquivo real.
        Assim uma interrupção durante a escrita tem menos chance de
        transformar o cache numa oferenda aos deuses da corrupção de dados.
        """

        temp_file = self.CACHE_FILE.with_suffix(".tmp")

        ordered_data = dict(
            sorted(
                self.characters.items(),
                key=lambda item: item[1]["name"].casefold(),
            )
        )

        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(
                ordered_data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        temp_file.replace(self.CACHE_FILE)

    # ==============================================================
    # VOZ
    # ==============================================================

    def get_voice(
        self,
        character: str,
        *,
        speech: str | None = None,
    ) -> str:
        """
        Retorna a voz do personagem.

        Se já existe:
            - reutiliza a voz;
            - incrementa speech_count.

        Se não existe:
            - pede ao LLM uma voz considerando personagens existentes;
            - cria o registro;
            - speech_count começa em 1.
        """

        character = self._normalize_character(character)

        if not character:
            return "ryan"

        key = self._character_key(character)

        # ----------------------------------------------------------
        # Personagem existente
        # ----------------------------------------------------------

        with self.lock:
            cached = self.characters.get(key)

            if cached:
                cached["speech_count"] += 1
                self._save_cache()

                logging.info(
                    "[STORY VOICE] Cache: %s -> %s | falas=%d",
                    cached["name"],
                    cached["voice"],
                    cached["speech_count"],
                )

                return cached["voice"]

        # ----------------------------------------------------------
        # Personagem novo
        # ----------------------------------------------------------

        voice, gender = self._classify_voice(
            character,
            speech=speech,
        )

        with self.lock:
            # Verificação dupla.
            #
            # Outra thread pode ter registrado o personagem enquanto
            # estávamos esperando o LLM responder.
            existing = self.characters.get(key)

            if existing:
                existing["speech_count"] += 1
                self._save_cache()
                return existing["voice"]

            self.characters[key] = {
                "name": character,
                "gender": gender,
                "voice": voice,
                "speech_count": 1,
            }

            self._save_cache()

        logging.info(
            "[STORY VOICE] Nova classificação: %s -> %s | falas=1",
            character,
            voice,
        )

        return voice

    # ==============================================================
    # INFORMAÇÕES PARA CLASSIFICAÇÃO
    # ==============================================================

    def _build_voice_usage_summary(self) -> str:
        """
        Produz para o LLM algo como:

        ryan:
          - Asta: 84 falas [CONSOLIDADO]

        serena:
          - Raegis: 4 falas

        vivian:
          - não utilizada
        """

        with self.lock:
            snapshot = {key: value.copy() for key, value in self.characters.items()}

        voice_usage = {voice: [] for voice in self.available_voices}

        for data in snapshot.values():
            voice = data["voice"]

            if voice not in voice_usage:
                continue

            voice_usage[voice].append(data)

        lines = []

        for voice in self.available_voices:
            entries = voice_usage[voice]

            if not entries:
                gender = self.voice_genders.get(voice, "unknown")
                lines.append(f"- {voice} [{gender}]: NÃO UTILIZADA")
                continue

            # Mais consolidados primeiro.
            entries = sorted(
                entries,
                key=lambda item: item["speech_count"],
                reverse=True,
            )

            descriptions = []

            for entry in entries:
                count = entry["speech_count"]

                consolidated = (
                    " [CONSOLIDADO]" if count >= self.CONSOLIDATED_SPEECH_COUNT else ""
                )

                descriptions.append(f'{entry["name"]}: {count} fala(s){consolidated}')

            gender = self.voice_genders.get(voice, "unknown")

            lines.append(f"- {voice} [{gender}]: " + "; ".join(descriptions))

        return "\n".join(lines)

    # ==============================================================
    # CLASSIFICAÇÃO LLM
    # ==============================================================

    def _classify_voice(
        self,
        character: str,
        *,
        speech: str | None = None,
    ) -> tuple[str, str]:

        usage_summary = self._build_voice_usage_summary()

        speech_context = (
            speech.strip()
            if isinstance(speech, str) and speech.strip()
            else "(nenhuma fala disponível)"
        )

        voice_catalog = "\n".join(
            f"- {voice}: {self.voice_genders.get(voice, 'unknown')}"
            for voice in self.available_voices
        )

        prompt = f"""
    Você atribui vozes TTS a personagens.

    Determine:
    1. o gênero mais provável do personagem;
    2. a voz mais apropriada e compatível.

    VOZES:
    {voice_catalog}

    PERSONAGEM:
    {character}

    FALA:
    {speech_context}

    USO ATUAL DAS VOZES:
    {usage_summary}

    REGRAS:

    - Gênero deve ser: male, female ou unknown.
    - Use principalmente o nome e contexto para inferir gênero.
    - female deve usar SOMENTE voz female.
    - male deve usar SOMENTE voz male.
    - unknown pode usar qualquer voz.
    - Compatibilidade de gênero tem prioridade sobre uso.
    - Entre vozes compatíveis, prefira as menos utilizadas.
    - Evite vozes de personagens [CONSOLIDADO].
    - Não invente vozes.

    Responda SOMENTE:
    gender|voice

    Exemplo:
    female|serena
    """.strip()

        request_payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classifique gênero e voz para personagens de TTS. "
                        "Responda somente no formato gender|voice."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0,
            "max_tokens": 20,
        }

        if self.llm_model:
            request_payload["model"] = self.llm_model

        data = json.dumps(
            request_payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.llm_url + "/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))

            content = str(result["choices"][0]["message"]["content"]).strip().lower()

            # ESSENCIAL PARA DIAGNÓSTICO
            logging.info(
                "[STORY VOICE] Resposta bruta do LLM para %s: %r",
                character,
                content,
            )

            # ----------------------------------------------------------
            # Procura male|voice, female|voice ou unknown|voice
            # mesmo que o modelo tenha acrescentado porcaria em volta.
            # ----------------------------------------------------------

            match = re.search(
                r"\b(male|female|unknown)\s*\|\s*" r"([a-zA-Z0-9_-]+)\b",
                content,
            )

            if not match:
                raise ValueError(
                    f"Resposta do LLM fora do formato esperado: {content!r}"
                )

            gender = match.group(1).lower()
            voice = match.group(2).lower()

            # ----------------------------------------------------------
            # Voz existe?
            # ----------------------------------------------------------

            if voice not in self.available_voices:
                logging.warning(
                    "[STORY VOICE] Voz inexistente retornada para %s: %s",
                    character,
                    voice,
                )

                return (
                    self._fallback_voice(gender=gender),
                    gender,
                )

            # ----------------------------------------------------------
            # Gênero da voz
            # ----------------------------------------------------------

            voice_gender = self.voice_genders.get(
                voice,
                "unknown",
            )

            # ----------------------------------------------------------
            # Impede combinação incompatível
            # ----------------------------------------------------------

            if gender in {"male", "female"} and voice_gender != gender:
                logging.warning(
                    "[STORY VOICE] Voz incompatível para %s: "
                    "personagem=%s, voz=%s (%s). "
                    "Aplicando fallback por gênero.",
                    character,
                    gender,
                    voice,
                    voice_gender,
                )

                voice = self._fallback_voice(gender=gender)

            logging.info(
                "[STORY VOICE] Classificação final: " "%s -> gênero=%s | voz=%s",
                character,
                gender,
                voice,
            )

            return voice, gender

        except Exception:
            logging.exception(
                "[STORY VOICE] Falha classificando personagem %s.",
                character,
            )

            # Aqui não conhecemos o gênero com segurança.
            return self._fallback_voice(), "unknown"

    # ==============================================================
    # FALLBACK
    # ==============================================================

    def _fallback_voice(
        self,
        gender: str | None = None,
    ) -> str:

        with self.lock:
            usage_count = {voice: 0 for voice in self.available_voices}

            for data in self.characters.values():
                voice = data["voice"]

                if voice in usage_count:
                    usage_count[voice] += data["speech_count"]

        if gender in {"male", "female"}:
            candidates = [
                voice
                for voice in self.available_voices
                if self.voice_genders.get(voice) == gender
            ]
        else:
            candidates = list(self.available_voices)

        if not candidates:
            candidates = list(self.available_voices)

        if not candidates:
            return "ryan"

        selected = min(
            candidates,
            key=lambda voice: usage_count.get(voice, 0),
        )

        logging.warning(
            "[STORY VOICE] Fallback de menor utilização: " "%s | gênero=%s | peso=%d",
            selected,
            gender or "unknown",
            usage_count.get(selected, 0),
        )

        return selected
