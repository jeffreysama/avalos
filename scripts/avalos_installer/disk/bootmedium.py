"""
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
