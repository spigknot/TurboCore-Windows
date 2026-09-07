"""Instalador online: baixa (R2, fallback GitHub full) e instala em Program Files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "installer"))

from installer_online import (  # noqa: E402
    APP_DIR,
    download_manifest,
    install_tree,
    verify_entry,
)


def _manifest():
    return {"schema": 2, "version": "20260907_001",
            "files": [{"path": "TurboCore.exe", "sha256": "a" * 64, "size": 4,
                       "drive_id": "", "github_url": "https://pub-x/TurboCore.exe"}]}


def test_download_manifest_fake(monkeypatch):
    import base64
    import json as json_mod
    import installer_online as online
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    monkeypatch.setattr(online, "UPDATE_PUBLIC_KEY_N", pub.n)
    manifest = _manifest()
    canonical = online.canonical_sync_manifest(manifest)
    sig = key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    manifest["signature"] = base64.b64encode(sig).decode("ascii")

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1):
            return json_mod.dumps(manifest).encode()

    def fake_urlopen(request, timeout=None):
        return FakeResp()

    out = download_manifest("https://pub-x/sync_manifest.json", urlopen=fake_urlopen)
    assert out["version"] == "20260907_001"


def test_download_manifest_sem_assinatura_rejeitado():
    import json as json_mod

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1):
            return json_mod.dumps(_manifest()).encode()

    try:
        download_manifest("https://pub-x/sync_manifest.json",
                          urlopen=lambda request, timeout=None: FakeResp())
        assert False, "deveria rejeitar"
    except RuntimeError as exc:
        assert "Assinatura" in str(exc)


def test_verify_entry_ok_e_divergente(tmp_path):
    target = tmp_path / "f.exe"
    target.write_bytes(b"1234")
    import hashlib
    assert verify_entry(target, hashlib.sha256(b"1234").hexdigest()) is True
    try:
        verify_entry(target, "0" * 64)
        assert False, "deveria levantar"
    except RuntimeError as exc:
        assert "SHA-256" in str(exc)


def test_install_tree_copia(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "TurboCore.exe").write_bytes(b"exe")
    (src / "sub" / "a.dll").write_bytes(b"dll")
    seen = []
    install_tree(src, tmp_path / "dst", report=lambda *a: seen.append(a))
    assert (tmp_path / "dst" / "TurboCore.exe").read_bytes() == b"exe"
    assert (tmp_path / "dst" / "sub" / "a.dll").read_bytes() == b"dll"
    assert seen, "report deve ser chamado"


def test_app_dir_program_files():
    assert "Program Files" in str(APP_DIR)
    assert "TurboCore" in str(APP_DIR)
