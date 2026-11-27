"""Los íconos Nerd Font del repo: ninguno puede quedar «en blanco».

Reporte (25 nov 2026, capturas de Jeff): el menú de Ajustes salía sin íconos y a fastfetch le faltaban los de OS, Kernel,
Shell, WM, Terminal y CPU. Al revisar, el mismo problema estaba en el menú de energía, en rofi y en waybar, donde el botón
de apagado de la barra tenía el texto VACÍO (un botón invisible).

Causa: un ícono escrito como carácter crudo del área privada BMP (U+E000–U+F8FF) se perdía al guardar o transferir el
archivo y solo quedaba el espacio de al lado. Los del plano 15 (U+F0000 en adelante) y los escritos como escape JSON
sobrevivían. Además, los 7 íconos de fastfetch que sí se veían usaban códigos de Nerd Fonts v2 (U+F55F, U+F879 y U+F55B ni
existen en v3): se dibujaban por casualidad con otra fuente y no eran los que se quisieron (Packages salía como una tarjeta
de crédito, GPU como «repo clone»).

Convención desde ahora: TODO ícono es nf-md (Material Design de Nerd Fonts v3, U+F0001–U+F1AF0, plano 15), que es lo que ya
usaban waybar y el menú de energía. En archivos JSON se escribe como escape ASCII (par sustituto), que no se puede perder; en
bash y rasi, que no tienen escapes utilizables, como carácter crudo. Los nombres de abajo se comprobaron contra
glyphnames.json de Nerd Fonts 3.5.1 (el fuente que trae la versión que instala AvalOS: ttf-jetbrains-mono-nerd).
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from translations import TRANSLATIONS
finally:
    sys.path.pop(0)

LANGS = ("en", "es", "zh", "ja")
NF_MD = range(0xF0001, 0xF1AF1)
KNOWN = {
    0xF056E: "md-view_dashboard",
    0xF03D8: "md-palette",
    0xF0379: "md-monitor",
    0xF057E: "md-volume_high",
    0xF05A9: "md-wifi",
    0xF00AF: "md-bluetooth",
    0xF0E09: "md-wallpaper",
    0xF024B: "md-folder",
    0xF05CA: "md-translate",
    0xF0004: "md-account",
    0xF006F: "md-backup_restore",
    0xF05F6: "md-heart_pulse",
    0xF14DE: "md-rocket_launch",
    0xF02FC: "md-information",
    0xF0493: "md-cog",
    0xF0425: "md-power",
    0xF0709: "md-restart",
    0xF0904: "md-power_sleep",
    0xF033E: "md-lock",
    0xF0343: "md-logout",
    0xF0426: "md-power_settings",
    0xF012C: "md-check",
    0xF0156: "md-close",
    0xF07B7: "md-console_line",
    0xF05B2: "md-window_restore",
    0xF0349: "md-magnify",
    0xF018D: "md-console",
    0xF0239: "md-firefox",
    0xF02AF: "md-google_chrome",
    0xF0169: "md-code_braces",
    0xF0A1E: "md-microsoft_visual_studio_code",
    0xF0150: "md-clock_outline",
    0xF00ED: "md-calendar",
    0xF0EE0: "md-cpu_64_bit",
    0xF033D: "md-linux",
    0xF01C4: "md-desktop_mac",
    0xF061A: "md-chip",
    0xF051F: "md-timer_sand",
    0xF03D7: "md-package_variant_closed",
    0xF05AF: "md-window_maximize",
    0xF0FB2: "md-expansion_card_variant",
    0xF035B: "md-memory",
    0xF02CA: "md-harddisk",
    0xF02D1: "md-heart",
}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def decode(value):
    """Texto de un valor JSON, con sus escapes \\uXXXX (también pares sustitutos) ya resueltos."""
    return json.loads('"' + value + '"') if "\\u" in value else value


def icon_of(value):
    """Código del ícono con el que empieza `value` (que debe ir seguido de un espacio), o None."""
    text = decode(value)
    if len(text) >= 2 and text[1] == " " and ord(text[0]) in NF_MD:
        return ord(text[0])
    return None


def glyphs_in(text):
    """Todos los caracteres del área privada de un archivo, crudos o como escape JSON."""
    resolved = re.sub(r"\\u[dD][89abAB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}", lambda m: json.loads('"' + m.group() + '"'), text)
    resolved = re.sub(r"\\u([eE-fF][0-9a-fA-F]{3})", lambda m: chr(int(m.group(1), 16)), resolved)
    return [ord(c) for c in resolved if 0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0xFFFFD]


class SettingsMenu(unittest.TestCase):
    def setUp(self):
        self.src = read("scripts/avalos-settings")
        menu = self.src.split("chosen=$(printf", 1)[1].split("| rofi", 1)[0]
        self.entries = [name.lstrip("$") for name in re.findall(r'"(\$T_[A-Z_]+)"', menu)]
        self.values = {}
        for name, value in re.findall(r'^\s+(T_[A-Z_]+)="(.*)"$', self.src, re.M):
            self.values.setdefault(name, []).append(value)

    def test_every_entry_and_the_title_starts_with_an_icon_in_all_four_languages(self):
        self.assertGreaterEqual(len(self.entries), 14)
        for name in self.entries + ["T_TITLE"]:
            values = self.values[name]
            self.assertEqual(len(values), 4, name)
            icons = {icon_of(v) for v in values}
            with self.subTest(entry=name):
                self.assertNotIn(None, icons, f"{name}: alguna traducción no empieza con ícono + espacio: {values}")
                self.assertEqual(len(icons), 1, f"{name}: el ícono debe ser el mismo en los 4 idiomas")
                self.assertLessEqual(icons, set(KNOWN), f"{name}: ícono que no está en la lista verificada de este test")

    def test_each_entry_has_its_own_icon(self):
        icons = [icon_of(self.values[name][0]) for name in self.entries]
        self.assertEqual(len(set(icons)), len(icons), "dos entradas del menú comparten ícono")


class PowerMenu(unittest.TestCase):
    NAMES = ("T_OFF", "T_REBOOT", "T_SUSPEND", "T_LOGOUT", "T_LOCK", "T_TITLE")

    def setUp(self):
        self.src = read("configs/rofi/powermenu.sh")

    def test_every_entry_has_an_icon_in_all_four_languages_and_the_same_one(self):
        for name in self.NAMES:
            values = re.findall(rf'^\s+{name}="(.*)"$', self.src, re.M)
            self.assertEqual(len(values), 4, name)
            icons = {icon_of(v.replace("  ", " ", 1)) for v in values}      # el menú usa ícono + dos espacios
            with self.subTest(entry=name):
                self.assertNotIn(None, icons, values)
                self.assertEqual(len(icons), 1)
                self.assertLessEqual(icons, set(KNOWN))

    def test_the_yes_no_confirmation_has_icons_too(self):
        pairs = re.findall(r'yes="([^"]*)" no="([^"]*)"', self.src)
        self.assertEqual(len(pairs), 4)
        for yes, no in pairs:
            self.assertIsNotNone(icon_of(yes.replace("  ", " ", 1)), yes)
            self.assertIsNotNone(icon_of(no.replace("  ", " ", 1)), no)
            self.assertNotEqual(yes[0], no[0])

    def test_the_translations_py_copies_match_the_script(self):
        mapping = {"pm-off": "T_OFF", "pm-reboot": "T_REBOOT", "pm-suspend": "T_SUSPEND", "pm-logout": "T_LOGOUT",
                   "pm-lock": "T_LOCK", "pm-title": "T_TITLE"}
        for key, name in mapping.items():
            script_icon = {icon_of(v.replace("  ", " ", 1)) for v in re.findall(rf'^\s+{name}="(.*)"$', self.src, re.M)}
            for lang in LANGS:
                with self.subTest(key=key, lang=lang):
                    self.assertEqual({icon_of(TRANSLATIONS[lang][key].replace("  ", " ", 1))}, script_icon)


class Rofi(unittest.TestCase):
    def test_every_mode_and_the_search_placeholder_have_an_icon(self):
        src = read("configs/rofi/config.rasi")
        for key in ("display-drun", "display-run", "display-window", "placeholder"):
            value = re.search(rf'^\s*{key}:\s+"([^"]*)";', src, re.M).group(1)
            with self.subTest(key=key):
                self.assertIsNotNone(icon_of(value), value)
                self.assertIn(icon_of(value), KNOWN)


class Waybar(unittest.TestCase):
    def setUp(self):
        self.src = read("configs/waybar/config.jsonc")

    def value(self, pattern):
        return re.search(pattern, self.src, re.S).group(1)

    def test_the_power_button_is_visible(self):
        fmt = self.value(r'"custom/powermenu":\s*\{\s*"format":\s*"([^"]*)"')
        self.assertTrue(decode(fmt).strip(), "el botón de apagado de la barra no puede tener el texto vacío: no se vería")
        self.assertEqual(ord(decode(fmt)[0]), 0xF0425)

    def test_clock_and_cpu_have_their_icons(self):
        for pattern in (r'"clock":\s*\{\s*"format":\s*"([^"]*)"', r'"clock":\s*\{.*?"format-alt":\s*"([^"]*)"', r'"cpu":\s*\{\s*"format":\s*"([^"]*)"'):
            with self.subTest(pattern=pattern):
                self.assertIn(icon_of(self.value(pattern)), KNOWN)

    def test_every_window_title_rewrite_rule_has_an_icon(self):
        block = self.value(r'"rewrite":\s*\{(.*?)\}')
        rules = re.findall(r'^\s+"[^"\n]+":\s+"([^"]+)",?\s*$', block, re.M)
        self.assertEqual(len(rules), 6)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn(icon_of(rule), KNOWN)


class Fastfetch(unittest.TestCase):
    MODULES = ("os", "host", "kernel", "uptime", "packages", "shell", "display", "wm", "terminal", "cpu", "gpu", "memory", "disk")
    TKEY = {"os": "ff-os", "host": "ff-host", "kernel": "ff-kernel", "uptime": "ff-uptime", "packages": "ff-packages",
            "shell": "ff-shell", "display": "ff-display", "wm": "ff-wm", "terminal": "ff-terminal", "cpu": "ff-cpu",
            "gpu": "ff-gpu", "memory": "ff-ram", "disk": "ff-disk"}

    def setUp(self):
        self.src = read("configs/fastfetch/config.jsonc")
        self.keys = dict(re.findall(r'\{ "type": "(\w+)",\s+"key": "([^"]*)"', self.src))

    def test_all_thirteen_rows_have_an_nf_md_icon(self):
        self.assertEqual(set(self.keys), set(self.MODULES))
        for module, key in self.keys.items():
            with self.subTest(module=module):
                self.assertIn(icon_of(key), KNOWN, key)

    def test_no_row_keeps_a_nerd_fonts_v2_code(self):
        self.assertEqual([c for c in glyphs_in(self.src) if c not in NF_MD], [], "quedan íconos fuera de nf-md (códigos de v2 o BMP)")

    def test_every_translation_uses_the_same_icon_as_the_shipped_config(self):
        for module in self.MODULES:
            expected = icon_of(self.keys[module])
            for lang in LANGS:
                with self.subTest(module=module, lang=lang):
                    self.assertEqual(icon_of(TRANSLATIONS[lang][self.TKEY[module]]), expected)

    def test_the_credits_line_has_its_icon(self):
        credits = re.search(r'"type": "custom", "format": "([^"]*AvalOS — Created[^"]*)"', self.src).group(1)
        self.assertIn(ord(decode(credits)[0]), KNOWN)


class Convention(unittest.TestCase):
    def test_every_icon_in_the_checked_files_is_nf_md_and_none_is_a_bare_bmp_character(self):
        files = ("scripts/avalos-settings", "configs/rofi/powermenu.sh", "configs/rofi/config.rasi", "configs/waybar/config.jsonc",
                 "configs/fastfetch/config.jsonc")
        for rel in files:
            found = glyphs_in(read(rel))
            with self.subTest(file=rel):
                self.assertTrue(found)
                self.assertEqual([hex(c) for c in found if c not in NF_MD], [])

    def test_the_known_names_are_all_material_design_icons(self):
        self.assertTrue(all(name.startswith("md-") for name in KNOWN.values()))
        self.assertTrue(all(code in NF_MD for code in KNOWN))


if __name__ == "__main__":
    unittest.main(verbosity=2)
