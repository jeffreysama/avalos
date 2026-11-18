"""avalos-control.health_summary(): la ventana principal del Centro de Control llama a avalos-doctor y reduce su JSON. Con un
doctor de otra versión (la sync no actualiza todo a la vez) o un JSON dañado, la ventana NO puede reventar: antes
`int(summary["ok"])` lanzaba ValueError/TypeError/OverflowError y `status in {...}` TypeError con un valor no hashable."""
import importlib.machinery
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("avalos_control_health_under_test", str(ROOT / "scripts" / "avalos-control"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
        loader.exec_module(module)
    return module


class HealthSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = load()

    def summary(self, stdout, which="/usr/bin/avalos-doctor", error=None):
        run = mock.Mock(side_effect=error) if error else mock.Mock(return_value=types.SimpleNamespace(stdout=stdout, returncode=0))
        with mock.patch.object(self.ctl.shutil, "which", return_value=which), mock.patch.object(self.ctl.subprocess, "run", run):
            return self.ctl.health_summary()

    def test_a_well_formed_report_is_reduced_and_problems_are_sorted_fail_first(self):
        doc = {"summary": {"ok": 20, "warn": 2, "fail": 1},
               "findings": [{"status": "ok", "title": "a"}, {"status": "warn", "title": "b"}, {"status": "fail", "title": "c"}, {"status": "info", "title": "d"}]}
        res = self.summary(json.dumps(doc))
        self.assertEqual((res["state"], res["ok"], res["warn"], res["fail"]), ("done", 20, 2, 1))
        self.assertEqual(res["issues"], [{"title": "c", "status": "fail"}, {"title": "b", "status": "warn"}])

    def test_missing_doctor_and_unusable_output_are_states_not_exceptions(self):
        self.assertEqual(self.summary("{}", which=None), {"state": "missing"})
        for out in ("", "no es json", "{", "\x00", "[]", "null", "42", '"x"', "{}", '{"summary": null}', '{"summary": []}',
                    '{"summary": {}, "findings": "x"}', "[" * 100000):
            with self.subTest(out=out[:20]):
                self.assertIn(self.summary(out)["state"], ("error", "done"))
        for err in (OSError("x"), FileNotFoundError("x"), __import__("subprocess").TimeoutExpired("d", 1)):
            with self.subTest(err=type(err).__name__):
                self.assertEqual(self.summary("", error=err), {"state": "error"})

    def test_odd_values_in_the_report_never_raise(self):
        shapes = [{"summary": {"ok": "abc"}}, {"summary": {"ok": None, "warn": 1, "fail": 0}}, {"summary": {"ok": 10 ** 400}},
                  {"summary": {"ok": 1}, "findings": [None, 5, "x", {"status": "warn"}, {"status": "fail", "title": None}, {"status": ["x"]}, {"status": {"a": 1}}]},
                  {"summary": {"ok": 1, "warn": {}, "fail": []}}, {"summary": {"ok": True, "warn": False, "fail": 2.9}, "findings": []},
                  {"summary": {"ok": -5, "warn": "-3", "fail": "7"}}]
        for sh in shapes:
            with self.subTest(sh=str(sh)[:60]):
                res = self.summary(json.dumps(sh))
                self.assertEqual(res["state"], "done")
                for key in ("ok", "warn", "fail"):
                    self.assertIsInstance(res[key], int)
                    self.assertGreaterEqual(res[key], 0)
        for text in ('{"summary": {"ok": NaN}}', '{"summary": {"ok": Infinity, "warn": -Infinity}}'):
            with self.subTest(text=text):
                self.assertEqual(self.summary(text)["ok"], 0)

    def test_the_number_of_listed_problems_is_capped(self):
        findings = [{"status": "warn", "title": f"t{i}"} for i in range(self.ctl.MAX_ISSUES + 20)]
        res = self.summary(json.dumps({"summary": {"ok": 0, "warn": len(findings), "fail": 0}, "findings": findings}))
        self.assertEqual(len(res["issues"]), self.ctl.MAX_ISSUES)


if __name__ == "__main__":
    unittest.main()
