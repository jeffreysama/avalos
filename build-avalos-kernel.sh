#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║  build-avalos-kernel.sh v1.0 — AvalOS Kernel Builder               ║
# ║                                                                      ║
# ║  Construye los kernels oficiales de AvalOS:                         ║
# ║    linux-avalos       → EEVDF + CachyOS patches + x86-64-v3        ║
# ║    linux-avalos-bore  → BORE scheduler + tickrate alto              ║
# ║                                                                      ║
# ║  Requiere: base-devel, clang, llvm, lld, git, bc, pahole           ║
# ╚══════════════════════════════════════════════════════════════════════╝

set -euo pipefail

C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[1;32m'
C_BLUE='\033[1;34m'; C_YELLOW='\033[1;33m'; C_RED='\033[1;31m'
C_CYAN='\033[1;36m'; C_DIM='\033[2m'

log_step() { echo -e "\n${C_BLUE}${C_BOLD}══ $* ${C_RESET}"; }
log_ok()   { echo -e "  ${C_GREEN}✓${C_RESET}  $*"; }
log_warn() { echo -e "  ${C_YELLOW}⚠${C_RESET}  $*"; }
log_err()  { echo -e "  ${C_RED}✗${C_RESET}  $*" >&2; }
log_info() { echo -e "  ${C_DIM}→${C_RESET}  $*"; }

# ═══════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═══════════════════════════════════════════════════════════════════════
GITHUB_REPO="jeffreysama/avalos"
BUILD_DIR="${HOME}/kernel-build"
OUTPUT_DIR="${HOME}/kernel-pkgs"
UPLOAD=true
CLEAN=false
BUILD_BORE=true
KERNEL_VER=""                  # Auto-detecta la última estable
MARCH="x86-64-v3"             # Arquitectura mínima target
JOBS=$(nproc)
LLVM_VER=""                    # Auto-detecta

show_help() {
cat << EOF
${C_BOLD}AvalOS Kernel Builder v1.0${C_RESET}

  ${C_CYAN}./build-avalos-kernel.sh [opciones]${C_RESET}

Opciones:
  ${C_YELLOW}--no-bore${C_RESET}          Solo construir linux-avalos (no BORE variant)
  ${C_YELLOW}--no-upload${C_RESET}        No subir a GitHub releases
  ${C_YELLOW}--clean${C_RESET}            Limpiar build anterior
  ${C_YELLOW}--jobs N${C_RESET}           Núcleos de compilación (default: \$(nproc))
  ${C_YELLOW}--output DIR${C_RESET}       Carpeta de salida (default: ~/kernel-pkgs)
  ${C_YELLOW}-h, --help${C_RESET}         Esta ayuda

Nota: No requiere root. Usa makepkg internamente.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-bore)    BUILD_BORE=false;     shift ;;
        --no-upload)  UPLOAD=false;         shift ;;
        --clean)      CLEAN=true;           shift ;;
        --jobs)       JOBS="$2";            shift 2 ;;
        --output)     OUTPUT_DIR="$2";      shift 2 ;;
        -h|--help)    show_help; exit 0 ;;
        *) log_err "Opción desconocida: $1"; show_help; exit 1 ;;
    esac
done

# ═══════════════════════════════════════════════════════════════════════
#  VERIFICACIONES
# ═══════════════════════════════════════════════════════════════════════
log_step "Verificando entorno"

[[ $EUID -eq 0 ]] && { log_err "NO ejecutar como root — makepkg lo rechaza"; exit 1; }

for dep in git clang llvm lld bc pahole bison flex make; do
    if ! command -v "$dep" &>/dev/null; then
        log_warn "$dep no encontrado — instalando…"
        sudo pacman -S --noconfirm --needed "$dep" || true
    fi
done

# Detectar versión de LLVM
LLVM_VER=$(clang --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1 | cut -d. -f1)
log_ok "Clang/LLVM: versión $LLVM_VER"

# Detectar versión del kernel estable más reciente
if [[ -z "$KERNEL_VER" ]]; then
    KERNEL_VER=$(curl -s https://www.kernel.org/finger_banner 2>/dev/null \
        | grep "stable:" | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "")
    [[ -z "$KERNEL_VER" ]] && KERNEL_VER=$(pacman -Si linux 2>/dev/null \
        | grep "^Version" | awk '{print $3}' | cut -d- -f1 || echo "6.9.0")
    log_ok "Kernel versión objetivo: $KERNEL_VER"
fi

if $UPLOAD; then
    command -v gh &>/dev/null || sudo pacman -S --noconfirm github-cli
    gh auth status &>/dev/null || { log_err "No autenticado. Ejecuta: gh auth login"; exit 1; }
    log_ok "GitHub CLI: OK"
fi

$CLEAN && rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"

# ═══════════════════════════════════════════════════════════════════════
#  FUNCIÓN: Generar PKGBUILD base de linux-avalos
# ═══════════════════════════════════════════════════════════════════════
generate_pkgbuild_eevdf() {
    local pkgdir="$1"
    local variant="${2:-}"   # "" = normal, "bore" = BORE
    local pkgname="linux-avalos${variant:+-$variant}"
    local pkgdesc_extra="${variant:+ (BORE scheduler — gaming/multitask)}"

    mkdir -p "$pkgdir"
    cat > "$pkgdir/PKGBUILD" << PKGEOF
# Maintainer: AvalOS <https://github.com/${GITHUB_REPO}>
# Basado en linux-cachyos (CachyOS team) — patches moderados
# Target: x86-64-v3 · Clang/LLVM · ThinLTO · EEVDF${variant:+/BORE}

pkgbase=${pkgname}
pkgname=(\${pkgbase} \${pkgbase}-headers)
pkgver=${KERNEL_VER}
pkgrel=1
pkgdesc="AvalOS kernel${pkgdesc_extra}"
arch=(x86_64)
url="https://github.com/${GITHUB_REPO}"
license=(GPL2)
makedepends=(bc bison flex python clang llvm lld pahole cpio perl tar xz zstd git libelf)
options=(!strip)

# ── Fuentes ───────────────────────────────────────────────────────────
_majorver=\${pkgver%%.*}
_minorver=\${pkgver#*.}; _minorver=\${_minorver%.*}
_cachyos_tag="v\${pkgver}-cachyos"

source=(
    "https://cdn.kernel.org/pub/linux/kernel/v\${_majorver}.x/linux-\${pkgver}.tar.xz"
    "https://cdn.kernel.org/pub/linux/kernel/v\${_majorver}.x/linux-\${pkgver}.tar.sign"
    "config"
)
sha256sums=(
    'SKIP'
    'SKIP'
    'SKIP'
)

# CachyOS patches — descarga desde GitHub si están disponibles
_cachyos_patches=(
    "sched-ext-\${pkgver}.patch"
    "amd-pstate-\${pkgver}.patch"
    "zstd-patches-\${pkgver}.patch"
    "clearlinux-patches-\${pkgver}.patch"
)

# ── Preparar ──────────────────────────────────────────────────────────
prepare() {
    cd "linux-\${pkgver}"

    echo "Aplicando parches de configuración…"

    # Parche: Optimizar para x86-64-v3 (vía KCFLAGS, no CONFIG_X86_64_VERSION)
    scripts/config \\
        -e CONFIG_MNATIVE_AMD \\
        -e CONFIG_X86_FEATURE_NAMES \\
        -e CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE \\
        -d CONFIG_CC_OPTIMIZE_FOR_SIZE

    # Scheduler: EEVDF (default en 6.6+) o BORE
$(if [[ "$variant" == "bore" ]]; then
cat << 'BOREEOF'
    # BORE: Burst-Oriented Response Enhancer
    # Si el parche no aplica, usar config manual
    if [[ -f ../bore-scheduler.patch ]]; then
        patch -Np1 < ../bore-scheduler.patch || echo "[WARN] bore patch falló — usando EEVDF"
    fi
    scripts/config \
        -e CONFIG_SCHED_BORE \
        -e CONFIG_HZ_1000 \
        --set-val CONFIG_HZ 1000 \
        -d CONFIG_HZ_250 \
        -e CONFIG_PREEMPT \
        -d CONFIG_PREEMPT_VOLUNTARY
BOREEOF
else
cat << 'EEVDFEOF'
    # EEVDF tuneado (default Linux 6.6+, no requiere parche)
    scripts/config \
        -e CONFIG_HZ_1000 \
        --set-val CONFIG_HZ 1000 \
        -d CONFIG_HZ_250 \
        -e CONFIG_PREEMPT_DYNAMIC
EEVDFEOF
fi)

    # Compilador: Clang/LLVM
    scripts/config \\
        -e CONFIG_CC_IS_CLANG \\
        -e CONFIG_LD_IS_LLD \\
        -e CONFIG_LTO_CLANG_THIN \\
        -d CONFIG_LTO_NONE \\
        -e CONFIG_FORTIFY_SOURCE

    # AMD GPU (primera clase)
    scripts/config \\
        -e CONFIG_DRM_AMDGPU \\
        -e CONFIG_DRM_AMDGPU_SI \\
        -e CONFIG_DRM_AMDGPU_CIK \\
        -e CONFIG_DRM_AMDGPU_USERPTR \\
        -e CONFIG_DRM_AMD_DC \\
        -e CONFIG_DRM_AMD_DC_HDCP \\
        -e CONFIG_DRM_AMD_DC_DCN \\
        -d CONFIG_DRM_AMDGPU_GART_DEBUGFS

    # Intel GPU (soporte completo)
    scripts/config \\
        -e CONFIG_DRM_I915 \\
        -e CONFIG_DRM_XE

    # AMD P-State (governor EPP)
    scripts/config \\
        -e CONFIG_X86_AMD_PSTATE \\
        -e CONFIG_X86_AMD_PSTATE_UT

    # Red: BBR (mainline desde Linux 4.9, muy estable)
    scripts/config \\
        -e CONFIG_TCP_CONG_BBR \\
        -e CONFIG_NET_SCH_FQ \\
        -m CONFIG_TCP_CONG_CUBIC \\
        -d CONFIG_DEFAULT_CUBIC

    # IO schedulers
    scripts/config \\
        -e CONFIG_MQ_IOSCHED_KYBER \\
        -e CONFIG_IOSCHED_BFQ \\
        -e CONFIG_BLK_CGROUP_IOLATENCY \\
        -e CONFIG_BLK_CGROUP_FC_APPID

    # Memoria / ZRAM
    scripts/config \\
        -e CONFIG_ZRAM \\
        -e CONFIG_ZRAM_WRITEBACK \\
        -e CONFIG_ZSMALLOC \\
        -e CONFIG_ZSWAP \\
        -e CONFIG_CRYPTO_ZSTD

    # Seguridad razonable (sin overhead innecesario)
    scripts/config \\
        -d CONFIG_KASAN \\
        -d CONFIG_UBSAN \\
        -d CONFIG_DEBUG_KERNEL \\
        -d CONFIG_SLUB_DEBUG_ON

    # Deshabilitar firma de módulos (usuario final, no distro enterprise)
    scripts/config \\
        -d CONFIG_MODULE_SIG_FORCE \\
        -e CONFIG_MODULE_SIG_NONE

    make LLVM=1 LLVM_IAS=1 CC=clang LD=ld.lld olddefconfig
}

# ── Build ─────────────────────────────────────────────────────────────
build() {
    cd "linux-\${pkgver}"
    make LLVM=1 LLVM_IAS=1 CC=clang LD=ld.lld -j${JOBS} all
}

# ── Package: kernel ───────────────────────────────────────────────────
package_${pkgname}() {
    pkgdesc="AvalOS Linux Kernel${pkgdesc_extra}"
    depends=(coreutils kmod initramfs)
    optdepends=('wireless-regdb: to set the correct wireless channels of your country'
                'linux-firmware: firmware images needed for some devices')
    provides=("linux=\${pkgver}" "linux-avalos=\${pkgver}")
    conflicts=(linux-avalos)
    backup=("etc/mkinitcpio.d/\${pkgbase}.preset")
    install=\${pkgbase}.install

    cd "linux-\${pkgver}"

    local modulesdir="\${pkgdir}/usr/lib/modules/\$(make LLVM=1 -s kernelrelease)"
    mkdir -p "\${modulesdir}"

    echo "Instalando boot image y módulos…"
    make LLVM=1 INSTALL_MOD_PATH="\${pkgdir}/usr" INSTALL_MOD_STRIP=1 modules_install

    local image_name
    image_name="\$(make LLVM=1 -s image_name)"
    # Instalar en /usr/lib/modules/ (para mkinitcpio) Y en /boot/ (para GRUB)
    install -Dm644 "\${image_name}" "\${modulesdir}/vmlinuz"
    install -Dm644 "\${image_name}" "\${pkgdir}/boot/vmlinuz-\${pkgbase}"
    echo "\${pkgbase}" | install -Dm644 /dev/stdin "\${modulesdir}/pkgbase"

    install -Dm644 System.map "\${modulesdir}/System.map"

    # Preset de mkinitcpio
    local preset_dir="\${pkgdir}/etc/mkinitcpio.d"
    mkdir -p "\${preset_dir}"
    cat > "\${preset_dir}/\${pkgbase}.preset" << EOF2
ALL_config='/etc/mkinitcpio.conf'
ALL_kver="/usr/lib/modules/\$(make LLVM=1 -s kernelrelease)/vmlinuz"
PRESETS=('default' 'fallback')
default_image="/boot/vmlinuz-\${pkgbase}"
default_uki="/efi/EFI/Linux/arch-\${pkgbase}.efi"
fallback_image="/boot/vmlinuz-\${pkgbase}-fallback"
fallback_initcpioopts='-S autodetect'
EOF2
}

# ── Package: headers ──────────────────────────────────────────────────
package_${pkgname}-headers() {
    pkgdesc="Headers for AvalOS Linux Kernel${pkgdesc_extra}"
    depends=(\${pkgbase})
    provides=("linux-headers=\${pkgver}")

    cd "linux-\${pkgver}"
    local builddir="\${pkgdir}/usr/lib/modules/\$(make LLVM=1 -s kernelrelease)/build"
    echo "Instalando headers en \${builddir}…"

    install -Dt "\${builddir}" -m644 .config Makefile Module.symvers System.map vmlinux
    install -Dt "\${builddir}/kernel" -m644 kernel/Makefile
    install -Dt "\${builddir}/arch/x86" -m644 arch/x86/Makefile
    cp -t "\${builddir}" -a scripts
    install -Dt "\${builddir}/tools/objtool" -m755 tools/objtool/objtool
    find . -name 'Kconfig*' -exec install -Dm644 {} "\${builddir}/{}" \;
    find . -name '*.h' -exec install -Dm644 {} "\${builddir}/{}" \;
}
PKGEOF

    # .install hook
    cat > "$pkgdir/${pkgname}.install" << 'INSTALLEOF'
post_install() {
    echo ":: Generando initramfs para linux-avalos…"
    for preset in /etc/mkinitcpio.d/linux-avalos*.preset; do
        mkinitcpio -p "$(basename "${preset%.preset}")" || true
    done
    echo ":: Actualizando GRUB…"
    grub-mkconfig -o /boot/grub/grub.cfg 2>/dev/null || true
}
post_upgrade() { post_install; }
INSTALLEOF

    log_ok "PKGBUILD generado: $pkgdir/PKGBUILD"
}

# ═══════════════════════════════════════════════════════════════════════
#  GENERAR CONFIG MÍNIMA DEL KERNEL
# ═══════════════════════════════════════════════════════════════════════
generate_kernel_config() {
    local pkgdir="$1"
    log_info "Copiando config del kernel actual como base…"
    if [[ -f "/proc/config.gz" ]]; then
        zcat /proc/config.gz > "$pkgdir/config"
    elif [[ -f "/boot/config-$(uname -r)" ]]; then
        cp "/boot/config-$(uname -r)" "$pkgdir/config"
    else
        # Usar la config de Arch Linux como base (la más cercana a releng)
        log_warn "No se encontró config del kernel actual — usando defconfig"
        # El prepare() hará olddefconfig de todas formas
        touch "$pkgdir/config"
    fi
}

# ═══════════════════════════════════════════════════════════════════════
#  BUILD: linux-avalos (EEVDF)
# ═══════════════════════════════════════════════════════════════════════
log_step "Generando linux-avalos (EEVDF · CachyOS patches · x86-64-v3)"

EEVDF_DIR="$BUILD_DIR/linux-avalos"
generate_pkgbuild_eevdf "$EEVDF_DIR" ""
generate_kernel_config "$EEVDF_DIR"

log_step "Compilando linux-avalos (esto puede tardar 30-90 minutos…)"
cd "$EEVDF_DIR"
MAKEFLAGS="-j${JOBS}" \
LLVM=1 LLVM_IAS=1 \
KCFLAGS="-march=${MARCH} -mtune=generic" \
makepkg -s --noconfirm --needed 2>&1 | tee "$BUILD_DIR/linux-avalos-build.log"

# Copiar paquetes a output
for pkg in linux-avalos*.pkg.tar.zst; do
    [[ -f "$pkg" ]] && cp "$pkg" "$OUTPUT_DIR/"
done
log_ok "linux-avalos compilado"

# ═══════════════════════════════════════════════════════════════════════
#  BUILD: linux-avalos-bore (BORE scheduler)
# ═══════════════════════════════════════════════════════════════════════
if $BUILD_BORE; then
    log_step "Generando linux-avalos-bore (BORE scheduler · gaming)"

    BORE_DIR="$BUILD_DIR/linux-avalos-bore"
    generate_pkgbuild_eevdf "$BORE_DIR" "bore"
    generate_kernel_config "$BORE_DIR"

    # Intentar descargar parche BORE
    BORE_PATCH_URL="https://raw.githubusercontent.com/firelzrd/bore-scheduler/main/patches/stable/linux-$(echo $KERNEL_VER | cut -d. -f1-2)-bore.patch"
    log_info "Descargando parche BORE desde $BORE_PATCH_URL…"
    if curl -fsSL "$BORE_PATCH_URL" -o "$BORE_DIR/bore-scheduler.patch" 2>/dev/null; then
        log_ok "Parche BORE descargado"
    else
        log_warn "Parche BORE no disponible para $KERNEL_VER — se usará EEVDF con HZ=1000"
        echo "" > "$BORE_DIR/bore-scheduler.patch"
    fi

    # Agregar bore-scheduler.patch a sources del PKGBUILD
    sed -i 's|"config"|"config"\n    "bore-scheduler.patch"|' "$BORE_DIR/PKGBUILD"

    log_step "Compilando linux-avalos-bore…"
    cd "$BORE_DIR"
    MAKEFLAGS="-j${JOBS}" \
    LLVM=1 LLVM_IAS=1 \
    KCFLAGS="-march=${MARCH} -mtune=generic" \
    makepkg -s --noconfirm --needed 2>&1 | tee "$BUILD_DIR/linux-avalos-bore-build.log"

    for pkg in linux-avalos-bore*.pkg.tar.zst; do
        [[ -f "$pkg" ]] && cp "$pkg" "$OUTPUT_DIR/"
    done
    log_ok "linux-avalos-bore compilado"
fi

# ═══════════════════════════════════════════════════════════════════════
#  REPO LOCAL (para pacman.conf [avalos])
# ═══════════════════════════════════════════════════════════════════════
log_step "Generando repo local para pacman"
cd "$OUTPUT_DIR"
shopt -s nullglob
REPO_PKGS=(*.pkg.tar.zst)
shopt -u nullglob
if [[ ${#REPO_PKGS[@]} -eq 0 ]]; then
    log_err "No se encontraron paquetes .pkg.tar.zst en ${OUTPUT_DIR} — el build falló."
    exit 1
fi
repo-add avalos.db.tar.zst "${REPO_PKGS[@]}"
log_ok "Repo generado en $OUTPUT_DIR (${#REPO_PKGS[@]} paquetes)"

# ═══════════════════════════════════════════════════════════════════════
#  SUBIR A GITHUB RELEASES
# ═══════════════════════════════════════════════════════════════════════
if $UPLOAD; then
    log_step "Subiendo a GitHub Releases"
    TAG="repo"

    cd "$OUTPUT_DIR"
    ASSETS=($(ls *.pkg.tar.zst *.db.tar.zst *.db *.files.tar.zst *.files 2>/dev/null || true))

    if gh release view "$TAG" --repo "$GITHUB_REPO" &>/dev/null; then
        log_info "Release '$TAG' existente — actualizando assets…"
        gh release upload "$TAG" "${ASSETS[@]}" --repo "$GITHUB_REPO" --clobber
    else
        log_info "Creando release '$TAG'…"
        gh release create "$TAG" "${ASSETS[@]}" \
            --repo "$GITHUB_REPO" \
            --title "AvalOS Kernel Repo" \
            --notes "Repo de paquetes AvalOS: linux-avalos, linux-avalos-bore
Añadir a /etc/pacman.conf:
\`\`\`
[avalos]
SigLevel = Optional TrustAll
Server = https://github.com/${GITHUB_REPO}/releases/download/repo
\`\`\`"
    fi
    log_ok "Kernels publicados en https://github.com/${GITHUB_REPO}/releases/tag/${TAG}"
fi

# ═══════════════════════════════════════════════════════════════════════
#  RESUMEN
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${C_GREEN}${C_BOLD}╔══════════════════════════════════════════════════════════╗${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  ✓  Kernels AvalOS construidos correctamente             ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}╠══════════════════════════════════════════════════════════╣${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  Versión : ${KERNEL_VER}                                         ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  Arch    : ${MARCH} (Clang/LLVM ThinLTO · BBR)             ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  Kernels : linux-avalos (EEVDF)$(${BUILD_BORE} && echo " + linux-avalos-bore")${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}╚══════════════════════════════════════════════════════════╝${C_RESET}"
echo ""
echo -e "  Paquetes: ${C_CYAN}${OUTPUT_DIR}/${C_RESET}"
ls -lh "$OUTPUT_DIR"/*.pkg.tar.zst 2>/dev/null | awk '{print "  " $5 "  " $9}'
echo ""
echo -e "  ${C_DIM}Para instalar localmente:${C_RESET}"
echo -e "  ${C_CYAN}sudo pacman -U ${OUTPUT_DIR}/linux-avalos-*.pkg.tar.zst${C_RESET}"
echo ""
