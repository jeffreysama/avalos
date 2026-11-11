"""AvalOS Version: el CI estampa el build en la ISO (scripts/gen-build-stamp.py), el instalador lo deja en el
BUILD_ID del os-release (Fastfetch lo muestra), en /usr/share/avalos/ y en su log, y `avalos-version` y el
Doctor lo leen. Nada se numera a mano: el build es AAAA.MM.DD-<commit> y cada script lleva su último commit."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402
from avalos_installer.core import buildstamp  # noqa: E402
from avalos_installer.core import logfile  # noqa: E402
from avalos_installer.system import locale as avalos_locale  # noqa: E402

LANGS = ("en", "es", "zh", "ja")
GEN = ROOT / "scripts" / "gen-build-stamp.py"
BUILD = "2026.11.09-3c4581b"
PIN_A, PIN_B = "9b6b8c6" + "0" * 33, "c77a78d" + "0" * 33


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(f"{name.replace('-', '_')}_under_test", str(ROOT / "scripts" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def workflow_script_list():
    wf = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
    return re.search(r"for _s in ([a-z\- ]+); do", wf).group(1).split()


class StampGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-stamp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.commit({"scripts/avalos-a": "a1\n", "scripts/avalos-b": "b1\n"}, "2026-10-01T10:00:00+00:00")
        # 23:30 en UTC-5 del día 9 = 04:30 UTC del día 10: el build tiene que usar la fecha UTC
        self.commit({"scripts/avalos-a": "a2\n"}, "2026-11-09T23:30:00-05:00")
        self.ship = self.tmp / "ship"
        self.ship.mkdir()
        for name in ("avalos-a", "avalos-b"):
            (self.ship / name).write_text((self.repo / "scripts" / name).read_text())
        (self.ship / "avalos-a.desktop").write_text("[Desktop Entry]\n")   # build-iso.yml también deja .desktop ahí
        (self.ship / "notas.txt").write_text("no es un script del repo\n")
        self.out = self.tmp / "out"

    def git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
                              env=dict(os.environ, **(env or {}))).stdout.strip()

    def commit(self, files, date):
        for rel, text in files.items():
            (self.repo / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c", env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})

    def run_gen(self, scripts_dir=None, repo=None):
        return subprocess.run([sys.executable, str(GEN), "--repo", str(repo or self.repo),
                               "--scripts-dir", str(scripts_dir or self.ship), "--out", str(self.out)],
                              capture_output=True, text=True, env=dict(os.environ, TZ="EST5"))   # zona local ≠ UTC a propósito

    def stamp(self):
        return buildstamp.parse_stamp((self.out / "avalos-build").read_text())

    def rows(self):
        return [line.split("\t") for line in (self.out / "avalos-scripts.tsv").read_text().splitlines()]

    def test_build_is_the_utc_commit_date_plus_the_short_commit(self):
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.stamp(), {"AVALOS_BUILD": f"2026.11.10-{head[:7]}", "AVALOS_COMMIT": head,
                                        "AVALOS_COMMIT_DATE": "2026-11-10"})

    def test_each_script_carries_the_last_commit_that_touched_it_and_its_hash(self):
        self.run_gen()
        first = self.git("rev-parse", "--short=7", self.git("rev-list", "--max-parents=0", "HEAD"))
        last = self.git("rev-parse", "--short=7", "HEAD")
        rows = {r[0]: r[1:] for r in self.rows()}
        self.assertEqual(set(rows), {"avalos-a", "avalos-b"})                 # sin el .desktop ni lo ajeno al repo
        self.assertEqual(rows["avalos-a"], [last, "2026-11-10", sha("a2\n")])
        self.assertEqual(rows["avalos-b"], [first, "2026-10-01", sha("b1\n")])

    def test_the_same_commit_gives_the_same_stamp(self):
        self.run_gen()
        before = ((self.out / "avalos-build").read_text(), (self.out / "avalos-scripts.tsv").read_text())
        shutil.rmtree(self.out)
        self.run_gen()
        self.assertEqual(before, ((self.out / "avalos-build").read_text(), (self.out / "avalos-scripts.tsv").read_text()))

    def test_it_works_when_git_thinks_the_checkout_belongs_to_someone_else(self):
        """build-iso.yml corre en un contenedor: el checkout es del uid del runner y git (root) se niega con
        «detected dubious ownership». Eso rompió el run #114 de Build AvalOS ISO."""
        env = dict(os.environ, TZ="EST5", GIT_TEST_ASSUME_DIFFERENT_OWNER="1")        # git cree que el dueño es otro
        plain = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, env=env)
        if plain.returncode == 0:
            self.skipTest("este git no comprueba el dueño del repositorio")
        self.assertIn("dubious ownership", plain.stderr)
        r = subprocess.run([sys.executable, str(GEN), "--repo", str(self.repo), "--scripts-dir", str(self.ship),
                            "--out", str(self.out)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.stamp()["AVALOS_COMMIT"], self.git("rev-parse", "HEAD"))
        self.assertEqual(len(self.rows()), 2)

    def test_the_repo_given_through_a_symlink_still_works(self):
        link = self.tmp / "enlace"
        link.symlink_to(self.repo, target_is_directory=True)
        env = dict(os.environ, GIT_TEST_ASSUME_DIFFERENT_OWNER="1")
        r = subprocess.run([sys.executable, str(GEN), "--repo", str(link), "--scripts-dir", str(self.ship),
                            "--out", str(self.out)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_it_fails_loudly_outside_git_or_without_scripts(self):
        not_git = self.tmp / "plain"
        (not_git / "scripts").mkdir(parents=True)
        r = self.run_gen(repo=not_git)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("git", r.stderr)
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self.run_gen(scripts_dir=empty)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no hay scripts", r.stderr)

    def test_a_script_without_history_is_marked_unknown_with_a_warning(self):
        (self.repo / "scripts" / "avalos-c").write_text("c\n")                 # existe pero no está commiteado
        (self.ship / "avalos-c").write_text("c\n")
        r = self.run_gen()
        self.assertEqual(r.returncode, 0)
        self.assertIn("avalos-c", r.stderr)
        self.assertEqual({x[0]: x[1:3] for x in self.rows()}["avalos-c"], ["?", "?"])

    def test_the_generated_files_are_read_back_by_both_runtime_parsers(self):
        self.run_gen()
        v = load_script("avalos-version")
        text = (self.out / "avalos-build").read_text()
        self.assertEqual(v.parse_build(text), buildstamp.parse_stamp(text))
        rows = v.parse_scripts((self.out / "avalos-scripts.tsv").read_text())
        self.assertEqual([r["name"] for r in rows], ["avalos-a", "avalos-b"])
        self.assertTrue(all(len(r["sha256"]) == 64 for r in rows))

    @unittest.skipUnless((ROOT / ".git").exists(), "hace falta un clon con .git")
    def test_the_real_scripts_of_the_iso_can_be_stamped(self):
        ship = self.tmp / "iso-scripts"
        ship.mkdir()
        for name in workflow_script_list():
            shutil.copy(ROOT / "scripts" / name, ship / name)
        r = subprocess.run([sys.executable, str(GEN), "--repo", str(ROOT), "--scripts-dir", str(ship), "--out", str(self.out)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {x[0]: x for x in self.rows()}
        self.assertEqual(set(rows), set(workflow_script_list()))
        for name, row in rows.items():
            tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", f"scripts/{name}"],
                                     capture_output=True).returncode == 0
            if tracked:                                              # un script nuevo aún sin commitear no tiene historia
                self.assertNotEqual(row[1], "?", f"{name}: sin commit (¿checkout superficial sin el archivo?)")
            self.assertEqual(row[3], hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest())
        self.assertRegex(self.stamp()["AVALOS_BUILD"], r"^\d{4}\.\d{2}\.\d{2}-[0-9a-f]{7}$")


class VersionCli(unittest.TestCase):
    def setUp(self):
        self.v = load_script("avalos-version")
        tmp = Path(tempfile.mkdtemp(prefix="avalos-ver-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.data, self.bin = tmp / "share", tmp / "bin"
        self.data.mkdir()
        self.bin.mkdir()
        patch = mock.patch.multiple(self.v, BUILD_FILE=self.data / "build", SCRIPTS_FILE=self.data / "scripts.tsv", BIN_DIR=self.bin)
        patch.start()
        self.addCleanup(patch.stop)

    def ship(self, scripts, build=BUILD):
        """Escribe el sello y deja instalados los scripts con ese mismo contenido."""
        (self.data / "build").write_text(f"AVALOS_BUILD={build}\nAVALOS_COMMIT={'3c4581b' + '0' * 33}\nAVALOS_COMMIT_DATE=2026-11-09\n")
        (self.data / "scripts.tsv").write_text("".join(f"{n}\tabc1234\t2026-11-0{i + 1}\t{sha(c)}\n" for i, (n, c) in enumerate(scripts.items())))
        for name, content in scripts.items():
            (self.bin / name).write_text(content)

    def run_main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.v.main(list(argv))
        return rc, buf.getvalue()

    def test_everything_as_shipped(self):
        self.ship({"avalos-a": "A\n", "avalos-b": "B\n"})
        info = self.v.collect()
        self.assertEqual(info["summary"], {"ok": 2, "changed": 0, "missing": 0})
        self.assertEqual((info["build"], info["stamp"], info["commit_date"]), (BUILD, True, "2026-11-09"))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn(f"AvalOS {BUILD}", out)
        self.assertIn("all as shipped in the ISO", out)

    def test_a_script_that_differs_from_the_iso_is_reported_as_changed(self):
        self.ship({"avalos-a": "A\n", "avalos-b": "B\n"})
        (self.bin / "avalos-b").write_text("B editado o sincronizado\n")
        rows = {r["name"]: r for r in self.v.collect()["scripts"]}
        self.assertEqual(rows["avalos-a"]["status"], "ok")
        self.assertEqual(rows["avalos-b"]["status"], "changed")
        self.assertEqual(rows["avalos-b"]["installed_sha256"], sha("B editado o sincronizado\n"))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)                                   # informativo: no es un error
        self.assertRegex(out, r"avalos-b\s+abc1234\s+2026-11-02\s+changed")
        self.assertIn("1 ok, 1 changed since the ISO, 0 missing", out)

    def test_a_script_that_is_gone_is_reported_as_missing(self):
        self.ship({"avalos-a": "A\n", "avalos-b": "B\n"})
        (self.bin / "avalos-a").unlink()
        rows = {r["name"]: r for r in self.v.collect()["scripts"]}
        self.assertEqual((rows["avalos-a"]["status"], rows["avalos-a"]["installed_sha256"]), ("missing", None))
        self.assertEqual(self.v.collect()["summary"], {"ok": 1, "changed": 0, "missing": 1})

    def test_a_system_without_stamp_says_so_and_does_not_fail(self):
        info = self.v.collect()
        self.assertEqual((info["build"], info["stamp"], info["scripts"]), (None, False, []))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("No build stamp", out)
        self.assertEqual(self.run_main("--short"), (1, ""))

    def test_short_prints_only_the_build(self):
        self.ship({"avalos-a": "A\n"})
        self.assertEqual(self.run_main("--short"), (0, BUILD + "\n"))

    def test_json_is_valid_and_complete(self):
        self.ship({"avalos-a": "A\n"})
        rc, out = self.run_main("--json")
        data = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(set(data), {"build", "commit", "commit_date", "stamp", "sync", "scripts", "summary"})
        self.assertEqual(data["scripts"][0]["status"], "ok")

    def test_json_and_short_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.v.main(["--short", "--json"])

    def test_malformed_lines_in_the_table_are_ignored(self):
        self.ship({"avalos-a": "A\n"})
        with open(self.data / "scripts.tsv", "a") as fh:
            fh.write("# comentario\nsolo-dos\tcolumnas\n\ncinco\ta\tb\tc\td\n")
        self.assertEqual([r["name"] for r in self.v.collect()["scripts"]], ["avalos-a"])

    def test_names_that_are_not_plain_file_names_are_ignored_and_never_read(self):
        """La tabla la escribe root, pero un nombre con ruta no debe poder hacer que se lea otro archivo."""
        self.ship({"avalos-a": "A\n"})
        secret = "secreto\n"
        (self.bin.parent / "decoy").write_text(secret)
        with open(self.data / "scripts.tsv", "a") as fh:
            for bad in ("../decoy", "sub/avalos-x", "/etc/passwd", ".oculto", "con espacio", "x" * 65, "-opcion", "a\\b"):
                fh.write(f"{bad}\tabc1234\t2026-11-01\t{sha(secret)}\n")
        self.assertEqual([r["name"] for r in self.v.collect()["scripts"]], ["avalos-a"])

    def pin(self, app, sha_):
        (self.bin / app).write_text(f'#!/usr/bin/env python3\nAVALOS_SYNC_REF = "{sha_}"\n')

    def test_sync_pins_match(self):
        self.ship({"avalos-a": "A\n"})
        self.pin("avalos-update-helper", PIN_A)
        self.pin("avalos-update", PIN_A)
        self.assertEqual(self.v.collect()["sync"], {"helper": PIN_A, "update": PIN_A, "match": True})
        self.assertIn("9b6b8c6  avalos-update-helper and avalos-update agree", self.run_main()[1])

    def test_sync_pins_that_differ_are_called_out(self):
        self.ship({"avalos-a": "A\n"})
        self.pin("avalos-update-helper", PIN_A)
        self.pin("avalos-update", PIN_B)
        self.assertIs(self.v.collect()["sync"]["match"], False)
        self.assertIn("9b6b8c6 / c77a78d  avalos-update-helper and avalos-update point to different versions", self.run_main()[1])

    def test_missing_pins_print_no_sync_line(self):
        self.ship({"avalos-a": "A\n"})
        self.pin("avalos-update", PIN_A)                           # falta el helper
        self.assertIsNone(self.v.collect()["sync"]["match"])
        self.assertNotIn("sync", self.run_main()[1])

    def test_every_language_renders_every_case_without_leftovers(self):
        self.ship({"avalos-a": "A\n", "avalos-b": "B\n", "avalos-c": "C\n"})
        (self.bin / "avalos-b").write_text("otro\n")
        (self.bin / "avalos-c").unlink()
        self.pin("avalos-update-helper", PIN_A)
        self.pin("avalos-update", PIN_B)
        for lang in LANGS:
            text = self.v.render(self.v.collect(), self.v.STR[lang])
            self.assertNotRegex(text, r"[{}]", lang)
            for word in ("st-ok", "st-changed", "st-missing"):
                self.assertIn(self.v.STR[lang][word], text, f"{lang}:{word}")

    def test_language_comes_from_avalos_lang_then_from_the_environment(self):
        lang_file = self.data / "avalos-lang"
        with mock.patch.object(self.v, "_AVALOS_LANG_FILE", lang_file):
            lang_file.write_text("es\n")
            with mock.patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}):
                self.assertEqual(self.v._detectar_idioma(), "es")                  # manda el idioma elegido en el instalador
            lang_file.write_text("xx\n")
            with mock.patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}):
                self.assertEqual(self.v._detectar_idioma(), "ja")                  # inválido: cae al entorno
            lang_file.unlink()
            with mock.patch.dict(os.environ, {"LANG": "fr_FR.UTF-8"}):
                self.assertEqual(self.v._detectar_idioma(), "en")                  # sin soporte: inglés

    def test_the_four_languages_have_the_same_keys_and_placeholders(self):
        en = self.v.STR["en"]
        for lang in LANGS:
            self.assertEqual(set(self.v.STR[lang]), set(en), lang)
            for key in en:
                self.assertEqual(set(re.findall(r"\{(\w+)\}", self.v.STR[lang][key])),
                                 set(re.findall(r"\{(\w+)\}", en[key])), f"{lang}:{key}")


class _FakeSession:
    def __init__(self):
        self.files, self.logs = {}, []

    def t(self, key, **kw):
        return key

    def log(self, msg, level="info"):
        self.logs.append((msg, level))

    def write_file(self, rel, content):
        self.files[rel] = content


class InstallerStamp(unittest.TestCase):
    STAMP = f"AVALOS_BUILD={BUILD}\nAVALOS_COMMIT={'3c4581b' + '0' * 33}\nAVALOS_COMMIT_DATE=2026-11-09\n"
    TSV = f"avalos-a\tabc1234\t2026-11-01\t{sha('A')}\n"

    def configs(self, files):
        patch = mock.patch.object(buildstamp, "read_config", lambda rel: files.get(rel))
        patch.start()
        self.addCleanup(patch.stop)

    def test_build_id_comes_from_the_stamp(self):
        self.configs({"avalos-build": self.STAMP})
        self.assertEqual(buildstamp.build_id(), BUILD)

    def test_no_stamp_means_no_build_id(self):
        self.configs({})
        self.assertIsNone(buildstamp.build_id())

    def test_a_build_with_dangerous_characters_is_rejected(self):
        for bad in ("a b", 'x"y', "x'y", "x`y", "../x", "$(id)", "", "-leading", ".leading", "a" * 65, "x;y", "x\ty", "x\\y"):
            self.configs({"avalos-build": f"AVALOS_BUILD={bad}\n"})
            self.assertIsNone(buildstamp.build_id(), repr(bad))

    def test_the_stamp_is_copied_to_the_installed_system_unchanged(self):
        self.configs({"avalos-build": self.STAMP, "avalos-scripts.tsv": self.TSV})
        s = _FakeSession()
        self.assertTrue(buildstamp.install_stamp(s))
        self.assertEqual(s.files, {"usr/share/avalos/build": self.STAMP, "usr/share/avalos/scripts.tsv": self.TSV})

    def test_a_stamp_without_script_table_still_installs_the_build(self):
        self.configs({"avalos-build": self.STAMP})
        s = _FakeSession()
        self.assertTrue(buildstamp.install_stamp(s))
        self.assertEqual(list(s.files), ["usr/share/avalos/build"])

    def test_an_iso_without_stamp_installs_nothing_and_says_so(self):
        self.configs({"avalos-scripts.tsv": self.TSV})
        s = _FakeSession()
        self.assertFalse(buildstamp.install_stamp(s))
        self.assertEqual((s.files, s.logs), ({}, [("log-build-stamp-missing", "info")]))

    def test_target_paths_are_the_ones_avalos_version_and_the_doctor_read(self):
        v, d = load_script("avalos-version"), load_script("avalos-doctor")
        self.assertEqual(v.BUILD_FILE.relative_to("/"), Path(buildstamp.TARGET_BUILD))
        self.assertEqual(v.SCRIPTS_FILE.relative_to("/"), Path(buildstamp.TARGET_SCRIPTS))
        self.assertEqual(d.BUILD_FILE, v.BUILD_FILE)

    def test_the_script_and_the_stamp_names_match_what_the_workflow_produces(self):
        gen = (ROOT / "scripts/gen-build-stamp.py").read_text()
        self.assertIn(f'"{buildstamp.STAMP_BUILD}"', gen)
        self.assertIn(f'"{buildstamp.STAMP_SCRIPTS}"', gen)

    def test_os_release_carries_the_build(self):
        with mock.patch.object(avalos_locale, "build_id", lambda: BUILD):
            s = _FakeSession()
            avalos_locale.write_os_release(s)
        text = s.files["etc/os-release"]
        self.assertIn(f"BUILD_ID={BUILD}\n", text)
        keys = [line.split("=")[0] for line in text.splitlines()]
        self.assertEqual(keys, ["NAME", "PRETTY_NAME", "ID", "ID_LIKE", "BUILD_ID", "ANSI_COLOR", "HOME_URL", "DOCUMENTATION_URL", "LOGO"])
        self.assertIn('NAME="AvalOS"', text)
        self.assertIn("ID=avalos\n", text)

    def test_os_release_falls_back_to_rolling_without_a_usable_stamp(self):
        for files in ({}, {"avalos-build": "AVALOS_BUILD=con espacios\n"}, {"avalos-build": 'AVALOS_BUILD=x"y\n'}):
            self.configs(files)
            s = _FakeSession()
            avalos_locale.write_os_release(s)
            self.assertIn("BUILD_ID=rolling\n", s.files["etc/os-release"], files)

    def test_extra_lines_in_the_stamp_never_reach_the_os_release(self):
        self.configs({"avalos-build": f"AVALOS_BUILD={BUILD}\nPRETTY_NAME=evil\nID=otro\n"})
        s = _FakeSession()
        avalos_locale.write_os_release(s)
        text = s.files["etc/os-release"]
        self.assertNotIn("evil", text)
        self.assertEqual((text.count("PRETTY_NAME="), text.count("ID=avalos")), (1, 1))
        self.assertIn(f"BUILD_ID={BUILD}\n", text)

    def test_the_installer_log_header_names_the_build(self):
        for build, shown in ((BUILD, BUILD), (None, "sin sello")):
            log = object.__new__(logfile.InstallLog)
            log._variant = "modular (test)"
            lines = []
            log._emit = lambda ls, lines=lines: lines.extend(ls)
            with mock.patch.object(logfile, "build_id", lambda b=build: b):
                log._write_header()
            self.assertTrue(any(l.startswith("Build de AvalOS: ") and shown in l for l in lines), lines)

    def test_the_missing_stamp_message_exists_in_every_language(self):
        for lang in LANGS:
            self.assertTrue(translations.TRANSLATIONS[lang].get("log-build-stamp-missing"), lang)

    def test_scripts_survive_the_copy_byte_for_byte(self):
        """El instalador lee cada script como texto y lo escribe de nuevo: si eso cambiara un byte (CRLF, BOM…)
        avalos-version diría «cambiado» en un sistema recién instalado."""
        tmp = Path(tempfile.mkdtemp(prefix="avalos-rt-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in workflow_script_list():
            src = ROOT / "scripts" / name
            dst = tmp / name
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(sha(dst.read_text(encoding="utf-8")), hashlib.sha256(src.read_bytes()).hexdigest(), name)


class Wiring(unittest.TestCase):
    def test_avalos_version_travels_in_the_iso_and_the_installed_system(self):
        self.assertIn("avalos-version", workflow_script_list())
        optimize = (ROOT / "scripts/avalos_installer/system/optimize.py").read_text(encoding="utf-8")
        tup = re.search(r"_avalos_scripts = \(([^)]*)\)", optimize).group(1)
        self.assertEqual(set(re.findall(r'"([a-z\-]+)"', tup)), set(workflow_script_list()))
        self.assertTrue((ROOT / "scripts/avalos-version").is_file())

    def test_the_workflow_stamps_after_copying_and_has_the_full_history(self):
        wf = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
        # sin el historial completo, cada script diría el mismo commit: se mira el paso de checkout, no un comentario
        checkout = wf.split("uses: actions/checkout@", 1)[1].split("\n      - ", 1)[0]
        self.assertRegex(checkout, r"(?m)^\s+fetch-depth: 0\s*$")
        step = re.search(r"python3 scripts/gen-build-stamp\.py \\\n\s+--scripts-dir \"\$AIROOTFS/usr/share/avalos/configs/scripts\" \\\n"
                         r"\s+--out \"\$AIROOTFS/usr/share/avalos/configs\"", wf)
        self.assertTrue(step, "falta el paso que estampa el build")
        self.assertGreater(step.start(), wf.index('cp "scripts/$_s"'))
        self.assertGreater(step.start(), wf.index("avalos-store.desktop\"\n          fi"))

    def test_the_installer_installs_the_stamp_after_the_scripts(self):
        optimize = (ROOT / "scripts/avalos_installer/system/optimize.py").read_text(encoding="utf-8")
        self.assertIn("install_stamp(session)", optimize)
        self.assertGreater(optimize.index("install_stamp(session)"), optimize.index("log-scripts-incomplete"))

    def test_fastfetch_shows_the_build_on_the_os_line(self):
        cfg = (ROOT / "configs/fastfetch/config.jsonc").read_text(encoding="utf-8")
        line = next(l for l in cfg.splitlines() if '"type": "os"' in l)
        self.assertIn('"format": "AvalOS {build-id}"', line)
        self.assertNotIn("{id}", line)

    def test_the_readme_lists_the_tool(self):
        self.assertIn("`avalos-version`", (ROOT / "README.md").read_text(encoding="utf-8"))


class DoctorBuildCheck(unittest.TestCase):
    def setUp(self):
        self.doc = load_script("avalos-doctor")
        tmp = Path(tempfile.mkdtemp(prefix="avalos-docb-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.file = tmp / "build"

    def check(self):
        with mock.patch.object(self.doc, "BUILD_FILE", self.file):
            return self.doc.chk_build()

    def test_a_stamped_system_reports_its_build(self):
        self.file.write_text(f"AVALOS_BUILD={BUILD}\nAVALOS_COMMIT=x\n")
        self.assertEqual(self.check(), ("ok", "d-build-ok", {"build": BUILD}, None))

    def test_a_system_without_stamp_is_informative_not_a_problem(self):
        self.assertEqual(self.check()[:2], ("info", "d-build-none"))
        self.file.write_text("basura\n")
        self.assertEqual(self.check()[:2], ("info", "d-build-none"))

    def test_registered_in_the_avalos_group_before_the_apps(self):
        order = [cid for cid, group, *_ in self.doc.CHECKS if group == "avalos"]
        self.assertEqual(order[:2], ["build", "apps"])
        table = {cid: (group, fn.__name__, net) for cid, group, fn, net in self.doc.CHECKS}
        self.assertEqual(table["build"], ("avalos", "chk_build", False))

    def test_texts_exist_in_every_language_with_the_same_placeholders(self):
        en = self.doc.STRINGS["en"]
        for key in ("t-build", "d-build-ok", "d-build-none"):
            want = set(re.findall(r"\{(\w+)\}", en[key]))
            for lang in LANGS:
                text = self.doc.STRINGS[lang].get(key)
                self.assertTrue(text, f"{lang}: falta {key}")
                self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), want, f"{lang}:{key}")

    def test_the_engine_renders_both_outcomes_in_every_language(self):
        for lang in LANGS:
            for content in (f"AVALOS_BUILD={BUILD}\n", ""):
                self.file.write_text(content)
                _, key, args, _ = self.check()
                text = self.doc.STRINGS[lang][key].format(**args)
                self.assertTrue(text.strip())
                self.assertNotRegex(text, r"[{}]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
