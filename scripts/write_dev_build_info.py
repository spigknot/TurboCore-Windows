#!/usr/bin/env python3
"""Grava dist/TurboCore/build-info.json do DEV lendo __version__ do pacote."""
import json
import pathlib
import re
import sys


def write_dev_build_info(root: pathlib.Path) -> str:
    init = (root / "src" / "turbocore" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1)
    out = root / "dist" / "TurboCore" / "build-info.json"
    out.write_text(json.dumps({"version": version, "dev": True}, indent=2), encoding="utf-8")
    return version


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parent.parent
    print("build-info:", write_dev_build_info(root))
    sys.exit(0)
