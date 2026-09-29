"""
core/shell.py — utilidad de bajo nivel compartida por todos los módulos
del instalador modular.

Extraído de skill_instalar_usb.py (era `_ejecutar`, línea 254). Se renombra
a público (`run_command`, antes `ejecutar`) porque deja de ser un helper
privado de un solo archivo y pasa a ser la implementación compartida que
hardware/, disk/, network/ y system/ importan. El comportamiento es
idéntico al original, no se tocó la lógica.
"""

from __future__ import annotations

import subprocess


def run_command(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Corre un comando y devuelve (returncode, stdout, stderr).

    Nunca lanza excepción: comando no encontrado, timeout, y cualquier otro
    error quedan codificados en el returncode (-1, -2, -3 respectivamente)
    con el mensaje en stderr, para que el llamador no necesite try/except.
    """
    try:
        # stdin=DEVNULL: un prompt interactivo recibe EOF en vez de quedarse esperando en la
        # terminal desde la que se lanzó el instalador (mismo criterio que core/runner.py).
        # errors="replace": un byte no-UTF-8 (p. ej. el modelo de un disco en lsblk) no debe
        # tumbar toda la salida con UnicodeDecodeError -> rc -3 -> "no hay discos".
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, errors="replace",
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"No encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", "Timeout"
    except Exception as e:
        return -3, "", str(e)
