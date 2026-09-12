"""
ui/api.py — InstallerAPI: el puente JS↔Python de pywebview.

Extraído de InstaladorAPI en skill_instalar_usb.py (líneas 2349-2533).
Cada método público de esta clase se llama directo desde el JS embebido
en ui/html.py vía window.pywebview.api.<nombre>(...) — los nombres de
método SÍ le importan a JS, así que se renombraron TODOS a inglés (regla
del proyecto) y se actualizaron los 11 call-sites correspondientes en
ui/html.py en la misma sesión, para que ambos lados del puente queden
sincronizados. Nunca se cambian estos nombres en un solo lado sin el otro.

Mapeo de nombres (original → nuevo):
    set_language                  → set_language   (ya estaba en inglés)
    on_ready                      → on_ready        (ya estaba en inglés)
    iniciar_instalacion           → start_installation
    abortar_instalacion           → abort_installation
    abrir_terminal_particionado   → open_partitioning_terminal
    verificar_particionado_manual → check_manual_partitioning
    confirmar_root_manual         → confirm_manual_root
    reintentar                    → retry
    elegir_mirror                 → choose_mirror
    reiniciar_equipo              → reboot_system
    cerrar                        → close

Los dict que cruzan a JS (ej. el resultado de check_manual_partitioning)
mantienen sus claves tal cual el original ("candidatas_root",
"requiere_seleccion", "subvols_existentes", etc.) — son payload de datos,
no identificadores de código, mismo criterio que ya usa disk/discovery.py
(ver "es_arranque"/"tipo"/"particiones" en list_disks()). Cambiarlas
exigiría tocar el JS que las lee sin ganar nada a cambio.

DECISIÓN DE DISEÑO — de dónde sale el InstallContext: en el original,
VentanaInstalador era a la vez el bridge de API y el runner de la
instalación, así que iniciar_instalacion() escribía username/password/
etc. directo como atributos de self. Acá InstallSession (comportamiento)
e InstallContext (config) están separados de InstallerAPI (bridge), así
que start_installation() arma un InstallContext completo recién al
final, lo dejá en session.pending_context, y llama
session._config_ready.set(). El hilo de instalación (arrancado temprano,
al cargar la ventana — ver core/install.py) está bloqueado esperando ese
mismo evento desde el principio, exactamente como _run_instalacion()
esperaba con self._config_lista.wait(timeout=600) en el original —
incluido el caso de retry(), donde _config_ready ya está seteado de la
primera vez y el wait() de core.install.run_installation() vuelve de
inmediato, sin bloquear.

Los campos de "modo manual" en curso (candidatas, EFI detectada,
subvolúmenes existentes, root elegida) no son ni comportamiento
(InstallSession) ni config final (InstallContext) — son estado de flujo
del wizard, solo relevante mientras el usuario todavía está llenando el
formulario. Por eso viven como atributos privados de InstallerAPI mismo,
igual que vivían en VentanaInstalador en el original.

BUG encontrado y corregido durante la extracción: el reiniciar_equipo()
original loguea con self._t(...) — pero _t solo existe en VentanaInstalador
(self._v._t), no en InstaladorAPI. Nunca se manifestó porque solo se
ejecuta si systemctl reboot falla al lanzarse (Popen), pero era un
AttributeError latente. Acá usa session.t(...), que sí existe.
"""
from __future__ import annotations

import shutil
import subprocess
import threading

import translations
from avalos_installer.core.config import (
    DEFAULT_HOSTNAME, DEFAULT_KEYMAP, DEFAULT_LOCALE, DEFAULT_TIMEZONE,
    KEYMAPS, LOCALES,
)
from avalos_installer.core.context import InstallContext
from avalos_installer.core.install import run_installation
from avalos_installer.core.session import InstallSession
from avalos_installer.disk.discovery import detect_btrfs_subvolumes, detect_manual_partitions, list_disks
from avalos_installer.hardware.detection import is_uefi


class InstallerAPI:
    """Métodos expuestos al JavaScript del wizard."""

    def __init__(self, session: InstallSession):
        self.session = session
        # Estado de flujo del wizard en modo manual — ver docstring del módulo.
        self._manual_ready = False
        self._manual_efi = ""
        self._manual_root_candidates: list[dict] = []
        self._manual_existing_subvolumes: list[str] = []
        self._manual_root = ""

    def set_language(self, code: str) -> bool:
        """Llamado desde JS al elegir idioma. Guarda el código para
        usarlo al generar archivos de configuración (fastfetch, etc.)."""
        allowed = tuple(c for c, _ in translations.SUPPORTED_LANGS)
        if code in allowed:
            self.session._lang = code
            return True
        return False

    def on_ready(self) -> bool:
        """DOM listo: poblar discos y mostrar bienvenida."""
        disks = list_disks()
        self.session.render_disks(disks)
        return True

    def start_installation(self, username: str, password: str, hostname: str,
                            timezone: str, disk: str, bootloader: str, usb: bool,
                            locale: str = "", keymap: str = "", gaming: bool = False,
                            bore: bool = False, manual: bool = False) -> bool:
        """El usuario pulsó 'Instalar AvalOS' con configuración válida."""
        clean_username = username.strip()
        if not clean_username:
            return False

        if manual and not self._manual_ready:
            # JS dice modo manual pero Python nunca confirmó una detección
            # válida (check_manual_partitioning/confirm_manual_root) — no
            # arrancar la instalación con partición root vacía.
            return False

        valid_locales = {lc for lc, _ in LOCALES}
        valid_keymaps = {km for km, _ in KEYMAPS}

        ctx = InstallContext(
            username=clean_username,
            password=password,
            hostname=hostname.strip() or DEFAULT_HOSTNAME,
            timezone=timezone or DEFAULT_TIMEZONE,
            locale=locale if locale in valid_locales else DEFAULT_LOCALE,
            keymap=keymap if keymap in valid_keymaps else DEFAULT_KEYMAP,
            lang=self.session._lang,
            target_disk=disk,
            bootloader=bootloader if bootloader in ('grub', 'sd-boot', 'refind', 'none') else 'grub',
            usb_mode=bool(usb),
            manual_mode=bool(manual) and self._manual_ready,
            manual_efi_partition=self._manual_efi if manual else "",
            manual_root_partition=self._manual_root if manual else "",
            manual_existing_subvolumes=self._manual_existing_subvolumes if manual else [],
            install_gaming=bool(gaming),
            install_bore=bool(bore),
        )
        self.session.pending_context = ctx
        self.session._config_ready.set()
        return True

    def abort_installation(self) -> bool:
        self.session._aborted = True
        return True

    def open_partitioning_terminal(self) -> bool:
        """Modo manual: lanza una terminal real del live ISO (no dentro
        del webview — webkit2gtk no tiene terminal embebido) para que el
        usuario corra cfdisk/parted/mkfs a mano. Se prueban varios
        emuladores comunes en orden porque este módulo no puede confirmar
        cuál viene empaquetado en el airootfs del ISO (eso se decide en
        build-iso.yml) — así el botón no depende de adivinar uno solo y
        fallar en silencio si no está. Bloquea (subprocess.run, no Popen)
        hasta que el usuario cierre la terminal, para que el JS sepa
        cuándo volver a habilitar el wizard."""
        candidates = [
            ["foot"], ["kitty"], ["alacritty"],
            ["xterm"], ["konsole"], ["gnome-terminal"],
        ]
        for cmd in candidates:
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, check=False)
                    return True
                except Exception as e:
                    self.session.log(
                        self.session.t("log-terminal-launch-warn", term=cmd[0], e=e), "warn"
                    )
                    continue
        self.session.log(self.session.t("err-no-terminal-found"), "err")
        return False

    def check_manual_partitioning(self, disk: str) -> dict:
        """Modo manual: tras volver de la terminal, analiza lo que el
        usuario dejó particionado en 'disk' vía detect_manual_partitions()
        (GUID GPT / flag bootable MBR — nunca heurística de tamaño u orden).

        Si hay una sola candidata a root y ya tiene Btrfs, además la sondea
        con detect_btrfs_subvolumes() para saber si el usuario ya creó los
        subvolúmenes de AvalOS a mano — así el orquestador puede saltarse
        la creación de los que ya existan en vez de pisarlos.

        Si hay más de una candidata a root, NO elige sola — devuelve la
        lista completa para que el wizard se la ofrezca al usuario en un
        dropdown; la decisión final llega después por confirm_manual_root()."""
        info = detect_manual_partitions(disk, is_uefi())
        candidates = info["candidatas_root"]

        if not candidates:
            self._manual_ready = False
            return {"ok": False, "efi": "", "candidatas_root": [], "requiere_seleccion": False}

        existing_subvolumes: list[str] = []
        if len(candidates) == 1 and candidates[0]["fstype"] == "btrfs":
            existing_subvolumes = detect_btrfs_subvolumes(candidates[0]["name"])

        self._manual_efi = info["efi"]
        self._manual_root_candidates = candidates
        self._manual_existing_subvolumes = existing_subvolumes
        # Solo queda "listo" sin intervención extra si hay una única
        # candidata — con varias, el wizard debe esperar a
        # confirm_manual_root() antes de dejar avanzar el botón Instalar.
        self._manual_ready = (len(candidates) == 1)
        if len(candidates) == 1:
            self._manual_root = candidates[0]["name"]

        return {
            "ok": True,
            "efi": info["efi"],
            "candidatas_root": candidates,
            "requiere_seleccion": len(candidates) > 1,
            "subvols_existentes": existing_subvolumes,
        }

    def confirm_manual_root(self, disk: str, chosen_root: str) -> bool:
        """Modo manual: cuando check_manual_partitioning() devolvió más
        de una candidata a root, el usuario elige una en el dropdown del
        wizard y esta llamada la fija como definitiva. Vuelve a validar
        contra self._manual_root_candidates (no confía ciegamente en el
        string que llega de JS) para no aceptar un device arbitrario.
        'disk' no se usa acá (tampoco se usaba en el original) — se
        mantiene en la firma porque el JS lo sigue mandando."""
        valid = {c["name"] for c in self._manual_root_candidates}
        if chosen_root not in valid:
            return False
        self._manual_root = chosen_root
        # Solo re-sondear subvolúmenes si la elección es btrfs y no se hizo
        # ya en check_manual_partitioning() (caso de candidata única).
        candidate = next((c for c in self._manual_root_candidates if c["name"] == chosen_root), None)
        if candidate and candidate["fstype"] == "btrfs" and not self._manual_existing_subvolumes:
            self._manual_existing_subvolumes = detect_btrfs_subvolumes(chosen_root)
        self._manual_ready = True
        return True

    def retry(self) -> bool:
        with self.session._lock:
            if self.session._installing:
                return True
            self.session._aborted = False
            self.session._installing = True
        t = threading.Thread(target=run_installation, args=(self.session,), daemon=True)
        t.start()
        return True

    def choose_mirror(self, choice) -> bool:
        # Recibe el clic de uno de los botones del diálogo ov-mirror y
        # libera el Event que el hilo de instalación está esperando
        # (bloqueado en _mirror_choice_event.wait() dentro del orquestador).
        self.session._mirror_choice = choice
        self.session._mirror_choice_event.set()
        return True

    def reboot_system(self) -> bool:
        try:
            subprocess.Popen(["systemctl", "reboot"])
        except Exception as e:
            self.session.log(self.session.t("log-reboot-warn", e=e), "warn")
        return True

    def close(self) -> bool:
        if self.session.window:
            try:
                self.session.window.destroy()
            except Exception:
                pass
        return True
