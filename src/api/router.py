"""Declarative table-driven HTTP router with path parameters and auth metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import unquote

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _compile_pattern(pattern: str) -> tuple[re.Pattern[str], list[str]]:
    params: list[str] = []
    parts: list[str] = ["^"]
    pos = 0
    for m in _PARAM_RE.finditer(pattern):
        parts.append(re.escape(pattern[pos : m.start()]))
        name = m.group(1)
        params.append(name)
        parts.append(f"(?P<{name}>[^/]+)")
        pos = m.end()
    parts.append(re.escape(pattern[pos:]))
    parts.append("$")
    return re.compile("".join(parts)), params


@dataclass
class RouteEntry:
    method: str
    pattern: str
    handler: Callable[..., Any]
    auth_required: str = "session"
    description: str = ""
    _regex: re.Pattern[str] = field(init=False, repr=False)
    _params: list[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        self._regex, self._params = _compile_pattern(self.pattern)

    def match(self, method: str, path: str) -> dict[str, str] | None:
        if method.upper() != self.method:
            return None
        m = self._regex.match(path)
        if not m:
            return None
        return {k: unquote(v) for k, v in m.groupdict().items()}


class Router:
    """Declarative (method, pattern) -> handler router."""

    def __init__(self) -> None:
        self._routes: list[RouteEntry] = []

    def add(
        self,
        method: str,
        pattern: str,
        handler: Callable[..., Any],
        *,
        auth_required: str = "session",
        description: str = "",
    ) -> RouteEntry:
        entry = RouteEntry(
            method=method,
            pattern=pattern,
            handler=handler,
            auth_required=auth_required,
            description=description,
        )
        self._routes.append(entry)
        return entry

    def match(self, method: str, path: str) -> tuple[RouteEntry, dict[str, str]] | None:
        for entry in self._routes:
            params = entry.match(method, path)
            if params is not None:
                return entry, params
        return None

    def dispatch(
        self,
        method: str,
        path: str,
        context: Any,
        data: dict[str, Any] | None = None,
        query: dict[str, list[str]] | None = None,
    ) -> tuple[bool, Any]:
        found = self.match(method, path)
        if found is None:
            return False, None
        entry, params = found
        return True, entry.handler(
            context,
            data if data is not None else {},
            query if query is not None else {},
            **params,
        )

    def list_routes(self) -> list[dict[str, str]]:
        return [
            {
                "method": r.method,
                "pattern": r.pattern,
                "auth_required": r.auth_required,
                "description": r.description,
            }
            for r in self._routes
        ]


_workspace_router: Router | None = None


def get_workspace_router() -> Router:
    global _workspace_router
    if _workspace_router is None:
        from .routes import register_all

        router = Router()
        register_all(router)
        _workspace_router = router
    return _workspace_router
