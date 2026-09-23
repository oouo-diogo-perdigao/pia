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
        if self.path == "/v1/chat/completions":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_length).decode("utf-8")

                # Log separado e dedicado das entradas da LLM/APIVocê está me escutando bem?
                llm_logger = logging.getLogger("llm_trace")
                llm_logger.info("[LLM INPUT] %s", raw_body)

                data = json.loads(raw_body)

                messages = data.get("messages", [])
                user_text = messages[-1].get("content", "").strip() if messages else ""

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

                is_stream = data.get("stream", False)
                model_name = data.get("model", "gemini-local")
                chunk_id = f"chatcmpl-{int(time.time())}"

                if is_stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()

                    full_response = ""
                    try:
                        for chunk_text in BUFFER_MANAGER.agent_manager.process_stream(
                            user_text
                        ):
                            if not chunk_text:
                                continue
                            full_response += chunk_text

                            chunk_payload = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": chunk_text},
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
                    except Exception as ex:
                        error_chunk = f"Erro no stream do agente: {ex}"
                        full_response += error_chunk

                    # Encerramento do stream
                    end_payload = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
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
                        full_response,
                    )

                else:
                    try:
                        agent_response = BUFFER_MANAGER.agent_manager.process(user_text)
                    except Exception as ex:
                        agent_response = f"Erro ao executar agente: {ex}"

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


def run_agent_server():
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
