"""Helpers to communicate with SAT/Agent servers (simple HTTP wrappers) in src."""

import json
import threading
import requests

from .config import SAT_SERVER_URL, AGENT_SERVER_URL, logging


def _synthesize_and_speak(text_chunk: str) -> None:
    """Envia um pedaço de texto para o SAT sintetizar e falar."""
    if not text_chunk or not text_chunk.strip():
        return
    try:
        # Exemplo padrão de chamada ao SAT local
        requests.post(
            f"{SAT_SERVER_URL}/speak",  # Ajuste para a rota real do seu SAT se necessário
            json={"text": text_chunk},
            timeout=5.0,
        )
    except Exception as e:
        logging.error(f"[SAT] Erro ao sintetizar trecho: {e}")


def _consume_agent_stream(prompt_text: str) -> None:
    """Consome o stream SSE do agente e envia os trechos para o SAT de forma fluida."""
    try:
        logging.info(f"[AGENT] Iniciando stream para -> '{prompt_text}'")

        payload = {
            "model": "gemini-local",
            "messages": [{"role": "user", "content": prompt_text}],
            "stream": True,
        }

        response = requests.post(
            f"{AGENT_SERVER_URL}/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=(2.0, 30.0),
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                data_content = line_str[6:].strip()

                if data_content == "[DONE]":
                    break

                try:
                    chunk_json = json.loads(data_content)
                    choices = chunk_json.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content_fragment = delta.get("content", "")

                        if content_fragment:
                            # Envia o pedaço imediatamente para o SAT falar
                            _synthesize_and_speak(content_fragment)
                except json.JSONDecodeError:
                    continue

        logging.info("[AGENT] Stream finalizado com sucesso.")

    except Exception as e:
        logging.error(f"[AGENT] Erro na conexão ou leitura do stream do Agent: {e}")


def send_to_agent(prompt_text: str) -> None:
    """Dispara o envio do prompt para o agente em background consumindo o stream via SSE."""
    if not prompt_text.strip():
        return

    # Roda em thread separada para não bloquear o loop principal da aplicação
    threading.Thread(
        target=_consume_agent_stream, args=(prompt_text,), daemon=True
    ).start()


def warm_up_services() -> None:
    def _ping(url: str, name: str) -> None:
        try:
            logging.info(f"[PIA] Pré-aquecendo o servidor {name}...")
            requests.get(url)
        except Exception as e:
            logging.warning(f"[PIA] Não foi possível pré-aquecer o {name}: {e}")

    threading.Thread(
        target=lambda: _ping(f"{SAT_SERVER_URL}/stt/warmup", "STT"), daemon=True
    ).start()
    threading.Thread(
        target=lambda: _ping(f"{SAT_SERVER_URL}/tts/warmup", "TTS"), daemon=True
    ).start()
    threading.Thread(
        target=lambda: _ping(f"{AGENT_SERVER_URL}/warmup", "Agent"), daemon=True
    ).start()
