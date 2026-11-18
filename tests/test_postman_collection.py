"""Offline catalogue checks: method/auth boundaries and absence of phantom routes."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pia_postman_generator", ROOT / "postman/generate_collection.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_catalogue_matches_generated_artifact_and_real_dispatch():
    collection = generator.build()
    assert collection == json.loads(generator.OUT.read_text(encoding="utf-8"))
    requests = [
        item["request"] for folder in collection["item"] for item in folder["item"]
    ]
    routes = {
        (r["method"], r["url"].split("?")[0].removeprefix("{{base_url}}"))
        for r in requests
    }
    assert ("POST", "/protocols/mcp") in routes
    assert ("POST", "/action/camera") in routes
    assert ("GET", "/v1/audio/transcriptions/progress/{{transcription_id}}") in routes
    assert ("POST", "/api/pia/apps/podcast_automation/start") in routes
    assert ("POST", "/api/pia/apps/podcast_automation/google_account") not in routes
    assert not any(
        "/protocols/acp" in path or "/protocols/a2a" in path for _, path in routes
    )
    for request in requests:
        if "/api/pia/" in request["url"]:
            assert request["auth"]["type"] == "noauth"
            assert {"key": "Origin", "value": "{{base_url}}"} in request["header"]
    formats = set()
    for request in requests:
        if request["url"] == "{{base_url}}/v1/audio/transcriptions":
            assert not any(h["key"] == "Content-Type" for h in request["header"])
            formats.add(
                next(
                    f["value"]
                    for f in request["body"]["formdata"]
                    if f["key"] == "response_format"
                )
            )
    assert formats == {"json", "text", "verbose_json", "srt", "vtt"}
    assert (
        next(v for v in collection["variable"] if v["key"] == "api_key")["value"] == ""
    )
    # /music/select e /music/providers sem o modo Suno local/manual (T8, RN18)
    # e sem a conta Suno, que vai só no generate (T9).
    select = next(r for r in requests if r["url"].endswith("/api/pia/music/select"))
    assert json.loads(select["body"]["raw"]) == {
        "provider": "suno_mcp",
        "gemini_model": "lyria-3.5",
    }
    providers = next(
        r for r in requests if r["url"].endswith("/api/pia/music/providers")
    )
    for key in ("credential_state", "reason", "legacy_credentials"):
        assert key in providers.get("description", "")
    app_select = next(
        r for r in requests if r["url"].endswith("/api/pia/apps/music/select")
    )
    assert json.loads(app_select["body"]["raw"]) == json.loads(select["body"]["raw"])
    assert not any("/suno/oauth" in path or "suno-oauth" in path for _, path in routes)
    assert ("GET", "/api/pia/music/suno/legacy-credentials") in routes
    remove = next(
        r
        for r in requests
        if r["url"].endswith("/api/pia/music/suno/legacy-credentials/remove")
    )
    assert remove["method"] == "POST"
    assert json.loads(remove["body"]["raw"]) == {"confirm": True}
    assert "confirmation_required" in remove["description"]
    assert ("POST", "/api/pia/music/suno/legacy-credentials/dismiss") in routes

    app_generate = next(
        item
        for folder in collection["item"]
        for item in folder["item"]
        if item["request"]["url"].endswith("/api/pia/apps/music/generate")
    )
    desc = app_generate["request"].get("description", "")
    assert "suno_not_connected" in desc
    assert "suno_credential_expired" in desc
    assert "`code`" in desc or "code" in desc
    examples = app_generate["response"]
    assert examples and examples[0]["code"] == 400
    example_body = json.loads(examples[0]["body"])
    assert example_body == {
        "error": "Conecte o Suno em Configurações → Música.",
        "code": "suno_not_connected",
    }
    # T6/T9: rotas locais do Suno pela PIA Server e do histórico.
    for route in (
        ("GET", "/api/pia/music/suno/status"),
        ("POST", "/api/pia/music/suno/connect"),
        ("GET", "/api/pia/music/suno/connect/{{suno_attempt_id}}"),
        ("POST", "/api/pia/music/suno/accounts/{{suno_account_id}}/rename"),
        ("POST", "/api/pia/music/suno/disconnect"),
        ("GET", "/api/pia/music/history"),
        ("DELETE", "/api/pia/music/history/{{history_id}}"),
        (
            "POST",
            "/api/pia/music/history/{{history_id}}/tracks/{{track_n}}/redownload",
        ),
    ):
        assert route in routes, route
    by_url = {
        (item["request"]["method"], item["request"]["url"]): item
        for folder in collection["item"]
        for item in folder["item"]
    }
    music_items = [
        item
        for (method, url), item in by_url.items()
        if "/api/pia/music/suno/" in url or "/api/pia/music/history" in url
    ]
    for item in music_items:
        assert item["response"], item["name"]
        for example in item["response"]:
            assert example["code"] in (200, 400)
            body = json.loads(example["body"])
            if example["code"] == 400:
                assert set(body) == {"error", "code"}
                assert body["code"] != "pia_server_error"
    connect = by_url[("POST", "{{base_url}}/api/pia/music/suno/connect")]
    assert json.loads(connect["request"]["body"]["raw"]) == {
        "replace_account_id": "{{suno_account_id}}"
    }
    assert set(json.loads(connect["response"][0]["body"])) == {
        "auth_url",
        "attempt_id",
        "expires_in",
    }
    attempt = by_url[
        ("GET", "{{base_url}}/api/pia/music/suno/connect/{{suno_attempt_id}}")
    ]
    attempt_bodies = [json.loads(e["body"]) for e in attempt["response"]]
    assert {"state": "expired"} in attempt_bodies
    rename = by_url[
        (
            "POST",
            "{{base_url}}/api/pia/music/suno/accounts/{{suno_account_id}}/rename",
        )
    ]
    assert json.loads(rename["request"]["body"]["raw"]) == {"label": "Conta principal"}
    assert "invalid_label" in rename["request"]["description"]
    history = by_url[("GET", "{{base_url}}/api/pia/music/history?cursor=&limit=100")]
    assert "availability" in history["request"]["description"]
    suno_generate = next(
        item
        for folder in collection["item"]
        for item in folder["item"]
        if item["name"].endswith("Suno (gasta créditos)")
    )
    body = json.loads(suno_generate["request"]["body"]["raw"])
    assert body["provider"] == "suno_mcp" and "suno_account_id" in body
    assert "GASTA CRÉDITOS" in suno_generate["request"]["description"]
    for url in (
        "{{base_url}}/api/pia/music/suno/legacy-credentials",
        "{{base_url}}/api/pia/music/suno/legacy-credentials/remove",
    ):
        method = "GET" if url.endswith("legacy-credentials") else "POST"
        assert by_url[(method, url)]["response"], url

    v1_generate = next(
        item
        for folder in collection["item"]
        for item in folder["item"]
        if item["request"]["url"].endswith("/v1/music/generations")
    )
    assert "suno_not_connected" in v1_generate["request"].get("description", "")
    assert json.loads(v1_generate["response"][0]["body"])["code"] == (
        "suno_not_connected"
    )
