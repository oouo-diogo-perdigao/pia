import json
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, logging

from .InactivityBufferManager import InactivityBufferManager

BUFFER_MANAGER = InactivityBufferManager(inactivity_timeout=3.0)


# ============================================================================
# SERVIDOR HTTP
# ============================================================================
class HTTPServer(BaseHTTPRequestHandler):
    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path in ("/process", "/v1/chat/completions"):
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")

            # Log separado e dedicado das entradas da LLM/API
            llm_logger = logging.getLogger("llm_trace")
            llm_logger.info("[LLM INPUT] %s", raw_body)

            try:
                data = json.loads(raw_body)

                # Suporte a payload padrão OpenAI (/v1/chat/completions) ou customizado (/process)
                if self.path == "/v1/chat/completions":
                    messages = data.get("messages", [])
                    user_text = (
                        messages[-1].get("content", "").strip() if messages else ""
                    )
                else:
                    user_text = data.get("text", "").strip()

                if not user_text:
                    error_payload = (
                        {
                            "error": {
                                "message": "Texto ou mensagens ausentes.",
                                "type": "invalid_request_error",
                            }
                        }
                        if "v1" in self.path
                        else {"ok": False, "error": "Texto ausente."}
                    )
                    self.send_json(400, error_payload)
                    return

                # Executa o processamento real do agente para obter a resposta da LLM
                try:
                    agent_response = BUFFER_MANAGER.agent_manager.process(user_text)
                except Exception as ex:
                    agent_response = f"Erro ao executar agente: {ex}"

                if self.path == "/v1/chat/completions":
                    is_stream = data.get("stream", False)
                    model_name = data.get("model", "gemini-local")
                    chunk_id = f"chatcmpl-{int(time.time())}"

                    if is_stream:
                        self.send_response(200)
                        self.send_header(
                            "Content-Type", "text/event-stream; charset=utf-8"
                        )
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()

                        # Envia o conteúdo gerado pelo agente em formato chunk SSE do padrão OpenAI
                        chunk_payload = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": agent_response},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        self.wfile.write(
                            f"data: {json.dumps(chunk_payload, ensure_ascii=False)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()

                        end_payload = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": "stop"}
                            ],
                        }
                        self.wfile.write(
                            f"data: {json.dumps(end_payload, ensure_ascii=False)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()

                        llm_logger.info(
                            "[LLM OUTPUT STREAM] Resposta enviada com sucesso: %s",
                            agent_response,
                        )
                    else:
                        response_payload = {
                            "id": chunk_id,
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": agent_response,
                                    },
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                        llm_logger.info(
                            "[LLM OUTPUT] %s",
                            json.dumps(response_payload, ensure_ascii=False),
                        )
                        self.send_json(200, response_payload)
                else:
                    self.send_json(200, {"ok": True, "response": agent_response})

            except Exception as e:
                logging.error("[HTTP ERRO]: %s", e)
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})

    def do_GET(self) -> None:
        if self.path == "/warmup":
            try:
                logging.info("[WARMUP] Aquecendo conexões do Agent/LiteLLM...")
                BUFFER_MANAGER.agent_manager.process("Diga Olá!")
                logging.info("[WARMUP] Modelo de IA aquecido com sucesso!")
                self.send_json(200, {"ok": True, "status": "warmed_up"})
            except Exception as e:
                logging.error("[HTTP ERRO]: %s", e)
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})

    # Override para suprimir logs de requisições HTTP padrão no console
    def log_message(self, fmt, *args) -> None:
        pass


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), HTTPServer)
    logging.info("Servidor HTTP leve iniciado em http://%s:%d", HOST, PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass
