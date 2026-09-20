#!/usr/bin/env python3
"""
validate_app_consistency.py — coherencia entre lo que las configs REFERENCIAN
y lo que el instalador/ISO realmente INSTALAN.

Por qué existe: tres fallos reales que ningún parser de sintaxis detecta,
porque cada archivo era "válido" por separado:
  · Los atajos SUPER+ALT_L+S / +U (Store y Update) nunca disparaban: en un
    bind de Hyprland, ALT_L es el nombre de una TECLA (sirve para bindear la
    tecla Alt sola con { release = true }), no un modificador. Los
    modificadores válidos son SUPER, SHIFT, CTRL y ALT.
  · AvalOS Update se instalaba en /usr/local/bin pero no tenía .desktop: no
    aparecía en rofi ni en ningún menú, así que para el usuario "no estaba
    instalado".
  · Apps de la Store sin ícono real (emoji) porque el nombre de ícono no
    coincidía con ninguno del tema.

Chequeos:
  binds    hl.bind(...) de configs/hyprland/hyprland.lua y del template:
           modificadores válidos y combinaciones duplicadas.
  apps     cada avalos-<x> que el template ejecuta o para el que define una
           window_rule: existe scripts/avalos-<x>, está en la lista del
           instalador modular, del legado y del workflow; las que deben
           aparecer en el lanzador (settings, store, update) tienen su
           .desktop en configs/ y el instalador lo copia.
  catalog  configs/avalos-store-catalog.json: campos, ids únicos, source.
           Con AVALOS_ICON_THEME_DIR=<carpeta Papirus> comprueba además que
           cada app resuelva un ícono del tema (por icon_name, exec, package
           o id) — o sea, que no caiga al emoji sin red.

Uso:  python3 scripts/validate_app_consistency.py
      AVALOS_ICON_THEME_DIR=/usr/share/icons/Papirus python3 scripts/validate_app_consistency.py
Salida: 0 = todo bien, 1 = hay errores (los avisos no fallan).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "configs" / "hyprland" / "hyprland.lua"
TEMPLATE = ROOT / "configs" / "hyprland" / "hyprland_conf_lua.template"
CATALOG = ROOT / "configs" / "avalos-store-catalog.json"
MODS = {"SUPER", "SHIFT", "CTRL", "ALT"}
NEEDS_DESKTOP = {"avalos-settings", "avalos-store", "avalos-update"}
FLAG_WORDS = ("long_press", "release", "repeating", "locked", "mouse", "click", "drag", "non_consuming", "transparent", "ignore_mods")

fails: list[str] = []
warns: list[str] = []


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def bad(msg: str, detail: str = "") -> None:
    fails.append(msg)
    print(f"  FAIL  {msg}")
    for ln in detail.splitlines():
        print(f"          {ln}")


def warn(msg: str) -> None:
    warns.append(msg)
    print(f"  aviso {msg}")


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# ── Lua: extraer los hl.bind(...) ─────────────────────────────────────────────
def _strip_comments(src: str) -> str:
    out = []
    for line in src.splitlines():
        in_s, q, cut = False, "", len(line)
        for i, c in enumerate(line):
            if in_s:
                if c == q and line[i - 1] != "\\":
                    in_s = False
            elif c in "\"'":
                in_s, q = True, c
            elif line.startswith("--", i):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def _split_top(text: str, sep: str) -> list[str]:
    """Parte `text` por `sep` fuera de comillas y paréntesis/llaves."""
    parts, buf, depth, in_s, q, i = [], "", 0, False, "", 0
    while i < len(text):
        c = text[i]
        if in_s:
            buf += c
            if c == q and text[i - 1] != "\\":
                in_s = False
        elif c in "\"'":
            in_s, q = True, c
            buf += c
        elif c in "({[":
            depth += 1
            buf += c
        elif c in ")}]":
            depth -= 1
            buf += c
        elif depth == 0 and text.startswith(sep, i):
            parts.append(buf)
            buf = ""
            i += len(sep)
            continue
        else:
            buf += c
        i += 1
    parts.append(buf)
    return parts


def _call_args(src: str, start: int) -> str:
    """Texto entre los paréntesis del llamado que abre en `start` (el '(')."""
    depth, in_s, q = 0, False, ""
    for i in range(start, len(src)):
        c = src[i]
        if in_s:
            if c == q and src[i - 1] != "\\":
                in_s = False
        elif c in "\"'":
            in_s, q = True, c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return src[start + 1:]


def parse_binds(path: Path) -> list[tuple[int, str, str, str]]:
    """[(línea, combo, flags, texto_del_llamado)] — los combos dinámicos (con variables
    que no son literales, ej. el bucle de workspaces) se omiten."""
    src = _strip_comments(path.read_text(encoding="utf-8"))
    env = dict(re.findall(r'^\s*local\s+(\w+)\s*=\s*"([^"]*)"', src, re.M))
    res = []
    for m in re.finditer(r"\bhl\.bind\(", src):
        args = _call_args(src, m.end() - 1)
        pieces = _split_top(args, ",")
        combo_parts = [p.strip() for p in _split_top(pieces[0], "..")]
        combo = ""
        for cp in combo_parts:
            if len(cp) >= 2 and cp[0] in "\"'" and cp[-1] == cp[0]:
                combo += cp[1:-1]
            elif cp in env:
                combo += env[cp]
            else:
                combo = None
                break
        if combo is None:
            continue
        flags = ",".join(sorted(w for w in FLAG_WORDS if re.search(rf"\b{w}\b", ",".join(pieces[2:]))))
        res.append((src[:m.start()].count("\n") + 1, combo, flags, args))
    return res


# ── 1) atajos ─────────────────────────────────────────────────────────────────
def check_binds() -> None:
    for f in (LIVE, TEMPLATE):
        if not f.exists():
            continue
        errs, seen = [], {}
        binds = parse_binds(f)
        for line, combo, flags, _args in binds:
            toks = [t.strip() for t in combo.split("+")]
            for t in toks[:-1]:
                if t.upper() not in MODS:
                    base = re.fullmatch(r"(SUPER|SHIFT|CTRL|CONTROL|ALT)_[LR]", t, re.I)
                    hint = (f" — '{t}' es una TECLA, no un modificador: usá {base.group(1).upper().replace('CONTROL', 'CTRL')}"
                            if base else " — modificadores válidos: SUPER, SHIFT, CTRL, ALT")
                    errs.append(f"línea {line}: \"{combo}\": modificador inválido '{t}'{hint}")
            key = (frozenset(t.upper() for t in toks[:-1]), toks[-1].lower(), flags)
            if key in seen:
                errs.append(f"línea {line}: \"{combo}\" duplica el atajo de la línea {seen[key]}")
            seen.setdefault(key, line)
        if errs:
            bad(f"binds: {rel(f)}", "\n".join(errs))
        else:
            ok(f"binds: {rel(f)} ({len(binds)} atajos literales, modificadores válidos, sin duplicados)")


# ── 2) apps referenciadas vs lo que se instala ───────────────────────────────────
def check_apps() -> None:
    if not TEMPLATE.exists():
        return
    src = _strip_comments(TEMPLATE.read_text(encoding="utf-8"))
    used = set(re.findall(r'exec_cmd\(\s*["\'](avalos-[a-z-]+)', src)) | set(re.findall(r'class\s*=\s*"(avalos-[a-z-]+)"', src))
    optimize = (ROOT / "scripts/avalos_installer/system/optimize.py").read_text(encoding="utf-8")
    legacy = (ROOT / "scripts/skill_instalar_usb.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/build-iso.yml").read_text(encoding="utf-8")
    m = re.search(r"for _s in ([a-z\- ]+); do", workflow)
    wf_list = set(m.group(1).split()) if m else set()
    for app in sorted(used):
        errs = []
        if not (ROOT / "scripts" / app).is_file():
            errs.append(f"no existe scripts/{app}")
        for label, text in (("instalador modular (optimize.py)", optimize), ("instalador legado", legacy)):
            if f'"{app}"' not in text:
                errs.append(f"no está en la lista de scripts del {label}")
        if app not in wf_list:
            errs.append("no está en la lista 'for _s in …' de build-iso.yml (no llegaría al live)")
        if app in NEEDS_DESKTOP:
            desk = ROOT / "configs" / f"{app}.desktop"
            if not desk.is_file():
                errs.append(f"falta configs/{app}.desktop: no aparece en rofi ni en ningún menú")
            else:
                reads = rf'\(\s*["\'](?:scripts/)?{re.escape(app)}\.desktop["\']'
                if not re.search(r"read_config" + reads, optimize):
                    errs.append(f"el instalador modular no lee/copia {app}.desktop (falta read_config(\"{app}.desktop\"))")
                if not re.search(r"_leer_config\s*" + reads, legacy):
                    errs.append(f"el instalador legado no lee/copia {app}.desktop")
        elif not (ROOT / "configs" / f"{app}.desktop").is_file():
            warn(f"{app}: sin .desktop (solo se abre por atajo/menú de Settings)")
        if errs:
            bad(f"apps: {app}", "\n".join(errs))
        else:
            ok(f"apps: {app} — script, listas del instalador/legado/workflow" + (" y .desktop" if app in NEEDS_DESKTOP else ""))


# ── 3) catálogo de la Store ──────────────────────────────────────────────────────
def check_catalog() -> None:
    if not CATALOG.exists():
        return
    try:
        apps = json.loads(CATALOG.read_text(encoding="utf-8"))
    except ValueError as e:
        bad(f"catalog: {rel(CATALOG)}", str(e))
        return
    errs, ids = [], set()
    for i, a in enumerate(apps):
        who = a.get("id", f"#{i}")
        for k in ("id", "name", "category", "source", "package", "icon"):
            if not a.get(k):
                errs.append(f"{who}: falta '{k}'")
        if a.get("source") not in ("pacman", "aur", "flatpak"):
            errs.append(f"{who}: source inválido {a.get('source')!r}")
        if a.get("id") in ids:
            errs.append(f"{who}: id duplicado")
        ids.add(a.get("id"))
        for k in ("flathub_id", "icon_name"):
            if k in a and not (isinstance(a[k], str) and a[k]):
                errs.append(f"{who}: '{k}' debe ser un texto no vacío")
    (bad if errs else lambda m, d="": ok(m))(f"catalog: {rel(CATALOG)} ({len(apps)} apps)", "\n".join(errs))

    theme = os.environ.get("AVALOS_ICON_THEME_DIR")
    if not theme:
        warn("catalog: sin AVALOS_ICON_THEME_DIR no se comprueba que cada app tenga ícono en el tema")
        return
    root = Path(theme)
    missing = []
    for a in apps:
        names = [n for n in dict.fromkeys([a.get("icon_name"), a.get("exec"), a.get("package"), a.get("id")]) if n]
        if not any((root / size / "apps" / f"{n}.{ext}").is_file() for n in names for size in ("64x64", "48x48", "32x32") for ext in ("svg", "png")):
            missing.append(f"{a['id']} (probé: {', '.join(names)})")
    if missing:
        bad("catalog: apps sin ícono en el tema (caerían al emoji sin red)", "\n".join(missing) + "\n→ agregá icon_name con el nombre del ícono del tema")
    else:
        ok(f"catalog: las {len(apps)} apps resuelven un ícono en {theme}")


def main() -> int:
    for fn in (check_binds, check_apps, check_catalog):
        fn()
    print(f"\n{len(fails)} con error · {len(warns)} avisos")
    if fails:
        print("FALLARON:", *fails, sep="\n  - ")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
