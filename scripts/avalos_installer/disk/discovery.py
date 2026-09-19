"""
disk/discovery.py — detección y listado de discos/particiones para el
instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 112, 265-479, 480-516, 617-627
de la versión actual en main). Lógica y comentarios explicativos sin
cambios respecto al original — solo se movió de lugar, se actualizó el
import de `run_command` (antes `_ejecutar` privada del monolito), y todos
los identificadores se llevaron a inglés a pedido explícito (los
comentarios se dejaron en español).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from avalos_installer.core.shell import run_command

MIN_DISK_GB = 30

# GUID oficial de partición EFI System en tablas GPT (UEFI Specification,
# confirmado también en ArchWiki y Microsoft Learn). Es la misma señal que
# usa el propio firmware UEFI para encontrar la ESP — no una heurística de
# tamaño u orden.
_GUID_EFI_SYSTEM_PARTITION = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


def detect_boot_disk() -> str:
    # FIX: en el live de archiso "/" es un overlay ("airootfs"), no un bloque:
    # la lógica de abajo devolvía "airootfs" y el disco de arranque (la USB)
    # nunca se marcaba como es_arranque — ni la UI lo bloqueaba ni el chequeo
    # de install.py lo rechazaba. El medio real sale de /run/archiso/bootmnt
    # (ver disk/bootmedium.py: dd, Ventoy, copytoram). Si no se puede
    # determinar (ej. VM con la ISO como CD-ROM) se sigue con lo de siempre.
    try:
        from avalos_installer.disk.bootmedium import boot_disks
        names = boot_disks()
        if names:
            return names[0]
    except Exception as e:
        print(f"[WARN] detect_boot_disk: bootmedium falló: {e}", file=sys.stderr)
    rc, out, _ = run_command(["findmnt", "-n", "-o", "SOURCE", "/"])
    if rc == 0 and out:
        dev = out.strip()
        if dev.startswith("/dev/mapper/") or dev.startswith("/dev/dm-"):
            rc2, out2, _ = run_command(["lsblk", "-no", "PKNAME", dev])
            if rc2 == 0 and out2.strip():
                return out2.strip().split()[0]
        dev = dev.removeprefix("/dev/")
        return re.sub(r'p?\d+$', '', dev)
    rc, out, _ = run_command(["lsblk", "-J", "-o", "NAME,MOUNTPOINTS"])
    if rc == 0 and out:
        try:
            for disk in json.loads(out).get("blockdevices", []):
                if _disk_has_mount(disk, "/"):
                    return disk["name"]
        except json.JSONDecodeError as e:
            print(f"[WARN] detect_boot_disk: lsblk JSON inválido: {e}", file=sys.stderr)
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "/":
                    src = parts[0]
                    if src.startswith("/dev/mapper/") or src.startswith("/dev/dm-"):
                        rc2, out2, _ = run_command(["lsblk", "-no", "PKNAME", src])
                        if rc2 == 0 and out2.strip():
                            return out2.strip().split()[0]
                    return re.sub(r'p?\d+$', '', src.removeprefix("/dev/"))
    except OSError:
        pass
    return ""


def _disk_has_mount(node: dict, point: str) -> bool:
    mount_points = node.get("mountpoints") or [node.get("mountpoint")]
    if point in (mount_points or []):
        return True
    for child in node.get("children", []):
        if _disk_has_mount(child, point):
            return True
    return False


def list_disks() -> list[dict]:
    rc, out, _ = run_command([
        "lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,MODEL,TRAN,ROTA,VENDOR"
    ])
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    boot_disk = detect_boot_disk()
    disks = []
    for node in data.get("blockdevices", []):
        if node.get("type") != "disk":
            continue
        name = node.get("name", "")
        size_b = int(node.get("size") or 0)
        model = (node.get("model") or node.get("vendor") or "").strip()
        tran = (node.get("tran") or "").strip()
        rotational = node.get("rota") in ("1", True, 1)
        parts = []
        for child in node.get("children", []):
            if child.get("type") in ("part", "lvm"):
                mount_points = child.get("mountpoints") or [child.get("mountpoint")]
                parts.append({
                    "name": child.get("name", ""),
                    "size_b": int(child.get("size") or 0),
                    "mounts": [m for m in mount_points if m],
                })
        disks.append({
            "name": name,
            "size_b": size_b,
            "size_human": _bytes_to_human(size_b),
            "model": model or "Disco desconocido",
            "tran": tran.upper() if tran else "—",
            "tipo": "HDD" if rotational else "SSD/NVMe",
            "es_arranque": (name == boot_disk),
            "particiones": parts,
            "montajes": _active_mounts(node),
        })
    return disks


def _active_mounts(node: dict) -> list[str]:
    result = []
    mount_points = node.get("mountpoints") or [node.get("mountpoint")]
    result.extend([m for m in (mount_points or []) if m])
    for child in node.get("children", []):
        result.extend(_active_mounts(child))
    return result


def _bytes_to_human(b: int) -> str:
    fb = float(b)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if fb < 1024.0:
            return f"{fb:.1f} {unit}"
        fb /= 1024.0
    return f"{fb:.1f} PB"


def detect_manual_partitions(dev: str, uefi: bool) -> dict:
    """Modo manual: analiza lo que el usuario dejó particionado a mano en
    'dev' (ej. /dev/nvme0n1) y separa la partición EFI/boot de las
    candidatas a root.

    GPT: compara PARTTYPE de cada partición contra el GUID oficial de EFI
    System Partition — señal estructural real, la misma que usa el
    firmware UEFI.

    MBR (sin tabla GPT): usa 'sfdisk -A dev' sin número de partición, que
    lista las particiones con el flag bootable/activo encendido (mismo
    criterio que ya usa 'parted ... set 1 boot on' en el modo automático
    de este instalador). sfdisk detecta solo internamente si el disco es
    GPT y avisa por stderr en vez de fallar, así que no hace falta
    detectar la tabla nosotros mismos antes de llamarlo.

    'uefi' (booleano, viene de is_uefi() del sistema en vivo) decide qué
    SIGNIFICA el flag bootable en MBR: en BIOS Legacy no existe el
    concepto de partición EFI — el flag bootable marca directamente la
    partición que contiene /boot (con frecuencia la única partición del
    disco), así que en ese caso nunca se descarta como "EFI", siempre
    queda como candidata a root. Solo si el firmware es UEFI pero el
    disco resultó estar en MBR (caso inusual, p.ej. "UEFI CSM/legacy
    boot") se sigue tratando el flag bootable como equivalente al GUID
    GPT de ESP, porque en ese caso sí puede haber una partición separada
    pensada para el firmware. Confirmado con ArchWiki/foros: en BIOS/MBR
    "lo que quieres bootable es tu directorio raíz, o /boot si está
    separado" — nunca una partición EFI real, ese concepto no existe sin
    UEFI.

    Devuelve {"efi": "/dev/X" | "", "candidatas_root": [ {"name","size_b",
    "size_human","fstype"} , ... ], "es_gpt": bool}. No decide sola cuál
    partición es root si hay más de una candidata — eso lo resuelve el
    usuario en el dropdown del wizard."""
    rc, out, _ = run_command([
        "lsblk", "-J", "-b", "-n", "-o",
        "NAME,SIZE,TYPE,PARTTYPE,FSTYPE,MOUNTPOINTS", dev,
    ])
    if rc != 0 or not out:
        return {"efi": "", "candidatas_root": [], "es_gpt": False}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"efi": "", "candidatas_root": [], "es_gpt": False}

    _disk_node = next(
        (n for n in data.get("blockdevices", []) if n.get("name") == dev.removeprefix("/dev/")),
        None,
    )
    _children = (_disk_node or {}).get("children", []) or []
    if not _children:
        # fallback: algunas versiones de lsblk aplanan el árbol si se le
        # pasa un device específico en vez del disco completo
        _children = data.get("blockdevices", [])

    _is_gpt = any((c.get("parttype") or "").strip().lower() == _GUID_EFI_SYSTEM_PARTITION
                  for c in _children)

    _efi = ""
    _boot_flags: set[str] = set()
    if not _is_gpt and uefi:
        # MBR + firmware UEFI (caso inusual: UEFI en modo legacy/CSM):
        # preguntarle a sfdisk qué partición tiene el flag bootable, igual
        # que hace el modo automático de este instalador para marcar la
        # partición equivalente a ESP. En BIOS puro (uefi=False) esta
        # llamada no hace falta — el flag bootable jamás se interpreta
        # como EFI en ese caso, así que no vale la pena el subprocess.
        # 'sfdisk -A dev' sin número de partición = modo listado (confirmado
        # en sfdisk(8)). No falla si el disco resulta ser GPT — solo avisa
        # por stderr y entra en modo PMBR, así que es seguro llamarlo aunque
        # _is_gpt haya dado False por error.
        try:
            _rc_sf, _out_sf, _ = run_command(["sfdisk", "-A", dev])
            if _rc_sf == 0:
                for _line in _out_sf.splitlines():
                    _line = _line.strip()
                    if _line.startswith(dev):
                        _boot_flags.add(_line.split()[0].removeprefix("/dev/"))
        except Exception:
            pass

    _candidates: list[dict] = []
    for _child in _children:
        if _child.get("type") != "part":
            continue
        _name = _child.get("name", "")
        _parttype = (_child.get("parttype") or "").strip().lower()
        _fstype = (_child.get("fstype") or "").strip()
        _size_b = int(_child.get("size") or 0)

        _is_this_efi = (
            (_is_gpt and _parttype == _GUID_EFI_SYSTEM_PARTITION)
            or (not _is_gpt and uefi and _name in _boot_flags)
        )
        if _is_this_efi and not _efi:
            _efi = "/dev/" + _name
            continue

        _candidates.append({
            "name": "/dev/" + _name,
            "size_b": _size_b,
            "size_human": _bytes_to_human(_size_b),
            "fstype": _fstype or "?",
        })

    return {"efi": _efi, "candidatas_root": _candidates, "es_gpt": _is_gpt}


def detect_btrfs_subvolumes(dev_root: str) -> list[str]:
    """Modo manual: si el usuario ya formateó dev_root con Btrfs y creó
    sus propios subvolúmenes, los lista para que el instalador pueda
    saltarse la creación de los que ya existan (según lo acordado) en vez
    de pisarlos.

    No hay forma de inspeccionar subvolúmenes sin montar el filesystem al
    menos una vez (confirmado: 'btrfs subvolume list' opera sobre un punto
    de montaje, no sobre el device crudo) — se monta de solo-lectura
    ('-o ro') para minimizar riesgo, ya que solo se necesita leer."""
    _tmp = "/tmp/btrfs_probe_manual"
    Path(_tmp).mkdir(parents=True, exist_ok=True)
    _rc_mnt, _, _ = run_command(["mount", "-o", "ro", dev_root, _tmp])
    if _rc_mnt != 0:
        try:
            os.rmdir(_tmp)
        except OSError:
            pass
        return []
    try:
        _rc, _out, _ = run_command(["btrfs", "subvolume", "list", _tmp])
        if _rc != 0 or not _out:
            return []
        _subvolumes = []
        for _line in _out.splitlines():
            # formato: "ID 256 gen 12 top level 5 path @home"
            _m = re.search(r"\bpath\s+(\S+)$", _line.strip())
            if _m:
                _subvolumes.append(_m.group(1))
        return _subvolumes
    finally:
        run_command(["umount", _tmp])
        try:
            os.rmdir(_tmp)
        except OSError:
            pass


def detect_target_disk_type(dev_name: str) -> str:
    """Detecta si el disco es HDD, SSD o NVMe para el IO scheduler."""
    rotational_path = Path(f"/sys/block/{dev_name}/queue/rotational")
    try:
        rotational = rotational_path.read_text().strip()
        if "nvme" in dev_name or "mmcblk" in dev_name:
            return "nvme"
        return "hdd" if rotational == "1" else "ssd"
    except Exception:
        return "ssd"
