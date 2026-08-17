#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/config"

PKGVER=$(grep '^pkgver=' "$SCRIPT_DIR/PKGBUILD" | cut -d= -f2 | cut -d' ' -f1 | cut -d'#' -f1 | tr -d '[:space:]')
MAJOR="${PKGVER%%.*}"
MINOR="${PKGVER#*.}"; MINOR="${MINOR%.*}"

echo "==> gen-config.sh — AvalOS kernel config"
echo "    pkgver: $PKGVER  (${MAJOR}.${MINOR}.x)"

# FIX-HOST-CONFIG (16-ago): tanto /proc/config.gz como /boot/config-$(uname -r)
# reflejan el kernel de la maquina que esta corriendo el script AHORA MISMO —
# no el kernel real de Arch que este proyecto necesita empaquetar. En CI eso
# es el kernel del contenedor/runner (comparten kernel via runc, asi que
# /proc/config.gz expone el del host ubuntu-latest, no el de Arch); local
# puede ser cualquier kernel que la maquina tenga booteado en ese momento —
# incluyendo un linux-avalos ya roto, lo que perpetuaria en silencio el mismo
# bug de wifi/touchpad del 15-ago en un rebuild futuro. Antes estas dos
# fuentes aceptaban cualquier archivo no vacio sin mirar su CONTENIDO,
# saltandose por completo la validacion de "N+ simbolos habilitados" que ya
# existia mas abajo, pero solo para la rama de pacman/curl. Se centraliza esa
# validacion en una funcion y se aplica ahora a las 3 fuentes por igual.
MIN_ENABLED_SYMBOLS=3000

_count_enabled_symbols() {
    grep -cE '^CONFIG_[A-Z0-9_]+=[ym]$' "$OUT" 2>/dev/null || echo 0
}

if [[ -f /proc/config.gz ]]; then
    echo "    Fuente: /proc/config.gz (kernel actual del host)"
    # FIX-SET-E: zcat suelto (sin if) + set -e de la linea 2 = si zcat falla
    # (permisos, WSL sin IKCONFIG_PROC real, etc.) el script muere aqui mismo,
    # dejando "$OUT" en 0 bytes y sin llegar jamas a los fallbacks de abajo.
    if zcat /proc/config.gz > "$OUT" 2>/dev/null && [[ -s "$OUT" ]]; then
        _n=$(_count_enabled_symbols)
        if (( _n >= MIN_ENABLED_SYMBOLS )); then
            echo "    ✓ config generado desde /proc/config.gz (${_n} símbolos habilitados)"
            exit 0
        else
            echo "    [WARN] /proc/config.gz solo trae ${_n} símbolos habilitados (se esperan miles)."
            echo "           Esto es casi seguro el kernel del HOST/runner, no un kernel de"
            echo "           escritorio de Arch — descartando y probando la siguiente fuente."
            rm -f "$OUT"
        fi
    else
        echo "    [WARN] /proc/config.gz no se pudo leer o generó archivo vacío — continuando con siguiente fuente"
        rm -f "$OUT"
    fi
fi

if [[ -f "/boot/config-$(uname -r)" ]]; then
    echo "    Fuente: /boot/config-$(uname -r)"
    if cp "/boot/config-$(uname -r)" "$OUT" 2>/dev/null && [[ -s "$OUT" ]]; then
        _n=$(_count_enabled_symbols)
        if (( _n >= MIN_ENABLED_SYMBOLS )); then
            echo "    ✓ config generado desde /boot (${_n} símbolos habilitados)"
            exit 0
        else
            echo "    [WARN] /boot/config-$(uname -r) solo trae ${_n} símbolos habilitados (se esperan miles)."
            echo "           Probablemente el kernel del HOST/runner, no uno de escritorio de"
            echo "           Arch — descartando y probando la siguiente fuente."
            rm -f "$OUT"
        fi
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
# del CI COMO USUARIO 'builder' (sudo -u builder bash gen-config.sh), no como
# root — por eso 'pacman -Sy'/'pacman -Sw' necesitan 'sudo' aqui (builder
# tiene NOPASSWD:ALL configurado por el workflow). Sin el 'sudo', pacman
# fallaba por falta de permisos para escribir en /var/lib/pacman/, y como el
# intento anterior de este fix silenciaba todo con '&>/dev/null', ese fallo
# real quedaba invisible en el log — parecia "no hay red" cuando en realidad
# era "permiso denegado". Ahora se captura el output real para diagnostico.
# FIX-SANDBOX (17-ago): pacman 7 introdujo un sandbox por landlock que
# ejecuta la DESCARGA REAL como el usuario sin privilegios 'alpm'
# (DownloadUser = alpm en pacman.conf), sin importar que pacman en si se haya
# invocado via sudo/root. Ese sandbox conoce las rutas normales de pacman
# (/var/cache/pacman/pkg, /var/lib/pacman/sync — por eso 'pacman -Sy' de
# abajo funciona bien), pero NO tiene por que tener acceso al directorio que
# nosotros armamos con 'mktemp -d' (dueño 'builder', modo 700) y pasamos via
# '--cachedir'. El resultado es exactamente lo que se vio en un build real:
# "-Sy" completa la sincronizacion de bases de datos sin problema, y luego
# "-Sw --cachedir $_tmpdir_pacman" falla con "Permission denied" al intentar
# escribir el .part del paquete — no es un problema de red ni de que falte
# sudo, es el sandbox del usuario alpm chocando con un directorio que no
# conoce. '--disable-sandbox' devuelve la descarga a correr con los mismos
# privilegios de quien invoco pacman (root, via sudo), igual que en pacman <7.
if command -v pacman &>/dev/null; then
    echo "    Fuente: pacman -Sw (paquete oficial 'linux' de Arch)"
    _pacman_log="$_tmpdir/pacman.log"
    _sudo=""
    [[ "$(id -u)" != "0" ]] && _sudo="sudo"
    if $_sudo pacman -Sy --noconfirm --disable-sandbox > "$_pacman_log" 2>&1 \
       && $_sudo pacman -Sw --noconfirm --nodeps --nodeps --disable-sandbox --cachedir "$_tmpdir_pacman" linux >> "$_pacman_log" 2>&1; then
        # FIX: 'pacman -Sw linux' sin '--nodeps --nodeps' tambien descarga las
        # dependencias de 'linux' (incluyendo 'linux-firmware', que SI depende
        # de el) al mismo --cachedir. El glob "linux-*.pkg.tar.zst" original
        # coincidia tambien con "linux-firmware-*" y "linux-firmware-whence-*",
        # y 'sort -V | tail -1' podia terminar eligiendo ESE archivo en vez
        # del kernel real — que ademas ni siquiera trae /boot/config, asi que
        # el resultado habria sido: o bien un config equivocado, o una nueva
        # caida silenciosa al fallback de defconfig, disfrazada de "exito".
        # '--nodeps --nodeps' (doble, para ignorar TODAS las dependencias, no
        # solo un nivel) evita que aparezca nada mas que el propio 'linux' en
        # el cachedir. El patron de busqueda ademas se restringe a exigir un
        # digito justo despues de "linux-" (la version del kernel), lo cual
        # por si solo ya excluye "linux-firmware*"/"linux-headers*" como
        # defensa adicional aunque --nodeps fallara por algun motivo.
        PKG_FILE=$(find "$_tmpdir_pacman" -maxdepth 1 -name "linux-[0-9]*-x86_64.pkg.tar.zst" | sort -V | tail -1)
        if [[ -n "$PKG_FILE" ]]; then
            if tar -I zstd -xf "$PKG_FILE" -C "$_tmpdir" "./boot/config" 2>/dev/null \
               || tar -I zstd -xf "$PKG_FILE" -C "$_tmpdir" "boot/config" 2>/dev/null; then
                CONFIG_FILE=$(find "$_tmpdir/boot" -name "config" 2>/dev/null | head -1)
                if [[ -f "$CONFIG_FILE" ]] && [[ -s "$CONFIG_FILE" ]]; then
                    cp "$CONFIG_FILE" "$OUT"
                    echo "    ✓ config extraído vía pacman -Sw (${PKG_FILE##*/})"
                    DOWNLOADED=true
                else
                    # FIX-DIAG (17-ago): antes esto caia en silencio al WARN
                    # generico de mas abajo, sin decir CUAL de los 4 pasos
                    # (comando pacman / find del .pkg.tar.zst / tar de
                    # boot/config / boot/config vacio) fue el que fallo —
                    # obligando a ir a cazar el log completo a mano cada vez.
                    echo "    [WARN] pacman -Sw: boot/config se extrajo de ${PKG_FILE##*/} pero salió vacío o no existe"
                fi
            else
                echo "    [WARN] pacman -Sw: no se pudo extraer boot/config de ${PKG_FILE##*/} — contenido real del paquete:"
                tar -I zstd -tf "$PKG_FILE" 2>/dev/null | grep -i boot | head -10 | sed 's/^/           /'
            fi
        else
            echo "    [WARN] pacman -Sw: el comando terminó sin error pero no se encontró ningún .pkg.tar.zst en $_tmpdir_pacman"
            echo "           Contenido real de $_tmpdir_pacman:"
            find "$_tmpdir_pacman" -maxdepth 2 2>/dev/null | sed 's/^/           /'
        fi
    else
        echo "    [WARN] pacman -Sy o pacman -Sw devolvieron código de error (ver diagnóstico abajo)"
    fi
    if ! $DOWNLOADED; then
        echo "    --- output completo de pacman (diagnóstico) ---"
        # FIX-DIAG: 'tail -20' venia cortando justo el error real cuando -Sy
        # y -Sw comparten el mismo log ("$_pacman_log" con > y luego >>) — la
        # salida de -Sy sola ya ocupa varias lineas, asi que un fallo tardio
        # de -Sw quedaba fuera de la ventana de 20 lineas. Se sube a 60.
        tail -60 "$_pacman_log" 2>/dev/null | sed 's/^/    /'
        echo "    ---------------------------------------"
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
    _enabled_count=$(_count_enabled_symbols)
    echo "    Símbolos habilitados detectados: ${_enabled_count}"
    if (( _enabled_count < MIN_ENABLED_SYMBOLS )); then
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
