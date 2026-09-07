"""Fumaca da UI do instalador online (display real, sem rede, sem instalar)."""
import sys

sys.path.insert(0, "D:/Projetos/TurboCore/installer")
import installer_online as online  # noqa: E402

root = __import__("tkinter").Tk()
app = online.InstallerApp(root)
root.update()
assert root.title() == "TurboCore — Instalação online", root.title()
assert root.geometry().startswith("560x280"), root.geometry()
assert app.action_button.cget("text") == "Baixar"
assert "Clique em Baixar" in app.status_var.get()
assert app.source == "" and app.download_ok is False
root.destroy()
print("SMOKE_INSTALLER_OK")
