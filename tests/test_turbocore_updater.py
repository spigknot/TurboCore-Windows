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
from unittest.mock import patch

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


def test_default_target_program_files(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    assert tu._default_target() == Path(r"C:\Program Files\TurboCore")


def test_full_download_vai_para_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    target = Path(r"C:\Program Files\TurboCore")
    dest = tu.full_download_path(target, "20260907_002", "full", "turbocore_x_full.zip")
    assert dest.name == "turbocore_x_full.zip"
    assert str(target) not in str(dest)
    assert "20260907_002" in str(dest)


def test_standalone_log_cai_no_cache_quando_target_sem_escrita(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    alvo_ok = tmp_path / "app"
    alvo_ok.mkdir()
    assert tu._standalone_log_path(alvo_ok) == alvo_ok / "TurboCoreUpdater.log"
    alvo_arquivo = tmp_path / "nao-dir"
    alvo_arquivo.write_bytes(b"x")
    assert tu._standalone_log_path(alvo_arquivo).parent.name == "updater"


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
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: launched.append(exe))
    log = tmp_path / "t.log"
    tu.worker_diff(target, 0, log, wait_timeout=1, startup_timeout=1)
    assert (target / "TurboCore.exe").read_bytes() == b"app-v2"
    assert (target / "assets" / "chip.ico").read_bytes() == b"ico"
    assert tu.installed_version(target) == "20260907_002"
    assert launched == [target / "TurboCore.exe"]
    assert "validada" in log.read_text(encoding="utf-8")


def test_worker_apply_staged_aplica_e_valida(tmp_path, monkeypatch):
    """worker_apply_staged aplica arquivos pré-baixados e relança o app."""
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    staged = tmp_path / "staged"
    (staged / "_internal").mkdir(parents=True)
    (staged / "TurboCore.exe").write_bytes(b"app-v3")
    (staged / "build-info.json").write_text(json.dumps({"version": "20260907_003"}))
    removals = tmp_path / "removals.txt"
    removals.write_text("assets/chip.ico\n")
    launched = []
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: launched.append(exe))
    log = tmp_path / "t.log"
    tu.worker_apply_staged(staged, removals, "20260907_003", target, 0, log,
                           wait_timeout=1, startup_timeout=1)
    assert (target / "TurboCore.exe").read_bytes() == b"app-v3"
    assert tu.installed_version(target) == "20260907_003"
    assert not (target / "assets" / "chip.ico").exists()
    assert launched == [target / "TurboCore.exe"]
    assert "validada" in log.read_text(encoding="utf-8")


def test_worker_apply_staged_ignora_removal_sobreposta(tmp_path, monkeypatch):
    """Vacina do 004->006: removals com o staged apagava a instalação.

    Um chamador com a lista invertida (1045 removals p/ 3 staged) esvaziava
    o Program Files; o worker agora ignora removals sobrepostas ao staged,
    o updater em execução e o lock — com trilha no log.
    """
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    staged = tmp_path / "staged"
    (staged / "_internal").mkdir(parents=True)
    (staged / "TurboCore.exe").write_bytes(b"app-v3")
    (staged / "build-info.json").write_text(json.dumps({"version": "20260907_003"}))
    removals = tmp_path / "removals.txt"
    removals.write_text("TurboCore.exe\nbuild-info.json\nassets/chip.ico\n"
                        "TurboCoreUpdater.exe\n.turbocore-update.lock\n")
    launched = []
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: launched.append(exe))
    log = tmp_path / "t.log"
    tu.worker_apply_staged(staged, removals, "20260907_003", target, 0, log,
                           wait_timeout=1, startup_timeout=1)
    assert (target / "TurboCore.exe").read_bytes() == b"app-v3"
    assert tu.installed_version(target) == "20260907_003"
    assert not (target / "assets" / "chip.ico").exists()  # órfão legítimo sai
    assert "removals ignoradas" in log.read_text(encoding="utf-8")
    assert launched == [target / "TurboCore.exe"]
    assert "validada" in log.read_text(encoding="utf-8")


def test_segundo_updater_falha_sem_tocar_transacao_alheia(tmp_path, monkeypatch):
    """Vacina do 23:17 do log real: dois updaters intercalavam apply/rollback.

    O recover de transações interrompidas roda DENTRO do lock: com lock
    fresco de outro run, o worker recusa ("outra atualização em andamento")
    sem reverter nem apagar a transação alheia — e sem NameError no
    except/finally (transaction ainda é None).
    """
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    target = _fake_target(tmp_path / "app")
    antes = sorted(p.relative_to(target).as_posix()
                   for p in target.rglob("*") if p.is_file())
    # Lock fresco de um run concorrente.
    (target / tu.UPDATE_LOCK_NAME).write_text("pid=99999")
    # Transação interrompida de outro run (seria revertida+apagada pelo recover).
    alheia = tu._transaction_root() / ".tc-updater-alheia"
    (alheia / "backup").mkdir(parents=True)
    (alheia / "journal.json").write_text(json.dumps({"status": "applied", "added": []}))
    (alheia / "backup" / "sentinela.txt").write_bytes(b"backup-alheio")
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "TurboCore.exe").write_bytes(b"app-v3")
    (staged / "build-info.json").write_text(json.dumps({"version": "20260907_003"}))
    removals = tmp_path / "removals.txt"
    removals.write_text("")
    launched = []
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: launched.append(exe))
    log = tmp_path / "t.log"
    with pytest.raises(tu.UpdateError, match="outra atualização em andamento"):
        tu.worker_apply_staged(staged, removals, "20260907_003", target, 0, log,
                               wait_timeout=1, startup_timeout=1)
    assert launched == []
    assert (alheia / "journal.json").is_file(), "transação alheia foi tocada"
    assert (alheia / "backup" / "sentinela.txt").read_bytes() == b"backup-alheio"
    depois = sorted(p.relative_to(target).as_posix()
                    for p in target.rglob("*") if p.is_file())
    assert depois == sorted(antes + [tu.UPDATE_LOCK_NAME]), (antes, depois)


def test_worker_diff_nao_auto_substitui_updater(tmp_path, monkeypatch):
    """O updater em execução NUNCA é substituído pelo diff (self-exclusão)."""
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)
    launched = []
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: launched.append(exe))
    log = tmp_path / "t.log"
    tu.worker_diff(target, 0, log, wait_timeout=1, startup_timeout=1)
    # O updater original permanece (sua cópia nova só entra no pacote; o
    # bootstrap a usa na próxima atualização).
    assert (target / "TurboCoreUpdater.exe").read_bytes() == b"upd-v1"
    assert "validada" in log.read_text(encoding="utf-8")


def test_worker_diff_falha_restaura(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)

    def boom(exe, t, log, **k):
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


def test_validate_sync_target(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    tu._validate_sync_target(vazio)  # vazio ok (instalação nova)
    ok = tmp_path / "ok"
    (ok).mkdir()
    (ok / "TurboCore.exe").write_bytes(b"x")
    tu._validate_sync_target(ok)
    estranha = tmp_path / "estranha"
    estranha.mkdir()
    (estranha / "outro.exe").write_bytes(b"x")
    with pytest.raises(tu.UpdateError):
        tu._validate_sync_target(estranha)


def test_worker_diff_chama_progress(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)
    monkeypatch.setattr(tu, "_launch_and_verify", lambda exe, t, log, **k: None)
    seen = []
    tu.worker_diff(target, 0, tmp_path / "t.log", wait_timeout=1, startup_timeout=1,
                   progress=lambda i, n, p: seen.append((i, n, p)))
    assert [s[0] for s in seen] == [1, 2, 3]
    assert all(s[1] == 3 for s in seen)


def test_relancamento_pos_update_abre_painel(tmp_path, monkeypatch):
    """O app relançado recebe --post-update (abre o painel p/ conferir)."""
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target = _fake_target(tmp_path / "app")
    manifest, _ = _fake_manifest_v2()
    monkeypatch.setattr(tu, "fetch_sync_manifest", lambda: manifest)
    _patch_downloads(monkeypatch, manifest)
    calls = []
    monkeypatch.setattr(tu, "_launch_and_verify",
                        lambda exe, t, log, **k: calls.append(k))
    tu.worker_diff(target, 0, tmp_path / "t.log", wait_timeout=1, startup_timeout=1)
    assert calls and calls[0].get("extra_args") == ("--post-update",)


def test_download_informa_total_real(tmp_path):
    import io

    data = b"y" * 100
    seen = []

    class FakeResp:
        headers = {"Content-Length": "100"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            nonlocal data
            chunk, data = data[:10], data[10:]
            return chunk

    dest = tmp_path / "x.bin"
    try:
        with patch.object(tu.urllib.request, "urlopen", return_value=FakeResp()):
            tu.download_file("https://x/f.zip", dest,
                             progress=lambda done, total: seen.append((done, total)))
    finally:
        if dest.exists():
            dest.unlink()
    assert seen, "progress deveria ter sido chamado"
    assert seen[-1][1] == 100, seen[-1]


def test_instalacao_exige_escrita_ou_avisa(tmp_path):
    alvo = tmp_path / "app"
    alvo.mkdir()
    tu.require_writable_target(alvo)  # gravável: passa
    travado = tmp_path / "nao-dir"
    travado.write_bytes(b"x")
    with pytest.raises(tu.UpdateError) as info:
        tu.require_writable_target(travado)
    assert "administrador" in str(info.value) or "permissão" in str(info.value)
