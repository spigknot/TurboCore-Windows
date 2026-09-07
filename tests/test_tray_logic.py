from unittest.mock import patch

from turbocore import tray


def _state(cores=18, remember=False, selected=None, boot=False):
    return {"physical": cores,
            "options": [1, 2, 4, 6] if cores == 6 else [1, 2, 4, 6, 8, 10, 12, 14, 16, 18],
            "selected": selected, "remember": remember, "boot": boot}


def test_click_core_aplica_e_marca():
    st = _state(selected=None)
    with patch.object(tray.power, "apply_core_limit", return_value=56) as ap, \
            patch.object(tray.config, "save_config") as sv:
        tray.on_pick_core(st, 10)
        ap.assert_called_once_with(chosen_cores=10, physical_cores=18)
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
