"""Fumaca da UI standalone do updater (display real, rede real somente-leitura)."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "D:/Projetos/TurboCore/updater")
import turbocore_updater as tu  # noqa: E402

target = Path(tempfile.mkdtemp(prefix="tc-ui-"))
ui = tu.StandaloneUpdaterUI(target)
deadline = time.monotonic() + 25
while time.monotonic() < deadline:
    ui.root.update()
    time.sleep(0.2)
    if "Completo:" in ui.available_var.get():
        break
ui.root.update()
def _text(w):
    try:
        return str(w.cget("text"))
    except Exception:
        return ""


texts = [_text(w) for w in ui.root.winfo_children()]
print("available:", ui.available_var.get())
print("installed:", ui.installed_var.get())
print("combo:", ui.full_version_combo.cget("values"))
assert ui.root.title() == "Atualizador do TurboCore"
flat = list(texts)
assert "Completo:" in ui.available_var.get(), ui.available_var.get()
assert ui.full_version_combo.cget("values"), "dropdown vazio"
log_text = ui.log.get("1.0", "end")
assert "Consulta concluída" in log_text, log_text[-300:]
ui.root.destroy()
print("SMOKE_UPDATER_UI_OK")
