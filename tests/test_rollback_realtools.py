"""Rollback de la tabla de particiones con las herramientas REALES (wipefs, parted, sfdisk,
mke2fs, debugfs) sobre una imagen de disco en un archivo: sin root, sin dispositivos.

Reproduce los comandos exactos de system/partition.py y comprueba lo que el rollback promete:
  · después de wipefs + parted los datos de las particiones siguen intactos (parted mkpart no
    crea sistemas de archivos y wipefs solo borra firmas);
  · el rollback devuelve el inicio y el final del disco byte a byte, y el archivo que había en
    el sistema de archivos original vuelve a leerse;
  · pasado el primer mkfs ya no se restaura nada (los datos ya no existen).
Si falta alguna herramienta, las pruebas se saltan.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402
from avalos_installer.system import rollback as rb  # noqa: E402

TOOLS = ("parted", "sfdisk", "wipefs", "mke2fs", "debugfs")
SBIN = os.pathsep.join(("/usr/sbin", "/sbin"))      # estas herramientas viven ahí y no siempre están en el PATH


def _tool(name):
    return shutil.which(name, path=os.environ.get("PATH", "") + os.pathsep + SBIN)

MIB = 1024 * 1024
DISK_SIZE = 1024 * MIB                      # imagen dispersa: solo ocupa lo que se escribe
P1_START = 4096                             # sectores (2 MiB): el sistema de archivos con el marcador
P1_SECTORS = 610304                         # 298 MiB
MARKER = "datos que NO se pueden perder\n"
BOOT_CODE = b"WINDOWS-MBR-BOOT-CODE".ljust(446, b"\x90")


def run(*cmd, input=None):
    r = subprocess.run([str(c) for c in cmd], input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"{' '.join(map(str, cmd))} -> rc={r.returncode}\n{r.stderr}{r.stdout}")
    return r.stdout


class RealSession:
    _lang = "es"

    def __init__(self):
        self.lines = []
        self.logfile = types.SimpleNamespace(diag=lambda text: None)
        self.rollback_memory = None

    def t(self, key, **kw):
        return translations.TRANSLATIONS[self._lang][key].format(**kw)

    def log(self, msg, cls="info"):
        self.lines.append((cls, msg))

    def run_cmd(self, cmd, timeout=300, log_cls="info", pre_mkdir=None, abortable=True):
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
        return r.returncode, r.stdout

    @property
    def text(self):
        return "\n".join(m for _c, m in self.lines)


@unittest.skipUnless(all(_tool(t) for t in TOOLS), "faltan herramientas: " + ", ".join(TOOLS))
class RealToolsOnDiskImage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-realtools-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        path_patch = mock.patch.dict(os.environ, {"PATH": os.environ.get("PATH", "") + os.pathsep + SBIN})
        path_patch.start()
        self.addCleanup(path_patch.stop)
        self.img = self.tmp / "disk.img"
        for name, value in (("ROLLBACK_DIR", self.tmp / "rb"), ("ESP_PROBE_DIR", self.tmp / "probe"),
                            ("MOUNT_EFI", self.tmp / "efi")):
            p = mock.patch.object(rb, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.s = RealSession()
        self.j = rb.InstallJournal(self.s)

    # ── la imagen original ─────────────────────────────────────
    def make_disk(self, label):
        with open(self.img, "wb") as fh:
            fh.truncate(DISK_SIZE)
        kind = "name=\"datos\"" if label == "gpt" else ""
        type_ = "L" if label == "gpt" else "83"
        script = (f"label: {label}\nunit: sectors\n\n"
                  f"start={P1_START}, size={P1_SECTORS}, type={type_} {', ' + kind if kind else ''}\n"
                  f"start=614400, size=1433600, type={type_}\n")
        run("sfdisk", self.img, input=script)
        content = self.tmp / "fs"
        content.mkdir()
        (content / "marker.txt").write_text(MARKER)
        run("mke2fs", "-q", "-t", "ext4", "-F", "-d", content, "-E", f"offset={P1_START * 512}", self.img, f"{P1_SECTORS // 2}k")
        if label == "dos":
            with open(self.img, "r+b") as fh:
                fh.write(BOOT_CODE)
        self.original_dump = run("sfdisk", "--dump", self.img)
        self.original_edges = rb.read_edges(str(self.img))
        self.assertEqual(self.marker(), MARKER)

    def marker(self):
        r = subprocess.run(["debugfs", "-R", "cat /marker.txt", f"{self.img}?offset={P1_START * 512}"],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    def dump(self):
        return run("sfdisk", "--dump", self.img)

    def installer_destroys_uefi_layout(self):
        """Lo mismo que system/partition.py en modo automático UEFI, sin el mkfs."""
        run("wipefs", "-a", self.img)
        run("parted", "-s", self.img, "mklabel", "gpt", "mkpart", "ESP", "fat32", "1MiB", "513MiB",
            "set", "1", "esp", "on", "mkpart", "root", "ext4", "513MiB", "100%")

    def installer_destroys_bios_layout(self):
        run("wipefs", "-a", self.img)
        run("parted", "-s", self.img, "mklabel", "msdos", "mkpart", "primary", "ext4", "1MiB", "100%",
            "set", "1", "boot", "on")

    def assert_back_to_original(self):
        back = rb.read_edges(str(self.img))
        self.assertEqual(back.head, self.original_edges.head)
        self.assertEqual(back.tail, self.original_edges.tail)
        self.assertEqual(rb.normalize_dump(self.dump()), rb.normalize_dump(self.original_dump))
        self.assertEqual(self.marker(), MARKER)
        wipefs_list = run("wipefs", self.img)
        return wipefs_list

    # ── pruebas ────────────────────────────────────────────────
    def test_data_survives_wipefs_and_parted_so_restoring_the_table_is_enough(self):
        self.make_disk("gpt")
        self.j.snapshot_table(str(self.img))
        self.installer_destroys_uefi_layout()
        self.assertNotEqual(rb.normalize_dump(self.dump()), rb.normalize_dump(self.original_dump))
        self.assertEqual(self.marker(), MARKER)                    # wipefs y parted no tocaron el sistema de archivos

    def test_gpt_disk_is_restored_byte_for_byte_after_the_installer_replaced_it(self):
        self.make_disk("gpt")
        self.j.snapshot_table(str(self.img))
        self.installer_destroys_uefi_layout()
        self.j.rollback(False)
        listing = self.assert_back_to_original()
        self.assertIn("gpt", listing)
        self.assertIn("restaurada y verificada", self.s.text)

    def test_dos_disk_with_boot_code_gets_the_boot_code_and_no_stale_gpt(self):
        self.make_disk("dos")
        self.j.snapshot_table(str(self.img))
        self.installer_destroys_uefi_layout()                       # parted escribe GPT sobre un disco DOS
        self.assertNotEqual(rb.read_edges(str(self.img)).head[:446], BOOT_CODE)
        self.j.rollback(False)
        listing = self.assert_back_to_original()
        self.assertEqual(rb.read_edges(str(self.img)).head[:446], BOOT_CODE)
        self.assertIn("dos", listing)
        self.assertNotIn("gpt", listing)                            # no queda un GPT viejo flotando

    def test_bios_layout_over_a_gpt_disk(self):
        self.make_disk("gpt")
        self.j.snapshot_table(str(self.img))
        self.installer_destroys_bios_layout()
        self.j.rollback(False)
        listing = self.assert_back_to_original()
        self.assertIn("gpt", listing)

    def test_text_dump_fallback_also_restores_with_the_real_sfdisk(self):
        self.make_disk("gpt")
        with mock.patch.object(rb, "read_edges", lambda dev: None):    # como si el disco no se hubiera podido leer
            self.j.snapshot_table(str(self.img))
            self.installer_destroys_uefi_layout()
            self.j.rollback(False)
        self.assertEqual(rb.normalize_dump(self.dump()), rb.normalize_dump(self.original_dump))
        self.assertEqual(self.marker(), MARKER)
        self.assertIn("restaurada y verificada", self.s.text)

    def test_nothing_is_restored_once_mkfs_ran_and_the_data_really_is_gone(self):
        self.make_disk("gpt")
        self.j.snapshot_table(str(self.img))
        self.installer_destroys_uefi_layout()
        self.j.mark_format(str(self.img))                           # justo antes del primer mkfs
        run("mke2fs", "-q", "-t", "ext4", "-F", "-E", f"offset={1 * MIB}", self.img, f"{512 * 1024}k")
        new_dump = self.dump()
        self.j.rollback(False)
        self.assertEqual(self.dump(), new_dump)                     # la tabla nueva se queda
        self.assertIn("no se pueden recuperar", self.s.text)
        self.assertNotEqual(self.marker(), MARKER)                  # y el dato original, efectivamente, ya no está

    def test_unchanged_disk_is_not_written(self):
        self.make_disk("gpt")
        self.j.snapshot_table(str(self.img))
        before = self.img.stat().st_mtime_ns
        with mock.patch.object(rb, "write_edges", side_effect=AssertionError("no debe escribir")):
            self.j.rollback(False)
        self.assertEqual(self.img.stat().st_mtime_ns, before)
        self.assertIn("seguía siendo la original", self.s.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
