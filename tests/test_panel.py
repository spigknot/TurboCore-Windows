"""Painel TurboCore: helpers puros + worker de update (sem Tk nos testes)."""
from unittest.mock import patch

from turbocore import panel


def test_verde_igual_sig():
    assert panel.UPDATE_GREEN == "#16833a"
    assert panel.UPDATE_GREEN_ACTIVE == "#116b30"


def test_sobre_traz_versao_atual():
    from turbocore import __version__
    title, subtitle, version_line = panel.sobre_texts()
    assert (title, subtitle) == ("Delegacia de Taguaí", "Setor de Investigações Gerais")
    assert version_line == f"Versão: {__version__}"


def test_sobre_wallpaper_existe():
    assert panel.sobre_artwork() is not None
    assert panel.sobre_artwork().name == "appwin.png"


def test_label_cores_mostra_selecionado():
    assert panel.cores_label(8, 18) == "Cores: 8"
    assert panel.cores_label(1, 6) == "Cores: 1"


def test_label_cores_sem_selecao_mostra_total():
    assert panel.cores_label(None, 18) == "Cores: 18"


def test_manual_check_trava_concorrencia():
    import threading
    checker = panel.ManualCheck()
    calls = []
    started = threading.Event()

    def slow_fetcher():
        started.set()
        import time
        time.sleep(0.3)
        return {"version": "20260907_009"}

    with patch.object(panel.updater_client, "check_for_update",
                      return_value={"update": True, "remote": "20260907_009"}):
        assert checker.start("/x", lambda k, v: calls.append((k, v)), fetcher=slow_fetcher) is True
        assert started.wait(timeout=5)
        assert checker.start("/x", lambda k, v: calls.append((k, v)), fetcher=slow_fetcher) is False
        deadline = __import__("time").monotonic() + 5
        while checker.busy and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert calls == [("updated", "20260907_009")]
    assert checker.busy is False


def test_manual_check_sem_novidade_e_erro():
    out = []
    with patch.object(panel.updater_client, "check_for_update",
                      return_value={"update": False}):
        panel.ManualCheck().start("/x", lambda k, v: out.append((k, v)),
                                  fetcher=lambda: {"version": "20260907_001"})
        deadline = __import__("time").monotonic() + 5
        while not out and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert out == [("uptodate", None)]
    out.clear()
    def boom():
        raise Exception("dns")
    checker = panel.ManualCheck()
    checker.start("/x", lambda k, v: out.append((k, v)), fetcher=boom)
    deadline = __import__("time").monotonic() + 5
    while not out and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    assert out[0][0] == "error"


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


def test_update_click_sem_updater_mantem_app():
    destroyed, stopped, errors = [], [], []
    with patch.object(panel.updater_client, "launch_updater", return_value=False):
        ok = panel.handle_update_click({}, destroyed.append, lambda: stopped.append(1), errors.append)
    assert ok is False
    assert destroyed == [] and stopped == []
    assert errors and "não encontrado" in errors[0]


def test_update_click_ok_libera_saida():
    destroyed, stopped = [], []
    with patch.object(panel.updater_client, "launch_updater", return_value=True):
        ok = panel.handle_update_click(
            {}, lambda: destroyed.append(1), lambda: stopped.append(1), lambda m: None)
    assert ok is True
    assert destroyed == [1]
    assert stopped == [1]


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
