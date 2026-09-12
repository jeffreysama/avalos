"""
avalos_installer/__main__.py — punto de entrada del instalador modular.

Permite correr el paquete con `python3 -m avalos_installer`. Réplica
fiel del bloque `if __name__ == "__main__":` de skill_instalar_usb.py
(líneas 5051-5108): mismo chequeo de root con el mismo mensaje, mismas
tres variables de entorno de WebKit, mismo GLib.set_prgname("avalos-install")
envuelto en try/except, misma geometría de ventana (960×640,
min_size 800×540, background #1a1b26), mismo patrón de guard con
_lock/_thread_started antes de lanzar el hilo al cargar la ventana, mismo
manejo de excepción si pywebview/webkit2gtk-4.1 no está instalado.

Única diferencia real respecto al original: el target del hilo es
core.install.run_installation en vez de VentanaInstalador._run_instalacion,
y el bridge es ui.api.InstallerAPI en vez de InstaladorAPI — misma forma,
implementación modular. También se ajustó el texto del mensaje de "sin
root" para reflejar que el comando real ahora es `avalos-install` (el
wrapper de build-iso.yml ya resuelve el `python3 -m avalos_installer` por
dentro), no `python avalos-install` como decía el original.

NO PROBADO CON PYWEBVIEW REAL: este sandbox no tiene GTK/webkit2gtk-4.1
ni servidor gráfico, así que esto se verificó por lectura línea por línea
contra el main() original (que sí corre en producción), no por ejecución.
La prueba real es la que J. va a hacer con la ISO en hardware de verdad.
"""

from __future__ import annotations

import os
import sys
import threading

import webview

from avalos_installer.core.install import run_installation
from avalos_installer.core.session import InstallSession
from avalos_installer.ui.api import InstallerAPI
from avalos_installer.ui.html import build_html


def main() -> None:
    if os.geteuid() != 0:
        print("╔═══════════════════════════════════════════════════╗")
        print("║  AvalOS Installer necesita privilegios de root.   ║")
        print("╠═══════════════════════════════════════════════════╣")
        print("║  Ejecuta con:  sudo avalos-install                ║")
        print("║  O como root:  avalos-install                     ║")
        print("╚═══════════════════════════════════════════════════╝")
        sys.exit(1)

    os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
    os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
    os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"

    session = InstallSession()
    api = InstallerAPI(session)
    html = build_html()

    try:
        from gi.repository import GLib
        GLib.set_prgname("avalos-install")
    except Exception:
        pass

    win = webview.create_window(
        title="AvalOS — Instalador",
        html=html,
        js_api=api,
        width=960,
        height=640,
        min_size=(800, 540),
        resizable=True,
        background_color="#1a1b26",
    )
    session.window = win
    win.events.closed += session.on_close

    def _on_loaded():
        with session._lock:
            if session._thread_started:
                return
            session._thread_started = True
            session._config_ready.clear()
        t = threading.Thread(target=run_installation, args=(session,), daemon=True)
        t.start()

    win.events.loaded += _on_loaded

    try:
        webview.start(debug=os.environ.get("AVALOS_DEBUG") == "1")
    except Exception as e:
        print(f"ERROR al iniciar pywebview: {e}")
        print("Asegúrate de que webkit2gtk-4.1 esté instalado:")
        print("  pacman -S webkit2gtk-4.1 python-gobject")
        sys.exit(1)


if __name__ == "__main__":
    main()
