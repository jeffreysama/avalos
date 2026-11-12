"""skill_instalar_usb.py — instalador de AvalOS de un solo archivo (`avalos-install-old`).

GENERADO por scripts/build-legacy-installer.py a partir de scripts/avalos_installer/: NO EDITAR A MANO (los
cambios se hacen en el paquete modular y se regenera este archivo; el test tests/test_legacy_bundle.py falla si
no está al día).

Es el mismo instalador que `avalos-install`, empaquetado: cada módulo viaja aquí dentro como texto y se importa
desde este archivo, así que funciona aunque el directorio avalos_installer/ de la ISO no esté. Lo único externo
es translations.py (igual que siempre) y, en la ISO, pywebview y GTK.

El monolito original de 5.538 líneas que estuvo aquí hasta el commit anterior a este cambio se puede recuperar con:
    git show 2f2d844:scripts/skill_instalar_usb.py
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import linecache
import os
import sys

BUNDLE_SOURCE_SHA256 = "cedcb70cb7d245c68168eb63c6fc6d9d1bba1859da929ff68088f70dc9f62308"

# nombre del módulo -> (¿es paquete?, ruta de origen, código fuente). Las rutas son las del repo, para que los
# errores y los tracebacks apunten a scripts/avalos_installer/… y no a este archivo.
_MODULES = {
    # ── avalos_installer/__init__.py (0 líneas)
    'avalos_installer': (True, 'avalos_installer/__init__.py', r''''''),
    # ── avalos_installer/__main__.py (107 líneas)
    'avalos_installer.__main__': (False, 'avalos_installer/__main__.py', r'''"""
avalos_installer/__main__.py — punto de entrada del instalador modular.

Permite correr el paquete con `python3 -m avalos_installer`. Réplica
fiel del bloque `if __name__ == "__main__":` de skill_instalar_usb.py
(líneas 5051-5108): mismo chequeo de root con el mismo mensaje, mismas
tres variables de entorno de WebKit, mismo GLib.set_prgname("avalos-install")
envuelto en try/except, misma geometría de ventana (960×640,
min_size 800×540, background #1a1b26), mismo patrón de guard con
_lock/_thread_started antes de lanzar el hilo al cargar la ventana, mismo
manejo de excepción si pywebview/webkit2gtk-4.1 no está instalado.

Única diferencia real respecto al original: el target del hilo es
core.install.run_installation en vez de VentanaInstalador._run_instalacion,
y el bridge es ui.api.InstallerAPI en vez de InstaladorAPI — misma forma,
implementación modular. También se ajustó el texto del mensaje de "sin
root" para reflejar que el comando real ahora es `avalos-install` (el
wrapper de build-iso.yml ya resuelve el `python3 -m avalos_installer` por
dentro), no `python avalos-install` como decía el original.

NO PROBADO CON PYWEBVIEW REAL: este sandbox no tiene GTK/webkit2gtk-4.1
ni servidor gráfico, así que esto se verificó por lectura línea por línea
contra el main() original (que sí corre en producción), no por ejecución.
La prueba real es la que J. va a hacer con la ISO en hardware de verdad.
"""

from __future__ import annotations

import os
import sys
import threading

import webview

from avalos_installer.core.install import run_installation
from avalos_installer.core.session import InstallSession
from avalos_installer.ui.api import InstallerAPI
from avalos_installer.ui.html import build_html


def main() -> None:
    if os.geteuid() != 0:
        print("╔═══════════════════════════════════════════════════╗")
        print("║  AvalOS Installer necesita privilegios de root.   ║")
        print("╠═══════════════════════════════════════════════════╣")
        print("║  Ejecuta con:  sudo avalos-install                ║")
        print("║  O como root:  avalos-install                     ║")
        print("╚═══════════════════════════════════════════════════╝")
        sys.exit(1)

    os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
    os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
    os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"

    session = InstallSession()
    session.logfile.install_hooks()   # excepciones sin capturar → archivo de log
    api = InstallerAPI(session)
    html = build_html()

    try:
        from gi.repository import GLib
        GLib.set_prgname("avalos-install")
    except Exception:
        pass

    win = webview.create_window(
        title="AvalOS — Instalador",
        html=html,
        js_api=api,
        width=960,
        height=640,
        min_size=(800, 540),
        resizable=True,
        background_color="#1a1b26",
    )
    session.window = win
    win.events.closed += session.on_close

    def _on_loaded():
        with session._lock:
            if session._thread_started:
                return
            session._thread_started = True
            session._config_ready.clear()
        t = threading.Thread(target=run_installation, args=(session,), daemon=True)
        session._install_thread = t
        t.start()

    win.events.loaded += _on_loaded

    try:
        webview.start(debug=os.environ.get("AVALOS_DEBUG") == "1")
    except Exception as e:
        print(f"ERROR al iniciar pywebview: {e}")
        print("Asegúrate de que webkit2gtk-4.1 esté instalado:")
        print("  pacman -S webkit2gtk-4.1 python-gobject")
        sys.exit(1)

    # Si se cerró la ventana a mitad de instalación, dejar que el hilo termine su rollback:
    # es daemon y el intérprete lo cortaría al salir.
    t = getattr(session, "_install_thread", None)
    if t is not None and t.is_alive():
        t.join(timeout=90)


if __name__ == "__main__":
    main()
'''),
    # ── avalos_installer/core/__init__.py (0 líneas)
    'avalos_installer.core': (True, 'avalos_installer/core/__init__.py', r''''''),
    # ── avalos_installer/core/buildstamp.py (51 líneas)
    'avalos_installer.core.buildstamp': (False, 'avalos_installer/core/buildstamp.py', r'''"""Sello de build de la ISO: leerlo y copiarlo al sistema instalado.

Lo escribe el CI al armar la ISO (scripts/gen-build-stamp.py) en /usr/share/avalos/configs/:
  avalos-build         AVALOS_BUILD=AAAA.MM.DD-<commit>, AVALOS_COMMIT, AVALOS_COMMIT_DATE
  avalos-scripts.tsv   nombre, commit, fecha y sha256 de cada script de la ISO
El instalador deja el build en el BUILD_ID del os-release (Fastfetch lo muestra) y copia ambos archivos a
/usr/share/avalos/ para que `avalos-version` y el Doctor sepan de qué ISO viene el sistema. Una ISO sin sello
(build de desarrollo) no es un error: todo sigue funcionando y el build figura como desconocido.
"""
from __future__ import annotations

import re

from avalos_installer.core.config import read_config

STAMP_BUILD = "avalos-build"
STAMP_SCRIPTS = "avalos-scripts.tsv"
TARGET_BUILD = "usr/share/avalos/build"
TARGET_SCRIPTS = "usr/share/avalos/scripts.tsv"

# Termina en una línea del os-release (BUILD_ID=…): solo caracteres inofensivos, sin comillas ni saltos de línea.
BUILD_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")


def parse_stamp(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"')
    return out


def build_id() -> str | None:
    """El build de la ISO, o None si no hay sello o no tiene un formato seguro."""
    value = parse_stamp(read_config(STAMP_BUILD) or "").get("AVALOS_BUILD", "")
    return value if BUILD_ID_RE.match(value) else None


def install_stamp(session) -> bool:
    """Copia el sello al sistema instalado. False (sin fallar) si la ISO no trae uno válido."""
    if not build_id():
        session.log(session.t("log-build-stamp-missing"), "info")
        return False
    session.write_file(TARGET_BUILD, read_config(STAMP_BUILD))
    scripts = read_config(STAMP_SCRIPTS)
    if scripts:
        session.write_file(TARGET_SCRIPTS, scripts)
    return True
'''),
    # ── avalos_installer/core/config.py (102 líneas)
    'avalos_installer.core.config': (False, 'avalos_installer/core/config.py', r'''"""
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

# Cuánto espera el instalador a que el usuario termine el asistente antes de darlo por abandonado. Antes eran
# 10 minutos: en una instalación real (conectar el Wi-Fi, mirar discos, pensar) se pasa fácil y el instalador
# moría con «Timeout expired. Close and reopen the installer». Cerrar la ventana lo despierta al instante
# (session.on_close), así que esperar mucho no deja nada colgado.
WIZARD_IDLE_TIMEOUT_S = 6 * 60 * 60
MOUNT_EFI = MOUNT_ROOT / "boot" / "efi"
MOUNT_ISO = Path("/tmp/avalos_iso")

# Compartida entre mount.py (montaje inicial de subvolúmenes) y
# services.py (re-montaje de @snapshots tras crear la config de Snapper)
# para que ambos usen exactamente las mismas opciones.
BTRFS_MOUNT_OPTS = "compress=zstd,noatime,space_cache=v2"

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
# Países de los mirrors de reflector: los usa el instalador (network/mirrors.py) y el
# reflector.conf del sistema instalado (desktop/hyprland.py). Antes estaba copiada en cada
# sitio y al añadir China solo se actualizó una: el reflector.timer del sistema instalado
# habría vuelto a dejar el mirrorlist solo con SV/US/MX/GT/JP.
MIRROR_COUNTRIES = 'SV,US,MX,GT,JP,CN,HK,TW,PL'
DEFAULT_TIMEZONE = 'America/El_Salvador'

LOCALES = [('es_SV.UTF-8', 'Español — El Salvador'), ('es_GT.UTF-8', 'Español — Guatemala'), ('es_HN.UTF-8', 'Español — Honduras'), ('es_NI.UTF-8', 'Español — Nicaragua'), ('es_CR.UTF-8', 'Español — Costa Rica'), ('es_PA.UTF-8', 'Español — Panamá'), ('es_MX.UTF-8', 'Español — México'), ('es_CO.UTF-8', 'Español — Colombia'), ('es_PE.UTF-8', 'Español — Perú'), ('es_CL.UTF-8', 'Español — Chile'), ('es_AR.UTF-8', 'Español — Argentina'), ('es_UY.UTF-8', 'Español — Uruguay'), ('es_BO.UTF-8', 'Español — Bolivia'), ('es_VE.UTF-8', 'Español — Venezuela'), ('es_ES.UTF-8', 'Español — España'), ('en_US.UTF-8', 'English — United States'), ('en_GB.UTF-8', 'English — United Kingdom'), ('pt_BR.UTF-8', 'Português — Brasil'), ('pt_PT.UTF-8', 'Português — Portugal'), ('fr_FR.UTF-8', 'Français — France'), ('de_DE.UTF-8', 'Deutsch — Deutschland'), ('it_IT.UTF-8', 'Italiano — Italia'), ('ja_JP.UTF-8', '日本語 — Japan'), ('zh_CN.UTF-8', '中文 — China')]
DEFAULT_LOCALE = 'es_SV.UTF-8'

KEYMAPS = [('la-latin1', 'Español Latinoamérica (la-latin1)'), ('es', 'Español España (es)'), ('latam', 'Español Latam — variante (latam)'), ('us', 'Inglés EE.UU. (us)'), ('uk', 'English UK (uk)'), ('br-abnt2', 'Português Brasil (br-abnt2)'), ('de', 'Deutsch (de)'), ('de-latin1', 'Deutsch Latin-1 (de-latin1)'), ('fr', 'Français (fr)'), ('it', 'Italiano (it)'), ('ru', 'Русский (ru)'), ('dvorak', 'Dvorak (dvorak)'), ('colemak', 'Colemak (colemak)')]
DEFAULT_KEYMAP = 'la-latin1'

TIMEZONES = ['America/El_Salvador', 'America/Guatemala', 'America/Honduras', 'America/Costa_Rica', 'America/Panama', 'America/Managua', 'America/Mexico_City', 'America/Bogota', 'America/Lima', 'America/Santiago', 'America/Argentina/Buenos_Aires', 'America/Sao_Paulo', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Caracas', 'America/Montevideo', 'Europe/Madrid', 'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Asia/Tokyo', 'Asia/Shanghai', 'UTC']

# Nombres de usuario que el wizard rechaza (cuentas de sistema de Arch/systemd). Única fuente
# de verdad: ui/api.py los valida en Python y ui/html.py los inyecta al JS
# (window._reservedUsers), para que los dos lados no se desincronicen.
RESERVED_USERNAMES = (
    'root', 'daemon', 'bin', 'sys', 'sync', 'games', 'man', 'lp', 'mail', 'news',
    'uucp', 'proxy', 'backup', 'list', 'irc', 'nobody',
    'http', 'ftp', 'git', 'sshd', 'dbus', 'polkitd', 'avahi', 'colord', 'rtkit',
    'uuidd', 'nm-openconnect', 'ntp', 'systemd-network', 'systemd-resolve',
    'systemd-timesync', 'tss', 'messagebus', 'cups', 'gdm', 'lightdm', 'sddm',
    'mysql', 'postgres', 'redis', 'mongodb', 'www', 'operator',
)


def read_config(relative_path: str) -> str | None:
    """Lee un config desde /usr/share/avalos/configs/. Retorna None si no existe."""
    p = AVALOS_CONFIGS / relative_path
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None
'''),
    # ── avalos_installer/core/context.py (52 líneas)
    'avalos_installer.core.context': (False, 'avalos_installer/core/context.py', r'''"""
core/context.py — InstallContext: la configuración elegida por el usuario
para esta instalación. Dato puro, sin comportamiento (para eso está
InstallSession, ver core/session.py).

A diferencia de la primera propuesta (antes de leer _run_instalacion
completo), estos campos NO son una suposición razonable — son literalmente
cada atributo de configuración que el método de 1675 líneas realmente lee,
uno por uno, confirmado leyendo el código fuente completo. Nada de esto
existía como dataclass en el monolito: VentanaInstalador.__init__ los tenía
como ~15 atributos sueltos (self._username, self._password, etc.),
recibidos de a poco vía la API de pywebview desde el wizard de la UI.

Los campos manual_* solo se usan cuando manual_mode=True — vienen de
verificar_particionado_manual()/confirmar_root_manual() en InstaladorAPI,
ya validados contra detect_manual_partitions() antes de llegar acá (ver
disk/discovery.py). No se re-validan en este dataclass a propósito: la
validación de "¿el usuario realmente eligió una partición root?" es lógica
de flujo (pertenece al paso que arma el InstallContext, no al dataclass en
sí), igual que el original tampoco la hacía en __init__.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InstallContext:
    # ── Identidad del sistema ──────────────────────────────────────────
    username: str
    password: str
    hostname: str = "avalos-pc"          # ver DEFAULT_HOSTNAME en core.config
    timezone: str = "America/El_Salvador"  # ver DEFAULT_TIMEZONE en core.config
    locale: str = "en_US.UTF-8"
    keymap: str = "us"
    lang: str = "en"                     # idioma de UI (en/es/zh/ja) — distinto de locale

    # ── Destino y modo de instalación ────────────────────────────────────
    target_disk: str | None = None       # nombre del disco (ej. "sda"), no /dev/sda
    bootloader: str = "grub"             # grub | sd-boot | refind | none
    usb_mode: bool = False               # True = ext4 sin journal, portable

    # ── Modo manual (el usuario ya particionó/formateó a mano) ──────────
    manual_mode: bool = False
    manual_efi_partition: str = ""       # ej. "/dev/sda1", vacío si no hay/no aplica
    manual_root_partition: str = ""      # ej. "/dev/sda2"
    manual_existing_subvolumes: list[str] = field(default_factory=list)

    # ── Perfil de instalación ────────────────────────────────────────────
    install_gaming: bool = False
    install_bore: bool = False
'''),
    # ── avalos_installer/core/install.py (438 líneas)
    'avalos_installer.core.install': (False, 'avalos_installer/core/install.py', r'''"""
core/install.py — run_installation(): el orquestador real.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas 3333-5006, ~1675 líneas — el método más grande de todo el
monolito). Reemplaza tanto la lógica de _run_instalacion como el punto
donde esta llamaba a los dos métodos grandes que vivían pegados a ella
(_configurar_optimizaciones, _configurar_hyprland) — acá son las
funciones ya extraídas configure_optimizations()/configure_hyprland().

DE DÓNDE SALE ctx: este orquestador arranca temprano (ver ui/api.py — se
lo lanza como target de un Thread apenas la ventana carga, igual que el
original lanzaba _run_instalacion), y bloquea en
session._config_ready.wait(timeout=600) — exactamente como
_run_instalacion() bloqueaba en self._config_lista.wait(timeout=600).
Recién cuando ui.api.InstallerAPI.start_installation() arma un
InstallContext completo y hace session.pending_context = ctx +
session._config_ready.set(), este método continúa y lee
session.pending_context. retry() reutiliza el mismo mecanismo: como
_config_ready ya quedó seteado la primera vez, el wait() de una segunda
corrida vuelve verdadero de inmediato, sin bloquear ni pedir el wizard
de nuevo.

PASO "aur" — ya implementado (system/aur.py, agregado después de las
pruebas en hardware real de la ISO base): yay/AUR + los extras de
gaming (gamemode.ini/MangoHud.conf/flatpak) que en el original viven
condicionados a que yay haya bootstrapeado bien.

Ningún cambio de lógica respecto al original en ningún otro paso,
incluida una asimetría real que tiene el original entre qué returns
limpian montajes (clean_mounts()) y cuáles no: los fatales de selección
de disco (antes de tocar el disco) no limpian nada porque no hay nada
que limpiar todavía; los chequeos de "¿se abortó?" a mitad de instalación
sí limpian siempre, sin importar si en ese punto exacto ya hay algo
montado. Se preservó punto por punto, no se armonizó a un único patrón
por prolijidad.
"""
from __future__ import annotations

import time

from avalos_installer.core.config import MOUNT_ROOT, WIZARD_IDLE_TIMEOUT_S
from avalos_installer.core.prereqs import TOOL_TO_PACKAGE, check_tools
from avalos_installer.core.session import InstallSession, output_indicates_gpg_error
from avalos_installer.desktop.hyprland import configure_hyprland
from avalos_installer.disk.discovery import MIN_DISK_GB, detect_target_disk_type, list_disks
from avalos_installer.hardware.detection import (
    detect_cpu_arch_level, detect_gpu, detect_microcode, is_uefi,
)
from avalos_installer.network.diagnose import diagnose_network
from avalos_installer.network.mirrors import optimize_mirrors, sync_time
from avalos_installer.system.aur import install_aur
from avalos_installer.system.bootloader import install_bootloader
from avalos_installer.system.fstab import generate_fstab
from avalos_installer.system.locale import configure_locale
from avalos_installer.system.mount import check_disk_space, mount_filesystems
from avalos_installer.system.optimize import configure_optimizations, enable_dns_over_tls
from avalos_installer.system.pacstrap import multilib_skipped_notice, run_pacstrap
from avalos_installer.system.partition import partition_and_format
from avalos_installer.system.repos import configure_repos
from avalos_installer.system.rollback import InstallJournal
from avalos_installer.system.services import configure_services
from avalos_installer.system.users import create_user

PASOS_IDS = [
    "uefi", "net", "tools", "part", "format", "mount", "mirrors",
    "pacstrap", "fstab", "config", "grub", "services", "user",
    "aur", "hypr", "umount",
]

_BOOTLOADER_LABELS = {"grub": "GRUB", "sd-boot": "systemd-boot", "refind": "rEFInd"}
_BOOTLOADER_SUMMARY = {"grub": "GRUB", "sd-boot": "systemd-boot", "refind": "rEFInd", "none": "Omitido"}


def run_installation(session: InstallSession) -> None:
    """Punto de entrada del hilo de instalación. Bloquea hasta que
    ui.api.InstallerAPI.start_installation() deje un InstallContext listo
    en session.pending_context (ver docstring del módulo)."""
    session._installing = True
    session.start_timer()

    if not session._config_ready.is_set():
        if not session._config_ready.wait(timeout=WIZARD_IDLE_TIMEOUT_S):
            session.log(session.t("log-timeout-wizard"), "err")
            session.error_step(session.t("err-timeout"))
            session._installing = False
            return
    if session._aborted:
        session._installing = False
        return

    ctx = session.pending_context
    if ctx is None:
        # No debería pasar nunca -- _config_ready solo se setea junto con
        # pending_context en start_installation() -- pero sin este chequeo
        # un bug ahí produciría un AttributeError feo más abajo en vez de
        # un log claro y una salida prolija.
        session.log(session.t("log-fatal-exception", e="pending_context vacío", tb=""), "err")
        session._installing = False
        return

    # El log jamás debe llevar la contraseña (aunque se colara en alguna línea)
    # y se avisa en la UI dónde queda guardado (RAM del live / USB de arranque).
    session.logfile.add_secret(ctx.password)
    session.report_log_destinations()

    session.info("user", ctx.username, "ok")
    session.info("modo", "USB (ext4 noatime)" if ctx.usb_mode else session.t("info-modo-pc"), "ok")
    session.info(
        "grub",
        _BOOTLOADER_LABELS.get(ctx.bootloader, session.t("info-bootloader-skipped")),
        "ok" if ctx.bootloader != "none" else "warn",
    )

    # Diario de rollback (system/rollback.py): uno por intento; lo que debe recordarse entre
    # intentos vive en session.rollback_memory.
    journal = InstallJournal(session)
    session.journal = journal
    completed = False

    total = len(PASOS_IDS)
    paso = 0

    def avanzar():
        nonlocal paso
        paso += 1
        session.progress(int(paso / total * 100))

    try:
        session.label(session.t("label-detecting-hw"))
        session.status(session.t("status-detecting-hw"))
        discos = list_disks()
        disponibles = [d for d in discos if not d["es_arranque"]]
        disco_boot = next((d for d in discos if d["es_arranque"]), None)

        cpu_arch = detect_cpu_arch_level()
        gpu_info = detect_gpu()
        es_v3 = cpu_arch in ("x86-64-v3", "x86-64-v4")
        if ctx.install_bore and es_v3:
            kernel_display = "linux-avalos-bore"
        elif es_v3:
            kernel_display = "linux-avalos"
        else:
            kernel_display = "linux-avalos-compat"
        session.log(
            session.t(
                "log-summary-pre-kernel", cpu_arch=cpu_arch,
                gpu_vendor=gpu_info["vendor"].upper(), gpu_model=gpu_info["model"],
                kernel_display=kernel_display,
            ), "ok",
        )

        session.info("ucode", detect_microcode(), "ok")
        session.info("dest", f"CPU: {cpu_arch} → {kernel_display} · GPU: {gpu_info['vendor'].upper()}", "ok")

        if not disponibles:
            session.error_fatal(
                session.t("err-no-disk-available", boot_disk=(disco_boot["name"] if disco_boot else "?"))
            )
            return

        # Falla cerrado: si el disco elegido ya no está (desconectado, renombrado al
        # reenumerar) NO se instala en otro. Solo sin selección se usa el primero disponible.
        dev_requested = (ctx.target_disk or "").removeprefix("/dev/")
        if dev_requested:
            disco = next((d for d in discos if d["name"] == dev_requested), None)
            if disco is None:
                session.error_fatal(session.t("err-disk-not-found", dev_name=dev_requested))
                return
        else:
            disco = disponibles[0]
        dev_name = disco["name"]

        if disco["es_arranque"]:
            session.error_fatal(session.t("err-disk-is-boot-disk", dev_name=dev_name))
            return

        size_gb = disco["size_b"] / 1e9
        if size_gb < MIN_DISK_GB:
            session.error_fatal(
                session.t("err-disk-too-small", dev_name=dev_name, size_gb=size_gb, min_gb=MIN_DISK_GB)
            )
            return

        dev = f"/dev/{dev_name}"
        disco_tipo = detect_target_disk_type(dev_name)
        session.info("dest", f"{dev} ({disco['size_human']} · {disco_tipo.upper()} · {disco['model'] or session.t('disk-unknown')})", "ok")
        session.log(
            session.t("log-target-disk", dev=dev, size_human=disco["size_human"], disco_tipo=disco_tipo.upper()),
            "ok",
        )

        # ── uefi ──────────────────────────────────────────────────────
        session.step("uefi", "active")
        uefi = is_uefi()
        ucode = detect_microcode()
        session.info("ucode", ucode, "ok")
        session.badges(None, uefi)
        session.step("uefi", "done", "UEFI" if uefi else "BIOS Legacy")
        journal.snapshot_firmware(uefi)
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── net ───────────────────────────────────────────────────────
        session.step("net", "active")
        session.status(session.t("status-checking-internet"))
        # Diagnóstico por capas (network/diagnose.py) en vez de un ping a 8.8.8.8: distingue sin
        # enlace / sin IP / sin salida / DNS / portal cautivo / hora / mirrors caídos, y el error le
        # dice al usuario QUÉ hacer. Un primer fallo se reintenta una vez: el DHCP o la asociación
        # Wi-Fi pueden estar terminando de levantar.
        diag = diagnose_network()
        if not diag.usable:
            session.log(session.t(f"pf-net-{diag.verdict}", **diag.text_params()), "warn")
            time.sleep(3)
            diag = diagnose_network()
        for ln in diag.lines():
            session.logfile.diag(f"net: {ln}")
        net_ok = diag.usable
        session.badges(net_ok, uefi)
        if not net_ok:
            hint_key = ("pf-hint-net-no_link_wifi" if diag.verdict == "no_link" and diag.has_wifi
                        else f"pf-hint-net-{diag.verdict}")
            session.step("net", "error", session.t("step-net-down"))
            session.error_step(session.t(
                "err-net-diagnosis",
                reason=session.t(f"pf-net-{diag.verdict}", **diag.text_params()),
                hint=session.t(hint_key),
            ))
            return
        if diag.verdict != "ok":               # usable pero degradado: se avisa y se sigue
            session.log(session.t(f"pf-net-{diag.verdict}", **diag.text_params()), "warn")
        session.step("net", "done", session.t("step-net-up"))
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── tools ─────────────────────────────────────────────────────
        session.step("tools", "active")
        herramientas = check_tools()
        faltantes = [h for h, ok in herramientas.items() if not ok]
        if faltantes:
            paquetes_faltantes = sorted({TOOL_TO_PACKAGE.get(h, h) for h in faltantes})
            session.log(
                session.t(
                    "log-missing-tools", faltantes=", ".join(faltantes),
                    paquetes=", ".join(paquetes_faltantes),
                ), "warn",
            )
            rc_tools, out_tools = session.run_cmd(
                ["pacman", "-Sy", "--noconfirm", "--needed"] + paquetes_faltantes, timeout=120
            )
            if rc_tools != 0:
                if output_indicates_gpg_error(out_tools):
                    session.log(session.t("log-pacman-gpg-signature-issue"), "err")
                else:
                    session.log(session.t("log-pacman-sync-failed", rc=rc_tools), "warn")
        session.step("tools", "done")
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── part + format ─────────────────────────────────────────────
        # Un solo llamado hace las dos cosas -- partition.py ya trae sus
        # propios step("part",...)/step("format",...) adentro -- pero
        # PASOS_IDS los sigue contando como 2 pasos separados, así que
        # avanzamos el progreso dos veces tras el éxito.
        result = partition_and_format(session, ctx, dev, dev_name, disco, uefi)
        if result is None:
            return
        avanzar()
        avanzar()

        # ── mount ─────────────────────────────────────────────────────
        if not mount_filesystems(session, ctx, result.root_device, result.efi_device, uefi):
            return
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        if not check_disk_space(session):
            return

        sync_time(session)

        # ── mirrors ───────────────────────────────────────────────────
        optimize_mirrors(session)
        avanzar()

        # ── pacstrap ──────────────────────────────────────────────────
        kernel_pkg = run_pacstrap(session, ctx, cpu_arch, gpu_info, ucode)
        if kernel_pkg is None:
            return
        avanzar()

        # ── fstab ─────────────────────────────────────────────────────
        if not generate_fstab(session, ctx):
            return
        avanzar()

        # ── config (locale) ──────────────────────────────────────────
        if not configure_locale(session, ctx, kernel_pkg):
            return
        avanzar()

        # ── grub (bootloader) ────────────────────────────────────────
        # Rollback: foto de la ESP (y del MBR en BIOS manual) justo antes de que el bootloader
        # toque algo; desde aquí un fallo puede dejar entradas o archivos de arranque.
        journal.snapshot_esp(result.efi_device)
        if not uefi and ctx.manual_mode and ctx.bootloader != "none":
            journal.snapshot_mbr(dev)
        journal.mark("boot")
        if not install_bootloader(session, ctx, dev, result.root_device, uefi, ucode, kernel_pkg):
            return
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── services ──────────────────────────────────────────────────
        configure_services(session, ctx)
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # Optimizaciones: nunca tuvo paso propio en PASOS_IDS -- corre
        # acá en silencio, sin avanzar(), igual que en el original.
        configure_optimizations(
            session, gpu_info, cpu_arch, disco_tipo, ctx.lang, ctx.install_gaming, ctx.install_bore
        )

        if session._aborted:
            session.clean_mounts()
            return

        # ── user ──────────────────────────────────────────────────────
        if not create_user(session, ctx):
            return
        journal.mark("usable")  # usuario creado: el sistema ya arranca, un fallo tardío no le quita el arranque
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # Repos: tampoco tuvo paso propio en PASOS_IDS -- corre en
        # silencio entre "user" y "aur", sin avanzar().
        configure_repos(session)

        # ── aur ───────────────────────────────────────────────────────
        install_aur(session, ctx)
        avanzar()

        # FIX: DNS-over-TLS se movió acá (ver comentario en
        # configure_optimizations) — antes corría antes de esta línea y
        # dejaba /etc/resolv.conf apuntando a un stub que nunca se
        # genera dentro de un chroot, rompiendo la resolución DNS para
        # el resto de la instalación (el 'git clone' de yay, arriba,
        # es justamente la primera operación de red que lo sufre).
        enable_dns_over_tls(session)

        # ── hypr ──────────────────────────────────────────────────────
        session.step("hypr", "active")
        session.status(session.t("status-configuring-hyprland"))
        session.label(session.t("label-configuring-hyprland"))
        session.log(session.t("log-section-hyprland-config"), "step")
        configure_hyprland(session, ctx.username, gpu_info, ctx.keymap, ctx.lang)
        session.step("hypr", "done", "SDDM · Waybar · hyprland.lua · rofi · kitty")
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── umount ────────────────────────────────────────────────────
        session.step("umount", "active")
        session.status(session.t("status-unmounting"))
        session.log(session.t("log-section-unmounting"), "step")
        session.clean_mounts()
        session.step("umount", "done")
        avanzar()
        completed = True

        bl_summary = _BOOTLOADER_SUMMARY.get(ctx.bootloader, "?")
        done_info = (
            f"<strong>Disco:</strong> {dev} ({disco['size_human']})<br>"
            f"<strong>Usuario:</strong> {ctx.username}<br>"
            f"<strong>Hostname:</strong> {ctx.hostname}<br>"
            f"<strong>Timezone:</strong> {ctx.timezone}<br>"
            f"<strong>Modo:</strong> {'USB (ext4 noatime)' if ctx.usb_mode else 'Disco (Btrfs)'}<br>"
            f"<strong>Bootloader:</strong> {bl_summary}<br>"
            f"<strong>DE/WM:</strong> Hyprland · Wayland · SDDM<br>"
            f"<strong>✓ Contraseña:</strong> establecida correctamente"
        )
        done_info += multilib_skipped_notice(session)
        session.install_complete(done_info)
        session.label(session.t("label-done"))
        session.log(
            session.t(
                "log-final-banner", dev=dev, size_human=disco["size_human"],
                usuario=ctx.username, hostname=ctx.hostname, timezone=ctx.timezone,
            ), "ok",
        )

    except Exception as e:
        import traceback
        session.log(session.t("log-fatal-exception", e=e, tb=traceback.format_exc()), "err")
        session.error_step(session.t("err-unexpected", e=e))
        session.clean_mounts()
    finally:
        # Rollback ANTES de soltar _installing: api.retry no arranca mientras dure, así el
        # intento siguiente ya ve el disco y el firmware en su estado original. No lanza.
        journal.rollback(completed)
        session._installing = False

        # Red de seguridad del NOPASSWD temporal de system/aur.py. El archivo real
        # es "zz-avalos-aur-build" (antes "99-aur-build", que ya no existe): se
        # barren ambos por glob para que un cambio de nombre no vuelva a dejar
        # esta limpieza apuntando a la nada.
        for sudoers_guard in (MOUNT_ROOT / "etc" / "sudoers.d").glob("*aur-build"):
            try:
                sudoers_guard.unlink()
                session.log(session.t("log-cleanup-sudoers-ok"), "ok")
            except OSError as e:
                session.log(session.t("log-cleanup-sudoers-fail", e=e), "warn")
        session.stop_timer()
        session.finalize_log()
'''),
    # ── avalos_installer/core/logfile.py (595 líneas)
    'avalos_installer.core.logfile': (False, 'avalos_installer/core/logfile.py', r'''"""
core/logfile.py — Log persistente de la instalación (archivo de texto).

Hasta ahora todo el log vivía SOLO en la ventana pywebview (session.log →
pyLog): si la UI se cerraba, se colgaba o el instalador reventaba antes de
mostrar algo, no quedaba ninguna traza, y los reportes de hardware llegaban
como capturas o logs parciales.

Destinos — todos "best effort": ninguno puede romper ni frenar la instalación
(cada operación de disco/USB tiene manejo de errores y timeouts, y la USB
se escribe desde un hilo aparte para que una memoria lenta no bloquee al
hilo de instalación):

  1. LIVE_LOG (/tmp/avalos-install.log, RAM del live): siempre, línea a
     línea. Sobrevive a un cuelgue de la UI; no a un reinicio.
  2. La USB de arranque: <partición escribible>/AvalOS-logs/
     avalos-install-<fecha>.txt, espejado cada pocos segundos con fsync.
     Se prueba, en orden: particiones del disco de arranque que ya estén
     montadas (ej. /run/mnt/ventoy), remontándolas rw si hace falta; y
     luego las que no estén montadas (la de datos de Ventoy primero). Se
     saltan iso9660 (solo lectura) y VTOYEFI (el arranque de Ventoy).
     OJO Ventoy: con la ISO cargada por device-mapper (/dev/mapper/ventoy),
     Ventoy RESERVA EN EXCLUSIVA su partición de datos y un mount normal falla
     ("mount: ... fsconfig() failed: /dev/sda1: Can't open blockdev", visto en
     una instalación real; util-linux más viejo dice "already mounted or mount
     point busy"). Se reintenta a través de un dispositivo loop
     (`mount -o loop,rw`): el loop abre el bloque SIN exclusividad y lo que
     se monta es el loop, así que la reserva no estorba (probado con una
     reserva O_EXCL real: escribe, desmonta, el loop se autolibera y los
     datos quedan en la partición). Si tampoco así, queda un aviso en el log
     (usb_hint = "ventoy-busy").
  3. El sistema instalado: /var/log/avalos-install.log. Desde que termina el
     paso "mount" se espeja cada ~20 s (con fsync) — es el canal que
     sobrevive a un cuelgue o a un aborto aunque la USB no se pueda escribir
     (Ventoy viejo) — y se copia una última vez justo antes de desmontar
     (session.clean_mounts), incluido el camino de error.

Además captura excepciones sin capturar (hilo principal y de instalación) y
los WARNING/ERROR de `logging` (pywebview), y tacha las contraseñas que se
registren con add_secret() por si alguna llegara a colarse en una línea.
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from avalos_installer.core.buildstamp import build_id

LIVE_LOG = Path("/tmp/avalos-install.log")
USB_MOUNT_DIR = Path("/tmp/avalos_usb_log")
USB_LOG_DIRNAME = "AvalOS-logs"
TARGET_LOG_REL = Path("var/log/avalos-install.log")

# Sistemas de archivos donde se puede escribir un .txt (y leerlo después
# desde Windows/Linux). iso9660/squashfs quedan afuera a propósito.
_WRITABLE_FS = {
    "exfat", "vfat", "fat", "msdos", "ntfs", "ntfs3",
    "ext2", "ext3", "ext4", "btrfs", "f2fs", "xfs",
}
_SKIP_LABELS = {"vtoyefi"}            # partición de arranque de Ventoy: no se toca
_VENTOY_MOUNTS = ("/run/mnt/ventoy", "/mnt/ventoy", "/ventoy")
# Salidas de `mount` cuando el bloque está reservado por otro (Ventoy/device-mapper)
_CLAIMED_RE = re.compile(r"busy|blockdev|already mounted", re.IGNORECASE)

_USB_MAX_BYTES = 8 * 1024 * 1024      # tope del archivo en la USB
_USB_MIN_FREE = 4 * 1024 * 1024       # espacio libre mínimo para elegir una partición
_SYNC_INTERVAL = 2.0                  # segundos entre volcados a la USB
_TARGET_INTERVAL = 20.0               # segundos entre copias al sistema instalado
_TRUNC_MSG = (
    "\n[LOG TRUNCADO EN LA USB: se alcanzó el límite de tamaño — el log completo "
    "sigue en /tmp/avalos-install.log y en /var/log/avalos-install.log del "
    "sistema instalado]\n"
).encode("utf-8")

_LEVELS = {
    "info": "INFO", "ok": "OK", "warn": "WARN", "err": "ERR",
    "cmd": "CMD", "step": "STEP", "state": "STATE", "diag": "DIAG", "rc": "RC",
}


def _sh(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """(returncode, stdout+stderr). Nunca lanza."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return -1, f"No encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "Timeout"
    except Exception as e:  # noqa: BLE001 — el log jamás debe explotar
        return -3, str(e)


def _write_all(fh, data: bytes) -> None:
    mv = memoryview(data)
    while mv:
        n = fh.write(mv)
        if not n:
            raise OSError("write devolvió 0 bytes")
        mv = mv[n:]


def _os_release() -> dict[str, str]:
    """Campos de /etc/os-release (archiso agrega IMAGE_ID / IMAGE_VERSION: dicen
    qué ISO estaba corriendo — clave para saber si un log viene de una
    build con o sin cierto arreglo)."""
    for p in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out: dict[str, str] = {}
        for ln in text.splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, _, v = ln.partition("=")
                out[k.strip()] = v.strip().strip('"')
        return out
    return {}


class _LogBridge(logging.Handler):
    """Reenvía WARNING/ERROR del módulo logging (pywebview, GTK...) al log."""

    def __init__(self, log: "InstallLog"):
        super().__init__(level=logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            cls = "err" if record.levelno >= logging.ERROR else "warn"
            self._log.write(cls, f"[{record.name}] {record.getMessage()}")
            if record.exc_info:
                self._log.write("err", "".join(traceback.format_exception(*record.exc_info)))
        except Exception:  # noqa: BLE001
            pass


class InstallLog:
    def __init__(self, path: Path = LIVE_LOG, usb_mount_dir: Path = USB_MOUNT_DIR, run=None,
                 variant: str | None = None):
        self.path = Path(path)
        # El instalador legado de un solo archivo (scripts/skill_instalar_usb.py) lo declara con esta variable.
        self._variant = variant or os.environ.get("AVALOS_INSTALLER_VARIANT") or "modular (avalos_installer)"
        self._usb_mount_dir = Path(usb_mount_dir)
        self._run = run or _sh

        self._lock = threading.RLock()       # archivo en RAM + estado corto
        self._usb_lock = threading.Lock()    # I/O hacia la USB (puede tardar)
        self._fh = None
        self._dirty = False
        self._closed = False
        self._secrets: list[str] = []
        self._hooks_installed = False

        # Estado del espejo en la USB
        self.usb_path: Path | None = None
        self.usb_desc = ""                    # texto legible para mostrar en la UI
        self.usb_hint = ""                    # "" | "ventoy-busy"
        self.boot_disks: list[str] = []
        self._usb_fh = None
        self._usb_offset = 0                  # bytes de LIVE_LOG ya copiados
        self._usb_written = 0
        self._usb_cap = _USB_MAX_BYTES
        self._usb_failed = False
        self._usb_mounted_here: Path | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Espejo en el sistema instalado (ver set_target_root)
        self._target_root: Path | None = None
        self._target_lock = threading.RLock()
        self._target_size = -1                # bytes del log ya copiados al destino
        self._target_err = False

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._start = self.path.stat().st_size if self.path.exists() else 0
            self._fh = open(self.path, "a", buffering=1, encoding="utf-8", errors="replace")
        except OSError as e:
            self._start = 0
            print(f"[WARN] logfile: no se pudo abrir {self.path}: {e}", file=sys.stderr)
        self._write_header()
        self._thread = threading.Thread(target=self._sync_loop, name="avalos-log-sync", daemon=True)
        self._thread.start()

    # ── Escritura ────────────────────────────────────────────────────
    def add_secret(self, value) -> None:
        """Registra un valor (ej. la contraseña) que nunca debe quedar en el log."""
        v = str(value or "")
        with self._lock:
            if len(v) >= 3 and v not in self._secrets:
                # lista nueva (no .sort() in situ): otro hilo que esté
                # formateando una línea nunca ve la lista vacía a mitad de orden
                self._secrets = sorted(self._secrets + [v], key=len, reverse=True)

    def _format(self, cls: str, text) -> list[str]:
        text = str(text)
        if "\r" in text:
            # barras de progreso (pacman/curl): quedarse con el último estado
            parts = [p for p in text.split("\r") if p.strip()]
            text = parts[-1] if parts else ""
        for s in self._secrets:
            text = text.replace(s, "***")   # iterar la lista vigente: se reemplaza entera, no se muta
        stamp = datetime.now().strftime("%H:%M:%S")
        lvl = _LEVELS.get(cls, str(cls).upper()[:5])
        return [f"[{stamp}] [{lvl:<5}] {ln}" for ln in text.split("\n")]

    def _emit(self, lines: list[str]) -> None:
        with self._lock:
            if self._fh is None:
                return
            try:
                for ln in lines:
                    self._fh.write(ln + "\n")
            except (OSError, ValueError):
                self._fh = None               # el log nunca tumba la instalación
                return
            self._dirty = True

    def write(self, cls: str, text) -> None:
        try:
            self._emit(self._format(cls, text))
        except Exception:  # noqa: BLE001
            pass

    def diag(self, text) -> None:
        self.write("diag", text)

    def _write_header(self) -> None:
        efi = "UEFI" if Path("/sys/firmware/efi").exists() else "BIOS"
        osr = _os_release()
        image = osr.get("IMAGE_VERSION") or osr.get("BUILD_ID") or "?"
        self._emit([
            "=" * 72,
            "AvalOS installer — log de instalación",
            f"Inicio: {datetime.now():%Y-%m-%d %H:%M:%S} (reloj del live: puede no ser la hora real)",
            f"Instalador: {self._variant} · imagen {osr.get('IMAGE_ID', '?')} {image}",
            f"Build de AvalOS: {build_id() or 'sin sello (ISO de desarrollo)'}",
            f"Kernel {os.uname().release} · Python {platform.python_version()} · arranque {efi}",
            "=" * 72,
        ])

    def snapshot(self, reason: str, dmesg: bool = False) -> None:
        """Foto del estado de discos/montajes (y errores recientes del kernel)
        para diagnosticar problemas de hardware en el reporte."""
        self.diag(f"── snapshot: {reason} ──")
        jobs = [
            ("lsblk", ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS"]),
            ("df", ["df", "-hT", "-x", "tmpfs", "-x", "devtmpfs"]),
        ]
        if dmesg:
            jobs.append(("dmesg", ["sh", "-c", "dmesg --level=err,warn 2>/dev/null | tail -n 25"]))
        for title, cmd in jobs:
            _rc, out = self._run(cmd, 8)
            for ln in out.splitlines()[:60]:
                self.diag(f"{title}: {ln}")

    # ── Excepciones sin capturar ─────────────────────────────────────────
    def install_hooks(self) -> None:
        if self._hooks_installed:
            return
        self._hooks_installed = True
        prev_sys = sys.excepthook

        def _sys_hook(tp, val, tb):
            self.write("err", "EXCEPCIÓN SIN CAPTURAR:\n" + "".join(traceback.format_exception(tp, val, tb)))
            prev_sys(tp, val, tb)

        sys.excepthook = _sys_hook
        prev_thr = threading.excepthook

        def _thr_hook(args):
            name = args.thread.name if args.thread else "?"
            self.write(
                "err",
                f"EXCEPCIÓN SIN CAPTURAR en el hilo '{name}':\n"
                + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            )
            prev_thr(args)

        threading.excepthook = _thr_hook
        logging.getLogger().addHandler(_LogBridge(self))
        atexit.register(self.close)

    # ── Sistema instalado ────────────────────────────────────────────
    def copy_to_target(self, mount_root: Path) -> tuple[bool, str]:
        """Copia el log de esta sesión a <mount_root>/var/log/avalos-install.log.
        Devuelve (ok, detalle). Si mount_root no está montado no hace nada
        (detalle 'no montado')."""
        with self._target_lock:               # serializa con el espejo periódico
            try:
                if not os.path.ismount(mount_root):
                    return False, "no montado"
                with self._lock:
                    if self._fh is not None:
                        self._fh.flush()
                with open(self.path, "rb") as src:
                    src.seek(self._start)
                    data = src.read()
                dest = Path(mount_root) / TARGET_LOG_REL
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                dest.chmod(0o644)
                self._target_size = len(data)
                return True, "/" + str(TARGET_LOG_REL)
            except OSError as e:
                return False, str(e)

    def set_target_root(self, mount_root: Path) -> None:
        """Activa el espejo periódico en <mount_root>/var/log/avalos-install.log
        (se llama al terminar el paso 'mount': antes, /var/log puede quedar
        tapado por el montaje de su subvolumen). Es el canal que sobrevive a
        un cuelgue o a un aborto aunque la USB no se pueda escribir."""
        with self._target_lock:
            self._target_root = Path(mount_root)
            self._target_size = -1
            self._target_err = False
        self.diag(f"LOG: espejo activo en el sistema instalado ({mount_root}/{TARGET_LOG_REL})")

    def stop_target_mirror(self) -> None:
        """Detiene el espejo (clean_mounts lo llama antes de desmontar)."""
        with self._target_lock:
            self._target_root = None

    def _mirror_target(self) -> None:
        with self._target_lock:
            root = self._target_root
            if root is None:
                return
            try:
                if self.path.stat().st_size - self._start == self._target_size:
                    return                    # nada nuevo desde la última copia
            except OSError:
                return
            ok, info = self.copy_to_target(root)
            if not ok and info != "no montado" and not self._target_err:
                self._target_err = True
                self.diag(f"LOG: no se pudo espejar el log en el sistema instalado: {info}")

    # ── USB de arranque ──────────────────────────────────────────────
    def attach_usb(self) -> bool:
        """Busca una partición escribible de la USB de arranque y empieza a
        espejar el log ahí. True si quedó activo. Nunca lanza (pensado para
        correr en un hilo de fondo al iniciar el instalador)."""
        try:
            self.snapshot("inicio")
            return self._attach_usb()
        except Exception as e:  # noqa: BLE001
            self.diag(f"USB-LOG: error inesperado buscando la USB: {e!r}")
            return False

    def _mounted_fs(self) -> list[dict]:
        rc, out = self._run(["findmnt", "-rn", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], 10)
        res: list[dict] = []
        if rc != 0:
            return res
        for ln in out.splitlines():
            p = ln.split(" ")
            if len(p) < 4:
                continue
            res.append({
                "target": p[0].replace("\\x20", " "),
                "source": p[1].split("[")[0],
                "fstype": p[2],
                "opts": p[3],
            })
        return res

    def _attach_usb(self) -> bool:
        from avalos_installer.disk import bootmedium as bm

        table = bm.lsblk_table()
        src = bm.boot_source(table)
        disk = bm.disk_of(table, src) if src else ""
        self.boot_disks = [disk] if disk else []
        self.diag(f"USB-LOG: medio de arranque={src or '?'} · disco={disk or '?'}")
        is_ventoy = "ventoy" in src.lower()

        # 1) Particiones del disco de arranque que ya están montadas (o rutas
        #    conocidas de Ventoy): usarlas tal cual, remontando rw si hace falta.
        for m in self._mounted_fs():
            if self._closed:
                return False
            dev, mp, fs = m["source"], m["target"], m["fstype"]
            on_boot = bool(disk) and bm.disk_of(table, dev) == disk
            if not (on_boot or mp in _VENTOY_MOUNTS) or fs not in _WRITABLE_FS:
                continue
            label = (table.get(dev) or {}).get("label") or ""
            if label.lower() in _SKIP_LABELS:
                continue
            if "rw" not in m["opts"].split(","):
                rc, out = self._run(["mount", "-o", "remount,rw", mp], 20)
                self.diag(f"USB-LOG: remount rw {mp} → rc={rc} {out[-120:]}")
                if rc != 0:
                    continue
            if self._open_usb_file(Path(mp), f"{dev} ({label or fs})"):
                return True

        # 2) Particiones sin montar del disco de arranque (sin disco conocido
        #    no se toca ninguna: no vamos a montar discos ajenos).
        cands = []
        if disk:
            for path, node in table.items():
                if node.get("type") not in ("part", "disk") or bm.disk_of(table, path) != disk:
                    continue
                fs = node.get("fstype") or ""
                label = node.get("label") or ""
                if fs not in _WRITABLE_FS or label.lower() in _SKIP_LABELS:
                    continue
                if any(x for x in (node.get("mountpoints") or []) if x):
                    continue
                size = int(node.get("size") or 0)
                cands.append(((0 if label.lower() == "ventoy" else 1, -size), path, fs, label))
        cands.sort()
        if not cands:
            self.diag("USB-LOG: no hay particiones escribibles sin montar en el disco de arranque")

        for _rank, path, fs, label in cands:
            if self._closed:
                return False
            mp = self._usb_mount_dir
            mp.mkdir(parents=True, exist_ok=True)
            ok, out, via_loop = self._mount_partition(path, fs, mp)
            how = "OK (vía loop)" if ok and via_loop else "OK" if ok else out[-160:]
            self.diag(f"USB-LOG: mount {path} ({fs}, '{label}') → {how}")
            if not ok:
                if _CLAIMED_RE.search(out) and (is_ventoy or label.lower() == "ventoy"):
                    self.usb_hint = "ventoy-busy"
                continue
            self._usb_mounted_here = mp
            if self._open_usb_file(mp, f"{path} ({label or fs}{', vía loop' if via_loop else ''})"):
                return True
            self._umount_ours()
        return False

    def _mount_partition(self, path: str, fs: str, mp: Path) -> tuple[bool, str, bool]:
        """Monta `path` en `mp` con escritura. Devuelve (ok, salida del último
        intento, si fue vía loop). Si el mount normal falla porque el bloque
        está reservado en exclusiva (Ventoy lo reserva con device-mapper), se
        reintenta con `-o loop`: el loop abre el bloque sin exclusividad y lo
        que se monta es el loop (autoclear: se libera solo al desmontar)."""
        types = ["ntfs3", None] if fs in ("ntfs", "ntfs3") else [None]
        out = ""
        for via_loop in (False, True):
            for fstype in types:
                cmd = ["mount"] + (["-t", fstype] if fstype else []) + \
                      ["-o", "loop,rw" if via_loop else "rw", path, str(mp)]
                rc, out = self._run(cmd, 30)
                if rc == 0:
                    return True, out, via_loop
            if not via_loop:
                if not _CLAIMED_RE.search(out):
                    return False, out, False          # otro motivo: el loop no ayuda
                self.diag(f"USB-LOG: {path} está reservado en exclusiva ({out[-100:]}) — reintento vía loop")
        return False, out, True

    def _open_usb_file(self, mp: Path, desc: str) -> bool:
        if self._closed:
            return False
        try:
            st = os.statvfs(mp)
            free = st.f_bavail * st.f_frsize
            if free < _USB_MIN_FREE:
                self.diag(f"USB-LOG: {mp} descartada: solo {free // 1024} KiB libres")
                return False
            d = mp / USB_LOG_DIRNAME
            d.mkdir(exist_ok=True)
            p = d / f"avalos-install-{datetime.now():%Y%m%d-%H%M%S}.txt"
            fh = open(p, "ab", buffering=0)
            os.fsync(fh.fileno())
        except OSError as e:
            self.diag(f"USB-LOG: no se pudo escribir en {mp}: {e}")
            return False
        with self._usb_lock:
            self._usb_fh = fh
            self.usb_path = p
            self._usb_offset = self._start
            self._usb_written = 0
            self._usb_cap = min(_USB_MAX_BYTES, max(free - _USB_MIN_FREE // 2, 512 * 1024))
            self.usb_desc = f"{desc} → {USB_LOG_DIRNAME}/{p.name}"
        self.diag(f"USB-LOG: activo → {p}")
        self.sync_usb()
        return True

    def _sync_loop(self) -> None:
        last_target = time.monotonic()
        while not self._stop.wait(_SYNC_INTERVAL):
            if self._dirty and self._usb_fh is not None:
                self.sync_usb()
            if self._target_root is not None and time.monotonic() - last_target >= _TARGET_INTERVAL:
                last_target = time.monotonic()
                self._mirror_target()

    def sync_usb(self) -> None:
        """Vuelca a la USB lo escrito desde la última vez (con fsync). El
        lock del archivo en RAM se suelta antes de tocar la USB: si la
        memoria es lenta, el hilo de instalación no se entera."""
        if self._usb_fh is None or self._usb_failed:
            return
        with self._usb_lock:
            if self._usb_fh is None or self._usb_failed:
                return
            with self._lock:
                self._dirty = False
                if self._fh is not None:
                    try:
                        self._fh.flush()
                    except (OSError, ValueError):
                        pass
                try:
                    size = self.path.stat().st_size
                except OSError:
                    return
                start = self._usb_offset
            if size <= start:
                return
            try:
                with open(self.path, "rb") as src:
                    src.seek(start)
                    chunk = src.read(size - start)
                consumed = len(chunk)
                room = max(self._usb_cap - self._usb_written, 0)
                truncated = len(chunk) > room
                if truncated:
                    chunk = chunk[:room]
                _write_all(self._usb_fh, chunk)
                self._usb_written += len(chunk)
                if truncated:
                    _write_all(self._usb_fh, _TRUNC_MSG)
                    self._usb_failed = True       # no seguir espejando
                os.fsync(self._usb_fh.fileno())
                self._usb_offset = start + consumed
            except (OSError, ValueError) as e:
                self._usb_failed = True
                self.diag(
                    f"USB-LOG: falló la escritura en la USB ({e}) — se deja de espejar; "
                    f"el log completo sigue en {self.path}"
                )

    def _umount_ours(self) -> None:
        mp = self._usb_mounted_here
        if mp is None:
            return
        rc, out = self._run(["umount", str(mp)], 20)
        if rc != 0:
            rc, out = self._run(["umount", "-l", str(mp)], 20)
        self._usb_mounted_here = None
        self.diag(f"USB-LOG: umount {mp} → rc={rc}")

    def _close_usb(self) -> None:
        self.sync_usb()
        with self._usb_lock:
            fh, self._usb_fh = self._usb_fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass
        self._umount_ours()

    def close(self) -> None:
        """Pie del log + volcado final a la USB + desmontaje de lo que montamos
        nosotros (para no dejar el exFAT/FAT 'sucio' en Windows). Idempotente
        y acotado en tiempo (una USB colgada no puede bloquear el cierre)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.write("info", f"Fin del log — {datetime.now():%Y-%m-%d %H:%M:%S}")
        self._stop.set()
        self._mirror_target()                 # si el destino sigue montado, una última copia
        self.stop_target_mirror()
        try:
            t = threading.Thread(target=self._close_usb, name="avalos-usb-close", daemon=True)
            t.start()
            t.join(25)
            if t.is_alive():
                self.diag("USB-LOG: el cierre de la USB tardó más de 25 s (¿memoria lenta o colgada?)")
        except RuntimeError:
            # cierre del intérprete (atexit): ya no se pueden crear hilos
            self._close_usb()
'''),
    # ── avalos_installer/core/prereqs.py (32 líneas)
    'avalos_installer.core.prereqs': (False, 'avalos_installer/core/prereqs.py', r'''"""
core/prereqs.py — verifica que el entorno live tenga las herramientas
necesarias antes de tocar un disco.

Extraído de skill_instalar_usb.py (líneas 540-556). Sin cambios de lógica.
"""

from __future__ import annotations

import shutil

TOOLS = [
    "parted", "mkfs.fat", "mkfs.ext4", "mkfs.btrfs", "btrfs", "arch-chroot",
    "pacstrap", "genfstab", "mount", "umount",
]

TOOL_TO_PACKAGE = {
    "parted": "parted",
    "mkfs.fat": "dosfstools",
    "mkfs.ext4": "e2fsprogs",
    "mkfs.btrfs": "btrfs-progs",
    "btrfs": "btrfs-progs",
    "arch-chroot": "arch-install-scripts",
    "pacstrap": "arch-install-scripts",
    "genfstab": "arch-install-scripts",
    "mount": "util-linux",
    "umount": "util-linux",
}


def check_tools() -> dict[str, bool]:
    return {tool: shutil.which(tool) is not None for tool in TOOLS}
'''),
    # ── avalos_installer/core/runner.py (297 líneas)
    'avalos_installer.core.runner': (False, 'avalos_installer/core/runner.py', r'''"""
core/runner.py — Ejecución de comandos con salida en streaming, a prueba de
cuelgues. Lo comparten core/session.py (instalador modular) y
skill_instalar_usb.py (el instalador legado, avalos-install-old).

POR QUÉ EXISTE (bug real, reproducido en un sandbox con sudo 1.9.15):
la versión anterior de run_cmd hacía `for line in proc.stdout` y "vigilaba"
el timeout con un threading.Timer que llamaba proc.kill(). Eso falla justo
en el caso que importa, un cuelgue SILENCIOSO:

  · El lector queda bloqueado en readline(): ni el timeout ni el botón
    Cancelar se revisaban hasta que llegaba otra línea.
  · kill() mata solo al hijo directo (arch-chroot). Sus descendientes
    (sudo → bash → makepkg → sudo pacman) siguen vivos con la tubería
    abierta, así que el `for` jamás llega a EOF: el timeout de 600 s del
    bootstrap de yay no terminaba nunca (85 min colgado en "installing
    missing dependencies").
  · El hijo heredaba stdin y la terminal de control del instalador. Si el
    instalador se lanzó desde una terminal (kitty), sudo pedía la contraseña
    AHÍ — nunca en el log — y esperaba para siempre.

QUÉ HACE ESTA VERSIÓN
  · stdin=/dev/null y sesión nueva (setsid): sin terminal de control, un
    prompt interactivo falla al instante ("a terminal is required to read
    the password...") y el error queda en el log, en vez de colgarse.
  · Lee con poll(): revisa timeout y abort cada segundo aunque no llegue
    ninguna línea.
  · Al vencer el timeout o cancelar mata TODO el árbol de procesos (por
    /proc, más el grupo): SIGTERM y, tras una gracia corta, SIGKILL.
  · Si el proceso principal terminó pero un demonio (gpg-agent, dirmngr...)
    heredó la tubería y la mantiene abierta, no espera a que la cierre.
  · Aviso de inactividad: tras N segundos sin salida informa cuál es el
    proceso hoja (el que en realidad está esperando algo) y su estado, y
    entrega el árbol completo para el log de diagnóstico.

Solo usa la biblioteca estándar (el legado lo importa opcionalmente).
"""

from __future__ import annotations

import atexit
import codecs
import os
import select
import signal
import subprocess
import threading
import time
from typing import Callable, NamedTuple


class RunResult(NamedTuple):
    rc: int              # código de retorno real del proceso principal
    output: str          # todas las líneas no vacías, unidas con \n
    status: str          # "ok" | "timeout" | "aborted"


# ── Árbol de procesos (vía /proc, sin depender de psutil) ─────────────────
def _children_map() -> dict[int, list[int]]:
    """{ppid: [pid, ...]} leyendo /proc/<pid>/stat."""
    kids: dict[int, list[int]] = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return kids
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                data = f.read().decode("utf-8", "replace")
            # "pid (comm) estado ppid ...": comm puede llevar espacios y
            # paréntesis, así que se corta en el ÚLTIMO ')'.
            rest = data[data.rindex(")") + 2:].split()
            ppid = int(rest[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(name))
    return kids


def descendants(pid: int) -> list[int]:
    """Todos los descendientes de pid (hijos, nietos...), sin incluirlo."""
    kids = _children_map()
    out: list[int] = []
    stack = [pid]
    while stack:
        cur = stack.pop()
        for k in kids.get(cur, []):
            out.append(k)
            stack.append(k)
    return out


def _state(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
        return data[data.rindex(")") + 2]
    except (OSError, ValueError, IndexError):
        return ""


def _alive(pid: int) -> bool:
    st = _state(pid)
    return st != "" and st != "Z"          # un zombi ya no cuenta como vivo


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def leaf_description(pid: int) -> str:
    """El proceso hoja más profundo del árbol (siguiendo al hijo más
    reciente): el que de verdad está esperando algo. 'sudo true (S)'."""
    kids = _children_map()
    cur = pid
    while kids.get(cur):
        cur = max(kids[cur])
    cmd = _cmdline(cur) or f"pid {cur}"
    return f"{cmd[:120]} ({_state(cur) or '?'})"


def describe_tree(pid: int, max_lines: int = 25) -> list[str]:
    """Líneas 'PID PPID ESTADO ETIME WCHAN ARGS' del árbol de pid (vía ps)."""
    pids = [pid] + descendants(pid)
    try:
        r = subprocess.run(
            ["ps", "-o", "pid,ppid,stat,etime,wchan:22,args", "--no-headers",
             "-p", ",".join(map(str, pids))],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
        return [ln.rstrip()[:200] for ln in r.stdout.splitlines()[:max_lines]]
    except Exception:  # noqa: BLE001
        return []


def kill_tree(pid: int, grace: float = 3.0) -> None:
    """SIGTERM a todo el árbol (y al grupo); tras 'grace' s, SIGKILL a lo que
    siga vivo. (Un init de PID-namespace, como el de arch-chroot, ignora
    SIGTERM sin handler — de ahí el SIGKILL de respaldo.)"""
    targets = descendants(pid) + [pid]

    def send(sig: int) -> None:
        for p in targets:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            os.killpg(pid, sig)             # start_new_session ⇒ pgid == pid
        except (ProcessLookupError, PermissionError):
            pass

    send(signal.SIGTERM)
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if not any(_alive(p) for p in targets):
            return
        time.sleep(0.1)
    targets = list(dict.fromkeys(descendants(pid) + targets))   # pudieron nacer más
    send(signal.SIGKILL)


# ── Registro de procesos en curso (para matarlos al cerrar el instalador) ──
_live: dict[int, "subprocess.Popen[bytes]"] = {}
_live_lock = threading.Lock()


def kill_all(grace: float = 2.0) -> None:
    """Mata el árbol de todos los comandos en curso. Se llama al cerrar la
    ventana y al salir el intérprete: como cada comando corre en su propia
    sesión, Ctrl+C en la terminal ya no les llega solo."""
    with _live_lock:
        pids = list(_live)
    for pid in pids:
        kill_tree(pid, grace)


atexit.register(kill_all)


# ── Ejecución ────────────────────────────────────────────────────────────
def run_streaming(
    cmd: list[str],
    timeout: float | None,
    on_line: Callable[[str], None],
    should_abort: Callable[[], bool] = lambda: False,
    on_idle: Callable[[int, str, list[str]], None] | None = None,
    on_kill: Callable[[str, list[str]], None] | None = None,
    idle_first: float = 120.0,
    idle_every: float = 300.0,
    poll: float = 1.0,
) -> RunResult:
    """Corre `cmd`, entrega cada línea de stdout+stderr a `on_line` y
    devuelve un RunResult. Lanza la excepción de Popen si el comando no se
    puede ni iniciar (FileNotFoundError, PermissionError...).

    · on_idle(segundos_sin_salida, proceso_hoja, arbol) — inactividad.
    · on_kill(motivo, arbol) — justo ANTES de matar por timeout/abort
      (después el árbol ya no existe); motivo = "timeout" | "aborted".
    """
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        stdin=subprocess.DEVNULL,           # un prompt recibe EOF, no espera
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,             # sin tty de control + grupo propio
    )
    with _live_lock:
        _live[proc.pid] = proc
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    poller = select.poll()                  # poll(), no select(): sin el tope de 1024 fds
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    lines: list[str] = []
    pending = ""
    status = "ok"

    def feed(chunk: bytes) -> None:
        nonlocal pending
        # newlines universales, como el modo texto de antes: \r\n, \r y \n
        pending = (pending + dec.decode(chunk)).replace("\r\n", "\n").replace("\r", "\n")
        *complete, pending = pending.split("\n")
        for ln in complete:
            if ln:
                lines.append(ln)
                on_line(ln)
        if len(pending) > 1_000_000:        # sin saltos de línea: no crecer sin fin
            lines.append(pending)
            on_line(pending)
            pending = ""

    start = time.monotonic()
    deadline = start + timeout if timeout else float("inf")   # None/0 = sin límite
    last_out = start
    next_idle = start + idle_first
    try:
        while True:
            if should_abort():
                status = "aborted"
                break
            now = time.monotonic()
            if now >= deadline:
                status = "timeout"
                break
            if poller.poll(int(poll * 1000)):
                chunk = os.read(fd, 65536)
                if not chunk:
                    break                   # EOF: todos cerraron la tubería
                last_out = time.monotonic()
                next_idle = last_out + idle_first
                feed(chunk)
                continue
            if proc.poll() is not None:
                break                       # terminó; si algo la retiene, no se espera
            if on_idle is not None and now >= next_idle:
                on_idle(int(now - last_out), leaf_description(proc.pid), describe_tree(proc.pid))
                next_idle = now + idle_every

        if status != "ok":
            if on_kill is not None:
                on_kill(status, describe_tree(proc.pid))
            kill_tree(proc.pid)

        # Lo que haya quedado en la tubería (sin bloquear)
        while poller.poll(0):
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            feed(chunk)
        tail = pending + dec.decode(b"", final=True)
        if tail:
            lines.append(tail)
            on_line(tail)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:   # cerró stdout pero sigue corriendo
            kill_tree(proc.pid)
            proc.wait()
        return RunResult(proc.returncode, "\n".join(lines), status)
    except BaseException:
        kill_tree(proc.pid)                 # nada queda huérfano si algo falla acá
        raise
    finally:
        with _live_lock:
            _live.pop(proc.pid, None)
        try:
            proc.stdout.close()
        except OSError:
            pass
'''),
    # ── avalos_installer/core/session.py (391 líneas)
    'avalos_installer.core.session': (False, 'avalos_installer/core/session.py', r'''"""
core/session.py — InstallSession: el "kit de herramientas" operativo que
necesita cualquier paso de la instalación (hardware, disk, network, system,
desktop) para hablar con la ventana pywebview, correr comandos con streaming
en vivo, escribir archivos bajo MOUNT_ROOT y traducir mensajes.

Extraído de VentanaInstalador en skill_instalar_usb.py (líneas 2536-2749:
__init__ parcial + _js, _jsc, _log, _step, _progress, _info, _status,
_label, _t, _on_close, _run_cmd, _salida_indica_error_gpg, _run_chroot,
_run_chroot_stdin, _limpiar_montajes, _escribir, _chown_r).

DECISIÓN DE DISEÑO (no estaba en la propuesta original de módulos): esto
NO es lo mismo que InstallContext. InstallContext (todavía por construir,
depende de terminar de leer _run_instalacion) va a ser configuración pura
— username, disco, bootloader, flags — sin comportamiento. InstallSession
es comportamiento puro — cómo hablar con la UI y con el sistema — con el
mínimo de estado necesario para hacerlo (ventana, flags de aborto/cierre,
locks). Los métodos que antes eran privados de VentanaInstalador (con
guion bajo) se exponen aquí sin guion bajo porque dejan de ser detalle
interno de una sola clase y pasan a ser la API que hardware/, disk/,
network/, system/ y desktop/ van a llamar. `_js`/`_jsc` sí quedan privados
— son el mecanismo interno; el resto del código debe pasar por `log`,
`step`, etc., nunca invocar JS directo.

Lógica sin cambios respecto al original, incluidos todos los comentarios
de por qué (el chmod 644 explícito, el chown_r que ya no falla en
silencio, el manejo de abort a mitad de stream, la detección de error GPG).

Todos los identificadores (métodos, parámetros, variables locales,
atributos de instancia) se llevaron a inglés a pedido explícito — los
docstrings y comentarios se dejaron en español, ahí vive el razonamiento.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import translations

from avalos_installer.core.config import MOUNT_ROOT, MOUNT_EFI, MOUNT_ISO
from avalos_installer.core.logfile import InstallLog
from avalos_installer.core.runner import kill_all, run_streaming

if TYPE_CHECKING:
    # Solo para type hints (nunca se ejecuta en runtime — TYPE_CHECKING es
    # siempre False fuera de un chequeo estático) — preserva la misma
    # intención que ya documentaba el string quoting de abajo: sin crear
    # una dependencia de import real entre session.py y context.py, ni
    # asumir que el paquete `webview` esté disponible en este punto, pero
    # ahora sí resoluble por ruff/mypy/IDEs en vez de ser un string suelto
    # que podría quedar desincronizado si `InstallContext` se renombra.
    import webview

    from avalos_installer.core.context import InstallContext


def output_indicates_gpg_error(output: str) -> bool:
    """Detecta si la salida de pacman apunta a un problema de confianza/firma GPG
    (clave no confiable, firma inválida, keyring corrupto) en vez de un simple
    problema de conectividad."""
    if not output:
        return False
    _o = output.lower()
    _markers = (
        "unknown trust", "signature from", "invalid or corrupted",
        "keyring is not writable", "key could not be looked up",
        "pgp signature",
    )
    return any(m in _o for m in _markers)


class InstallSession:
    """Kit de herramientas operativo de una instalación en curso.

    No confundir con InstallContext (configuración elegida por el usuario).
    Esto es "cómo hacer las cosas", no "qué se eligió hacer"."""

    # pywebview expone al JS TODOS los métodos públicos de js_api y, recursivamente, de sus
    # atributos públicos (InstallerAPI.session es uno): sin esto el webview podía llamar a
    # window.pywebview.api.session.run_cmd()/run_chroot()/clean_mounts() como root. El JS del
    # wizard solo usa los métodos de InstallerAPI; pywebview salta lo que tenga
    # _serializable = False. Solo los métodos de InstallerAPI quedan visibles.
    _serializable = False

    def __init__(self, window: "webview.Window | None" = None, lang: str = "en"):
        # Log persistente (ver core/logfile.py): el archivo en RAM existe desde
        # ya, así que hasta lo que pase antes de que cargue la UI queda
        # registrado. La búsqueda de la USB de arranque corre en segundo
        # plano para no demorar el arranque de la ventana.
        self.logfile = InstallLog()
        self._usb_thread = threading.Thread(
            target=self.logfile.attach_usb, name="avalos-usb-attach", daemon=True
        )
        self._usb_thread.start()

        self.window = window
        self._closed = False
        self._aborted = False
        self._installing = False
        self._thread_started = False
        # Rollback (system/rollback.py): run_installation crea el diario en cada intento;
        # rollback_memory sobrevive a «Reintentar» (tabla original, firmware original, discos formateados).
        self.journal = None
        self.rollback_memory = None
        # Paquetes que pacstrap omitió porque multilib iba desincronizado (system/pacstrap.py): la
        # pantalla final los muestra para que el usuario los instale después.
        self.multilib_skipped: list[str] = []

        self._lang = lang

        # Coordinación con la UI para pasos que esperan input del usuario
        # a mitad de instalación (elegir mirror manualmente, etc.)
        self._config_ready = threading.Event()
        self._mirror_choice_event = threading.Event()
        self._mirror_choice: str | None = None
        self._lock = threading.Lock()

        # Handoff ui/ → core/install.py: ui.api.InstallerAPI.start_installation()
        # arma acá el InstallContext ya validado y llama self._config_ready.set().
        # El orquestador espera _config_ready y recién ahí lee pending_context.
        # No se importa InstallContext en este archivo — mismo patrón que
        # "webview.Window" arriba: type hint como string, sin crear una
        # dependencia de import real entre session.py y context.py.
        self.pending_context: "InstallContext | None" = None

    # ── Puente JS (bajo nivel, no llamar directo desde fuera) ────────────
    def _js(self, code: str):
        if self.window and not self._closed:
            try:
                self.window.evaluate_js(code)
            except Exception as e:
                print(f"[JS] {e}")
                self.logfile.write("warn", f"[JS] {e} — {code[:80]}")

    def _jsc(self, func: str, *args):
        encoded = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        self._js(f"{func}({encoded})")

    # ── API pública de logging/progreso hacia la UI ──────────────────────
    def log(self, txt: str, cls: str = "info"):
        self.logfile.write(cls, txt)
        self._jsc("pyLog", txt, cls)

    def step(self, id_: str, st: str, det: str = ""):
        self.logfile.write("state", f"{id_} → {st}" + (f" ({det})" if det else ""))
        if id_ == "mount" and st == "done":
            self.logfile.set_target_root(MOUNT_ROOT)   # espejo del log en el disco destino
        self._jsc("pyStep", id_, st, det)

    def progress(self, pct: int): self._jsc("pyProgress", pct)
    def info(self, id_: str, v: str, c: str = ""): self._jsc("pyInfo", id_, v, c)
    def status(self, msg: str):
        self.logfile.write("state", f"estado: {msg}")
        self._jsc("pyStatus", msg)
    def label(self, txt: str): self._jsc("pyStatusLabel", txt)

    # ── Señales específicas que el monolito manda directo por _jsc (desde
    # _run_instalacion o desde InstaladorAPI, ej. on_ready) y que nunca
    # tuvieron wrapper propio ahí. Se agregan acá a medida que se van
    # necesitando durante la extracción de cada paso/módulo — no se
    # adivinaron todas de una vez, se confirman contra el código real
    # según se extrae.
    def error_step(self, msg: str):
        self.logfile.write("err", f"ERROR DE PASO: {msg}")
        self._jsc("pyErrorPaso", msg)
        self.logfile.snapshot("error de paso", dmesg=True)

    def error_fatal(self, msg: str):
        self.logfile.write("err", f"ERROR FATAL: {msg}")
        self._jsc("pyErrorFatal", msg)
        self.logfile.snapshot("error fatal", dmesg=True)
    def badges(self, net_ok: bool | None, uefi: bool): self._jsc("pyBadges", net_ok, uefi)
    def countdown_start(self, dev: str, model: str, size_human: str):
        self._jsc("pyIniciarCountdown", dev, model, size_human)
    def countdown_tick(self, seconds_left: int): self._jsc("pyActualizarCountdown", seconds_left)
    def countdown_cancel(self): self._jsc("pyCerrarCountdown")
    def mirror_dialog(self, detail: str): self._jsc("pyMirrorDialog", detail)
    def install_complete(self, summary_html: str): self._jsc("pyInstalacionCompleta", summary_html)

    def render_disks(self, disks: list[dict]):
        """Usado por ui.api.InstallerAPI.on_ready(). El original hace
        json.dumps(discos) ANTES de pasarlo a _jsc — que a su vez vuelve a
        codificar cada argumento — a propósito: el JS de pyRenderDiscos
        espera recibir un string y lo parsea él mismo (JSON.parse) del
        lado JS, no un array ya materializado. Se preserva ese doble
        encoding tal cual, no es un bug."""
        self._jsc("pyRenderDiscos", json.dumps(disks, ensure_ascii=False))

    def start_timer(self): self._jsc("pyStartTimer")
    def stop_timer(self): self._jsc("pyStopTimer")

    def t(self, key: str, **kwargs) -> str:
        """Traduce 'key' al idioma elegido por el usuario (self._lang) y
        aplica .format(**kwargs) para los textos con partes dinámicas
        (rutas, nombres de disco, mensajes de excepción, etc. — esas partes
        NUNCA se traducen, solo el texto que las rodea).
        Fallback en cadena: idioma actual → inglés → la propia key (nunca
        debe explotar el log de instalación por una clave faltante)."""
        _translations = translations.TRANSLATIONS.get(self._lang, translations.TRANSLATIONS["en"])
        template = _translations.get(key) or translations.TRANSLATIONS["en"].get(key) or key
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def on_close(self):
        self._closed = True
        self._aborted = True
        self._config_ready.set()
        kill_all()                        # cada comando corre en su propia sesión: no reciben Ctrl+C solos
        self.finalize_log()

    # ── Log persistente ──────────────────────────────────────────
    def report_log_destinations(self):
        """Avisa en el log de la UI dónde quedó guardado el log. Espera (acotado)
        a que termine la búsqueda de la USB de arranque."""
        th = getattr(self, "_usb_thread", None)
        if th is not None:
            th.join(timeout=20)
        self.log(self.t("log-file-live", path=str(self.logfile.path)), "info")
        if self.logfile.usb_desc:
            self.log(self.t("log-file-usb-ok", desc=self.logfile.usb_desc), "ok")
        else:
            self.log(self.t("log-file-usb-none"), "warn")
            if self.logfile.usb_hint == "ventoy-busy":
                self.log(self.t("log-file-usb-ventoy-busy"), "warn")

    def finalize_log(self):
        """Volcado final a la USB y desmontaje de lo que montó el log. Idempotente."""
        self.logfile.close()

    # ── Ejecución de comandos ─────────────────────────────────────────────
    def run_cmd(self, cmd: list[str], timeout: int = 300,
                log_cls: str = "info",
                pre_mkdir: str | None = None,
                abortable: bool = True) -> tuple[int, str]:
        """Corre un comando en el live, transmite su salida al log y deja el
        código de retorno (y cuánto tardó) en el archivo de log — antes el
        rc solo lo veía quien lo consultaba en el código.

        abortable=False hace que ignore el botón Cancelar. Es solo para la limpieza
        (clean_mounts): con _aborted ya en True, run_streaming mata cualquier comando en su
        primera vuelta, así que los umount de la limpieza posterior a un Cancelar nunca
        corrían y el destino quedaba montado (y "Reintentar" chocaba con esos montajes)."""
        t0 = time.monotonic()
        rc, out = self._run_cmd_raw(cmd, timeout=timeout, log_cls=log_cls, pre_mkdir=pre_mkdir,
                                    abortable=abortable)
        self.logfile.write("rc", f"rc={rc} ({time.monotonic() - t0:.1f}s) {' '.join(map(str, cmd))[:160]}")
        return rc, out

    def _run_cmd_raw(self, cmd: list[str], timeout: int = 300,
                     log_cls: str = "info",
                     pre_mkdir: str | None = None,
                     abortable: bool = True) -> tuple[int, str]:
        """Ejecuta `cmd` en streaming (ver core/runner.py: timeout y Cancelar
        reales sobre todo el árbol de procesos, stdin=/dev/null, sin terminal
        de control). Devuelve (rc, salida); -2 timeout, -99 cancelado, -3
        excepción — igual que antes."""
        if pre_mkdir:
            Path(pre_mkdir).mkdir(parents=True, exist_ok=True)
        cmd = [str(c) for c in cmd]
        self.log(f"$ {' '.join(cmd)}", "cmd")

        def _idle(secs: int, leaf: str, tree: list[str]) -> None:
            self.log(self.t("log-cmd-idle", secs=secs, proc=leaf), "warn")
            for ln in tree:
                self.logfile.diag(f"árbol: {ln}")

        def _kill(reason: str, tree: list[str]) -> None:
            self.logfile.diag(f"árbol de procesos justo antes de matarlo ({reason}):")
            for ln in tree:
                self.logfile.diag(f"árbol: {ln}")

        try:
            res = run_streaming(
                cmd, timeout,
                on_line=lambda ln: self.log(ln, log_cls),
                should_abort=(lambda: self._aborted) if abortable else (lambda: False),
                on_idle=_idle, on_kill=_kill,
            )
        except Exception as e:
            self.log(self.t("log-exception", e=e), "err")
            return -3, ""
        if res.status == "aborted":
            return -99, res.output
        if res.status == "timeout":
            self.log(self.t("log-timeout-proc", timeout=timeout), "err")
            return -2, res.output
        return res.rc, res.output

    def run_chroot(self, cmd: list[str], timeout: int = 300,
                    systemd_mode: bool = False) -> tuple[int, str]:
        """systemd_mode=True agrega '-S' a arch-chroot (modo systemd real,
        via systemd-run/nspawn en vez de un chroot+namespace plano). Hace
        falta para que bootctl no se abstenga de tocar variables EFI
        dentro del chroot (ver system/bootloader.py, rama sd-boot) — sin
        esto bootctl detecta que corre en un namespace de PID y se salta
        la creación de la entrada NVRAM en silencio, con rc=0 igual.

        NO usar systemd_mode=True como default general: -S es un flag
        relativamente nuevo de arch-install-scripts (agregado en algún
        punto de 2025) y hay reportes de 'invalid option' en versiones
        de archiso más viejas — el llamador debe estar preparado para
        reintentar sin systemd_mode si esto falla por esa razón
        específica (ver el patrón en install_bootloader)."""
        cmd_prefix = ["arch-chroot"] + (["-S"] if systemd_mode else []) + [str(MOUNT_ROOT)]
        return self.run_cmd(cmd_prefix + cmd, timeout=timeout)

    def run_chroot_stdin(self, stdin_data: str, cmd: list[str], timeout: int = 60) -> tuple[int, str]:
        """Ejecuta un comando en chroot pasando datos sensibles por stdin (ej: chpasswd)."""
        full_cmd = ["arch-chroot", str(MOUNT_ROOT)] + cmd
        try:
            proc = subprocess.run(
                full_cmd, input=stdin_data, capture_output=True, text=True, timeout=timeout,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            self.logfile.write("rc", f"rc={proc.returncode} [stdin] {' '.join(map(str, cmd))[:80]}")
            return proc.returncode, out.strip()
        except subprocess.TimeoutExpired:
            self.log(self.t("log-timeout-cmd", timeout=timeout, cmd0=cmd[0]), "err")
            return -2, ""
        except Exception as e:
            self.log(self.t("log-exception", e=e), "err")
            return -3, ""

    def clean_mounts(self):
        self.log(self.t("log-cleaning-mounts"), "warn")
        # El log viaja con el sistema: se copia a /var/log/avalos-install.log
        # del destino justo antes de desmontarlo. Este método también corre en
        # cada camino de error, así que un fallo a mitad de instalación deja
        # su log en el disco (si llegó a montarse).
        self.logfile.stop_target_mirror()
        ok, info = self.logfile.copy_to_target(MOUNT_ROOT)
        if ok:
            self.log(self.t("log-file-target-ok", path=info), "ok")
        elif info != "no montado":
            self.log(self.t("log-file-target-fail", e=info), "warn")
        # Escribir a disco ANTES de los umount -l: el desmontaje diferido no sincroniza, y en
        # instalaciones a USB (ext4) quitar el pendrive al terminar dejaba datos en la caché.
        self.run_cmd(["sync"], timeout=120, abortable=False)
        mount_points = [
            str(MOUNT_EFI),
            str(MOUNT_ROOT / "boot"),
            str(MOUNT_ROOT / "proc"),
            str(MOUNT_ROOT / "sys" / "firmware" / "efi" / "efivars"),
            str(MOUNT_ROOT / "sys"),
            str(MOUNT_ROOT / "dev" / "pts"),
            str(MOUNT_ROOT / "dev"),
            str(MOUNT_ROOT / "run"),
            str(MOUNT_ROOT / "tmp"),
            str(MOUNT_ROOT / "var" / "cache"),
            str(MOUNT_ROOT / "var" / "log"),
            str(MOUNT_ROOT / ".snapshots"),
            str(MOUNT_ROOT / "home"),
            str(MOUNT_ROOT),
            str(MOUNT_ISO),
        ]
        for point in mount_points:
            if Path(point).is_mount():
                rc, _ = self.run_cmd(["umount", "-l", point], abortable=False)
                if rc == 0:
                    self.log(self.t("log-unmounted", p=point), "ok")

    def write_file(self, relative_path: str, content: str):
        dest = MOUNT_ROOT / relative_path.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        # Modo explicito: dest.write_text() hereda el umask del proceso (root,
        # instalador). Si ese umask es mas restrictivo que 022 (022 -> 644,
        # world-readable), el archivo queda sin bit de lectura para "other" Y
        # el chown_r de mas abajo SOLO arregla dueño, nunca modo -- si por lo
        # que sea ese chown no llega a cubrir este archivo a tiempo, el dueño
        # real (root, todavia) + modo restrictivo = exactamente "Permission
        # denied" para el usuario real al leer su propio hyprland.lua. Fijar
        # 644 aca hace que la lectura no dependa de NINGUNA de las dos cosas.
        dest.chmod(0o644)
        self.log(self.t("log-written", ruta=relative_path), "ok")

    def chown_r(self, path: str, user: str):
        rc, out = self.run_chroot(["chown", "-R", f"{user}:{user}", path])
        if rc != 0:
            # Antes esto fallaba en silencio -- sin rc ni log, no habia forma
            # de notar (ni de diagnosticar) un home mal dueño hasta que el
            # usuario ya estaba adentro con la sesion rota.
            self.log(self.t("log-chown-r-fail", ruta=path, rc=rc, out=out.strip()[-300:]), "warn")
        return rc
'''),
    # ── avalos_installer/core/shell.py (39 líneas)
    'avalos_installer.core.shell': (False, 'avalos_installer/core/shell.py', r'''"""
core/shell.py — utilidad de bajo nivel compartida por todos los módulos
del instalador modular.

Extraído de skill_instalar_usb.py (era `_ejecutar`, línea 254). Se renombra
a público (`run_command`, antes `ejecutar`) porque deja de ser un helper
privado de un solo archivo y pasa a ser la implementación compartida que
hardware/, disk/, network/ y system/ importan. El comportamiento es
idéntico al original, no se tocó la lógica.
"""

from __future__ import annotations

import subprocess


def run_command(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Corre un comando y devuelve (returncode, stdout, stderr).

    Nunca lanza excepción: comando no encontrado, timeout, y cualquier otro
    error quedan codificados en el returncode (-1, -2, -3 respectivamente)
    con el mensaje en stderr, para que el llamador no necesite try/except.
    """
    try:
        # stdin=DEVNULL: un prompt interactivo recibe EOF en vez de quedarse esperando en la
        # terminal desde la que se lanzó el instalador (mismo criterio que core/runner.py).
        # errors="replace": un byte no-UTF-8 (p. ej. el modelo de un disco en lsblk) no debe
        # tumbar toda la salida con UnicodeDecodeError -> rc -3 -> "no hay discos".
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, errors="replace",
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"No encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", "Timeout"
    except Exception as e:
        return -3, "", str(e)
'''),
    # ── avalos_installer/desktop/__init__.py (0 líneas)
    'avalos_installer.desktop': (True, 'avalos_installer/desktop/__init__.py', r''''''),
    # ── avalos_installer/desktop/hyprland.py (305 líneas)
    'avalos_installer.desktop.hyprland': (False, 'avalos_installer/desktop/hyprland.py', r'''"""
desktop/hyprland.py — configuración completa del escritorio (Hyprland,
SDDM, Waybar, Mako, Rofi, Kitty, GTK, fastfetch) del sistema recién
instalado.

Extraído de VentanaInstalador._configurar_hyprland en skill_instalar_usb.py
(líneas 3043-3332). Lógica y comentarios explicativos sin cambios — incluye
el fix de BUG-8 (separador QT_QPA_PLATFORM), el fallback de wallpaper
generado a mano si no hay uno embebido, y la nota sobre por qué se instala
tanto hyprland.desktop como hyprland-uwsm.desktop.

Cambios respecto al original (solo de forma, no de lógica):
- `self.X` → `session.X` (ver core/session.py — InstallSession)
- `self._keymap` → parámetro `keymap` (es config del usuario, no del
  session; hasta que exista InstallContext, el llamador pasa ctx.keymap)
- `self._lang` → parámetro `lang`, mismo motivo
- `_leer_config` (privada del monolito) → `read_config` (core.config)
- todos los identificadores restantes → inglés (usuario→user, etc.)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import translations

from avalos_installer.core.config import MOUNT_ROOT, MIRROR_COUNTRIES, read_config, VCONSOLE_TO_XKB
from avalos_installer.core.session import InstallSession


def configure_hyprland(session: InstallSession, user: str, gpu_info: dict,
                        keymap: str, lang: str):
    home = f"home/{user}"

    _gpu_vendor = gpu_info.get("vendor", "amd")
    if _gpu_vendor == "intel":
        _gpu_env = "LIBVA_DRIVER_NAME=iHD\nVDPAU_DRIVER=va_gl\n"
    else:
        _gpu_env = "VDPAU_DRIVER=radeonsi\nLIBVA_DRIVER_NAME=radeonsi\n"

    session.write_file("etc/environment", f"""\
# BUG-8 FIX: separador ':' en vez de ';' en QT_QPA_PLATFORM.
# Qt parsea esta variable como lista separada por ';' (no ':') de plugins
# de plataforma a probar en orden, con fallback al siguiente si el primero
# no carga. Con ':', Qt busca un plugin llamado literalmente "wayland:xcb",
# no lo encuentra, y cae a su comportamiento por defecto — rompiendo el
# fallback wayland→xcb para toda app Qt que lea /etc/environment (vía PAM/
# systemd), aunque hl.env() en hyprland.lua sí lo tenga bien con ';'.
QT_QPA_PLATFORM=wayland;xcb
QT_AUTO_SCREEN_SCALE_FACTOR=1
QT_WAYLAND_DISABLE_WINDOWDECORATION=1
GDK_BACKEND=wayland,x11
SDL_VIDEODRIVER=wayland,x11
CLUTTER_BACKEND=wayland
MOZ_ENABLE_WAYLAND=1
ELECTRON_OZONE_PLATFORM_HINT=auto
XDG_SESSION_TYPE=wayland
XDG_SESSION_DESKTOP=Hyprland
XDG_CURRENT_DESKTOP=Hyprland
{_gpu_env}__GLX_VENDOR_LIBRARY_NAME=mesa
""")

    _gpu_env_amd = ('hl.env("AMD_VULKAN_ICD",    "RADV")\n'
                    'hl.env("VDPAU_DRIVER",      "radeonsi")\n'
                    'hl.env("LIBVA_DRIVER_NAME", "radeonsi")')
    _gpu_env_intel = ('hl.env("LIBVA_DRIVER_NAME", "iHD")\n'
                       'hl.env("VDPAU_DRIVER",      "va_gl")')
    _gpu_env_body = _gpu_env_amd if _gpu_vendor == "amd" else _gpu_env_intel
    _gpu_env_str = (
        "-- AVALOS_GPU_ENV_START\n"
        f"{_gpu_env_body}\n"
        "-- AVALOS_GPU_ENV_END"
    )

    _hypr_tmpl = read_config("hyprland/hyprland_conf_lua.template")
    if _hypr_tmpl:
        session.write_file(f"{home}/.config/hypr/hyprland.lua",
                            _hypr_tmpl.replace("%%GPU_ENV%%", _gpu_env_str)
                            .replace("%%KEYMAP%%", VCONSOLE_TO_XKB.get(keymap, keymap)))
    else:
        session.log(session.t("log-hyprland-template-missing"), "err")
        raise RuntimeError(
            "hyprland_conf_lua.template no encontrado en /usr/share/avalos/configs/hyprland/.\n"
            "La imagen ISO está incompleta — reconstruye con build-iso.yml."
        )

    _content = read_config("hyprland/hyprpaper.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hyprpaper.conf", _content)
    else:
        session.write_file(f"{home}/.config/hypr/hyprpaper.conf",
                            "wallpaper {\n    monitor =\n"
                            "    path = ~/.config/hypr/wallpaper.png\n"
                            "    fit_mode = cover\n}\nsplash = false\nipc = on\n")

    wp_path = MOUNT_ROOT / f"{home}/.config/hypr/wallpaper.png"
    _default_wp = Path("/usr/share/avalos/wallpaper-default.png")
    try:
        if _default_wp.is_file():
            wp_path.write_bytes(_default_wp.read_bytes())
            session.log(session.t("log-wallpaper-copied"), "ok")
        else:
            import struct as _struct, zlib as _zlib

            def _make_chunk(tag, data):
                crc = _zlib.crc32(tag + data) & 0xffffffff
                return _struct.pack('>I', len(data)) + tag + data + _struct.pack('>I', crc)

            _w, _h, _r, _g, _b = 1920, 1080, 26, 27, 38
            _rows = (b'\x00' + bytes([_r, _g, _b]) * _w) * _h
            _png = (
                b'\x89PNG\r\n\x1a\n'
                + _make_chunk(b'IHDR', _struct.pack('>IIBBBBB', _w, _h, 8, 2, 0, 0, 0))
                + _make_chunk(b'IDAT', _zlib.compress(_rows, 9))
                + _make_chunk(b'IEND', b'')
            )
            wp_path.write_bytes(_png)
            session.log(session.t("log-wallpaper-fallback"), "warn")
    except Exception as _e:
        session.log(f"  [WARN] wallpaper: {_e}", "warn")

    _content = read_config("hyprland/hypridle.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hypridle.conf", _content)
    else:
        session.log(session.t("log-hypridle-missing"), "warn")

    _content = read_config("hyprland/hyprlock.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hyprlock.conf", _content)
    else:
        session.log(session.t("log-hyprlock-missing"), "warn")

    _content = read_config("waybar/config.jsonc")
    if _content:
        session.write_file(f"{home}/.config/waybar/config.jsonc", _content)
    else:
        session.log(session.t("log-waybar-config-missing"), "warn")

    _content = read_config("waybar/style.css")
    if _content:
        session.write_file(f"{home}/.config/waybar/style.css", _content)
    else:
        session.log(session.t("log-waybar-style-missing"), "warn")

    _content = read_config("mako/config")
    if _content:
        session.write_file(f"{home}/.config/mako/config", _content)

    _content = read_config("rofi/config.rasi")
    if _content:
        session.write_file(f"{home}/.config/rofi/config.rasi", _content)

    _content = read_config("rofi/powermenu.sh")
    if _content:
        session.write_file(f"{home}/.config/rofi/scripts/powermenu.sh", _content)
    try:
        (MOUNT_ROOT / f"{home}/.config/rofi/scripts/powermenu.sh").chmod(0o755)
    except OSError as e:
        session.log(session.t("log-chmod-powermenu-fail", e=e), "warn")

    _content = read_config("kitty/kitty.conf")
    if _content:
        session.write_file(f"{home}/.config/kitty/kitty.conf", _content)

    _sddm_qml_tpl = read_config("sddm/Main.qml")
    _sddm_meta = read_config("sddm/metadata.desktop")
    if _sddm_qml_tpl and _sddm_meta:
        _sddm_translations = translations.TRANSLATIONS.get(lang, translations.TRANSLATIONS["en"])
        _sddm_qml = (_sddm_qml_tpl
                     .replace("%%SDDM_USER%%", _sddm_translations.get("lbl-user", "Username"))
                     .replace("%%SDDM_PASS%%", _sddm_translations.get("lbl-pass", "Password"))
                     .replace("%%SDDM_SIGNIN%%", _sddm_translations.get("sddm-signin", "Sign In"))
                     .replace("%%SDDM_FAIL%%", _sddm_translations.get("sddm-fail", "Authentication failed. Try again."))
                     .replace("%%SDDM_SESSION%%", _sddm_translations.get("sddm-session", "Session"))
                     .replace("%%SDDM_SUSPEND%%", _sddm_translations.get("sddm-suspend", "Suspend"))
                     .replace("%%SDDM_RESTART%%", _sddm_translations.get("sddm-restart", "Restart"))
                     .replace("%%SDDM_SHUTDOWN%%", _sddm_translations.get("sddm-shutdown", "Shutdown")))
        _sddm_dir = MOUNT_ROOT / "usr" / "share" / "sddm" / "themes" / "avalos"
        _sddm_dir.mkdir(parents=True, exist_ok=True)
        (_sddm_dir / "metadata.desktop").write_text(_sddm_meta, encoding="utf-8")
        (_sddm_dir / "Main.qml").write_text(_sddm_qml, encoding="utf-8")
        session.log(session.t("log-sddm-theme-installed"), "ok")
    else:
        # No deberia pasar nunca si build-iso.yml copio bien configs/ al
        # live (mismo mecanismo que ya usan kitty.conf, powermenu.sh,
        # etc. mas arriba) -- si aparece, es señal de que configs/sddm/
        # no llego al ISO, no de que el tema este mal.
        session.log("[WARN] configs/sddm/Main.qml o metadata.desktop no encontrados en /usr/share/avalos/configs — tema SDDM no instalado", "warn")

    session.write_file("etc/sddm.conf.d/hyprland.conf", """\
[Theme]
Current=avalos

[Wayland]
EnableHiDPI=true

[General]
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
""")

    # FIX: antes escribíamos hyprland.desktop y hyprland-uwsm.desktop acá a
    # mano, copiados de un log de foro puntual (ver git blame). El paquete
    # oficial 'hyprland' de Arch YA instala esos dos archivos exactos en
    # usr/share/wayland-sessions/ (confirmado contra el listado real del
    # paquete), mantenidos por los propios desarrolladores de Hyprland —
    # sobreescribirlos con una copia nuestra los deja desactualizados apenas
    # upstream cambia el invocado correcto de uwsm (que de hecho ya cambió:
    # el ArchWiki actual dice que uwsm "ya no se recomienda, se considera
    # experimental", justo lo contrario de lo que decía nuestro comentario
    # viejo). Confirmado en hardware real (Sept. 2026): con nuestra copia,
    # el warning "Hyprland was started without start-hyprland" salía tanto
    # en la sesión plana como en la de uwsm — dejar de pisar los archivos
    # del paquete es la corrección real, no un ajuste al contenido.

    _gtk_fallback = """\
[Settings]
gtk-theme-name = Adwaita-dark
gtk-icon-theme-name = Papirus-Dark
gtk-font-name = JetBrainsMono Nerd Font 11
gtk-cursor-theme-name = capitaine-cursors
gtk-cursor-theme-size = 24
gtk-application-prefer-dark-theme = true
"""
    for gtk_ver in ("gtk-3.0", "gtk-4.0"):
        # Prioriza configs/gtk/settings.ini del repo (mismo patron que
        # hyprland/waybar/mako/etc mas arriba); si no existe todavia en
        # /usr/share/avalos/configs/gtk/, usa el default de siempre --
        # asi no se rompe nada aunque configs/gtk/ aun no este conectado.
        _gtk_content = read_config("gtk/settings.ini") or _gtk_fallback
        session.write_file(f"{home}/.config/{gtk_ver}/settings.ini", _gtk_content)

    bashrc_extra = """\

# ── AvalOS / Wayland ────────────────────────────────
export QT_QPA_PLATFORM="wayland;xcb"
export MOZ_ENABLE_WAYLAND=1
export ELECTRON_OZONE_PLATFORM_HINT=auto
export XDG_SESSION_TYPE=wayland
"""
    bashrc_path = MOUNT_ROOT / f"{home}/.bashrc"
    try:
        existing = bashrc_path.read_text(encoding="utf-8") if bashrc_path.exists() else ""
        bashrc_path.write_text(existing + bashrc_extra, encoding="utf-8")
    except OSError as e:
        session.log(f"[WARN] .bashrc: {e}", "warn")

    _content = read_config("fastfetch/config.jsonc")
    if _content:
        _translations = translations.TRANSLATIONS.get(lang, translations.TRANSLATIONS["en"])
        _ff_keys = {
            '" OS"': f'"{_translations.get("ff-os", " OS")}"',
            '"\\uf0e4 Host"': f'"{_translations.get("ff-host", "\\uf0e4 Host")}"',
            '" Kernel"': f'"{_translations.get("ff-kernel", " Kernel")}"',
            '"\\uf55f Uptime"': f'"{_translations.get("ff-uptime", "\\uf55f Uptime")}"',
            '"\\uf439 Packages"': f'"{_translations.get("ff-packages", "\\uf439 Packages")}"',
            '" Shell"': f'"{_translations.get("ff-shell", " Shell")}"',
            '"\\uf879 Resolution"': f'"{_translations.get("ff-display", "\\uf879 Resolution")}"',
            '" WM"': f'"{_translations.get("ff-wm", " WM")}"',
            '" Terminal"': f'"{_translations.get("ff-terminal", " Terminal")}"',
            '" CPU"': f'"{_translations.get("ff-cpu", " CPU")}"',
            '"\\uf43f GPU"': f'"{_translations.get("ff-gpu", "\\uf43f GPU")}"',
            '"\\uf4cb Disk"': f'"{_translations.get("ff-disk", "\\uf4cb Disk")}"',
            '"\\uf55b RAM"': f'"{_translations.get("ff-ram", "\\uf55b RAM")}"',
        }
        for _old_k, _new_k in _ff_keys.items():
            _content = _content.replace(_old_k, _new_k)
        session.write_file(f"{home}/.config/fastfetch/config.jsonc", _content)

    _src_logo = Path("/etc/fastfetch/avalos.txt")
    _dst_logo = MOUNT_ROOT / "etc" / "fastfetch" / "avalos.txt"
    _dst_logo.parent.mkdir(parents=True, exist_ok=True)
    if _src_logo.exists():
        shutil.copy2(_src_logo, _dst_logo)
        session.log(session.t("log-fastfetch-logo-copied"))
    else:
        session.log(session.t("log-fastfetch-logo-missing"), "warn")

    session.chown_r(f"/home/{user}", user)

    ref_conf = MOUNT_ROOT / "etc" / "xdg" / "reflector" / "reflector.conf"
    ref_conf.parent.mkdir(parents=True, exist_ok=True)
    ref_conf.write_text(f"--country {MIRROR_COUNTRIES}\n--latest 10\n--sort rate\n--protocol https\n")
    session.run_chroot(["systemctl", "enable", "reflector.timer"])

    linger = MOUNT_ROOT / "etc/systemd/system/avalos-enable-linger.service"
    linger.parent.mkdir(parents=True, exist_ok=True)
    linger.write_text(f"""\
[Unit]
Description=Enable linger for {user} (PipeWire user services)
After=systemd-logind.service
ConditionPathExists=!/var/lib/systemd/linger/{user}

[Service]
Type=oneshot
ExecStart=/usr/bin/loginctl enable-linger {user}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
""")
    session.run_chroot(["systemctl", "enable", "avalos-enable-linger.service"])
    session.log(session.t("log-hyprland-ok"), "ok")
'''),
    # ── avalos_installer/disk/__init__.py (0 líneas)
    'avalos_installer.disk': (True, 'avalos_installer/disk/__init__.py', r''''''),
    # ── avalos_installer/disk/bootmedium.py (147 líneas)
    'avalos_installer.disk.bootmedium': (False, 'avalos_installer/disk/bootmedium.py', r'''"""
disk/bootmedium.py — ¿De qué disco físico arrancó el live?

Lo usan dos cosas:
  · disk.discovery.detect_boot_disk(): marcar (y bloquear como destino) el
    disco de arranque.
  · core.logfile.InstallLog: guardar el log en la MISMA USB desde la que
    corre el instalador.

Por qué no alcanza con mirar el origen de "/": en el live de archiso "/" es
un overlay ("airootfs"), no un dispositivo de bloque. La lógica anterior
devolvía "airootfs" y el disco de arranque nunca se marcaba como tal. El
medio real está montado (solo lectura) en /run/archiso/bootmnt. Casos que
cubre este módulo:

  · USB con `dd`/Etcher/Rufus modo DD: bootmnt = /dev/sdb1 (iso9660).
  · Ventoy: bootmnt = /dev/mapper/ventoy (dm-linear sobre la USB); hay que
    subir por PKNAME hasta el disco físico.
  · copytoram=y: archiso desmonta bootmnt — se vuelve a la cmdline
    (archisodevice / archisosearchuuid / archisolabel).
  · ISO cargada por loop desde un archivo: se resuelve el dispositivo que
    contiene ese archivo.
  · Máquina virtual con la ISO como CD-ROM (tipo "rom"): no hay disco
    físico que excluir → lista vacía (mismo comportamiento que antes).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from avalos_installer.core.shell import run_command

BOOTMNT = "/run/archiso/bootmnt"
_COLS = "NAME,TYPE,PKNAME,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINTS"


def lsblk_table() -> dict[str, dict]:
    """Todos los dispositivos de bloque, indexados por path completo
    (/dev/sdb1, /dev/mapper/ventoy, ...). Vacío si lsblk falla."""
    rc, out, _ = run_command(["lsblk", "-J", "-b", "-p", "-o", _COLS])
    table: dict[str, dict] = {}
    if rc != 0 or not out:
        return table
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return table

    def walk(node: dict) -> None:
        name = node.get("name")
        if name:
            table.setdefault(name, node)
        for child in node.get("children") or []:
            walk(child)

    for node in data.get("blockdevices", []):
        walk(node)
    return table


def _cmdline() -> dict[str, str]:
    try:
        raw = Path("/proc/cmdline").read_text().split()
    except OSError:
        return {}
    return dict(a.split("=", 1) for a in raw if "=" in a)


def _resolve_spec(spec: str, table: dict[str, dict]) -> str:
    """archisodevice puede ser /dev/..., UUID=..., LABEL=... o un symlink
    /dev/disk/by-*/... (su valor por defecto es /dev/disk/by-label/<label>).
    Devuelve el path real que figura en la tabla de lsblk, o ''."""
    kind, _, val = spec.partition("=")
    if val and kind.upper() in ("UUID", "LABEL"):
        col = kind.lower()
        for path, node in table.items():
            got = node.get(col) or ""
            if got == val or (col == "uuid" and got.lower() == val.lower()):
                return path
        return ""
    real = os.path.realpath(spec)
    return real if real in table else ""


def boot_source(table: dict[str, dict]) -> str:
    """Dispositivo que contiene el medio de arranque ('' si no se pudo
    determinar). Orden: el montaje real de archiso; si no está (copytoram),
    los parámetros de arranque en el orden en que los aplica archiso
    (archisosearchuuid pisa a archisodevice)."""
    rc, out, _ = run_command(["findmnt", "-n", "-o", "SOURCE", BOOTMNT])
    if rc == 0 and out:
        return out.split("[")[0].strip()
    kv = _cmdline()
    uuid = kv.get("archisosearchuuid")
    if uuid:
        dev = _resolve_spec(f"UUID={uuid}", table)
        if dev:
            return dev
    if kv.get("archisodevice"):
        dev = _resolve_spec(kv["archisodevice"], table)
        if dev:
            return dev
    if kv.get("archisolabel"):
        return _resolve_spec(f"LABEL={kv['archisolabel']}", table)
    return ""


def _loop_backing_device(loop_dev: str) -> str:
    """Dispositivo que contiene el archivo respaldando un /dev/loopN."""
    rc, out, _ = run_command(["losetup", "-nO", "BACK-FILE", loop_dev])
    if rc != 0 or not out:
        return ""
    rc, src, _ = run_command(["findmnt", "-n", "-o", "SOURCE", "-T", out.strip()])
    return src.split("[")[0].strip() if rc == 0 else ""


def disk_of(table: dict[str, dict], path: str) -> str:
    """Sube por PKNAME (partición → disco, dm → partición/disco, loop →
    dispositivo del archivo) hasta el disco físico. Devuelve su NOMBRE sin
    /dev/ (ej. 'sdb', 'nvme0n1'), o '' si no llega a ningún disco."""
    seen: set[str] = set()
    node = table.get(path)
    while node is not None and node.get("name") not in seen:
        seen.add(node.get("name"))
        typ = node.get("type")
        if typ == "disk":
            return str(node["name"]).removeprefix("/dev/")
        if typ == "loop":
            back = _loop_backing_device(node["name"])
            node = table.get(back) if back else None
            continue
        parent = node.get("pkname")
        node = table.get(parent) if parent else None
    return ""


def boot_disks() -> list[str]:
    """Nombres de los discos físicos de los que arrancó el live ([] si no se
    pudo determinar — ej. VM con la ISO como CD-ROM)."""
    table = lsblk_table()
    src = boot_source(table)
    if not src:
        return []
    disk = disk_of(table, src)
    return [disk] if disk else []
'''),
    # ── avalos_installer/disk/discovery.py (312 líneas)
    'avalos_installer.disk.discovery': (False, 'avalos_installer/disk/discovery.py', r'''"""
disk/discovery.py — detección y listado de discos/particiones para el
instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 112, 265-479, 480-516, 617-627
de la versión actual en main). Lógica y comentarios explicativos sin
cambios respecto al original — solo se movió de lugar, se actualizó el
import de `run_command` (antes `_ejecutar` privada del monolito), y todos
los identificadores se llevaron a inglés a pedido explícito (los
comentarios se dejaron en español).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from avalos_installer.core.shell import run_command

MIN_DISK_GB = 30

# GUID oficial de partición EFI System en tablas GPT (UEFI Specification,
# confirmado también en ArchWiki y Microsoft Learn). Es la misma señal que
# usa el propio firmware UEFI para encontrar la ESP — no una heurística de
# tamaño u orden.
_GUID_EFI_SYSTEM_PARTITION = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


def detect_boot_disk() -> str:
    # FIX: en el live de archiso "/" es un overlay ("airootfs"), no un bloque:
    # la lógica de abajo devolvía "airootfs" y el disco de arranque (la USB)
    # nunca se marcaba como es_arranque — ni la UI lo bloqueaba ni el chequeo
    # de install.py lo rechazaba. El medio real sale de /run/archiso/bootmnt
    # (ver disk/bootmedium.py: dd, Ventoy, copytoram). Si no se puede
    # determinar (ej. VM con la ISO como CD-ROM) se sigue con lo de siempre.
    try:
        from avalos_installer.disk.bootmedium import boot_disks
        names = boot_disks()
        if names:
            return names[0]
    except Exception as e:
        print(f"[WARN] detect_boot_disk: bootmedium falló: {e}", file=sys.stderr)
    rc, out, _ = run_command(["findmnt", "-n", "-o", "SOURCE", "/"])
    if rc == 0 and out:
        dev = out.strip()
        if dev.startswith("/dev/mapper/") or dev.startswith("/dev/dm-"):
            rc2, out2, _ = run_command(["lsblk", "-no", "PKNAME", dev])
            if rc2 == 0 and out2.strip():
                return out2.strip().split()[0]
        dev = dev.removeprefix("/dev/")
        return re.sub(r'p?\d+$', '', dev)
    rc, out, _ = run_command(["lsblk", "-J", "-o", "NAME,MOUNTPOINTS"])
    if rc == 0 and out:
        try:
            for disk in json.loads(out).get("blockdevices", []):
                if _disk_has_mount(disk, "/"):
                    return disk["name"]
        except json.JSONDecodeError as e:
            print(f"[WARN] detect_boot_disk: lsblk JSON inválido: {e}", file=sys.stderr)
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "/":
                    src = parts[0]
                    if src.startswith("/dev/mapper/") or src.startswith("/dev/dm-"):
                        rc2, out2, _ = run_command(["lsblk", "-no", "PKNAME", src])
                        if rc2 == 0 and out2.strip():
                            return out2.strip().split()[0]
                    return re.sub(r'p?\d+$', '', src.removeprefix("/dev/"))
    except OSError:
        pass
    return ""


def _disk_has_mount(node: dict, point: str) -> bool:
    mount_points = node.get("mountpoints") or [node.get("mountpoint")]
    if point in (mount_points or []):
        return True
    for child in node.get("children", []):
        if _disk_has_mount(child, point):
            return True
    return False


def list_disks() -> list[dict]:
    rc, out, _ = run_command([
        "lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,MODEL,TRAN,ROTA,VENDOR"
    ])
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    boot_disk = detect_boot_disk()
    disks = []
    for node in data.get("blockdevices", []):
        if node.get("type") != "disk":
            continue
        name = node.get("name", "")
        size_b = int(node.get("size") or 0)
        model = (node.get("model") or node.get("vendor") or "").strip()
        tran = (node.get("tran") or "").strip()
        rotational = node.get("rota") in ("1", True, 1)
        parts = []
        for child in node.get("children", []):
            if child.get("type") in ("part", "lvm"):
                mount_points = child.get("mountpoints") or [child.get("mountpoint")]
                parts.append({
                    "name": child.get("name", ""),
                    "size_b": int(child.get("size") or 0),
                    "mounts": [m for m in mount_points if m],
                })
        disks.append({
            "name": name,
            "size_b": size_b,
            "size_human": _bytes_to_human(size_b),
            "model": model,  # vacío si lsblk no lo informa: la UI lo traduce (disk-unknown)
            "tran": tran.upper() if tran else "—",
            "tipo": "HDD" if rotational else "SSD/NVMe",
            "es_arranque": (name == boot_disk),
            "particiones": parts,
            "montajes": _active_mounts(node),
        })
    return disks


def _active_mounts(node: dict) -> list[str]:
    result = []
    mount_points = node.get("mountpoints") or [node.get("mountpoint")]
    result.extend([m for m in (mount_points or []) if m])
    for child in node.get("children", []):
        result.extend(_active_mounts(child))
    return result


def _bytes_to_human(b: int) -> str:
    fb = float(b)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if fb < 1024.0:
            return f"{fb:.1f} {unit}"
        fb /= 1024.0
    return f"{fb:.1f} PB"


def detect_manual_partitions(dev: str, uefi: bool) -> dict:
    """Modo manual: analiza lo que el usuario dejó particionado a mano en
    'dev' (ej. /dev/nvme0n1) y separa la partición EFI/boot de las
    candidatas a root.

    GPT: compara PARTTYPE de cada partición contra el GUID oficial de EFI
    System Partition — señal estructural real, la misma que usa el
    firmware UEFI.

    MBR (sin tabla GPT): usa 'sfdisk -A dev' sin número de partición, que
    lista las particiones con el flag bootable/activo encendido (mismo
    criterio que ya usa 'parted ... set 1 boot on' en el modo automático
    de este instalador). sfdisk detecta solo internamente si el disco es
    GPT y avisa por stderr en vez de fallar, así que no hace falta
    detectar la tabla nosotros mismos antes de llamarlo.

    'uefi' (booleano, viene de is_uefi() del sistema en vivo) decide qué
    SIGNIFICA el flag bootable en MBR: en BIOS Legacy no existe el
    concepto de partición EFI — el flag bootable marca directamente la
    partición que contiene /boot (con frecuencia la única partición del
    disco), así que en ese caso nunca se descarta como "EFI", siempre
    queda como candidata a root. Solo si el firmware es UEFI pero el
    disco resultó estar en MBR (caso inusual, p.ej. "UEFI CSM/legacy
    boot") se sigue tratando el flag bootable como equivalente al GUID
    GPT de ESP, porque en ese caso sí puede haber una partición separada
    pensada para el firmware. Confirmado con ArchWiki/foros: en BIOS/MBR
    "lo que quieres bootable es tu directorio raíz, o /boot si está
    separado" — nunca una partición EFI real, ese concepto no existe sin
    UEFI.

    Devuelve {"efi": "/dev/X" | "", "candidatas_root": [ {"name","size_b",
    "size_human","fstype"} , ... ], "es_gpt": bool}. No decide sola cuál
    partición es root si hay más de una candidata — eso lo resuelve el
    usuario en el dropdown del wizard."""
    # lsblk exige la RUTA del dispositivo y el wizard manda el nombre pelado de list_disks()
    # ("sda", "nvme0n1"): con eso lsblk falla ("not a block device") y el modo manual nunca
    # encontraba particiones. Se normaliza acá (también para el sfdisk de más abajo).
    _name = (dev or "").removeprefix("/dev/")
    if not _name:
        return {"efi": "", "candidatas_root": [], "es_gpt": False}
    dev = "/dev/" + _name
    rc, out, _ = run_command([
        "lsblk", "-J", "-b", "-n", "-o",
        "NAME,SIZE,TYPE,PARTTYPE,FSTYPE,MOUNTPOINTS", dev,
    ])
    if rc != 0 or not out:
        return {"efi": "", "candidatas_root": [], "es_gpt": False}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"efi": "", "candidatas_root": [], "es_gpt": False}

    _disk_node = next(
        (n for n in data.get("blockdevices", []) if n.get("name") == dev.removeprefix("/dev/")),
        None,
    )
    _children = (_disk_node or {}).get("children", []) or []
    if not _children:
        # fallback: algunas versiones de lsblk aplanan el árbol si se le
        # pasa un device específico en vez del disco completo
        _children = data.get("blockdevices", [])

    _is_gpt = any((c.get("parttype") or "").strip().lower() == _GUID_EFI_SYSTEM_PARTITION
                  for c in _children)

    _efi = ""
    _boot_flags: set[str] = set()
    if not _is_gpt and uefi:
        # MBR + firmware UEFI (caso inusual: UEFI en modo legacy/CSM):
        # preguntarle a sfdisk qué partición tiene el flag bootable, igual
        # que hace el modo automático de este instalador para marcar la
        # partición equivalente a ESP. En BIOS puro (uefi=False) esta
        # llamada no hace falta — el flag bootable jamás se interpreta
        # como EFI en ese caso, así que no vale la pena el subprocess.
        # 'sfdisk -A dev' sin número de partición = modo listado (confirmado
        # en sfdisk(8)). No falla si el disco resulta ser GPT — solo avisa
        # por stderr y entra en modo PMBR, así que es seguro llamarlo aunque
        # _is_gpt haya dado False por error.
        try:
            _rc_sf, _out_sf, _ = run_command(["sfdisk", "-A", dev])
            if _rc_sf == 0:
                for _line in _out_sf.splitlines():
                    _line = _line.strip()
                    if _line.startswith(dev):
                        _boot_flags.add(_line.split()[0].removeprefix("/dev/"))
        except Exception:
            pass

    _candidates: list[dict] = []
    for _child in _children:
        if _child.get("type") != "part":
            continue
        _name = _child.get("name", "")
        _parttype = (_child.get("parttype") or "").strip().lower()
        _fstype = (_child.get("fstype") or "").strip()
        _size_b = int(_child.get("size") or 0)

        _is_this_efi = (
            (_is_gpt and _parttype == _GUID_EFI_SYSTEM_PARTITION)
            or (not _is_gpt and uefi and _name in _boot_flags)
        )
        if _is_this_efi and not _efi:
            _efi = "/dev/" + _name
            continue

        _candidates.append({
            "name": "/dev/" + _name,
            "size_b": _size_b,
            "size_human": _bytes_to_human(_size_b),
            "fstype": _fstype or "?",
        })

    return {"efi": _efi, "candidatas_root": _candidates, "es_gpt": _is_gpt}


def detect_btrfs_subvolumes(dev_root: str) -> list[str]:
    """Modo manual: si el usuario ya formateó dev_root con Btrfs y creó
    sus propios subvolúmenes, los lista para que el instalador pueda
    saltarse la creación de los que ya existan (según lo acordado) en vez
    de pisarlos.

    No hay forma de inspeccionar subvolúmenes sin montar el filesystem al
    menos una vez (confirmado: 'btrfs subvolume list' opera sobre un punto
    de montaje, no sobre el device crudo) — se monta de solo-lectura
    ('-o ro') para minimizar riesgo, ya que solo se necesita leer."""
    _tmp = "/tmp/btrfs_probe_manual"
    Path(_tmp).mkdir(parents=True, exist_ok=True)
    _rc_mnt, _, _ = run_command(["mount", "-o", "ro", dev_root, _tmp])
    if _rc_mnt != 0:
        try:
            os.rmdir(_tmp)
        except OSError:
            pass
        return []
    try:
        _rc, _out, _ = run_command(["btrfs", "subvolume", "list", _tmp])
        if _rc != 0 or not _out:
            return []
        _subvolumes = []
        for _line in _out.splitlines():
            # formato: "ID 256 gen 12 top level 5 path @home"
            _m = re.search(r"\bpath\s+(\S+)$", _line.strip())
            if _m:
                _subvolumes.append(_m.group(1))
        return _subvolumes
    finally:
        run_command(["umount", _tmp])
        try:
            os.rmdir(_tmp)
        except OSError:
            pass


def detect_target_disk_type(dev_name: str) -> str:
    """Detecta si el disco es HDD, SSD o NVMe para el IO scheduler."""
    rotational_path = Path(f"/sys/block/{dev_name}/queue/rotational")
    try:
        rotational = rotational_path.read_text().strip()
        if "nvme" in dev_name or "mmcblk" in dev_name:
            return "nvme"
        return "hdd" if rotational == "1" else "ssd"
    except Exception:
        return "ssd"
'''),
    # ── avalos_installer/hardware/__init__.py (0 líneas)
    'avalos_installer.hardware': (True, 'avalos_installer/hardware/__init__.py', r''''''),
    # ── avalos_installer/hardware/detection.py (131 líneas)
    'avalos_installer.hardware.detection': (False, 'avalos_installer/hardware/detection.py', r'''"""
hardware/detection.py — detección de hardware del instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 160-170 y 517-616 de la versión
actual en main). Lógica sin cambios respecto al original — solo se movió
de lugar y se le puso el import de `run_command` desde core.shell en vez
de la `_ejecutar` privada del monolito.
"""

from __future__ import annotations

from pathlib import Path

from avalos_installer.core.shell import run_command

# ── Paquetes de driver recomendados por vendor de GPU ───────────────────
# (Sin cambios respecto al original — mismas listas, mismo orden.)

DRIVER_PKGS_AMD = [
    "mesa", "mesa-utils", "vulkan-radeon", "vulkan-icd-loader", "vulkan-tools",
    "libva-mesa-driver", "libva-utils", "radeontop", "gst-plugin-va",
    "libva", "lib32-mesa", "lib32-vulkan-radeon",
]

DRIVER_PKGS_INTEL = [
    "mesa", "mesa-utils", "vulkan-intel", "vulkan-icd-loader", "vulkan-tools",
    "intel-media-driver", "libva-intel-driver", "libva-utils", "libva",
    "gst-plugin-va", "lib32-mesa", "lib32-vulkan-intel",
]


def is_uefi() -> bool:
    return Path("/sys/firmware/efi").exists()


def detect_microcode() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            c = f.read().lower()
        # Se decide por la línea vendor_id: buscar "intel"/"amd" en TODO el archivo
        # también matchea nombres de flags, modelo, etc. El substring queda de respaldo.
        vendor = next((ln.split(":", 1)[1].strip() for ln in c.splitlines()
                       if ln.startswith("vendor_id") and ":" in ln), "")
        if vendor == "genuineintel":
            return "intel-ucode"
        if vendor == "authenticamd":
            return "amd-ucode"
        if "genuineintel" in c or "intel" in c:
            return "intel-ucode"
        if "authenticamd" in c or "amd" in c:
            return "amd-ucode"
    except OSError:
        pass
    return ""


def detect_cpu_arch_level() -> str:
    """Detecta el nivel de arquitectura x86: v2, v3, v4."""
    try:
        with open("/proc/cpuinfo") as f:
            flags = ""
            for line in f:
                if line.startswith("flags"):
                    flags = line.split(":", 1)[1].lower()
                    break
        flag_set = set(flags.split())
        # /proc/cpuinfo NO tiene flag "lzcnt": el kernel lo expone como "abm"
        # (X86_FEATURE_ABM = CPUID 0x80000001 ECX bit 5 = LZCNT). Con "lzcnt" en el set,
        # v3 nunca se cumplía: toda CPU v3 SIN AVX-512 (Ryzen 1000-5000, Intel de escritorio
        # sin AVX-512...) caía a v2, recibía linux-avalos-compat y se le negaba el kernel BORE.
        # Solo las CPU con AVX-512 (v4) escapaban, porque v4 no mira v3.
        if "lzcnt" in flag_set:
            flag_set.add("abm")
        v4 = {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}
        v3 = {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}
        v2 = {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"}
        if v4.issubset(flag_set) and v3.issubset(flag_set):
            return "x86-64-v4"
        elif v3.issubset(flag_set):
            return "x86-64-v3"
        elif v2.issubset(flag_set):
            return "x86-64-v2"
        else:
            return "x86-64"
    except Exception:
        return "x86-64"


def _parse_lspci_model(line: str) -> str:
    """Extrae el nombre del modelo de una línea de lspci -mm."""
    parts = [p.strip('"') for p in line.split('"') if p.strip('"')]
    return parts[5] if len(parts) > 5 else parts[-1] if parts else "Desconocido"


def detect_gpu() -> dict:
    """Detecta el vendor de GPU via /proc o lspci. Devuelve vendor + pkgs recomendados."""
    try:
        rc, out, _ = run_command(["lspci", "-mm"])
        if rc == 0 and out:
            amd_keywords = ["advanced micro devices", "amd/ati", "radeon", "navi",
                            "polaris", "vega", "rdna", "gfx"]
            intel_keywords = ["intel corporation", "intel xe", "iris xe",
                              "uhd graphics", "hd graphics"]
            gpu_lines = [ln for ln in out.splitlines()
                         if any(k in ln.lower() for k in ("vga", "display", "3d controller"))]
            # Dos pasadas: si hay alguna GPU AMD gana sobre Intel. Antes valía el orden de
            # lspci, y en un portátil con iGPU Intel (00:02.0, sale primero) + dGPU Radeon
            # se instalaban solo los drivers Intel: la GPU con la que se juega quedaba sin
            # vulkan-radeon.
            for line in gpu_lines:
                if any(k in line.lower() for k in amd_keywords):
                    return {"vendor": "amd", "model": _parse_lspci_model(line),
                            "pkgs": DRIVER_PKGS_AMD}
            for line in gpu_lines:
                if any(k in line.lower() for k in intel_keywords):
                    return {"vendor": "intel", "model": _parse_lspci_model(line),
                            "pkgs": DRIVER_PKGS_INTEL}
    except Exception as e:
        print(f"[WARN] detect_gpu lspci: {e}")

    try:
        for vendor_file in Path("/sys/class/drm").glob("card*/device/vendor"):
            vid = vendor_file.read_text().strip()
            if vid == "0x1002":
                return {"vendor": "amd", "model": "AMD GPU", "pkgs": DRIVER_PKGS_AMD}
            if vid == "0x8086":
                return {"vendor": "intel", "model": "Intel GPU", "pkgs": DRIVER_PKGS_INTEL}
    except Exception as e:
        print(f"[WARN] detect_gpu /sys/class/drm: {e}")

    return {"vendor": "amd", "model": "GPU desconocida (asumiendo AMD)", "pkgs": DRIVER_PKGS_AMD}
'''),
    # ── avalos_installer/hardware/preflight.py (255 líneas)
    'avalos_installer.hardware.preflight': (False, 'avalos_installer/hardware/preflight.py', r'''"""
hardware/preflight.py — comprobación previa del equipo ("preflight"), ANTES de que
el usuario llene el asistente y de tocar ningún disco.

Hasta ahora todo esto se comprobaba DESPUÉS de que el usuario terminaba el
wizard (sin disco disponible, disco < 30 GB, sin internet...) y el error
llegaba en plena instalación. Esta pantalla lo adelanta: la bienvenida muestra
qué tiene el equipo, qué kernel le va a tocar y qué puede salir mal.

Cada comprobación devuelve un Check con CLAVES i18n (label/detail/hint) y sus
parámetros — no texto — para que la UI lo traduzca en el idioma vigente y lo
re-renderice si el usuario cambia de idioma. Estados:

  ok     todo bien             warn   se puede continuar, pero conviene mirarlo
  fail   problema; con blocking=True impide instalar (la UI ofrece
         "continuar de todos modos" por si fuera un falso positivo)
  info   dato, sin juicio

Ninguna comprobación lanza: si una falla, queda como "info" y el resto sigue.
Todo lo que lee del sistema vive en constantes de módulo para poder simularlo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from avalos_installer.core.prereqs import check_tools
from avalos_installer.core.shell import run_command
from avalos_installer.disk.discovery import MIN_DISK_GB, list_disks
from avalos_installer.hardware.detection import detect_cpu_arch_level, detect_gpu, is_uefi
from avalos_installer.network.diagnose import NetDiagnosis, diagnose_network

_MEMINFO = Path("/proc/meminfo")
_CPUINFO = Path("/proc/cpuinfo")
_POWER = Path("/sys/class/power_supply")
_SB_VAR = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c")

RAM_FAIL_GIB = 1.5           # por debajo, la instalación no es viable
RAM_WARN_GIB = 4.0           # por debajo, funciona pero conviene avisar
BATTERY_WARN_PCT = 30
CLOCK_WARN_S = 120


@dataclass
class Check:
    id: str
    status: str                                   # ok | warn | fail | info
    label: str                                    # clave i18n (pf-l-*)
    detail: str                                   # clave i18n
    params: dict[str, Any] = field(default_factory=dict)
    hint: str | None = None                       # clave i18n
    blocking: bool = False                        # solo cuenta con status == "fail"


# ── comprobaciones ───────────────────────────────────────────────────────────
def _boot(uefi: bool) -> Check:
    return Check("boot", "ok" if uefi else "info", "pf-l-boot", "pf-boot-uefi" if uefi else "pf-boot-bios")


def _secureboot(uefi: bool) -> Check | None:
    if not uefi:
        return None
    try:
        data = _SB_VAR.read_bytes()
    except OSError:
        return None                               # efivars no legible: no se opina
    if len(data) < 5:
        return None
    if data[4] == 1:
        return Check("sb", "warn", "pf-l-sb", "pf-sb-on", hint="pf-hint-sb-on")
    return Check("sb", "ok", "pf-l-sb", "pf-sb-off")


def _cpu_model() -> str:
    try:
        for ln in _CPUINFO.read_text(errors="replace").splitlines():
            if ln.lower().startswith("model name"):
                return " ".join(ln.split(":", 1)[1].split())
    except OSError:
        pass
    return "CPU"


def _cpu() -> Check:
    level = detect_cpu_arch_level()
    model = _cpu_model()
    if level == "x86-64":
        return Check("cpu", "warn", "pf-l-cpu", "pf-cpu-old", {"model": model}, hint="pf-hint-cpu-old")
    kernel = "linux-avalos" if level in ("x86-64-v3", "x86-64-v4") else "linux-avalos-compat"
    return Check("cpu", "ok", "pf-l-cpu", "pf-cpu", {"model": model, "level": level, "kernel": kernel})


def _nvidia_model() -> str | None:
    rc, out, _ = run_command(["lspci", "-mm"], timeout=10)
    if rc != 0 or not out:
        return None
    for ln in out.splitlines():
        low = ln.lower()
        if "nvidia" in low and ("vga" in low or "3d" in low or "display" in low):
            parts = ln.split('"')
            return parts[5] if len(parts) > 5 else "NVIDIA"
    return None


def _gpu() -> Check:
    nv = _nvidia_model()
    if nv:
        return Check("gpu", "warn", "pf-l-gpu", "pf-gpu-nvidia", {"model": nv}, hint="pf-hint-gpu-nvidia")
    g = detect_gpu()
    if g["model"].startswith("GPU desconocida"):
        return Check("gpu", "info", "pf-l-gpu", "pf-gpu-unknown")
    return Check("gpu", "ok", "pf-l-gpu", "pf-gpu", {"vendor": g["vendor"].upper(), "model": g["model"]})


def _ram() -> Check | None:
    try:
        for ln in _MEMINFO.read_text().splitlines():
            if ln.startswith("MemTotal:"):
                gib = int(ln.split()[1]) / 1024 / 1024
                break
        else:
            return None
    except (OSError, ValueError, IndexError):
        return None
    p = {"gib": f"{gib:.1f}"}
    if gib < RAM_FAIL_GIB:
        return Check("ram", "fail", "pf-l-ram", "pf-ram-fail", p, hint="pf-hint-ram", blocking=True)
    if gib < RAM_WARN_GIB:
        return Check("ram", "warn", "pf-l-ram", "pf-ram-low", p, hint="pf-hint-ram")
    return Check("ram", "ok", "pf-l-ram", "pf-ram", p)


def _disks() -> Check:
    discos = list_disks()
    eligible = [d for d in discos if not d["es_arranque"] and d["size_b"] / 1e9 >= MIN_DISK_GB]
    if not eligible:
        boot = next((d["name"] for d in discos if d["es_arranque"]), "?")
        return Check("disk", "fail", "pf-l-disk", "pf-disk-none", {"min_gb": MIN_DISK_GB, "boot": boot},
                     hint="pf-hint-disk-none", blocking=True)
    listing = " · ".join(f"{d['name']} {d['size_human']} {d['tipo']}" for d in eligible[:3])
    return Check("disk", "ok", "pf-l-disk", "pf-disk", {"n": len(eligible), "list": listing})


def _net(diag: NetDiagnosis) -> Check:
    v = diag.verdict
    detail = f"pf-net-{v}"
    if v == "ok":
        return Check("net", "ok", "pf-l-net", detail, diag.text_params())
    if diag.usable:                               # mirrors_partial / clock
        hint = "pf-hint-net-clock" if v == "clock" else None
        return Check("net", "warn", "pf-l-net", detail, diag.text_params(), hint=hint)
    hint = "pf-hint-net-no_link_wifi" if v == "no_link" and diag.has_wifi else f"pf-hint-net-{v}"
    return Check("net", "fail", "pf-l-net", detail, diag.text_params(), hint=hint, blocking=True)


def _clock(diag: NetDiagnosis) -> Check | None:
    s = diag.clock_skew_s
    if s is None:
        return None
    if abs(s) > CLOCK_WARN_S:
        return Check("clock", "warn", "pf-l-clock", "pf-clock-skew", diag.text_params(), hint="pf-hint-clock-skew")
    return Check("clock", "ok", "pf-l-clock", "pf-clock-ok")


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _power() -> Check | None:
    bat, ac_online = None, False
    try:
        supplies = sorted(_POWER.iterdir())
    except OSError:
        return None
    for s in supplies:
        typ = _read(s / "type").lower()
        if typ == "battery" and bat is None:
            try:
                bat = (int(_read(s / "capacity")), _read(s / "status").lower())
            except ValueError:
                pass
        elif typ == "mains" and _read(s / "online") == "1":
            ac_online = True
    if bat is None:
        return None                                # equipo de escritorio
    pct, state = bat
    on_ac = ac_online or state in ("charging", "full")
    if on_ac:
        return Check("power", "ok", "pf-l-power", "pf-power-ac", {"pct": pct})
    if pct < BATTERY_WARN_PCT:
        return Check("power", "warn", "pf-l-power", "pf-power-low", {"pct": pct}, hint="pf-hint-power-low")
    return Check("power", "ok", "pf-l-power", "pf-power-batt", {"pct": pct})


def _tools() -> Check:
    missing = sorted(t for t, ok in check_tools().items() if not ok)
    if missing:
        return Check("tools", "warn", "pf-l-tools", "pf-tools-missing", {"names": ", ".join(missing)})
    return Check("tools", "ok", "pf-l-tools", "pf-tools-ok")


def _virt() -> Check | None:
    rc, out, _ = run_command(["systemd-detect-virt"], timeout=5)
    kind = out.strip()
    if rc == 0 and kind and kind != "none":
        return Check("virt", "info", "pf-l-virt", "pf-virt", {"kind": kind})
    return None


def _log(session) -> Check | None:
    lf = getattr(session, "logfile", None)
    if lf is None:
        return None
    th = getattr(session, "_usb_thread", None)
    if th is not None:
        th.join(timeout=3)                         # la búsqueda de la USB arranca al abrir la app
    if getattr(lf, "usb_desc", ""):
        return Check("log", "info", "pf-l-log", "pf-log-usb", {"desc": lf.usb_desc})
    return Check("log", "info", "pf-l-log", "pf-log-ram")


def run_preflight(session=None, diag: NetDiagnosis | None = None) -> list[Check]:
    """Corre todas las comprobaciones (≈1–15 s según la red). Nunca lanza."""
    def guard(fn, *a) -> Check | None:
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 — un check roto no debe tumbar la pantalla
            return Check(fn.__name__.strip("_"), "info", "pf-l-other", "pf-check-error", {"why": str(e)[:80]})

    diag = diag or diagnose_network()
    uefi = is_uefi()
    plan = [(_boot, uefi), (_secureboot, uefi), (_cpu,), (_gpu,), (_ram,), (_disks,), (_net, diag),
            (_clock, diag), (_power,), (_tools,), (_virt,), (_log, session)]
    checks = [c for c in (guard(f, *a) for f, *a in plan) if c is not None]
    return checks


def to_dict(checks: list[Check]) -> dict:
    """Estructura serializable para la UI (JSON)."""
    return {
        "checks": [asdict(c) for c in checks],
        "blocking": any(c.blocking and c.status == "fail" for c in checks),
        "warnings": sum(1 for c in checks if c.status == "warn"),
    }


def report_lines(checks: list[Check]) -> list[str]:
    """Una línea por check, para el archivo de log (claves, no traducción)."""
    return [f"{c.status:<4} {c.id:<6} {c.detail} {c.params}" + (" [BLOQUEA]" if c.blocking and c.status == "fail" else "")
            for c in checks]
'''),
    # ── avalos_installer/network/__init__.py (0 líneas)
    'avalos_installer.network': (True, 'avalos_installer/network/__init__.py', r''''''),
    # ── avalos_installer/network/connectivity.py (22 líneas)
    'avalos_installer.network.connectivity': (False, 'avalos_installer/network/connectivity.py', r'''"""
network/connectivity.py — chequeo de conectividad del instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 532-539). Sin cambios de lógica.

NOTA: esto es solo el chequeo binario "hay internet sí/no" (ping) que ya existía y
que el instalador ya NO usa: el paso "net" y la comprobación previa del equipo usan
el diagnóstico por capas de network/diagnose.py (sin enlace / sin IP / sin salida /
DNS / portal cautivo / hora / mirrors caídos). Se deja por compatibilidad.
"""

from __future__ import annotations

from avalos_installer.core.shell import run_command


def check_internet() -> bool:
    rc4, _, _ = run_command(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=6)
    if rc4 == 0:
        return True
    rc6, _, _ = run_command(["ping6", "-c", "1", "-W", "3", "2001:4860:4860::8888"], timeout=6)
    return rc6 == 0
'''),
    # ── avalos_installer/network/diagnose.py (404 líneas)
    'avalos_installer.network.diagnose': (False, 'avalos_installer/network/diagnose.py', r'''"""
network/diagnose.py — diagnóstico de red por capas del instalador de AvalOS.

Antes el paso "net" hacía un solo ping a 8.8.8.8: "hay internet sí/no". Eso
falla en los dos sentidos — un router que bloquea ICMP daba "sin internet"
con la red perfecta, y una red con DNS roto, un portal cautivo o la hora
mal daba "hay internet" para después reventar en pacstrap con un error
críptico. Acá se prueba capa por capa y el PRIMER fallo decide el veredicto:

  enlace → IP → ruta → salida a Internet → DNS → portal cautivo → HTTPS
  (hora/certificados) → mirrors de Arch

  ok               todo responde
  mirrors_partial  usable: algunos mirrors no responden (el failover usa los demás)
  clock            usable: la hora del equipo está desfasada y rompe TLS;
                   sync_time() del instalador la corrige antes de pacman
  no_link          ninguna interfaz con cable/Wi-Fi conectado
  no_ip            hay enlace pero no se obtuvo dirección IP (DHCP)
  no_route         hay IP pero no hay puerta de enlace (ruta por defecto)
  no_internet      red local sí, salida a Internet no (router/firewall)
  dns              hay Internet pero no se resuelven nombres
  portal           la red exige iniciar sesión en un portal cautivo
  tls              falla la verificación HTTPS por otro motivo (¿proxy?)
  mirrors_down     Internet funciona pero ningún mirror de Arch responde

Cada sonda es una función de módulo (_probe_*) para poder simularlas en
pruebas. Ninguna lanza: un fallo de la sonda es un resultado, no una
excepción. El total está acotado (~15 s en el peor caso): las sondas de
red corren en paralelo con timeouts cortos.
"""

from __future__ import annotations

import concurrent.futures as cf
import email.utils
import http.client
import json
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from avalos_installer.core.shell import run_command

OK, MIRRORS_PARTIAL, CLOCK = "ok", "mirrors_partial", "clock"
NO_LINK, NO_IP, NO_ROUTE, NO_INTERNET = "no_link", "no_ip", "no_route", "no_internet"
DNS, PORTAL, TLS, MIRRORS_DOWN = "dns", "portal", "tls", "mirrors_down"
USABLE = {OK, MIRRORS_PARTIAL, CLOCK}

MIRRORLIST = Path("/etc/pacman.d/mirrorlist")
_SYS_NET = Path("/sys/class/net")
_PROC_ROUTE = Path("/proc/net/route")
_PROC_ROUTE6 = Path("/proc/net/ipv6_route")
# Sondas de salida a Internet por IP (TCP/443: funciona aunque el router filtre ICMP)
_IP_PROBES = [("1.1.1.1", 443), ("9.9.9.9", 443), ("8.8.8.8", 443), ("2606:4700:4700::1111", 443)]
_DNS_NAMES = ["archlinux.org", "geo.mirror.pkgbuild.com"]
_PORTAL_PROBES = [
    ("connectivitycheck.gstatic.com", "/generate_204", "204"),
    ("detectportal.firefox.com", "/success.txt", "success"),
]
_FALLBACK_MIRRORS = ["https://geo.mirror.pkgbuild.com", "https://mirror.rackspace.com/archlinux"]
_VIRTUAL_IF = ("lo", "docker", "veth", "br-", "virbr", "vnet", "tun", "tap", "vmnet", "sit")
_SKEW_LIMIT_S = 300   # más que esto y los certificados TLS / firmas GPG empiezan a fallar


@dataclass
class Layer:
    id: str
    status: str          # "ok" | "fail" | "skip"
    detail: str = ""
    ms: int | None = None


@dataclass
class NetDiagnosis:
    verdict: str = OK
    layers: list[Layer] = field(default_factory=list)
    clock_skew_s: int | None = None      # hora local − hora del servidor (s); None si no se pudo medir
    mirrors_ok: int = 0
    mirrors_total: int = 0
    has_wifi: bool = False

    @property
    def usable(self) -> bool:
        return self.verdict in USABLE

    def text_params(self) -> dict:
        """Valores para las plantillas i18n pf-net-<veredicto> ({ok}, {total}, {skew})."""
        return {"ok": self.mirrors_ok, "total": self.mirrors_total, "skew": fmt_duration(self.clock_skew_s)}

    def lines(self) -> list[str]:
        """Detalle por capa, para el archivo de log."""
        out = [f"veredicto={self.verdict} usable={self.usable} skew={self.clock_skew_s}s "
               f"mirrors={self.mirrors_ok}/{self.mirrors_total}"]
        for ly in self.layers:
            ms = f" {ly.ms}ms" if ly.ms is not None else ""
            out.append(f"  {ly.status:<4} {ly.id:<9}{ms}  {ly.detail}")
        return out


def fmt_duration(seconds: int | None) -> str:
    """'1 h 05 min', '5 min', '42 s' (valor absoluto; '?' si no se conoce)."""
    if seconds is None:
        return "?"
    n = abs(int(seconds))
    if n >= 3600:
        return f"{n // 3600} h {n % 3600 // 60:02d} min"
    if n >= 60:
        return f"{n // 60} min"
    return f"{n} s"


# ── sondas (cada una simulable en pruebas) ──────────────────────────────
def _sysfs_interfaces() -> list[dict]:
    """Respaldo si `ip` no está: enlace por /sys/class/net/<if>/carrier. No se pueden
    conocer las IP, así que las interfaces con enlace se marcan con ips=["?"] y la
    decisión la toman las sondas de más abajo (TCP/DNS)."""
    res: list[dict] = []
    try:
        dirs = sorted(_SYS_NET.iterdir())
    except OSError:
        return res
    for d in dirs:
        if d.name.startswith(_VIRTUAL_IF):
            continue
        try:
            carrier = (d / "carrier").read_text().strip()      # EINVAL si la interfaz está caída
        except OSError:
            carrier = "0"
        res.append({"name": d.name, "up": carrier == "1", "ips": ["?"] if carrier == "1" else [],
                    "wifi": (d / "wireless").exists() or d.name.startswith("wl")})
    return res


def _probe_interfaces() -> list[dict]:
    """[{name, up, ips, wifi}] de las interfaces físicas (sin lo ni virtuales)."""
    rc, out, _ = run_command(["ip", "-j", "addr", "show"], timeout=5)
    res: list[dict] = []
    try:
        data = json.loads(out) if rc == 0 and out else None
    except ValueError:
        data = None
    if data is None:                       # sin iproute2 (o salida ilegible): respaldo por sysfs
        return _sysfs_interfaces()
    for it in data:
        name = it.get("ifname", "")
        if name.startswith(_VIRTUAL_IF):
            continue
        flags = it.get("flags", [])
        ips = [a.get("local") for a in it.get("addr_info", [])
               if a.get("scope") == "global" and a.get("local")]
        res.append({
            "name": name,
            "up": "LOWER_UP" in flags or it.get("operstate") == "UP",
            "ips": ips,
            "wifi": Path(f"/sys/class/net/{name}/wireless").exists() or name.startswith("wl"),
        })
    return res


def _proc_default_route() -> bool:
    """Respaldo sin `ip`: /proc/net/route (IPv4) y /proc/net/ipv6_route."""
    try:
        for ln in _PROC_ROUTE.read_text().splitlines()[1:]:
            f = ln.split()
            if len(f) > 7 and f[1] == "00000000" and f[7] == "00000000":
                return True
    except OSError:
        pass
    try:
        for ln in _PROC_ROUTE6.read_text().splitlines():
            f = ln.split()
            if len(f) > 9 and f[0] == "0" * 32 and f[1] == "00" and f[9] != "lo":
                return True
    except OSError:
        pass
    return False


def _probe_default_route() -> bool:
    ran = False
    for fam in ("-4", "-6"):
        rc, out, _ = run_command(["ip", "-j", fam, "route", "show", "default"], timeout=5)
        if rc != 0:
            continue
        ran = True
        try:
            if out and json.loads(out):
                return True
        except ValueError:
            pass
    return False if ran else _proc_default_route()


def _tcp_ok(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolves(name: str, timeout: float = 5.0) -> bool:
    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return bool(ex.submit(socket.getaddrinfo, name, 443).result(timeout=timeout))
    except (OSError, cf.TimeoutError):
        return False
    finally:
        ex.shutdown(wait=False)         # si el resolver se cuelga, no bloqueamos


def _http_get(host: str, path: str, timeout: float = 4.0) -> tuple[int, dict, str] | None:
    """(status, headers en minúscula, primeros 300 bytes) o None si no conecta."""
    try:
        conn = http.client.HTTPConnection(host, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "avalos-installer", "Connection": "close"})
        r = conn.getresponse()
        body = r.read(300).decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in r.getheaders()}
        conn.close()
        return r.status, headers, body
    except (OSError, http.client.HTTPException):
        return None


def _https_head(url: str, timeout: float = 5.0) -> tuple[str, int | None, str]:
    """('ok', status, '') | ('cert', None, mensaje) | ('fail', None, mensaje)."""
    u = urllib.parse.urlsplit(url)
    try:
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                           context=ssl.create_default_context())
        conn.request("HEAD", u.path or "/", headers={"User-Agent": "avalos-installer", "Connection": "close"})
        status = conn.getresponse().status
        conn.close()
        return "ok", status, ""
    except ssl.SSLCertVerificationError as e:
        return "cert", None, getattr(e, "verify_message", "") or str(e)
    except ssl.SSLError as e:
        return "cert", None, str(e)
    except (OSError, http.client.HTTPException) as e:
        return "fail", None, str(e)


def _mirror_bases(mirrorlist: Path) -> list[str]:
    bases: list[str] = []
    try:
        for ln in mirrorlist.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln.startswith("Server") and "=" in ln:
                url = ln.split("=", 1)[1].strip()
                url = url.replace("$repo", "core").replace("$arch", "x86_64")
                if url.endswith("/core/os/x86_64"):
                    bases.append(url[: -len("/core/os/x86_64")])
    except OSError:
        pass
    for fb in _FALLBACK_MIRRORS:
        if fb not in bases:
            bases.append(fb)
    return list(dict.fromkeys(bases))[:8]


def _mirror_ok(base: str, timeout: float = 5.0) -> bool:
    u = urllib.parse.urlsplit(base)
    path = f"{u.path.rstrip('/')}/core/os/x86_64/core.db"
    if not u.hostname or not _resolves(u.hostname, min(timeout, 4.0)):
        return False
    try:
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=timeout)
        conn.request("HEAD", path, headers={"User-Agent": "avalos-installer", "Connection": "close"})
        status = conn.getresponse().status
        conn.close()
        return status < 400
    except (OSError, http.client.HTTPException, ssl.SSLError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _skew_from_headers(headers: dict) -> int | None:
    raw = headers.get("date")
    if not raw:
        return None
    try:
        return int((_now() - email.utils.parsedate_to_datetime(raw)).total_seconds())
    except (TypeError, ValueError):
        return None


# ── diagnóstico ──────────────────────────────────────────────────────────
def diagnose_network(mirrorlist: Path = MIRRORLIST) -> NetDiagnosis:
    d = NetDiagnosis()
    t0 = time.monotonic()

    def add(id_: str, status: str, detail: str = "", since: float | None = None) -> None:
        ms = int((time.monotonic() - since) * 1000) if since is not None else None
        d.layers.append(Layer(id_, status, detail, ms))

    def done(verdict: str) -> NetDiagnosis:
        d.verdict = verdict
        return d

    # 1) enlace + IP
    t = time.monotonic()
    ifs = _probe_interfaces()
    d.has_wifi = any(i["wifi"] for i in ifs)
    up = [i for i in ifs if i["up"]]
    if not up:
        add("link", "fail", f"interfaces={[i['name'] for i in ifs] or 'ninguna'} (ninguna con enlace)", t)
        return done(NO_LINK)
    add("link", "ok", ", ".join(i["name"] for i in up), t)
    with_ip = [i for i in up if i["ips"]]
    if not with_ip:
        add("ip", "fail", "enlace sin dirección IP global", t)
        return done(NO_IP)
    add("ip", "ok", ", ".join(f"{i['name']}={i['ips'][0]}" for i in with_ip), t)

    # 2) ruta por defecto
    t = time.monotonic()
    if not _probe_default_route():
        add("route", "fail", "sin ruta por defecto", t)
        return done(NO_ROUTE)
    add("route", "ok", "", t)

    # 3) salida a Internet por IP (en paralelo)
    t = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=len(_IP_PROBES)) as ex:
        hits = [hp for hp, ok in zip(_IP_PROBES, ex.map(lambda hp: _tcp_ok(*hp), _IP_PROBES), strict=True) if ok]
    if not hits:
        add("internet", "fail", "ninguna IP pública responde en TCP/443", t)
        return done(NO_INTERNET)
    add("internet", "ok", f"{hits[0][0]}:{hits[0][1]}", t)

    # Desde acá, los fallos "blandos" (dns, portal, tls, hora) solo deciden el veredicto si
    # NINGÚN mirror responde: que pacman llegue a un mirror es la verdad de fondo, y una sonda
    # de portal o de DNS lenta no debe frenar una instalación que va a funcionar.
    soft: str | None = None

    # 4) DNS
    t = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=len(_DNS_NAMES)) as ex:
        resolved = [n for n, ok in zip(_DNS_NAMES, ex.map(_resolves, _DNS_NAMES), strict=True) if ok]
    if not resolved:
        add("dns", "fail", f"no resuelve {', '.join(_DNS_NAMES)}", t)
        soft = DNS
    else:
        add("dns", "ok", ", ".join(resolved), t)

    # 5) portal cautivo (y de paso la hora del servidor, sin TLS) — necesita DNS
    if soft is None:
        t = time.monotonic()
        checked = False
        for host, path, expect in _PORTAL_PROBES:
            r = _http_get(host, path)
            if r is None:
                continue
            checked = True
            status, headers, body = r
            if d.clock_skew_s is None:
                d.clock_skew_s = _skew_from_headers(headers)
            good = (status == 204) if expect == "204" else (status == 200 and body.strip().lower().startswith(expect))
            if not good:
                add("portal", "fail", f"{host}{path} → {status} {headers.get('location', '')}".strip(), t)
                soft = PORTAL
            break
        if soft is None:
            add("portal", "ok" if checked else "skip", "" if checked else "sondas de portal inaccesibles", t)

    # 6) HTTPS (certificados ↔ hora) — solo si no hay portal ni DNS roto
    if soft is None:
        t = time.monotonic()
        kind, status, msg = _https_head("https://archlinux.org/")
        if kind == "cert":
            skewed = d.clock_skew_s is not None and abs(d.clock_skew_s) > _SKEW_LIMIT_S
            low = msg.lower()
            if skewed or "not yet valid" in low or "expired" in low:
                add("tls", "fail", f"certificado rechazado ({msg}); hora local − servidor = {d.clock_skew_s}s", t)
                soft = CLOCK
            else:
                add("tls", "fail", f"certificado rechazado: {msg}", t)
                soft = TLS
        else:
            add("tls", "ok" if kind == "ok" else "skip", f"archlinux.org → {status}" if kind == "ok" else msg[:80], t)

    # 7) mirrors (la prueba que decide)
    t = time.monotonic()
    bases = _mirror_bases(mirrorlist)
    with cf.ThreadPoolExecutor(max_workers=max(1, len(bases))) as ex:
        results = list(ex.map(_mirror_ok, bases))
    d.mirrors_total, d.mirrors_ok = len(bases), sum(results)
    if d.mirrors_ok == 0:
        add("mirrors", "fail", f"0/{d.mirrors_total} responden", t)
        return done(soft or MIRRORS_DOWN)
    add("mirrors", "ok", f"{d.mirrors_ok}/{d.mirrors_total} responden", t)
    if soft:
        add("nota", "skip", f"'{soft}' ignorado: {d.mirrors_ok} mirror(s) responden, pacman va a poder descargar")
    add("total", "ok", f"{time.monotonic() - t0:.1f}s")
    return done(OK if d.mirrors_ok == d.mirrors_total else MIRRORS_PARTIAL)
'''),
    # ── avalos_installer/network/mirrors.py (117 líneas)
    'avalos_installer.network.mirrors': (False, 'avalos_installer/network/mirrors.py', r'''"""
network/mirrors.py — sincronización de hora previa a cualquier operación
de red, y optimización de mirrors (rate-mirrors → reflector → mirrorlist
por defecto). Corresponde al tramo entre el paso "mount" y el paso
"pacstrap" de _run_instalacion en skill_instalar_usb.py (líneas
3843-3918) — el time-sync no tiene su propio PASOS_ID (corre "gratis"
antes de "mirrors"), pero se extrae acá y no en system/mount.py porque su
único propósito documentado en el original es proteger las operaciones de
red que siguen, no el montaje en sí.

Cambios de forma (no de lógica): `self.X` → `session.X`. Todos los
identificadores → inglés.
"""

from __future__ import annotations

import time

from avalos_installer.core.config import MIRROR_COUNTRIES
from avalos_installer.core.session import InstallSession


def sync_time(session: InstallSession):
    """Sincronización de hora ANTES de cualquier operación de red: si el
    reloj del sistema está mal (batería CMOS muerta, o NTP que no
    alcanzó a sincronizar en el boot), la validación de certificado TLS
    puede fallar igual contra CUALQUIER mirror — no es un problema de
    "este mirror en particular", es la hora local. Forzamos esto antes
    de tocar reflector/pacman."""
    session.log(session.t("log-timesync-start"), "info")
    session.run_cmd(["timedatectl", "set-ntp", "true"], timeout=10)
    for _attempt in range(10):
        rc, out = session.run_cmd(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=5
        )
        if rc == 0 and "yes" in out.strip().lower():
            session.log(session.t("log-timesync-ok"), "ok")
            return
        time.sleep(1)
    else:
        session.log(session.t("log-timesync-timeout"), "warn")


def optimize_mirrors(session: InstallSession):
    """rate-mirrors primero (más rápido y confiable); si falla instalarlo
    o correrlo, cae a reflector; si reflector también falla, se queda con
    el mirrorlist que ya trae el live. En los dos casos de éxito se le
    agrega al final un mirror grande fijo (Rackspace, siempre completo
    incluyendo multilib) como red de seguridad — el comentario de por qué
    es ligeramente distinto en cada rama porque el riesgo que cubre es
    distinto (hueco puntual del mirror elegido por rate-mirrors, vs.
    multilib incompleto/viejo en mirrors regionales de reflector)."""
    session.step("mirrors", "active")
    session.status(session.t("status-optimizing-mirrors"))
    session.log(session.t("log-section-mirrors"), "step")

    rc_rm_install, _ = session.run_cmd(
        ["pacman", "-Sy", "--noconfirm", "--needed", "rate-mirrors"], timeout=120
    )
    mirrors_ok = False
    if rc_rm_install == 0:
        # --allow-root y --save son opciones BASE: van antes del subcomando («arch»); después, clap
        # responde «unexpected argument '--allow-root' found» y siempre se caía a reflector.
        rc_rm, _ = session.run_cmd([
            "rate-mirrors", "--allow-root", "--save", "/etc/pacman.d/mirrorlist", "arch",
        ], timeout=90)
        if rc_rm == 0:
            mirrors_ok = True
            session.step("mirrors", "done", session.t("step-mirrors-optimized"))
            session.log(session.t("log-ratemirrors-ok"), "ok")

    if mirrors_ok:
        try:
            with open("/etc/pacman.d/mirrorlist", "a") as mlf:
                mlf.write(
                    "\n# Fallback agregado por el instalador: mirror grande y "
                    "siempre completo (incluye multilib), por si el mirror "
                    "elegido igual tiene algun hueco\n"
                    "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n"
                )
        except Exception as e:
            session.log(f"[WARN] No se pudo agregar mirror de respaldo: {e}", "warn")
        return

    session.log(session.t("log-ratemirrors-fallback"), "warn")
    rc_refl_install, out_refl_install = session.run_cmd(
        ["pacman", "-Sy", "--noconfirm", "--needed", "reflector"], timeout=120
    )
    if rc_refl_install != 0:
        session.step("mirrors", "skip", session.t("step-mirrors-default"))
        from avalos_installer.core.session import output_indicates_gpg_error
        if output_indicates_gpg_error(out_refl_install):
            session.log(session.t("log-pacman-gpg-signature-issue"), "err")
        else:
            session.log(session.t("log-reflector-install-fail"), "warn")
        return

    rc, _ = session.run_cmd([
        "reflector", "--country", MIRROR_COUNTRIES,
        "--latest", "10", "--sort", "rate",
        "--protocol", "https", "--save", "/etc/pacman.d/mirrorlist",
    ], timeout=120)
    if rc == 0:
        session.step("mirrors", "done", session.t("step-mirrors-optimized"))
        try:
            with open("/etc/pacman.d/mirrorlist", "a") as mlf:
                mlf.write(
                    "\n# Fallback agregado por el instalador: mirror grande y "
                    "siempre completo (incluye multilib), por si los mirrors "
                    "regionales de reflector tienen multilib incompleto/viejo\n"
                    "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n"
                )
        except Exception as e:
            session.log(f"[WARN] No se pudo agregar mirror de respaldo: {e}", "warn")
    else:
        session.step("mirrors", "skip", session.t("step-mirrors-default"))
        session.log(session.t("log-reflector-fail"), "warn")
'''),
    # ── avalos_installer/system/__init__.py (0 líneas)
    'avalos_installer.system': (True, 'avalos_installer/system/__init__.py', r''''''),
    # ── avalos_installer/system/aur.py (243 líneas)
    'avalos_installer.system.aur': (False, 'avalos_installer/system/aur.py', r'''"""
system/aur.py — bootstrap de yay desde AUR (git clone + makepkg -si como
usuario no-root, con sudoers temporal NOPASSWD), instalación de paquetes
AUR, y los extras de gaming (gamemode.ini, MangoHud.conf, flathub) que en
el original solo corren si yay funcionó. Corresponde al paso "aur" de
_run_instalacion en skill_instalar_usb.py (líneas 4857-4956).

Este es el módulo que quedaba pendiente a pedido explícito — el bug ya
diagnosticado (yay se salta intermitentemente) sigue exactamente igual,
sin corregir: la extracción es fiel, no es el lugar para meter el fix.
Hipótesis de esa sesión de diagnóstico, sin cambios: mismo problema de
raíz que los 404 de mirrors ya confirmados como reales (makepkg -s corre
'pacman -S go' internamente), o el propio git clone contra
aur.archlinux.org fallando — la salida real capturada en `out_yay` es lo
que lo confirma cuando vuelva a pasar.

Ningún fallo acá detiene la instalación completa (ni un solo `return` en
todo el bloque original) — yay fallido, AUR parcial, o gaming-extras
fallidos quedan como warnings logueados, igual que repos.py. Los extras
de gaming se quedan acá (no en system/optimize.py) porque en el original
están condicionados al mismo bloque `if` de "yay funcionó", no por
diseño temático — separarlos hubiera sido reorganizar de más.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`.
`usuario` → `ctx.username`. Todos los identificadores → inglés.
"""

from __future__ import annotations

import os
from pathlib import Path

from avalos_installer.core.config import MOUNT_ROOT, read_config
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession
from avalos_installer.system.pacstrap import HYPRLAND_AUR_PKGS, GAMING_AUR_PKGS


def write_user_mangohud_config(mount_root: Path, username: str, content: str) -> Path:
    """Deja la config de MangoHud donde MangoHud la lee: ~/.config/MangoHud/MangoHud.conf del usuario.

    MangoHud solo busca ./MangoHud.conf, $XDG_CONFIG_HOME/MangoHud/ (MangoHud.conf, <app>.conf y
    wine-<app>.conf) y $MANGOHUD_CONFIGFILE. /etc/MangoHud/MangoHud.conf, donde se dejaba antes, no
    lo lee nadie: el tema Tokyo Night nunca se veía. El instalador corre como root, así que lo que se
    crea dentro del home se entrega al usuario (uid/gid salen del /etc/passwd del sistema instalado:
    el home en sí no se toca). Lanza OSError/KeyError si no se puede; el que llama lo registra."""
    uid = gid = None
    for line in (mount_root / "etc" / "passwd").read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) >= 6 and fields[0] == username:
            uid, gid, home = int(fields[2]), int(fields[3]), fields[5]
            break
    if uid is None:
        raise KeyError(f"{username} no está en /etc/passwd del sistema instalado")
    base = mount_root / home.lstrip("/")
    created = []
    for folder in (base / ".config", base / ".config" / "MangoHud"):
        if not folder.exists():
            folder.mkdir()
            created.append(folder)
    target = base / ".config" / "MangoHud" / "MangoHud.conf"
    target.write_text(content, encoding="utf-8")
    for path in (*created, target):
        os.chown(path, uid, gid)
    return target


USERMOD_NO_SUCH_GROUP = 6  # usermod(8): «specified user/group doesn't exist» (sí, el mismo código para los dos)


def add_user_to_gamemode_group(session: InstallSession, username: str) -> bool:
    """Mete al usuario en el grupo «gamemode».

    La regla de polkit del paquete gamemode autoriza (sin contraseña) el helper que cambia el gobernador de
    la CPU solo a los miembros de ese grupo: sin él, el modo rendimiento del Game Center no funciona. El
    paquete crea el grupo con un hook de sysusers; si ese hook no corrió, usermod sale con 6 y antes el fallo
    pasaba sin dejar rastro. Aquí se crea el grupo, se reintenta una vez y el resultado queda en el log.
    """
    rc, out = session.run_chroot(["usermod", "-aG", "gamemode", username])
    if rc == USERMOD_NO_SUCH_GROUP:
        # El 6 también sale cuando falta el USUARIO: solo se crea el grupo si de verdad no existe
        # (getent, no el texto del error, que depende del idioma).
        group_rc, _ = session.run_chroot(["getent", "group", "gamemode"])
        if group_rc != 0:
            session.run_chroot(["groupadd", "-r", "gamemode"])
            rc, out = session.run_chroot(["usermod", "-aG", "gamemode", username])
    if rc == 0:
        session.log(session.t("log-gamemode-group-ok"), "ok")
        return True
    session.log(session.t("log-gamemode-group-failed", rc=rc, out=(out or "").strip()[-300:]), "warn")
    return False


def install_aur(session: InstallSession, ctx: InstallContext) -> None:
    session.step("aur", "active")
    session.status(session.t("status-installing-aur"))
    session.log("\n── yay + AUR ──\n", "step")

    # FIX (cuelgue de 85 min en "installing missing dependencies"): sudo lee
    # /etc/sudoers.d/ en orden alfabético y GANA LA ÚLTIMA regla que
    # coincide. El archivo persistente del grupo wheel (users.py) se llama
    # "wheel" ('%wheel ALL=(ALL:ALL) ALL', pide contraseña) y ordena DESPUÉS
    # de "99-aur-build" ('w' > '9'), así que le ganaba: el usuario recién
    # creado está en wheel y makepkg → 'sudo pacman -S go' terminaba pidiendo
    # una contraseña que nadie iba a escribir (el prompt salía en la terminal
    # desde la que se lanzó el instalador, nunca en el log). Probado con sudo
    # 1.9.15: wheel + 99-aur-build → "sudo: a password is required"; con este
    # nombre, que ordena después de todo, rc=0. La línea Defaults quita
    # además el prompt para este usuario sea cual sea el orden.
    sudoers_tmp = MOUNT_ROOT / "etc" / "sudoers.d" / "zz-avalos-aur-build"
    try:
        sudoers_tmp.write_text(
            f"Defaults:{ctx.username} !authenticate\n"
            f"{ctx.username} ALL=(ALL:ALL) NOPASSWD: ALL\n"
        )
        sudoers_tmp.chmod(0o440)
    except OSError:
        sudoers_tmp = None

    # SEGURIDAD: todo lo que sigue corre con sudo NOPASSWD activo para
    # ctx.username. El original limpiaba este archivo con una sola línea
    # secuencial al final de la función — si CUALQUIER cosa entre acá y
    # ahí tira una excepción sin capturar (el write_text de MangoHud.conf
    # más abajo no tenía try/except propio, a diferencia de gamemode.ini
    # dos líneas arriba), esa línea de limpieza nunca se alcanza y el
    # NOPASSWD queda para siempre en el sistema instalado: cualquier
    # proceso corriendo como ese usuario tiene root sin contraseña, sin
    # límite. Se envuelve todo en try/finally para que la limpieza corra
    # pase lo que pase, y se le agrega su propio try/except a MangoHud.
    try:
        # Comprobación previa (10 s en vez de un cuelgue de minutos): si sudo
        # sin contraseña no funciona, makepkg va a fallar exactamente igual.
        rc_sudo, out_sudo = session.run_chroot(
            ["sudo", "-H", "-u", ctx.username, "sudo", "-n", "true"], timeout=30
        )
        if rc_sudo != 0:
            session.log(session.t("log-aur-sudo-preflight-fail", out=out_sudo.strip()[-200:]), "warn")

        yay_script = (
            "set -euo pipefail; "
            "export GIT_TERMINAL_PROMPT=0; "
            "TMPD=$(mktemp -d) && "
            "git clone --depth=1 https://aur.archlinux.org/yay.git \"$TMPD/yay_build\" && "
            "cd \"$TMPD/yay_build\" && "
            "makepkg -si --noconfirm --needed && "
            "rm -rf \"$TMPD\""
        )
        # Sin captura de output ni reintento, un solo corte de red durante
        # el 'git clone' o durante la descarga de 'go' (makedepend de yay)
        # tira todo el bootstrap sin dejar rastro de POR QUE -- rc se veía
        # pero el output se descartaba (== "_"). Con todo lo que ya vimos
        # de mirrors/red inestables en esta build, vale un reintento igual
        # que el resto de la instalación.
        rc, out_yay = "", ""
        for attempt in range(2):
            rc, out_yay = session.run_chroot(
                ["sudo", "-H", "-u", ctx.username, "bash", "-c", yay_script], timeout=600
            )
            if rc == 0:
                break
            if attempt == 0:
                session.log(session.t("log-yay-retry"), "warn")

        if rc != 0:
            session.log(session.t("log-yay-not-installed", out=out_yay.strip()[-500:]), "warn")
            session.step("aur", "skip", session.t("step-yay-failed-label"))
        else:
            all_aur = HYPRLAND_AUR_PKGS + (GAMING_AUR_PKGS if ctx.install_gaming else [])
            if all_aur:
                rc_aur, out_aur = session.run_chroot(
                    ["sudo", "-H", "-u", ctx.username, "yay", "-S", "--noconfirm", "--needed"]
                    + all_aur, timeout=1800
                )
                if rc_aur != 0:
                    session.log(
                        session.t("log-aur-partial-fail", rc=rc_aur, out=out_aur.strip()[-500:]),
                        "warn"
                    )
                    session.step("aur", "done", session.t("step-aur-count-warn", n=len(all_aur)))
                else:
                    session.step("aur", "done", session.t("step-aur-count", n=len(all_aur)))
            else:
                session.step("aur", "done", session.t("step-aur-count-zero"))

        # La configuración de juegos (grupo gamemode, gamemode.ini, MangoHud, Flathub) no necesita yay: los
        # paquetes son de los repos oficiales. Antes esto vivía dentro del `else:` de arriba y, si el
        # bootstrap de AUR fallaba (red, makepkg), se saltaba entero y en silencio.
        if ctx.install_gaming:
            add_user_to_gamemode_group(session, ctx.username)

            gamemode_conf = (
                "[general]\n"
                "reaper_freq=5\n"
                "desiredgov=performance\n"
                "softrealtime=auto\n"
                "renice=-10\n\n"
                "[gpu]\n"
                "apply_gpu_optimisations=accept-responsibility\n"
                "gpu_device=0\n"
                "amd_performance_level=high\n\n"
                "[filter]\n"
                "whitelist=steam\nwhitelist=lutris\nwhitelist=heroic\n"
            )
            try:
                gm_path = MOUNT_ROOT / "etc" / "gamemode.ini"
                gm_path.write_text(gamemode_conf, encoding="utf-8")
                session.log(session.t("log-gamemode-ini-ok"), "ok")
            except OSError as e:
                session.log(f"[WARN] gamemode.ini: {e}", "warn")

            mango_content = read_config("mangohud/MangoHud.conf")
            if mango_content:
                try:
                    write_user_mangohud_config(MOUNT_ROOT, ctx.username, mango_content)
                    session.log(session.t("log-mangohud-ok"), "ok")
                except (OSError, KeyError, ValueError) as e:
                    session.log(f"[WARN] MangoHud.conf: {e}", "warn")

            # --user: las instalaciones de la tienda (avalos-store) son --user, así que el remoto va en la
            # configuración del usuario. Sin --user flatpak usa la instalación del SISTEMA y habla con su
            # helper por D-Bus, que dentro del chroot no existe («The name is not activatable»); además el
            # rc se ignoraba y se anunciaba un éxito falso. Si aun así falla, avalos-store lo agrega solo.
            rc_flat, _ = session.run_chroot(
                ["sudo", "-H", "-u", ctx.username, "flatpak", "remote-add", "--user",
                 "--if-not-exists", "flathub",
                 "https://dl.flathub.org/repo/flathub.flatpakrepo"],
                timeout=120
            )
            if rc_flat == 0:
                session.log(session.t("log-flathub-ok"), "ok")
            else:
                session.log(session.t("log-flathub-failed"), "warn")
    finally:
        if sudoers_tmp and sudoers_tmp.exists():
            try:
                sudoers_tmp.unlink()
            except OSError as e:
                session.log(
                    f"[WARN] no se pudo borrar el sudoers temporal de AUR "
                    f"({sudoers_tmp}) — revisar a mano, queda NOPASSWD activo "
                    f"para {ctx.username}: {e}",
                    "err",
                )
'''),
    # ── avalos_installer/system/bootloader.py (308 líneas)
    'avalos_installer.system.bootloader': (False, 'avalos_installer/system/bootloader.py', r'''"""
system/bootloader.py — instala el bootloader elegido (grub / refind /
sd-boot / none). Corresponde al paso "grub" (el PASOS_ID se sigue
llamando así aunque cubre los tres bootloaders) de _run_instalacion en
skill_instalar_usb.py (líneas 4463-4670).

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`. `dev`,
`dev_root`, `uefi`, `ucode` se reciben como parámetros — ya calculados
por pasos anteriores del orquestador. Todos los identificadores → inglés.

AVISO — hallazgo de esta pasada, ver el mensaje que acompaña esta
extracción: la rama sd-boot puede estar creando la entrada EFI de forma
silenciosamente incompleta por cómo se invoca bootctl. No se corrigió acá
— ver el comentario puntual en esa rama y la explicación completa fuera
del código.
"""

from __future__ import annotations

import glob
import shutil
from pathlib import Path

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession
from avalos_installer.core.shell import run_command

GRUB_UEFI_REMOVABLE = False


def _kernel_name(kernel_pkg: str | None) -> str:
    """Sufijo de /boot/vmlinuz-<nombre>. Se prefiere el kernel_pkg que devolvió pacstrap
    (vmlinuz-<pkgbase> lo instala el PKGBUILD); el glob queda de respaldo y ordenado,
    porque glob.glob() no garantiza orden y con más de un vmlinuz elegía uno al azar."""
    if kernel_pkg and (MOUNT_ROOT / "boot" / f"vmlinuz-{kernel_pkg}").exists():
        return kernel_pkg
    found = sorted(glob.glob(str(MOUNT_ROOT / "boot" / "vmlinuz-*")))
    return Path(found[0]).name.replace("vmlinuz-", "", 1) if found else "linux"


def install_bootloader(session: InstallSession, ctx: InstallContext,
                        dev: str, dev_root: str, uefi: bool, ucode: str,
                        kernel_pkg: str | None = None) -> bool:
    session.step("grub", "active")

    if ctx.bootloader == 'none':
        session.step("grub", "skip", session.t("step-bootloader-skipped-label"))
        session.log(session.t("log-bootloader-skipped"), "warn")
        return True

    elif ctx.bootloader == 'grub':
        session.status(session.t("status-installing-grub"))
        session.log(session.t("log-section-installing-grub"), "step")
        if uefi:
            # Id propio (no el genérico «GRUB»): grub-install borra las entradas UEFI que tengan el
            # mismo id y pisa EFI/<id>/, y «GRUB» es el que usa cualquier instalación manual de Arch
            # junto a la que se instala AvalOS. system/rollback.py reconoce «avalos» como nuestro.
            grub_cmd = ["grub-install", "--target=x86_64-efi",
                        "--efi-directory=/boot/efi", "--bootloader-id=AvalOS"]

            if GRUB_UEFI_REMOVABLE or ctx.usb_mode:
                grub_cmd.append("--removable")
            rc, _ = session.run_chroot(grub_cmd)

            # Respaldo: en instalacion normal (con entrada NVRAM),
            # instalar TAMBIEN en la ruta fija /EFI/BOOT/BOOTX64.EFI.
            # Protege contra NVRAM corrupta/reseteada/no soportada
            # que dejaria el disco sin forma de arrancar aunque
            # grub-install haya funcionado bien en su momento. No
            # bloquea la instalacion si este paso extra falla.
            if rc == 0 and not (GRUB_UEFI_REMOVABLE or ctx.usb_mode):
                rc_rem, _ = session.run_chroot([
                    "grub-install", "--target=x86_64-efi",
                    "--efi-directory=/boot/efi", "--removable"
                ])
                session.log(
                    session.t("log-grub-removable-ok" if rc_rem == 0 else "log-grub-removable-fail"),
                    "ok" if rc_rem == 0 else "warn"
                )
        else:
            rc, _ = session.run_chroot(["grub-install", "--target=i386-pc", dev])

        if rc != 0:
            session.step("grub", "error")
            session.error_step(session.t("err-grub-install-failed"))
            session.clean_mounts()
            return False

        gd_path = MOUNT_ROOT / "etc" / "default" / "grub"
        if gd_path.exists():
            lines = [l for l in gd_path.read_text().splitlines()
                     if not l.strip().startswith("GRUB_DISABLE_OS_PROBER")]
            lines.append("GRUB_DISABLE_OS_PROBER=false")
            gd_path.write_text("\n".join(lines) + "\n")
        rc_cfg, out_cfg = session.run_chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        # grub-install sin grub.cfg deja un disco que cae al prompt de GRUB. grub-mkconfig
        # escribe grub.cfg.new y lo mueve solo si termina bien, así que en una instalación
        # nueva "no existe / está vacío" = falló de verdad; rc != 0 con el archivo presente
        # solo se avisa.
        grub_cfg = MOUNT_ROOT / "boot" / "grub" / "grub.cfg"
        if rc_cfg != 0:
            session.log(f"[ERR] grub-mkconfig rc={rc_cfg}: {out_cfg.strip()[-500:]}", "err")
        if not grub_cfg.exists() or grub_cfg.stat().st_size == 0:
            session.step("grub", "error")
            session.error_step(session.t("err-grub-mkconfig-failed"))
            session.clean_mounts()
            return False
        session.step("grub", "done", session.t("step-grub-installed-label"))
        return True

    elif ctx.bootloader == 'refind':
        if not uefi:
            session.step("grub", "error")
            session.error_step(session.t("err-refind-needs-uefi"))
            session.clean_mounts()
            return False

        session.status(session.t("status-installing-refind"))
        session.log(session.t("log-section-installing-refind"), "step")

        rc, _ = session.run_chroot(["pacman", "-S", "--noconfirm", "--needed", "refind"])
        if rc != 0:
            session.step("grub", "error")
            session.error_step(session.t("err-refind-pkg-failed"))
            session.clean_mounts()
            return False

        rc, _ = session.run_chroot(["refind-install"])
        if rc != 0:
            session.step("grub", "error")
            session.error_step(session.t("err-refind-install-failed"))
            session.clean_mounts()
            return False

        rc_uuid, uuid_out, _ = run_command(["blkid", "-s", "UUID", "-o", "value", dev_root])
        root_uuid = uuid_out.strip() if rc_uuid == 0 and uuid_out.strip() else ""
        root_opts = (f"root=UUID={root_uuid}" if root_uuid else f"root={dev_root}")
        if not ctx.usb_mode:
            # Btrfs: sin esto el kernel monta el volumen top-level
            # (subvolid 5) en vez del subvolumen @ real -- no
            # arranca, cae a emergency shell. GRUB lo resuelve solo
            # via grub-mkconfig; rEFInd/sd-boot necesitan que se lo
            # pasemos a mano en el cmdline.
            root_opts += " rootflags=subvol=@"

        kernel_name = _kernel_name(kernel_pkg)
        session.log(session.t("log-kernel-detected", kernel_name=kernel_name), "info")

        refind_conf = MOUNT_ROOT / "boot" / "refind_linux.conf"
        refind_conf.write_text(
            f'"AvalOS (normal)"   "{root_opts} rw quiet splash loglevel=3"\n'
            f'"AvalOS (verbose)"  "{root_opts} rw"\n'
            f'"AvalOS (recovery)" "{root_opts} rw single"\n'
        )
        session.log(session.t("log-refind-conf-created"), "info")

        hook_dir = MOUNT_ROOT / "etc" / "pacman.d" / "hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "refind.hook").write_text(
            "[Trigger]\n"
            "Operation = Upgrade\n"
            "Type = Package\n"
            "Target = refind\n"
            "\n"
            "[Action]\n"
            "Description = Actualizando rEFInd en la ESP…\n"
            "When = PostTransaction\n"
            "Exec = /usr/bin/refind-install\n"
        )

        session.step("grub", "done", session.t("step-refind-installed-label", kernel_name=kernel_name))
        return True

    elif ctx.bootloader == 'sd-boot':
        if not uefi:
            session.step("grub", "error")
            session.error_step(session.t("err-sdboot-needs-uefi"))
            session.clean_mounts()
            return False

        session.status(session.t("status-installing-sdboot"))
        session.log(session.t("log-section-installing-sdboot"), "step")

        # HALLAZGO (verificado contra ArchWiki y varios reportes/issues de
        # systemd, la mayoria de 2025-2026, incluyendo systemd/systemd#36174
        # y #39002): 'bootctl install' corrido via arch-chroot normal (sin
        # -S) detecta que esta en un PID namespace y se abstiene de tocar
        # las variables EFI -- "Not booted with EFI or running in a
        # container, skipping EFI variable modifications" -- SIN marcarlo
        # como error (bootctl sigue devolviendo 0). O sea: esta llamada
        # probablemente instala los archivos de systemd-boot bien, pero es
        # muy probable que NO cree la entrada NVRAM "Linux Boot Manager".
        # FIX (aplicado): arch-chroot -S pone a bootctl en modo systemd real
        # (via systemd-run/nspawn), donde SI puede tocar variables EFI. Pero
        # -S es un flag relativamente nuevo de arch-install-scripts (agregado
        # en algun punto de 2025) -- hay al menos un reporte real (foro de
        # Arch, oct. 2025) de 'invalid option' en un archiso mas viejo que
        # todavia no lo tenia. Por eso el intento con -S va primero, y si
        # arch-chroot mismo lo rechaza (no bootctl -- arch-chroot), se
        # reintenta sin el flag: mismo comportamiento que antes de este fix,
        # nunca peor.
        rc, out = session.run_chroot(
            ["bootctl", "install", "--esp-path=/boot/efi"], systemd_mode=True
        )
        if rc != 0 and "invalid option" in out.lower():
            session.log(session.t("log-bootctl-no-systemd-mode"), "warn")
            rc, out = session.run_chroot(["bootctl", "install", "--esp-path=/boot/efi"])
        if rc != 0:
            session.step("grub", "error")
            session.error_step(session.t("err-bootctl-failed"))
            session.clean_mounts()
            return False

        kernel_name = _kernel_name(kernel_pkg)
        session.log(session.t("log-kernel-detected", kernel_name=kernel_name), "info")

        rc_uuid, uuid_out, _ = run_command(["blkid", "-s", "UUID", "-o", "value", dev_root])
        root_uuid = uuid_out.strip() if rc_uuid == 0 and uuid_out.strip() else ""

        esp_entries_dir = MOUNT_ROOT / "boot" / "efi" / "AvalOS"
        try:
            esp_entries_dir.mkdir(parents=True, exist_ok=True)

            shutil.copy2(MOUNT_ROOT / f"boot/vmlinuz-{kernel_name}",
                         esp_entries_dir / f"vmlinuz-{kernel_name}")
            initrd_src = MOUNT_ROOT / f"boot/initramfs-{kernel_name}.img"
            if initrd_src.exists():
                shutil.copy2(initrd_src, esp_entries_dir / f"initramfs-{kernel_name}.img")
        except OSError as e:
            # FIX: shutil.copy2 sin try/except -- si el glob de vmlinuz_files
            # no encontró nada (kernel_name cae al fallback "linux", que
            # puede no existir como archivo real), esto tiraba una excepción
            # sin capturar a mitad de la instalación del bootloader, en vez
            # de un fallo prolijo como el resto de esta función (step
            # "error" + error_step + clean_mounts + return False).
            session.step("grub", "error")
            session.error_step(session.t("err-sdboot-kernel-copy-failed", e=str(e)))
            session.clean_mounts()
            return False

        ucode_copied = False
        ucode_name = ""
        if ucode:
            ucode_name = f"{ucode}.img"
            ucode_src = MOUNT_ROOT / f"boot/{ucode_name}"
            if ucode_src.exists():
                shutil.copy2(ucode_src, esp_entries_dir / ucode_name)
                ucode_copied = True
                session.log(session.t("log-microcode-copied", ucode_name=ucode_name), "ok")
            else:
                session.log(session.t("log-microcode-missing", ucode_src=ucode_src), "warn")
        else:
            session.log(session.t("log-microcode-unidentified"), "warn")

        loader_dir = MOUNT_ROOT / "boot" / "efi" / "loader"
        loader_dir.mkdir(parents=True, exist_ok=True)
        (loader_dir / "loader.conf").write_text(
            "default  avalos.conf\n"
            "timeout  3\n"
            "console-mode auto\n"
            "editor   no\n"
        )

        entries_dir = loader_dir / "entries"
        entries_dir.mkdir(parents=True, exist_ok=True)
        root_opts = (f"root=UUID={root_uuid}" if root_uuid else f"root={dev_root}")
        if not ctx.usb_mode:
            root_opts += " rootflags=subvol=@"
        ucode_initrd_line = (
            f"initrd  /AvalOS/{ucode_name}\n" if ucode_copied else ""
        )
        (entries_dir / "avalos.conf").write_text(
            f"title   AvalOS\n"
            f"linux   /AvalOS/vmlinuz-{kernel_name}\n"
            f"{ucode_initrd_line}"
            f"initrd  /AvalOS/initramfs-{kernel_name}.img\n"
            f"options {root_opts} rw quiet splash loglevel=3\n"
        )

        hook_dir = MOUNT_ROOT / "etc" / "pacman.d" / "hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "95-systemd-boot.hook").write_text(
            "[Trigger]\n"
            "Type = Package\n"
            f"Target = {kernel_name}\n"
            # El microcode también se copia a la ESP: sin este Target, un update de
            # amd-ucode/intel-ucode dejaba la copia de la ESP vieja hasta el próximo kernel.
            + (f"Target = {ucode}\n" if ucode else "") +
            "Operation = Install\n"
            "Operation = Upgrade\n"
            "\n"
            "[Action]\n"
            "Description = Updating systemd-boot kernel files\n"
            "When = PostTransaction\n"
            f"Exec = /usr/bin/bash -c '"
            f"cp /boot/vmlinuz-{kernel_name} /boot/efi/AvalOS/vmlinuz-{kernel_name}; "
            f"cp /boot/initramfs-{kernel_name}.img /boot/efi/AvalOS/initramfs-{kernel_name}.img; "
            f"[[ -n \"{ucode}\" ]] && [[ -f /boot/{ucode}.img ]] && cp /boot/{ucode}.img /boot/efi/AvalOS/{ucode}.img || true'\n"
            "Depends = bash\n"
        )

        # Mantiene el binario de systemd-boot de la ESP al día tras updates de systemd.
        session.run_chroot(["systemctl", "enable", "systemd-boot-update.service"])
        session.step("grub", "done", session.t("step-sdboot-installed-label"))
        return True

    return True
'''),
    # ── avalos_installer/system/fstab.py (68 líneas)
    'avalos_installer.system.fstab': (False, 'avalos_installer/system/fstab.py', r'''"""
system/fstab.py — genera /etc/fstab con genfstab -U, con dos ajustes:
noatime en modo USB (reduce desgaste en el pendrive), y la eliminación de
subvolid= (que rompe grub-btrfs al arrancar snapshots). Corresponde al
paso "fstab" de _run_instalacion en skill_instalar_usb.py (líneas
4214-4256).

El comentario original sobre por qué subvolid rompe grub-btrfs se dejó
intacto — es la explicación técnica completa de uno de los bugs más
sutiles de todo el instalador (una entrada de fstab que en apariencia es
correcta, pero pisa silenciosamente la elección de snapshot del usuario
al arrancar).

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`. Todos
los identificadores → inglés.
"""

from __future__ import annotations

import re

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession


def generate_fstab(session: InstallSession, ctx: InstallContext) -> bool:
    session.step("fstab", "active")
    session.status(session.t("status-generating-fstab"))
    rc, fstab_out = session.run_cmd(["genfstab", "-U", str(MOUNT_ROOT)])
    if rc != 0 or not fstab_out.strip():
        session.step("fstab", "error")
        session.error_step(session.t("err-genfstab-failed"))
        session.clean_mounts()
        return False

    if ctx.usb_mode:
        fstab_out = fstab_out.replace("relatime", "noatime")

        def _add_noatime(m):
            opts = m.group(0)
            if "noatime" not in opts and "vfat" not in opts.lower():
                return opts.replace("defaults", "defaults,noatime", 1)
            return opts
        fstab_out = re.sub(r'(defaults[^\s]*)', _add_noatime, fstab_out)

    # subvolid=NNN (que genfstab -U inserta solo en lineas Btrfs) es
    # una referencia ABSOLUTA al subvolumen -- tiene prioridad sobre
    # subvol=@nombre y por eso ROMPE grub-btrfs: al arrancar una
    # snapshot desde el menu de GRUB, el kernel monta la snapshot
    # via cmdline, pero systemd despues remonta root segun fstab, y
    # con subvolid= fijo siempre vuelve al @ original sin importar
    # que snapshot se eligio. Se saca en las dos posiciones posibles
    # (antes o al final de la lista de opciones) para dejar solo
    # subvol=@... funcionando como se espera.
    fstab_out = re.sub(r'subvolid=\d+,', '', fstab_out)
    fstab_out = re.sub(r',subvolid=\d+', '', fstab_out)

    try:
        (MOUNT_ROOT / "etc" / "fstab").write_text(fstab_out + "\n")
    except OSError as e:
        session.step("fstab", "error")
        session.error_step(session.t("err-fstab-write-failed", e=e))
        session.clean_mounts()
        return False

    session.step("fstab", "done")
    return True
'''),
    # ── avalos_installer/system/locale.py (286 líneas)
    'avalos_installer.system.locale': (False, 'avalos_installer/system/locale.py', r'''"""
system/locale.py — configuración regional (timezone, locale, keymap),
identidad del sistema (hostname, os-release, GRUB_DISTRIBUTOR), password
de root, y los hooks de mkinitcpio necesarios para arrancar sobre Btrfs
(+ grub-btrfs-overlayfs si el bootloader es GRUB). Corresponde al paso
"config" de _run_instalacion en skill_instalar_usb.py (líneas 4257-4459).

Dos comentarios originales se dejaron completos porque documentan bugs
sutiles ya resueltos: por qué os-release se escribe ANTES de grub (10_linux
de grub-mkconfig lo lee una sola vez al generar el menú), y por qué
GRUB_DISTRIBUTOR en /etc/default/grub —no os-release— es lo que realmente
controla el título "Arch Linux" que aparecía en el menú de GRUB.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`.
`kernel_pkg` (antes `self._kernel_pkg`, fijado durante pacstrap) se recibe
como parámetro — es el valor que ahora devuelve
system.pacstrap.run_pacstrap(). Todos los identificadores → inglés.
"""

from __future__ import annotations

import re

from avalos_installer.core.buildstamp import build_id
from avalos_installer.core.config import MOUNT_ROOT, VCONSOLE_TO_XKB, AVALOS_REPO
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession


def write_os_release(session: InstallSession) -> None:
    """/etc/os-release de AvalOS. BUILD_ID es el build de la ISO con la que se instaló (el sello del CI, ver
    core/buildstamp.py), o «rolling» si la ISO no trae sello; Fastfetch lo muestra en su línea OS."""
    build = build_id() or "rolling"
    session.write_file("etc/os-release", f"""\
NAME="AvalOS"
PRETTY_NAME="AvalOS"
ID=avalos
ID_LIKE=arch
BUILD_ID={build}
ANSI_COLOR="38;2;122;162;247"
HOME_URL="https://github.com/{AVALOS_REPO}"
DOCUMENTATION_URL="https://wiki.archlinux.org"
LOGO=avalos-logo
""")


def configure_locale(session: InstallSession, ctx: InstallContext, kernel_pkg: str) -> bool:
    session.step("config", "active")
    session.status(session.t("status-configuring-system"))
    session.log(session.t("log-section-system-config"), "step")

    session.run_chroot(["ln", "-sf", f"/usr/share/zoneinfo/{ctx.timezone}", "/etc/localtime"])
    session.run_chroot(["hwclock", "--systohc"])

    loc = ctx.locale
    loc_gen = f"{loc} UTF-8"
    keymap = ctx.keymap

    loc_gen_extra = "en_US.UTF-8 UTF-8"

    extra_locales = [loc_gen, loc_gen_extra]
    if loc.startswith("zh_") and "zh_CN.UTF-8 UTF-8" not in extra_locales:
        extra_locales.append("zh_CN.UTF-8 UTF-8")

    locale_gen_path = MOUNT_ROOT / "etc" / "locale.gen"
    if locale_gen_path.exists():
        txt = locale_gen_path.read_text()
        for loc_entry in extra_locales:
            txt = txt.replace(f"#{loc_entry}", loc_entry)
            txt = txt.replace(f"# {loc_entry}", loc_entry)
            if loc_entry not in txt:
                txt += f"\n{loc_entry}\n"
        locale_gen_path.write_text(txt)
    else:
        session.log(session.t("log-localegen-missing"), "warn")
        locale_gen_path.parent.mkdir(parents=True, exist_ok=True)
        locale_gen_path.write_text("\n".join(extra_locales) + "\n")

    # FIX: en al menos una instalación real, locale-gen falló para
    # es_SV.UTF-8 puntualmente con "cannot open locale definition file
    # `es_SV': No such file or directory", mientras en_US.UTF-8 sí
    # generaba bien — faltaba el archivo fuente en
    # /usr/share/i18n/locales/es_SV (parte del paquete glibc) en ESE
    # chroot puntual. es_SV es un locale real y válido (está en
    # SUPPORTED upstream de glibc), así que esto es extracción
    # incompleta de glibc, no un locale inválido — causa de fondo
    # todavía sin confirmar. Se verifica el archivo fuente ANTES de
    # generar y, si falta, se reextrae SOLO usr/share/i18n/locales/
    # desde el propio .pkg.tar.zst de glibc que ya está en la cache de
    # pacstrap — más seguro que reinstalar glibc entero a mitad de
    # instalación.
    i18n_locales_dir = MOUNT_ROOT / "usr" / "share" / "i18n" / "locales"
    missing_defs = []
    for loc_entry in extra_locales:
        base = loc_entry.split(".")[0]
        if base not in missing_defs and not (i18n_locales_dir / base).exists():
            missing_defs.append(base)
    if missing_defs:
        session.log(
            f"  [WARN] faltan definiciones de locale en glibc: "
            f"{', '.join(missing_defs)} — reextrayendo desde la cache de pacman",
            "warn",
        )
        session.run_chroot([
            "bash", "-c",
            "f=(/var/cache/pacman/pkg/glibc-*.pkg.tar.zst); "
            "[ -e \"${f[0]}\" ] && bsdtar -xf \"${f[0]}\" -C / usr/share/i18n/locales/"
        ])

    # Antes esto se llamaba sin capturar rc/output: si locale-gen
    # fallaba (o generaba todo MENOS el locale pedido) quedaba en
    # silencio total -- nada en el log, nada en pantalla -- y recien
    # te enterabas con "setlocale: cannot change locale" ya en el
    # sistema instalado y arrancado, sin ninguna pista de a que paso
    # apuntar. El texto que arma loc_gen/extra_locales de arriba
    # ya se verifico a mano contra un locale.gen real de Arch y
    # contra locale-gen real (genera "es_SV.UTF-8... done" limpio),
    # asi que si esto llega a fallar en un run concreto el problema
    # esta en ESTE chroot puntual, no en la logica -- por eso vale
    # la pena verificar explicitamente en vez de asumir.
    rc_locgen, out_locgen = session.run_chroot(["locale-gen"])
    if rc_locgen != 0:
        session.log(session.t("log-localegen-failed", loc=loc, rc=rc_locgen,
                               out=out_locgen.strip()[-300:]), "err")
    else:
        rc_check, out_check = session.run_chroot(["locale", "-a"])
        loc_norm = loc.replace("-", "").lower()
        if loc_norm not in out_check.replace("-", "").lower():
            session.log(session.t("log-localegen-verify-fail", loc=loc,
                                   out=out_locgen.strip()[-300:]), "err")
        else:
            session.log(session.t("log-localegen-verify-ok", loc=loc), "ok")

    (MOUNT_ROOT / "etc" / "locale.conf").write_text(f"LANG={loc}\n")
    (MOUNT_ROOT / "etc" / "vconsole.conf").write_text(f"KEYMAP={keymap}\n")
    xkb_layout = VCONSOLE_TO_XKB.get(keymap, keymap)
    xorg_kbd_dir = MOUNT_ROOT / "etc" / "X11" / "xorg.conf.d"
    xorg_kbd_dir.mkdir(parents=True, exist_ok=True)
    (xorg_kbd_dir / "00-keyboard.conf").write_text(
        "Section \"InputClass\"\n"
        "    Identifier \"system-keyboard\"\n"
        "    MatchIsKeyboard \"yes\"\n"
        f"    Option \"XkbLayout\" \"{xkb_layout}\"\n"
        "EndSection\n"
    )
    session.log(session.t("log-locale-keymap", loc=loc, keymap=keymap), "ok")
    (MOUNT_ROOT / "etc" / "hostname").write_text(ctx.hostname + "\n")
    (MOUNT_ROOT / "etc" / "hosts").write_text(
        f"127.0.0.1   localhost\n::1         localhost\n127.0.1.1   {ctx.hostname}.localdomain {ctx.hostname}\n"
    )

    # os-release/lsb-release ANTES de grub (paso siguiente): el
    # 10_linux de grub-mkconfig lee NAME/PRETTY_NAME de os-release UNA
    # sola vez, al generar grub.cfg, y hornea ese texto en las
    # entradas del menu. Antes esto se escribia recien en el paso
    # 'hypr' (el ULTIMO paso, dentro de configure_hyprland) -- para
    # ese momento grub-mkconfig ya habia corrido dos veces (bootloader
    # + snapper/grub-btrfs) contra el os-release de fabrica de Arch,
    # asi que el menu quedaba diciendo "Arch Linux" para siempre por
    # mas que el archivo en si ya dijera AvalOS.
    write_os_release(session)
    session.write_file("etc/lsb-release", """\
LSB_VERSION=1.4
DISTRIB_ID=AvalOS
DISTRIB_RELEASE=rolling
DISTRIB_CODENAME=avalos
DISTRIB_DESCRIPTION="AvalOS"
""")

    # BUG-FIX (GRUB siempre decia "Arch Linux"): GRUB_DISTRIBUTOR en
    # /etc/default/grub -- NO /etc/os-release -- es lo que el
    # 10_linux de grub-mkconfig usa para armar el titulo de cada
    # entrada del menu (literalmente "${GRUB_DISTRIBUTOR} Linux").
    # De fabrica el paquete grub de Arch trae esa linea fija en
    # "Arch" (o resuelta via `lsb_release`, binario que ni siquiera
    # esta instalado aca, cayendo al fallback "Arch Linux"). Escribir
    # os-release antes de grub-mkconfig (arriba) NUNCA iba a arreglar
    # esto porque 10_linux ni lo lee para este proposito -- son dos
    # mecanismos totalmente separados. Se pisa aca, antes de CUALQUIER
    # grub-mkconfig, y sin condicionar a usb_mode: si hay GRUB
    # tiene que decir AvalOS sea instalacion a disco o a USB.
    grub_default_early = MOUNT_ROOT / "etc" / "default" / "grub"
    if grub_default_early.exists():
        try:
            gd_txt = grub_default_early.read_text()
            gd_txt, n_distrib = re.subn(
                r'^GRUB_DISTRIBUTOR=.*$',
                'GRUB_DISTRIBUTOR="AvalOS"',
                gd_txt,
                flags=re.MULTILINE,
            )
            if n_distrib == 0:
                gd_txt += '\nGRUB_DISTRIBUTOR="AvalOS"\n'
            grub_default_early.write_text(gd_txt)
            session.log(session.t("log-grub-distributor-set"), "ok")
        except OSError as e:
            session.log(session.t("log-grub-distributor-fail", e=e), "warn")

    rc_pw, out_pw = session.run_chroot_stdin(f"root:{ctx.password}\n", ["chpasswd"])
    if rc_pw != 0:
        session.log(session.t("log-chpasswd-root-fail", rc=rc_pw, out=out_pw), "err")
        session.step("config", "error")
        session.error_step(session.t("err-chpasswd-failed", usuario="root"))
        session.clean_mounts()
        return False

    if not ctx.usb_mode:
        mkinit_path = MOUNT_ROOT / "etc" / "mkinitcpio.conf"
        if mkinit_path.exists():
            mkinit_txt = mkinit_path.read_text()

            if "btrfs" not in mkinit_txt:
                mkinit_txt = re.sub(
                    r'^(HOOKS=\([^)]*)\bfilesystems\b',
                    r'\1btrfs filesystems',
                    mkinit_txt,
                    flags=re.MULTILINE
                )
                mkinit_path.write_text(mkinit_txt)
                session.log(session.t("log-mkinitcpio-btrfs-added"), "ok")
            else:
                session.log(session.t("log-mkinitcpio-btrfs-present"), "ok")

            mkinit_txt = mkinit_path.read_text()
            if ("grub-btrfs-overlayfs" not in mkinit_txt
                    and ctx.bootloader == "grub"):
                mkinit_txt = re.sub(
                    r'^(HOOKS=\([^)]*)\bfsck\b',
                    r'\1fsck grub-btrfs-overlayfs',
                    mkinit_txt,
                    flags=re.MULTILINE
                )
                mkinit_path.write_text(mkinit_txt)
                session.log(session.t("log-mkinitcpio-overlayfs-added"), "ok")

        grub_default = MOUNT_ROOT / "etc" / "default" / "grub"
        if grub_default.exists():
            grub_txt = grub_default.read_text()
            grub_btrfs_additions = []
            if "GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION" not in grub_txt:
                grub_btrfs_additions.append(
                    "GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION=true"
                )
            if "GRUB_DISABLE_OS_PROBER" not in grub_txt:
                grub_btrfs_additions.append("GRUB_DISABLE_OS_PROBER=false")
            if grub_btrfs_additions:
                grub_txt += "\n# AvalOS Btrfs snapshot support\n"
                grub_txt += "\n".join(grub_btrfs_additions) + "\n"
                grub_default.write_text(grub_txt)
                session.log(session.t("log-grub-btrfs-configured"), "ok")

    # mkinitcpio -P procesa TODOS los .preset que encuentre en
    # mkinitcpio.d/, no solo el del kernel instalado. Si quedó un
    # preset huérfano apuntando a un vmlinuz que no existe (ej.
    # 'linux.preset' -> /boot/vmlinuz-linux, cuando lo único
    # instalado es linux-avalos), falla con "must be readable" —
    # no rompe la transacción de pacman, pero ensucia el log y no
    # debería estar ahí. Se deja solo el preset del kernel real.
    presets_dir = MOUNT_ROOT / "etc" / "mkinitcpio.d"
    if presets_dir.is_dir():
        valid_preset = f"{kernel_pkg}.preset"
        for p in presets_dir.glob("*.preset"):
            if p.name != valid_preset:
                try:
                    p.unlink()
                    session.log(session.t("log-mkinitcpio-stray-preset-removed", preset=p.name), "warn")
                except OSError as e:
                    session.log(session.t("log-mkinitcpio-stray-preset-error", preset=p.name, e=e), "warn")

    rc_initcpio, out_initcpio = session.run_chroot(["mkinitcpio", "-P"])
    # Antes el rc se descartaba: si mkinitcpio fallaba (hook inexistente, preset borrado
    # de más...) la instalación terminaba "con éxito" en un sistema que no arranca. El
    # initramfs del pacstrap puede seguir ahí aunque -P falle (sin los hooks nuevos, pero
    # normalmente booteable), así que rc != 0 con imagen presente solo avisa; sin imagen
    # es fatal.
    initramfs_img = MOUNT_ROOT / "boot" / f"initramfs-{kernel_pkg}.img"
    if rc_initcpio != 0:
        session.log(f"[ERR] mkinitcpio -P rc={rc_initcpio}: {out_initcpio.strip()[-500:]}", "err")
    if not initramfs_img.exists():
        session.step("config", "error")
        session.error_step(session.t("err-initramfs-failed"))
        session.clean_mounts()
        return False
    session.step("config", "done", "locale · timezone · hostname · initramfs · btrfs-hook"
                 if not ctx.usb_mode else "locale · timezone · hostname · initramfs")
    return True
'''),
    # ── avalos_installer/system/mount.py (111 líneas)
    'avalos_installer.system.mount': (False, 'avalos_installer/system/mount.py', r'''"""
system/mount.py — monta el root (con sus subvolúmenes Btrfs si aplica) y
la partición EFI bajo MOUNT_ROOT, más el chequeo de espacio libre que
corre justo después. Corresponde al paso "mount" de _run_instalacion en
skill_instalar_usb.py (líneas ~3767-3841).

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`; los
paths de partición (antes `dev_root`/`dev_efi`, variables locales de
_run_instalacion) se reciben como parámetros — vienen del
PartitionResult que devuelve system.partition.partition_and_format().
Todos los identificadores → inglés.
"""

from __future__ import annotations

import shutil

from avalos_installer.core.config import MOUNT_ROOT, MOUNT_EFI, BTRFS_MOUNT_OPTS
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession

# Chequeo de espacio ANTES de gastar minutos en mirrors/pacstrap. Con "-c"
# fuera del pacstrap (fix anterior: cache ahora vive en MOUNT_ROOT, no en
# el host), mejor fallar acá en segundos con mensaje claro que a mitad de
# pacstrap con curl reintentando contra un disco lleno. 20 GiB es
# conservador para base+Hyprland+drivers+firmware+fuentes CJK+gaming
# (Steam/Wine).
MIN_FREE_SPACE_GB = 20


def mount_filesystems(session: InstallSession, ctx: InstallContext,
                       root_device: str, efi_device: str, uefi: bool) -> bool:
    if session._aborted:
        session.clean_mounts()
        return False

    session.step("mount", "active")
    MOUNT_ROOT.mkdir(parents=True, exist_ok=True)

    if ctx.usb_mode:
        rc, _ = session.run_cmd(["mount", root_device, str(MOUNT_ROOT)])
        if rc != 0:
            session.step("mount", "error")
            session.error_step(session.t("err-mount-failed", dev_root=root_device))
            session.clean_mounts()
            return False
    else:
        rc, _ = session.run_cmd(["mount", "-o", f"subvol=@,{BTRFS_MOUNT_OPTS}", root_device, str(MOUNT_ROOT)])
        if rc != 0:
            session.step("mount", "error")
            session.error_step(session.t("err-mount-subvol-failed", dev_root=root_device))
            session.clean_mounts()
            return False

        subvol_mounts = [
            ("@home", MOUNT_ROOT / "home"),
            ("@snapshots", MOUNT_ROOT / ".snapshots"),
            ("@log", MOUNT_ROOT / "var" / "log"),
            ("@cache", MOUNT_ROOT / "var" / "cache"),
            ("@tmp", MOUNT_ROOT / "tmp"),
        ]
        for sv_name, sv_path in subvol_mounts:
            sv_path.mkdir(parents=True, exist_ok=True)
            sv_opts = f"subvol={sv_name},{BTRFS_MOUNT_OPTS}"
            if sv_name == "@tmp":
                sv_opts += ",nodatacow"
            rc_sv, _ = session.run_cmd(["mount", "-o", sv_opts, root_device, str(sv_path)])
            if rc_sv != 0:
                session.log(session.t("log-subvol-mount-fail", sv_name=sv_name, sv_path=sv_path), "warn")
                if sv_name in ("@home", "@snapshots"):
                    # Sin @home el /home cae dentro de @ y un restore (que intercambia @)
                    # pisaría los datos del usuario; sin @snapshots Snapper no puede
                    # crear snapshots. Seguir adelante dejaría una instalación con el
                    # layout equivocado sin que nadie se entere: se aborta.
                    session.step("mount", "error")
                    session.error_step(session.t("err-mount-subvol-failed", dev_root=root_device))
                    session.clean_mounts()
                    return False
            elif sv_name == "@tmp":
                session.run_cmd(["chattr", "+C", str(sv_path)])
                session.log(session.t("log-tmp-cow-disabled"), "ok")

        session.log(session.t("log-subvols-mounted-ok"), "ok")

    if uefi:
        MOUNT_EFI.mkdir(parents=True, exist_ok=True)
        rc, _ = session.run_cmd(["mount", efi_device, str(MOUNT_EFI)])
        if rc != 0:
            session.step("mount", "error")
            session.error_step(session.t("err-mount-efi-failed", dev_efi=efi_device))
            session.clean_mounts()
            return False

    session.step("mount", "done")
    return True


def check_disk_space(session: InstallSession, min_gb: int = MIN_FREE_SPACE_GB) -> bool:
    try:
        free_gb = shutil.disk_usage(MOUNT_ROOT).free / (1024 ** 3)
    except Exception as e:
        # Si no se pudo determinar el espacio libre, el original no
        # bloquea la instalación por eso — solo avisa y sigue.
        session.log(session.t("log-diskcheck-error", e=e), "warn")
        return True
    if free_gb < min_gb:
        session.error_fatal(session.t("err-disk-space-low", libre=f"{free_gb:.1f}", minimo=min_gb))
        session.clean_mounts()
        return False
    session.log(session.t("log-diskcheck-ok", libre=f"{free_gb:.1f}"), "ok")
    return True
'''),
    # ── avalos_installer/system/optimize.py (468 líneas)
    'avalos_installer.system.optimize': (False, 'avalos_installer/system/optimize.py', r'''"""
system/optimize.py — instala los scripts propios de AvalOS (settings,
wallpaper, about, update, update-helper, store + su catálogo, .desktop,
polkit policies, ícono) y aplica el tuning de sistema (ZRAM, systemd-oomd,
sysctl, IO scheduler por tipo de disco, DNS-over-TLS).

Extraído de VentanaInstalador._configurar_optimizaciones en
skill_instalar_usb.py (líneas 2750-3042). Lógica y comentarios
explicativos sin cambios — incluye el razonamiento completo de por qué
cada polkit policy es propia (no la genérica de freedesktop), por qué el
catálogo de la store no lleva el prefijo scripts/, y por qué avalos-lang
existe aparte de LANG del sistema.

Nota: este método hace dos cosas bastante distintas (instalar los
binarios/assets propios de AvalOS, y tunear el sistema) que en el
monolito viven juntas por orden de ejecución, no por diseño. Se dejaron
juntas acá también — separarlas es un cambio de estructura, no una
extracción fiel, y no es lo que se pidió en esta pasada.

Cambios respecto al original (solo de forma, no de lógica):
- `self.X` → `session.X`
- `self._lang` → parámetro `lang`
- `self._install_gaming` / `self._install_bore` (leídos con getattr por si
  no existían todavía en __init__) → parámetros `install_gaming` /
  `install_bore`, con el mismo default False
- `disco_tipo` → `disk_type`
- todos los identificadores restantes → inglés
"""

from __future__ import annotations

import datetime

from avalos_installer.core.buildstamp import install_stamp
from avalos_installer.core.config import MOUNT_ROOT, read_config
from avalos_installer.core.session import InstallSession


def configure_optimizations(session: InstallSession, gpu_info: dict, cpu_arch: str,
                             disk_type: str, lang: str,
                             install_gaming: bool = False, install_bore: bool = False):
    """Configura ZRAM+zstd, systemd-oomd, BBR, IO scheduler, sysctl y binarios de sistema."""

    session.log(session.t("log-section-optimizations"), "step")

    _bin_dir = MOUNT_ROOT / "usr/local/bin"
    _bin_dir.mkdir(parents=True, exist_ok=True)
    _gpu_env_bin = _bin_dir / "avalos-gpu-env"
    _gpu_env_bin.write_text(
        "#!/bin/bash\n"
        "# AvalOS: detecta GPU y actualiza el bloque hl.env(...) de hyprland.lua\n"
        "# para cada usuario, entre los marcadores AVALOS_GPU_ENV_START/END.\n"
        "set -uo pipefail\n\n"
        "# Solo lineas de tarjeta grafica: 'amd' sobre TODO lspci matchea el Root Complex\n"
        "# de cualquier CPU AMD y forzaba el entorno RADV/radeonsi aunque la GPU fuera NVIDIA.\n"
        "GPUS=\"$(lspci 2>/dev/null | grep -iE 'vga compatible|3d controller|display controller')\"\n"
        "if grep -qiE 'amd|radeon' <<< \"$GPUS\"; then\n"
        "    GPU_BLOCK='hl.env(\"AMD_VULKAN_ICD\",    \"RADV\")\n"
        "hl.env(\"VDPAU_DRIVER\",      \"radeonsi\")\n"
        "hl.env(\"LIBVA_DRIVER_NAME\", \"radeonsi\")'\n"
        "elif grep -qi 'intel' <<< \"$GPUS\"; then\n"
        "    GPU_BLOCK='hl.env(\"LIBVA_DRIVER_NAME\", \"iHD\")\n"
        "hl.env(\"VDPAU_DRIVER\",      \"va_gl\")'\n"
        "else\n"
        "    # GPU desconocida: no tocar hyprland.lua, dejar el bloque existente.\n"
        "    exit 0\n"
        "fi\n\n"
        "for hypr_conf in /home/*/.config/hypr/hyprland.lua; do\n"
        "    [[ -f \"$hypr_conf\" ]] || continue\n"
        "    if ! grep -q 'AVALOS_GPU_ENV_START' \"$hypr_conf\"; then\n"
        "        # Marcadores no presentes (instalación antigua o editados por\n"
        "        # el usuario) — no reemplazar a ciegas, evitar corromper el archivo.\n"
        "        continue\n"
        "    fi\n"
        "    # BUG-FIX (permission denied en hyprland.lua tras cada boot):\n"
        "    # owner/modo se leian DESPUES del mv (ver git blame), o sea del\n"
        "    # archivo temporal de mktemp (root:root, 0600 -- este script\n"
        "    # corre como root via avalos-gpu-detect.service, Before=sddm),\n"
        "    # no del hyprland.lua original del usuario. El chown de mas\n"
        "    # abajo terminaba re-confirmando root:root en vez de restaurar\n"
        "    # al usuario real, y el modo 0600 de mktemp quedaba puesto. Con\n"
        "    # este servicio corriendo ANTES de sddm en cada arranque,\n"
        "    # hyprland.lua del usuario quedaba root:root justo antes de que\n"
        "    # el usuario pudiera loguearse -- exactamente 'Permission\n"
        "    # denied' al abrir su propio config (y por eso Hyprland caia a\n"
        "    # sus colores/tema por defecto: nunca llegaba a leer el archivo\n"
        "    # con Tokyo Night). Fix: capturar owner Y modo ANTES de pisar\n"
        "    # el archivo, restaurar los dos despues del mv.\n"
        "    owner=\"$(stat -c '%U:%G' \"$hypr_conf\")\"\n"
        "    mode=\"$(stat -c '%a' \"$hypr_conf\")\"\n"
        "    tmp=\"$(mktemp)\"\n"
        "    awk -v block=\"$GPU_BLOCK\" '\n"
        "        /-- AVALOS_GPU_ENV_START/ { print; print block; skip=1; next }\n"
        "        /-- AVALOS_GPU_ENV_END/   { skip=0; print; next }\n"
        "        skip { next }\n"
        "        { print }\n"
        "    ' \"$hypr_conf\" > \"$tmp\" && mv \"$tmp\" \"$hypr_conf\"\n"
        "    chown \"$owner\" \"$hypr_conf\"\n"
        "    chmod \"$mode\" \"$hypr_conf\"\n"
        "done\n"
    )
    _gpu_env_bin.chmod(0o755)
    session.log(session.t("log-gpu-env-installed"), "ok")

    session.log(session.t("log-installing-scripts"), "info")
    _avalos_scripts = ("avalos-settings", "avalos-wallpaper", "avalos-about",
                       "avalos-update", "avalos-update-helper", "avalos-store", "avalos-restore", "avalos-doctor", "avalos-welcome", "avalos-control", "avalos-gamecenter", "avalos-version")
    for _script_name in _avalos_scripts:
        _content = read_config(f"scripts/{_script_name}")
        if _content:
            _script_path = _bin_dir / _script_name
            _script_path.write_text(_content, encoding="utf-8")
            _script_path.chmod(0o755)
            session.log(session.t("log-script-installed", script=_script_name), "ok")
        else:
            session.log(session.t("log-script-missing", script=_script_name), "warn")

    # Comprobación final: si algún script no quedó en /usr/local/bin, que el log lo diga
    # con nombre en vez de que "no se instaló" se descubra al buscar la app.
    _scripts_faltantes = [n for n in _avalos_scripts if not (_bin_dir / n).is_file()]
    if _scripts_faltantes:
        session.log(session.t("log-scripts-incomplete", names=", ".join(_scripts_faltantes)), "err")

    # Sello de build de la ISO (build + hash de cada script): lo lee avalos-version.
    install_stamp(session)

    # avalos-store necesita su catálogo de apps aparte — no es un script
    # ejecutable, es data, así que va directo a configs/ (sin el prefijo
    # "scripts/" que usan los .desktop por el bug histórico de abajo) y
    # sin chmod 755.
    _content = read_config("avalos-store-catalog.json")
    if _content:
        (_bin_dir / "avalos-store-catalog.json").write_text(_content, encoding="utf-8")
        session.log(session.t("log-script-installed", script="avalos-store-catalog.json"), "ok")
    else:
        session.log(session.t("log-script-missing", script="avalos-store-catalog.json"), "warn")

    _apps_dir = MOUNT_ROOT / "usr" / "share" / "applications"
    _apps_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("scripts/avalos-settings.desktop")
    if _content:
        (_apps_dir / "avalos-settings.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-settings-desktop-installed"), "ok")
    else:
        session.log(session.t("log-settings-desktop-missing"), "warn")

    _content = read_config("scripts/avalos-store.desktop")
    if _content:
        (_apps_dir / "avalos-store.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-store-desktop-installed"), "ok")
    else:
        session.log(session.t("log-store-desktop-missing"), "warn")

    # avalos-update no tenía entrada de escritorio: el script se instalaba en
    # /usr/local/bin pero no aparecía en rofi (drun) ni en ningún menú, así que
    # para el usuario "no estaba instalado".
    _content = read_config("avalos-update.desktop")
    if _content:
        (_apps_dir / "avalos-update.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-update-desktop-installed"), "ok")
    else:
        session.log(session.t("log-update-desktop-missing"), "warn")

    # avalos-update necesita pkexec para elevar avalos-update-helper (ver
    # avalos-update.policy) — polkitd + hyprpolkitagent ya corren en el
    # sistema instalado (servicios habilitados / exec-once de Hyprland),
    # así que lo único que falta es que la acción exista donde polkit la
    # busca. 0644, NO ejecutable: polkitd solo necesita leerla.
    _polkit_dir = MOUNT_ROOT / "usr" / "share" / "polkit-1" / "actions"
    _polkit_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("avalos-update.policy")
    if _content:
        _policy_path = _polkit_dir / "com.avalos.update.policy"
        _policy_path.write_text(_content, encoding="utf-8")
        _policy_path.chmod(0o644)
        session.log(session.t("log-polkit-policy-installed"), "ok")
    else:
        session.log(session.t("log-polkit-policy-missing"), "warn")

    # avalos-store: mismo mecanismo de polkit que avalos-update (ver
    # comentario arriba), acción separada (com.avalos.store.policy) para
    # que pkexec pacman -S/-R dentro de avalos-store recuerde la sesión
    # (auth_admin_keep) y muestre mensaje/ícono propios de AvalOS, en vez
    # de caer en la acción genérica org.freedesktop.policykit.exec (sin
    # policy dedicada, pkexec pide contraseña en CADA instalación/
    # desinstalación de la Store, sin recordar nada entre una app y la
    # siguiente — ver avalos-store.policy para el detalle completo).
    _content = read_config("avalos-store.policy")
    if _content:
        _policy_path = _polkit_dir / "com.avalos.store.policy"
        _policy_path.write_text(_content, encoding="utf-8")
        _policy_path.chmod(0o644)
        session.log(session.t("log-store-polkit-policy-installed"), "ok")
    else:
        session.log(session.t("log-store-polkit-policy-missing"), "warn")

    # Ícono de avalos-store en el theme hicolor del sistema, para que
    # Icon=avalos-store (en avalos-store.desktop) resuelva a algo real en
    # vez de caer al ícono genérico de "aplicación desconocida" — mismo
    # spec que ya usa el propio avalos-store para resolver íconos de
    # terceros (_HICOLOR_ROOTS/_HICOLOR_SIZES), aplicado ahora a sí mismo.
    # scalable/ porque es un SVG: un solo archivo cubre todos los tamaños
    # que el spec de FreeDesktop Icon Theme pida, sin necesidad de
    # generar rasters en 48/64/128/256 aparte.
    _icon_dir = MOUNT_ROOT / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    _icon_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("avalos-store.svg")
    if _content:
        (_icon_dir / "avalos-store.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-store-icon-installed"), "ok")
    else:
        session.log(session.t("log-store-icon-missing"), "warn")

    _content = read_config("avalos-update.svg")
    if _content:
        (_icon_dir / "avalos-update.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-update-icon-installed"), "ok")
    else:
        session.log(session.t("log-update-icon-missing"), "warn")

    # avalos-restore: mismo caso que avalos-update en su momento (script sin
    # entrada de escritorio ni ícono = "no está instalado" para quien lo busca).
    _content = read_config("avalos-restore.desktop")
    if _content:
        (_apps_dir / "avalos-restore.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-restore-desktop-installed"), "ok")
    else:
        session.log(session.t("log-restore-desktop-missing"), "warn")

    # avalos-doctor: mismo caso (chequeo de salud, solo lectura; sin polkit).
    _content = read_config("avalos-doctor.desktop")
    if _content:
        (_apps_dir / "avalos-doctor.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-doctor-desktop-installed"), "ok")
    else:
        session.log(session.t("log-doctor-desktop-missing"), "warn")

    # avalos-welcome: bienvenida del primer arranque (solo abre otras apps; sin polkit).
    _content = read_config("avalos-welcome.desktop")
    if _content:
        (_apps_dir / "avalos-welcome.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-welcome-desktop-installed"), "ok")
    else:
        session.log(session.t("log-welcome-desktop-missing"), "warn")

    # avalos-control: centro de control (solo abre otras apps y lee datos; sin polkit).
    _content = read_config("avalos-control.desktop")
    if _content:
        (_apps_dir / "avalos-control.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-control-desktop-installed"), "ok")
    else:
        session.log(session.t("log-control-desktop-missing"), "warn")

    # avalos-gamecenter: lanzadores, GameMode, perfiles de MangoHud (todo como usuario, sin polkit).
    _content = read_config("avalos-gamecenter.desktop")
    if _content:
        (_apps_dir / "avalos-gamecenter.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-gamecenter-desktop-installed"), "ok")
    else:
        session.log(session.t("log-gamecenter-desktop-missing"), "warn")

    _content = read_config("avalos-restore.svg")
    if _content:
        (_icon_dir / "avalos-restore.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-restore-icon-installed"), "ok")
    else:
        session.log(session.t("log-restore-icon-missing"), "warn")

    _content = read_config("avalos-doctor.svg")
    if _content:
        (_icon_dir / "avalos-doctor.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-doctor-icon-installed"), "ok")
    else:
        session.log(session.t("log-doctor-icon-missing"), "warn")

    _content = read_config("avalos-welcome.svg")
    if _content:
        (_icon_dir / "avalos-welcome.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-welcome-icon-installed"), "ok")
    else:
        session.log(session.t("log-welcome-icon-missing"), "warn")

    _content = read_config("avalos-control.svg")
    if _content:
        (_icon_dir / "avalos-control.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-control-icon-installed"), "ok")
    else:
        session.log(session.t("log-control-icon-missing"), "warn")

    _content = read_config("avalos-gamecenter.svg")
    if _content:
        (_icon_dir / "avalos-gamecenter.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-gamecenter-icon-installed"), "ok")
    else:
        session.log(session.t("log-gamecenter-icon-missing"), "warn")

    (MOUNT_ROOT / "etc" / "avalos-install-date").write_text(
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        encoding="utf-8"
    )

    # Idioma real de UI (en/es/zh/ja) elegido en el instalador, para que
    # apps del sistema (avalos-wallpaper, avalos-settings, futuras apps)
    # lo lean directo sin tener que adivinarlo mal desde LANG (que es el
    # locale REGIONAL — es_MX/es_AR/pt_BR/etc, un valor totalmente
    # distinto al idioma de traducción de la UI, y ni siquiera cubre
    # los 4 idiomas soportados: pt_BR o fr_FR no tienen equivalente acá).
    (MOUNT_ROOT / "etc" / "avalos-lang").write_text(
        lang + "\n",
        encoding="utf-8"
    )

    # Perfil de instalación (gaming/bore) para que herramientas
    # post-instalación (avalos-store) sepan qué eligió el usuario acá
    # sin tener que re-detectarlo. Una flag por línea, solo las que
    # quedaron en True — mismo espíritu que avalos-lang: un archivo,
    # una fuente de verdad, nada de parsear config compartida.
    _profile_flags = []
    if install_gaming:
        _profile_flags.append("gaming")
    if install_bore:
        _profile_flags.append("bore")
    (MOUNT_ROOT / "etc" / "avalos-profile").write_text(
        ("\n".join(_profile_flags) + "\n") if _profile_flags else "",
        encoding="utf-8"
    )

    zram_path = MOUNT_ROOT / "etc" / "systemd" / "zram-generator.conf"
    zram_path.parent.mkdir(parents=True, exist_ok=True)
    zram_path.write_text(
        "[zram0]\n"
        "# ZRAM: swap comprimido en RAM — AvalOS\n"
        "# Limita a min(RAM_total/2, 8GB) — estándar zram-generator\n"
        "zram-size = min(ram / 2, 8192)\n"
        "compression-algorithm = zstd\n"
        "swap-priority = 100\n"
    )
    session.log(session.t("log-zram-ok"), "ok")

    oomd_conf = MOUNT_ROOT / "etc" / "systemd" / "oomd.conf"
    oomd_conf.write_text(
        "[OOM]\n"
        "# Mata procesos cuando la presión de swap supera el 85%\n"
        "SwapUsedLimit=85%\n"
        "# o cuando la presión de memoria supera el 70% por más de 10s\n"
        "DefaultMemoryPressureLimit=70%\n"
        "DefaultMemoryPressureDurationSec=10s\n"
    )
    session.run_chroot(["systemctl", "enable", "systemd-oomd"])
    session.log(session.t("log-oomd-ok"), "ok")

    sysctl_dir = MOUNT_ROOT / "etc" / "sysctl.d"
    sysctl_dir.mkdir(parents=True, exist_ok=True)

    (sysctl_dir / "80-avalos-memory.conf").write_text(
        "# AvalOS: memory tuning (conservador, medido)\n"
        "# Reduce agresividad de swap (ZRAM lo maneja)\n"
        "vm.swappiness = 10\n"
        "# Cache de VFS: más agresivo en retener inodos/dentries\n"
        "vm.vfs_cache_pressure = 50\n"
        "# Dirty pages: escribir antes de que sea urgente\n"
        "vm.dirty_ratio = 10\n"
        "vm.dirty_background_ratio = 5\n"
        "# Tiempo máximo de dirty pages antes de flush\n"
        "vm.dirty_expire_centisecs = 3000\n"
        "vm.dirty_writeback_centisecs = 500\n"
    )
    session.log(session.t("log-sysctl-mem-ok"), "ok")

    (sysctl_dir / "81-avalos-bbr.conf").write_text(
        "# AvalOS: BBR congestion control (mainline desde Linux 4.9, muy estable)\n"
        "# FQ como qdisc (requerido por BBR)\n"
        "net.core.default_qdisc = fq\n"
        "# BBR: mejor throughput y latencia que CUBIC\n"
        "net.ipv4.tcp_congestion_control = bbr\n"
        "# Buffers de red razonables\n"
        "net.core.rmem_max = 16777216\n"
        "net.core.wmem_max = 16777216\n"
        "net.ipv4.tcp_rmem = 4096 87380 16777216\n"
        "net.ipv4.tcp_wmem = 4096 65536 16777216\n"
    )
    session.log("  BBR: net.ipv4.tcp_congestion_control=bbr + fq", "ok")

    (sysctl_dir / "82-avalos-security.conf").write_text(
        "# AvalOS: seguridad mínima razonable\n"
        "kernel.dmesg_restrict = 1\n"
        "kernel.kptr_restrict = 1\n"
        "net.ipv4.conf.default.rp_filter = 1\n"
        "net.ipv4.conf.all.rp_filter = 1\n"
    )
    session.log(session.t("log-sysctl-security-ok"), "ok")

    udev_dir = MOUNT_ROOT / "etc" / "udev" / "rules.d"
    udev_dir.mkdir(parents=True, exist_ok=True)
    (udev_dir / "60-avalos-iosched.rules").write_text(
        '# AvalOS: IO scheduler automático por tipo de disco\n'
        '# HDD → bfq  (justo, buena latencia interactiva)\n'
        'ACTION=="add|change", KERNEL=="sd[a-z]*", '
        'ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"\n'
        '# SSD SATA → mq-deadline  (simple, baja latencia)\n'
        'ACTION=="add|change", KERNEL=="sd[a-z]*", '
        'ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"\n'
        '# NVMe → kyber  (diseñado para baja latencia NVMe)\n'
        'ACTION=="add|change", KERNEL=="nvme[0-9n]*", '
        'ATTR{queue/scheduler}="kyber"\n'
        '# eMMC → mq-deadline\n'
        'ACTION=="add|change", KERNEL=="mmcblk[0-9]*", '
        'ATTR{queue/scheduler}="mq-deadline"\n'
    )
    session.log(session.t("log-io-scheduler", disco_tipo=disk_type), "ok")

    # FIX: el bloque DNS-over-TLS vivía acá mismo, corriendo ANTES de
    # create_user()/configure_repos()/install_aur() en el orden real del
    # orquestador (configure_optimizations corre en la línea 291 de
    # core/install.py, install_aur en la 313 — antes, no después). Pisa
    # /etc/resolv.conf con un symlink a .../stub-resolv.conf, un archivo
    # que systemd-resolved recién genera cuando el servicio ARRANCA de
    # verdad — cosa que nunca pasa dentro de un chroot (systemctl enable
    # ahí abajo solo arma el symlink de habilitación para el próximo
    # boot real, no arranca nada). Resultado: desde acá en adelante,
    # CUALQUIER resolución DNS dentro del chroot queda rota — incluido
    # el 'git clone' de yay más adelante, que es exactamente el "Could
    # not resolve host: aur.archlinux.org" que se está viendo. Se saca
    # de acá y se llama aparte (ver enable_dns_over_tls) recién después
    # de install_aur(), para que todo lo que necesita red dentro del
    # chroot durante la instalación siga teniendo un resolv.conf que
    # funciona.

    session.log(
        session.t("log-summary-cpu-gpu-disk", cpu_arch=cpu_arch,
                   gpu_vendor=gpu_info["vendor"].upper(), gpu_model=gpu_info["model"],
                   disco_tipo=disk_type.upper()),
        "ok"
    )


def enable_dns_over_tls(session: InstallSession) -> None:
    """Configura systemd-resolved con DNS-over-TLS para el sistema instalado.

    Se llama DESPUÉS de install_aur() a propósito — ver el comentario
    en configure_optimizations() de por qué no puede ir antes.
    """
    resolved_conf = MOUNT_ROOT / "etc" / "systemd" / "resolved.conf"
    resolved_conf.write_text(
        "[Resolve]\n"
        "# AvalOS: DNS-over-TLS con Cloudflare + Google\n"
        "DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com "
        "8.8.8.8#dns.google 8.8.4.4#dns.google\n"
        "FallbackDNS=9.9.9.9#dns.quad9.net\n"
        # opportunistic, no yes: con "yes" estricto, si el puerto 853 o esos servidores no
        # son alcanzables (China bloquea 1.1.1.1/8.8.8.8; portales cautivos, hoteles y redes
        # corporativas filtran 853) NO hay DNS y el sistema queda sin red. opportunistic usa
        # TLS cuando puede y cae a DNS normal cuando no.
        "DNSOverTLS=opportunistic\n"
        "DNSSEC=allow-downgrade\n"
        "Cache=yes\n"
        "DNSStubListener=yes\n"
    )

    try:
        (MOUNT_ROOT / "etc" / "resolv.conf").unlink(missing_ok=True)
        (MOUNT_ROOT / "etc" / "resolv.conf").symlink_to(
            "../run/systemd/resolve/stub-resolv.conf"
        )
    except OSError as e:
        session.log(session.t("log-resolvconf-fail", e=e), "warn")
    session.run_chroot(["systemctl", "enable", "systemd-resolved"])
    session.log("  DNS-over-TLS: systemd-resolved (Cloudflare + Google + Quad9)", "ok")
'''),
    # ── avalos_installer/system/pacstrap.py (607 líneas)
    'avalos_installer.system.pacstrap': (False, 'avalos_installer/system/pacstrap.py', r'''"""
system/pacstrap.py — arma la lista de paquetes, resuelve qué variante de
kernel instalar, corre un preflight de disponibilidad (con recorte
automático de extras lib32- caídos y diálogo manual si hace falta), y
ejecuta pacstrap de verdad con reintento bajando el paralelismo de
descargas. Corresponde al paso "pacstrap" de _run_instalacion en
skill_instalar_usb.py (líneas 3922-4210).

Las listas de paquetes (BASE_PKGS, BTRFS_PKGS, HYPRLAND_PKGS, GAMING_PKGS,
etc.) se quedan acá porque es el único lugar que las consume hoy — si en
el futuro existe un profiles/gaming.py real con más lógica que solo la
lista de paquetes, GAMING_PKGS/GAMING_AUR_PKGS se mudan ahí. Por ahora,
moverlas hubiera sido reorganizar de más, no una extracción fiel.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`. La
llamada anidada `_pacman_disponible` del original pasa a ser una función
de módulo `_pacman_package_available`. Todos los identificadores → inglés.

Cambios posteriores (de lógica): se pide 'rofi' en vez del alias 'rofi-wayland'; 'grub-btrfs'
solo se instala con GRUB (ya solo se usaba ahí); y los dos
fatales que retornaban con el root ya montado (kernel sin repo / diálogo de mirror rechazado)
ahora llaman a clean_mounts(), como dice el docstring de run_pacstrap: sin eso el botón
"Reintentar" chocaba con los montajes del intento anterior en el chequeo de partition.py.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import time

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession, output_indicates_gpg_error

BASE_PKGS = [
    "base", "base-devel",
    # El desglose por vendor de linux-firmware (AMD/Intel/red/bluetooth, sin
    # NVIDIA) vive centralizado en el PKGBUILD de linux-avalos-firmware (repo
    # [avalos], pkgs/linux-avalos-firmware/PKGBUILD) en vez de duplicado acá
    # paquete por paquete — evita que esta lista y ese PKGBUILD diverjan con
    # el tiempo (ya pasó: esta lista no traía marvell/mellanox/qcom/qlogic/
    # nfp/liquidio que sí están en el PKGBUILD) y adopta automáticamente
    # cualquier ajuste futuro de Arch al desglose de vendors sin tener que
    # tocar el instalador. 'linux-avalos-firmware' provides+conflicts contra
    # el 'linux-firmware' oficial de Arch, así que nunca coexisten ambos.
    "linux-avalos-firmware",
    "sof-firmware",
    "grub", "efibootmgr", "os-prober", "ntfs-3g", "networkmanager", "nm-connection-editor", "wireless-regdb",
    "sudo", "bash", "bash-completion", "nano", "vim", "git", "curl", "wget", "htop",
    "python", "python-pip", "man-db", "man-pages", "less", "openssh",
    "zip", "unzip", "p7zip", "zram-generator",
    "reflector", "pacman-contrib", "xdg-utils", "udiskie",
    "fastfetch", "bat", "github-cli",
    "btrfs-progs",
]

BTRFS_PKGS = [
    "snapper",
    "snap-pac",
    "grub-btrfs",
    "inotify-tools",
]

HYPRLAND_PKGS = [
    "hyprland", "uwsm", "libnewt", "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk",
    # rofi 2.0+ ya trae el backend Wayland (antes era el paquete aparte 'rofi-wayland', que
    # Arch absorbió en 'rofi'). Se pide 'rofi' directo: si Arch retira el alias, 'rofi-wayland'
    # daría "target not found", que NO es lib32- y por eso no se recorta solo: bloquearía
    # TODAS las instalaciones en el preflight.
    "xdg-user-dirs", "kitty", "waybar", "rofi", "mako",
    "hyprpaper", "hyprlock", "hypridle", "hyprpicker",
    "grim", "slurp", "wl-clipboard", "cliphist",
    "pipewire", "pipewire-alsa", "pipewire-pulse", "pipewire-jack",
    "wireplumber", "pavucontrol",
    "qt5-quickcontrols2",
    "qt5-wayland", "qt6-wayland", "gtk3", "gtk4", "hyprpolkitagent",
    "thunar", "gvfs", "brightnessctl",
    "ttf-font-awesome", "ttf-jetbrains-mono-nerd", "ttf-nerd-fonts-symbols",
    "noto-fonts", "noto-fonts-emoji", "noto-fonts-cjk",
    "sddm", "network-manager-applet", "blueman",
    "playerctl", "firefox", "bluez", "bluez-utils", "libnotify", "sound-theme-freedesktop",
    "file-roller", "thunar-archive-plugin", "thunar-volman",
    "gvfs-mtp", "gvfs-smb", "nwg-look", "nwg-displays", "papirus-icon-theme",
    "lm_sensors", "acpi", "capitaine-cursors",
    "python-pywebview", "python-gobject", "webkit2gtk-4.1",
    # archlinux-appstream-data: catálogo oficial de metadata AppStream de los
    # repos [core]/[extra]/[multilib], con los íconos reales (48/64/128px) de
    # la inmensa mayoría de paquetes empaquetados — no es dependencia de
    # pywebview, es lo que avalos-store usa para mostrar el ícono REAL de una
    # app en la tarjeta ANTES de instalarla (sin esto, apps sin flathub_id en
    # el catálogo solo muestran su ícono real una vez ya instaladas, porque
    # ahí sí lo trae el propio paquete en /usr/share/icons/hicolor/).
    "archlinux-appstream-data",
    # hicolor-icon-theme: casi con certeza llega igual como dependencia
    # transitiva de gtk3/gtk4 (ya en esta lista), pero se deja explícito acá
    # porque es la pieza de la que depende directamente que el propio ícono
    # de avalos-store.svg (instalado por el instalador en hicolor/scalable/
    # apps/) resuelva en el theme — 55KB, sin costo real, sin dejarlo librado
    # a una dependencia transitiva sin confirmar contra el .PKGINFO real.
    "hicolor-icon-theme",
]

HYPRLAND_AUR_PKGS: list[str] = []

GAMING_PKGS = [
    "steam",
    "wine-staging",
    "wine-gecko", "wine-mono",
    "winetricks",
    "lib32-gnutls", "lib32-libpulse", "lib32-alsa-plugins",
    "lib32-libx11", "lib32-libxext", "lib32-libxcomposite",
    "lib32-libxrandr", "lib32-libxinerama", "lib32-libxi",
    "lib32-sdl2-compat", "lib32-freetype2",
    "lib32-gst-plugins-base-libs",
    "vkd3d",
    "gamemode", "lib32-gamemode",
    "mangohud", "lib32-mangohud",
    "lutris",
    "flatpak",
    "lib32-pipewire",
    "gst-plugins-bad", "gst-plugins-ugly", "gst-libav",
]

GAMING_AUR_PKGS = [
    "proton-ge-custom-bin",
    "heroic-games-launcher-bin",
]


def _pacman_package_available(session: InstallSession, pkg: str,
                               attempts: int = 4, wait: int = 6) -> bool:
    last_output = ""
    for i in range(attempts):
        cmd = ["pacman", "-Syi" if i == 0 else "-Syyi", "--noconfirm", pkg]
        rc, last_output = session.run_cmd(cmd, timeout=25, log_cls="info")
        if rc == 0:
            return True
        if i < attempts - 1:
            session.log(
                session.t("log-kernel-retry", pkg=pkg, intento=i + 2, total=attempts), "warn"
            )
            time.sleep(wait)
    if output_indicates_gpg_error(last_output):
        session.log(session.t("log-pacman-gpg-signature-issue"), "err")
    return False


# Índices ya sincronizados del live (pacman -Sy los deja acá).
LIVE_PACMAN_DBPATH = "/var/lib/pacman"

# Tres formas de «esta dependencia no tiene salida» (pacman 6): sin base local previa, con un
# paquete que la rompe, y la advertencia de resolución cuando la dependencia lleva versión.
_DEP_CONFLICT_RE = re.compile(
    r"unable to satisfy dependency '[^']+' required by (?P<a>\S+)"
    r"|installing \S+ \([^)]+\) breaks dependency '[^']+' required by (?P<b>\S+)"
    r'|cannot resolve "[^"]*[<>=][^"]*", a dependency of "(?P<c>[^"]+)"'
)


def _make_preflight_dbpath() -> str | None:
    """Base de datos local VACÍA para el preflight, con los índices (sync) del live.

    pacstrap instala en un root nuevo, o sea con la base local vacía: el preflight tiene que
    resolver contra lo mismo. Con la base local del live, lo que ya trae la ISO (lib32-mesa y
    con él lib32-libelf...) cuenta como instalado y pacman contesta «installing libelf
    (0.197-1) breaks dependency 'libelf=0.196' required by lib32-libelf» por un paquete del
    LIVE: quitar paquetes de la lista del destino no lo arregla nunca (reproducido con pacman
    6.0.2) y el diálogo de mirror reaparecía. Devuelve None si no se pudo armar y el preflight
    sigue como antes, contra la base del live."""
    sync = os.path.join(LIVE_PACMAN_DBPATH, "sync")
    if not os.path.isdir(sync):
        return None
    path = None
    try:
        path = tempfile.mkdtemp(prefix="avalos-preflight-")
        os.makedirs(os.path.join(path, "local"))
        os.symlink(sync, os.path.join(path, "sync"))
    except OSError:
        if path:
            shutil.rmtree(path, ignore_errors=True)
        return None
    return path


def dependency_conflict_packages(output: str) -> list[str]:
    """Paquetes que pacman señala por una dependencia que no se puede satisfacer, en orden de
    aparición y sin repetir. Cubre «unable to satisfy dependency 'X' required by P», «installing
    Y (v) breaks dependency 'X' required by P» y «cannot resolve "X>=v", a dependency of "P"»
    (este último solo si la dependencia lleva versión: sin versión es un paquete que no existe y
    lo trata el recorte de «target not found»)."""
    found: list[str] = []
    for m in _DEP_CONFLICT_RE.finditer(output):
        name = m.group("a") or m.group("b") or m.group("c")
        if name and name not in found:
            found.append(name)
    return found


def _sync_repos(pacman_conf: str, dbpath: str | None, names: list[str]) -> dict[str, str]:
    """{paquete: repo} según los índices sincronizados (pacman -Si). Lo que pacman no conoce
    no aparece. LC_ALL=C: los nombres de los campos se traducen con el locale."""
    if not names:
        return {}
    cmd = ["pacman", "-Si", "--config", pacman_conf] + (["--dbpath", dbpath] if dbpath else []) + names
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return {}
    repos: dict[str, str] = {}
    repo = None
    for line in res.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Repository":
            repo = value
        elif key == "Name" and repo:
            repos[value] = repo
            repo = None
    return repos


def multilib_desync_culprits(pacman_conf: str, dbpath: str | None, output: str,
                             pkgs: list[str]) -> list[str]:
    """Paquetes de NUESTRA lista que están en multilib y que pacman señala como imposibles de
    instalar. Con la base local vacía pacman lista toda la cadena de dependientes hasta los
    paquetes explícitos (lib32-libelf ← lib32-llvm-libs ← lib32-mesa ← steam), así que alcanza
    con cruzar esa lista con `pkgs`."""
    implicated = dependency_conflict_packages(output)
    candidates = [p for p in pkgs if p in implicated]
    repos = _sync_repos(pacman_conf, dbpath, candidates)
    return [p for p in candidates if repos.get(p) == "multilib"]


def preflight_error_summary(output: str, limit: int = 400) -> str:
    """Lo que dijo pacman, sin la barra de progreso de curl (XferCommand) que ensuciaba el
    detalle del diálogo de mirror."""
    pieces = [ln.strip() for ln in re.split(r"[\r\n]+", output)]
    keep: list[str] = []
    for ln in pieces:
        if ln.startswith(("error:", "warning:", "::")) and ln not in keep:
            keep.append(ln)
    if not keep:
        keep = [ln for ln in pieces
                if re.search(r"[A-Za-z]{3}", ln) and not ln.startswith(("%", "Dload"))][-3:]
    text = " · ".join(keep) or output.strip()[-300:]
    return text if len(text) <= limit else text[:limit - 1] + "…"


def multilib_skipped_notice(session: InstallSession) -> str:
    """Bloque HTML para la pantalla final cuando multilib desincronizado obligó a omitir paquetes
    (steam, lib32-mesa...) y el usuario tiene que instalarlos después. Los omitidos por «target not
    found» no cuentan: no hay nada que instalar luego. Vacío si no hubo."""
    skipped = getattr(session, "multilib_skipped", None) or []
    if not skipped:
        return ""
    names = [html.escape(p) for p in skipped]
    return session.t("done-multilib-skipped", pkgs=", ".join(names), cmd=" ".join(names))


def _preflight_packages(session: InstallSession, pkgs: list[str],
                         pacman_conf_target: str) -> tuple[str, list[str]] | None:
    """Preflight de disponibilidad de la lista de paquetes: recorta lo que Arch tiene caído
    (extras lib32- que no existen, paquetes de multilib desincronizado) y, si falla otra cosa,
    deja decidir al usuario en el diálogo de mirror. Quita de `pkgs` (en el lugar) lo omitido.
    Devuelve (salida del preflight que pasó, paquetes omitidos), o None si hay que cortar
    (error ya reportado y clean_mounts() ya llamado)."""
    skipped_pkgs: list[str] = []
    desync_dropped: list[str] = []      # solo lo omitido por multilib desincronizado
    session.multilib_skipped = []
    pf_dbpath = _make_preflight_dbpath()
    pf_opts = ["--dbpath", pf_dbpath] if pf_dbpath else []
    try:
        while True:
            preflight_ok = False
            preflight_out = ""
            for preflight_attempt in range(3):
                pf_cmd = ["pacman", "-Sp" if preflight_attempt == 0 else "-Syyp",
                          "--config", pacman_conf_target, *pf_opts, "--noconfirm"] + pkgs
                pf_rc, preflight_out = session.run_cmd(pf_cmd, timeout=120, log_cls="info")
                if pf_rc == 0:
                    preflight_ok = True
                    break
                # Un conflicto de dependencias es determinista: refrescar los índices UNA vez
                # alcanza (un mirror rezagado sí puede arreglarlo); más vueltas con espera no.
                conflict = bool(dependency_conflict_packages(preflight_out))
                if conflict and preflight_attempt >= 1:
                    break
                if preflight_attempt < 2:
                    session.log(
                        session.t("log-kernel-retry", pkg="multilib",
                                   intento=preflight_attempt + 2, total=3), "warn"
                    )
                    if not conflict:
                        time.sleep(6)
            if preflight_ok:
                session.multilib_skipped = sorted(set(desync_dropped))
                return preflight_out, skipped_pkgs

            # Dos frases distintas de pacman para "esto no existe": 'target
            # not found: X' (típico cuando X está directo en nuestra lista)
            # y 'cannot resolve "X"' (visto en foros reales — CachyOS tuvo
            # este mismo lib32-gst-plugins-base-libs así en abr-may 2026).
            # Se capturan las dos para que el recorte de abajo no dependa
            # de cuál de las dos decida usar pacman.
            missing_pkgs = sorted(set(
                re.findall(r"target not found:\s*(\S+)", preflight_out)
                + re.findall(r'cannot resolve\s*"([^"]+)"', preflight_out)
            ))
            trimmable = [p for p in missing_pkgs if p.startswith("lib32-")]
            if trimmable and all(p in pkgs for p in trimmable):
                # Se puede recortar: son paquetes lib32- explícitos de
                # NUESTRA lista (no dependencias transitivas de otra
                # cosa), así que sacarlos es seguro y no deja nada a
                # medias. Visto en producción (hilo de CachyOS, abr-may
                # 2026, CVE en el stack multimedia lib32): Arch a veces
                # retira paquetes lib32-gst-*/lib32-sdl2* de multilib
                # entero por semanas mientras responde a un CVE — pasa
                # en TODOS los mirrors por igual, así que ni reintentar
                # ni cambiar de mirror lo arregla. Mejor seguir sin
                # ellos que bloquear toda la instalación por un extra
                # de compatibilidad.
                #
                # El recorte queda LIMITADO a lib32- a propósito: un
                # 'target not found' en linux-avalos-firmware, un
                # kernel, o cualquier otro paquete no-lib32 NUNCA se
                # auto-recorta en silencio — cae al diálogo de mirror
                # de abajo, porque faltar ahí sí deja un sistema roto
                # (sin firmware de hardware, sin kernel, etc), a
                # diferencia de un extra de compatibilidad multilib.
                for p in trimmable:
                    pkgs.remove(p)
                skipped_pkgs += trimmable
                session.log(
                    session.t("log-multilib-pkg-dropped", pkgs=", ".join(trimmable)), "warn"
                )
                continue

            # Multilib va detrás de core/extra: un lib32-X pide 'libelf=0.196' y el repo ya
            # publica 0.197 (visto en un cliente: «installing libelf (0.197-1) breaks dependency
            # 'libelf=0.196' required by lib32-libelf»). Pasa en TODOS los mirrors y se arregla
            # solo cuando Arch reconstruye lib32-X, así que reintentar o cambiar de mirror no
            # sirve; seguir sin los paquetes de multilib implicados sí. Solo se omiten paquetes
            # EXPLÍCITOS de NUESTRA lista que estén en multilib: nunca el kernel, el firmware ni
            # nada de core/extra, que cae al diálogo de abajo. Con la base local del live (sin
            # pf_dbpath) el error puede venir de un paquete de la ISO y omitir no lo arregla.
            desync = (multilib_desync_culprits(pacman_conf_target, pf_dbpath, preflight_out, pkgs)
                      if pf_dbpath else [])
            if desync:
                for p in desync:
                    pkgs.remove(p)
                skipped_pkgs += desync
                desync_dropped += desync
                session.log(
                    session.t("log-multilib-desync-dropped", pkgs=", ".join(desync),
                               causa=dependency_conflict_packages(preflight_out)[0]), "warn"
                )
                continue

            # Ya no hay más que recortar y sigue fallando — esto no es
            # "un par de extras caídos", puede ser el mirror/red. Aquí
            # sí conviene que decida el usuario.
            detail = ", ".join(missing_pkgs) if missing_pkgs else preflight_error_summary(preflight_out)
            session.mirror_dialog(detail)
            while not session._mirror_choice_event.wait(timeout=1.0):
                if session._aborted:
                    session.clean_mounts()
                    return None
            session._mirror_choice_event.clear()
            choice = session._mirror_choice
            session._mirror_choice = None
            if session._aborted:
                session.clean_mounts()
                return None
            if choice == "aceptar":
                session.log(session.t("log-mirror-broadening"), "info")
                session.run_cmd(
                    ["reflector", "--latest", "15", "--sort", "rate", "--protocol", "https",
                     "--save", "/etc/pacman.d/mirrorlist"], timeout=120
                )
            elif choice != "reintentar":
                # "rechazar" (o cierre inesperado del diálogo): el
                # usuario prefiere resolverlo por su cuenta — cortamos
                # con el mismo error claro de siempre y lo dejamos usar
                # el botón "Reintentar" global cuando esté listo.
                session.error_fatal(session.t("err-multilib-unreachable", detalle=detail))
                session.clean_mounts()  # el root ya está montado: sin esto "Reintentar" choca con /mnt
                return None
            # "reintentar": vuelve a probar tal cual, con los mismos mirrors

    finally:
        if pf_dbpath:
            shutil.rmtree(pf_dbpath, ignore_errors=True)


def run_pacstrap(session: InstallSession, ctx: InstallContext,
                  cpu_arch: str, gpu_info: dict, ucode: str) -> str | None:
    """Devuelve el nombre del paquete de kernel instalado (ej.
    "linux-avalos") si todo salió bien — lo necesita system/locale.py más
    adelante para saber qué .preset de mkinitcpio conservar — o None si
    falló (con error ya reportado y clean_mounts() ya llamado)."""
    session.step("pacstrap", "active")
    session.status(session.t("status-installing-base"))
    session.label(session.t("label-installing-base"))
    session.log("\n── pacstrap ──\n", "step")

    # El /etc/pacman.conf del live trae 'IgnorePkg = linux-avalos ...'
    # (protección contra 'pacman -S linux-avalos' accidental DENTRO
    # del live — ver build-iso.yml). pacstrap reusa /etc/pacman.conf
    # por defecto si no se le pasa -C, así que sin esta copia limpia
    # ese IgnorePkg queda activo también al pacstrapear MOUNT_ROOT (un
    # root distinto, sin ese riesgo) y linux-avalos deja de contar
    # como proveedor válido de la dependencia virtual 'linux' —
    # pacman cae de vuelta al 'linux' genérico de [core] para
    # satisfacerla. Copia SOLO para el pacstrap del target; el
    # /etc/pacman.conf real del live no se toca.
    pacman_conf_target = "/tmp/avalos_pacman_target.conf"
    try:
        with open("/etc/pacman.conf") as f_conf:
            conf_lines = [l for l in f_conf if not l.lstrip().startswith("IgnorePkg")]
        # 'failed retrieving file' aislado (paquetes grandes tipo
        # noto-fonts-cjk, linux-firmware-*) suele ser UN intento que
        # se corta — no necesariamente el mirror entero está mal.
        # pacman por sí solo no reintenta la MISMA descarga, solo
        # pasa al siguiente mirror. XferCommand delega la descarga a
        # curl, que sí reintenta la misma URL antes de rendirse.
        # Costo: pacman deja de paralelizar descargas (ParallelDownloads
        # se ignora con XferCommand activo) — aceptable acá, porque el
        # retry de más abajo YA asume que menos paralelismo ayuda en
        # conexiones inestables.
        for i_opt, l_opt in enumerate(conf_lines):
            if l_opt.strip() == "[options]":
                conf_lines.insert(
                    i_opt + 1,
                    "XferCommand = /usr/bin/curl -L -C - -f --retry 3 --retry-delay 3 "
                    "--connect-timeout 10 -o %o %u\n"
                )
                break
        with open(pacman_conf_target, "w") as f_conf:
            f_conf.writelines(conf_lines)
    except Exception as e:
        session.log(session.t("log-pacman-conf-target-error", e=e), "warn")
        pacman_conf_target = "/etc/pacman.conf"

    pkgs = list(BASE_PKGS)

    if not ctx.usb_mode:
        pkgs += BTRFS_PKGS
    if ctx.bootloader == 'sd-boot':
        pkgs = [p for p in pkgs if p not in {"grub", "os-prober"}]
    elif ctx.bootloader == 'refind':
        pkgs = [p for p in pkgs if p not in {"grub", "os-prober"}]
    elif ctx.bootloader == 'none':
        pkgs = [p for p in pkgs if p not in {"grub", "efibootmgr", "os-prober"}]
    if ctx.bootloader != 'grub':
        # grub-btrfs (servicio y hook de initramfs) solo se usa con GRUB: services.py y
        # locale.py ya lo condicionan al bootloader. Sin GRUB no hace nada y se instalaba igual.
        pkgs = [p for p in pkgs if p != "grub-btrfs"]

    is_v3_or_higher = cpu_arch in ("x86-64-v3", "x86-64-v4")
    cpu_level_name = "v3/v4 (AVX2+)" if is_v3_or_higher else "baseline (sin AVX2)"
    session.log(session.t("log-cpu-detected", cpu_arch=cpu_arch, nivel=cpu_level_name), "info")

    wants_bore = ctx.install_bore
    if wants_bore and not is_v3_or_higher:
        session.log(
            session.t("log-bore-not-supported", cpu_arch=cpu_arch), "warn"
        )
        wants_bore = False

    session.log(session.t("log-checking-kernel-repo"), "info")

    if wants_bore:
        target_kernel = "linux-avalos-bore"
        target_headers = "linux-avalos-bore-headers"
    elif is_v3_or_higher:
        target_kernel = "linux-avalos"
        target_headers = "linux-avalos-headers"
    else:
        target_kernel = "linux-avalos-compat"
        target_headers = "linux-avalos-compat-headers"

    kernel_pkg = None
    headers_pkg = None

    try:
        if _pacman_package_available(session, target_kernel):
            kernel_pkg, headers_pkg = target_kernel, target_headers
            session.log(session.t("log-kernel-available", kernel_pkg=kernel_pkg), "ok")

        elif wants_bore and _pacman_package_available(session, "linux-avalos"):
            # BORE no publicado — mismo nivel de CPU sin BORE es seguro
            # (mismo -march, solo cambia el scheduler).
            kernel_pkg, headers_pkg = "linux-avalos", "linux-avalos-headers"
            session.log(
                session.t("log-kernel-fallback-no-bore", target=target_kernel,
                           alt=kernel_pkg, cpu_arch=cpu_arch),
                "warn"
            )
        # Si el objetivo es avalos o avalos-compat y no está disponible,
        # NO cambiamos de nivel de CPU — instalar v3 sin AVX2 (o al revés)
        # puede no arrancar. Mejor bloquear con error claro que arriesgar
        # un sistema que no bootea o meter un kernel que no sea AvalOS.

    except Exception as e:
        session.log(session.t("log-kernel-repo-query-error", e=e), "warn")

    if not kernel_pkg:
        session.error_fatal(session.t("err-avalos-repo-unreachable", target=target_kernel))
        session.clean_mounts()  # el root ya está montado (mount_filesystems corre antes)
        return None

    pkgs += [kernel_pkg, headers_pkg]
    pkgs += gpu_info["pkgs"] + HYPRLAND_PKGS + ([ucode] if ucode else [])

    if ctx.install_gaming:
        pkgs += GAMING_PKGS
        session.log(session.t("log-gaming-enabled"), "ok")
    else:
        session.log(session.t("log-gaming-skipped"), "info")
    session.log(session.t("log-gpu-detected", gpu_vendor=gpu_info["vendor"].upper(),
                           drivers=", ".join(gpu_info["pkgs"][:3])), "info")
    session.log(session.t("log-total-packages", total=len(pkgs),
                           preview=", ".join(pkgs[:8]), extra=max(0, len(pkgs) - 8)), "info")

    session.log(session.t("log-checking-multilib"), "info")
    resolved = _preflight_packages(session, pkgs, pacman_conf_target)
    if resolved is None:
        return None
    preflight_out, skipped_pkgs = resolved

    if skipped_pkgs:
        session.log(
            session.t("log-multilib-pkgs-omitidos", pkgs=", ".join(sorted(set(skipped_pkgs)))),
            "warn"
        )

    # Guardia: 'linux'/'linux-headers' genéricos NUNCA deben aparecer
    # resueltos para pacstrap — si aparecen es que algo (una
    # dependencia sin 'provides' correcto en el PKGBUILD del kernel
    # avalos objetivo, un IgnorePkg mal alcanzando este pacman.conf,
    # etc) hizo que pacman los use para satisfacer 'linux' en vez de
    # kernel_pkg. Cortar acá evita gastar minutos bajando un kernel
    # de ~150MB que no queremos y que además suele fallar por mirror.
    intruder_kernels = sorted(set(re.findall(
        r"/(linux(?:-headers)?-\d[^/\s]*)-(?:x86_64|any)\.pkg\.tar", preflight_out
    )))
    if intruder_kernels:
        session.log(
            session.t("log-generic-kernel-detected", pkgs=", ".join(intruder_kernels),
                       target=kernel_pkg), "err"
        )
        session.error_fatal(session.t("err-generic-kernel-in-transaction",
                                       pkgs=", ".join(intruder_kernels)))
        session.clean_mounts()
        return None

    pacstrap_ok = False
    pacstrap_out = ""
    for parallel_downloads in (None, 2, 1):
        if session._aborted:
            session.clean_mounts()
            return None
        if parallel_downloads is not None:
            # Solo llegamos acá si el intento anterior falló con
            # "failed retrieving file" para TODOS/casi todos los
            # paquetes — eso, con el preflight de resolución ya
            # habiendo pasado antes, es la firma típica de una
            # conexión que no aguanta N descargas grandes en
            # paralelo (ParallelDownloads=5 por defecto). Bajar el
            # paralelismo no arregla un mirror caído, pero sí
            # arregla esto — que es lo que se vio en pruebas reales
            # (los .db, chicos, entraban bien; firefox/wine/firmware,
            # grandes, fallaban todos).
            session.run_cmd(
                ["sed", "-i", f"s/^ParallelDownloads.*/ParallelDownloads = {parallel_downloads}/",
                 pacman_conf_target], timeout=10
            )
            session.log(session.t("log-pacstrap-retry-slower", n=parallel_downloads), "warn")
        rc, pacstrap_out = session.run_cmd(
            ["pacstrap", "-C", pacman_conf_target, str(MOUNT_ROOT)] + pkgs,
            timeout=3600, log_cls="info"
        )
        if rc == 0:
            pacstrap_ok = True
            break
        if "failed retrieving file" not in pacstrap_out:
            # Otro tipo de fallo (disco lleno, permisos, etc) —
            # bajar el paralelismo no va a arreglar nada, no vale
            # la pena seguir reintentando.
            break

    if not pacstrap_ok:
        session.step("pacstrap", "error")
        session.error_step(session.t("err-pacstrap-failed"))
        session.clean_mounts()
        return None

    session.step("pacstrap", "done")
    return kernel_pkg
'''),
    # ── avalos_installer/system/partition.py (427 líneas)
    'avalos_installer.system.partition': (False, 'avalos_installer/system/partition.py', r'''"""
system/partition.py — particionado y formateo del disco destino, modo
manual y modo automático. Corresponde a los pasos "part" y "format" de
_run_instalacion en skill_instalar_usb.py (líneas ~3471-3763), que se
mantienen juntos acá porque en el original ya comparten variables y fluyen
uno al otro sin punto de corte limpio — separarlos hubiera sido un cambio
de estructura, no una extracción fiel.

Incluye el countdown de 10s antes de tocar el disco (solo modo automático),
el chequeo de /proc/mounts para detectar particiones ya montadas del disco
destino, la lógica de reintento de wipefs (condición de carrera documentada
de udev), y la creación de subvolúmenes Btrfs — todos con sus comentarios
originales intactos.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`; todos
los identificadores → inglés. `dev`, `dev_name` y `disk_info` (el dict que
antes era `disco`, viene de disk.discovery.list_disks()) y `uefi` se
reciben como parámetros — se calculan ANTES de este paso en el orquestador,
no acá.

Endurecimientos posteriores a la extracción (estos sí son de lógica): el chequeo de uso del
disco (_in_use) compara nombres de partición con la regla del kernel y mira también
/proc/swaps y los montajes en árbol de list_disks(); los nombres de partición salen de esa
misma regla (_part_sep); en modo manual root/EFI tienen que ser particiones del disco destino;
y en modo automático el log solo declara los subvolúmenes que de verdad se crearon.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession
from avalos_installer.core.shell import run_command


@dataclass
class PartitionResult:
    root_device: str
    efi_device: str  # "" si no hay partición EFI (BIOS/MBR)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _part_sep(disk_name: str) -> str:
    """Separador entre el disco y el número de partición según la regla del kernel: si el
    nombre del disco termina en dígito (nvme0n1, mmcblk0, loop0, md0…) lleva una 'p'
    (nvme0n1p1); si no (sda), va pegado (sda1)."""
    return "p" if disk_name[-1:].isdigit() else ""


def _is_part_of(name: str, disk_name: str) -> bool:
    """¿`name` (sin /dev/) es una partición de `disk_name`? Coincidencia exacta con la regla
    anterior: un startswith() a secas daba falso positivo entre nvme0n1 y nvme0n10p1."""
    prefix = disk_name + _part_sep(disk_name)
    return name.startswith(prefix) and name[len(prefix):].isdigit()


def _in_use(dev_name: str, disk_info: dict) -> list[str]:
    """Puntos de montaje (o [SWAP]) que están usando el disco destino o sus particiones.
    Junta tres fuentes: /proc/mounts y /proc/swaps (el estado de AHORA) y los 'montajes' que
    list_disks() recorrió en árbol — esos cubren LUKS/LVM/md/Ventoy apilados sobre el disco,
    que en /proc/mounts aparecen como /dev/mapper/… y el nombre del disco no los delata.
    Un montaje del disco entero (sin tabla de particiones) también cuenta."""
    def es_del_disco(fuente: str) -> bool:
        nombre = fuente.removeprefix("/dev/")
        return nombre == dev_name or _is_part_of(nombre, dev_name)

    usados: list[str] = []
    for line in _read_text("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 2 and es_del_disco(parts[0]):
            usados.append(parts[1])
    try:
        swaps = _read_text("/proc/swaps").splitlines()[1:]  # la primera línea es el encabezado
    except OSError:  # kernel sin swap
        swaps = []
    for line in swaps:
        parts = line.split()
        if parts and es_del_disco(parts[0]):
            usados.append("[SWAP]")
    usados.extend(disk_info.get("montajes") or [])
    return list(dict.fromkeys(usados))


def _mark_format(session, dev: str) -> None:
    """Rollback (system/rollback.py): justo antes de cada mkfs los datos del disco dejan de
    existir; desde ahí ya no se restaura la tabla original."""
    journal = getattr(session, "journal", None)
    if journal:
        journal.mark_format(dev)


def partition_and_format(session: InstallSession, ctx: InstallContext,
                          dev: str, dev_name: str, disk_info: dict,
                          uefi: bool) -> PartitionResult | None:
    """Devuelve PartitionResult si todo salió bien, None si falló o se
    abortó (en ambos casos ya se llamó session.clean_mounts() y se
    reportó el error a la UI antes de retornar — el llamador solo
    necesita chequear el retorno y detenerse)."""

    if not ctx.manual_mode:
        session.countdown_start(dev, disk_info["model"] or session.t("disk-unknown"), disk_info["size_human"])
        for i in range(10, 0, -1):
            if session._aborted:
                session.countdown_cancel()
                session.clean_mounts()
                return None
            session.countdown_tick(i - 1)
            time.sleep(1)
        session.countdown_cancel()

    if session._aborted:
        session.clean_mounts()
        return None

    # El chequeo de uso aplica en ambos modos: en modo manual protege
    # contra que el dropdown del wizard haya apuntado al disco equivocado,
    # exactamente igual que en modo automático protege contra un disco mal
    # seleccionado. Mira /proc/mounts, /proc/swaps y los montajes en árbol
    # de list_disks() (ver _in_use).
    session.log(session.t("log-checking-mounted-partitions"), "info")
    mounted = _in_use(dev_name, disk_info)
    if mounted:
        session.error_fatal(session.t("err-disk-has-mounted-partitions", dev=dev, puntos=", ".join(mounted)))
        return None
    session.log(session.t("log-disk-not-mounted", dev=dev), "ok")

    if ctx.manual_mode:
        # ── MODO MANUAL ──────────────────────────────────────────────
        # El usuario ya particionó (y puede que ya haya formateado) el
        # disco a mano en una terminal real. efi_device/root_device
        # vienen de verificar_particionado_manual()/confirmar_root_manual()
        # (InstaladorAPI), que ya los validó contra
        # disk.discovery.detect_manual_partitions() — no se vuelve a
        # tocar el esquema de particiones acá.
        efi_device = ctx.manual_efi_partition
        root_device = ctx.manual_root_partition

        if not root_device:
            session.step("part", "error")
            session.error_step(session.t("err-manual-no-root-selected"))
            session.clean_mounts()
            return None

        # Defensa en profundidad: root y EFI tienen que ser particiones de ESTE
        # disco. El estado manual de la API se fijó con el disco que había
        # seleccionado al verificar el particionado, y selectDisk() del wizard
        # no lo reinicia: si el usuario cambia de disco después, llegarían
        # particiones de un disco con el `dev` de otro (se formatearía una y
        # el bootloader iría a la otra).
        ajenas = [p for p in (root_device, efi_device)
                  if p and not _is_part_of(p.removeprefix("/dev/"), dev_name)]
        if ajenas:
            session.step("part", "error")
            session.error_step(session.t("err-manual-partition-other-disk", dev=dev))
            session.clean_mounts()
            return None

        if uefi and not efi_device:
            session.step("part", "error")
            session.error_step(session.t("err-manual-no-efi-found"))
            session.clean_mounts()
            return None

        if uefi and efi_device:
            # Mismo criterio que para root: blkid vacío/rc!=0 = sin
            # filesystem reconocible = el usuario dejó la partición EFI
            # creada pero sin formatear a propósito. Se formatea con el
            # mismo comando que usa el modo automático (mkfs.fat -F32) —
            # si ya tiene FAT32 u otro filesystem, se respeta tal cual,
            # igual que root.
            rc_efi, fstype_efi, _ = run_command(["blkid", "-s", "TYPE", "-o", "value", efi_device])
            fstype_efi = fstype_efi.strip() if rc_efi == 0 else ""
            if not fstype_efi:
                _mark_format(session, dev)
                rc_efi_fmt, _ = session.run_cmd(["mkfs.fat", "-F32", efi_device])
                if rc_efi_fmt != 0:
                    session.step("part", "error")
                    session.error_step(session.t("err-mkfs-fat-failed", dev_efi=efi_device))
                    session.clean_mounts()
                    return None
                session.log(session.t("log-manual-efi-formatted", dev_efi=efi_device), "ok")
            else:
                session.log(session.t("log-manual-fs-detected", dev_root=efi_device, fstype=fstype_efi), "ok")

        session.step("part", "done", session.t("step-manual-partitions-detected"))

        if session._aborted:
            session.clean_mounts()
            return None

        session.step("format", "active")
        session.status(session.t("status-formatting"))
        session.log(session.t("log-section-formatting"), "step")

        # ¿La root ya está formateada? blkid con salida vacía/rc!=0
        # significa "sin filesystem reconocible" — en ese caso el usuario
        # dejó la partición sin formatear a propósito (creó el esquema
        # pero delega el mkfs al instalador) y sí se formatea acá, igual
        # que en modo automático.
        rc_fs, fstype_actual, _ = run_command(["blkid", "-s", "TYPE", "-o", "value", root_device])
        fstype_actual = fstype_actual.strip() if rc_fs == 0 else ""

        if not fstype_actual:
            _mark_format(session, dev)
            if ctx.usb_mode:
                rc, _ = session.run_cmd(["mkfs.ext4", "-O", "^has_journal", "-F", root_device])
            else:
                rc, _ = session.run_cmd(["mkfs.btrfs", "-f", "-L", "AvalOS", root_device])
            if rc != 0:
                session.step("format", "error")
                session.error_step(session.t("err-mkfs-failed", dev_root=root_device))
                session.clean_mounts()
                return None
            fstype_actual = "ext4" if ctx.usb_mode else "btrfs"
        else:
            session.log(session.t("log-manual-fs-detected", dev_root=root_device, fstype=fstype_actual), "ok")

        if fstype_actual == "btrfs" and not ctx.usb_mode:
            btrfs_tmp = "/tmp/btrfs_setup"
            rc_mnt, _ = session.run_cmd(["mount", root_device, btrfs_tmp, "-o", "compress=zstd"],
                                         pre_mkdir=btrfs_tmp)
            if rc_mnt != 0:
                session.step("format", "error")
                session.error_step(session.t("err-btrfs-mount-failed"))
                session.clean_mounts()
                return None

            # Según lo acordado: crear solo los subvolúmenes que falten,
            # sin pisar los que el usuario ya armó a mano.
            existing = set(ctx.manual_existing_subvolumes)
            subvols = ["@", "@home", "@snapshots", "@log", "@cache", "@tmp"]
            created = []
            for sv in subvols:
                if sv in existing:
                    session.log(session.t("log-subvol-already-exists", sv=sv), "info")
                    continue
                rc_sv, _ = session.run_cmd(["btrfs", "subvolume", "create", f"{btrfs_tmp}/{sv}"])
                if rc_sv != 0:
                    session.log(session.t("log-subvol-create-fail", sv=sv), "warn")
                else:
                    created.append(sv)

            rc_um, out_um = session.run_cmd(["umount", btrfs_tmp])
            if rc_um != 0:
                # No es fatal (los subvolúmenes ya están creados en disco,
                # que es lo que importa) pero si /tmp/btrfs_setup queda
                # montado, ese mismo dispositivo sigue "ocupado" más
                # adelante — mejor un warning visible acá que un "target
                # is busy" sin explicación al desmontar todo al final de
                # la instalación.
                session.log(
                    session.t("log-btrfs-tmp-umount-fail", out=out_um.strip()[-200:]),
                    "warn",
                )
            if created:
                session.log(session.t("log-subvols-created", subvols=", ".join(created)), "ok")

        fmt_label = session.t("step-fmt-manual-detected", fstype=fstype_actual.upper())
        session.step("format", "done", fmt_label)

        try:
            subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
        except Exception:
            time.sleep(1)

    else:
        # ── MODO AUTOMÁTICO ──────────────────────────────────────────
        # FIX (particionado): 'wipefs' puede fallar con "probing
        # initialization failed: Device or resource busy" aunque el disco
        # no esté montado (confirmado en /proc/mounts arriba). Es una
        # condición de carrera conocida y documentada en udisks2/udev: el
        # kernel abre brevemente el device node para (re)enumerar
        # metadata justo después de que un disco nuevo aparece o cambia,
        # y wipefs no puede abrirlo con O_EXCL mientras tanto. Es
        # transitorio — 'udevadm settle' + reintentos con backoff es la
        # mitigación estándar (mismo patrón que usa ceph-volume en
        # producción, ver comentario "workaround probable race condition"
        # en su código). No hay garantía de timing exacta
        # (systemd-udev-settle.service(8) es explícito: "There can be no
        # guarantee that hardware is fully discovered at any specific
        # time"), por eso reintentamos en vez de esperar una sola vez.
        try:
            subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
        except Exception:
            pass

        # Rollback: copia de la tabla original ANTES del primer comando destructivo.
        _journal = getattr(session, "journal", None)
        if _journal:
            _journal.snapshot_table(dev)

        rc_wipe = 1
        for attempt in range(1, 4):
            wipe_cmd = ["wipefs", "-a", dev]
            if attempt == 3:
                # Último intento: --force evita el chequeo O_EXCL de
                # wipefs (confirmado en 'wipefs --help' del propio
                # binario). Solo se usa acá, no antes — los intentos 1-2
                # son "limpios" (settle + retry) para no enmascarar un
                # problema real si /proc/mounts tuviera un falso negativo
                # por alguna razón.
                wipe_cmd = ["wipefs", "-a", "-f", dev]
            rc_wipe, _ = session.run_cmd(wipe_cmd)
            if rc_wipe == 0:
                break
            if attempt < 3:
                session.log(session.t("log-wipefs-retry", intento=attempt, dev=dev), "warn")
                try:
                    subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
                except Exception:
                    pass
                time.sleep(2 * attempt)
        if rc_wipe != 0:
            session.step("part", "error")
            session.error_step(session.t("err-wipefs-failed", dev=dev))
            session.clean_mounts()
            return None

        if uefi:
            rc, _ = session.run_cmd([
                "parted", "-s", dev,
                "mklabel", "gpt",
                "mkpart", "ESP", "fat32", "1MiB", "513MiB",
                "set", "1", "esp", "on",
                "mkpart", "root", "ext4", "513MiB", "100%",
            ])
            efi_device = f"{dev}{_part_sep(dev_name)}1"
            root_device = f"{dev}{_part_sep(dev_name)}2"
        else:
            rc, _ = session.run_cmd([
                "parted", "-s", dev,
                "mklabel", "msdos",
                "mkpart", "primary", "ext4", "1MiB", "100%",
                "set", "1", "boot", "on",
            ])
            root_device = f"{dev}{_part_sep(dev_name)}1"
            efi_device = ""

        if rc != 0:
            session.step("part", "error")
            session.error_step(session.t("err-parted-failed", dev=dev))
            session.clean_mounts()
            return None

        try:
            subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
        except Exception:
            time.sleep(2)
        session.step("part", "done", "GPT: EFI (512MB) + root" if uefi else "MBR: root (100%)")

        if session._aborted:
            session.clean_mounts()
            return None

        session.step("format", "active")
        session.status(session.t("status-formatting"))
        session.log(session.t("log-section-formatting"), "step")

        _mark_format(session, dev)
        if uefi:
            rc, _ = session.run_cmd(["mkfs.fat", "-F32", efi_device])
            if rc != 0:
                session.step("format", "error")
                session.error_step(session.t("err-mkfs-fat-failed", dev_efi=efi_device))
                session.clean_mounts()
                return None

        if ctx.usb_mode:
            rc, _ = session.run_cmd(["mkfs.ext4", "-O", "^has_journal", "-F", root_device])
        else:
            rc, _ = session.run_cmd(["mkfs.btrfs", "-f", "-L", "AvalOS", root_device])

        if rc != 0:
            session.step("format", "error")
            session.error_step(session.t("err-mkfs-failed", dev_root=root_device))
            session.clean_mounts()
            return None

        if not ctx.usb_mode:
            btrfs_tmp = "/tmp/btrfs_setup"
            rc_mnt, _ = session.run_cmd(["mount", root_device, btrfs_tmp, "-o", "compress=zstd"],
                                         pre_mkdir=btrfs_tmp)
            if rc_mnt != 0:
                session.step("format", "error")
                session.error_step(session.t("err-btrfs-mount-failed"))
                session.clean_mounts()
                return None

            subvols = ["@", "@home", "@snapshots", "@log", "@cache", "@tmp"]
            created = []
            for sv in subvols:
                rc_sv, _ = session.run_cmd(["btrfs", "subvolume", "create", f"{btrfs_tmp}/{sv}"])
                if rc_sv != 0:
                    session.log(session.t("log-subvol-create-fail", sv=sv), "warn")
                else:
                    created.append(sv)

            rc_um, out_um = session.run_cmd(["umount", btrfs_tmp])
            if rc_um != 0:
                session.log(
                    session.t("log-btrfs-tmp-umount-fail", out=out_um.strip()[-200:]),
                    "warn",
                )
            if created:
                session.log(session.t("log-subvols-created", subvols=", ".join(created)), "ok")

        if uefi and ctx.usb_mode:
            fmt_label = "FAT32 + " + session.t("step-fmt-ext4-nojournal")
        elif uefi:
            fmt_label = "FAT32 + Btrfs (@, @home, @snapshots, @log, @cache, @tmp)"
        else:
            fmt_label = session.t("step-fmt-ext4-nojournal") if ctx.usb_mode else "Btrfs (@, @home, @snapshots, @log, @cache, @tmp)"
        session.step("format", "done", fmt_label)

        try:
            subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
        except Exception:
            time.sleep(1)

    return PartitionResult(root_device=root_device, efi_device=efi_device)
'''),
    # ── avalos_installer/system/repos.py (166 líneas)
    'avalos_installer.system.repos': (False, 'avalos_installer/system/repos.py', r'''"""
system/repos.py — repos [avalos] + [multilib] en el pacman.conf del
chroot, más la importación de la llave GPG de AvalOS al keyring del
target.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas ~4801-4856). Esta sección NO tiene paso propio en PASOS_IDS —
en el original corre en silencio entre "user" y "aur", solo con
llamadas a self._log(...), sin un solo self._step(...). El orquestador
NO debe envolver configure_repos() en su propio session.step()/
progress() — se llama tal cual, entre create_user() y el paso "aur".

Por qué va ANTES de yay/AUR (comentario del original, preservado en
espíritu): yay resuelve dependencias lib32-* contra [multilib], y
pacstrap no copia pacman.conf al target (no se le pasa -P) — sin este
paso, el chroot todavía tendría el pacman.conf de fábrica del paquete
'pacman', sin multilib, y 'yay -S proton-ge-custom-bin' fallaría al
resolver dependencias.

Ningún fallo acá es fatal: ni un solo `return` en todo el bloque
original, solo warnings logueados y la instalación sigue.
"""
from __future__ import annotations

import re

from avalos_installer.core.config import AVALOS_REPO_URL, MOUNT_ROOT
from avalos_installer.core.session import InstallSession

# Fingerprint de la llave GPG de AvalOS. Ya está en el keyring del live
# ISO de fábrica (ver build-iso.yml) — acá solo se exporta desde ahí y
# se reimporta en el keyring nuevo del chroot del target.
AVALOS_GPG_FINGERPRINT = "60FD7887C1DA5B080281B9B8F548844B24E0379D"


def configure_repos(session: InstallSession) -> None:
    """Agrega [avalos] y [multilib] a /etc/pacman.conf del chroot si no
    están ya presentes, e importa la llave GPG de AvalOS al keyring del
    target. No devuelve nada: no hay condición de fallo que deba
    detener la instalación, igual que en el original."""
    session.log(session.t("log-section-repo-setup"), "step")

    avalos_repo_txt = (
        "\n[avalos]\n"
        "SigLevel = Required DatabaseOptional\n"
        f"Server = {AVALOS_REPO_URL}\n"
    )
    multilib_repo_txt = "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n"

    pac_path = MOUNT_ROOT / "etc" / "pacman.conf"
    try:
        existing = pac_path.read_text(encoding="utf-8") if pac_path.exists() else ""
        to_append = ""
        base_changed = False

        # FIX: en al menos una instalación real, el pacman.conf que quedó
        # en el target no tenía ni [options] ni [core]/[extra] — nada más
        # que lo que esta misma función agrega. El comentario de arriba
        # asume que siempre llega el pacman.conf de fábrica completo (vía
        # el paquete 'pacman'); en la práctica no se puede dar por hecho.
        # Sin 'Architecture' definida, pacman revienta hasta en 'pacman -Q'
        # local, contra cualquier mirror con $arch en la URL, real o no.
        # Causa de fondo (por qué pacstrap dejó esto incompleto) todavía
        # sin confirmar — esto reconstruye una base mínima válida si hace
        # falta, en vez de asumir que ya está.
        if "[options]" not in existing:
            existing = (
                "[options]\n"
                "Architecture = auto\n"
                "SigLevel = Required DatabaseOptional\n"
                "LocalFileSigLevel = Optional\n"
                "\n"
                "[core]\n"
                "Include = /etc/pacman.d/mirrorlist\n"
                "\n"
                "[extra]\n"
                "Include = /etc/pacman.d/mirrorlist\n"
                "\n"
            ) + existing
            base_changed = True
        elif not re.search(r'^#?\s*Architecture\s*=', existing, flags=re.MULTILINE):
            # REVISIÓN EXTRA: el elif de abajo solo cubre "Architecture
            # está pero comentada". Si [options] existe pero la línea
            # Architecture no aparece en NINGUNA forma (ni comentada),
            # ese caso quedaba sin cubrir — se insertaba nada y el bug
            # seguía. Se inserta la línea recién creada, justo después
            # del header [options].
            existing = re.sub(
                r'(\[options\]\s*\n)',
                r'\1Architecture = auto\n',
                existing,
                count=1,
            )
            base_changed = True
        elif re.search(r'^#\s*Architecture\s*=\s*auto\s*$', existing, flags=re.MULTILINE):
            existing = re.sub(
                r'^#\s*Architecture\s*=\s*auto\s*$',
                "Architecture = auto",
                existing,
                count=1,
                flags=re.MULTILINE,
            )
            base_changed = True

        needs_avalos = "[avalos]" not in existing
        if needs_avalos:
            to_append += avalos_repo_txt

        if "[multilib]" not in existing:
            existing_new = re.sub(
                r'#\s*\[multilib\]\s*\n#\s*Include\s*=\s*/etc/pacman\.d/mirrorlist',
                "[multilib]\nInclude = /etc/pacman.d/mirrorlist",
                existing,
            )
            if "[multilib]" not in existing_new:
                to_append += multilib_repo_txt
            else:
                existing = existing_new

        # FIX: pacman-key necesita que /etc/pacman.conf YA EXISTA en disco
        # para correr — si se escribe recién al final de la función (como
        # hacía el original), pacman-key --init/--add/--lsign-key revientan
        # los TRES con "pacman configuration file '/etc/pacman.conf' not
        # found" en TODAS las corridas, porque el archivo nunca llegó a
        # existir antes de esas tres llamadas. Se escribe ACÁ, antes de
        # tocar pacman-key para nada.
        if to_append or base_changed:
            pac_path.write_text(existing + to_append, encoding="utf-8")

        if needs_avalos:
            # FIX: el archivo temporal en MOUNT_ROOT/tmp, leído después
            # como /tmp/avalos.gpg DESDE DENTRO del chroot, asumía que
            # ambas rutas son el mismo archivo real. En al menos una
            # instalación real no lo fueron: pacman-key --add reportó
            # "can't open '/tmp/avalos.gpg': No such file or directory"
            # a pesar de que el archivo sí existía y se había verificado
            # del lado host (rc==0 y tamaño > 0) un instante antes.
            # Causa exacta sin confirmar — se elimina el archivo
            # intermedio del todo en vez de seguir dependiendo de esa
            # ruta compartida: un solo pipe que exporta del lado host
            # y lo mete por stdin directo al pacman-key del CHROOT
            # (arch-chroot reenvía stdin al proceso que ejecuta), sin
            # ningún archivo de por medio.
            rc1, out1 = session.run_chroot(["pacman-key", "--init"])
            rc2, out2 = session.run_cmd([
                "bash", "-c",
                # --no-permission-warning: este gpg corre en el LIVE y el keyring de la
                # ISO trae /etc/pacman.d/gnupg con permisos que gpg considera "unsafe"
                # ("gpg: WARNING: unsafe permissions on homedir"). Es solo un aviso —solo
                # lee y exporta una clave pública—, pero ensuciaba el log de instalación.
                f"set -o pipefail; gpg --no-permission-warning --homedir /etc/pacman.d/gnupg --armor "
                f"--export {AVALOS_GPG_FINGERPRINT} "
                f"| arch-chroot {MOUNT_ROOT} pacman-key --add -",
            ])
            rc3, out3 = session.run_chroot(["pacman-key", "--lsign-key", AVALOS_GPG_FINGERPRINT])
            if rc1 == 0 and rc2 == 0 and rc3 == 0:
                session.log(f"  clave GPG AvalOS ({AVALOS_GPG_FINGERPRINT}) importada al keyring", "ok")
            else:
                session.log(
                    f"  [WARN] pacman-key falló (init={rc1}, add={rc2}, lsign={rc3}) — "
                    f"el repo [avalos] puede fallar por firma no confiable", "warn"
                )

        session.log("  repos [avalos] + [multilib] → pacman.conf", "ok")
    except OSError as e:
        session.log(f"[WARN] pacman.conf: {e}", "warn")
'''),
    # ── avalos_installer/system/rollback.py (626 líneas)
    'avalos_installer.system.rollback': (False, 'avalos_installer/system/rollback.py', r'''"""
system/rollback.py — deshacer lo que una instalación fallida o cancelada dejó FUERA de lo
que el instalador formatea.

Lo que promete (ni más ni menos):

  · Entradas de arranque UEFI (NVRAM): se borran las que creó el bootloader de esta
    instalación y se restaura el orden de arranque original. Solo se borra una entrada
    que (a) no existía al empezar (o cambió) y (b) lleva una etiqueta de nuestros
    bootloaders. Nunca una que ya estaba.
  · Archivos de la ESP: si la ESP ya existía (instalación manual junto a otro sistema), se
    quita lo que esta instalación agregó y se devuelven los archivos de arranque que pisó
    (EFI/BOOT, EFI/AvalOS, EFI/GRUB, EFI/refind, EFI/systemd y loader).
  · Código de arranque del MBR (BIOS, modo manual): se devuelven sus 446 bytes.
  · Tabla de particiones (modo automático): se guarda byte a byte el primer y el último MiB
    del disco (ahí viven la tabla GPT/MBR y su copia, el código de arranque del MBR y las
    firmas de RAID/LVM/LUKS/ZFS que `wipefs -a` borra a nivel de disco). Si el fallo ocurre
    DESPUÉS de reemplazar la tabla y ANTES del primer mkfs, se devuelven esos bytes y se
    verifica leyendo de nuevo. Pasado ese punto los datos anteriores ya no existen: no se toca
    nada y se avisa. (parted mkpart no crea sistemas de archivos y wipefs solo borra firmas:
    antes del primer mkfs el contenido de las particiones sigue intacto.)

Lo que NO hace: recuperar datos ya formateados, recrear una entrada UEFI preexistente que el
bootloader reemplazó (lo avisa), ni tocar el arranque de un sistema que ya quedó arrancable
(fase «usable»: usuario creado), porque ahí un fallo tardío no justifica quitarle el arranque.

Todo es defensivo: cualquier error se registra y se sigue; el rollback nunca lanza ni tapa el
error original de la instalación. Interruptor de emergencia: AVALOS_NO_ROLLBACK=1.

Cómo se usa (core/install.py y system/partition.py):

    journal = InstallJournal(session);  session.journal = journal
    journal.snapshot_firmware(uefi)          # al saber que es UEFI, antes de tocar nada
    journal.snapshot_table(dev)              # modo automático: justo antes de wipefs
    journal.mark_format(dev)                 # justo antes de cada mkfs (punto sin retorno)
    journal.snapshot_esp(efi_device)         # antes de instalar el bootloader
    journal.mark("boot")                     #   (y snapshot_mbr(dev) si es BIOS manual)
    journal.mark("usable")                   # el usuario ya existe: el sistema arranca
    journal.rollback(completed)              # en el finally de run_installation

El diario recuerda entre «Reintentar» (session.rollback_memory): la tabla original, el estado
original del firmware y qué discos ya se formatearon, para que un segundo intento no tome por
«original» lo que dejó el primero.
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from avalos_installer.core.config import MOUNT_EFI
from avalos_installer.core.shell import run_command

ROLLBACK_DIR = Path("/tmp/avalos-rollback")       # copias de seguridad (RAM del live)
ESP_PROBE_DIR = Path("/tmp/avalos-rollback-esp")  # montaje propio de la ESP; FUERA de ROLLBACK_DIR a propósito
KILL_SWITCH_ENV = "AVALOS_NO_ROLLBACK"

# Fases, siempre hacia adelante. table = ya se puede haber reemplazado la tabla; format = se
# empezó a formatear (sin retorno para los datos); boot = el bootloader puede haber tocado
# NVRAM/ESP/MBR; usable = usuario creado, el sistema arranca.
PHASES = ("init", "table", "format", "boot", "usable")

# Directorios de la ESP que un bootloader puede pisar: de sus archivos previos se guarda copia.
ESP_TRACKED = ("efi/boot", "efi/avalos", "efi/grub", "efi/refind", "efi/systemd", "loader")
ESP_BACKUP_FILE_MAX = 32 * 1024 * 1024
ESP_BACKUP_TOTAL_MAX = 96 * 1024 * 1024
MBR_BOOT_CODE_SIZE = 446
EDGE_BYTES = 1024 * 1024   # primer y último MiB del disco (tabla de particiones, copia GPT, firmas)

# Etiquetas de las entradas UEFI que crean los bootloaders de AvalOS: solo esas se borran.
OUR_BOOT_LABELS = ("grub", "refind", "linux boot manager", "avalos")


# ── Firmware (efibootmgr) ─────────────────────────────────────────────────
_RE_ORDER = re.compile(r"^BootOrder:\s*([0-9A-Fa-f]{4}(?:,[0-9A-Fa-f]{4})*)\s*$", re.M)
_RE_CURRENT = re.compile(r"^BootCurrent:\s*([0-9A-Fa-f]{4})\s*$", re.M)
_RE_ENTRY = re.compile(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.*?)\s*$", re.M)


_RE_DEVICE_PATH = re.compile(r"\s+[A-Za-z]+\(")   # primer nodo de la ruta de dispositivo: HD(, PciRoot(, USB(...


def split_label(text: str) -> str:
    """Etiqueta de una entrada UEFI. Con -v, efibootmgr la separa de la ruta con un tab; si no
    hubiera tab se corta en el primer nodo de ruta (HD(…), PciRoot(…)), para que algo como
    «\\EFI\\ubuntu\\grubx64.efi» de la ruta nunca cuente como parte de la etiqueta."""
    if "\t" in text:
        return text.split("\t", 1)[0].strip()
    m = _RE_DEVICE_PATH.search(text)
    return (text[:m.start()] if m else text).strip()


@dataclass
class FirmwareState:
    order: list = field(default_factory=list)      # ["0001", "0000"]
    entries: dict = field(default_factory=dict)    # id -> texto completo (etiqueta + ruta con -v)
    current: str | None = None

    def label(self, bid: str) -> str:
        return split_label(self.entries.get(bid, ""))


def parse_efibootmgr(text: str) -> FirmwareState | None:
    """Salida de `efibootmgr` (con o sin -v). None si no se reconoce nada."""
    entries = {m.group(1).upper(): m.group(2) for m in _RE_ENTRY.finditer(text or "")}
    order_m = _RE_ORDER.search(text or "")
    order = [x.upper() for x in order_m.group(1).split(",")] if order_m else []
    cur_m = _RE_CURRENT.search(text or "")
    if not entries and not order and not cur_m and not re.search(r"^(?:Timeout|BootNext):", text or "", re.M):
        return None                               # ni una línea que parezca de efibootmgr
    return FirmwareState(order=order, entries=entries, current=cur_m.group(1).upper() if cur_m else None)


def is_ours(label: str) -> bool:
    low = label.lower()
    return any(k in low for k in OUR_BOOT_LABELS)


# ── Árbol de archivos de la ESP ───────────────────────────────────────────
@dataclass
class EspSnapshot:
    device: str
    files: dict           # ruta relativa -> (tamaño, mtime_ns)
    dirs: set
    backups: dict         # ruta relativa -> Path de la copia
    skipped: list         # archivos rastreados que no se pudieron copiar (tamaño)


@dataclass
class TreeResult:
    removed: list = field(default_factory=list)
    restored: list = field(default_factory=list)
    unrestorable: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def scan_tree(root: Path) -> tuple[dict, set]:
    files: dict = {}
    dirs: set = set()
    for dirpath, _dirnames, filenames in os.walk(root):   # os.walk no sigue symlinks
        d = Path(dirpath)
        rel_d = d.relative_to(root).as_posix()
        if rel_d != ".":
            dirs.add(rel_d)
        for name in filenames:
            p = d / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                files[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return files, dirs


def _is_tracked(rel: str) -> bool:
    low = rel.lower()
    return any(low == t or low.startswith(t + "/") for t in ESP_TRACKED)


def backup_tracked(root: Path, files: dict, dest: Path) -> tuple[dict, list]:
    saved: dict = {}
    skipped: list = []
    total = 0
    for rel, (size, _mtime) in sorted(files.items()):
        if not _is_tracked(rel):
            continue
        if size > ESP_BACKUP_FILE_MAX or total + size > ESP_BACKUP_TOTAL_MAX:
            skipped.append(rel)
            continue
        target = dest / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, target)
        except OSError:
            skipped.append(rel)
            continue
        saved[rel] = target
        total += size
    return saved, skipped


def _unchanged(root: Path, rel: str, sig: tuple, snap: EspSnapshot, now_files: dict) -> bool:
    """¿El archivo sigue igual? Por tamaño y, si hay copia, por contenido. NO por fecha: FAT
    guarda la hora local y el kernel la convierte según la zona y las opciones de montaje
    (docs.kernel.org/filesystems/vfat), así que dos montajes pueden ver mtimes distintos."""
    cur = now_files.get(rel)
    if cur is None or cur[0] != sig[0]:
        return False
    saved = snap.backups.get(rel)
    if saved is None:
        return True                      # sin copia solo se puede comparar el tamaño
    try:
        return filecmp.cmp(root / rel, saved, shallow=False)
    except OSError:
        return False


def restore_tree(root: Path, snap: EspSnapshot) -> TreeResult:
    """Deja `root` como estaba en `snap`: quita archivos y carpetas nuevos, devuelve los
    archivos rastreados que se pisaron o borraron. Lo que ya existía y no se rastreó se
    deja como está (y se reporta si cambió)."""
    res = TreeResult()
    now_files, now_dirs = scan_tree(root)

    for rel in sorted(set(now_files) - set(snap.files)):          # archivos que agregó la instalación
        try:
            (root / rel).unlink()
            res.removed.append(rel)
        except OSError as e:
            res.errors.append(f"{rel}: {e}")

    for rel, sig in snap.files.items():                            # archivos previos cambiados o borrados
        if _unchanged(root, rel, sig, snap, now_files):
            continue
        saved = snap.backups.get(rel)
        if saved is None:
            res.unrestorable.append(rel)
            continue
        try:
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, dest)
            res.restored.append(rel)
        except OSError as e:
            res.errors.append(f"{rel}: {e}")

    for rel in sorted(now_dirs - snap.dirs, key=lambda r: r.count("/"), reverse=True):   # carpetas nuevas
        try:
            (root / rel).rmdir()                                   # solo si quedó vacía
        except OSError:
            pass
    return res


# ── MBR (BIOS) ────────────────────────────────────────────────────────────
def read_boot_code(dev: str) -> bytes | None:
    try:
        with open(dev, "rb") as fh:
            data = fh.read(MBR_BOOT_CODE_SIZE)
        return data if len(data) == MBR_BOOT_CODE_SIZE else None
    except OSError:
        return None


def write_boot_code(dev: str, data: bytes) -> None:
    """Escribe SOLO los 446 bytes de código: ni la tabla de particiones (446-509) ni la firma."""
    with open(dev, "r+b") as fh:
        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


# ── Bordes del disco (tabla de particiones byte a byte) ───────────────────
@dataclass
class DiskEdges:
    size: int
    head: bytes          # primer MiB (o el disco entero si es más chico)
    tail: bytes          # último MiB (vacío si head ya cubre todo el disco)
    tail_offset: int


def read_edges(dev: str) -> DiskEdges | None:
    try:
        with open(dev, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size < 4096:
                return None
            head_len = min(EDGE_BYTES, size)
            tail_len = min(EDGE_BYTES, size - head_len)
            tail_offset = size - tail_len
            fh.seek(0)
            head = fh.read(head_len)
            tail = b""
            if tail_len:
                fh.seek(tail_offset)
                tail = fh.read(tail_len)
        if len(head) != head_len or len(tail) != tail_len:
            return None
        return DiskEdges(size=size, head=head, tail=tail, tail_offset=tail_offset)
    except OSError:
        return None


def write_edges(dev: str, edges: DiskEdges) -> None:
    """Devuelve los bytes tal como estaban: la copia del final primero y el inicio al último."""
    with open(dev, "r+b") as fh:
        if edges.tail:
            fh.seek(edges.tail_offset)
            fh.write(edges.tail)
        fh.seek(0)
        fh.write(edges.head)
        fh.flush()
        os.fsync(fh.fileno())


# ── Tabla de particiones (texto) ──────────────────────────────────────────
def normalize_dump(text: str) -> list:
    """Compara dos `sfdisk --dump` sin que importen espacios ni la línea «device:»."""
    return [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()
            if ln.strip() and not ln.startswith("device:")]


# ── El diario ─────────────────────────────────────────────────────────────
class InstallJournal:
    def __init__(self, session):
        self.session = session
        mem = getattr(session, "rollback_memory", None)
        if mem is None:
            mem = {"tables": {}, "table_paths": {}, "edges": {}, "formatted": set(), "fw": None}
            session.rollback_memory = mem
        self.mem = mem
        self.phase = "init"
        self.uefi = False
        self.table_dev: str | None = None
        self.esp: EspSnapshot | None = None
        self.mbr: tuple | None = None            # (dispositivo, bytes)
        self.fw_unreadable = False               # UEFI pero efibootmgr falta en el live o no pudo leer el firmware
        self.warnings = 0

    # ── utilidades ────────────────────────────────────────────────
    def _log(self, key: str, cls: str = "info", **kw) -> None:
        self.session.log(self.session.t(key, **kw), cls)

    def _warn(self, key: str, **kw) -> None:
        self.warnings += 1
        self._log(key, "warn", **kw)

    def _diag(self, text: str) -> None:
        try:
            self.session.logfile.diag(text)
        except Exception:  # noqa: BLE001 — el log jamás debe romper el rollback
            pass

    def mark(self, phase: str) -> None:
        if PHASES.index(phase) > PHASES.index(self.phase):
            self.phase = phase

    def mark_format(self, dev: str) -> None:
        """Se llama justo ANTES de cada mkfs: desde aquí los datos del disco ya no existen."""
        self.mem["formatted"].add(dev)
        self.mark("format")

    # ── instantáneas (antes de cambiar nada) ──────────────────────
    def snapshot_firmware(self, uefi: bool) -> None:
        self.uefi = bool(uefi)
        if not self.uefi or self.mem.get("fw"):      # el primer intento de la sesión es el «original»
            return
        rc, out, _err = run_command(["efibootmgr", "-v"])
        state = parse_efibootmgr(out) if rc == 0 else None
        self.mem["fw"] = state
        self.fw_unreadable = state is None

    def snapshot_table(self, dev: str) -> None:
        """Modo automático, justo antes de wipefs. Guarda (solo la primera vez de la sesión)
        el primer y el último MiB del disco byte a byte y además un `sfdisk --dump` legible;
        deja copias en disco y en el log."""
        self.table_dev = dev
        self.mark("table")
        edges_mem = self.mem.setdefault("edges", {})
        if dev in self.mem["tables"] or dev in edges_mem:
            return
        edges = read_edges(dev)
        edges_mem[dev] = edges
        rc, out, _err = run_command(["sfdisk", "--dump", dev])
        dump = out if rc == 0 and re.search(r"^label:\s*\w+", out or "", re.M) else None
        self.mem["tables"][dev] = dump
        if edges is not None:
            self._persist_edges(dev, edges)
        if dump is None:
            if edges is not None:
                self._log("rb-table-saved", "info", dev=dev, path=ROLLBACK_DIR)
            return
        for line in dump.splitlines():
            self._diag(f"sfdisk-dump {dev}: {line}")
        path = ROLLBACK_DIR / f"sfdisk-{Path(dev).name}.dump"
        try:
            ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(dump, encoding="utf-8")
            path.chmod(0o600)
            self.mem["table_paths"][dev] = path
            self._log("rb-table-saved", "info", dev=dev, path=path)
        except OSError:
            pass

    def _persist_edges(self, dev: str, edges: DiskEdges) -> None:
        """Copias con el nombre y el formato de sfdisk/wipefs (<disp>-<offset>.bak): se restauran
        a mano con dd if=<archivo> of=<disp> seek=$((0x<offset>)) bs=1 conv=notrunc."""
        try:
            ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
            name = Path(dev).name
            for offset, data in ((0, edges.head), (edges.tail_offset, edges.tail)):
                if not data:
                    continue
                path = ROLLBACK_DIR / f"edges-{name}-0x{offset:08x}.bak"
                path.write_bytes(data)
                path.chmod(0o600)
                self._diag(f"edges-backup {dev}: dd if={path} of={dev} seek=$((0x{offset:08x})) bs=1 conv=notrunc")
        except OSError:
            pass                                  # sigue la copia en memoria

    def snapshot_esp(self, efi_device: str, root: Path | None = None) -> None:
        """Con la ESP montada y ANTES del bootloader: árbol de archivos y copia de los que un
        bootloader suele pisar."""
        root = root or MOUNT_EFI
        if not (self.uefi and efi_device) or not os.path.ismount(root):
            return
        backup_dir = ROLLBACK_DIR / "esp-backup"
        shutil.rmtree(backup_dir, ignore_errors=True)
        files, dirs = scan_tree(root)
        saved, skipped = backup_tracked(root, files, backup_dir)
        self.esp = EspSnapshot(device=efi_device, files=files, dirs=dirs, backups=saved, skipped=skipped)

    def snapshot_mbr(self, dev: str) -> None:
        """BIOS en modo manual: el MBR de un disco ajeno conserva su código de arranque."""
        code = read_boot_code(dev)
        if code is not None:
            self.mbr = (dev, code)

    # ── deshacer ──────────────────────────────────────────────────
    def rollback(self, completed: bool) -> None:
        """Se llama siempre desde el finally de run_installation. Nunca lanza."""
        try:
            if completed:
                shutil.rmtree(ROLLBACK_DIR, ignore_errors=True)
                return
            if self.phase == "init":
                return                                  # no se cambió nada: sin ruido
            if os.environ.get(KILL_SWITCH_ENV) == "1":
                self._log("rb-disabled", "warn", env=KILL_SWITCH_ENV)
                return
            if self.phase == "usable":
                self._log("rb-kept", "info")
                return
            self._log("rb-start", "warn")
            for step in (self._undo_mbr, self._undo_esp, self._undo_firmware, self._undo_table):
                try:
                    step()
                except Exception as e:  # noqa: BLE001 — un paso roto no frena a los demás
                    self._warn("rb-error", e=e)
            if self.warnings:
                self._log("rb-done-warn", "warn")
            else:
                self._log("rb-done", "ok")
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        shutil.rmtree(ROLLBACK_DIR / "esp-backup", ignore_errors=True)
        try:
            if ESP_PROBE_DIR.is_dir() and not os.path.ismount(ESP_PROBE_DIR):
                ESP_PROBE_DIR.rmdir()                  # rmdir, jamás rmtree: podría ser una ESP montada
        except OSError:
            pass

    def _undo_mbr(self) -> None:
        if not self.mbr or self.phase != "boot":
            return
        dev, saved = self.mbr
        now = read_boot_code(dev)
        if now is None:
            self._warn("rb-mbr-failed", dev=dev, e="read")
            return
        if now == saved:
            return
        try:
            write_boot_code(dev, saved)
        except OSError as e:
            self._warn("rb-mbr-failed", dev=dev, e=e)
            return
        if read_boot_code(dev) == saved:
            self._log("rb-mbr-restored", "ok", dev=dev)
        else:
            self._warn("rb-mbr-failed", dev=dev, e="verify")

    def _undo_esp(self) -> None:
        snap = self.esp
        if snap is None or self.phase != "boot":
            return
        probe = ESP_PROBE_DIR
        mounted_here = False
        root = MOUNT_EFI
        if not os.path.ismount(root):
            probe.mkdir(parents=True, exist_ok=True)
            rc, _out = self.session.run_cmd(["mount", snap.device, str(probe)], timeout=30, abortable=False)
            if rc != 0 or not os.path.ismount(probe):
                self._warn("rb-esp-failed", e=f"mount rc={rc}")
                return
            mounted_here = True
            root = probe
        try:
            res = restore_tree(root, snap)
        finally:
            if mounted_here:
                self.session.run_cmd(["sync"], timeout=60, abortable=False)
                self.session.run_cmd(["umount", str(probe)], timeout=30, abortable=False)
        if res.errors:
            self._warn("rb-esp-failed", e="; ".join(res.errors[:3]))
        if res.unrestorable:
            self._warn("rb-esp-unrestorable", n=len(res.unrestorable), files=", ".join(res.unrestorable[:5]))
        if res.removed or res.restored:
            self._log("rb-esp-done", "ok", removed=len(res.removed), restored=len(res.restored))

    def _undo_firmware(self) -> None:
        before: FirmwareState | None = self.mem.get("fw")
        if not self.uefi or self.phase != "boot":
            return
        if before is None:
            if self.fw_unreadable:                # ISO sin efibootmgr (o firmware ilegible): que no sea en silencio
                self._warn("rb-fw-unavailable")
            return
        rc, out, _err = run_command(["efibootmgr", "-v"])
        after = parse_efibootmgr(out) if rc == 0 else None
        if after is None:
            self._warn("rb-fw-failed", what="efibootmgr")
            return

        # 1) entradas nuevas (o cambiadas) y nuestras: fuera. Las preexistentes no se tocan jamás.
        for bid, text in after.entries.items():
            if before.entries.get(bid) == text:
                continue
            label = after.label(bid)
            if not is_ours(label):
                self._log("rb-fw-kept", "info", id=bid, label=label)
                continue
            rc_del, _o = self.session.run_cmd(["efibootmgr", "-b", bid, "-B"], timeout=30, abortable=False)
            if rc_del == 0:
                self._log("rb-fw-removed", "ok", id=bid, label=label)
            else:
                self._warn("rb-fw-failed", what=f"Boot{bid}")

        # 2) orden de arranque: el original, sin las entradas que ya no existen
        rc, out, _err = run_command(["efibootmgr", "-v"])
        final = parse_efibootmgr(out) if rc == 0 else None
        if final is None:
            return
        lost = [before.label(b) for b in before.entries if final.entries.get(b) != before.entries[b]]
        if lost:
            self._warn("rb-fw-lost", labels=", ".join(l or "?" for l in lost))
            for bid in before.entries:
                if final.entries.get(bid) != before.entries[bid]:
                    self._diag(f"efi-entry-lost Boot{bid}: {before.entries[bid]}")
        target = [b for b in before.order if b in final.entries]
        if target and final.order != target:
            order = ",".join(target)
            rc_o, _o = self.session.run_cmd(["efibootmgr", "-o", order], timeout=30, abortable=False)
            if rc_o == 0:
                self._log("rb-fw-order", "ok", order=order)
            else:
                self._warn("rb-fw-failed", what="BootOrder")

    def _undo_table(self) -> None:
        dev = self.table_dev
        if not dev:
            return
        if dev in self.mem["formatted"]:
            self._log("rb-table-formatted", "warn", dev=dev)
            return
        edges = self.mem.get("edges", {}).get(dev)
        if edges is not None:
            self._restore_edges(dev, edges)
        elif self.mem["tables"].get(dev):
            self._restore_with_sfdisk(dev)            # no se pudo leer el disco: queda el volcado de texto

    def _restore_edges(self, dev: str, edges: DiskEdges) -> None:
        now = read_edges(dev)
        if now is None:
            self._warn("rb-edges-failed", dev=dev, e="read", dir=ROLLBACK_DIR)
            return
        if now.size != edges.size:                    # otro disco con el mismo nombre: no se toca
            self._warn("rb-edges-failed", dev=dev, e=f"size {now.size} != {edges.size}", dir=ROLLBACK_DIR)
            return
        if now.head == edges.head and now.tail == edges.tail:
            self._log("rb-table-unchanged", "info", dev=dev)
            return
        try:
            write_edges(dev, edges)
        except OSError as e:
            self._warn("rb-edges-failed", dev=dev, e=e, dir=ROLLBACK_DIR)
            return
        run_command(["blockdev", "--rereadpt", dev], timeout=15)
        run_command(["udevadm", "settle", "--timeout=5"], timeout=15)
        back = read_edges(dev)
        if back is not None and back.head == edges.head and back.tail == edges.tail:
            self._log("rb-table-restored", "ok", dev=dev)
        else:
            self._warn("rb-table-mismatch", dev=dev, path=ROLLBACK_DIR)

    def _restore_with_sfdisk(self, dev: str) -> None:
        saved = self.mem["tables"].get(dev)
        rc, now, _err = run_command(["sfdisk", "--dump", dev])
        if rc == 0 and normalize_dump(now) == normalize_dump(saved):
            self._log("rb-table-unchanged", "info", dev=dev)
            return
        path = self.mem["table_paths"].get(dev)
        if path is None or not Path(path).is_file():
            path = ROLLBACK_DIR / f"sfdisk-{Path(dev).name}.dump"
            try:
                ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(saved, encoding="utf-8")
                path.chmod(0o600)
                self.mem["table_paths"][dev] = path
            except OSError as e:
                self._warn("rb-error", e=e)
                return
        # --wipe-partitions never: restaurar la tabla no debe borrar firmas de nada
        rc_restore, _out = self.session.run_cmd(
            ["sh", "-c", 'sfdisk --wipe-partitions never "$1" < "$2"', "sh", dev, str(path)],
            timeout=60, abortable=False)
        run_command(["blockdev", "--rereadpt", dev], timeout=15)
        run_command(["udevadm", "settle", "--timeout=5"], timeout=15)
        rc, after, _err = run_command(["sfdisk", "--dump", dev])
        if rc == 0 and normalize_dump(after) == normalize_dump(saved):
            self._log("rb-table-restored", "ok", dev=dev)      # aunque sfdisk se quejara del reread
        elif rc_restore != 0:
            self._warn("rb-table-failed", dev=dev, rc=rc_restore, path=path)
        else:
            self._warn("rb-table-mismatch", dev=dev, path=path)
'''),
    # ── avalos_installer/system/services.py (198 líneas)
    'avalos_installer.system.services': (False, 'avalos_installer/system/services.py', r'''"""
system/services.py — servicios systemd base (red, bluetooth, sddm,
sensores, audio) + snapshots con Snapper/grub-btrfs.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas ~4674-4762, sección "services" de PASOS_IDS). Sin cambios de
lógica respecto al original: ninguna falla acá es fatal para la
instalación (ni un solo `return` en todo el bloque) — Snapper/snapshots
es un extra, no algo de lo que dependa el sistema para arrancar o
funcionar. Por eso configure_services() no devuelve bool ni tiene su
propio try/except: cualquier excepción inesperada sube hasta el
try/except general del orquestador (core/install.py), igual que en el
original.
"""
from __future__ import annotations

from avalos_installer.core.config import MOUNT_ROOT, BTRFS_MOUNT_OPTS
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession

# Recorte de retención de Snapper respecto a los defaults del paquete
# (10/10/0/10/10, 50/50) — pensado para no llenar @snapshots en discos
# chicos. Mismos valores que el original.
_SNAPPER_RETENTION = {
    'TIMELINE_LIMIT_HOURLY="10"': 'TIMELINE_LIMIT_HOURLY="5"',
    'TIMELINE_LIMIT_DAILY="10"': 'TIMELINE_LIMIT_DAILY="7"',
    'TIMELINE_LIMIT_WEEKLY="0"': 'TIMELINE_LIMIT_WEEKLY="4"',
    'TIMELINE_LIMIT_MONTHLY="10"': 'TIMELINE_LIMIT_MONTHLY="3"',
    'TIMELINE_LIMIT_YEARLY="10"': 'TIMELINE_LIMIT_YEARLY="0"',
    'NUMBER_LIMIT="50"': 'NUMBER_LIMIT="10"',
    'NUMBER_LIMIT_IMPORTANT="50"': 'NUMBER_LIMIT_IMPORTANT="10"',
}

_GPU_DETECT_UNIT = (
    "[Unit]\n"
    "Description=AvalOS — GPU Environment Detection\n"
    "Documentation=https://github.com/jeffreysama/avalos\n"
    "Before=sddm.service display-manager.service\n"
    "After=systemd-udev-settle.service\n\n"
    "[Service]\n"
    "Type=oneshot\n"
    "ExecStart=/usr/local/bin/avalos-gpu-env\n"
    "RemainAfterExit=yes\n\n"
    "[Install]\n"
    "WantedBy=graphical.target\n"
)


def configure_services(session: InstallSession, ctx: InstallContext) -> None:
    """Habilita NetworkManager/bluetooth/sddm/lm_sensors, pipewire en
    modo --global, el servicio propio de detección de GPU, y (fuera de
    modo USB) Snapper + grub-btrfsd con la retención recortada de
    arriba. Ninguna falla acá detiene la instalación."""
    session.step("services", "active")
    session.status(session.t("status-enabling-services"))

    svc_dir = MOUNT_ROOT / "etc/systemd/system"
    svc_dir.mkdir(parents=True, exist_ok=True)
    (svc_dir / "avalos-gpu-detect.service").write_text(_GPU_DETECT_UNIT)

    wants = svc_dir / "graphical.target.wants"
    wants.mkdir(exist_ok=True)
    symlink = wants / "avalos-gpu-detect.service"
    # is_symlink(), no exists(): el destino es absoluto y exists() lo resuelve contra la raíz del
    # HOST (donde ese archivo no existe), así que un symlink ya creado se veía como "no existe" y
    # symlink_to() reventaba con FileExistsError en un reintento sobre el mismo target.
    if not symlink.is_symlink():
        symlink.symlink_to("/etc/systemd/system/avalos-gpu-detect.service")
    session.log(session.t("log-gpu-detect-service-ok"), "ok")

    for svc in ["NetworkManager", "bluetooth", "sddm", "lm_sensors"]:
        session.run_chroot(["systemctl", "enable", svc])
    session.run_chroot(["systemctl", "--global", "enable",
                         "pipewire", "pipewire-pulse", "wireplumber"])
    session.log(session.t("log-sensors-detect-skipped"), "warn")

    if not ctx.usb_mode:
        session.log(session.t("log-section-snapper"), "step")

        # FIX (documentado en wiki.archlinux.org/title/Snapper): con un
        # layout de subvolúmenes @-prefijados como este, @snapshots ya
        # queda montado en /.snapshots desde el particionado —
        # 'create-config' SIEMPRE falla ahí con errno 17 ("creating btrfs
        # subvolume .snapshots failed since it already exists"): intenta
        # crear su PROPIO subvolumen en ese path y el nombre ya está
        # ocupado. El propio archinstall tuvo este bug hasta la 3.0.5.
        # Secuencia completa:
        #   umount /.snapshots -> rm -r /.snapshots -> create-config
        #   -> btrfs subvolume delete /.snapshots -> mkdir /.snapshots
        #   -> mount del @snapshots persistente de siempre.
        # La versión anterior solo hacía umount + remount: faltaban el
        # rm -r (el directorio vacío que queda como punto de montaje sigue
        # ocupando el nombre, así que create-config fallaba igual) y el
        # mkdir (delete se lleva el directorio y mount no lo crea: el
        # re-montaje fallaba siempre).
        snap_mount = MOUNT_ROOT / ".snapshots"
        root_dev = ""
        was_mounted = False
        if snap_mount.exists():
            # --mountpoint (no --target): solo matchea si /.snapshots ES un
            # punto de montaje. Con --target, si no lo fuera, findmnt
            # devolvería el montaje padre (@) y se intentaría desmontar
            # algo que no corresponde.
            rc_find, out_find = session.run_cmd(
                ["findmnt", "-n", "-o", "SOURCE", "--mountpoint", str(snap_mount)]
            )
            root_dev = out_find.strip().split("[")[0].strip()
            if rc_find == 0 and root_dev:
                rc_um, _ = session.run_cmd(["umount", str(snap_mount)])
                was_mounted = (rc_um == 0)
            if was_mounted:
                try:
                    snap_mount.rmdir()  # vacío: es solo el punto de montaje
                except OSError as e:
                    session.log(
                        f"[WARN] no se pudo borrar el punto de montaje {snap_mount} "
                        f"({e}) — create-config va a fallar con errno 17", "warn"
                    )
            else:
                session.log(
                    f"[WARN] no se pudo desmontar {snap_mount} antes de Snapper "
                    f"(o no se identificó el dispositivo) — create-config puede "
                    f"fallar igual que antes", "warn"
                )

        rc_snap, out_snap = session.run_chroot(
            ["snapper", "--no-dbus", "-c", "root", "create-config", "/"]
        )

        if was_mounted:
            # El .snapshots que dejó create-config es un subvolumen nuevo y
            # vacío (si falló, puede no existir) — se descarta y se vuelve
            # a montar el @snapshots persistente con las mismas opciones
            # que el resto de los subvolúmenes. Esto corre también si
            # create-config falló, para no dejar el sistema sin @snapshots.
            if snap_mount.exists():
                session.run_cmd(["btrfs", "subvolume", "delete", str(snap_mount)])
            try:
                snap_mount.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                session.log(f"[WARN] no se pudo recrear {snap_mount}: {e}", "warn")
            rc_rm, out_rm = session.run_cmd(
                ["mount", "-o", f"subvol=@snapshots,{BTRFS_MOUNT_OPTS}", root_dev, str(snap_mount)]
            )
            if rc_rm != 0:
                session.log(
                    f"[WARN] no se pudo re-montar el @snapshots persistente en "
                    f"{snap_mount} — puede haber quedado sin ese subvolumen: "
                    f"{out_rm.strip()[-160:]}", "err"
                )

        if rc_snap != 0:
            # No fatal: Snapper es un extra (snapshots), no algo de lo
            # que dependa el sistema para arrancar o funcionar. Mejor
            # entregar un sistema completo y booteable sin snapshots que
            # tirar todo el trabajo ya hecho (kernel+bootloader+servicios)
            # por este extra.
            session.log(
                session.t("log-snapper-create-config-fail", rc=rc_snap, out=out_snap), "warn"
            )
            session.log(session.t("log-snapper-skipped-continuing"), "warn")
        else:
            session.log(session.t("log-snapper-config-created"), "ok")

            snapper_cfg = MOUNT_ROOT / "etc" / "snapper" / "configs" / "root"
            if snapper_cfg.exists():
                cfg_txt = snapper_cfg.read_text()
                for old, new in _SNAPPER_RETENTION.items():
                    cfg_txt = cfg_txt.replace(old, new)
                snapper_cfg.write_text(cfg_txt)
                session.log(session.t("log-snapper-retention-ok"), "ok")

            for svc in ["snapper-timeline.timer", "snapper-cleanup.timer"]:
                session.run_chroot(["systemctl", "enable", svc])
            session.log(session.t("log-snapper-timers-ok"), "ok")

            if ctx.bootloader == "grub":
                session.run_chroot(["systemctl", "enable", "grub-btrfsd"])
                session.run_chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
                session.log(session.t("log-grubbtrfs-ok"), "ok")
            else:
                session.log(session.t("log-grubbtrfs-skipped"), "warn")
                session.log(session.t("log-snapshots-still-work"), "warn")
                session.log(session.t("log-manual-rollback-hint"), "warn")

            snap_dir = MOUNT_ROOT / ".snapshots"
            if snap_dir.exists():
                session.run_cmd(["chmod", "750", str(snap_dir)])
                session.log(session.t("log-snapshots-perms-ok"), "ok")

            session.log(session.t("log-snapshots-configured-ok"), "ok")

    session.step(
        "services", "done",
        "NetworkManager · bluetooth · sddm · pipewire · snapper"
        if not ctx.usb_mode else
        "NetworkManager · bluetooth · sddm · pipewire · avalos-gpu-detect",
    )
'''),
    # ── avalos_installer/system/users.py (64 líneas)
    'avalos_installer.system.users': (False, 'avalos_installer/system/users.py', r'''"""
system/users.py — creación del usuario final y su acceso sudo.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas ~4772-4797, sección "user" de PASOS_IDS). Sin cambios de lógica
respecto al original: mismos grupos, mismo shell, mismo archivo sudoers.

El chpasswd del usuario final reusa el mismo patrón que ya usa
system/locale.py para el chpasswd de root — va por stdin, nunca por
argv (la contraseña no debe aparecer en `ps aux` ni en ningún log de
comandos).
"""
from __future__ import annotations

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession


def create_user(session: InstallSession, ctx: InstallContext) -> bool:
    """Crea el usuario final (grupos wheel/audio/video/storage/optical),
    le fija la contraseña, y habilita sudo para el grupo wheel.

    Devuelve True si todo salió bien, False si falló. En caso de falla
    ya se llamó session.clean_mounts() y ya se reportó el error a la UI
    antes de retornar — el llamador (el orquestador) solo necesita
    chequear el retorno y detenerse, igual que con el resto de los
    módulos de system/.
    """
    session.step("user", "active")
    session.status(session.t("status-creating-user"))
    session.log(session.t("log-section-creating-user"), "step")

    rc, _ = session.run_chroot([
        "useradd", "-m", "-G", "wheel,audio,video,storage,optical",
        "-s", "/bin/bash", ctx.username,
    ])
    if rc != 0:
        session.step("user", "error")
        session.error_step(session.t("err-useradd-failed", usuario=ctx.username))
        session.clean_mounts()
        return False

    rc_pw, out_pw = session.run_chroot_stdin(f"{ctx.username}:{ctx.password}\n", ["chpasswd"])
    if rc_pw != 0:
        session.log(
            session.t("log-chpasswd-user-fail", usuario=ctx.username, rc=rc_pw, out=out_pw),
            "err",
        )
        session.step("user", "error")
        session.error_step(session.t("err-chpasswd-failed", usuario=ctx.username))
        session.clean_mounts()
        return False

    try:
        sudoers = MOUNT_ROOT / "etc" / "sudoers.d" / "wheel"
        sudoers.parent.mkdir(parents=True, exist_ok=True)
        sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
        sudoers.chmod(0o440)
    except OSError as e:
        session.log(session.t("log-sudoers-wheel-fail", e=str(e)), "warn")

    session.step("user", "done", session.t("step-user-created-label", usuario=ctx.username))
    return True
'''),
    # ── avalos_installer/ui/__init__.py (0 líneas)
    'avalos_installer.ui': (True, 'avalos_installer/ui/__init__.py', r''''''),
    # ── avalos_installer/ui/api.py (323 líneas)
    'avalos_installer.ui.api': (False, 'avalos_installer/ui/api.py', r'''"""
ui/api.py — InstallerAPI: el puente JS↔Python de pywebview.

Extraído de InstaladorAPI en skill_instalar_usb.py (líneas 2349-2533).
Cada método público de esta clase se llama directo desde el JS embebido
en ui/html.py vía window.pywebview.api.<nombre>(...) — los nombres de
método SÍ le importan a JS, así que se renombraron TODOS a inglés (regla
del proyecto) y se actualizaron los 11 call-sites correspondientes en
ui/html.py en la misma sesión, para que ambos lados del puente queden
sincronizados. Nunca se cambian estos nombres en un solo lado sin el otro.

Mapeo de nombres (original → nuevo):
    set_language                  → set_language   (ya estaba en inglés)
    on_ready                      → on_ready        (ya estaba en inglés)
    iniciar_instalacion           → start_installation
    abortar_instalacion           → abort_installation
    abrir_terminal_particionado   → open_partitioning_terminal
    verificar_particionado_manual → check_manual_partitioning
    confirmar_root_manual         → confirm_manual_root
    reintentar                    → retry
    elegir_mirror                 → choose_mirror
    reiniciar_equipo              → reboot_system
    cerrar                        → close

Los dict que cruzan a JS (ej. el resultado de check_manual_partitioning)
mantienen sus claves tal cual el original ("candidatas_root",
"requiere_seleccion", "subvols_existentes", etc.) — son payload de datos,
no identificadores de código, mismo criterio que ya usa disk/discovery.py
(ver "es_arranque"/"tipo"/"particiones" en list_disks()). Cambiarlas
exigiría tocar el JS que las lee sin ganar nada a cambio.

DECISIÓN DE DISEÑO — de dónde sale el InstallContext: en el original,
VentanaInstalador era a la vez el bridge de API y el runner de la
instalación, así que iniciar_instalacion() escribía username/password/
etc. directo como atributos de self. Acá InstallSession (comportamiento)
e InstallContext (config) están separados de InstallerAPI (bridge), así
que start_installation() arma un InstallContext completo recién al
final, lo dejá en session.pending_context, y llama
session._config_ready.set(). El hilo de instalación (arrancado temprano,
al cargar la ventana — ver core/install.py) está bloqueado esperando ese
mismo evento desde el principio, exactamente como _run_instalacion()
esperaba con self._config_lista.wait(timeout=600) en el original —
incluido el caso de retry(), donde _config_ready ya está seteado de la
primera vez y el wait() de core.install.run_installation() vuelve de
inmediato, sin bloquear.

Los campos de "modo manual" en curso (candidatas, EFI detectada,
subvolúmenes existentes, root elegida) no son ni comportamiento
(InstallSession) ni config final (InstallContext) — son estado de flujo
del wizard, solo relevante mientras el usuario todavía está llenando el
formulario. Por eso viven como atributos privados de InstallerAPI mismo,
igual que vivían en VentanaInstalador en el original.

BUG encontrado y corregido durante la extracción: el reiniciar_equipo()
original loguea con self._t(...) — pero _t solo existe en VentanaInstalador
(self._v._t), no en InstaladorAPI. Nunca se manifestó porque solo se
ejecuta si systemctl reboot falla al lanzarse (Popen), pero era un
AttributeError latente. Acá usa session.t(...), que sí existe.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading

import translations
from avalos_installer.core.config import (
    DEFAULT_HOSTNAME, DEFAULT_KEYMAP, DEFAULT_LOCALE, DEFAULT_TIMEZONE,
    KEYMAPS, LOCALES, RESERVED_USERNAMES, TIMEZONES,
)
from avalos_installer.core.context import InstallContext
from avalos_installer.core.install import run_installation
from avalos_installer.core.session import InstallSession
from avalos_installer.disk.discovery import detect_btrfs_subvolumes, detect_manual_partitions, list_disks
from avalos_installer.hardware.detection import is_uefi


class InstallerAPI:
    """Métodos expuestos al JavaScript del wizard."""

    def __init__(self, session: InstallSession):
        self.session = session
        # Estado de flujo del wizard en modo manual — ver docstring del módulo.
        self._manual_ready = False
        self._manual_efi = ""
        self._manual_root_candidates: list[dict] = []
        self._manual_existing_subvolumes: list[str] = []
        self._manual_root = ""
        self._manual_disk = ""  # disco (sin /dev/) para el que se hizo la verificación manual

    def set_language(self, code: str) -> bool:
        """Llamado desde JS al elegir idioma. Guarda el código para
        usarlo al generar archivos de configuración (fastfetch, etc.)."""
        allowed = tuple(c for c, _ in translations.SUPPORTED_LANGS)
        if code in allowed:
            self.session._lang = code
            return True
        return False

    def on_ready(self) -> bool:
        """DOM listo: poblar discos y mostrar bienvenida."""
        disks = list_disks()
        self.session.render_disks(disks)
        return True

    def run_preflight(self) -> dict:
        """Comprobación previa del equipo para la pantalla de bienvenida (ver
        hardware/preflight.py). Devuelve CLAVES i18n + parámetros para que la UI
        traduzca en el idioma vigente. No lanza: si algo falla devuelve ok=False y la
        UI deja continuar (la comprobación es una ayuda, no un candado)."""
        s = self.session
        try:
            from avalos_installer.hardware.preflight import report_lines, run_preflight, to_dict
            from avalos_installer.network.diagnose import diagnose_network
            diag = diagnose_network()
            checks = run_preflight(s, diag)
            s.logfile.diag("── preflight ──")
            for ln in diag.lines():
                s.logfile.diag(f"net: {ln}")
            for ln in report_lines(checks):
                s.logfile.diag(f"preflight: {ln}")
            return {"ok": True, **to_dict(checks)}
        except Exception as e:  # noqa: BLE001
            s.logfile.write("err", f"preflight falló: {e!r}")
            return {"ok": False, "checks": [], "blocking": False, "warnings": 0, "error": str(e)}

    def start_installation(self, username: str, password: str, hostname: str,
                            timezone: str, disk: str, bootloader: str, usb: bool,
                            locale: str = "", keymap: str = "", gaming: bool = False,
                            bore: bool = False, manual: bool = False) -> bool:
        """El usuario pulsó 'Instalar AvalOS' con configuración válida."""
        clean_username = username.strip()
        clean_hostname = hostname.strip() or DEFAULT_HOSTNAME
        # Revalidación del lado Python: el JS ya filtra, pero estos valores acaban en
        # sudoers.d (aur.py), useradd, /etc/hostname y chpasswd por stdin, así que un
        # salto de línea o un carácter raro no debe llegar hasta ahí aunque el front falle.
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", clean_username):
            return False
        if clean_username in RESERVED_USERNAMES:  # mismo criterio que el JS (lista única en config.py)
            return False
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", clean_hostname):
            return False
        if not password or any(c in password for c in "\n\r\0"):
            return False

        if manual and not self._manual_ready:
            # JS dice modo manual pero Python nunca confirmó una detección
            # válida (check_manual_partitioning/confirm_manual_root) — no
            # arrancar la instalación con partición root vacía.
            return False
        if manual and (disk or "").removeprefix("/dev/") != self._manual_disk:
            # La detección manual se hizo para OTRO disco (el usuario cambió la selección después
            # de verificar): root/EFI son de aquel. El JS vuelve al formulario con el aviso del
            # particionado manual y hay que verificar de nuevo sobre este disco.
            self._manual_ready = False
            return False

        valid_locales = {lc for lc, _ in LOCALES}
        valid_keymaps = {km for km, _ in KEYMAPS}

        ctx = InstallContext(
            username=clean_username,
            password=password,
            hostname=clean_hostname,
            # acaba en el symlink de /etc/localtime: solo valores de la lista; otro cae al
            # default, igual que locale y keymap
            timezone=timezone if timezone in TIMEZONES else DEFAULT_TIMEZONE,
            locale=locale if locale in valid_locales else DEFAULT_LOCALE,
            keymap=keymap if keymap in valid_keymaps else DEFAULT_KEYMAP,
            lang=self.session._lang,
            target_disk=disk,
            bootloader=bootloader if bootloader in ('grub', 'sd-boot', 'refind', 'none') else 'grub',
            usb_mode=bool(usb),
            manual_mode=bool(manual) and self._manual_ready,
            manual_efi_partition=self._manual_efi if manual else "",
            manual_root_partition=self._manual_root if manual else "",
            manual_existing_subvolumes=self._manual_existing_subvolumes if manual else [],
            install_gaming=bool(gaming),
            install_bore=bool(bore),
        )
        self.session.pending_context = ctx
        self.session._config_ready.set()
        return True

    def abort_installation(self) -> bool:
        self.session._aborted = True
        return True

    def open_partitioning_terminal(self) -> bool:
        """Modo manual: lanza una terminal real del live ISO (no dentro
        del webview — webkit2gtk no tiene terminal embebido) para que el
        usuario corra cfdisk/parted/mkfs a mano. Se prueban varios
        emuladores comunes en orden porque este módulo no puede confirmar
        cuál viene empaquetado en el airootfs del ISO (eso se decide en
        build-iso.yml) — así el botón no depende de adivinar uno solo y
        fallar en silencio si no está. Bloquea (subprocess.run, no Popen)
        hasta que el usuario cierre la terminal, para que el JS sepa
        cuándo volver a habilitar el wizard."""
        candidates = [
            ["foot"], ["kitty"], ["alacritty"],
            ["xterm"], ["konsole"], ["gnome-terminal"],
        ]
        for cmd in candidates:
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, check=False)
                    return True
                except Exception as e:
                    self.session.log(
                        self.session.t("log-terminal-launch-warn", term=cmd[0], e=e), "warn"
                    )
                    continue
        self.session.log(self.session.t("err-no-terminal-found"), "err")
        return False

    def check_manual_partitioning(self, disk: str) -> dict:
        """Modo manual: tras volver de la terminal, analiza lo que el
        usuario dejó particionado en 'disk' vía detect_manual_partitions()
        (GUID GPT / flag bootable MBR — nunca heurística de tamaño u orden).

        Si hay una sola candidata a root y ya tiene Btrfs, además la sondea
        con detect_btrfs_subvolumes() para saber si el usuario ya creó los
        subvolúmenes de AvalOS a mano — así el orquestador puede saltarse
        la creación de los que ya existan en vez de pisarlos.

        Si hay más de una candidata a root, NO elige sola — devuelve la
        lista completa para que el wizard se la ofrezca al usuario en un
        dropdown; la decisión final llega después por confirm_manual_root()."""
        # Estado nuevo en cada verificación: nada de un disco o intento anterior debe sobrevivir.
        disk_name = (disk or "").removeprefix("/dev/")
        self._manual_ready = False
        self._manual_disk = disk_name
        self._manual_efi = ""
        self._manual_root = ""
        self._manual_root_candidates = []
        self._manual_existing_subvolumes = []
        info = detect_manual_partitions(disk_name, is_uefi())
        candidates = info["candidatas_root"]

        if not candidates:
            self._manual_ready = False
            return {"ok": False, "efi": "", "candidatas_root": [], "requiere_seleccion": False}

        existing_subvolumes: list[str] = []
        if len(candidates) == 1 and candidates[0]["fstype"] == "btrfs":
            existing_subvolumes = detect_btrfs_subvolumes(candidates[0]["name"])

        self._manual_efi = info["efi"]
        self._manual_root_candidates = candidates
        self._manual_existing_subvolumes = existing_subvolumes
        # Solo queda "listo" sin intervención extra si hay una única
        # candidata — con varias, el wizard debe esperar a
        # confirm_manual_root() antes de dejar avanzar el botón Instalar.
        self._manual_ready = (len(candidates) == 1)
        if len(candidates) == 1:
            self._manual_root = candidates[0]["name"]

        return {
            "ok": True,
            "efi": info["efi"],
            "candidatas_root": candidates,
            "requiere_seleccion": len(candidates) > 1,
            "subvols_existentes": existing_subvolumes,
        }

    def confirm_manual_root(self, disk: str, chosen_root: str) -> bool:
        """Modo manual: cuando check_manual_partitioning() devolvió más
        de una candidata a root, el usuario elige una en el dropdown del
        wizard y esta llamada la fija como definitiva. Vuelve a validar
        contra self._manual_root_candidates (no confía ciegamente en el
        string que llega de JS) para no aceptar un device arbitrario.
        'disk' tiene que ser el mismo disco para el que se verificó el particionado: si el
        usuario cambió la selección entre medio, las candidatas son de otro disco."""
        if (disk or "").removeprefix("/dev/") != self._manual_disk:
            return False
        valid = {c["name"] for c in self._manual_root_candidates}
        if chosen_root not in valid:
            return False
        self._manual_root = chosen_root
        # Los subvolúmenes se sondean SIEMPRE sobre el root elegido: con dos candidatas btrfs,
        # conservar la lista de la elección anterior hacía saltarse la creación de subvolúmenes
        # que en ESTA partición no existen.
        candidate = next((c for c in self._manual_root_candidates if c["name"] == chosen_root), None)
        self._manual_existing_subvolumes = (
            detect_btrfs_subvolumes(chosen_root) if candidate and candidate["fstype"] == "btrfs" else []
        )
        self._manual_ready = True
        return True

    def retry(self) -> bool:
        with self.session._lock:
            if self.session._installing:
                return True
            self.session._aborted = False
            self.session._installing = True
        t = threading.Thread(target=run_installation, args=(self.session,), daemon=True)
        self.session._install_thread = t
        t.start()
        return True

    def choose_mirror(self, choice) -> bool:
        # Recibe el clic de uno de los botones del diálogo ov-mirror y
        # libera el Event que el hilo de instalación está esperando
        # (bloqueado en _mirror_choice_event.wait() dentro del orquestador).
        self.session._mirror_choice = choice
        self.session._mirror_choice_event.set()
        return True

    def reboot_system(self) -> bool:
        try:
            subprocess.Popen(["systemctl", "reboot"])
        except Exception as e:
            self.session.log(self.session.t("log-reboot-warn", e=e), "warn")
        return True

    def close(self) -> bool:
        if self.session.window:
            try:
                self.session.window.destroy()
            except Exception:
                pass
        return True
'''),
    # ── avalos_installer/ui/assets.py (17 líneas)
    'avalos_installer.ui.assets': (False, 'avalos_installer/ui/assets.py', r'''"""
ui/assets.py — logo de AvalOS embebido como PNG base64 para el wizard.

Extraído programáticamente (nunca retipeado a mano, ver regla del
proyecto sobre blobs base64) de skill_instalar_usb.py, constante
_LOGO_B64 (línea 33). Único consumidor: ui.html (reemplaza
"LOGO_PLACEHOLDER" en el HTML del wizard) — por eso vive en ui/ y no en
core/config.py, mismo criterio que ya usa system/pacstrap.py para sus
listas de paquetes ("vive en el único lugar que la consume hoy").

sha256 del valor de LOGO_B64 al momento de la extracción (para poder
confirmar en cualquier momento que no se corrompió un solo byte):
bf4a36cdad5963e04b5ab14c55b805b1eb67cc1debcaa2927907d5ef196abce1
"""
from __future__ import annotations

LOGO_B64 = 'iVBORw0KGgoAAAANSUhEUgAABAAAAAQACAMAAABIw9uxAAABCGlDQ1BJQ0MgUHJvZmlsZQAAeJxjYGA8wQAELAYMDLl5JUVB7k4KEZFRCuwPGBiBEAwSk4sLGHADoKpv1yBqL+viUYcLcKakFicD6Q9ArFIEtBxopAiQLZIOYWuA2EkQtg2IXV5SUAJkB4DYRSFBzkB2CpCtkY7ETkJiJxcUgdT3ANk2uTmlyQh3M/Ck5oUGA2kOIJZhKGYIYnBncAL5H6IkfxEDg8VXBgbmCQixpJkMDNtbGRgkbiHEVBYwMPC3MDBsO48QQ4RJQWJRIliIBYiZ0tIYGD4tZ2DgjWRgEL7AwMAVDQsIHG5TALvNnSEfCNMZchhSgSKeDHkMyQx6QJYRgwGDIYMZAKbWPz9HbOBQAAADAFBMVEUAAACo5llVpf57zUREiy2N10yv52ZKkzJ4yjtnqfXP/I3F9nK09G88iCmc4VN90ESk3FQCFQBRnfRts/wAByiGyk0NSAAVVwAxdxIpaAmr2W0QNwFPdyx60DwMJgAvVw9Hd6/E628AFTUaZACLuFWZ5mmU2GcGJ04vWItTickqSA11pkplhzeWxmbn/6ZJaShkmNZymEdalNXk/phrljY4ZZd3tUqw8Vs5hBqFqVJTmEKkymolSXUTOWc6aqRBbadFhxtqqDm66IO3+YPD7IVShLojOwcAG0UPMliTumNYpDKD0zxsikU4eiM9kS9lnOZGeBiBzD3Z/6MaRHBttzlGZxpbsP4vU3k7Zic2WCRDaZg7c61ZokYmTYNhfTdqotoKIjpGkhtEXSdViUNKfMJBXBpOcZbB9F5hjMmKqWajzFsMK2JieEWLuO632oMdSoEkPmdoh6kdU4goPVorTSJXdUN5wf+Bqj6AuDye8Gs4XqNEW3tRZndhd5TC7l0AD0EaQV4hJg8/c5s6fcRMa0FXjuB4wmGGm1iImWKAwP+f4DqtzIDB32UAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgnUg+AAABAHRSTlMA/v////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAZvAFiwAAj0NJREFUeJzt/Qdj20iztYuKIrpBBJJgTpJoSaRsKwdb0fZrS7I9zmnGk2feuPPeX07nnHvSzeFH364GGAFGNEVKWs+MZY/HphjQhdXVVavm5gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGF4sT7tZwAAmBapvf9natrPAQAwJVL/dgYJAMBtZfOyvDft5wAAmA6VV8v/9P99Me1nAQCYBqlNkzuXkAAA3EqWXpmOw8vIAgBwG1kwHR5x+MYcTgIAuHWQAIiwCCQAALeRhUvOnUgkwk+g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'
'''),
    # ── avalos_installer/ui/html.py (1993 líneas)
    'avalos_installer.ui.html': (False, 'avalos_installer/ui/html.py', r'''"""
ui/html.py — HTML/CSS/JS del wizard del instalador, con el bridge
JS→Python ya apuntando a los nombres nuevos de ui.api.InstallerAPI.

Extraído programáticamente (nunca retipeado a mano) de skill_instalar_usb.py,
constante _HTML (líneas 628-2346, ~1719 líneas) + la función _build_html()
(líneas 5008-5049). El contenido es idéntico byte a byte al original EXCEPTO
por 10 líneas: las 9 llamadas window.pywebview.api.<nombre_viejo>(...) que
se renombraron a inglés para que coincidan con los métodos nuevos de
ui.api.InstallerAPI (ver el mapeo completo en el docstring de ese módulo).
set_language y on_ready ya estaban en inglés, no se tocaron. Verificado:
12 call-sites antes, 12 después, ningún nombre viejo sobrevive, y un diff
línea por línea confirmó que ninguna otra línea cambió.

CSS/markup/lógica de UI: sin cambios de ningún tipo respecto al original,
incluidos los comentarios de por qué (ej. el punto de inyección de
window._tzList/_localeList/_keymapList ANTES de 'use strict' para que las
IIFEs de initTZ()/initLocale()/initKeymap() las encuentren ya definidas).
"""
from __future__ import annotations

import json

import translations
from avalos_installer.core.config import (
    DEFAULT_HOSTNAME, DEFAULT_KEYMAP, DEFAULT_LOCALE, DEFAULT_TIMEZONE,
    KEYMAPS, LOCALES, RESERVED_USERNAMES, TIMEZONES,
)
from avalos_installer.ui.assets import LOGO_B64

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>AvalOS — Instalador</title>
<style>
/* ── RESET ─────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; font-size: 13px; cursor: default; user-select: none; }

/* ── TOKYO NIGHT + PHOSPHOR TOKENS ─────────────────────────────────────── */
:root {
  --tn-bg:      #1a1b26;  --tn-bg2:     #16161e;  --tn-surface: #24283b;
  --tn-border:  #414868;  --tn-blue:    #7aa2f7;  --tn-blue2:   #2ac3de;
  --tn-cyan:    #7dcfff;  --tn-green:   #9ece6a;  --tn-yellow:  #e0af68;
  --tn-red:     #f7768e;  --tn-purple:  #bb9af7;  --tn-orange:  #ff9e64;
  --tn-text:    #c0caf5;  --tn-dim:     #565f89;  --tn-white:   #a9b1d6;
  --ph-bg:      #020c02;  --ph-surface: #030f03;  --ph-border:  #0a2a0a;
  --ph-green:   #00ff41;  --ph-dim:     #4a8a4a;  --ph-text:    #b8ffb8;
  --ph-cyan:    #00f5d4;  --ph-yellow:  #f5e642;  --ph-red:     #ff3c3c;
  --ph-orange:  #ff8c00;  --ph-muted:   #2a5c2a;  --ph-lo:      #003d0f;
  --font-ui: 'Segoe UI', system-ui, -apple-system, sans-serif;
  --font-mono: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  --r: 8px; --r-sm: 4px; --trans: 0.15s ease;
}

/* ── PAGES ──────────────────────────────────────────────────────────────── */
.lang-key-hint { position:absolute; right:12px; top:50%; transform:translateY(-50%);
  font-size:10px; color:#565f89; border:1px solid #414868; border-radius:4px;
  width:16px; height:16px; line-height:14px; text-align:center; }
.page { display: none; height: 100vh; width: 100vw; flex-direction: column; }
.page.active { display: flex; }
/* NOTA: no vuelvas a poner style="display:..." inline en ninguna .page —
   un display inline gana a .page/.page.active por especificidad de cascada
   y la página queda "pegada" visible aunque se le quite la clase active. */
#pg-lang { align-items: center; justify-content: center; height: 100%; gap: 0; }

/* ── SCROLLBAR ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--tn-border); border-radius: 3px; }

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 1: WELCOME
══════════════════════════════════════════════════════════════════════════ */
#pg-welcome {
  background: var(--tn-bg2);
  align-items: center; justify-content: center; gap: 28px;
}
.welcome-logo {
  font-family: var(--font-mono);
  color: var(--tn-blue); font-size: 11px; line-height: 1.25;
  text-align: center;
  text-shadow: 0 0 20px rgba(122,162,247,.4);
}
.welcome-sub {
  color: var(--tn-dim); font-family: var(--font-mono);
  font-size: 10px; letter-spacing: 3px; text-transform: uppercase;
  text-align: center; margin-top: -12px;
}
.welcome-desc {
  color: var(--tn-text); font-family: var(--font-ui);
  font-size: 14px; line-height: 1.7; text-align: center; max-width: 460px;
}
.welcome-desc strong { color: var(--tn-blue); }
.btn-primary {
  background: rgba(122,162,247,.12); border: 1px solid var(--tn-blue);
  color: var(--tn-blue); font-family: var(--font-ui); font-size: 13px;
  font-weight: 600; letter-spacing: 1px; padding: 11px 32px;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans);
}
.btn-primary:hover {
  background: rgba(122,162,247,.22);
  box-shadow: 0 0 16px rgba(122,162,247,.3);
}
.welcome-badges {
  display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;
}
.badge {
  font-family: var(--font-mono); font-size: 10px; padding: 3px 10px;
  border-radius: 20px; letter-spacing: .5px;
  border: 1px solid; opacity: .75;
}
.badge-blue   { color: var(--tn-blue);   border-color: var(--tn-blue); }
.badge-green  { color: var(--tn-green);  border-color: var(--tn-green); }
.badge-purple { color: var(--tn-purple); border-color: var(--tn-purple); }
.badge-cyan   { color: var(--tn-cyan);   border-color: var(--tn-cyan); }
/* Badges de snapshots en los botones de bootloader */
.badge-snap {
  font-size: 9px; padding: 2px 7px; border-radius: 20px;
  background: rgba(158,206,106,.15); color: #9ece6a;
  border: 1px solid rgba(158,206,106,.4);
  font-weight: 500; vertical-align: middle; margin-left: 5px;
}
.badge-warn {
  font-size: 9px; padding: 2px 7px; border-radius: 20px;
  background: rgba(224,175,104,.12); color: #e0af68;
  border: 1px solid rgba(224,175,104,.4);
  font-weight: 500; vertical-align: middle; margin-left: 5px;
}

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 2: CONFIG (disk + form)
══════════════════════════════════════════════════════════════════════════ */
#pg-config { background: var(--tn-bg); }

.cfg-topbar {
  height: 40px; background: var(--tn-bg2); border-bottom: 1px solid var(--tn-border);
  display: flex; align-items: center; padding: 0 16px; gap: 10px; flex-shrink: 0;
}
.cfg-topbar-title { color: var(--tn-blue); font-family: var(--font-mono); font-size: 12px; font-weight: 700; }
.cfg-topbar-step  { color: var(--tn-dim); font-size: 11px; margin-left: auto; }

.cfg-body { display: flex; flex: 1; overflow: hidden; }

/* Left: disk list */
.cfg-left {
  width: 330px; min-width: 280px; border-right: 1px solid var(--tn-border);
  display: flex; flex-direction: column; overflow: hidden;
}
.cfg-section-title {
  padding: 10px 14px 8px; border-bottom: 1px solid var(--tn-border); flex-shrink: 0;
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  text-transform: uppercase; color: var(--tn-dim);
}
#disk-list {
  flex: 1; overflow-y: auto; padding: 8px;
}
/* ── Comprobación previa del equipo (pantalla de bienvenida) ── */
.pf-panel {
  width: min(780px, 92vw); margin: 2px 0 4px; padding: 8px 14px 10px; text-align: left;
  font-family: var(--font-ui);
  background: var(--tn-surface); border: 1px solid var(--tn-border); border-radius: var(--r);
}
.pf-head {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;
  font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--tn-dim);
}
.pf-retry {
  font-family: var(--font-ui);
  background: transparent; border: 1px solid var(--tn-border); color: var(--tn-blue);
  border-radius: var(--r-sm); padding: 2px 10px; font-size: 12px; cursor: pointer;
}
.pf-retry:hover { border-color: var(--tn-blue); }
.pf-list { list-style: none; margin: 0; padding: 0; max-height: 200px; overflow-y: auto; }
.pf-row { display: flex; gap: 10px; align-items: baseline; padding: 2px 0; font-size: 12.5px; line-height: 1.35; }
.pf-ic { width: 16px; flex: none; text-align: center; }
.pf-l { width: 92px; flex: none; color: var(--tn-dim); }
.pf-d { flex: 1; min-width: 0; color: var(--tn-text); word-break: break-word; }
.pf-h { display: block; margin-top: 1px; font-size: 11.5px; color: var(--tn-yellow); }
.pf-ok .pf-ic { color: var(--tn-green); }
.pf-warn .pf-ic { color: var(--tn-yellow); }
.pf-fail .pf-ic { color: var(--tn-red); }
.pf-info .pf-ic { color: var(--tn-cyan); }
.pf-fail .pf-d { color: var(--tn-red); }
.pf-fail .pf-h { color: var(--tn-orange); }
.pf-note { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--tn-border); font-size: 12px; min-height: 16px; }
.pf-note-ok { color: var(--tn-green); }
.pf-note-warn { color: var(--tn-yellow); }
.pf-note-fail { color: var(--tn-red); }
.pf-note-run { color: var(--tn-dim); animation: pf-pulse 1.2s ease-in-out infinite; }
@keyframes pf-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
.btn-primary:disabled { opacity: .4; cursor: not-allowed; box-shadow: none; }
.btn-primary:disabled:hover { background: rgba(122,162,247,.12); box-shadow: none; }
.pf-anyway {
  background: transparent; border: none; color: var(--tn-dim); text-decoration: underline;
  cursor: pointer; font-size: 12px; margin-top: 6px; font-family: var(--font-ui);
}
.pf-anyway:hover { color: var(--tn-text); }
.pf-hidden { display: none; }
/* La bienvenida ahora incluye la comprobación del equipo: en pantallas bajas se compacta y, si
   aun así no cabe, se DESPLAZA en vez de cortar el botón. ::before/::after con margin:auto
   centran el contenido cuando sobra espacio y se anulan cuando falta (justify-content:center,
   en cambio, corta arriba y abajo lo que no entra y ese contenido queda inalcanzable). */
#pg-welcome { justify-content: flex-start; overflow-y: auto; }
#pg-welcome::before, #pg-welcome::after { content: ""; margin: auto; }
/* El logo lleva width/height/margin en línea (110px, -8px): hace falta !important para achicarlo. */
@media (max-height: 780px) {
  #pg-welcome { gap: 14px; } .pf-list { max-height: 190px; }
  #pg-welcome #avalos-logo { width: 88px !important; height: 88px !important; margin-bottom: 0 !important; }
}
@media (max-height: 660px) {
  #pg-welcome { gap: 8px; } .pf-list { max-height: 120px; } .welcome-sub { display: none; }
  #pg-welcome #avalos-logo { width: 64px !important; height: 64px !important; }
}
.disk-card {
  background: var(--tn-surface); border: 1px solid var(--tn-border);
  border-radius: var(--r-sm); padding: 9px 11px; margin-bottom: 6px;
  cursor: pointer; transition: border-color var(--trans);
}
.disk-card:hover { border-color: rgba(122,162,247,.5); }
.disk-card.selected {
  border-color: var(--tn-blue);
  box-shadow: 0 0 0 1px rgba(122,162,247,.2) inset;
}
.disk-card.boot-disk { opacity: .45; cursor: not-allowed; border-color: #2d2f44; }
.disk-name { color: var(--tn-blue); font-family: var(--font-mono); font-size: 13px; font-weight: 700; }
.disk-meta { color: var(--tn-dim); font-family: var(--font-mono); font-size: 10.5px; margin-top: 3px; line-height: 1.6; }
.disk-size { color: var(--tn-cyan); }
.dtag {
  display: inline-block; font-size: 9px; padding: 1px 5px;
  border-radius: 3px; letter-spacing: .4px; text-transform: uppercase;
  margin-left: 5px; vertical-align: middle; font-family: var(--font-mono);
}
.dtag-ssd  { background: #001829; color: var(--tn-cyan);   border: 1px solid #00304a; }
.dtag-hdd  { background: #1c1a00; color: var(--tn-yellow); border: 1px solid #3a3500; }
.dtag-boot { background: #1c1000; color: var(--tn-orange); border: 1px solid #3a2000; }
.dtag-sel  { background: rgba(122,162,247,.1); color: var(--tn-blue); border: 1px solid rgba(122,162,247,.3); }
.disk-warn { font-size: 10px; color: var(--tn-orange); margin-top: 3px; }

/* Right: form */
.cfg-right { flex: 1; overflow-y: auto; padding: 20px 24px; }
.cfg-form-wrap { max-width: 500px; margin: 0 auto; }

.form-section-title {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  text-transform: uppercase; color: var(--tn-dim);
  margin-bottom: 14px; margin-top: 4px;
}

.form-row { display: flex; gap: 12px; }
.form-row .form-group { flex: 1; }

.form-group { margin-bottom: 14px; }
.form-group label {
  display: block; font-size: 11px; color: var(--tn-white);
  margin-bottom: 5px; font-weight: 500;
}
.form-group input,
.form-group select {
  width: 100%; padding: 8px 10px;
  background: var(--tn-surface); border: 1px solid var(--tn-border);
  border-radius: var(--r-sm); color: var(--tn-text);
  font-family: var(--font-mono); font-size: 12px;
  outline: none; transition: border-color var(--trans);
}
.form-group input:focus,
.form-group select:focus { border-color: var(--tn-blue); }
.form-group input.error  { border-color: var(--tn-red); }
.form-group input.ok     { border-color: var(--tn-green); }
.field-hint { font-size: 10px; color: var(--tn-dim); margin-top: 3px; display: block; }
.field-hint.err  { color: var(--tn-red); }
.field-hint.good { color: var(--tn-green); }

/* ── PASSWORD STRENGTH ──────────────────────────────────────────────── */
.pass-wrap { position: relative; }
.pass-wrap input { padding-right: 32px; }
.pass-toggle {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: var(--tn-dim); cursor: pointer;
  font-size: 13px; padding: 0; line-height: 1;
  transition: color var(--trans);
}
.pass-toggle:hover { color: var(--tn-text); }

.strength-bar-wrap {
  height: 3px; background: var(--tn-border); border-radius: 2px;
  margin-top: 5px; overflow: hidden;
}
.strength-bar {
  height: 100%; width: 0%; border-radius: 2px;
  transition: width 0.25s ease, background 0.25s ease;
}
.strength-bar.s0 { width: 0%; }
.strength-bar.s1 { width: 25%; background: var(--tn-red); }
.strength-bar.s2 { width: 50%; background: var(--tn-orange); }
.strength-bar.s3 { width: 75%; background: var(--tn-yellow); }
.strength-bar.s4 { width: 100%; background: var(--tn-green); }

.strength-reqs {
  display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 5px;
}
.req {
  font-family: var(--font-mono); font-size: 9.5px; color: var(--tn-dim);
  transition: color var(--trans);
}
.req.ok { color: var(--tn-green); }

.opts-row { display: flex; gap: 8px; }
.opt-btn {
  flex: 1; padding: 8px 10px; font-family: var(--font-mono); font-size: 11px;
  border-radius: var(--r-sm); cursor: pointer; transition: all var(--trans);
  border: 1px solid var(--tn-border); background: var(--tn-surface);
  color: var(--tn-dim); text-align: left; line-height: 1.4;
}
.opt-btn .opt-title { font-weight: 700; color: var(--tn-text); display: block; }
.opt-btn .opt-desc  { font-size: 9.5px; color: var(--tn-dim); }
.opt-btn.sel {
  border-color: var(--tn-blue); background: rgba(122,162,247,.1); color: var(--tn-blue);
}
.opt-btn.sel .opt-title { color: var(--tn-blue); }
.opt-btn.sel .opt-desc  { color: rgba(122,162,247,.6); }
.opt-btn:hover:not(.sel) { border-color: var(--tn-dim); }

.divider { border: none; border-top: 1px solid var(--tn-border); margin: 18px 0; }

#btn-instalar {
  width: 100%; padding: 12px 0; margin-top: 6px;
  font-family: var(--font-ui); font-size: 13px; font-weight: 700;
  letter-spacing: 1px; border-radius: var(--r); cursor: pointer;
  transition: all var(--trans);
  background: rgba(158,206,106,.12); border: 1px solid var(--tn-green);
  color: var(--tn-green); text-shadow: 0 0 8px rgba(158,206,106,.3);
}
#btn-instalar:hover {
  background: rgba(158,206,106,.22);
  box-shadow: 0 0 16px rgba(158,206,106,.25);
}
#btn-instalar:disabled { opacity: .35; cursor: not-allowed; }

#form-error {
  display: none; color: var(--tn-red); font-size: 11px;
  margin-top: 8px; text-align: center; padding: 6px;
  background: rgba(247,118,142,.08); border-radius: var(--r-sm);
  border: 1px solid rgba(247,118,142,.2);
}

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 3: INSTALL  (phosphor terminal)
══════════════════════════════════════════════════════════════════════════ */
#pg-install {
  background: var(--ph-bg);
  font-family: var(--font-mono);
}
.blink { animation: blink 1.1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

#topbar {
  height: 38px; background: var(--ph-surface);
  border-bottom: 1px solid var(--ph-border);
  display: flex; align-items: center; padding: 0 12px; gap: 10px; flex-shrink: 0;
}
#topbar-title { color: var(--ph-green); font-size: 12px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  text-shadow: 0 0 8px rgba(0,255,65,.5); display: flex; align-items: center; gap: 8px; }
#status-label { font-size: 10px; color: var(--ph-dim); margin-left: 4px; letter-spacing: .5px; }
#topbar-right  { margin-left: auto; display: flex; gap: 8px; align-items: center; }
#internet-badge, #uefi-badge {
  font-size: 10px; padding: 2px 7px; border-radius: 2px;
  letter-spacing: .5px; border: 1px solid var(--ph-border);
  font-family: var(--font-mono);
}
.badge-ok  { color: var(--ph-green); border-color: var(--ph-lo) !important; }
.badge-err { color: var(--ph-red);   border-color: #3d0000 !important; }
.badge-warn{ color: var(--ph-yellow);border-color: #3d3000 !important; }

#inst-layout { display: flex; flex: 1; overflow: hidden; }

#inst-left {
  width: 290px; min-width: 250px; display: flex; flex-direction: column;
  border-right: 1px solid var(--ph-border); overflow: hidden;
}
.ph-section {
  font-size: 10px; letter-spacing: 1.2px; color: var(--ph-dim);
  text-transform: uppercase; padding: 8px 12px 6px;
  border-bottom: 1px solid var(--ph-border); flex-shrink: 0;
}
#info-panel { flex: 0 0 auto; padding: 7px 12px; border-bottom: 1px solid var(--ph-border); }
.info-row { display: flex; gap: 6px; font-size: 10.5px; margin-bottom: 2px; }
.info-key { color: var(--ph-dim); width: 80px; flex-shrink: 0; text-align: right; }
.info-val { color: var(--ph-text); }
.info-val.ok   { color: var(--ph-green); }
.info-val.err  { color: var(--ph-red); }
.info-val.warn { color: var(--ph-yellow); }

#steps-panel { flex: 1; overflow-y: auto; padding: 6px 10px; }
.step { display: flex; align-items: flex-start; gap: 8px; padding: 4px 0; border-bottom: 1px solid rgba(10,42,10,.3); }
.step:last-child { border-bottom: none; }
.step-icon  { width: 14px; flex-shrink: 0; font-size: 11px; }
.step-label { font-size: 11px; color: var(--ph-dim); line-height: 1.4; }
.step-detail{ font-size: 9.5px; color: var(--ph-dim); opacity: .7; margin-top: 1px; }
.step.done   .step-icon, .step.done   .step-label { color: var(--ph-green); }
.step.active .step-icon  { color: var(--ph-yellow); animation: blink .7s step-end infinite; }
.step.active .step-label { color: var(--ph-yellow); }
.step.error  .step-icon, .step.error  .step-label { color: var(--ph-red); }
.step.skip   .step-label { color: var(--ph-dim); text-decoration: line-through; }

#btn-area { flex-shrink: 0; padding: 8px 10px; border-top: 1px solid var(--ph-border); display: flex; gap: 6px; }
.action-btn {
  flex: 1; padding: 6px 0; font-family: var(--font-mono); font-size: 11px;
  letter-spacing: .8px; text-transform: uppercase; border-radius: 3px; cursor: pointer;
  transition: all var(--trans);
}
#btn-abort {
  background: #1a0000; border: 1px solid #5a0000; color: var(--ph-red);
}
#btn-abort:hover:not(:disabled) { background: #2d0000; }
#btn-abort:disabled { opacity: .3; cursor: not-allowed; }
#btn-retry {
  background: var(--ph-lo); border: 1px solid #1a6a1a; color: var(--ph-green); display: none;
}
#btn-retry:hover { background: rgba(0,255,65,.08); }

#inst-right { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#log-header {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px 6px;
  border-bottom: 1px solid var(--ph-border); flex-shrink: 0;
}
#log-title      { font-size: 10px; letter-spacing: 1.2px; color: var(--ph-dim); text-transform: uppercase; }
#log-lines-count{ font-size: 10px; color: var(--ph-dim); margin-left: auto; }
#log-wrap       { flex: 1; overflow-y: auto; padding: 8px 12px; }
#log { font-size: 11.5px; line-height: 1.65; white-space: pre-wrap; word-break: break-all; }
.log-cmd  { color: var(--ph-cyan); }
.log-ok   { color: var(--ph-green); }
.log-err  { color: var(--ph-red); }
.log-warn { color: var(--ph-yellow); }
.log-info { color: rgba(184,255,184,.55); }
.log-step { color: var(--ph-orange); font-weight: 700; }

#statusbar {
  height: 22px; background: var(--ph-surface); border-top: 1px solid var(--ph-border);
  display: flex; align-items: center; padding: 0 12px;
  font-size: 10.5px; color: var(--ph-dim); gap: 12px; flex-shrink: 0;
}
#statusbar-time { margin-left: auto; }
#progress-bar-wrap { position: absolute; bottom: 22px; left: 290px; right: 0; height: 2px; }
#progress-bar {
  height: 2px; background: var(--ph-green);
  width: 0%; transition: width .5s ease;
  box-shadow: 0 0 6px rgba(0,255,65,.6);
}

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: COUNTDOWN
══════════════════════════════════════════════════════════════════════════ */
.overlay {
  display: none; position: fixed; inset: 0; z-index: 900;
  background: rgba(0,0,0,.82);
  align-items: center; justify-content: center;
}
.overlay.show { display: flex; }
#ov-countdown .box {
  background: #1a0000; border: 2px solid var(--ph-red);
  border-radius: 8px; padding: 28px 36px; max-width: 460px;
  text-align: center; box-shadow: 0 0 40px rgba(255,60,60,.3);
  font-family: var(--font-mono);
}
#cd-title   { color: var(--ph-red); font-size: 15px; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 12px; }
#cd-body    { color: var(--ph-text); font-size: 12px; line-height: 1.8; margin-bottom: 14px; }
#cd-num     { color: var(--ph-red); font-size: 42px; font-weight: 700; letter-spacing: 2px; }
#cd-hint    { color: var(--ph-dim); font-size: 10.5px; margin-top: 8px; }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: ELEGIR MIRROR
══════════════════════════════════════════════════════════════════════════ */
#ov-mirror .box {
  background: var(--tn-surface); border: 1px solid var(--tn-yellow);
  border-radius: 8px; padding: 28px 36px; max-width: 520px; text-align: center;
  box-shadow: 0 0 40px rgba(224,175,104,.2); font-family: var(--font-ui);
}
#mirror-title   { color: var(--tn-yellow); font-size: 16px; font-weight: 700; letter-spacing: 1px; margin-bottom: 12px; }
#mirror-body    { color: var(--tn-text); font-size: 12px; line-height: 1.7; margin-bottom: 10px; }
#mirror-detalle { color: var(--tn-dim); font-size: 10.5px; font-family: var(--font-mono); line-height: 1.6; margin-bottom: 18px; word-break: break-word; }
.mirror-btns    { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.mirror-btns button {
  font-family: var(--font-mono); font-size: 10.5px; letter-spacing: .5px;
  border-radius: 6px; padding: 10px 14px; cursor: pointer; transition: .15s;
}
#btn-mirror-aceptar {
  background: rgba(158,206,106,.1); border: 1px solid var(--tn-green); color: var(--tn-green);
}
#btn-mirror-aceptar:hover { background: rgba(158,206,106,.2); }
#btn-mirror-rechazar {
  background: rgba(122,162,247,.1); border: 1px solid var(--tn-blue); color: var(--tn-blue);
}
#btn-mirror-rechazar:hover { background: rgba(122,162,247,.2); }
#btn-mirror-reintentar {
  background: rgba(224,175,104,.1); border: 1px solid var(--tn-yellow); color: var(--tn-yellow);
}
#btn-mirror-reintentar:hover { background: rgba(224,175,104,.2); }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: ERROR FATAL
══════════════════════════════════════════════════════════════════════════ */
#ov-error .box {
  background: var(--tn-surface); border: 1px solid var(--tn-red);
  border-radius: 8px; padding: 28px 36px; max-width: 480px; text-align: center;
  box-shadow: 0 0 40px rgba(247,118,142,.2); font-family: var(--font-ui);
}
#err-title { color: var(--tn-red); font-size: 16px; font-weight: 700; letter-spacing: 1px; margin-bottom: 12px; }
#err-msg   { color: var(--tn-text); font-size: 12px; line-height: 1.7; margin-bottom: 16px; }
#err-hint  { color: var(--tn-dim); font-size: 10.5px; margin-bottom: 16px; font-family: var(--font-mono); }
#btn-err-close {
  background: rgba(247,118,142,.1); border: 1px solid var(--tn-red); color: var(--tn-red);
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px;
  text-transform: uppercase; padding: 7px 20px; border-radius: var(--r-sm);
  cursor: pointer; transition: all var(--trans);
}
#btn-err-close:hover { background: rgba(247,118,142,.2); }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: DONE
══════════════════════════════════════════════════════════════════════════ */
#ov-done .box {
  background: var(--tn-surface); border: 1px solid var(--tn-green);
  border-radius: 12px; padding: 36px 44px; max-width: 520px; text-align: center;
  box-shadow: 0 0 48px rgba(158,206,106,.18); font-family: var(--font-ui);
}
#done-icon  { font-size: 52px; margin-bottom: 12px; }
#done-title { color: var(--tn-green); font-size: 20px; font-weight: 700; margin-bottom: 8px; }
#done-sub   { color: var(--tn-text); font-size: 12.5px; line-height: 1.75; margin-bottom: 8px; }
#done-info  { color: var(--tn-dim); font-size: 10.5px; line-height: 1.7;
  font-family: var(--font-mono); margin-bottom: 20px;
  background: var(--tn-bg2); border-radius: var(--r-sm);
  padding: 10px 14px; text-align: left; }
#done-info strong { color: var(--tn-blue); }
.done-btns { display: flex; gap: 10px; justify-content: center; }
.done-btns button {
  padding: 10px 24px; font-family: var(--font-ui); font-size: 12px; font-weight: 600;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans); letter-spacing: .5px;
}
#btn-reboot {
  background: rgba(158,206,106,.14); border: 1px solid var(--tn-green); color: var(--tn-green);
}
#btn-reboot:hover { background: rgba(158,206,106,.26); }
#btn-view-log {
  background: rgba(122,162,247,.14); border: 1px solid var(--tn-blue); color: var(--tn-blue);
}
#btn-view-log:hover { background: rgba(122,162,247,.26); }
#btn-close-done {
  background: var(--tn-surface); border: 1px solid var(--tn-border); color: var(--tn-dim);
}
#btn-close-done:hover { color: var(--tn-text); border-color: var(--tn-white); }

/* Botón flotante "← Volver" — solo visible mientras se está viendo el log
   después de haber cerrado el overlay de "instalación completada" (ver
   funciones verLog()/volverADone() en el bloque de JavaScript de más
   abajo). display:none es el estado normal; JS le agrega .show cuando
   corresponde. */
#btn-back-to-done {
  display: none; position: fixed; top: 16px; right: 16px; z-index: 50;
  padding: 8px 18px; font-family: var(--font-ui); font-size: 11.5px; font-weight: 600;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans); letter-spacing: .5px;
  background: var(--tn-surface); border: 1px solid var(--tn-green); color: var(--tn-green);
  box-shadow: 0 2px 16px rgba(0,0,0,.35);
}
#btn-back-to-done.show { display: block; }
#btn-back-to-done:hover { background: rgba(158,206,106,.14); }
</style>
<script>
(function () {
  var overlay = null;
  var shown = {};
  function showJsError(msg) {
    if (shown[msg]) return;
    shown[msg] = true;
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'js-error-overlay';
      overlay.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
        'background:#3a0d0d;color:#ff9494;font:11px/1.5 monospace;' +
        'padding:8px 12px;max-height:38vh;overflow:auto;white-space:pre-wrap;' +
        'border-bottom:2px solid #ff5555;';
      (document.body || document.documentElement).appendChild(overlay);
    }
    var line = document.createElement('div');
    line.textContent = msg;
    overlay.appendChild(line);
  }
  window.__showJsError = showJsError;
  window.addEventListener('error', function (e) {
    showJsError('JS ERROR: ' + e.message + '  @' + (e.filename || '?') + ':' + e.lineno + ':' + e.colno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    showJsError('PROMISE REJECTION: ' + (r && r.message ? r.message : String(r)));
  });
})();
</script>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 0 — LANGUAGE SELECTION
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-lang" class="page active">
  <div style="font-size:32px;font-weight:700;color:#c0caf5;letter-spacing:0.04em;
              margin-bottom:6px;">AvalOS</div>
  <div style="font-size:12px;color:#565f89;letter-spacing:0.14em;margin-bottom:40px;">
    INSTALLER · INSTALADOR · 安装程序
  </div>
  <div style="display:flex;flex-direction:column;gap:12px;width:260px;">
    <button data-lang="en" onclick="chooseLang('en')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇺🇸&nbsp; English
      <span class="lang-key-hint">1</span>
    </button>
    <button data-lang="es" onclick="chooseLang('es')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇪🇸&nbsp; Español
      <span class="lang-key-hint">2</span>
    </button>
    <button data-lang="zh" onclick="chooseLang('zh')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇨🇳&nbsp; 中文简体
      <span class="lang-key-hint">3</span>
    </button>
    <button data-lang="ja" onclick="chooseLang('ja')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇯🇵&nbsp; 日本語
      <span class="lang-key-hint">4</span>
    </button>
  </div>
  <div style="font-size:10px;color:#414868;letter-spacing:0.08em;margin-top:16px;">
    1‑4 · ↑↓ + Enter
  </div>
  <div id="lang-warning-box"
    style="margin-top:28px;max-width:340px;text-align:center;padding:10px 14px;
           background:rgba(224,175,104,0.08);border:1px solid rgba(224,175,104,0.25);
           border-radius:8px;">
    <span data-i18n="lang-warning"
      style="font-size:11px;color:#e0af68;line-height:1.6;">
      ⚠  UI language pack only · Mirrors optimized for US, MX &amp; GT
      — may be slow for mainland China or distant regions.
    </span>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 1 — WELCOME
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-welcome" class="page">
  <img id="avalos-logo" alt="AvalOS" src="data:image/png;base64,LOGO_PLACEHOLDER"
       style="width:110px;height:110px;object-fit:contain;margin-bottom:-8px;
              border-radius:16px;box-shadow:0 0 18px 4px rgba(122,162,247,.35);">
  <pre class="welcome-logo" style="display:none;">
     _             _  ___  ____
    / \__   ____ _| |/ _ \/ ___|
   / _ \ \ / / _` | | | | \___ \
  / ___ \ V / (_| | | |_| |___) |
 /_/   \_\_/ \__,_|_|\___/|____/</pre>
  <div class="welcome-sub" data-i18n="welcome-sub">Arch Linux · Hyprland · Wayland · Tokyo Night</div>
  <div class="welcome-desc">
    <span data-i18n="welcome-desc">Bienvenido al instalador de <strong>AvalOS</strong>.<br>Este asistente configurará e instalará el sistema en el disco de tu elección.</span>
  </div>
  <div class="welcome-badges">
    <span class="badge badge-blue">Arch Linux (rolling)</span>
    <span class="badge badge-purple">Hyprland</span>
    <span class="badge badge-green">Wayland</span>
    <span class="badge badge-cyan">Tokyo Night</span>
    <span class="badge badge-blue">SDDM · PipeWire · AMD GPU</span>
  </div>
  <div id="pf-panel" class="pf-panel">
    <div class="pf-head">
      <span data-i18n="pf-title">Comprobación del equipo</span>
      <button id="pf-retry" class="pf-retry" onclick="runPreflight()" data-i18n="pf-retry">↻ Reintentar</button>
    </div>
    <ul id="pf-list" class="pf-list"></ul>
    <div id="pf-note" class="pf-note"></div>
  </div>
  <button id="btn-start" class="btn-primary" onclick="showPage('config')" data-i18n="btn-start">Comenzar instalación →</button>
  <button id="btn-start-anyway" class="pf-anyway pf-hidden" onclick="showPage('config')" data-i18n="pf-anyway">Continuar de todos modos</button>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 2 — CONFIG  (disco + formulario)
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-config" class="page">
  <div class="cfg-topbar">
    <span class="cfg-topbar-title" data-i18n="topbar">● AvalOS Installer</span>
    <span id="cfg-step-hint" class="cfg-topbar-step" data-i18n="step-hint">Selecciona disco y configura el sistema</span>
  </div>
  <div class="cfg-body">

    <!-- LEFT: discos -->
    <div class="cfg-left">
      <div class="cfg-section-title" data-i18n="sec-disk">▸ Disco de destino</div>
      <div id="auto-partition-warning" style="
        font-family:var(--font-mono); font-size:10px; padding:8px 12px;
        background:rgba(247,118,142,.08); border-bottom:1px solid rgba(247,118,142,.25);
        color:var(--tn-red); line-height:1.5; flex-shrink:0;
        display:flex; align-items:center; justify-content:space-between; gap:10px;">
        <span data-i18n="warn-auto-partition">⚠ El particionado automático borra <strong>todo</strong> el disco elegido sin posibilidad de deshacer. Si prefieres controlarlo tú mismo, usa el modo manual.</span>
        <button id="btn-manual-mode" onclick="abrirModoManual()" data-i18n="btn-manual-mode"
          style="flex-shrink:0;padding:6px 12px;font-size:10px;background:#24283b;color:#c0caf5;
                 border:1px solid var(--tn-red);border-radius:6px;cursor:pointer;white-space:nowrap;">
          Modo manual
        </button>
      </div>
      <div id="live-disk-banner" data-i18n="disk-current-unavailable" style="
        font-family:var(--font-mono); font-size:10px; padding:8px 12px;
        background:rgba(224,175,104,.07); border-bottom:1px solid rgba(224,175,104,.2);
        color:var(--tn-yellow); display:none; line-height:1.5; flex-shrink:0;">
        ⚠ El <strong>Disco actual</strong> no está disponible como destino
        porque es el disco donde se ejecuta este live ISO.
      </div>
      <div id="manual-root-picker" style="
        font-family:var(--font-mono); font-size:10px; padding:10px 12px;
        background:rgba(122,162,247,.07); border-bottom:1px solid rgba(122,162,247,.25);
        color:var(--tn-text); display:none; flex-direction:column; gap:6px; flex-shrink:0;">
        <span data-i18n="manual-pick-root-label">Se detectó más de una partición de datos. Elegí cuál usar como root:</span>
        <div style="display:flex; gap:8px; align-items:center;">
          <select id="manual-root-select" style="
            flex:1; padding:6px 8px; background:#1a1b26; color:#c0caf5;
            border:1px solid rgba(122,162,247,.4); border-radius:6px;
            font-family:var(--font-mono); font-size:10px;"></select>
          <button id="btn-confirm-manual-root" onclick="confirmarRootManual()" data-i18n="btn-confirm-root"
            style="flex-shrink:0;padding:6px 12px;font-size:10px;background:#24283b;color:#c0caf5;
                   border:1px solid var(--tn-blue);border-radius:6px;cursor:pointer;white-space:nowrap;">
            Confirmar
          </button>
        </div>
      </div>
      <div id="disk-list">
        <div style="padding:14px;color:var(--tn-dim);font-family:var(--font-mono);font-size:11px;">
          <span data-i18n="disk-detecting-placeholder">Detectando discos…</span>
        </div>
      </div>
    </div>

    <!-- RIGHT: formulario -->
    <div class="cfg-right">
      <div class="cfg-form-wrap">

        <div class="form-section-title" data-i18n="sec-user">▸ Cuenta de usuario</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-user">Nombre de usuario</label>
            <input id="f-user" type="text" placeholder="johndoe"
                   oninput="sanitizeUser(this)" autocomplete="off" spellcheck="false">
            <span class="field-hint" id="hint-user" data-i18n="hint-username">Solo letras minúsculas, números y guiones</span>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-pass">Contraseña</label>
            <div class="pass-wrap">
              <input id="f-pass" type="password" placeholder="••••••••" oninput="checkPass()">
              <button class="pass-toggle" type="button" onclick="togglePass('f-pass','pt-1')" id="pt-1" data-i18n-title="lbl-show-hide" title="Mostrar/ocultar">👁</button>
            </div>
            <div class="strength-bar-wrap"><div class="strength-bar s0" id="strength-bar"></div></div>
            <div class="strength-reqs" id="strength-reqs">
              <span class="req" id="req-len" data-i18n="req-len-x">✗ 8+ caracteres</span>
              <span class="req" id="req-upper" data-i18n="req-upper-x">✗ mayúscula</span>
              <span class="req" id="req-lower" data-i18n="req-lower-x">✗ minúscula</span>
              <span class="req" id="req-num" data-i18n="req-num-x">✗ número</span>
              <span class="req" id="req-sym" data-i18n="req-sym-x">✗ símbolo</span>
            </div>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-confirm-pass">Confirmar contraseña</label>
            <div class="pass-wrap">
              <input id="f-pass2" type="password" placeholder="••••••••" oninput="checkPass()">
              <button class="pass-toggle" type="button" onclick="togglePass('f-pass2','pt-2')" id="pt-2" data-i18n-title="lbl-show-hide" title="Mostrar/ocultar">👁</button>
            </div>
            <span class="field-hint" id="hint-pass"></span>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-host">▸ Nombre del equipo</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-hostname">Hostname</label>
            <input id="f-host" type="text" placeholder="mi-pc"
                   oninput="sanitizeHost(this)" autocomplete="off" spellcheck="false">
            <span class="field-hint">Identificador en la red. Ej: avalos-pc</span>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-timezone">Zona horaria</label>
            <select id="f-tz"></select>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-lang">▸ Idioma y teclado</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-locale">Locale del sistema</label>
            <select id="f-locale"></select>
            <span class="field-hint">Idioma de mensajes, fechas y formatos del sistema</span>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-keymap">Distribución de teclado</label>
            <select id="f-keymap"></select>
            <span class="field-hint" data-i18n="hint-keymap">Mapa de teclas para la consola y sesión</span>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-advanced">▸ Opciones avanzadas</div>

        <div class="form-group">
          <label data-i18n="lbl-bootloader">Bootloader</label>
          <div class="opts-row">
            <button class="opt-btn sel" id="opt-bl-grub" onclick="selBootloader('grub')">
              <span class="opt-title">GRUB <span class="badge-snap" data-i18n="badge-snap-yes">✦ Snapshots</span></span>
              <span class="opt-desc" data-i18n="opt-grub-desc">Universal. BIOS + UEFI, dual-boot. Menú de snapshots Btrfs en el arranque.</span>
            </button>
            <button class="opt-btn" id="opt-bl-sd" onclick="selBootloader('sd-boot')">
              <span class="opt-title">systemd-boot <span class="badge-warn" data-i18n="badge-snap-no">⚠ Sin snapshots en boot</span></span>
              <span class="opt-desc" data-i18n="opt-sdboot-desc">Solo UEFI, rápido. Snapshots disponibles vía terminal, sin menú visual en el arranque.</span>
            </button>
            <button class="opt-btn" id="opt-bl-refind" onclick="selBootloader('refind')">
              <span class="opt-title">rEFInd <span class="badge-warn" data-i18n="badge-snap-no">⚠ Sin snapshots en boot</span></span>
              <span class="opt-desc" data-i18n="opt-refind-desc">Solo UEFI. Detecta kernels automáticamente. Snapshots requieren configuración manual.</span>
            </button>
            <button class="opt-btn" id="opt-bl-none" onclick="selBootloader('none')">
              <span class="opt-title" data-i18n="opt-no-boot">Sin bootloader</span>
              <span class="opt-desc">Omitir. Ya tengo un gestor de arranque instalado.</span>
            </button>
          </div>
        </div>

        <!-- Panel de advertencia snapshots — visible solo con sd-boot o rEFInd -->
        <div id="snap-boot-warning" style="display:none; margin:10px 0 0 0;
             background:rgba(224,175,104,0.10); border:1.5px solid #e0af68;
             border-radius:10px; padding:12px 16px; font-size:12.5px; line-height:1.7;
             color:#e0af68;">
        </div>

        <div class="form-group" style="margin-top:14px;">
          <label data-i18n="lbl-install-type">Tipo de instalación</label>
          <div class="opts-row">
            <button class="opt-btn sel" id="opt-modo-disco" onclick="selModo('disco', true)">
              <span class="opt-title" data-i18n="opt-pc">💾 PC / HDD / SSD</span>
              <span class="opt-desc" data-i18n="opt-pc-desc">Btrfs con subvolúmenes — snapshots automáticos, rollback desde GRUB.</span>
            </button>
            <button class="opt-btn" id="opt-modo-usb" onclick="selModo('usb', true)">
              <span class="opt-title" data-i18n="opt-usb">🔌 USB Persistente</span>
              <span class="opt-desc" data-i18n="opt-usb-desc">ext4 sin journal + noatime — minimiza escrituras en pendrive.</span>
            </button>
          </div>
        </div>

        <!-- ── Opciones adicionales ─────────────────────────────────── -->
        <div class="form-group" style="margin-top:10px;">
          <label data-i18n="lbl-extras">Extras</label>
          <div style="display:flex;flex-direction:column;gap:8px;margin-top:6px;">
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;
                          background:var(--tn-bg2);border:1px solid var(--tn-border);
                          border-radius:8px;padding:9px 12px;">
              <input type="checkbox" id="chk-gaming" onchange="window._installGaming=this.checked"
                     style="width:15px;height:15px;accent-color:var(--tn-blue);flex-shrink:0;">
              <span>
                <span class="opt-title" style="font-size:12.5px;" data-i18n="chk-gaming-title">🎮 Gaming</span>
                <span class="opt-desc" style="display:block;margin-top:2px;" data-i18n="chk-gaming-desc">Steam · Wine · DXVK · VKD3D · GameMode · MangoHUD · Lutris · Proton-GE (~2.5 GB extra)</span>
              </span>
            </label>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;
                          background:var(--tn-bg2);border:1px solid var(--tn-border);
                          border-radius:8px;padding:9px 12px;">
              <input type="checkbox" id="chk-bore" onchange="window._installBore=this.checked"
                     style="width:15px;height:15px;accent-color:var(--tn-blue);flex-shrink:0;">
              <span>
                <span class="opt-title" style="font-size:12.5px;" data-i18n="chk-bore-title">⚡ Scheduler BORE</span>
                <span class="opt-desc" style="display:block;margin-top:2px;" data-i18n="chk-bore-desc">Kernel linux-avalos-bore — mejor respuesta en juegos. Requiere CPU con AVX2 (x86-64-v3+); si no es compatible, se ignora y se usa el kernel estándar.</span>
              </span>
            </label>
          </div>
        </div>

        <button id="btn-instalar" onclick="validarEIniciar()">
          <span data-i18n="btn-install">▶ Instalar AvalOS</span>
        </button>
        <div id="form-error"></div>
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 3 — INSTALLATION LOG
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-install" class="page">
  <div id="topbar">
    <div id="topbar-title">
      <span class="blink">▮</span> AvalOS — Instalador
    </div>
    <span id="status-label">inicializando…</span>
    <div id="topbar-right">
      <span id="internet-badge" class="badge-warn">NET ···</span>
      <span id="uefi-badge" class="badge-warn">···</span>
    </div>
  </div>

  <div id="inst-layout">

    <div id="inst-left">
      <div class="ph-section">▸ Info del sistema</div>
      <div id="info-panel">
        <div class="info-row"><span class="info-key">Disco:</span><span id="iv-dest" class="info-val warn">—</span></div>
        <div class="info-row"><span class="info-key">Arranque:</span><span id="iv-boot" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Microcode:</span><span id="iv-ucode" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Internet:</span><span id="iv-net" class="info-val warn">verif…</span></div>
        <div class="info-row"><span class="info-key">Modo:</span><span id="iv-modo" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Bootloader:</span><span id="iv-grub" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Usuario:</span><span id="iv-user" class="info-val ok">—</span></div>
        <div class="info-row"><span class="info-key">DE/WM:</span><span class="info-val ok">Hyprland · Wayland</span></div>
      </div>
      <div class="ph-section">▸ Progreso</div>
      <div id="steps-panel"></div>
      <div id="btn-area">
        <button class="action-btn" id="btn-abort" onclick="abortar()" data-i18n="btn-abort">⛔ Abortar</button>
        <button class="action-btn" id="btn-retry" onclick="reintentar()" data-i18n="btn-retry">↺ Reintentar</button>
      </div>
    </div>

    <div id="inst-right">
      <div id="log-header">
        <span id="log-title" data-i18n="log-title">▸ Log de instalación</span>
        <span id="log-lines-count">0 líneas</span>
      </div>
      <div id="log-wrap"><pre id="log"></pre></div>
      <div id="progress-bar-wrap"><div id="progress-bar"></div></div>
      <div id="statusbar">
        <span id="statusbar-msg">Esperando inicio…</span>
        <span id="statusbar-time"></span>
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: COUNTDOWN
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-countdown" class="overlay">
  <div class="box">
    <div id="cd-title" data-i18n="cd-title">⚠ ZONA DE NO RETORNO</div>
    <div id="cd-body"><span data-i18n="cd-about-to-erase">A punto de borrar</span> <span id="cd-dev" style="color:var(--ph-red);font-weight:700;"></span><br>
    <span id="cd-info" style="color:var(--ph-yellow);"></span><br>
    <span data-i18n="cd-data-permanent">Todos los datos serán eliminados permanentemente.</span></div>
    <div id="cd-num">10</div>
    <div id="cd-hint"><span data-i18n="cd-press">Pulsa</span> <kbd data-i18n="btn-abort" style="color:var(--ph-cyan);">⛔ Abortar</kbd> <span data-i18n="cd-to-cancel">para cancelar</span></div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: ELEGIR MIRROR (preflight de paquetes fallo tras reintentos)
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-mirror" class="overlay">
  <div class="box">
    <div id="mirror-title" data-i18n="mirror-title">⚠ Problema con el mirror de paquetes</div>
    <div id="mirror-body" data-i18n="mirror-body">Algunos paquetes no se pudieron resolver tras varios intentos — probablemente el mirror actual está atrasado o incompleto, no que el paquete no exista.</div>
    <div id="mirror-detalle"></div>
    <div class="mirror-btns">
      <button id="btn-mirror-aceptar" onclick="elegirMirror('aceptar')" data-i18n="btn-mirror-aceptar">Cambiar de mirror</button>
      <button id="btn-mirror-rechazar" onclick="elegirMirror('rechazar')" data-i18n="btn-mirror-rechazar">Lo hago yo</button>
      <button id="btn-mirror-reintentar" onclick="elegirMirror('reintentar')" data-i18n="btn-mirror-reintentar">Reintentar igual</button>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: ERROR FATAL
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-error" class="overlay">
  <div class="box">
    <div id="err-title" data-i18n="err-title">⛔ Error crítico</div>
    <div id="err-msg"></div>
    <div id="err-hint">Cierra esta ventana o presiona <kbd>Ctrl+C</kbd> en terminal</div>
    <button id="btn-err-close" onclick="window.pywebview.api.close()" data-i18n="btn-close">Cerrar</button>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: DONE (instalación completada)
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-done" class="overlay">
  <div class="box">
    <div id="done-icon">✓</div>
    <div id="done-title" data-i18n="done-title">AvalOS instalado correctamente</div>
    <div id="done-sub" data-i18n="done-desc">Retira el USB y reinicia el equipo.<br>
      SDDM te pedirá iniciar sesión → selecciona <strong>Hyprland</strong>.</div>
    <div id="done-info"></div>
    <div class="done-btns">
      <button id="btn-reboot" onclick="window.pywebview.api.reboot_system()" data-i18n="btn-reboot">⟳ Reiniciar ahora</button>
      <button id="btn-view-log" onclick="verLog()" data-i18n="btn-view-log">📋 Ver log</button>
      <button id="btn-close-done" onclick="window.pywebview.api.close()" data-i18n="btn-close">Cerrar</button>
    </div>
  </div>
</div>

<!-- Botón flotante para volver a la pantalla de "instalación completada"
     después de haber elegido "Ver log" — normalmente oculto (ver CSS). -->
<button id="btn-back-to-done" onclick="volverADone()" data-i18n="btn-back-to-done">← Volver</button>

<script>
'use strict';

// ══════════════════════════════════════════════════════════════════
//  INTERNACIONALIZACIÓN (i18n)
//  STRINGS se inyecta en runtime desde translations.TRANSLATIONS
//  (ver _build_html). Para añadir/editar un idioma o clave, editar
//  translations.py — es la única fuente de verdad para los textos
//  del wizard y de fastfetch.
// ══════════════════════════════════════════════════════════════════
const STRINGS = STRINGS_PLACEHOLDER;

let _lang = 'en';

// MOVIDO: PASOS vivía como `const` mucho más abajo (sección INSTALL PAGE).
// applyLang() lo lee vía "typeof PASOS" y se llama desde chooseLang() —
// osea, en CADA click/tecla de idioma. Cualquier excepción sin capturar
// entre el inicio del script y la línea vieja de PASOS (ej. alguna de las
// IIFEs initTZ/initLocale/initKeymap tirando por lo que sea en el entorno
// real) dejaba PASOS atascado en su temporal dead zone para siempre. A
// partir de ahí, TODO click o tecla repetía el mismo ReferenceError
// "Cannot access 'PASOS' before initialization" a medio camino de
// chooseLang() — antes de llegar a showPage() — y visualmente parecía que
// el click "no hacía nada". Declarándolo aquí arriba, antes de cualquier
// IIFE que pueda fallar, se lo saca por completo de esa cadena de fallos.
const PASOS = [
  { id:'uefi',     label:'Detectando modo de arranque',        detail:'UEFI / BIOS Legacy' },
  { id:'net',      label:'Verificando conexión a internet',    detail:'Requerida para pacstrap' },
  { id:'tools',    label:'Verificando herramientas',           detail:'parted, mkfs, pacstrap…' },
  { id:'part',     label:'Particionando disco destino',        detail:'' },
  { id:'format',   label:'Formateando particiones',            detail:'FAT32 (EFI) + Btrfs (root)' },
  { id:'mount',    label:'Montando sistema de archivos',       detail:'' },
  { id:'mirrors',  label:'Optimizando mirrors con reflector',  detail:'Seleccionando mirrors más rápidos' },
  { id:'pacstrap', label:'Instalando sistema base',            detail:'pacstrap — puede tardar varios minutos' },
  { id:'fstab',    label:'Generando fstab',                    detail:'' },
  { id:'config',   label:'Configurando sistema',               detail:'locale · hostname · timezone · initramfs' },
  { id:'grub',     label:'Instalando bootloader',               detail:'' },
  { id:'services', label:'Habilitando servicios',              detail:'NetworkManager · bluetooth · SDDM' },
  { id:'user',     label:'Creando usuario del sistema',        detail:'' },
  { id:'aur',      label:'Instalando paquetes AUR (yay)',      detail:'Proton-GE · Heroic (solo si Gaming activo)' },
  { id:'hypr', label:'Configurando Hyprland + Wayland',    detail:'SDDM · Waybar · hyprland.lua' },
  { id:'umount',   label:'Desmontando y finalizando',          detail:'' },
];

function t(key, params) {
  // BUG-FIX: no usar || para encadenar fallbacks — en JS, "" es falsy, así que
  // (dict[key] || fallback) devolvería 'key' en lugar de "" para las claves
  // step-*-d con detail vacío intencional. Esto corrompía PASOS en applyLang()
  // (s.detail = "step-part-d") y al hacer Retry se renderizaba la clave cruda en la UI.
  // Fix: comprobar explícitamente si la clave existe en el dict antes de recurrir al fallback.
  const dict = STRINGS[_lang] || STRINGS.en;
  let val = (key in dict) ? dict[key] : ((key in STRINGS.en) ? STRINGS.en[key] : key);
  // Sustitución simple de {nombre} -> valor, espejo de self._t(**kwargs) en Python,
  // para los pocos casos donde el texto traducido necesita un valor dinámico
  // (ej. el contador de líneas del log).
  if (params) {
    for (const k in params) val = val.split('{' + k + '}').join(params[k]);
  }
  return val;
}

function applyLang(code) {
  _lang = code;
  // <html lang> tiene que seguir al idioma de la UI. Con lang="es" fijo,
  // WebKit elige la variante regional por defecto de Noto Sans CJK (la JP va
  // primero) y algunos hanzi del chino se dibujan con la forma japonesa.
  // «zh» es chino simplificado (botón «中文简体»).
  document.documentElement.lang = ({ zh: 'zh-CN' })[code] || code;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    if (val) el.innerHTML = val;
  });
  // FIX: algunos elementos no traducen su contenido sino el atributo title
  // (ej. el botón 👁 mostrar/ocultar contraseña) — data-i18n ya cubre
  // innerHTML, pero title necesita su propio paso porque no es contenido visible.
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.dataset.i18nTitle;
    const val = t(key);
    if (val) el.title = val;
  });
  // BUG-i18n FIX: actualizar PASOS array Y nodos del DOM ya renderizados.
  // initSteps() se ejecuta en pywebviewready (antes de seleccionar idioma),
  // por lo que el DOM inicial queda en español. applyLang() actualizaba el
  // array PASOS pero no los elementos step-label / step-detail del DOM,
  // ya que no tienen data-i18n y se renderizan desde PASOS directamente.
  // Fix: también actualizar los nodos del DOM si el paso ya está renderizado.
  if (typeof PASOS !== 'undefined') {
    PASOS.forEach(s => {
      const lbl = t('step-' + s.id);
      const det = t('step-' + s.id + '-d');
      if (lbl !== undefined) s.label = lbl;
      if (det !== undefined) s.detail = det;
      // Actualizar DOM si el step ya está renderizado
      const stepEl = document.getElementById('step-' + s.id);
      if (stepEl) {
        const lblEl = stepEl.querySelector('.step-label');
        const detEl = stepEl.querySelector('.step-detail');
        // BUG-12 FIX: "if (lblEl && lbl)" / "if (detEl && det)" usaban chequeo
        // truthy — el mismo problema que t() ya resuelve explícitamente (una
        // traducción vacía "" es válida y no debe tratarse como "no hay
        // traducción"). Con detail = "" en algún idioma y no vacío en otro,
        // el texto viejo se quedaba pegado en el DOM al cambiar de idioma.
        // Misma condición que ya se usa 2 líneas arriba para s.detail.
        if (lblEl && lbl !== undefined) lblEl.textContent = lbl;
        if (detEl && det !== undefined) detEl.textContent = det;
      }
    });
  }
  document.title = t('title');
  const llc = document.getElementById('log-lines-count');
  if (llc) llc.textContent = t('log-lines-count', { n: logLines });
  // BUG-i18n FIX: las tarjetas de disco (pyRenderDiscos) se arman con
  // innerHTML compuesto por t() en el momento de creación, no con
  // data-i18n — mismo problema estructural que PASOS arriba, mismo tipo
  // de solución: si ya se listaron discos, volver a renderizarlos con el
  // idioma nuevo. pyRenderDiscos() ya preserva cuál estaba seleccionado.
  if (_ultimoDiscosJson) {
    pyRenderDiscos(_ultimoDiscosJson);
  }
  // La comprobación previa guarda claves i18n: se vuelve a dibujar con el idioma nuevo.
  if (_pfResult && !_pfRunning) renderPreflight(_pfResult);
}

function chooseLang(code) {
  applyLang(code);
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_language(code);
  }
  showPage('welcome');
  // Comprobación previa: se corre al llegar a la bienvenida (y de nuevo con "Reintentar").
  // Si ya hubo un resultado bueno solo se vuelve a dibujar (applyLang ya lo hizo).
  if (!_pfResult || _pfResult.blocking || _pfResult.ok === false) runPreflight();
}

// REFUERZO: el keydown se registra ANTES que el delegado de click, a
// propósito — document.addEventListener('keydown', ...) nunca puede fallar
// (document siempre existe), a diferencia de getElementById('pg-lang') de
// abajo. Poniéndolo primero, el atajo de teclado queda registrado pase lo
// que pase con la línea siguiente.
document.addEventListener('keydown', function (e) {
  const pgLang = document.getElementById('pg-lang');
  if (!pgLang || !pgLang.classList.contains('active')) return;

  const langBtns = Array.from(pgLang.querySelectorAll('button[data-lang]'));
  const byKeyNumber = { '1': 'en', '2': 'es', '3': 'zh', '4': 'ja' };

  if (byKeyNumber[e.key]) {
    chooseLang(byKeyNumber[e.key]);
    return;
  }

  if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
    const focused = document.activeElement;
    if (langBtns.includes(focused)) {
      e.preventDefault();
      chooseLang(focused.dataset.lang);
    }
    return;
  }

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const focusedIdx = langBtns.indexOf(document.activeElement);
    const delta = e.key === 'ArrowDown' ? 1 : -1;
    const nextIdx = focusedIdx === -1
      ? 0
      : (focusedIdx + delta + langBtns.length) % langBtns.length;
    langBtns[nextIdx].focus();
  }
});

// REFUERZO: delegado de click sobre el contenedor de idioma. Envuelto en
// try/catch — si getElementById('pg-lang') fallara por lo que sea, no debe
// tumbar el resto del script (el keydown de arriba y todo lo que sigue
// abajo, como las IIFEs de timezone/locale/keymap, deben seguir corriendo).
try {
  document.getElementById('pg-lang').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-lang]');
    if (btn) chooseLang(btn.dataset.lang);
  });
} catch (err) {
  console.error('lang click delegate:', err);
  if (window.__showJsError) window.__showJsError('lang click delegate: ' + err.message);
}

// ══════════════════════════════════════════════════════════════════
//  NAVIGATION
// ══════════════════════════════════════════════════════════════════
// showPage() controla visibilidad SOLO vía la clase 'active' (ver CSS
// .page/.page.active). No asignes el.style.display aquí ni en el HTML de
// ninguna .page — un inline style gana a la cascada y la página queda
// visualmente encima aunque pierda 'active'.
function showPage(name) {
  ['lang','welcome','config','install'].forEach(p => {
    const el = document.getElementById('pg-' + p);
    if (!el) {
      console.error('showPage: no existe #pg-' + p);
      if (window.__showJsError) window.__showJsError('showPage: falta #pg-' + p);
      return;
    }
    el.classList.toggle('active', p === name);
  });
}

// ═════════════════════════════════════════════
//  COMPROBACIÓN PREVIA DEL EQUIPO (hardware/preflight.py)
// ═════════════════════════════════════════════
// Python devuelve CLAVES i18n + parámetros (no texto): acá se traducen con t() en el idioma
// vigente, y el último resultado se guarda para re-renderizarlo si el usuario cambia de
// idioma (applyLang). `var` a propósito: sin zona muerta temporal si applyLang corre antes.
//
// La comprobación es una AYUDA, no un candado: si falla o tarda de más, el botón de
// comenzar queda habilitado; y ante un problema "bloqueante" se ofrece "continuar de todos
// modos" por si fuera un falso positivo (el orquestador igual falla en el paso que
// corresponda si el problema es real).
var _pfResult = null;
var _pfRunning = false;
const PF_ICONS = { ok: '✔', warn: '⚠', fail: '✖', info: 'ℹ' };

function pfSetGate(state) {            // 'running' | 'ok' | 'blocked' | 'error'
  const btn = document.getElementById('btn-start');
  const anyway = document.getElementById('btn-start-anyway');
  if (btn) btn.disabled = (state === 'running' || state === 'blocked');
  if (anyway) anyway.classList.toggle('pf-hidden', state !== 'blocked');
}

function renderPreflight(res) {
  const list = document.getElementById('pf-list');
  const note = document.getElementById('pf-note');
  if (!list || !note || !res) return;
  list.textContent = '';
  // Lo que necesita atención va arriba (fail, warn, info, ok; orden estable): la lista tiene
  // altura acotada y con scroll, y un bloqueo nunca debe quedar escondido abajo.
  const SEV = { fail: 0, warn: 1, info: 2, ok: 3 };
  const ordered = (res.checks || []).map(function (c, i) { return { c: c, i: i }; })
    .sort(function (a, b) { return ((SEV[a.c.status] !== undefined ? SEV[a.c.status] : 2) - (SEV[b.c.status] !== undefined ? SEV[b.c.status] : 2)) || (a.i - b.i); })
    .map(function (x) { return x.c; });
  ordered.forEach(function (c) {
    const li = document.createElement('li');
    li.className = 'pf-row pf-' + c.status;
    const ic = document.createElement('span'); ic.className = 'pf-ic'; ic.textContent = PF_ICONS[c.status] || 'ℹ';
    const lb = document.createElement('span'); lb.className = 'pf-l';  lb.textContent = t(c.label);
    const dt = document.createElement('span'); dt.className = 'pf-d';  dt.textContent = t(c.detail, c.params);
    if (c.hint) {
      const h = document.createElement('span'); h.className = 'pf-h'; h.textContent = t(c.hint, c.params);
      dt.appendChild(h);
    }
    li.appendChild(ic); li.appendChild(lb); li.appendChild(dt);
    list.appendChild(li);
  });
  const key = res.ok === false ? 'pf-failed' : res.blocking ? 'pf-blocked' : res.warnings ? 'pf-warnings' : 'pf-all-ok';
  note.className = 'pf-note ' + (res.blocking ? 'pf-note-fail' : (res.ok === false || res.warnings) ? 'pf-note-warn' : 'pf-note-ok');
  note.textContent = t(key);
}

async function runPreflight() {
  if (_pfRunning) return;
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.run_preflight) { pfSetGate('error'); return; }   // fuera de pywebview: no bloquear
  const list = document.getElementById('pf-list');
  const note = document.getElementById('pf-note');
  _pfRunning = true;
  pfSetGate('running');
  if (list) list.textContent = '';
  if (note) { note.className = 'pf-note pf-note-run'; note.textContent = t('pf-running'); }
  let res;
  try {
    res = await Promise.race([
      api.run_preflight(),
      new Promise(function (_, reject) { setTimeout(function () { reject(new Error('timeout')); }, 45000); }),
    ]);
  } catch (e) {
    res = { ok: false, checks: [], blocking: false, warnings: 0 };
  }
  _pfRunning = false;
  _pfResult = res;
  renderPreflight(res);
  pfSetGate(res.ok === false ? 'error' : res.blocking ? 'blocked' : 'ok');
}

// ══════════════════════════════════════════════════════════════════
//  WIZARD CONFIG STATE
// ══════════════════════════════════════════════════════════════════
let _selDisco = '';
let _bootloader = 'grub';  // 'grub' | 'sd-boot' | 'refind' | 'none'
let _modoUsb  = false;

// populate timezone select
try {
  (function initTZ() {
    const sel = document.getElementById('f-tz');
    window._tzList.forEach(tz => {
      const opt = document.createElement('option');
      opt.value = tz; opt.textContent = tz;
      if (tz === window._defaultTZ) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initTZ:', err);
  if (window.__showJsError) window.__showJsError('initTZ: ' + err.message);
}

// populate locale select
try {
  (function initLocale() {
    const sel = document.getElementById('f-locale');
    window._localeList.forEach(([code, label]) => {
      const opt = document.createElement('option');
      opt.value = code; opt.textContent = label;
      if (code === window._defaultLocale) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initLocale:', err);
  if (window.__showJsError) window.__showJsError('initLocale: ' + err.message);
}

// populate keymap select
try {
  (function initKeymap() {
    const sel = document.getElementById('f-keymap');
    window._keymapList.forEach(([code, label]) => {
      const opt = document.createElement('option');
      opt.value = code; opt.textContent = label;
      if (code === window._defaultKeymap) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initKeymap:', err);
  if (window.__showJsError) window.__showJsError('initKeymap: ' + err.message);
}

// ── Disk selection ────────────────────────────────────────────────
// BUG-i18n: pyRenderDiscos() se invoca UNA sola vez desde Python al
// listar discos (InstallerAPI.on_ready), así que las
// tarjetas de disco (incluyendo tag-disco-actual-live y tag-montado, que
// se inyectan vía t() en el momento de creación) quedaban congeladas en
// el idioma que estaba activo en ese instante. Si el usuario cambiaba de
// idioma DESPUÉS de que la lista ya cargó, las tarjetas nunca se
// actualizaban porque no tienen data-i18n (son innerHTML compuesto, no
// un solo nodo de texto) y applyLang() nunca volvía a llamar a
// pyRenderDiscos(). Fix: cachear el último JSON recibido para poder
// re-renderizar la lista completa desde applyLang() sin pedirle los
// datos de nuevo a Python.
let _ultimoDiscosJson = null;

// Escapa texto antes de meterlo con innerHTML. El modelo/tran de un disco lo reporta el
// propio dispositivo (un USB puede anunciar cualquier cadena) y el instalador corre como
// root con la API de Python expuesta al webview: sin esto, un modelo con markup
// ejecutaria JS con acceso a start_installation()/open_partitioning_terminal().
function esc(s) {
  return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function pyRenderDiscos(discosJson) {
  _ultimoDiscosJson = discosJson;
  const _seleccionPrevia = _selDisco;
  const discos = JSON.parse(discosJson);
  const cont = document.getElementById('disk-list');
  cont.innerHTML = '';
  let autoSel = '';
  discos.forEach(d => {
    const esBoot = d.es_arranque;
    const sizeGb = (d.size_b / 1e9).toFixed(1);
    const bajo   = parseFloat(sizeGb) < 30;
    // FIX: la condición anterior "!d.tran.includes('SATA') && d.tipo === 'SSD/NVMe'"
    // marcaba como 'nvme' a CUALQUIER disco no-rotacional cuyo transporte no fuera
    // SATA (ej. un SSD externo por USB, o un disco virtio en una VM), aunque no
    // fuera NVMe real. Ahora 'nvme' solo se asigna si el transporte es NVMe o el
    // nombre del dispositivo lo indica (ej. "nvme0n1") — igual que detectar_tipo_disco_destino()
    // en el lado Python. Cualquier otro disco no-rotacional cae en 'ssd'.
    const esNvme = d.tran === 'NVME' || d.name.includes('nvme');
    const tipo   = esNvme ? 'nvme' :
                   d.tipo === 'SSD/NVMe' ? 'ssd' : 'hdd';

    if (!esBoot && !autoSel) autoSel = d.name;

    const div = document.createElement('div');
    div.className = 'disk-card' + (esBoot ? ' boot-disk' : '');
    div.id = 'dc-' + d.name;
    div.innerHTML = `
      <div class="disk-name">
        /dev/${esc(d.name)}
        <span class="dtag dtag-${tipo}">${esc(d.tipo)}</span>
        ${esBoot ? `<span class="dtag dtag-boot">${t('tag-disco-actual-live')}</span>` : ''}
      </div>
      <div class="disk-meta">
        <span class="disk-size">${esc(d.size_human)}</span> · ${esc(d.model || t('disk-unknown'))} · ${esc(d.tran)}
        ${d.montajes.length ? ` · <span style="color:var(--tn-orange)">${t('tag-montado')}</span>` : ''}
      </div>
      ${esBoot ? `<div class="disk-warn" style="color:var(--tn-dim);font-style:italic;">${t('disk-unavailable-live')}</div>` : ''}
      ${bajo && !esBoot ? `<div class="disk-warn">${t('disk-low-space', { gb: sizeGb })}</div>` : ''}
    `;
    if (!esBoot) div.onclick = () => selectDisk(d.name);
    cont.appendChild(div);
  });
  // Preservar la selección del usuario si ya había una y sigue existiendo
  // en la nueva lista (ej. re-render por cambio de idioma) — solo caer a
  // auto-selección la primera vez que se lista, cuando no había nada elegido.
  const _sigueExistiendo = _seleccionPrevia && discos.some(d => d.name === _seleccionPrevia);
  if (_sigueExistiendo) {
    selectDisk(_seleccionPrevia);
  } else if (autoSel) {
    selectDisk(autoSel);
  }
  // Show banner only if there's a boot disk in the list
  const hasBoot = discos.some(d => d.es_arranque);
  const banner = document.getElementById('live-disk-banner');
  if (banner) banner.style.display = hasBoot ? 'block' : 'none';
}

function selectDisk(name) {
  _selDisco = name;
  // Auto-suggest USB mode when the selected disk has USB transport
  try {
    const dc = document.getElementById('dc-' + name);
    const meta = dc ? dc.querySelector('.disk-meta') : null;
    const metaTxt = meta ? meta.textContent.toLowerCase() : '';
    // BUG-FIX: name.startsWith('sd') marcaba como USB cualquier disco SATA
    // interno (sda, sdb... también son SATA, no solo USB), activando el modo
    // "USB Persistente" (ext4 sin journal) en instalaciones normales sobre un
    // SSD/HDD SATA interno en lugar del modo PC/Btrfs correcto. metaTxt ya
    // incluye d.tran (el transporte real reportado por lsblk: "usb"/"sata"/
    // "nvme"), que es la señal correcta — sin heurística de nombre de archivo.
    const isUsb = metaTxt.includes('usb');
    // Only auto-switch if user hasn't manually picked
    if (isUsb && !window._modoManuallySet) {
      selModo('usb');
    }
  } catch(e) {}
  document.querySelectorAll('.disk-card').forEach(c => {
    const isSel = c.id === 'dc-' + name;
    c.classList.toggle('selected', isSel);
    // remove/add DESTINO tag
    let tag = c.querySelector('.dtag-sel');
    if (isSel && !tag) {
      tag = document.createElement('span');
      tag.className = 'dtag dtag-sel'; tag.setAttribute('data-i18n', 'tag-destino');
      tag.textContent = t('tag-destino');
      c.querySelector('.disk-name').appendChild(tag);
    } else if (!isSel && tag) {
      tag.remove();
    }
  });
}

// ── Modo manual (particionado a mano en terminal real) ─────────────
// El terminal NO corre dentro del webview (webkit2gtk no tiene uno
// embebido) — Python lanza un emulador real del sistema y bloquea hasta
// que el usuario lo cierra. Por eso este botón se deshabilita mientras
// tanto: evita doble-click y dos terminales superpuestas.
async function abrirModoManual() {
  if (!_selDisco) {
    showFormError(t('val-select-disk'));
    return;
  }
  const btn = document.getElementById('btn-manual-mode');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = t('btn-manual-mode-open');
  document.getElementById('manual-root-picker').style.display = 'none';
  try {
    const abierto = await window.pywebview.api.open_partitioning_terminal();
    if (!abierto) {
      showFormError(t('err-no-terminal-found'));
      return;
    }
    const resultado = await window.pywebview.api.check_manual_partitioning(_selDisco);
    aplicarResultadoParticionadoManual(resultado);
  } catch (e) {
    console.error('abrirModoManual:', e);
    if (window.__showJsError) window.__showJsError('abrirModoManual: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// Separado de abrirModoManual() para poder reusarlo si en el futuro se
// agrega un botón "re-verificar" sin tener que reabrir la terminal.
function aplicarResultadoParticionadoManual(resultado) {
  if (!resultado || !resultado.ok) {
    window._modoManualListo = false;
    showFormError(t('warn-manual-no-partitions'));
    return;
  }

  if (resultado.requiere_seleccion) {
    // Más de una candidata a root — no se puede continuar todavía, el
    // usuario tiene que elegir en el dropdown (confirmarRootManual()).
    window._modoManualListo = false;
    poblarDropdownRootManual(resultado.candidatas_root);
    document.getElementById('manual-root-picker').style.display = 'flex';
    return;
  }

  // Candidata única — Python ya la fijó como root en
  // verificar_particionado_manual(), acá solo reflejamos el estado.
  window._modoManualListo = true;
  document.getElementById('manual-root-picker').style.display = 'none';
  showFormError(t('ok-manual-partition-detected'));
}

function poblarDropdownRootManual(candidatas) {
  const sel = document.getElementById('manual-root-select');
  sel.innerHTML = '';
  candidatas.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = `${c.name} — ${c.size_human} — ${c.fstype}`;
    sel.appendChild(opt);
  });
}

async function confirmarRootManual() {
  const sel = document.getElementById('manual-root-select');
  const elegida = sel.value;
  if (!elegida) return;
  const btn = document.getElementById('btn-confirm-manual-root');
  btn.disabled = true;
  try {
    const ok = await window.pywebview.api.confirm_manual_root(_selDisco, elegida);
    if (ok) {
      window._modoManualListo = true;
      document.getElementById('manual-root-picker').style.display = 'none';
      showFormError(t('ok-manual-partition-detected'));
    } else {
      window._modoManualListo = false;
      showFormError(t('err-manual-invalid-root-choice'));
    }
  } catch (e) {
    console.error('confirmarRootManual:', e);
    if (window.__showJsError) window.__showJsError('confirmarRootManual: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── Form helpers ─────────────────────────────────────────────────
function sanitizeUser(el) {
  el.value = el.value.toLowerCase()
    .replace(/[^a-z0-9_-]/g, '')
    .replace(/^[-]+/, '');  // BUG-008: '-hola' como argumento en useradd puede interpretarse como flag
  const h = document.getElementById('hint-user');
  const startsWithLetter = /^[a-z_]/.test(el.value);
  const validLen = el.value.length >= 2 && el.value.length <= 32;
  const ok = validLen && startsWithLetter;
  let hint = t('val-invalid-user');
  if (el.value) {
    if (!startsWithLetter) hint = t('val-invalid-user');
    else if (!validLen)     hint = t('val-min-user');
    else                    hint = '✓';
  }
  h.className = 'field-hint ' + (el.value ? (ok ? 'good' : 'err') : '');
  h.textContent = hint;
  el.className = el.value ? (ok ? 'ok' : 'error') : '';
}

function sanitizeHost(el) {
  el.value = el.value.toLowerCase().replace(/[^a-z0-9-]/g, '').replace(/^-+/, '');
}

// ── Password toggle (show/hide) ───────────────────────────────────
function togglePass(inputId, btnId) {
  const inp = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  if (inp.type === 'password') {
    inp.type = 'text';
    btn.style.opacity = '1';
    btn.textContent = '🙈';
  } else {
    inp.type = 'password';
    btn.style.opacity = '0.45';
    btn.textContent = '👁';
  }
}

// ── Password strength checker ─────────────────────────────────────
function _passStrength(p) {
  const checks = {
    len:   p.length >= 8,
    upper: /[A-Z]/.test(p),
    lower: /[a-z]/.test(p),
    num:   /[0-9]/.test(p),
    sym:   /[^A-Za-z0-9]/.test(p),
  };
  const score = Object.values(checks).filter(Boolean).length;
  return { checks, score };
}

function checkPass() {
  const p1 = document.getElementById('f-pass').value;
  const p2 = document.getElementById('f-pass2').value;
  const h  = document.getElementById('hint-pass');
  const bar = document.getElementById('strength-bar');

  // -- strength requirements (left field)
  if (p1) {
    const { checks, score } = _passStrength(p1);
    // update req indicators
    const map = { len: 'req-len', upper: 'req-upper', lower: 'req-lower', num: 'req-num', sym: 'req-sym' };
    const labels  = { len: t('req-len-ok'), upper: t('req-upper-ok'), lower: t('req-lower-ok'), num: t('req-num-ok'), sym: t('req-sym-ok') };
    const labelsX = { len: t('req-len-x'),  upper: t('req-upper-x'),  lower: t('req-lower-x'),  num: t('req-num-x'),  sym: t('req-sym-x')  };
    Object.entries(map).forEach(([k, id]) => {
      const el = document.getElementById(id);
      el.className = 'req' + (checks[k] ? ' ok' : '');
      el.textContent = checks[k] ? labels[k] : labelsX[k];
    });
    // update bar
    bar.className = 'strength-bar s' + score;
    // update left input border
    const inp1 = document.getElementById('f-pass');
    inp1.className = score >= 3 ? 'ok' : 'error';
  } else {
    bar.className = 'strength-bar s0';
    ['req-len','req-upper','req-lower','req-num','req-sym'].forEach(id => {
      const el = document.getElementById(id);
      el.className = 'req';
    });
    document.getElementById('f-pass').className = '';
  }

  // -- confirm match (right field)
  if (!p1) { h.textContent = ''; h.className = 'field-hint'; document.getElementById('f-pass2').className = ''; return; }
  if (!p2)  { h.textContent = ''; h.className = 'field-hint'; document.getElementById('f-pass2').className = ''; return; }
  if (p1 === p2) {
    h.textContent = t('val-pass-ok');
    h.className = 'field-hint good';
    document.getElementById('f-pass2').className = 'ok';
  } else {
    h.textContent = t('val-pass-mismatch');
    h.className = 'field-hint err';
    document.getElementById('f-pass2').className = 'error';
  }
}

function selBootloader(val) {
  _bootloader = val;
  const map = {grub:'opt-bl-grub','sd-boot':'opt-bl-sd','refind':'opt-bl-refind','none':'opt-bl-none'};
  Object.entries(map).forEach(([k,id]) => {
    document.getElementById(id).classList.toggle('sel', k === val);
  });

  // ── Advertencia de snapshots para non-GRUB ──────────────────────────────
  const snapWarn = document.getElementById('snap-boot-warning');
  if (snapWarn) {
    if (val === 'sd-boot') {
      snapWarn.style.display = 'block';
      snapWarn.innerHTML = t('warn-sdboot-snaps');
    } else if (val === 'refind') {
      snapWarn.style.display = 'block';
      snapWarn.innerHTML = t('warn-refind-snaps');
    } else {
      snapWarn.style.display = 'none';
    }
  }

  // Advertencia UEFI requerido para sd-boot y rEFInd
  if (val === 'refind' || val === 'sd-boot') {
    const name = val === 'refind' ? 'rEFInd' : 'systemd-boot';
    if (window._esUEFI === false) {
      showFormError('⛔ ' + name + ' ' + t('val-uefi-req'));
    } else if (window._esUEFI === undefined) {
      showFormError('⚠ ' + name + ' ' + t('val-uefi-warn'));
    }
  }
}

function selModo(val, manual) {
  if (manual) window._modoManuallySet = true;
  _modoUsb = (val === 'usb');
  document.getElementById('opt-modo-disco').classList.toggle('sel', !_modoUsb);
  document.getElementById('opt-modo-usb').classList.toggle('sel', _modoUsb);
}

function showFormError(msg) {
  const el = document.getElementById('form-error');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

function validarEIniciar() {
  const user   = document.getElementById('f-user').value.trim();
  const pass   = document.getElementById('f-pass').value;
  const pass2  = document.getElementById('f-pass2').value;
  const host   = document.getElementById('f-host').value.trim() || window._defaultHostname;
  const tz     = document.getElementById('f-tz').value;
  const locale = document.getElementById('f-locale').value;
  const keymap = document.getElementById('f-keymap').value;

  if (!_selDisco)                   return showFormError(t('val-select-disk'));
  if (!user || user.length < 2)     return showFormError(t('val-invalid-user'));
  // Misma regla que ui/api.py (start_installation): si el front deja pasar algo que Python
  // rechaza, el wizard ya estaria en la pantalla de instalacion sin que arranque nada.
  if (!/^[a-z_][a-z0-9_-]{1,31}$/.test(user))
                                    return showFormError(t('val-invalid-user'));
  if (pass.length < 8)              return showFormError(t('val-pass-short'));
  if (_passStrength(pass).score < 2) return showFormError(t('val-pass-weak'));
  if (pass !== pass2)               return showFormError(t('val-pass-mismatch'));
  // Usernames de sistema reservados: build_html() inyecta la lista de core/config.py
  // (RESERVED_USERNAMES), la misma que valida ui/api.py en Python.
  const _RESERVED = window._reservedUsers || [];
  if (_RESERVED.includes(user))
                                    return showFormError(t('val-reserved-user'));

  // Pasar a la página de instalación y avisar a Python
  showPage('install');
  const _gaming = window._installGaming === true;
  const _bore   = window._installBore === true;
  const _manual = window._modoManualListo === true;
  window.pywebview.api.start_installation(user, pass, host, tz, _selDisco, _bootloader, _modoUsb, locale, keymap, _gaming, _bore, _manual)
    .then(function (ok) {
      if (ok === false) {          // Python rechazo la config: volver al formulario, no dejar la pantalla muerta
        showPage('config');
        showFormError(_manual ? t('warn-manual-no-partitions') : t('val-invalid-user'));
      }
    });
}

// ══════════════════════════════════════════════════════════════════
//  INSTALL PAGE
// ══════════════════════════════════════════════════════════════════
let logLines = 0, startTime = null, timerIv = null, abortado = false;

function initSteps() {
  const cont = document.getElementById('steps-panel');
  cont.innerHTML = '';
  PASOS.forEach(p => {
    const d = document.createElement('div');
    d.className = 'step'; d.id = 'step-' + p.id;
    d.innerHTML = `<span class="step-icon">○</span><div>
      <div class="step-label">${p.label}</div>
      ${p.detail ? `<div class="step-detail">${p.detail}</div>` : ''}
    </div>`;
    cont.appendChild(d);
  });
}

function setStep(id, estado, detalle) {
  const el = document.getElementById('step-' + id);
  if (!el) return;
  el.className = 'step ' + estado;
  const icons = { done:'✓', active:'▶', error:'✗', skip:'—' };
  el.querySelector('.step-icon').textContent = icons[estado] || '○';
  if (detalle) {
    let dd = el.querySelector('.step-detail');
    if (!dd) { dd = document.createElement('div'); dd.className = 'step-detail'; el.firstElementChild.appendChild(dd); }
    dd.textContent = detalle;
  }
  if (estado === 'active') el.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function setProgress(pct) {
  document.getElementById('progress-bar').style.width = Math.min(100, pct) + '%';
}

function appendLog(texto, clase) {
  const pre = document.getElementById('log');
  const span = document.createElement('span');
  if (clase) span.className = 'log-' + clase;
  span.textContent = texto + '\n';
  pre.appendChild(span);
  logLines++;
  document.getElementById('log-lines-count').textContent = t('log-lines-count', { n: logLines });
  const wrap = document.getElementById('log-wrap');
  wrap.scrollTop = wrap.scrollHeight;
}

function setInfo(id, val, cls) {
  const el = document.getElementById('iv-' + id);
  if (!el) return;
  el.textContent = val;
  el.className = 'info-val ' + (cls || '');
}

function setStatus(msg) { document.getElementById('statusbar-msg').textContent = msg; }

function startTimer() {
  startTime = Date.now();
  timerIv = setInterval(() => {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    document.getElementById('statusbar-time').textContent =
      (m > 0 ? m + 'm ' : '') + (s % 60) + 's';
  }, 1000);
}
function stopTimer() { if (timerIv) clearInterval(timerIv); }

// ── Buttons ───────────────────────────────────────────────────────
function abortar() {
  if (abortado) return;
  abortado = true;
  document.getElementById('btn-abort').disabled = true;
  appendLog('\n' + t('log-user-aborted'), 'err');
  setStatus(t('status-aborting'));
  window.pywebview.api.abort_installation();
}
function reintentar() {
  document.getElementById('btn-retry').style.display = 'none';
  document.getElementById('btn-abort').disabled = false;
  abortado = false;
  window.pywebview.api.retry();
}

// ══════════════════════════════════════════════════════════════════
//  PYTHON → JS  callbacks
// ══════════════════════════════════════════════════════════════════
function pyLog(texto, clase)     { appendLog(texto, clase || 'info'); }
function pyStep(id, estado, det) { setStep(id, estado, det || ''); }
function pyProgress(pct)         { setProgress(pct); }
function pyInfo(id, val, cls)    { setInfo(id, val, cls || ''); }
function pyStatus(msg)           { setStatus(msg); }
function pyStartTimer()          { startTimer(); }
function pyStopTimer()           { stopTimer(); }
function pyStatusLabel(txt)      { document.getElementById('status-label').textContent = txt; }

function pyBadges(internet, uefi) {
  window._esUEFI = uefi;
  const nb = document.getElementById('internet-badge');
  if (internet === null || internet === undefined) {
    nb.textContent = 'NET ···';
    nb.className   = 'badge-warn';
    setInfo('net', t('badge-checking'), 'warn');
  } else {
    nb.textContent = internet ? 'NET ✓' : t('badge-no-network');
    nb.className   = 'badge-' + (internet ? 'ok' : 'err');
    setInfo('net', internet ? t('step-net-up') : t('step-net-down'), internet ? 'ok' : 'err');
  }
  const ub = document.getElementById('uefi-badge');
  ub.textContent = uefi ? 'UEFI' : 'BIOS';
  setInfo('boot', uefi ? 'UEFI (GPT)' : 'BIOS Legacy (MBR)', 'ok');
}

function pyIniciarCountdown(dev, modelo, size) {
  document.getElementById('cd-dev').textContent = dev;
  document.getElementById('cd-info').textContent = modelo + ' · ' + size;
  const el = document.getElementById('cd-num');
  if (el) el.textContent = 10;
  document.getElementById('ov-countdown').classList.add('show');
  // BUG-009 FIX: el countdown ya no corre de forma independiente con setInterval.
  // Python controla el tiempo real y llama pyActualizarCountdown() en cada tick,
  // garantizando que la acción destructiva no ocurre antes de que el contador llegue a 0.
}

function pyActualizarCountdown(n) {
  const el = document.getElementById('cd-num');
  if (el) el.textContent = n;
}

function pyCerrarCountdown() {
  const ov = document.getElementById('ov-countdown');
  ov.classList.remove('show');
}

function pyInstalacionCompleta(info) {
  stopTimer();
  document.getElementById('btn-abort').disabled = true;
  document.getElementById('status-label').textContent = t('status-label-done');
  setProgress(100);
  setStatus(t('status-complete'));
  // Show done overlay
  if (info) document.getElementById('done-info').innerHTML = info;
  document.getElementById('ov-done').classList.add('show');
}

// "Ver log": esconde el overlay de done (el log siempre estuvo detrás,
// nunca se destruye, ver #log-wrap más arriba) y muestra el botón
// flotante para volver. No llama a close() en ningún momento -- a
// diferencia del botón "Cerrar", esto no termina el proceso.
function verLog() {
  document.getElementById('ov-done').classList.remove('show');
  document.getElementById('btn-back-to-done').classList.add('show');
}

function volverADone() {
  document.getElementById('btn-back-to-done').classList.remove('show');
  document.getElementById('ov-done').classList.add('show');
}


function pyMirrorDialog(detalle) {
  document.getElementById('mirror-detalle').textContent = detalle || '';
  document.getElementById('ov-mirror').classList.add('show');
}

function elegirMirror(choice) {
  document.getElementById('ov-mirror').classList.remove('show');
  window.pywebview.api.choose_mirror(choice);
}

function pyErrorFatal(msg) {
  stopTimer();
  document.getElementById('btn-abort').disabled = true;
  document.getElementById('btn-retry').style.display = 'block';
  document.getElementById('err-msg').textContent = msg;
  document.getElementById('ov-error').classList.add('show');
}

function pyErrorPaso(msg) {
  stopTimer();
  document.getElementById('btn-retry').style.display = 'block';
  appendLog('\n[ERROR] ' + msg, 'err');
  setStatus(t('status-error'));
  document.getElementById('status-label').textContent = t('status-label-error');
}

// ══════════════════════════════════════════════════════════════════
//  READY
// ══════════════════════════════════════════════════════════════════
window.addEventListener('pywebviewready', function() {
  initSteps();
  window.pywebview.api.on_ready();
});
</script>
</body>
</html>
"""

def build_html() -> str:
    """Arma el HTML final del wizard: inyecta el logo (LOGO_PLACEHOLDER),
    las traducciones (STRINGS_PLACEHOLDER) y las listas de timezone/
    locale/keymap + sus defaults como variables globales de JS.

    El punto de inyección de estas últimas es ANTES de 'use strict' (no
    antes del listener de pywebviewready, como estaba en un diseño
    anterior) porque initTZ()/initLocale()/initKeymap() son IIFEs que se
    auto-ejecutan apenas se declaran, mucho antes de pywebviewready, y
    leen exactamente esas variables — con el punto de inyección viejo
    todavía no existían cuando esas IIFEs corrían, lo que rompía en
    silencio los 3 selectores del wizard en los 3 idiomas por igual."""
    tz_json = json.dumps(TIMEZONES, ensure_ascii=False)
    default_tz = json.dumps(DEFAULT_TIMEZONE)
    default_host = json.dumps(DEFAULT_HOSTNAME)
    locales_json = json.dumps(LOCALES, ensure_ascii=False)
    keymaps_json = json.dumps(KEYMAPS, ensure_ascii=False)
    default_loc = json.dumps(DEFAULT_LOCALE)
    default_km = json.dumps(DEFAULT_KEYMAP)
    reserved_json = json.dumps(list(RESERVED_USERNAMES))

    strings_json = json.dumps(translations.TRANSLATIONS, ensure_ascii=False)

    inject = (
        f"window._tzList = {tz_json};\n"
        f"window._defaultTZ = {default_tz};\n"
        f"window._defaultHostname = {default_host};\n"
        f"window._localeList = {locales_json};\n"
        f"window._keymapList = {keymaps_json};\n"
        f"window._defaultLocale = {default_loc};\n"
        f"window._defaultKeymap = {default_km};\n"
        f"window._reservedUsers = {reserved_json};\n"
    )

    content = _HTML.replace("LOGO_PLACEHOLDER", LOGO_B64)
    content = content.replace("STRINGS_PLACEHOLDER", strings_json)
    return content.replace(
        "'use strict';",
        "'use strict';\n" + inject
    )
'''),
}


class _BundleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Sirve los módulos de avalos_installer desde _MODULES, antes que cualquier copia que haya en disco."""

    def __init__(self, modules):
        self._modules = modules

    def find_spec(self, fullname, path=None, target=None):
        entry = self._modules.get(fullname)
        if entry is None:
            return None
        is_pkg, filename, _source = entry
        return importlib.util.spec_from_loader(fullname, self, origin=filename, is_package=is_pkg)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        is_pkg, filename, source = self._modules[module.__spec__.name]
        module.__file__ = filename
        linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)   # tracebacks con su línea
        code = compile(source, filename, "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102  # nosec B102 - código del propio repo, embebido arriba


def _install_finder():
    for finder in sys.meta_path:
        if isinstance(finder, _BundleFinder):
            return finder
    finder = _BundleFinder(_MODULES)
    sys.meta_path.insert(0, finder)
    return finder


def main() -> None:
    _install_finder()
    os.environ.setdefault("AVALOS_INSTALLER_VARIANT", "legado (un solo archivo)")   # lo dice el log del instalador
    from avalos_installer.__main__ import main as run_installer
    run_installer()


if __name__ == "__main__":
    main()
