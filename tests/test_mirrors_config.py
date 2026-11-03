"""Países de los mirrors: una sola lista para el instalador, el reflector del sistema instalado
y la documentación. Antes vivía copiada en cada sitio y al añadir China solo se actualizó una
(el reflector.timer del sistema instalado habría vuelto a dejar el mirrorlist sin ella)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from avalos_installer.core.config import MIRROR_COUNTRIES  # noqa: E402

CODES = MIRROR_COUNTRIES.split(",")


class MirrorCountries(unittest.TestCase):
    def test_poland_is_included(self):
        self.assertIn("PL", CODES)

    def test_format_is_what_reflector_accepts(self):
        """Códigos ISO 3166-1 alpha-2 en mayúsculas, separados por coma, sin espacios ni repetidos."""
        self.assertTrue(all(re.fullmatch(r"[A-Z]{2}", c) for c in CODES), CODES)
        self.assertEqual(len(CODES), len(set(CODES)))

    def test_the_installer_modules_use_the_constant_instead_of_a_copy(self):
        for rel in ("network/mirrors.py", "desktop/hyprland.py"):
            src = (ROOT / "scripts" / "avalos_installer" / rel).read_text(encoding="utf-8")
            self.assertIn("MIRROR_COUNTRIES", src, rel)
            self.assertNotRegex(src, r"SV,US", rel)

    def test_every_list_in_the_install_guide_is_the_installer_list(self):
        guide = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        found = re.findall(r"(?:--country |installer uses )([A-Z]{2}(?:,[A-Z]{2})+)", guide)
        self.assertGreaterEqual(len(found), 3, "la guía debería mencionar la lista 3 veces")
        self.assertEqual(set(found), {MIRROR_COUNTRIES})


if __name__ == "__main__":
    unittest.main(verbosity=2)
