"""Preflight de pacstrap con multilib desincronizado (error de un cliente, oct 2026):

    :: installing libelf (0.197-1) breaks dependency 'libelf=0.196' required by lib32-libelf

Multilib va detrás de core/extra: lib32-libelf sigue pidiendo 'libelf=0.196' cuando el repo ya
publica 0.197. Pasa en todos los mirrors, así que reintentar o cambiar de mirror no sirve; lo que
sirve es seguir sin los paquetes de multilib implicados.

Lo que descubrió la reproducción con un pacman real (6.0.2): el preflight corría contra la base de
datos local del LIVE, y la ISO trae lib32-mesa (y con él lib32-libelf). El error era de un paquete
del live y sacar paquetes de la lista del destino nunca lo arreglaba. pacstrap instala en un root
nuevo, así que el preflight ahora resuelve contra una base local vacía, igual que él.

Dos niveles: salidas literales de pacman (unitarias) y un pacman real sobre repos de mentira
(se saltan si no hay pacman; CI lo instala).
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402
from avalos_installer.core.session import InstallSession  # noqa: E402
from avalos_installer.system import pacstrap  # noqa: E402

# Salida literal de pacman 6.0.2 contra el caso del cliente (live con lib32-libelf instalado).
LIVE_DB_OUTPUT = (
    "error: failed to prepare transaction (could not satisfy dependencies)\n"
    ":: installing libelf (0.197-1) breaks dependency 'libelf=0.196' required by lib32-libelf\n"
)
# Y la misma resolución contra una base local vacía (lo que ve pacstrap): lista toda la cadena.
EMPTY_DB_OUTPUT = (
    ":: unable to satisfy dependency 'libelf=0.196' required by lib32-libelf\n"
    ":: unable to satisfy dependency 'lib32-libelf' required by lib32-llvm-libs\n"
    ":: unable to satisfy dependency 'lib32-llvm-libs' required by lib32-mesa\n"
    ":: unable to satisfy dependency 'lib32-mesa' required by lib32-vulkan-radeon\n"
    ":: unable to satisfy dependency 'lib32-vulkan-driver' required by steam\n"
    ":: unable to satisfy dependency 'libelf=0.196' required by lib32-libelf\n"
    "error: failed to prepare transaction (could not satisfy dependencies)\n"
)
CHAIN = ["lib32-libelf", "lib32-llvm-libs", "lib32-mesa", "lib32-vulkan-radeon", "steam"]


class FakeSession:
    """Lo mínimo de InstallSession que usa el preflight. `outputs` = lo que devuelve cada
    run_cmd (rc, salida); sin ellas, `runner(cmd)` decide (para correr pacman de verdad)."""

    def __init__(self, outputs=(), choices=(), runner=None):
        self.outputs, self.choices, self.runner = list(outputs), list(choices), runner
        self.cmds, self.logs, self.dialogs, self.fatal, self.cleaned = [], [], [], [], 0
        self._aborted = False
        self._mirror_choice = None
        self._mirror_choice_event = threading.Event()

    def t(self, key, **kw):
        return key + ("" if not kw else " " + " ".join(f"{k}={v}" for k, v in sorted(kw.items())))

    def log(self, txt, cls="info"):
        self.logs.append((cls, txt))

    def run_cmd(self, cmd, timeout=300, log_cls="info", **kw):
        self.cmds.append([str(c) for c in cmd])
        return self.runner(self.cmds[-1]) if self.runner else self.outputs.pop(0)

    def mirror_dialog(self, detail):
        self.dialogs.append(detail)
        self._mirror_choice = self.choices.pop(0)
        self._mirror_choice_event.set()

    def error_fatal(self, msg):
        self.fatal.append(msg)

    def clean_mounts(self):
        self.cleaned += 1


def logged(session, key):
    return [txt for _, txt in session.logs if txt.startswith(key)]


class ParsingPacmanMessages(unittest.TestCase):
    def test_the_message_the_client_saw(self):
        self.assertEqual(pacstrap.dependency_conflict_packages(LIVE_DB_OUTPUT), ["lib32-libelf"])

    def test_the_whole_chain_comes_in_order_without_repeats(self):
        self.assertEqual(pacstrap.dependency_conflict_packages(EMPTY_DB_OUTPUT), CHAIN)

    def test_versioned_cannot_resolve_counts_but_a_missing_package_does_not(self):
        # Texto de libalpm (deps.c): 'cannot resolve "%s", a dependency of "%s"'.
        versioned = 'warning: cannot resolve "libelf=0.196", a dependency of "lib32-libelf"\n'
        self.assertEqual(pacstrap.dependency_conflict_packages(versioned), ["lib32-libelf"])
        missing = 'warning: cannot resolve "lib32-gst-plugins-base-libs", a dependency of "steam"\n'
        self.assertEqual(pacstrap.dependency_conflict_packages(missing), [])
        self.assertEqual(pacstrap.dependency_conflict_packages("error: target not found: lib32-x\n"), [])

    def test_dialog_detail_drops_the_curl_progress_bar(self):
        noisy = ("  % Total    % Received % Xferd  Average Speed   Time\r\n"
                 "                                 Dload  Upload   Total\r\n"
                 "100  4096  100  4096    0     0  81920      0 --:--:--\r\n"
                 "######################################## 100.0%\r\n") + LIVE_DB_OUTPUT
        detail = pacstrap.preflight_error_summary(noisy)
        self.assertIn("breaks dependency 'libelf=0.196' required by lib32-libelf", detail)
        for junk in ("Total", "Dload", "####", "--:--"):
            self.assertNotIn(junk, detail)
        self.assertLessEqual(len(pacstrap.preflight_error_summary("error: x\n" * 500)), 400)

    def test_new_message_exists_in_the_four_languages_with_its_placeholders(self):
        for lang in ("en", "es", "zh", "ja"):
            msg = translations.TRANSLATIONS[lang]["log-multilib-desync-dropped"]
            self.assertIn("{pkgs}", msg, lang)
            self.assertIn("{causa}", msg, lang)


class PreflightFlow(unittest.TestCase):
    """La lógica del preflight con respuestas de pacman ya grabadas (sin pacman)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avalos-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (Path(self.tmp) / "sync").mkdir()
        (Path(self.tmp) / "sync" / "core.db").write_text("indice")
        patcher = mock.patch.object(pacstrap, "LIVE_PACMAN_DBPATH", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(pacstrap.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def run_flow(self, session, pkgs, repos):
        with mock.patch.object(pacstrap, "_sync_repos", return_value=repos):
            return pacstrap._preflight_packages(session, pkgs, "/tmp/p.conf")

    def test_a_passing_preflight_changes_nothing(self):
        s = FakeSession([(0, "https://m/linux-avalos-6.1-1-x86_64.pkg.tar.zst\n")])
        pkgs = ["base", "steam"]
        out, skipped = self.run_flow(s, pkgs, {})
        self.assertIn("linux-avalos", out)
        self.assertEqual((skipped, pkgs), ([], ["base", "steam"]))

    def test_it_resolves_against_an_empty_local_database_and_cleans_up(self):
        s = FakeSession([(0, "")])
        self.run_flow(s, ["base"], {})
        cmd = s.cmds[0]
        dbpath = cmd[cmd.index("--dbpath") + 1]
        self.assertNotEqual(dbpath, self.tmp)
        self.assertFalse(os.path.exists(dbpath), "el directorio temporal del preflight debe borrarse")
        self.assertTrue((Path(self.tmp) / "sync" / "core.db").exists(),
                        "borrarlo no puede tocar los índices del live (es un symlink)")

    def test_the_local_database_it_uses_is_empty_and_shares_the_live_indexes(self):
        seen = {}

        def runner(cmd):
            dbpath = cmd[cmd.index("--dbpath") + 1]
            seen["local"] = os.listdir(os.path.join(dbpath, "local"))
            seen["sync"] = os.path.realpath(os.path.join(dbpath, "sync"))
            return 0, ""
        self.run_flow(FakeSession(runner=runner), ["base"], {})
        self.assertEqual(seen["local"], [])
        self.assertEqual(seen["sync"], os.path.realpath(os.path.join(self.tmp, "sync")))

    def test_multilib_desync_drops_the_implicated_multilib_packages_and_keeps_going(self):
        s = FakeSession([(1, EMPTY_DB_OUTPUT), (1, EMPTY_DB_OUTPUT), (0, "ok\n")])
        pkgs = ["hyprland", "lib32-mesa", "lib32-vulkan-radeon", "steam", "lib32-gnutls"]
        repos = {"lib32-mesa": "multilib", "lib32-vulkan-radeon": "multilib", "steam": "multilib"}
        out, skipped = self.run_flow(s, pkgs, repos)
        self.assertEqual(sorted(skipped), ["lib32-mesa", "lib32-vulkan-radeon", "steam"])
        self.assertEqual(pkgs, ["hyprland", "lib32-gnutls"])
        self.assertEqual(s.dialogs, [])
        note = logged(s, "log-multilib-desync-dropped")
        self.assertEqual(len(note), 1)
        self.assertIn("causa=lib32-libelf", note[0])

    def test_it_never_drops_a_package_that_is_not_in_multilib(self):
        """Un hyprland o un kernel implicado cae al diálogo, no se omite en silencio."""
        out = ":: unable to satisfy dependency 'foo>=2' required by hyprland\n"
        s = FakeSession([(1, out), (1, out), (1, out)], choices=["rechazar"])
        pkgs = ["hyprland", "steam"]
        self.assertIsNone(self.run_flow(s, pkgs, {"hyprland": "extra"}))
        self.assertEqual(pkgs, ["hyprland", "steam"])
        self.assertEqual(len(s.dialogs), 1)
        self.assertEqual(len(s.fatal), 1)
        self.assertEqual(s.cleaned, 1)

    def test_a_deterministic_conflict_does_not_burn_three_attempts_nor_sleep(self):
        s = FakeSession([(1, EMPTY_DB_OUTPUT)] * 2 + [(0, "ok\n")])
        self.run_flow(s, ["steam"], {"steam": "multilib"})
        first_round = s.cmds[:2]
        self.assertEqual([c[1] for c in first_round], ["-Sp", "-Syyp"])
        self.assertEqual(len(s.cmds), 3)          # 2 del conflicto + 1 ya sin los paquetes
        self.sleep.assert_not_called()

    def test_other_failures_keep_the_old_three_attempts_with_a_pause(self):
        bad = "error: failed retrieving file 'core.db' from mirror\n"
        s = FakeSession([(1, bad)] * 3, choices=["rechazar"])
        self.assertIsNone(self.run_flow(s, ["base"], {}))
        self.assertEqual(len(s.cmds), 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_without_the_empty_database_it_does_not_drop_anything(self):
        """Sin base vacía el error puede venir de un paquete de la ISO: omitir no lo arreglaría."""
        # En el live, lib32-mesa (explícito y también instalado en la ISO) es el que rompe.
        broken = LIVE_DB_OUTPUT.replace("required by lib32-libelf", "required by lib32-mesa")
        s = FakeSession([(1, broken)] * 2, choices=["rechazar"])
        pkgs = ["lib32-mesa"]
        with mock.patch.object(pacstrap, "LIVE_PACMAN_DBPATH", os.path.join(self.tmp, "no-existe")):
            self.assertIsNone(self.run_flow(s, pkgs, {"lib32-mesa": "multilib"}))
        self.assertNotIn("--dbpath", s.cmds[0])
        self.assertEqual(pkgs, ["lib32-mesa"])

    def test_repo_queries_force_the_C_locale_so_field_names_are_not_translated(self):
        with mock.patch.dict(os.environ, {"LC_ALL": "es_ES.UTF-8", "LANG": "es_ES.UTF-8"}), \
                mock.patch.object(pacstrap.subprocess, "run",
                                  return_value=mock.Mock(stdout="")) as run:
            pacstrap._sync_repos("/tmp/p.conf", None, ["steam"])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_the_old_target_not_found_trimming_still_works(self):
        s = FakeSession([(1, "error: target not found: lib32-gst-plugins-base-libs\n")] * 3 + [(0, "ok\n")])
        pkgs = ["lib32-gst-plugins-base-libs", "steam"]
        out, skipped = self.run_flow(s, pkgs, {})
        self.assertEqual((skipped, pkgs), (["lib32-gst-plugins-base-libs"], ["steam"]))
        self.assertTrue(logged(s, "log-multilib-pkg-dropped"))

    def test_only_the_multilib_desync_omissions_are_kept_for_the_final_screen(self):
        s = FakeSession([(1, EMPTY_DB_OUTPUT), (1, EMPTY_DB_OUTPUT), (0, "ok\n")])
        repos = {"lib32-mesa": "multilib", "lib32-vulkan-radeon": "multilib", "steam": "multilib"}
        self.run_flow(s, ["hyprland", "lib32-mesa", "lib32-vulkan-radeon", "steam"], repos)
        self.assertEqual(s.multilib_skipped, ["lib32-mesa", "lib32-vulkan-radeon", "steam"])

    def test_target_not_found_trimming_is_not_shown_on_the_final_screen(self):
        """lib32-sdl2-compat no existe en los repos oficiales y se omite en CADA instalación:
        avisar siempre sería ruido y no hay nada que instalar después."""
        nf = "error: target not found: lib32-sdl2-compat\n"
        s = FakeSession([(1, nf)] * 3 + [(0, "ok\n")])
        self.run_flow(s, ["lib32-sdl2-compat", "steam"], {})
        self.assertEqual(s.multilib_skipped, [])

    def test_a_retry_forgets_what_the_previous_attempt_skipped(self):
        s = FakeSession([(1, EMPTY_DB_OUTPUT), (1, EMPTY_DB_OUTPUT), (0, "ok\n"), (0, "ok\n")])
        self.run_flow(s, ["steam", "hyprland"], {"steam": "multilib"})
        self.assertEqual(s.multilib_skipped, ["steam"])
        self.run_flow(s, ["hyprland"], {})
        self.assertEqual(s.multilib_skipped, [])


class FinalScreenNotice(unittest.TestCase):
    """Lo omitido por multilib desincronizado se le dice al usuario en la pantalla final."""

    @staticmethod
    def notice(lang, skipped):
        stub = types.SimpleNamespace(_lang=lang, multilib_skipped=skipped)
        stub.t = lambda key, **kw: InstallSession.t(stub, key, **kw)      # traducciones de verdad
        return pacstrap.multilib_skipped_notice(stub)

    def test_nothing_skipped_means_no_notice(self):
        self.assertEqual(self.notice("es", []), "")

    def test_it_lists_the_packages_and_the_install_command_in_every_language(self):
        for lang in ("en", "es", "zh", "ja"):
            out = self.notice(lang, ["lib32-mesa", "steam"])
            self.assertIn("lib32-mesa, steam", out, lang)
            self.assertIn("sudo pacman -S --needed lib32-mesa steam", out, lang)
            self.assertNotIn("{", out, f"{lang}: quedó un marcador sin rellenar")

    def test_package_names_are_html_escaped(self):
        out = self.notice("en", ["<b>x</b>"])
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)
        self.assertNotIn("<b>x", out)

    def test_the_final_summary_gets_the_notice_before_the_screen_is_shown(self):
        src = (ROOT / "scripts/avalos_installer/core/install.py").read_text(encoding="utf-8")
        self.assertLess(src.index("done_info += multilib_skipped_notice(session)"),
                        src.index("session.install_complete(done_info)"))

    def test_the_session_starts_with_an_empty_list(self):
        src = (ROOT / "scripts/avalos_installer/core/session.py").read_text(encoding="utf-8")
        self.assertIn("self.multilib_skipped: list[str] = []", src)


# ── pacman de verdad, repos de mentira ────────────────────────────────────────────────────────
TOOLS = ("pacman",)      # nada más: las bases se escriben acá, sin repo-add (que en Ubuntu carga
                         # sus funciones del paquete "makepkg", solo recomendado) ni bsdtar

REPOS = {
    "core": [("libelf", "0.197-1", ()), ("glibc", "2.40-1", ()),
             ("elfutils", "0.197-1", ("libelf=0.197",)), ("debugedit", "5.0-1", ("elfutils",))],
    "extra": [("mesa", "25-1", ("libelf",)), ("hyprland", "0.40-1", ("mesa",))],
    "multilib": [
        ("lib32-libelf", "0.196-1", ("libelf=0.196",)),
        ("lib32-llvm-libs", "1-1", ("lib32-libelf",)),
        ("lib32-mesa", "25-1", ("lib32-llvm-libs",)),
        ("lib32-vulkan-radeon", "25-1", ("lib32-mesa",), ("lib32-vulkan-driver",)),
        ("lib32-gnutls", "3.8-1", ()),
        ("steam", "1.0-1", ("lib32-vulkan-driver", "lib32-gnutls")),
        ("wine-staging", "9-1", ("lib32-gnutls",)),
    ],
}
# El live del cliente: libelf y lib32-libelf (de lib32-mesa, que trae la ISO) instalados en 0.196.
LIVE_INSTALLED = [("libelf", "0.196-1", ()), ("lib32-libelf", "0.196-1", ("libelf=0.196",)),
                  ("lib32-llvm-libs", "1-1", ("lib32-libelf",)), ("lib32-mesa", "24-1", ("lib32-llvm-libs",))]
# Lo que pide el instalador: base-devel (→ debugedit → elfutils → libelf 0.197) + GPU + gaming.
TARGETS = ["debugedit", "hyprland", "lib32-mesa", "lib32-vulkan-radeon", "steam", "lib32-gnutls", "wine-staging"]


def _db_entry(name, ver, depends=(), provides=()):
    """Entrada de una base sync (<nombre>-<ver>/desc), con los campos que escribe repo-add."""
    filename = f"{name}-{ver}-x86_64.pkg.tar.zst"
    fields = [("FILENAME", [filename]), ("NAME", [name]), ("BASE", [name]), ("VERSION", [ver]),
              ("DESC", ["fixture"]), ("CSIZE", ["1024"]), ("ISIZE", ["2048"]),
              ("MD5SUM", [hashlib.md5(filename.encode()).hexdigest()]),
              ("SHA256SUM", [hashlib.sha256(filename.encode()).hexdigest()]),
              ("URL", ["https://example.org"]), ("LICENSE", ["GPL"]), ("ARCH", ["x86_64"]),
              ("BUILDDATE", ["1700000000"]), ("PACKAGER", ["test"])]
    if depends:
        fields.append(("DEPENDS", list(depends)))
    if provides:
        fields.append(("PROVIDES", list(provides)))
    return f"{name}-{ver}", "".join(f"%{key}%\n" + "\n".join(vals) + "\n\n" for key, vals in fields)


def _write_sync_db(path, entries):
    """Base sync = tar.gz con una carpeta por paquete. pacman -Sp/-Si solo lee esto: no hacen
    falta los .pkg de verdad (-Sp imprime URLs y no descarga nada)."""
    with tarfile.open(path, "w:gz") as tf:
        for dirname, desc in entries:
            folder = tarfile.TarInfo(dirname + "/")
            folder.type, folder.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(folder)
            data = desc.encode()
            entry = tarfile.TarInfo(f"{dirname}/desc")
            entry.size, entry.mode = len(data), 0o644
            tf.addfile(entry, io.BytesIO(data))


def _add_installed(root, name, ver, depends=()):
    d = os.path.join(root, "db", "local", f"{name}-{ver}")
    os.makedirs(d)
    Path(root, "db", "local", "ALPM_DB_VERSION").write_text("9\n")
    desc = (f"%NAME%\n{name}\n\n%VERSION%\n{ver}\n\n%BASE%\n{name}\n\n%DESC%\nx\n\n%ARCH%\nx86_64\n\n"
            "%BUILDDATE%\n1700000000\n\n%INSTALLDATE%\n1700000001\n\n%PACKAGER%\nt\n\n%SIZE%\n1024\n\n"
            "%REASON%\n1\n\n" + ("%DEPENDS%\n" + "\n".join(depends) + "\n\n" if depends else ""))
    Path(d, "desc").write_text(desc)
    Path(d, "files").write_text("%FILES%\n")


def build_fixture(root):
    """Repos core/extra/multilib de mentira (bases escritas a mano) + un 'live' con paquetes ya
    instalados. -> ruta del pacman.conf"""
    sync = os.path.join(root, "db", "sync")
    for d in (sync, os.path.join(root, "root"), os.path.join(root, "cache")):
        os.makedirs(d)
    conf = ["[options]", f"RootDir = {root}/root", f"DBPath = {root}/db", f"CacheDir = {root}/cache",
            f"LogFile = {root}/pacman.log", f"GPGDir = {root}/gpg", "Architecture = x86_64",
            "SigLevel = Never"]
    for repo, pkgs in REPOS.items():
        d = os.path.join(root, "repo", repo)
        os.makedirs(d)
        _write_sync_db(os.path.join(sync, f"{repo}.db"), [_db_entry(*p) for p in pkgs])
        conf += ["", f"[{repo}]", f"Server = file://{d}"]
    for name, ver, deps in LIVE_INSTALLED:
        _add_installed(root, name, ver, deps)
    path = os.path.join(root, "pacman.conf")
    Path(path).write_text("\n".join(conf) + "\n")
    return path


def real_runner(cmd):
    # El refresco (-Syyp) es un no-op contra un repo estático y exige root: se corre como -Sp.
    cmd = ["-Sp" if c == "-Syyp" else c for c in cmd]
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                         env={**os.environ, "LC_ALL": "C"}, timeout=60)
    return res.returncode, res.stdout + res.stderr


@unittest.skipUnless(all(shutil.which(t) for t in TOOLS), "faltan herramientas: " + ", ".join(TOOLS))
class RealPacman(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="avalos-pacman-")
        cls.conf = build_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def pacman(self, *args):
        return real_runner(["pacman", "--config", self.conf, *args, "--noconfirm"])

    def test_fixture_reproduces_the_client_message_against_the_live_database(self):
        rc, out = self.pacman("-Sp", *TARGETS)
        self.assertEqual(rc, 1)
        self.assertEqual(pacstrap.dependency_conflict_packages(out), ["lib32-libelf"])
        self.assertIn("installing libelf (0.197-1) breaks dependency 'libelf=0.196' "
                      "required by lib32-libelf", out)

    def test_dropping_packages_never_fixes_it_while_the_live_database_is_used(self):
        """Por qué el preflight resuelve contra una base vacía: el bloqueo es del live."""
        rc, out = self.pacman("-Sp", "debugedit", "hyprland", "lib32-gnutls", "wine-staging")
        self.assertEqual(rc, 1)
        self.assertIn("required by lib32-libelf", out)

    def test_the_real_flow_drops_what_depends_on_the_lagging_package(self):
        s = FakeSession(runner=real_runner)
        pkgs = list(TARGETS)
        with mock.patch.object(pacstrap, "LIVE_PACMAN_DBPATH", os.path.join(self.root, "db")):
            out, skipped = pacstrap._preflight_packages(s, pkgs, self.conf)
        self.assertEqual(sorted(skipped), ["lib32-mesa", "lib32-vulkan-radeon", "steam"])
        self.assertEqual(s.multilib_skipped, ["lib32-mesa", "lib32-vulkan-radeon", "steam"])
        self.assertEqual(pkgs, ["debugedit", "hyprland", "lib32-gnutls", "wine-staging"])
        self.assertIn("libelf-0.197-1", out)
        self.assertEqual(s.dialogs, [])
        self.assertEqual(s.fatal, [])
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "db", "sync"))),
                         ["core.db", "extra.db", "multilib.db"])

    def test_sync_repos_reads_the_repository_of_each_package(self):
        repos = pacstrap._sync_repos(self.conf, None, ["steam", "hyprland", "no-existe", "libelf"])
        self.assertEqual(repos, {"steam": "multilib", "hyprland": "extra", "libelf": "core"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
