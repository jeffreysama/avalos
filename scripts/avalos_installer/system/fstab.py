"""
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
