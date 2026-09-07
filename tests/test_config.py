from turbocore import config


def test_defaults_quando_sem_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    assert config.load_config() == {"remember": False, "cores": None}


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    config.save_config({"remember": True, "cores": 10})
    assert config.load_config() == {"remember": True, "cores": 10}


def test_corrompido_volta_ao_default(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("{json quebrado", encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: p)
    assert config.load_config() == {"remember": False, "cores": None}
