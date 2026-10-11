"""Pruebas del rollback del instalador (scripts/avalos_installer/system/rollback.py).

Solo stdlib (unittest) y sin tocar discos ni el firmware: efibootmgr, sfdisk y los montajes
son simulados; los archivos de la ESP son un directorio temporal de verdad. Se corren con

    python3 -m unittest discover -s tests -v
"""
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402
from avalos_installer.core import install as install_mod  # noqa: E402
from avalos_installer.system import partition as part_mod  # noqa: E402
from avalos_installer.system import rollback as rb  # noqa: E402

LANGS = ("en", "es", "zh", "ja")
_REAL_READ_EDGES, _REAL_WRITE_EDGES = rb.read_edges, rb.write_edges

ORIG_DUMP = """label: gpt
label-id: 11111111-2222-3333-4444-555555555555
device: /dev/vdb
unit: sectors
first-lba: 34
last-lba: 41943006
sector-size: 512

/dev/vdb1 : start=        2048, size=      204800, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=AAAAAAAA-0000-0000-0000-000000000001, name="EFI system partition"
/dev/vdb2 : start=      206848, size=    41000000, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, uuid=AAAAAAAA-0000-0000-0000-000000000002, name="Basic data partition"
"""
NEW_DUMP = """label: gpt
label-id: 99999999-8888-7777-6666-555555555555
device: /dev/vdb
unit: sectors
first-lba: 34
last-lba: 41943006
sector-size: 512

/dev/vdb1 : start=        2048, size=     1048576, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=BBBBBBBB-0000-0000-0000-000000000001, name="ESP"
/dev/vdb2 : start=     1050624, size=    40892416, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=BBBBBBBB-0000-0000-0000-000000000002, name="root"
"""

WIN = "Windows Boot Manager\tHD(1,GPT,AAAAAAAA-0000-0000-0000-000000000001,0x800,0x32000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)"
UBU = "ubuntu\tHD(1,GPT,AAAAAAAA-0000-0000-0000-000000000001,0x800,0x32000)/File(\\EFI\\ubuntu\\shimx64.efi)"
USB = "UEFI: Live USB\tUSB(0,0)"
GRUB_OLD = "GRUB\tHD(1,GPT,CCCCCCCC-0000-0000-0000-000000000001,0x800,0x32000)/File(\\EFI\\GRUB\\grubx64.efi)"
GRUB_NEW = "GRUB\tHD(1,GPT,BBBBBBBB-0000-0000-0000-000000000001,0x800,0x100000)/File(\\EFI\\GRUB\\grubx64.efi)"


# ── Simulación ────────────────────────────────────────────────────────────
class FakeFirmware:
    def __init__(self, entries, order, current="0002"):
        self.entries, self.order, self.current = dict(entries), list(order), current

    def render(self):
        lines = [f"BootCurrent: {self.current}", "Timeout: 1 seconds"]
        if self.order:
            lines.append("BootOrder: " + ",".join(self.order))
        lines += [f"Boot{b}* {t}" for b, t in sorted(self.entries.items())]
        return "\n".join(lines) + "\n"

    def handle(self, cmd):
        if "-B" in cmd:
            bid = cmd[cmd.index("-b") + 1]
            self.entries.pop(bid, None)
            self.order = [o for o in self.order if o != bid]
            return 0, "", ""
        if "-o" in cmd:
            self.order = cmd[cmd.index("-o") + 1].split(",")
            return 0, "", ""
        return 0, self.render(), ""


class FakeDisk:
    def __init__(self, dump):
        self.dump = dump          # None = sin tabla (sfdisk --dump falla)


class Machine:
    """Firmware, discos y montajes simulados. probe() reemplaza a rollback.run_command;
    run() es lo que contesta session.run_cmd."""
    def __init__(self):
        self.fw = None
        self.disks = {}
        self.mounts = set()
        self.calls = []           # ("probe"|"run", cmd)
        self.fail = {}            # prefijo del comando -> rc forzado

    def _forced(self, cmd):
        text = " ".join(map(str, cmd))
        return next((rc for prefix, rc in self.fail.items() if text.startswith(prefix)), None)

    def probe(self, cmd, timeout=30):
        self.calls.append(("probe", list(cmd)))
        rc = self._forced(cmd)
        if rc is not None:
            return rc, "", "forzado"
        if cmd[0] == "efibootmgr":
            return self.fw.handle(cmd) if self.fw else (1, "", "EFI variables are not supported")
        if cmd[:2] == ["sfdisk", "--dump"]:
            disk = self.disks.get(cmd[2])
            return (0, disk.dump, "") if disk and disk.dump else (1, "", "failed to parse")
        return 0, "", ""

    def run(self, cmd):
        self.calls.append(("run", list(cmd)))
        rc = self._forced(cmd)
        if rc is not None:
            return rc, ""
        if cmd[0] == "efibootmgr":
            rc, out, _ = self.fw.handle(cmd)
            return rc, out
        if cmd[:2] == ["sh", "-c"] and "sfdisk" in cmd[2]:
            self.disks[cmd[4]].dump = Path(cmd[5]).read_text(encoding="utf-8")
            return 0, ""
        if cmd[0] == "mount":
            self.mounts.add(cmd[2])
        elif cmd[0] == "umount":
            self.mounts.discard(cmd[1])
        return 0, ""

    def ran(self, *prefix):
        return [c for kind, c in self.calls if kind == "run" and c[:len(prefix)] == list(prefix)]


class FakeLogfile:
    def __init__(self):
        self.diag_lines = []

    def diag(self, text):
        self.diag_lines.append(text)

    def add_secret(self, value):
        pass


class FakeSession:
    def __init__(self, machine=None, lang="es"):
        self._lang = lang
        self._aborted = False
        self.machine = machine or Machine()
        self.lines, self.errors, self.events = [], [], []
        self.logfile = FakeLogfile()
        self.journal = None

    def t(self, key, **kw):
        tpl = translations.TRANSLATIONS[self._lang].get(key)
        if tpl is None:
            if key.startswith("rb-"):
                raise KeyError(key)            # un rb-* sin traducir es un bug
            return key
        return tpl.format(**kw)

    def log(self, msg, cls="info"):
        self.lines.append((cls, msg))

    def run_cmd(self, cmd, timeout=300, log_cls="info", pre_mkdir=None, abortable=True):
        self.events.append(("cmd", list(cmd)))
        return self.machine.run([str(c) for c in cmd])

    def error_step(self, msg): self.errors.append(msg)
    def error_fatal(self, msg): self.errors.append(msg)
    def clean_mounts(self): self.events.append(("clean_mounts",))
    def step(self, *a, **k): pass
    def status(self, *a, **k): pass
    def countdown_start(self, *a, **k): pass
    def countdown_tick(self, *a, **k): pass
    def countdown_cancel(self, *a, **k): pass

    @property
    def text(self):
        return "\n".join(m for _c, m in self.lines)

    def classes(self):
        return [c for c, _m in self.lines]


def make_tree(root: Path, files: dict):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def tree_state(root: Path):
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    dirs = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}
    return files, dirs


def patch_edges(case, disk_files):
    """Los «discos» de las pruebas son archivos temporales: ninguna prueba abre un dispositivo
    real. Un dispositivo sin archivo asignado se comporta como un disco ilegible."""
    def read_edges(dev):
        f = disk_files.get(dev)
        return _REAL_READ_EDGES(str(f)) if f else None

    def write_edges(dev, edges):
        f = disk_files.get(dev)
        if f is None:
            raise OSError("dispositivo simulado sin archivo")
        _REAL_WRITE_EDGES(str(f), edges)

    for p in (mock.patch.object(rb, "read_edges", read_edges), mock.patch.object(rb, "write_edges", write_edges)):
        p.start()
        case.addCleanup(p.stop)


def scribble(path, wipefs=True, parted=True):
    """Lo que wipefs -a y parted mklabel gpt le hacen a los bordes de un disco."""
    size = os.path.getsize(path)
    with open(path, "r+b") as fh:
        if wipefs:
            fh.seek(0x1fe); fh.write(b"\x00\x00")
            fh.seek(0x200); fh.write(b"\x00" * 8)
            fh.seek(size - 512); fh.write(b"\x00" * 8)
            fh.seek(0x7f000); fh.write(b"\x00" * 16)               # firma a nivel de disco (p. ej. miembro ZFS)
        if parted:
            fh.seek(0); fh.write(b"\x00" * 512)                    # MBR protector nuevo, sin código de arranque
            fh.seek(512); fh.write(b"EFI PART" + b"\x11" * 504)
            fh.seek(1024); fh.write(b"\x22" * (32 * 512))
            fh.seek(size - 33 * 512); fh.write(b"\x33" * (33 * 512))


class Base(unittest.TestCase):
    lang = "es"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-rb-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.efi = self.tmp / "efi"
        self.efi.mkdir()
        self.m = Machine()
        self.s = FakeSession(self.m, self.lang)
        for name, value in (("ROLLBACK_DIR", self.tmp / "rb"), ("ESP_PROBE_DIR", self.tmp / "probe"),
                            ("MOUNT_EFI", self.efi)):
            p = mock.patch.object(rb, name, value)
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch.object(rb, "run_command", self.m.probe),
                  mock.patch("os.path.ismount", side_effect=lambda x: str(x) in self.m.mounts)):
            p.start()
            self.addCleanup(p.stop)
        self.disk_files = {}
        patch_edges(self, self.disk_files)
        self.j = rb.InstallJournal(self.s)
        self.s.journal = self.j

    def new_journal(self):
        """Un intento nuevo (Reintentar): diario nuevo, misma sesión."""
        self.j = rb.InstallJournal(self.s)
        self.s.journal = self.j
        return self.j


# ── Parseo de efibootmgr ──────────────────────────────────────────────────
class ParseTests(unittest.TestCase):
    def test_plain(self):
        st = rb.parse_efibootmgr("BootCurrent: 0001\nTimeout: 1 seconds\nBootOrder: 0001,0000\n"
                                 "Boot0000* Windows Boot Manager\nBoot0001* GRUB\n")
        self.assertEqual(st.order, ["0001", "0000"])
        self.assertEqual(st.current, "0001")
        self.assertEqual(set(st.entries), {"0000", "0001"})
        self.assertEqual(st.label("0000"), "Windows Boot Manager")

    def test_verbose_label_stops_at_tab(self):
        st = rb.parse_efibootmgr(f"BootOrder: 0000\nBoot0000* {WIN}\n")
        self.assertEqual(st.label("0000"), "Windows Boot Manager")
        self.assertIn("bootmgfw.efi", st.entries["0000"])

    def test_inactive_and_lowercase_ids(self):
        st = rb.parse_efibootmgr("BootOrder: 000a,0001\nBoot000a  Linux\nBoot0001* Other\n")
        self.assertEqual(st.order, ["000A", "0001"])
        self.assertEqual(set(st.entries), {"000A", "0001"})

    def test_current_and_order_lines_are_not_entries(self):
        st = rb.parse_efibootmgr("BootCurrent: 0001\nBootOrder: 0001\nBootNext: 0002\nBoot0001* GRUB\n")
        self.assertEqual(set(st.entries), {"0001"})

    def test_unrecognised_is_none(self):
        self.assertIsNone(rb.parse_efibootmgr("EFI variables are not supported on this system.\n"))
        self.assertIsNone(rb.parse_efibootmgr(""))
        self.assertIsNone(rb.parse_efibootmgr(None))

    def test_is_ours(self):
        for label in ("GRUB", "grub", "rEFInd Boot Manager", "Linux Boot Manager", "AvalOS"):
            self.assertTrue(rb.is_ours(label), label)
        for label in ("Windows Boot Manager", "ubuntu", "UEFI: Live USB", "Fedora", ""):
            self.assertFalse(rb.is_ours(label), label)

    def test_split_label_with_tab(self):
        self.assertEqual(rb.split_label("GRUB\tHD(1,GPT,x,0x800,0x1)/File(\\EFI\\GRUB\\grubx64.efi)"), "GRUB")

    def test_split_label_without_tab_cuts_at_the_device_path(self):
        self.assertEqual(rb.split_label("Windows Boot Manager HD(1,GPT,x,0x800,0x1)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)"),
                         "Windows Boot Manager")
        self.assertEqual(rb.split_label("UEFI: PXE IPv4 PciRoot(0x0)/Pci(0x1c,0x2)"), "UEFI: PXE IPv4")
        self.assertEqual(rb.split_label("Ubuntu (Samsung SSD) HD(1,GPT,x,0x800,0x1)/File(\\EFI\\ubuntu\\shimx64.efi)"),
                         "Ubuntu (Samsung SSD)")
        self.assertEqual(rb.split_label("GRUB"), "GRUB")
        self.assertEqual(rb.split_label(""), "")

    def test_path_text_never_counts_as_label(self):
        st = rb.parse_efibootmgr("Boot0005* UEFI: Algo HD(1,GPT,x,0x800,0x1)/File(\\EFI\\ubuntu\\grubx64.efi)\n")
        self.assertFalse(rb.is_ours(st.label("0005")))

    def test_header_only_output_is_a_valid_empty_state(self):
        for text in ("BootCurrent: 0001\nTimeout: 1 seconds\n", "Timeout: 0 seconds\n", "BootNext: 0003\n"):
            st = rb.parse_efibootmgr(text)
            self.assertIsNotNone(st, text)
            self.assertEqual((st.entries, st.order), ({}, []))
        self.assertIsNone(rb.parse_efibootmgr("efibootmgr: command not found\n"))



# ── Árbol de la ESP (sistema de archivos real) ────────────────────────────
class TreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-tree-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "esp"
        self.root.mkdir()
        self.bk = self.tmp / "backup"

    def snap(self):
        files, dirs = rb.scan_tree(self.root)
        saved, skipped = rb.backup_tracked(self.root, files, self.bk)
        return rb.EspSnapshot("/dev/x1", files, dirs, saved, skipped)

    WINDOWS = {
        "EFI/Microsoft/Boot/bootmgfw.efi": b"windows-boot-manager",
        "EFI/Microsoft/Boot/BCD": b"bcd-data",
        "EFI/BOOT/BOOTX64.EFI": b"fallback-original",
        "loader/loader.conf": b"default old.conf\n",
    }

    def install_like_avalos(self):
        """Lo que un instalador de AvalOS escribe: GRUB + fallback + sd-boot."""
        make_tree(self.root, {
            "EFI/GRUB/grubx64.efi": b"grub" * 100,
            "EFI/BOOT/BOOTX64.EFI": b"grub-fallback-pisado",
            "loader/loader.conf": b"default avalos.conf\n",
            "loader/entries/avalos.conf": b"title AvalOS\n",
            "AvalOS/vmlinuz-linux": b"kernel" * 50,
        })

    def test_restores_exact_original(self):
        make_tree(self.root, self.WINDOWS)
        before = tree_state(self.root)
        snap = self.snap()
        self.install_like_avalos()
        self.assertNotEqual(tree_state(self.root), before)
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(sorted(res.restored), ["EFI/BOOT/BOOTX64.EFI", "loader/loader.conf"])
        self.assertEqual(sorted(res.removed), ["AvalOS/vmlinuz-linux", "EFI/GRUB/grubx64.efi", "loader/entries/avalos.conf"])
        self.assertEqual((res.unrestorable, res.errors), ([], []))

    def test_windows_files_never_touched(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        mtimes = {r: (self.root / r).stat().st_mtime_ns for r in self.WINDOWS if r.startswith("EFI/Microsoft")}
        self.install_like_avalos()
        rb.restore_tree(self.root, snap)
        for r, mt in mtimes.items():
            self.assertEqual((self.root / r).stat().st_mtime_ns, mt)

    def test_untracked_change_is_reported_not_deleted(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        (self.root / "EFI/Microsoft/Boot/BCD").write_bytes(b"cambiado por otro")
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(res.unrestorable, ["EFI/Microsoft/Boot/BCD"])
        self.assertEqual((self.root / "EFI/Microsoft/Boot/BCD").read_bytes(), b"cambiado por otro")

    def test_backups_only_for_tracked_dirs(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        self.assertEqual(set(snap.backups), {"EFI/BOOT/BOOTX64.EFI", "loader/loader.conf"})

    def test_tracked_match_is_case_insensitive_and_exact(self):
        make_tree(self.root, {"efi/boot/bootx64.efi": b"x", "EFI/BOOTLEG/a.efi": b"y", "EFI/Systemd/z": b"z"})
        snap = self.snap()
        self.assertIn("efi/boot/bootx64.efi", snap.backups)
        self.assertIn("EFI/Systemd/z", snap.backups)
        self.assertNotIn("EFI/BOOTLEG/a.efi", snap.backups)

    def test_big_tracked_file_is_skipped_and_then_unrestorable(self):
        make_tree(self.root, {"EFI/BOOT/BOOTX64.EFI": b"x" * 64})
        with mock.patch.object(rb, "ESP_BACKUP_FILE_MAX", 10):
            snap = self.snap()
        self.assertEqual(snap.skipped, ["EFI/BOOT/BOOTX64.EFI"])
        (self.root / "EFI/BOOT/BOOTX64.EFI").write_bytes(b"pisado")
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(res.unrestorable, ["EFI/BOOT/BOOTX64.EFI"])

    def test_total_backup_cap(self):
        make_tree(self.root, {"EFI/BOOT/a": b"1" * 8, "EFI/BOOT/b": b"2" * 8})
        with mock.patch.object(rb, "ESP_BACKUP_TOTAL_MAX", 10):
            snap = self.snap()
        self.assertEqual(len(snap.backups), 1)
        self.assertEqual(len(snap.skipped), 1)

    def test_deleted_tracked_file_comes_back(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        (self.root / "EFI/BOOT/BOOTX64.EFI").unlink()
        res = rb.restore_tree(self.root, snap)
        self.assertEqual((self.root / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"fallback-original")
        self.assertEqual(res.restored, ["EFI/BOOT/BOOTX64.EFI"])

    def test_fresh_esp_is_emptied_of_new_files_only(self):
        snap = self.snap()                                # ESP vacía (modo automático)
        self.install_like_avalos()
        rb.restore_tree(self.root, snap)
        self.assertEqual(tree_state(self.root), ({}, set()))

    def test_new_nested_dirs_removed_and_old_dirs_kept(self):
        make_tree(self.root, {"EFI/Microsoft/Boot/x": b"1"})
        (self.root / "EFI/Vacio").mkdir()
        snap = self.snap()
        make_tree(self.root, {"EFI/nuevo/a/b/c.efi": b"2"})
        rb.restore_tree(self.root, snap)
        files, dirs = tree_state(self.root)
        self.assertEqual(files, {"EFI/Microsoft/Boot/x": b"1"})
        self.assertIn("EFI/Vacio", dirs)
        self.assertNotIn("EFI/nuevo", dirs)

    def test_files_added_inside_foreign_dir_are_removed(self):
        make_tree(self.root, {"EFI/Microsoft/Boot/x": b"1"})
        snap = self.snap()
        make_tree(self.root, {"EFI/Microsoft/Boot/avalos-extra.efi": b"2"})
        rb.restore_tree(self.root, snap)
        self.assertEqual(tree_state(self.root)[0], {"EFI/Microsoft/Boot/x": b"1"})

    def test_mtime_only_difference_is_not_a_change(self):
        """FAT guarda hora local y el kernel la convierte según zona y opciones de montaje:
        dos montajes pueden ver mtimes distintos. Solo cuentan tamaño y contenido."""
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        for p in self.root.rglob("*"):
            if p.is_file():
                st = p.stat()
                os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 3 * 3600 * 10**9))
        res = rb.restore_tree(self.root, snap)
        self.assertEqual((res.restored, res.unrestorable, res.removed, res.errors), ([], [], [], []))

    def test_same_size_content_change_in_a_tracked_file_is_restored(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        (self.root / "EFI/BOOT/BOOTX64.EFI").write_bytes(b"X" * len(self.WINDOWS["EFI/BOOT/BOOTX64.EFI"]))
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(res.restored, ["EFI/BOOT/BOOTX64.EFI"])
        self.assertEqual((self.root / "EFI/BOOT/BOOTX64.EFI").read_bytes(), self.WINDOWS["EFI/BOOT/BOOTX64.EFI"])

    def test_untracked_files_are_compared_by_size_only(self):
        make_tree(self.root, self.WINDOWS)
        snap = self.snap()
        (self.root / "EFI/Microsoft/Boot/BCD").write_bytes(b"x" * len(self.WINDOWS["EFI/Microsoft/Boot/BCD"]))
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(res.unrestorable, [])                       # límite conocido y documentado

    def test_files_of_a_previous_avalos_install_on_the_esp_are_restored(self):
        make_tree(self.root, {"EFI/AvalOS/grubx64.efi": b"grub-de-la-instalacion-anterior",
                              "EFI/Microsoft/Boot/bootmgfw.efi": b"windows"})
        snap = self.snap()
        (self.root / "EFI/AvalOS/grubx64.efi").write_bytes(b"grub-de-la-instalacion-fallida!")
        res = rb.restore_tree(self.root, snap)
        self.assertEqual(res.restored, ["EFI/AvalOS/grubx64.efi"])
        self.assertEqual((self.root / "EFI/AvalOS/grubx64.efi").read_bytes(), b"grub-de-la-instalacion-anterior")



# ── MBR (BIOS) ────────────────────────────────────────────────────────────
class MbrTests(Base):
    def make_disk(self, code=b"\xEA" * 446, rest=b"\x00" * 578):
        p = self.tmp / "disk.img"
        p.write_bytes(code + rest)
        return str(p)

    def test_restores_only_the_boot_code(self):
        dev = self.make_disk(code=b"WINDOWS-MBR".ljust(446, b"\x90"), rest=b"\x01" * 578)
        self.j.uefi = False
        self.j.snapshot_mbr(dev)
        data = bytearray(Path(dev).read_bytes())
        data[:446] = b"GRUB-STAGE1".ljust(446, b"\x00")
        data[450:454] = b"NEW!"                           # tabla de particiones tocada por otro: se respeta
        Path(dev).write_bytes(bytes(data))
        self.j.mark("boot")
        self.j.rollback(False)
        out = Path(dev).read_bytes()
        self.assertEqual(out[:446], b"WINDOWS-MBR".ljust(446, b"\x90"))
        self.assertEqual(out[450:454], b"NEW!")
        self.assertEqual(len(out), 1024)
        self.assertIn("MBR", self.s.text)

    def test_unchanged_boot_code_is_not_rewritten(self):
        dev = self.make_disk()
        self.j.snapshot_mbr(dev)
        self.j.mark("boot")
        with mock.patch.object(rb, "write_boot_code") as w:
            self.j.rollback(False)
        w.assert_not_called()

    def test_short_or_missing_device_is_ignored(self):
        self.j.snapshot_mbr(str(self.tmp / "no-existe"))
        short = self.tmp / "short"
        short.write_bytes(b"x" * 100)
        self.j.snapshot_mbr(str(short))
        self.assertIsNone(self.j.mbr)

    def test_not_restored_before_boot_phase(self):
        dev = self.make_disk()
        self.j.snapshot_mbr(dev)
        Path(dev).write_bytes(b"\x00" * 1024)
        self.j.mark("format")
        with mock.patch.object(rb, "write_boot_code") as w:
            self.j.rollback(False)
        w.assert_not_called()

    def test_write_failure_warns(self):
        dev = self.make_disk()
        self.j.snapshot_mbr(dev)
        Path(dev).write_bytes(b"\x00" * 1024)
        self.j.mark("boot")
        with mock.patch.object(rb, "write_boot_code", side_effect=OSError("ro")):
            self.j.rollback(False)
        self.assertIn("warn", self.s.classes())


# ── Firmware UEFI ─────────────────────────────────────────────────────────
class FirmwareTests(Base):
    def setup_fw(self, before_entries, before_order, after_entries=None, after_order=None):
        self.m.fw = FakeFirmware(before_entries, before_order)
        self.j.snapshot_firmware(True)
        if after_entries is not None:
            self.m.fw.entries = dict(after_entries)
            self.m.fw.order = list(after_order)
        self.j.mark("boot")

    def base_entries(self):
        return {"0000": WIN, "0002": USB, "0003": UBU}

    def test_removes_only_the_new_grub_entry(self):
        after = dict(self.base_entries(), **{"0004": GRUB_NEW})
        self.setup_fw(self.base_entries(), ["0000", "0003"], after, ["0004", "0000", "0003"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr", "-b", "0004", "-B"), [["efibootmgr", "-b", "0004", "-B"]])
        self.assertEqual(len(self.m.ran("efibootmgr")), 1)           # ni otro -B ni -o
        self.assertEqual(self.m.fw.order, ["0000", "0003"])
        self.assertEqual(set(self.m.fw.entries), {"0000", "0002", "0003"})
        self.assertIn("Boot0004", self.s.text)
        self.assertEqual(self.s.classes()[-1], "ok")

    def test_reorders_when_the_bootloader_shuffled_others(self):
        after = dict(self.base_entries(), **{"0004": GRUB_NEW})
        self.setup_fw(self.base_entries(), ["0000", "0003"], after, ["0004", "0003", "0000"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr", "-o"), [["efibootmgr", "-o", "0000,0003"]])
        self.assertEqual(self.m.fw.order, ["0000", "0003"])

    def test_foreign_new_entry_is_left_alone(self):
        after = dict(self.base_entries(), **{"0005": "UEFI: Algo\tPCI(0,0)"})
        self.setup_fw(self.base_entries(), ["0000", "0003"], after, ["0005", "0000", "0003"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [])
        self.assertIn("0005", self.m.fw.entries)

    def test_preexisting_entries_are_never_deleted(self):
        self.setup_fw(self.base_entries(), ["0000", "0003"])        # nada cambió
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr"), [])
        self.assertEqual(set(self.m.fw.entries), {"0000", "0002", "0003"})

    def test_preexisting_grub_replaced_in_place_is_removed_and_reported_lost(self):
        before = dict(self.base_entries(), **{"0001": GRUB_OLD})
        after = dict(before, **{"0001": GRUB_NEW})                   # grub-install reutilizó el id
        self.setup_fw(before, ["0001", "0000", "0003"], after, ["0001", "0000", "0003"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr", "-b", "0001", "-B"), [["efibootmgr", "-b", "0001", "-B"]])
        self.assertEqual(self.m.fw.order, ["0000", "0003"])
        self.assertIn("GRUB", self.s.text)
        self.assertIn("warn", self.s.classes())
        self.assertEqual(self.s.classes()[-1], "warn")               # rb-done-warn

    def test_same_id_same_text_is_untouched_even_if_label_is_ours(self):
        before = dict(self.base_entries(), **{"0001": GRUB_OLD})
        self.setup_fw(before, ["0001", "0000"], dict(before), ["0001", "0000"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr"), [])

    def test_unreadable_efibootmgr_warns_and_deletes_nothing(self):
        self.m.fw = FakeFirmware(self.base_entries(), ["0000"])
        self.j.snapshot_firmware(True)
        self.j.mark("boot")
        self.m.fail["efibootmgr -v"] = 1
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr"), [])
        self.assertIn("warn", self.s.classes())

    def test_delete_failure_warns(self):
        after = dict(self.base_entries(), **{"0004": GRUB_NEW})
        self.setup_fw(self.base_entries(), ["0000"], after, ["0004", "0000"])
        self.m.fail["efibootmgr -b 0004 -B"] = 5
        self.j.rollback(False)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_noop_outside_boot_phase_and_without_snapshot_or_uefi(self):
        after = dict(self.base_entries(), **{"0004": GRUB_NEW})
        self.m.fw = FakeFirmware(self.base_entries(), ["0000"])
        self.j.snapshot_firmware(True)
        self.m.fw.entries, self.m.fw.order = dict(after), ["0004", "0000"]
        self.j.mark("format")                                        # el bootloader aún no empezó
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr"), [])
        # BIOS: no hay firmware que mirar
        j2 = rb.InstallJournal(FakeSession(Machine()))
        j2.snapshot_firmware(False)
        self.assertIsNone(j2.mem["fw"])

    def test_first_snapshot_of_the_session_is_the_original(self):
        self.m.fw = FakeFirmware(self.base_entries(), ["0000"])
        self.j.snapshot_firmware(True)
        first = self.j.mem["fw"]
        self.m.fw.entries["0009"] = GRUB_NEW                         # quedó basura de un intento fallido
        j2 = self.new_journal()
        j2.snapshot_firmware(True)
        self.assertIs(j2.mem["fw"], first)
        self.assertNotIn("0009", j2.mem["fw"].entries)

    def test_failed_probe_is_retried_next_attempt(self):
        self.j.snapshot_firmware(True)                               # efibootmgr no está
        self.assertIsNone(self.j.mem["fw"])
        self.m.fw = FakeFirmware(self.base_entries(), ["0000"])
        self.new_journal().snapshot_firmware(True)
        self.assertIsNotNone(self.j.mem["fw"])

    def test_without_tabs_a_foreign_entry_whose_path_mentions_grub_is_not_ours(self):
        before = {"0000": "Windows Boot Manager HD(1,GPT,AAAA,0x800,0x1)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)"}
        after = dict(before, **{
            "0005": "UEFI: Algo HD(1,GPT,CCCC,0x800,0x1)/File(\\EFI\\ubuntu\\grubx64.efi)",
            "0006": "GRUB HD(1,GPT,BBBB,0x800,0x1)/File(\\EFI\\GRUB\\grubx64.efi)"})
        self.setup_fw(before, ["0000"], after, ["0006", "0005", "0000"])
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [["efibootmgr", "-b", "0006", "-B"]])
        self.assertIn("0005", self.m.fw.entries)

    def test_details_of_a_lost_entry_go_to_the_log_for_manual_recreation(self):
        before = dict(self.base_entries(), **{"0001": GRUB_OLD})
        after = dict(before, **{"0001": GRUB_NEW})
        self.setup_fw(before, ["0001", "0000", "0003"], after, ["0001", "0000", "0003"])
        self.j.rollback(False)
        lost = [l for l in self.s.logfile.diag_lines if l.startswith("efi-entry-lost Boot0001")]
        self.assertEqual(len(lost), 1)
        self.assertIn("CCCCCCCC", lost[0])                            # el UUID de la partición original

    def test_missing_efibootmgr_is_reported_instead_of_silently_doing_nothing(self):
        self.m.fail["efibootmgr"] = -1                                # el live no lo trae
        self.j.snapshot_firmware(True)
        self.j.mark("boot")
        self.j.rollback(False)
        self.assertIn("efibootmgr no está disponible", self.s.text)
        self.assertEqual(self.m.ran("efibootmgr"), [])
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_unreadable_firmware_is_reported_too(self):
        self.m.fail["efibootmgr"] = 2                                 # «EFI variables are not supported on this system»
        self.j.snapshot_firmware(True)
        self.j.mark("boot")
        self.j.rollback(False)
        self.assertIn("efibootmgr no está disponible", self.s.text)

    def test_no_unavailable_warning_when_efibootmgr_works(self):
        after = dict(self.base_entries(), **{"0004": GRUB_NEW})
        self.setup_fw(self.base_entries(), ["0000", "0003"], after, ["0004", "0000", "0003"])
        self.j.rollback(False)
        self.assertNotIn("no está disponible", self.s.text)

    def test_empty_but_working_firmware_is_a_valid_original_state(self):
        self.m.fw = FakeFirmware({}, [])                              # NVRAM sin entradas
        self.j.snapshot_firmware(True)
        self.assertIsNotNone(self.j.mem["fw"])
        self.m.fw.entries, self.m.fw.order = {"0000": GRUB_NEW}, ["0000"]
        self.j.mark("boot")
        self.j.rollback(False)
        self.assertEqual(self.m.fw.entries, {})
        self.assertNotIn("no está disponible", self.s.text)

    def test_bios_never_talks_about_efibootmgr(self):
        self.j.snapshot_firmware(False)
        self.j.mark("boot")
        self.j.rollback(False)
        self.assertNotIn("efibootmgr", self.s.text)
        self.assertEqual(self.m.ran("efibootmgr"), [])



# ── Tabla de particiones ──────────────────────────────────────────────────
class TableTests(Base):
    DEV = "/dev/vdb"

    def start(self, dump=ORIG_DUMP):
        self.m.disks[self.DEV] = FakeDisk(dump)
        self.j.snapshot_table(self.DEV)

    def wipe_and_repartition(self):
        self.m.disks[self.DEV].dump = NEW_DUMP

    def test_restores_and_verifies_when_failure_precedes_mkfs(self):
        self.start()
        self.wipe_and_repartition()
        self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.m.disks[self.DEV].dump), rb.normalize_dump(ORIG_DUMP))
        self.assertIn("restaurada y verificada", self.s.text)
        self.assertEqual(self.s.classes()[-1], "ok")

    def test_restore_command_shape(self):
        self.start()
        self.wipe_and_repartition()
        self.j.rollback(False)
        (cmd,) = self.m.ran("sh", "-c")
        self.assertEqual(cmd[2], 'sfdisk --wipe-partitions never "$1" < "$2"')
        self.assertEqual(cmd[3:5], ["sh", self.DEV])
        self.assertEqual(Path(cmd[5]).read_text(encoding="utf-8"), ORIG_DUMP)
        self.assertIn("--wipe-partitions never", cmd[2])

    def test_dump_file_is_private_and_logged(self):
        self.start()
        path = self.j.mem["table_paths"][self.DEV]
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(any("label-id: 11111111" in l for l in self.s.logfile.diag_lines))
        self.assertTrue(all(l.startswith("sfdisk-dump /dev/vdb: ") for l in self.s.logfile.diag_lines))

    def test_unchanged_table_is_not_rewritten(self):
        self.start()                                                  # wipefs falló: el disco sigue igual
        self.j.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])
        self.assertIn("seguía siendo la original", self.s.text)

    def test_whitespace_and_device_line_differences_do_not_count(self):
        self.start()
        self.m.disks[self.DEV].dump = ORIG_DUMP.replace("device: /dev/vdb", "device: /dev/vdb ").replace("start=        2048", "start= 2048")
        self.j.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])

    def test_never_restored_after_formatting_started(self):
        self.start()
        self.wipe_and_repartition()
        self.j.mark_format(self.DEV)
        self.j.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])
        self.assertEqual(self.m.disks[self.DEV].dump, NEW_DUMP)
        self.assertIn("no se pueden recuperar", self.s.text)

    def test_restore_failure_tells_how_to_do_it_by_hand(self):
        self.start()
        self.wipe_and_repartition()
        self.m.fail["sh -c"] = 1
        self.j.rollback(False)
        self.assertIn("sfdisk /dev/vdb <", self.s.text)
        self.assertIn(str(self.j.mem["table_paths"][self.DEV]), self.s.text)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_mismatch_after_restore_warns(self):
        self.start()
        self.wipe_and_repartition()
        real = self.m.run
        def lying_run(cmd):
            rc, out = real(cmd)
            if cmd[:2] == ["sh", "-c"]:
                self.m.disks[self.DEV].dump = NEW_DUMP               # el kernel/sfdisk no dejó la tabla igual
            return rc, out
        self.m.run = lying_run
        self.j.rollback(False)
        self.assertIn("no coincide", self.s.text)

    def test_disk_without_original_table_is_left_alone(self):
        self.start(dump=None)
        self.assertIsNone(self.j.mem["tables"][self.DEV])
        self.wipe_and_repartition()
        self.j.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])

    def test_dump_file_is_rewritten_if_it_vanished(self):
        self.start()
        self.wipe_and_repartition()
        self.j.mem["table_paths"][self.DEV].unlink()
        self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.m.disks[self.DEV].dump), rb.normalize_dump(ORIG_DUMP))

    def test_retry_keeps_the_first_dump_as_the_original(self):
        self.start()
        self.wipe_and_repartition()
        self.j.rollback(False)                                        # intento 1: restaurada
        probes = len(self.m.calls)
        j2 = self.new_journal()
        j2.snapshot_table(self.DEV)
        dumps = [c for k, c in self.m.calls[probes:] if c[:2] == ["sfdisk", "--dump"]]
        self.assertEqual(dumps, [])                                   # no se vuelve a «fotografiar»
        self.assertEqual(j2.mem["tables"][self.DEV], ORIG_DUMP)

    def test_retry_after_formatting_never_restores(self):
        self.start()
        self.wipe_and_repartition()
        self.j.mark_format(self.DEV)
        self.j.rollback(False)                                        # intento 1: formateó
        j2 = self.new_journal()
        j2.snapshot_table(self.DEV)                                   # intento 2: otra vez en fase table
        self.m.disks[self.DEV].dump = None                            # y falla con el disco sin tabla
        j2.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])
        self.assertIn("no se pueden recuperar", self.s.text)

    def test_manual_mode_has_no_table_logic(self):
        self.j.mark("boot")                                           # modo manual: nunca snapshot_table
        self.m.disks[self.DEV] = FakeDisk(NEW_DUMP)
        self.j.rollback(False)
        self.assertEqual(self.m.ran("sh", "-c"), [])

    def test_nonzero_exit_but_matching_table_counts_as_restored(self):
        """sfdisk puede quejarse de no poder releer la tabla y aun así haberla escrito."""
        self.start()
        self.wipe_and_repartition()
        real = self.m.run
        def complaining_run(cmd):
            rc, out = real(cmd)
            return (1, out) if cmd[:2] == ["sh", "-c"] else (rc, out)
        self.m.run = complaining_run
        self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.m.disks[self.DEV].dump), rb.normalize_dump(ORIG_DUMP))
        self.assertIn("restaurada y verificada", self.s.text)
        self.assertEqual(self.s.classes()[-1], "ok")



# ── ESP dentro del diario (con «montaje» simulado) ────────────────────────
class EspJournalTests(Base):
    def prepare(self):
        make_tree(self.efi, TreeTests.WINDOWS)
        self.before = tree_state(self.efi)
        self.m.mounts.add(str(self.efi))                              # ESP montada: se fotografía
        self.j.uefi = True
        self.j.snapshot_esp("/dev/vdb1")
        self.j.mark("boot")
        TreeTests.install_like_avalos(SimpleNamespace(root=self.efi))

    def test_snapshot_skipped_without_uefi_device_or_mount(self):
        j = rb.InstallJournal(FakeSession(Machine()))
        j.snapshot_esp("/dev/vdb1")                                   # sin uefi
        j.uefi = True
        j.snapshot_esp("")                                            # sin dispositivo
        j.snapshot_esp("/dev/vdb1")                                   # no montada
        self.assertIsNone(j.esp)

    def test_restores_through_its_own_mount_when_clean_mounts_already_ran(self):
        self.prepare()
        self.m.mounts.discard(str(self.efi))                          # clean_mounts() desmontó todo
        with mock.patch.object(rb, "ESP_PROBE_DIR", self.efi):        # el «montaje propio» ve el mismo árbol
            self.j.rollback(False)
        self.assertEqual(self.m.ran("mount", "/dev/vdb1", str(self.efi)), [["mount", "/dev/vdb1", str(self.efi)]])
        self.assertEqual(len(self.m.ran("umount")), 1)
        self.assertEqual(tree_state(self.efi), self.before)
        self.assertIn("Partición EFI restaurada", self.s.text)

    def test_uses_the_existing_mount_if_still_mounted(self):
        self.prepare()                                                # MOUNT_EFI sigue montada
        self.j.rollback(False)
        self.assertEqual(self.m.ran("mount"), [])
        self.assertEqual(tree_state(self.efi), self.before)

    def test_mount_failure_warns_and_touches_nothing(self):
        self.prepare()
        self.m.mounts.discard(str(self.efi))
        after = tree_state(self.efi)
        self.m.fail["mount"] = 32
        self.j.rollback(False)
        self.assertEqual(tree_state(self.efi), after)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_not_run_before_boot_phase(self):
        self.prepare()
        self.j.phase = "format"
        after = tree_state(self.efi)
        self.j.rollback(False)
        self.assertEqual(tree_state(self.efi), after)

    def test_mounted_probe_dir_is_never_deleted(self):
        probe = self.tmp / "probe"
        probe.mkdir()
        (probe / "EFI-de-otro-sistema").write_text("no me borres")
        self.m.mounts.add(str(probe))
        self.j.mark("table")
        self.j.rollback(False)
        self.assertTrue((probe / "EFI-de-otro-sistema").exists())


# ── Orquestación ──────────────────────────────────────────────────────────
class OrchestratorTests(Base):
    def test_completed_cleans_up_silently(self):
        (self.tmp / "rb").mkdir()
        (self.tmp / "rb" / "x.dump").write_text("x")
        self.j.mark("usable")
        self.j.rollback(True)
        self.assertFalse((self.tmp / "rb").exists())
        self.assertEqual((self.s.lines, self.m.calls), ([], []))

    def test_nothing_touched_means_no_noise(self):
        self.j.rollback(False)
        self.assertEqual((self.s.lines, self.m.calls), ([], []))

    def test_usable_system_keeps_its_boot_configuration(self):
        after = {"0000": WIN, "0004": GRUB_NEW}
        self.m.fw = FakeFirmware({"0000": WIN}, ["0000"])
        self.j.snapshot_firmware(True)
        self.m.fw.entries, self.m.fw.order = after, ["0004", "0000"]
        self.j.mark("boot")
        self.j.mark("usable")
        self.j.rollback(False)
        self.assertEqual(self.m.ran("efibootmgr"), [])
        self.assertIn("ya arrancaba", self.s.text)

    def test_kill_switch(self):
        self.j.mark("boot")
        with mock.patch.dict(os.environ, {rb.KILL_SWITCH_ENV: "1"}):
            self.j.rollback(False)
        self.assertEqual(self.m.calls, [])
        self.assertIn(rb.KILL_SWITCH_ENV, self.s.text)

    def test_undo_order_is_boot_things_first_then_table(self):
        order = []
        for name in ("_undo_mbr", "_undo_esp", "_undo_firmware", "_undo_table"):
            p = mock.patch.object(rb.InstallJournal, name, lambda self, n=name: order.append(n))
            p.start()
            self.addCleanup(p.stop)
        self.j.mark("boot")
        self.j.rollback(False)
        self.assertEqual(order, ["_undo_mbr", "_undo_esp", "_undo_firmware", "_undo_table"])

    def test_a_broken_step_does_not_stop_the_others_and_is_reported(self):
        ran = []
        def boom(self_): raise RuntimeError("kaboom")
        with mock.patch.object(rb.InstallJournal, "_undo_esp", boom), \
             mock.patch.object(rb.InstallJournal, "_undo_table", lambda s_: ran.append("table")):
            self.j.mark("boot")
            self.j.rollback(False)
        self.assertEqual(ran, ["table"])
        self.assertIn("kaboom", self.s.text)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_rollback_never_raises_even_if_logging_does(self):
        self.s.log = mock.Mock(side_effect=RuntimeError("log roto"))
        self.j.mark("boot")
        self.j.rollback(False)                                        # no debe lanzar

    def test_phases_only_move_forward(self):
        self.j.mark("boot")
        self.j.mark("table")
        self.assertEqual(self.j.phase, "boot")
        with self.assertRaises(ValueError):
            self.j.mark("inexistente")

    def test_mark_format_remembers_the_disk_across_attempts(self):
        self.j.mark_format("/dev/vdb")
        self.assertIn("/dev/vdb", self.new_journal().mem["formatted"])

    def test_cleanup_removes_esp_backups_but_keeps_dumps(self):
        (self.tmp / "rb" / "esp-backup").mkdir(parents=True)
        (self.tmp / "rb" / "sfdisk-vdb.dump").write_text("x")
        self.j.mark("table")
        self.j.rollback(False)
        self.assertFalse((self.tmp / "rb" / "esp-backup").exists())
        self.assertTrue((self.tmp / "rb" / "sfdisk-vdb.dump").exists())


# ── Todo el flujo, en los 4 idiomas ───────────────────────────────────────
class EveryLanguage(Base):
    def test_full_rollback_renders_cleanly_in_all_languages(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                m = self.m
                m.fw, m.disks, m.mounts, m.calls, m.fail = None, {}, set(), [], {}
                shutil.rmtree(self.efi)
                self.efi.mkdir()
                s = self.s = FakeSession(m, lang)
                j = self.j = rb.InstallJournal(s)
                s.journal = j
                j.mem.update({"tables": {}, "table_paths": {}, "formatted": set(), "fw": None})
                m.fw = FakeFirmware({"0000": WIN, "0001": GRUB_OLD}, ["0001", "0000"])
                j.snapshot_firmware(True)
                m.disks["/dev/vdb"] = FakeDisk(ORIG_DUMP)
                j.snapshot_table("/dev/vdb")
                make_tree(self.efi, TreeTests.WINDOWS)
                m.mounts.add(str(self.efi))
                j.snapshot_esp("/dev/vdb1")
                j.mark("boot")
                TreeTests.install_like_avalos(SimpleNamespace(root=self.efi))
                (self.efi / "EFI/Microsoft/Boot/BCD").write_bytes(b"otro")          # -> sin restaurar
                m.fw.entries = {"0000": WIN, "0001": GRUB_NEW, "0005": "UEFI: raro\tPCI(0)"}
                m.fw.order = ["0001", "0000", "0005"]
                m.disks["/dev/vdb"].dump = NEW_DUMP
                j.rollback(False)
                self.assertGreaterEqual(len(s.lines), 6)
                for _cls, msg in s.lines:
                    self.assertNotRegex(msg, r"[{}]", msg)
                j.mark_format("/dev/vdb")                                           # y el caso «ya se formateó»
                s.lines.clear()
                j2 = rb.InstallJournal(s)
                j2.snapshot_table("/dev/vdb")
                j2.rollback(False)
                self.assertTrue(s.lines)

    def test_unavailable_firmware_message_renders_in_every_language(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                s = FakeSession(Machine(), lang)
                s.machine.fail["efibootmgr"] = -1
                j = rb.InstallJournal(s)
                j.snapshot_firmware(True)
                j.mark("boot")
                j.rollback(False)
                self.assertIn("efibootmgr", s.text)
                self.assertNotRegex(s.text, r"[{}]")



class TranslationTests(unittest.TestCase):
    def test_every_key_used_is_translated_and_none_is_dead(self):
        src = (ROOT / "scripts/avalos_installer/system/rollback.py").read_text(encoding="utf-8")
        used = set(re.findall(r'"(rb-[a-z-]+)"', src))
        self.assertGreater(len(used), 15)
        for lang in LANGS:
            tr = translations.TRANSLATIONS[lang]
            have = {k for k in tr if k.startswith("rb-")}
            self.assertEqual(have, used, lang)

    def test_placeholders_match_english(self):
        en = translations.TRANSLATIONS["en"]
        for key in (k for k in en if k.startswith("rb-")):
            want = set(re.findall(r"\{(\w+)\}", en[key]))
            for lang in LANGS:
                got = set(re.findall(r"\{(\w+)\}", translations.TRANSLATIONS[lang][key]))
                self.assertEqual(got, want, f"{lang}:{key}")

    def test_disk_not_found_message_in_every_language(self):
        for lang in LANGS:
            tpl = translations.TRANSLATIONS[lang]["err-disk-not-found"]
            self.assertIn("{dev_name}", tpl, lang)
            self.assertEqual(set(re.findall(r"\{(\w+)\}", tpl)), {"dev_name"}, lang)



# ── El flujo real de particionado: diario antes de lo destructivo ─────────
class PartitionFlow(unittest.TestCase):
    """Corre partition_and_format de verdad (con comandos simulados) y comprueba el orden de
    las marcas del diario: copia de la tabla antes de wipefs, marca antes de cada mkfs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-flow-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.m = Machine()
        self.m.disks["/dev/vdb"] = FakeDisk(ORIG_DUMP)
        self.s = FakeSession(self.m, "es")
        for name, value in (("ROLLBACK_DIR", self.tmp / "rb"), ("ESP_PROBE_DIR", self.tmp / "probe"),
                            ("MOUNT_EFI", self.tmp / "efi")):
            p = mock.patch.object(rb, name, value)
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch.object(rb, "run_command", self.m.probe),
                  mock.patch.object(part_mod.time, "sleep", lambda *_: None),
                  mock.patch.object(part_mod.subprocess, "run", lambda *a, **k: None),
                  mock.patch.object(part_mod, "_in_use", lambda *a, **k: [])):
            p.start()
            self.addCleanup(p.stop)
        self.disk_files = {}
        patch_edges(self, self.disk_files)
        self.j = rb.InstallJournal(self.s)
        self.s.journal = self.j
        spy = self.j
        orig_snap, orig_mark = spy.snapshot_table, spy.mark_format
        spy.snapshot_table = lambda dev: (self.s.events.append(("journal", "snapshot_table")), orig_snap(dev))[1]
        spy.mark_format = lambda dev: (self.s.events.append(("journal", "mark_format")), orig_mark(dev))[1]
        self._real_run = self.m.run
        self.m.run = self._sim

    def _sim(self, cmd):
        disk = self.m.disks["/dev/vdb"]
        text = " ".join(cmd)
        img = self.disk_files.get("/dev/vdb")
        if cmd[0] == "wipefs":
            if self.fail_on == "wipefs":
                return 1, ""
            disk.dump = None
            if img:
                scribble(img, wipefs=True, parted=False)
            return 0, ""
        if cmd[0] == "parted":
            if img:
                scribble(img, wipefs=False, parted=True)                 # aunque parted falle, pudo escribir
            if self.fail_on == "parted":
                return 1, ""
            disk.dump = NEW_DUMP
            return 0, ""
        if cmd[0] == "mkfs.btrfs" and self.fail_on == "mkfs.btrfs":
            return 1, ""
        if cmd[0] == "mkfs.fat" and self.fail_on == "mkfs.fat":
            return 1, ""
        return self._real_run(cmd)

    fail_on = None

    def run_auto(self, fail_on):
        self.fail_on = fail_on
        ctx = SimpleNamespace(manual_mode=False, usb_mode=False)
        return part_mod.partition_and_format(
            self.s, ctx, "/dev/vdb", "vdb", {"model": "QEMU", "size_human": "20 GB", "montajes": []}, True)

    def cmd_index(self, prefix):
        return next(i for i, e in enumerate(self.s.events) if e[0] == "cmd" and e[1][0] == prefix)

    def test_auto_success_marks_in_order(self):
        res = self.run_auto(None)
        self.assertIsNotNone(res)
        ev = self.s.events
        self.assertLess(ev.index(("journal", "snapshot_table")), self.cmd_index("wipefs"))
        self.assertLess(ev.index(("journal", "mark_format")), self.cmd_index("mkfs.fat"))
        self.assertLess(self.cmd_index("parted"), self.cmd_index("mkfs.fat"))
        self.assertEqual(self.j.phase, "format")

    def test_auto_parted_failure_is_rolled_back_to_the_original_table(self):
        self.assertIsNone(self.run_auto("parted"))
        self.assertEqual(self.j.phase, "table")
        self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.m.disks["/dev/vdb"].dump), rb.normalize_dump(ORIG_DUMP))
        self.assertIn("restaurada y verificada", self.s.text)

    def test_auto_wipefs_failure_leaves_disk_untouched(self):
        self.assertIsNone(self.run_auto("wipefs"))
        self.j.rollback(False)
        self.assertEqual(self.m.disks["/dev/vdb"].dump, ORIG_DUMP)
        self.assertEqual(self.m.ran("sh", "-c"), [])

    def test_auto_mkfs_failure_is_past_the_point_of_no_return(self):
        for kind in ("mkfs.fat", "mkfs.btrfs"):
            with self.subTest(kind=kind):
                self.m.disks["/dev/vdb"].dump = ORIG_DUMP
                self.j = rb.InstallJournal(self.s)
                self.s.journal = self.j
                self.s.lines.clear()
                self.assertIsNone(self.run_auto(kind))
                self.assertEqual(self.j.phase, "format")
                self.j.rollback(False)
                self.assertEqual(self.m.disks["/dev/vdb"].dump, NEW_DUMP)
                self.assertEqual(self.m.ran("sh", "-c"), [])
                self.assertIn("no se pueden recuperar", self.s.text)

    def test_manual_mode_marks_before_each_mkfs_and_never_snapshots_the_table(self):
        blkid = {"/dev/vdb1": "", "/dev/vdb2": ""}
        def fake_blkid(cmd, timeout=30):
            return 0, blkid.get(cmd[-1], ""), ""
        ctx = SimpleNamespace(manual_mode=True, usb_mode=False, manual_efi_partition="/dev/vdb1",
                              manual_root_partition="/dev/vdb2", manual_existing_subvolumes=[])
        with mock.patch.object(part_mod, "run_command", fake_blkid):
            self.fail_on = None
            res = part_mod.partition_and_format(self.s, ctx, "/dev/vdb", "vdb",
                                                {"model": "QEMU", "size_human": "20 GB", "montajes": []}, True)
        self.assertIsNotNone(res)
        marks = [i for i, e in enumerate(self.s.events) if e == ("journal", "mark_format")]
        mkfs = [i for i, e in enumerate(self.s.events) if e[0] == "cmd" and e[1][0].startswith("mkfs")]
        self.assertEqual(len(mkfs), 2)
        for i in mkfs:
            self.assertTrue(any(mk < i for mk in marks))
        self.assertNotIn(("journal", "snapshot_table"), self.s.events)
        self.assertEqual(self.m.ran("wipefs"), [])

    def test_manual_mode_reusing_filesystems_does_not_mark_format(self):
        ctx = SimpleNamespace(manual_mode=True, usb_mode=False, manual_efi_partition="/dev/vdb1",
                              manual_root_partition="/dev/vdb2", manual_existing_subvolumes=["@"])
        with mock.patch.object(part_mod, "run_command", lambda cmd, timeout=30: (0, "vfat" if cmd[-1].endswith("1") else "btrfs", "")):
            res = part_mod.partition_and_format(self.s, ctx, "/dev/vdb", "vdb",
                                                {"model": "QEMU", "size_human": "20 GB", "montajes": []}, True)
        self.assertIsNotNone(res)
        self.assertNotIn(("journal", "mark_format"), self.s.events)
        self.assertEqual(self.j.phase, "init")

    def test_auto_parted_failure_restores_the_disk_edges_byte_for_byte(self):
        img = self.tmp / "vdb.img"
        original = bytearray(os.urandom(8 * 1024 * 1024))
        original[:446] = b"WINDOWS-MBR-CODE".ljust(446, b"\x90")
        img.write_bytes(bytes(original))
        self.disk_files["/dev/vdb"] = img
        self.assertIsNone(self.run_auto("parted"))
        self.assertNotEqual(img.read_bytes(), bytes(original))        # wipefs + parted sí dejaron huella
        self.j.rollback(False)
        self.assertEqual(img.read_bytes(), bytes(original))
        self.assertIn("restaurada y verificada", self.s.text)

    def test_auto_mkfs_failure_leaves_the_edges_alone(self):
        img = self.tmp / "vdb.img"
        original = os.urandom(8 * 1024 * 1024)
        img.write_bytes(original)
        self.disk_files["/dev/vdb"] = img
        self.assertIsNone(self.run_auto("mkfs.btrfs"))
        scribbled = img.read_bytes()
        self.assertNotEqual(scribbled, original)
        self.j.rollback(False)
        self.assertEqual(img.read_bytes(), scribbled)



# ── run_installation de punta a punta (pasos simulados, orquestador real) ──
class SmokeSession(FakeSession):
    rollback_memory = None

    def __init__(self, machine, lang="es"):
        super().__init__(machine, lang)
        self._config_ready = SimpleNamespace(is_set=lambda: True, wait=lambda timeout=None: True)
        self.pending_context = SimpleNamespace(
            password="pw", username="jeff", usb_mode=False, bootloader="grub", install_bore=False,
            install_gaming=False, target_disk=None, manual_mode=False, lang="es", keymap="us",
            hostname="pc", timezone="UTC")
        self.completed = 0
        self.__dict__["_inst"] = False

    @property
    def _installing(self):
        return self.__dict__["_inst"]

    @_installing.setter
    def _installing(self, value):
        self.__dict__["_inst"] = value
        self.events.append(("installing", value))

    def info(self, *a, **k): pass
    def badges(self, *a, **k): pass
    def progress(self, *a, **k): pass
    def label(self, *a, **k): pass
    def start_timer(self): pass
    def stop_timer(self): pass
    def finalize_log(self): pass
    def report_log_destinations(self): pass

    def install_complete(self, info):
        self.completed += 1


class RunInstallationSmoke(Base):
    """Cada escenario corre run_installation de verdad; solo los pasos que tocan el sistema son
    simulados. Comprueba CUÁNDO se dispara el rollback y QUÉ deshace en cada tipo de fallo."""

    def setUp(self):
        super().setUp()
        self.s = SmokeSession(self.m, "es")
        self.j = None
        make_tree(self.efi, TreeTests.WINDOWS)
        self.windows_esp = tree_state(self.efi)
        self.m.mounts.add(str(self.efi))
        self.m.fw = FakeFirmware({"0000": WIN, "0002": USB, "0003": UBU}, ["0000", "0003"])
        self.m.disks["/dev/vdb"] = FakeDisk(ORIG_DUMP)
        self.opt = dict(partition="ok", bootloader="ok", user="ok", locale="ok", aur="ok", abort_after_bootloader=False)
        self.partition_calls = []

    def stubs(self):
        o, s, m, efi = self.opt, self.s, self.m, self.efi

        def partition_and_format(session, ctx, dev, dev_name, disco, uefi):
            self.partition_calls.append(dev)
            session.journal.snapshot_table(dev)
            m.disks[dev].dump = None                       # wipefs
            if o["partition"] == "fail-before-format":
                m.disks[dev].dump = NEW_DUMP               # parted dejó una tabla nueva y luego falló
                return None
            m.disks[dev].dump = NEW_DUMP
            session.journal.mark_format(dev)               # primer mkfs
            return None if o["partition"] == "fail-after-format" else SimpleNamespace(
                root_device="/dev/vdb2", efi_device="/dev/vdb1")

        def install_bootloader(session, ctx, dev, root, uefi, ucode, kernel):
            TreeTests.install_like_avalos(SimpleNamespace(root=efi))
            m.fw.entries["0004"] = GRUB_NEW
            m.fw.order = ["0004"] + m.fw.order
            if o["abort_after_bootloader"]:
                session._aborted = True
            return o["bootloader"] == "ok"

        def configure_locale(session, ctx, kernel):
            if o["locale"] == "raise":
                raise RuntimeError("locale explotó")
            return True

        def install_aur(session, ctx):
            if o["aur"] == "raise":
                raise RuntimeError("aur explotó")

        noop = lambda *a, **k: None
        return dict(
            list_disks=lambda: [
                {"name": "vdb", "es_arranque": False, "size_b": 64e9, "size_human": "64 GB", "model": "", "montajes": []},
                {"name": "sda", "es_arranque": True, "size_b": 8e9, "size_human": "8 GB", "model": "USB", "montajes": []}],
            detect_cpu_arch_level=lambda: "x86-64-v3", detect_gpu=lambda: {"vendor": "amd", "model": "X"},
            detect_microcode=lambda: "amd-ucode", is_uefi=lambda: True, detect_target_disk_type=lambda d: "ssd",
            diagnose_network=lambda: SimpleNamespace(usable=True, verdict="ok", has_wifi=False,
                                                     lines=lambda: [], text_params=lambda: {}),
            check_tools=lambda: {}, partition_and_format=partition_and_format,
            mount_filesystems=lambda *a, **k: True, check_disk_space=lambda *a: True,
            sync_time=noop, optimize_mirrors=noop, run_pacstrap=lambda *a, **k: "linux",
            generate_fstab=lambda *a: True, configure_locale=configure_locale,
            install_bootloader=install_bootloader, configure_services=noop, configure_optimizations=noop,
            create_user=lambda *a: o["user"] == "ok", configure_repos=noop, install_aur=install_aur,
            enable_dns_over_tls=noop, configure_hyprland=noop)

    def run_flow(self):
        with mock.patch.multiple(install_mod, **self.stubs()), mock.patch.object(install_mod.time, "sleep", lambda *_: None), \
                mock.patch.object(install_mod, "MOUNT_ROOT", self.tmp / "no-existe"):
            install_mod.run_installation(self.s)

    def idx(self, pred):
        return next(i for i, e in enumerate(self.s.events) if pred(e))

    def assert_rolled_back_before_releasing(self):
        released = self.idx(lambda e: e == ("installing", False))
        self.assertLess(self.idx(lambda e: e[0] == "cmd" and e[1][:2] == ["efibootmgr", "-b"]), released)

    def test_success_leaves_everything_and_cleans_up(self):
        self.run_flow()
        self.assertEqual(self.s.completed, 1)
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [])
        self.assertIn("0004", self.m.fw.entries)                      # el arranque nuevo se queda
        self.assertNotIn("Rollback", self.s.text)
        self.assertFalse((self.tmp / "rb").exists())
        self.assertFalse(self.s.errors)
        self.assertEqual([e for e in self.s.events if e[0] == "installing"], [("installing", True), ("installing", False)])

    def test_bootloader_failure_restores_firmware_and_esp_but_not_the_formatted_disk(self):
        self.opt["bootloader"] = "fail"
        self.run_flow()
        self.assertEqual(self.s.completed, 0)
        self.assertEqual(self.m.fw.order, ["0000", "0003"])
        self.assertEqual(set(self.m.fw.entries), {"0000", "0002", "0003"})
        self.assertEqual(tree_state(self.efi), self.windows_esp)
        self.assertEqual(self.m.disks["/dev/vdb"].dump, NEW_DUMP)     # ya estaba formateado
        self.assertEqual(self.m.ran("sh", "-c"), [])
        self.assertIn("no se pueden recuperar", self.s.text)
        self.assert_rolled_back_before_releasing()

    def test_user_creation_failure_still_rolls_the_boot_config_back(self):
        self.opt["user"] = "fail"
        self.run_flow()
        self.assertEqual(tree_state(self.efi), self.windows_esp)
        self.assertEqual(set(self.m.fw.entries), {"0000", "0002", "0003"})
        self.assert_rolled_back_before_releasing()

    def test_cancel_right_after_the_bootloader_is_rolled_back_too(self):
        self.opt["abort_after_bootloader"] = True
        self.run_flow()
        self.assertEqual(self.s.completed, 0)
        self.assertEqual(set(self.m.fw.entries), {"0000", "0002", "0003"})
        self.assertEqual(tree_state(self.efi), self.windows_esp)
        self.assert_rolled_back_before_releasing()

    def test_late_failure_after_the_user_exists_keeps_the_bootable_system(self):
        self.opt["aur"] = "raise"
        self.run_flow()
        self.assertEqual(self.s.completed, 0)
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [])
        self.assertIn("0004", self.m.fw.entries)
        self.assertIn("AvalOS/vmlinuz-linux", tree_state(self.efi)[0])
        self.assertIn("ya arrancaba", self.s.text)
        self.assertTrue(any("err-unexpected" in str(m) or "aur explotó" in str(m) for m in self.s.errors + [self.s.text]))

    def test_exception_before_the_bootloader_restores_only_what_applies(self):
        self.opt["locale"] = "raise"
        self.run_flow()
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [])          # el bootloader ni empezó
        self.assertEqual(self.m.disks["/dev/vdb"].dump, NEW_DUMP)     # formateado: sin retorno
        self.assertIn("no se pueden recuperar", self.s.text)
        self.assertTrue(self.s.errors)

    def test_failure_between_wipe_and_format_gets_the_original_table_back(self):
        self.opt["partition"] = "fail-before-format"
        self.run_flow()
        self.assertEqual(rb.normalize_dump(self.m.disks["/dev/vdb"].dump), rb.normalize_dump(ORIG_DUMP))
        self.assertIn("restaurada y verificada", self.s.text)
        released = self.idx(lambda e: e == ("installing", False))
        self.assertLess(self.idx(lambda e: e[0] == "cmd" and e[1][:2] == ["sh", "-c"]), released)

    def test_failure_after_format_never_restores_the_table(self):
        self.opt["partition"] = "fail-after-format"
        self.run_flow()
        self.assertEqual(self.m.disks["/dev/vdb"].dump, NEW_DUMP)
        self.assertEqual(self.m.ran("sh", "-c"), [])

    def test_retry_after_a_failed_attempt_succeeds_and_keeps_the_original_state(self):
        self.opt["bootloader"] = "fail"
        self.run_flow()                                                    # intento 1: falla y deshace
        first_fw = self.s.rollback_memory["fw"]
        self.opt["bootloader"] = "ok"
        self.m.fw.entries.pop("0004", None)
        self.run_flow()                                                    # intento 2: termina bien
        self.assertEqual(self.s.completed, 1)
        self.assertIs(self.s.rollback_memory["fw"], first_fw)
        self.assertIn("0004", self.m.fw.entries)
        self.assertEqual([e for e in self.s.events if e[0] == "installing"].count(("installing", False)), 2)

    def test_kill_switch_skips_the_whole_rollback(self):
        self.opt["bootloader"] = "fail"
        with mock.patch.dict(os.environ, {rb.KILL_SWITCH_ENV: "1"}):
            self.run_flow()
        self.assertIn("0004", self.m.fw.entries)
        self.assertEqual(self.m.ran("efibootmgr", "-b"), [])

    def test_early_fatal_error_before_touching_anything_is_silent(self):
        stubs = self.stubs()
        stubs["list_disks"] = lambda: [{"name": "sda", "es_arranque": True, "size_b": 8e9, "size_human": "8 GB", "model": "", "montajes": []}]
        with mock.patch.multiple(install_mod, **stubs), mock.patch.object(install_mod.time, "sleep", lambda *_: None):
            install_mod.run_installation(self.s)
        self.assertEqual(self.m.calls, [])
        self.assertNotIn("Rollback", self.s.text)
        self.assertNotIn("Deshaciendo", self.s.text)

    def test_selected_disk_that_disappeared_fails_closed_instead_of_using_another(self):
        self.s.pending_context.target_disk = "sdz"
        self.run_flow()
        self.assertEqual(self.partition_calls, [])                    # jamás se particiona OTRO disco
        self.assertEqual(self.m.calls, [])
        self.assertEqual(self.s.completed, 0)
        self.assertTrue(any("sdz" in str(e) for e in self.s.errors))

    def test_dev_prefix_in_the_selection_is_accepted(self):
        self.s.pending_context.target_disk = "/dev/vdb"
        self.run_flow()
        self.assertEqual(self.partition_calls, ["/dev/vdb"])
        self.assertEqual(self.s.completed, 1)

    def test_no_selection_uses_the_first_available_disk(self):
        self.s.pending_context.target_disk = None
        self.run_flow()
        self.assertEqual(self.partition_calls, ["/dev/vdb"])

    def test_the_boot_disk_is_still_refused(self):
        self.s.pending_context.target_disk = "sda"
        self.run_flow()
        self.assertEqual(self.partition_calls, [])
        self.assertTrue(any("sda" in str(e) for e in self.s.errors))



# ── Bordes del disco: restauración byte a byte ────────────────────────────
class EdgesTests(Base):
    DEV = "/dev/vdb"
    MIB = 1024 * 1024

    def make_disk(self, size=8 * 1024 * 1024):
        data = bytearray(os.urandom(size))
        data[:446] = b"WINDOWS-MBR-CODE".ljust(446, b"\x90")
        path = self.tmp / "vdb.img"
        path.write_bytes(bytes(data))
        self.disk_files[self.DEV] = path
        return path, bytes(data)

    def start(self, dump=ORIG_DUMP):
        self.m.disks[self.DEV] = FakeDisk(dump)
        self.j.snapshot_table(self.DEV)

    def test_restores_boot_code_table_copy_and_disk_level_signatures_byte_for_byte(self):
        path, original = self.make_disk()
        self.start()
        scribble(path)
        self.assertNotEqual(path.read_bytes(), original)
        middle = 3 * self.MIB
        with open(path, "r+b") as fh:
            fh.seek(middle)
            fh.write(b"MIDDLE-UNTOUCHED")
        self.j.rollback(False)
        expected = bytearray(original)
        expected[middle:middle + 16] = b"MIDDLE-UNTOUCHED"            # el medio del disco no se toca
        self.assertEqual(path.read_bytes(), bytes(expected))
        self.assertEqual(path.read_bytes()[:446], b"WINDOWS-MBR-CODE".ljust(446, b"\x90"))
        self.assertIn("restaurada y verificada", self.s.text)
        self.assertEqual(self.m.ran("sh", "-c"), [])                  # no hizo falta sfdisk
        self.assertEqual(self.s.classes()[-1], "ok")

    def test_unchanged_disk_is_never_written(self):
        path, original = self.make_disk()
        self.start()
        with mock.patch.object(rb, "write_edges", side_effect=AssertionError("no debe escribir")):
            self.j.rollback(False)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("seguía siendo la original", self.s.text)

    def test_never_restored_once_formatting_started(self):
        path, original = self.make_disk()
        self.start()
        scribble(path)
        scribbled = path.read_bytes()
        self.j.mark_format(self.DEV)
        self.j.rollback(False)
        self.assertEqual(path.read_bytes(), scribbled)
        self.assertIn("no se pueden recuperar", self.s.text)

    def test_a_different_disk_with_the_same_name_is_not_touched(self):
        path, original = self.make_disk()
        self.start()
        other = os.urandom(4 * self.MIB)
        path.write_bytes(other)                                       # «otro disco» (tamaño distinto)
        with mock.patch.object(rb, "write_edges", side_effect=AssertionError("no debe escribir")):
            self.j.rollback(False)
        self.assertEqual(path.read_bytes(), other)
        self.assertIn(str(len(original)), self.s.text)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_write_failure_tells_how_to_restore_by_hand_with_dd(self):
        path, _ = self.make_disk()
        self.start()
        scribble(path)
        with mock.patch.object(rb, "write_edges", side_effect=OSError("solo lectura")):
            self.j.rollback(False)
        self.assertIn("dd if=", self.s.text)
        self.assertIn("solo lectura", self.s.text)
        self.assertIn(str(self.tmp / "rb"), self.s.text)
        self.assertEqual(self.s.classes()[-1], "warn")

    def test_read_back_is_verified(self):
        path, _ = self.make_disk()
        self.start()
        scribble(path)
        def bad_write(dev, edges):
            _REAL_WRITE_EDGES(str(path), edges)
            with open(path, "r+b") as fh:
                fh.seek(100)
                fh.write(b"\xff")                                    # algo quedó mal
        with mock.patch.object(rb, "write_edges", bad_write):
            self.j.rollback(False)
        self.assertIn("no coincide", self.s.text)
        self.assertNotIn("restaurada y verificada", self.s.text)

    def test_disk_without_partition_table_but_with_signatures_is_restored(self):
        path, original = self.make_disk()
        self.start(dump=None)                                         # sfdisk no ve tabla (p. ej. un miembro RAID/LUKS entero)
        scribble(path)
        self.j.rollback(False)
        self.assertEqual(path.read_bytes(), original)

    def test_small_disks_head_only_and_head_plus_short_tail(self):
        for size in (1 * self.MIB, 1536 * 1024, 3 * self.MIB):
            with self.subTest(size=size):
                self.s.rollback_memory = None
                j = self.new_journal()
                self.m.disks[self.DEV] = FakeDisk(ORIG_DUMP)
                path, original = self.make_disk(size)
                j.snapshot_table(self.DEV)
                with open(path, "r+b") as fh:
                    fh.write(b"\x77" * 512)
                    fh.seek(size - 512)
                    fh.write(b"\x77" * 512)
                j.rollback(False)
                self.assertEqual(path.read_bytes(), original)

    def test_backup_files_follow_the_sfdisk_wipefs_dd_convention(self):
        path, original = self.make_disk()
        self.start()
        head = self.tmp / "rb" / "edges-vdb-0x00000000.bak"
        tail = self.tmp / "rb" / "edges-vdb-0x00700000.bak"
        self.assertEqual(head.read_bytes(), original[:self.MIB])
        self.assertEqual(tail.read_bytes(), original[7 * self.MIB:])
        self.assertEqual(head.stat().st_mode & 0o777, 0o600)
        cmds = [l for l in self.s.logfile.diag_lines if l.startswith("edges-backup")]
        self.assertEqual(len(cmds), 2)
        self.assertTrue(any("seek=$((0x00700000))" in c and "bs=1 conv=notrunc" in c for c in cmds))

    def test_retry_keeps_the_first_snapshot_and_does_not_read_the_disk_again(self):
        path, _ = self.make_disk()
        self.start()
        first = self.j.mem["edges"][self.DEV]
        scribble(path)
        self.j.rollback(False)
        j2 = self.new_journal()
        with mock.patch.object(rb, "read_edges", wraps=rb.read_edges) as spy:
            j2.snapshot_table(self.DEV)
        spy.assert_not_called()
        self.assertIs(j2.mem["edges"][self.DEV], first)

    def test_success_removes_the_backups(self):
        self.make_disk()
        self.start()
        self.j.rollback(True)
        self.assertFalse((self.tmp / "rb").exists())

    def test_unreadable_disk_falls_back_to_the_text_dump(self):
        self.start()                                                  # sin archivo asignado: read_edges -> None
        self.assertIsNone(self.j.mem["edges"][self.DEV])
        self.m.disks[self.DEV].dump = NEW_DUMP
        self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.m.disks[self.DEV].dump), rb.normalize_dump(ORIG_DUMP))


# ── Cableado en el orquestador (texto del código) ─────────────────────────
class WiringTests(unittest.TestCase):
    @staticmethod
    def read(rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_install_py_hooks_and_order(self):
        src = self.read("scripts/avalos_installer/core/install.py")
        self.assertIn("from avalos_installer.system.rollback import InstallJournal", src)
        idx = lambda s, start=0: src.index(s, start)
        self.assertLess(idx("journal = InstallJournal(session)"), idx("    try:\n        session.label(session.t(\"label-detecting-hw\"))"))
        self.assertLess(idx("journal.snapshot_firmware(uefi)"), idx("result = partition_and_format("))
        self.assertLess(idx("journal.snapshot_esp(result.efi_device)"), idx("journal.mark(\"boot\")"))
        self.assertLess(idx("journal.mark(\"boot\")"), idx("if not install_bootloader("))
        self.assertLess(idx("if not create_user(session, ctx):"), idx("journal.mark(\"usable\")"))
        self.assertLess(idx("session.step(\"umount\", \"done\")"), idx("completed = True"))
        finally_at = idx("    finally:\n")
        self.assertLess(finally_at, idx("journal.rollback(completed)"))
        self.assertLess(idx("journal.rollback(completed)"), idx("session._installing = False", finally_at))

    def test_completed_is_set_only_once_and_after_the_last_step(self):
        src = self.read("scripts/avalos_installer/core/install.py")
        self.assertEqual(src.count("completed = True"), 1)
        self.assertEqual(src.count("completed = False"), 1)

    def test_partition_py_has_a_mark_before_every_mkfs_branch(self):
        src = self.read("scripts/avalos_installer/system/partition.py")
        self.assertEqual(src.count("_mark_format(session, dev)"), 3)
        self.assertEqual(src.count("snapshot_table(dev)"), 1)
        self.assertLess(src.index("snapshot_table(dev)"), src.index('["wipefs", "-a", dev]'))

    def test_main_waits_for_the_install_thread(self):
        main = self.read("scripts/avalos_installer/__main__.py")
        api = self.read("scripts/avalos_installer/ui/api.py")
        self.assertIn("session._install_thread = t", main)
        self.assertIn("t.join(timeout=90)", main)
        self.assertLess(main.index("webview.start("), main.index("t.join(timeout=90)"))
        self.assertIn("self.session._install_thread = t", api)

    def test_session_declares_the_attributes(self):
        src = self.read("scripts/avalos_installer/core/session.py")
        self.assertIn("self.journal = None", src)
        self.assertIn("self.rollback_memory = None", src)

    def test_install_py_no_longer_falls_back_silently_to_another_disk(self):
        src = self.read("scripts/avalos_installer/core/install.py")
        self.assertNotIn('next((d for d in discos if d["name"] == dev_name), disponibles[0])', src)
        self.assertIn('session.t("err-disk-not-found", dev_name=dev_requested)', src)

    @staticmethod
    def live_packages():
        """La lista de paquetes del live, tal como la genera el workflow de la ISO (va en base64)."""
        import base64
        import subprocess
        wf = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
        m = re.search(r"printf '%s' \"([A-Za-z0-9+/=]+)\" \| base64 -d > /tmp/pypkgpyeof\.py", wf)
        assert m, "no se encontró el generador de packages.x86_64 en build-iso.yml"
        with tempfile.TemporaryDirectory() as d:
            gen, out = Path(d) / "gen.py", Path(d) / "packages.x86_64"
            gen.write_text(base64.b64decode(m.group(1)).decode("utf-8"), encoding="utf-8")
            subprocess.run([sys.executable, str(gen), str(out), "linux"], check=True, capture_output=True)
            return {l.strip() for l in out.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}

    def test_live_iso_ships_the_tools_the_installer_and_rollback_need(self):
        pk = self.live_packages()
        # efibootmgr: sin él el rollback del NVRAM no hace nada; el resto: lo que usan particionado y formato
        for needed in ("efibootmgr", "parted", "gptfdisk", "dosfstools", "e2fsprogs", "btrfs-progs",
                       "arch-install-scripts", "base"):
            self.assertIn(needed, pk, f"el live no trae {needed}")

    def test_ci_installs_the_disk_tools_so_the_real_tool_tests_do_not_skip(self):
        wf = self.read(".github/workflows/validate-configs.yml")
        for tool in ("parted", "fdisk", "e2fsprogs"):
            self.assertIn(tool, wf)

    def test_grub_uses_its_own_bootloader_id_in_both_installers_and_rollback_recognises_it(self):
        """grub-install borra las entradas UEFI con el mismo id y pisa EFI/<id>/: con el genérico
        «GRUB» una instalación manual de Arch vecina perdería su arranque (Launchpad #1568050)."""
        ids = {rel: set(re.findall(r"--bootloader-id=(\w+)", self.read(rel)))
               for rel in ("scripts/avalos_installer/system/bootloader.py", "scripts/skill_instalar_usb.py")}
        for rel, found in ids.items():
            self.assertEqual(len(found), 1, rel)
            (bid,) = found
            self.assertNotEqual(bid.lower(), "grub", rel)
            self.assertTrue(rb.is_ours(bid), f"{rel}: el rollback no reconocería «{bid}» como nuestro")
            self.assertIn(f"efi/{bid.lower()}", rb.ESP_TRACKED, f"{rel}: EFI/{bid} no se respalda en la ESP")
        self.assertEqual(len({next(iter(f)) for f in ids.values()}), 1, "los dos instaladores deben usar el mismo id")



if __name__ == "__main__":
    unittest.main(verbosity=2)
