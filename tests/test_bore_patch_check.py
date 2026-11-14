"""scripts/check-bore-patch.py — el filtro que decide si el parche BORE (de un repositorio AJENO, bajado de una rama
mutable) se aplica al kernel que AvalOS firma. Se prueba con parches sintéticos: nada de red, nada del repo de CachyOS.
"""
import contextlib
import hashlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-bore-patch.py"
PIN_FILE = ROOT / "pkgs" / "linux-avalos" / "bore.pin"
WORKFLOW = ROOT / ".github" / "workflows" / "build-kernel.yml"


def load():
    spec = importlib.util.spec_from_file_location("check_bore_patch_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def diff(path, added=("int x;",), removed=(), new_file=True, a=None):
    a = a or path
    head = f"diff --git a/{a} b/{path}\n"
    if new_file:
        head += "new file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
    else:
        head += f"index 1111111..2222222 100644\n--- a/{a}\n"
    body = "".join(f"-{l}\n" for l in removed) + "".join(f"+{l}\n" for l in added)
    return head + f"+++ b/{path}\n@@ -1,{len(removed)} +1,{len(added)} @@\n" + body


GOOD_FILES = ["include/linux/sched.h", "include/linux/sched/bore.h", "init/Kconfig", "kernel/Kconfig.hz", "kernel/exit.c",
              "kernel/fork.c", "kernel/futex/waitwake.c", "kernel/sched/Makefile", "kernel/sched/bore.c", "kernel/sched/core.c",
              "kernel/sched/debug.c", "kernel/sched/fair.c", "kernel/sched/sched.h"]


def good_patch():
    return "From 1111 Mon Sep 17 00:00:00 2001\nSubject: [PATCH] bore\n---\n" + "".join(
        diff(f, added=("static int burst_score;", "register_sysctl_init(\"kernel\", sched_bore_sysctls);",
                       "debugfs_create_file(\"min_base_slice_ns\", 0644, d, NULL, &fops);"), new_file=False) for f in GOOD_FILES)


class Check(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.tmp = Path(tempfile.mkdtemp(prefix="avalos-bore-test-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))

    def patch_file(self, text, name="bore.patch"):
        p = self.tmp / name
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return p

    def pin_file(self, text):
        p = self.tmp / "bore.pin"
        p.write_text(text, encoding="utf-8")
        return p

    def run_check(self, patch_text, pin="", version="7.2", summary=None):
        args = [str(self.patch_file(patch_text)), "--version", version, "--pin", str(self.pin_file(pin))]
        if summary:
            args += ["--summary", str(summary)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.m.main(args)
        return rc, out.getvalue() + err.getvalue()

    def sha(self, text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ── alcance ──────────────────────────────────────────────────────────────────────────────────────────
    def test_a_normal_scheduler_patch_passes_including_sysctl_and_debugfs_knobs(self):
        rc, out = self.run_check(good_patch())
        self.assertEqual(rc, 0, out)

    def test_files_outside_the_scheduler_are_rejected(self):
        for path in ("fs/ext4/inode.c", "drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c", "security/selinux/hooks.c", "net/core/dev.c",
                     "arch/x86/entry/syscalls/syscall_64.tbl", "crypto/sha256_generic.c", "kernel/cred.c", "kernel/capability.c",
                     "kernel/module/main.c", "Makefile", "scripts/Makefile.build", "kernel/sched", "include/linux/cred.h",
                     "kernel/sched/../cred.c", "init/main.c", "mm/mmap.c", ".github/workflows/x.yml"):
            with self.subTest(path=path):
                rc, out = self.run_check(good_patch() + diff(path))
                self.assertEqual(rc, 1, out)
                self.assertIn(path, out)

    def test_suspicious_paths_are_rejected(self):
        for path in ("/etc/passwd", "../../etc/passwd", "kernel/sched/../../fs/x.c", "kernel\\sched\\x.c"):
            with self.subTest(path=path):
                self.assertEqual(self.run_check(good_patch() + diff(path))[0], 1)

    def test_renames_copies_deletions_and_mode_changes_are_rejected(self):
        for extra in ("rename from kernel/sched/a.c\nrename to kernel/sched/b.c\n", "copy from kernel/sched/a.c\ncopy to kernel/sched/b.c\n",
                      "old mode 100644\nnew mode 100755\n", "deleted file mode 100644\n", "similarity index 90%\n"):
            with self.subTest(extra=extra.splitlines()[0]):
                self.assertEqual(self.run_check(good_patch() + "diff --git a/kernel/sched/x.c b/kernel/sched/x.c\n" + extra)[0], 1)
        self.assertEqual(self.run_check(good_patch() + diff("kernel/sched/y.c", a="kernel/sched/x.c"))[0], 1)

    def test_binary_empty_garbage_and_nul_bytes_are_rejected(self):
        for text in (b"", b"no es un parche", good_patch() + "GIT binary patch\nliteral 5\n", good_patch() + "Binary files a/x and b/x differ\n",
                     good_patch().encode() + b"\x00\x01", b"\xff\xfe\xfd", "diff --git sin forma"):
            with self.subTest(text=str(text)[:30]):
                self.assertEqual(self.run_check(text)[0], 1)

    def test_size_and_line_budgets(self):
        big = diff("kernel/sched/core.c", added=[f"int v{i};" for i in range(self.m.MAX_ADDED + 1)])
        self.assertEqual(self.run_check(big)[0], 1)
        many_removed = diff("kernel/sched/core.c", added=("x",), removed=[f"int v{i};" for i in range(self.m.MAX_REMOVED + 1)], new_file=False)
        self.assertEqual(self.run_check(many_removed)[0], 1)
        huge = diff("kernel/sched/core.c", added=["/* " + "x" * 200 + " */"] * 900)
        self.assertGreater(len(huge), self.m.MAX_BYTES)
        self.assertEqual(self.run_check(huge)[0], 1)
        many_files = "".join(diff(f"kernel/sched/f{i}.c") for i in range(self.m.MAX_FILES + 1))
        self.assertEqual(self.run_check(many_files)[0], 1)

    # ── patrones ─────────────────────────────────────────────────────────────────────────────────────────
    def test_suspicious_added_lines_are_rejected_anywhere_in_the_patch(self):
        bad_lines = ["commit_creds(prepare_kernel_cred(NULL));", "override_creds(x);", "if (capable(CAP_SYS_ADMIN)) grant();", "call_usermodehelper(path, argv, envp, UMH_WAIT_EXEC);",
                     "request_module(\"x\");", "SYSCALL_DEFINE1(evil, int, x)", "kallsyms_lookup_name(\"sys_call_table\");", "register_kprobe(&kp);",
                     "text_poke(addr, code, 5);", "asm volatile(\"wrmsr\");", "set_memory_rw(addr, 1);", "current->cred->uid = GLOBAL_ROOT_UID;" if False else "ksys_setuid(0);",
                     "filp_open(\"/etc/shadow\", O_RDONLY, 0);", "kernel_write(f, buf, n, &pos);", "cap_raise(new->cap_effective, CAP_SYS_ADMIN);"]
        for line in bad_lines:
            with self.subTest(line=line):
                rc, out = self.run_check(good_patch() + diff("kernel/sched/core.c", added=("int ok;", line, "int ok2;"), new_file=False))
                self.assertEqual(rc, 1, out)

    def test_a_suspicious_line_that_starts_with_plus_plus_is_still_inspected(self):
        """«+++» al inicio de una línea añadida es contenido (++payload();), no una cabecera de archivo."""
        # contenido «++commit_creds(x);» → línea del diff «+++commit_creds(x);» (empieza con tres «+»)
        text = good_patch() + diff("kernel/sched/core.c", added=("++commit_creds(x);",), new_file=False)
        self.assertIn("+++commit_creds", text)
        self.assertEqual(self.run_check(text)[0], 1)
        # y lo mismo para el contador de líneas quitadas: «--x;» → «---x;» cuenta como línea quitada, no como cabecera
        many = diff("kernel/sched/core.c", added=("int ok;",), removed=[f"--v{i};" for i in range(self.m.MAX_REMOVED + 1)], new_file=False)
        self.assertIn("\n---v0;", many)
        self.assertEqual(self.run_check(many)[0], 1)

    def test_suspicious_words_in_removed_or_context_lines_are_fine(self):
        text = good_patch() + diff("kernel/sched/core.c", added=("int ok;",), removed=("commit_creds(x);",), new_file=False)
        text += " context line with capable(CAP_X)\n"
        self.assertEqual(self.run_check(text)[0], 0)

    # ── pin de revisión humana ───────────────────────────────────────────────────────────────────────────
    def test_warn_mode_applies_an_unreviewed_patch_but_says_so_and_prints_the_pin_line(self):
        rc, out = self.run_check(good_patch(), pin="mode=warn\n")
        self.assertEqual(rc, 0)
        self.assertIn("::warning::", out)
        self.assertIn(self.sha(good_patch()), out)
        self.assertIn("bore.pin", out)

    def test_enforce_mode_refuses_a_patch_that_does_not_match_the_pin(self):
        other = "7.2 " + "a" * 64 + " " + "b" * 40
        rc, out = self.run_check(good_patch(), pin=f"mode=enforce\n{other}\n")
        self.assertEqual(rc, 1)
        self.assertIn("::error::", out)
        rc, out = self.run_check(good_patch(), pin="mode=enforce\n")                         # sin entrada para esta versión
        self.assertEqual(rc, 1)

    def test_a_matching_pin_is_ok_in_both_modes(self):
        entry = f"7.2 {self.sha(good_patch())} {'c' * 40}"
        for mode in ("warn", "enforce"):
            with self.subTest(mode=mode):
                rc, out = self.run_check(good_patch(), pin=f"mode={mode}\n{entry}\n")
                self.assertEqual(rc, 0, out)
                self.assertIn("OK (coincide con el pin revisado)", out)
                self.assertNotIn("::warning::", out)

    def test_a_pin_for_another_version_does_not_apply(self):
        entry = f"7.1 {self.sha(good_patch())} {'c' * 40}"
        self.assertEqual(self.run_check(good_patch(), pin=f"mode=enforce\n{entry}\n", version="7.2")[0], 1)

    def test_scope_violations_are_rejected_even_when_the_hash_is_pinned(self):
        evil = good_patch() + diff("fs/ext4/inode.c")
        entry = f"7.2 {self.sha(evil)} {'c' * 40}"
        self.assertEqual(self.run_check(evil, pin=f"mode=warn\n{entry}\n")[0], 1)

    def test_an_unknown_mode_is_treated_as_enforce_not_silently_as_warn(self):
        for mode in ("enforced", "ENFORCE", "strict", "", "true"):
            with self.subTest(mode=mode):
                rc, out = self.run_check(good_patch(), pin=f"mode={mode}\n")
                self.assertEqual(rc, 1, out)
                self.assertIn("no existe", out)

    def test_missing_or_garbage_pin_files_behave_like_warn_with_no_entries(self):
        p = self.patch_file(good_patch())
        for pin_arg in (["--pin", str(self.tmp / "no-existe.pin")], []):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.m.main([str(p), "--version", "7.2", *pin_arg]), 0)
        garbage = self.pin_file("\x00\xff basura\n7.2 xyz abc\n7.2 " + "g" * 64 + " " + "b" * 40 + "\n7.x " + "a" * 64 + " " + "b" * 40 + "\n#7.2 " + "a" * 64 + " " + "b" * 40 + "\n")
        pin = self.m.load_pin(str(garbage))
        self.assertEqual((pin.mode, pin.entries), ("warn", {}))
        (self.tmp / "bin.pin").write_bytes(b"\xff\xfe\x00")
        self.assertEqual(self.m.load_pin(str(self.tmp / "bin.pin")).entries, {})

    def test_print_ref_uses_the_pinned_commit_only_when_it_is_enforced(self):
        entry = f"7.2 {'a' * 64} {'c' * 40}"
        cases = [("mode=warn\n" + entry, "7.2", "master"), ("mode=enforce\n" + entry, "7.2", "c" * 40),
                 ("mode=enforce\n" + entry, "7.3", "master"), ("", "7.2", "master")]
        for pin, version, expected in cases:
            with self.subTest(pin=pin[:12], version=version):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(self.m.main(["--print-ref", "--version", version, "--pin", str(self.pin_file(pin))]), 0)
                self.assertEqual(out.getvalue().strip(), expected)

    # ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────
    def test_hostile_versions_are_refused_before_anything_is_read(self):
        for version in ("7.2; id", "7", "7.2.1", "../7.2", "$(id)", "", "7.x", "7.2\n"):
            with self.subTest(version=version), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.m.main(["--print-ref", "--version", version]), 2)

    def test_the_summary_is_appended_and_an_unwritable_summary_is_only_a_warning(self):
        summary = self.tmp / "summary.md"
        summary.write_text("previo\n")
        rc, _ = self.run_check(good_patch(), summary=summary)
        self.assertEqual(rc, 0)
        text = summary.read_text()
        self.assertTrue(text.startswith("previo\n"))
        self.assertIn("### Parche BORE 7.2", text)
        rc, out = self.run_check(good_patch(), summary=self.tmp / "no" / "existe" / "summary.md")
        self.assertEqual(rc, 0)
        self.assertIn("no se pudo escribir el resumen", out)

    def test_an_unreadable_patch_file_is_a_clean_rejection(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.m.main([str(self.tmp / "no-existe.patch"), "--version", "7.2"]), 1)
        self.assertIn("no se pudo leer", out.getvalue())


class Wiring(unittest.TestCase):
    def test_the_committed_pin_is_well_formed_and_covers_the_kernel_series_in_the_pkgbuild(self):
        m = load()
        pin = m.load_pin(str(PIN_FILE))
        self.assertIn(pin.mode, ("warn", "enforce"))
        pkgver = re.search(r"^pkgver=(\d+)\.(\d+)", (ROOT / "pkgs/linux-avalos/PKGBUILD").read_text(encoding="utf-8"), re.M)
        series = f"{pkgver[1]}.{pkgver[2]}"
        self.assertIn(series, pin.entries, f"bore.pin no tiene entrada para la serie del PKGBUILD ({series})")
        sha, commit = pin.entries[series]
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertRegex(commit, r"^[0-9a-f]{40}$")

    def test_the_workflow_runs_the_checker_and_no_longer_downloads_from_a_mutable_branch_unchecked(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        # assertTrue y no assertIn: si falla, assertIn volcaría el workflow entero
        self.assertTrue("scripts/check-bore-patch.py" in text and "--print-ref" in text, "el workflow no llama al verificador")
        self.assertNotRegex(text, r"kernel-patches/master/\$\{MAJOR\}")
        self.assertRegex(text, r"kernel-patches/\$\{BORE_REF\}/\$\{MAJOR\}\.\$\{MINOR\}/sched/0001-bore\.patch")
        # la condición del «if» que aplica el parche incluye al verificador: si lo rechaza se cae a la rama «sin BORE»
        cond = text[text.index("if curl -fsSL --max-time 60 --max-filesize"):text.index("; then", text.index("if curl -fsSL --max-time 60"))]
        self.assertTrue("check-bore-patch.py" in cond and cond.count("&&") >= 2, "el verificador no forma parte de la condición del if")
        # el checkout parcial va ANTES de bajar el artifact (actions/checkout limpia el workspace) y trae el script y el pin
        job = text[text.index("  build-bore:"):text.index("  build-compat:")]
        self.assertLess(job.index("Checkout parcial"), job.index("Descargar PKGBUILD preparado"))
        self.assertTrue("scripts/check-bore-patch.py" in job and "pkgs/linux-avalos/bore.pin" in job)

    def test_the_script_is_executable_and_runs_standalone(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--print-ref", "--version", "7.2", "--pin", str(PIN_FILE)], capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "master" if "mode=warn" in PIN_FILE.read_text() else r.stdout.strip()))


if __name__ == "__main__":
    unittest.main()
