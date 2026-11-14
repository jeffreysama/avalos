"""Guardias de robustez para las herramientas de AvalOS (hallazgos de la auditoría de 2026-11-13 que NO eran bugs hoy,
pero que si se rompen mañana se rompen en silencio):

  · i18n: cada tabla de textos (instalador y las 9 herramientas) trae las mismas claves en los 4 idiomas y los mismos
    placeholders. Un `{n}` que falta en la traducción japonesa solo revienta (KeyError) cuando alguien abre la app en
    japonés: el idioma que menos se prueba.
  · Doctor: sobre un sistema ROTO (comandos que fallan o devuelven basura, archivos con bytes raros) ningún chequeo
    puede lanzar una excepción ni devolver un texto que no se pueda formatear en los 4 idiomas — el Doctor existe
    precisamente para correr cuando algo anda mal.
  · Parsers puros (gamecenter, version): ninguna entrada de texto, por rara que sea, los hace lanzar.

El azar va con semilla fija: si algo falla, falla siempre igual y se puede reproducir.
"""
import ast
import importlib.machinery
import importlib.util
import random
import string
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
LANGS = {"en", "es", "zh", "ja"}
TOOLS_WITH_STRINGS = ["avalos-control", "avalos-doctor", "avalos-gamecenter", "avalos-restore", "avalos-store",
                      "avalos-update", "avalos-wallpaper", "avalos-welcome", "avalos-version"]
fmt = string.Formatter()


def load(path, name):
    sys.modules.setdefault("webview", types.ModuleType("webview"))
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def fields(text):
    """Nombres de campo de str.format: lanza ValueError si las llaves están mal."""
    return sorted(f for _, f, _, _ in fmt.parse(text) if f is not None)


def lang_tables(path):
    """{nombre_de_variable: {idioma: {clave: texto}}} para toda `X = {"en": {...}, "es": {...}, ...}` del archivo."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and isinstance(node.targets[0], ast.Name):
            keys = [const_str(k) for k in node.value.keys]
            if keys and set(keys) <= LANGS and all(isinstance(v, ast.Dict) for v in node.value.values):
                out[node.targets[0].id] = {
                    lang: {const_str(k): const_str(v) for k, v in zip(d.keys, d.values)}
                    for lang, d in zip(keys, node.value.values)}
    return out


class I18nConsistency(unittest.TestCase):
    def check_table(self, label, table):
        self.assertEqual(set(table), LANGS, f"{label}: faltan idiomas")
        base_keys = set().union(*[set(t) for t in table.values()])
        for lang, t in table.items():
            missing = sorted(base_keys - set(t), key=str)
            self.assertEqual(missing, [], f"{label}[{lang}]: faltan {len(missing)} claves, p. ej. {missing[:5]}")
        for key in sorted(base_keys, key=str):
            seen = {}
            for lang, t in table.items():
                value = t.get(key)
                if value is None:
                    continue
                self.assertIsInstance(value, str, f"{label}[{lang}][{key}] no es un texto literal")
                try:
                    seen[lang] = fields(value)
                except ValueError as e:
                    self.fail(f"{label}[{lang}][{key}]: llaves mal formadas ({e}): {value[:60]!r}")
            self.assertEqual(len({tuple(v) for v in seen.values()}), 1, f"{label}[{key}]: placeholders distintos entre idiomas: {seen}")

    def test_every_tool_has_the_same_keys_and_placeholders_in_all_four_languages(self):
        for tool in TOOLS_WITH_STRINGS:
            tables = lang_tables(SCRIPTS / tool)
            self.assertTrue(tables, f"{tool}: no encontré su tabla de textos (¿cambió el formato?)")
            for name, table in tables.items():
                with self.subTest(tool=tool, table=name):
                    self.check_table(f"{tool}.{name}", table)

    def test_the_installer_translations_are_complete_and_only_the_step_detail_keys_may_be_empty(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            from translations import TRANSLATIONS
        finally:
            sys.path.pop(0)
        self.assertEqual(set(TRANSLATIONS), LANGS)
        self.check_table("translations.TRANSLATIONS", TRANSLATIONS)
        for lang, table in TRANSLATIONS.items():
            empty = sorted(k for k, v in table.items() if not v.strip())
            self.assertTrue(all(k.startswith("step-") and k.endswith("-d") for k in empty), f"{lang}: textos vacíos fuera de step-*-d: {empty}")


JUNK = ["", " ", "\n", "\n\n\n", "0", "-1", "nan", "inf", "99999999999999999999", "x" * 5000, "\x00\x01\x02", "ÿþ", "{", "[]", "null", "{}",
        "Filesystem Size Used Avail Use% Mounted on\n", "a b c d e f g\n", "1 2 3\n", "default via\n", "default via dev\n", "nameserver\n",
        "Device Size Used\n", "Label: none uuid:\n", "Total devices 0\n", "UNCONFIGURED\n", "flathub\n", "\t\t\t", "/dev/sda1 [/@] rw\n",
        "gamemode is active\n", "gamemode is inactive\n", "[general]\nrenice=\n", "= = =\n", "DP-1 1920x1080@60\n", "#\n##\n###\n"]
ALPHABET = string.printable + "áéñ中日\x00\x1b\u202e"


def junk(rnd):
    if rnd.random() < 0.6:
        return rnd.choice(JUNK)
    return "".join(rnd.choice(ALPHABET) for _ in range(rnd.randint(1, 400)))


class DoctorOnABrokenSystem(unittest.TestCase):
    ROUNDS = 60

    def test_no_check_raises_or_produces_unformattable_text_on_garbage_input(self):
        doc = load(SCRIPTS / "avalos-doctor", "avalos_doctor_fuzz")
        rnd = random.Random(1234)

        def fake_run(cmd, timeout=6):
            return rnd.choice([0, 0, 1, 2, 127, -1]), junk(rnd)

        class FakeProc:
            def __init__(self):
                self.returncode, self.stdout, self.stderr = rnd.choice([0, 1, 127]), junk(rnd), junk(rnd)

        failures = []
        for _ in range(self.ROUNDS):
            doc._CACHE.clear()
            with mock.patch.object(doc, "_run", fake_run), mock.patch.object(doc, "_read", lambda path: junk(rnd)), \
                 mock.patch.object(doc.subprocess, "run", side_effect=lambda *a, **k: FakeProc()), \
                 mock.patch.object(doc, "_probe", lambda *a, **k: rnd.choice([True, False, None])):
                for cid, _group, fn, _net in doc.CHECKS:
                    try:
                        status, key, args, _action = fn()
                        self.assertIn(status, ("ok", "info", "skip", "warn", "fail"))
                        for lang in LANGS:
                            doc.STRINGS[lang][key].format(**args)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"{cid}: {type(e).__name__}: {str(e)[:80]}")
        self.assertEqual(sorted(set(failures)), [], f"{len(failures)} fallos")


class PureParsers(unittest.TestCase):
    ROUNDS = 400

    def test_gamecenter_and_version_parsers_never_raise(self):
        gc = load(SCRIPTS / "avalos-gamecenter", "avalos_gamecenter_fuzz")
        ver = load(SCRIPTS / "avalos-version", "avalos_version_fuzz")
        parsers = [gc.parse_gamemode_status, gc.parse_gamemode_ini, gc.parse_monitors, gc._line_key, gc._effective_lines,
                   gc._natural_key, ver.parse_build, ver.parse_scripts]
        rnd = random.Random(7)
        for _ in range(self.ROUNDS):
            text = junk(rnd)
            for fn in parsers:
                try:
                    fn(text)
                except Exception as e:  # noqa: BLE001
                    self.fail(f"{fn.__name__}({text[:40]!r}) lanzó {type(e).__name__}: {e}")


if __name__ == "__main__":
    unittest.main()
