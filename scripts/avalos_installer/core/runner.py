"""
core/runner.py — Ejecución de comandos con salida en streaming, a prueba de
cuelgues. Lo comparten core/session.py (instalador modular) y
skill_instalar_usb.py (el instalador legado, avalos-install-old).

POR QUÉ EXISTE (bug real, reproducido en un sandbox con sudo 1.9.15):
la versión anterior de run_cmd hacía `for line in proc.stdout` y "vigilaba"
el timeout con un threading.Timer que llamaba proc.kill(). Eso falla justo
en el caso que importa, un cuelgue SILENCIOSO:

  · El lector queda bloqueado en readline(): ni el timeout ni el botón
    Cancelar se revisaban hasta que llegaba otra línea.
  · kill() mata solo al hijo directo (arch-chroot). Sus descendientes
    (sudo → bash → makepkg → sudo pacman) siguen vivos con la tubería
    abierta, así que el `for` jamás llega a EOF: el timeout de 600 s del
    bootstrap de yay no terminaba nunca (85 min colgado en "installing
    missing dependencies").
  · El hijo heredaba stdin y la terminal de control del instalador. Si el
    instalador se lanzó desde una terminal (kitty), sudo pedía la contraseña
    AHÍ — nunca en el log — y esperaba para siempre.

QUÉ HACE ESTA VERSIÓN
  · stdin=/dev/null y sesión nueva (setsid): sin terminal de control, un
    prompt interactivo falla al instante ("a terminal is required to read
    the password...") y el error queda en el log, en vez de colgarse.
  · Lee con poll(): revisa timeout y abort cada segundo aunque no llegue
    ninguna línea.
  · Al vencer el timeout o cancelar mata TODO el árbol de procesos (por
    /proc, más el grupo): SIGTERM y, tras una gracia corta, SIGKILL.
  · Si el proceso principal terminó pero un demonio (gpg-agent, dirmngr...)
    heredó la tubería y la mantiene abierta, no espera a que la cierre.
  · Aviso de inactividad: tras N segundos sin salida informa cuál es el
    proceso hoja (el que en realidad está esperando algo) y su estado, y
    entrega el árbol completo para el log de diagnóstico.

Solo usa la biblioteca estándar (el legado lo importa opcionalmente).
"""

from __future__ import annotations

import atexit
import codecs
import os
import select
import signal
import subprocess
import threading
import time
from typing import Callable, NamedTuple


class RunResult(NamedTuple):
    rc: int              # código de retorno real del proceso principal
    output: str          # todas las líneas no vacías, unidas con \n
    status: str          # "ok" | "timeout" | "aborted"


# ── Árbol de procesos (vía /proc, sin depender de psutil) ─────────────────
def _children_map() -> dict[int, list[int]]:
    """{ppid: [pid, ...]} leyendo /proc/<pid>/stat."""
    kids: dict[int, list[int]] = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return kids
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                data = f.read().decode("utf-8", "replace")
            # "pid (comm) estado ppid ...": comm puede llevar espacios y
            # paréntesis, así que se corta en el ÚLTIMO ')'.
            rest = data[data.rindex(")") + 2:].split()
            ppid = int(rest[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(name))
    return kids


def descendants(pid: int) -> list[int]:
    """Todos los descendientes de pid (hijos, nietos...), sin incluirlo."""
    kids = _children_map()
    out: list[int] = []
    stack = [pid]
    while stack:
        cur = stack.pop()
        for k in kids.get(cur, []):
            out.append(k)
            stack.append(k)
    return out


def _state(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
        return data[data.rindex(")") + 2]
    except (OSError, ValueError, IndexError):
        return ""


def _alive(pid: int) -> bool:
    st = _state(pid)
    return st != "" and st != "Z"          # un zombi ya no cuenta como vivo


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def leaf_description(pid: int) -> str:
    """El proceso hoja más profundo del árbol (siguiendo al hijo más
    reciente): el que de verdad está esperando algo. 'sudo true (S)'."""
    kids = _children_map()
    cur = pid
    while kids.get(cur):
        cur = max(kids[cur])
    cmd = _cmdline(cur) or f"pid {cur}"
    return f"{cmd[:120]} ({_state(cur) or '?'})"


def describe_tree(pid: int, max_lines: int = 25) -> list[str]:
    """Líneas 'PID PPID ESTADO ETIME WCHAN ARGS' del árbol de pid (vía ps)."""
    pids = [pid] + descendants(pid)
    try:
        r = subprocess.run(
            ["ps", "-o", "pid,ppid,stat,etime,wchan:22,args", "--no-headers",
             "-p", ",".join(map(str, pids))],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
        return [ln.rstrip()[:200] for ln in r.stdout.splitlines()[:max_lines]]
    except Exception:  # noqa: BLE001
        return []


def kill_tree(pid: int, grace: float = 3.0) -> None:
    """SIGTERM a todo el árbol (y al grupo); tras 'grace' s, SIGKILL a lo que
    siga vivo. (Un init de PID-namespace, como el de arch-chroot, ignora
    SIGTERM sin handler — de ahí el SIGKILL de respaldo.)"""
    targets = descendants(pid) + [pid]

    def send(sig: int) -> None:
        for p in targets:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            os.killpg(pid, sig)             # start_new_session ⇒ pgid == pid
        except (ProcessLookupError, PermissionError):
            pass

    send(signal.SIGTERM)
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if not any(_alive(p) for p in targets):
            return
        time.sleep(0.1)
    targets = list(dict.fromkeys(descendants(pid) + targets))   # pudieron nacer más
    send(signal.SIGKILL)


# ── Registro de procesos en curso (para matarlos al cerrar el instalador) ──
_live: dict[int, "subprocess.Popen[bytes]"] = {}
_live_lock = threading.Lock()


def kill_all(grace: float = 2.0) -> None:
    """Mata el árbol de todos los comandos en curso. Se llama al cerrar la
    ventana y al salir el intérprete: como cada comando corre en su propia
    sesión, Ctrl+C en la terminal ya no les llega solo."""
    with _live_lock:
        pids = list(_live)
    for pid in pids:
        kill_tree(pid, grace)


atexit.register(kill_all)


# ── Ejecución ────────────────────────────────────────────────────────────
def run_streaming(
    cmd: list[str],
    timeout: float | None,
    on_line: Callable[[str], None],
    should_abort: Callable[[], bool] = lambda: False,
    on_idle: Callable[[int, str, list[str]], None] | None = None,
    on_kill: Callable[[str, list[str]], None] | None = None,
    idle_first: float = 120.0,
    idle_every: float = 300.0,
    poll: float = 1.0,
) -> RunResult:
    """Corre `cmd`, entrega cada línea de stdout+stderr a `on_line` y
    devuelve un RunResult. Lanza la excepción de Popen si el comando no se
    puede ni iniciar (FileNotFoundError, PermissionError...).

    · on_idle(segundos_sin_salida, proceso_hoja, arbol) — inactividad.
    · on_kill(motivo, arbol) — justo ANTES de matar por timeout/abort
      (después el árbol ya no existe); motivo = "timeout" | "aborted".
    """
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        stdin=subprocess.DEVNULL,           # un prompt recibe EOF, no espera
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,             # sin tty de control + grupo propio
    )
    with _live_lock:
        _live[proc.pid] = proc
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    poller = select.poll()                  # poll(), no select(): sin el tope de 1024 fds
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    lines: list[str] = []
    pending = ""
    status = "ok"

    def feed(chunk: bytes) -> None:
        nonlocal pending
        # newlines universales, como el modo texto de antes: \r\n, \r y \n
        pending = (pending + dec.decode(chunk)).replace("\r\n", "\n").replace("\r", "\n")
        *complete, pending = pending.split("\n")
        for ln in complete:
            if ln:
                lines.append(ln)
                on_line(ln)
        if len(pending) > 1_000_000:        # sin saltos de línea: no crecer sin fin
            lines.append(pending)
            on_line(pending)
            pending = ""

    start = time.monotonic()
    deadline = start + timeout if timeout else float("inf")   # None/0 = sin límite
    last_out = start
    next_idle = start + idle_first
    try:
        while True:
            if should_abort():
                status = "aborted"
                break
            now = time.monotonic()
            if now >= deadline:
                status = "timeout"
                break
            if poller.poll(int(poll * 1000)):
                chunk = os.read(fd, 65536)
                if not chunk:
                    break                   # EOF: todos cerraron la tubería
                last_out = time.monotonic()
                next_idle = last_out + idle_first
                feed(chunk)
                continue
            if proc.poll() is not None:
                break                       # terminó; si algo la retiene, no se espera
            if on_idle is not None and now >= next_idle:
                on_idle(int(now - last_out), leaf_description(proc.pid), describe_tree(proc.pid))
                next_idle = now + idle_every

        if status != "ok":
            if on_kill is not None:
                on_kill(status, describe_tree(proc.pid))
            kill_tree(proc.pid)

        # Lo que haya quedado en la tubería (sin bloquear)
        while poller.poll(0):
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            feed(chunk)
        tail = pending + dec.decode(b"", final=True)
        if tail:
            lines.append(tail)
            on_line(tail)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:   # cerró stdout pero sigue corriendo
            kill_tree(proc.pid)
            proc.wait()
        return RunResult(proc.returncode, "\n".join(lines), status)
    except BaseException:
        kill_tree(proc.pid)                 # nada queda huérfano si algo falla acá
        raise
    finally:
        with _live_lock:
            _live.pop(proc.pid, None)
        try:
            proc.stdout.close()
        except OSError:
            pass
