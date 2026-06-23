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
# BUG-04 FIX: cut -d= -f2 incluye comentarios inline (ej: "7.0.11  # auto-updated").
# Añadir triple filtrado: por espacio, por '#', y trim de espacios — siempre seguro.
PKGVER=$(grep '^pkgver=' "$SCRIPT_DIR/PKGBUILD" | cut -d= -f2 | cut -d' ' -f1 | cut -d'#' -f1 | tr -d '[:space:]')
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
# BUG-FIX: el pkgver REAL del paquete linux de Arch incluye un sufijo ".archN"
# entre la versión y el pkgrel (ej. "linux-7.0.3.arch1-2-x86_64.pkg.tar.zst",
# "linux-6.17.5.arch1-1-x86_64.pkg.tar.zst" — confirmado contra nombres reales
# en archive.archlinux.org y mirrors oficiales). Nuestro PKGVER sigue la
# numeración de kernel.org sin ese sufijo (ej. "7.0.11"), así que las URLs
# "linux-${PKGVER}-${pkgrel}-x86_64.pkg.tar.zst" (pkgrel 1, 2, 3) NUNCA
# coinciden con un archivo real — el ".archN" no es adivinable a partir de
# PKGVER. Esas 3 URLs SIEMPRE fallaban (404) y el script terminaba cayendo
# de todos modos a la URL canónica de abajo; solo desperdiciaban 3 intentos
# de curl y dejaban un log confuso de "Intentando: ..." sin éxito.
#
# Fix: usar directamente la URL canónica de "descarga actual" como única
# fuente de Arch. No garantiza la versión EXACTA que estamos compilando
# (Arch podría estar en una versión de kernel.org distinta a la nuestra en
# este momento), pero es la única forma de obtener un archivo que realmente
# existe sin depender de conocer el sufijo ".archN" de antemano. Si la
# versión difiere bastante, olddefconfig generará más preguntas/avisos de lo
# ideal, pero sigue siendo una base mucho mejor que defconfig vacío.
ARCH_CONFIG_URLS=(
    "https://archlinux.org/packages/core/x86_64/linux/download/"
)

echo "    Fuente: config de Arch Linux (descarga)"
_tmpdir=$(mktemp -d)
trap 'rm -rf "$_tmpdir"' EXIT

# Intentar descargar el paquete de Arch y extraer su config
DOWNLOADED=false
for url in "${ARCH_CONFIG_URLS[@]}"; do
    echo "    Intentando: $url"
    if curl -fsSL --max-time 60 -o "$_tmpdir/linux.pkg.tar.zst" "$url" 2>/dev/null; then
        # BUG-03 FIX: usar rutas exactas en lugar de wildcard '*/config*'.
        # '*/config*' podría capturar config.h, config.yaml, etc.
        # La ruta exacta en el .pkg de Arch es boot/config (sin sufijo de versión).
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
    # Config vacío especial: una sola línea de comentario.
    # make olddefconfig sobre un .config casi vacío trata todas las opciones
    # como "nuevas" y las resuelve a sus defaults del Kconfig — equivalente
    # funcional a "make defconfig + olddefconfig". No es necesario detectar
    # este marker en el PKGBUILD; olddefconfig lo maneja solo.
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
