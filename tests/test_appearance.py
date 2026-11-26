"""El cursor que se elige en «Apariencia» (nwg-look) tiene que cambiar de verdad.

Reporte (25 nov 2026): en Ajustes → Apariencia el tipo de letra y el esquema de color sí cambian, el cursor no.

Causa, comprobada en el código de nwg-look 1.2.1 y de Hyprland:
  · «Apply» de nwg-look escribe gsettings, settings.ini e index.theme, pero nunca llama a hyprctl: el compositor,
    XWayland y las apps que leen XCURSOR_* (kitty, Qt, Electron) no se enteran.
  · hyprland.lua fijaba XCURSOR_THEME=capitaine-cursors, y Hyprland (cursor:sync_gsettings_theme, activo por
    defecto) reescribe gsettings con ESE tema cada vez que carga su cursor: la elección se revertía sola.

Arreglo: scripts/avalos-appearance (nwg-look + aplicar el cursor en vivo) y un bloque en hyprland.lua que lee el mismo
settings.ini al arrancar. Se prueba el script real con hyprctl/nwg-look de mentira, y el bloque Lua con un intérprete
de Lua (en CI viene lua5.4; si no hay, esa parte se omite).
"""
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPEARANCE = ROOT / "scripts" / "avalos-appearance"
LIVE_LUA = ROOT / "configs" / "hyprland" / "hyprland.lua"
TEMPLATE_LUA = ROOT / "configs" / "hyprland" / "hyprland_conf_lua.template"
LUA = shutil.which("lua5.4") or shutil.which("lua")
BASH = shutil.which("bash")
SYSTEM_TOOLS = ("awk", "cat", "sleep", "stat", "tr")

INI = "[Settings]\ngtk-theme-name = Adwaita-dark\ngtk-cursor-theme-name = {theme}\ngtk-cursor-theme-size = {size}\n"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        # PATH aislado: solo estas herramientas del sistema (por enlace) y los stubs de cada test. Sin esto, un hyprctl o un
        # nwg-look REALES (en el equipo de Jeff están los dos) se ejecutarían de verdad durante los tests.
        for name in SYSTEM_TOOLS:
            real = shutil.which(name)
            if real is None:
                self.skipTest(f"este sistema no tiene `{name}`")
            (self.bin / name).symlink_to(real)
        self.log = self.dir / "hyprctl.log"
        self.ini = self.dir / "settings.ini"
        self.stub("hyprctl", f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{self.log}"\n')
        # Aislar el test de la máquina: un gsettings real contestaría con el tema de quien lo corre («Adwaita»).
        self.stub("gsettings", "#!/bin/sh\nexit 1\n")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def env(self, **extra):
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.dir),
            "HYPRLAND_INSTANCE_SIGNATURE": "test-instance",
            "AVALOS_GTK_SETTINGS": str(self.ini),
            "AVALOS_APPEARANCE_POLL": "0.1",
        }
        env.update(extra)
        return env

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def apply(self, **extra_env):
        proc = subprocess.run([BASH, str(APPEARANCE), "--apply-cursor"], env=self.env(**extra_env),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.calls()


class ApplyCursor(Sandbox):
    def test_the_saved_theme_and_size_reach_hyprland_in_both_ways(self):
        self.ini.write_text(INI.format(theme="capitaine-cursors-white", size=32), encoding="utf-8")
        calls = self.apply()
        self.assertEqual(calls, [
            "eval hl.env('XCURSOR_THEME', 'capitaine-cursors-white'); hl.env('XCURSOR_SIZE', '32')",
            "setcursor capitaine-cursors-white 32",
        ])

    def test_it_reads_the_format_nwg_look_writes_and_ignores_other_sections(self):
        self.ini.write_text(
            "[Settings]\ngtk-theme-name=Adwaita-dark\ngtk-cursor-theme-name=Bibata-Modern-Classic\n"
            "gtk-cursor-theme-size=28\n[Other]\ngtk-cursor-theme-name=Wrong\ngtk-cursor-theme-size=99\n",
            encoding="utf-8")
        self.assertEqual(self.apply()[-1], "setcursor Bibata-Modern-Classic 28")

    def test_a_theme_that_could_not_be_a_folder_name_is_never_sent_to_hyprland(self):
        for bad in ("foo'bar", "a b", "x;y", "$(id)", "`id`", "tema\"x", "../etc", ""):
            with self.subTest(theme=bad):
                self.log.unlink(missing_ok=True)
                self.ini.write_text(f"[Settings]\ngtk-cursor-theme-name = {bad}\ngtk-cursor-theme-size = 24\n", encoding="utf-8")
                self.assertEqual(self.apply(), [])

    def test_a_missing_or_absurd_size_falls_back_to_24(self):
        for size in ("", "abc", "4", "9999", "-3"):
            with self.subTest(size=size):
                self.log.unlink(missing_ok=True)
                self.ini.write_text(INI.format(theme="capitaine-cursors", size=size), encoding="utf-8")
                self.assertEqual(self.apply()[-1], "setcursor capitaine-cursors 24")

    def test_a_size_with_leading_zeros_is_not_read_as_octal(self):
        self.ini.write_text(INI.format(theme="capitaine-cursors", size="024"), encoding="utf-8")
        self.assertEqual(self.apply()[-1], "setcursor capitaine-cursors 24")
        self.log.unlink()
        self.ini.write_text(INI.format(theme="capitaine-cursors", size="08"), encoding="utf-8")
        self.assertEqual(self.apply()[-1], "setcursor capitaine-cursors 8")

    def test_without_settings_ini_it_falls_back_to_gsettings_and_without_both_it_does_nothing(self):
        self.assertEqual(self.apply(), [])
        self.stub("gsettings", "#!/bin/sh\ncase \"$3\" in cursor-theme) echo \"'capitaine-cursors-white'\";; cursor-size) echo 30;; esac\n")
        self.assertEqual(self.apply()[-1], "setcursor capitaine-cursors-white 30")

    def test_outside_hyprland_or_without_hyprctl_it_does_nothing_and_does_not_fail(self):
        self.ini.write_text(INI.format(theme="capitaine-cursors", size=24), encoding="utf-8")
        proc = subprocess.run([BASH, str(APPEARANCE), "--apply-cursor"], capture_output=True, text=True, timeout=30,
                              env={"PATH": str(self.bin), "HOME": str(self.dir), "AVALOS_GTK_SETTINGS": str(self.ini)})
        self.assertEqual((proc.returncode, self.calls()), (0, []))
        (self.bin / "hyprctl").unlink()
        self.assertEqual(self.apply(), [])      # sin hyprctl en el PATH (aislado: el del equipo no cuenta)


class Launcher(Sandbox):
    def fake_nwg_look(self, new_theme=None, exit_code=0):
        rewrite = ""
        if new_theme:
            rewrite = f'sleep 0.5\nprintf "[Settings]\\ngtk-cursor-theme-name={new_theme}\\ngtk-cursor-theme-size=24\\n" > "{self.ini}"\n'
        self.stub("nwg-look", f"#!/bin/sh\n{rewrite}sleep 1.2\nexit {exit_code}\n")

    def run_launcher(self):
        return subprocess.run([BASH, str(APPEARANCE)], env=self.env(), capture_output=True, text=True, timeout=60)

    def test_pressing_apply_changes_the_cursor_once_and_the_launcher_returns_nwg_looks_exit_code(self):
        self.ini.write_text(INI.format(theme="capitaine-cursors", size=24), encoding="utf-8")
        self.fake_nwg_look(new_theme="capitaine-cursors-white", exit_code=3)
        proc = self.run_launcher()
        self.assertEqual(proc.returncode, 3, proc.stderr)
        # una sola vez: el cambio se aplica con la ventana abierta, y al cerrarla ya no hay nada nuevo que aplicar
        self.assertEqual([c for c in self.calls() if c.startswith("setcursor")], ["setcursor capitaine-cursors-white 24"])

    def test_the_cursor_is_applied_while_nwg_look_is_still_open(self):
        self.ini.write_text(INI.format(theme="capitaine-cursors", size=24), encoding="utf-8")
        self.stub("nwg-look", f'#!/bin/sh\nsleep 0.4\nprintf "[Settings]\\ngtk-cursor-theme-name=Bibata-Modern-Classic\\n" > "{self.ini}"\nsleep 4\n')
        proc = subprocess.Popen([BASH, str(APPEARANCE)], env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(c.startswith("setcursor") for c in self.calls()):
            time.sleep(0.1)
        self.assertIsNone(proc.poll(), "nwg-look debería seguir abierto")
        self.assertIn("setcursor Bibata-Modern-Classic 24", self.calls())
        proc.wait(timeout=30)

    def test_closing_without_changes_still_aligns_the_compositor_with_what_is_saved(self):
        # p. ej. un hyprland.lua viejo arrancó con el tema fijo y settings.ini guarda otro
        self.ini.write_text(INI.format(theme="capitaine-cursors-white", size=24), encoding="utf-8")
        self.fake_nwg_look()
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertEqual([c for c in self.calls() if c.startswith("setcursor")], ["setcursor capitaine-cursors-white 24"])

    def test_without_nwg_look_it_fails_with_a_message_instead_of_hanging(self):
        proc = subprocess.run([BASH, str(APPEARANCE)], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nwg-look", proc.stderr)


def cursor_block(path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"-- avalos:cursor-begin\n(.*?)-- avalos:cursor-end", text, re.S)
    assert match, f"{path.name}: falta el bloque de cursor"
    return match.group(1)


@unittest.skipUnless(LUA, "no hay intérprete de Lua (en CI viene lua5.4)")
class HyprlandLuaBlock(Sandbox):
    """Corre el bloque real (el que está entre los marcadores) con un `hl` de mentira que solo imprime hl.env."""

    def run_block(self, path, ini_text=None, home=True):
        if ini_text is not None:
            (self.dir / ".config" / "gtk-3.0").mkdir(parents=True, exist_ok=True)
            (self.dir / ".config" / "gtk-3.0" / "settings.ini").write_text(ini_text, encoding="utf-8")
        program = ('hl = { env = function(k, v) print(k .. "=" .. v) end }\n' + cursor_block(path))
        env = {"HOME": str(self.dir)} if home else {}
        proc = subprocess.run([LUA, "-"], input=program, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.splitlines()

    def test_live_and_installed_configs_carry_the_same_block(self):
        self.assertEqual(cursor_block(LIVE_LUA), cursor_block(TEMPLATE_LUA))

    def test_the_theme_is_no_longer_hardcoded(self):
        for path in (LIVE_LUA, TEMPLATE_LUA):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r'hl\.env\("XCURSOR_THEME",\s+"capitaine-cursors"\)')
                self.assertIn('hl.env("XCURSOR_THEME", cursor_theme)', text)
                self.assertIn('hl.env("XCURSOR_SIZE",  cursor_size)', text)

    def test_what_nwg_look_saved_is_what_hyprland_starts_with(self):
        for path in (LIVE_LUA, TEMPLATE_LUA):
            with self.subTest(path=path.name):
                out = self.run_block(path, INI.format(theme="capitaine-cursors-white", size=32))
                self.assertEqual(out, ["XCURSOR_SIZE=32", "XCURSOR_THEME=capitaine-cursors-white"])

    def test_the_nwg_look_format_without_spaces_works_too(self):
        out = self.run_block(TEMPLATE_LUA, "[Settings]\ngtk-cursor-theme-name=Bibata-Modern-Ice\ngtk-cursor-theme-size=40\n")
        self.assertEqual(out, ["XCURSOR_SIZE=40", "XCURSOR_THEME=Bibata-Modern-Ice"])

    def test_defaults_when_nothing_is_saved_yet(self):
        for label, ini in (("sin archivo", None), ("vacío", ""), ("otra sección", "[Other]\ngtk-cursor-theme-name=X\n")):
            with self.subTest(case=label):
                self.assertEqual(self.run_block(TEMPLATE_LUA, ini), ["XCURSOR_SIZE=24", "XCURSOR_THEME=capitaine-cursors"])

    def test_without_home_or_with_garbage_the_config_still_loads_with_defaults(self):
        self.assertEqual(self.run_block(TEMPLATE_LUA, home=False), ["XCURSOR_SIZE=24", "XCURSOR_THEME=capitaine-cursors"])
        garbage = "[Settings]\ngtk-cursor-theme-name = a b;c\ngtk-cursor-theme-size = 99999\n\x00\x01 = \n"
        self.assertEqual(self.run_block(TEMPLATE_LUA, garbage), ["XCURSOR_SIZE=24", "XCURSOR_THEME=capitaine-cursors"])


class Wiring(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_the_settings_menu_and_the_control_center_open_it_instead_of_bare_nwg_look(self):
        settings = self.read("scripts/avalos-settings")
        self.assertIn("_run avalos-appearance", settings)
        self.assertIn("_run nwg-look", settings)     # respaldo si todavía no llegó por la sync
        self.assertRegex(self.read("scripts/avalos-control"), r'\("look", "appearance", \("avalos-appearance",\), ')

    def test_it_is_installed_synced_and_shipped_in_the_iso(self):
        self.assertIn('("scripts/avalos-appearance", "/usr/local/bin/avalos-appearance", 0o755)', self.read("scripts/avalos-update-helper"))
        self.assertIn('"scripts/avalos-appearance",', self.read("scripts/gen-sync-manifest.py"))
        self.assertRegex(self.read(".github/workflows/build-iso.yml"), r"for _s in [^\n]*\bavalos-appearance\b")
        self.assertIn('"avalos-appearance"', self.read("scripts/avalos_installer/system/optimize.py"))
        self.assertIn('"avalos-appearance"', self.read("scripts/skill_instalar_usb.py"))

    def test_the_script_is_executable_valid_bash(self):
        self.assertTrue(APPEARANCE.stat().st_mode & 0o111, "sin permiso de ejecución")
        self.assertEqual(subprocess.run(["bash", "-n", str(APPEARANCE)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
