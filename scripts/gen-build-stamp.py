#!/usr/bin/env python3
"""Sello de build de la ISO de AvalOS: lo llama build-iso.yml, lo copia el instalador al sistema instalado y
lo lee `avalos-version`.

Escribe dos archivos en --out:

  avalos-build        AVALOS_BUILD=AAAA.MM.DD-<commit corto>, AVALOS_COMMIT (40 hex) y AVALOS_COMMIT_DATE.
                      La fecha es la del commit, en UTC: la misma ISO reconstruida otro día lleva el mismo build.
  avalos-scripts.tsv  una línea por script de --scripts-dir: nombre, último commit que lo tocó, su fecha y el
                      sha256 de lo que viaja en la ISO (columnas separadas por tabulador).

Nada se numera a mano: todo sale del historial de git, así que no puede quedar desactualizado. Hace falta el
historial completo (actions/checkout con fetch-depth: 0); sin él cada script diría el mismo commit.

Uso:  python3 scripts/gen-build-stamp.py --scripts-dir DIR --out DIR [--repo DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

BUILD_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}-[0-9a-f]{7}$")


def git(repo: Path, *args: str) -> str:
    # TZ=UTC: las fechas salen en UTC aunque el commit se hiciera en otra zona horaria.
    # safe.directory: build-iso.yml corre en un contenedor (root) sobre un checkout que creó el runner (otro uid) y
    # git se niega con «detected dubious ownership» (run #114). Es nuestro propio checkout y solo se lee: se declara
    # seguro solo para estas llamadas (git únicamente respeta safe.directory en la configuración global, del
    # sistema o de la línea de comandos, y -c es lo último) sin tocar la configuración global, que cambiaría lo
    # que hacen los demás pasos del job.
    env = dict(os.environ, TZ="UTC", LC_ALL="C")
    r = subprocess.run(["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise SystemExit(f"gen-build-stamp: «git {' '.join(args)}» falló: {r.stderr.strip()}")
    return r.stdout.strip()


def build_info(repo: Path) -> dict[str, str]:
    commit = git(repo, "rev-parse", "HEAD")
    date = git(repo, "log", "-1", "--format=%cd", "--date=format-local:%Y.%m.%d", "HEAD")
    build = f"{date}-{commit[:7]}"
    if not BUILD_RE.match(build):
        raise SystemExit(f"gen-build-stamp: build con formato inesperado: {build!r}")
    return {"AVALOS_BUILD": build, "AVALOS_COMMIT": commit, "AVALOS_COMMIT_DATE": date.replace(".", "-")}


def script_rows(repo: Path, scripts_dir: Path) -> list[tuple[str, str, str, str]]:
    rows = []
    for f in sorted(scripts_dir.iterdir()):
        # build-iso.yml deja en esa carpeta también los .desktop: solo cuentan los scripts del repo
        if not f.is_file() or not (repo / "scripts" / f.name).is_file():
            continue
        out = git(repo, "log", "-1", "--abbrev=7", "--format=%h%x09%cd", "--date=format-local:%Y-%m-%d",
                  "--", f"scripts/{f.name}")
        commit, _, date = out.partition("\t")
        if not commit:
            print(f"gen-build-stamp: aviso: {f.name} no tiene historial en git", file=sys.stderr)
            commit, date = "?", "?"
        rows.append((f.name, commit, date, hashlib.sha256(f.read_bytes()).hexdigest()))
    if not rows:
        raise SystemExit(f"gen-build-stamp: no hay scripts de AvalOS en {scripts_dir}")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genera el sello de build de la ISO de AvalOS.")
    ap.add_argument("--scripts-dir", required=True, type=Path, help="carpeta con los scripts que van en la ISO")
    ap.add_argument("--out", required=True, type=Path, help="carpeta donde escribir avalos-build y avalos-scripts.tsv")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent, help="raíz del repo")
    args = ap.parse_args(argv)

    repo = args.repo.resolve()    # safe.directory se compara con la ruta real
    info = build_info(repo)
    rows = script_rows(repo, args.scripts_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "avalos-build").write_text("".join(f"{k}={v}\n" for k, v in info.items()), encoding="utf-8")
    (args.out / "avalos-scripts.tsv").write_text("".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    print(f"gen-build-stamp: {info['AVALOS_BUILD']} · {len(rows)} scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
