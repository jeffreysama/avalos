#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  AvalOS — gen-config.sh                                         ║
# ║  Genera el archivo `config` base que usa el PKGBUILD.           ║
# ║                                                                  ║
# ║  Fuente de prioridad (de mayor a menor):                        ║
# ║    1. /proc/config.gz  (kernel actual del host)                 ║
# ║    2. /boot/config-$(uname -r)  (archivo de config del host)   ║
# ║    3. Config de Arch Linux (descargada desde archlinux.org)     ║
# ║    4. defconfig  (mínima, como último recurso)                  ║
# ║                                                                  ║
# ║  La idea: usar la config de Arch Linux como base, que es la más ║
# ║  cercana a un kernel "completo funcional", y encima el prepare()║
# ║  del PKGBUILD añade las configs específicas de AvalOS.          ║
# ╚══════════════════════════════════════════════════════════════════╝
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/config"

# Versión del kernel (para buscar la config de Arch correcta)
PKGVER=$(grep '^pkgver=' "$SCRIPT_DIR/PKGBUILD" | cut -d= -f2)
MAJOR="${PKGVER%%.*}"
MINOR="${PKGVER#*.}"; MINOR="${MINOR%.*}"

echo "==> gen-config.sh — AvalOS kernel config"
echo "    pkgver: $PKGVER  (${MAJOR}.${MINOR}.x)"

# ── Opción 1: kernel actual del host ──────────────────────────────────────────
if [[ -f /proc/config.gz ]]; then
    echo "    Fuente: /proc/config.gz (kernel actual del host)"
    zcat /proc/config.gz > "$OUT"
    echo "    ✓ config generado desde /proc/config.gz"
    exit 0
fi

# ── Opción 2: archivo /boot/config-$(uname -r) ────────────────────────────────
if [[ -f "/boot/config-$(uname -r)" ]]; then
    echo "    Fuente: /boot/config-$(uname -r)"
    cp "/boot/config-$(uname -r)" "$OUT"
    echo "    ✓ config generado desde /boot"
    exit 0
fi

# ── Opción 3: config de Arch Linux (ideal para CI/GitHub Actions) ─────────────
# Arch publica su config en el repo extra de paquetes; la descargamos de ALA
# (Arch Linux Archive) para la versión exacta del kernel si está disponible.
ARCH_CONFIG_URLS=(
    # ALA — versión exacta (puede no existir si es muy reciente)
    "https://archive.archlinux.org/packages/l/linux/linux-${PKGVER}.pkg.tar.zst"
    # Paquete actual de Arch (siempre existe pero puede ser distinta versión)
    "https://archlinux.org/packages/core/x86_64/linux/download/"
)

echo "    Fuente: config de Arch Linux (descarga)"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Intentar descargar el paquete de Arch y extraer su config
DOWNLOADED=false
for url in "${ARCH_CONFIG_URLS[@]}"; do
    echo "    Intentando: $url"
    if curl -fsSL --max-time 60 -o "$TMPDIR/linux.pkg.tar.zst" "$url" 2>/dev/null; then
        # Extraer config desde el paquete
        if tar -I zstd -xf "$TMPDIR/linux.pkg.tar.zst" -C "$TMPDIR" \
               "./boot/config" 2>/dev/null \
           || tar -I zstd -xf "$TMPDIR/linux.pkg.tar.zst" -C "$TMPDIR" \
               "boot/config" 2>/dev/null; then
            CONFIG_FILE=$(find "$TMPDIR/boot" -name "config" | head -1)
            if [[ -f "$CONFIG_FILE" ]]; then
                cp "$CONFIG_FILE" "$OUT"
                echo "    ✓ config extraído del paquete Arch Linux"
                DOWNLOADED=true
                break
            fi
        fi
        # Intentar extraer el .config directamente (algunos paquetes lo incluyen)
        if tar -I zstd -xf "$TMPDIR/linux.pkg.tar.zst" -C "$TMPDIR" \
               --wildcards "*/config*" 2>/dev/null; then
            CONFIG_FILE=$(find "$TMPDIR" -name "config" | grep -v ".pkg" | head -1)
            if [[ -f "$CONFIG_FILE" ]]; then
                cp "$CONFIG_FILE" "$OUT"
                echo "    ✓ config extraído del paquete Arch Linux (wildcard)"
                DOWNLOADED=true
                break
            fi
        fi
    fi
done

if ! $DOWNLOADED; then
    # ── Opción 4: defconfig (último recurso) ──────────────────────────────────
    echo "    [WARN] No se pudo descargar la config de Arch. Se usará un config vacío."
    echo "    El prepare() del PKGBUILD llamará a olddefconfig para completarla."
    # Config vacío = el PKGBUILD hará `make LLVM=1 olddefconfig` que genera
    # una config completa con valores por defecto del kernel
    touch "$OUT"
fi

echo ""
echo "==> config generado en: $OUT"
echo "    Tamaño: $(wc -l < "$OUT" 2>/dev/null || echo 0) líneas"
echo ""
echo "    Para usar localmente antes de makepkg:"
echo "      cd pkgs/linux-avalos"
echo "      bash gen-config.sh"
echo "      makepkg -s"
