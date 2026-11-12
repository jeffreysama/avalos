"""El instalador legado (scripts/skill_instalar_usb.py, `avalos-install-old`) es el instalador modular empaquetado
en un solo archivo por scripts/build-legacy-installer.py. Aquí se comprueba que el archivo está al día, que lo
embebido es exactamente el paquete, y que arranca solo (sin el paquete en disco) y igual que el modular."""
import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
BUNDLE = SCRIPTS / "skill_instalar_usb.py"
GEN_PATH = SCRIPTS / "build-legacy-installer.py"


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def embedded_modules():
    tree = ast.parse(BUNDLE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_MODULES")
    return ast.literal_eval(node.value)


class Freshness(unittest.TestCase):
    def test_the_bundle_is_up_to_date_with_the_modular_package(self):
        r = subprocess.run([sys.executable, str(GEN_PATH), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + "\n→ python3 scripts/build-legacy-installer.py")

    def test_what_is_embedded_is_exactly_the_package(self):
        gen = load_file(GEN_PATH, "gen_under_test_fresh")
        self.addCleanup(sys.modules.pop, "gen_under_test_fresh", None)
        want = {name: (is_pkg, rel, src) for name, is_pkg, rel, src in gen.collect_modules()}
        self.assertEqual(embedded_modules(), want)
        on_disk = {p.relative_to(SCRIPTS).as_posix() for p in (SCRIPTS / "avalos_installer").rglob("*.py")}
        self.assertEqual({rel for _, rel, _ in embedded_modules().values()}, on_disk)

    def test_header_and_hash(self):
        gen = load_file(GEN_PATH, "gen_under_test_hdr")
        self.addCleanup(sys.modules.pop, "gen_under_test_hdr", None)
        text = BUNDLE.read_text(encoding="utf-8")
        self.assertIn("GENERADO por scripts/build-legacy-installer.py", text)
        self.assertIn(f'BUNDLE_SOURCE_SHA256 = "{gen.source_sha256(gen.collect_modules())}"', text)
        self.assertIn(f"git show {gen.MONOLITH_COMMIT}:scripts/skill_instalar_usb.py", text)
        self.assertRegex(gen.MONOLITH_COMMIT, r"^[0-9a-f]{7,40}$")

    def test_a_single_changed_character_in_a_module_makes_the_bundle_stale(self):
        gen = load_file(GEN_PATH, "gen_under_test_stale")
        self.addCleanup(sys.modules.pop, "gen_under_test_stale", None)
        tmp = Path(tempfile.mkdtemp(prefix="avalos-bundle-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        pkg = tmp / "avalos_installer"
        shutil.copytree(SCRIPTS / "avalos_installer", pkg, ignore=shutil.ignore_patterns("__pycache__"))
        out = tmp / "skill_instalar_usb.py"
        out.write_text(BUNDLE.read_text(encoding="utf-8"), encoding="utf-8")
        gen.PKG, gen.OUT = pkg, out
        quiet, quiet_err = contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())
        with quiet, quiet_err:
            self.assertEqual(gen.main(["--check"]), 0)
            target = pkg / "core" / "config.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# cambio\n", encoding="utf-8")
            self.assertEqual(gen.main(["--check"]), 1)
            self.assertEqual(gen.main([]), 0)                              # regenerar lo deja al día
            self.assertEqual(gen.main(["--check"]), 0)
        self.assertIn("# cambio", out.read_text(encoding="utf-8"))


class LiteralFidelity(unittest.TestCase):
    def setUp(self):
        self.gen = load_file(GEN_PATH, "gen_under_test_lit")
        self.addCleanup(sys.modules.pop, "gen_under_test_lit", None)

    def test_awkward_sources_round_trip_exactly(self):
        cases = [
            "x = 1\n",
            "a = '''triple simple'''\n",
            'b = """triple doble"""\n',
            "a = '''x'''\nb = \"\"\"y\"\"\"\n",                         # las dos: obliga al repr
            "ruta = 'C:\\\\dir\\\\nuevo'\nrx = r'\\d+\\n'\n",           # barras invertidas
            "texto = 'it\\'s'\n",
            "s = 'termina en comilla'\n'",                             # acaba en comilla simple
            's = "termina en comilla"\n"',
            "fin = 1 \\\n",                                             # acaba en barra
            "acentos = 'ñandú — 日本語 — ✓'\nbox = '╔═╗'\n",
            "\n\n",
            "",
            "def f():\n    return '\\u00e9'\n",
            "a''' 'b",                                                  # con el literal crudo sale otra cosa («ab»), no un error
            'a""" "b',
        ]
        for src in cases:
            code = self.gen.literal(src)
            self.assertEqual(ast.literal_eval(code), src, repr(src))

    def test_readable_literal_is_used_whenever_it_fits(self):
        self.assertTrue(self.gen.literal("x = 1\n").startswith("r'''"))
        self.assertTrue(self.gen.literal("a = '''x'''\n").startswith('r"""'))
        self.assertFalse(self.gen.literal("a = '''x'''\nb = \"\"\"y\"\"\"\n").startswith("r"))

    def test_sources_with_carriage_returns_or_nul_are_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="avalos-bundle-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        pkg = tmp / "avalos_installer"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        self.gen.PKG = pkg
        for bad in ("x = 1\r\n", "x = 1\0\n"):
            (pkg / "mod.py").write_bytes(bad.encode())
            with self.assertRaises(SystemExit):
                self.gen.collect_modules()

    def test_an_empty_package_is_an_error(self):
        tmp = Path(tempfile.mkdtemp(prefix="avalos-bundle-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.gen.PKG = tmp / "avalos_installer"
        self.gen.PKG.mkdir()
        with self.assertRaises(SystemExit):
            self.gen.collect_modules()


class Finder(unittest.TestCase):
    """Semántica del importador embebido, con un paquete de juguete."""

    def setUp(self):
        self.bundle = load_file(BUNDLE, "bundle_under_test_finder")
        self.addCleanup(sys.modules.pop, "bundle_under_test_finder", None)
        self.mods = {
            "toypkg": (True, "toypkg/__init__.py", ""),
            "toypkg.core": (True, "toypkg/core/__init__.py", ""),
            "toypkg.core.base": (False, "toypkg/core/base.py", "VALUE = 41\n\ndef bump():\n    return VALUE + 1\n"),
            "toypkg.user": (False, "toypkg/user.py", "from toypkg.core.base import bump\nfrom toypkg.core import base\nRESULT = bump()\nSAME = base.VALUE\n"),
            "toypkg.boom": (False, "toypkg/boom.py", "x = 1\nraise RuntimeError('fallo a propósito')\n"),
        }
        self.finder = self.bundle._BundleFinder(self.mods)
        sys.meta_path.insert(0, self.finder)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.finder in sys.meta_path:
            sys.meta_path.remove(self.finder)
        for name in [n for n in sys.modules if n == "toypkg" or n.startswith("toypkg.")]:
            del sys.modules[name]

    def test_packages_submodules_and_cross_imports_work(self):
        import toypkg.user as user                                       # noqa: PLC0415
        self.assertEqual((user.RESULT, user.SAME), (42, 41))
        self.assertEqual(sys.modules["toypkg"].__path__, [])
        self.assertEqual(sys.modules["toypkg.core.base"].__file__, "toypkg/core/base.py")
        self.assertIs(sys.modules["toypkg.core.base"].__spec__.loader, self.finder)

    def test_unknown_modules_are_left_to_the_normal_machinery(self):
        self.assertIsNone(self.finder.find_spec("toypkg.no_existe"))
        with self.assertRaises(ModuleNotFoundError):
            import toypkg.no_existe  # noqa: F401, PLC0415

    def test_tracebacks_show_the_original_source_line(self):
        with self.assertRaises(RuntimeError):
            import toypkg.boom  # noqa: F401, PLC0415
        try:
            import toypkg.boom  # noqa: F401, PLC0415
        except RuntimeError:
            tb = traceback.format_exc()
        self.assertIn('File "toypkg/boom.py", line 2', tb)
        self.assertIn("raise RuntimeError('fallo a propósito')", tb)

    def test_installing_twice_reuses_the_same_finder(self):
        sys.meta_path.remove(self.finder)                       # el de juguete estorbaría: mira si ya hay uno
        a = self.bundle._install_finder()
        self.addCleanup(lambda: sys.meta_path.remove(a) if a in sys.meta_path else None)
        self.assertIs(self.bundle._install_finder(), a)
        self.assertEqual(sum(isinstance(f, self.bundle._BundleFinder) for f in sys.meta_path), 1)
        self.assertIs(sys.meta_path[0], a)                      # y va el primero, antes que cualquier copia en disco


DRIVER = textwrap.dedent('''
    import hashlib, importlib.util, json, os, sys, types
    from pathlib import Path
    mode, scripts, tmp = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    sys.path.insert(0, str(tmp))                       # translations.py: lo único externo
    if mode in ("package", "bundle_beside_package"):
        sys.path.insert(0, scripts)                    # el paquete en disco (en la ISO está junto al legado)
    calls = {}
    class _Ev:
        def __iadd__(self, f):
            return self
    class _Win:
        def __init__(self):
            self.events = types.SimpleNamespace(closed=_Ev(), loaded=_Ev())
    fake = types.ModuleType("webview")
    def create_window(**kw):
        calls["html"], calls["api"] = kw["html"], kw["js_api"]
        return _Win()
    fake.create_window = create_window
    fake.start = lambda debug=False: calls.setdefault("started", True)
    sys.modules["webview"] = fake
    os.geteuid = lambda: 0
    if mode in ("bundle", "bundle_beside_package"):
        spec = importlib.util.spec_from_file_location("bundle_under_test", Path(scripts) / "skill_instalar_usb.py")
        bundle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bundle)
        bundle._install_finder()
        entry = bundle.main
    else:
        from avalos_installer.__main__ import main as entry
    from avalos_installer.core import logfile
    _orig = logfile.InstallLog.__init__
    def _init(self, path=None, usb_mount_dir=None, run=None, variant=None):
        _orig(self, path or tmp / "live.log", usb_mount_dir or tmp / "usb", run, variant)
    logfile.InstallLog.__init__ = _init
    entry()
    mods = sorted(n for n in sys.modules if n == "avalos_installer" or n.startswith("avalos_installer."))
    api = calls["api"]
    session = getattr(api, "session", None) or getattr(api, "_session", None)
    print(json.dumps({
        "started": calls.get("started"),
        "html_sha": hashlib.sha256(calls["html"].encode()).hexdigest(),
        "html_len": len(calls["html"]),
        "modules": mods,
        "loaders": sorted({type(sys.modules[n].__spec__.loader).__name__ for n in mods}),
        "variant": session.logfile._variant,
        "files": sorted({sys.modules[n].__file__ for n in mods}),
    }))
''')


class Startup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="avalos-boot-"))
        shutil.copy(SCRIPTS / "translations.py", cls.tmp / "translations.py")      # lo único que el legado necesita fuera
        (cls.tmp / "driver.py").write_text(DRIVER, encoding="utf-8")
        cls.out = {}
        for mode in ("bundle", "package", "bundle_beside_package"):
            r = subprocess.run([sys.executable, str(cls.tmp / "driver.py"), mode, str(SCRIPTS), str(cls.tmp)],
                               capture_output=True, text=True, timeout=120, cwd=cls.tmp)
            if r.returncode != 0:
                raise AssertionError(f"{mode}: rc={r.returncode}\n{r.stderr[-1500:]}")
            cls.out[mode] = json.loads(r.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_both_reach_the_window_and_start_it(self):
        self.assertTrue(self.out["bundle"]["started"])
        self.assertTrue(self.out["package"]["started"])
        self.assertGreater(self.out["bundle"]["html_len"], 50_000)

    def test_the_bundle_runs_without_the_package_on_disk(self):
        b = self.out["bundle"]
        self.assertEqual(b["loaders"], ["_BundleFinder"])
        self.assertTrue(all(not os.path.isabs(f) for f in b["files"]), b["files"])     # rutas del repo, no del disco
        self.assertFalse((self.tmp / "avalos_installer").exists())

    def test_in_the_iso_layout_the_bundle_wins_over_the_package_sitting_next_to_it(self):
        """En la ISO, skill_instalar_usb.py y avalos_installer/ viven en el mismo directorio: el legado tiene
        que usar SU código embebido (si no, no serviría de respaldo cuando ese directorio falle)."""
        b = self.out["bundle_beside_package"]
        self.assertEqual(b["loaders"], ["_BundleFinder"])
        self.assertTrue(all(not os.path.isabs(f) for f in b["files"]), b["files"])
        self.assertEqual(b["html_sha"], self.out["package"]["html_sha"])
        self.assertEqual(b["variant"], "legado (un solo archivo)")

    def test_it_shows_the_same_ui_and_loads_the_same_modules_as_the_modular_installer(self):
        b, p = self.out["bundle"], self.out["package"]
        self.assertEqual(b["html_sha"], p["html_sha"])
        self.assertEqual(b["modules"], p["modules"])

    def test_the_install_log_says_which_installer_ran(self):
        self.assertEqual(self.out["bundle"]["variant"], "legado (un solo archivo)")
        self.assertEqual(self.out["package"]["variant"], "modular (avalos_installer)")


class Wiring(unittest.TestCase):
    def test_the_iso_workflow_still_ships_the_same_file_and_wrapper(self):
        wf = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
        self.assertIn('cp scripts/skill_instalar_usb.py', wf)
        self.assertIn("avalos-install-old", wf)

    def test_the_generator_is_executable_and_documented(self):
        doc = ast.get_docstring(ast.parse(GEN_PATH.read_text(encoding="utf-8")))
        self.assertIn("--check", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
