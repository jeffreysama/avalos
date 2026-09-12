"""
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

from avalos_installer.core.config import MOUNT_ROOT
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
    if not symlink.exists():
        symlink.symlink_to("/etc/systemd/system/avalos-gpu-detect.service")
    session.log(session.t("log-gpu-detect-service-ok"), "ok")

    for svc in ["NetworkManager", "bluetooth", "sddm", "lm_sensors"]:
        session.run_chroot(["systemctl", "enable", svc])
    session.run_chroot(["systemctl", "--global", "enable",
                         "pipewire", "pipewire-pulse", "wireplumber"])
    session.log(session.t("log-sensors-detect-skipped"), "warn")

    if not ctx.usb_mode:
        session.log(session.t("log-section-snapper"), "step")

        rc_snap, out_snap = session.run_chroot(
            ["snapper", "--no-dbus", "-c", "root", "create-config", "/"]
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
