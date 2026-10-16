"""Pulido que salió del log de la primera instalación real (laptop, 11 oct 2026):

  · wireless-regdb: sin regulatory.db cfg80211 no puede cargar las reglas de cada país («Direct firmware
    load for regulatory.db failed with error -2») y algunos chips no levantan el Wi-Fi (Arch FS#59434).
  · El asistente moría a los 10 minutos de espera con «Timeout expired. Close and reopen the installer».
  · «Limpiando montajes pendientes antes de particionar…» aparecía también al final de la instalación.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_rollback as _tr  # noqa: E402  (solo su ayudante live_packages(); sin importar la clase)
import translations  # noqa: E402
from avalos_installer.core import config  # noqa: E402
from avalos_installer.core import install as install_mod  # noqa: E402
from avalos_installer.system import pacstrap  # noqa: E402

LANGS = ("en", "es", "zh", "ja")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class WirelessRegdb(unittest.TestCase):
    def test_the_installed_system_gets_it(self):
        packages = set()
        for name in dir(pacstrap):
            value = getattr(pacstrap, name)
            if name.endswith("_PKGS") and isinstance(value, (list, tuple, set)):
                packages |= set(value)
        self.assertIn("wireless-regdb", packages)

    def test_legacy_installer_and_manual_guide_install_it_too(self):
        self.assertIn('"wireless-regdb"', read("scripts/skill_instalar_usb.py"))
        self.assertRegex(read("docs/INSTALL.md"), r"nm-connection-editor wireless-regdb")

    def test_the_live_iso_ships_it_so_wifi_works_while_installing(self):
        self.assertIn("wireless-regdb", _tr.WiringTests.live_packages())


class WizardTimeout(unittest.TestCase):
    def test_it_is_at_least_an_hour(self):
        self.assertGreaterEqual(config.WIZARD_IDLE_TIMEOUT_S, 3600)

    def test_both_installers_use_the_long_wait_and_not_ten_minutes(self):
        modular = read("scripts/avalos_installer/core/install.py")
        self.assertIn("_config_ready.wait(timeout=WIZARD_IDLE_TIMEOUT_S)", modular)
        self.assertNotRegex(modular, r"_config_ready\.wait\(timeout=600\)\):")
        legacy = read("scripts/skill_instalar_usb.py")
        self.assertIn("_config_lista .wait (timeout =6 *60 *60 )", legacy)
        self.assertNotIn("_config_lista .wait (timeout =600 )", legacy)

    def test_the_modular_installer_waits_that_long_and_reports_an_abandoned_wizard(self):
        waited = []
        session = mock.MagicMock()
        session._config_ready = SimpleNamespace(is_set=lambda: False,
                                                wait=lambda timeout=None: waited.append(timeout) or False)
        session.t = lambda key, **kw: key
        install_mod.run_installation(session)
        self.assertEqual(waited, [config.WIZARD_IDLE_TIMEOUT_S])
        session.error_step.assert_called_once_with("err-timeout")

    def test_closing_the_window_still_wakes_the_wizard_wait_immediately(self):
        """Por eso esperar mucho no deja nada colgado: on_close libera el wait."""
        source = (ROOT / "scripts/avalos_installer/core/session.py").read_text(encoding="utf-8")
        body = source[source.index("def on_close"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn("_config_ready.set()", body)


class CleaningMountsMessage(unittest.TestCase):
    def test_it_no_longer_claims_to_run_before_partitioning(self):
        for lang in LANGS:
            msg = translations.TRANSLATIONS[lang]["log-cleaning-mounts"]
            self.assertTrue(msg.strip(), lang)
            for banned in ("antes de particionar", "before partitioning", "分区前", "パーティション分割の前"):
                self.assertNotIn(banned, msg, lang)


if __name__ == "__main__":
    unittest.main(verbosity=2)
