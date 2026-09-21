"""
hardware/preflight.py — comprobación previa del equipo ("preflight"), ANTES de que
el usuario llene el asistente y de tocar ningún disco.

Hasta ahora todo esto se comprobaba DESPUÉS de que el usuario terminaba el
wizard (sin disco disponible, disco < 30 GB, sin internet...) y el error
llegaba en plena instalación. Esta pantalla lo adelanta: la bienvenida muestra
qué tiene el equipo, qué kernel le va a tocar y qué puede salir mal.

Cada comprobación devuelve un Check con CLAVES i18n (label/detail/hint) y sus
parámetros — no texto — para que la UI lo traduzca en el idioma vigente y lo
re-renderice si el usuario cambia de idioma. Estados:

  ok     todo bien             warn   se puede continuar, pero conviene mirarlo
  fail   problema; con blocking=True impide instalar (la UI ofrece
         "continuar de todos modos" por si fuera un falso positivo)
  info   dato, sin juicio

Ninguna comprobación lanza: si una falla, queda como "info" y el resto sigue.
Todo lo que lee del sistema vive en constantes de módulo para poder simularlo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from avalos_installer.core.prereqs import check_tools
from avalos_installer.core.shell import run_command
from avalos_installer.disk.discovery import MIN_DISK_GB, list_disks
from avalos_installer.hardware.detection import detect_cpu_arch_level, detect_gpu, is_uefi
from avalos_installer.network.diagnose import NetDiagnosis, diagnose_network

_MEMINFO = Path("/proc/meminfo")
_CPUINFO = Path("/proc/cpuinfo")
_POWER = Path("/sys/class/power_supply")
_SB_VAR = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c")

RAM_FAIL_GIB = 1.5           # por debajo, la instalación no es viable
RAM_WARN_GIB = 4.0           # por debajo, funciona pero conviene avisar
BATTERY_WARN_PCT = 30
CLOCK_WARN_S = 120


@dataclass
class Check:
    id: str
    status: str                                   # ok | warn | fail | info
    label: str                                    # clave i18n (pf-l-*)
    detail: str                                   # clave i18n
    params: dict[str, Any] = field(default_factory=dict)
    hint: str | None = None                       # clave i18n
    blocking: bool = False                        # solo cuenta con status == "fail"


# ── comprobaciones ───────────────────────────────────────────────────────────
def _boot(uefi: bool) -> Check:
    return Check("boot", "ok" if uefi else "info", "pf-l-boot", "pf-boot-uefi" if uefi else "pf-boot-bios")


def _secureboot(uefi: bool) -> Check | None:
    if not uefi:
        return None
    try:
        data = _SB_VAR.read_bytes()
    except OSError:
        return None                               # efivars no legible: no se opina
    if len(data) < 5:
        return None
    if data[4] == 1:
        return Check("sb", "warn", "pf-l-sb", "pf-sb-on", hint="pf-hint-sb-on")
    return Check("sb", "ok", "pf-l-sb", "pf-sb-off")


def _cpu_model() -> str:
    try:
        for ln in _CPUINFO.read_text(errors="replace").splitlines():
            if ln.lower().startswith("model name"):
                return " ".join(ln.split(":", 1)[1].split())
    except OSError:
        pass
    return "CPU"


def _cpu() -> Check:
    level = detect_cpu_arch_level()
    model = _cpu_model()
    if level == "x86-64":
        return Check("cpu", "warn", "pf-l-cpu", "pf-cpu-old", {"model": model}, hint="pf-hint-cpu-old")
    kernel = "linux-avalos" if level in ("x86-64-v3", "x86-64-v4") else "linux-avalos-compat"
    return Check("cpu", "ok", "pf-l-cpu", "pf-cpu", {"model": model, "level": level, "kernel": kernel})


def _nvidia_model() -> str | None:
    rc, out, _ = run_command(["lspci", "-mm"], timeout=10)
    if rc != 0 or not out:
        return None
    for ln in out.splitlines():
        low = ln.lower()
        if "nvidia" in low and ("vga" in low or "3d" in low or "display" in low):
            parts = ln.split('"')
            return parts[5] if len(parts) > 5 else "NVIDIA"
    return None


def _gpu() -> Check:
    nv = _nvidia_model()
    if nv:
        return Check("gpu", "warn", "pf-l-gpu", "pf-gpu-nvidia", {"model": nv}, hint="pf-hint-gpu-nvidia")
    g = detect_gpu()
    if g["model"].startswith("GPU desconocida"):
        return Check("gpu", "info", "pf-l-gpu", "pf-gpu-unknown")
    return Check("gpu", "ok", "pf-l-gpu", "pf-gpu", {"vendor": g["vendor"].upper(), "model": g["model"]})


def _ram() -> Check | None:
    try:
        for ln in _MEMINFO.read_text().splitlines():
            if ln.startswith("MemTotal:"):
                gib = int(ln.split()[1]) / 1024 / 1024
                break
        else:
            return None
    except (OSError, ValueError, IndexError):
        return None
    p = {"gib": f"{gib:.1f}"}
    if gib < RAM_FAIL_GIB:
        return Check("ram", "fail", "pf-l-ram", "pf-ram-fail", p, hint="pf-hint-ram", blocking=True)
    if gib < RAM_WARN_GIB:
        return Check("ram", "warn", "pf-l-ram", "pf-ram-low", p, hint="pf-hint-ram")
    return Check("ram", "ok", "pf-l-ram", "pf-ram", p)


def _disks() -> Check:
    discos = list_disks()
    eligible = [d for d in discos if not d["es_arranque"] and d["size_b"] / 1e9 >= MIN_DISK_GB]
    if not eligible:
        boot = next((d["name"] for d in discos if d["es_arranque"]), "?")
        return Check("disk", "fail", "pf-l-disk", "pf-disk-none", {"min_gb": MIN_DISK_GB, "boot": boot},
                     hint="pf-hint-disk-none", blocking=True)
    listing = " · ".join(f"{d['name']} {d['size_human']} {d['tipo']}" for d in eligible[:3])
    return Check("disk", "ok", "pf-l-disk", "pf-disk", {"n": len(eligible), "list": listing})


def _net(diag: NetDiagnosis) -> Check:
    v = diag.verdict
    detail = f"pf-net-{v}"
    if v == "ok":
        return Check("net", "ok", "pf-l-net", detail, diag.text_params())
    if diag.usable:                               # mirrors_partial / clock
        hint = "pf-hint-net-clock" if v == "clock" else None
        return Check("net", "warn", "pf-l-net", detail, diag.text_params(), hint=hint)
    hint = "pf-hint-net-no_link_wifi" if v == "no_link" and diag.has_wifi else f"pf-hint-net-{v}"
    return Check("net", "fail", "pf-l-net", detail, diag.text_params(), hint=hint, blocking=True)


def _clock(diag: NetDiagnosis) -> Check | None:
    s = diag.clock_skew_s
    if s is None:
        return None
    if abs(s) > CLOCK_WARN_S:
        return Check("clock", "warn", "pf-l-clock", "pf-clock-skew", diag.text_params(), hint="pf-hint-clock-skew")
    return Check("clock", "ok", "pf-l-clock", "pf-clock-ok")


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _power() -> Check | None:
    bat, ac_online = None, False
    try:
        supplies = sorted(_POWER.iterdir())
    except OSError:
        return None
    for s in supplies:
        typ = _read(s / "type").lower()
        if typ == "battery" and bat is None:
            try:
                bat = (int(_read(s / "capacity")), _read(s / "status").lower())
            except ValueError:
                pass
        elif typ == "mains" and _read(s / "online") == "1":
            ac_online = True
    if bat is None:
        return None                                # equipo de escritorio
    pct, state = bat
    on_ac = ac_online or state in ("charging", "full")
    if on_ac:
        return Check("power", "ok", "pf-l-power", "pf-power-ac", {"pct": pct})
    if pct < BATTERY_WARN_PCT:
        return Check("power", "warn", "pf-l-power", "pf-power-low", {"pct": pct}, hint="pf-hint-power-low")
    return Check("power", "ok", "pf-l-power", "pf-power-batt", {"pct": pct})


def _tools() -> Check:
    missing = sorted(t for t, ok in check_tools().items() if not ok)
    if missing:
        return Check("tools", "warn", "pf-l-tools", "pf-tools-missing", {"names": ", ".join(missing)})
    return Check("tools", "ok", "pf-l-tools", "pf-tools-ok")


def _virt() -> Check | None:
    rc, out, _ = run_command(["systemd-detect-virt"], timeout=5)
    kind = out.strip()
    if rc == 0 and kind and kind != "none":
        return Check("virt", "info", "pf-l-virt", "pf-virt", {"kind": kind})
    return None


def _log(session) -> Check | None:
    lf = getattr(session, "logfile", None)
    if lf is None:
        return None
    th = getattr(session, "_usb_thread", None)
    if th is not None:
        th.join(timeout=3)                         # la búsqueda de la USB arranca al abrir la app
    if getattr(lf, "usb_desc", ""):
        return Check("log", "info", "pf-l-log", "pf-log-usb", {"desc": lf.usb_desc})
    return Check("log", "info", "pf-l-log", "pf-log-ram")


def run_preflight(session=None, diag: NetDiagnosis | None = None) -> list[Check]:
    """Corre todas las comprobaciones (≈1–15 s según la red). Nunca lanza."""
    def guard(fn, *a) -> Check | None:
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 — un check roto no debe tumbar la pantalla
            return Check(fn.__name__.strip("_"), "info", "pf-l-other", "pf-check-error", {"why": str(e)[:80]})

    diag = diag or diagnose_network()
    uefi = is_uefi()
    plan = [(_boot, uefi), (_secureboot, uefi), (_cpu,), (_gpu,), (_ram,), (_disks,), (_net, diag),
            (_clock, diag), (_power,), (_tools,), (_virt,), (_log, session)]
    checks = [c for c in (guard(f, *a) for f, *a in plan) if c is not None]
    return checks


def to_dict(checks: list[Check]) -> dict:
    """Estructura serializable para la UI (JSON)."""
    return {
        "checks": [asdict(c) for c in checks],
        "blocking": any(c.blocking and c.status == "fail" for c in checks),
        "warnings": sum(1 for c in checks if c.status == "warn"),
    }


def report_lines(checks: list[Check]) -> list[str]:
    """Una línea por check, para el archivo de log (claves, no traducción)."""
    return [f"{c.status:<4} {c.id:<6} {c.detail} {c.params}" + (" [BLOQUEA]" if c.blocking and c.status == "fail" else "")
            for c in checks]
