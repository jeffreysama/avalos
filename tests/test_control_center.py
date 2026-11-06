"""AvalOS Control Center (scripts/avalos-control).

Un hub que solo abre otras apps y lee datos: lo que se vigila es que nunca pueda lanzar algo fuera
de su lista cerrada, que los datos del equipo no revienten con archivos que faltan, que el resumen
de salud se arme bien con lo que devuelve avalos-doctor (y se degrade con gracia si no hay Doctor, si
falla o si se cuelga), que los textos existan en los 4 idiomas y que la app esté registrada en todos
los sitios (ISO, instaladores, sync, atajo, menú de Settings, Welcome).
"""
import importlib.machinery
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402

SCRIPT = ROOT / "scripts" / "avalos-control"
LANGS = ("en", "es", "zh", "ja")


def load():
    loader = importlib.machinery.SourceFileLoader("avalos_control_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ctl = load()


class Texts(unittest.TestCase):
    def test_every_language_has_exactly_the_same_keys(self):
        base = set(ctl.STRINGS["en"])
        for lang in LANGS:
            self.assertEqual(set(ctl.STRINGS[lang]), base, f"{lang}: {sorted(set(ctl.STRINGS[lang]) ^ base)}")

    def test_no_text_is_empty_and_the_title_keeps_the_brand_word(self):
        for lang in LANGS:
            for key, value in ctl.STRINGS[lang].items():
                self.assertTrue(value.strip(), f"{lang}/{key} vacío")
            self.assertIn("AvalOS", ctl.STRINGS[lang]["title"], "el título lleva el degradado en «AvalOS»")

    def test_placeholders_survive_in_every_language(self):
        needs = {"no-results": ("{q}",), "health-summary": ("{ok}", "{warn}", "{fail}")}
        for lang in LANGS:
            for key, marks in needs.items():
                for mark in marks:
                    self.assertIn(mark, ctl.STRINGS[lang][key], f"{lang}/{key}")

    def test_every_tile_group_and_fact_has_its_texts(self):
        for lang in LANGS:
            table = ctl.STRINGS[lang]
            for _g, tid, _argv, _icon in ctl.TILES:
                self.assertIn(f"t-{tid}", table, f"{lang}")
                self.assertIn(f"d-{tid}", table, f"{lang}")
            for g in ctl.GROUPS:
                self.assertIn(f"grp-{g}", table)
            for fact in ctl.FACTS:
                self.assertIn(f"f-{fact}", table)


class Tiles(unittest.TestCase):
    def test_ids_are_unique_and_groups_known(self):
        ids = [t[1] for t in ctl.TILES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(t[0] in ctl.GROUPS for t in ctl.TILES))

    def test_every_command_is_a_fixed_tuple_of_strings(self):
        for _g, _tid, argv, _icon in ctl.TILES:
            self.assertIsInstance(argv, tuple)
            self.assertTrue(argv and all(isinstance(a, str) and a for a in argv), argv)
        self.assertEqual(set(ctl.TILE_ARGV), {t[1] for t in ctl.TILES})

    def test_every_group_shows_something(self):
        self.assertEqual({t[0] for t in ctl.TILES}, set(ctl.GROUPS))


class OpeningApps(unittest.TestCase):
    def setUp(self):
        self.api = ctl.ControlAPI()

    def test_an_unknown_or_malformed_id_never_launches_anything(self):
        with mock.patch.object(ctl, "_spawn") as spawn, mock.patch.object(ctl.shutil, "which", return_value="/usr/bin/x"):
            for bad in ("rm", "../etc/passwd", "update; rm -rf /", "", None, 7, ["update"], {"id": "update"}):
                self.assertFalse(self.api.open_tile(bad), repr(bad))
        spawn.assert_not_called()

    def test_a_known_tile_launches_exactly_its_fixed_command(self):
        with mock.patch.object(ctl, "_spawn", return_value=True) as spawn, mock.patch.object(ctl.shutil, "which", return_value="/usr/bin/x"):
            self.assertTrue(self.api.open_tile("update"))
            self.assertTrue(self.api.open_tile("account"))
        self.assertEqual(spawn.call_args_list[0].args[0], ["avalos-update"])
        self.assertEqual(spawn.call_args_list[1].args[0], ["kitty", "--title", "AvalOS — passwd", "--", "passwd"])

    def test_a_tool_that_is_not_installed_is_not_launched(self):
        with mock.patch.object(ctl, "_spawn") as spawn, mock.patch.object(ctl.shutil, "which", return_value=None):
            self.assertFalse(self.api.open_tile("doctor"))
        spawn.assert_not_called()

    def test_availability_looks_up_the_program_not_its_arguments(self):
        looked = []
        with mock.patch.object(ctl.shutil, "which", side_effect=lambda c: looked.append(c) or (c if c == "kitty" else None)):
            avail = ctl.available_tiles()
        self.assertTrue(avail["account"])
        self.assertFalse(avail["update"])
        self.assertNotIn("passwd", looked)
        self.assertEqual(set(avail), set(ctl.TILE_ARGV))

    def test_spawn_survives_a_missing_binary(self):
        with mock.patch.object(ctl.subprocess, "Popen", side_effect=OSError("no existe")):
            self.assertFalse(ctl._spawn(["nada"]))
        with mock.patch.object(ctl.subprocess, "Popen") as popen:
            self.assertTrue(ctl._spawn(["avalos-update"]))
        self.assertTrue(popen.call_args.kwargs["start_new_session"], "la app no debe morir con la ventana")


class SystemInfo(unittest.TestCase):
    def fake_system(self, **files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proc = Path(tmp.name) / "proc"
        proc.mkdir()
        for name, text in files.items():
            (proc / name).write_text(text, encoding="utf-8")
        osr = Path(tmp.name) / "os-release"
        patches = [mock.patch.object(ctl, "PROC", proc), mock.patch.object(ctl, "OS_RELEASE", osr)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return osr

    def test_reads_the_hardware_facts(self):
        osr = self.fake_system(
            cpuinfo="processor\t: 0\nmodel name\t: AMD  Ryzen 5   5600G\nmodel name\t: otra\n",
            meminfo="MemTotal:       16384000 kB\nMemFree:  1000 kB\nMemAvailable:    12288000 kB\n",
            uptime="11520.55 90000.1\n")
        osr.write_text('NAME="AvalOS"\nPRETTY_NAME="AvalOS 1.2"\n', encoding="utf-8")
        with mock.patch.object(ctl.platform, "release", return_value="7.2.11-avalos"), \
                mock.patch.object(ctl.shutil, "disk_usage", return_value=SimpleNamespace(total=500 * 1024**3, used=125 * 1024**3, free=0)):
            info = ctl.system_info()
        self.assertEqual(info, {"os": "AvalOS 1.2", "kernel": "7.2.11-avalos", "cpu": "AMD Ryzen 5 5600G",
                                "memory": "3.9 / 15.6 GiB", "disk": "125 / 500 GiB (25%)", "uptime": "3h 12m"})
        self.assertEqual(tuple(info), ctl.FACTS)

    def test_a_system_without_proc_files_still_answers(self):
        self.fake_system()
        with mock.patch.object(ctl.platform, "release", return_value=""), \
                mock.patch.object(ctl.shutil, "disk_usage", side_effect=OSError("sin disco")):
            info = ctl.system_info()
        self.assertEqual(info["os"], "AvalOS")
        self.assertEqual([info[k] for k in ("kernel", "cpu", "memory", "disk", "uptime")], ["—"] * 5)

    def test_garbage_in_proc_files_does_not_raise(self):
        self.fake_system(cpuinfo="\x00\x01 sin formato", meminfo="MemTotal: mucho kB\nMemAvailable: x\n", uptime="no es un número")
        info = ctl.system_info()
        self.assertEqual([info[k] for k in ("cpu", "memory", "uptime")], ["—"] * 3)

    def test_uptime_format(self):
        cases = {59: "0m", 180: "3m", 3600: "1h 0m", 11520: "3h 12m", 86400 + 3 * 3600 + 59: "1d 3h", 5 * 86400: "5d 0h"}
        for seconds, text in cases.items():
            self.fake_system(uptime=f"{seconds}.12 1.0\n")
            self.assertEqual(ctl._uptime(), text, seconds)

    def test_a_zero_sized_disk_does_not_divide_by_zero(self):
        with mock.patch.object(ctl.shutil, "disk_usage", return_value=SimpleNamespace(total=0, used=0, free=0)):
            self.assertEqual(ctl._disk(), "—")


def doctor_json(**overrides):
    data = {
        "summary": {"fail": 1, "warn": 3, "info": 4, "skip": 2, "ok": 11},
        "findings": [
            {"id": "a", "status": "ok", "title": "Bien"},
            {"id": "b", "status": "warn", "title": "Aviso 1"},
            {"id": "c", "status": "fail", "title": "Problema"},
            {"id": "d", "status": "info", "title": "Dato"},
            {"id": "e", "status": "warn", "title": "Aviso 2"},
        ],
    }
    data.update(overrides)
    return json.dumps(data)


class Health(unittest.TestCase):
    def run_doctor(self, stdout="", returncode=0, side_effect=None, exe="/usr/bin/avalos-doctor"):
        with mock.patch.object(ctl.shutil, "which", return_value=exe), \
                mock.patch.object(ctl.subprocess, "run", side_effect=side_effect,
                                  return_value=SimpleNamespace(stdout=stdout, returncode=returncode)) as run:
            return ctl.health_summary(), run

    def test_without_the_doctor_it_says_so(self):
        result, run = self.run_doctor(exe=None)
        self.assertEqual(result, {"state": "missing"})
        run.assert_not_called()

    def test_it_reduces_the_report_to_counts_and_the_worst_problems_first(self):
        result, run = self.run_doctor(doctor_json())
        self.assertEqual(result, {"state": "done", "ok": 11, "warn": 3, "fail": 1,
                                  "issues": [{"title": "Problema", "status": "fail"},
                                             {"title": "Aviso 1", "status": "warn"},
                                             {"title": "Aviso 2", "status": "warn"}]})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1:], ["--json", "--no-network", "--lang", ctl.LANG])
        self.assertEqual(run.call_args.kwargs["timeout"], ctl.DOCTOR_TIMEOUT)

    def test_at_most_five_issues_are_listed(self):
        findings = [{"status": "warn", "title": f"w{i}"} for i in range(9)]
        result, _ = self.run_doctor(doctor_json(findings=findings))
        self.assertEqual(len(result["issues"]), ctl.MAX_ISSUES)

    def test_a_report_with_problems_is_read_even_if_the_doctor_exits_non_zero(self):
        result, _ = self.run_doctor(doctor_json(), returncode=1)
        self.assertEqual(result["state"], "done")

    def test_every_way_the_doctor_can_fail_becomes_a_plain_error(self):
        for stdout, effect in (("", None), ("<traceback>", None), ("[]", None), ('{"findings": []}', None),
                               ('{"summary": 5, "findings": []}', None), ('{"summary": {}, "findings": "x"}', None),
                               ("", subprocess.TimeoutExpired("avalos-doctor", 90)), ("", OSError("sin permiso"))):
            result, _ = self.run_doctor(stdout, side_effect=effect)
            self.assertEqual(result, {"state": "error"}, f"{stdout!r} {effect!r}")

    def test_malformed_findings_are_skipped_not_fatal(self):
        findings = ["texto", None, {"status": "fail", "title": "Real"}, {"status": "fail"}]
        result, _ = self.run_doctor(doctor_json(findings=findings))
        self.assertEqual([i["title"] for i in result["issues"]], ["Real", ""])


class Page(unittest.TestCase):
    def test_every_placeholder_is_filled_in_every_language(self):
        for lang in LANGS:
            html = ctl._render_html(lang)
            self.assertNotRegex(html, r"[A-Z]+_PLACEHOLDER", lang)
            self.assertIn(f'<html lang="{"zh-CN" if lang == "zh" else lang}">', html)

    def test_the_embedded_data_is_the_real_data(self):
        html = ctl._render_html("es")
        strings = json.loads(re.search(r"const S = (\{.*?\});\nconst TILES", html, re.S).group(1))
        tiles = json.loads(re.search(r"const TILES = (\[.*?\]);\nconst GROUPS", html, re.S).group(1))
        self.assertEqual(strings, ctl.STRINGS["es"])
        self.assertEqual([t[1] for t in tiles], [t[1] for t in ctl.TILES])

    def test_a_closing_script_tag_in_the_data_cannot_break_the_page(self):
        with mock.patch.dict(ctl.STRINGS["en"], {"title": "x</script><script>alert(1)</script>"}):
            html = ctl._render_html("en")
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertEqual(html.count("</script>"), 1, "solo la etiqueta de cierre real; los datos llevan «<\\/»")

    def test_the_window_class_matches_the_hyprland_rule(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('set_prgname("avalos-control")', src)
        for cfg in ("hyprland.lua", "hyprland_conf_lua.template"):
            self.assertIn('class = "avalos-control"', (ROOT / "configs/hyprland" / cfg).read_text(encoding="utf-8"), cfg)


class Language(unittest.TestCase):
    def detect(self, file_text, env_lang):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "avalos-lang"
            if file_text is not None:
                f.write_text(file_text, encoding="utf-8")
            with mock.patch.object(ctl, "_AVALOS_LANG_FILE", f), mock.patch.dict(ctl.os.environ, {"LANG": env_lang}):
                return ctl._detectar_idioma()

    def test_the_installer_choice_wins_over_the_regional_locale(self):
        self.assertEqual(self.detect("ja\n", "es_MX.UTF-8"), "ja")

    def test_without_a_valid_file_it_falls_back_to_the_locale_then_english(self):
        self.assertEqual(self.detect(None, "es_SV.UTF-8"), "es")
        self.assertEqual(self.detect("klingon", "zh_CN.UTF-8"), "zh")
        self.assertEqual(self.detect(None, "pt_BR.UTF-8"), "en")


class CommandLine(unittest.TestCase):
    def test_json_prints_the_summary_and_the_available_tools(self):
        out = io.StringIO()
        with mock.patch.object(ctl, "system_info", return_value={"os": "AvalOS"}), \
                mock.patch.object(ctl, "available_tiles", return_value={"update": True}), redirect_stdout(out):
            self.assertEqual(ctl.main(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"info": {"os": "AvalOS"}, "available": {"update": True}})

    def test_without_a_graphical_session_it_exits_with_a_message(self):
        with mock.patch.object(ctl, "_has_display", return_value=False), \
                mock.patch.object(ctl, "_gui") as gui, mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(ctl.main([]), 1)
        gui.assert_not_called()
        self.assertIn("no graphical session", err.getvalue())


class RegisteredEverywhere(unittest.TestCase):
    """Los sitios que el validador no cubre (y los que sí, a modo de red doble)."""

    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_it_is_in_the_sync_list_the_helper_and_the_iso(self):
        for rel in ("scripts/gen-sync-manifest.py", "scripts/avalos-update-helper"):
            text = self.read(rel)
            for item in ("scripts/avalos-control", "configs/avalos-control.desktop", "configs/avalos-control.svg"):
                self.assertIn(item, text, f"{rel} no lista {item}")
        self.assertRegex(self.read(".github/workflows/build-iso.yml"), r"for _s in [a-z\- ]*avalos-control[a-z\- ]*; do")

    def test_both_installers_copy_the_script_the_desktop_file_and_the_icon(self):
        modular = self.read("scripts/avalos_installer/system/optimize.py")
        legacy = self.read("scripts/skill_instalar_usb.py")
        # en la lista de scripts que se copian (puede no ser el último elemento)
        self.assertRegex(modular, r'"avalos-control"\s*[,)]')
        self.assertRegex(legacy, r'"avalos-control"\s*[,)]')
        for src in (modular, legacy):
            for key in ("log-control-desktop-installed", "log-control-desktop-missing",
                        "log-control-icon-installed", "log-control-icon-missing"):
                self.assertIn(key, src)
            # que de verdad se ESCRIBAN (no basta con nombrarlos): .desktop en el menú, ícono en hicolor
            self.assertRegex(src, r'_apps_dir\s*/\s*"avalos-control\.desktop"\)\s*\.write_text\s*\(')
            self.assertRegex(src, r'_icon_dir\s*/\s*"avalos-control\.svg"\)\s*\.write_text\s*\(')

    def test_the_installer_log_messages_exist_in_the_four_languages(self):
        for lang in LANGS:
            table = translations.TRANSLATIONS[lang]
            for key in ("log-control-desktop-installed", "log-control-desktop-missing",
                        "log-control-icon-installed", "log-control-icon-missing"):
                self.assertTrue(table.get(key), f"{lang}/{key}")

    def test_the_shortcut_exists_and_welcome_shows_it(self):
        for cfg in ("hyprland.lua", "hyprland_conf_lua.template"):
            self.assertIn('hl.bind(mod .. " + ALT + C", hl.dsp.exec_cmd("avalos-control"))',
                          self.read(f"configs/hyprland/{cfg}"), cfg)
        self.assertIn('(("Super", "Alt", "C"), "k-control")', self.read("scripts/avalos-welcome"))

    def test_the_settings_menu_opens_it_in_every_language(self):
        src = self.read("scripts/avalos-settings")
        self.assertEqual(len(re.findall(r'^\s+T_CONTROL="', src, re.M)), 4)
        self.assertIn('"$T_CONTROL"', src)
        self.assertIn("_run avalos-control", src)

    def test_the_desktop_entry_and_icon_are_well_formed(self):
        desktop = self.read("configs/avalos-control.desktop")
        for line in ("Exec=avalos-control", "Icon=avalos-control", "StartupWMClass=avalos-control", "Type=Application"):
            self.assertIn(line, desktop)
        for loc in ("es", "zh_CN", "ja"):
            self.assertIn(f"Name[{loc}]=", desktop)
            self.assertIn(f"Comment[{loc}]=", desktop)
        svg = self.read("configs/avalos-control.svg")
        self.assertTrue(svg.lstrip().startswith("<svg") and svg.rstrip().endswith("</svg>"))
        self.assertIn('viewBox="0 0 100 100"', svg)

    def test_the_readme_lists_it(self):
        self.assertRegex(self.read("README.md"), r"(?m)^\| \*\*AvalOS Control Center\*\* \|", "falta su fila en la tabla de herramientas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
