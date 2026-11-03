"""El instalador legado (scripts/skill_instalar_usb.py, `avalos-install-old`) es el respaldo autónomo:
no importa el paquete avalos_installer, así que lleva su propia copia del preflight de pacstrap.

Dos cosas se vigilan: que la copia siga siendo el mismo código que la original (si no, un arreglo
en una se pierde en la otra), y que el bucle del legado funcione de verdad: se extrae del fuente y
se ejecuta contra un pacman real sobre repos de mentira, con el mismo fixture de
test_pacstrap_preflight.py (el legado es una clase gigante con GTK y pywebview: no se puede importar).
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from avalos_installer.core.config import MIRROR_COUNTRIES  # noqa: E402
import test_pacstrap_preflight as base  # noqa: E402  (fixture de pacman real y su runner)

LEGACY = ROOT / "scripts" / "skill_instalar_usb.py"
MODULAR = ROOT / "scripts" / "avalos_installer" / "system" / "pacstrap.py"
COPIED = ("LIVE_PACMAN_DBPATH", "_DEP_CONFLICT_RE", "_make_preflight_dbpath",
          "dependency_conflict_packages", "_sync_repos", "multilib_desync_culprits",
          "preflight_error_summary")


def top_level(path):
    src = path.read_text(encoding="utf-8")
    nodes = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
    return src, nodes


class TheCopyStaysEqual(unittest.TestCase):
    def test_the_preflight_helpers_are_the_same_code_in_both_installers(self):
        _, legacy = top_level(LEGACY)
        _, modular = top_level(MODULAR)
        for name in COPIED:
            self.assertIn(name, legacy, f"{name} falta en el instalador legado")
            self.assertIn(name, modular, name)
            self.assertEqual(ast.dump(legacy[name]), ast.dump(modular[name]),
                             f"{name} cambió en uno solo de los dos instaladores")

    def test_both_installers_use_the_same_mirror_countries(self):
        src = LEGACY.read_text(encoding="utf-8")
        found = re.findall(r'(?:--country |"--country"\s*,\s*")([A-Z]{2}(?:,[A-Z]{2})+)', src)
        self.assertGreaterEqual(len(found), 2, "el legado debería usar la lista en 2 sitios")
        self.assertEqual(set(found), {MIRROR_COUNTRIES})


def load_legacy_loop():
    """Helpers copiados + el bucle del preflight, extraídos del fuente del legado y ejecutables."""
    src, nodes = top_level(LEGACY)
    chunks = [ast.get_source_segment(src, nodes[n]) for n in sorted(COPIED, key=lambda n: nodes[n].lineno)]
    ns = {"os": os, "re": re, "shutil": shutil, "subprocess": subprocess, "tempfile": tempfile,
          "time": types.SimpleNamespace(sleep=lambda seconds: None)}
    exec("from __future__ import annotations\n" + "\n\n".join(chunks), ns)
    start = src.index('self ._log (self ._t ("log-checking-multilib"),"info")')
    end = src.index("            if _pkgs_omitidos :", start)
    body = textwrap.dedent("            " + src[start:end])
    exec("def loop(self, pkgs, _pacman_conf_target):\n" + textwrap.indent(body, "    ")
         + "\n    return _pf_out, _pkgs_omitidos\n", ns)
    return ns


class LegacySelf:
    """Lo mínimo de VentanaInstalador que toca el bucle."""

    def __init__(self, runner, choices=()):
        self.runner, self.choices = runner, list(choices)
        self.cmds, self.logs, self.js, self.cleaned = [], [], [], 0
        self._abortado = False
        self._mirror_choice = None
        self._mirror_choice_event = threading.Event()

    def _t(self, key, **kw):
        return key + ("" if not kw else " " + " ".join(f"{k}={v}" for k, v in sorted(kw.items())))

    def _log(self, txt, cls="info"):
        self.logs.append((cls, txt))

    def _run_cmd(self, cmd, timeout=300, log_cls="info"):
        self.cmds.append([str(c) for c in cmd])
        return self.runner(self.cmds[-1])

    def _jsc(self, func, *args):
        self.js.append((func, args))
        if func == "pyMirrorDialog":
            self._mirror_choice = self.choices.pop(0)
            self._mirror_choice_event.set()

    def _limpiar_montajes(self):
        self.cleaned += 1


@unittest.skipUnless(all(shutil.which(t) for t in base.TOOLS), "faltan herramientas: " + ", ".join(base.TOOLS))
class LegacyPreflightLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="avalos-legacy-")
        cls.conf = base.build_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.ns = load_legacy_loop()
        self.sleeps = []
        self.ns["time"] = types.SimpleNamespace(sleep=self.sleeps.append)
        self.ns["LIVE_PACMAN_DBPATH"] = os.path.join(self.root, "db")

    def run_loop(self, pkgs, runner=base.real_runner, choices=()):
        me = LegacySelf(runner, choices)
        return me, self.ns["loop"](me, pkgs, self.conf)

    def test_the_real_flow_drops_what_depends_on_the_lagging_package(self):
        pkgs = list(base.TARGETS)
        me, result = self.run_loop(pkgs)
        out, omitted = result
        self.assertEqual(sorted(omitted), ["lib32-mesa", "lib32-vulkan-radeon", "steam"])
        self.assertEqual(pkgs, ["debugedit", "hyprland", "lib32-gnutls", "wine-staging"])
        self.assertIn("libelf-0.197-1", out)
        self.assertEqual([f for f, _ in me.js], [])
        dropped = [t for _, t in me.logs if t.startswith("log-multilib-desync-dropped")]
        self.assertEqual(len(dropped), 1)
        self.assertIn("causa=lib32-libelf", dropped[0])
        self.assertEqual(self.sleeps, [], "un conflicto determinista no espera entre intentos")
        self.assertEqual(len([c for c in me.cmds if c[0] == "pacman"]), 3,
                         "2 intentos con el conflicto (el segundo refresca) y 1 ya sin los paquetes")

    def test_it_resolves_against_an_empty_local_database_and_cleans_it_up(self):
        me, _ = self.run_loop(["debugedit", "hyprland"])
        cmd = me.cmds[0]
        dbpath = cmd[cmd.index("--dbpath") + 1]
        self.assertNotEqual(dbpath, os.path.join(self.root, "db"))
        self.assertFalse(os.path.exists(dbpath), "el directorio temporal debe borrarse")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "db", "sync"))),
                         ["core.db", "extra.db", "multilib.db"])

    def test_a_package_outside_multilib_goes_to_the_dialog_and_is_never_dropped(self):
        conflict = ":: unable to satisfy dependency 'foo>=2' required by hyprland\n"
        pkgs = ["hyprland", "steam"]
        me, result = self.run_loop(pkgs, runner=lambda cmd: (1, conflict), choices=["rechazar"])
        self.assertIsNone(result)
        self.assertEqual(pkgs, ["hyprland", "steam"])
        self.assertEqual([f for f, _ in me.js], ["pyMirrorDialog", "pyErrorFatal"])

    def test_without_the_empty_database_nothing_is_dropped(self):
        self.ns["LIVE_PACMAN_DBPATH"] = os.path.join(self.root, "no-existe")
        broken = base.LIVE_DB_OUTPUT.replace("required by lib32-libelf", "required by lib32-mesa")
        pkgs = ["lib32-mesa"]
        me, result = self.run_loop(pkgs, runner=lambda cmd: (1, broken), choices=["rechazar"])
        self.assertIsNone(result)
        self.assertNotIn("--dbpath", me.cmds[0])
        self.assertEqual(pkgs, ["lib32-mesa"])

    def test_other_failures_keep_three_attempts_with_a_pause(self):
        bad = ("  % Total    % Received % Xferd  Average Speed\r\n100  4096  100  4096    0     0  81920\r\n"
               "error: failed retrieving file 'core.db' from mirror\n")
        me, result = self.run_loop(["base"], runner=lambda cmd: (1, bad), choices=["rechazar"])
        self.assertIsNone(result)
        self.assertEqual(len([c for c in me.cmds if c[0] == "pacman"]), 3)
        self.assertEqual(len(self.sleeps), 2)
        dialog = [a for f, a in me.js if f == "pyMirrorDialog"][0][0]
        self.assertIn("failed retrieving file", dialog)
        self.assertNotIn("% Total", dialog, "la barra de progreso de curl no debe llegar al diálogo")

    def test_the_old_target_not_found_trimming_still_works(self):
        nf = "error: target not found: lib32-sdl2-compat\n"
        outputs = [(1, nf)] * 3 + [(0, "ok\n")]
        pkgs = ["lib32-sdl2-compat", "steam"]
        me, result = self.run_loop(pkgs, runner=lambda cmd: outputs.pop(0))
        self.assertEqual(result[1], ["lib32-sdl2-compat"])
        self.assertEqual(pkgs, ["steam"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
