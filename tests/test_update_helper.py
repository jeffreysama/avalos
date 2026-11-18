"""Inyección de fallos contra scripts/avalos-update-helper — el único script de AvalOS que corre como
root (vía pkexec) Y baja código de internet. Cada prueba provoca a propósito un fallo o una entrada
hostil y comprueba que el helper falla CERRADO: sin escribir nada, sin dejar sudo abierto y sin colgarse.

Se carga como módulo (el script no tiene extensión). Nada de esto toca el sistema real: las rutas de
sistema (SYNC_ROOT, SUDOERS_AUR, AUR_LOCK, TMPFILES_AUR) van a un directorio temporal y la red, visudo
y yay se sustituyen por dobles. Correr: python3 -m unittest tests.test_update_helper -v
"""
import ast
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "avalos-update-helper"
GOOD_BACKUP = "@.avalos-restore-backup-20260101-123456-000001"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("avalos_update_helper_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def helper_sync_entries():
    """(origen, destino, modo) de `manifest` dentro de cmd_sync_system_files, leídos con ast: la misma
    forma en que scripts/gen-sync-manifest.py comprueba que las dos listas coinciden."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "cmd_sync_system_files":
            for n in ast.walk(fn):
                if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                        and n.targets[0].id == "manifest" and isinstance(n.value, ast.List)):
                    return [tuple(e.value for e in t.elts) for t in n.value.elts]
    raise AssertionError("no encontré `manifest = [...]` en cmd_sync_system_files")


class FakeResponse:
    """Lo mínimo de http.client.HTTPResponse que usa el helper."""

    def __init__(self, body=b"", status=200):
        self.status, self._body, self.reads = status, body, []

    def read(self, n=-1):
        self.reads.append(n)
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-helper-test-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))
        self.sudoers_dir = self.tmp / "sudoers.d"
        self.sudoers_dir.mkdir()
        self.sudoers = self.sudoers_dir / "zz-avalos-update-aur"
        self.lock = self.tmp / "aur.lock"
        self.tmpfiles = self.tmp / "tmpfiles.d" / "avalos-update-aur.conf"
        self.root = self.tmp / "root"
        self.root.mkdir()
        patches = [
            mock.patch.object(self.h, "SUDOERS_AUR", self.sudoers),
            mock.patch.object(self.h, "AUR_LOCK", self.lock),
            mock.patch("os.geteuid", return_value=0),
            mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid())}),
        ]
        for name, value in (("TMPFILES_AUR", self.tmpfiles), ("SYNC_ROOT", self.root)):
            patches.append(mock.patch.object(self.h, name, value))  # sin create=True: si falta, falla (y no escribe en /)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *argv):
        buf = io.StringIO()
        with (mock.patch.object(sys, "argv", ["avalos-update-helper", *argv]),
              contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO())):
            try:
                self.h.main()
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, buf.getvalue()


# ── 1. nombres de respaldo (delete-backup borra subvolúmenes: la validación tiene que ser exacta) ──────
class BackupNames(HelperCase):
    def test_the_canonical_name_is_accepted(self):
        self.assertTrue(self.h._es_nombre_de_respaldo(GOOD_BACKUP))

    def test_hostile_or_malformed_names_are_rejected(self):
        hostile = [
            GOOD_BACKUP + "\n",                      # `$` de re.match acepta un salto de línea final
            GOOD_BACKUP + "\x00",
            "\n" + GOOD_BACKUP,
            "x" + GOOD_BACKUP,
            GOOD_BACKUP + "x",
            "@.avalos-restore-backup-٢٠٢٦٠١٠١-١٢٣٤٥٦-٠٠٠٠٠١",   # \d de str acepta dígitos Unicode
            "@.avalos-restore-backup-2026010-123456-000001",
            "../" + GOOD_BACKUP,
            GOOD_BACKUP.replace("@.", "@/"),
            "@", "@.avalos-restore-backup-", "", " ",
            "@.avalos-restore-backup-20260101-123456-000001/../@",
        ]
        for name in hostile:
            with self.subTest(name=name):
                self.assertFalse(self.h._es_nombre_de_respaldo(name))

    def test_delete_backup_never_mounts_anything_for_a_bad_name(self):
        with mock.patch.object(self.h, "_mount_top_level") as mount, \
             mock.patch.object(self.h, "_root_source_device") as dev:
            for name in (GOOD_BACKUP + "\n", "../@", "@", "../../etc"):
                with self.subTest(name=name):
                    code, _ = self.run_main("delete-backup", "--name", name)
                    self.assertNotEqual(code, 0)
        mount.assert_not_called()
        dev.assert_not_called()


# ── 2. el manifiesto de checksums (CWE-494: lo que decide qué se instala como root) ─────────────────────
class ManifestParsing(HelperCase):
    H1, H2 = "a" * 64, "b" * 64

    def parse(self, text):
        with mock.patch.object(self.h, "_descargar", return_value=text.encode("utf-8")):
            return self.h._cargar_manifest_hashes()

    def test_well_formed_manifest(self):
        got = self.parse(f"# comentario\n\n{self.H1}  scripts/avalos-store\n{self.H2}  configs/x.json\r\n")
        self.assertEqual(got, {"scripts/avalos-store": self.H1, "configs/x.json": self.H2})

    def test_every_kind_of_corruption_fails_closed(self):
        bad = {
            "hash corto": f"{'a' * 63}  scripts/x\n",
            "hash largo": f"{'a' * 65}  scripts/x\n",
            "hash no hexadecimal": f"{'g' * 64}  scripts/x\n",
            "sin ruta": f"{self.H1}\n",
            "ruta duplicada": f"{self.H1}  scripts/x\n{self.H2}  scripts/x\n",
            "ruta con ..": f"{self.H1}  ../../etc/shadow\n",
            "ruta absoluta": f"{self.H1}  /etc/shadow\n",
            "ruta con ..  en medio": f"{self.H1}  scripts/../../etc/shadow\n",
            "vacío": "",
            "solo comentarios": "# nada\n# más nada\n",
            "una línea buena y una mala": f"{self.H1}  scripts/x\nbasura\n",
        }
        for label, text in bad.items():
            with self.subTest(label):
                self.assertIsNone(self.parse(text))

    def test_non_utf8_body_and_network_errors_return_none_never_raise(self):
        with mock.patch.object(self.h, "_descargar", return_value=b"\xff\xfe\x00" + self.H1.encode()):
            self.assertIsNone(self.h._cargar_manifest_hashes())
        for exc in (OSError("boom"), urllib.error.URLError("sin red"), TimeoutError(), ValueError("x"),
                    ConnectionResetError()):
            with self.subTest(exc=type(exc).__name__), mock.patch.object(self.h, "_descargar", side_effect=exc):
                self.assertIsNone(self.h._cargar_manifest_hashes())

    def test_verification_rejects_unlisted_and_mismatching_files(self):
        data = b"hola"
        good = {"scripts/x": hashlib.sha256(data).hexdigest()}
        self.assertIsNone(self.h._verificar_contra_manifest("scripts/x", data, good))
        self.assertIn("no está listado", self.h._verificar_contra_manifest("scripts/y", data, good))
        self.assertIn("no coincide", self.h._verificar_contra_manifest("scripts/x", b"HOLA", good))


# ── 3. descargas: solo https, con tope de tamaño, sin seguir redirecciones a http ──────────────────────
class Download(HelperCase):
    def test_non_https_urls_are_refused_before_touching_the_network(self):
        with mock.patch.object(self.h._OPENER, "open") as opener:
            for url in ("http://raw.githubusercontent.com/x", "file:///etc/shadow", "ftp://x/y", "//x/y", ""):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.h._descargar(url)
        opener.assert_not_called()

    def test_http_errors_and_oversized_bodies_raise(self):
        with mock.patch.object(self.h._OPENER, "open", return_value=FakeResponse(b"x", status=503)):
            with self.assertRaises(OSError):
                self.h._descargar("https://example.org/a")
        big = FakeResponse(b"A" * 5000)
        with mock.patch.object(self.h._OPENER, "open", return_value=big):
            with self.assertRaises(OSError):
                self.h._descargar("https://example.org/a", limite=1000)
        self.assertTrue(all(isinstance(n, int) and 0 < n <= 1001 for n in big.reads),
                        f"nunca debe leer sin tope: {big.reads}")

    def test_a_normal_body_is_returned_intact(self):
        with mock.patch.object(self.h._OPENER, "open", return_value=FakeResponse(b"contenido")):
            self.assertEqual(self.h._descargar("https://example.org/a"), b"contenido")

    def test_redirect_to_http_is_refused_but_https_is_followed(self):
        handler = self.h._SoloHttpsRedirect()
        req = urllib.request.Request("https://raw.githubusercontent.com/a")
        for target in ("http://evil.example/a", "ftp://evil.example/a", "file:///etc/shadow"):
            with self.subTest(target=target), self.assertRaises(urllib.error.URLError):
                handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, target)
        nxt = handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://objects.githubusercontent.com/b")
        self.assertEqual(nxt.full_url, "https://objects.githubusercontent.com/b")


# ── 4. sync-system-files: nada se escribe sin pasar la verificación; escritura atómica y a prueba de symlinks
class SyncSystemFiles(HelperCase):
    def setUp(self):
        super().setUp()
        self.entries = helper_sync_entries()
        self.repo = {src: f"contenido de {src}\n".encode() for src, _d, _m in self.entries}
        self.listed = {src: hashlib.sha256(data).hexdigest() for src, data in self.repo.items()}
        self.get_calls = []
        p = mock.patch.object(self.h, "_descargar", side_effect=self.fake_get)
        p.start()
        self.addCleanup(p.stop)

    def manifest_bytes(self):
        return "".join(f"{h}  {src}\n" for src, h in self.listed.items()).encode()

    def fake_get(self, url, *a, **kw):
        self.get_calls.append(url)
        prefix = self.h.REPO_RAW + "/"
        self.assertTrue(url.startswith(prefix), f"URL fuera del commit pineado: {url}")
        rel = url[len(prefix):]
        if rel == "configs/MANIFEST.sha256":
            return self.manifest_bytes()
        if rel not in self.repo:
            raise OSError("HTTP 404")
        value = self.repo[rel]
        if isinstance(value, Exception):
            raise value
        return value

    def dest(self, absolute):
        return self.root / absolute.lstrip("/")

    def leftovers(self):
        return [p for p in self.root.rglob("*") if "avalos-tmp" in p.name]

    def test_happy_path_writes_every_file_with_its_mode_and_leaves_no_temp_files(self):
        code, out = self.run_main("sync-system-files")
        self.assertEqual(code, 0, out)
        for src, dest, mode in self.entries:
            p = self.dest(dest)
            self.assertEqual(p.read_bytes(), self.repo[src], dest)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), mode, dest)
        self.assertEqual(self.leftovers(), [])

    def test_a_tampered_file_is_never_written_and_the_run_reports_failure(self):
        victim_src, victim_dest, _ = next(e for e in self.entries if e[0] == "scripts/avalos-store")
        self.repo[victim_src] = b"#!/bin/sh\nrm -rf /\n"          # el manifiesto sigue con el hash legítimo
        old = self.dest(victim_dest)
        old.parent.mkdir(parents=True)
        old.write_bytes(b"version vieja\n")
        code, out = self.run_main("sync-system-files")
        self.assertNotEqual(code, 0, "un archivo rechazado no puede terminar como éxito")
        self.assertEqual(old.read_bytes(), b"version vieja\n")
        others = [d for _s, d, _m in self.entries if d != victim_dest]
        self.assertTrue(all(self.dest(d).exists() for d in others), "el resto sí se sincroniza")
        self.assertIn("no coincide", out)

    def test_a_file_missing_from_the_manifest_is_refused(self):
        src, dest, _ = self.entries[0]
        del self.listed[src]
        code, out = self.run_main("sync-system-files")
        self.assertNotEqual(code, 0)
        self.assertFalse(self.dest(dest).exists())
        self.assertIn("no está listado", out)

    def test_a_failed_download_keeps_the_installed_file_and_reports_failure(self):
        src, dest, _ = self.entries[3]
        self.repo[src] = OSError("HTTP 500")
        old = self.dest(dest)
        old.parent.mkdir(parents=True)
        old.write_bytes(b"instalado antes\n")
        code, _ = self.run_main("sync-system-files")
        self.assertNotEqual(code, 0)
        self.assertEqual(old.read_bytes(), b"instalado antes\n")

    def test_unreachable_manifest_writes_nothing_and_fails(self):
        with mock.patch.object(self.h, "_descargar", side_effect=urllib.error.URLError("sin red")):
            code, out = self.run_main("sync-system-files")
        self.assertEqual(code, 1)
        self.assertEqual(list(self.root.rglob("*")), [])
        self.assertIn("MANIFEST", out)

    def test_an_unpinned_release_fails_closed_without_any_request(self):
        for bad in ("UNSET", "", "main", "g" * 40, "A" * 40, "a" * 39, "a" * 41):
            with self.subTest(ref=bad), mock.patch.object(self.h, "AVALOS_SYNC_REF", bad):
                self.get_calls.clear()
                code, _ = self.run_main("sync-system-files")
                self.assertEqual(code, 1)
                self.assertEqual(self.get_calls, [])
        self.assertEqual(list(self.root.rglob("*")), [])

    def test_a_symlink_planted_at_the_destination_is_replaced_never_followed(self):
        src, dest, _ = self.entries[0]
        victim = self.tmp / "victim"
        victim.write_bytes(b"intacto\n")
        d = self.dest(dest)
        d.parent.mkdir(parents=True)
        d.symlink_to(victim)
        self.assertEqual(self.run_main("sync-system-files")[0], 0)
        self.assertEqual(victim.read_bytes(), b"intacto\n")
        self.assertFalse(d.is_symlink())
        self.assertEqual(d.read_bytes(), self.repo[src])

    def test_a_symlink_planted_at_a_predictable_temp_name_is_not_written_through(self):
        victim = self.tmp / "victim"
        victim.write_bytes(b"intacto\n")
        for _src, dest, _m in self.entries:
            d = self.dest(dest)
            d.parent.mkdir(parents=True, exist_ok=True)
            for guess in (str(d) + ".avalos-tmp", str(d.parent / f".{d.name}.avalos-tmp"),
                          str(d.parent / f"{d.name}.tmp"), str(d.parent / f".{d.name}.tmp")):
                with contextlib.suppress(FileExistsError):
                    os.symlink(victim, guess)
        self.assertEqual(self.run_main("sync-system-files")[0], 0)
        self.assertEqual(victim.read_bytes(), b"intacto\n")

    def test_a_write_failure_midway_leaves_the_destination_intact_and_cleans_the_temp(self):
        src, dest, _ = self.entries[5]
        d = self.dest(dest)
        d.parent.mkdir(parents=True)
        d.write_bytes(b"viejo\n")
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(a, b, *args, **kw):
            if str(b).endswith(d.name):
                calls["n"] += 1
                raise OSError(28, "No space left on device")
            return real_replace(a, b, *args, **kw)

        with mock.patch("os.replace", side_effect=flaky):
            code, out = self.run_main("sync-system-files")
        self.assertEqual(calls["n"], 1)
        self.assertNotEqual(code, 0)
        self.assertEqual(d.read_bytes(), b"viejo\n")
        self.assertEqual(self.leftovers(), [], "no debe quedar el temporal")
        self.assertIn("No space left", out)

    def test_stale_temp_files_from_a_killed_run_are_swept(self):
        src, dest, _ = self.entries[0]
        d = self.dest(dest)
        d.parent.mkdir(parents=True)
        stale = [d.parent / f".{d.name}.avalos-tmp-abc123", Path(str(d) + ".avalos-tmp")]
        for s in stale:
            s.write_bytes(b"restos")
        self.assertEqual(self.run_main("sync-system-files")[0], 0)
        self.assertEqual(self.leftovers(), [])

    def test_every_destination_stays_inside_the_system_root(self):
        for _src, dest, _m in self.entries:
            self.assertTrue(dest.startswith("/") and ".." not in Path(dest).parts, dest)
            self.assertEqual(os.path.commonpath([self.root, self.dest(dest)]), str(self.root))


# ── 5. apply-aur: el NOPASSWD temporal es lo más delicado del helper ────────────────────────────────────
class ApplyAur(HelperCase):
    def setUp(self):
        super().setUp()
        self.visudo = mock.patch.object(self.h, "_visudo_ok", return_value=True)
        self.visudo_mock = self.visudo.start()
        self.addCleanup(self.visudo.stop)

    def stream_double(self, rc=0, seen=None):
        def fake(cmd, idle_timeout=None, **kw):
            if seen is not None:
                seen["cmd"] = list(cmd)
                seen["exists"] = self.sudoers.exists()
                seen["text"] = self.sudoers.read_text() if self.sudoers.exists() else None
                seen["mode"] = stat.S_IMODE(self.sudoers.stat().st_mode) if self.sudoers.exists() else None
            return rc
        return mock.patch.object(self.h, "_stream", side_effect=fake)

    def test_valid_package_names_reach_yay_unchanged(self):
        names = ["yay-bin", "lib32-foo", "python-pip_x", "gtk2+", "foo@bar", "libc++", "a", "Foo.Bar-1"]
        seen = {}
        with self.stream_double(0, seen):
            code, _ = self.run_main("apply-aur", *names)
        self.assertEqual(code, 0)
        self.assertEqual(seen["cmd"][-len(names):], names)
        self.assertIn("yay", seen["cmd"])

    def test_hostile_package_names_are_rejected_before_anything_is_written(self):
        hostile = ["--sudo=/tmp/x", "-S", "--editor=/bin/sh", "a b", "a;b", "$(id)", "`id`", "a|b", "a&b",
                   "a\nb", "", "..", ".hidden", "-", "x" * 300, "a/b", "a\\b", "a'b", 'a"b', "a\x00b", "ä"]
        with self.stream_double() as stream:
            for name in hostile:
                with self.subTest(name=name):
                    code, _ = self.run_main("apply-aur", "--", name)   # `--`: argparse deja pasar «-S» como posicional
                    self.assertNotEqual(code, 0)
        stream.assert_not_called()
        self.assertFalse(self.sudoers.exists())
        self.assertEqual(list(self.sudoers_dir.iterdir()), [])

    def test_the_sudoers_file_is_validated_before_it_becomes_active_and_has_the_right_shape(self):
        seen_at_validation = {}

        def validate(path):
            seen_at_validation["active"] = self.sudoers.exists()
            seen_at_validation["name"] = Path(path).name
            seen_at_validation["text"] = Path(path).read_text()
            seen_at_validation["mode"] = stat.S_IMODE(Path(path).stat().st_mode)
            return True

        self.visudo_mock.side_effect = validate
        seen = {}
        with self.stream_double(0, seen):
            self.assertEqual(self.run_main("apply-aur", "foo")[0], 0)
        user = self.h.pwd.getpwuid(os.getuid()).pw_name
        self.assertFalse(seen_at_validation["active"], "sudo ya lo habría leído sin validar")
        self.assertIn(".", seen_at_validation["name"], "con punto en el nombre sudo lo ignora hasta el rename")
        self.assertEqual(seen_at_validation["mode"], 0o440)
        self.assertTrue(seen["exists"])
        self.assertEqual(seen["mode"], 0o440)
        self.assertEqual(seen["text"], f"Defaults:{user} !authenticate\n{user} ALL=(ALL:ALL) NOPASSWD: ALL\n")
        self.assertFalse(self.sudoers.exists(), "se borra al terminar")

    def test_visudo_ok_only_trusts_a_clean_exit_and_fails_closed_when_visudo_is_missing(self):
        self.visudo.stop()                      # los demás tests sustituyen _visudo_ok entero; este usa el verdadero
        self.addCleanup(self.visudo.start)
        target = self.tmp / "x"
        for rc, expected in ((0, True), (1, False), (2, False), (-1, False), (127, False)):
            with self.subTest(rc=rc), mock.patch.object(self.h, "_run", return_value=(rc, "", "")) as run:
                self.assertIs(self.h._visudo_ok(target), expected)
                self.assertEqual(run.call_args[0][0], ["visudo", "-cf", str(target)])

    def test_an_invalid_sudoers_file_is_never_activated(self):
        self.visudo_mock.return_value = False
        with self.stream_double() as stream:
            code, out = self.run_main("apply-aur", "foo")
        self.assertNotEqual(code, 0)
        stream.assert_not_called()
        self.assertEqual(list(self.sudoers_dir.iterdir()), [], "ni el temporal debe quedar")
        self.assertIn("sudoers", out)

    def test_sudoers_is_removed_when_the_build_raises(self):
        with mock.patch.object(self.h, "_stream", side_effect=RuntimeError("yay reventó")):
            with self.assertRaises(RuntimeError):
                self.run_main("apply-aur", "foo")
        self.assertEqual(list(self.sudoers_dir.iterdir()), [])
        fd = self.h._aur_lock_try()
        self.assertIsNotNone(fd, "el candado debe soltarse aunque falle")
        os.close(fd)

    def test_failing_to_delete_the_sudoers_is_reported_loudly_and_still_releases_the_lock(self):
        real_unlink = Path.unlink

        def immutable(self_, *a, **kw):   # p. ej. chattr +i
            if self_.name == "zz-avalos-update-aur":
                raise PermissionError("Operation not permitted")
            return real_unlink(self_, *a, **kw)

        with self.stream_double(0), mock.patch.object(Path, "unlink", immutable):
            code, out = self.run_main("apply-aur", "foo")
        self.assertEqual(code, 5, "con el NOPASSWD aún puesto no puede terminar como éxito")
        self.assertIn("sin contraseña", out.lower())
        self.assertIn(str(self.sudoers), out, "tiene que decir qué archivo borrar a mano")
        fd = self.h._aur_lock_try()
        self.assertIsNotNone(fd, "un fallo al borrar no debe dejar el candado tomado")
        os.close(fd)

    def test_the_lock_is_released_even_if_the_cleanup_itself_blows_up(self):
        with self.stream_double(0), mock.patch.object(self.h, "_borrar_sudoers_aur", side_effect=RuntimeError("raro")):
            with self.assertRaises(RuntimeError):
                self.run_main("apply-aur", "foo")
        fd = self.h._aur_lock_try()
        self.assertIsNotNone(fd)
        os.close(fd)

    def test_names_that_would_corrupt_sudoers_are_refused(self):
        evil = ["evil\nroot ALL=(ALL) NOPASSWD: ALL", "a b", "a,b", "#0", "%wheel", "-x", "", "a=b", "a:b", "!x", "+x", "@x"]
        with self.stream_double() as stream:
            for name in evil:
                with self.subTest(name=name), mock.patch.object(self.h.pwd, "getpwuid",
                                                                return_value=SimpleNamespace(pw_name=name)):
                    code, _ = self.run_main("apply-aur", "foo")
                    self.assertNotEqual(code, 0)
        stream.assert_not_called()
        self.assertEqual(list(self.sudoers_dir.iterdir()), [])

    def test_a_second_concurrent_run_is_refused_and_does_not_steal_the_first_ones_sudoers(self):
        held = self.h._aur_lock_try()
        self.addCleanup(os.close, held)
        self.sudoers.write_text("# del apply-aur que sigue vivo\n")
        with self.stream_double() as stream:
            code, out = self.run_main("apply-aur", "foo")
        self.assertNotEqual(code, 0)
        stream.assert_not_called()
        self.assertTrue(self.sudoers.exists(), "ese archivo es del otro proceso, que mantiene el candado")
        self.assertIn("otra", out)

    def test_an_orphan_sudoers_file_is_removed_by_any_subcommand_when_nobody_holds_the_lock(self):
        self.sudoers.write_text("user ALL=(ALL:ALL) NOPASSWD: ALL\n")
        with mock.patch.object(self.h, "_stream", return_value=0):
            self.run_main("snapshot")
        self.assertFalse(self.sudoers.exists())

    def test_a_boot_time_cleanup_rule_is_installed_so_a_power_cut_cannot_leave_sudo_open(self):
        with self.stream_double(0):
            self.assertEqual(self.run_main("apply-aur", "foo")[0], 0)
        self.assertEqual(self.tmpfiles.read_text(), f"r! {self.sudoers}\n")

    def test_failing_to_install_the_boot_rule_is_only_a_warning(self):
        self.tmpfiles.parent.parent.joinpath("tmpfiles.d").write_text("soy un archivo, no un directorio")
        with self.stream_double(0):
            code, out = self.run_main("apply-aur", "foo")
        self.assertEqual(code, 0)
        self.assertIn("tmpfiles", out)

    def test_yay_failure_is_reported_with_its_exit_code(self):
        with self.stream_double(rc=7):
            code, _ = self.run_main("apply-aur", "foo")
        self.assertEqual(code, 7)
        self.assertEqual(list(self.sudoers_dir.iterdir()), [])


class ApplyAurSignals(HelperCase):
    """Cierra el hueco real: matar el helper (la GUI hace kill tras 180 s de silencio; el usuario cierra la
    ventana; corte de luz) NO puede dejar un NOPASSWD permanente. SIGTERM/SIGHUP ejecutan el `finally`;
    SIGKILL no se puede atrapar, y ahí manda la limpieza al siguiente arranque del helper."""

    DRIVER = textwrap.dedent("""
        import importlib.machinery, importlib.util, os, sys, time
        from pathlib import Path
        from unittest import mock
        loader = importlib.machinery.SourceFileLoader("h", sys.argv[1])
        spec = importlib.util.spec_from_loader("h", loader)
        h = importlib.util.module_from_spec(spec); loader.exec_module(h)
        d = Path(sys.argv[2])
        h.SUDOERS_AUR = d / "sudoers.d" / "zz-avalos-update-aur"
        h.AUR_LOCK = d / "aur.lock"
        h.TMPFILES_AUR = d / "tmpfiles.d" / "avalos-update-aur.conf"
        h._visudo_ok = lambda p: True
        def fake_stream(cmd, idle_timeout=None, **kw):
            print("READY", flush=True)
            time.sleep(60)
            return 0
        h._stream = fake_stream
        os.geteuid = lambda: 0
        os.environ["PKEXEC_UID"] = str(os.getuid())
        sys.argv = ["avalos-update-helper", "apply-aur", "foo"]
        h.main()
    """)

    @staticmethod
    def reap(proc):
        """Mata si sigue vivo, espera y CIERRA los pipes (si no, ResourceWarning por cada subproceso)."""
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=20)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

    def start(self):
        proc = subprocess.Popen([sys.executable, "-c", self.DRIVER, str(SCRIPT), str(self.tmp)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.reap, proc)
        vistas = []
        while True:   # el helper imprime «### instalando…» antes de llegar al _stream falso que imprime READY
            line = proc.stdout.readline()
            if not line:
                break
            vistas.append(line.strip())
            if line.strip() == "READY":
                break
        self.assertIn("READY", vistas, f"el driver no llegó a READY: {vistas}\n{proc.stderr.read() if proc.poll() is not None else ''}")
        self.assertTrue(self.sudoers.exists(), "mientras compila, el NOPASSWD tiene que existir")
        return proc

    def test_sigterm_and_sighup_run_the_cleanup(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                proc = self.start()
                proc.send_signal(sig)
                proc.wait(timeout=20)
                self.assertFalse(self.sudoers.exists(), f"{sig.name} dejó el sudoers abierto")
                self.assertEqual(list(self.sudoers_dir.iterdir()), [])

    def test_after_sigkill_the_next_run_cleans_the_orphan(self):
        proc = self.start()
        proc.kill()
        proc.wait(timeout=20)
        self.assertTrue(self.sudoers.exists(), "SIGKILL no se puede atrapar: el archivo queda")
        with contextlib.redirect_stdout(io.StringIO()):         # imprime «eliminado un NOPASSWD temporal huérfano…»
            self.h._limpiar_sudoers_aur_huerfano()
        self.assertFalse(self.sudoers.exists())


# ── 6. _stream: salida en vivo, colgados, bytes raros ──────────────────────────────────────────────────
class Stream(HelperCase):
    def py(self, code):
        """El hijo va en un archivo: así el eco «### $ …» del helper es UNA línea y las pruebas pueden comparar
        la salida del hijo sin tener que saltarse un número variable de líneas."""
        self._n = getattr(self, "_n", 0) + 1
        script = self.tmp / f"child{self._n}.py"
        script.write_text(textwrap.dedent(code), encoding="utf-8")
        return [sys.executable, str(script)]

    def run_stream(self, cmd, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.h._stream(cmd, **kw)
        return rc, buf.getvalue()

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:   # zombi sin reapear cuenta como muerto
            return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
        except (OSError, IndexError):
            return False

    def test_lines_are_forwarded_and_the_exit_code_is_returned(self):
        rc, out = self.run_stream(self.py("print('uno'); print('dos'); raise SystemExit(3)"))
        self.assertEqual(rc, 3)
        self.assertIn("uno\ndos\n", out)

    def test_invalid_utf8_in_the_output_does_not_break_the_stream(self):
        rc, out = self.run_stream(self.py("import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe fin\\n')"))
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

    def test_a_missing_binary_returns_127_instead_of_a_traceback(self):
        rc, out = self.run_stream(["/no/existe/pacman-fantasma"])
        self.assertEqual(rc, 127)
        self.assertIn("pacman-fantasma", out)

    def test_a_silent_hang_is_killed_and_reported_as_124_with_the_whole_process_tree(self):
        pidfile = self.tmp / "pids"
        code = f"""
            import os, subprocess, sys, time
            g = subprocess.Popen(["sleep", "60"])
            open({str(pidfile)!r}, "w").write(f"{{os.getpid()}} {{g.pid}}")
            time.sleep(60)
        """
        t0 = time.monotonic()
        rc, out = self.run_stream(self.py(code), idle_timeout=0.7)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - t0, 30)
        child, grandchild = (int(x) for x in pidfile.read_text().split())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (self.alive(child) or self.alive(grandchild)):
            time.sleep(0.05)
        self.assertFalse(self.alive(child), "el hijo sigue vivo")
        self.assertFalse(self.alive(grandchild), "yay/makepkg (nietos) quedaron huérfanos")

    def test_lines_written_just_before_a_hang_are_not_lost(self):
        """Lo que imprime un pacman justo antes de colgarse es lo que explica el cuelgue. select() mira el fd,
        no el búfer de Python: con readline() las líneas que llegaban juntas quedaban retenidas y, al matar
        por silencio, se perdían."""
        code = """
            import sys, time
            sys.stdout.write("uno\\ndos\\ntres\\ncuatro\\n"); sys.stdout.flush()
            time.sleep(60)
        """
        rc, out = self.run_stream(self.py(code), idle_timeout=0.7)
        self.assertEqual(rc, 124)
        for linea in ("uno", "dos", "tres", "cuatro"):
            self.assertIn(linea, out)

    def test_an_unfinished_line_written_before_a_hang_is_not_lost_either(self):
        code = """
            import sys, time
            sys.stdout.write("Waiting for db.lck to be released"); sys.stdout.flush()
            time.sleep(60)
        """
        rc, out = self.run_stream(self.py(code), idle_timeout=0.7)
        self.assertEqual(rc, 124)
        self.assertIn("Waiting for db.lck to be released", out)

    def test_progress_bars_that_redraw_with_carriage_returns_still_arrive_as_separate_lines(self):
        rc, out = self.run_stream(self.py(r"""
            import sys
            sys.stdout.write("10%\r50%\r100%\nlisto")
            sys.stdout.flush()
        """))
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines()[1:], ["10%", "50%", "100%", "listo"])

    def test_a_crlf_split_across_two_reads_does_not_produce_a_phantom_empty_line(self):
        rc, out = self.run_stream(self.py(r"""
            import sys, time
            sys.stdout.write("a\r"); sys.stdout.flush(); time.sleep(0.3)
            sys.stdout.write("\nb\n"); sys.stdout.flush()
        """))
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines()[1:], ["a", "b"])

    def test_a_hung_child_gets_sigterm_first_so_pacman_can_roll_back(self):
        marker = self.tmp / "got-term"
        code = f"""
            import signal, sys, time
            def on_term(*a):
                open({str(marker)!r}, "w").write("term")
                sys.exit(0)
            signal.signal(signal.SIGTERM, on_term)
            time.sleep(60)
        """
        rc, _ = self.run_stream(self.py(code), idle_timeout=0.7)
        self.assertEqual(rc, 124)
        self.assertEqual(marker.read_text(), "term", "se mató con SIGKILL sin dar oportunidad de limpiar")

    def test_a_child_that_ignores_sigterm_is_still_killed(self):
        code = """
            import signal, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        """
        with mock.patch.object(self.h, "KILL_GRACE", 0.5):
            t0 = time.monotonic()
            rc, _ = self.run_stream(self.py(code), idle_timeout=0.5)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - t0, 20)


# ── 7. restauración de snapshots: parsers y validación de argumentos ────────────────────────────────────
class RestoreParsers(HelperCase):
    def test_snapper_json_in_every_shape_never_raises(self):
        shapes = [
            "", "null", "[]", "{}", "42", '"texto"', "[[[[", "{", '{"root": 5}', '{"root": null}', '{"snapshots": "x"}',
            "[1, 2, 3]", '[{"number": "7"}]', '{"root": [{"number": 3}]}', '[{"nope": 1}, null, "x", 5]',
            "[" * 200000, '{"a":' * 100000, "\x00\xff", "[" + "{}," * 50 + "{}]",
        ]
        for raw in shapes:
            with self.subTest(raw=raw[:30]):
                self.assertIsInstance(self.h._parse_snapper_json(raw), list)

    def test_snapper_json_known_shapes_parse(self):
        pts = [{"number": 1}]
        self.assertEqual(self.h._parse_snapper_json(json.dumps(pts)), pts)
        self.assertEqual(self.h._parse_snapper_json(json.dumps({"root": pts})), pts)
        self.assertEqual(self.h._parse_snapper_json(json.dumps({"snapshots": pts})), pts)

    def test_list_restore_points_survives_garbage_from_snapper(self):
        top = self.tmp / "top"
        top.mkdir()
        (top / GOOD_BACKUP).mkdir()
        (top / (GOOD_BACKUP + "x")).mkdir()
        (top / "@home").mkdir()
        junk = json.dumps([{"number": "x"}, {"number": None}, {"number": 0}, {"number": -4}, {"number": 9, "date": None,
                                                                                              "description": None},
                           "rareza", None, {}])
        with mock.patch.object(self.h, "_run", return_value=(0, junk, "")), \
             mock.patch.object(self.h, "_root_source_device", return_value="/dev/fake"), \
             mock.patch.object(self.h, "_mount_top_level", return_value=top), \
             mock.patch.object(self.h, "_unmount_top_level") as umount:
            code, out = self.run_main("list-restore-points")
        self.assertEqual(code, 0, out)
        data = json.loads(out.strip().splitlines()[-1])
        self.assertEqual([p["number"] for p in data["points"]], [9])
        self.assertEqual(data["backups"], [GOOD_BACKUP])
        umount.assert_called_once()

    def test_the_top_level_mount_is_released_even_if_listing_it_fails(self):
        with mock.patch.object(self.h, "_run", return_value=(1, "", "no hay config")), \
             mock.patch.object(self.h, "_root_source_device", return_value="/dev/fake"), \
             mock.patch.object(self.h, "_mount_top_level", return_value=self.tmp / "no-existe"), \
             mock.patch.object(self.h, "_unmount_top_level") as umount:
            with self.assertRaises(OSError):
                self.run_main("list-restore-points")
        umount.assert_called_once()

    def test_restore_rejects_nonsense_snapshot_numbers_before_touching_the_disk(self):
        with mock.patch.object(self.h, "_root_source_device") as dev, mock.patch.object(self.h, "_stream") as st:
            for n in ("0", "-1", "-99999"):
                with self.subTest(n=n):
                    self.assertNotEqual(self.run_main("restore", "--number", n)[0], 0)
            for n in ("abc", "1.5", "", "1e3", "0x10"):
                with self.subTest(n=n):
                    self.assertEqual(self.run_main("restore", "--number", n)[0], 2)
        dev.assert_not_called()
        st.assert_not_called()

    def test_restore_refuses_a_root_that_is_not_the_avalos_btrfs_layout(self):
        for line in ("/dev/sda2[/@] rw,relatime,subvol=/@home\n", "/dev/sda2 rw\n", "", "/dev/sda2 ro,subvol=/@var\n"):
            with self.subTest(line=line), mock.patch.object(self.h, "_run", return_value=(0, line, "")):
                with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                    self.h._root_source_device()
        with mock.patch.object(self.h, "_run", return_value=(0, "/dev/mapper/cr[/@] rw,subvol=/@,x\n", "")):
            self.assertEqual(self.h._root_source_device(), "/dev/mapper/cr")


# ── 8. detección de CPU y superficie de la CLI ──────────────────────────────────────────────────────────
class CpuLevel(HelperCase):
    V3 = "avx avx2 bmi1 bmi2 f16c fma abm movbe xsave"
    V4 = V3 + " avx512f avx512bw avx512cd avx512dq avx512vl"

    def level(self, flags_line):
        data = f"processor\t: 0\nflags\t\t: {flags_line}\n" if flags_line is not None else "processor\t: 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=data)):
            return self.h.detectar_cpu_arch_level()

    def test_levels(self):
        self.assertEqual(self.level(self.V4), "x86-64-v4")
        self.assertEqual(self.level(self.V3), "x86-64-v3")
        self.assertEqual(self.level("sse sse2 ssse3 sse4_1 sse4_2 popcnt"), "x86-64-v2")

    def test_lzcnt_counts_as_abm_because_cpuinfo_never_lists_abm_on_some_cpus(self):
        self.assertEqual(self.level(self.V3.replace("abm", "lzcnt")), "x86-64-v3")

    def test_missing_or_unreadable_cpuinfo_degrades_without_raising(self):
        self.assertIn(self.level(None), ("x86-64-v2", "x86-64"))
        with mock.patch("builtins.open", side_effect=OSError("sin /proc")):
            self.assertEqual(self.h.detectar_cpu_arch_level(), "x86-64")


class CliSurface(HelperCase):
    def test_enum_arguments_are_closed(self):
        with mock.patch.object(self.h, "_stream") as st:
            for bad in ("../../x", "BORE", "", "bore;id", "eevdf "):
                with self.subTest(bad=bad):
                    self.assertEqual(self.run_main("apply-kernel", "--variant", bad)[0], 2)
        st.assert_not_called()

    def test_bore_is_refused_on_a_cpu_without_avx2_before_pacman_runs(self):
        with mock.patch.object(self.h, "detectar_cpu_arch_level", return_value="x86-64-v2"), \
             mock.patch.object(self.h, "_stream") as st, mock.patch.object(self.h, "_pacman_disponible") as av:
            code, out = self.run_main("apply-kernel", "--variant", "bore")
        self.assertEqual(code, 1)
        st.assert_not_called()
        av.assert_not_called()
        self.assertIn("AVX2", out)

    def test_every_subcommand_refuses_to_run_without_root(self):
        cases = [("apply-system",), ("apply-kernel", "--variant", "eevdf"), ("apply-aur", "foo"), ("snapshot",),
                 ("sync-system-files",), ("list-restore-points",), ("restore", "--number", "3"), ("list-backups",),
                 ("delete-backup", "--name", GOOD_BACKUP)]
        with mock.patch("os.geteuid", return_value=1000), mock.patch.object(self.h, "_stream") as st, \
             mock.patch.object(self.h, "_descargar") as dl, mock.patch.object(self.h, "_run") as run:
            for argv in cases:
                with self.subTest(argv=argv):
                    self.assertEqual(self.run_main(*argv)[0], 1)
        for m in (st, dl, run):
            m.assert_not_called()

    def test_every_subcommand_refuses_to_run_when_not_launched_by_pkexec(self):
        cases = [("apply-system",), ("snapshot",), ("sync-system-files",), ("list-backups",)]
        env = {k: v for k, v in os.environ.items() if k != "PKEXEC_UID"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(self.h, "_stream") as st:
            for argv in cases:
                with self.subTest(argv=argv):
                    self.assertEqual(self.run_main(*argv)[0], 1)
        st.assert_not_called()

    def test_a_uid_that_makes_pwd_overflow_is_refused_not_a_traceback(self):
        """En Python 3.12 pwd.getpwuid(-1) lanza KeyError, pero en otras versiones/plataformas lanza OverflowError."""
        with mock.patch.object(self.h.pwd, "getpwuid", side_effect=OverflowError("uid fuera de rango")), \
             mock.patch.object(self.h, "_stream") as st:
            self.assertEqual(self.run_main("snapshot")[0], 1)
        st.assert_not_called()

    def test_a_pkexec_uid_that_is_not_a_user_is_refused(self):
        for uid in ("abc", "", "99999999", "-1"):
            with self.subTest(uid=uid), mock.patch.dict(os.environ, {"PKEXEC_UID": uid}), \
                 mock.patch.object(self.h, "_stream") as st:
                self.assertEqual(self.run_main("snapshot")[0], 1)
                st.assert_not_called()


if __name__ == "__main__":
    unittest.main()
