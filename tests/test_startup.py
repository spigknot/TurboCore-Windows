from unittest.mock import patch

from turbocore import main


def _wait_called(mock, timeout=10.0):
    """O power inicial roda em background: espera a chamada convergir."""
    import time
    deadline = time.monotonic() + timeout
    while mock.call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    return mock


def test_startup_com_lembrar_aplica_salvo():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "apply_selection", return_value=(3, 56)) as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray") as run, \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "start_monitor_prewarm"):
        main.main(argv=["--tray"])
        _wait_called(ap).assert_called_once_with(
            chosen_cores=10, physical_cores=18, logical_count=36)
        rel.assert_not_called()
        run.assert_called_once()


def test_startup_sem_lembrar_libera_100():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": False, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "apply_selection") as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "start_monitor_prewarm"):
        main.main(argv=["--tray"])
        _wait_called(rel).assert_called_once()
        ap.assert_not_called()


def test_startup_lembrar_sem_valor_libera():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": None}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "start_monitor_prewarm"):
        main.main(argv=["--tray"])
        _wait_called(rel).assert_called_once()


def test_power_inicial_nao_bloqueia_o_startup():
    """Vacina do startup lento: main retorna com o power ainda em voo.

    Se o apply inicial voltar a ser síncrono, este teste trava junto (o main
    só retorna depois dos 3 powercfg).
    """
    import threading
    import time
    entered = threading.Event()
    release = threading.Event()

    def slow_apply(**_kwargs):
        entered.set()
        assert release.wait(timeout=10), "power em voo abandonado"
        return (3, 56)

    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config",
                         return_value={"remember": True, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "apply_selection", side_effect=slow_apply) as ap, \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "start_monitor_prewarm"):
        done = []
        thread = threading.Thread(
            target=lambda: (main.main(argv=["--tray"]), done.append(1)),
            daemon=True)
        started = time.monotonic()
        thread.start()
        assert entered.wait(timeout=10), "apply inicial nem começou"
        thread.join(timeout=5)
        elapsed = time.monotonic() - started
        assert done == [1], "main não retornou com o power em voo (bloqueou?)"
        assert elapsed < 2.0, f"main levou {elapsed:.2f}s com power em voo"
        release.set()
        thread.join(timeout=10)
        assert ap.call_count == 1


def test_falha_no_power_inicial_nao_mata_o_app(capsys):
    """Erro no power em background vira aviso; o app abre mesmo assim."""
    import time
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config",
                         return_value={"remember": False, "cores": None}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "release_all_cores",
                         side_effect=RuntimeError("acesso negado")) as rel, \
            patch.object(main.tray, "run_tray") as run, \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "start_monitor_prewarm"):
        main.main(argv=["--tray"])
        deadline = time.monotonic() + 10
        while rel.call_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        out = ""
        deadline = time.monotonic() + 10
        while "acesso negado" not in out and time.monotonic() < deadline:
            time.sleep(0.02)
            out += capsys.readouterr().out
        run.assert_called_once()
        assert "acesso negado" in out


def test_decide_panel_at_start():
    assert main.decide_panel_at_start([], False) == (True, False)  # manual: painel
    assert main.decide_panel_at_start(["--tray"], False) == (False, False)  # boot: só tray
    assert main.decide_panel_at_start([], True) == (False, False)  # Run antigo migrado: só tray
    assert main.decide_panel_at_start(["--post-update"], False) == (True, True)
    assert main.decide_panel_at_start(["--tray", "--post-update"], False) == (True, True)


def _run_main(argv):
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.cpu_info, "get_logical_count", return_value=36), \
            patch.object(main.config, "load_config", return_value={"remember": False}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.autostart, "migrate", return_value=False), \
            patch.object(main.power, "release_all_cores"), \
            patch.object(main.tray, "run_tray"), \
            patch.object(main.panel_mod, "start_auto_check"), \
            patch.object(main.panel_mod, "run_panel") as rp, \
            patch.object(main.tray, "open_tray_popup"):
        main.main(argv=argv)
        return rp


def test_manual_abre_painel_junto_da_tray():
    assert _run_main([]).call_count == 1


def test_boot_tray_nao_abre_painel():
    assert _run_main(["--tray"]).call_count == 0


def test_pos_update_abre_painel():
    assert _run_main(["--post-update"]).call_count == 1


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
