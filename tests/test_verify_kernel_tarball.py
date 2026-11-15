"""scripts/verify-kernel-tarball.py con gpg y xz REALES y claves desechables (nada de red ni de kernel.org).

kernel.org firma el tar SIN comprimir (`linux-X.tar.sign`) y distribuye el .tar.xz: el script descomprime con xz y
verifica la firma sobre ese flujo. Aquí se reproduce el mismo esquema con un tar pequeño y una clave de prueba.
"""
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:      # CI lo instala (python3-yaml)
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify-kernel-tarball.py"
HAVE_TOOLS = bool(shutil.which("gpg") and shutil.which("xz"))


def load():
    spec = importlib.util.spec_from_file_location("verify_kernel_tarball_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, check=True, **kw)


@unittest.skipUnless(HAVE_TOOLS, "faltan gpg y/o xz")
class SignedTarball(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="avalos-vkt-"))      # corto: los sockets de gpg-agent tienen límite de ruta
        cls.m = load()
        cls.keys = {}
        for name, faked in (("greg", None), ("other", None), ("expired", "20200101T000000")):
            home = cls.base / f"sign-{name}"
            home.mkdir(mode=0o700)
            cmd = ["gpg", "--homedir", str(home), "--batch", "--passphrase", "", "--quick-generate-key", f"{name} <{name}@example.org>", "ed25519", "sign", "30d" if faked else "1y"]
            if faked:
                cmd[1:1] = ["--faked-system-time", faked]
            run(*cmd)
            out = run("gpg", "--homedir", str(home), "--with-colons", "--fingerprint", "--list-secret-keys").stdout.decode()
            fpr = next(l.split(":")[9] for l in out.splitlines() if l.startswith("fpr:"))
            pub = run("gpg", "--homedir", str(home), "--export", fpr).stdout
            cls.keys[name] = (home, fpr, pub)

    @classmethod
    def tearDownClass(cls):
        for name, (home, _f, _p) in cls.keys.items():
            subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "all"], capture_output=True)
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-vkt-t-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # tar «del kernel» (sin comprimir) + xz + firma detached sobre el tar, como kernel.org
        self.tar = self.tmp / "linux-9.9.9.tar"
        with tarfile.open(self.tar, "w") as t:
            for name, data in (("linux-9.9.9/Makefile", b"VERSION = 9\n"), ("linux-9.9.9/kernel/sched/core.c", b"int x;\n" * 500)):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        self.sig = self.tmp / "linux-9.9.9.tar.sign"
        self.sign_with("greg", self.tar, self.sig)
        run("xz", "-k", str(self.tar))
        self.xz = self.tmp / "linux-9.9.9.tar.xz"
        self.home = self.tmp / "g"                      # el llavero de verificación (como el del CI)
        self.home.mkdir(mode=0o700)
        self.addCleanup(lambda: subprocess.run(["gpgconf", "--homedir", str(self.home), "--kill", "all"], capture_output=True))
        self.import_key("greg")
        self.pinned = {self.keys["greg"][1]: "Greg (prueba)"}

    def sign_with(self, name, src, dst, faked_time=None):
        home, fpr, _ = self.keys[name]
        cmd = ["gpg", "--homedir", str(home), "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase", "", "--local-user", fpr,
               "--detach-sign", "-o", str(dst), str(src)]
        if faked_time:
            cmd[1:1] = ["--faked-system-time", faked_time]
        run(*cmd)

    def import_key(self, name):
        subprocess.run(["gpg", "--homedir", str(self.home), "--batch", "--import"], input=self.keys[name][2], capture_output=True, check=True)

    def verify(self, **kw):
        return self.m.verify(self.xz, self.sig, self.home, self.pinned, **kw)

    # ── la firma buena y sus fallos ─────────────────────────────────────────────────────────────────────
    def test_a_good_signature_by_a_pinned_key_is_accepted(self):
        ok, msg = self.verify()
        self.assertTrue(ok, msg)
        self.assertIn("Greg", msg)

    def test_a_tampered_tarball_is_rejected(self):
        self.tar.unlink()
        raw = bytearray(subprocess.run(["xz", "-dc", str(self.xz)], capture_output=True, check=True).stdout)
        raw[600] ^= 0xFF                                                   # un byte distinto en el tar
        (self.tmp / "evil.tar").write_bytes(bytes(raw))
        self.xz.unlink()
        run("xz", "-k", str(self.tmp / "evil.tar"))
        shutil.move(self.tmp / "evil.tar.xz", self.xz)
        ok, msg = self.verify()
        self.assertFalse(ok)
        self.assertIn("BADSIG", msg)

    def test_a_truncated_or_corrupt_xz_is_rejected(self):
        data = self.xz.read_bytes()
        for label, blob in (("truncado", data[:len(data) // 2]), ("basura", b"no es xz" * 100), ("vacío", b"")):
            with self.subTest(label):
                self.xz.write_bytes(blob)
                self.assertFalse(self.verify()[0])
        self.xz.write_bytes(data)

    def test_a_tampered_or_garbage_signature_is_rejected(self):
        good = self.sig.read_bytes()
        raw = bytearray(good)
        raw[-5] ^= 0x01
        for label, blob in (("un bit distinto", bytes(raw)), ("vacía", b""), ("basura", b"basura" * 50), ("truncada", good[:20])):
            with self.subTest(label):
                self.sig.write_bytes(blob)
                self.assertFalse(self.verify()[0])
        self.assertFalse(self.m.verify(self.xz, self.tmp / "no-existe.sign", self.home, self.pinned)[0])

    def test_a_signature_over_the_compressed_file_does_not_count(self):
        self.sign_with("greg", self.xz, self.sig)               # firma del .xz, no del tar: no es el esquema de kernel.org
        self.assertFalse(self.verify()[0])

    def test_a_signature_for_a_different_tarball_is_rejected(self):
        other = self.tmp / "otro.tar"
        other.write_bytes(b"otro contenido")
        self.sign_with("greg", other, self.sig)
        self.assertFalse(self.verify()[0])

    def test_without_the_public_key_it_fails_instead_of_trusting(self):
        empty = self.tmp / "vacio"
        empty.mkdir(mode=0o700)
        ok, msg = self.m.verify(self.xz, self.sig, empty, self.pinned)
        self.assertFalse(ok)
        self.assertTrue("NO_PUBKEY" in msg or "no válida" in msg, msg)

    # ── firmantes que no están pineados ─────────────────────────────────────────────────────────────────
    def test_a_valid_signature_by_a_key_that_is_not_pinned_is_rejected_but_names_the_signer(self):
        self.import_key("other")
        self.sign_with("other", self.tar, self.sig)
        ok, msg = self.verify()
        self.assertFalse(ok)
        self.assertIn(self.keys["other"][1], msg)
        self.assertIn("pineada", msg)

    def test_allow_unpinned_signer_accepts_it_with_a_warning_but_never_a_bad_signature(self):
        self.import_key("other")
        self.sign_with("other", self.tar, self.sig)
        ok, msg = self.verify(allow_unpinned=True)
        self.assertTrue(ok)
        self.assertTrue(msg.startswith("AVISO"), msg)
        raw = bytearray(self.sig.read_bytes())
        raw[-5] ^= 0x01
        self.sig.write_bytes(bytes(raw))
        self.assertFalse(self.verify(allow_unpinned=True)[0], "el modo warn no perdona una firma MALA")

    def test_a_key_that_has_expired_since_signing_is_rejected_even_if_it_is_pinned(self):
        """gpg no firma con una clave caducada, así que se firma «en el pasado» (la clave valía 30 días desde 2020-01-01)."""
        self.import_key("expired")
        self.sign_with("expired", self.tar, self.sig, faked_time="20200110T000000")
        self.pinned = {self.keys["expired"][1]: "caducada"}
        ok, msg = self.verify()
        self.assertFalse(ok, msg)
        self.assertIn("EXPKEYSIG", msg)

    # ── gpg o xz que se portan raro: el verificador tiene que fallar CERRADO ─────────────────────────────
    def with_fake(self, name, script):
        bindir = self.tmp / "fakebin"
        bindir.mkdir(exist_ok=True)
        f = bindir / name
        f.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        f.chmod(0o755)
        return mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"})

    def test_a_gpg_that_exits_zero_without_saying_good_signature_is_not_accepted(self):
        with self.with_fake("gpg", "cat > /dev/null\nexit 0\n"):
            ok, msg = self.verify()
        self.assertFalse(ok, "rc=0 sin GOODSIG/VALIDSIG no prueba nada")

    def test_a_gpg_that_fails_without_any_status_line_is_not_accepted(self):
        with self.with_fake("gpg", "cat > /dev/null\necho 'gpg: algo raro' >&2\nexit 2\n"):
            self.assertFalse(self.verify()[0])

    def test_goodsig_without_validsig_or_validsig_without_goodsig_is_not_accepted(self):
        fpr = self.keys["greg"][1]
        for label, lines in (("solo GOODSIG", "[GNUPG:] GOODSIG AAAA greg"), ("solo VALIDSIG", f"[GNUPG:] VALIDSIG {fpr} 2026-01-01 1 0 4 0 22 10 00 {fpr}")):
            with self.subTest(label), self.with_fake("gpg", f"cat > /dev/null\necho '{lines}'\nexit 0\n"):
                self.assertFalse(self.verify()[0])

    def test_a_bad_status_line_wins_even_if_gpg_exits_zero_and_even_in_warn_mode(self):
        fpr = self.keys["greg"][1]
        script = f"cat > /dev/null\necho '[GNUPG:] GOODSIG AAAA greg'\necho '[GNUPG:] VALIDSIG {fpr} 2026-01-01 1 0 4 0 22 10 00 {fpr}'\necho '[GNUPG:] REVKEYSIG AAAA greg'\nexit 0\n"
        for kw in ({}, {"allow_unpinned": True}):
            with self.subTest(kw=kw), self.with_fake("gpg", script):
                ok, msg = self.verify(**kw)
                self.assertFalse(ok)
                self.assertIn("REVKEYSIG", msg)

    def test_an_xz_that_streams_the_right_bytes_but_exits_with_an_error_is_not_accepted(self):
        real_xz = shutil.which("xz")
        with self.with_fake("xz", f'{real_xz} "$@"\nexit 1\n'):
            ok, msg = self.verify()
        self.assertFalse(ok, msg)
        self.assertIn("xz", msg)

    def test_a_missing_gpg_or_xz_binary_is_a_clear_rejection_not_a_traceback_and_not_a_pass(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "no-hay-nada")}):
            ok, msg = self.verify()
        self.assertFalse(ok)
        self.assertIn("no se pudo ejecutar", msg)
        only_xz = self.tmp / "solo-xz"
        only_xz.mkdir()
        (only_xz / "xz").symlink_to(shutil.which("xz"))
        with mock.patch.dict(os.environ, {"PATH": str(only_xz)}):
            ok, msg = self.verify()
        self.assertFalse(ok)
        self.assertIn("gpg", msg)

    # ── parseo de estados de gpg ────────────────────────────────────────────────────────────────────────
    def test_status_parser(self):
        P = self.m.parse_status
        primary, sub = "A" * 40, "B" * 40
        validsig = f"[GNUPG:] VALIDSIG {sub} 2026-11-13 1763000000 0 4 0 22 10 00 {primary}"
        info = P(f"[GNUPG:] GOODSIG 1234 x\n{validsig}\n")
        self.assertTrue(info["good"])
        self.assertEqual(info["validsig"], [{sub, primary}], "se aceptan la huella de la subclave y la de la clave primaria")
        for bad in ("BADSIG", "ERRSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY", "KEYEXPIRED", "NODATA"):
            with self.subTest(bad=bad):
                self.assertTrue(P(f"[GNUPG:] GOODSIG 1 x\n{validsig}\n[GNUPG:] {bad} 1234 x\n")["bad"])
        self.assertEqual(P("texto suelto\nGOODSIG\n[GNUPG:]\n[GNUPG:] VALIDSIG\n"), {"good": False, "validsig": [], "bad": []})

    def test_keyring_fingerprints_only_lists_primary_keys(self):
        self.assertEqual(self.m.keyring_fingerprints(self.home), {self.keys["greg"][1].upper()})

    # ── importación de claves ───────────────────────────────────────────────────────────────────────────
    def test_unpinned_keys_that_arrive_are_deleted_and_failing_sources_fall_through(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir(mode=0o700)
        self.addCleanup(lambda: subprocess.run(["gpgconf", "--homedir", str(fresh), "--kill", "all"], capture_output=True))
        calls = []

        def broken(home, fprs):
            calls.append("roto")
            raise RuntimeError("sin red")

        def serves_both(home, fprs):
            calls.append("sirve")
            for n in ("greg", "other"):
                subprocess.run(["gpg", "--homedir", str(home), "--batch", "--import"], input=self.keys[n][2], capture_output=True, check=True)

        def never_called(home, fprs):
            calls.append("sobra")

        notes = self.m.import_pinned_keys(fresh, self.pinned, sources=[("roto", broken), ("bueno", serves_both), ("sobra", never_called)])
        self.assertEqual(calls, ["roto", "sirve"], "para de buscar en cuanto tiene todas las claves pineadas")
        self.assertEqual(self.m.keyring_fingerprints(fresh), {self.keys["greg"][1]}, "la clave no pineada se descarta")
        self.assertTrue(any("falló" in n for n in notes) and any("descartada" in n for n in notes), notes)

    # ── descarga ────────────────────────────────────────────────────────────────────────────────────────
    def test_downloads_are_https_only_bounded_and_clean_up(self):
        dest = self.tmp / "d.bin"
        for url in ("http://cdn.kernel.org/x", "file:///etc/passwd", "ftp://x/y", "", None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.m.download(url, dest, 1000)

        class Resp:
            status = 200

            def __init__(self, n):
                self.left = n

            def read(self, k):
                k = min(k, self.left)
                self.left -= k
                return b"x" * k

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(self.m._OPENER, "open", return_value=Resp(5000)), self.assertRaises(ValueError):
            self.m.download("https://x/y", dest, 1000)
        self.assertFalse(dest.exists(), "un tarball a medias no puede quedar en disco")
        with mock.patch.object(self.m._OPENER, "open", return_value=Resp(500)):
            self.m.download("https://x/y", dest, 1000)
        self.assertEqual(dest.stat().st_size, 500)
        handler = self.m._SoloHttpsRedirect()
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(urllib.request.Request("https://cdn.kernel.org/a"), io.BytesIO(), 302, "x", {}, "http://evil/a")

    # ── la CLI completa, con descarga y claves simuladas ────────────────────────────────────────────────
    def run_main(self, version="9.9.9", extra=(), serve=None, with_keys=True):
        served = serve or {f"linux-{version}.tar.xz": self.xz, f"linux-{version}.tar.sign": self.sig}
        dest = self.tmp / "pkgbuild"
        dest.mkdir(exist_ok=True)

        def fake_download(url, to, limit, timeout=60):
            name = url.rsplit("/", 1)[-1]
            if name not in served:
                raise OSError("HTTP 404")
            shutil.copyfile(served[name], to)

        def fetch_greg(home, fprs):
            subprocess.run(["gpg", "--homedir", str(home), "--batch", "--import"], input=self.keys["greg"][2], capture_output=True, check=True)

        sources = [("prueba", fetch_greg)] if with_keys else []
        with mock.patch.object(self.m, "download", side_effect=fake_download), mock.patch.object(self.m, "PINNED", self.pinned):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = self.m.main(["--version", version, "--dest", str(dest), *extra], key_sources=sources)
        return rc, out.getvalue(), dest

    def test_cli_leaves_the_verified_tarball_where_makepkg_will_find_it(self):
        rc, out, dest = self.run_main()
        self.assertEqual(rc, 0, out)
        placed = dest / "linux-9.9.9.tar.xz"
        self.assertEqual(placed.read_bytes(), self.xz.read_bytes())
        self.assertEqual([p.name for p in dest.iterdir()], ["linux-9.9.9.tar.xz"], "sin restos .part")
        self.assertIn("sha256", out)

    def test_cli_leaves_nothing_behind_when_verification_fails(self):
        bad = self.tmp / "bad.sign"
        bad.write_bytes(b"basura")
        rc, out, dest = self.run_main(serve={"linux-9.9.9.tar.xz": self.xz, "linux-9.9.9.tar.sign": bad})
        self.assertEqual(rc, 1)
        self.assertEqual(list(dest.iterdir()), [])
        self.assertIn("::error::", out)

    def test_cli_failures_to_download_or_to_get_keys_are_failures(self):
        self.assertEqual(self.run_main(serve={"linux-9.9.9.tar.xz": self.xz})[0], 1)          # sin .sign
        self.assertEqual(self.run_main(serve={"linux-9.9.9.tar.sign": self.sig})[0], 1)       # sin tarball
        rc, out, dest = self.run_main(with_keys=False)                                         # ninguna fuente de claves
        self.assertEqual(rc, 1)
        self.assertEqual(list(dest.iterdir()), [])

    def test_cli_rejects_hostile_versions_and_bad_destinations(self):
        for version in ("9.9.9; id", "../9.9", "9", "9.9.9.9", "", "$(id)", "9.9\n", "٩.٩"):
            with self.subTest(version=version):
                rc = self.m.main(["--version", version, "--dest", str(self.tmp)])
                self.assertEqual(rc, 2)
        self.assertEqual(self.m.main(["--version", "9.9.9", "--dest", str(self.tmp / "no-existe")]), 2)

    def test_the_urls_it_builds_are_kernel_org_per_major_series(self):
        seen = []

        def fake_download(url, to, limit, timeout=60):
            seen.append(url)
            raise OSError("stop")

        with mock.patch.object(self.m, "download", side_effect=fake_download), mock.patch("sys.stdout", io.StringIO()):
            self.m.main(["--version", "7.2.14", "--dest", str(self.tmp)])
        self.assertEqual(seen[0], "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.14.tar.sign")

    def test_the_pinned_fingerprints_are_the_ones_confirmed_from_archs_pkgbuild(self):
        self.assertEqual(set(self.m.PINNED), {"ABAF11C65A2970B130ABE3C479BE3E4300411886", "647F28654894E3BD457199BE38DBBDC86092693E"})
        for fpr in self.m.PINNED:
            self.assertRegex(fpr, r"^[0-9A-F]{40}$")


WORKFLOW = ROOT / ".github" / "workflows" / "build-kernel.yml"
VERIFY_STEP = "Verificar la firma PGP del tarball del kernel"


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class WorkflowWiring(unittest.TestCase):
    """Cada job que corre makepkg verifica el tarball ANTES (si no, el kernel firmado de AvalOS vuelve a compilarse con lo
    que entregue una CDN de terceros) y el modo warn solo se activa con el valor exacto «warn»."""

    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def names(self, job):
        return [st.get("name") for st in self.doc["jobs"][job]["steps"]]

    def step(self, job, name):
        return next(st for st in self.doc["jobs"][job]["steps"] if st.get("name") == name)

    def test_every_makepkg_job_verifies_the_tarball_after_the_artifact_and_before_compiling(self):
        compile_steps = {"build-standard": "Compilar linux-avalos", "build-bore": "Compilar linux-avalos-bore",
                         "build-compat": "Compilar linux-avalos-compat (x86-64-v2)"}
        for job, compile_name in compile_steps.items():
            with self.subTest(job=job):
                names = self.names(job)
                checkout = next(n for n in names if n.startswith("Checkout parcial"))
                order = [names.index(checkout), names.index("Descargar PKGBUILD preparado"), names.index("Crear usuario builder"),
                         names.index(VERIFY_STEP), names.index(compile_name)]
                self.assertEqual(order, sorted(order), f"{job}: orden de pasos incorrecto: {names}")
                sparse = self.step(job, checkout)["with"]["sparse-checkout"]
                self.assertTrue("scripts/verify-kernel-tarball.py" in sparse, f"{job}: el checkout parcial no trae el verificador")
                run = self.step(job, VERIFY_STEP)["run"]
                self.assertTrue("scripts/verify-kernel-tarball.py" in run and '--version "$KERNEL_VER"' in run)
                self.assertTrue('--dest "${{ env.PKGBUILD_DIR }}"' in run, "el tarball verificado tiene que quedar donde makepkg lo busca")
                env = self.step(job, VERIFY_STEP)["env"]
                self.assertEqual(env["KERNEL_VER"], "${{ needs.check-version.outputs.kernel_ver }}")
                self.assertTrue("${{" not in run.replace('${{ env.PKGBUILD_DIR }}', ""), "nada se interpola en el script salvo la ruta fija")

    def test_only_the_three_kernel_jobs_download_a_tarball_and_the_firmware_metapackage_has_no_sources(self):
        """build-firmware compila un metapaquete sin `source=` (solo dependencias de Arch): no hay nada que verificar ahí."""
        firmware = (ROOT / "pkgs/linux-avalos-firmware/PKGBUILD").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^source=", firmware, re.M), "si el firmware gana fuentes, hay que verificarlas también")
        for job in self.doc["jobs"]:
            has_step = VERIFY_STEP in self.names(job)
            self.assertEqual(has_step, job in ("build-standard", "build-bore", "build-compat"), f"{job}")

    def run_step(self, mode):
        """Ejecuta de verdad el script del paso con un verificador falso que registra sus argumentos."""
        run = self.step("build-standard", VERIFY_STEP)["run"].replace("${{ env.PKGBUILD_DIR }}", "pkgs/linux-avalos")
        work = Path(tempfile.mkdtemp(prefix="avalos-vkt-wf-"))
        self.addCleanup(shutil.rmtree, work, True)
        (work / "scripts").mkdir()
        (work / "scripts" / "verify-kernel-tarball.py").write_text("import json, sys\nopen('args.json', 'w').write(json.dumps(sys.argv[1:]))\n")
        env = {**os.environ, "KERNEL_VER": "7.2.14"}
        if mode is not None:
            env["PGP_MODE"] = mode
        r = subprocess.run(["bash", "-e", "-c", run], cwd=work, env=env, capture_output=True, text=True, timeout=30)
        args = __import__("json").loads((work / "args.json").read_text()) if (work / "args.json").exists() else None
        return r, args, work

    def test_enforce_is_the_default_and_warn_needs_the_exact_value(self):
        for mode in (None, "", "enforce", "WARN", "warn ", " warn", "warn; touch pwned", "$(touch pwned)", "warning", "true", "1"):
            with self.subTest(mode=mode):
                r, args, work = self.run_step(mode)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(args, ["--version", "7.2.14", "--dest", "pkgs/linux-avalos"])
                self.assertFalse((work / "pwned").exists(), "el valor de la variable no se ejecuta")
        r, args, _ = self.run_step("warn")
        self.assertEqual(args, ["--version", "7.2.14", "--dest", "pkgs/linux-avalos", "--allow-unpinned-signer"])

    def test_a_failing_verifier_stops_the_job(self):
        run = self.step("build-standard", VERIFY_STEP)["run"].replace("${{ env.PKGBUILD_DIR }}", "x")
        work = Path(tempfile.mkdtemp(prefix="avalos-vkt-wf-"))
        self.addCleanup(shutil.rmtree, work, True)
        (work / "scripts").mkdir()
        (work / "scripts" / "verify-kernel-tarball.py").write_text("import sys\nsys.exit(1)\n")
        r = subprocess.run(["bash", "-e", "-c", run], cwd=work, env={**os.environ, "KERNEL_VER": "7.2.14"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
