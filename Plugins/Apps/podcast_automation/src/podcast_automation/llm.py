"""Cliente de resumos pela API Chat Completions da PIA."""

import json
import os
import re
import time
import requests
from src.app_access import current, headers


class PiaClient:
    def __init__(self):
        context = current()
        self.base_url = context["url"].rstrip("/") + "/v1"
        self.model = context["model"]
        self.headers = {"Content-Type": "application/json", **headers()}
        self.timeout = float(context.get("timeout", 3600))

    def complete_json(self, prompt, fields, attempts=3, *, validate=None):
        payload = {
            "model": self.model,
            "stream": False,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                    + "\nResponda SOMENTE com um objeto JSON com os campos: "
                    + ", ".join(fields),
                }
            ],
        }
        for attempt in range(attempts):
            try:
                response = requests.post(
                    self.base_url + "/chat/completions",
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    detail = ""
                    try:
                        message = response.json().get("error", {}).get("message")
                        if isinstance(message, str):
                            # Não imprime corpo completo; oculta a chave e URLs.
                            key = self.headers.get("Authorization", "").removeprefix(
                                "Bearer "
                            )
                            if key:
                                message = message.replace(key, "[chave omitida]")
                            message = re.sub(
                                r"https?://[^\s]+", "[URL omitida]", message
                            )
                            detail = " " + message[:1000]
                    except (ValueError, AttributeError):
                        pass
                    raise RuntimeError(
                        f"PIA retornou HTTP {response.status_code}.{detail}"
                    )
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("A API não retornou conteúdo textual.")
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                data = json.loads(content)
                if not isinstance(data, dict) or any(
                    not isinstance(data.get(k), str) or not data[k].strip()
                    for k in fields
                ):
                    raise ValueError("Resposta JSON sem os campos obrigatórios.")
            except requests.RequestException as exc:
                if attempt + 1 == attempts:
                    raise RuntimeError(
                        "Não foi possível comunicar com a PIA. Verifique se o servidor "
                        "está iniciado na mesma instalação."
                    ) from exc
            except (KeyError, IndexError, ValueError) as exc:
                if attempt + 1 == attempts:
                    raise RuntimeError(
                        "A PIA não retornou um JSON válido com os campos do resumo."
                    ) from exc
            except RuntimeError:
                if (
                    response.status_code not in (429, 500, 502, 503, 504)
                    or attempt + 1 == attempts
                ):
                    raise
            else:
                if validate is None:
                    return data
                try:
                    return validate(data)
                except ValueError as exc:
                    if attempt + 1 == attempts:
                        raise RuntimeError(
                            f"A PIA não gerou um resumo válido após {attempts} "
                            f"tentativa(s). Último erro: {exc}"
                        ) from exc
            time.sleep(min(2**attempt, 30))
