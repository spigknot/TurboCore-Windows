from unittest.mock import patch

from turbocore import main


def test_startup_com_lembrar_aplica_salvo():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "apply_selection", return_value=(3, 56)) as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray") as run, \
            patch.object(main.panel_mod, "start_auto_check"):
        main.main()
        ap.assert_called_once_with(chosen_cores=10, physical_cores=18, logical_count=36)
        rel.assert_not_called()
        run.assert_called_once()


def test_startup_sem_lembrar_libera_100():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": False, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "apply_selection") as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"):
        main.main()
        rel.assert_called_once()
        ap.assert_not_called()


def test_startup_lembrar_sem_valor_libera():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": None}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"):
        main.main()
        rel.assert_called_once()


def test_event_loop_abre_painel_e_encerra():
    import threading
    state = {"panel_request": threading.Event(), "stopped": threading.Event()}
    opened = []
    done = threading.Event()
    state["panel_request"].set()

    def panel_fn():
        opened.append(1)
        done.set()

    def icon_fn():
        done.wait(timeout=5)

    main.run_event_loop(state, icon_fn=icon_fn, panel_fn=panel_fn)
    assert opened == [1]
    assert state["stopped"].is_set()


def test_event_loop_sem_pedido_so_encerra():
    import threading
    state = {"panel_request": threading.Event(), "stopped": threading.Event()}
    opened = []
    state["stopped"].set()
    main.run_event_loop(state, icon_fn=lambda: None, panel_fn=lambda: opened.append(1))
    assert opened == []
