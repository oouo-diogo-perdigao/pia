import os
import json
import time
import logging
import threading
import requests
import pygame
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from litellm import Router
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 8766))
HOST = os.getenv("HOST", "127.0.0.1")

PROCESSING_SOUND_PATH = os.path.join("..", "sounds", "end.mp3")

pygame.mixer.init()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)

# Inicializa o Roteador de LLMs carregando as prioridades e fallbacks do YAML
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "models.yaml")
llm_router = Router(config_path=CONFIG_PATH)


def play_sound(file_path: str):
    """Reproduz som de feedback sem bloquear a thread."""

    def _play():
        try:
            if os.path.exists(file_path):
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
        except Exception as e:
            logging.error("[SOUND] Erro ao tocar som: %s", e)

    threading.Thread(target=_play, daemon=True).start()


def speak_tts(text: str):
    """Envia o texto para o serviço local de TTS."""
    try:
        requests.post(
            f"{os.getenv('TTS_SERVER_URL', 'http://127.0.0.1:8765')}/speak",
            json={"text": text},
            timeout=5,
        )
    except Exception as e:
        logging.error("[TTS ERRO] Falha ao enviar para o TTS: %s", e)


# ============================================================================
# GERENCIADOR DE AGENTES COM LITELLM ROUTER
# ============================================================================
class GenericAgent:
    """Agente genérico que consome a lista de prioridades do Router."""

    def run(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "Você é um assistente de voz prestativo e sucinto. Responda de forma direta em português.",
            },
            {"role": "user", "content": prompt},
        ]

        # O Router tenta o primeiro modelo da lista. Se estourar a cota/erro, faz fallback automático
        response = llm_router.completion(model="auto-agent", messages=messages)

        # Log de qual modelo realmente respondeu essa requisição
        used_model = response.get("model", "desconhecido")
        logging.info("[ROUTER] Resposta gerada usando o modelo: %s", used_model)

        return response.choices[0].message.content.strip()


class AgentManager:
    def __init__(self):
        self.agents = {
            "generic": GenericAgent(),
        }

    def process(self, prompt: str, agent_type: str = "generic") -> str:
        agent = self.agents.get(agent_type, self.agents["generic"])
        return agent.run(prompt)


# ============================================================================
# GERENCIADOR DE BUFFER E INATIVIDADE
# ============================================================================
class InactivityBufferManager:
    def __init__(self, inactivity_timeout: float = 3.0):
        self.timeout = inactivity_timeout
        self.buffer = []
        self.last_update_time = 0.0
        self.lock = threading.Lock()
        self.agent_manager = AgentManager()
        self.worker_thread = threading.Thread(
            target=self._monitor_inactivity, daemon=True
        )
        self.worker_thread.start()

    def add_text(self, text: str):
        with self.lock:
            self.buffer.append(text)
            self.last_update_time = time.time()
            logging.info("[BUFFER] Texto adicionado: '%s'", " ".join(self.buffer))

    def _monitor_inactivity(self):
        while True:
            time.sleep(0.2)
            with self.lock:
                if not self.buffer:
                    continue

                elapsed = time.time() - self.last_update_time
                if elapsed >= self.timeout:
                    full_prompt = " ".join(self.buffer).strip()
                    self.buffer.clear()

                    play_sound(PROCESSING_SOUND_PATH)

                    threading.Thread(
                        target=self._execute_agent, args=(full_prompt,), daemon=True
                    ).start()

    def _execute_agent(self, prompt: str):
        logging.info("[AGENT EXEC] Prompt final: '%s'", prompt)
        try:
            response_text = self.agent_manager.process(prompt)
            logging.info("[AGENT EXEC] Resposta: '%s'", response_text)
            speak_tts(response_text)
        except Exception as e:
            logging.error("[AGENT EXEC] Erro ao executar LLM/Fallback: %s", e)


BUFFER_MANAGER = InactivityBufferManager(inactivity_timeout=3.0)


# ============================================================================
# SERVIDOR HTTP (Porta 8766)
# ============================================================================
class AgentHandler(BaseHTTPRequestHandler):
    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/process":
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")

            try:
                data = json.loads(raw_body)
                user_text = data.get("text", "").strip()

                if not user_text:
                    self.send_json(400, {"ok": False, "error": "Texto ausente."})
                    return

                BUFFER_MANAGER.add_text(user_text)
                self.send_json(200, {"ok": True, "status": "buffered"})

            except Exception as e:
                logging.error("[HTTP ERRO]: %s", e)
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})

    def log_message(self, fmt, *args) -> None:
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), AgentHandler)
    logging.info(
        "Servidor AGENT ativo na porta %d com suporte a Fallback/YAML...", PORT
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando Agent...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
