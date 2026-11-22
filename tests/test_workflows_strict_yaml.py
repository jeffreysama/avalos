"""Los workflows se leen con YAML estricto: repetir una clave es un error, igual que para GitHub.

PyYAML acepta `env:` dos veces en el mismo paso (se queda con la última) y por eso las pruebas que usan
`yaml.safe_load` no lo notan. GitHub, en cambio, rechaza el archivo entero: el workflow «falla» en 0 s sin
ejecutar nada, en cada push, con «This run likely failed because of a workflow file issue». Le pasó a
build-kernel.yml en la rama de la auditoría (dos `env:` en el paso check_build) y solo lo cazó el CI de una
rama de prueba. Estas pruebas lo cazan antes de subir nada.
"""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:      # CI lo instala (python3-yaml); sin él estas pruebas se saltan, como las de test_workflows.py
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

STEP_WITH_TWO_ENVS = """\
jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - name: Revisar
        env:
          FORCE: "1"
        run: echo hola
        env:
          GH_TOKEN: x
"""

TWO_STEPS_EACH_WITH_ITS_ENV = """\
jobs:
  j:
    runs-on: ubuntu-24.04
    steps:
      - name: Uno
        env:
          A: "1"
        run: echo uno
      - name: Dos
        env:
          A: "2"
        run: echo dos
"""

if yaml is not None:
    class StrictLoader(yaml.SafeLoader):
        """SafeLoader que falla si un mapa repite una clave, como hace GitHub con un workflow."""

    def _mapping_without_duplicates(loader, node, deep=False):
        seen = {}
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            line = key_node.start_mark.line + 1
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"clave duplicada {key!r}: líneas {seen[key]} y {line}", key_node.start_mark)
            seen[key] = line
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)


def load_strict(text):
    return yaml.load(text, Loader=StrictLoader)


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class StrictLoaderCatchesTheRealFailure(unittest.TestCase):
    """El detector no es decorativo: ve el fallo de verdad y no se queja de lo que es válido."""

    def test_two_env_blocks_in_the_same_step_are_rejected(self):
        # safe_load lo acepta (por eso el fallo pasó desapercibido); el cargador estricto no
        env = yaml.safe_load(STEP_WITH_TWO_ENVS)["jobs"]["j"]["steps"][0]["env"]
        self.assertIn("GH_TOKEN", env)
        with self.assertRaisesRegex(yaml.YAMLError, "clave duplicada 'env'"):
            load_strict(STEP_WITH_TWO_ENVS)

    def test_the_same_key_in_different_steps_is_not_a_duplicate(self):
        steps = load_strict(TWO_STEPS_EACH_WITH_ITS_ENV)["jobs"]["j"]["steps"]
        self.assertEqual([s["env"]["A"] for s in steps], ["1", "2"])


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class EveryWorkflowIsStrictYaml(unittest.TestCase):
    def test_no_workflow_repeats_a_key(self):
        self.assertTrue(WORKFLOWS, "no se encontró ningún workflow en .github/workflows")
        for wf in WORKFLOWS:
            with self.subTest(workflow=wf.name):
                load_strict(wf.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
