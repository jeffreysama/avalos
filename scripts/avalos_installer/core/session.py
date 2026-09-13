"""
core/session.py — InstallSession: el "kit de herramientas" operativo que
necesita cualquier paso de la instalación (hardware, disk, network, system,
desktop) para hablar con la ventana pywebview, correr comandos con streaming
en vivo, escribir archivos bajo MOUNT_ROOT y traducir mensajes.

Extraído de VentanaInstalador en skill_instalar_usb.py (líneas 2536-2749:
__init__ parcial + _js, _jsc, _log, _step, _progress, _info, _status,
_label, _t, _on_close, _run_cmd, _salida_indica_error_gpg, _run_chroot,
_run_chroot_stdin, _limpiar_montajes, _escribir, _chown_r).

DECISIÓN DE DISEÑO (no estaba en la propuesta original de módulos): esto
NO es lo mismo que InstallContext. InstallContext (todavía por construir,
depende de terminar de leer _run_instalacion) va a ser configuración pura
— username, disco, bootloader, flags — sin comportamiento. InstallSession
es comportamiento puro — cómo hablar con la UI y con el sistema — con el
mínimo de estado necesario para hacerlo (ventana, flags de aborto/cierre,
locks). Los métodos que antes eran privados de VentanaInstalador (con
guion bajo) se exponen aquí sin guion bajo porque dejan de ser detalle
interno de una sola clase y pasan a ser la API que hardware/, disk/,
network/, system/ y desktop/ van a llamar. `_js`/`_jsc` sí quedan privados
— son el mecanismo interno; el resto del código debe pasar por `log`,
`step`, etc., nunca invocar JS directo.

Lógica sin cambios respecto al original, incluidos todos los comentarios
de por qué (el chmod 644 explícito, el chown_r que ya no falla en
silencio, el manejo de abort a mitad de stream, la detección de error GPG).

Todos los identificadores (métodos, parámetros, variables locales,
atributos de instancia) se llevaron a inglés a pedido explícito — los
docstrings y comentarios se dejaron en español, ahí vive el razonamiento.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import translations

from avalos_installer.core.config import MOUNT_ROOT, MOUNT_EFI, MOUNT_ISO


def output_indicates_gpg_error(output: str) -> bool:
    """Detecta si la salida de pacman apunta a un problema de confianza/firma GPG
    (clave no confiable, firma inválida, keyring corrupto) en vez de un simple
    problema de conectividad."""
    if not output:
        return False
    _o = output.lower()
    _markers = (
        "unknown trust", "signature from", "invalid or corrupted",
        "keyring is not writable", "key could not be looked up",
        "pgp signature",
    )
    return any(m in _o for m in _markers)


class InstallSession:
    """Kit de herramientas operativo de una instalación en curso.

    No confundir con InstallContext (configuración elegida por el usuario).
    Esto es "cómo hacer las cosas", no "qué se eligió hacer"."""

    def __init__(self, window: "webview.Window | None" = None, lang: str = "en"):
        self.window = window
        self._closed = False
        self._aborted = False
        self._installing = False
        self._thread_started = False

        self._lang = lang

        # Coordinación con la UI para pasos que esperan input del usuario
        # a mitad de instalación (elegir mirror manualmente, etc.)
        self._config_ready = threading.Event()
        self._mirror_choice_event = threading.Event()
        self._mirror_choice: str | None = None
        self._lock = threading.Lock()

        # Handoff ui/ → core/install.py: ui.api.InstallerAPI.start_installation()
        # arma acá el InstallContext ya validado y llama self._config_ready.set().
        # El orquestador espera _config_ready y recién ahí lee pending_context.
        # No se importa InstallContext en este archivo — mismo patrón que
        # "webview.Window" arriba: type hint como string, sin crear una
        # dependencia de import real entre session.py y context.py.
        self.pending_context: "InstallContext | None" = None

    # ── Puente JS (bajo nivel, no llamar directo desde fuera) ────────────
    def _js(self, code: str):
        if self.window and not self._closed:
            try:
                self.window.evaluate_js(code)
            except Exception as e:
                print(f"[JS] {e}")

    def _jsc(self, func: str, *args):
        encoded = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        self._js(f"{func}({encoded})")

    # ── API pública de logging/progreso hacia la UI ──────────────────────
    def log(self, txt: str, cls: str = "info"): self._jsc("pyLog", txt, cls)
    def step(self, id_: str, st: str, det: str = ""): self._jsc("pyStep", id_, st, det)
    def progress(self, pct: int): self._jsc("pyProgress", pct)
    def info(self, id_: str, v: str, c: str = ""): self._jsc("pyInfo", id_, v, c)
    def status(self, msg: str): self._jsc("pyStatus", msg)
    def label(self, txt: str): self._jsc("pyStatusLabel", txt)

    # ── Señales específicas que el monolito manda directo por _jsc (desde
    # _run_instalacion o desde InstaladorAPI, ej. on_ready) y que nunca
    # tuvieron wrapper propio ahí. Se agregan acá a medida que se van
    # necesitando durante la extracción de cada paso/módulo — no se
    # adivinaron todas de una vez, se confirman contra el código real
    # según se extrae.
    def error_step(self, msg: str): self._jsc("pyErrorPaso", msg)
    def error_fatal(self, msg: str): self._jsc("pyErrorFatal", msg)
    def badges(self, net_ok: bool | None, uefi: bool): self._jsc("pyBadges", net_ok, uefi)
    def countdown_start(self, dev: str, model: str, size_human: str):
        self._jsc("pyIniciarCountdown", dev, model, size_human)
    def countdown_tick(self, seconds_left: int): self._jsc("pyActualizarCountdown", seconds_left)
    def countdown_cancel(self): self._jsc("pyCerrarCountdown")
    def mirror_dialog(self, detail: str): self._jsc("pyMirrorDialog", detail)
    def install_complete(self, summary_html: str): self._jsc("pyInstalacionCompleta", summary_html)

    def render_disks(self, disks: list[dict]):
        """Usado por ui.api.InstallerAPI.on_ready(). El original hace
        json.dumps(discos) ANTES de pasarlo a _jsc — que a su vez vuelve a
        codificar cada argumento — a propósito: el JS de pyRenderDiscos
        espera recibir un string y lo parsea él mismo (JSON.parse) del
        lado JS, no un array ya materializado. Se preserva ese doble
        encoding tal cual, no es un bug."""
        self._jsc("pyRenderDiscos", json.dumps(disks, ensure_ascii=False))

    def start_timer(self): self._jsc("pyStartTimer")
    def stop_timer(self): self._jsc("pyStopTimer")

    def t(self, key: str, **kwargs) -> str:
        """Traduce 'key' al idioma elegido por el usuario (self._lang) y
        aplica .format(**kwargs) para los textos con partes dinámicas
        (rutas, nombres de disco, mensajes de excepción, etc. — esas partes
        NUNCA se traducen, solo el texto que las rodea).
        Fallback en cadena: idioma actual → inglés → la propia key (nunca
        debe explotar el log de instalación por una clave faltante)."""
        _translations = translations.TRANSLATIONS.get(self._lang, translations.TRANSLATIONS["en"])
        template = _translations.get(key) or translations.TRANSLATIONS["en"].get(key) or key
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def on_close(self):
        self._closed = True
        self._aborted = True
        self._config_ready.set()

    # ── Ejecución de comandos ─────────────────────────────────────────────
    def run_cmd(self, cmd: list[str], timeout: int = 300,
                log_cls: str = "info",
                pre_mkdir: str | None = None) -> tuple[int, str]:
        if pre_mkdir:
            Path(pre_mkdir).mkdir(parents=True, exist_ok=True)
        self.log(f"$ {' '.join(cmd)}", "cmd")
        output: list[str] = []
        proc: "subprocess.Popen[str] | None" = None
        _timed_out = False

        def _kill_on_timeout():
            nonlocal _timed_out
            _timed_out = True
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
            if proc.stdout is None:
                return -1, "No stdout"

            timer = threading.Timer(timeout, _kill_on_timeout)
            timer.start()
            try:
                for line in proc.stdout:
                    line = line.rstrip('\n')
                    if line:
                        self.log(line, log_cls)
                        output.append(line)
                    if self._aborted:
                        proc.kill()
                        proc.wait()
                        return -99, "\n".join(output)
                proc.wait(timeout=5)
            finally:
                timer.cancel()

            if _timed_out:
                self.log(self.t("log-timeout-proc", timeout=timeout), "err")
                return -2, "\n".join(output)

            return proc.returncode, "\n".join(output)
        except Exception as e:
            self.log(self.t("log-exception", e=e), "err")
            if proc is not None:
                try:
                    proc.kill(); proc.wait()
                except Exception:
                    pass
            return -3, ""

    def run_chroot(self, cmd: list[str], timeout: int = 300,
                    systemd_mode: bool = False) -> tuple[int, str]:
        """systemd_mode=True agrega '-S' a arch-chroot (modo systemd real,
        via systemd-run/nspawn en vez de un chroot+namespace plano). Hace
        falta para que bootctl no se abstenga de tocar variables EFI
        dentro del chroot (ver system/bootloader.py, rama sd-boot) — sin
        esto bootctl detecta que corre en un namespace de PID y se salta
        la creación de la entrada NVRAM en silencio, con rc=0 igual.

        NO usar systemd_mode=True como default general: -S es un flag
        relativamente nuevo de arch-install-scripts (agregado en algún
        punto de 2025) y hay reportes de 'invalid option' en versiones
        de archiso más viejas — el llamador debe estar preparado para
        reintentar sin systemd_mode si esto falla por esa razón
        específica (ver el patrón en install_bootloader)."""
        cmd_prefix = ["arch-chroot"] + (["-S"] if systemd_mode else []) + [str(MOUNT_ROOT)]
        return self.run_cmd(cmd_prefix + cmd, timeout=timeout)

    def run_chroot_stdin(self, stdin_data: str, cmd: list[str], timeout: int = 60) -> tuple[int, str]:
        """Ejecuta un comando en chroot pasando datos sensibles por stdin (ej: chpasswd)."""
        full_cmd = ["arch-chroot", str(MOUNT_ROOT)] + cmd
        try:
            proc = subprocess.run(
                full_cmd, input=stdin_data, capture_output=True, text=True, timeout=timeout,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return proc.returncode, out.strip()
        except subprocess.TimeoutExpired:
            self.log(self.t("log-timeout-cmd", timeout=timeout, cmd0=cmd[0]), "err")
            return -2, ""
        except Exception as e:
            self.log(self.t("log-exception", e=e), "err")
            return -3, ""

    def clean_mounts(self):
        self.log(self.t("log-cleaning-mounts"), "warn")
        mount_points = [
            str(MOUNT_EFI),
            str(MOUNT_ROOT / "boot"),
            str(MOUNT_ROOT / "proc"),
            str(MOUNT_ROOT / "sys" / "firmware" / "efi" / "efivars"),
            str(MOUNT_ROOT / "sys"),
            str(MOUNT_ROOT / "dev" / "pts"),
            str(MOUNT_ROOT / "dev"),
            str(MOUNT_ROOT / "run"),
            str(MOUNT_ROOT / "tmp"),
            str(MOUNT_ROOT / "var" / "cache"),
            str(MOUNT_ROOT / "var" / "log"),
            str(MOUNT_ROOT / ".snapshots"),
            str(MOUNT_ROOT / "home"),
            str(MOUNT_ROOT),
            str(MOUNT_ISO),
        ]
        for point in mount_points:
            if Path(point).is_mount():
                rc, _ = self.run_cmd(["umount", "-l", point])
                if rc == 0:
                    self.log(self.t("log-unmounted", p=point), "ok")

    def write_file(self, relative_path: str, content: str):
        dest = MOUNT_ROOT / relative_path.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        # Modo explicito: dest.write_text() hereda el umask del proceso (root,
        # instalador). Si ese umask es mas restrictivo que 022 (022 -> 644,
        # world-readable), el archivo queda sin bit de lectura para "other" Y
        # el chown_r de mas abajo SOLO arregla dueño, nunca modo -- si por lo
        # que sea ese chown no llega a cubrir este archivo a tiempo, el dueño
        # real (root, todavia) + modo restrictivo = exactamente "Permission
        # denied" para el usuario real al leer su propio hyprland.lua. Fijar
        # 644 aca hace que la lectura no dependa de NINGUNA de las dos cosas.
        dest.chmod(0o644)
        self.log(self.t("log-written", ruta=relative_path), "ok")

    def chown_r(self, path: str, user: str):
        rc, out = self.run_chroot(["chown", "-R", f"{user}:{user}", path])
        if rc != 0:
            # Antes esto fallaba en silencio -- sin rc ni log, no habia forma
            # de notar (ni de diagnosticar) un home mal dueño hasta que el
            # usuario ya estaba adentro con la sesion rota.
            self.log(self.t("log-chown-r-fail", ruta=path, rc=rc, out=out.strip()[-300:]), "warn")
        return rc
