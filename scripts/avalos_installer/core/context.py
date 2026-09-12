"""
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
