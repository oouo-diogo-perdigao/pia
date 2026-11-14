"""Gerenciamento seguro de manifestos e artefatos locais de modelos TTS."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable

from src.user_paths import user_path


def models_root() -> Path:
    return user_path("tts_models")


def model_dir(provider_id: str, model_id: str) -> Path:
    safe_p = "".join(c for c in provider_id if c.isalnum() or c in "-_")
    safe_m = "".join(c for c in model_id if c.isalnum() or c in "-_.")
    if not safe_p or not safe_m or ".." in safe_m:
        raise ValueError("Identificador de modelo inválido.")
    return models_root() / safe_p / safe_m


def manifest_path(provider_id: str, model_id: str) -> Path:
    return model_dir(provider_id, model_id) / "manifest.json"


def read_manifest(provider_id: str, model_id: str) -> dict[str, Any] | None:
    path = manifest_path(provider_id, model_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        files = data.get("files") or []
        base = model_dir(provider_id, model_id).resolve()
        for rel in files:
            candidate = (base / rel).resolve()
            if not candidate.is_relative_to(base) or not candidate.is_file():
                return None
        return data
    except Exception:
        return None


def is_manifest_installed(provider_id: str, model_id: str) -> bool:
    return read_manifest(provider_id, model_id) is not None


def _download_file(
    url: str,
    dest: Path,
    expected_sha256: str | None,
    progress_cb: Callable[[int, int | None], None] | None,
    cancel_event: threading.Event | None,
    completed_base: int,
    total_bytes: int | None,
) -> int:
    if not url.startswith("https://"):
        raise ValueError("Somente downloads HTTPS são permitidos no catálogo TTS.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "PIA-TTS-Installer/1.0"})
    hasher = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(req, timeout=60) as resp:
        content_len = resp.headers.get("Content-Length")
        file_total = int(content_len) if content_len and content_len.isdigit() else None
        effective_total = total_bytes or file_total
        with dest.open("wb") as out:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Instalação cancelada.")
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
                if progress_cb is not None:
                    progress_cb(completed_base + written, effective_total)
    if expected_sha256 and hasher.hexdigest().lower() != expected_sha256.lower():
        raise ValueError(f"Checksum inválido para {dest.name}.")
    return written


def install_artifacts(
    provider_id: str,
    model_id: str,
    artifacts: list[dict[str, Any]],
    *,
    job_id: str,
    progress_cb: Callable[[int, int | None], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Baixa artefatos em staging, valida checksums e promove atomicamente."""
    target_dir = model_dir(provider_id, model_id)
    staging_dir = models_root() / ".staging" / f"{provider_id}_{model_id}_{job_id}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    total_hint = sum(int(a.get("size_bytes") or 0) for a in artifacts) or None
    downloaded = 0
    rel_files: list[str] = []
    try:
        for item in artifacts:
            filename = str(item["filename"]).replace("\\", "/").lstrip("/")
            if ".." in filename or filename.startswith("/"):
                raise ValueError("Caminho de artefato inválido no catálogo.")
            dest = (staging_dir / filename).resolve()
            if not dest.is_relative_to(staging_dir.resolve()):
                raise ValueError("Path traversal detectado no artefato.")
            written = _download_file(
                str(item["url"]),
                dest,
                item.get("sha256"),
                progress_cb,
                cancel_event,
                downloaded,
                total_hint,
            )
            downloaded += written
            rel_files.append(filename)

        manifest = {
            "schema_version": 1,
            "provider": provider_id,
            "model": model_id,
            "files": rel_files,
            "bytes": downloaded,
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = None
        if target_dir.exists():
            backup_dir = target_dir.with_name(target_dir.name + ".bak")
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            os.replace(target_dir, backup_dir)
        try:
            os.replace(staging_dir, target_dir)
        except Exception:
            if backup_dir and backup_dir.exists() and not target_dir.exists():
                os.replace(backup_dir, target_dir)
            raise
        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        return manifest
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def uninstall_artifacts(provider_id: str, model_id: str) -> bool:
    """Remove apenas os artefatos declarados no manifesto deste modelo."""
    manifest = read_manifest(provider_id, model_id)
    target_dir = model_dir(provider_id, model_id)
    if not manifest or not target_dir.exists():
        return False
    base = target_dir.resolve()
    for rel in manifest.get("files") or []:
        candidate = (base / rel).resolve()
        if (
            candidate.is_relative_to(base)
            and candidate.is_file()
            and not candidate.is_symlink()
        ):
            candidate.unlink(missing_ok=True)
    mfile = manifest_path(provider_id, model_id)
    if mfile.is_file():
        mfile.unlink(missing_ok=True)
    try:
        shutil.rmtree(target_dir, ignore_errors=True)
    except Exception:
        pass
    return True
