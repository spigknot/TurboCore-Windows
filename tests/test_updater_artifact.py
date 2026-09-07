"""Gate: updater/bin/TurboCoreUpdater.exe bate com updater/artifact.json.

Se falhar com divergência de size/sha256, o updater.py mudou (ou o toolchain
resolveu DLLs novas): rebuildar via updater/build.ps1 e revisar a composição.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_updater_artifact_gate():
    artifact_path = ROOT / "updater" / "artifact.json"
    assert artifact_path.is_file(), "updater/artifact.json não existe (rode updater/build.ps1)"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    source = ROOT / artifact["source"]
    assert source.is_file()
    assert _sha256(source) == artifact["source_sha256"], "updater.py mudou sem rebuild"
    binary = ROOT / "updater" / "bin" / artifact["name"]
    assert binary.is_file(), "binário do updater não existe (rode updater/build.ps1)"
    assert binary.stat().st_size == artifact["size"], "size do updater divergiu"
    assert _sha256(binary) == artifact["sha256"], "sha256 do updater divergiu"
