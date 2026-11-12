#!/usr/bin/env python3
"""Genera scripts/skill_instalar_usb.py (el instalador legado, `avalos-install-old`) a partir del paquete
modular scripts/avalos_installer/.

El legado dejó de ser una copia aparte: es el MISMO instalador empaquetado en un solo archivo autónomo. Así
tiene todo lo que tiene el modular (rollback, comprobaciones previas, diagnóstico de red, failover de mirrors…)
y no puede volver a quedarse atrás. Sigue sin depender de los archivos del paquete: lleva el código de cada
módulo dentro y los importa desde ahí (un MetaPathFinder), así que sirve de respaldo aunque el directorio
avalos_installer/ de la ISO esté roto. Lo único externo es translations.py, igual que antes.

El archivo se genera sin fechas ni nada que dependa de la máquina (la misma entrada da la misma salida); un
test del repo lo regenera en memoria y falla si no coincide.

Uso:  python3 scripts/build-legacy-installer.py            regenera scripts/skill_instalar_usb.py
      python3 scripts/build-legacy-installer.py --check    sale con 1 si el archivo no está al día
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "scripts" / "avalos_installer"
OUT = ROOT / "scripts" / "skill_instalar_usb.py"

# Último commit del monolito original (5.538 líneas), por si hace falta recuperarlo: git show <commit>:scripts/skill_instalar_usb.py
MONOLITH_COMMIT = "2f2d844"

TEMPLATE = '''"""skill_instalar_usb.py — instalador de AvalOS de un solo archivo (`avalos-install-old`).

GENERADO por scripts/build-legacy-installer.py a partir de scripts/avalos_installer/: NO EDITAR A MANO (los
cambios se hacen en el paquete modular y se regenera este archivo; el test tests/test_legacy_bundle.py falla si
no está al día).

Es el mismo instalador que `avalos-install`, empaquetado: cada módulo viaja aquí dentro como texto y se importa
desde este archivo, así que funciona aunque el directorio avalos_installer/ de la ISO no esté. Lo único externo
es translations.py (igual que siempre) y, en la ISO, pywebview y GTK.

El monolito original de 5.538 líneas que estuvo aquí hasta el commit anterior a este cambio se puede recuperar con:
    git show @@MONOLITH@@:scripts/skill_instalar_usb.py
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import linecache
import os
import sys

BUNDLE_SOURCE_SHA256 = "@@SHA@@"

# nombre del módulo -> (¿es paquete?, ruta de origen, código fuente). Las rutas son las del repo, para que los
# errores y los tracebacks apunten a scripts/avalos_installer/… y no a este archivo.
_MODULES = {
@@MODULES@@}


class _BundleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Sirve los módulos de avalos_installer desde _MODULES, antes que cualquier copia que haya en disco."""

    def __init__(self, modules):
        self._modules = modules

    def find_spec(self, fullname, path=None, target=None):
        entry = self._modules.get(fullname)
        if entry is None:
            return None
        is_pkg, filename, _source = entry
        return importlib.util.spec_from_loader(fullname, self, origin=filename, is_package=is_pkg)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        is_pkg, filename, source = self._modules[module.__spec__.name]
        module.__file__ = filename
        linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)   # tracebacks con su línea
        code = compile(source, filename, "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102  # nosec B102 - código del propio repo, embebido arriba


def _install_finder():
    for finder in sys.meta_path:
        if isinstance(finder, _BundleFinder):
            return finder
    finder = _BundleFinder(_MODULES)
    sys.meta_path.insert(0, finder)
    return finder


def main() -> None:
    _install_finder()
    os.environ.setdefault("AVALOS_INSTALLER_VARIANT", "legado (un solo archivo)")   # lo dice el log del instalador
    from avalos_installer.__main__ import main as run_installer
    run_installer()


if __name__ == "__main__":
    main()
'''


def collect_modules() -> list[tuple[str, bool, str, str]]:
    """(nombre, ¿paquete?, ruta relativa, fuente) de cada .py del paquete, ordenados por ruta."""
    mods = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG.parent).as_posix()                    # avalos_installer/core/config.py
        parts = list(path.relative_to(PKG.parent).with_suffix("").parts)
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        source = path.read_bytes().decode("utf-8")           # en bytes: read_text() ocultaría los \r (newline universal)
        if "\0" in source or "\r" in source:
            raise SystemExit(f"build-legacy-installer: {rel} tiene NUL o retornos de carro: no se puede embeber")
        mods.append((".".join(parts), is_pkg, rel, source))
    if not mods:
        raise SystemExit(f"build-legacy-installer: no hay módulos en {PKG}")
    return mods


def source_sha256(mods) -> str:
    h = hashlib.sha256()
    for name, is_pkg, rel, source in mods:
        h.update(f"{name}\0{int(is_pkg)}\0{rel}\0{source}\0".encode())
    return h.hexdigest()


def literal(source: str) -> str:
    """Un literal de Python que vale exactamente `source`: crudo y de comillas triples si cabe (se lee como el
    original), y repr() si no."""
    for quote in ("'''", '"""'):
        code = f"r{quote}{source}{quote}"
        try:
            if ast.literal_eval(code) == source:        # la comprobación de verdad: lo que se lee es lo que se escribió
                return code
        except (SyntaxError, ValueError):
            pass
    return repr(source)


def render(mods=None) -> str:
    mods = mods or collect_modules()
    blocks = []
    for name, is_pkg, rel, source in mods:
        blocks.append(f"    # ── {rel} ({source.count(chr(10))} líneas)\n"
                      f"    {name!r}: ({is_pkg}, {rel!r}, {literal(source)}),\n")
    return (TEMPLATE.replace("@@SHA@@", source_sha256(mods))
            .replace("@@MONOLITH@@", MONOLITH_COMMIT)
            .replace("@@MODULES@@", "".join(blocks)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genera el instalador legado de un solo archivo.")
    ap.add_argument("--check", action="store_true", help="no escribe: sale con 1 si el archivo no está al día")
    args = ap.parse_args(argv)
    text = render()
    current = OUT.read_text(encoding="utf-8") if OUT.is_file() else None
    if args.check:
        if current == text:
            print("ok: skill_instalar_usb.py está al día con scripts/avalos_installer/")
            return 0
        print("ERROR: scripts/skill_instalar_usb.py no está al día con scripts/avalos_installer/.\n"
              "       Regéneralo con: python3 scripts/build-legacy-installer.py", file=sys.stderr)
        return 1
    if current == text:
        print("sin cambios: skill_instalar_usb.py ya estaba al día")
        return 0
    OUT.write_text(text, encoding="utf-8")
    try:
        shown = OUT.relative_to(ROOT).as_posix()
    except ValueError:                                       # una ruta de salida fuera del repo (las pruebas)
        shown = str(OUT)
    print(f"escrito {shown}: {len(text.splitlines())} líneas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
