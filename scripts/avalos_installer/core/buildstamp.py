"""Sello de build de la ISO: leerlo y copiarlo al sistema instalado.

Lo escribe el CI al armar la ISO (scripts/gen-build-stamp.py) en /usr/share/avalos/configs/:
  avalos-build         AVALOS_BUILD=AAAA.MM.DD-<commit>, AVALOS_COMMIT, AVALOS_COMMIT_DATE
  avalos-scripts.tsv   nombre, commit, fecha y sha256 de cada script de la ISO
El instalador deja el build en el BUILD_ID del os-release (Fastfetch lo muestra) y copia ambos archivos a
/usr/share/avalos/ para que `avalos-version` y el Doctor sepan de qué ISO viene el sistema. Una ISO sin sello
(build de desarrollo) no es un error: todo sigue funcionando y el build figura como desconocido.
"""
from __future__ import annotations

import re

from avalos_installer.core.config import read_config

STAMP_BUILD = "avalos-build"
STAMP_SCRIPTS = "avalos-scripts.tsv"
TARGET_BUILD = "usr/share/avalos/build"
TARGET_SCRIPTS = "usr/share/avalos/scripts.tsv"

# Termina en una línea del os-release (BUILD_ID=…): solo caracteres inofensivos, sin comillas ni saltos de línea.
BUILD_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")


def parse_stamp(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"')
    return out


def build_id() -> str | None:
    """El build de la ISO, o None si no hay sello o no tiene un formato seguro."""
    value = parse_stamp(read_config(STAMP_BUILD) or "").get("AVALOS_BUILD", "")
    return value if BUILD_ID_RE.match(value) else None


def install_stamp(session) -> bool:
    """Copia el sello al sistema instalado. False (sin fallar) si la ISO no trae uno válido."""
    if not build_id():
        session.log(session.t("log-build-stamp-missing"), "info")
        return False
    session.write_file(TARGET_BUILD, read_config(STAMP_BUILD))
    scripts = read_config(STAMP_SCRIPTS)
    if scripts:
        session.write_file(TARGET_SCRIPTS, scripts)
    return True
