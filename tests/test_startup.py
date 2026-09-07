from unittest.mock import patch

from turbocore import main


def test_startup_com_lembrar_aplica_salvo():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "apply_core_limit", return_value=56) as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray") as run:
        main.main()
        ap.assert_called_once_with(chosen_cores=10, physical_cores=18)
        rel.assert_not_called()
        run.assert_called_once()


def test_startup_sem_lembrar_libera_100():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.config, "load_config", return_value={"remember": False, "cores": 10}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "apply_core_limit") as ap, \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"):
        main.main()
        rel.assert_called_once()
        ap.assert_not_called()


def test_startup_lembrar_sem_valor_libera():
    with patch.object(main.cpu_info, "get_physical_cores", return_value=18), \
            patch.object(main.config, "load_config", return_value={"remember": True, "cores": None}), \
            patch.object(main.autostart, "is_enabled", return_value=False), \
            patch.object(main.power, "release_all_cores") as rel, \
            patch.object(main.tray, "run_tray"):
        main.main()
        rel.assert_called_once()
