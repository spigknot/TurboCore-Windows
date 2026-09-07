"""Painel TurboCore: helpers puros + worker de update (sem Tk nos testes)."""
from unittest.mock import patch

from turbocore import panel


def test_format_status_sem_limite():
    assert panel.format_status(None, 18) == "Sem limite (todos os núcleos liberados)"


def test_format_status_com_limite():
    assert panel.format_status(10, 18, 56) == "Limite: 10 Cores (56%) — mín 1 thread"


def test_format_status_singular():
    assert panel.format_status(1, 18, 6) == "Limite: 1 Core (6%) — mín 1 thread"


def test_verde_igual_sig():
    assert panel.UPDATE_GREEN == "#16833a"
    assert panel.UPDATE_GREEN_ACTIVE == "#116b30"


def test_poll_update_encontra_nova():
    with patch.object(panel.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_002"}), \
            patch.object(panel.updater_client, "check_for_update",
                         return_value={"update": True, "remote": "20260907_002"}):
        assert panel.poll_update_once("/x") == "20260907_002"


def test_poll_update_sem_novidade():
    with patch.object(panel.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_001"}), \
            patch.object(panel.updater_client, "check_for_update",
                         return_value={"update": False}):
        assert panel.poll_update_once("/x") is None


def test_poll_update_falha_rede():
    with patch.object(panel.updater_client, "fetch_sync_manifest", side_effect=Exception("dns")):
        assert panel.poll_update_once("/x") is None


def test_start_auto_check_guarda_pendente_e_avisa():
    import threading
    state = {}
    avisos = []
    with patch.object(panel, "poll_update_once", return_value="20260907_009"):
        panel.start_auto_check(state, notify=avisos.append)
        deadline = __import__("time").monotonic() + 5
        while "pending_update" not in state and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert state["pending_update"] == "20260907_009"
    assert avisos == ["20260907_009"]
