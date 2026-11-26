"""Cambiar el idioma de AvalOS después de la instalación.

Reporte (25 nov 2026): el idioma solo se podía elegir al instalar; en Ajustes ya no había nada para cambiarlo.

Qué se prueba:
  · `avalos-update-helper set-language` (root): escribe /etc/avalos-lang y deja el tema de SDDM EXACTAMENTE como lo
    dejaría el instalador en ese idioma; falla cerrado (sin root o con un código raro no escribe nada) y un fallo del
    login no deshace el cambio de idioma.
  · `avalos-language` (usuario): las etiquetas de fastfetch quedan como las del instalador, sin importar en qué
    idioma estuvieran antes; cada resultado de pkexec (éxito, cancelado, helper viejo, error) tiene su camino.
  · Las tablas que duplican a translations.py (SDDM en el helper, fastfetch en avalos-language) no se desalinean.
  · El menú de Ajustes y el Centro de control lo ofrecen y el script está registrado donde toca.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HELPER = SCRIPTS / "avalos-update-helper"
LANGUAGE = SCRIPTS / "avalos-language"
LANGS = ("en", "es", "zh", "ja")

sys.path.insert(0, str(SCRIPTS))
try:
    from translations import TRANSLATIONS
finally:
    sys.path.pop(0)


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# Lo que hace el instalador (scripts/avalos_installer/desktop/hyprland.py), copiado tal cual: es la referencia.
def installer_sddm(template, lang):
    t = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    return (template
            .replace("%%SDDM_USER%%", t.get("lbl-user", "Username"))
            .replace("%%SDDM_PASS%%", t.get("lbl-pass", "Password"))
            .replace("%%SDDM_SIGNIN%%", t.get("sddm-signin", "Sign In"))
            .replace("%%SDDM_FAIL%%", t.get("sddm-fail", "Authentication failed. Try again."))
            .replace("%%SDDM_SESSION%%", t.get("sddm-session", "Session"))
            .replace("%%SDDM_SUSPEND%%", t.get("sddm-suspend", "Suspend"))
            .replace("%%SDDM_RESTART%%", t.get("sddm-restart", "Restart"))
            .replace("%%SDDM_SHUTDOWN%%", t.get("sddm-shutdown", "Shutdown")))


def installer_fastfetch(baseline, lang):
    t = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    keys = {
        '" OS"': f'"{t.get("ff-os", " OS")}"',
        '"\\uf0e4 Host"': f'"{t.get("ff-host", "\\uf0e4 Host")}"',
        '" Kernel"': f'"{t.get("ff-kernel", " Kernel")}"',
        '"\\uf55f Uptime"': f'"{t.get("ff-uptime", "\\uf55f Uptime")}"',
        '"\\uf439 Packages"': f'"{t.get("ff-packages", "\\uf439 Packages")}"',
        '" Shell"': f'"{t.get("ff-shell", " Shell")}"',
        '"\\uf879 Resolution"': f'"{t.get("ff-display", "\\uf879 Resolution")}"',
        '" WM"': f'"{t.get("ff-wm", " WM")}"',
        '" Terminal"': f'"{t.get("ff-terminal", " Terminal")}"',
        '" CPU"': f'"{t.get("ff-cpu", " CPU")}"',
        '"\\uf43f GPU"': f'"{t.get("ff-gpu", "\\uf43f GPU")}"',
        '"\\uf4cb Disk"': f'"{t.get("ff-disk", "\\uf4cb Disk")}"',
        '"\\uf55b RAM"': f'"{t.get("ff-ram", "\\uf55b RAM")}"',
    }
    for old, new in keys.items():
        baseline = baseline.replace(old, new)
    return baseline


SDDM_TEMPLATE = (ROOT / "configs" / "sddm" / "Main.qml").read_text(encoding="utf-8")
FASTFETCH_BASELINE = (ROOT / "configs" / "fastfetch" / "config.jsonc").read_text(encoding="utf-8")


class SetLanguageHelper(unittest.TestCase):
    """`avalos-update-helper set-language`, con la raíz del sistema en un directorio temporal."""

    def setUp(self):
        self.h = load(HELPER, "avalos_update_helper_language_under_test")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.root = tmp / "root"
        self.lang_file = self.root / "etc" / "avalos-lang"
        self.template = self.root / "usr" / "share" / "avalos" / "configs" / "sddm" / "Main.qml"
        self.theme_dir = self.root / "usr" / "share" / "sddm" / "themes" / "avalos"
        (self.root / "etc").mkdir(parents=True)
        for patch in (mock.patch.object(self.h, "SYNC_ROOT", self.root),
                      mock.patch.object(self.h, "SUDOERS_AUR", tmp / "sudoers.d" / "zz-avalos"),
                      mock.patch.object(self.h, "AUR_LOCK", tmp / "aur.lock"),
                      mock.patch.object(self.h, "TMPFILES_AUR", tmp / "tmpfiles.d" / "avalos.conf"),
                      mock.patch("os.geteuid", return_value=0),
                      mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid())})):
            patch.start()
            self.addCleanup(patch.stop)

    def install_sddm(self, template=SDDM_TEMPLATE, rendered="viejo"):
        self.template.parent.mkdir(parents=True, exist_ok=True)
        self.template.write_text(template, encoding="utf-8")
        self.theme_dir.mkdir(parents=True, exist_ok=True)
        (self.theme_dir / "Main.qml").write_text(rendered, encoding="utf-8")

    def run_main(self, *argv):
        out = io.StringIO()
        with (mock.patch.object(sys, "argv", ["avalos-update-helper", *argv]),
              contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO())):
            try:
                self.h.main()
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, out.getvalue()

    def test_it_writes_the_language_file_the_way_the_installer_does(self):
        code, out = self.run_main("set-language", "--code", "zh")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lang_file.read_text(encoding="utf-8"), "zh\n")
        self.assertEqual(stat.S_IMODE(self.lang_file.stat().st_mode), 0o644)
        self.assertIn("idioma de AvalOS: zh", out)

    def test_the_login_screen_ends_up_exactly_as_if_the_installer_had_rendered_it(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.install_sddm()
                code, out = self.run_main("set-language", "--code", lang)
                self.assertEqual(code, 0, out)
                rendered = (self.theme_dir / "Main.qml").read_text(encoding="utf-8")
                self.assertEqual(rendered, installer_sddm(SDDM_TEMPLATE, lang))
                self.assertNotIn("%%SDDM_", rendered)

    def test_switching_back_and_forth_leaves_no_trace_of_the_previous_language(self):
        self.install_sddm()
        for lang in ("ja", "es", "en"):
            self.assertEqual(self.run_main("set-language", "--code", lang)[0], 0)
        self.assertEqual((self.theme_dir / "Main.qml").read_text(encoding="utf-8"), installer_sddm(SDDM_TEMPLATE, "en"))

    def test_an_unknown_language_is_rejected_by_argparse_and_nothing_is_written(self):
        for bad in ("fr", "EN", "", "../etc/passwd", "es;id", "zh\nja"):
            with self.subTest(code=bad):
                code, _ = self.run_main("set-language", "--code", bad)
                self.assertEqual(code, 2)
                self.assertFalse(self.lang_file.exists())

    def test_without_root_it_refuses_and_writes_nothing(self):
        with mock.patch("os.geteuid", return_value=1000):
            code, out = self.run_main("set-language", "--code", "es")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertFalse(self.lang_file.exists())

    def test_without_the_sddm_theme_the_language_still_changes_and_it_says_so(self):
        code, out = self.run_main("set-language", "--code", "ja")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lang_file.read_text(encoding="utf-8"), "ja\n")
        self.assertIn("SDDM", out)
        self.assertFalse(self.theme_dir.exists(), "no debe crear un tema que el sistema no tiene")

    def test_a_broken_sddm_template_warns_but_does_not_undo_the_language_and_keeps_the_old_login(self):
        for label, kwargs in (("sin plantilla", {}), ("marca desconocida", {"template": SDDM_TEMPLATE + "\n%%SDDM_NOPE%%\n"})):
            with self.subTest(case=label):
                self.install_sddm(rendered="login anterior", **kwargs)
                if label == "sin plantilla":
                    self.template.unlink()
                code, out = self.run_main("set-language", "--code", "es")
                self.assertEqual(code, 0, out)
                self.assertEqual(self.lang_file.read_text(encoding="utf-8"), "es\n")
                self.assertIn("aviso", out)
                self.assertEqual((self.theme_dir / "Main.qml").read_text(encoding="utf-8"), "login anterior")

    def test_the_helper_table_matches_translations_py(self):
        self.assertEqual(tuple(self.h.LANG_CODES), LANGS)
        names = {"SDDM_USER": "lbl-user", "SDDM_PASS": "lbl-pass", "SDDM_SIGNIN": "sddm-signin", "SDDM_FAIL": "sddm-fail",
                 "SDDM_SESSION": "sddm-session", "SDDM_SUSPEND": "sddm-suspend", "SDDM_RESTART": "sddm-restart",
                 "SDDM_SHUTDOWN": "sddm-shutdown"}
        for lang in LANGS:
            with self.subTest(lang=lang):
                table = self.h.SDDM_TEXTOS[lang]
                self.assertEqual(set(table), set(names))
                for mark, key in names.items():
                    self.assertEqual(table[mark], TRANSLATIONS[lang][key], f"{lang}/{mark}")
                    # van dentro de un literal de QML: ni comillas, ni barras, ni marcas
                    self.assertFalse(set(table[mark]) & set('"\\%\n'), f"{lang}/{mark}: {table[mark]!r}")

    def test_every_placeholder_of_the_template_is_known_to_the_helper(self):
        marks = set(re.findall(r"%%(SDDM_[A-Z]+)%%", SDDM_TEMPLATE))
        self.assertEqual(marks, set(self.h.SDDM_TEXTOS["en"]))


class FastfettLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load(LANGUAGE, "avalos_language_under_test")

    def test_the_table_matches_translations_py(self):
        modules = {"os": "ff-os", "host": "ff-host", "kernel": "ff-kernel", "uptime": "ff-uptime", "packages": "ff-packages",
                   "shell": "ff-shell", "display": "ff-display", "wm": "ff-wm", "terminal": "ff-terminal", "cpu": "ff-cpu",
                   "gpu": "ff-gpu", "memory": "ff-ram", "disk": "ff-disk"}
        self.assertEqual(self.m.SUPPORTED, LANGS)
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(set(self.m.FASTFETCH_KEYS[lang]), set(modules))
                for module, key in modules.items():
                    self.assertEqual(self.m.FASTFETCH_KEYS[lang][module], TRANSLATIONS[lang][key], f"{lang}/{module}")

    def test_relabeling_the_shipped_config_gives_what_the_installer_writes_in_every_language(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(self.m.relabel_fastfetch(FASTFETCH_BASELINE, lang), installer_fastfetch(FASTFETCH_BASELINE, lang))

    def test_it_does_not_matter_which_language_the_config_was_in_before(self):
        for first in LANGS:
            for second in LANGS:
                with self.subTest(first=first, second=second):
                    once = self.m.relabel_fastfetch(FASTFETCH_BASELINE, second)
                    via = self.m.relabel_fastfetch(self.m.relabel_fastfetch(FASTFETCH_BASELINE, first), second)
                    self.assertEqual(via, once)

    def test_only_the_keys_change(self):
        out = self.m.relabel_fastfetch(FASTFETCH_BASELINE, "ja")
        strip = lambda text: re.sub(r'"key"\s*:\s*"(?:[^"\\]|\\.)*"', '"key": ""', text)    # noqa: E731
        self.assertEqual(strip(out), strip(FASTFETCH_BASELINE))
        self.assertIn('"format": "AvalOS {build-id}"', out)
        self.assertIn("Created, Developed & Supported by", out)

    def test_a_module_the_user_removed_or_reordered_is_left_alone(self):
        custom = '{ "format": "x", "type": "os", "key": "MIO" },\n{ "type": "kernel", "key": " Kernel" },\n'
        out = self.m.relabel_fastfetch(custom, "es")
        self.assertIn('"key": "MIO"', out)                         # el «key» no va pegado al «type»: no se reconoce
        self.assertEqual(self.m.relabel_fastfetch("", "zh"), "")
        self.assertEqual(self.m.relabel_fastfetch("{ }", "zh"), "{ }")

    def test_the_file_is_rewritten_atomically_keeping_its_mode_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real.jsonc"
            real.write_text(FASTFETCH_BASELINE, encoding="utf-8")
            real.chmod(0o600)
            link = Path(tmp) / "config.jsonc"
            link.symlink_to(real)
            self.assertTrue(self.m.relabel_fastfetch_file(link, "zh"))
            self.assertTrue(link.is_symlink())
            self.assertEqual(real.read_text(encoding="utf-8"), installer_fastfetch(FASTFETCH_BASELINE, "zh"))
            self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o600)
            self.assertFalse(self.m.relabel_fastfetch_file(link, "zh"), "ya estaba así: no hay nada que reescribir")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["config.jsonc", "real.jsonc"], "sin temporales sobrantes")

    def test_a_missing_config_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(self.m.relabel_fastfetch_file(Path(tmp) / "nope.jsonc", "es"))


class ChangeLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load(LANGUAGE, "avalos_language_flow_under_test")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.lang_file = self.dir / "avalos-lang"
        self.lang_file.write_text("es\n", encoding="utf-8")
        self.ff = self.dir / "config.jsonc"
        self.ff.write_text(installer_fastfetch(FASTFETCH_BASELINE, "es"), encoding="utf-8")
        self.helper = self.dir / "avalos-update-helper"
        self.helper.write_text("#!/bin/sh\n", encoding="utf-8")
        self.helper.chmod(0o755)
        patch = mock.patch.object(self.m, "HELPER", str(self.helper))
        patch.start()
        self.addCleanup(patch.stop)
        self.calls = []

    def runner(self, returncode=0, stdout="", stderr=""):
        def run(argv, **kwargs):
            self.calls.append(argv)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        return run

    def change(self, code, **runner_args):
        return self.m.change_language(code, run=self.runner(**runner_args), lang_file=self.lang_file, ff_config=self.ff)

    def test_success_calls_the_helper_through_pkexec_and_relabels_fastfetch(self):
        self.assertEqual(self.change("ja"), ("done", ""))
        self.assertEqual(self.calls, [["pkexec", str(self.helper), "set-language", "--code", "ja"]])
        self.assertEqual(self.ff.read_text(encoding="utf-8"), installer_fastfetch(FASTFETCH_BASELINE, "ja"))

    def test_choosing_the_current_language_does_nothing(self):
        self.assertEqual(self.change("es"), ("same", ""))
        self.assertEqual(self.calls, [])

    def test_cancelling_the_password_dialog_changes_nothing(self):
        before = self.ff.read_text(encoding="utf-8")
        for rc in (126, 127):
            with self.subTest(rc=rc):
                self.assertEqual(self.change("en", returncode=rc), ("cancelled", ""))
                self.assertEqual(self.ff.read_text(encoding="utf-8"), before)

    def test_an_old_helper_that_does_not_know_set_language_is_reported_as_outdated(self):
        before = self.ff.read_text(encoding="utf-8")
        err = "avalos-update-helper: error: argument cmd: invalid choice: 'set-language' (choose from 'apply-system', ...)"
        self.assertEqual(self.change("en", returncode=2, stderr=err), ("outdated", ""))
        self.assertEqual(self.ff.read_text(encoding="utf-8"), before)

    def test_a_helper_error_is_reported_with_its_last_line_and_does_not_touch_fastfetch(self):
        before = self.ff.read_text(encoding="utf-8")
        self.assertEqual(self.change("en", returncode=1, stdout="### idioma\n### ERROR: no hay espacio\n"), ("error", "no hay espacio"))
        self.assertEqual(self.ff.read_text(encoding="utf-8"), before)

    def test_a_missing_helper_or_unknown_code_never_calls_pkexec(self):
        self.helper.unlink()
        self.assertEqual(self.change("en")[0], "error")
        self.helper.write_text("#!/bin/sh\n", encoding="utf-8")
        self.helper.chmod(0o755)
        for bad in ("fr", "", "es;id", "../x"):
            self.assertEqual(self.change(bad)[0], "error")
        self.assertEqual(self.calls, [])

    def test_current_language_reads_the_file_then_lang_then_english(self):
        env = {"LANG": "ja_JP.UTF-8"}
        self.assertEqual(self.m.current_language(self.lang_file, env), "es")
        self.lang_file.write_text("basura\n", encoding="utf-8")
        self.assertEqual(self.m.current_language(self.lang_file, env), "ja")
        self.assertEqual(self.m.current_language(self.dir / "no-existe", {"LANG": "pt_BR.UTF-8"}), "en")
        self.assertEqual(self.m.current_language(self.dir / "no-existe", {}), "en")

    def test_the_rofi_menu_marks_the_current_language_and_maps_the_choice_back(self):
        seen = {}

        def rofi(argv, **kwargs):
            seen["input"] = kwargs["input"]
            return SimpleNamespace(returncode=0, stdout="   中文（简体）\n", stderr="")
        self.assertEqual(self.m.pick_with_rofi("es", run=rofi), "zh")
        lines = seen["input"].splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("✔  Español", lines[1])
        self.assertEqual(sum("✔" in ln for ln in lines), 1)
        self.assertIsNone(self.m.pick_with_rofi("es", run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="")))

    def test_the_command_line(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            self.m.main(["--set", "fr"])
        self.assertEqual(raised.exception.code, 2)
        out = io.StringIO()
        with mock.patch.object(self.m, "LANG_FILE", self.lang_file), contextlib.redirect_stdout(out):
            self.assertEqual(self.m.main(["--current"]), 0)
        self.assertEqual(out.getvalue().strip(), "es")

    def test_every_result_has_a_message_in_the_four_languages(self):
        for lang in LANGS:
            table = self.m.STRINGS[lang]
            for key in ("title", "done", "same", "outdated", "failed", "no-rofi"):
                self.assertTrue(table[key].strip(), f"{lang}/{key}")
            self.assertIn("{name}", table["done"])
            self.assertIn("{why}", table["failed"])


class Wiring(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_the_settings_menu_offers_it_in_every_language_and_the_menu_height_fits_every_entry(self):
        src = self.read("scripts/avalos-settings")
        self.assertEqual(len(re.findall(r'^\s+T_LANGUAGE="', src, re.M)), 4)
        menu = src.split("chosen=$(printf", 1)[1].split("| rofi", 1)[0]
        entries = re.findall(r'"\$T_[A-Z_]+"', menu)
        self.assertIn('"$T_LANGUAGE"', entries)
        self.assertEqual(int(re.search(r"listview \{lines: (\d+);\}", src).group(1)), len(entries),
                         "las líneas del menú de rofi tienen que ser tantas como entradas (si no, hay que hacer scroll)")
        self.assertRegex(src, r'\[\[ "\$chosen" == "\$T_LANGUAGE" \]\]; then\n(?:    #.*\n)*    _run avalos-language\n')

    def test_the_control_center_has_a_language_tile_with_texts_in_four_languages(self):
        src = self.read("scripts/avalos-control")
        self.assertRegex(src, r'\("session", "language", \("avalos-language",\), ')
        self.assertEqual(len(re.findall(r'"t-language": ".+", "d-language": ".+",', src)), 4)

    def test_it_is_installed_synced_and_shipped_in_the_iso(self):
        self.assertIn('("scripts/avalos-language", "/usr/local/bin/avalos-language", 0o755)', self.read("scripts/avalos-update-helper"))
        self.assertIn('"scripts/avalos-language",', self.read("scripts/gen-sync-manifest.py"))
        self.assertRegex(self.read(".github/workflows/build-iso.yml"), r"for _s in [^\n]*\bavalos-language\b")
        self.assertIn('"avalos-language"', self.read("scripts/avalos_installer/system/optimize.py"))
        self.assertIn('"avalos-language"', self.read("scripts/skill_instalar_usb.py"))

    def test_the_script_is_executable_and_compiles(self):
        self.assertTrue(LANGUAGE.stat().st_mode & 0o111)
        self.assertEqual(subprocess.run([sys.executable, "-m", "py_compile", str(LANGUAGE)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
