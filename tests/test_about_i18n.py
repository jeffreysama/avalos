"""avalos-about en los 4 idiomas.

Reporte (25 nov 2026, probando «Acerca de / Info del sistema» en un AvalOS en inglés): debajo de fastfetch
quedaban «Memoria libre», «Disco raíz», «Pulsa Enter para cerrar / Press Enter to close.» fijos en español, y
la línea de Waybar mostraba un mensaje de log («[info] no JOURNAL_STREAM, logging to console») en lugar de la
versión: waybar escribe sus logs ANTES de la versión y el script se quedaba con la primera línea.

Se prueba el script real (`--text`: mismo contenido que la ventana, sin kitty) con waybar/hyprctl de mentira.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABOUT = ROOT / "scripts" / "avalos-about"
SETTINGS = ROOT / "scripts" / "avalos-settings"
BASH = shutil.which("bash")
SYSTEM_TOOLS = ("awk", "cat", "cut", "df", "free", "grep", "head", "readlink", "uname")

# 93784 s = 1 día, 2 horas, 3 minutos
UPTIME_SECONDS = "93784.52 180000.10\n"

LABELS = {   # (memoria, disco, uptime esperado)
    "en": ("Free memory", "Root disk", "1 d 2 h 3 min"),
    "es": ("Memoria libre", "Disco raíz", "1 d 2 h 3 min"),
    "zh": ("可用内存", "根分区", "1天 2小时 3分钟"),
    "ja": ("空きメモリ", "ルートディスク", "1日 2時間 3分"),
}
SPANISH_ONLY = ("Memoria libre", "Disco raíz", "Pulsa Enter", "Instalado", "Autor", "Tiempo encendido")

WAYBAR_NOISY = """#!/bin/sh
echo "[2026-11-25 07:10:28.840] [info] no JOURNAL_STREAM, logging to console"
echo "Waybar v0.12.0"
"""


class AboutTextBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        # PATH aislado: solo estas herramientas del sistema (por enlace) y los stubs de cada test. Si no, el waybar o el
        # hyprctl REALES del equipo de quien corre los tests (en el de Jeff sí están) se cuelan en el resultado.
        for name in SYSTEM_TOOLS:
            real = shutil.which(name)
            if real is None:
                self.skipTest(f"este sistema no tiene `{name}`")
            (self.bin / name).symlink_to(real)
        self.stub("fastfetch", "#!/bin/sh\necho FASTFETCH-STUB\n")
        self.stub("hyprctl", "#!/bin/sh\necho 'Hyprland 0.57.2, built from branch main (v0.57.2).'\n")
        self.stub("waybar", WAYBAR_NOISY)
        (self.dir / "uptime").write_text(UPTIME_SECONDS, encoding="utf-8")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def run_about(self, lang="en", with_waybar=True, lang_file=True):
        if lang_file:
            (self.dir / "lang").write_text(f"{lang}\n", encoding="utf-8")
        if not with_waybar:
            (self.bin / "waybar").unlink()
        env = {
            "PATH": str(self.bin),
            "AVALOS_LANG_FILE": str(self.dir / ("lang" if lang_file else "no-such-file")),
            "AVALOS_PROC_UPTIME": str(self.dir / "uptime"),
            "SHELL": "/bin/bash",
            "LANG": "C",
            "HOME": str(self.dir),
        }
        proc = subprocess.run([BASH, str(ABOUT), "--text"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout


class AboutIsFullyTranslated(AboutTextBase):
    def test_each_language_shows_its_own_labels_and_uptime(self):
        for lang, (memory, disk, uptime) in LABELS.items():
            with self.subTest(lang=lang):
                out = self.run_about(lang)
                self.assertIn(memory, out)
                self.assertIn(disk, out)
                self.assertIn(uptime, out)
                self.assertIn("FASTFETCH-STUB", out)

    def test_nothing_in_spanish_leaks_into_the_other_languages(self):
        for lang in ("en", "zh", "ja"):
            out = self.run_about(lang)
            for word in SPANISH_ONLY:
                with self.subTest(lang=lang, word=word):
                    self.assertNotIn(word, out)

    def test_the_uptime_is_not_the_english_only_uptime_p(self):
        for lang in ("es", "zh", "ja"):
            self.assertNotRegex(self.run_about(lang), r"\bup \d+ ", lang)

    def test_a_missing_or_invalid_language_file_falls_back_to_english(self):
        self.assertIn("Free memory", self.run_about(lang_file=False))
        (self.dir / "lang").write_text("xx\n", encoding="utf-8")
        self.assertIn("Free memory", self.run_about("xx"))


class WaybarVersion(AboutTextBase):
    def test_the_version_is_shown_not_the_log_line_waybar_prints_first(self):
        for lang in LABELS:
            out = self.run_about(lang)
            with self.subTest(lang=lang):
                self.assertRegex(out, r"Waybar\s*[:：]\s*v0\.12\.0")
                self.assertNotIn("JOURNAL_STREAM", out)
                self.assertNotIn("[info]", out)

    def test_without_waybar_it_says_na_and_not_the_shell_error(self):
        out = self.run_about("en", with_waybar=False)
        self.assertRegex(out, r"Waybar\s*:\s*N/A")
        self.assertNotIn("command not found", out)

    def test_a_waybar_that_prints_no_version_at_all_is_na(self):
        self.stub("waybar", "#!/bin/sh\necho '[2026-11-25 07:10:28.840] [info] hello'\n")
        self.assertRegex(self.run_about("en"), r"Waybar\s*:\s*N/A")


class SettingsLeftovers(unittest.TestCase):
    """Los respaldos de avalos-settings (usuario, snapshots sin avalos-restore, About sin avalos-about) también
    mezclaban idiomas: «Press Enter to close.» fijo en inglés y mensajes de snapper fijos en español."""

    def setUp(self):
        self.src = SETTINGS.read_text(encoding="utf-8")

    def test_every_language_block_defines_the_new_texts(self):
        for var in ("T_PRESS_ENTER", "T_SNAP_NOCONF", "T_SNAP_MISSING"):
            with self.subTest(var=var):
                self.assertEqual(len(re.findall(rf'^\s+{var}="', self.src, re.M)), 4)

    def test_no_text_is_hardcoded_anymore_outside_the_language_blocks(self):
        body = self.src.split("# ── Helper: ejecutar", 1)[1]    # todo lo que va después de las tablas de traducción
        self.assertNotIn("Press Enter to close", body)
        self.assertNotIn("no está configurado", body)
        self.assertNotIn("no está instalado", body)

    def test_the_kitty_children_receive_the_translated_texts_through_the_environment(self):
        self.assertIn('AVALOS_PRESS_ENTER="$T_PRESS_ENTER"', self.src)
        self.assertIn('AVALOS_SNAP_NOCONF="$T_SNAP_NOCONF"', self.src)
        self.assertIn('AVALOS_SNAP_MISSING="$T_SNAP_MISSING"', self.src)

    def test_both_scripts_are_valid_bash(self):
        for script in (ABOUT, SETTINGS):
            with self.subTest(script=script.name):
                self.assertEqual(subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
