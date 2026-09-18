"""
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
