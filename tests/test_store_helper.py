"""Inyección de fallos contra scripts/avalos-store-helper (root vía pkexec) y contra el lado de la Store que lo
llama, más las invariantes que atan la policy de polkit, la GUI, el catálogo y las listas de instalación.

Antes de este helper la policy autorizaba «pkexec /usr/bin/pacman -S <lo que sea>» con auth_admin_keep: con la
autenticación en caché, un proceso del mismo usuario podía pasarle a pacman un pacman.conf propio (XferCommand)
y ejecutar lo que quisiera como root, sin contraseña. Estas pruebas fijan lo contrario: del exterior solo entra
un ID de app, y solo se acepta si el catálogo de root lo declara.

El pacman es un script falso que registra sus argumentos: se prueba el flujo REAL (Popen, señales, grupos de
procesos), no dobles de subprocess. Correr: python3 -m unittest tests.test_store_helper -v
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "avalos-store-helper"
STORE = ROOT / "scripts" / "avalos-store"
POLICY = ROOT / "configs" / "avalos-store.policy"
CATALOG_FILE = ROOT / "configs" / "avalos-store-catalog.json"
HELPER_PATH = "/usr/local/bin/avalos-store-helper"

CATALOG = [
    {"id": "steam", "source": "pacman", "package": "steam"},
    {"id": "firefox", "source": "pacman", "package": "firefox"},
    {"id": "heroic", "source": "aur", "package": "heroic-games-launcher-bin"},
    {"id": "obs-flatpak", "source": "flatpak", "package": "com.obsproject.Studio"},
    {"id": "evil-flag", "source": "pacman", "package": "--config=/tmp/x"},
    {"id": "evil-space", "source": "pacman", "package": "a b"},
    {"id": "evil-dash", "source": "pacman", "package": "-Syu"},
    {"id": "evil-newline", "source": "pacman", "package": "a\nb"},
    {"id": "kernel", "source": "pacman", "package": "linux"},
    {"id": "no-package", "source": "pacman"},
    {"id": "numeric-package", "source": "pacman", "package": 5},
    {"id": "weird-source", "source": "rpm", "package": "x"},
    "no-soy-un-dict", None, 5, [],
]


def load_script(path, name, **modules):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        loader.exec_module(module)
    return module


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.h = load_script(HELPER, "avalos_store_helper_under_test")
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-store-helper-test-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))
        self.tmp.chmod(0o755)
        self.catalog = self.tmp / "avalos-store-catalog.json"
        self.write_catalog(CATALOG)
        self.args_file = self.tmp / "pacman-args"
        self.pacman = self.tmp / "pacman"
        self.pacman.write_text(textwrap.dedent("""\
            #!/bin/sh
            printf '%s\\n' "$@" > "$FAKE_PACMAN_ARGS"
            echo "fake pacman: $*"
            exit "${FAKE_PACMAN_RC:-0}"
            """))
        self.pacman.chmod(0o755)
        for p in (mock.patch.object(self.h, "CATALOG_CANDIDATES", [self.catalog]),
                  mock.patch.object(self.h, "TRUSTED_UIDS", (os.getuid(),)),
                  mock.patch.object(self.h, "PACMAN", str(self.pacman)),
                  mock.patch("os.geteuid", return_value=0),
                  mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid()), "FAKE_PACMAN_ARGS": str(self.args_file)})):
            p.start()
            self.addCleanup(p.stop)

    def write_catalog(self, data, mode=0o644):
        if self.catalog.is_symlink() or self.catalog.exists():
            self.catalog.unlink()
        self.catalog.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        self.catalog.chmod(mode)

    def run_main(self, *argv):
        buf = io.StringIO()
        with (mock.patch.object(sys, "argv", ["avalos-store-helper", *argv]),
              contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO())):
            try:
                self.h.main()
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, buf.getvalue()

    def pacman_args(self):
        return self.args_file.read_text().splitlines() if self.args_file.exists() else None


class Happy(HelperCase):
    def test_install_runs_a_fixed_pacman_command_for_a_pacman_app(self):
        code, out = self.run_main("install", "steam")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pacman_args(), ["-S", "--noconfirm", "--needed", "--", "steam"])
        self.assertIn("fake pacman", out, "la salida de pacman se reenvía a la GUI")

    def test_uninstall_works_for_pacman_and_aur_apps(self):
        for app_id, pkg in (("firefox", "firefox"), ("heroic", "heroic-games-launcher-bin")):
            with self.subTest(app=app_id):
                self.args_file.unlink(missing_ok=True)
                self.assertEqual(self.run_main("uninstall", app_id)[0], 0)
                self.assertEqual(self.pacman_args(), ["-R", "--noconfirm", "--", pkg])

    def test_pacman_exit_code_and_failure_output_reach_the_caller(self):
        with mock.patch.dict(os.environ, {"FAKE_PACMAN_RC": "7"}):
            code, out = self.run_main("install", "steam")
        self.assertEqual(code, 7)
        self.assertIn("fake pacman", out)


class Rejections(HelperCase):
    def assertRefused(self, *argv):
        self.args_file.unlink(missing_ok=True)
        code, out = self.run_main(*argv)
        self.assertNotEqual(code, 0, f"{argv}: {out}")
        self.assertIsNone(self.pacman_args(), f"{argv}: pacman NO debió ejecutarse")
        return out

    def test_app_ids_that_are_not_ids_are_refused(self):
        hostile = ["../x", "steam --config=/tmp/evil", "-S", "--config=/tmp/evil", "", "STEAM", "a b", "steam\n",
                   "x" * 100, "ste/am", "steam;id", "$(id)", "`id`", "stéam", ".steam", "-steam", "steam\x00"]
        for app_id in hostile:
            with self.subTest(app_id=app_id):
                self.assertRefused("install", "--", app_id)
                self.assertRefused("uninstall", "--", app_id)

    def test_the_id_format_is_enforced_even_for_ids_the_catalog_itself_declares(self):
        """Defensa en profundidad: aunque un catálogo (de confianza) trajera un id raro, el helper no lo acepta."""
        valid = {"source": "pacman", "package": "steam"}
        self.write_catalog([{"id": i, **valid} for i in ("Steam Evil", "UPPER", "a/b", "-s", "x" * 70, "a\nb")])
        for app_id in ("Steam Evil", "UPPER", "a/b", "-s", "x" * 70, "a\nb"):
            with self.subTest(app_id=app_id):
                self.assertRefused("install", "--", app_id)

    def test_a_package_name_on_the_command_line_is_not_an_id_and_is_refused(self):
        for name in ("pacman", "base", "linux", "sudo", "openssh"):
            with self.subTest(name=name):
                self.assertRefused("install", name)

    def test_unknown_ids_are_refused(self):
        self.assertRefused("install", "does-not-exist")

    def test_install_only_handles_pacman_apps(self):
        for app_id in ("heroic", "obs-flatpak", "weird-source"):
            with self.subTest(app=app_id):
                self.assertRefused("install", app_id)

    def test_uninstall_refuses_flatpak_and_unknown_sources(self):
        for app_id in ("obs-flatpak", "weird-source"):
            with self.subTest(app=app_id):
                self.assertRefused("uninstall", app_id)

    def test_a_poisoned_catalog_entry_cannot_smuggle_options_into_pacman(self):
        for app_id in ("evil-flag", "evil-space", "evil-dash", "evil-newline", "no-package", "numeric-package"):
            with self.subTest(app=app_id):
                self.assertRefused("install", app_id)
                self.assertRefused("uninstall", app_id)

    def test_system_packages_are_never_uninstalled_even_if_the_catalog_lists_them(self):
        out = self.assertRefused("uninstall", "kernel")
        self.assertIn("sistema", out)
        for pkg in ("base", "linux-avalos", "pacman", "sudo", "polkit", "systemd", "hyprland", "grub"):
            self.assertIn(pkg, self.h.PROTECTED)

    def test_argparse_rejects_missing_unknown_and_extra_arguments(self):
        for argv in ((), ("install",), ("remove", "steam"), ("install", "steam", "extra"), ("-S", "steam"),
                     ("install", "--config=/tmp/x", "steam")):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(*argv)[0], 2)
        self.assertIsNone(self.pacman_args())

    def test_it_refuses_to_run_without_root_or_outside_pkexec(self):
        with mock.patch("os.geteuid", return_value=1000):
            self.assertRefused("install", "steam")
        env = {k: v for k, v in os.environ.items() if k != "PKEXEC_UID"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertRefused("install", "steam")
        for uid in ("abc", "", "99999999", "-1"):
            with self.subTest(uid=uid), mock.patch.dict(os.environ, {"PKEXEC_UID": uid}):
                self.assertRefused("install", "steam")
        with mock.patch.object(self.h.pwd, "getpwuid", side_effect=OverflowError):
            self.assertRefused("install", "steam")


class CatalogTrust(HelperCase):
    def test_a_catalog_that_other_users_can_write_is_not_trusted(self):
        for mode in (0o664, 0o666, 0o646, 0o622):
            with self.subTest(mode=oct(mode)):
                self.write_catalog(CATALOG, mode=mode)
                self.assertNotEqual(self.run_main("install", "steam")[0], 0)
        self.assertIsNone(self.pacman_args())

    def test_a_catalog_owned_by_someone_else_is_not_trusted(self):
        with mock.patch.object(self.h, "TRUSTED_UIDS", (os.getuid() + 1,)):
            code, out = self.run_main("install", "steam")
        self.assertNotEqual(code, 0)
        self.assertIn("confianza", out)
        self.assertIsNone(self.pacman_args())

    def test_a_catalog_inside_a_directory_others_can_write_is_not_trusted(self):
        self.tmp.chmod(0o777)
        self.addCleanup(self.tmp.chmod, 0o755)
        self.assertNotEqual(self.run_main("install", "steam")[0], 0)
        self.assertIsNone(self.pacman_args())

    def test_a_symlinked_catalog_is_not_trusted_even_if_the_target_is(self):
        real = self.tmp / "real.json"
        real.write_text(json.dumps(CATALOG))
        real.chmod(0o644)
        self.catalog.unlink()
        self.catalog.symlink_to(real)
        self.assertNotEqual(self.run_main("install", "steam")[0], 0)
        self.assertIsNone(self.pacman_args())

    def test_an_untrusted_first_candidate_aborts_instead_of_falling_through_to_the_next(self):
        good = self.tmp / "good.json"
        good.write_text(json.dumps(CATALOG))
        good.chmod(0o644)
        self.write_catalog(CATALOG, mode=0o666)
        with mock.patch.object(self.h, "CATALOG_CANDIDATES", [self.catalog, good]):
            self.assertNotEqual(self.run_main("install", "steam")[0], 0)
        self.assertIsNone(self.pacman_args())

    def test_a_missing_catalog_falls_through_to_the_next_candidate(self):
        good = self.tmp / "good.json"
        good.write_text(json.dumps(CATALOG))
        good.chmod(0o644)
        with mock.patch.object(self.h, "CATALOG_CANDIDATES", [self.tmp / "no-existe.json", good]):
            self.assertEqual(self.run_main("install", "steam")[0], 0)

    def test_no_catalog_at_all_fails_with_a_message_not_a_traceback(self):
        with mock.patch.object(self.h, "CATALOG_CANDIDATES", [self.tmp / "no-existe.json"]):
            code, out = self.run_main("install", "steam")
        self.assertEqual(code, 1)
        self.assertIn("catálogo", out)

    def test_corrupt_catalogs_fail_cleanly(self):
        corrupt = ["", "{", "null", "42", '"texto"', '{"id": "steam"}', "[" * 100000, "\x00\xff", b"\xff\xfe".decode("latin-1")]
        for raw in corrupt:
            with self.subTest(raw=raw[:20]):
                self.write_catalog(raw)
                code, out = self.run_main("install", "steam")
                self.assertNotEqual(code, 0)
                self.assertNotIn("Traceback", out)
        self.assertIsNone(self.pacman_args())

    def test_invalid_utf8_bytes_in_the_catalog_fail_cleanly(self):
        self.catalog.write_bytes(b'[{"id": "steam", "source": "pacman", "package": "\xff\xfe"}]')
        self.assertNotEqual(self.run_main("install", "steam")[0], 0)


class Execution(HelperCase):
    def run_stream(self, cmd, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.h._stream(cmd, **kw)
        return rc, buf.getvalue()

    def script(self, body):
        n = len(list(self.tmp.glob("child*.py")))
        path = self.tmp / f"child{n}.py"
        path.write_text(textwrap.dedent(body))
        return [sys.executable, str(path)]

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
        except (OSError, IndexError):
            return False

    def test_a_missing_pacman_binary_is_a_clean_127(self):
        with mock.patch.object(self.h, "PACMAN", "/no/existe/pacman"):
            code, out = self.run_main("install", "steam")
        self.assertEqual(code, 127)
        self.assertIn("no se pudo ejecutar", out)

    def test_a_silent_hang_is_killed_with_its_whole_process_tree(self):
        pidfile = self.tmp / "pids"
        cmd = self.script(f"""
            import os, subprocess, time
            g = subprocess.Popen(["sleep", "60"])
            open({str(pidfile)!r}, "w").write(f"{{os.getpid()}} {{g.pid}}")
            time.sleep(60)
        """)
        with mock.patch.object(self.h, "IDLE_TIMEOUT", 0.7):
            rc, out = self.run_stream(cmd)
        self.assertEqual(rc, 124)
        self.assertIn("colgado", out)
        child, grandchild = (int(x) for x in pidfile.read_text().split())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (self.alive(child) or self.alive(grandchild)):
            time.sleep(0.05)
        self.assertFalse(self.alive(child))
        self.assertFalse(self.alive(grandchild))

    def test_sigterm_is_tried_before_sigkill_so_pacman_can_roll_back(self):
        marker = self.tmp / "got-term"
        cmd = self.script(f"""
            import signal, sys, time
            def on_term(*a):
                open({str(marker)!r}, "w").write("term"); sys.exit(0)
            signal.signal(signal.SIGTERM, on_term)
            time.sleep(60)
        """)
        rc, _ = self.run_stream(cmd, idle_timeout=0.7)
        self.assertEqual(rc, 124)
        self.assertEqual(marker.read_text(), "term")

    def test_lines_written_right_before_a_hang_are_not_lost(self):
        cmd = self.script("""
            import sys, time
            sys.stdout.write("uno\\ndos\\ntres\\nesperando db.lck"); sys.stdout.flush()
            time.sleep(60)
        """)
        rc, out = self.run_stream(cmd, idle_timeout=0.7)
        self.assertEqual(rc, 124)
        for text in ("uno", "dos", "tres", "esperando db.lck"):
            self.assertIn(text, out)

    def test_progress_redraws_with_carriage_returns_arrive_as_lines_and_bad_bytes_are_survivable(self):
        cmd = self.script(r"""
            import sys
            sys.stdout.buffer.write(b"10%\r50%\r100%\nlisto \xff\xfe fin\n"); sys.stdout.flush()
        """)
        rc, out = self.run_stream(cmd)
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines()[:3], ["10%", "50%", "100%"])
        self.assertIn("listo", out.splitlines()[3])


class SignalsKillPacman(HelperCase):
    """Matar al helper (la GUI cierra, kill por silencio, corte de sesión) no puede dejar a pacman huérfano
    escribiendo en la base de datos sin nadie mirando."""

    DRIVER = textwrap.dedent("""
        import importlib.machinery, importlib.util, os, sys
        from pathlib import Path
        loader = importlib.machinery.SourceFileLoader("h", sys.argv[1]); spec = importlib.util.spec_from_loader("h", loader)
        h = importlib.util.module_from_spec(spec); loader.exec_module(h)
        d = Path(sys.argv[2])
        h.CATALOG_CANDIDATES = [d / "avalos-store-catalog.json"]
        h.TRUSTED_UIDS = (os.getuid(),)
        h.PACMAN = str(d / "slow-pacman")
        os.geteuid = lambda: 0
        os.environ["PKEXEC_UID"] = str(os.getuid())
        sys.argv = ["avalos-store-helper", "install", "steam"]
        h.main()
    """)

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
        except (OSError, IndexError):
            return False

    def test_terminating_the_helper_terminates_pacman(self):
        pidfile = self.tmp / "pacman.pid"
        slow = self.tmp / "slow-pacman"
        slow.write_text(f"#!/bin/sh\necho $$ > {pidfile}\necho started\nexec sleep 60\n")
        slow.chmod(0o755)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                pidfile.unlink(missing_ok=True)
                proc = subprocess.Popen([sys.executable, "-c", self.DRIVER, str(HELPER), str(self.tmp)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.addCleanup(lambda p=proc: p.poll() is None and p.kill())
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not pidfile.exists():
                    time.sleep(0.05)
                self.assertTrue(pidfile.exists(), proc.stderr.read() if proc.poll() is not None else "pacman no arrancó")
                pid = int(pidfile.read_text())
                self.assertTrue(self.alive(pid))
                proc.send_signal(sig)
                proc.wait(timeout=30)
                end = time.monotonic() + 10
                while time.monotonic() < end and self.alive(pid):
                    time.sleep(0.05)
                self.assertFalse(self.alive(pid), f"{sig.name}: pacman quedó huérfano")


# ── la GUI: arma el comando de pkexec ──────────────────────────────────────────────────────────────────
class StoreGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load_script(STORE, "avalos_store_under_test", webview=types.ModuleType("webview"))

    def test_with_the_helper_installed_only_the_app_id_is_passed(self):
        helper = Path(tempfile.mkdtemp()) / "avalos-store-helper"
        helper.write_text("#!/bin/sh\n")
        helper.chmod(0o755)
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(helper.parent)], check=False))
        app = {"id": "steam", "package": "steam; rm -rf /", "source": "pacman"}
        for action in ("install", "uninstall"):
            cmd = self.store.privileged_pacman_cmd(action, app, helper=str(helper))
            self.assertEqual(cmd, ["pkexec", str(helper), action, "steam"])
            self.assertNotIn(app["package"], cmd, "el nombre del paquete no sale de la GUI")

    def test_the_helper_path_in_the_gui_is_the_one_the_policy_authorizes(self):
        self.assertEqual(self.store.STORE_HELPER, HELPER_PATH)

    def test_without_the_helper_it_falls_back_to_absolute_pacman_with_double_dash(self):
        app = {"id": "steam", "package": "steam", "source": "pacman"}
        missing = "/no/existe/avalos-store-helper"
        self.assertEqual(self.store.privileged_pacman_cmd("install", app, helper=missing),
                         ["pkexec", "/usr/bin/pacman", "-S", "--noconfirm", "--needed", "--", "steam"])
        self.assertEqual(self.store.privileged_pacman_cmd("uninstall", app, helper=missing),
                         ["pkexec", "/usr/bin/pacman", "-R", "--noconfirm", "--", "steam"])

    def test_the_gui_never_asks_pkexec_for_a_bare_pacman_anymore(self):
        text = STORE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r'\[\s*"pkexec"\s*,\s*"pacman"')
        self.assertEqual(len(re.findall(r'subprocess\.Popen\(\s*privileged_pacman_cmd\(', text)), 2)


# ── la GUI: red (https, tope de tamaño, JSON raro) ─────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, body=b"", ctype="image/png"):
        self._body, self.reads = body, []
        self.headers = {"Content-Type": ctype}

    def read(self, n=-1):
        self.reads.append(n)
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StoreNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load_script(STORE, "avalos_store_net_under_test", webview=types.ModuleType("webview"))

    def setUp(self):
        self.cache = Path(tempfile.mkdtemp(prefix="avalos-store-icons-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.cache)], check=False))
        p = mock.patch.object(self.store, "ICON_CACHE_DIR", self.cache)
        p.start()
        self.addCleanup(p.stop)

    def opener(self, *responses):
        return mock.patch.object(self.store._OPENER, "open", side_effect=list(responses))

    def test_only_https_is_fetched_and_nothing_touches_the_network_otherwise(self):
        with self.opener() as op:
            for url in ("file:///etc/passwd", "http://flathub.org/x.png", "ftp://x/y", "//evil/x", "", None, 5):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.store._get_https(url, 5, 1000)
        op.assert_not_called()

    def test_responses_are_size_capped_and_never_read_without_a_limit(self):
        big = FakeResp(b"A" * 5000)
        with self.opener(big), self.assertRaises(ValueError):
            self.store._get_https("https://example.org/x", 5, 1000)
        self.assertTrue(all(isinstance(n, int) and 0 < n <= 1001 for n in big.reads), big.reads)
        with self.opener(FakeResp(b"ok", "text/plain")):
            self.assertEqual(self.store._get_https("https://example.org/x", 5, 1000), (b"ok", "text/plain"))

    def test_redirects_to_anything_but_https_are_refused(self):
        h = self.store._SoloHttpsRedirect()
        req = urllib.request.Request("https://flathub.org/a")
        for target in ("http://evil/x", "ftp://evil/x", "file:///etc/passwd"):
            with self.subTest(target=target), self.assertRaises(urllib.error.URLError):
                h.redirect_request(req, io.BytesIO(), 302, "Found", {}, target)
        self.assertEqual(h.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://dl.flathub.org/b").full_url,
                         "https://dl.flathub.org/b")

    def test_aur_info_survives_every_kind_of_bad_answer(self):
        good = json.dumps({"results": [{"Name": "x", "Version": "1"}]}).encode()
        with self.opener(FakeResp(good, "application/json")):
            self.assertEqual(self.store.fetch_aur_info("x"), {"Name": "x", "Version": "1"})
        for body in (b"", b"no es json", b"null", b"[]", b'{"results": null}', b'{"results": []}', b"\xff\xfe", b"[" * 200000,
                     b"A" * (self.store.MAX_RESPUESTA + 10)):
            with self.subTest(body=body[:20]), self.opener(FakeResp(body, "application/json")):
                self.assertIsNone(self.store.fetch_aur_info("x"))
        with mock.patch.object(self.store._OPENER, "open", side_effect=OSError("sin red")):
            self.assertIsNone(self.store.fetch_aur_info("x"))

    def appstream(self, payload):
        return FakeResp(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload, "application/json")

    def test_icon_urls_from_the_flathub_api_must_be_https(self):
        for evil in ("file:///etc/passwd", "http://evil.example/x.png", "ftp://evil/x.png", "//evil.example/x.png", "javascript:alert(1)"):
            with self.subTest(url=evil), self.opener(self.appstream({"icon": evil})) as op:
                self.assertIsNone(self.store._fetch_flathub_icon("app", "org.x.App"))
                self.assertEqual(op.call_count, 1, "solo el appstream; el ícono malo no se pidió")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_relative_icon_path_is_resolved_against_flathub_over_https(self):
        with self.opener(self.appstream({"icon": "/repo/icons/x.png"}), FakeResp(b"\x89PNG....")) as op:
            uri = self.store._fetch_flathub_icon("app", "org.x.App")
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertEqual(op.call_args_list[1].args[0].full_url, "https://flathub.org/repo/icons/x.png")
        self.assertTrue((self.cache / "app.png").is_file())

    def test_oversized_or_empty_icons_are_dropped_and_never_cached(self):
        for body in (b"", b"A" * (self.store.MAX_ICONO + 1)):
            with self.subTest(size=len(body)), self.opener(self.appstream({"icon": "https://flathub.org/x.png"}), FakeResp(body)):
                self.assertIsNone(self.store._fetch_flathub_icon("app", "org.x.App"))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_unexpected_shapes_in_the_flathub_json_do_not_crash_the_icon_thread(self):
        """Antes: json.loads dentro del try pero data.get(...) fuera → AttributeError con `null`, una lista, etc."""
        shapes = [None, [], [1, 2], 5, "texto", {}, {"icon": None}, {"icon": 5}, {"icon": {"url": 5}}, {"icon": {"url": None}},
                  {"icon": []}, {"icons": []}, {"icons": [None]}, {"icons": ["x"]}, {"icons": [{"url": 7}]}, {"icon": {}}]
        for payload in shapes:
            with self.subTest(payload=payload), self.opener(self.appstream(payload)):
                self.assertIsNone(self.store._fetch_flathub_icon("app", "org.x.App"))
        with self.opener(self.appstream(b"{no es json")):
            self.assertIsNone(self.store._fetch_flathub_icon("app", "org.x.App"))

    def test_svg_icons_are_recognised_and_encoded_as_svg(self):
        with self.opener(self.appstream({"icon": "https://flathub.org/x.svg"}), FakeResp(b"<svg/>", "image/svg+xml")):
            uri = self.store._fetch_flathub_icon("app", "org.x.App")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
        self.assertTrue((self.cache / "app.svg").is_file())


# ── invariantes entre policy, GUI, catálogo e instalación ─────────────────────────────────────────────
class Invariants(unittest.TestCase):
    def actions(self, path):
        out = {}
        for a in ET.parse(path).getroot().iter("action"):
            ann = {n.get("key").rsplit(".", 1)[-1]: (n.text or "").strip() for n in a.iter("annotate")}
            defaults = {d.tag: (d.text or "").strip() for d in a.find("defaults")}
            out[a.get("id")] = (ann, defaults)
        return out

    def test_the_store_policy_authorizes_only_the_helper_and_one_verb_per_action(self):
        acts = self.actions(POLICY)
        self.assertEqual(set(acts), {"com.avalos.store.install", "com.avalos.store.uninstall"})
        for action_id, verb in (("com.avalos.store.install", "install"), ("com.avalos.store.uninstall", "uninstall")):
            ann, defaults = acts[action_id]
            self.assertEqual(ann["path"], HELPER_PATH, "ninguna acción puede volver a autorizar /usr/bin/pacman")
            self.assertEqual(ann["argv1"], verb)
            self.assertEqual(defaults, {"allow_any": "no", "allow_inactive": "no", "allow_active": "auth_admin_keep"})

    def test_no_polkit_policy_in_the_repo_authorizes_pacman_a_shell_or_an_interpreter(self):
        for policy in (ROOT / "configs").glob("*.policy"):
            for action_id, (ann, _d) in self.actions(policy).items():
                path = ann.get("path", "")
                self.assertTrue(path.startswith("/usr/local/bin/avalos-"), f"{action_id} autoriza {path}")

    def test_every_path_a_policy_authorizes_exists_as_a_script_that_the_installer_copies(self):
        optimize = (ROOT / "scripts/avalos_installer/system/optimize.py").read_text(encoding="utf-8")
        for policy in (ROOT / "configs").glob("*.policy"):
            for action_id, (ann, _d) in self.actions(policy).items():
                name = Path(ann["path"]).name
                self.assertTrue((ROOT / "scripts" / name).is_file(), f"{action_id}: no existe scripts/{name}")
                self.assertIn(f'"{name}"', optimize, f"{name} no está en la lista de scripts del instalador")

    def test_the_helper_is_executable_python_and_registered_everywhere(self):
        self.assertTrue(os.access(HELPER, os.X_OK))
        self.assertEqual(HELPER.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")
        optimize = (ROOT / "scripts/avalos_installer/system/optimize.py").read_text(encoding="utf-8")
        legacy = (ROOT / "scripts/skill_instalar_usb.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
        sync = (ROOT / "scripts/gen-sync-manifest.py").read_text(encoding="utf-8")
        helper_sync = (ROOT / "scripts/avalos-update-helper").read_text(encoding="utf-8")
        doctor = (ROOT / "scripts/avalos-doctor").read_text(encoding="utf-8")
        for label, text in (("optimize.py", optimize), ("instalador legado", legacy), ("doctor", doctor)):
            # assertTrue y no assertIn: si falla, assertIn volcaría el archivo entero (el legado pesa 9 000 líneas)
            self.assertTrue('"avalos-store-helper"' in text, f"{label}: falta avalos-store-helper")
        self.assertRegex(workflow, r"for _s in [a-z\- ]*avalos-store-helper[a-z\- ]*; do")
        self.assertIn('"scripts/avalos-store-helper"', sync)
        self.assertIn('("scripts/avalos-store-helper", "/usr/local/bin/avalos-store-helper", 0o755)', helper_sync)

    def test_every_app_in_the_catalog_is_acceptable_to_the_helper(self):
        h = load_script(HELPER, "avalos_store_helper_catalog_check")
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        for app in catalog:
            self.assertRegex(app["id"], h._APP_ID_RE.pattern, f"id no aceptado por el helper: {app['id']}")
            if app.get("source") in ("pacman", "aur"):
                self.assertRegex(app["package"], h._PKG_RE.pattern, f"{app['id']}: nombre de paquete no aceptado")
                self.assertNotIn(app["package"], h.PROTECTED, f"{app['id']}: no se podría desinstalar nunca (paquete protegido)")

    def test_the_default_catalog_candidates_are_system_paths_only(self):
        h = load_script(HELPER, "avalos_store_helper_paths")
        for p in h.CATALOG_CANDIDATES:
            self.assertTrue(str(p).startswith(("/usr/local/", "/usr/share/")), p)
        self.assertEqual(h.PACMAN, "/usr/bin/pacman")
        self.assertEqual(h.TRUSTED_UIDS, (0,))


if __name__ == "__main__":
    unittest.main()
