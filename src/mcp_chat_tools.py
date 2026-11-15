"""Native PIA MCP tools for screenshots, Object Storage buckets, RPG sessions, and Suno MCP."""

from __future__ import annotations

import base64
import difflib
import json
import re
import shlex
import subprocess
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from .config_paths import BASE_DIR
from .user_paths import user_path

_SENSITIVE_KEY_RE = re.compile(
    r"(^|/)(secrets?|credentials?|\.env|.*service[-_]?account.*\.json|.*\.pem|.*\.key)$",
    re.IGNORECASE,
)
_SEASON_EP_RE = re.compile(r"S(\d{1,3})E(\d{1,4})", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only).strip()


def _fuzzy_score(query: str, candidate: str) -> float:
    nq = _norm(query)
    nc = _norm(candidate)
    if not nq or not nc:
        return 0.0
    if nq == nc:
        return 1.0
    if nq in nc:
        return 0.92
    q_tokens = [t for t in nq.split() if len(t) > 1]
    c_tokens = [t for t in nc.split() if len(t) > 1]
    if q_tokens and c_tokens:
        hits = 0.0
        for qt in q_tokens:
            best = max(
                (
                    1.0
                    if qt == ct or ct.startswith(qt[:4]) or qt.startswith(ct[:4])
                    else difflib.SequenceMatcher(None, qt, ct).ratio()
                )
                for ct in c_tokens
            )
            if best >= 0.72:
                hits += best
        token_score = hits / len(q_tokens)
        if token_score >= 0.7:
            return min(0.95, token_score)
    return difflib.SequenceMatcher(None, nq, nc).ratio()


def take_screenshot() -> dict[str, Any]:
    root = user_path("chat")
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".png"
    dest = root / name

    captured = False
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(all_screens=True)
        img.save(dest, format="PNG")
        captured = True
    except Exception:
        pass

    if not captured:
        try:
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                pixmap = screen.grabWindow(0)
                if not pixmap.isNull() and pixmap.save(str(dest), "PNG"):
                    captured = True
        except Exception:
            pass

    if not captured or not dest.is_file():
        raise RuntimeError("Não foi possível capturar a tela neste ambiente.")

    url = f"/api/pia/chat/assets/{name}"
    return {
        "image_url": url,
        "path": str(dest),
        "markdown": f"![Captura de tela]({url})",
    }


def _get_storage():
    from Plugins.Connectors.object_storage.service import ObjectStorage

    return ObjectStorage()


def _is_sensitive_key(key: str) -> bool:
    clean = str(key or "").replace("\\", "/").strip()
    if ".." in clean.split("/"):
        return True
    return bool(_SENSITIVE_KEY_RE.search(clean))


def storage_list(
    *,
    account: str | None = None,
    bucket: str | None = None,
    prefix: str = "",
    query: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    store = _get_storage()
    accounts = store.accounts()
    if not accounts:
        return {"accounts": [], "buckets": [], "objects": []}
    acc = store.account(account)
    acc_id = acc["id"]
    if not bucket and not acc.get("bucket"):
        buckets = [
            b["Name"] for b in store.client(acc_id).list_buckets().get("Buckets", [])
        ]
        if not prefix and not query:
            return {"account": acc_id, "buckets": buckets, "objects": []}
        bucket = buckets[0] if buckets else None
    listing = store.list(
        acc_id, bucket, prefix=prefix or "", limit=min(max(1, int(limit)), 500)
    )
    items = [
        item
        for item in listing.get("objects", [])
        if not _is_sensitive_key(item.get("key", ""))
    ]
    if query:
        items = [
            item for item in items if _fuzzy_score(query, item.get("key", "")) >= 0.45
        ]
    return {
        "account": acc_id,
        "bucket": listing.get("bucket") or bucket or acc.get("bucket"),
        "prefixes": listing.get("prefixes", []),
        "objects": items,
    }


def storage_get(
    key: str,
    *,
    account: str | None = None,
    bucket: str | None = None,
    max_chars: int = 24000,
) -> dict[str, Any]:
    if _is_sensitive_key(key):
        raise PermissionError("Acesso negado a arquivo sensível no bucket.")
    store = _get_storage()
    clean_key = store.key(key)
    if _is_sensitive_key(clean_key):
        raise PermissionError("Acesso negado a arquivo sensível no bucket.")
    acc = store.account(account)
    bkt = store.bucket(acc["id"], bucket)
    client = store.client(acc["id"])
    resp = client.get_object(Bucket=bkt, Key=clean_key)
    raw = resp["Body"].read(512 * 1024 + 1)
    truncated = len(raw) > 512 * 1024
    raw = raw[: 512 * 1024]
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... conteúdo truncado ...]"
        truncated = True
    return {
        "bucket": bkt,
        "key": clean_key,
        "content": text,
        "truncated": truncated,
    }


def _session_sort_key(
    key_or_name: str, modified: str = ""
) -> tuple[int, int, str, str]:
    m_se = _SEASON_EP_RE.search(key_or_name)
    season = int(m_se.group(1)) if m_se else 0
    episode = int(m_se.group(2)) if m_se else 0
    m_dt = _DATE_RE.search(key_or_name)
    date_str = m_dt.group(1) if m_dt else ""
    return (season, episode, date_str, str(modified or ""))


def _collect_bucket_rpg_objects() -> list[dict[str, Any]]:
    try:
        store = _get_storage()
        accounts = store.accounts()
    except Exception:
        return []
    if not accounts:
        return []
    results: list[dict[str, Any]] = []
    for acc in accounts:
        acc_id = acc["id"]
        try:
            bkt = store.bucket(acc_id, acc.get("bucket"))
            client = store.client(acc_id)
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bkt, Prefix="campaigns/"):
                for obj in page.get("Contents", []):
                    key = obj.get("Key", "")
                    if not key or _is_sensitive_key(key):
                        continue
                    lm = obj.get("LastModified")
                    results.append(
                        {
                            "source": "bucket",
                            "account": acc_id,
                            "bucket": bkt,
                            "key": key,
                            "size": int(obj.get("Size") or 0),
                            "modified": lm.isoformat()
                            if hasattr(lm, "isoformat")
                            else str(lm or ""),
                        }
                    )
        except Exception:
            continue
    return results


def _collect_local_rpg_files() -> list[dict[str, Any]]:
    roots = [
        BASE_DIR / "cache" / "Apps" / "podcast_automation" / "transcription",
        BASE_DIR / "cache" / "Apps" / "podcast_automation" / "transcription-responses",
        user_path("podcast_automation"),
    ]
    results: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for file in root.rglob("*"):
            if not file.is_file():
                continue
            results.append(
                {
                    "source": "local",
                    "path": str(file),
                    "key": file.relative_to(root).as_posix(),
                    "size": file.stat().st_size,
                    "modified": str(file.stat().st_mtime),
                }
            )
    return results


def _read_entry_text(entry: dict[str, Any], max_chars: int) -> str:
    if entry.get("source") == "bucket":
        return storage_get(
            entry["key"],
            account=entry.get("account"),
            bucket=entry.get("bucket"),
            max_chars=max_chars,
        )["content"]
    p = Path(entry["path"])
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[... conteúdo truncado ...]"
    return text


def rpg_sessions(
    *,
    action: str = "latest",
    campaign: str = "",
    session: str = "",
    max_chars: int = 18000,
) -> dict[str, Any]:
    entries = _collect_bucket_rpg_objects() + _collect_local_rpg_files()
    if not entries:
        return {
            "campaigns": [],
            "sessions": [],
            "message": "Nenhuma sessão de RPG encontrada nos buckets ou cache local.",
        }

    # Group by campaign folder (e.g. campaigns/RPG 2025 Origem e Destructo/...)
    campaigns_map: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        key = item["key"]
        parts = [p for p in key.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "campaigns":
            camp_name = parts[1]
        elif len(parts) >= 2:
            camp_name = parts[0]
        else:
            camp_name = "geral"
        campaigns_map.setdefault(camp_name, []).append(item)

    matched_campaign = None
    if campaign:
        scored = sorted(
            ((_fuzzy_score(campaign, cname), cname) for cname in campaigns_map),
            reverse=True,
        )
        if scored and scored[0][0] >= 0.45:
            matched_campaign = scored[0][1]
    elif len(campaigns_map) == 1:
        matched_campaign = next(iter(campaigns_map))

    if action == "list":
        out = {}
        target_camps = (
            {matched_campaign: campaigns_map[matched_campaign]}
            if matched_campaign
            else campaigns_map
        )
        for cname, citems in target_camps.items():
            out[cname] = sorted(
                [it["key"] for it in citems],
                key=lambda k: _session_sort_key(k),
                reverse=True,
            )[:50]
        return {"matched_campaign": matched_campaign, "campaigns": out}

    pool = campaigns_map[matched_campaign] if matched_campaign else entries

    # Group files into sessions by stem (stripping .mp3 / .txt / .resumo.json)
    sessions_map: dict[str, dict[str, Any]] = {}
    for item in pool:
        fname = item["key"].rsplit("/", 1)[-1]
        if fname.lower() in ("rss.xml", "transcripts.html"):
            continue
        stem = re.sub(
            r"(\.resumo\.json|\.txt|\.mp3|\.wav|\.m4a|\.srt|\.vtt)$",
            "",
            fname,
            flags=re.IGNORECASE,
        )
        grp = sessions_map.setdefault(
            stem,
            {
                "session": stem,
                "sort_key": _session_sort_key(stem, item.get("modified", "")),
                "files": [],
            },
        )
        grp["files"].append(item)

    ordered = sorted(sessions_map.values(), key=lambda g: g["sort_key"], reverse=True)
    if not ordered:
        return {
            "matched_campaign": matched_campaign,
            "latest": None,
            "message": "Nenhuma sessão encontrada para a campanha.",
        }

    chosen = ordered[0]
    if session:
        best_s = max(
            ordered,
            key=lambda g: _fuzzy_score(session, g["session"]),
        )
        if _fuzzy_score(session, best_s["session"]) >= 0.45:
            chosen = best_s

    res: dict[str, Any] = {
        "matched_campaign": matched_campaign,
        "latest_session": chosen["session"],
        "files": [f["key"] for f in chosen["files"]],
        "total_sessions": len(ordered),
    }

    if action == "transcript":
        summary_text = ""
        transcript_text = ""
        for f in chosen["files"]:
            low = f["key"].lower()
            if low.endswith(".resumo.json"):
                summary_text = _read_entry_text(f, max_chars // 2)
            elif low.endswith((".txt", ".md", ".srt", ".vtt")):
                transcript_text = _read_entry_text(f, max_chars - len(summary_text))
        res["summary"] = summary_text
        res["transcript"] = transcript_text
    return res


def _mcp_http_rpc(
    url: str, method: str, params: dict[str, Any], token: str = "", req_id: int = 1
) -> dict[str, Any]:
    import requests

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(
        url,
        headers=headers,
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        timeout=300,
        allow_redirects=False,
    )
    resp.raise_for_status()
    return resp.json()


def _mcp_stdio_call(
    command: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    args = shlex.split(command, posix=False)
    if not args:
        raise RuntimeError("Comando do servidor Suno MCP inválido.")
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pia", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    ]
    payload = "\n".join(json.dumps(m) for m in msgs) + "\n"
    proc = subprocess.run(
        args,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(
            proc.stderr.strip() or "Falha ao executar servidor Suno MCP."
        )
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if parsed.get("id") == 2:
                if "error" in parsed:
                    raise RuntimeError(parsed["error"].get("message", "Erro MCP"))
                return parsed.get("result") or {}
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Servidor Suno MCP não retornou resposta JSON-RPC válida.")


def call_suno_mcp(
    prompt: str,
    *,
    lyrics: str = "",
    duration: int = 30,
    suno_url: str = "",
    suno_cmd: str = "",
    suno_token: str = "",
) -> dict[str, Any]:
    arguments = {"prompt": prompt, "lyrics": lyrics, "duration": duration}
    if suno_url:
        # Try JSON-RPC MCP tools/call first; fall back to plain REST JSON if endpoint returns non-JSON-RPC.
        try:
            rpc_res = _mcp_http_rpc(
                suno_url,
                "tools/call",
                {"name": "generate_music", "arguments": arguments},
                token=suno_token,
                req_id=2,
            )
            if isinstance(rpc_res, dict) and "result" in rpc_res:
                return rpc_res["result"]
            if isinstance(rpc_res, dict) and (
                "audio_base64" in rpc_res or "audio_url" in rpc_res
            ):
                return rpc_res
        except Exception:
            pass
        import requests

        headers = {"Content-Type": "application/json"}
        if suno_token:
            headers["Authorization"] = f"Bearer {suno_token}"
        resp = requests.post(
            suno_url,
            headers=headers,
            json=arguments,
            timeout=300,
            allow_redirects=False,
        )
        resp.raise_for_status()
        return resp.json()
    if suno_cmd:
        return _mcp_stdio_call(suno_cmd, "generate_music", arguments)
    raise RuntimeError(
        "Suno (MCP) não configurado: informe a URL ou comando do servidor MCP do Suno."
    )
