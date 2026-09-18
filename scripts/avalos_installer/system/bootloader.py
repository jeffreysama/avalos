"""
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


def install_bootloader(session: InstallSession, ctx: InstallContext,
                        dev: str, dev_root: str, uefi: bool, ucode: str) -> bool:
    session.step("grub", "active")

    if ctx.bootloader == 'none':
        session.step("grub", "skip", session.t("step-bootloader-skipped-label"))
        session.log(session.t("log-bootloader-skipped"), "warn")
        return True

    elif ctx.bootloader == 'grub':
        session.status(session.t("status-installing-grub"))
        session.log(session.t("log-section-installing-grub"), "step")
        if uefi:
            grub_cmd = ["grub-install", "--target=x86_64-efi",
                        "--efi-directory=/boot/efi", "--bootloader-id=GRUB"]

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
        session.run_chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
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

        vmlinuz_files = glob.glob(str(MOUNT_ROOT / "boot" / "vmlinuz-*"))
        kernel_name = Path(vmlinuz_files[0]).name.replace("vmlinuz-", "") if vmlinuz_files else "linux"
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

        vmlinuz_files = glob.glob(str(MOUNT_ROOT / "boot" / "vmlinuz-*"))
        kernel_name = Path(vmlinuz_files[0]).name.replace("vmlinuz-", "") if vmlinuz_files else "linux"
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

        session.step("grub", "done", session.t("step-sdboot-installed-label"))
        return True

    return True
