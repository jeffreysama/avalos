#!/usr/bin/env python3
"""verify-kernel-tarball.py — baja linux-<ver>.tar.xz de kernel.org y comprueba su firma PGP antes de dejarlo para makepkg.

POR QUÉ. El PKGBUILD de linux-avalos usa `sha256sums=('SKIP' …)` y los cuatro `makepkg` del CI llevan
`--skippgpcheck`: el tarball del kernel que AvalOS compila, firma con su clave y publica a todos los equipos se
aceptaba tal como llegara de cdn.kernel.org (una CDN de terceros). kernel.org firma cada tarball: la firma
(`linux-<ver>.tar.sign`) es un detached sign de Greg Kroah-Hartman o de Linus Torvalds sobre el tar SIN comprimir.

QUÉ HACE.
  1. Descarga el .tar.xz y el .tar.sign por https (tope de tamaño, sin seguir redirecciones a http).
  2. Importa las claves PINEADAS (huellas fijas abajo) a un GNUPGHOME temporal: primero por WKD de kernel.org y, si no, por
     keyservers. La confianza NO viene de la fuente de la clave sino de que la huella coincida con la fijada; cualquier otra
     clave que llegara se borra.
  3. `xz -dc linux.tar.xz | gpg --verify linux.tar.sign -` y exige: una firma BUENA (GOODSIG/VALIDSIG), hecha por una clave
     pineada, sin BADSIG/ERRSIG/EXPKEYSIG/REVKEYSIG/KEYEXPIRED. Una firma válida de una clave que NO está pineada falla
     (con la huella del firmante en el mensaje) salvo con --allow-unpinned-signer (el workflow lo activa con
     AVALOS_KERNEL_PGP=warn), que la acepta con un aviso — para no parar un build semanal si aparece un firmante nuevo.
  4. Solo si todo está bien deja el tarball en --dest/linux-<ver>.tar.xz: makepkg lo encuentra ahí, lo usa y NO lo vuelve a
     bajar (no hay ventana entre «verificado» y «usado»).

HUELLAS PINEADAS (verificadas con el PKGBUILD de `linux` de Arch, archivado en archlinux/svntogit-packages, 2026-11-13):
  Linus Torvalds        ABAF11C65A2970B130ABE3C479BE3E4300411886
  Greg Kroah-Hartman    647F28654894E3BD457199BE38DBBDC86092693E
NO está pineada la de Sasha Levin (co-mantenedor de stable, firma algunos tarballs): no pude confirmar su huella sin red hacia
kernel.org. Si un release sale firmado por él, el build falla con su huella en el mensaje: comprueba esa huella en
https://www.kernel.org/category/signatures.html y añádela a PINNED.

Salida: 0 verificado (tarball en --dest) · 1 NO verificado · 2 uso incorrecto.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

PINNED = {
    "ABAF11C65A2970B130ABE3C479BE3E4300411886": "Linus Torvalds",
    "647F28654894E3BD457199BE38DBBDC86092693E": "Greg Kroah-Hartman",
}
WKD_ADDRESSES = ("torvalds@kernel.org", "gregkh@kernel.org")
KEYSERVERS = ("hkps://keys.openpgp.org", "hkps://keyserver.ubuntu.com")
BASE_URL = "https://cdn.kernel.org/pub/linux/kernel"
MAX_TARBALL = 400 * 1024 * 1024         # linux-7.x.tar.xz pesa ~150 MB
MAX_SIGNATURE = 16 * 1024               # una firma detached pesa unos cientos de bytes
VERSION = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?")
FPR = re.compile(r"[0-9A-F]{40}")
BAD_STATUS = ("BADSIG", "ERRSIG", "EXPKEYSIG", "REVKEYSIG", "EXPSIG", "KEYEXPIRED", "KEYREVOKED", "BADARMOR", "NODATA", "NO_PUBKEY")


# ── descarga ────────────────────────────────────────────────────────────────────────────────────────────
class _SoloHttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"redirección a un destino que no es https rechazada: {newurl[:80]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SoloHttpsRedirect)


def download(url: str, dest: Path, limit: int, timeout: float = 60) -> None:
    """GET por https a `dest`, con tope de `limit` bytes (lanza ValueError/OSError/URLError; borra lo parcial)."""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise ValueError(f"solo se descarga por https: {str(url)[:80]!r}")
    req = urllib.request.Request(url, headers={"User-Agent": "avalos-verify-kernel-tarball"})
    total = 0
    try:
        with _OPENER.open(req, timeout=timeout) as resp, open(dest, "wb") as out:
            if resp.status != 200:
                raise OSError(f"HTTP {resp.status}")
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"la respuesta supera el tope de {limit} bytes")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


# ── claves ──────────────────────────────────────────────────────────────────────────────────────────────
def gpg(home: Path, *args: str, input: bytes | None = None, timeout: float = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["gpg", "--homedir", str(home), "--batch", "--no-tty", *args], input=input,
                          capture_output=True, timeout=timeout)


def keyring_fingerprints(home: Path) -> set[str]:
    """Huellas de las claves PRIMARIAS del llavero (las líneas fpr que siguen a «pub»)."""
    out = gpg(home, "--with-colons", "--fingerprint", "--list-keys").stdout.decode("utf-8", "replace")
    fprs, after_pub = set(), False
    for line in out.splitlines():
        kind = line.split(":", 1)[0]
        if kind == "pub":
            after_pub = True
        elif kind == "sub":
            after_pub = False
        elif kind == "fpr" and after_pub:
            fprs.add(line.split(":")[9].upper())
            after_pub = False
    return fprs


def import_pinned_keys(home: Path, pinned: dict[str, str], sources=None) -> list[str]:
    """Trae las claves pineadas probando cada fuente hasta tenerlas todas, y borra cualquier otra que haya llegado.
    Devuelve las notas de lo que pasó (para el log). La confianza está en la huella, no en la fuente."""
    notes: list[str] = []
    sources = sources if sources is not None else default_key_sources()
    for name, fetch in sources:
        if set(pinned) <= keyring_fingerprints(home):
            break
        try:
            fetch(home, sorted(pinned))
            notes.append(f"claves: {name} OK")
        except Exception as e:  # noqa: BLE001
            notes.append(f"claves: {name} falló ({str(e)[:100]})")
    present = keyring_fingerprints(home)
    for fpr in sorted(present - set(pinned)):
        gpg(home, "--yes", "--delete-keys", fpr)
        notes.append(f"clave NO pineada descartada: {fpr}")
    return notes


def default_key_sources():
    def last_line(r, default):
        lines = r.stderr.decode("utf-8", "replace").strip().splitlines()
        return lines[-1] if lines else default

    def wkd(home, fprs):
        r = gpg(home, "--auto-key-locate", "clear,wkd", "--locate-keys", *WKD_ADDRESSES)
        if r.returncode != 0:
            raise RuntimeError(last_line(r, "gpg --locate-keys falló"))

    def keyserver(url):
        def fetch(home, fprs):
            r = gpg(home, "--keyserver", url, "--recv-keys", *fprs)
            if r.returncode != 0:
                raise RuntimeError(last_line(r, "gpg --recv-keys falló"))
        return fetch

    return [("WKD de kernel.org", wkd)] + [(f"keyserver {u}", keyserver(u)) for u in KEYSERVERS]


# ── verificación ────────────────────────────────────────────────────────────────────────────────────────
def parse_status(text: str) -> dict:
    """Interpreta las líneas «[GNUPG:] …» de gpg --status-fd. VALIDSIG: <fpr firmante> … <fpr de la clave primaria>."""
    info = {"good": False, "validsig": [], "bad": []}
    for line in text.splitlines():
        if not line.startswith("[GNUPG:] "):
            continue
        parts = line[9:].split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "GOODSIG":
            info["good"] = True
        elif tag == "VALIDSIG" and len(parts) >= 2:
            fprs = {parts[1].upper()}
            if len(parts) >= 11:
                fprs.add(parts[10].upper())
            info["validsig"].append(fprs)
        elif tag in BAD_STATUS:
            info["bad"].append(" ".join(parts[:3]))
    return info


def verify(tarball: Path, signature: Path, home: Path, pinned: dict[str, str], allow_unpinned: bool = False) -> tuple[bool, str]:
    """Verifica `signature` (detached, sobre el tar SIN comprimir) contra el contenido descomprimido de `tarball`."""
    try:
        sig_bytes = signature.read_bytes()
    except OSError as e:
        return False, f"no se pudo leer la firma: {e}"
    if not sig_bytes.strip():
        return False, "el archivo de firma está vacío"
    try:
        xz = subprocess.Popen(["xz", "-dc", str(tarball)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        return False, f"no se pudo ejecutar xz: {e}"
    try:
        g = subprocess.Popen(["gpg", "--homedir", str(home), "--batch", "--no-tty", "--status-fd", "1", "--verify", str(signature), "-"],
                             stdin=xz.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        xz.stdout.close()
        out, err = g.communicate(timeout=1800)
        xz_err = xz.stderr.read().decode("utf-8", "replace")
        xz_rc = xz.wait(timeout=60)
    except subprocess.TimeoutExpired:
        xz.kill()
        return False, "gpg/xz no terminaron a tiempo"
    except OSError as e:
        xz.kill()
        return False, f"no se pudo ejecutar gpg: {e}"
    finally:
        for p in (xz, ):
            if p.poll() is None:
                p.kill()
    status = parse_status(out.decode("utf-8", "replace"))
    if xz_rc != 0:
        return False, f"xz no pudo descomprimir el tarball (rc={xz_rc}): {xz_err.strip()[:120]}"
    if status["bad"]:
        return False, f"gpg reportó: {', '.join(status['bad'])}"
    if g.returncode != 0 or not status["good"] or not status["validsig"]:
        return False, f"firma no válida (gpg rc={g.returncode}): {err.decode('utf-8', 'replace').strip()[-200:]}"
    for fprs in status["validsig"]:
        match = fprs & set(pinned)
        if match:
            return True, f"firma buena de {pinned[sorted(match)[0]]} ({sorted(match)[0]})"
    signer = sorted(status["validsig"][0])[-1]
    if allow_unpinned:
        return True, f"AVISO: firma válida de una clave que NO está pineada ({signer}); modo warn"
    return False, (f"la firma es válida pero de una clave que no está pineada: {signer}. Si es un firmante legítimo de kernel.org, "
                   "comprueba la huella en https://www.kernel.org/category/signatures.html y añádela a PINNED en este script")


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None, key_sources=None) -> int:
    ap = argparse.ArgumentParser(description="baja y verifica el tarball del kernel")
    ap.add_argument("--version", required=True)
    ap.add_argument("--dest", required=True, help="directorio donde dejar linux-<ver>.tar.xz verificado (el del PKGBUILD)")
    ap.add_argument("--allow-unpinned-signer", action="store_true")
    args = ap.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        print(f"::error::versión de kernel inválida: {args.version!r}", file=sys.stderr)
        return 2
    dest = Path(args.dest)
    if not dest.is_dir():
        print(f"::error::--dest no es un directorio: {dest}", file=sys.stderr)
        return 2
    major = args.version.split(".")[0]
    base = f"{BASE_URL}/v{major}.x"
    work = Path(tempfile.mkdtemp(prefix="avalos-kernel-verify-"))
    home = work / "gnupg"
    home.mkdir(mode=0o700)
    try:
        tar, sig = work / f"linux-{args.version}.tar.xz", work / f"linux-{args.version}.tar.sign"
        try:
            download(f"{base}/linux-{args.version}.tar.sign", sig, MAX_SIGNATURE)
            download(f"{base}/linux-{args.version}.tar.xz", tar, MAX_TARBALL, timeout=300)
        except (OSError, ValueError, urllib.error.URLError) as e:
            print(f"::error::no se pudo descargar el kernel {args.version} de kernel.org: {e}")
            return 1
        for note in import_pinned_keys(home, PINNED, key_sources):
            print(note)
        ok, msg = verify(tar, sig, home, PINNED, allow_unpinned=args.allow_unpinned_signer)
        if not ok:
            print(f"::error::tarball del kernel {args.version} NO verificado: {msg}")
            return 1
        print(f"tarball del kernel {args.version} verificado: {msg}")
        if msg.startswith("AVISO"):
            print(f"::warning::{msg}")
        sha = hashlib.sha256()
        with open(tar, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        final = dest / tar.name
        part = dest / (tar.name + ".part")
        shutil.copyfile(tar, part)
        os.replace(part, final)
        print(f"sha256 {sha.hexdigest()}  {final}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
