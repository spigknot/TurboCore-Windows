import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from write_dev_build_info import write_dev_build_info  # noqa: E402


def test_grava_versao_do_pacote(tmp_path):
    src = tmp_path / "src" / "turbocore"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "20260907_009"\n')
    (tmp_path / "dist" / "TurboCore").mkdir(parents=True)
    assert write_dev_build_info(tmp_path) == "20260907_009"
    import json
    assert json.loads((tmp_path / "dist" / "TurboCore" / "build-info.json").read_text())[
        "version"] == "20260907_009"
