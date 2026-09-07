"""tc_sync_r2: snapshot, manifesto e compatibilidade de assinatura com o app."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import tc_sync_r2 as sync  # noqa: E402
from turbocore import updater_client  # noqa: E402


def test_snapshot_exclui_cache(tmp_path):
    pkg = tmp_path / "package"
    (pkg / "_internal").mkdir(parents=True)
    (pkg / "TurboCore.exe").write_bytes(b"exe1")
    (pkg / "_internal" / "a.dll").write_bytes(b"dll")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "x.pyc").write_bytes(b"pyc")
    (pkg / "mod.pyc").write_bytes(b"pyc")
    files = sync.snapshot(pkg)
    assert sorted(files) == ["TurboCore.exe", "_internal/a.dll"]
    assert files["TurboCore.exe"]["size"] == 4
    assert len(files["TurboCore.exe"]["sha256"]) == 64


def _ephemeral_key(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = tmp_path / "priv.pem"
    priv.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    pub = key.public_key().public_numbers()
    return priv, pub.n, 65537


def test_assinatura_release_verifica_no_app(tmp_path, monkeypatch):
    """Prova cruzada: o que o sync assina, o updater_client valida."""
    priv, n, e = _ephemeral_key(tmp_path)
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_N", n)
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_E", e)
    files = {"TurboCore.exe": {"sha256": "a" * 64, "size": 4},
             "TurboCoreUpdater.exe": {"sha256": "b" * 64, "size": 4},
             "build-info.json": {"sha256": "c" * 64, "size": 4},
             "_internal/base_library.zip": {"sha256": "d" * 64, "size": 4},
             "_internal/python311.dll": {"sha256": "e" * 64, "size": 4}}
    manifest = sync.build_manifest(files, "20260907_001", "https://pub-x.r2.dev")
    assert manifest["schema"] == 2
    assert manifest["files"][0]["github_url"].startswith("https://pub-x.r2.dev/")
    sync.sign_manifest(manifest, priv)
    assert "signature" in manifest
    # canônicos idênticos dos dois lados
    assert sync.canonical_manifest(manifest) == updater_client.canonical_sync_manifest(manifest)
    assert updater_client.validate_sync_manifest(manifest)["version"] == "20260907_001"
