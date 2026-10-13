"""Chequeos del Doctor que habrían detectado los fallos de la primera instalación real:
sin agente de polkit corriendo, pkexec falla y ni la tienda ni Actualizar pueden pedir permisos; y el
remoto de Flathub tiene que estar en la configuración del usuario porque la tienda instala con --user."""
import importlib.machinery
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "es", "zh", "ja")


def load_doctor():
    loader = importlib.machinery.SourceFileLoader("avalos_doctor_under_test", str(ROOT / "scripts" / "avalos-doctor"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PolkitAgentCheck(unittest.TestCase):
    def setUp(self):
        self.doc = load_doctor()
        self.proc = Path(tempfile.mkdtemp(prefix="avalos-proc-"))
        self.addCleanup(shutil.rmtree, self.proc, True)
        for p in (mock.patch.object(self.doc, "PROC", self.proc),
                  mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"})):
            p.start()
            self.addCleanup(p.stop)

    def spawn(self, pid, argv):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

    def test_hyprpolkitagent_started_by_its_real_path_is_found(self):
        self.spawn(311, ["/usr/lib/hyprpolkitagent/hyprpolkitagent"])
        self.assertEqual(self.doc.chk_polkit_agent(), ("ok", "d-polkit-agent-ok", {"name": "hyprpolkitagent"}, None))

    def test_other_well_known_agents_count(self):
        for argv0 in ("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1", "/usr/bin/lxqt-policykit-agent",
                      "/usr/lib/polkit-kde-authentication-agent-1"):
            with self.subTest(agent=argv0):
                shutil.rmtree(self.proc)
                self.proc.mkdir()
                self.spawn(9, [argv0])
                self.assertEqual(self.doc.chk_polkit_agent()[0], "ok")

    def test_no_agent_is_a_warning_with_the_fix_in_the_text(self):
        self.spawn(1, ["/usr/bin/Hyprland"])
        self.spawn(2, ["/usr/bin/waybar"])
        status, key, args, action = self.doc.chk_polkit_agent()
        self.assertEqual((status, key), ("warn", "d-polkit-agent-warn"))
        for lang in LANGS:
            self.assertIn("/usr/lib/hyprpolkitagent/hyprpolkitagent", self.doc.STRINGS[lang]["d-polkit-agent-warn"], lang)

    def test_the_bare_name_that_arch_does_not_ship_is_not_confused_with_a_running_agent(self):
        self.spawn(5, ["hyprpolkitagent-notes.txt"])                 # algo que solo se parece
        self.assertEqual(self.doc.chk_polkit_agent()[0], "warn")

    def test_an_agent_of_another_user_does_not_count(self):
        self.spawn(7, ["/usr/lib/hyprpolkitagent/hyprpolkitagent"])
        with mock.patch.object(self.doc.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(self.doc.chk_polkit_agent()[0], "warn")

    def test_without_a_graphical_session_the_check_is_skipped(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.doc.chk_polkit_agent()[:2], ("skip", "d-polkit-agent-skip"))

    def test_unreadable_proc_does_not_crash(self):
        with mock.patch.object(self.doc, "PROC", self.proc / "no-existe"):
            self.assertEqual(self.doc.chk_polkit_agent()[0], "warn")


class FlathubCheck(unittest.TestCase):
    def setUp(self):
        self.doc = load_doctor()
        self.cmds = []

    def run_with(self, rc, out, flatpak=True):
        def fake_run(cmd, timeout=6):
            self.cmds.append(cmd)
            return rc, out
        with mock.patch.object(self.doc, "_run", fake_run), \
                mock.patch.object(self.doc.shutil, "which", lambda n: "/usr/bin/flatpak" if flatpak else None):
            return self.doc.chk_flathub()

    def test_configured_for_the_user(self):
        self.assertEqual(self.run_with(0, "flathub\n")[:2], ("ok", "d-flathub-ok"))
        self.assertEqual(self.cmds, [["flatpak", "remotes", "--user", "--columns=name"]])

    def test_missing_remote_is_informational_because_the_store_adds_it(self):
        self.assertEqual(self.run_with(0, "")[:2], ("info", "d-flathub-info"))
        self.assertEqual(self.run_with(0, "otro-remoto\n")[:2], ("info", "d-flathub-info"))

    def test_a_remote_whose_name_only_contains_flathub_does_not_count(self):
        self.assertEqual(self.run_with(0, "flathub-beta\n")[0], "info")

    def test_no_flatpak_is_skipped_without_running_anything(self):
        self.assertEqual(self.run_with(0, "", flatpak=False)[:2], ("skip", "d-flathub-skip"))
        self.assertEqual(self.cmds, [])

    def test_a_failing_flatpak_is_reported_as_could_not_check(self):
        status, key, args, _ = self.run_with(1, "")
        self.assertEqual((status, key), ("skip", "d-error"))
        self.assertIn("err", args)


class Registration(unittest.TestCase):
    def setUp(self):
        self.doc = load_doctor()

    def test_new_checks_are_registered_in_their_groups(self):
        table = {cid: (group, fn.__name__, net) for cid, group, fn, net in self.doc.CHECKS}
        self.assertEqual(table["polkit-agent"], ("system", "chk_polkit_agent", False))
        self.assertEqual(table["flathub"], ("packages", "chk_flathub", False))
        self.assertEqual(len(table), len(self.doc.CHECKS))           # sin ids repetidos

    def test_every_check_has_a_title_in_every_language(self):
        for cid, *_ in self.doc.CHECKS:
            for lang in LANGS:
                self.assertIn(f"t-{cid}", self.doc.STRINGS[lang], f"{lang}: falta t-{cid}")

    def test_every_text_key_the_new_checks_can_return_exists_in_every_language(self):
        keys = {"d-polkit-agent-ok", "d-polkit-agent-warn", "d-polkit-agent-skip",
                "d-flathub-ok", "d-flathub-info", "d-flathub-skip", "d-error"}
        for lang in LANGS:
            for key in keys:
                self.assertTrue(self.doc.STRINGS[lang].get(key), f"{lang}: falta {key}")

    def test_placeholders_match_english(self):
        en = self.doc.STRINGS["en"]
        for key in (k for k in en if k.startswith(("d-polkit-agent", "d-flathub"))):
            want = set(re.findall(r"\{(\w+)\}", en[key]))
            for lang in LANGS:
                self.assertEqual(set(re.findall(r"\{(\w+)\}", self.doc.STRINGS[lang][key])), want, f"{lang}:{key}")

    def test_the_engine_runs_the_new_checks_and_renders_them(self):
        """Ida y vuelta por el motor real: cada chequeo nuevo sale en el informe en los 4 idiomas."""
        for lang in LANGS:
            with self.subTest(lang=lang):
                doc = load_doctor()
                with mock.patch.object(doc, "LANG", lang), mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "w"}), \
                        mock.patch.object(doc, "PROC", Path(tempfile.mkdtemp())), \
                        mock.patch.object(doc, "_run", lambda cmd, timeout=6: (0, "")), \
                        mock.patch.object(doc.shutil, "which", lambda n: "/usr/bin/x"):
                    for cid in ("polkit-agent", "flathub"):
                        fn = next(f for i, _g, f, _n in doc.CHECKS if i == cid)
                        status, key, args, _ = fn()
                        text = doc.STRINGS[lang][key].format(**args)
                        self.assertTrue(text.strip())
                        self.assertNotRegex(text, r"[{}]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
