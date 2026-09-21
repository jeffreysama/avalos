"""
network/connectivity.py — chequeo de conectividad del instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 532-539). Sin cambios de lógica.

NOTA: esto es solo el chequeo binario "hay internet sí/no" (ping) que ya existía y
que el instalador ya NO usa: el paso "net" y la comprobación previa del equipo usan
el diagnóstico por capas de network/diagnose.py (sin enlace / sin IP / sin salida /
DNS / portal cautivo / hora / mirrors caídos). Se deja por compatibilidad.
"""

from __future__ import annotations

from avalos_installer.core.shell import run_command


def check_internet() -> bool:
    rc4, _, _ = run_command(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=6)
    if rc4 == 0:
        return True
    rc6, _, _ = run_command(["ping6", "-c", "1", "-W", "3", "2001:4860:4860::8888"], timeout=6)
    return rc6 == 0
