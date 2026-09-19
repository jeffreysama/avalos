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
