import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.router import Router, get_workspace_router  # noqa: E402
from src.core.secrets.vault import MemoryVault, UnifiedVault  # noqa: E402
from src.integrations.plugins.context import PluginContext  # noqa: E402
from src.integrations.plugins.host import PluginHost  # noqa: E402


def _plugins_imports(file_path: Path) -> list[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "Plugins" or alias.name.startswith("Plugins."):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "Plugins" or mod.startswith("Plugins."):
                found.append(mod)
    return found


def test_core_layers_have_no_hardcoded_plugin_imports():
    targets: list[Path] = [
        ROOT / "src" / "api" / "router.py",
        ROOT / "src" / "integrations" / "plugins" / "context.py",
    ]
    for folder in ("core", "voice", "ai"):
        targets.extend((ROOT / "src" / folder).rglob("*.py"))

    violations: dict[str, list[str]] = {}
    for path in targets:
        hits = _plugins_imports(path)
        if hits:
            violations[str(path.relative_to(ROOT))] = hits
    assert violations == {}, f"Imports proibidos de Plugins.*: {violations}"


def test_router_table_matching_params_and_listing():
    router = Router()
    router.add(
        "GET",
        "/items/{item_id}/sub/{sub_id}",
        lambda ctx, data, query, item_id, sub_id: {
            "item": item_id,
            "sub": sub_id,
            "ctx": ctx,
        },
        auth_required="session",
        description="Get nested item",
    )
    routes = router.list_routes()
    assert len(routes) == 1
    assert routes[0]["method"] == "GET"
    assert routes[0]["pattern"] == "/items/{item_id}/sub/{sub_id}"

    matched, res = router.dispatch("GET", "/items/abc%201/sub/42", "ctx-ok")
    assert matched is True
    assert res == {"item": "abc 1", "sub": "42", "ctx": "ctx-ok"}

    not_matched, _ = router.dispatch("POST", "/items/abc/sub/42", "ctx-ok")
    assert not_matched is False

    ws_router = get_workspace_router()
    patterns = {(r["method"], r["pattern"]) for r in ws_router.list_routes()}
    assert ("GET", "/mcp/servers") in patterns
    assert ("GET", "/plugins") in patterns
    assert ("GET", "/skills") in patterns
    assert ("GET", "/tts/providers") in patterns
    assert ("GET", "/chat/models") in patterns


def test_plugin_context_and_host_load_plugin_tools():
    vault = MemoryVault()
    ctx = PluginContext("music", "app", vault=vault)
    ctx.vault.set("suno_key", "secret-123")
    assert ctx.vault.get("suno_key") == "secret-123"

    called = []
    ctx.tools.register("ping", lambda x: called.append(x) or f"pong:{x}")
    assert ctx.tools.get("ping")("ok") == "pong:ok"
    assert called == ["ok"]

    host = PluginHost(ROOT / "Plugins")
    manifests = host.manifests()
    for pid in ("music", "podcast_automation", "screenshots", "object_storage"):
        assert pid in manifests
        mod = host.load_tools_module(pid)
        assert mod is not None

    assert host.get_context("music").tools.get("pia_music_suno_mcp") is not None
    assert (
        host.get_context("podcast_automation").tools.get("pia_rpg_sessions") is not None
    )
    assert host.get_context("screenshots").tools.get("pia_screenshot") is not None
    assert host.get_context("object_storage").tools.get("pia_storage_list") is not None
    assert host.get_context("object_storage").tools.get("pia_storage_get") is not None


def test_unified_vault_roundtrip():
    vault = UnifiedVault(backend=MemoryVault())
    vault.set("k1", {"token": "abc"})
    assert vault.get("k1") == {"token": "abc"}
    vault.delete("k1")
    assert vault.get("k1") is None


def test_bot_chat_and_plugin_routes_no_404(tmp_path):
    from types import SimpleNamespace
    from src.desktop_backend import DesktopBackend
    from src.pia.service import WorkspaceService
    from src.workspace_store import WorkspaceStore

    http_text = (ROOT / "src" / "pia" / "http.py").read_text(encoding="utf-8")
    assert 'subpath.startswith("/plugins/")' in http_text
    assert 'subpath.startswith("/apps/")' in http_text
    assert 'subpath.startswith("/bots/")' in http_text
    assert '"/api/pia/bots/chat"' in http_text

    store = WorkspaceStore(tmp_path / "ws.db")
    backend = DesktopBackend(lambda *a, **kw: None)
    backend.store = store
    captured = {}

    class _FakeAgent:
        def complete(self, messages, model=None, tools=None):
            captured["system"] = messages[0]["content"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Oi, sou a Secretária!")
                    )
                ]
            )

        def complete_stream(self, messages, model=None):
            captured["system"] = messages[0]["content"]
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Oi, sou a Secretária!")
                    )
                ]
            )

        def last_meta(self):
            return {"model": "fake-m", "provider": "fake-p"}

    backend.agent = _FakeAgent()
    service = WorkspaceService(backend=backend)

    # Secretária config and plugin routes return valid dicts
    sec = service._dispatch("GET", "/bots/secretaria", {}, {})
    assert "config" in sec
    plug = service._dispatch("GET", "/plugins/secretaria", {}, {})
    assert plug["plugin"]["id"] == "secretaria"

    # Direct bot chat via /bots/chat
    res = service._dispatch(
        "POST",
        "/bots/chat",
        {"bot_id": "secretaria", "text": "Qual minha agenda hoje?"},
        {},
    )
    assert res["bot_id"] == "secretaria"
    assert res["chat"]
    assert res["job"]
    import time

    for _ in range(150):
        if service.jobs[res["job"]].status != "running":
            break
        time.sleep(0.02)
    assert service.jobs[res["job"]].status == "done"
    assert "Secretária" in captured["system"]
