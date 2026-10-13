"""Hallazgos de la primera instalación en hardware real (laptop HP, 11 oct 2026), con sus pruebas.

  · pkexec fallaba con «Error creating textual authentication agent… /dev/tty» (código 127): el
    agente de polkit nunca arrancaba porque el paquete de Arch instala hyprpolkitagent en
    /usr/lib/hyprpolkitagent/ (fuera del PATH) y las configs lo lanzaban por su nombre pelado.
  · rate-mirrors respondía «unexpected argument '--allow-root' found»: es una opción base y va ANTES
    del subcomando; siempre se caía a reflector.
  · El remoto de Flathub no quedaba configurado (flatpak remote-add sin --user usa el helper del
    sistema por D-Bus, que en el chroot no existe) y el instalador anunciaba un éxito falso.
"""
import ast
import importlib.machinery
import importlib.util
import os
import re
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

LANGS = ("en", "es", "zh", "ja")
HYPRLAND_CONFIGS = ("configs/hyprland/hyprland.lua", "configs/hyprland/hyprland_conf_lua.template")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class PolkitAgent(unittest.TestCase):
    def test_agent_is_started_by_its_real_path(self):
        for rel in HYPRLAND_CONFIGS:
            text = read(rel)
            self.assertNotRegex(text, r'exec_cmd\(\s*"hyprpolkitagent[\s"]', rel)
            self.assertIn('hl.exec_cmd("/usr/lib/hyprpolkitagent/hyprpolkitagent")', text, rel)

    def test_no_command_started_by_the_configs_is_a_known_off_path_binary(self):
        off_path = {"hyprpolkitagent"}      # Arch no los pone en /usr/bin: solo se pueden lanzar por ruta completa
        for rel in HYPRLAND_CONFIGS:
            commands = re.findall(r'exec_cmd\(\s*"([^"]+)"', read(rel))
            self.assertTrue(commands, rel)
            for cmd in commands:
                self.assertNotIn(cmd.split()[0], off_path, f"{rel}: {cmd}")

    def test_the_agent_is_started_in_both_the_live_and_the_installed_system(self):
        for rel in HYPRLAND_CONFIGS:
            self.assertEqual(read(rel).count("/usr/lib/hyprpolkitagent/hyprpolkitagent"), 1, rel)


class RateMirrors(unittest.TestCase):
    def test_modular_installer_puts_base_options_before_the_subcommand(self):
        tree = ast.parse(read("scripts/avalos_installer/network/mirrors.py"))
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) \
                    and node.elts[0].value == "rate-mirrors":
                calls.append([e.value for e in node.elts if isinstance(e, ast.Constant)])
        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertEqual(args[-1], "arch")                      # el subcomando va al final
        self.assertIn("--allow-root", args[:-1])
        self.assertIn("--save", args[:-1])

    def test_legacy_installer_and_manual_guide_use_the_same_order(self):
        legacy = read("scripts/skill_instalar_usb.py")
        self.assertIn('"rate-mirrors","--allow-root","--save","/etc/pacman.d/mirrorlist","arch"', legacy)
        self.assertNotRegex(legacy, r'"rate-mirrors"\s*,\s*"arch"')
        guide = read("docs/INSTALL.md")
        self.assertIn("rate-mirrors --allow-root --save /etc/pacman.d/mirrorlist arch", guide)
        self.assertNotIn("rate-mirrors arch --allow-root", guide)


class FlathubRemote(unittest.TestCase):
    def test_both_installers_add_the_user_remote_and_check_the_result(self):
        aur = read("scripts/avalos_installer/system/aur.py")
        self.assertRegex(aur, r'"flatpak", "remote-add", "--user",')
        self.assertIn('session.t("log-flathub-failed")', aur)
        self.assertIn("if rc_flat == 0:", aur)
        legacy = read("scripts/skill_instalar_usb.py")
        self.assertIn('"flatpak","remote-add","--user",', legacy)
        self.assertIn('self ._t ("log-flathub-failed")', legacy)

    def test_manual_guide_adds_the_remote_for_the_user(self):
        guide = read("docs/INSTALL.md")
        self.assertIn("flatpak remote-add --user --if-not-exists flathub", guide)
        self.assertNotRegex(guide, r"flatpak remote-add --if-not-exists")

    def test_ci_installs_flatpak_so_the_real_flatpak_test_runs_instead_of_skipping(self):
        wf = read(".github/workflows/validate-configs.yml")
        self.assertRegex(wf, r"parted fdisk e2fsprogs flatpak")

    def test_failure_message_exists_in_every_language_without_placeholders(self):
        for lang in LANGS:
            msg = translations.TRANSLATIONS[lang]["log-flathub-failed"]
            self.assertTrue(msg.strip(), lang)
            self.assertNotRegex(msg, r"[{}]", lang)


def load_store():
    sys.modules.setdefault("webview", types.ModuleType("webview"))     # no hace falta el real para probar la lógica
    loader = importlib.machinery.SourceFileLoader("avalos_store_under_test", str(ROOT / "scripts" / "avalos-store"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class StoreFlatpak(unittest.TestCase):
    def setUp(self):
        self.store = load_store()
        self.api = self.store.StoreAPI.__new__(self.store.StoreAPI)
        self.events = []
        self.api._log = lambda app_id, msg: self.events.append(("log", msg))
        self.api._finish = lambda app_id, kind, ok, msg, **kw: self.events.append(("finish", ok))
        self.api._stream = lambda app_id, proc: 0
        self.api._notify = lambda msg: None
        self.calls = []
        self.remote_rc = 0

        def fake_run(cmd, **kw):
            self.calls.append(("run", list(cmd)))
            return types.SimpleNamespace(returncode=self.remote_rc, stdout="", stderr="boom")

        def fake_popen(cmd, **kw):
            self.calls.append(("popen", list(cmd)))
            return object()

        for p in (mock.patch.object(self.store.subprocess, "run", fake_run),
                  mock.patch.object(self.store.subprocess, "Popen", fake_popen),
                  mock.patch.object(self.store.shutil, "which", lambda name: f"/usr/bin/{name}")):
            p.start()
            self.addCleanup(p.stop)

    def flatpak_app(self):
        return {"id": "x", "name": "X", "source": "flatpak", "package": "org.example.X"}

    def test_user_remote_is_added_before_installing_a_flatpak(self):
        self.api._do_install(self.flatpak_app())
        self.assertEqual(self.calls, [
            ("run", ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", self.store.FLATHUB_REPO_URL]),
            ("popen", ["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", "org.example.X"]),
        ])
        self.assertIn(("finish", True), self.events)

    def test_a_failing_remote_add_is_logged_but_does_not_block_the_install(self):
        self.remote_rc = 1
        self.api._do_install(self.flatpak_app())
        self.assertEqual([c[0] for c in self.calls], ["run", "popen"])
        self.assertTrue(any(e[0] == "log" and e[1].startswith("flathub:") and "boom" in e[1] for e in self.events))

    def test_a_crashing_remote_add_does_not_block_the_install_either(self):
        def explode(cmd, **kw):
            raise OSError("sin red")
        with mock.patch.object(self.store.subprocess, "run", explode):
            self.api._do_install(self.flatpak_app())
        self.assertEqual(self.calls[-1][0], "popen")
        self.assertTrue(any(e[0] == "log" and "sin red" in e[1] for e in self.events))

    def test_pacman_installs_never_touch_flathub(self):
        self.api._do_install({"id": "y", "name": "Y", "source": "pacman", "package": "htop"})
        self.assertEqual(self.calls, [("popen", ["pkexec", "pacman", "-S", "--noconfirm", "--needed", "htop"])])

    def test_the_official_flathub_url_is_used(self):
        self.assertEqual(self.store.FLATHUB_REPO_URL, "https://dl.flathub.org/repo/flathub.flatpakrepo")


@unittest.skipUnless(shutil.which("flatpak"), "falta flatpak")
class RealFlatpak(unittest.TestCase):
    """Con flatpak de verdad: el remoto del usuario se agrega sin D-Bus del sistema y es idempotente."""

    def test_user_remote_works_without_a_system_bus_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "prueba.flatpakrepo"
            repo.write_text("[Flatpak Repo]\nTitle=prueba\nUrl=https://example.invalid/repo/\n", encoding="utf-8")
            env = {**os.environ, "HOME": home, "XDG_DATA_HOME": f"{home}/.local/share",
                   "XDG_CONFIG_HOME": f"{home}/.config", "XDG_CACHE_HOME": f"{home}/.cache",
                   "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent/bus",
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}
            add = ["flatpak", "remote-add", "--user", "--if-not-exists", "--no-gpg-verify", "prueba", str(repo)]
            for _ in range(2):                                   # la segunda vez no debe fallar
                r = subprocess.run(add, env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run(["flatpak", "remotes", "--user", "--columns=name"], env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertIn("prueba", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
