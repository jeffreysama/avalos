"""
core/config.py — rutas y utilidades de configuración compartidas por todo
el instalador modular.

Extraído de skill_instalar_usb.py (líneas 35-37, 46-47, 115-116, 38-45).
Lógica sin cambios; `_leer_config` se renombra a `read_config` (público)
por la misma razón que `run_command` en core/shell.py: pasa de ser un
helper privado de un solo archivo a ser la implementación compartida.
"""

from __future__ import annotations

from pathlib import Path

# ── Rutas de montaje del sistema en instalación ──────────────────────────
MOUNT_ROOT = Path("/mnt/avalos_install")
MOUNT_EFI = MOUNT_ROOT / "boot" / "efi"
MOUNT_ISO = Path("/tmp/avalos_iso")

# ── Configs de AvalOS embebidas en el ISO/sistema instalado ──────────────
AVALOS_CONFIGS = Path("/usr/share/avalos/configs")

# ── Repo de origen (usado para URLs de release, os-release, etc.) ────────
AVALOS_REPO = "jeffreysama/avalos"
AVALOS_REPO_URL = f"https://github.com/{AVALOS_REPO}/releases/download/repo"


# Traduce nombres de keymap de consola (vconsole.conf / loadkeys) al layout
# XKB que espera tanto Hyprland/Wayland como X11. No todos coinciden 1:1
# (ej. "la-latin1" en consola es "latam" en XKB). Vive acá (no en desktop/
# ni en system/) porque tanto desktop.hyprland como system.locale la
# necesitan — moverla a cualquiera de los dos hubiera obligado al otro a
# importar de un módulo que no le corresponde conceptualmente.
VCONSOLE_TO_XKB = {
    "la-latin1": "latam",
    "es": "es",
    "latam": "latam",
    "us": "us",
    "uk": "gb",
    "br-abnt2": "br",
    "de": "de",
    "de-latin1": "de",
    "fr": "fr",
    "it": "it",
    "ru": "ru",
    "dvorak": "us(dvorak)",
    "colemak": "us(colemak)",
}


def read_config(relative_path: str) -> str | None:
    """Lee un config desde /usr/share/avalos/configs/. Retorna None si no existe."""
    p = AVALOS_CONFIGS / relative_path
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None
