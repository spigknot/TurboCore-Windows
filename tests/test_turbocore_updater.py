"""Nucleo do TurboCoreUpdater: protocolo, zip, lock, classify (tudo mockado)."""
import base64
import json
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "updater"))

import turbocore_updater as tu  # noqa: E402


def _test_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    return key, pub.n, 65537


def _sign(private_key, manifest: dict) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    manifest = {k: v for k, v in manifest.items() if k != "signature"}
    canonical = tu.canonical_sync_manifest(manifest)
    sig = private_key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    manifest["signature"] = base64.b64encode(sig).decode("ascii")
    return manifest


def _manifest(version="20260907_001"):
    files = [
        {"path": p, "sha256": "a" * 64, "size": 10, "drive_id": "",
         "github_url": f"https://x/{p}"}
        for p in ("TurboCore.exe", "TurboCoreUpdater.exe", "build-info.json",
                  "_internal/base_library.zip", "_internal/python311.dll")
    ]
    return {"schema": 2, "version": version, "created_at": "2026-09-07T00:00:00+0000",
            "files": files}


@pytest.fixture()
def signed(monkeypatch):
    key, n, e = _test_keypair()
    monkeypatch.setattr(tu, "UPDATE_PUBLIC_KEY_N", n)
    monkeypatch.setattr(tu, "UPDATE_PUBLIC_KEY_E", e)
    return _sign(key, _manifest())


def test_manifesto_valido(signed):
    assert tu.validate_sync_manifest(signed)["version"] == "20260907_001"


def test_manifesto_assinatura_invalida(signed):
    signed["signature"] = base64.b64encode(b"\x01" * 256).decode("ascii")
    with pytest.raises(tu.UpdateError):
        tu.validate_sync_manifest(signed)


def test_classify(tmp_path):
    import hashlib
    (tmp_path / "same.exe").write_bytes(b"1234")
    (tmp_path / "diff.exe").write_bytes(b"xxxx")
    files = {
        "same.exe": {"sha256": hashlib.sha256(b"1234").hexdigest()},
        "diff.exe": {"sha256": "0" * 64},
    }
    out = tu.classify_sync_files(tmp_path, files)
    assert out == {"download": ["diff.exe"], "keep": ["same.exe"]}


def _zip(tmp_path, names, with_build_info=True):
    zp = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        if with_build_info:
            zf.writestr("build-info.json", json.dumps({"version": "20260907_002"}))
        for name in names:
            zf.writestr(name, b"data:" + name.encode())
    return zp


def test_zip_full_ok(tmp_path):
    zp = _zip(tmp_path, ["TurboCore.exe", "TurboCoreUpdater.exe",
                         "_internal/base_library.zip", "_internal/python311.dll"])
    assert tu.validate_zip(zp) == "full"


def test_zip_traversal_rejeitado(tmp_path):
    zp = _zip(tmp_path, ["TurboCore.exe", "../evil.exe"])
    with pytest.raises(tu.UpdateError):
        tu.validate_zip(zp)


def test_zip_sem_obrigatorio_rejeitado(tmp_path):
    zp = _zip(tmp_path, ["TurboCore.exe"])
    with pytest.raises(tu.UpdateError):
        tu.validate_zip(zp)


def test_zip_symlink_rejeitado(tmp_path):
    zp = tmp_path / "link.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("build-info.json", json.dumps({"version": "20260907_002"}))
        info = zipfile.ZipInfo("evil.lnk")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "target")
    with pytest.raises(tu.UpdateError):
        tu.validate_zip(zp)


def test_zip_version_lido_sem_extrair(tmp_path):
    zp = _zip(tmp_path, ["TurboCore.exe"])
    assert tu.zip_version(zp) == "20260907_002"


def test_lock_exclusivo_e_stale(tmp_path):
    target = tmp_path / "app"
    target.mkdir()
    with tu.installation_lock(target, stale_after=60):
        with pytest.raises(tu.UpdateError):
            with tu.installation_lock(target, stale_after=60):
                pass
    # lock liberado: adquire de novo
    with tu.installation_lock(target, stale_after=60):
        pass
    # lock velho: takeover
    lock = target / tu.UPDATE_LOCK_NAME
    lock.write_text("pid=9999")
    old = time.time() - 7200
    os.utime(lock, (old, old))
    with tu.installation_lock(target, stale_after=60):
        pass


def test_version_key():
    assert tu.version_key("20260907_002") > tu.version_key("20260907_001")
    assert tu.version_key("x") == (0, 0, 0)


def _fake_target(root: Path, version="20260907_001"):
    (root / "_internal").mkdir(parents=True, exist_ok=True)
    (root / "TurboCore.exe").write_bytes(b"app-v1")
    (root / "TurboCoreUpdater.exe").write_bytes(b"upd-v1")
    (root / "build-info.json").write_text(json.dumps({"version": version}))
    (root / "_internal" / "base_library.zip").write_bytes(b"lib")
    (root / "_internal" / "python311.dll").write_bytes(b"dll")
    return root


def _fake_manifest_v2():
    def entry(path, data: bytes):
        import hashlib
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data), "drive_id": "",
                "github_url": f"https://x/{path}"}
    new_app, new_info = b"app-v2", json.dumps({"version": "20260907_002"}).encode()
    files = [entry("TurboCore.exe", new_app), entry("build-info.json", new_info),
             entry("TurboCoreUpdater.exe", b"upd-v1"),
             entry("_internal/base_library.zip", b"lib"),
             entry("_internal/python311.dll", b"dll"),
             entry("assets/chip.ico", b"ico")]
    return {"schema": 2, "version": "20260907_002",
            "created_at": "2026-09-07T00:00:00+0000", "files": files}, new_app


def _patch_downloads(monkeypatch, manifest):
    import hashlib

    def fake_download(url, dest, max_bytes=0):
        for entry in manifest["files"]:
            if entry["github_url"] == url:
                data = {"TurboCore.exe": b"app-v2",
                        "build-info.json": json.dumps({"version": "20260907_002"}).encode(),
                        "assets/chip.ico": b"ico"}.get(entry["path"], b"upd-v1" if "Updater" in entry["path"] else b"lib" if "base" in entry["path"] else b"dll")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return
        raise AssertionError(f"url desconhecida: {url}")

    monkeypatch.setattr(tu, "download_file", fake_download)


def test_worker_diff_aplica_e_limpa(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)
    launched = []
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log: launched.append(exe))
    log = tmp_path / "t.log"
    tu.worker_diff(target, 0, log, wait_timeout=1, startup_timeout=1)
    assert (target / "TurboCore.exe").read_bytes() == b"app-v2"
    assert (target / "assets" / "chip.ico").read_bytes() == b"ico"
    assert tu.installed_version(target) == "20260907_002"
    assert launched == [target / "TurboCore.exe"]
    assert "validada" in log.read_text(encoding="utf-8")


def test_worker_diff_falha_restaura(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)

    def boom(exe, t, log):
        raise tu.UpdateError("novo exe morreu")

    monkeypatch.setattr(tu, "_launch_and_verify", boom)
    log = tmp_path / "t.log"
    with pytest.raises(tu.UpdateError):
        tu.worker_diff(target, 0, log, wait_timeout=1, startup_timeout=1)
    assert (target / "TurboCore.exe").read_bytes() == b"app-v1"
    assert tu.installed_version(target) == "20260907_001"
    assert not (target / "assets" / "chip.ico").exists()


def test_recover_interrompida(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    target = _fake_target(tmp_path / "app")
    txn = tu._transaction_root() / "txn1"
    (txn / "backup").mkdir(parents=True)
    (txn / "backup" / "TurboCore.exe").write_bytes(b"app-v1")
    (target / "TurboCore.exe").write_bytes(b"app-QUEBRADO")
    (txn / "journal.json").write_text(json.dumps({"status": "started"}))
    tu._recover_interrupted(target, tmp_path / "r.log")
    assert (target / "TurboCore.exe").read_bytes() == b"app-v1"
    assert not txn.exists()
