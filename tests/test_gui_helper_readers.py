"""Cómo avalos-update y avalos-restore leen la salida del helper de root (vía pkexec), con un helper FALSO de verdad
(un script que imprime en ráfagas, se cuelga, escribe bytes inválidos…) en lugar de dobles de subprocess.

Tres fallos que esto fija (reproducidos contra el código anterior):
  · select() miraba el fd y readline() retenía líneas en el búfer de Python: al dar por colgado al helper se perdían las
    últimas líneas, justo las que explican el cuelgue.
  · tras el exec de pkexec el proceso es de ROOT: el usuario no puede matarlo y proc.kill() lanzaba PermissionError, que
    mataba el hilo y dejaba la pantalla en «Actualizando…» para siempre.
  · avalos-restore.list_points() hacía data.get() sobre cualquier JSON: con «[]» o «42» como última línea → AttributeError.
"""
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
REAL_POPEN = subprocess.Popen


def load(name):
    loader = importlib.machinery.SourceFileLoader(f"avalos_{name}_readers_under_test", str(ROOT / "scripts" / f"avalos-{name}"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
        loader.exec_module(module)
    return module


class ReaderCase(unittest.TestCase):
    MODULE = None

    def setUp(self):
        self.mod = load(self.MODULE)
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-readers-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.popen_calls = []
        self.kill_error = None
        outer = self

        def fake_popen(cmd, **kw):
            # quita «pkexec»: se ejecuta el helper falso directamente
            outer.popen_calls.append(list(cmd))
            assert cmd[0] == "pkexec", cmd
            proc = REAL_POPEN(cmd[1:], **kw)
            if outer.kill_error:
                real_kill = proc.kill

                def kill():
                    real_kill()                    # (el hijo muere de verdad para no dejar procesos; el error es lo que se simula)
                    raise outer.kill_error
                proc.kill = kill
            return proc

        class FakeSubprocess:
            Popen = staticmethod(fake_popen)

            def __getattr__(self_, name):
                return getattr(subprocess, name)

        for p in (mock.patch.object(self.mod, "subprocess", FakeSubprocess()), mock.patch.object(self.mod, "HELPER_IDLE_TIMEOUT", 0.8)):
            p.start()
            self.addCleanup(p.stop)
        self.logs = []
        self.api = self.make_api()

    def helper(self, body):
        path = self.tmp / "fake-helper"
        path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o755)
        self.mod.HELPER_BIN = str(path)

    def texts(self):
        return [t for _c, t in self.logs]


class AbortProc(unittest.TestCase):
    """Un helper que el usuario no puede matar (es de root) tampoco se espera sin límite."""

    class Immortal:
        def __init__(self, kill_error):
            self.kill_error, self.waited = kill_error, []

        def kill(self):
            raise self.kill_error

        def wait(self, timeout=None):
            self.waited.append(timeout)
            if timeout is None:
                raise AssertionError("wait() sin límite sobre un proceso que no se pudo matar")
            raise subprocess.TimeoutExpired("helper", timeout)

    def test_neither_gui_blocks_or_raises_on_a_process_it_cannot_kill(self):
        for name in ("update", "restore"):
            mod = load(name)
            for err in (PermissionError(1, "EPERM"), ProcessLookupError(3, "ESRCH")):
                with self.subTest(gui=name, err=type(err).__name__):
                    proc = self.Immortal(err)
                    mod._abort_proc(proc)
                    self.assertEqual(proc.waited, [20], "una espera acotada, nunca indefinida")


class UpdateReader(ReaderCase):
    MODULE = "update"

    def make_api(self):
        api = self.mod.UpdateAPI()
        api._log = lambda txt, cls="info": self.logs.append((cls, txt))
        return api

    def run_helper(self, *args):
        return self.api._run_helper(list(args or ["x"]))

    def test_every_line_of_a_burst_is_logged_in_order_and_a_zero_exit_is_success(self):
        self.helper("printf '### $ pacman -Syu\\nuno\\ndos\\ntres\\n'; exit 0")
        self.assertTrue(self.run_helper())
        self.assertEqual(self.texts()[1:], ["$ pacman -Syu", "uno", "dos", "tres"])
        self.assertEqual([c for c, t in self.logs][1:], ["step", "info", "info", "info"])

    def test_lines_printed_right_before_a_hang_are_not_lost(self):
        self.helper("printf 'uno\\ndos\\ntres\\nesperando db.lck'; sleep 30")
        t0 = time.monotonic()
        self.assertFalse(self.run_helper())
        self.assertLess(time.monotonic() - t0, 15)
        for expected in ("uno", "dos", "tres", "esperando db.lck"):
            self.assertIn(expected, self.texts())
        self.assertTrue(any("sin respuesta" in t for t in self.texts()))

    def test_a_helper_that_cannot_be_killed_by_the_user_does_not_crash_the_worker(self):
        self.kill_error = PermissionError(1, "Operation not permitted")
        self.helper("printf 'hola\\n'; sleep 30")
        self.assertFalse(self.run_helper())                   # antes: PermissionError sin atrapar en el hilo
        self.assertTrue(any("sin respuesta" in t for t in self.texts()))

    def test_a_nonzero_exit_is_a_failure_and_says_the_code(self):
        self.helper("echo 'algo'; exit 3")
        self.assertFalse(self.run_helper())
        self.assertIn("(código de salida 3)", self.texts())

    def test_invalid_utf8_progress_bars_and_a_last_line_without_newline_are_handled(self):
        self.helper("printf '10%%\\r50%%\\r100%%\\nraro \\377\\376 fin\\nsin salto final'")
        self.assertTrue(self.run_helper())
        self.assertEqual(self.texts()[1:4], ["10%", "50%", "100%"])
        self.assertIn("sin salto final", self.texts())
        self.assertTrue(any(t.startswith("raro") for t in self.texts()))

    def test_pkexec_missing_is_reported(self):
        self.mod.subprocess.Popen = staticmethod(lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("pkexec")))
        self.assertFalse(self.run_helper())
        self.assertIn("pkexec no está disponible en este sistema.", self.texts())


class RestoreReader(ReaderCase):
    MODULE = "restore"

    def make_api(self):
        api = self.mod.RestoreAPI()
        api._log = lambda txt, cls="info": self.logs.append((cls, txt))
        return api

    def capture(self, *args):
        return self.api._run_helper_capture(list(args or ["list-restore-points"]))

    def test_data_lines_are_captured_and_narration_goes_to_the_log(self):
        self.helper("printf '### $ list\\n### ERROR: algo\\n{\"points\": []}\\n'")
        ok, captured = self.capture()
        self.assertTrue(ok)
        self.assertEqual(captured, ['{"points": []}'])
        self.assertEqual([c for c, t in self.logs][1:], ["step", "err"])

    def test_a_burst_followed_by_a_hang_keeps_everything_and_stops(self):
        self.helper("printf '### paso 1\\n### paso 2\\ndato'; sleep 30")
        ok, captured = self.capture()
        self.assertFalse(ok)
        self.assertEqual(captured, ["dato"])
        self.assertTrue({"paso 1", "paso 2"} <= set(self.texts()))

    def test_an_unkillable_helper_does_not_crash(self):
        self.kill_error = PermissionError(1, "Operation not permitted")
        self.helper("echo hola; sleep 30")
        ok, _ = self.capture()
        self.assertFalse(ok)

    def list_points(self, last_line, before=""):
        self.helper(f"printf '### $ list-restore-points\\n{before}'; printf '%s\\n' '{last_line}'")
        return json.loads(self.api.list_points())

    def test_list_points_returns_the_helper_answer_when_it_is_an_object(self):
        res = self.list_points('{"points": [{"number": 3}], "backups": ["b"], "snapper_ok": true}')
        self.assertEqual((res["ok"], res["points"], res["backups"], res["snapper_ok"]), (True, [{"number": 3}], ["b"], True))

    def test_list_points_survives_a_last_line_that_is_valid_json_but_not_an_object(self):
        for last in ("[]", "42", "null", '"texto"', "true", "[1,2,3]", "3.14"):
            with self.subTest(last=last):
                res = self.list_points(last)
                self.assertFalse(res["ok"], res)
                self.assertEqual(res["points"], [])

    def test_list_points_survives_garbage_and_failure(self):
        for last in ("no es json", "{", "", "[" * 100000):
            with self.subTest(last=last[:10]):
                res = self.list_points(last)
                self.assertFalse(res["ok"])
        self.helper("echo '### ERROR: layout no soportado'; exit 1")
        res = json.loads(self.api.list_points())
        self.assertFalse(res["ok"])
        self.assertIn("layout no soportado", res["detail"])


if __name__ == "__main__":
    unittest.main()
