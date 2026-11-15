"""RPG session tools owned by the podcast_automation plugin."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from Plugins.Connectors.object_storage.tools import (
    _fuzzy_score,
    _get_storage,
    _is_sensitive_key,
    storage_get,
)
from src.config_paths import BASE_DIR
from src.user_paths import user_path

_SEASON_EP_RE = re.compile(r"S(\d{1,3})E(\d{1,4})", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _session_sort_key(
    key_or_name: str, modified: str = ""
) -> tuple[int, int, str, str]:
    m_se = _SEASON_EP_RE.search(key_or_name)
    season = int(m_se.group(1)) if m_se else 0
    episode = int(m_se.group(2)) if m_se else 0
    m_dt = _DATE_RE.search(key_or_name)
    date_str = m_dt.group(1) if m_dt else ""
    return (season, episode, date_str, str(modified or ""))


def _collect_bucket_rpg_objects(storage_factory: Any = None) -> list[dict[str, Any]]:
    try:
        store = storage_factory() if storage_factory else _get_storage()
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


def _collect_local_rpg_files(user_path_fn: Any = None) -> list[dict[str, Any]]:
    up = user_path_fn or user_path
    roots = [
        BASE_DIR / "cache" / "Apps" / "podcast_automation" / "transcription",
        BASE_DIR / "cache" / "Apps" / "podcast_automation" / "transcription-responses",
        up("podcast_automation"),
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


def _read_entry_text(
    entry: dict[str, Any], max_chars: int, storage_factory: Any = None
) -> str:
    if entry.get("source") == "bucket":
        return storage_get(
            entry["key"],
            account=entry.get("account"),
            bucket=entry.get("bucket"),
            max_chars=max_chars,
            storage_factory=storage_factory,
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
    storage_factory: Any = None,
    user_path_fn: Any = None,
) -> dict[str, Any]:
    entries = _collect_bucket_rpg_objects(storage_factory) + _collect_local_rpg_files(
        user_path_fn
    )
    if not entries:
        return {
            "campaigns": [],
            "sessions": [],
            "message": "Nenhuma sessão de RPG encontrada nos buckets ou cache local.",
        }

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
                summary_text = _read_entry_text(f, max_chars // 2, storage_factory)
            elif low.endswith((".txt", ".md", ".srt", ".vtt")):
                transcript_text = _read_entry_text(
                    f, max_chars - len(summary_text), storage_factory
                )
        res["summary"] = summary_text
        res["transcript"] = transcript_text
    return res


def register_tools(ctx: Any) -> None:
    ctx.tools.register("pia_rpg_sessions", rpg_sessions)
