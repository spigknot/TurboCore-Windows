from unittest.mock import patch

from turbocore import tray


def _state(cores=18, logical=36, remember=False, selected=None, boot=False):
    return {"physical": cores, "logical": logical,
            "options": [1, 2, 4, 6] if cores == 6 else [1, 2, 4, 6, 8, 10, 12, 14, 16, 18],
            "selected": selected, "remember": remember, "boot": boot}


def test_click_core_aplica_e_marca():
    st = _state(selected=None)
    with patch.object(tray.power, "apply_selection", return_value=(3, 56)) as ap, \
            patch.object(tray.config, "save_config") as sv:
        tray.on_pick_core(st, 10)
        ap.assert_called_once_with(chosen_cores=10, physical_cores=18, logical_count=36)
    assert st["selected"] == 10
    sv.assert_called_once()


def test_toggle_remember_inverte_e_salva():
    st = _state(remember=False, selected=10)
    with patch.object(tray.config, "save_config"):
        tray.on_toggle_remember(st)
    assert st["remember"] is True


def test_toggle_boot_chama_winreg():
    st = _state(boot=False)
    with patch.object(tray.autostart, "set_enabled") as se, \
            patch.object(tray.autostart, "is_enabled", return_value=True):
        tray.on_toggle_boot(st)
        se.assert_called_once_with(True)
    assert st["boot"] is True


def test_labels_plural():
    assert tray.core_label(1) == "1 Core"
    assert tray.core_label(10) == "10 Cores"


class _FakeIcon:
    def __init__(self):
        self.notes = []
        self.stopped = False

    def notify(self, message, title=None):
        self.notes.append(message)

    def stop(self):
        self.stopped = True


def test_check_update_sem_novidade_avisa():
    st = _state()
    st["icon"] = _FakeIcon()
    with patch.object(tray.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_001"}), \
            patch.object(tray.updater_client, "install_dir", return_value="/x"), \
            patch.object(tray.updater_client, "check_for_update",
                         return_value={"local": "20260907_001", "remote": "20260907_001", "update": False}), \
            patch.object(tray.updater_client, "launch_updater") as launch:
        tray._check_update_worker(st)
        launch.assert_not_called()
    assert any("atualizado" in n for n in st["icon"].notes)
    assert st["icon"].stopped is False


def test_check_update_com_novidade_dispara_e_para():
    st = _state()
    st["icon"] = _FakeIcon()
    with patch.object(tray.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_002"}), \
            patch.object(tray.updater_client, "install_dir", return_value="/x"), \
            patch.object(tray.updater_client, "check_for_update",
                         return_value={"local": "20260907_001", "remote": "20260907_002", "update": True}), \
            patch.object(tray.updater_client, "launch_updater", return_value=True) as launch:
        tray._check_update_worker(st)
        launch.assert_called_once_with("/x")
    assert st["icon"].stopped is True


def test_check_update_falha_de_rede_avisa():
    st = _state()
    st["icon"] = _FakeIcon()
    with patch.object(tray.updater_client, "fetch_sync_manifest", side_effect=Exception("dns")):
        tray._check_update_worker(st)
    assert any("Não foi possível verificar" in n for n in st["icon"].notes)


def test_open_panel_sinaliza_evento():
    import threading
    st = _state()
    st["panel_request"] = threading.Event()
    tray.on_open_panel(st)
    assert st["panel_request"].is_set()


def test_quit_para_icone_e_fecha_painel():
    st = _state()
    st["icon"] = _FakeIcon()
    closed = []
    st["panel"] = type("P", (), {"destroy": lambda self: closed.append(1),
                                 "winfo_exists": lambda self: True})()
    tray.on_quit(st, st["icon"])
    assert st["icon"].stopped is True
    assert closed == [1]
    assert st["panel"] is None
