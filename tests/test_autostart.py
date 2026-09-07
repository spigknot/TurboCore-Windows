import sys
import types

from turbocore import autostart


def _fake_winreg(store: dict):
    fake = types.SimpleNamespace()
    fake.HKEY_CURRENT_USER = "HKCU"
    fake.KEY_READ = 1
    fake.KEY_WRITE = 2
    fake.REG_SZ = 1

    def OpenKey(*a, **k):
        return ("key", a)

    def QueryValueEx(key, name):
        if name in store:
            return (store[name], 1)
        raise FileNotFoundError(name)

    def SetValueEx(key, name, r, t, v):
        store[name] = v

    def DeleteValue(key, name):
        if name in store:
            del store[name]
        else:
            raise FileNotFoundError(name)

    def CloseKey(k):
        pass

    fake.OpenKey = OpenKey
    fake.QueryValueEx = QueryValueEx
    fake.SetValueEx = SetValueEx
    fake.DeleteValue = DeleteValue
    fake.CloseKey = CloseKey
    return fake


def test_is_enabled_false_quando_sem_valor(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({}))
    assert autostart.is_enabled() is False


def test_set_enabled_true_false(monkeypatch):
    store = {}
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    monkeypatch.setattr(autostart, "get_startup_command", lambda: '"C:\\x\\TurboCore.exe"')
    autostart.set_enabled(True)
    assert autostart.is_enabled() is True
    autostart.set_enabled(False)
    assert autostart.is_enabled() is False


def test_boot_grava_flag_tray():
    assert autostart.SILENT_FLAG == "--tray"


def test_migrate_reescreve_entrada_antiga(monkeypatch):
    store = {"TurboCore": '"C:\\x\\TurboCore.exe"'}
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    monkeypatch.setattr(autostart, "get_startup_command",
                        lambda: '"C:\\x\\TurboCore.exe" --tray')
    assert autostart.migrate() is True
    assert store["TurboCore"] == '"C:\\x\\TurboCore.exe" --tray'
    # Segunda vez: já migrado, nada a fazer.
    assert autostart.migrate() is False


def test_migrate_sem_entrada_nao_faz_nada(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({}))
    assert autostart.migrate() is False
