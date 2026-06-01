#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  AvalOS — gen-config.sh                                         ║
# ║  Genera el archivo `config` base que usa el PKGBUILD.           ║
# ║                                                                  ║
# ║  Fuente de prioridad (de mayor a menor):                        ║
# ║    1. /proc/config.gz  (kernel actual del host)                 ║
# ║    2. /boot/config-$(uname -r)  (archivo de config del host)   ║
# ║    3. Config de Arch Linux (descargada desde ALA/archlinux.org) ║
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
    # BUG-017 FIX: verificar que el config generado tiene contenido.
    # /proc/config.gz puede existir pero estar vacío/corrupto.
    if [[ -s "$OUT" ]]; then
        echo "    ✓ config generado desde /proc/config.gz"
        exit 0
    else
        echo "    [WARN] /proc/config.gz generó archivo vacío — continuando con siguiente fuente"
        rm -f "$OUT"
    fi
fi

# ── Opción 2: archivo /boot/config-$(uname -r) ────────────────────────────────
if [[ -f "/boot/config-$(uname -r)" ]]; then
    echo "    Fuente: /boot/config-$(uname -r)"
    cp "/boot/config-$(uname -r)" "$OUT"
    if [[ -s "$OUT" ]]; then
        echo "    ✓ config generado desde /boot"
        exit 0
    else
        echo "    [WARN] /boot/config-$(uname -r) está vacío — continuando con siguiente fuente"
        rm -f "$OUT"
    fi
fi

# ── Opción 3: config de Arch Linux (ideal para CI/GitHub Actions) ─────────────
# Arch publica su config en el repo extra de paquetes; la descargamos de ALA
# (Arch Linux Archive) para la versión exacta del kernel si está disponible.
#
# FIX: el pkgrel en ALA no siempre es -1 — frecuentemente hay rebuilds (-2, -3).
# Si pkgrel-1 no existe, se prueba hasta -3 antes de caer al paquete actual.
# Esto evita descargar un config de una versión diferente del kernel (ej. 7.0.9
# cuando compilamos 7.0.10), que generaría miles de advertencias en olddefconfig.

ARCH_CONFIG_URLS=()

# ALA — versión exacta con pkgrel 1, 2 y 3
for pkgrel in 1 2 3; do
    ARCH_CONFIG_URLS+=(
        "https://archive.archlinux.org/packages/l/linux/linux-${PKGVER}-${pkgrel}-x86_64.pkg.tar.zst"
    )
done

# Paquete actual de Arch (siempre existe pero puede ser distinta versión)
ARCH_CONFIG_URLS+=(
    "https://archlinux.org/packages/core/x86_64/linux/download/"
)

# Mirror alternativo geo-distribuido como fallback adicional
ARCH_CONFIG_URLS+=(
    "https://geo.mirror.pkgbuild.com/core/os/x86_64/linux-${PKGVER}-1-x86_64.pkg.tar.zst"
)

echo "    Fuente: config de Arch Linux (descarga)"
_tmpdir=$(mktemp -d)
trap 'rm -rf "$_tmpdir"' EXIT

# Intentar descargar el paquete de Arch y extraer su config
DOWNLOADED=false
for url in "${ARCH_CONFIG_URLS[@]}"; do
    echo "    Intentando: $url"
    if curl -fsSL --max-time 60 -o "$_tmpdir/linux.pkg.tar.zst" "$url" 2>/dev/null; then
        # Extraer config desde el paquete
        if tar -I zstd -xf "$_tmpdir/linux.pkg.tar.zst" -C "$_tmpdir" \
               "./boot/config" 2>/dev/null \
           || tar -I zstd -xf "$_tmpdir/linux.pkg.tar.zst" -C "$_tmpdir" \
               "boot/config" 2>/dev/null; then
            CONFIG_FILE=$(find "$_tmpdir/boot" -name "config" | head -1)
            if [[ -f "$CONFIG_FILE" ]] && [[ -s "$CONFIG_FILE" ]]; then
                cp "$CONFIG_FILE" "$OUT"
                echo "    ✓ config extraído del paquete Arch Linux"
                DOWNLOADED=true
                break
            fi
        fi
        # Intentar extraer el .config directamente (algunos paquetes lo incluyen)
        if tar -I zstd -xf "$_tmpdir/linux.pkg.tar.zst" -C "$_tmpdir" \
               --wildcards "*/config*" 2>/dev/null; then
            CONFIG_FILE=$(find "$_tmpdir" -name "config" | grep -v ".pkg" | head -1)
            if [[ -f "$CONFIG_FILE" ]] && [[ -s "$CONFIG_FILE" ]]; then
                cp "$CONFIG_FILE" "$OUT"
                echo "    ✓ config extraído del paquete Arch Linux (wildcard)"
                DOWNLOADED=true
                break
            fi
        fi
    fi
    # Limpiar el .pkg descargado fallido antes del siguiente intento
    rm -f "$_tmpdir/linux.pkg.tar.zst"
done

if ! $DOWNLOADED; then
    # ── Opción 4: defconfig (último recurso) ──────────────────────────────────
    # FIX: en lugar de un archivo vacío, usar make defconfig como base mínima.
    # Un config vacío hace que olddefconfig active TODOS los módulos por defecto
    # (~4000 opciones extra), lo que resulta en un kernel mucho más grande y
    # un tiempo de compilación considerablemente mayor.
    # Con defconfig, olddefconfig solo necesita resolver las opciones específicas
    # de AvalOS que se añaden en prepare().
    echo "    [WARN] No se pudo descargar la config de Arch."
    echo "    Se generará un config mínimo con 'make defconfig' en prepare()."
    echo "    Nota: el PKGBUILD llamará 'make LLVM=1 olddefconfig' que lo completará."
    # Config vacío especial: una sola línea para indicar que es el fallback.
    # prepare() lo detecta y llama a 'make defconfig' antes de olddefconfig.
    echo "# AVALOS_FALLBACK_DEFCONFIG" > "$OUT"
fi

echo ""
echo "==> config generado en: $OUT"
echo "    Tamaño: $(wc -l < "$OUT" 2>/dev/null || echo 0) líneas"
echo ""
echo "    Para usar localmente antes de makepkg:"
echo "      cd pkgs/linux-avalos"
echo "      bash gen-config.sh"
echo "      makepkg -s"
