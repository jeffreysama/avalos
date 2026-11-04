"""Front-end de avalos-control (la página que dibuja pywebview).

Dos niveles: una comprobación de sintaxis del JavaScript que corre donde haya `node` (los runners de
GitHub lo traen) y una prueba de humo con jsdom de 29 comprobaciones por idioma (tiles, búsqueda,
teclado, estados de salud, escapado de HTML) que solo corre si jsdom está disponible. Para correrla
en local:  cd /tmp && npm install jsdom && NODE_PATH=/tmp/node_modules python3 -m unittest tests.test_control_center_ui
"""
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
UI_TEST = ROOT / "tests" / "js" / "control_center_ui.js"


def render(lang):
    loader = importlib.machinery.SourceFileLoader("avalos_control_ui", str(ROOT / "scripts" / "avalos-control"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module._render_html(lang)


def jsdom_available():
    if not NODE:
        return False
    res = subprocess.run([NODE, "-e", "require.resolve('jsdom')"], capture_output=True, env=os.environ)
    return res.returncode == 0


@unittest.skipUnless(NODE, "falta node")
class JavaScriptSyntax(unittest.TestCase):
    def test_the_page_script_parses_in_every_language(self):
        for lang in ("en", "es", "zh", "ja"):
            script = re.search(r"<script>(.*)</script>", render(lang), re.S).group(1)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "page.js"
                path.write_text(script, encoding="utf-8")
                res = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"{lang}: {res.stderr}")


@unittest.skipUnless(jsdom_available(), "falta jsdom (npm install jsdom; NODE_PATH)")
class Smoke(unittest.TestCase):
    def test_the_page_works_in_every_language(self):
        for lang in ("en", "es", "zh", "ja"):
            with tempfile.TemporaryDirectory() as tmp:
                page = Path(tmp) / f"page-{lang}.html"
                page.write_text(render(lang), encoding="utf-8")
                res = subprocess.run([NODE, str(UI_TEST), str(page), lang], capture_output=True, text=True, timeout=120)
            self.assertEqual(res.returncode, 0, f"{lang}:\n{res.stdout}\n{res.stderr}")
            self.assertIn("TODO OK", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
