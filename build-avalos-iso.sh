#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  build-avalos-iso.sh v2.0 — AvalOS ISO Builder                  ║
# ║                                                                   ║
# ║  NUEVO: bundlea skill_instalar_usb.py dentro de la ISO y lo     ║
# ║  registra como app de escritorio + autostart en Hyprland live.  ║
# ║  La ISO arranca directo en SDDM → Hyprland live → instalador.   ║
# ╚══════════════════════════════════════════════════════════════════╝

set -euo pipefail

C_RESET='\033[0m'
C_BOLD='\033[1m'
C_GREEN='\033[1;32m'
C_BLUE='\033[1;34m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_CYAN='\033[1;36m'
C_DIM='\033[2m'

log_step() { echo -e "\n${C_BLUE}${C_BOLD}══ $* ${C_RESET}"; }
log_ok()   { echo -e "  ${C_GREEN}✓${C_RESET}  $*"; }
log_warn() { echo -e "  ${C_YELLOW}⚠${C_RESET}  $*"; }
log_err()  { echo -e "  ${C_RED}✗${C_RESET}  $*" >&2; }
log_info() { echo -e "  ${C_DIM}→${C_RESET}  $*"; }

# ═══════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═══════════════════════════════════════════════════════════════════
DISTRO_NAME="AvalOS"
DISTRO_ID="avalos"
GITHUB_REPO="jeffreysama/avalos"
GITHUB_RELEASES_URL="https://github.com/${GITHUB_REPO}/releases/download/repo"

KERNEL_PKG="linux"
KERNEL_HEADERS_PKG="linux-headers"
VERSION=""
OUTPUT_DIR="${HOME}/iso"
BUILD_DIR="/tmp/avalos-iso-build"
UPLOAD=true
CLEAN=false

# ═══════════════════════════════════════════════════════════════════
#  ARGS
# ═══════════════════════════════════════════════════════════════════
show_help() {
cat << EOF
${C_BOLD}${DISTRO_NAME} ISO Builder v2.0${C_RESET}

  ${C_CYAN}sudo ./build-avalos-iso.sh [opciones]${C_RESET}

Opciones:
  ${C_YELLOW}-v, --version${C_RESET}  VERSION   Versión (ej: 2025.06.01). Default: fecha actual
  ${C_YELLOW}-o, --output${C_RESET}   DIR       Carpeta de salida. Default: ~/iso
  ${C_YELLOW}-k, --kernel${C_RESET}   PKGNAME   Kernel a incluir. Default: auto-detecta linux-avalos
  ${C_YELLOW}    --no-upload${C_RESET}           Construir sin subir a GitHub
  ${C_YELLOW}    --clean${C_RESET}               Limpiar build anterior
  ${C_YELLOW}-h, --help${C_RESET}                Esta ayuda
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--version)   VERSION="$2";       shift 2 ;;
        -o|--output)    OUTPUT_DIR="$2";    shift 2 ;;
        -k|--kernel)    KERNEL_PKG="$2";    KERNEL_HEADERS_PKG="${2}-headers"; shift 2 ;;
        --no-upload)    UPLOAD=false;        shift ;;
        --clean)        CLEAN=true;          shift ;;
        -h|--help)      show_help; exit 0 ;;
        *)  log_err "Opción desconocida: $1"; show_help; exit 1 ;;
    esac
done

# ═══════════════════════════════════════════════════════════════════
#  VERIFICACIONES PREVIAS
# ═══════════════════════════════════════════════════════════════════
log_step "Verificando entorno"

[[ $EUID -ne 0 ]] && { log_err "Necesita root. Usa: sudo $0 $*"; exit 1; }

command -v mkarchiso &>/dev/null || { log_warn "Instalando archiso…"; pacman -S --noconfirm --needed archiso; }
log_ok "archiso disponible"

if $UPLOAD; then
    command -v gh &>/dev/null || { log_warn "Instalando github-cli…"; pacman -S --noconfirm --needed github-cli; }
    gh auth status &>/dev/null || { log_err "No autenticado en GitHub. Ejecuta: gh auth login"; exit 1; }
    log_ok "GitHub CLI autenticado ($(gh api user --jq .login 2>/dev/null || echo 'OK'))"
fi

# Auto-detectar kernel personalizado
if [[ "$KERNEL_PKG" == "linux" ]]; then
    if pacman -Qq linux-avalos &>/dev/null 2>&1; then
        KERNEL_PKG="linux-avalos"; KERNEL_HEADERS_PKG="linux-avalos-headers"
        log_ok "Kernel personalizado: linux-avalos"
    else
        log_info "Usando kernel estándar: linux"
    fi
fi

# Versión
[[ -z "$VERSION" ]] && VERSION="$(date +%Y.%m.%d)"
if git -C "$(dirname "$0")" describe --tags --abbrev=0 &>/dev/null 2>&1; then
    GIT_VER="$(git -C "$(dirname "$0")" describe --tags --abbrev=0)"
    VERSION="${GIT_VER#v}"
    log_ok "Versión desde git tag: ${VERSION}"
else
    log_info "Versión auto-generada: ${VERSION}"
fi

ISO_NAME="${DISTRO_ID}-${VERSION}-x86_64"
ISO_FILE="${OUTPUT_DIR}/${ISO_NAME}.iso"
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# ═══════════════════════════════════════════════════════════════════
#  VALIDAR EXISTENCIA DEL INSTALADOR
# ═══════════════════════════════════════════════════════════════════
INSTALLER_SRC="${SCRIPT_DIR}/skill_instalar_usb.py"
if [[ ! -f "$INSTALLER_SRC" ]]; then
    log_warn "skill_instalar_usb.py no encontrado junto al script."
    log_warn "El live USB no tendrá instalador gráfico automático."
    log_warn "Coloca skill_instalar_usb.py en: ${SCRIPT_DIR}"
    INSTALLER_SRC=""
fi

log_ok "Configuración:"
echo -e "     Distro    : ${C_CYAN}${DISTRO_NAME} ${VERSION}${C_RESET}"
echo -e "     Kernel    : ${C_CYAN}${KERNEL_PKG}${C_RESET}"
echo -e "     ISO       : ${C_CYAN}${ISO_FILE}${C_RESET}"
echo -e "     Instalador: ${C_CYAN}${INSTALLER_SRC:-NO ENCONTRADO}${C_RESET}"
echo -e "     GitHub    : ${C_CYAN}$( $UPLOAD && echo "${GITHUB_REPO}" || echo "sin subir" )${C_RESET}"

# ═══════════════════════════════════════════════════════════════════
#  PREPARAR DIRECTORIO DE BUILD
# ═══════════════════════════════════════════════════════════════════
log_step "Preparando perfil archiso"

$CLEAN && [[ -d "$BUILD_DIR" ]] && { log_info "Limpiando build anterior…"; rm -rf "$BUILD_DIR"; }
mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"

PROFILE_SRC="/usr/share/archiso/configs/releng"
[[ -d "$PROFILE_SRC" ]] || { log_err "Perfil archiso no encontrado: $PROFILE_SRC"; exit 1; }
cp -r "$PROFILE_SRC/." "$BUILD_DIR/"
log_ok "Perfil releng copiado"

AIROOTFS="$BUILD_DIR/airootfs"

# ═══════════════════════════════════════════════════════════════════
#  profiledef.sh
# ═══════════════════════════════════════════════════════════════════
log_step "profiledef.sh"

cat > "$BUILD_DIR/profiledef.sh" << PROFILEEOF
#!/usr/bin/env bash
iso_name="${ISO_NAME}"
iso_label="${DISTRO_NAME}_${VERSION//./_}"
iso_publisher="${DISTRO_NAME} <https://github.com/${GITHUB_REPO}>"
iso_application="${DISTRO_NAME} — Arch-based · Hyprland · Tokyo Night"
iso_version="${VERSION}"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux' 'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/usr/local/bin/avalos-install"]="0:0:755"
)
PROFILEEOF
log_ok "profiledef.sh listo"

# ═══════════════════════════════════════════════════════════════════
#  pacman.conf
# ═══════════════════════════════════════════════════════════════════
log_step "pacman.conf"

cp /etc/pacman.conf "$BUILD_DIR/pacman.conf"
grep -q "\[avalos\]" "$BUILD_DIR/pacman.conf" || cat >> "$BUILD_DIR/pacman.conf" << PACEOF

[avalos]
SigLevel = Optional TrustAll
Server = ${GITHUB_RELEASES_URL}
PACEOF
sed -i 's/^#ParallelDownloads/ParallelDownloads/' "$BUILD_DIR/pacman.conf" || true
log_ok "pacman.conf con repo [avalos]"

# ═══════════════════════════════════════════════════════════════════
#  packages.x86_64
# ═══════════════════════════════════════════════════════════════════
log_step "packages.x86_64"

cat > "$BUILD_DIR/packages.x86_64" << PKGEOF
# ── AvalOS live environment ──────────────────────────────────────
# Kernel
${KERNEL_PKG}
${KERNEL_HEADERS_PKG}
linux-firmware
amd-ucode

# Base
base
base-devel
sudo
bash
bash-completion

# Boot
grub
efibootmgr
os-prober
syslinux
memtest86+
memtest86+-efi

# Red
networkmanager
nm-connection-editor
network-manager-applet

# Herramientas
nano
vim
git
curl
wget
htop
man-db
man-pages
less
openssh
zip
unzip
p7zip
python
python-pip
reflector
pacman-contrib
xdg-utils
fastfetch
bat
github-cli

# AMD GPU
mesa
mesa-utils
vulkan-radeon
vulkan-icd-loader
vulkan-tools
libva-mesa-driver
libva-utils
radeontop
gstreamer-vaapi

# Hyprland + Wayland
hyprland
xdg-desktop-portal-hyprland
xdg-desktop-portal-gtk
xdg-user-dirs
kitty
waybar
rofi-wayland
dunst
hyprpaper
hyprlock
hypridle
hyprpicker
grim
slurp
wl-clipboard
cliphist
pipewire
pipewire-alsa
pipewire-pulse
pipewire-jack
wireplumber
pavucontrol
qt5-wayland
qt6-wayland
gtk3
gtk4
hyprpolkitagent
thunar
gvfs
brightnessctl
ttf-font-awesome
ttf-jetbrains-mono-nerd
ttf-nerd-fonts-symbols
noto-fonts
noto-fonts-emoji
sddm
blueman
playerctl
firefox
bluez
bluez-utils
libnotify
file-roller
thunar-archive-plugin
thunar-volman
gvfs-mtp
gvfs-smb
nwg-look
papirus-icon-theme
lm_sensors
acpi
capitaine-cursors
udiskie
zram-generator

# Deps del instalador gráfico (pywebview)
python-gobject
webkit2gtk-4.1
python-pywebview
parted

# Archiso (disponible en el live para rebuild)
archiso
PKGEOF

log_ok "packages.x86_64 generado ($(wc -l < "$BUILD_DIR/packages.x86_64") líneas)"

# ═══════════════════════════════════════════════════════════════════
#  airootfs — identidad + instalador + autostart
# ═══════════════════════════════════════════════════════════════════
log_step "Configurando airootfs"

mkdir -p "$AIROOTFS/etc"

# os-release / lsb-release / hostname
cat > "$AIROOTFS/etc/os-release" << OSEOF
NAME="${DISTRO_NAME}"
PRETTY_NAME="${DISTRO_NAME} ${VERSION} Live"
ID=${DISTRO_ID}
ID_LIKE=arch
BUILD_ID=${VERSION}
ANSI_COLOR="38;2;122;162;247"
HOME_URL="https://github.com/${GITHUB_REPO}"
DOCUMENTATION_URL="https://wiki.archlinux.org"
LOGO=${DISTRO_ID}-logo
OSEOF

cat > "$AIROOTFS/etc/lsb-release" << LSBEOF
LSB_VERSION=1.4
DISTRIB_ID=${DISTRO_NAME}
DISTRIB_RELEASE=${VERSION}
DISTRIB_CODENAME=${DISTRO_ID}
DISTRIB_DESCRIPTION="${DISTRO_NAME} ${VERSION} Live"
LSBEOF

echo "avalos-live" > "$AIROOTFS/etc/hostname"

# zram en el live
mkdir -p "$AIROOTFS/etc/systemd"
cat > "$AIROOTFS/etc/systemd/zram-generator.conf" << 'ZRAMEOF'
[zram0]
zram-size = min(ram / 2, 8192)
compression-algorithm = zstd
ZRAMEOF

# ── Instalar el instalador gráfico ────────────────────────────────
mkdir -p \
    "$AIROOTFS/usr/local/bin" \
    "$AIROOTFS/usr/share/applications" \
    "$AIROOTFS/usr/share/pixmaps"

if [[ -n "$INSTALLER_SRC" ]]; then
    # Script ejecutable directo
    cp "$INSTALLER_SRC" "$AIROOTFS/usr/local/bin/avalos-install"
    chmod 755 "$AIROOTFS/usr/local/bin/avalos-install"
    log_ok "skill_instalar_usb.py → /usr/local/bin/avalos-install"

    # .desktop para SDDM / apps menu / Thunar
    cat > "$AIROOTFS/usr/share/applications/avalos-install.desktop" << 'DESKEOF'
[Desktop Entry]
Name=Instalar AvalOS
Comment=Instala AvalOS en tu disco desde el entorno live
Exec=sudo /usr/local/bin/avalos-install
Icon=avalos-install
Terminal=false
Type=Application
Categories=System;
Keywords=install;installer;arch;avalos;
StartupNotify=true
DESKEOF

    # Icono SVG simple (azul Tokyo Night)
    cat > "$AIROOTFS/usr/share/pixmaps/avalos-install.svg" << 'SVGEOF'
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#1a1b26"/>
  <text x="32" y="42" font-size="32" text-anchor="middle" fill="#7aa2f7" font-family="monospace">⬇</text>
</svg>
SVGEOF

    log_ok "avalos-install.desktop + ícono creados"
else
    log_warn "Instalador no incluido (skill_instalar_usb.py no encontrado)"
fi

# ── Hyprland config del entorno LIVE ──────────────────────────────
# El live arranca como root, config en /root/.config
LIVE_HYPR="$AIROOTFS/root/.config/hypr"
mkdir -p "$LIVE_HYPR"

cat > "$LIVE_HYPR/hyprland.conf" << 'HYPREOF'
# ── AvalOS Live — hyprland.conf ──────────────────────────────────
monitor = ,preferred,auto,1

env = XCURSOR_SIZE,24
env = QT_QPA_PLATFORM,wayland;xcb
env = GDK_BACKEND,wayland,x11
env = MOZ_ENABLE_WAYLAND,1
env = AMD_VULKAN_ICD,RADV
env = VDPAU_DRIVER,radeonsi
env = LIBVA_DRIVER_NAME,radeonsi
env = __GLX_VENDOR_LIBRARY_NAME,mesa

# ── AUTOSTART del live ────────────────────────────────────────────
exec-once = waybar
exec-once = dunst
exec-once = nm-applet --indicator
exec-once = hyprpolkitagent
exec-once = udiskie -t

# ── AUTOSTART INSTALADOR: abre el wizard al entrar al live ────────
exec-once = sudo /usr/local/bin/avalos-install

general {
    gaps_in = 5; gaps_out = 10; border_size = 2
    col.active_border = rgba(7aa2f7ee) rgba(bb9af7ee) 45deg
    col.inactive_border = rgba(414868aa)
    layout = dwindle; resize_on_border = true
}

decoration {
    rounding = 10; active_opacity = 1.0; inactive_opacity = 0.9
    blur { enabled = true; size = 3; passes = 1 }
    shadow { enabled = true; range = 10; render_power = 2; color = rgba(1a1b2660) }
}

animations {
    enabled = true
    bezier = snappy, 0.05, 0.9, 0.1, 1.05
    animation = windows, 1, 5, snappy
    animation = fade, 1, 5, default
    animation = workspaces, 1, 4, default, slide
}

dwindle { pseudotile = true; preserve_split = true }

input {
    kb_layout = latam
    follow_mouse = 1; sensitivity = 0
}

misc {
    force_default_wallpaper = 0
    disable_hyprland_logo = true
    disable_splash_rendering = true
    vfr = true
}

$mod = SUPER
bind = $mod, Return, exec, kitty
bind = $mod, Space,  exec, rofi -show drun
bind = $mod, E,      exec, thunar
bind = $mod, Q,      killactive
bind = $mod, F,      fullscreen
bind = $mod, I,      exec, sudo /usr/local/bin/avalos-install
bind = $mod, 1, workspace, 1
bind = $mod, 2, workspace, 2
bind = $mod, 3, workspace, 3

windowrulev2 = float, class:(avalos-install)
windowrulev2 = float, class:(pavucontrol)
windowrulev2 = float, class:(nm-connection-editor)
HYPREOF

log_ok "hyprland.conf del live configurado (con autostart del instalador)"

# ── Waybar live (minimalista) ─────────────────────────────────────
LIVE_WAYBAR="$AIROOTFS/root/.config/waybar"
mkdir -p "$LIVE_WAYBAR"

cat > "$LIVE_WAYBAR/config.jsonc" << 'WBEOF'
{
  "layer": "top", "position": "top", "height": 28, "spacing": 4,
  "modules-left":   ["hyprland/workspaces"],
  "modules-center": ["clock"],
  "modules-right":  ["network","pulseaudio","tray","custom/install"],
  "hyprland/workspaces": {"format":"{icon}","format-icons":{"1":"①","2":"②","3":"③"},"persistent-workspaces":{"*":3}},
  "clock": {"format":"{:%H:%M  %a %d/%m/%Y}"},
  "network": {"format-wifi":"󰤨 {signalStrength}%","format-ethernet":"󰈀","format-disconnected":"󰤭 Sin red"},
  "pulseaudio": {"format":"{icon} {volume}%","format-muted":"󰝟","format-icons":{"default":["󰕿","󰖀","󰕾"]},"on-click":"pavucontrol"},
  "tray": {"spacing":8},
  "custom/install": {
    "format": "  Instalar AvalOS",
    "tooltip": false,
    "on-click": "sudo /usr/local/bin/avalos-install"
  }
}
WBEOF

cat > "$LIVE_WAYBAR/style.css" << 'WCSSEOF'
* { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 13px; border: none; border-radius: 0; min-height: 0; }
window#waybar { background-color: rgba(26,27,38,0.94); border-bottom: 2px solid rgba(122,162,247,.4); color: #c0caf5; }
.modules-left, .modules-center, .modules-right { padding: 0 6px; }
#workspaces button { color: #414868; padding: 0 4px; background: transparent; }
#workspaces button.active { color: #7aa2f7; background: rgba(122,162,247,.18); border-radius: 4px; }
#clock { color: #bb9af7; font-weight: 700; }
#network { color: #7dcfff; }
#pulseaudio { color: #c0caf5; }
#custom-install {
  color: #9ece6a; font-weight: 700; padding: 0 12px;
  background: rgba(158,206,106,.12); border: 1px solid rgba(158,206,106,.3);
  border-radius: 4px; margin: 2px 4px;
  transition: background 0.15s;
}
#custom-install:hover { background: rgba(158,206,106,.25); }
WCSSEOF

log_ok "Waybar del live configurado (botón 'Instalar AvalOS' en la barra)"

# ── dunst live ────────────────────────────────────────────────────
mkdir -p "$AIROOTFS/root/.config/dunst"
cat > "$AIROOTFS/root/.config/dunst/dunstrc" << 'DUNSTEOF'
[global]
    width = 340; height = 100; origin = top-right; offset = 10x40
    font = JetBrainsMono Nerd Font 11; markup = full
    format = "<b>%s</b>\n%b"; corner_radius = 6
    mouse_left_click = close_current

[urgency_normal]
    background = "#24283b"; foreground = "#c0caf5"; timeout = 8

[urgency_critical]
    background = "#1a0000"; foreground = "#f7768e"; timeout = 0
DUNSTEOF

# ── rofi live ─────────────────────────────────────────────────────
mkdir -p "$AIROOTFS/root/.config/rofi"
cat > "$AIROOTFS/root/.config/rofi/config.rasi" << 'ROFIEOF'
configuration { modi: "drun,run"; font: "JetBrainsMono Nerd Font 13"; show-icons: true; icon-theme: "Papirus"; terminal: "kitty"; }
* { bg: rgba(26,27,38,0.96); fg: #c0caf5; accent: #7aa2f7; border: rgba(122,162,247,0.3); sel-bg: rgba(122,162,247,0.18); sel-fg: #7aa2f7; }
window { background-color: @bg; border: 1px solid @border; border-radius: 8px; width: 520px; }
element selected { background-color: @sel-bg; text-color: @sel-fg; }
inputbar { background-color: transparent; text-color: @fg; }
entry { background-color: transparent; text-color: @accent; }
ROFIEOF

# ── kitty live ───────────────────────────────────────────────────
mkdir -p "$AIROOTFS/root/.config/kitty"
cat > "$AIROOTFS/root/.config/kitty/kitty.conf" << 'KITTYEOF'
font_family JetBrainsMono Nerd Font
font_size 12.0
background #1a1b26; foreground #c0caf5
cursor #c0caf5; cursor_text_color #1a1b26
background_opacity 0.92; window_padding_width 10
enable_audio_bell no; scrollback_lines 5000
KITTYEOF

# ── hyprpaper (wallpaper sólido Tokyo Night) ──────────────────────
mkdir -p "$AIROOTFS/root/.config/hypr"
cat > "$AIROOTFS/root/.config/hypr/hyprpaper.conf" << 'HPEOF'
splash = false
HPEOF

# ── sudo NOPASSWD para el live (como releng) ──────────────────────
mkdir -p "$AIROOTFS/etc/sudoers.d"
cat > "$AIROOTFS/etc/sudoers.d/live-nopasswd" << 'SUDOEOF'
# Live USB: permitir sudo sin contraseña
root  ALL=(ALL:ALL) NOPASSWD: ALL
%wheel ALL=(ALL:ALL) NOPASSWD: ALL
SUDOEOF
chmod 440 "$AIROOTFS/etc/sudoers.d/live-nopasswd"

# ── SDDM: sesión Hyprland automática en el live ───────────────────
mkdir -p "$AIROOTFS/etc/sddm.conf.d"
cat > "$AIROOTFS/etc/sddm.conf.d/autologin.conf" << 'SDDMEOF'
[Autologin]
User=root
Session=hyprland

[Theme]
Current=breeze

[Wayland]
EnableHiDPI=true
SDDMEOF

# Sesión Hyprland para SDDM
mkdir -p "$AIROOTFS/usr/share/wayland-sessions"
cat > "$AIROOTFS/usr/share/wayland-sessions/hyprland.desktop" << 'SESSEOF'
[Desktop Entry]
Name=Hyprland
Comment=An intelligent dynamic tiling Wayland compositor
Exec=Hyprland
Type=Application
SESSEOF

# ── Welcome message en TTY (fallback si Hyprland no arranca) ─────
mkdir -p "$AIROOTFS/etc/profile.d"
cat > "$AIROOTFS/etc/profile.d/avalos-welcome.sh" << 'MOTDEOF'
#!/bin/bash
echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║   AvalOS ${VERSION} — Live Environment         ║"
echo "  ║   github.com/jeffreysama/avalos           ║"
echo "  ╠═══════════════════════════════════════════╣"
echo "  ║   Para instalar AvalOS:                   ║"
echo "  ║     sudo avalos-install                   ║"
echo "  ║   O desde el menú de Hyprland:            ║"
echo "  ║     Super+I                               ║"
echo "  ╚═══════════════════════════════════════════╝"
echo ""
MOTDEOF
chmod +x "$AIROOTFS/etc/profile.d/avalos-welcome.sh"

# ── Bundlear avalos-update.py si existe ───────────────────────────
for extra in "avalos-update.py" "avalos-update.desktop" "logo_4.png" "build-avalos-kernel.sh"; do
    src="${SCRIPT_DIR}/${extra}"
    if [[ -f "$src" ]]; then
        case "$extra" in
            *.py)        cp "$src" "$AIROOTFS/usr/local/bin/${extra%.py}"; chmod +x "$AIROOTFS/usr/local/bin/${extra%.py}"; log_ok "$extra incluido" ;;
            *.desktop)   mkdir -p "$AIROOTFS/usr/share/applications"; cp "$src" "$AIROOTFS/usr/share/applications/$extra"; log_ok "$extra incluido" ;;
            *.png)       mkdir -p "$AIROOTFS/usr/share/pixmaps"; cp "$src" "$AIROOTFS/usr/share/pixmaps/avalos-logo.png"; log_ok "$extra incluido" ;;
            *.sh)        cp "$src" "$AIROOTFS/usr/local/bin/${extra%.sh}"; chmod +x "$AIROOTFS/usr/local/bin/${extra%.sh}"; log_ok "$extra incluido" ;;
        esac
    fi
done

log_ok "airootfs configurado"

# ═══════════════════════════════════════════════════════════════════
#  BOOT ENTRIES
# ═══════════════════════════════════════════════════════════════════
log_step "Entradas de arranque"

LOADER_ENTRIES="$BUILD_DIR/efiboot/loader/entries"
mkdir -p "$LOADER_ENTRIES"

if [[ -f "$LOADER_ENTRIES/01-archiso-x86_64-linux.conf" ]]; then
    sed -i "s/Arch Linux/${DISTRO_NAME} ${VERSION}/g; s/archiso/avalos/g" \
        "$LOADER_ENTRIES/01-archiso-x86_64-linux.conf" 2>/dev/null || true
fi

GRUB_CFG="$BUILD_DIR/grub/grub.cfg"
[[ -f "$GRUB_CFG" ]] && sed -i "s/Arch Linux/${DISTRO_NAME} ${VERSION}/g" "$GRUB_CFG" 2>/dev/null || true

for cfg in "$BUILD_DIR"/syslinux/*.cfg; do
    [[ -f "$cfg" ]] && sed -i "s/Arch Linux/${DISTRO_NAME} ${VERSION}/g" "$cfg" 2>/dev/null || true
done

log_ok "Entradas actualizadas: '${DISTRO_NAME} ${VERSION}'"

# ═══════════════════════════════════════════════════════════════════
#  CONSTRUIR ISO
# ═══════════════════════════════════════════════════════════════════
log_step "Construyendo ISO con mkarchiso"
echo -e "  ${C_DIM}Esto puede tardar 10-30 minutos…${C_RESET}\n"

BUILD_WORK="/tmp/avalos-work"
rm -rf "$BUILD_WORK"
mkdir -p "$BUILD_WORK" "$OUTPUT_DIR"

if mkarchiso -v -w "$BUILD_WORK" -o "$OUTPUT_DIR" "$BUILD_DIR"; then
    GENERATED_ISO="$(find "$OUTPUT_DIR" -maxdepth 1 -name "${DISTRO_ID}*.iso" | sort | tail -1)"
    [[ -n "$GENERATED_ISO" && "$GENERATED_ISO" != "$ISO_FILE" ]] && mv "$GENERATED_ISO" "$ISO_FILE"
    ISO_SIZE="$(du -sh "$ISO_FILE" | cut -f1)"
    log_ok "ISO generada: ${ISO_FILE} (${ISO_SIZE})"
else
    log_err "mkarchiso falló. Revisa los logs."; exit 1
fi

rm -rf "$BUILD_WORK"

# ═══════════════════════════════════════════════════════════════════
#  CHECKSUM
# ═══════════════════════════════════════════════════════════════════
log_step "Checksum"
SHA_FILE="${ISO_FILE}.sha256"
sha256sum "$ISO_FILE" > "$SHA_FILE"
log_ok "SHA256: $(awk '{print $1}' "$SHA_FILE")"

# ═══════════════════════════════════════════════════════════════════
#  SUBIR A GITHUB RELEASES
# ═══════════════════════════════════════════════════════════════════
if $UPLOAD; then
    log_step "Subiendo a GitHub Releases"

    TAG="v${VERSION}"
    NOTES="## ${DISTRO_NAME} ${VERSION}

**Build:** $(date '+%Y-%m-%d %H:%M:%S')  
**Kernel:** ${KERNEL_PKG}  
**Base:** Arch Linux (rolling)  
**Entorno:** Hyprland · Wayland · Tokyo Night  

### Flujo rápido
1. Descarga la ISO
2. Grábala en un USB con [Ventoy](https://ventoy.net) o \`dd\`
3. Arranca desde el USB
4. El instalador gráfico abre automáticamente en Hyprland
5. Sigue el wizard: elige disco · usuario · contraseña · timezone → Instalar

### Checksums
\`\`\`
$(cat "$SHA_FILE")
\`\`\`
"
    if gh release view "$TAG" --repo "$GITHUB_REPO" &>/dev/null 2>&1; then
        log_info "Tag ${TAG} existe — actualizando assets…"
        gh release upload "$TAG" "$ISO_FILE" "$SHA_FILE" --repo "$GITHUB_REPO" --clobber
    else
        log_info "Creando release ${TAG}…"
        gh release create "$TAG" "$ISO_FILE" "$SHA_FILE" \
            --repo "$GITHUB_REPO" --title "${DISTRO_NAME} ${VERSION}" --notes "$NOTES"
    fi
    log_ok "Release publicado"
    echo -e "\n  ${C_CYAN}${C_BOLD}→ https://github.com/${GITHUB_REPO}/releases/tag/${TAG}${C_RESET}"
fi

# ═══════════════════════════════════════════════════════════════════
#  RESUMEN
# ═══════════════════════════════════════════════════════════════════
echo ""
echo -e "${C_GREEN}${C_BOLD}╔══════════════════════════════════════════════════════════╗${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  ✓  ${DISTRO_NAME} ${VERSION} — ISO lista${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}╠══════════════════════════════════════════════════════════╣${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  Flujo para el usuario:                                  ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  1. Graba la ISO en el USB con Ventoy / dd / Rufus       ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  2. Arranca desde el USB                                 ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  3. SDDM → Hyprland live (autologin root)               ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  4. El instalador abre solo (wizard gráfico)             ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  5. Elige disco · llena el form · pulsa Instalar         ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}║  6. Reinicia sin el USB → SDDM → Hyprland               ║${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}╚══════════════════════════════════════════════════════════╝${C_RESET}"
echo ""
echo -e "  ISO    : ${C_CYAN}${ISO_FILE}${C_RESET} (${ISO_SIZE})"
echo -e "  SHA256 : ${C_CYAN}${SHA_FILE}${C_RESET}"
$UPLOAD && echo -e "  GitHub : ${C_CYAN}https://github.com/${GITHUB_REPO}/releases/tag/v${VERSION}${C_RESET}"
echo ""
echo -e "  ${C_DIM}Para grabar en USB con dd:${C_RESET}"
echo -e "  ${C_CYAN}sudo dd if=${ISO_FILE} of=/dev/sdX bs=4M status=progress oflag=sync${C_RESET}"
echo ""
