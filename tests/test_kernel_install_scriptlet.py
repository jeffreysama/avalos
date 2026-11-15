"""pkgs/linux-avalos/linux-avalos.install corre como root en cada instalación/actualización/eliminación del kernel.
Aquí se prueba la detección de la versión instalada con un /usr/lib/modules falso. Los kernels -bore y -compat
reutilizan este archivo con `sed 's|linux-avalos|linux-avalos-bore|g'` (build-kernel.yml): se prueba también esa variante."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "pkgs" / "linux-avalos" / "linux-avalos.install"


class KernelVersionDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-install-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.modules = self.tmp / "modules"
        self.modules.mkdir()

    def kernel_version(self, pkgbase, text=None):
        script = (text or INSTALL.read_text(encoding="utf-8")).replace("/usr/lib/modules", str(self.modules))
        (self.tmp / "s.sh").write_text(script, encoding="utf-8")
        r = subprocess.run(["bash", "-c", f'source "{self.tmp}/s.sh"; _kernel_version "$1"', "bash", pkgbase], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def make(self, *names):
        for n in names:
            (self.modules / n).mkdir()

    def test_picks_the_newest_version_by_version_order_not_alphabetical_order(self):
        self.make("7.2.9-1-avalos", "7.2.14-1-avalos", "7.2.10-1-avalos")
        self.assertEqual(self.kernel_version("linux-avalos"), "7.2.14-1-avalos")

    def test_a_variant_only_sees_its_own_kernels(self):
        self.make("7.2.14-1-avalos", "7.2.14-1-avalos-bore", "7.2.14-1-avalos-compat", "6.12.1-arch1-1", "7.2.99-1-avalos-bore-extra")
        self.assertEqual(self.kernel_version("linux-avalos"), "7.2.14-1-avalos")
        self.assertEqual(self.kernel_version("linux-avalos-bore"), "7.2.14-1-avalos-bore")
        self.assertEqual(self.kernel_version("linux-avalos-compat"), "7.2.14-1-avalos-compat")

    def test_nothing_installed_or_no_modules_dir_gives_an_empty_answer_not_an_error(self):
        self.assertEqual(self.kernel_version("linux-avalos"), "")
        shutil.rmtree(self.modules)
        self.assertEqual(self.kernel_version("linux-avalos"), "")

    def test_plain_files_and_odd_names_are_ignored_or_handled(self):
        (self.modules / "9.9.9-1-avalos").write_text("no soy un directorio")
        self.make("7.2.14-1-avalos", "con espacio 7.3-1-avalos", "raro\nsalto-0-avalos")
        self.assertEqual(self.kernel_version("linux-avalos"), "raro\nsalto-0-avalos", "un nombre con salto de línea se trata como UN nombre (NUL-safe)")
        (self.modules / "raro\nsalto-0-avalos").rmdir()
        self.assertEqual(self.kernel_version("linux-avalos"), "con espacio 7.3-1-avalos")

    def test_the_bore_and_compat_scriptlets_derived_by_the_workflow_still_work(self):
        self.make("7.2.14-1-avalos", "7.2.14-1-avalos-bore")
        for variant in ("bore", "compat"):
            with self.subTest(variant=variant):
                derived = INSTALL.read_text(encoding="utf-8").replace("linux-avalos", f"linux-avalos-{variant}")
                (self.modules / f"7.2.14-1-avalos-{variant}").mkdir(exist_ok=True)
                self.assertEqual(self.kernel_version(f"linux-avalos-{variant}", text=derived), f"7.2.14-1-avalos-{variant}")
                self.assertRegex(derived, rf'local _pkgbase="linux-avalos-{variant}"')

    def test_no_ls_pipe_grep_is_left_and_the_scriptlet_parses(self):
        text = INSTALL.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))      # los comentarios pueden nombrarlo
        self.assertIsNone(re.search(r"\bls\b[^\n]*\|\s*grep", code), "ls | grep (SC2010) volvió")
        self.assertEqual(subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
