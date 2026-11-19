"""T9: ajustes de contrato aprovados pelo TechLead, contra o fake da pia-server.

1. Tentativa de conexão expirada: 200 {state: "expired"}; 400
   suno_connect_not_found só para tentativa inexistente.
2. Nenhum code fora do contrato vaza da API local por uma recusa genérica da
   PIA Server: o fallback interno pia_server_error vira pia_server_unreachable;
   um id de conta inválido enviado pelo cliente é suno_account_not_found.
3. /music/select não recebe mais a conta Suno: um body antigo com
   suno_account_id é aceito, mas o campo é ignorado (nada é salvo).

Sem chamada real ao Suno nem à pia-server.
"""

from __future__ import annotations

import pytest

from Plugins.Apps.music import history, remote_suno, web_api
from Plugins.Connectors.pia_server import remote as device
from tests._suno_remote_support import remote_env  # noqa: F401  (fixture)
from tests.fixtures.fake_pia_server_suno import account


def _route(env, method, path, data=None):
    return web_api.route(method, path, data or {}, {}, env.context)


def _refused_without_code(*_args, **_kwargs):
    # What device_call raises for a 4xx answer without a valid ``code``.
    raise device.DeviceApiError(
        "pia_server_error", "A PIA Server recusou o pedido.", 400
    )


# --- 1. connect expirado ------------------------------------------------------
def test_expired_attempt_is_200_state_expired(remote):
    started = _route(remote, "POST", "/music/suno/connect")
    remote.fake.attempt_outcome = {"state": "expired"}
    path = f"/music/suno/connect/{started['attempt_id']}"
    assert _route(remote, "GET", path) == {"state": "expired"}


def test_missing_attempt_is_still_suno_connect_not_found(remote):
    with pytest.raises(ValueError) as err:
        _route(remote, "GET", "/music/suno/connect/nao-existe")
    assert err.value.code == "suno_connect_not_found"


# --- 2. codes fora do contrato ------------------------------------------------
def test_generic_server_refusal_is_pia_server_unreachable(remote, monkeypatch):
    acc = remote.fake.accounts[0]
    monkeypatch.setattr(device, "device_call", _refused_without_code)
    for method, path, data in (
        ("POST", "/music/suno/disconnect", {"account_id": acc["id"]}),
        ("POST", f"/music/suno/accounts/{acc['id']}/rename", {"label": "Nova"}),
        ("POST", "/music/suno/connect", {}),
    ):
        with pytest.raises(ValueError) as err:
            _route(remote, method, path, data)
        assert err.value.code == "pia_server_unreachable", path
        assert str(err.value) == device.UNREACHABLE_MESSAGE


def test_history_delete_generic_refusal_is_pia_server_unreachable(remote, monkeypatch):
    history.record("item-t9", source="local", provider="local", count=1)
    history.update("item-t9", generation_id="gen_t9")
    monkeypatch.setattr(device, "device_call", _refused_without_code)
    with pytest.raises(ValueError) as err:
        _route(remote, "DELETE", "/music/history/item-t9")
    assert err.value.code == "pia_server_unreachable"


def test_invalid_server_answer_is_pia_server_unreachable(remote, monkeypatch):
    monkeypatch.setattr(
        device,
        "device_call",
        lambda *_a, **_k: {"url": "http://inseguro.example", "attempt_id": "a1"},
    )
    with pytest.raises(ValueError) as err:
        _route(remote, "POST", "/music/suno/connect")
    assert err.value.code == "pia_server_unreachable"


@pytest.mark.parametrize(
    "path,data",
    [
        ("/music/suno/disconnect", {"account_id": "conta inválida!"}),
        ("/music/suno/disconnect", {}),
        ("/music/suno/connect", {"replace_account_id": "../outra"}),
    ],
)
def test_invalid_account_id_from_client_is_suno_account_not_found(remote, path, data):
    with pytest.raises(ValueError) as err:
        _route(remote, "POST", path, data)
    assert err.value.code == "suno_account_not_found"


def test_remote_music_error_never_carries_the_internal_code():
    err = remote_suno.RemoteMusicError("pia_server_error", "detalhe interno")
    assert err.code == "pia_server_unreachable"
    assert str(err) == device.UNREACHABLE_MESSAGE
    assert history.HistoryError("pia_server_error", "x").code == (
        "pia_server_unreachable"
    )


# --- 3. /music/select sem conta Suno ---------------------------------------------
def test_select_ignores_old_suno_account_id_and_saves_nothing(remote):
    first, second = account(label="a@suno"), account(label="b@suno")
    remote.fake.accounts = [first, second]
    catalog = _route(
        remote,
        "POST",
        "/music/select",
        {"provider": "suno_mcp", "suno_account_id": first["id"]},
    )
    assert catalog["selection"]["provider"] == "suno_mcp"
    saved = dict(remote.profile.values("Apps/music"))
    assert "MUSIC_SUNO_ACCOUNT_ID" not in saved
    suno = next(p for p in catalog["providers"] if p["id"] == "suno_mcp")
    assert suno["selected_account_id"] is None
    with pytest.raises(ValueError) as err:
        web_api.handle(
            "generate",
            {"prompt": "piano", "provider": "suno_mcp", "duration": 30},
            remote.context,
        )
    assert err.value.code == "suno_account_required"


def test_select_with_invalid_old_suno_account_id_is_not_an_error(remote):
    catalog = _route(
        remote,
        "POST",
        "/music/select",
        {"provider": "local", "suno_account_id": "conta inválida!"},
    )
    assert catalog["selection"]["provider"] == "local"


def test_select_provider_has_no_suno_account_parameter():
    from Plugins.Apps.music import service

    with pytest.raises(TypeError):
        service.select_provider(provider="local", suno_account_id="acc")
