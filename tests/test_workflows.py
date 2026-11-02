"""build-kernel.yml: el paso «Limpiar paquetes anteriores del release» se ejecuta de verdad.

El paso comparaba los assets del release contra los paquetes de /tmp/avalos-repo y borraba lo que
no figuraba ahí. Con esa carpeta vacía (o inexistente) NADA figuraba, así que borraba TODOS los
.pkg.tar.zst del release (comprobado ejecutándolo con un `gh` falso). Ahora sale sin tocar nada.

Un script de CI que borra cosas se prueba corriéndolo: se extrae el `run:` del YAML, se resuelven
las expresiones de GitHub a valores fijos y se ejecuta con bash y un `gh` que solo anota lo que le
piden. Lo único que se cambia es la ruta /tmp/avalos-repo (por una carpeta temporal).
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:      # CI lo instala (python3-yaml); sin él estas pruebas se saltan
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "build-kernel.yml"
CLEANUP_STEP = "Limpiar paquetes anteriores del release"
COMPAT_STEP = "Compilar linux-avalos-compat (x86-64-v2)"
EXPRESSIONS = {"env.REPO_TAG": "kernel-repo", "env.AVALOS_REPO": "owner/avalos"}

FAKE_GH = """#!/bin/sh
echo "$@" >> "$GH_LOG"
case "$1 $2" in
  "release view")
    [ -n "$GH_FAIL_VIEW" ] && exit 1
    printf '%s\\n' "$GH_ASSETS" ;;
  *) exit 0 ;;
esac
"""


def load_step(name):
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == name:
                return step
    raise AssertionError(f"no hay un paso llamado {name!r} en {WORKFLOW.name}")


def resolve(script, repo_dir):
    def expr(m):
        return EXPRESSIONS[m.group(1).strip()]
    script = re.sub(r"\$\{\{\s*([\w.]+)\s*\}\}", expr, script)
    assert "${{" not in script
    return script.replace("/tmp/avalos-repo", repo_dir)


@unittest.skipUnless(yaml, "falta PyYAML")
class ReleaseCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avalos-wf-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "avalos-repo")
        os.makedirs(self.repo)
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        gh = os.path.join(bindir, "gh")
        Path(gh).write_text(FAKE_GH)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
        self.bindir, self.log = bindir, os.path.join(self.tmp, "gh.log")

    def run_step(self, remote_assets, local_files=(), view_fails=False):
        for name in local_files:
            Path(self.repo, name).write_text("x")
        script = resolve(load_step(CLEANUP_STEP)["run"], self.repo)
        env = {"PATH": self.bindir + os.pathsep + os.environ["PATH"], "GH_LOG": self.log,
               "GH_ASSETS": "\n".join(remote_assets), "GH_TOKEN": "x"}
        if view_fails:
            env["GH_FAIL_VIEW"] = "1"
        res = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True,
                             timeout=60)
        calls = Path(self.log).read_text().splitlines() if os.path.exists(self.log) else []
        deleted = sorted(c.split()[3] for c in calls if c.startswith("release delete-asset"))
        return res, deleted

    def test_an_empty_local_folder_deletes_nothing(self):
        remote = ["linux-avalos-7.2.11-1-x86_64.pkg.tar.zst", "linux-avalos-7.2.11-1-x86_64.pkg.tar.zst.sig"]
        res, deleted = self.run_step(remote)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(deleted, [])
        self.assertIn("no se elimina nada", res.stdout + res.stderr)

    def test_a_missing_local_folder_deletes_nothing_either(self):
        shutil.rmtree(self.repo)
        res, deleted = self.run_step(["linux-avalos-7.2.11-1-x86_64.pkg.tar.zst"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(deleted, [])

    def test_it_deletes_only_what_is_obsolete_including_orphan_signatures(self):
        current = ["linux-avalos-7.2.11-1-x86_64.pkg.tar.zst", "linux-avalos-7.2.11-1-x86_64.pkg.tar.zst.sig",
                   "avalos.db.tar.zst"]
        old = ["linux-avalos-7.2.9-1-x86_64.pkg.tar.zst", "linux-avalos-7.2.9-1-x86_64.pkg.tar.zst.sig",
               "linux-avalos-headers-7.2.5-1-x86_64.pkg.tar.zst.sig"]
        other = ["avalos.db.tar.zst", "avalos.files.tar.zst", "README.txt"]
        res, deleted = self.run_step(current[:2] + old + other, local_files=current)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(deleted, sorted(old))

    def test_a_failing_release_query_deletes_nothing(self):
        res, deleted = self.run_step([], local_files=["linux-avalos-7.2.11-1-x86_64.pkg.tar.zst"],
                                     view_fails=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(deleted, [])

    def test_names_are_compared_exactly_not_by_substring(self):
        """Un asset cuyo nombre es un trozo de uno vigente igual es obsoleto (grep -x, no -F a secas)."""
        current = "linux-avalos-7.2.11-1-x86_64.pkg.tar.zst"
        res, deleted = self.run_step([current, "avalos-7.2.11-1-x86_64.pkg.tar.zst"], local_files=[current])
        self.assertEqual(deleted, ["avalos-7.2.11-1-x86_64.pkg.tar.zst"])


@unittest.skipUnless(yaml, "falta PyYAML")
class ShellcheckFindings(unittest.TestCase):
    """Las 2 advertencias que dejó la auditoría de oct 2026 (actionlint + shellcheck)."""

    def test_the_compat_step_no_longer_assigns_a_variable_it_never_uses(self):
        script = load_step(COMPAT_STEP)["run"]
        self.assertNotIn("KERNEL_VER", script)

    def test_the_cleanup_step_lists_files_with_find_not_ls_into_xargs(self):
        script = load_step(CLEANUP_STEP)["run"]
        self.assertNotIn("xargs", script)
        self.assertIn("find /tmp/avalos-repo", script)


@unittest.skipUnless(yaml and shutil.which("shellcheck"), "falta PyYAML o shellcheck")
class ShellcheckOnTheCleanupStep(unittest.TestCase):
    def test_no_findings_at_warning_level(self):
        script = resolve(load_step(CLEANUP_STEP)["run"], "/tmp/avalos-repo")
        res = subprocess.run(["shellcheck", "-s", "bash", "-S", "warning", "-"], input=script,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
