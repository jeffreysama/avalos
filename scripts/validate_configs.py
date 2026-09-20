#!/usr/bin/env python3
"""
validate_configs.py — valida las configs de configs/ con los parsers REALES.

Por qué existe: Waybar carga style.css con el parser CSS de GTK3 y, ante UNA
sola propiedad o pseudo-clase desconocida, devuelve error y la barra no
arranca ("style.css:18:12'box-sizing' is not a valid property name"). Ese
error llegó tres veces a una instalación real porque nada lo detectaba antes
de generar la ISO, y un comentario que decía "GTK la ignora en silencio"
(falso) lo dejó en su lugar. Lo mismo pasó con el logo de fastfetch: la ISO
usaba una copia embebida en el workflow, no el archivo del repo.

Chequeos:
  css      cada configs/**/*.css con Gtk.CssProvider (el mismo parser de Waybar)
  jsonc    configs/**/*.jsonc y *.json (comentarios // y /* */ permitidos)
  lua      configs/hyprland/*.lua y el template (con sus %%marcadores%% resueltos)
           con `luac -p`
  shell    powermenu.sh y los scripts de scripts/ con shebang bash/sh: `bash -n`
  python   los scripts de scripts/ con shebang python: compilación
  desktop  configs/*.desktop con desktop-file-validate
  xml      configs/*.policy (polkit)
  ini      configs/gtk/settings.ini, configs/mako/config
  hyprlang llaves balanceadas en hypridle/hyprlock/hyprpaper .conf
  logo     el logo de fastfetch solo usa colores definidos en config.jsonc, es
           idéntico en assets/, y build-iso.yml lo toma del repo
  copias   configs/kitty/kitty.conf y configs/hyprland/kitty.conf coinciden
           (ignorando comentarios)
  yaml     .github/workflows/*.yml

Uso:  python3 scripts/validate_configs.py [--strict] [--only css,json,...]
  --strict  un chequeo que no se puede ejecutar (falta GTK, luac...) cuenta
            como error. Es lo que usa CI.
  --only    corre solo esos chequeos (nombres de arriba, separados por coma).
            La compuerta de build-iso.yml usa: css,json,lua,logo
Salida: 0 = todo bien, 1 = hay errores.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "configs"


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


class Report:
    def __init__(self, strict: bool):
        self.strict = strict
        self.ok = 0
        self.fail: list[str] = []
        self.skip: list[str] = []

    def good(self, what: str) -> None:
        self.ok += 1
        print(f"  ok    {what}")

    def bad(self, what: str, detail: str = "") -> None:
        self.fail.append(what)
        print(f"  FAIL  {what}")
        for ln in detail.splitlines():
            print(f"          {ln}")

    def skipped(self, what: str, why: str) -> None:
        if self.strict:
            self.bad(what, f"no se pudo ejecutar (--strict): {why}")
        else:
            self.skip.append(what)
            print(f"  skip  {what} ({why})")

    def check(self, what: str, errors: list[str]) -> None:
        if errors:
            self.bad(what, "\n".join(errors))
        else:
            self.good(what)


def strip_jsonc(text: str) -> str:
    """Quita comentarios // y /* */ (respetando strings) y comas finales."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


# ── css ──────────────────────────────────────────────────────────────────
def check_css(rep: Report) -> None:
    files = sorted(CFG.rglob("*.css"))
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
    except Exception as e:  # noqa: BLE001
        for f in files:
            rep.skipped(f"css (GTK3): {rel(f)}", f"PyGObject/GTK3 no disponible: {e}")
        return
    for f in files:
        prov = Gtk.CssProvider()
        errs: list[str] = []

        def on_err(_p, sec, err, errs=errs):
            errs.append(f"línea {sec.get_start_line() + 1}:{sec.get_end_position()}  {err.message}")

        prov.connect("parsing-error", on_err)
        try:
            prov.load_from_path(str(f))
        except GLib.Error as e:
            if not errs:
                errs.append(e.message)
        rep.check(f"css (GTK3): {rel(f)}", errs)


# ── jsonc / json ──────────────────────────────────────────────────────────
def check_json(rep: Report) -> None:
    for f in sorted(list(CFG.rglob("*.jsonc")) + list(CFG.rglob("*.json"))):
        try:
            json.loads(strip_jsonc(f.read_text(encoding="utf-8")))
            rep.good(f"json: {rel(f)}")
        except (ValueError, OSError) as e:
            rep.bad(f"json: {rel(f)}", str(e))


# ── lua ──────────────────────────────────────────────────────────────────
def check_lua(rep: Report) -> None:
    files = sorted(CFG.rglob("*.lua")) + sorted(CFG.rglob("*.lua.template")) + sorted(CFG.rglob("*_lua.template"))
    luac = next((shutil.which(x) for x in ("luac5.4", "luac", "luac5.3", "luac5.1") if shutil.which(x)), None)
    for f in files:
        if luac is None:
            rep.skipped(f"lua: {rel(f)}", "luac no encontrado")
            continue
        src = f.read_text(encoding="utf-8")
        src = src.replace("%%GPU_ENV%%", "-- gpu").replace("%%KEYMAP%%", "us")
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as tmp:
            tmp.write(src)
        r = subprocess.run([luac, "-p", tmp.name], capture_output=True, text=True)
        Path(tmp.name).unlink(missing_ok=True)
        rep.check(f"lua: {rel(f)}", [r.stderr.strip()] if r.returncode else [])


# ── shell / python ────────────────────────────────────────────────────────
def check_scripts(rep: Report) -> None:
    cands = [CFG / "rofi" / "powermenu.sh"] + [p for p in sorted((ROOT / "scripts").iterdir()) if p.is_file() and p.suffix in ("", ".sh", ".py")]
    for f in cands:
        try:
            first = f.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        except OSError:
            continue
        if not first.startswith("#!"):
            continue
        if re.search(r"\b(ba)?sh\b", first):
            r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
            rep.check(f"shell: {rel(f)}", [r.stderr.strip()] if r.returncode else [])
        elif "python" in first:
            r = subprocess.run([sys.executable, "-c", "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1], 'exec')", str(f)],
                               capture_output=True, text=True)
            rep.check(f"python: {rel(f)}", [r.stderr.strip().splitlines()[-1]] if r.returncode else [])


# ── desktop / xml / ini ────────────────────────────────────────────────────
def check_desktop(rep: Report) -> None:
    exe = shutil.which("desktop-file-validate")
    for f in sorted(CFG.glob("*.desktop")):
        if exe is None:
            rep.skipped(f"desktop: {rel(f)}", "desktop-file-validate no encontrado")
            continue
        r = subprocess.run([exe, str(f)], capture_output=True, text=True)
        rep.check(f"desktop: {rel(f)}", [(r.stdout + r.stderr).strip()] if r.returncode else [])


def check_xml(rep: Report) -> None:
    for f in sorted(CFG.glob("*.policy")):
        try:
            ET.parse(f)
            rep.good(f"xml: {rel(f)}")
        except ET.ParseError as e:
            rep.bad(f"xml: {rel(f)}", str(e))


def check_ini(rep: Report) -> None:
    f = CFG / "gtk" / "settings.ini"
    if f.exists():
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read_string(f.read_text(encoding="utf-8"))
            rep.check(f"ini: {rel(f)}", [] if cp.has_section("Settings") else ["falta la sección [Settings]"])
        except configparser.Error as e:
            rep.bad(f"ini: {rel(f)}", str(e))
    f = CFG / "mako" / "config"
    if f.exists():
        errs = []
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = ln.strip()
            if s and not s.startswith("#") and not re.match(r"^(\[[^\]]+\]|[A-Za-z0-9_-]+\s*=.*)$", s):
                errs.append(f"línea {n}: no es 'clave=valor' ni '[sección]': {s[:60]}")
        rep.check(f"ini: {rel(f)}", errs)


def check_hyprlang(rep: Report) -> None:
    for name in ("hypridle.conf", "hyprlock.conf", "hyprpaper.conf"):
        f = CFG / "hyprland" / name
        if not f.exists():
            continue
        depth, errs = 0, []
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = ln.split("#", 1)[0]
            depth += code.count("{") - code.count("}")
            if depth < 0:
                errs.append(f"línea {n}: '}}' sin abrir")
                depth = 0
        if depth:
            errs.append(f"{depth} bloque(s) '{{' sin cerrar")
        rep.check(f"hyprlang (llaves): {rel(f)}", errs)


# ── consistencia ──────────────────────────────────────────────────────────
def check_logo(rep: Report) -> None:
    logo, cfg = CFG / "fastfetch" / "avalos.txt", CFG / "fastfetch" / "config.jsonc"
    if not (logo.exists() and cfg.exists()):
        return
    defined = set(json.loads(strip_jsonc(cfg.read_text(encoding="utf-8")))["logo"]["color"])
    errs = []
    for n, ln in enumerate(logo.read_text(encoding="utf-8").split("\n"), 1):
        i = 0
        while i < len(ln):
            if ln[i] == "$":
                nxt = ln[i + 1:i + 2]
                if nxt == "$":
                    i += 2
                    continue
                if not nxt.isdigit():
                    errs.append(f"línea {n}: '$' suelto (un '$' literal se escribe '$$')")
                elif nxt not in defined:
                    errs.append(f"línea {n}: usa ${nxt} pero config.jsonc no lo define en logo.color")
                i += 2
                continue
            i += 1
    rep.check("logo fastfetch: códigos $N definidos en config.jsonc", errs)

    dup = ROOT / "assets" / "avalos.txt"
    if dup.exists():
        rep.check("logo fastfetch: assets/avalos.txt == configs/fastfetch/avalos.txt",
                  [] if dup.read_bytes() == logo.read_bytes() else ["las dos copias difieren"])

    wf = ROOT / ".github" / "workflows" / "build-iso.yml"
    if wf.exists():
        rep.check("logo fastfetch: build-iso.yml copia configs/fastfetch/avalos.txt",
                  [] if "configs/fastfetch/avalos.txt" in wf.read_text(encoding="utf-8")
                  else ["la ISO no usa el logo del repo (editarlo no tendría efecto)"])


def _code_lines(path: Path) -> list[str]:
    return [re.sub(r"\s+", " ", ln.strip()) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def check_copies(rep: Report) -> None:
    a, b = CFG / "kitty" / "kitty.conf", CFG / "hyprland" / "kitty.conf"
    if a.exists() and b.exists():
        rep.check("copias: kitty.conf (kitty/ y hyprland/) coinciden sin comentarios",
                  [] if _code_lines(a) == _code_lines(b) else ["las dos copias tienen opciones distintas"])


def check_yaml(rep: Report) -> None:
    files = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    try:
        import yaml
    except ImportError:
        for f in files:
            rep.skipped(f"yaml: {rel(f)}", "PyYAML no disponible")
        return
    for f in files:
        try:
            yaml.safe_load(f.read_text(encoding="utf-8"))
            rep.good(f"yaml: {rel(f)}")
        except yaml.YAMLError as e:
            rep.bad(f"yaml: {rel(f)}", str(e))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="un chequeo que no se puede ejecutar cuenta como error")
    ap.add_argument("--only", default="", help="chequeos a correr, separados por coma (por defecto todos)")
    args = ap.parse_args()
    checks = {
        "css": check_css, "json": check_json, "lua": check_lua, "shell": check_scripts, "python": check_scripts,
        "desktop": check_desktop, "xml": check_xml, "ini": check_ini, "hyprlang": check_hyprlang,
        "logo": check_logo, "copias": check_copies, "yaml": check_yaml,
    }
    wanted = [w.strip() for w in args.only.split(",") if w.strip()]
    unknown = [w for w in wanted if w not in checks]
    if unknown:
        ap.error(f"chequeo(s) desconocido(s): {', '.join(unknown)} (válidos: {', '.join(checks)})")
    fns = list(dict.fromkeys(checks[w] for w in wanted)) if wanted else list(dict.fromkeys(checks.values()))
    rep = Report(args.strict)
    for fn in fns:
        fn(rep)
    print(f"\n{rep.ok} ok · {len(rep.fail)} con error · {len(rep.skip)} omitidos")
    if rep.fail:
        print("FALLARON:", *rep.fail, sep="\n  - ")
    return 1 if rep.fail else 0


if __name__ == "__main__":
    sys.exit(main())
