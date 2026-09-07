"""Vacina anti-drift: updater_client, updater congelado e instalador online
NÃO podem importar entre si (frozen), mas DEVEM concordar em protocolo.

Se este teste quebrar, a mesma constante mudou só de um lado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "installer"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "updater"))

from turbocore import updater_client  # noqa: E402
import turbocore_updater as updater  # noqa: E402
import installer_online as online  # noqa: E402


def test_mesma_base_r2():
    assert updater_client.R2_PUBLIC_BASE == updater.R2_PUBLIC_BASE == online.R2_MANIFEST_URL.rsplit("/", 1)[0]


def test_mesmo_user_agent():
    assert updater_client.HTTP_USER_AGENT == updater.HTTP_USER_AGENT
    # instalador tem UA próprio (identifica o chamador), mas mesmo padrão
    assert online.HTTP_USER_AGENT.startswith("TurboCore")
    assert "spigknot/TurboCore-Windows" in online.HTTP_USER_AGENT


def test_mesma_chave_publica():
    assert updater_client.UPDATE_PUBLIC_KEY_N == updater.UPDATE_PUBLIC_KEY_N
    assert updater_client.UPDATE_PUBLIC_KEY_E == updater.UPDATE_PUBLIC_KEY_E == 65537
    assert online.UPDATE_PUBLIC_KEY_N == updater_client.UPDATE_PUBLIC_KEY_N


def test_canonical_compativel():
    manifest = {"schema": 2, "version": "20260907_001", "created_at": "x",
                "files": [{"path": "a.exe", "sha256": "A" * 64, "size": 1,
                           "drive_id": "", "github_url": "u"}]}
    assert (updater.canonical_sync_manifest(manifest)
            == updater_client.canonical_sync_manifest(manifest)
            == online.canonical_sync_manifest(manifest))
