#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/config"

PKGVER=$(grep '^pkgver=' "$SCRIPT_DIR/PKGBUILD" | cut -d= -f2 | cut -d' ' -f1 | cut -d'#' -f1 | tr -d '[:space:]')
MAJOR="${PKGVER%%.*}"
MINOR="${PKGVER#*.}"; MINOR="${MINOR%.*}"

echo "==> gen-config.sh — AvalOS kernel config"
echo "    pkgver: $PKGVER  (${MAJOR}.${MINOR}.x)"

if [[ -f /proc/config.gz ]]; then
    echo "    Fuente: /proc/config.gz (kernel actual del host)"
    # FIX-SET-E: zcat suelto (sin if) + set -e de la linea 2 = si zcat falla
    # (permisos, WSL sin IKCONFIG_PROC real, etc.) el script muere aqui mismo,
    # dejando "$OUT" en 0 bytes y sin llegar jamas a los fallbacks de abajo.
    if zcat /proc/config.gz > "$OUT" 2>/dev/null && [[ -s "$OUT" ]]; then
        echo "    ✓ config generado desde /proc/config.gz"
        exit 0
    else
        echo "    [WARN] /proc/config.gz no se pudo leer o generó archivo vacío — continuando con siguiente fuente"
        rm -f "$OUT"
    fi
fi

if [[ -f "/boot/config-$(uname -r)" ]]; then
    echo "    Fuente: /boot/config-$(uname -r)"
    if cp "/boot/config-$(uname -r)" "$OUT" 2>/dev/null && [[ -s "$OUT" ]]; then
        echo "    ✓ config generado desde /boot"
        exit 0
    else
        echo "    [WARN] /boot/config-$(uname -r) no se pudo copiar o está vacío — continuando con siguiente fuente"
        rm -f "$OUT"
    fi
fi

ARCH_CONFIG_URLS=(
    "https://archlinux.org/packages/core/x86_64/linux/download/"
)

echo "    Fuente: config de Arch Linux (descarga)"
_tmpdir=$(mktemp -d)
trap 'rm -rf "$_tmpdir"' EXIT

DOWNLOADED=false
for url in "${ARCH_CONFIG_URLS[@]}"; do
    echo "    Intentando: $url"
    if curl -fsSL --max-time 60 -o "$_tmpdir/linux.pkg.tar.zst" "$url" 2>/dev/null; then
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
    fi
    rm -f "$_tmpdir/linux.pkg.tar.zst"
done

if ! $DOWNLOADED; then
    echo "    [WARN] No se pudo descargar la config de Arch."
    echo "    Se generará un config mínimo con 'make defconfig' en prepare()."
    echo "    Nota: el PKGBUILD llamará 'make LLVM=1 olddefconfig' que lo completará."
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
