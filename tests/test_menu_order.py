from turbocore import tray


def test_menu_build_ordem_boot_por_ultimo():
    st = {"physical": 18,
          "options": [1, 2, 4, 6, 8, 10, 12, 14, 16, 18],
          "selected": 10, "remember": True, "boot": False}
    menu = tray.build_menu(st)  # nao deve levantar ValueError do pystray
    names = [getattr(i, "text", "SEP") for i in menu.items]
    assert names[0] == "1 Core"
    assert names[9] == "18 Cores"
    assert names[-1] == "Sair"
    assert names[-2] == "Iniciar no boot"
    assert names[-3] == "Lembrar escolha"
