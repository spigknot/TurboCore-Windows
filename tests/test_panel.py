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


def test_apply_outcome_mudanca():
    msg, run = panel.apply_outcome(18, 8, 18)
    assert (msg, run) == ("Núcleos ativos 8 -> 18.", True)
    msg, run = panel.apply_outcome(4, 18, 18)
    assert (msg, run) == ("Núcleos ativos 18 -> 4.", True)


def test_apply_outcome_mesmo_valor_noop():
    msg, run = panel.apply_outcome(4, 4, 18)
    assert (msg, run) == ("Núcleos ativos já é 4.", False)


def test_apply_outcome_sem_aplicado_usa_fisico():
    msg, run = panel.apply_outcome(4, None, 18)
    assert (msg, run) == ("Núcleos ativos 18 -> 4.", True)


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
    activity.append("Painel aberto.", "vad_total")
    activity.append("Núcleos ativos 8 -> 10.", "vad_total")
    activity.begin("update:check", "Buscando updates")
    activity.finish("update:check", 1.5, suffix="- Não tem!")
    activity._drain()  # o drain roda na UI thread; teste chama direto
    content = box.get("1.0", "end")
    assert "Painel aberto." in content
    # Mensagens de sucesso simples também saem em verde (vad_total).
    for needle in ("Painel aberto.", "Núcleos ativos 8 -> 10."):
        linha_ok = next(i for i in range(1, int(box.index("end-1c").split(".")[0]) + 1)
                        if needle in box.get(f"{i}.0", f"{i}.end"))
        assert "vad_total" in box.tag_names(f"{linha_ok}.1"), (needle, box.tag_names(f"{linha_ok}.1"))
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


def test_sync_removals_so_orfaos(tmp_path):
    """Vacina do 004->006: removals.txt levava o manifesto inteiro (1045).

    Órfãos = arquivos no disco AUSENTES do manifesto novo; o updater em
    execução, seu lock e seu log nunca entram na lista.
    """
    import tempfile
    from pathlib import Path
    target = tmp_path / "app"
    (target / "_internal").mkdir(parents=True)
    (target / "TurboCore.exe").write_bytes(b"exe")
    (target / "_internal" / "base_library.zip").write_bytes(b"lib")
    (target / "velho.dll").write_bytes(b"orphan")
    (target / "TurboCoreUpdater.exe").write_bytes(b"updater")
    (target / ".turbocore-update.lock").write_bytes(b"lock")
    (target / "TurboCoreUpdater.log").write_bytes(b"log")
    files = {"TurboCore.exe": {}, "_internal/base_library.zip": {}}
    got = {}
    panel.sync_download_worker({}, target, files, [], panel._NullLog(),
                               lambda k, p: got.setdefault("done", (k, p)),
                               version="20260907_009")
    assert got["done"][0] == "ready", got
    removals = Path(tempfile.gettempdir(), "turbocore_updater_sync",
                    "removals.txt").read_text(encoding="utf-8").split()
    assert removals == ["velho.dll"], removals


def test_update_click_ignora_segundo_clique(tmp_path, monkeypatch):
    """Vacina do 23:17: dois updaters concorrentes intercalavam apply/rollback.

    Com update em voo, o segundo clique retorna False sem disparar nada; após
    o desfecho com erro, a trava libera e o retry volta a retornar True.
    """
    import time
    from turbocore import updater_client
    target = tmp_path / "app"
    target.mkdir()
    monkeypatch.setattr(updater_client, "install_dir", lambda: target)

    def boom_fetch():
        raise Exception("dns")

    monkeypatch.setattr(updater_client, "fetch_sync_manifest", boom_fetch)
    destroyed, stopped, errors = [], [], []
    state = {"pending_update": "20260907_009", "log": panel._NullLog()}
    assert panel.handle_update_click(
        state, lambda: destroyed.append(1), lambda: stopped.append(1),
        errors.append) is True
    assert panel.handle_update_click(
        state, lambda: destroyed.append(1), lambda: stopped.append(1),
        errors.append) is False  # em voo: ignorado, sem nova thread
    deadline = time.monotonic() + 15
    while "update_settle" not in state and time.monotonic() < deadline:
        time.sleep(0.02)
    assert panel.poll_update_settle(state) is True
    assert errors and "dns" in errors[0]
    assert destroyed == [] and stopped == []
    assert panel.handle_update_click(
        state, lambda: destroyed.append(1), lambda: stopped.append(1),
        errors.append) is True  # trava liberou: retry permitido


def test_update_teardown_somente_via_recolhimento_ui(tmp_path, monkeypatch):
    """Vacina do PID que nunca morria: destroy/stop vinham da thread de download.

    A worker só deposita state["update_settle"]; quem executa é o
    poll_update_settle() — chamado pelo tick() na UI thread. Nenhum chamado
    Tkinter parte da worker (after/event_generate levantam "main thread is
    not in main loop" de forma racy). O watchdog cobre o painel fechado.
    """
    import hashlib
    import threading
    import time
    from pathlib import Path
    from turbocore import updater_client
    target = tmp_path / "app"
    target.mkdir()
    payload = b"novo-exe"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updater_client, "install_dir", lambda: target)
    monkeypatch.setattr(updater_client, "fetch_sync_manifest",
                        lambda: {"version": "20260907_009",
                                 "files": [{"path": "TurboCore.exe", "sha256": digest,
                                            "github_url": "https://x/novo"}]})
    monkeypatch.setattr(updater_client, "download_url",
                        lambda url, dest, progress_callback=None, urlopen=None:
                        (Path(dest).write_bytes(payload),
                         progress_callback(len(payload), len(payload))
                         if progress_callback else None))
    launched = []
    monkeypatch.setattr(updater_client, "launch_updater_sync",
                        lambda staged, rem, ver, tgt: launched.append(ver) or True)
    main_ident = threading.get_ident()
    calls: dict = {}
    state = {"pending_update": "20260907_009", "log": panel._NullLog()}
    assert panel.handle_update_click(
        state, lambda: calls.setdefault("destroy", threading.get_ident()),
        lambda: calls.setdefault("stop", threading.get_ident()),
        lambda m: calls.setdefault("err", m)) is True
    # A worker termina (outcome depositado) SEM executar o teardown...
    deadline = time.monotonic() + 15
    while "update_settle" not in state and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "update_settle" in state, (launched, calls)
    assert launched == [] and "destroy" not in calls and "stop" not in calls, calls
    # ...quem executa é o recolhimento (tick, na UI thread):
    assert panel.poll_update_settle(state) is True
    assert launched == ["20260907_009"], (launched, calls)
    assert calls.get("destroy") == main_ident, calls
    assert calls.get("stop") == main_ident, calls
    assert "err" not in calls, calls.get("err")
    assert panel.poll_update_settle(state) is False  # idempotente


def test_update_watchdog_fecha_app_com_painel_fechado(tmp_path, monkeypatch):
    """Sem tick (painel fechado no meio do download), o watchdog desliga.

    O destroy falha (root morta) e é ignorado, mas o stop TEM que rodar para
    o updater sair da espera do PID e relançar o app.
    """
    import hashlib
    import threading
    import time
    from pathlib import Path
    from turbocore import updater_client
    target = tmp_path / "app"
    target.mkdir()
    payload = b"novo-exe"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updater_client, "install_dir", lambda: target)
    monkeypatch.setattr(updater_client, "fetch_sync_manifest",
                        lambda: {"version": "20260907_009",
                                 "files": [{"path": "TurboCore.exe", "sha256": digest,
                                            "github_url": "https://x/novo"}]})
    monkeypatch.setattr(updater_client, "download_url",
                        lambda url, dest, progress_callback=None, urlopen=None:
                        Path(dest).write_bytes(payload))
    monkeypatch.setattr(updater_client, "launch_updater_sync",
                        lambda staged, rem, ver, tgt: True)

    fired = {}

    class FakeTimer:
        def __init__(self, delay, fn):
            self.fn = fn
            fired["delay"] = delay
        daemon = True
        def start(self):
            self.fn()  # watchdog imediato: simula tick morto

    monkeypatch.setattr("threading.Timer", FakeTimer)
    calls: dict = {}
    state = {"pending_update": "20260907_009", "log": panel._NullLog()}

    def destroy():
        calls["destroy tried"] = True
        raise RuntimeError("root morta")

    assert panel.handle_update_click(
        state, destroy,
        lambda: calls.setdefault("stop", True),
        lambda m: calls.setdefault("err", m)) is True
    deadline = time.monotonic() + 15
    while "stop" not in calls and "err" not in calls \
            and time.monotonic() < deadline:
        time.sleep(0.02)
    assert calls.get("stop") is True, calls  # stop rodou mesmo sem painel
    assert fired.get("delay") == 8.0, fired


def test_bolt_image_nitido_e_quadrado():
    """Raio RGBA com fundo transparente e corpo centralizado (supersample)."""
    from turbocore.icons import bolt_image
    img = bolt_image(16)
    assert img.size == (16, 16) and img.mode == "RGBA"
    opaque = sum(img.getchannel("A").histogram()[128:])  # nº de px >=50% alfa
    assert 256 * 0.05 < opaque < 256 * 0.6, opaque
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert right - left >= 4 and bottom - top >= 8


def test_aplicar_botao_raio_quadrado(tk_root):
    """Botão Aplicar: ícone de raio, sem texto, quadrado, ~36px de lado."""
    import tkinter as tk
    from tkinter import ttk
    ttk.Style(tk_root).configure("Apply.TButton", padding=(4, 4))
    parent = tk.Frame(tk_root)
    btn = panel.create_apply_button(parent, "Apply.TButton", lambda: None)
    assert btn.cget("text") == ""
    assert str(btn.cget("image")) != "", "sem imagem de raio"
    w, h = btn.winfo_reqwidth(), btn.winfo_reqheight()
    assert w == h, (w, h)
    assert 32 <= h <= 40, h  # +50% sobre os 24px originais
    parent.destroy()


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
        state = {"pending_update": "20260907_002", "log": None}
        ok = panel.handle_update_click(
            state,
            destroyed.append, lambda: stopped.append(1), errors.append)
    deadline = __import__("time").monotonic() + 5
    while not errors and __import__("time").monotonic() < deadline:
        panel.poll_update_settle(state)  # o tick faz isso na UI thread
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
        state = {"pending_update": "20260907_002", "log": None}
        ok = panel.handle_update_click(
            state,
            lambda: destroyed.append(1), lambda: stopped.append(1), errors.append,
            set_busy=lambda b: busy.append(b))
        deadline = __import__("time").monotonic() + 8
        while not destroyed and __import__("time").monotonic() < deadline:
            panel.poll_update_settle(state)  # o tick faz isso na UI thread
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
