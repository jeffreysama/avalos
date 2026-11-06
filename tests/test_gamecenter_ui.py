"""Front-end de avalos-gamecenter (la página que dibuja pywebview).

Dos niveles, igual que el Centro de control: comprobación de sintaxis del JavaScript donde haya `node`
(los runners de GitHub lo traen) y prueba de humo con jsdom (55 comprobaciones por idioma: lanzadores,
GameMode, perfiles de MangoHud, opciones de lanzamiento, escapado de HTML) si jsdom está disponible.
En local:  cd /tmp && npm install jsdom && NODE_PATH=/tmp/node_modules python3 -m unittest tests.test_gamecenter_ui
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
UI_TEST = ROOT / "tests" / "js" / "gamecenter_ui.js"


def render(lang):
    loader = importlib.machinery.SourceFileLoader("avalos_gamecenter_ui", str(ROOT / "scripts" / "avalos-gamecenter"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module._render_html(lang)


def jsdom_available():
    if not NODE:
        return False
    return subprocess.run([NODE, "-e", "require.resolve('jsdom')"], capture_output=True, env=os.environ).returncode == 0


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
                res = subprocess.run([NODE, str(UI_TEST), str(page), lang], capture_output=True, text=True, timeout=180)
            self.assertEqual(res.returncode, 0, f"{lang}:\n{res.stdout[-1500:]}\n{res.stderr[-500:]}")
            self.assertIn("TODO OK", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
