"""Entrada do app: deteccao -> decisao inicial -> tray."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from turbocore import autostart, config, cpu_info, power, tray
from turbocore.core_calc import build_core_options


def load_icon() -> Image.Image:
    here = Path(__file__).resolve()
    for cand in [here.parent.parent.parent / "assets" / "chip.ico",
                 here.parent / "chip.ico",
                 Path("assets/chip.ico")]:
        if cand.exists():
            return Image.open(cand)
    # fallback: quadrado simples p/ nunca quebrar o boot
    return Image.new("RGB", (64, 64), (16, 122, 87))


def decide_initial_action(physical: int, cfg: dict) -> tuple[str, int | None]:
    """('apply', cores) se remember+valor valido e dentro das opcoes; senão ('release', None)."""
    cores = cfg.get("cores")
    if cfg.get("remember") and isinstance(cores, int) and cores in build_core_options(physical):
        return ("apply", cores)
    return ("release", None)


def main() -> None:
    physical = cpu_info.get_physical_cores()
    logical = cpu_info.get_logical_count()
    cfg = config.load_config()
    options = build_core_options(physical)
    state = {"physical": physical, "logical": logical,
             "options": options,
             "selected": cfg.get("cores") if cfg.get("cores") in options else None,
             "remember": bool(cfg.get("remember")),
             "boot": autostart.is_enabled(),
             "icon": None}
    action, cores = decide_initial_action(physical, cfg)
    try:
        if action == "apply":
            power.apply_selection(chosen_cores=cores, physical_cores=physical,
                                  logical_count=logical)
            state["selected"] = cores
        else:
            power.release_all_cores()  # Lembrar=OFF (ou sem valor): libera explicitamente com 100
    except RuntimeError as e:
        # Sem privilegio p/ powercfg: abre o tray mesmo assim; usuario tenta de novo como admin.
        print(f"[TurboCore] aviso: nao apliquei limite inicial: {e}")
    tray.run_tray(state, load_icon())


if __name__ == "__main__":
    main()
