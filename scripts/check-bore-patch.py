#!/usr/bin/env python3
"""check-bore-patch.py — revisa el parche BORE antes de aplicarlo al kernel que AvalOS firma y publica.

POR QUÉ. build-kernel.yml bajaba `…/CachyOS/kernel-patches/master/<X.Y>/sched/0001-bore.patch` (rama MUTABLE, sin
checksum: 'SKIP'), lo aplicaba al kernel y el resultado se firmaba con la clave de AvalOS y llegaba a todos los
equipos con el `pacman -Syu` siguiente. Un commit malicioso (o una cuenta comprometida) en ese repositorio ajeno
acababa como código de kernel firmado por AvalOS en la siguiente corrida semanal, sin que nadie lo viera.

QUÉ HACE (todo sin red; el workflow descarga el archivo y llama a este script):
  1. Alcance. Un parche de planificador toca el planificador. Se rechaza si toca archivos fuera de una lista
     blanca (kernel/sched/, include/linux/sched*, init/Kconfig, kernel/Kconfig.hz|preempt, kernel/fork.c|exit.c,
     kernel/futex/, kernel/sysctl.c), si renombra, borra o cambia permisos, si trae un parche binario, si usa rutas
     absolutas o con «..», o si es desproporcionado (tamaño, líneas añadidas/quitadas).
  2. Patrones que un planificador no necesita (credenciales, syscalls nuevas, módulos de usuario, ensamblador inline,
     kprobes/ftrace/kallsyms…) en las líneas AÑADIDAS. Es una red de seguridad, no una prueba: lo que no atrapa lo ve
     un humano gracias a (3).
  3. Pin de revisión humana (pkgs/linux-avalos/bore.pin): sha256 del parche tal como se revisó, por X.Y. Si el parche
     cambió desde la última revisión, el resumen del job lo dice y deja listo el comando para fijar el nuevo hash.
       mode=warn     (por defecto) se aplica igual y se avisa (no rompe el build semanal si CachyOS actualiza BORE);
       mode=enforce  un parche que no coincide con el pin NO se aplica (se compila sin BORE) y, para que BORE siga
                     funcionando con lo revisado, el workflow baja el parche del COMMIT fijado en el pin, no de master.

Uso:
  check-bore-patch.py PARCHE --version X.Y [--pin ARCHIVO] [--summary ARCHIVO]   → 0 aplicar · 1 rechazado
  check-bore-patch.py --print-ref --version X.Y [--pin ARCHIVO]                   → imprime «master» o el commit fijado
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

MAX_BYTES = 160 * 1024          # el parche real pesa ~40 KB
MAX_ADDED = 4000                # real: ~730
MAX_REMOVED = 400               # real: ~13
MAX_FILES = 40                  # real: 13

# archivos que un parche de planificador tiene motivos para tocar
ALLOWED_PATHS = re.compile(
    r"^(?:"
    r"include/linux/sched\.h|include/linux/sched/[A-Za-z0-9_.-]+\.h|"
    r"init/Kconfig|kernel/Kconfig\.(?:hz|preempt)|"
    r"kernel/(?:exit|fork|sysctl)\.c|kernel/futex/[A-Za-z0-9_.-]+\.[ch]|"
    r"kernel/sched/[A-Za-z0-9_.-]+"
    r")$"
)

# líneas AÑADIDAS que un planificador no necesita. Ojo: register_sysctl*/debugfs_create_* SÍ las usa BORE de verdad.
SUSPICIOUS = re.compile(
    r"commit_creds|prepare_kernel_cred|override_creds|revert_creds|set_cred|cap_raise|\bcapable\s*\(|ns_capable|"
    r"\bsetuid\b|\bseteuid\b|call_usermodehelper|request_module|filp_open|kernel_write|kernel_read_file|"
    r"SYSCALL_DEFINE|__x64_sys_|__ia32_sys_|ksys_|kallsyms_lookup_name|register_kprobe|register_ftrace|ftrace_set_filter|"
    r"text_poke|set_memory_(?:x|rw)|\basm\s+volatile|\b__asm__\b|\bwrmsr|\brdmsr",
    re.IGNORECASE,
)

# fullmatch + [0-9]: con `^…$` y match(), `$` también acepta un salto de línea final y \d acepta dígitos Unicode
PIN_ENTRY = re.compile(r"(?P<ver>[0-9]+\.[0-9]+)\s+(?P<sha>[0-9a-f]{64})\s+(?P<commit>[0-9a-f]{40})")
VERSION = re.compile(r"[0-9]+\.[0-9]+")


class Pin:
    def __init__(self, mode: str = "warn", entries: dict[str, tuple[str, str]] | None = None):
        self.mode = mode
        self.entries = entries or {}


def load_pin(path: str | None) -> Pin:
    """pkgs/linux-avalos/bore.pin. Ausente o ilegible → mode=warn y sin entradas (nunca rompe el build); un mode= desconocido → enforce."""
    if not path:
        return Pin()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return Pin()
    mode, entries = "warn", {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("mode="):
            value = line[5:].strip()
            if value not in ("warn", "enforce"):
                print(f"::warning::bore.pin: mode={value!r} no existe (warn|enforce); se trata como enforce", file=sys.stderr)
                value = "enforce"      # un typo («enforced») no debe degradar la seguridad en silencio
            mode = value
            continue
        m = PIN_ENTRY.fullmatch(line)
        if m:
            entries[m["ver"]] = (m["sha"], m["commit"])
    return Pin(mode, entries)


def print_ref(version: str, pin: Pin) -> str:
    """Qué ref de CachyOS/kernel-patches descargar: el commit revisado si el pin es obligatorio, si no 'master'."""
    if pin.mode == "enforce" and version in pin.entries:
        return pin.entries[version][1]
    return "master"


def inspect(data: bytes) -> tuple[list[str], dict]:
    """Devuelve (problemas, info). Problemas = motivos de rechazo duro."""
    problems: list[str] = []
    info = {"files": [], "added": 0, "removed": 0, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if not data:
        return ["el parche está vacío"], info
    if len(data) > MAX_BYTES:
        problems.append(f"pesa {len(data)} bytes (tope {MAX_BYTES})")
    text = data.decode("utf-8", errors="replace")
    if "\x00" in text:
        problems.append("contiene bytes nulos (no es un parche de texto)")
    if re.search(r"^GIT binary patch", text, re.M) or re.search(r"^Binary files .* differ", text, re.M):
        problems.append("contiene un parche binario")
    for marker in ("rename from ", "rename to ", "copy from ", "copy to ", "old mode ", "new mode ", "deleted file mode ", "similarity index "):
        if re.search(r"^" + re.escape(marker), text, re.M):
            problems.append(f"usa «{marker.strip()}» (renombrar/copiar/borrar/cambiar permisos no es lo que hace BORE)")
    headers = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M)
    if not headers:
        problems.append("no tiene ninguna cabecera «diff --git»")
    info["files"] = sorted({b for _a, b in headers})
    if len(headers) > MAX_FILES:
        problems.append(f"toca {len(headers)} archivos (tope {MAX_FILES})")
    for a, b in headers:
        for p in (a, b):
            if p.startswith("/") or ".." in p.split("/") or "\\" in p:
                problems.append(f"ruta sospechosa: {p!r}")
        if a != b:
            problems.append(f"la cabecera cambia de nombre {a!r} → {b!r}")
        if not ALLOWED_PATHS.match(b):
            problems.append(f"toca un archivo fuera del planificador: {b}")
    # Líneas de contenido del diff. Solo el PAR exacto «--- a/…» + «+++ b/…» es cabecera: excluir todo lo que empiece
    # con «+++» dejaría pasar una línea añadida «++payload();» sin mirarla.
    added, removed = [], []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if (re.fullmatch(r"--- (?:a/\S+|/dev/null)", line) and i + 1 < len(lines)
                and re.fullmatch(r"\+\+\+ (?:b/\S+|/dev/null)", lines[i + 1])):
            i += 2
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
        i += 1
    info["added"], info["removed"] = len(added), len(removed)
    if len(added) > MAX_ADDED:
        problems.append(f"añade {len(added)} líneas (tope {MAX_ADDED})")
    if len(removed) > MAX_REMOVED:
        problems.append(f"quita {len(removed)} líneas (tope {MAX_REMOVED})")
    for line in added:
        m = SUSPICIOUS.search(line)
        if m:
            problems.append(f"línea añadida con un patrón que un planificador no necesita ({m.group(0)!r}): {line.strip()[:90]!r}")
            break
    return problems, info


def summary_block(version: str, info: dict, pin: Pin, verdict: str, notes: list[str]) -> str:
    entry = pin.entries.get(version)
    lines = [f"### Parche BORE {version}: {verdict}", "",
             f"- sha256: `{info['sha256']}`", f"- tamaño: {info['bytes']} bytes · +{info['added']} / −{info['removed']} líneas · {len(info['files'])} archivos",
             f"- pin (mode={pin.mode}): " + (f"revisado `{entry[0][:12]}…`" if entry else "sin entrada para esta versión")]
    lines += [f"- {n}" for n in notes]
    lines += ["", "<details><summary>archivos que toca</summary>", "", *[f"- `{f}`" for f in info["files"]], "", "</details>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="revisa el parche BORE antes de aplicarlo")
    ap.add_argument("patch", nargs="?")
    ap.add_argument("--version", required=True)
    ap.add_argument("--pin")
    ap.add_argument("--summary")
    ap.add_argument("--print-ref", action="store_true")
    args = ap.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        print(f"::error::versión inválida: {args.version!r}", file=sys.stderr)
        return 2
    pin = load_pin(args.pin)
    if args.print_ref:
        print(print_ref(args.version, pin))
        return 0
    if not args.patch:
        ap.error("falta el archivo del parche")
    try:
        data = Path(args.patch).read_bytes()
    except OSError as e:
        print(f"::error::no se pudo leer el parche: {e}")
        return 1
    problems, info = inspect(data)
    notes: list[str] = []
    entry = pin.entries.get(args.version)
    mismatch = entry is None or entry[0] != info["sha256"]
    new_pin = f"{args.version} {info['sha256']} <commit de CachyOS/kernel-patches revisado>"
    if mismatch:
        why = "no hay pin para esta versión" if entry is None else "el parche CAMBIÓ desde la última revisión"
        notes.append(f"{why}. Tras revisarlo, fíjalo en pkgs/linux-avalos/bore.pin:  `{new_pin}`")
    if problems:
        verdict = "RECHAZADO (se compila SIN BORE)"
        notes = [f"❌ {p}" for p in problems] + notes
        print(f"::error::parche BORE rechazado: {'; '.join(problems)}")
        rc = 1
    elif mismatch and pin.mode == "enforce":
        verdict = "NO COINCIDE con el pin y mode=enforce (se compila SIN BORE)"
        print(f"::error::parche BORE {args.version} no coincide con bore.pin (mode=enforce): sha256 {info['sha256']}")
        rc = 1
    elif mismatch:
        verdict = "aplicado con AVISO (cambió desde la última revisión)"
        print(f"::warning::parche BORE {args.version} sin revisar (sha256 {info['sha256']}); revisarlo y fijarlo en bore.pin")
        rc = 0
    else:
        verdict = "OK (coincide con el pin revisado)"
        rc = 0
    block = summary_block(args.version, info, pin, verdict, notes)
    print(block)
    if args.summary:
        try:
            with open(args.summary, "a", encoding="utf-8") as f:
                f.write(block + "\n")
        except OSError as e:
            print(f"::warning::no se pudo escribir el resumen: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
