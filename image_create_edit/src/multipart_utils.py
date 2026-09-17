from __future__ import annotations

from collections import defaultdict
from email import policy
from email.parser import BytesParser
import mimetypes
import uuid


def parse_multipart(content_type: str, body: bytes):
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Content-Type não é multipart/form-data.")

    synthetic = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + body

    message = BytesParser(policy=policy.default).parsebytes(synthetic)
    if not message.is_multipart():
        raise ValueError("Corpo multipart inválido.")

    fields: dict[str, str] = {}
    files = defaultdict(list)

    for part in message.iter_parts():
        if not part.get("Content-Disposition"):
            continue

        name = part.get_param("name", header="content-disposition")
        if not name:
            continue

        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            fields[str(name)] = payload.decode(charset, errors="replace")
            continue

        files[str(name)].append(
            {
                "filename": str(filename),
                "content_type": part.get_content_type() or "application/octet-stream",
                "data": payload,
            }
        )

    return fields, dict(files)


def encode_multipart(*, fields=None, files=None) -> tuple[str, bytes]:
    boundary = f"----pia-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in (fields or {}).items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode("utf-8"),
            b"\r\n",
        ])

    for field_name, filename, content_type, data in (files or []):
        safe_filename = filename.replace('"', "_")
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{safe_filename}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            b"\r\n",
        ])

    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def extension_for_content_type(content_type: str, fallback: str = ".png") -> str:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    aliases = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return aliases.get(content_type) or mimetypes.guess_extension(content_type) or fallback
