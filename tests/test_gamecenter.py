"""AvalOS Game Center (scripts/avalos-gamecenter).

Lo que se vigila: que nunca lance nada fuera de su lista cerrada; que lea GameMode (estado, gobernador,
gamemode.ini con varias líneas whitelist=) sin romper con archivos que faltan; que los perfiles de
MangoHud se escriban donde MangoHud los lee (~/.config/MangoHud), de forma atómica, sin pisar nunca la
config propia del usuario (queda un respaldo UNA vez); que las opciones de lanzamiento sean las
correctas; que la página no interprete HTML ajeno; que los textos existan en los 4 idiomas y que la
app esté registrada en todos los sitios (ISO, instaladores, sync, atajo, Welcome, Centro de control).
"""
import importlib.machinery
import importlib.util
import io
import json
import os
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

SCRIPT = ROOT / "scripts" / "avalos-gamecenter"
LANGS = ("en", "es", "zh", "ja")


def load():
    loader = importlib.machinery.SourceFileLoader("avalos_gamecenter_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


gc = load()


class Sandbox(unittest.TestCase):
    """Un HOME y unos XDG falsos: ninguna prueba toca el home de verdad."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "XDG_DATA_HOME": str(self.home / ".local" / "share")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = self.home / ".config"
        self.data = self.home / ".local" / "share"

    def put(self, path: Path, text="x"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class Texts(unittest.TestCase):
    def test_every_language_has_exactly_the_same_keys(self):
        base = set(gc.STRINGS["en"])
        for lang in LANGS:
            self.assertEqual(set(gc.STRINGS[lang]), base, f"{lang}: {sorted(set(gc.STRINGS[lang]) ^ base)}")

    def test_no_text_is_empty_and_the_title_keeps_the_brand_word(self):
        for lang in LANGS:
            for key, value in gc.STRINGS[lang].items():
                self.assertTrue(value.strip(), f"{lang}/{key} vacío")
            self.assertIn("AvalOS", gc.STRINGS[lang]["title"])

    def test_placeholders_survive_in_every_language(self):
        needs = {"gm-test-ok": ("{n}",), "gm-test-fail": ("{n}",), "mg-applied": ("{name}",), "pt-count": ("{n}",)}
        for lang in LANGS:
            for key, marks in needs.items():
                for mark in marks:
                    self.assertIn(mark, gc.STRINGS[lang][key], f"{lang}/{key}")

    def test_every_launcher_profile_and_variant_has_its_texts(self):
        for lang in LANGS:
            table = gc.STRINGS[lang]
            for lid, _name, _cands, _icon in gc.LAUNCHERS:
                self.assertIn(f"d-{lid}", table)
            for pid in gc.MANGO_ORDER:
                self.assertIn(f"mp-{pid}", table)
                self.assertIn(f"mpd-{pid}", table)
            for variant in gc.LAUNCH_VARIANTS:
                self.assertIn(f"lo-{variant}", table)


class Launchers(Sandbox):
    def test_the_list_is_closed_and_well_formed(self):
        ids = [lid for lid, _n, _c, _i in gc.LAUNCHERS]
        self.assertEqual(len(ids), len(set(ids)))
        for _lid, name, candidates, icon in gc.LAUNCHERS:
            self.assertTrue(name and icon and candidates)
            for argv in candidates:
                self.assertIsInstance(argv, tuple)
                self.assertTrue(all(isinstance(a, str) and a for a in argv))
                if argv[0] == "flatpak":
                    self.assertEqual(argv[1], "run")
                    self.assertEqual(len(argv), 3)

    def test_a_native_binary_is_used_when_it_exists(self):
        with mock.patch.object(gc.shutil, "which", side_effect=lambda c: "/usr/bin/" + c if c == "heroic" else None):
            self.assertEqual(gc.resolve_launcher("heroic"), ["heroic"])

    def test_heroic_falls_back_to_its_flatpak_only_when_flatpak_and_the_app_exist(self):
        app = self.data / "flatpak" / "app" / "com.heroicgameslauncher.hgl"
        which = lambda c: "/usr/bin/flatpak" if c == "flatpak" else None  # noqa: E731
        with mock.patch.object(gc.shutil, "which", side_effect=which):
            self.assertIsNone(gc.resolve_launcher("heroic"), "sin la app instalada")
            app.mkdir(parents=True)
            self.assertEqual(gc.resolve_launcher("heroic"), ["flatpak", "run", "com.heroicgameslauncher.hgl"])
        with mock.patch.object(gc.shutil, "which", return_value=None):
            self.assertIsNone(gc.resolve_launcher("heroic"), "sin el programa flatpak")

    def test_a_system_wide_flatpak_counts_too(self):
        system = self.root / "flatpak-system"
        (system / "com.usebottles.bottles").mkdir(parents=True)
        with mock.patch.object(gc, "FLATPAK_SYSTEM_APPS", system), \
                mock.patch.object(gc.shutil, "which", side_effect=lambda c: "/usr/bin/flatpak" if c == "flatpak" else None):
            self.assertEqual(gc.resolve_launcher("bottles"), ["flatpak", "run", "com.usebottles.bottles"])

    def test_unknown_launchers_resolve_to_nothing(self):
        with mock.patch.object(gc.shutil, "which", return_value="/usr/bin/x"):
            for bad in ("rm", "", "nope", None, 3):
                self.assertIsNone(gc.resolve_launcher(bad), repr(bad))

    def test_availability_covers_every_launcher(self):
        with mock.patch.object(gc.shutil, "which", side_effect=lambda c: "/usr/bin/steam" if c == "steam" else None):
            avail = gc.launchers_available()
        self.assertEqual(set(avail), set(gc.LAUNCHER_CANDIDATES))
        self.assertTrue(avail["steam"])
        self.assertFalse(avail["lutris"])


class GameModeParsing(unittest.TestCase):
    def test_status_texts(self):
        for text, state in (("gamemode is active\n", "active"), ("gamemode is inactive", "idle"),
                            ("GameMode is INACTIVE", "idle"), ("gamemode is active and this client is registered", "active"),
                            ("", "unknown"), ("error: could not connect to the bus", "unknown")):
            self.assertEqual(gc.parse_gamemode_status(text), state, text)

    def test_ini_keeps_every_whitelist_line_and_the_desired_governor(self):
        ini = ("# comentario\n[general]\ndesiredgov=performance\nrenice=0\n\n[filter]\n;whitelist=ignorada\n"
               "whitelist=steam\nWhiteList = lutris\nblacklist=glxgears\n[gpu]\nwhitelist=otra\n")
        self.assertEqual(gc.parse_gamemode_ini(ini), {"desiredgov": "performance", "whitelist": ["steam", "lutris"],
                                                      "blacklist": ["glxgears"]})

    def test_ini_ignores_empty_values_and_garbage(self):
        self.assertEqual(gc.parse_gamemode_ini("[general]\ndesiredgov=\nsin igual\n[filter]\nwhitelist=\n"),
                         {"desiredgov": None, "whitelist": [], "blacklist": []})
        self.assertEqual(gc.parse_gamemode_ini(""), {"desiredgov": None, "whitelist": [], "blacklist": []})


class GameModeStatus(Sandbox):
    def setUp(self):
        super().setUp()
        self.cpu = self.root / "cpufreq"
        self.put(self.cpu / "scaling_governor", "powersave\n")
        self.put(self.cpu / "scaling_driver", "amd-pstate-epp\n")
        self.put(self.cpu / "energy_performance_preference", "balance_performance\n")
        self.system_ini = self.put(self.root / "etc-gamemode.ini", "[general]\ndesiredgov=performance\n[filter]\nwhitelist=steam\nwhitelist=lutris\n")
        for patcher in (mock.patch.object(gc, "SYSFS_CPUFREQ", self.cpu),
                        mock.patch.object(gc, "GAMEMODE_INI_SYSTEM", (self.root / "no-existe.ini", self.system_ini))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def status(self, exe="/usr/bin/gamemoded", run=(0, "gamemode is inactive\n"), group=77, groups=(77,)):
        fake_grp = SimpleNamespace(getgrnam=lambda name: SimpleNamespace(gr_gid=group)) if group is not None else \
            SimpleNamespace(getgrnam=mock.Mock(side_effect=KeyError("gamemode")))
        with mock.patch.object(gc.shutil, "which", side_effect=lambda c: exe if c == "gamemoded" else None), \
                mock.patch.object(gc, "_run", return_value=run), mock.patch.object(gc, "grp", fake_grp), \
                mock.patch.object(gc.os, "getgroups", return_value=list(groups)), \
                mock.patch.object(gc.os, "getgid", return_value=1000):
            return gc.gamemode_status()

    def test_a_ready_system(self):
        info = self.status()
        self.assertEqual(info, {"installed": True, "state": "idle", "in_group": True, "governor": "powersave",
                                "driver": "amd-pstate-epp", "epp": "balance_performance", "target": "performance",
                                "whitelist": ["steam", "lutris"]})

    def test_active_unknown_and_missing(self):
        self.assertEqual(self.status(run=(0, "gamemode is active"))["state"], "active")
        self.assertEqual(self.status(run=None)["state"], "unknown")
        missing = self.status(exe=None)
        self.assertEqual((missing["installed"], missing["state"], missing["in_group"]), (False, "missing", None))

    def test_group_membership(self):
        self.assertFalse(self.status(groups=(10, 20))["in_group"])
        self.assertTrue(self.status(groups=(77,))["in_group"])
        self.assertTrue(self.status(group=1000, groups=())["in_group"], "también cuenta el grupo primario")
        self.assertIsNone(self.status(group=None)["in_group"])

    def test_without_cpufreq_files_the_values_are_dashes(self):
        with mock.patch.object(gc, "SYSFS_CPUFREQ", self.root / "no-hay"):
            info = self.status()
        self.assertEqual((info["governor"], info["driver"], info["epp"]), ("—", "—", "—"))

    def test_the_user_ini_is_merged_over_the_system_one(self):
        self.put(self.config / "gamemode.ini", "[general]\ndesiredgov=schedutil\n[filter]\nwhitelist=heroic\nwhitelist=steam\n")
        cfg = gc.gamemode_config()
        self.assertEqual(cfg["desiredgov"], "schedutil")
        self.assertEqual(cfg["whitelist"], ["steam", "lutris", "heroic"])

    def test_the_default_target_governor_is_performance(self):
        self.system_ini.write_text("[filter]\nwhitelist=steam\n", encoding="utf-8")
        self.assertEqual(self.status()["target"], "performance")


class GameModeTest(unittest.TestCase):
    def run_test(self, result, exe="/usr/bin/gamemoded"):
        with mock.patch.object(gc.shutil, "which", return_value=exe), mock.patch.object(gc, "_run", return_value=result) as run:
            return gc.gamemode_test(), run

    def test_without_gamemode(self):
        out, run = self.run_test(None, exe=None)
        self.assertEqual(out, {"state": "missing"})
        run.assert_not_called()

    def test_it_runs_the_official_self_test_and_counts_the_checks(self):
        text = "\n".join([":: Loading config", ":: Passed"] * 3 + [":: Running tests"])
        out, run = self.run_test((0, text))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/gamemoded", "-t"])
        self.assertEqual(run.call_args.args[1], gc.GAMEMODE_TEST_TIMEOUT)
        self.assertEqual((out["state"], out["passed"], out["failed"]), ("done", 3, 0))

    def test_failed_checks_are_counted(self):
        out, _ = self.run_test((1, ":: Passed\n:: Failed\n:: Failed\n"))
        self.assertEqual((out["passed"], out["failed"]), (1, 2))

    def test_a_non_zero_exit_with_no_failed_line_still_counts_as_a_failure(self):
        out, _ = self.run_test((1, ":: Passed\n"))
        self.assertEqual(out["failed"], 1)

    def test_output_without_any_marker_is_an_error_with_the_tail(self):
        out, _ = self.run_test((1, "\n".join(f"linea {i}" for i in range(30))))
        self.assertEqual(out["state"], "error")
        self.assertEqual(out["output"].splitlines()[-1], "linea 29")
        self.assertEqual(len(out["output"].splitlines()), 12)

    def test_a_test_that_cannot_run_is_an_error(self):
        self.assertEqual(self.run_test(None)[0], {"state": "error"})


class MangoHudFiles(Sandbox):
    def test_the_embedded_style_is_the_shipped_style(self):
        shipped = (ROOT / "configs/mangohud/MangoHud.conf").read_text(encoding="utf-8")
        style, metrics = {}, set()
        for line in shipped.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key.strip() in gc.MANGO_METRIC_KEYS:
                metrics.add(line)
            else:
                style[key.strip()] = value.strip()
        self.assertEqual(style, gc.MANGO_STYLE)
        self.assertEqual(metrics, set(gc.MANGO_PROFILES["standard"]), "el perfil Estándar es el que trae el instalador")

    def test_every_profile_only_uses_known_metric_keys_and_no_style_keys(self):
        for pid, lines in gc.MANGO_PROFILES.items():
            for line in lines:
                self.assertIn(gc._line_key(line), gc.MANGO_METRIC_KEYS, f"{pid}: {line}")
        self.assertEqual(tuple(gc.MANGO_PROFILES), gc.MANGO_ORDER)

    def test_profiles_differ_in_the_expected_way(self):
        minimal, standard, full, hidden = (gc._effective_lines(gc.profile_text(p)) for p in gc.MANGO_ORDER)
        self.assertLess(minimal, standard | minimal)
        self.assertTrue(standard - {"no_display=0"} <= full)
        self.assertIn("no_display=1", hidden)
        self.assertNotIn("no_display=1", standard)
        self.assertIn("gamemode", full)
        self.assertNotIn("gpu_stats", minimal)

    def test_active_profile_detection(self):
        self.assertEqual(gc.active_profile(), "none")
        conf = self.config / "MangoHud" / gc.MANGO_CONF
        for pid in gc.MANGO_ORDER:
            self.put(conf, gc.profile_text(pid))
            self.assertEqual(gc.active_profile(), pid)
        self.put(conf, gc.profile_text("standard") + "fps_sampling_period=500\n")
        self.assertEqual(gc.active_profile(), "custom")

    def test_a_profile_with_a_line_missing_is_custom_not_that_profile(self):
        conf = self.config / "MangoHud" / gc.MANGO_CONF
        lines = gc.profile_text("standard").splitlines()
        self.put(conf, "\n".join(l for l in lines if l != "gpu_stats") + "\n")
        self.assertEqual(gc.active_profile(), "custom")

    def test_comments_and_blank_lines_do_not_change_the_detected_profile(self):
        conf = self.config / "MangoHud" / gc.MANGO_CONF
        self.put(conf, "# mi nota\n\n" + gc.profile_text("full") + "\n# otra\n")
        self.assertEqual(gc.active_profile(), "full")

    def test_the_xdg_config_home_is_honoured(self):
        other = self.root / "otro-config"
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(other)}):
            gc.apply_profile("minimal")
        self.assertTrue((other / "MangoHud" / gc.MANGO_CONF).is_file())
        self.assertFalse((self.config / "MangoHud").exists())


class ApplyingProfiles(Sandbox):
    def folder(self):
        return self.config / "MangoHud"

    def test_it_writes_every_profile_and_the_chosen_default(self):
        status = gc.apply_profile("full")
        for pid in gc.MANGO_ORDER:
            self.assertEqual((self.folder() / "profiles" / f"{pid}.conf").read_text(encoding="utf-8"), gc.profile_text(pid))
        self.assertEqual((self.folder() / gc.MANGO_CONF).read_text(encoding="utf-8"), gc.profile_text("full"))
        self.assertEqual(status["active"], "full")
        self.assertFalse(status["has_backup"])

    def test_a_custom_config_is_saved_once_and_never_overwritten(self):
        mine = "fps\nmi_opcion=1\n"
        self.put(self.folder() / gc.MANGO_CONF, mine)
        self.assertTrue(gc.apply_profile("standard")["has_backup"])
        self.assertEqual((self.folder() / gc.MANGO_BACKUP).read_text(encoding="utf-8"), mine)
        self.put(self.folder() / gc.MANGO_CONF, "otra_cosa=2\n")           # el usuario vuelve a personalizar
        gc.apply_profile("minimal")
        self.assertEqual((self.folder() / gc.MANGO_BACKUP).read_text(encoding="utf-8"), mine, "el respaldo original sigue")

    def test_an_avalos_profile_is_not_backed_up_as_if_it_were_the_users(self):
        self.put(self.folder() / gc.MANGO_CONF, gc.profile_text("hidden"))
        self.assertFalse(gc.apply_profile("standard")["has_backup"])

    def test_without_a_previous_config_there_is_nothing_to_back_up(self):
        self.assertFalse(gc.apply_profile("minimal")["has_backup"])

    def test_restoring_brings_the_original_back(self):
        mine = "fps\nmi_opcion=1\n"
        self.put(self.folder() / gc.MANGO_CONF, mine)
        gc.apply_profile("standard")
        status = gc.restore_backup()
        self.assertEqual((self.folder() / gc.MANGO_CONF).read_text(encoding="utf-8"), mine)
        self.assertEqual(status["active"], "custom")

    def test_restoring_without_a_backup_is_an_error(self):
        self.assertEqual(gc.restore_backup(), {"error": "restore"})

    def test_an_unknown_profile_writes_nothing(self):
        for bad in ("../../etc/passwd", "", "FULL", None, 3):
            self.assertEqual(gc.apply_profile(bad), {"error": "profile"}, repr(bad))
        self.assertFalse(self.folder().exists())

    def test_a_write_failure_is_reported_not_raised(self):
        with mock.patch.object(gc, "_write_atomic", side_effect=OSError("disco lleno")):
            self.assertEqual(gc.apply_profile("full"), {"error": "write"})

    def test_writes_leave_no_temporary_files_behind(self):
        gc.apply_profile("full")
        gc.apply_profile("minimal")
        leftovers = [p.name for p in self.folder().rglob("*") if p.is_file() and not p.name.endswith(".conf")
                     and p.name != gc.MANGO_BACKUP]
        self.assertEqual(leftovers, [])

    def test_a_failed_atomic_write_keeps_the_old_file_and_cleans_its_temporary(self):
        target = self.put(self.folder() / gc.MANGO_CONF, "viejo\n")
        with mock.patch.object(gc.os, "replace", side_effect=OSError("sin permiso")), self.assertRaises(OSError):
            gc._write_atomic(target, "nuevo\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "viejo\n")
        self.assertEqual([p.name for p in self.folder().iterdir()], [gc.MANGO_CONF])

    def test_status_reflects_the_binary_and_the_backup(self):
        with mock.patch.object(gc.shutil, "which", return_value="/usr/bin/mangohud"):
            self.assertTrue(gc.mangohud_status()["installed"])
        with mock.patch.object(gc.shutil, "which", return_value=None):
            self.assertFalse(gc.mangohud_status()["installed"])
        self.assertEqual(gc.mangohud_status()["profiles"], list(gc.MANGO_ORDER))


class LaunchOptions(unittest.TestCase):
    def test_the_four_variants(self):
        opts = gc.launch_options("full")
        self.assertEqual(opts["gamemode"], "gamemoderun %command%")
        self.assertEqual(opts["mangohud"], "mangohud %command%")
        self.assertEqual(opts["both"], "mangohud gamemoderun %command%")
        self.assertEqual(opts["profile"], "MANGOHUD_CONFIGFILE=${XDG_CONFIG_HOME:-$HOME/.config}/MangoHud/profiles/full.conf "
                                          "mangohud gamemoderun %command%")
        self.assertEqual(tuple(opts), gc.LAUNCH_VARIANTS)

    def test_every_variant_ends_with_steams_command_placeholder(self):
        for pid in gc.MANGO_ORDER:
            for text in gc.launch_options(pid).values():
                self.assertTrue(text.endswith("%command%"), text)

    def test_an_unknown_profile_cannot_inject_anything(self):
        for bad in ("x; rm -rf ~", "../../x", "", None, 5):
            self.assertIn("/profiles/standard.conf ", gc.launch_options(bad)["profile"])

    def test_the_profile_path_is_one_that_apply_profile_really_writes(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp, "HOME": tmp}):
            gc.apply_profile("hidden")
            path = gc.launch_options("hidden")["profile"].split()[0].split("=", 1)[1].replace("${XDG_CONFIG_HOME:-$HOME/.config}", tmp)
            self.assertTrue(Path(path).is_file(), path)


class Clipboard(unittest.TestCase):
    def test_without_wl_copy_it_says_no(self):
        with mock.patch.object(gc.shutil, "which", return_value=None):
            self.assertFalse(gc.copy_to_clipboard("x"))

    def test_with_wl_copy_the_text_is_piped_in(self):
        with mock.patch.object(gc.shutil, "which", return_value="/usr/bin/wl-copy"), \
                mock.patch.object(gc.subprocess, "run") as run:
            self.assertTrue(gc.copy_to_clipboard("gamemoderun %command%"))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wl-copy"])
        self.assertEqual(run.call_args.kwargs["input"], "gamemoderun %command%")

    def test_a_failing_wl_copy_is_not_an_exception(self):
        for err in (OSError("no"), subprocess.CalledProcessError(1, "wl-copy"), subprocess.TimeoutExpired("wl-copy", 5)):
            with mock.patch.object(gc.shutil, "which", return_value="/usr/bin/wl-copy"), \
                    mock.patch.object(gc.subprocess, "run", side_effect=err):
                self.assertFalse(gc.copy_to_clipboard("x"))


class ProtonTools(Sandbox):
    def setUp(self):
        super().setUp()
        self.system = self.root / "system-tools"
        patcher = mock.patch.object(gc, "STEAM_SYSTEM_TOOLS", self.system)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_finds_user_system_and_official_proton_newest_first(self):
        for name in ("GE-Proton9-2", "GE-Proton9-20", "GE-Proton10-1"):
            (self.data / "Steam" / "compatibilitytools.d" / name).mkdir(parents=True)
        (self.system / "proton-ge-custom").mkdir(parents=True)
        (self.data / "Steam" / "steamapps" / "common" / "Proton 9.0").mkdir(parents=True)
        (self.data / "Steam" / "steamapps" / "common" / "Half-Life").mkdir(parents=True)
        self.assertEqual(gc.proton_tools(), ["proton-ge-custom", "Proton 9.0", "GE-Proton10-1", "GE-Proton9-20", "GE-Proton9-2"])

    def test_files_and_duplicates_are_ignored(self):
        self.put(self.data / "Steam" / "compatibilitytools.d" / "suelto.txt")
        (self.data / "Steam" / "compatibilitytools.d" / "GE-Proton9-1").mkdir(parents=True)
        (self.home / ".steam" / "root" / "compatibilitytools.d" / "GE-Proton9-1").mkdir(parents=True)
        self.assertEqual(gc.proton_tools(), ["GE-Proton9-1"])

    def test_nothing_installed_is_an_empty_list(self):
        self.assertEqual(gc.proton_tools(), [])

    def test_the_list_is_capped(self):
        for i in range(gc.MAX_TOOLS + 7):
            (self.data / "Steam" / "compatibilitytools.d" / f"GE-Proton{i}").mkdir(parents=True)
        tools = gc.proton_tools()
        self.assertEqual(len(tools), gc.MAX_TOOLS)
        self.assertEqual(tools[0], f"GE-Proton{gc.MAX_TOOLS + 6}")


class Graphics(Sandbox):
    def card(self, name, vendor, uevent):
        base = self.root / "drm" / name / "device"
        self.put(base / "vendor", vendor + "\n")
        self.put(base / "uevent", uevent)

    def test_gpus_are_labelled_by_vendor_and_driver(self):
        self.card("card0", "0x1002", "DRIVER=amdgpu\nPCI_ID=1002:73FF\n")
        self.card("card1", "0x8086", "DRIVER=i915\n")
        self.card("card2", "0x10DE", "DRIVER=nouveau\n")
        self.card("card3", "0x9999", "DRIVER=raro\n")
        self.card("card4", "0x1002", "DRIVER=amdgpu\n")                       # repetida
        self.card("card0-HDMI-A-1", "0x1002", "DRIVER=conector\n")            # un conector, no una GPU
        with mock.patch.object(gc, "SYSFS_DRM", self.root / "drm"):
            self.assertEqual(gc.gpus(), ["AMD · amdgpu", "Intel · i915", "NVIDIA · nouveau", "raro"])

    def test_no_drm_directory_means_no_gpus(self):
        with mock.patch.object(gc, "SYSFS_DRM", self.root / "no-hay"):
            self.assertEqual(gc.gpus(), [])

    HYPR = json.dumps([
        {"name": "DP-1", "width": 2560, "height": 1440, "refreshRate": 164.9985, "vrr": True},
        {"name": "eDP-1", "width": 1920, "height": 1080, "refreshRate": 60.0, "vrr": False},
        {"name": "HDMI-A-1", "width": "x", "vrr": "quizá"},
        {"width": 1, "height": 1},
        "basura",
    ])

    def test_monitors_are_parsed_without_inventing_data(self):
        self.assertEqual(gc.parse_monitors(self.HYPR), [
            {"name": "DP-1", "mode": "2560×1440 @ 165 Hz", "vrr": True},
            {"name": "eDP-1", "mode": "1920×1080 @ 60 Hz", "vrr": False},
            {"name": "HDMI-A-1", "mode": "", "vrr": None}])
        for bad in ("", "no es json", "{}", "null", "[1, 2]"):
            self.assertEqual(gc.parse_monitors(bad), [], repr(bad))

    def run_monitors(self, signature="abc", exe="/usr/bin/hyprctl", result=(0, "[]")):
        env = {"HYPRLAND_INSTANCE_SIGNATURE": signature} if signature else {}
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(gc.shutil, "which", return_value=exe), \
                mock.patch.object(gc, "_run", return_value=result) as run:
            if not signature:
                os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
            return gc.monitors(), run

    def test_monitors_need_hyprland_running_and_hyprctl(self):
        for kwargs in ({"signature": "", "result": (0, self.HYPR)}, {"exe": None, "result": (0, self.HYPR)},
                       {"result": None}, {"result": (1, self.HYPR)}):
            out, _ = self.run_monitors(**kwargs)
            self.assertEqual(out, [], kwargs)
        out, run = self.run_monitors(result=(0, self.HYPR))
        self.assertEqual(len(out), 3)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/hyprctl", "-j", "monitors"])


class RunningCommands(unittest.TestCase):
    def test_run_never_raises(self):
        with mock.patch.object(gc.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIsNone(gc._run(["x"], 1))
        with mock.patch.object(gc.subprocess, "run", side_effect=OSError("no existe")):
            self.assertIsNone(gc._run(["x"], 1))
        with mock.patch.object(gc.subprocess, "run", return_value=SimpleNamespace(returncode=3, stdout="a", stderr="b")):
            self.assertEqual(gc._run(["x"], 1), (3, "ab"))

    def test_spawn_survives_a_missing_binary_and_detaches_the_child(self):
        with mock.patch.object(gc.subprocess, "Popen", side_effect=OSError("no")):
            self.assertFalse(gc._spawn(["nada"]))
        with mock.patch.object(gc.subprocess, "Popen") as popen:
            self.assertTrue(gc._spawn(["steam"]))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


class TheAPI(unittest.TestCase):
    def setUp(self):
        self.api = gc.GameAPI()

    def test_an_unknown_launcher_never_launches_anything(self):
        with mock.patch.object(gc, "_spawn") as spawn, mock.patch.object(gc.shutil, "which", return_value="/usr/bin/x"):
            for bad in ("rm", "../x", "", None, 7, ["steam"], {"id": "steam"}):
                self.assertFalse(self.api.open_launcher(bad), repr(bad))
        spawn.assert_not_called()

    def test_a_known_launcher_runs_exactly_the_resolved_command(self):
        with mock.patch.object(gc, "resolve_launcher", return_value=["flatpak", "run", "com.usebottles.bottles"]), \
                mock.patch.object(gc, "_spawn", return_value=True) as spawn:
            self.assertTrue(self.api.open_launcher("bottles"))
        spawn.assert_called_once_with(["flatpak", "run", "com.usebottles.bottles"])

    def test_a_launcher_that_is_not_installed_is_not_run(self):
        with mock.patch.object(gc, "resolve_launcher", return_value=None), mock.patch.object(gc, "_spawn") as spawn:
            self.assertFalse(self.api.open_launcher("steam"))
        spawn.assert_not_called()

    def test_the_store_button(self):
        with mock.patch.object(gc.shutil, "which", return_value=None), mock.patch.object(gc, "_spawn") as spawn:
            self.assertFalse(self.api.open_store())
        spawn.assert_not_called()
        with mock.patch.object(gc.shutil, "which", return_value="/usr/bin/avalos-store"), \
                mock.patch.object(gc, "_spawn", return_value=True) as spawn:
            self.assertTrue(self.api.open_store())
        spawn.assert_called_once_with(["avalos-store"])

    def test_profile_arguments_are_validated(self):
        with mock.patch.object(gc, "apply_profile", return_value={"ok": 1}) as apply:
            self.assertEqual(self.api.mango_apply("full"), {"ok": 1})
            for bad in (None, 3, ["full"], {"p": 1}):
                self.assertEqual(self.api.mango_apply(bad), {"error": "profile"})
        apply.assert_called_once_with("full")

    def test_copy_only_copies_the_known_variants(self):
        with mock.patch.object(gc, "copy_to_clipboard", return_value=True) as copy:
            ok = self.api.copy_options("both", "hidden")
            self.assertEqual(ok, {"ok": True, "text": "mangohud gamemoderun %command%"})
            for bad in ("rm -rf", "", None, 3, ["both"]):
                self.assertEqual(self.api.copy_options(bad, "hidden"), {"ok": False, "text": ""}, repr(bad))
        copy.assert_called_once_with("mangohud gamemoderun %command%")

    def test_copy_reports_when_there_is_no_clipboard(self):
        with mock.patch.object(gc, "copy_to_clipboard", return_value=False):
            result = self.api.copy_options("gamemode", "full")
        self.assertEqual(result, {"ok": False, "text": "gamemoderun %command%"})

    def test_launch_options_tolerates_a_bad_profile_argument(self):
        self.assertEqual(self.api.launch_options(None), gc.launch_options("standard"))
        self.assertEqual(self.api.launch_options("full"), gc.launch_options("full"))

    def test_the_snapshot_has_every_section(self):
        with mock.patch.object(gc, "launchers_available", return_value={}), mock.patch.object(gc, "gamemode_status", return_value={}), \
                mock.patch.object(gc, "mangohud_status", return_value={}), mock.patch.object(gc, "proton_tools", return_value=[]), \
                mock.patch.object(gc, "gpus", return_value=[]), mock.patch.object(gc, "monitors", return_value=[]):
            self.assertEqual(set(self.api.snapshot()), {"launchers", "gamemode", "mango", "tools", "system"})


class Page(unittest.TestCase):
    def test_every_placeholder_is_filled_in_every_language(self):
        for lang in LANGS:
            html = gc._render_html(lang)
            self.assertNotRegex(html, r"[A-Z]+_PLACEHOLDER", lang)
            self.assertIn(f'<html lang="{"zh-CN" if lang == "zh" else lang}">', html)

    def test_the_embedded_data_is_the_real_data(self):
        html = gc._render_html("es")
        strings = json.loads(re.search(r"const S = (\{.*?\});\nconst LAUNCHERS", html, re.S).group(1))
        launchers = json.loads(re.search(r"const LAUNCHERS = (\[.*?\]);\nconst PROFILES", html, re.S).group(1))
        profiles = json.loads(re.search(r"const PROFILES = (\[.*?\]);\nconst VARIANTS", html, re.S).group(1))
        variants = json.loads(re.search(r"const VARIANTS = (\[.*?\]);\nconst \$", html, re.S).group(1))
        self.assertEqual(strings, gc.STRINGS["es"])
        self.assertEqual([l[0] for l in launchers], [l[0] for l in gc.LAUNCHERS])
        self.assertEqual((profiles, variants), (list(gc.MANGO_ORDER), list(gc.LAUNCH_VARIANTS)))

    def test_a_closing_script_tag_in_the_data_cannot_break_the_page(self):
        with mock.patch.dict(gc.STRINGS["en"], {"title": "x</script><script>alert(1)</script>"}):
            html = gc._render_html("en")
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertEqual(html.count("</script>"), 1)

    def test_the_window_class_matches_the_hyprland_rule(self):
        self.assertIn('set_prgname("avalos-gamecenter")', SCRIPT.read_text(encoding="utf-8"))
        for cfg in ("hyprland.lua", "hyprland_conf_lua.template"):
            self.assertIn('class = "avalos-gamecenter"', (ROOT / "configs/hyprland" / cfg).read_text(encoding="utf-8"), cfg)


class Language(unittest.TestCase):
    def detect(self, file_text, env_lang):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "avalos-lang"
            if file_text is not None:
                f.write_text(file_text, encoding="utf-8")
            with mock.patch.object(gc, "_AVALOS_LANG_FILE", f), mock.patch.dict(gc.os.environ, {"LANG": env_lang}):
                return gc._detectar_idioma()

    def test_the_installer_choice_wins_then_the_locale_then_english(self):
        self.assertEqual(self.detect("ja\n", "es_MX.UTF-8"), "ja")
        self.assertEqual(self.detect(None, "es_SV.UTF-8"), "es")
        self.assertEqual(self.detect("klingon", "pt_BR.UTF-8"), "en")


class CommandLine(unittest.TestCase):
    def test_json_prints_the_snapshot(self):
        out = io.StringIO()
        with mock.patch.object(gc, "snapshot", return_value={"launchers": {"steam": True}}), redirect_stdout(out):
            self.assertEqual(gc.main(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"launchers": {"steam": True}})

    def test_without_a_graphical_session_it_exits_with_a_message(self):
        with mock.patch.object(gc, "_has_display", return_value=False), mock.patch.object(gc, "_gui") as gui, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(gc.main([]), 1)
        gui.assert_not_called()
        self.assertIn("no graphical session", err.getvalue())


class RegisteredEverywhere(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_it_is_in_the_sync_list_the_helper_and_the_iso(self):
        for rel in ("scripts/gen-sync-manifest.py", "scripts/avalos-update-helper"):
            text = self.read(rel)
            for item in ("scripts/avalos-gamecenter", "configs/avalos-gamecenter.desktop", "configs/avalos-gamecenter.svg"):
                self.assertIn(item, text, f"{rel} no lista {item}")
        self.assertRegex(self.read(".github/workflows/build-iso.yml"), r"for _s in [a-z\- ]*avalos-gamecenter[a-z\- ]*; do")

    def test_both_installers_copy_the_script_the_desktop_file_and_the_icon(self):
        modular = self.read("scripts/avalos_installer/system/optimize.py")
        legacy = self.read("scripts/skill_instalar_usb.py")
        for src in (modular, legacy):
            self.assertRegex(src, r'"avalos-gamecenter"\s*[,)]')
            for key in ("log-gamecenter-desktop-installed", "log-gamecenter-desktop-missing",
                        "log-gamecenter-icon-installed", "log-gamecenter-icon-missing"):
                self.assertIn(key, src)
            self.assertRegex(src, r'_apps_dir\s*/\s*"avalos-gamecenter\.desktop"\)\s*\.write_text\s*\(')
            self.assertRegex(src, r'_icon_dir\s*/\s*"avalos-gamecenter\.svg"\)\s*\.write_text\s*\(')

    def test_the_installer_log_messages_exist_in_the_four_languages(self):
        for lang in LANGS:
            for key in ("log-gamecenter-desktop-installed", "log-gamecenter-desktop-missing",
                        "log-gamecenter-icon-installed", "log-gamecenter-icon-missing"):
                self.assertTrue(translations.TRANSLATIONS[lang].get(key), f"{lang}/{key}")

    def test_the_shortcut_exists_and_welcome_shows_it(self):
        for cfg in ("hyprland.lua", "hyprland_conf_lua.template"):
            self.assertIn('hl.bind(mod .. " + ALT + G", hl.dsp.exec_cmd("avalos-gamecenter"))', self.read(f"configs/hyprland/{cfg}"), cfg)
        self.assertIn('(("Super", "Alt", "G"), "k-gamecenter")', self.read("scripts/avalos-welcome"))

    def test_the_control_center_opens_it(self):
        self.assertIn('("apps", "games", ("avalos-gamecenter",)', self.read("scripts/avalos-control"))

    def test_the_desktop_entry_and_icon_are_well_formed(self):
        desktop = self.read("configs/avalos-gamecenter.desktop")
        for line in ("Exec=avalos-gamecenter", "Icon=avalos-gamecenter", "StartupWMClass=avalos-gamecenter", "Type=Application"):
            self.assertIn(line, desktop)
        for loc in ("es", "zh_CN", "ja"):
            self.assertIn(f"Name[{loc}]=", desktop)
            self.assertIn(f"Comment[{loc}]=", desktop)
        svg = self.read("configs/avalos-gamecenter.svg")
        self.assertTrue(svg.lstrip().startswith("<svg") and svg.rstrip().endswith("</svg>"))
        self.assertIn('viewBox="0 0 100 100"', svg)

    def test_the_readme_lists_it(self):
        self.assertRegex(self.read("README.md"), r"(?m)^\| \*\*AvalOS Game Center\*\* \|")


if __name__ == "__main__":
    unittest.main(verbosity=2)
