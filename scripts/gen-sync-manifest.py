#!/usr/bin/env python3
"""Manifiesto de checksums para `sync-system-files` (scripts/avalos-update-helper).

    python3 scripts/gen-sync-manifest.py           # regenera configs/MANIFEST.sha256
    python3 scripts/gen-sync-manifest.py --check   # valida listas, manifiesto y commit pineado (lo corre CI)
    python3 scripts/gen-sync-manifest.py --pin     # fija AVALOS_SYNC_REF = HEAD
    python3 scripts/gen-sync-manifest.py --release # pasos 2 y 3 de abajo de una vez (sin push)

Cómo encaja (ver el comentario de AVALOS_SYNC_REF en avalos-update-helper):
sync-system-files corre como root, baja archivos de raw.githubusercontent.com en
un commit FIJO (AVALOS_SYNC_REF) y verifica cada uno contra
configs/MANIFEST.sha256, que vive en ese mismo commit. RUTAS = los archivos que
sync instala, 1:1 con `manifest` en cmd_sync_system_files (`--check` lo
verifica). PIN_FILES (helper + avalos-update) llevan el pin, así que NO se
sincronizan: un archivo no puede instalar su propia ancla de confianza desde el
canal que esa ancla autentica.

Cortar una release: commitear los cambios y correr --release (hace el manifiesto, el pin y
sus dos commits; el push sigue siendo tuyo a propósito: es la compuerta humana de la release).
A mano son estos pasos, en este orden:
  1. commitear los cambios a los archivos de RUTAS
  2. python3 scripts/gen-sync-manifest.py
     git add configs/MANIFEST.sha256 && git commit -m "chore: manifiesto de sync"
  3. python3 scripts/gen-sync-manifest.py --pin
     git commit -am "chore: pin AVALOS_SYNC_REF"
  4. git push        (el commit pineado tiene que estar en GitHub antes del primer sync)
     Si el push sale rechazado: `git pull --no-rebase` (un rebase reescribe el commit
     pineado y ese SHA dejaría de existir → sync fallaría cerrado).

--pin se niega a correr si el manifiesto de HEAD no coincide con los archivos
de HEAD. Esto NO cubre un commit pineado legítimamente comprometido — para eso
hace falta firmar (GPG) o distribuir estos archivos como paquete del repo [avalos].
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

# Debe reflejar 1:1 los `src_rel` de `manifest` en cmd_sync_system_files. Son 2
# listas separadas A PROPÓSITO (avalos-update-helper no tiene extensión .py, no
# hay forma limpia de importarlo); `--check` detecta si se desalinean.
RUTAS = [
    "scripts/avalos-settings",
    "scripts/avalos-wallpaper",
    "scripts/avalos-about",
    "scripts/avalos-store",
    "scripts/avalos-restore",
    "configs/avalos-store-catalog.json",
    "configs/avalos-settings.desktop",
    "configs/avalos-store.desktop",
    "configs/avalos-update.policy",
    "configs/avalos-store.policy",
    "configs/avalos-store.svg",
    "configs/avalos-update.desktop",
    "configs/avalos-update.svg",
    "configs/avalos-restore.desktop",
    "configs/avalos-restore.svg",
    "configs/hyprland/hyprland_conf_lua.template",
    "configs/hyprland/hyprpaper.conf",
    "configs/hyprland/hypridle.conf",
    "configs/hyprland/hyprlock.conf",
    "configs/waybar/config.jsonc",
    "configs/waybar/style.css",
    "configs/mako/config",
    "configs/kitty/kitty.conf",
    "configs/rofi/config.rasi",
    "configs/rofi/powermenu.sh",
    "configs/mangohud/MangoHud.conf",
    "configs/fastfetch/config.jsonc",
    "configs/fastfetch/avalos.txt",
    "configs/gtk/settings.ini",
    "configs/sddm/Main.qml",
    "configs/sddm/metadata.desktop",
]
PIN_FILES = ["scripts/avalos-update-helper", "scripts/avalos-update"]
HELPER = "scripts/avalos-update-helper"
MANIFEST = "configs/MANIFEST.sha256"
_PIN_RE = re.compile(r'^(AVALOS_SYNC_REF\s*=\s*)"([^"\n]*)"', re.M)


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=check)


def _root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_manifest(texto: str) -> dict[str, str]:
    """Mismo formato estricto que _cargar_manifest_hashes() del helper."""
    hashes: dict[str, str] = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        partes = linea.split(None, 1)
        if len(partes) != 2 or not re.fullmatch(r"[0-9a-f]{64}", partes[0]):
            raise ValueError(f"línea con formato inesperado: {linea!r}")
        hashes[partes[1].strip()] = partes[0]
    return hashes


def _rutas_del_helper(root: Path) -> list[str]:
    tree = ast.parse((root / HELPER).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "cmd_sync_system_files":
            for nodo in ast.walk(fn):
                if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                        and isinstance(nodo.targets[0], ast.Name) and nodo.targets[0].id == "manifest"
                        and isinstance(nodo.value, ast.List)):
                    return [e.elts[0].value for e in nodo.value.elts]  # type: ignore[attr-defined]
    raise RuntimeError("no encontré `manifest = [...]` dentro de cmd_sync_system_files")


def _verificar_ref(root: Path, ref: str) -> list[str]:
    """Problemas de `ref` como commit sincronizable: tiene que traer MANIFEST.sha256,
    listar exactamente RUTAS, y cada hash tiene que coincidir con el archivo de ESE commit."""
    corto = ref[:12]
    m = _git(root, "show", f"{ref}:{MANIFEST}", check=False)
    if m.returncode != 0:
        return [f"{MANIFEST} no existe en {corto} — sync-system-files fallaría cerrado "
                "(commiteá el manifiesto ANTES de pinear)"]
    try:
        hashes = _parse_manifest(m.stdout.decode("utf-8"))
    except ValueError as e:
        return [f"{MANIFEST} en {corto}: {e}"]
    if set(hashes) != set(RUTAS):
        return [f"{MANIFEST} en {corto} no lista exactamente RUTAS — regenerá y commiteá"]
    malos = []
    for r in RUTAS:
        f = _git(root, "show", f"{ref}:{r}", check=False)
        if f.returncode != 0 or _sha(f.stdout) != hashes[r]:
            malos.append(r)
    if malos:
        return [f"el manifiesto de {corto} no coincide con sus archivos: {', '.join(malos)}"]
    return []


def _check_pin(root: Path) -> list[str]:
    """El pin de los 2 archivos: mismo valor, UNSET o SHA de 40 hex, y si el commit está
    disponible, que traiga un manifiesto consistente (el error que deja sync roto)."""
    pines: dict[str, str | None] = {}
    for p in PIN_FILES:
        mo = _PIN_RE.search((root / p).read_text(encoding="utf-8"))
        pines[p] = mo.group(2) if mo else None
    if None in pines.values():
        return [f"no encontré AVALOS_SYNC_REF en: {', '.join(p for p, v in pines.items() if v is None)}"]
    if len(set(pines.values())) != 1:
        return [f"AVALOS_SYNC_REF distinto entre archivos: {pines}"]
    pin = next(iter(pines.values())) or ""
    if pin == "UNSET":
        print("aviso: AVALOS_SYNC_REF = UNSET (release sin cortar) — sync-system-files se niega a correr hasta pinear")
        return []
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        return [f"AVALOS_SYNC_REF no es UNSET ni un SHA de 40 hex: {pin!r}"]
    existe = ["cat-file", "-e", f"{pin}^{{commit}}"]
    if _git(root, *existe, check=False).returncode != 0:
        _git(root, "fetch", "-q", "--depth=1", "origin", pin, check=False)  # CI hace checkout superficial
        if _git(root, *existe, check=False).returncode != 0:
            print(f"aviso: no pude verificar el commit pineado {pin[:12]} (no está en el clon y no se pudo traer de origin)")
            return []
    problemas = _verificar_ref(root, pin)
    if not problemas:
        _avisar_release_pendiente(root, pin)
    return problemas


def _cambiados_desde(root: Path, ref: str) -> list[str]:
    """Archivos de RUTAS cuyo contenido actual difiere del que tenía `ref`."""
    out = []
    for r in RUTAS:
        antes = _git(root, "show", f"{ref}:{r}", check=False)
        if antes.returncode != 0 or not (root / r).is_file() or antes.stdout != (root / r).read_bytes():
            out.append(r)
    return out


def _avisar_release_pendiente(root: Path, pin: str) -> None:
    """Los sistemas instalados solo reciben lo que está en el commit pineado: si RUTAS cambió
    desde el pin, esos cambios NO llegan a nadie hasta cortar release. Se avisa, no se falla."""
    cambiados = _cambiados_desde(root, pin)
    if not cambiados:
        return
    msg = (f"{len(cambiados)} archivo(s) sincronizable(s) cambiaron desde el commit pineado "
           f"{pin[:12]} y todavía NO llegan a los sistemas instalados: {', '.join(cambiados)}")
    print(f"aviso: {msg} — para publicarlos: python3 scripts/gen-sync-manifest.py --release")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Release de sync pendiente::{msg}")


def cmd_generar(root: Path) -> int:
    faltan = [r for r in RUTAS if not (root / r).is_file()]
    if faltan:
        print("ERROR: faltan archivos de RUTAS: " + ", ".join(faltan), file=sys.stderr)
        return 1
    lineas = [f"{_sha((root / r).read_bytes())}  {r}\n" for r in sorted(RUTAS)]
    (root / MANIFEST).write_text("".join(lineas), encoding="utf-8")
    print(f"escrito: {MANIFEST} ({len(lineas)} archivos)")
    return 0


def cmd_check(root: Path) -> int:
    errores: list[str] = []
    if len(set(RUTAS)) != len(RUTAS):
        errores.append("RUTAS tiene entradas duplicadas")
    for p in PIN_FILES:
        if p in RUTAS:
            errores.append(f"{p} lleva el pin y NO debe estar en RUTAS (ver AVALOS_SYNC_REF)")
    try:
        del_helper = _rutas_del_helper(root)
    except (RuntimeError, OSError, SyntaxError) as e:
        errores.append(str(e))
        del_helper = None
    if del_helper is not None and sorted(del_helper) != sorted(RUTAS):
        solo_helper = sorted(set(del_helper) - set(RUTAS))
        solo_rutas = sorted(set(RUTAS) - set(del_helper))
        errores.append(f"`manifest` del helper y RUTAS no coinciden — solo en helper: {solo_helper}, solo en RUTAS: {solo_rutas}")
    for r in RUTAS:
        if not (root / r).is_file():
            errores.append(f"no existe en el repo: {r}")
    mf = root / MANIFEST
    if not mf.is_file():
        errores.append(f"falta {MANIFEST} (correr: python3 scripts/gen-sync-manifest.py)")
    else:
        try:
            hashes = _parse_manifest(mf.read_text(encoding="utf-8"))
        except ValueError as e:
            errores.append(f"{MANIFEST}: {e}")
        else:
            if set(hashes) != set(RUTAS):
                errores.append(f"{MANIFEST} no lista exactamente RUTAS — regenerar")
            else:
                viejos = [r for r in RUTAS if (root / r).is_file() and _sha((root / r).read_bytes()) != hashes[r]]
                if viejos:  # aviso, no error: el manifiesto solo tiene que estar al día al cortar una release
                    print(f"aviso: {len(viejos)} archivo(s) cambiaron desde el último manifiesto (regenerarlo antes de cortar release): {', '.join(viejos)}")
    errores += _check_pin(root)
    for e in errores:
        print(f"ERROR: {e}", file=sys.stderr)
    if not errores:
        print("ok: RUTAS == manifest del helper, manifiesto bien formado, pin consistente")
    return 1 if errores else 0


def cmd_pin(root: Path, *, indicar_siguiente: bool = True) -> int:
    problemas = _verificar_ref(root, "HEAD")
    if problemas:
        for e in problemas:
            print(f"ERROR: {e}", file=sys.stderr)
        print("       arreglalo, commiteá y volvé a correr --pin.", file=sys.stderr)
        return 1
    sha = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    for p in PIN_FILES:
        ruta = root / p
        nuevo, n = _PIN_RE.subn(lambda mo: f'{mo.group(1)}"{sha}"', ruta.read_text(encoding="utf-8"))
        if n != 1:
            print(f"ERROR: no encontré exactamente una línea AVALOS_SYNC_REF en {p}", file=sys.stderr)
            return 1
        ruta.write_text(nuevo, encoding="utf-8")
    print(f"AVALOS_SYNC_REF = {sha}  (en {', '.join(PIN_FILES)})")
    if not _git(root, "branch", "-r", "--contains", "HEAD", check=False).stdout.strip():
        print("aviso: HEAD todavía no está en ningún remoto — pushealo antes de que alguien corra sync.")
    if indicar_siguiente:
        print('siguiente: git commit -am "chore: pin AVALOS_SYNC_REF" && git push')
        print("ojo: si el push sale rechazado usá 'git pull --no-rebase' (un rebase reescribe el commit pineado)")
    return 0


def cmd_release(root: Path) -> int:
    """Manifiesto -> commit -> pin -> commit. NO hace push."""
    tocados = [*RUTAS, *PIN_FILES, MANIFEST]
    sucio = _git(root, "status", "--porcelain", "--", *tocados, check=False).stdout.decode().strip()
    if sucio:
        print("ERROR: hay cambios sin commitear en archivos de la release:\n" + sucio, file=sys.stderr)
        print("       commitealos primero (el manifiesto se calcula sobre lo commiteado) y volvé a correr --release.", file=sys.stderr)
        return 1
    pin_actual = next(iter({m.group(2) for p in PIN_FILES if (m := _PIN_RE.search((root / p).read_text(encoding="utf-8")))}), "")
    if re.fullmatch(r"[0-9a-f]{40}", pin_actual) and _git(root, "cat-file", "-e", f"{pin_actual}^{{commit}}", check=False).returncode == 0 \
            and not _cambiados_desde(root, pin_actual):
        print(f"nada que publicar: los archivos sincronizables no cambiaron desde el pin actual ({pin_actual[:12]}).")
        return 0
    try:
        if cmd_generar(root) != 0:
            return 1
        if _git(root, "status", "--porcelain", "--", MANIFEST).stdout.strip():
            _git(root, "add", MANIFEST)
            _git(root, "commit", "-q", "-m", "chore: manifiesto de sync")
            print("commit: chore: manifiesto de sync")
        if cmd_pin(root, indicar_siguiente=False) != 0:
            return 1
        _git(root, "add", *PIN_FILES)
        _git(root, "commit", "-q", "-m", "chore: pin AVALOS_SYNC_REF")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: git falló: {e.stderr.decode(errors='replace').strip() or e}", file=sys.stderr)
        print("       (si dice que falta user.name/user.email: git config --global user.name ... / user.email ...)", file=sys.stderr)
        return 1
    print("commit: chore: pin AVALOS_SYNC_REF")
    print("listo. Falta solo: git push   (si sale rechazado: git pull --no-rebase, NUNCA rebase: reescribiría el commit pineado)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="valida RUTAS vs helper + formato del manifiesto")
    g.add_argument("--pin", action="store_true", help="fija AVALOS_SYNC_REF al SHA de HEAD (tras commitear el manifiesto)")
    g.add_argument("--release", action="store_true", help="manifiesto + pin + los dos commits (sin push)")
    a = ap.parse_args()
    root = _root()
    if a.release:
        return cmd_release(root)
    return cmd_check(root) if a.check else cmd_pin(root) if a.pin else cmd_generar(root)


if __name__ == "__main__":
    sys.exit(main())
