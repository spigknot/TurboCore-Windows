"""Lado app da atualização (spec: docs/update-pipeline.md §1)."""
import base64
import json

import pytest

from turbocore import updater_client
from turbocore.updater_client import UpdateError


def _test_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    return key, pub.n, 65537


def _sign(private_key, manifest: dict) -> dict:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key  # noqa
    manifest = dict(manifest)
    if "signature" in manifest:
        del manifest["signature"]
    canonical = updater_client.canonical_sync_manifest(manifest)
    sig = private_key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    manifest["signature"] = base64.b64encode(sig).decode("ascii")
    return manifest


def _manifest(version="20260907_001", extra_files=()):
    files = [
        {"path": "TurboCore.exe", "sha256": "a" * 64, "size": 100,
         "drive_id": "", "github_url": "https://x/TurboCore.exe"},
        {"path": "TurboCoreUpdater.exe", "sha256": "b" * 64, "size": 100,
         "drive_id": "", "github_url": "https://x/TurboCoreUpdater.exe"},
        {"path": "build-info.json", "sha256": "c" * 64, "size": 10,
         "drive_id": "", "github_url": "https://x/build-info.json"},
        {"path": "_internal/base_library.zip", "sha256": "d" * 64, "size": 10,
         "drive_id": "", "github_url": "https://x/base_library.zip"},
        {"path": "_internal/python311.dll", "sha256": "e" * 64, "size": 10,
         "drive_id": "", "github_url": "https://x/python311.dll"},
    ]
    files.extend(extra_files)
    return {"schema": 2, "version": version, "created_at": "2026-09-07T00:00:00+0000",
            "files": files}


@pytest.fixture()
def signed(monkeypatch):
    key, n, e = _test_keypair()
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_N", n)
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_E", e)
    return _sign(key, _manifest())


def test_verify_roundtrip(signed):
    assert updater_client._verify_rsa_sha256_signature(
        signed["signature"], updater_client.canonical_sync_manifest(signed)) is True


def test_verify_tampered(signed, monkeypatch):
    key, n, e = _test_keypair()
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_N", n)
    signed["files"][0]["sha256"] = "f" * 64
    assert updater_client._verify_rsa_sha256_signature(
        signed["signature"], updater_client.canonical_sync_manifest(signed)) is False


def test_validate_ok(signed):
    assert updater_client.validate_sync_manifest(signed)["version"] == "20260907_001"


def test_validate_rejects_bad_schema(signed):
    signed["schema"] = 1
    with pytest.raises(UpdateError):
        updater_client.validate_sync_manifest(signed)


def test_validate_rejects_bad_version(signed):
    signed["version"] = "0.1.0"
    with pytest.raises(UpdateError):
        updater_client.validate_sync_manifest(signed)


def test_validate_rejects_missing_required(signed):
    signed["files"] = [f for f in signed["files"] if f["path"] != "TurboCore.exe"]
    with pytest.raises(UpdateError):
        updater_client.validate_sync_manifest(signed)


def test_validate_rejects_bad_signature(signed):
    signed["signature"] = base64.b64encode(b"\x00" * 256).decode("ascii")
    with pytest.raises(UpdateError):
        updater_client.validate_sync_manifest(signed)


def test_validate_ignores_unknown_component(signed, monkeypatch):
    key, n, e = _test_keypair()
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_N", n)
    monkeypatch.setattr(updater_client, "UPDATE_PUBLIC_KEY_E", e)
    m = _manifest(extra_files=[{"path": "novo_recurso.dat", "sha256": "9" * 64,
                                "size": 5, "drive_id": "", "github_url": "https://x/n"}])
    assert updater_client.validate_sync_manifest(_sign(key, m))


def test_fetch_uses_ua_and_validates(signed):
    seen = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return json.dumps(signed).encode()

    def fake_urlopen(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        seen["url"] = request.full_url
        return FakeResp()

    out = updater_client.fetch_sync_manifest(urlopen=fake_urlopen)
    assert out["version"] == "20260907_001"
    assert "TurboCoreUpdater" in seen["ua"]
    assert seen["url"].endswith("/sync_manifest.json")


def test_classify(tmp_path):
    (tmp_path / "same.exe").write_bytes(b"1234")
    (tmp_path / "diff.exe").write_bytes(b"xxxx")
    import hashlib
    files = {
        "same.exe": {"sha256": hashlib.sha256(b"1234").hexdigest()},
        "diff.exe": {"sha256": "0" * 64},
        "new.exe": {"sha256": "0" * 64},
    }
    out = updater_client.classify_sync_files(tmp_path, files)
    assert out == {"download": ["diff.exe", "new.exe"], "keep": ["same.exe"]}


def test_installed_version(tmp_path):
    assert updater_client.installed_version(tmp_path) is None
    (tmp_path / "build-info.json").write_text('{"version": "0.1.0"}')
    assert updater_client.installed_version(tmp_path) is None
    (tmp_path / "build-info.json").write_text('{"version": "20260907_001"}')
    assert updater_client.installed_version(tmp_path) == "20260907_001"


def test_version_key_ordering():
    assert updater_client.version_key("20260907_002") > updater_client.version_key("20260907_001")
    assert updater_client.version_key("lixo") == (0, 0, 0)


def test_check_for_update(tmp_path):
    manifest = _manifest("20260907_002")
    assert updater_client.check_for_update(tmp_path, manifest)["update"] is True
    (tmp_path / "build-info.json").write_text('{"version": "20260907_002"}')
    out = updater_client.check_for_update(tmp_path, manifest)
    assert out == {"local": "20260907_002", "remote": "20260907_002", "update": False}


def test_find_updater_none_em_dev():
    assert updater_client.find_updater_exe() is None
    assert updater_client.launch_updater(updater_client.install_dir()) is False
