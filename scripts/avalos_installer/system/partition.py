"""
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


def partition_and_format(session: InstallSession, ctx: InstallContext,
                          dev: str, dev_name: str, disk_info: dict,
                          uefi: bool) -> PartitionResult | None:
    """Devuelve PartitionResult si todo salió bien, None si falló o se
    abortó (en ambos casos ya se llamó session.clean_mounts() y se
    reportó el error a la UI antes de retornar — el llamador solo
    necesita chequear el retorno y detenerse)."""

    if not ctx.manual_mode:
        session.countdown_start(dev, disk_info["model"], disk_info["size_human"])
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

    # El chequeo de /proc/mounts aplica en ambos modos: en modo manual
    # protege contra que el dropdown del wizard haya apuntado al disco
    # equivocado, exactamente igual que en modo automático protege contra
    # un disco mal seleccionado.
    session.log(session.t("log-checking-mounted-partitions"), "info")
    with open("/proc/mounts") as mf:
        proc_mounts = mf.read()
    dev_base = dev_name
    mounted = []
    for line in proc_mounts.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        src = parts[0].removeprefix("/dev/")
        if src.startswith(dev_base) and src != dev_base:
            suffix = src[len(dev_base):]
            if suffix and (suffix[0].isdigit() or suffix[0] == 'p'):
                if parts[0] != dev:
                    mounted.append(parts[1])
    if mounted:
        points = ", ".join(mounted)
        session.error_fatal(session.t("err-disk-has-mounted-partitions", dev=dev, puntos=points))
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
            efi_device = dev + ("p1" if "nvme" in dev_name or "mmcblk" in dev_name else "1")
            root_device = dev + ("p2" if "nvme" in dev_name or "mmcblk" in dev_name else "2")
        else:
            rc, _ = session.run_cmd([
                "parted", "-s", dev,
                "mklabel", "msdos",
                "mkpart", "primary", "ext4", "1MiB", "100%",
                "set", "1", "boot", "on",
            ])
            root_device = dev + ("p1" if "nvme" in dev_name or "mmcblk" in dev_name else "1")
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
            for sv in subvols:
                rc_sv, _ = session.run_cmd(["btrfs", "subvolume", "create", f"{btrfs_tmp}/{sv}"])
                if rc_sv != 0:
                    session.log(session.t("log-subvol-create-fail", sv=sv), "warn")

            rc_um, out_um = session.run_cmd(["umount", btrfs_tmp])
            if rc_um != 0:
                session.log(
                    session.t("log-btrfs-tmp-umount-fail", out=out_um.strip()[-200:]),
                    "warn",
                )
            session.log(session.t("log-subvols-created", subvols=", ".join(subvols)), "ok")

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
