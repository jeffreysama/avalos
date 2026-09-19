"""
core/logfile.py — Log persistente de la instalación (archivo de texto).

Hasta ahora todo el log vivía SOLO en la ventana pywebview (session.log →
pyLog): si la UI se cerraba, se colgaba o el instalador reventaba antes de
mostrar algo, no quedaba ninguna traza, y los reportes de hardware llegaban
como capturas o logs parciales.

Destinos — todos "best effort": ninguno puede romper ni frenar la instalación
(cada operación de disco/USB tiene manejo de errores y timeouts, y la USB
se escribe desde un hilo aparte para que una memoria lenta no bloquee al
hilo de instalación):

  1. LIVE_LOG (/tmp/avalos-install.log, RAM del live): siempre, línea a
     línea. Sobrevive a un cuelgue de la UI; no a un reinicio.
  2. La USB de arranque: <partición escribible>/AvalOS-logs/
     avalos-install-<fecha>.txt, espejado cada pocos segundos con fsync.
     Se prueba, en orden: particiones del disco de arranque que ya estén
     montadas (ej. /run/mnt/ventoy), remontándolas rw si hace falta; y
     luego las que no estén montadas (la de datos de Ventoy primero). Se
     saltan iso9660 (solo lectura) y VTOYEFI (el arranque de Ventoy).
     OJO Ventoy: antes de la 1.1.01 su partición de datos NO se puede
     montar desde el live (device busy, restricción de device-mapper);
     si pasa, queda un aviso en el log (usb_hint = "ventoy-busy").
  3. El sistema instalado: /var/log/avalos-install.log, copiado justo antes
     de desmontar (session.clean_mounts) — incluido el camino de error.

Además captura excepciones sin capturar (hilo principal y de instalación) y
los WARNING/ERROR de `logging` (pywebview), y tacha las contraseñas que se
registren con add_secret() por si alguna llegara a colarse en una línea.
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

LIVE_LOG = Path("/tmp/avalos-install.log")
USB_MOUNT_DIR = Path("/tmp/avalos_usb_log")
USB_LOG_DIRNAME = "AvalOS-logs"
TARGET_LOG_REL = Path("var/log/avalos-install.log")

# Sistemas de archivos donde se puede escribir un .txt (y leerlo después
# desde Windows/Linux). iso9660/squashfs quedan afuera a propósito.
_WRITABLE_FS = {
    "exfat", "vfat", "fat", "msdos", "ntfs", "ntfs3",
    "ext2", "ext3", "ext4", "btrfs", "f2fs", "xfs",
}
_SKIP_LABELS = {"vtoyefi"}            # partición de arranque de Ventoy: no se toca
_VENTOY_MOUNTS = ("/run/mnt/ventoy", "/mnt/ventoy", "/ventoy")

_USB_MAX_BYTES = 8 * 1024 * 1024      # tope del archivo en la USB
_USB_MIN_FREE = 4 * 1024 * 1024       # espacio libre mínimo para elegir una partición
_SYNC_INTERVAL = 2.0                  # segundos entre volcados a la USB
_TRUNC_MSG = (
    "\n[LOG TRUNCADO EN LA USB: se alcanzó el límite de tamaño — el log completo "
    "sigue en /tmp/avalos-install.log y en /var/log/avalos-install.log del "
    "sistema instalado]\n"
).encode("utf-8")

_LEVELS = {
    "info": "INFO", "ok": "OK", "warn": "WARN", "err": "ERR",
    "cmd": "CMD", "step": "STEP", "state": "STATE", "diag": "DIAG", "rc": "RC",
}


def _sh(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """(returncode, stdout+stderr). Nunca lanza."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return -1, f"No encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "Timeout"
    except Exception as e:  # noqa: BLE001 — el log jamás debe explotar
        return -3, str(e)


def _write_all(fh, data: bytes) -> None:
    mv = memoryview(data)
    while mv:
        n = fh.write(mv)
        if not n:
            raise OSError("write devolvió 0 bytes")
        mv = mv[n:]


class _LogBridge(logging.Handler):
    """Reenvía WARNING/ERROR del módulo logging (pywebview, GTK...) al log."""

    def __init__(self, log: "InstallLog"):
        super().__init__(level=logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            cls = "err" if record.levelno >= logging.ERROR else "warn"
            self._log.write(cls, f"[{record.name}] {record.getMessage()}")
            if record.exc_info:
                self._log.write("err", "".join(traceback.format_exception(*record.exc_info)))
        except Exception:  # noqa: BLE001
            pass


class InstallLog:
    def __init__(self, path: Path = LIVE_LOG, usb_mount_dir: Path = USB_MOUNT_DIR, run=None):
        self.path = Path(path)
        self._usb_mount_dir = Path(usb_mount_dir)
        self._run = run or _sh

        self._lock = threading.RLock()       # archivo en RAM + estado corto
        self._usb_lock = threading.Lock()    # I/O hacia la USB (puede tardar)
        self._fh = None
        self._dirty = False
        self._closed = False
        self._secrets: list[str] = []
        self._hooks_installed = False

        # Estado del espejo en la USB
        self.usb_path: Path | None = None
        self.usb_desc = ""                    # texto legible para mostrar en la UI
        self.usb_hint = ""                    # "" | "ventoy-busy"
        self.boot_disks: list[str] = []
        self._usb_fh = None
        self._usb_offset = 0                  # bytes de LIVE_LOG ya copiados
        self._usb_written = 0
        self._usb_cap = _USB_MAX_BYTES
        self._usb_failed = False
        self._usb_mounted_here: Path | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._start = self.path.stat().st_size if self.path.exists() else 0
            self._fh = open(self.path, "a", buffering=1, encoding="utf-8", errors="replace")
        except OSError as e:
            self._start = 0
            print(f"[WARN] logfile: no se pudo abrir {self.path}: {e}", file=sys.stderr)
        self._write_header()

    # ── Escritura ────────────────────────────────────────────────────
    def add_secret(self, value) -> None:
        """Registra un valor (ej. la contraseña) que nunca debe quedar en el log."""
        v = str(value or "")
        with self._lock:
            if len(v) >= 3 and v not in self._secrets:
                # lista nueva (no .sort() in situ): otro hilo que esté
                # formateando una línea nunca ve la lista vacía a mitad de orden
                self._secrets = sorted(self._secrets + [v], key=len, reverse=True)

    def _format(self, cls: str, text) -> list[str]:
        text = str(text)
        if "\r" in text:
            # barras de progreso (pacman/curl): quedarse con el último estado
            parts = [p for p in text.split("\r") if p.strip()]
            text = parts[-1] if parts else ""
        for s in self._secrets:
            text = text.replace(s, "***")   # iterar la lista vigente: se reemplaza entera, no se muta
        stamp = datetime.now().strftime("%H:%M:%S")
        lvl = _LEVELS.get(cls, str(cls).upper()[:5])
        return [f"[{stamp}] [{lvl:<5}] {ln}" for ln in text.split("\n")]

    def _emit(self, lines: list[str]) -> None:
        with self._lock:
            if self._fh is None:
                return
            try:
                for ln in lines:
                    self._fh.write(ln + "\n")
            except (OSError, ValueError):
                self._fh = None               # el log nunca tumba la instalación
                return
            self._dirty = True

    def write(self, cls: str, text) -> None:
        try:
            self._emit(self._format(cls, text))
        except Exception:  # noqa: BLE001
            pass

    def diag(self, text) -> None:
        self.write("diag", text)

    def _write_header(self) -> None:
        efi = "UEFI" if Path("/sys/firmware/efi").exists() else "BIOS"
        self._emit([
            "=" * 72,
            "AvalOS installer — log de instalación",
            f"Inicio: {datetime.now():%Y-%m-%d %H:%M:%S} (reloj del live: puede no ser la hora real)",
            f"Kernel {os.uname().release} · Python {platform.python_version()} · arranque {efi}",
            "=" * 72,
        ])

    def snapshot(self, reason: str, dmesg: bool = False) -> None:
        """Foto del estado de discos/montajes (y errores recientes del kernel)
        para diagnosticar problemas de hardware en el reporte."""
        self.diag(f"── snapshot: {reason} ──")
        jobs = [
            ("lsblk", ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS"]),
            ("df", ["df", "-hT", "-x", "tmpfs", "-x", "devtmpfs"]),
        ]
        if dmesg:
            jobs.append(("dmesg", ["sh", "-c", "dmesg --level=err,warn 2>/dev/null | tail -n 25"]))
        for title, cmd in jobs:
            _rc, out = self._run(cmd, 8)
            for ln in out.splitlines()[:60]:
                self.diag(f"{title}: {ln}")

    # ── Excepciones sin capturar ─────────────────────────────────────────
    def install_hooks(self) -> None:
        if self._hooks_installed:
            return
        self._hooks_installed = True
        prev_sys = sys.excepthook

        def _sys_hook(tp, val, tb):
            self.write("err", "EXCEPCIÓN SIN CAPTURAR:\n" + "".join(traceback.format_exception(tp, val, tb)))
            prev_sys(tp, val, tb)

        sys.excepthook = _sys_hook
        prev_thr = threading.excepthook

        def _thr_hook(args):
            name = args.thread.name if args.thread else "?"
            self.write(
                "err",
                f"EXCEPCIÓN SIN CAPTURAR en el hilo '{name}':\n"
                + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            )
            prev_thr(args)

        threading.excepthook = _thr_hook
        logging.getLogger().addHandler(_LogBridge(self))
        atexit.register(self.close)

    # ── Sistema instalado ────────────────────────────────────────────
    def copy_to_target(self, mount_root: Path) -> tuple[bool, str]:
        """Copia el log de esta sesión a <mount_root>/var/log/avalos-install.log.
        Devuelve (ok, detalle). Si mount_root no está montado no hace nada
        (detalle 'no montado')."""
        try:
            if not os.path.ismount(mount_root):
                return False, "no montado"
            with self._lock:
                if self._fh is not None:
                    self._fh.flush()
            with open(self.path, "rb") as src:
                src.seek(self._start)
                data = src.read()
            dest = Path(mount_root) / TARGET_LOG_REL
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o644)
            return True, "/" + str(TARGET_LOG_REL)
        except OSError as e:
            return False, str(e)

    # ── USB de arranque ──────────────────────────────────────────────
    def attach_usb(self) -> bool:
        """Busca una partición escribible de la USB de arranque y empieza a
        espejar el log ahí. True si quedó activo. Nunca lanza (pensado para
        correr en un hilo de fondo al iniciar el instalador)."""
        try:
            self.snapshot("inicio")
            return self._attach_usb()
        except Exception as e:  # noqa: BLE001
            self.diag(f"USB-LOG: error inesperado buscando la USB: {e!r}")
            return False

    def _mounted_fs(self) -> list[dict]:
        rc, out = self._run(["findmnt", "-rn", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], 10)
        res: list[dict] = []
        if rc != 0:
            return res
        for ln in out.splitlines():
            p = ln.split(" ")
            if len(p) < 4:
                continue
            res.append({
                "target": p[0].replace("\\x20", " "),
                "source": p[1].split("[")[0],
                "fstype": p[2],
                "opts": p[3],
            })
        return res

    def _attach_usb(self) -> bool:
        from avalos_installer.disk import bootmedium as bm

        table = bm.lsblk_table()
        src = bm.boot_source(table)
        disk = bm.disk_of(table, src) if src else ""
        self.boot_disks = [disk] if disk else []
        self.diag(f"USB-LOG: medio de arranque={src or '?'} · disco={disk or '?'}")
        is_ventoy = "ventoy" in src.lower()

        # 1) Particiones del disco de arranque que ya están montadas (o rutas
        #    conocidas de Ventoy): usarlas tal cual, remontando rw si hace falta.
        for m in self._mounted_fs():
            if self._closed:
                return False
            dev, mp, fs = m["source"], m["target"], m["fstype"]
            on_boot = bool(disk) and bm.disk_of(table, dev) == disk
            if not (on_boot or mp in _VENTOY_MOUNTS) or fs not in _WRITABLE_FS:
                continue
            label = (table.get(dev) or {}).get("label") or ""
            if label.lower() in _SKIP_LABELS:
                continue
            if "rw" not in m["opts"].split(","):
                rc, out = self._run(["mount", "-o", "remount,rw", mp], 20)
                self.diag(f"USB-LOG: remount rw {mp} → rc={rc} {out[-120:]}")
                if rc != 0:
                    continue
            if self._open_usb_file(Path(mp), f"{dev} ({label or fs})"):
                return True

        # 2) Particiones sin montar del disco de arranque (sin disco conocido
        #    no se toca ninguna: no vamos a montar discos ajenos).
        cands = []
        if disk:
            for path, node in table.items():
                if node.get("type") not in ("part", "disk") or bm.disk_of(table, path) != disk:
                    continue
                fs = node.get("fstype") or ""
                label = node.get("label") or ""
                if fs not in _WRITABLE_FS or label.lower() in _SKIP_LABELS:
                    continue
                if any(x for x in (node.get("mountpoints") or []) if x):
                    continue
                size = int(node.get("size") or 0)
                cands.append(((0 if label.lower() == "ventoy" else 1, -size), path, fs, label))
        cands.sort()
        if not cands:
            self.diag("USB-LOG: no hay particiones escribibles sin montar en el disco de arranque")

        for _rank, path, fs, label in cands:
            if self._closed:
                return False
            mp = self._usb_mount_dir
            mp.mkdir(parents=True, exist_ok=True)
            out = ""
            ok = False
            for fstype in (["ntfs3", None] if fs in ("ntfs", "ntfs3") else [None]):
                cmd = ["mount"] + (["-t", fstype] if fstype else []) + ["-o", "rw", path, str(mp)]
                rc, out = self._run(cmd, 30)
                if rc == 0:
                    ok = True
                    break
            self.diag(f"USB-LOG: mount {path} ({fs}, '{label}') → {'OK' if ok else out[-160:]}")
            if not ok:
                if "busy" in out.lower() and (is_ventoy or label.lower() == "ventoy"):
                    self.usb_hint = "ventoy-busy"
                continue
            self._usb_mounted_here = mp
            if self._open_usb_file(mp, f"{path} ({label or fs})"):
                return True
            self._umount_ours()
        return False

    def _open_usb_file(self, mp: Path, desc: str) -> bool:
        if self._closed:
            return False
        try:
            st = os.statvfs(mp)
            free = st.f_bavail * st.f_frsize
            if free < _USB_MIN_FREE:
                self.diag(f"USB-LOG: {mp} descartada: solo {free // 1024} KiB libres")
                return False
            d = mp / USB_LOG_DIRNAME
            d.mkdir(exist_ok=True)
            p = d / f"avalos-install-{datetime.now():%Y%m%d-%H%M%S}.txt"
            fh = open(p, "ab", buffering=0)
            os.fsync(fh.fileno())
        except OSError as e:
            self.diag(f"USB-LOG: no se pudo escribir en {mp}: {e}")
            return False
        with self._usb_lock:
            self._usb_fh = fh
            self.usb_path = p
            self._usb_offset = self._start
            self._usb_written = 0
            self._usb_cap = min(_USB_MAX_BYTES, max(free - _USB_MIN_FREE // 2, 512 * 1024))
            self.usb_desc = f"{desc} → {USB_LOG_DIRNAME}/{p.name}"
        self.diag(f"USB-LOG: activo → {p}")
        self.sync_usb()
        self._thread = threading.Thread(target=self._sync_loop, name="avalos-usb-log", daemon=True)
        self._thread.start()
        return True

    def _sync_loop(self) -> None:
        while not self._stop.wait(_SYNC_INTERVAL):
            if self._dirty:
                self.sync_usb()

    def sync_usb(self) -> None:
        """Vuelca a la USB lo escrito desde la última vez (con fsync). El
        lock del archivo en RAM se suelta antes de tocar la USB: si la
        memoria es lenta, el hilo de instalación no se entera."""
        if self._usb_fh is None or self._usb_failed:
            return
        with self._usb_lock:
            if self._usb_fh is None or self._usb_failed:
                return
            with self._lock:
                self._dirty = False
                if self._fh is not None:
                    try:
                        self._fh.flush()
                    except (OSError, ValueError):
                        pass
                try:
                    size = self.path.stat().st_size
                except OSError:
                    return
                start = self._usb_offset
            if size <= start:
                return
            try:
                with open(self.path, "rb") as src:
                    src.seek(start)
                    chunk = src.read(size - start)
                consumed = len(chunk)
                room = max(self._usb_cap - self._usb_written, 0)
                truncated = len(chunk) > room
                if truncated:
                    chunk = chunk[:room]
                _write_all(self._usb_fh, chunk)
                self._usb_written += len(chunk)
                if truncated:
                    _write_all(self._usb_fh, _TRUNC_MSG)
                    self._usb_failed = True       # no seguir espejando
                os.fsync(self._usb_fh.fileno())
                self._usb_offset = start + consumed
            except (OSError, ValueError) as e:
                self._usb_failed = True
                self.diag(
                    f"USB-LOG: falló la escritura en la USB ({e}) — se deja de espejar; "
                    f"el log completo sigue en {self.path}"
                )

    def _umount_ours(self) -> None:
        mp = self._usb_mounted_here
        if mp is None:
            return
        rc, out = self._run(["umount", str(mp)], 20)
        if rc != 0:
            rc, out = self._run(["umount", "-l", str(mp)], 20)
        self._usb_mounted_here = None
        self.diag(f"USB-LOG: umount {mp} → rc={rc}")

    def _close_usb(self) -> None:
        self.sync_usb()
        with self._usb_lock:
            fh, self._usb_fh = self._usb_fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass
        self._umount_ours()

    def close(self) -> None:
        """Pie del log + volcado final a la USB + desmontaje de lo que montamos
        nosotros (para no dejar el exFAT/FAT 'sucio' en Windows). Idempotente
        y acotado en tiempo (una USB colgada no puede bloquear el cierre)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.write("info", f"Fin del log — {datetime.now():%Y-%m-%d %H:%M:%S}")
        self._stop.set()
        try:
            t = threading.Thread(target=self._close_usb, name="avalos-usb-close", daemon=True)
            t.start()
            t.join(25)
            if t.is_alive():
                self.diag("USB-LOG: el cierre de la USB tardó más de 25 s (¿memoria lenta o colgada?)")
        except RuntimeError:
            # cierre del intérprete (atexit): ya no se pueden crear hilos
            self._close_usb()
