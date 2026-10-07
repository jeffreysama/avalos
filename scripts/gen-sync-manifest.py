#!/usr/bin/env python3
"""Manifiesto de checksums para `sync-system-files` (scripts/avalos-update-helper).

    python3 scripts/gen-sync-manifest.py           # regenera configs/MANIFEST.sha256
    python3 scripts/gen-sync-manifest.py --check   # valida listas, manifiesto y commit pineado (lo corre CI)
    python3 scripts/gen-sync-manifest.py --pin     # fija AVALOS_SYNC_REF = HEAD
    python3 scripts/gen-sync-manifest.py --release # pasos 2 y 3 de abajo de una vez (sin push)
    python3 scripts/gen-sync-manifest.py --verify-remote  # post-push: baja los archivos al SHA pineado desde GitHub y los compara

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
También se puede cortar desde GitHub: Actions → "Sync release" → Run workflow (solo en main).
Hace --release, valida, pushea (sin rebase) y corre --verify-remote; ahí la compuerta humana es
el botón (más el aprobador del Environment `sync-release`, si se configura en Settings).
A mano son estos pasos, en este orden:
  1. commitear los cambios a los archivos de RUTAS
  2. python3 scripts/gen-sync-manifest.py
     git add configs/MANIFEST.sha256 && git commit -m "chore: manifiesto de sync"
  3. python3 scripts/gen-sync-manifest.py --pin
     git commit -am "chore: pin AVALOS_SYNC_REF"
  4. git push        (el commit pineado tiene que estar en GitHub antes del primer sync)
     Si el push sale rechazado: `git pull --no-rebase` (un rebase reescribe el commit
     pineado y ese SHA dejaría de existir → sync fallaría cerrado).
  5. python3 scripts/gen-sync-manifest.py --verify-remote   (opcional: lo que bajará sync, desde GitHub)

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
import time
import urllib.request
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
    "scripts/avalos-doctor",
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
    "configs/avalos-doctor.desktop",
    "configs/avalos-doctor.svg",
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
_REPO_RAW_RE = re.compile(r'^REPO_RAW\s*=\s*f?"(https://raw\.githubusercontent\.com/[^/"\s]+/[^/"\s]+)/', re.M)


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


def _rutas_del_helper_texto(texto: str) -> list[str]:
    tree = ast.parse(texto)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "cmd_sync_system_files":
            for nodo in ast.walk(fn):
                if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                        and isinstance(nodo.targets[0], ast.Name) and nodo.targets[0].id == "manifest"
                        and isinstance(nodo.value, ast.List)):
                    return [e.elts[0].value for e in nodo.value.elts]  # type: ignore[attr-defined]
    raise RuntimeError("no encontré `manifest = [...]` dentro de cmd_sync_system_files")


def _rutas_del_helper(root: Path) -> list[str]:
    return _rutas_del_helper_texto((root / HELPER).read_text(encoding="utf-8"))


def _verificar_ref(root: Path, ref: str, rutas: list[str] | None = None) -> list[str]:
    """Problemas de `ref` como commit sincronizable: tiene que traer MANIFEST.sha256,
    listar exactamente `rutas` (por defecto las de HEAD), y cada hash tiene que coincidir con
    el archivo de ESE commit."""
    rutas = RUTAS if rutas is None else rutas
    corto = ref[:12]
    m = _git(root, "show", f"{ref}:{MANIFEST}", check=False)
    if m.returncode != 0:
        return [f"{MANIFEST} no existe en {corto} — sync-system-files fallaría cerrado "
                "(commiteá el manifiesto ANTES de pinear)"]
    try:
        hashes = _parse_manifest(m.stdout.decode("utf-8"))
    except ValueError as e:
        return [f"{MANIFEST} en {corto}: {e}"]
    if set(hashes) != set(rutas):
        return [f"{MANIFEST} en {corto} no lista exactamente RUTAS — regenerá y commiteá"]
    malos = []
    for r in rutas:
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
    # RUTAS pudo crecer DESPUÉS del pin: el commit pineado se valida contra las RUTAS que tenía él (el
    # `manifest` de su propio helper), no contra las de HEAD. Contra las de HEAD, agregar un archivo
    # sincronizable dejaría --check en rojo hasta cortar la release, y sync-release.yml corre --check ANTES.
    rutas_ref = None
    h = _git(root, "show", f"{pin}:{HELPER}", check=False)
    if h.returncode == 0:
        try:
            rutas_ref = _rutas_del_helper_texto(h.stdout.decode("utf-8"))
        except (RuntimeError, SyntaxError, UnicodeDecodeError):
            rutas_ref = None  # helper ilegible en ese commit: se cae a las RUTAS de HEAD (más estricto)
    problemas = _verificar_ref(root, pin, rutas_ref)
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
                # aviso, no error: RUTAS puede crecer (o achicarse) en un commit y el manifiesto se rehace al
                # cortar la release. Que algo así NO se pueda pinear lo garantizan --pin/--release
                # (_verificar_ref de HEAD) y --verify-remote.
                faltan = sorted(set(RUTAS) - set(hashes))
                sobran = sorted(set(hashes) - set(RUTAS))
                print(f"aviso: {MANIFEST} no lista exactamente RUTAS (faltan: {', '.join(faltan) or '—'}; "
                      f"sobran: {', '.join(sobran) or '—'}) — se rehace al cortar release")
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


def _http_get(url: str, intentos: int = 5, espera: float = 3.0) -> bytes:
    """GET con reintentos: recién pusheado, raw.githubusercontent.com puede tardar unos segundos."""
    ultimo: Exception | None = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "avalos-gen-sync-manifest"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except OSError as e:  # URLError, HTTPError y timeouts heredan de OSError
            ultimo = e
            if i + 1 < intentos:
                time.sleep(espera)
    raise OSError(f"{url}: {ultimo}")


def cmd_verify_remote(root: Path, raw_base: str | None = None) -> int:
    """Lo que hará sync-system-files en un sistema instalado, pero desde acá: baja de GitHub el
    manifiesto y cada archivo de RUTAS AL SHA PINEADO y los compara. Para correr tras el push."""
    pines = [_PIN_RE.search((root / p).read_text(encoding="utf-8")) for p in PIN_FILES]
    valores = {m.group(2) for m in pines if m}
    pin = next(iter(valores)) if all(pines) and len(valores) == 1 else ""
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        print(f"ERROR: AVALOS_SYNC_REF tiene que ser el mismo SHA de 40 hex en {', '.join(PIN_FILES)} (¿release sin cortar?)", file=sys.stderr)
        return 1
    if raw_base is None:
        mo = _REPO_RAW_RE.search((root / HELPER).read_text(encoding="utf-8"))
        if not mo:
            print(f"ERROR: no encontré REPO_RAW en {HELPER}", file=sys.stderr)
            return 1
        raw_base = mo.group(1)
    base = f"{raw_base.rstrip('/')}/{pin}"
    try:
        remoto = _parse_manifest(_http_get(f"{base}/{MANIFEST}").decode("utf-8"))
    except (OSError, ValueError) as e:  # UnicodeDecodeError es ValueError
        print(f"ERROR: no pude leer {MANIFEST} de {base}: {e}", file=sys.stderr)
        return 1
    problemas = []
    if set(remoto) != set(RUTAS):
        problemas.append(f"{MANIFEST} remoto no lista exactamente RUTAS")
    for r in RUTAS:
        try:
            real = _sha(_http_get(f"{base}/{r}", intentos=3))
        except OSError as e:
            problemas.append(f"{r}: no se pudo bajar ({e})")
            continue
        if real != remoto.get(r):
            problemas.append(f"{r}: el hash de lo servido ({real[:12]}) no coincide con el manifiesto")
    for e in problemas:
        print(f"ERROR: {e}", file=sys.stderr)
    if not problemas:
        print(f"ok: los {len(RUTAS)} archivos de RUTAS bajados de {base} coinciden con su manifiesto")
    return 1 if problemas else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="valida RUTAS vs helper + formato del manifiesto")
    g.add_argument("--pin", action="store_true", help="fija AVALOS_SYNC_REF al SHA de HEAD (tras commitear el manifiesto)")
    g.add_argument("--release", action="store_true", help="manifiesto + pin + los dos commits (sin push)")
    g.add_argument("--verify-remote", action="store_true", help="baja RUTAS de GitHub al SHA pineado y las compara con el manifiesto (tras el push)")
    ap.add_argument("--raw-base", metavar="URL", help="solo con --verify-remote: base alternativa a la REPO_RAW del helper (tests)")
    a = ap.parse_args()
    if a.raw_base and not a.verify_remote:
        ap.error("--raw-base solo se usa con --verify-remote")
    root = _root()
    if a.verify_remote:
        return cmd_verify_remote(root, a.raw_base)
    if a.release:
        return cmd_release(root)
    return cmd_check(root) if a.check else cmd_pin(root) if a.pin else cmd_generar(root)


if __name__ == "__main__":
    sys.exit(main())
