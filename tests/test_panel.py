"""Painel TurboCore: helpers puros + worker de update (sem Tk nos testes)."""
from unittest.mock import patch

from turbocore import panel


def test_verde_igual_sig():
    assert panel.UPDATE_GREEN == "#16833a"
    assert panel.UPDATE_GREEN_ACTIVE == "#116b30"


def test_botao_update_clones_sig():
    assert panel.UPDATE_LABEL == "Atualizar"
    assert panel.UPDATE_FG_DISABLED == "#f1f4f2"


def test_painel_largura_da_slider():
    # Estreito: linha do slider (240px) + margens, sem folga de 513.
    assert panel.PANEL_GEOMETRY == "300x720"


def test_slider_index_para_selecionado():
    options = [1, 2, 4, 6, 8, 10, 12, 14, 16, 18]
    assert panel.slider_index_for(options, 10) == 5
    assert panel.slider_index_for(options, 1) == 0
    assert panel.slider_index_for(options, None) == len(options) - 1
    assert panel.slider_index_for(options, 999) == len(options) - 1


def test_aplicar_somente_quando_preview_difere():
    assert panel.needs_apply(8, 10) is True
    assert panel.needs_apply(10, 10) is False
    assert panel.needs_apply(18, None) is True


def test_step_line_formato_sig():
    assert panel.step_line("14:19:29", "Buscando updates") == \
        "14:19:29  Buscando updates\n"


def test_finished_step_sem_novidade():
    assert panel.finished_step_line("14:19:29", "Buscando updates", 1.5,
                                    suffix="- Não tem!") == \
        "14:19:29  Buscando updates - Não tem! (1.5s)\n"


def test_finished_step_encontrada():
    assert panel.finished_step_line("14:19:29", "Buscando updates", 2.0,
                                    suffix="- Encontrada!") == \
        "14:19:29  Buscando updates - Encontrada! (2.0s)\n"


def test_finished_step_erro():
    assert panel.finished_step_line("14:19:29", "Buscando updates", 0.4,
                                    error="dns") == \
        "14:19:29  Buscando updates ERRO (0.4s): dns\n"


def test_sync_file_line_progresso_e_concluido():
    assert panel.sync_file_line("14:20:01", "TurboCore.exe", "42%") == \
        "14:20:01  Baixando TurboCore.exe - 42%\n"
    assert panel.sync_file_line("14:20:02", "TurboCore.exe", "100%") == \
        "14:20:02  Baixando TurboCore.exe\n"


def test_format_size_igual_sig():
    assert panel.format_size(1) == "1 byte"
    assert panel.format_size(512) == "512 bytes"
    assert panel.format_size(1500) == "1,5 KB"
    assert panel.format_size(2_500_000) == "2,5 MB"


def test_sobre_traz_versao_atual():
    from turbocore import __version__
    title, subtitle, version_line = panel.sobre_texts()
    assert (title, subtitle) == ("Delegacia de Taguaí", "Setor de Investigações Gerais")
    assert version_line == f"Versão: {__version__}"


def test_sobre_wallpaper_existe():
    assert panel.sobre_artwork() is not None
    assert panel.sobre_artwork().name == "appwin.png"


def test_label_cores_mostra_selecionado():
    assert panel.cores_label(8, 18) == "Cores: 8"
    assert panel.cores_label(1, 6) == "Cores: 1"


def test_label_cores_sem_selecao_mostra_total():
    assert panel.cores_label(None, 18) == "Cores: 18"


def test_remove_paths_lista_presentes_no_alvo(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"x")
    out = panel.remove_paths(tmp_path, {"a.txt": {}, "sub/b.bin": {}, "nao.txt": {}})
    assert sorted(out) == ["a.txt", "sub/b.bin"]


def test_activity_log_caixa_e_passos(tk_root):
    """ActivityLog desenha passo e reescreve a mesma linha (clone SIG)."""
    import tkinter as tk
    box = tk.Text(tk_root)
    activity = panel.ActivityLog(tk_root, box)
    activity.append("Painel aberto.")
    activity.begin("update:check", "Buscando updates")
    activity.finish("update:check", 1.5, suffix="- Não tem!")
    activity._drain()  # o drain roda na UI thread; teste chama direto
    content = box.get("1.0", "end")
    assert "Painel aberto." in content
    # A etapa não deve gerar uma segunda linha: reescrita na mesma linha.
    assert content.count("Buscando updates") == 1
    assert "- Não tem! (1.5s)" in content
    # Início vira verde no fim.
    linha = next(i for i in range(1, int(box.index("end-1c").split(".")[0]) + 1)
                 if "Não tem!" in box.get(f"{i}.0", f"{i}.end"))
    tags_linha = box.tag_names(f"{linha}.1")
    assert "activity_step_done" in tags_linha, tags_linha
    box.destroy()


def test_activity_log_arquivo_progresso(tk_root):
    """Linha viva por arquivo: % muda na MESMA linha; 100% verde."""
    import tkinter as tk
    box = tk.Text(tk_root)
    activity = panel.ActivityLog(tk_root, box)
    activity.file_progress("TurboCore.exe", "42%")
    activity.file_progress("TurboCore.exe", "100%", done_tag="vad_total")
    activity._drain()
    content = box.get("1.0", "end")
    assert content.count("Baixando TurboCore.exe") == 1, content
    assert "42%" not in content and "- 100%" not in content
    assert content.strip().endswith("Baixando TurboCore.exe")
    assert "vad_total" in box.tag_names("1.1")
    box.destroy()


def test_manual_check_trava_concorrencia():
    import threading
    checker = panel.ManualCheck()
    calls = []
    started = threading.Event()

    def slow_fetcher():
        started.set()
        import time
        time.sleep(0.3)
        return {"version": "20260907_009", "files": []}

    with patch.object(panel.updater_client, "check_for_update",
                      return_value={"update": True, "remote": "20260907_009"}), \
            patch.object(panel.updater_client, "classify_sync_files",
                         return_value={"download": ["TurboCore.exe"], "keep": []}):
        assert checker.start("/x", lambda k, v: calls.append((k, v)), fetcher=slow_fetcher) is True
        assert started.wait(timeout=5)
        assert checker.start("/x", lambda k, v: calls.append((k, v)), fetcher=slow_fetcher) is False
        deadline = __import__("time").monotonic() + 5
        while checker.busy and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert calls[0][0] == "updated"
    assert calls[0][1]["version"] == "20260907_009"
    assert calls[0][1]["download"] == ["TurboCore.exe"]
    assert checker.busy is False


def test_manual_check_sem_novidade_e_erro():
    out = []
    with patch.object(panel.updater_client, "check_for_update",
                      return_value={"update": False}):
        panel.ManualCheck().start("/x", lambda k, v: out.append((k, v)),
                                  fetcher=lambda: {"version": "20260907_001"})
        deadline = __import__("time").monotonic() + 5
        while not out and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert out == [("uptodate", None)]
    out.clear()
    def boom():
        raise Exception("dns")
    checker = panel.ManualCheck()
    checker.start("/x", lambda k, v: out.append((k, v)), fetcher=boom)
    deadline = __import__("time").monotonic() + 5
    while not out and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    assert out[0][0] == "error"


def test_poll_update_encontra_nova():
    with patch.object(panel.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_002"}), \
            patch.object(panel.updater_client, "check_for_update",
                         return_value={"update": True, "remote": "20260907_002"}):
        assert panel.poll_update_once("/x") == "20260907_002"


def test_poll_update_sem_novidade():
    with patch.object(panel.updater_client, "fetch_sync_manifest",
                      return_value={"version": "20260907_001"}), \
            patch.object(panel.updater_client, "check_for_update",
                         return_value={"update": False}):
        assert panel.poll_update_once("/x") is None


def test_poll_update_falha_rede():
    with patch.object(panel.updater_client, "fetch_sync_manifest", side_effect=Exception("dns")):
        assert panel.poll_update_once("/x") is None


def test_update_click_sem_updater_mantem_app():
    destroyed, stopped, errors = [], [], []
    # fluxo atual: sem updater instalado, o erro chega só após o download;
    # com download vazio (sem arquivos), cai no erro imediatamente.
    def boom_fetch():
        raise Exception("dns")
    with patch.object(panel.updater_client, "fetch_sync_manifest", side_effect=boom_fetch), \
            patch.object(panel.updater_client, "launch_updater_sync", return_value=False):
        ok = panel.handle_update_click(
            {"pending_update": "20260907_002", "log": None},
            destroyed.append, lambda: stopped.append(1), errors.append)
    deadline = __import__("time").monotonic() + 5
    while not errors and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    assert ok is True  # o clique inicia o fluxo em thread; app continua até o fim
    assert errors and "dns" in errors[0]


def test_update_click_baixa_e_dispara_sync(tmp_path, monkeypatch):
    import hashlib as _hl
    sha_x = _hl.sha256(b"x" * 64).hexdigest()
    destroyed, stopped, errors, busy = [], [], [], []
    manifest = {"schema": 2, "version": "20260907_002", "created_at": "x",
                "files": [{"path": "TurboCore.exe", "sha256": sha_x, "size": 64,
                           "drive_id": "", "github_url": "https://x/TurboCore.exe"},
                          {"path": "build-info.json", "sha256": "b" * 64, "size": 1,
                           "drive_id": "", "github_url": "https://x/build-info.json"},
                          {"path": "TurboCoreUpdater.exe", "sha256": "c" * 64, "size": 1,
                           "drive_id": "", "github_url": "https://x/TurboCoreUpdater.exe"}]}

    def fake_fetch():
        return manifest

    def fake_classify(_t, files):
        # só TurboCore.exe difere (os demais já existem localmente)
        return {"download": ["TurboCore.exe"], "keep": ["build-info.json"]}

    called = {}

    def fake_launch(staged, removals, version, target):
        called["staged"] = staged
        called["version"] = version
        return True

    def fake_download_url(url, dest, progress_callback=None, urlopen=None):
        import hashlib as _hl
        data = b"x" * 64
        dest.write_bytes(data)
        if progress_callback:
            progress_callback(len(data), len(data))
        return _hl.sha256(data).hexdigest()  # sha real do que escreveu

    with patch.object(panel.updater_client, "fetch_sync_manifest", side_effect=fake_fetch), \
            patch.object(panel.updater_client, "classify_sync_files", side_effect=fake_classify), \
            patch.object(panel.updater_client, "launch_updater_sync", side_effect=fake_launch), \
            patch.object(panel.updater_client, "download_url", side_effect=fake_download_url), \
            patch.object(panel.updater_client, "install_dir", return_value=tmp_path):
        ok = panel.handle_update_click(
            {"pending_update": "20260907_002", "log": None},
            lambda: destroyed.append(1), lambda: stopped.append(1), errors.append,
            set_busy=lambda b: busy.append(b))
        deadline = __import__("time").monotonic() + 8
        while not destroyed and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert ok is True
    assert called.get("version") == "20260907_002"
    assert destroyed == [1] and stopped == [1]
    assert errors == []
    assert busy[0] is True
    # o updater em execução nunca é substituído pelo staged
    assert not called["staged"].joinpath("TurboCoreUpdater.exe").exists()


def test_start_auto_check_guarda_pendente_e_avisa():
    import threading
    state = {}
    avisos = []
    with patch.object(panel, "poll_update_once", return_value="20260907_009"):
        panel.start_auto_check(state, notify=avisos.append)
        deadline = __import__("time").monotonic() + 5
        while "pending_update" not in state and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
    assert state["pending_update"] == "20260907_009"
    assert avisos == ["20260907_009"]
