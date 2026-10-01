from __future__ import annotations

import base64
import logging
import re
import threading
import uuid

from .ComfyUIClient import ComfyUIClient
from .WorkflowFactory import build_generation_workflow, build_edit_workflow
from .config import (
    COMFYUI_AUTO_FREE,
    COMFYUI_SERIALIZE_JOBS,
    IMAGE_DEFAULT_SIZE,
    IMAGE_MAX_N,
    IMAGE_MAX_UPLOAD_BYTES,
    IMAGE_EDIT_DENOISE,
    IMAGE_EDIT_MASK_DENOISE,
    IMAGE_VARIATION_DENOISE,
    IMAGE_VARIATION_PROMPT,
)
from .multipart_utils import extension_for_content_type


class OpenAIImageRequestError(ValueError):
    def __init__(self, message: str, *, param: str | None = None, status: int = 400):
        super().__init__(message)
        self.param = param
        self.status = status


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def decode_data_url(value: str) -> tuple[bytes, str]:
    if not isinstance(value, str) or not value.startswith("data:") or "," not in value:
        raise OpenAIImageRequestError(
            "A imagem JSON deve ser uma data URL base64.", param="image"
        )
    header, encoded = value.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "image/png"
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise OpenAIImageRequestError(
            "Base64 de imagem inválido.", param="image"
        ) from exc
    return data, content_type


class ImageManager:
    def __init__(self):
        self.client = ComfyUIClient()
        self._job_lock = threading.Lock()

    @staticmethod
    def parse_size(
        size: str | None, *, preserve_on_auto: bool = False
    ) -> tuple[int, int]:
        size = (size or IMAGE_DEFAULT_SIZE).strip().lower()
        if size in {"auto", ""}:
            if preserve_on_auto:
                return 0, 0
            size = IMAGE_DEFAULT_SIZE

        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", size)
        if not match:
            raise OpenAIImageRequestError(
                "size deve estar no formato WIDTHxHEIGHT ou 'auto'.", param="size"
            )
        width, height = int(match.group(1)), int(match.group(2))
        if not (64 <= width <= 2048 and 64 <= height <= 2048):
            raise OpenAIImageRequestError(
                "width e height devem estar entre 64 e 2048.", param="size"
            )
        width = max(64, round(width / 16) * 16)
        height = max(64, round(height / 16) * 16)
        return width, height

    @staticmethod
    def validate_n(n) -> int:
        try:
            n = int(n or 1)
        except (TypeError, ValueError) as exc:
            raise OpenAIImageRequestError("n deve ser inteiro.", param="n") from exc
        if not 1 <= n <= IMAGE_MAX_N:
            raise OpenAIImageRequestError(
                f"n deve estar entre 1 e {IMAGE_MAX_N}.", param="n"
            )
        return n

    @staticmethod
    def validate_prompt(prompt) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise OpenAIImageRequestError(
                "O campo prompt é obrigatório.", param="prompt"
            )
        return prompt.strip()

    @staticmethod
    def validate_upload(data: bytes, *, param: str) -> None:
        if not data:
            raise OpenAIImageRequestError(
                f"O arquivo '{param}' está vazio.", param=param
            )
        if len(data) > IMAGE_MAX_UPLOAD_BYTES:
            raise OpenAIImageRequestError(
                f"O arquivo '{param}' excede o limite de {IMAGE_MAX_UPLOAD_BYTES} bytes.",
                param=param,
                status=413,
            )

    def _lock(self):
        return self._job_lock if COMFYUI_SERIALIZE_JOBS else _NullLock()

    def _run_and_free(self, callback):
        with self._lock():
            try:
                return callback()
            finally:
                if COMFYUI_AUTO_FREE:
                    self.client.safe_free_memory()

    def generate(self, payload: dict) -> list[bytes]:
        prompt = self.validate_prompt(payload.get("prompt"))
        n = self.validate_n(payload.get("n", 1))
        width, height = self.parse_size(payload.get("size"))
        workflow = build_generation_workflow(
            prompt=prompt,
            width=width,
            height=height,
            n=n,
            seed=payload.get("seed"),
            steps=payload.get("steps"),
        )
        logging.info(
            "[IMAGE] generation prompt_chars=%d size=%dx%d n=%d",
            len(prompt),
            width,
            height,
            n,
        )
        return self._run_and_free(lambda: self.client.run_workflow(workflow))

    def edit(self, *, fields: dict, image: dict, mask: dict | None) -> list[bytes]:
        prompt = self.validate_prompt(fields.get("prompt"))
        n = self.validate_n(fields.get("n", 1))
        width, height = self.parse_size(
            fields.get("size") or "auto", preserve_on_auto=True
        )

        image_data = image["data"]
        image_type = image.get("content_type") or "image/png"
        self.validate_upload(image_data, param="image")
        if mask:
            self.validate_upload(mask["data"], param="mask")

        def job():
            image_name = self.client.upload_image(
                image_data,
                filename=f"openai_edit_{uuid.uuid4().hex}{extension_for_content_type(image_type)}",
                content_type=image_type,
            )
            mask_name = None
            denoise = IMAGE_EDIT_DENOISE
            if mask:
                mask_type = mask.get("content_type") or "image/png"
                mask_name = self.client.upload_image(
                    mask["data"],
                    filename=f"openai_mask_{uuid.uuid4().hex}{extension_for_content_type(mask_type)}",
                    content_type=mask_type,
                )
                denoise = IMAGE_EDIT_MASK_DENOISE

            workflow = build_edit_workflow(
                prompt=prompt,
                image_name=image_name,
                mask_name=mask_name,
                width=width,
                height=height,
                n=n,
                denoise=denoise,
                seed=fields.get("seed"),
                steps=fields.get("steps"),
            )
            return self.client.run_workflow(workflow)

        logging.info(
            "[IMAGE] edit prompt_chars=%d size=%s n=%d masked=%s",
            len(prompt),
            f"{width}x{height}" if width and height else "original",
            n,
            bool(mask),
        )
        return self._run_and_free(job)

    def variation(self, *, fields: dict, image: dict) -> list[bytes]:
        n = self.validate_n(fields.get("n", 1))
        width, height = self.parse_size(
            fields.get("size") or "auto", preserve_on_auto=True
        )
        image_data = image["data"]
        image_type = image.get("content_type") or "image/png"
        self.validate_upload(image_data, param="image")

        def job():
            image_name = self.client.upload_image(
                image_data,
                filename=f"openai_variation_{uuid.uuid4().hex}{extension_for_content_type(image_type)}",
                content_type=image_type,
            )
            workflow = build_edit_workflow(
                prompt=IMAGE_VARIATION_PROMPT,
                image_name=image_name,
                mask_name=None,
                width=width,
                height=height,
                n=n,
                denoise=IMAGE_VARIATION_DENOISE,
                seed=fields.get("seed"),
                steps=fields.get("steps"),
            )
            return self.client.run_workflow(workflow)

        logging.info(
            "[IMAGE] variation size=%s n=%d",
            f"{width}x{height}" if width and height else "original",
            n,
        )
        return self._run_and_free(job)

    def health(self) -> dict:
        return self.client.health()


IMAGE_MANAGER = ImageManager()
