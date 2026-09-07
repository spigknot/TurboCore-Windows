"""Persistencia do 'Lembrar escolha' + ultima escolha em %APPDATA%/TurboCore/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"remember": False, "cores": None}


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "TurboCore" / "config.json"


def load_config() -> dict:
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
        remember = bool(raw.get("remember", False))
        cores = raw.get("cores", None)
        if isinstance(cores, int):
            pass
        elif isinstance(cores, str) and str(cores).isdigit():
            cores = int(cores)
        else:
            cores = None
        return {"remember": remember, "cores": cores}
    except Exception:
        return dict(DEFAULTS)


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"remember": bool(cfg.get("remember", False)),
                               "cores": cfg.get("cores", None)}, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p
