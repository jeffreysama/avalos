"""
system/rollback.py — deshacer lo que una instalación fallida o cancelada dejó FUERA de lo
que el instalador formatea.

Lo que promete (ni más ni menos):

  · Entradas de arranque UEFI (NVRAM): se borran las que creó el bootloader de esta
    instalación y se restaura el orden de arranque original. Solo se borra una entrada
    que (a) no existía al empezar (o cambió) y (b) lleva una etiqueta de nuestros
    bootloaders. Nunca una que ya estaba.
  · Archivos de la ESP: si la ESP ya existía (instalación manual junto a otro sistema), se
    quita lo que esta instalación agregó y se devuelven los archivos de arranque que pisó
    (EFI/BOOT, EFI/AvalOS, EFI/GRUB, EFI/refind, EFI/systemd y loader).
  · Código de arranque del MBR (BIOS, modo manual): se devuelven sus 446 bytes.
  · Tabla de particiones (modo automático): se guarda byte a byte el primer y el último MiB
    del disco (ahí viven la tabla GPT/MBR y su copia, el código de arranque del MBR y las
    firmas de RAID/LVM/LUKS/ZFS que `wipefs -a` borra a nivel de disco). Si el fallo ocurre
    DESPUÉS de reemplazar la tabla y ANTES del primer mkfs, se devuelven esos bytes y se
    verifica leyendo de nuevo. Pasado ese punto los datos anteriores ya no existen: no se toca
    nada y se avisa. (parted mkpart no crea sistemas de archivos y wipefs solo borra firmas:
    antes del primer mkfs el contenido de las particiones sigue intacto.)

Lo que NO hace: recuperar datos ya formateados, recrear una entrada UEFI preexistente que el
bootloader reemplazó (lo avisa), ni tocar el arranque de un sistema que ya quedó arrancable
(fase «usable»: usuario creado), porque ahí un fallo tardío no justifica quitarle el arranque.

Todo es defensivo: cualquier error se registra y se sigue; el rollback nunca lanza ni tapa el
error original de la instalación. Interruptor de emergencia: AVALOS_NO_ROLLBACK=1.

Cómo se usa (core/install.py y system/partition.py):

    journal = InstallJournal(session);  session.journal = journal
    journal.snapshot_firmware(uefi)          # al saber que es UEFI, antes de tocar nada
    journal.snapshot_table(dev)              # modo automático: justo antes de wipefs
    journal.mark_format(dev)                 # justo antes de cada mkfs (punto sin retorno)
    journal.snapshot_esp(efi_device)         # antes de instalar el bootloader
    journal.mark("boot")                     #   (y snapshot_mbr(dev) si es BIOS manual)
    journal.mark("usable")                   # el usuario ya existe: el sistema arranca
    journal.rollback(completed)              # en el finally de run_installation

El diario recuerda entre «Reintentar» (session.rollback_memory): la tabla original, el estado
original del firmware y qué discos ya se formatearon, para que un segundo intento no tome por
«original» lo que dejó el primero.
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from avalos_installer.core.config import MOUNT_EFI
from avalos_installer.core.shell import run_command

ROLLBACK_DIR = Path("/tmp/avalos-rollback")       # copias de seguridad (RAM del live)
ESP_PROBE_DIR = Path("/tmp/avalos-rollback-esp")  # montaje propio de la ESP; FUERA de ROLLBACK_DIR a propósito
KILL_SWITCH_ENV = "AVALOS_NO_ROLLBACK"

# Fases, siempre hacia adelante. table = ya se puede haber reemplazado la tabla; format = se
# empezó a formatear (sin retorno para los datos); boot = el bootloader puede haber tocado
# NVRAM/ESP/MBR; usable = usuario creado, el sistema arranca.
PHASES = ("init", "table", "format", "boot", "usable")

# Directorios de la ESP que un bootloader puede pisar: de sus archivos previos se guarda copia.
ESP_TRACKED = ("efi/boot", "efi/avalos", "efi/grub", "efi/refind", "efi/systemd", "loader")
ESP_BACKUP_FILE_MAX = 32 * 1024 * 1024
ESP_BACKUP_TOTAL_MAX = 96 * 1024 * 1024
MBR_BOOT_CODE_SIZE = 446
EDGE_BYTES = 1024 * 1024   # primer y último MiB del disco (tabla de particiones, copia GPT, firmas)

# Etiquetas de las entradas UEFI que crean los bootloaders de AvalOS: solo esas se borran.
OUR_BOOT_LABELS = ("grub", "refind", "linux boot manager", "avalos")


# ── Firmware (efibootmgr) ─────────────────────────────────────────────────
_RE_ORDER = re.compile(r"^BootOrder:\s*([0-9A-Fa-f]{4}(?:,[0-9A-Fa-f]{4})*)\s*$", re.M)
_RE_CURRENT = re.compile(r"^BootCurrent:\s*([0-9A-Fa-f]{4})\s*$", re.M)
_RE_ENTRY = re.compile(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.*?)\s*$", re.M)


_RE_DEVICE_PATH = re.compile(r"\s+[A-Za-z]+\(")   # primer nodo de la ruta de dispositivo: HD(, PciRoot(, USB(...


def split_label(text: str) -> str:
    """Etiqueta de una entrada UEFI. Con -v, efibootmgr la separa de la ruta con un tab; si no
    hubiera tab se corta en el primer nodo de ruta (HD(…), PciRoot(…)), para que algo como
    «\\EFI\\ubuntu\\grubx64.efi» de la ruta nunca cuente como parte de la etiqueta."""
    if "\t" in text:
        return text.split("\t", 1)[0].strip()
    m = _RE_DEVICE_PATH.search(text)
    return (text[:m.start()] if m else text).strip()


@dataclass
class FirmwareState:
    order: list = field(default_factory=list)      # ["0001", "0000"]
    entries: dict = field(default_factory=dict)    # id -> texto completo (etiqueta + ruta con -v)
    current: str | None = None

    def label(self, bid: str) -> str:
        return split_label(self.entries.get(bid, ""))


def parse_efibootmgr(text: str) -> FirmwareState | None:
    """Salida de `efibootmgr` (con o sin -v). None si no se reconoce nada."""
    entries = {m.group(1).upper(): m.group(2) for m in _RE_ENTRY.finditer(text or "")}
    order_m = _RE_ORDER.search(text or "")
    order = [x.upper() for x in order_m.group(1).split(",")] if order_m else []
    cur_m = _RE_CURRENT.search(text or "")
    if not entries and not order and not cur_m and not re.search(r"^(?:Timeout|BootNext):", text or "", re.M):
        return None                               # ni una línea que parezca de efibootmgr
    return FirmwareState(order=order, entries=entries, current=cur_m.group(1).upper() if cur_m else None)


def is_ours(label: str) -> bool:
    low = label.lower()
    return any(k in low for k in OUR_BOOT_LABELS)


# ── Árbol de archivos de la ESP ───────────────────────────────────────────
@dataclass
class EspSnapshot:
    device: str
    files: dict           # ruta relativa -> (tamaño, mtime_ns)
    dirs: set
    backups: dict         # ruta relativa -> Path de la copia
    skipped: list         # archivos rastreados que no se pudieron copiar (tamaño)


@dataclass
class TreeResult:
    removed: list = field(default_factory=list)
    restored: list = field(default_factory=list)
    unrestorable: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def scan_tree(root: Path) -> tuple[dict, set]:
    files: dict = {}
    dirs: set = set()
    for dirpath, _dirnames, filenames in os.walk(root):   # os.walk no sigue symlinks
        d = Path(dirpath)
        rel_d = d.relative_to(root).as_posix()
        if rel_d != ".":
            dirs.add(rel_d)
        for name in filenames:
            p = d / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                files[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return files, dirs


def _is_tracked(rel: str) -> bool:
    low = rel.lower()
    return any(low == t or low.startswith(t + "/") for t in ESP_TRACKED)


def backup_tracked(root: Path, files: dict, dest: Path) -> tuple[dict, list]:
    saved: dict = {}
    skipped: list = []
    total = 0
    for rel, (size, _mtime) in sorted(files.items()):
        if not _is_tracked(rel):
            continue
        if size > ESP_BACKUP_FILE_MAX or total + size > ESP_BACKUP_TOTAL_MAX:
            skipped.append(rel)
            continue
        target = dest / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, target)
        except OSError:
            skipped.append(rel)
            continue
        saved[rel] = target
        total += size
    return saved, skipped


def _unchanged(root: Path, rel: str, sig: tuple, snap: EspSnapshot, now_files: dict) -> bool:
    """¿El archivo sigue igual? Por tamaño y, si hay copia, por contenido. NO por fecha: FAT
    guarda la hora local y el kernel la convierte según la zona y las opciones de montaje
    (docs.kernel.org/filesystems/vfat), así que dos montajes pueden ver mtimes distintos."""
    cur = now_files.get(rel)
    if cur is None or cur[0] != sig[0]:
        return False
    saved = snap.backups.get(rel)
    if saved is None:
        return True                      # sin copia solo se puede comparar el tamaño
    try:
        return filecmp.cmp(root / rel, saved, shallow=False)
    except OSError:
        return False


def restore_tree(root: Path, snap: EspSnapshot) -> TreeResult:
    """Deja `root` como estaba en `snap`: quita archivos y carpetas nuevos, devuelve los
    archivos rastreados que se pisaron o borraron. Lo que ya existía y no se rastreó se
    deja como está (y se reporta si cambió)."""
    res = TreeResult()
    now_files, now_dirs = scan_tree(root)

    for rel in sorted(set(now_files) - set(snap.files)):          # archivos que agregó la instalación
        try:
            (root / rel).unlink()
            res.removed.append(rel)
        except OSError as e:
            res.errors.append(f"{rel}: {e}")

    for rel, sig in snap.files.items():                            # archivos previos cambiados o borrados
        if _unchanged(root, rel, sig, snap, now_files):
            continue
        saved = snap.backups.get(rel)
        if saved is None:
            res.unrestorable.append(rel)
            continue
        try:
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, dest)
            res.restored.append(rel)
        except OSError as e:
            res.errors.append(f"{rel}: {e}")

    for rel in sorted(now_dirs - snap.dirs, key=lambda r: r.count("/"), reverse=True):   # carpetas nuevas
        try:
            (root / rel).rmdir()                                   # solo si quedó vacía
        except OSError:
            pass
    return res


# ── MBR (BIOS) ────────────────────────────────────────────────────────────
def read_boot_code(dev: str) -> bytes | None:
    try:
        with open(dev, "rb") as fh:
            data = fh.read(MBR_BOOT_CODE_SIZE)
        return data if len(data) == MBR_BOOT_CODE_SIZE else None
    except OSError:
        return None


def write_boot_code(dev: str, data: bytes) -> None:
    """Escribe SOLO los 446 bytes de código: ni la tabla de particiones (446-509) ni la firma."""
    with open(dev, "r+b") as fh:
        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


# ── Bordes del disco (tabla de particiones byte a byte) ───────────────────
@dataclass
class DiskEdges:
    size: int
    head: bytes          # primer MiB (o el disco entero si es más chico)
    tail: bytes          # último MiB (vacío si head ya cubre todo el disco)
    tail_offset: int


def read_edges(dev: str) -> DiskEdges | None:
    try:
        with open(dev, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size < 4096:
                return None
            head_len = min(EDGE_BYTES, size)
            tail_len = min(EDGE_BYTES, size - head_len)
            tail_offset = size - tail_len
            fh.seek(0)
            head = fh.read(head_len)
            tail = b""
            if tail_len:
                fh.seek(tail_offset)
                tail = fh.read(tail_len)
        if len(head) != head_len or len(tail) != tail_len:
            return None
        return DiskEdges(size=size, head=head, tail=tail, tail_offset=tail_offset)
    except OSError:
        return None


def write_edges(dev: str, edges: DiskEdges) -> None:
    """Devuelve los bytes tal como estaban: la copia del final primero y el inicio al último."""
    with open(dev, "r+b") as fh:
        if edges.tail:
            fh.seek(edges.tail_offset)
            fh.write(edges.tail)
        fh.seek(0)
        fh.write(edges.head)
        fh.flush()
        os.fsync(fh.fileno())


# ── Tabla de particiones (texto) ──────────────────────────────────────────
def normalize_dump(text: str) -> list:
    """Compara dos `sfdisk --dump` sin que importen espacios ni la línea «device:»."""
    return [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()
            if ln.strip() and not ln.startswith("device:")]


# ── El diario ─────────────────────────────────────────────────────────────
class InstallJournal:
    def __init__(self, session):
        self.session = session
        mem = getattr(session, "rollback_memory", None)
        if mem is None:
            mem = {"tables": {}, "table_paths": {}, "edges": {}, "formatted": set(), "fw": None}
            session.rollback_memory = mem
        self.mem = mem
        self.phase = "init"
        self.uefi = False
        self.table_dev: str | None = None
        self.esp: EspSnapshot | None = None
        self.mbr: tuple | None = None            # (dispositivo, bytes)
        self.fw_unreadable = False               # UEFI pero efibootmgr falta en el live o no pudo leer el firmware
        self.warnings = 0

    # ── utilidades ────────────────────────────────────────────────
    def _log(self, key: str, cls: str = "info", **kw) -> None:
        self.session.log(self.session.t(key, **kw), cls)

    def _warn(self, key: str, **kw) -> None:
        self.warnings += 1
        self._log(key, "warn", **kw)

    def _diag(self, text: str) -> None:
        try:
            self.session.logfile.diag(text)
        except Exception:  # noqa: BLE001 — el log jamás debe romper el rollback
            pass

    def mark(self, phase: str) -> None:
        if PHASES.index(phase) > PHASES.index(self.phase):
            self.phase = phase

    def mark_format(self, dev: str) -> None:
        """Se llama justo ANTES de cada mkfs: desde aquí los datos del disco ya no existen."""
        self.mem["formatted"].add(dev)
        self.mark("format")

    # ── instantáneas (antes de cambiar nada) ──────────────────────
    def snapshot_firmware(self, uefi: bool) -> None:
        self.uefi = bool(uefi)
        if not self.uefi or self.mem.get("fw"):      # el primer intento de la sesión es el «original»
            return
        rc, out, _err = run_command(["efibootmgr", "-v"])
        state = parse_efibootmgr(out) if rc == 0 else None
        self.mem["fw"] = state
        self.fw_unreadable = state is None

    def snapshot_table(self, dev: str) -> None:
        """Modo automático, justo antes de wipefs. Guarda (solo la primera vez de la sesión)
        el primer y el último MiB del disco byte a byte y además un `sfdisk --dump` legible;
        deja copias en disco y en el log."""
        self.table_dev = dev
        self.mark("table")
        edges_mem = self.mem.setdefault("edges", {})
        if dev in self.mem["tables"] or dev in edges_mem:
            return
        edges = read_edges(dev)
        edges_mem[dev] = edges
        rc, out, _err = run_command(["sfdisk", "--dump", dev])
        dump = out if rc == 0 and re.search(r"^label:\s*\w+", out or "", re.M) else None
        self.mem["tables"][dev] = dump
        if edges is not None:
            self._persist_edges(dev, edges)
        if dump is None:
            if edges is not None:
                self._log("rb-table-saved", "info", dev=dev, path=ROLLBACK_DIR)
            return
        for line in dump.splitlines():
            self._diag(f"sfdisk-dump {dev}: {line}")
        path = ROLLBACK_DIR / f"sfdisk-{Path(dev).name}.dump"
        try:
            ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(dump, encoding="utf-8")
            path.chmod(0o600)
            self.mem["table_paths"][dev] = path
            self._log("rb-table-saved", "info", dev=dev, path=path)
        except OSError:
            pass

    def _persist_edges(self, dev: str, edges: DiskEdges) -> None:
        """Copias con el nombre y el formato de sfdisk/wipefs (<disp>-<offset>.bak): se restauran
        a mano con dd if=<archivo> of=<disp> seek=$((0x<offset>)) bs=1 conv=notrunc."""
        try:
            ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
            name = Path(dev).name
            for offset, data in ((0, edges.head), (edges.tail_offset, edges.tail)):
                if not data:
                    continue
                path = ROLLBACK_DIR / f"edges-{name}-0x{offset:08x}.bak"
                path.write_bytes(data)
                path.chmod(0o600)
                self._diag(f"edges-backup {dev}: dd if={path} of={dev} seek=$((0x{offset:08x})) bs=1 conv=notrunc")
        except OSError:
            pass                                  # sigue la copia en memoria

    def snapshot_esp(self, efi_device: str, root: Path | None = None) -> None:
        """Con la ESP montada y ANTES del bootloader: árbol de archivos y copia de los que un
        bootloader suele pisar."""
        root = root or MOUNT_EFI
        if not (self.uefi and efi_device) or not os.path.ismount(root):
            return
        backup_dir = ROLLBACK_DIR / "esp-backup"
        shutil.rmtree(backup_dir, ignore_errors=True)
        files, dirs = scan_tree(root)
        saved, skipped = backup_tracked(root, files, backup_dir)
        self.esp = EspSnapshot(device=efi_device, files=files, dirs=dirs, backups=saved, skipped=skipped)

    def snapshot_mbr(self, dev: str) -> None:
        """BIOS en modo manual: el MBR de un disco ajeno conserva su código de arranque."""
        code = read_boot_code(dev)
        if code is not None:
            self.mbr = (dev, code)

    # ── deshacer ──────────────────────────────────────────────────
    def rollback(self, completed: bool) -> None:
        """Se llama siempre desde el finally de run_installation. Nunca lanza."""
        try:
            if completed:
                shutil.rmtree(ROLLBACK_DIR, ignore_errors=True)
                return
            if self.phase == "init":
                return                                  # no se cambió nada: sin ruido
            if os.environ.get(KILL_SWITCH_ENV) == "1":
                self._log("rb-disabled", "warn", env=KILL_SWITCH_ENV)
                return
            if self.phase == "usable":
                self._log("rb-kept", "info")
                return
            self._log("rb-start", "warn")
            for step in (self._undo_mbr, self._undo_esp, self._undo_firmware, self._undo_table):
                try:
                    step()
                except Exception as e:  # noqa: BLE001 — un paso roto no frena a los demás
                    self._warn("rb-error", e=e)
            if self.warnings:
                self._log("rb-done-warn", "warn")
            else:
                self._log("rb-done", "ok")
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        shutil.rmtree(ROLLBACK_DIR / "esp-backup", ignore_errors=True)
        try:
            if ESP_PROBE_DIR.is_dir() and not os.path.ismount(ESP_PROBE_DIR):
                ESP_PROBE_DIR.rmdir()                  # rmdir, jamás rmtree: podría ser una ESP montada
        except OSError:
            pass

    def _undo_mbr(self) -> None:
        if not self.mbr or self.phase != "boot":
            return
        dev, saved = self.mbr
        now = read_boot_code(dev)
        if now is None:
            self._warn("rb-mbr-failed", dev=dev, e="read")
            return
        if now == saved:
            return
        try:
            write_boot_code(dev, saved)
        except OSError as e:
            self._warn("rb-mbr-failed", dev=dev, e=e)
            return
        if read_boot_code(dev) == saved:
            self._log("rb-mbr-restored", "ok", dev=dev)
        else:
            self._warn("rb-mbr-failed", dev=dev, e="verify")

    def _undo_esp(self) -> None:
        snap = self.esp
        if snap is None or self.phase != "boot":
            return
        probe = ESP_PROBE_DIR
        mounted_here = False
        root = MOUNT_EFI
        if not os.path.ismount(root):
            probe.mkdir(parents=True, exist_ok=True)
            rc, _out = self.session.run_cmd(["mount", snap.device, str(probe)], timeout=30, abortable=False)
            if rc != 0 or not os.path.ismount(probe):
                self._warn("rb-esp-failed", e=f"mount rc={rc}")
                return
            mounted_here = True
            root = probe
        try:
            res = restore_tree(root, snap)
        finally:
            if mounted_here:
                self.session.run_cmd(["sync"], timeout=60, abortable=False)
                self.session.run_cmd(["umount", str(probe)], timeout=30, abortable=False)
        if res.errors:
            self._warn("rb-esp-failed", e="; ".join(res.errors[:3]))
        if res.unrestorable:
            self._warn("rb-esp-unrestorable", n=len(res.unrestorable), files=", ".join(res.unrestorable[:5]))
        if res.removed or res.restored:
            self._log("rb-esp-done", "ok", removed=len(res.removed), restored=len(res.restored))

    def _undo_firmware(self) -> None:
        before: FirmwareState | None = self.mem.get("fw")
        if not self.uefi or self.phase != "boot":
            return
        if before is None:
            if self.fw_unreadable:                # ISO sin efibootmgr (o firmware ilegible): que no sea en silencio
                self._warn("rb-fw-unavailable")
            return
        rc, out, _err = run_command(["efibootmgr", "-v"])
        after = parse_efibootmgr(out) if rc == 0 else None
        if after is None:
            self._warn("rb-fw-failed", what="efibootmgr")
            return

        # 1) entradas nuevas (o cambiadas) y nuestras: fuera. Las preexistentes no se tocan jamás.
        for bid, text in after.entries.items():
            if before.entries.get(bid) == text:
                continue
            label = after.label(bid)
            if not is_ours(label):
                self._log("rb-fw-kept", "info", id=bid, label=label)
                continue
            rc_del, _o = self.session.run_cmd(["efibootmgr", "-b", bid, "-B"], timeout=30, abortable=False)
            if rc_del == 0:
                self._log("rb-fw-removed", "ok", id=bid, label=label)
            else:
                self._warn("rb-fw-failed", what=f"Boot{bid}")

        # 2) orden de arranque: el original, sin las entradas que ya no existen
        rc, out, _err = run_command(["efibootmgr", "-v"])
        final = parse_efibootmgr(out) if rc == 0 else None
        if final is None:
            return
        lost = [before.label(b) for b in before.entries if final.entries.get(b) != before.entries[b]]
        if lost:
            self._warn("rb-fw-lost", labels=", ".join(l or "?" for l in lost))
            for bid in before.entries:
                if final.entries.get(bid) != before.entries[bid]:
                    self._diag(f"efi-entry-lost Boot{bid}: {before.entries[bid]}")
        target = [b for b in before.order if b in final.entries]
        if target and final.order != target:
            order = ",".join(target)
            rc_o, _o = self.session.run_cmd(["efibootmgr", "-o", order], timeout=30, abortable=False)
            if rc_o == 0:
                self._log("rb-fw-order", "ok", order=order)
            else:
                self._warn("rb-fw-failed", what="BootOrder")

    def _undo_table(self) -> None:
        dev = self.table_dev
        if not dev:
            return
        if dev in self.mem["formatted"]:
            self._log("rb-table-formatted", "warn", dev=dev)
            return
        edges = self.mem.get("edges", {}).get(dev)
        if edges is not None:
            self._restore_edges(dev, edges)
        elif self.mem["tables"].get(dev):
            self._restore_with_sfdisk(dev)            # no se pudo leer el disco: queda el volcado de texto

    def _restore_edges(self, dev: str, edges: DiskEdges) -> None:
        now = read_edges(dev)
        if now is None:
            self._warn("rb-edges-failed", dev=dev, e="read", dir=ROLLBACK_DIR)
            return
        if now.size != edges.size:                    # otro disco con el mismo nombre: no se toca
            self._warn("rb-edges-failed", dev=dev, e=f"size {now.size} != {edges.size}", dir=ROLLBACK_DIR)
            return
        if now.head == edges.head and now.tail == edges.tail:
            self._log("rb-table-unchanged", "info", dev=dev)
            return
        try:
            write_edges(dev, edges)
        except OSError as e:
            self._warn("rb-edges-failed", dev=dev, e=e, dir=ROLLBACK_DIR)
            return
        run_command(["blockdev", "--rereadpt", dev], timeout=15)
        run_command(["udevadm", "settle", "--timeout=5"], timeout=15)
        back = read_edges(dev)
        if back is not None and back.head == edges.head and back.tail == edges.tail:
            self._log("rb-table-restored", "ok", dev=dev)
        else:
            self._warn("rb-table-mismatch", dev=dev, path=ROLLBACK_DIR)

    def _restore_with_sfdisk(self, dev: str) -> None:
        saved = self.mem["tables"].get(dev)
        rc, now, _err = run_command(["sfdisk", "--dump", dev])
        if rc == 0 and normalize_dump(now) == normalize_dump(saved):
            self._log("rb-table-unchanged", "info", dev=dev)
            return
        path = self.mem["table_paths"].get(dev)
        if path is None or not Path(path).is_file():
            path = ROLLBACK_DIR / f"sfdisk-{Path(dev).name}.dump"
            try:
                ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(saved, encoding="utf-8")
                path.chmod(0o600)
                self.mem["table_paths"][dev] = path
            except OSError as e:
                self._warn("rb-error", e=e)
                return
        # --wipe-partitions never: restaurar la tabla no debe borrar firmas de nada
        rc_restore, _out = self.session.run_cmd(
            ["sh", "-c", 'sfdisk --wipe-partitions never "$1" < "$2"', "sh", dev, str(path)],
            timeout=60, abortable=False)
        run_command(["blockdev", "--rereadpt", dev], timeout=15)
        run_command(["udevadm", "settle", "--timeout=5"], timeout=15)
        rc, after, _err = run_command(["sfdisk", "--dump", dev])
        if rc == 0 and normalize_dump(after) == normalize_dump(saved):
            self._log("rb-table-restored", "ok", dev=dev)      # aunque sfdisk se quejara del reread
        elif rc_restore != 0:
            self._warn("rb-table-failed", dev=dev, rc=rc_restore, path=path)
        else:
            self._warn("rb-table-mismatch", dev=dev, path=path)
