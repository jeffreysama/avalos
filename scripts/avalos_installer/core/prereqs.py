"""
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
