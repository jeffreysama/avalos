"""Ejecuta de verdad (con bash) el trozo del paso «Compilar linux-avalos-bore» que descarga y aplica el parche BORE,
con un `curl` y un `chown` falsos: comprueba el cableado real entre el workflow, check-bore-patch.py y el PKGBUILD —
quoting, la cadena de `&&`, la rama «sin BORE», el ref que se pide según bore.pin — que las pruebas unitarias del
script no ven. No toca la red ni el sistema."""
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:      # CI lo instala (python3-yaml)
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "build-kernel.yml"
STEP = "Compilar linux-avalos-bore"


def bore_script():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    run = next(s["run"] for s in doc["jobs"]["build-bore"]["steps"] if s.get("name") == STEP)
    # lo que hay antes de lanzar makepkg (que aquí no corre); las expresiones ${{ }} se sustituyen por valores de prueba
    run = run[:run.index("sudo -u builder env")]
    subs = {"env.PKGBUILD_DIR": "pkgs/linux-avalos", "needs.check-version.outputs.kernel_ver": "7.2.14", "env.MARCH": "x86-64-v3"}
    return re.sub(r"\$\{\{\s*([\w.\-]+)\s*\}\}", lambda m: subs[m.group(1)], run)


def synthetic_patch(extra_file=None):
    def d(path):
        return (f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n--- a/{path}\n+++ b/{path}\n"
                f"@@ -1,1 +1,2 @@\n int a;\n+int burst_score;\n")
    body = "Subject: [PATCH] bore\n---\n" + "".join(d(p) for p in ("kernel/sched/core.c", "kernel/sched/fair.c", "init/Kconfig"))
    return body + (d(extra_file) if extra_file else "")


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class BoreStepShell(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="avalos-bore-wf-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        (self.work / "scripts").mkdir()
        shutil.copy(ROOT / "scripts" / "check-bore-patch.py", self.work / "scripts")
        pk = self.work / "pkgs" / "linux-avalos"
        pk.mkdir(parents=True)
        for f in ("PKGBUILD", "linux-avalos.install", "bore.pin"):
            shutil.copy(ROOT / "pkgs" / "linux-avalos" / f, pk)
        bindir = self.work / "bin"
        bindir.mkdir()
        self.curl_log = self.work / "curl.log"
        self.served = self.work / "served.patch"
        (bindir / "curl").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            # curl falso: registra los argumentos y sirve $SERVED (o falla si FAKE_CURL_FAIL=1)
            printf '%s\\n' "$*" >> {self.curl_log}
            [[ -n "$FAKE_CURL_FAIL" ]] && exit 22
            out=""; while [[ $# -gt 0 ]]; do [[ "$1" == "-o" ]] && out="$2"; shift; done
            cp {self.served} "$out"
            """))
        (bindir / "chown").write_text("#!/bin/bash\nexit 0\n")
        for f in bindir.iterdir():
            f.chmod(0o755)
        self.bindir = bindir
        (self.work / "summary.md").write_text("")

    def run_step(self, patch=None, curl_fail=False, pin_text=None):
        shutil.rmtree(self.work / "pkgs" / "linux-avalos-bore", ignore_errors=True)    # el paso hace `cp -r` a un destino que debe no existir
        if patch is not None:
            self.served.write_text(patch, encoding="utf-8")
        if pin_text is not None:
            (self.work / "pkgs/linux-avalos/bore.pin").write_text(pin_text, encoding="utf-8")
        env = {**os.environ, "PATH": f"{self.bindir}:{os.environ['PATH']}", "GITHUB_STEP_SUMMARY": str(self.work / "summary.md")}
        if curl_fail:
            env["FAKE_CURL_FAIL"] = "1"
        r = subprocess.run(["bash", "-e", "-c", bore_script()], cwd=self.work, env=env, capture_output=True, text=True, timeout=60)
        return r, (self.work / "pkgs/linux-avalos-bore")

    def pkgbuild(self, bore_dir):
        return (bore_dir / "PKGBUILD").read_text(encoding="utf-8")

    def test_a_scheduler_only_patch_is_applied_and_added_to_the_pkgbuild(self):
        r, bore = self.run_step(patch=synthetic_patch())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((bore / "bore-scheduler.patch").is_file())
        pkg = self.pkgbuild(bore)
        self.assertEqual(pkg.count('"bore-scheduler.patch"'), 1)
        self.assertRegex(pkg, r"sha256sums=\('SKIP' 'SKIP' 'SKIP'\)")
        self.assertTrue("EEVDF+BORE" in pkg and "SIN BORE" not in pkg)
        self.assertTrue("revisado" in r.stdout)

    def test_a_patch_that_touches_the_filesystem_layer_is_rejected_and_the_kernel_builds_without_bore(self):
        r, bore = self.run_step(patch=synthetic_patch(extra_file="fs/ext4/inode.c"))
        self.assertEqual(r.returncode, 0, "rechazar BORE no puede tumbar el build: sale el kernel sin BORE")
        self.assertFalse((bore / "bore-scheduler.patch").exists(), "el parche rechazado no puede quedar para que prepare() lo aplique")
        pkg = self.pkgbuild(bore)
        self.assertTrue("SIN BORE" in pkg)
        self.assertNotRegex(pkg, r'(?m)^\s*"bore-scheduler\.patch"', "el parche rechazado no puede figurar en source=()")
        self.assertTrue("::error::parche BORE rechazado" in r.stdout and "fs/ext4/inode.c" in r.stdout)
        self.assertTrue("::warning::linux-avalos-bore se compila SIN el parche BORE" in r.stdout)

    def test_a_download_failure_still_falls_back_to_a_bore_less_build(self):
        r, bore = self.run_step(patch=synthetic_patch(), curl_fail=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((bore / "bore-scheduler.patch").exists())
        self.assertTrue("SIN BORE" in self.pkgbuild(bore))

    def test_the_download_is_bounded_and_uses_the_ref_chosen_by_the_pin(self):
        self.run_step(patch=synthetic_patch(), pin_text="mode=warn\n")
        calls = self.curl_log.read_text()
        self.assertTrue("--max-time 60" in calls and "--max-filesize" in calls, calls)
        self.assertTrue("/CachyOS/kernel-patches/master/7.2/sched/0001-bore.patch" in calls, calls)
        self.curl_log.unlink()
        commit = "d" * 40
        r, _ = self.run_step(patch=synthetic_patch(), pin_text=f"mode=enforce\n7.2 {'e' * 64} {commit}\n")
        self.assertTrue(f"/CachyOS/kernel-patches/{commit}/7.2/sched/0001-bore.patch" in self.curl_log.read_text(), r.stdout)

    def test_enforce_with_a_non_matching_hash_builds_without_bore_and_says_why(self):
        r, bore = self.run_step(patch=synthetic_patch(), pin_text=f"mode=enforce\n7.2 {'e' * 64} {'d' * 40}\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((bore / "bore-scheduler.patch").exists())
        self.assertTrue("no coincide con bore.pin" in r.stdout)

    def test_the_job_summary_receives_the_review_block_for_the_maintainer(self):
        self.run_step(patch=synthetic_patch(), pin_text="mode=warn\n")
        summary = (self.work / "summary.md").read_text(encoding="utf-8")
        self.assertTrue("### Parche BORE 7.2" in summary and "sha256:" in summary and "bore.pin" in summary)


if __name__ == "__main__":
    unittest.main()
