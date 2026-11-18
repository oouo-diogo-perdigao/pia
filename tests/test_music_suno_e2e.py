"""E2e T8 do Suno contra o mock MCP local: removido na T8 do v2 (RN18).

A PIA local não fala mais com o MCP do Suno. Os cenários e2e serão reescritos
na T6 contra o fake da pia-server (tests/fixtures/fake_pia_server_suno.py).
Fica só o probe de superfície usado pelo DevFullstack.
"""

from __future__ import annotations

from tests._suno_e2e_support import assert_t3_t4_surface


def test_t3_t4_behavior_probes():
    assert_t3_t4_surface()
