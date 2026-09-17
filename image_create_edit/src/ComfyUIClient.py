from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .config import (
    COMFYUI_URL,
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
    COMFYUI_SAFE_FREE,
    COMFYUI_UNLOAD_MODELS,
    COMFYUI_FREE_MEMORY,
)
from .multipart_utils import encode_multipart


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str = COMFYUI_URL):
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        expect_json: bool = True,
    ):
        request_headers = dict(headers or {})
        request_body = body

        if json_body is not None:
            request_body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(
            self._url(path),
            data=request_body,
            headers=request_headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(
                req, timeout=timeout or COMFYUI_TIMEOUT_SECONDS
            ) as response:
                data = response.read()
                if not expect_json:
                    return data, dict(response.headers.items())
                if not data:
                    return {}
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise ComfyUIError(
                f"ComfyUI respondeu HTTP {exc.code} em {path}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ComfyUIError(
                f"Não foi possível conectar ao ComfyUI em {self.base_url}: {exc}"
            ) from exc

    def health(self) -> dict:
        return self._request("GET", "/system_stats")

    def list_models(self, folder: str) -> list[str]:
        response = self._request("GET", f"/models/{urllib.parse.quote(folder)}")
        return [str(x) for x in response] if isinstance(response, list) else []

    def queue_state(self) -> dict:
        return self._request("GET", "/queue")

    def submit_prompt(self, workflow: dict) -> str:
        response = self._request(
            "POST",
            "/prompt",
            json_body={"prompt": workflow, "client_id": uuid.uuid4().hex},
        )
        node_errors = response.get("node_errors") or {}
        if node_errors:
            raise ComfyUIError(
                "ComfyUI rejeitou o workflow: "
                + json.dumps(node_errors, ensure_ascii=False)
            )

        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(
                "ComfyUI não devolveu prompt_id: "
                + json.dumps(response, ensure_ascii=False)
            )
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> dict:
        return self._request("GET", f"/history/{urllib.parse.quote(prompt_id)}")

    def wait_for_prompt(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + COMFYUI_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if str(status.get("status_str") or "").lower() == "error":
                    raise ComfyUIError(
                        "Workflow do ComfyUI terminou com erro: "
                        + json.dumps(status.get("messages") or [], ensure_ascii=False)
                    )
                outputs = entry.get("outputs") or {}
                if outputs or status.get("completed"):
                    return entry
            time.sleep(COMFYUI_POLL_INTERVAL_SECONDS)
        raise TimeoutError(
            f"Tempo limite excedido aguardando o prompt {prompt_id} no ComfyUI."
        )

    @staticmethod
    def output_image_refs(history_entry: dict) -> list[dict]:
        refs = []
        for output in (history_entry.get("outputs") or {}).values():
            for item in output.get("images") or []:
                if item.get("filename"):
                    refs.append(item)
        if not refs:
            raise ComfyUIError(
                "O workflow terminou, mas nenhum nó de saída retornou imagem."
            )
        return refs

    def download_image(self, ref: dict) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": ref.get("filename", ""),
                "subfolder": ref.get("subfolder", ""),
                "type": ref.get("type", "output"),
            }
        )
        data, _headers = self._request("GET", f"/view?{query}", expect_json=False)
        return data

    def run_workflow(self, workflow: dict) -> list[bytes]:
        prompt_id = self.submit_prompt(workflow)
        logging.info("[COMFYUI] Workflow enviado: prompt_id=%s", prompt_id)
        history_entry = self.wait_for_prompt(prompt_id)
        images = [
            self.download_image(ref) for ref in self.output_image_refs(history_entry)
        ]
        logging.info(
            "[COMFYUI] Workflow concluído: prompt_id=%s imagens=%d",
            prompt_id,
            len(images),
        )
        return images

    def upload_image(
        self, data: bytes, *, filename: str, content_type: str = "image/png"
    ) -> str:
        multipart_type, multipart_body = encode_multipart(
            fields={"type": "input", "overwrite": "true"},
            files=[
                ("image", filename, content_type or "application/octet-stream", data)
            ],
        )
        response = self._request(
            "POST",
            "/upload/image",
            body=multipart_body,
            headers={"Content-Type": multipart_type},
        )
        name = response.get("name") or filename
        subfolder = response.get("subfolder") or ""
        return f"{subfolder}/{name}".strip("/") if subfolder else str(name)

    def safe_free_memory(self) -> bool:
        if COMFYUI_SAFE_FREE:
            try:
                queue = self.queue_state()
                running = queue.get("queue_running") or []
                pending = queue.get("queue_pending") or []
                if running or pending:
                    logging.warning(
                        "[COMFYUI] /free não executado: running=%d pending=%d.",
                        len(running),
                        len(pending),
                    )
                    return False
            except Exception:
                logging.exception("[COMFYUI] Falha ao consultar /queue antes de /free.")
                return False

        try:
            self._request(
                "POST",
                "/free",
                json_body={
                    "unload_models": COMFYUI_UNLOAD_MODELS,
                    "free_memory": COMFYUI_FREE_MEMORY,
                },
            )
            logging.info(
                "[COMFYUI] /free solicitado (unload_models=%s free_memory=%s).",
                COMFYUI_UNLOAD_MODELS,
                COMFYUI_FREE_MEMORY,
            )
            return True
        except Exception:
            logging.exception("[COMFYUI] Falha ao solicitar liberação de memória.")
            return False
