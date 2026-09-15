"""Prova funcional do EXE congelado (o que o usuário vê):

1. Start do exe -> janela do painel visível (startup do app).
2. Frames datados da janela logo depois de abrir: o painel já mostra as
   linhas 'Core N ... MHz' (antes: lista vazia por ~3 s).
3. Nenhum `powershell.exe` filho do app com o painel aberto (o monitor antigo
   criava ~19/min).
4. CPU do processo ao longo de ~8 s de painel aberto (leitura ~1 ms).

Os PNGs ficam em .hermes/scratch/panel_frames/ para inspeção.
APPDATA temporário: não encosta na config real; apply inicial = cores=18
(físicos) => min=3/max=100, o mesmo estado liberado da máquina.

Uso: python scripts/smoke_panel_latency.py
"""
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXE = Path("D:/Projetos/TurboCore/dist/TurboCore/TurboCore.exe")
ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / ".hermes" / "scratch" / "panel_frames"
TIMEOUT_S = 25.0
SHOTS = [0.0, 0.35, 0.7, 1.2, 2.0]  # segundos após a janela aparecer

sys.path.insert(0, str(ROOT / "src"))
from turbocore import cpu_info  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _pid_of(hwnd) -> int:
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    return owner.value


def _text_of(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    return buf.value


def _class_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_panel(pid: int):
    """Janela do PAINEL (classe TkTopLevel).

    O app tem duas janelas com o título "TurboCore": o painel (TkTopLevel) e o
    popup da tray (TurboCoreTray, escondido) — filtrar pelo título pega a errada.
    """
    found = []

    def cb(hwnd, _lp):
        if _pid_of(hwnd) == pid and _class_of(hwnd) == "TkTopLevel":
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def force_foreground(hwnd) -> None:
    """Traz a janela para frente de verdade (SetForegroundWindow sozinho é
    bloqueado quando quem chama não é o app em primeiro plano)."""
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    foreground = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    tid_self = kernel32.GetCurrentThreadId()
    if tid_fg:
        user32.AttachThreadInput(tid_fg, tid_self, True)
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if tid_fg:
            user32.AttachThreadInput(tid_fg, tid_self, False)


def capture(hwnd, path: Path) -> tuple[float, bool]:
    """Grab da tela com a janela em primeiro plano; repete até o frame ser da
    janela (o painel é claro; o tema do desktop/Hermes é escuro).

    Retorna (brilho médio, se conseguiu a janela na frente).
    """
    from PIL import ImageGrab, ImageStat
    rect = window_rect(hwnd)
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    image = None
    brightness = 0.0
    for _ in range(6):
        force_foreground(hwnd)
        time.sleep(0.15)
        image = ImageGrab.grab(bbox=bbox)
        brightness = ImageStat.Stat(image.convert("L")).mean[0]
        if brightness > 150:  # painel Tk claro
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return brightness, brightness > 150


def powershell_children(pid: int) -> list:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | "
          f"Where-Object {{ $_.ParentProcessId -eq {pid} }} | "
          "Select-Object ProcessId | Format-List")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                         capture_output=True, timeout=60)
    return re.findall(r"ProcessId\s*:\s*(\d+)",
                      out.stdout.decode("utf-8", errors="replace"))


def process_cpu(pid: int):
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE,
                                         ctypes.POINTER(wintypes.FILETIME),
                                         ctypes.POINTER(wintypes.FILETIME),
                                         ctypes.POINTER(wintypes.FILETIME),
                                         ctypes.POINTER(wintypes.FILETIME)]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000 | 0x0400, False, pid)  # QUERY_INFO
    if not handle:
        return None
    creation, exit_, kern, user = (wintypes.FILETIME(), wintypes.FILETIME(),
                                    wintypes.FILETIME(), wintypes.FILETIME())
    kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_),
                             ctypes.byref(kern), ctypes.byref(user))
    kernel32.CloseHandle(handle)
    ticks = ((user.dwHighDateTime << 32) + user.dwLowDateTime)
    ticks += ((kern.dwHighDateTime << 32) + kern.dwLowDateTime)
    return ticks / 1e7


def main() -> int:
    if not EXE.is_file():
        print("EXE nao encontrado:", EXE)
        return 1
    subprocess.run(["taskkill", "/F", "/IM", "TurboCore.exe"], capture_output=True)

    physical = cpu_info.get_physical_cores()
    tmp_appdata = tempfile.mkdtemp(prefix="turbocore_smoke_")
    cfg_dir = Path(tmp_appdata) / "TurboCore"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"remember": True, "cores": physical}), encoding="utf-8")

    for old in FRAMES.glob("*.png"):
        old.unlink()

    started = time.perf_counter()
    proc = subprocess.Popen([str(EXE)], env=dict(os.environ, APPDATA=tmp_appdata))
    app_pid = proc.pid
    shots = []
    cpu_start = cpu_end = None
    ph = []
    try:
        hwnd = None
        while time.perf_counter() - started < TIMEOUT_S:
            hwnd = find_panel(app_pid)
            if hwnd:
                break
            time.sleep(0.02)
        if hwnd is None:
            print(f"painel nao apareceu em {TIMEOUT_S:.0f}s")
            return 1
        window_at = time.perf_counter() - started

        # Frames datados (o 1o sai no instante em que a janela aparece).
        for index, delay in enumerate(SHOTS):
            target = window_at + delay
            while time.perf_counter() - started < target:
                time.sleep(0.005)
            path = FRAMES / f"{index}.png"
            brightness, ok = capture(hwnd, path)
            elapsed_ms = (time.perf_counter() - started) * 1000
            shots.append((elapsed_ms, path, brightness, ok))

        cpu_start = process_cpu(app_pid)
        for _ in range(8):
            ph += powershell_children(app_pid)
            time.sleep(1.0)
        cpu_end = process_cpu(app_pid)

        # Painel fechado (WM_CLOSE): o app continua vivo e não sobra thread
        # girando — um leitor vazado apareceria como CPU acumulando.
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(2.0)
        alive_after_close = proc.poll() is None
        cpu_idle_start = process_cpu(app_pid)
        time.sleep(4.0)
        cpu_idle_end = process_cpu(app_pid)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp_appdata, ignore_errors=True)

    print(f"exe                 : {EXE.name} ({EXE.stat().st_size} bytes)")
    print(f"janela do painel em  : {window_at*1000:.0f} ms (startup do app)")
    for elapsed_ms, path, brightness, ok in shots:
        flag = "painel" if ok else "OUTRA JANELA na frente!"
        print(f"  frame {elapsed_ms:6.0f} ms  brilho={brightness:5.1f} [{flag}]"
              f" -> {path.relative_to(ROOT)}")
    print(f"powershell filho do app (painel aberto): {len(ph)} {ph}")
    if cpu_start is not None and cpu_end is not None:
        print(f"CPU do app em ~8 s de painel aberto    : {cpu_end - cpu_start:.2f} s")
    print(f"apos fechar o painel: app vivo={alive_after_close}, "
          f"CPU em 4 s={cpu_idle_end - cpu_idle_start if cpu_idle_end and cpu_idle_start else -1:.2f} s")
    print("frames salvos em", FRAMES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
