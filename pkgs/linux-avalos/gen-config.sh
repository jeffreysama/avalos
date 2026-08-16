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

_tmpdir=$(mktemp -d)
trap 'rm -rf "$_tmpdir"' EXIT
_tmpdir_pacman="$_tmpdir/pkgcache"
mkdir -p "$_tmpdir_pacman"

DOWNLOADED=false

# FIX: metodo primario ahora es 'pacman -Sw' en vez de adivinar una URL de
# descarga directa a archlinux.org/.../download/. Ese endpoint puede cambiar
# de formato, redirigir a una pagina HTML en vez del binario, o simplemente
# fallar sin que 'curl -fsSL' lo reporte como error fatal — y como el 'tar'
# subsiguiente corre con 2>/dev/null, un fallo asi quedaba TOTALMENTE
# silencioso: el script caia al fallback de 'make defconfig' (minimo, sin
# ath9k/psmouse/muchisimos drivers) sin ningun aviso visible en el log de CI.
# Esto paso de verdad el 15-ago con el kernel 7.1.8: wifi (ath9k) y touchpad
# (psmouse/i2c_hid) quedaron sin driver en la laptop del cliente porque el
# .config publicado nunca fue el real de Arch.
#
# 'pacman -Sw' usa el sistema de mirrors real de Arch (pacman.conf, no una
# URL fija), descarga el paquete SIN instalarlo, y deja rastro claro en el
# log si falla. Este script corre dentro del contenedor archlinux:base-devel
# del CI, asi que pacman ya esta disponible.
if command -v pacman &>/dev/null; then
    echo "    Fuente: pacman -Sw (paquete oficial 'linux' de Arch)"
    if pacman -Sy --noconfirm &>/dev/null \
       && pacman -Sw --noconfirm --cachedir "$_tmpdir_pacman" linux &>/dev/null; then
        PKG_FILE=$(find "$_tmpdir_pacman" -maxdepth 1 -name "linux-*.pkg.tar.zst" | sort -V | tail -1)
        if [[ -n "$PKG_FILE" ]]; then
            if tar -I zstd -xf "$PKG_FILE" -C "$_tmpdir" "./boot/config" 2>/dev/null \
               || tar -I zstd -xf "$PKG_FILE" -C "$_tmpdir" "boot/config" 2>/dev/null; then
                CONFIG_FILE=$(find "$_tmpdir/boot" -name "config" 2>/dev/null | head -1)
                if [[ -f "$CONFIG_FILE" ]] && [[ -s "$CONFIG_FILE" ]]; then
                    cp "$CONFIG_FILE" "$OUT"
                    echo "    ✓ config extraído vía pacman -Sw (${PKG_FILE##*/})"
                    DOWNLOADED=true
                fi
            fi
        fi
    fi
    if ! $DOWNLOADED; then
        echo "    [WARN] pacman -Sw no pudo traer/extraer el paquete linux — probando siguiente fuente"
    fi
fi

if ! $DOWNLOADED; then
    echo "    Fuente: config de Arch Linux (descarga directa, fallback)"
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
                    echo "    ✓ config extraído del paquete Arch Linux (descarga directa)"
                    DOWNLOADED=true
                    break
                fi
            fi
        fi
        rm -f "$_tmpdir/linux.pkg.tar.zst"
    done
fi

# FIX: validar CONTENIDO real, no solo "el archivo no esta vacio". Un config
# truncado, una pagina de error HTML guardada por error, o un config de un
# kernel muy viejo/minimo pasarian el chequeo anterior (`[[ -s "$OUT" ]]`)
# sin problema. Un .config real y completo de Arch tiene ~9000+ lineas
# totales y miles de simbolos habilitados (=y o =m). Un 'make defconfig'
# minimo genera bastantes menos simbolos habilitados que eso. Se exige un
# minimo de 3000 simbolos ACTIVOS (no solo lineas totales) para aceptar el
# archivo como valido antes de darlo por bueno.
if $DOWNLOADED; then
    _enabled_count=$(grep -cE '^CONFIG_[A-Z0-9_]+=[ym]$' "$OUT" 2>/dev/null || echo 0)
    echo "    Símbolos habilitados detectados: ${_enabled_count}"
    if (( _enabled_count < 3000 )); then
        echo "    [WARN] Solo ${_enabled_count} símbolos habilitados (se esperan miles) —"
        echo "           el archivo descargado no parece un .config completo de Arch."
        echo "           Descartando y cayendo al fallback de defconfig."
        rm -f "$OUT"
        DOWNLOADED=false
    fi
fi

if ! $DOWNLOADED; then
    echo "    [WARN] No se pudo obtener un config completo y válido de Arch."
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
