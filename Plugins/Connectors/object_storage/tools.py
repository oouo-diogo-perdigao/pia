"""Object Storage bucket tools owned by the object_storage connector."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

_SENSITIVE_KEY_RE = re.compile(
    r"(^|/)(secrets?|credentials?|\.env|.*service[-_]?account.*\.json|.*\.pem|.*\.key)$",
    re.IGNORECASE,
)


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
    storage_factory: Any = None,
) -> dict[str, Any]:
    store = storage_factory() if storage_factory else _get_storage()
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
    storage_factory: Any = None,
) -> dict[str, Any]:
    if _is_sensitive_key(key):
        raise PermissionError("Acesso negado a arquivo sensível no bucket.")
    store = storage_factory() if storage_factory else _get_storage()
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


def register_tools(ctx: Any) -> None:
    ctx.tools.register("pia_storage_list", storage_list)
    ctx.tools.register("pia_storage_get", storage_get)
