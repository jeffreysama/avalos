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


# ── Defaults y listas del wizard (idioma/timezone/keymap) ───────────────
# Extraído de skill_instalar_usb.py (líneas ~49-127). Vive acá (no en ui/)
# porque tanto ui.api (valida contra estas listas) como la función que arma
# el HTML del wizard (para poblar los <select>) lo necesitan — mismo criterio
# que ya usa VCONSOLE_TO_XKB arriba.
DEFAULT_HOSTNAME = 'avalos-pc'
DEFAULT_TIMEZONE = 'America/El_Salvador'

LOCALES = [('es_SV.UTF-8', 'Español — El Salvador'), ('es_GT.UTF-8', 'Español — Guatemala'), ('es_HN.UTF-8', 'Español — Honduras'), ('es_NI.UTF-8', 'Español — Nicaragua'), ('es_CR.UTF-8', 'Español — Costa Rica'), ('es_PA.UTF-8', 'Español — Panamá'), ('es_MX.UTF-8', 'Español — México'), ('es_CO.UTF-8', 'Español — Colombia'), ('es_PE.UTF-8', 'Español — Perú'), ('es_CL.UTF-8', 'Español — Chile'), ('es_AR.UTF-8', 'Español — Argentina'), ('es_UY.UTF-8', 'Español — Uruguay'), ('es_BO.UTF-8', 'Español — Bolivia'), ('es_VE.UTF-8', 'Español — Venezuela'), ('es_ES.UTF-8', 'Español — España'), ('en_US.UTF-8', 'English — United States'), ('en_GB.UTF-8', 'English — United Kingdom'), ('pt_BR.UTF-8', 'Português — Brasil'), ('pt_PT.UTF-8', 'Português — Portugal'), ('fr_FR.UTF-8', 'Français — France'), ('de_DE.UTF-8', 'Deutsch — Deutschland'), ('it_IT.UTF-8', 'Italiano — Italia'), ('ja_JP.UTF-8', '日本語 — Japan'), ('zh_CN.UTF-8', '中文 — China')]
DEFAULT_LOCALE = 'es_SV.UTF-8'

KEYMAPS = [('la-latin1', 'Español Latinoamérica (la-latin1)'), ('es', 'Español España (es)'), ('latam', 'Español Latam — variante (latam)'), ('us', 'Inglés EE.UU. (us)'), ('uk', 'English UK (uk)'), ('br-abnt2', 'Português Brasil (br-abnt2)'), ('de', 'Deutsch (de)'), ('de-latin1', 'Deutsch Latin-1 (de-latin1)'), ('fr', 'Français (fr)'), ('it', 'Italiano (it)'), ('ru', 'Русский (ru)'), ('dvorak', 'Dvorak (dvorak)'), ('colemak', 'Colemak (colemak)')]
DEFAULT_KEYMAP = 'la-latin1'

TIMEZONES = ['America/El_Salvador', 'America/Guatemala', 'America/Honduras', 'America/Costa_Rica', 'America/Panama', 'America/Managua', 'America/Mexico_City', 'America/Bogota', 'America/Lima', 'America/Santiago', 'America/Argentina/Buenos_Aires', 'America/Sao_Paulo', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Caracas', 'America/Montevideo', 'Europe/Madrid', 'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Asia/Tokyo', 'Asia/Shanghai', 'UTC']


def read_config(relative_path: str) -> str | None:
    """Lee un config desde /usr/share/avalos/configs/. Retorna None si no existe."""
    p = AVALOS_CONFIGS / relative_path
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None
