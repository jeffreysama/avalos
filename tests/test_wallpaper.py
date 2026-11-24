"""avalos-wallpaper: inyección de nombres de archivo hostiles y de fallos del sistema.

El bug que fijan estas pruebas: apply() escribía la ruta del fondo TAL CUAL en hyprpaper.conf, y hyprlang interpreta
caracteres dentro de los valores. Verificado contra la librería real (hyprlang 0.6.8, commit b2aaa23, compilada a
mano el 2026-11-13 con un programa mínimo que parsea «path = …» y lo imprime):

    path = /a/Sunset #3.png      →  /a/Sunset            (el '#' abre un comentario)
    path = /a/doble ##x.png      →  /a/doble #x.png      ('##' es el escape de '#')
    path = /a/cuatro ####x.png   →  /a/cuatro ##         (hyprlang trunca aunque se escape: no hay forma fiable)
    path = /a/dolar $HOME.png    →  /a/dolar /root.png   ('$' expande variables y entorno)
    path = /a/llaves {{x}}.png   →  error de expresión   (la config entera se rechaza)
    (con un salto de línea)      →  «Invalid config line» (hyprpaper no arranca en el siguiente login)

El hyprctl en caliente enmascaraba el fallo (usaba la ruta real): el fondo parecía bien hasta cerrar sesión.
Ahora `path` apunta a un enlace simbólico fijo con nombre seguro. Estas pruebas usan un port a Python de
CConfig::parseLine (el de abajo coincide con la librería real en todos los casos de arriba salvo la expansión de
'$', que el port no modela — por eso además se exige que la ruta escrita NO contenga ningún especial). Si
AVALOS_HYPRLANG_PROBE apunta a un binario que imprima «PATH:<valor>» al parsear un archivo, las pruebas lo usan
además del port.
"""
import base64
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    from PIL import Image as PILImage
except ImportError:      # opcional: sin Pillow solo se saltan las pruebas que lo necesitan
    PILImage = None

ROOT = Path(__file__).resolve().parent.parent
TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")  # PNG válido de 1x1
SCRIPT = ROOT / "scripts" / "avalos-wallpaper"
PROBE = os.environ.get("AVALOS_HYPRLANG_PROBE")

HOSTILE_NAMES = ["normal.png", "Sunset #3.png", "doble ##x.png", "cuatro ####x.png", "dolar $HOME.png", "dolar ${HOME}x.png",
                 "llaves {{x}}.png", "una{llave.png", "otra}llave.png", "con\\barra.png", "dos\\\\barras.png", "esc\\{x.png",
                 "salto\nde linea.png", "retorno\rde carro.png", "tab\tx.png", "coma, uno.png", "ñandú 日本語.png",
                 "espacios  dobles.png", " empieza con espacio.png", "termina con espacio .png", "~tilde.png", "-guion.png",
                 "'comilla'.png", '"dobles".png', "punto.y.coma;.png", "pipe|.png", "amp&.png", "porciento%20.png"]


def load():
    home = tempfile.mkdtemp(prefix="avalos-wp-home-")
    # webview y HOME falsos SOLO mientras se carga el script (unittest discover corre todo en un mismo proceso)
    with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}), mock.patch.dict(os.environ, {"HOME": home}):
        loader = importlib.machinery.SourceFileLoader("avalos_wallpaper_under_test", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module, Path(home)


def parse_line(line):
    """Port de CConfig::parseLine (hyprlang b2aaa23) para «clave = valor» sin variables definidas por el usuario."""
    line = line.strip()
    comment_pos = line.find("#")
    if comment_pos == 0:
        return None
    last_hash = 0
    while comment_pos != -1:
        escaped = False
        if comment_pos < len(line) - 1 and line[comment_pos + 1] == "#":
            last_hash, escaped = comment_pos + 2, True
        if not escaped:
            line = line[:comment_pos]
            break
        line = line[:comment_pos + 1] + line[comment_pos + 2:]
        comment_pos = line.find("#", last_hash)
    line = line.strip()
    if not line:
        return None
    eq = line.find("=")
    if eq == -1 and not line.endswith("{") and line != "}":
        raise ValueError("Invalid config line")
    if eq == -1:
        return None
    lhs, rhs = line[:eq].strip(), line[eq + 1:].strip()
    if not lhs:
        raise ValueError("Empty lhs.")
    if "{{" in rhs and "}}" in rhs[rhs.find("{{") + 2:]:
        raise ValueError("expression")
    i = 0
    while rhs and i < len(rhs) - 1:
        if rhs[i] != "\\":
            i += 1
            continue
        if rhs[i + 1] == "\\":
            rhs = rhs[:i] + rhs[i + 1:]
            i += 1
            continue
        if rhs[i + 1] in "{}":
            rhs = rhs[:i] + rhs[i + 1:]
            i -= 1
        i += 1
    return lhs, rhs


def hyprlang_paths(conf_text):
    """Valores de `path` que hyprlang (port) leería. Lanza ValueError si hyprlang rechazaría la config."""
    out = []
    for ln in conf_text.splitlines():
        r = parse_line(ln)
        if r and r[0] == "path":
            out.append(r[1])
    return out


def probe_path(conf_text):
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False, encoding="utf-8") as f:
        for ln in conf_text.splitlines():
            if ln.strip().startswith("path"):
                f.write(ln + "\n")
        name = f.name
    try:
        out = subprocess.run([PROBE, name], capture_output=True, text=True, timeout=10).stdout.strip()
    finally:
        os.unlink(name)
    return out


class WallpaperCase(unittest.TestCase):
    def setUp(self):
        self.wp, self.home = load()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.pics = self.home / "Pictures" / "Wallpapers"
        self.pics.mkdir(parents=True)
        self.hypr = self.home / ".config" / "hypr"
        self.rc = 0
        self.calls = []

        def fake_run(cmd, **kw):
            self.calls.append(("run", list(cmd)))
            if cmd[0] == "hyprctl" and isinstance(self.rc, Exception):
                raise self.rc
            return types.SimpleNamespace(returncode=self.rc if cmd[0] == "hyprctl" else 0, stdout="", stderr="")

        self.popen_error = None

        def fake_popen(cmd, **kw):
            if self.popen_error:
                raise self.popen_error
            self.calls.append(("popen", list(cmd)))

        # el módulo `subprocess` del script se sustituye ENTERO por un doble (el real queda intacto para el resto del proceso)
        class FakeSubprocess:
            run = staticmethod(fake_run)
            Popen = staticmethod(fake_popen)

            def __getattr__(self_, name):
                return getattr(subprocess, name)

        for p in (mock.patch.object(self.wp, "HYPR_DIR", self.hypr), mock.patch.object(self.wp, "HYPR_CONF", self.hypr / "hyprpaper.conf"),
                  mock.patch.object(self.wp, "WALLPAPER_DIRS", [self.pics]),
                  mock.patch.object(self.wp, "subprocess", FakeSubprocess())):
            p.start()
            self.addCleanup(p.stop)
        self.api = self.wp.WallpaperAPI()

    def image(self, name, data=b"\x89PNG\r\n\x1a\n"):
        f = self.pics / name
        f.write_bytes(data)
        return f

    def apply(self, path, fit="cover"):
        return json.loads(self.api.apply(str(path), fit))

    def conf(self):
        return self.wp.HYPR_CONF.read_text(encoding="utf-8")


class HostileFileNames(WallpaperCase):
    def test_every_file_name_round_trips_through_hyprlang_to_the_exact_image(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                f = self.image(name)
                res = self.apply(f)
                self.assertTrue(res["ok"], res)
                text = self.conf()
                (value,) = hyprlang_paths(text)                      # una sola clave path, y la config se acepta
                self.assertTrue(self.wp._hyprlang_seguro(value), f"la ruta escrita tiene especiales: {value!r}")
                self.assertEqual(Path(value).resolve(), f.resolve(), "lo que hyprpaper leería no es la imagen elegida")
                if PROBE:
                    self.assertEqual(probe_path(text), f"PATH:{value}")

    def test_the_original_behaviour_would_have_failed_these_names(self):
        """Documenta el bug: escribir la ruta cruda (lo que hacía antes) rompe con estos nombres."""
        broken = 0
        for name in HOSTILE_NAMES:
            raw = f"wallpaper {{\n    monitor =\n    path = {self.pics / name}\n    fit_mode = cover\n}}\n"
            try:
                got = hyprlang_paths(raw)
                broken += got != [str(self.pics / name)]
            except ValueError:
                broken += 1
        self.assertGreaterEqual(broken, 6, "el port ya no reproduce los fallos documentados: revisar el port")

    def test_the_hyprctl_live_call_uses_the_safe_path_without_commas(self):
        f = self.image("coma, uno #2.png")
        self.apply(f)
        hyprctl = [c for kind, c in self.calls if kind == "run" and c[0] == "hyprctl"]
        self.assertEqual(len(hyprctl), 1)
        arg = hyprctl[0][-1]
        self.assertEqual(arg.count(","), 2, f"hyprctl parte el argumento por comas: {arg!r}")
        self.assertTrue(arg.endswith(",cover"))
        self.assertNotIn("#", arg)

    def test_the_current_wallpaper_badge_still_points_at_the_real_file(self):
        f = self.image("Sunset #3.png")
        self.apply(f, "contain")
        path, fit = self.wp._current_state()
        self.assertEqual(path, str(f.resolve()))
        self.assertEqual(fit, "contain")
        listed = json.loads(self.api.list())
        self.assertEqual(listed["current"], str(f.resolve()))
        self.assertIn(str(f.resolve()), [i["path"] for i in listed["items"]])


class ApplyValidation(WallpaperCase):
    def test_bad_inputs_are_refused_without_touching_the_config(self):
        d = self.pics / "carpeta.png"
        d.mkdir()
        for bad in ("", "/no/existe.png", str(d), "relativa.png", "~/no-existe.png", None, 5, ["x"]):
            with self.subTest(bad=bad):
                res = json.loads(self.api.apply(bad, "cover"))
                self.assertFalse(res["ok"])
        self.assertFalse(self.wp.HYPR_CONF.exists())
        self.assertEqual(self.calls, [])

    def test_a_relative_path_is_refused_even_if_it_exists_from_the_current_directory(self):
        self.image("a.png")
        cwd = os.getcwd()
        os.chdir(self.pics)
        self.addCleanup(os.chdir, cwd)
        res = json.loads(self.api.apply("a.png", "cover"))
        self.assertFalse(res["ok"])
        self.assertFalse(self.wp.HYPR_CONF.exists())

    def test_an_unknown_fit_mode_falls_back_to_cover(self):
        f = self.image("a.png")
        for fit in ("bogus", "", None, "cover\nsplash = true", "fill; rm -rf /"):
            with self.subTest(fit=fit):
                self.assertTrue(json.loads(self.api.apply(str(f), fit))["ok"])
                self.assertIn("fit_mode = cover\n", self.conf())
                self.assertEqual(self.conf().count("fit_mode"), 1)

    def test_every_valid_fit_mode_is_written_exactly(self):
        f = self.image("a.png")
        for fit in self.wp.FIT_MODES:
            self.assertTrue(self.apply(f, fit)["ok"])
            self.assertIn(f"fit_mode = {fit}\n", self.conf())


class LinkAndConfIntegrity(WallpaperCase):
    def links(self):
        return sorted(p.name for p in self.hypr.iterdir() if p.name.startswith(self.wp.LINK_BASE))

    def test_switching_between_extensions_leaves_exactly_one_link_and_no_temp_files(self):
        a, b, c = self.image("a.png"), self.image("b.jpg"), self.image("c.webp")
        for f, ext in ((a, ".png"), (b, ".jpg"), (c, ".webp"), (a, ".png")):
            self.assertTrue(self.apply(f)["ok"])
            self.assertEqual(self.links(), [f"{self.wp.LINK_BASE}{ext}"])
            self.assertEqual([p.name for p in self.hypr.iterdir() if p.name.endswith(".tmp")], [])
            self.assertEqual(os.path.realpath(self.hypr / f"{self.wp.LINK_BASE}{ext}"), str(f.resolve()))

    def test_a_failure_creating_the_new_link_keeps_the_previous_wallpaper_working(self):
        a = self.image("a.png")
        self.assertTrue(self.apply(a)["ok"])
        before = self.conf()
        with mock.patch("os.symlink", side_effect=OSError(13, "Permission denied")):
            res = self.apply(self.image("b.png"))
        self.assertFalse(res["ok"])
        link = self.hypr / f"{self.wp.LINK_BASE}.png"
        self.assertEqual(os.path.realpath(link), str(a.resolve()), "el enlace viejo tenía que seguir apuntando a a.png")
        self.assertEqual(self.conf(), before)

    def test_uppercase_and_unknown_extensions_get_a_normal_link_name(self):
        f = self.image("FOTO.JPG")
        self.assertTrue(self.apply(f)["ok"])
        self.assertEqual(self.links(), [f"{self.wp.LINK_BASE}.jpg"])

    def test_a_real_file_with_the_link_name_is_never_deleted(self):
        self.hypr.mkdir(parents=True)
        precious = self.hypr / f"{self.wp.LINK_BASE}.jpg"
        precious.write_text("no me borres")
        f = self.image("a.png")
        self.assertTrue(self.apply(f)["ok"])
        self.assertEqual(precious.read_text(), "no me borres")

    def test_a_dangling_or_foreign_link_is_replaced_not_followed(self):
        self.hypr.mkdir(parents=True)
        victim = self.home / "victima"
        victim.write_text("intacto")
        (self.hypr / f"{self.wp.LINK_BASE}.png").symlink_to(victim)
        f = self.image("a.png", data=b"IMG")
        self.assertTrue(self.apply(f)["ok"])
        self.assertEqual(victim.read_text(), "intacto")
        self.assertEqual((self.hypr / f"{self.wp.LINK_BASE}.png").read_bytes(), b"IMG")

    def test_a_stale_temp_link_from_a_killed_run_does_not_block_the_next_apply(self):
        self.hypr.mkdir(parents=True)
        os.symlink("/no/existe", self.hypr / f".{self.wp.LINK_BASE}.{os.getpid()}.tmp")
        self.assertTrue(self.apply(self.image("a.png"))["ok"])

    def test_the_config_is_replaced_atomically_and_a_failed_replace_keeps_the_old_one(self):
        f = self.image("a.png")
        self.assertTrue(self.apply(f, "fill")["ok"])
        before = self.conf()
        real_replace = os.replace

        def flaky(a, b, *x, **kw):
            if str(b).endswith("hyprpaper.conf"):
                raise OSError(28, "No space left on device")
            return real_replace(a, b, *x, **kw)

        with mock.patch("os.replace", side_effect=flaky):
            res = self.apply(f, "tile")
        self.assertFalse(res["ok"])
        self.assertIn("No space left", res["message"])
        self.assertEqual(self.conf(), before, "la config vieja tiene que sobrevivir intacta")
        self.assertEqual([p.name for p in self.hypr.iterdir() if p.name.endswith(".tmp")], [], "sin temporales")

    def test_an_unwritable_config_dir_is_reported_not_raised(self):
        blocker = self.home / "bloqueado"
        blocker.write_text("soy un archivo")
        with mock.patch.object(self.wp, "HYPR_DIR", blocker / "hypr"), mock.patch.object(self.wp, "HYPR_CONF", blocker / "hypr" / "hyprpaper.conf"):
            res = self.apply(self.image("a.png"))
        self.assertFalse(res["ok"])
        self.assertIn(self.wp.T["err-write"], res["message"])

    def test_a_home_whose_path_has_hyprlang_specials_is_refused_instead_of_writing_a_broken_config(self):
        weird = self.home / "home #1"
        with mock.patch.object(self.wp, "HYPR_DIR", weird), mock.patch.object(self.wp, "HYPR_CONF", weird / "hyprpaper.conf"):
            res = self.apply(self.image("a.png"))
        self.assertFalse(res["ok"])
        self.assertFalse((weird / "hyprpaper.conf").exists())


class LiveChangeAndFallback(WallpaperCase):
    def kinds(self):
        return [(k, c[0]) for k, c in self.calls if k in ("run", "popen") and c[0] in ("hyprctl", "pkill", "hyprpaper")]

    def test_live_change_success_does_not_restart_hyprpaper(self):
        self.rc = 0
        self.assertTrue(self.apply(self.image("a.png"))["live"])
        self.assertEqual(self.kinds(), [("run", "hyprctl")])

    def test_when_hyprctl_fails_or_is_missing_hyprpaper_is_restarted_from_the_new_config(self):
        for rc in (1, 2, FileNotFoundError("hyprctl"), subprocess.TimeoutExpired("hyprctl", 5), OSError("boom")):
            with self.subTest(rc=repr(rc)):
                self.calls.clear()
                self.rc = rc
                res = self.apply(self.image("a.png"))
                self.assertTrue(res["ok"])
                self.assertFalse(res["live"])
                self.assertEqual(self.kinds(), [("run", "hyprctl"), ("run", "pkill"), ("popen", "hyprpaper")])

    def test_a_hyprpaper_that_cannot_start_is_reported(self):
        self.rc = 1
        self.popen_error = FileNotFoundError("hyprpaper")
        res = self.apply(self.image("a.png"))
        self.assertFalse(res["ok"])
        self.assertIn(self.wp.T["err-restart"], res["message"])


class Scanning(WallpaperCase):
    def test_lists_images_dedups_by_resolved_path_and_orders_by_folder_then_name(self):
        (self.pics / "b").mkdir()
        (self.pics / "a").mkdir()
        self.image("z.png")
        (self.pics / "b" / "y.jpg").write_bytes(b"x")
        (self.pics / "a" / "x.webp").write_bytes(b"x")
        (self.pics / "a" / "notes.txt").write_text("no")
        (self.pics / "a" / "dup.png").symlink_to(self.pics / "z.png")        # mismo archivo por otro nombre
        items = json.loads(self.api.list())["items"]
        names = [(i["dir"], i["name"]) for i in items]
        self.assertEqual(names, sorted(names, key=lambda t: (t[0].lower(), t[1].lower())))
        self.assertEqual(len([i for i in items if i["path"].endswith("z.png")]), 1)
        self.assertNotIn("notes.txt", [i["name"] for i in items])

    def test_symlink_loops_deep_trees_and_unreadable_dirs_do_not_hang_or_raise(self):
        (self.pics / "loop").mkdir()
        (self.pics / "loop" / "self").symlink_to(self.pics)
        deep = self.pics
        for i in range(10):
            deep = deep / f"n{i}"
            deep.mkdir()
        (deep / "muy-profunda.png").write_bytes(b"x")
        noperm = self.pics / "sin-permiso"
        noperm.mkdir()
        (noperm / "a.png").write_bytes(b"x")
        noperm.chmod(0)
        self.addCleanup(noperm.chmod, 0o755)
        self.image("visible.png")
        names = [i["name"] for i in json.loads(self.api.list())["items"]]
        self.assertIn("visible.png", names)
        self.assertNotIn("muy-profunda.png", names, "respeta MAX_DEPTH")

    def test_current_state_survives_any_garbage_in_the_config(self):
        self.hypr.mkdir(parents=True)
        junk = ["", "\x00\xff", "wallpaper {", "wallpaper { path = }", "wallpaper {\n path =\n}", "}{}{", "wallpaper { path = \x00 }",
                "wallpaper {\n path = ~/x/../../..//etc\n fit_mode = ???\n}", "wallpaper { fit_mode = cover }", "a" * 200000,
                "wallpaper {" * 5000, "path = " + "/" * 5000]
        for text in junk:
            with self.subTest(text=text[:20]):
                self.wp.HYPR_CONF.write_text(text, encoding="utf-8", errors="ignore")
                path, fit = self.wp._current_state()
                self.assertIn(fit, self.wp.FIT_MODES)
                self.assertTrue(path is None or isinstance(path, str))
        self.wp.HYPR_CONF.unlink()
        self.assertEqual(self.wp._current_state(), (None, "cover"))
        self.wp.HYPR_CONF.mkdir()                       # un directorio en vez de archivo
        self.assertEqual(self.wp._current_state(), (None, "cover"))


class Thumbnails(WallpaperCase):
    """Las miniaturas salían negras en vivo (webkit2gtk 2.54.3 + pywebview 6.2.1): la página, cargada desde una cadena,
    no puede cargar <img src="file://…">. Ahora Python entrega la miniatura como data: URI por api.thumb()."""

    def listed(self, f):
        self.api.list()                       # thumb() solo sirve lo que list() acaba de mostrar
        return str(f.resolve())

    @unittest.skipUnless(PILImage, "Pillow no está instalado")
    def test_a_big_png_becomes_a_small_jpeg_data_uri(self):
        f = self.pics / "grande.png"
        PILImage.new("RGB", (3840, 2160), (200, 30, 30)).save(f)
        uri = self.api.thumb(self.listed(f))
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        im = PILImage.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        self.assertLessEqual(im.width, self.wp.THUMB_MAX[0])
        self.assertLessEqual(im.height, self.wp.THUMB_MAX[1])
        self.assertGreater(im.convert("RGB").getpixel((5, 5))[0], 150)         # sigue siendo rojo, no negro
        self.assertLess(len(uri), f.stat().st_size)                            # y pesa mucho menos que el original

    @unittest.skipUnless(PILImage, "Pillow no está instalado")
    def test_transparent_pixels_land_on_the_dark_ui_background_not_on_black(self):
        f = self.pics / "transparente.png"
        PILImage.new("RGBA", (64, 40), (0, 0, 0, 0)).save(f)
        uri = self.api.thumb(self.listed(f))
        im = PILImage.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).convert("RGB")
        r, g, b = im.getpixel((10, 10))
        self.assertTrue(18 <= r <= 26 and 18 <= g <= 26 and 26 <= b <= 34, (r, g, b))      # #16161e de la UI

    def test_without_pillow_the_original_bytes_are_sent(self):
        f = self.image("x.png", b"\x89PNG\r\n\x1a\nbytes de prueba")
        with mock.patch.dict(sys.modules, {"PIL": None}):                      # `import PIL` falla
            uri = self.api.thumb(self.listed(f))
        self.assertEqual(uri, "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode())

    def test_without_pillow_a_file_over_the_limit_is_skipped(self):
        f = self.image("enorme.png", b"0" * (self.wp.RAW_MAX_BYTES + 1))
        with mock.patch.dict(sys.modules, {"PIL": None}):
            self.assertEqual(self.api.thumb(self.listed(f)), "")

    @unittest.skipUnless(PILImage, "Pillow no está instalado")
    def test_a_corrupt_image_gives_no_thumbnail_and_does_not_raise(self):
        f = self.image("rota.png", b"esto no es una imagen")
        self.assertEqual(self.api.thumb(self.listed(f)), "")

    def test_only_what_list_returned_is_served(self):
        fuera = self.home / "secreto.png"
        fuera.write_bytes(b"\x89PNG\r\n\x1a\nsecreto")
        dentro = self.image("ok.png", TINY_PNG)
        self.assertEqual(self.api.thumb(str(dentro.resolve())), "")              # antes de list(): nada
        self.api.list()
        for malo in (str(fuera), "/etc/passwd", str(self.pics / ".." / "secreto.png"), "", None, 42, ["a"]):
            with self.subTest(path=malo):
                self.assertEqual(self.api.thumb(malo), "")
        self.assertTrue(self.api.thumb(str(dentro.resolve())).startswith("data:image/"))

    def test_the_page_asks_python_for_thumbnails_instead_of_loading_file_urls(self):
        html = self.wp._build_html()
        self.assertNotIn("file://", html)
        self.assertIn("api.thumb(", html)


class ProbeAvailable(unittest.TestCase):
    @unittest.skipUnless(PROBE and os.access(PROBE, os.X_OK), "AVALOS_HYPRLANG_PROBE no apunta a un binario ejecutable")
    def test_the_probe_confirms_the_documented_hyprlang_behaviour(self):
        expected = {"path = /a/Sunset #3.png": "PATH:/a/Sunset", "path = /a/doble ##x.png": "PATH:/a/doble #x.png",
                    "path = /a/ok.png": "PATH:/a/ok.png"}
        for line, want in expected.items():
            with self.subTest(line=line):
                self.assertEqual(probe_path(line + "\n"), want)


if __name__ == "__main__":
    unittest.main()
