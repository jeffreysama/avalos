"""
network/diagnose.py — diagnóstico de red por capas del instalador de AvalOS.

Antes el paso "net" hacía un solo ping a 8.8.8.8: "hay internet sí/no". Eso
falla en los dos sentidos — un router que bloquea ICMP daba "sin internet"
con la red perfecta, y una red con DNS roto, un portal cautivo o la hora
mal daba "hay internet" para después reventar en pacstrap con un error
críptico. Acá se prueba capa por capa y el PRIMER fallo decide el veredicto:

  enlace → IP → ruta → salida a Internet → DNS → portal cautivo → HTTPS
  (hora/certificados) → mirrors de Arch

  ok               todo responde
  mirrors_partial  usable: algunos mirrors no responden (el failover usa los demás)
  clock            usable: la hora del equipo está desfasada y rompe TLS;
                   sync_time() del instalador la corrige antes de pacman
  no_link          ninguna interfaz con cable/Wi-Fi conectado
  no_ip            hay enlace pero no se obtuvo dirección IP (DHCP)
  no_route         hay IP pero no hay puerta de enlace (ruta por defecto)
  no_internet      red local sí, salida a Internet no (router/firewall)
  dns              hay Internet pero no se resuelven nombres
  portal           la red exige iniciar sesión en un portal cautivo
  tls              falla la verificación HTTPS por otro motivo (¿proxy?)
  mirrors_down     Internet funciona pero ningún mirror de Arch responde

Cada sonda es una función de módulo (_probe_*) para poder simularlas en
pruebas. Ninguna lanza: un fallo de la sonda es un resultado, no una
excepción. El total está acotado (~15 s en el peor caso): las sondas de
red corren en paralelo con timeouts cortos.
"""

from __future__ import annotations

import concurrent.futures as cf
import email.utils
import http.client
import json
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from avalos_installer.core.shell import run_command

OK, MIRRORS_PARTIAL, CLOCK = "ok", "mirrors_partial", "clock"
NO_LINK, NO_IP, NO_ROUTE, NO_INTERNET = "no_link", "no_ip", "no_route", "no_internet"
DNS, PORTAL, TLS, MIRRORS_DOWN = "dns", "portal", "tls", "mirrors_down"
USABLE = {OK, MIRRORS_PARTIAL, CLOCK}

MIRRORLIST = Path("/etc/pacman.d/mirrorlist")
_SYS_NET = Path("/sys/class/net")
_PROC_ROUTE = Path("/proc/net/route")
_PROC_ROUTE6 = Path("/proc/net/ipv6_route")
# Sondas de salida a Internet por IP (TCP/443: funciona aunque el router filtre ICMP)
_IP_PROBES = [("1.1.1.1", 443), ("9.9.9.9", 443), ("8.8.8.8", 443), ("2606:4700:4700::1111", 443)]
_DNS_NAMES = ["archlinux.org", "geo.mirror.pkgbuild.com"]
_PORTAL_PROBES = [
    ("connectivitycheck.gstatic.com", "/generate_204", "204"),
    ("detectportal.firefox.com", "/success.txt", "success"),
]
_FALLBACK_MIRRORS = ["https://geo.mirror.pkgbuild.com", "https://mirror.rackspace.com/archlinux"]
_VIRTUAL_IF = ("lo", "docker", "veth", "br-", "virbr", "vnet", "tun", "tap", "vmnet", "sit")
_SKEW_LIMIT_S = 300   # más que esto y los certificados TLS / firmas GPG empiezan a fallar


@dataclass
class Layer:
    id: str
    status: str          # "ok" | "fail" | "skip"
    detail: str = ""
    ms: int | None = None


@dataclass
class NetDiagnosis:
    verdict: str = OK
    layers: list[Layer] = field(default_factory=list)
    clock_skew_s: int | None = None      # hora local − hora del servidor (s); None si no se pudo medir
    mirrors_ok: int = 0
    mirrors_total: int = 0
    has_wifi: bool = False

    @property
    def usable(self) -> bool:
        return self.verdict in USABLE

    def text_params(self) -> dict:
        """Valores para las plantillas i18n pf-net-<veredicto> ({ok}, {total}, {skew})."""
        return {"ok": self.mirrors_ok, "total": self.mirrors_total, "skew": fmt_duration(self.clock_skew_s)}

    def lines(self) -> list[str]:
        """Detalle por capa, para el archivo de log."""
        out = [f"veredicto={self.verdict} usable={self.usable} skew={self.clock_skew_s}s "
               f"mirrors={self.mirrors_ok}/{self.mirrors_total}"]
        for ly in self.layers:
            ms = f" {ly.ms}ms" if ly.ms is not None else ""
            out.append(f"  {ly.status:<4} {ly.id:<9}{ms}  {ly.detail}")
        return out


def fmt_duration(seconds: int | None) -> str:
    """'1 h 05 min', '5 min', '42 s' (valor absoluto; '?' si no se conoce)."""
    if seconds is None:
        return "?"
    n = abs(int(seconds))
    if n >= 3600:
        return f"{n // 3600} h {n % 3600 // 60:02d} min"
    if n >= 60:
        return f"{n // 60} min"
    return f"{n} s"


# ── sondas (cada una simulable en pruebas) ──────────────────────────────
def _sysfs_interfaces() -> list[dict]:
    """Respaldo si `ip` no está: enlace por /sys/class/net/<if>/carrier. No se pueden
    conocer las IP, así que las interfaces con enlace se marcan con ips=["?"] y la
    decisión la toman las sondas de más abajo (TCP/DNS)."""
    res: list[dict] = []
    try:
        dirs = sorted(_SYS_NET.iterdir())
    except OSError:
        return res
    for d in dirs:
        if d.name.startswith(_VIRTUAL_IF):
            continue
        try:
            carrier = (d / "carrier").read_text().strip()      # EINVAL si la interfaz está caída
        except OSError:
            carrier = "0"
        res.append({"name": d.name, "up": carrier == "1", "ips": ["?"] if carrier == "1" else [],
                    "wifi": (d / "wireless").exists() or d.name.startswith("wl")})
    return res


def _probe_interfaces() -> list[dict]:
    """[{name, up, ips, wifi}] de las interfaces físicas (sin lo ni virtuales)."""
    rc, out, _ = run_command(["ip", "-j", "addr", "show"], timeout=5)
    res: list[dict] = []
    try:
        data = json.loads(out) if rc == 0 and out else None
    except ValueError:
        data = None
    if data is None:                       # sin iproute2 (o salida ilegible): respaldo por sysfs
        return _sysfs_interfaces()
    for it in data:
        name = it.get("ifname", "")
        if name.startswith(_VIRTUAL_IF):
            continue
        flags = it.get("flags", [])
        ips = [a.get("local") for a in it.get("addr_info", [])
               if a.get("scope") == "global" and a.get("local")]
        res.append({
            "name": name,
            "up": "LOWER_UP" in flags or it.get("operstate") == "UP",
            "ips": ips,
            "wifi": Path(f"/sys/class/net/{name}/wireless").exists() or name.startswith("wl"),
        })
    return res


def _proc_default_route() -> bool:
    """Respaldo sin `ip`: /proc/net/route (IPv4) y /proc/net/ipv6_route."""
    try:
        for ln in _PROC_ROUTE.read_text().splitlines()[1:]:
            f = ln.split()
            if len(f) > 7 and f[1] == "00000000" and f[7] == "00000000":
                return True
    except OSError:
        pass
    try:
        for ln in _PROC_ROUTE6.read_text().splitlines():
            f = ln.split()
            if len(f) > 9 and f[0] == "0" * 32 and f[1] == "00" and f[9] != "lo":
                return True
    except OSError:
        pass
    return False


def _probe_default_route() -> bool:
    ran = False
    for fam in ("-4", "-6"):
        rc, out, _ = run_command(["ip", "-j", fam, "route", "show", "default"], timeout=5)
        if rc != 0:
            continue
        ran = True
        try:
            if out and json.loads(out):
                return True
        except ValueError:
            pass
    return False if ran else _proc_default_route()


def _tcp_ok(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolves(name: str, timeout: float = 5.0) -> bool:
    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return bool(ex.submit(socket.getaddrinfo, name, 443).result(timeout=timeout))
    except (OSError, cf.TimeoutError):
        return False
    finally:
        ex.shutdown(wait=False)         # si el resolver se cuelga, no bloqueamos


def _http_get(host: str, path: str, timeout: float = 4.0) -> tuple[int, dict, str] | None:
    """(status, headers en minúscula, primeros 300 bytes) o None si no conecta."""
    try:
        conn = http.client.HTTPConnection(host, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "avalos-installer", "Connection": "close"})
        r = conn.getresponse()
        body = r.read(300).decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in r.getheaders()}
        conn.close()
        return r.status, headers, body
    except (OSError, http.client.HTTPException):
        return None


def _https_head(url: str, timeout: float = 5.0) -> tuple[str, int | None, str]:
    """('ok', status, '') | ('cert', None, mensaje) | ('fail', None, mensaje)."""
    u = urllib.parse.urlsplit(url)
    try:
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                           context=ssl.create_default_context())
        conn.request("HEAD", u.path or "/", headers={"User-Agent": "avalos-installer", "Connection": "close"})
        status = conn.getresponse().status
        conn.close()
        return "ok", status, ""
    except ssl.SSLCertVerificationError as e:
        return "cert", None, getattr(e, "verify_message", "") or str(e)
    except ssl.SSLError as e:
        return "cert", None, str(e)
    except (OSError, http.client.HTTPException) as e:
        return "fail", None, str(e)


def _mirror_bases(mirrorlist: Path) -> list[str]:
    bases: list[str] = []
    try:
        for ln in mirrorlist.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln.startswith("Server") and "=" in ln:
                url = ln.split("=", 1)[1].strip()
                url = url.replace("$repo", "core").replace("$arch", "x86_64")
                if url.endswith("/core/os/x86_64"):
                    bases.append(url[: -len("/core/os/x86_64")])
    except OSError:
        pass
    for fb in _FALLBACK_MIRRORS:
        if fb not in bases:
            bases.append(fb)
    return list(dict.fromkeys(bases))[:8]


def _mirror_ok(base: str, timeout: float = 5.0) -> bool:
    u = urllib.parse.urlsplit(base)
    path = f"{u.path.rstrip('/')}/core/os/x86_64/core.db"
    if not u.hostname or not _resolves(u.hostname, min(timeout, 4.0)):
        return False
    try:
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=timeout)
        conn.request("HEAD", path, headers={"User-Agent": "avalos-installer", "Connection": "close"})
        status = conn.getresponse().status
        conn.close()
        return status < 400
    except (OSError, http.client.HTTPException, ssl.SSLError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _skew_from_headers(headers: dict) -> int | None:
    raw = headers.get("date")
    if not raw:
        return None
    try:
        return int((_now() - email.utils.parsedate_to_datetime(raw)).total_seconds())
    except (TypeError, ValueError):
        return None


# ── diagnóstico ──────────────────────────────────────────────────────────
def diagnose_network(mirrorlist: Path = MIRRORLIST) -> NetDiagnosis:
    d = NetDiagnosis()
    t0 = time.monotonic()

    def add(id_: str, status: str, detail: str = "", since: float | None = None) -> None:
        ms = int((time.monotonic() - since) * 1000) if since is not None else None
        d.layers.append(Layer(id_, status, detail, ms))

    def done(verdict: str) -> NetDiagnosis:
        d.verdict = verdict
        return d

    # 1) enlace + IP
    t = time.monotonic()
    ifs = _probe_interfaces()
    d.has_wifi = any(i["wifi"] for i in ifs)
    up = [i for i in ifs if i["up"]]
    if not up:
        add("link", "fail", f"interfaces={[i['name'] for i in ifs] or 'ninguna'} (ninguna con enlace)", t)
        return done(NO_LINK)
    add("link", "ok", ", ".join(i["name"] for i in up), t)
    with_ip = [i for i in up if i["ips"]]
    if not with_ip:
        add("ip", "fail", "enlace sin dirección IP global", t)
        return done(NO_IP)
    add("ip", "ok", ", ".join(f"{i['name']}={i['ips'][0]}" for i in with_ip), t)

    # 2) ruta por defecto
    t = time.monotonic()
    if not _probe_default_route():
        add("route", "fail", "sin ruta por defecto", t)
        return done(NO_ROUTE)
    add("route", "ok", "", t)

    # 3) salida a Internet por IP (en paralelo)
    t = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=len(_IP_PROBES)) as ex:
        hits = [hp for hp, ok in zip(_IP_PROBES, ex.map(lambda hp: _tcp_ok(*hp), _IP_PROBES)) if ok]
    if not hits:
        add("internet", "fail", "ninguna IP pública responde en TCP/443", t)
        return done(NO_INTERNET)
    add("internet", "ok", f"{hits[0][0]}:{hits[0][1]}", t)

    # Desde acá, los fallos "blandos" (dns, portal, tls, hora) solo deciden el veredicto si
    # NINGÚN mirror responde: que pacman llegue a un mirror es la verdad de fondo, y una sonda
    # de portal o de DNS lenta no debe frenar una instalación que va a funcionar.
    soft: str | None = None

    # 4) DNS
    t = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=len(_DNS_NAMES)) as ex:
        resolved = [n for n, ok in zip(_DNS_NAMES, ex.map(_resolves, _DNS_NAMES)) if ok]
    if not resolved:
        add("dns", "fail", f"no resuelve {', '.join(_DNS_NAMES)}", t)
        soft = DNS
    else:
        add("dns", "ok", ", ".join(resolved), t)

    # 5) portal cautivo (y de paso la hora del servidor, sin TLS) — necesita DNS
    if soft is None:
        t = time.monotonic()
        checked = False
        for host, path, expect in _PORTAL_PROBES:
            r = _http_get(host, path)
            if r is None:
                continue
            checked = True
            status, headers, body = r
            if d.clock_skew_s is None:
                d.clock_skew_s = _skew_from_headers(headers)
            good = (status == 204) if expect == "204" else (status == 200 and body.strip().lower().startswith(expect))
            if not good:
                add("portal", "fail", f"{host}{path} → {status} {headers.get('location', '')}".strip(), t)
                soft = PORTAL
            break
        if soft is None:
            add("portal", "ok" if checked else "skip", "" if checked else "sondas de portal inaccesibles", t)

    # 6) HTTPS (certificados ↔ hora) — solo si no hay portal ni DNS roto
    if soft is None:
        t = time.monotonic()
        kind, status, msg = _https_head("https://archlinux.org/")
        if kind == "cert":
            skewed = d.clock_skew_s is not None and abs(d.clock_skew_s) > _SKEW_LIMIT_S
            low = msg.lower()
            if skewed or "not yet valid" in low or "expired" in low:
                add("tls", "fail", f"certificado rechazado ({msg}); hora local − servidor = {d.clock_skew_s}s", t)
                soft = CLOCK
            else:
                add("tls", "fail", f"certificado rechazado: {msg}", t)
                soft = TLS
        else:
            add("tls", "ok" if kind == "ok" else "skip", f"archlinux.org → {status}" if kind == "ok" else msg[:80], t)

    # 7) mirrors (la prueba que decide)
    t = time.monotonic()
    bases = _mirror_bases(mirrorlist)
    with cf.ThreadPoolExecutor(max_workers=max(1, len(bases))) as ex:
        results = list(ex.map(_mirror_ok, bases))
    d.mirrors_total, d.mirrors_ok = len(bases), sum(results)
    if d.mirrors_ok == 0:
        add("mirrors", "fail", f"0/{d.mirrors_total} responden", t)
        return done(soft or MIRRORS_DOWN)
    add("mirrors", "ok", f"{d.mirrors_ok}/{d.mirrors_total} responden", t)
    if soft:
        add("nota", "skip", f"'{soft}' ignorado: {d.mirrors_ok} mirror(s) responden, pacman va a poder descargar")
    add("total", "ok", f"{time.monotonic() - t0:.1f}s")
    return done(OK if d.mirrors_ok == d.mirrors_total else MIRRORS_PARTIAL)
