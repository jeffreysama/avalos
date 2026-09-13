"""
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

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.prereqs import TOOL_TO_PACKAGE, check_tools
from avalos_installer.core.session import InstallSession, output_indicates_gpg_error
from avalos_installer.desktop.hyprland import configure_hyprland
from avalos_installer.disk.discovery import MIN_DISK_GB, detect_target_disk_type, list_disks
from avalos_installer.hardware.detection import (
    detect_cpu_arch_level, detect_gpu, detect_microcode, is_uefi,
)
from avalos_installer.network.connectivity import check_internet
from avalos_installer.network.mirrors import optimize_mirrors, sync_time
from avalos_installer.system.aur import install_aur
from avalos_installer.system.bootloader import install_bootloader
from avalos_installer.system.fstab import generate_fstab
from avalos_installer.system.locale import configure_locale
from avalos_installer.system.mount import check_disk_space, mount_filesystems
from avalos_installer.system.optimize import configure_optimizations
from avalos_installer.system.pacstrap import run_pacstrap
from avalos_installer.system.partition import partition_and_format
from avalos_installer.system.repos import configure_repos
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
        if not session._config_ready.wait(timeout=600):
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

    session.info("user", ctx.username, "ok")
    session.info("modo", "USB (ext4 noatime)" if ctx.usb_mode else session.t("info-modo-pc"), "ok")
    session.info(
        "grub",
        _BOOTLOADER_LABELS.get(ctx.bootloader, session.t("info-bootloader-skipped")),
        "ok" if ctx.bootloader != "none" else "warn",
    )

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

        dev_name = ctx.target_disk or disponibles[0]["name"]
        disco = next((d for d in discos if d["name"] == dev_name), disponibles[0])
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
        session.info("dest", f"{dev} ({disco['size_human']} · {disco_tipo.upper()} · {disco['model']})", "ok")
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
        avanzar()

        if session._aborted:
            session.clean_mounts()
            return

        # ── net ───────────────────────────────────────────────────────
        session.step("net", "active")
        session.status(session.t("status-checking-internet"))
        net_ok = check_internet()
        session.badges(net_ok, uefi)
        if not net_ok:
            session.step("net", "error", session.t("step-net-down"))
            session.error_step(session.t("err-no-internet"))
            return
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
        if not install_bootloader(session, ctx, dev, result.root_device, uefi, ucode):
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
        session._installing = False

        sudoers_guard = MOUNT_ROOT / "etc" / "sudoers.d" / "99-aur-build"
        if sudoers_guard.exists():
            try:
                sudoers_guard.unlink()
                session.log(session.t("log-cleanup-sudoers-ok"), "ok")
            except OSError as e:
                session.log(session.t("log-cleanup-sudoers-fail", e=e), "warn")
        session.stop_timer()
