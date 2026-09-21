# Installing AvalOS Manually

This guide walks you through installing AvalOS **from the live ISO**, by hand, using the same architecture the graphical installer targets: Btrfs with Snapper snapshots, ZRAM, BBR, Hyprland, and the custom `linux-avalos` kernel line. Every value in this guide (package names, mount options, subvolume layout, file contents) is taken directly from AvalOS's own installer code (`scripts/avalos_installer/`), so a manual install ends up equivalent to what the automatic one would produce — including fixes for several real bugs the installer only worked around after this guide was first written (an incomplete `pacman.conf` in the target, `makepkg` refusing to run as root, systemd-boot silently skipping its own NVRAM entry, and a few others called out inline below).

> **Only AMD and Intel hardware is supported.** AvalOS deliberately avoids NVIDIA firmware and drivers project-wide. If you have an NVIDIA GPU, this distribution is not for you yet.

---

## 0. Before you start

- **Back up your data.** This guide erases the target disk.
- **UEFI is recommended.** BIOS/Legacy works but skips Secure Boot entirely (Secure Boot isn't supported either way). This guide assumes UEFI; BIOS-specific commands are called out where they differ.
- **At least 30 GB of free disk space.**
- **A working internet connection** — the installer downloads packages live from Arch's repos plus AvalOS's own kernel/firmware repo, it does not ship them on the ISO.
- Commands below assume you're **root** in the live session (the live ISO auto-logs in as root).

---

## 1. Boot the live ISO and connect to the internet

Boot the AvalOS USB. If you're on Ethernet, you likely already have a connection. For Wi-Fi, use `iwctl`:

```bash
iwctl
[iwd]# device list
[iwd]# station wlan0 scan
[iwd]# station wlan0 get-networks
[iwd]# station wlan0 connect "Your-Network-Name"
[iwd]# exit
```

Or, if NetworkManager is already running on the live session:

```bash
nmtui
```

Verify you actually have connectivity before continuing:

```bash
curl -fsI https://archlinux.org && echo "OK: internet is up"
```

## 2. Sync the system clock

Do this **before** touching pacman or any mirror — if the clock is wrong, HTTPS certificate validation can fail against every mirror you try, which looks exactly like a dead network even when it isn't.

```bash
timedatectl set-ntp true
timedatectl show -p NTPSynchronized --value   # should print "yes" within a few seconds
```

## 3. Partition the disk

Identify your target disk first — **do not** point this at the USB you booted from:

```bash
lsblk
```

Assume the target is `/dev/sda` (swap in `/dev/nvme0n1`, etc. as needed — for NVMe/eMMC devices, partitions are named `nvme0n1p1`, `nvme0n1p2`, not `sda1`/`sda2`).

**UEFI (GPT):**

```bash
parted -s /dev/sda mklabel gpt
parted -s /dev/sda mkpart ESP fat32 1MiB 513MiB
parted -s /dev/sda set 1 esp on
parted -s /dev/sda mkpart root 513MiB 100%
```

This gives a 512 MiB EFI System Partition and a root partition using the rest of the disk. If you plan to use systemd-boot (see step 17), consider bumping the ESP to 1 GiB — 512 MiB gets tight once you have two kernel variants plus fallback images sitting in it.

**BIOS (MBR)**, if you're not using UEFI:

```bash
parted -s /dev/sda mklabel msdos
parted -s /dev/sda mkpart primary ext4 1MiB 100%
parted -s /dev/sda set 1 boot on
```

Refresh the kernel's view of the partition table:

```bash
partprobe /dev/sda
udevadm settle
```

> **Why this matters:** on some hardware, the kernel finishes writing the new partition table but refuses to re-read it ("`partition(s) on /dev/sda have been written, but we have been unable to inform the kernel of the change`"), and the very next command fails as if the partition didn't exist. That's exactly what `partprobe` + `udevadm settle` above fix. This is a real, currently-open issue in AvalOS's own graphical installer (it only calls `udevadm settle` after `parted`, not `partprobe`) — this guide is intentionally more careful here than the installer is today.

## 4. Format the partitions

**UEFI:**

```bash
mkfs.fat -F32 /dev/sda1        # ESP
mkfs.btrfs -f /dev/sda2        # root
```

**BIOS:**

```bash
mkfs.ext4 /dev/sda1
```

(If you'd rather use ext4 for root instead of Btrfs — no snapshots, no compression, but simpler — format `/dev/sda2` with `mkfs.ext4` instead and skip straight to step 6, mounting it plainly at `/mnt`. The rest of this guide assumes Btrfs, which is what AvalOS is tuned for.)

## 5. Create and mount the Btrfs subvolumes

AvalOS uses a fixed six-subvolume layout. Mount the raw filesystem once to create them:

```bash
mount /dev/sda2 /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@snapshots
btrfs subvolume create /mnt/@log
btrfs subvolume create /mnt/@cache
btrfs subvolume create /mnt/@tmp
umount /mnt
```

Now mount each subvolume at its real path. The options string is the same for all of them:

```bash
BTRFS_OPTS="compress=zstd,noatime,space_cache=v2"

mount -o "subvol=@,$BTRFS_OPTS" /dev/sda2 /mnt

mkdir -p /mnt/{home,.snapshots,var/log,var/cache,tmp,boot/efi}

mount -o "subvol=@home,$BTRFS_OPTS"      /dev/sda2 /mnt/home
mount -o "subvol=@snapshots,$BTRFS_OPTS" /dev/sda2 /mnt/.snapshots
mount -o "subvol=@log,$BTRFS_OPTS"       /dev/sda2 /mnt/var/log
mount -o "subvol=@cache,$BTRFS_OPTS"     /dev/sda2 /mnt/var/cache
mount -o "subvol=@tmp,$BTRFS_OPTS,nodatacow" /dev/sda2 /mnt/tmp
chattr +C /mnt/tmp
```

`@tmp` gets `nodatacow` plus `chattr +C`: temp files churn constantly and don't need copy-on-write, so this avoids needless fragmentation and COW overhead.

**UEFI only** — mount the ESP:

```bash
mount /dev/sda1 /mnt/boot/efi
```

## 6. Optimize mirrors

`rate-mirrors` (official repo, no AUR needed) explores mirrors by real network topology and skips outdated or still-syncing ones — prefer it over `reflector` if it's available:

```bash
pacman -Sy --noconfirm --needed rate-mirrors
rate-mirrors arch --allow-root --save /etc/pacman.d/mirrorlist
```

If that's unavailable for some reason, fall back to `reflector`:

```bash
pacman -Sy --noconfirm --needed reflector
reflector --latest 10 --sort rate --protocol https --save /etc/pacman.d/mirrorlist
```

> **Tip:** whichever of the two you used, the installer appends one more line afterwards as a safety net — a large, always-complete mirror that's never missing packages (including multilib):
> ```bash
> echo 'Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch' >> /etc/pacman.d/mirrorlist
> ```
> This only helps if the mirror(s) picked above have a gap for a specific package later — it's optional, but cheap insurance before the long `pacstrap` run in the next step.

## 7. Install the base system

The live ISO already ships with the `[avalos]` repo and `[multilib]` enabled in `/etc/pacman.conf` — you don't need to add them yourself. Confirm they're there:

```bash
grep -A2 "\[avalos\]" /etc/pacman.conf
grep -A2 "\[multilib\]" /etc/pacman.conf
```

> **One thing to check before you `pacstrap`:** the live session's `/etc/pacman.conf` also ships with `IgnorePkg = linux-avalos linux-avalos-headers linux-avalos-bore linux-avalos-bore-headers linux-avalos-compat linux-avalos-compat-headers` — a deliberate guard so nobody accidentally runs `pacman -S linux-avalos` *inside the live session itself*. The problem is that `pacstrap` (below) reuses this same file by default, so that guard stays active for the **target** install too — pacman then treats `linux-avalos` as unavailable and silently falls back to resolving the generic `linux` package instead, leaving you with the wrong kernel and no error. Check and neutralize it first:
> ```bash
> grep '^IgnorePkg' /etc/pacman.conf
> # If it lists any linux-avalos* packages, comment that line out (or remove those
> # entries from it) before continuing — it only exists to protect the live session:
> sed -i 's/^IgnorePkg/#IgnorePkg/' /etc/pacman.conf
> ```
> You can restore it afterwards if you like; it doesn't matter once you're done with `pacstrap`.

**Pick your kernel variant.** Check your CPU's microarchitecture level:

```bash
/lib/ld-linux-x86-64.so.2 --help | grep supported
```

- Supports **x86-64-v4** (AVX-512) or **x86-64-v3** (AVX2, most CPUs from ~2015 onward): use `linux-avalos` (or `linux-avalos-bore` if you want the BORE scheduler for gaming — same requirement, x86-64-v3+).
- Anything older (**x86-64-v2** or below): use `linux-avalos-compat`.

Do **not** mix these up — `linux-avalos`/`-bore` are compiled specifically for v3+ and will not boot on older CPUs.

**Pick your microcode** based on CPU vendor:

```bash
grep -m1 vendor_id /proc/cpuinfo
```

`GenuineIntel` → `intel-ucode`. `AuthenticAMD` → `amd-ucode`.

Now install. This is the exact base package set AvalOS uses — note that firmware comes from a single `linux-avalos-firmware` package (from the `[avalos]` repo) rather than individual `linux-firmware-*` picks: it bundles every AMD/Intel/network/Bluetooth vendor split Arch ships, deliberately **excluding NVIDIA**, and `provides`+`conflicts` against Arch's own `linux-firmware` meta-package so nothing can pull NVIDIA firmware back in as a transitive dependency later:

```bash
pacstrap -c --needed /mnt \
  base base-devel \
  linux-avalos linux-avalos-headers \
  intel-ucode \
  linux-avalos-firmware \
  sof-firmware \
  grub efibootmgr os-prober ntfs-3g networkmanager nm-connection-editor \
  sudo bash bash-completion nano vim git curl wget htop \
  python python-pip man-db man-pages less openssh \
  zip unzip p7zip zram-generator \
  reflector pacman-contrib xdg-utils udiskie \
  fastfetch bat github-cli \
  btrfs-progs snapper snap-pac grub-btrfs inotify-tools
```

(Swap `linux-avalos linux-avalos-headers` for `linux-avalos-compat linux-avalos-compat-headers` if that's what your CPU needs, and `intel-ucode` for `amd-ucode` on AMD. Drop `os-prober`/`ntfs-3g` if you don't need Windows dual-boot detection. If you picked a bootloader other than GRUB back in step 3, you can also drop `grub`/`efibootmgr`/`os-prober` here — see step 17.)

If `pacstrap` fails partway through with a burst of `failed retrieving file` errors on otherwise-valid packages (not "target not found" — an actual download failure), it's usually a connection that can't handle several large files downloading at once. Lower the parallelism and retry:

```bash
sed -i 's/^ParallelDownloads.*/ParallelDownloads = 1/' /etc/pacman.conf
```

then re-run the same `pacstrap` command — it'll skip anything already installed since `--needed` is set.

> **Known caveat:** `lib32-sdl2-compat` and `lib32-gst-plugins-base-libs` (32-bit multimedia libs, needed for some older Wine/Proton titles and used later in step 21) have occasionally been pulled from Arch's official `[multilib]` repo for days-to-weeks at a time following security advisories in that stack. If a `pacman`/`pacstrap` run reports one of these specifically as `target not found`, that's not a mistake on your end — just drop it from the package list and continue; most modern Proton/Wine builds don't need them. Install them later once they reappear upstream.

Once `pacstrap` finishes, double-check you actually got the AvalOS kernel and not a generic fallback — this is exactly the failure mode the `IgnorePkg` caveat above describes:

```bash
arch-chroot /mnt pacman -Q linux-avalos    # (or linux-avalos-compat / linux-avalos-bore)
# should print a version, not "package 'linux-avalos' was not found"
```

## 8. Generate fstab

```bash
genfstab -U /mnt >> /mnt/etc/fstab
```

**Critical for Btrfs installs:** strip `subvolid=` from the generated fstab. `genfstab` inserts it automatically, and it's an absolute reference to one specific subvolume that overrides `subvol=@name` — leaving it in silently breaks booting into Snapper/grub-btrfs snapshots later (you'd always end up back on the original `@`, no matter which snapshot you picked in the boot menu).

```bash
sed -i 's/,subvolid=[0-9]*//g; s/subvolid=[0-9]*,//g' /mnt/etc/fstab
```

Double check the result — every Btrfs line should have a `subvol=@...` and no `subvolid=`:

```bash
cat /mnt/etc/fstab
```

## 9. Chroot into the new system

`pacstrap` only installs official Arch (and AvalOS kernel/firmware) packages into `/mnt` — it doesn't carry over anything that lives on the live ISO's own filesystem outside of a package. Two things you'll need over the next several steps live exactly there and become **unreachable** the moment you `arch-chroot`, so copy them in first:

```bash
# AvalOS's own configs (Hyprland, Waybar, SDDM theme, avalos-settings/store/update
# scripts, icons, polkit policies, etc.) — steps 13-15 and 21 all read from this tree.
cp -r /usr/share/avalos/configs /mnt/usr/share/avalos/configs

# The default wallpaper lives one level up from configs/, not inside it.
[ -f /usr/share/avalos/wallpaper-default.png ] && \
  cp /usr/share/avalos/wallpaper-default.png /mnt/usr/share/avalos/wallpaper-default.png

# The AvalOS repo's GPG public key + trust file — needed by step 12. The live
# ISO already trusts this key (it was populated into its own keyring at build
# time); pacstrap doesn't carry that trust into the target, so this file pair
# is how you re-establish it there with `pacman-key --populate` in step 12.
mkdir -p /mnt/usr/share/pacman/keyrings
cp /usr/share/pacman/keyrings/avalos.gpg     /mnt/usr/share/pacman/keyrings/
cp /usr/share/pacman/keyrings/avalos-trusted /mnt/usr/share/pacman/keyrings/
```

Now enter the chroot:

```bash
arch-chroot /mnt
```

Everything from here on runs **inside the chroot**, on the new system (steps 17's systemd-boot section has one brief, clearly-marked exception).

## 10. Timezone, locale, hostname, and identity

```bash
ln -sf /usr/share/zoneinfo/Region/City /etc/localtime
hwclock --systohc

echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen   # add whatever locales you need
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf

echo "avalos" > /etc/hostname
cat >> /etc/hosts << 'EOF'
127.0.0.1   localhost
::1         localhost
127.0.1.1   avalos.localdomain avalos
EOF
```

> **Always keep `en_US.UTF-8` generated** even if your primary locale is something else — a fair number of scripts and tools assume it exists as a fallback. If `locale-gen` reports it can't find the source definition for your locale (`cannot open locale definition file`), the fix is usually `pacman -S glibc` to make sure the full `/usr/share/i18n/locales/` set is present, then re-run `locale-gen`.

**Console keymap.** If you don't need anything besides US English, you can skip this — `us` is the default either way. Otherwise, set the console keymap and the matching keyboard layout Hyprland/X11 will use:

```bash
echo "KEYMAP=la-latin1" > /etc/vconsole.conf   # whatever `loadkeys` name matches your keyboard

mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/00-keyboard.conf << 'EOF'
Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "yes"
    Option "XkbLayout" "latam"
EndSection
EOF
```

The console keymap name and the XKB layout name aren't always identical. AvalOS's own installer maps between them like this — find your console keymap on the left and use the matching XKB name on the right (you'll need the XKB name again in step 14):

| Console keymap (`vconsole.conf`) | XKB layout (`XkbLayout`) |
|---|---|
| `la-latin1` | `latam` |
| `es` | `es` |
| `latam` | `latam` |
| `us` | `us` |
| `uk` | `gb` |
| `br-abnt2` | `br` |
| `de`, `de-latin1` | `de` |
| `fr` | `fr` |
| `it` | `it` |
| `ru` | `ru` |
| `dvorak` | `us(dvorak)` |
| `colemak` | `us(colemak)` |

Not listed? `localectl list-x11-keymap-layouts` shows every valid XKB layout name.

**Root password:**

```bash
passwd
```

**System identity.** This is what makes `fastfetch`, distro-detection scripts, and anything else that reads the standard `os-release`/`lsb-release` files say "AvalOS" instead of "Arch Linux":

```bash
cat > /etc/os-release << 'EOF'
NAME="AvalOS"
PRETTY_NAME="AvalOS"
ID=avalos
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;122;162;247"
HOME_URL="https://github.com/jeffreysama/avalos"
DOCUMENTATION_URL="https://wiki.archlinux.org"
LOGO=avalos-logo
EOF

cat > /etc/lsb-release << 'EOF'
LSB_VERSION=1.4
DISTRIB_ID=AvalOS
DISTRIB_RELEASE=rolling
DISTRIB_CODENAME=avalos
DISTRIB_DESCRIPTION="AvalOS"
EOF
```

> **The GRUB menu title is a separate setting from `os-release`.** If you're using GRUB (step 17), its `10_linux` menu-generation script actually reads `GRUB_DISTRIBUTOR` from `/etc/default/grub`, not `os-release` — the two are unrelated mechanisms. Without this, GRUB's default (`Arch` — or a fallback to `Arch Linux` if `lsb_release` isn't installed, which it isn't here) shows up in the boot menu no matter what `os-release` says:
> ```bash
> grep -q '^GRUB_DISTRIBUTOR=' /etc/default/grub \
>   && sed -i 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="AvalOS"/' /etc/default/grub \
>   || echo 'GRUB_DISTRIBUTOR="AvalOS"' >> /etc/default/grub
> ```
> Skip this if you're using systemd-boot or rEFInd instead — they don't read this file for their menu labels.

## 11. Create your user account

```bash
useradd -m -G wheel,audio,video,storage,optical -s /bin/bash yourusername
passwd yourusername
```

Grant the `wheel` group sudo access with its own drop-in file, rather than editing `/etc/sudoers` directly — it's easier to review, and it's what the installer itself does:

```bash
cat > /etc/sudoers.d/wheel << 'EOF'
%wheel ALL=(ALL:ALL) ALL
EOF
chmod 440 /etc/sudoers.d/wheel
```

## 12. Enable the AvalOS repo and keyring

`pacstrap` installs a completely default `pacman.conf` into the target — it does **not** inherit the `[avalos]`/`[multilib]` setup from the live session's own config that step 7 relied on. Without this step, `pacman -S linux-avalos-firmware`/any future kernel update, and every `lib32-*` package in steps 13 and 21, will fail with "target not found" inside the chroot.

First, a sanity check — in at least one real install, the `pacman.conf` that `pacstrap` left behind was missing not just `[avalos]`, but `[options]`/`[core]`/`[extra]` entirely (cause unconfirmed; possibly ISO-specific). Without an `Architecture` line, pacman breaks on essentially everything, even `pacman -Q`. Rebuild a minimal valid base first if that's what you find:

```bash
cat /etc/pacman.conf   # look for [options] with an Architecture line

grep -q '^\[options\]' /etc/pacman.conf || cat >> /etc/pacman.conf << 'EOF'
[options]
Architecture = auto
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist
EOF
```

Now add the `[avalos]` repo and enable `[multilib]`:

```bash
grep -q '^\[avalos\]' /etc/pacman.conf || cat >> /etc/pacman.conf << 'EOF'

[avalos]
SigLevel = Required DatabaseOptional
Server = https://github.com/jeffreysama/avalos/releases/download/repo
EOF

grep -q '^\[multilib\]' /etc/pacman.conf || \
  sed -i '/^#\[multilib\]/,/^#Include = \/etc\/pacman.d\/mirrorlist/ s/^#//' /etc/pacman.conf

grep -A2 '^\[multilib\]' /etc/pacman.conf   # confirm it's uncommented and active
```

Finally, populate the keyring using the key + trust file you copied in from the live session back in step 9 (this is the officially-documented archiso mechanism — the same one already used, successfully, for the `archlinux` keyring below):

```bash
pacman-key --init
pacman-key --populate archlinux
pacman-key --populate avalos
```

## 13. Install the desktop: Hyprland + GPU drivers

First, detect your GPU vendor:

```bash
lspci -k | grep -A2 -E "(VGA|3D)"
```

**If AMD:**

```bash
pacman -S --needed mesa mesa-utils vulkan-radeon vulkan-icd-loader vulkan-tools \
  libva-mesa-driver libva-utils radeontop gst-plugin-va libva \
  lib32-mesa lib32-vulkan-radeon
```

**If Intel:**

```bash
pacman -S --needed mesa mesa-utils vulkan-intel vulkan-icd-loader vulkan-tools \
  intel-media-driver libva-intel-driver libva-utils libva \
  gst-plugin-va lib32-mesa lib32-vulkan-intel
```

Then the Hyprland desktop stack:

```bash
pacman -S --needed \
  hyprland uwsm libnewt xdg-desktop-portal-hyprland xdg-desktop-portal-gtk \
  xdg-user-dirs kitty waybar rofi-wayland mako \
  hyprpaper hyprlock hypridle hyprpicker \
  grim slurp wl-clipboard cliphist \
  pipewire pipewire-alsa pipewire-pulse pipewire-jack wireplumber pavucontrol \
  qt5-quickcontrols2 qt5-wayland qt6-wayland gtk3 gtk4 hyprpolkitagent \
  thunar gvfs brightnessctl \
  ttf-font-awesome ttf-jetbrains-mono-nerd ttf-nerd-fonts-symbols \
  noto-fonts noto-fonts-emoji noto-fonts-cjk \
  sddm network-manager-applet blueman \
  playerctl firefox bluez bluez-utils libnotify sound-theme-freedesktop \
  file-roller thunar-archive-plugin thunar-volman gvfs-mtp gvfs-smb \
  nwg-look nwg-displays papirus-icon-theme lm_sensors acpi capitaine-cursors \
  python-pywebview python-gobject webkit2gtk-4.1 \
  archlinux-appstream-data hicolor-icon-theme
```

`noto-fonts-cjk` is the one big download here (~300 MB) — it's what gives full Chinese/Japanese/Korean character coverage instead of the much smaller but incomplete `wqy-microhei`. The last two lines are new additions over what you might expect: `python-pywebview`/`python-gobject`/`webkit2gtk-4.1` are the runtime AvalOS's own GUI apps (avalos-settings, avalos-store) are built on, and `archlinux-appstream-data`+`hicolor-icon-theme` are what let avalos-store show real app icons instead of a generic placeholder.

## 14. Copy the AvalOS configs and branding

The configs you copied into `/usr/share/avalos/configs/` back in step 9 are AvalOS's actual Hyprland/Waybar/Kitty/Rofi/Mako/SDDM/fastfetch/GTK configs. Most copy straight across, but the Hyprland config and the SDDM theme are **templates** with `%%PLACEHOLDER%%` markers that need filling in — copying them verbatim (as you might expect) leaves literal placeholder text in a config Hyprland/SDDM will try to parse, which is worse than just skipping them.

Start with the simple, direct copies:

```bash
mkdir -p /home/yourusername/.config
cp -r /usr/share/avalos/configs/waybar     /home/yourusername/.config/waybar
cp -r /usr/share/avalos/configs/kitty      /home/yourusername/.config/kitty
cp -r /usr/share/avalos/configs/mako       /home/yourusername/.config/mako
cp -r /usr/share/avalos/configs/rofi       /home/yourusername/.config/rofi
chmod 755 /home/yourusername/.config/rofi/scripts/powermenu.sh
mkdir -p /home/yourusername/.config/hypr
cp /usr/share/avalos/configs/hyprland/hypridle.conf  /home/yourusername/.config/hypr/hypridle.conf
cp /usr/share/avalos/configs/hyprland/hyprlock.conf  /home/yourusername/.config/hypr/hyprlock.conf
cp /usr/share/avalos/configs/hyprland/hyprpaper.conf /home/yourusername/.config/hypr/hyprpaper.conf
mkdir -p /etc/fastfetch
cp -r /usr/share/avalos/configs/fastfetch/. /etc/fastfetch/
mkdir -p /usr/share/sddm/themes/avalos
```

Wallpaper — use the one you copied in during step 9, or fall back to a plain background if the ISO didn't ship one:

```bash
if [ -f /usr/share/avalos/wallpaper-default.png ]; then
  cp /usr/share/avalos/wallpaper-default.png /home/yourusername/.config/hypr/wallpaper.png
fi
```

**Hyprland config** — copy the template, then fill in your GPU's environment block (from step 13) and your XKB keymap (from step 10, `us` if you skipped that section):

```bash
cp /usr/share/avalos/configs/hyprland/hyprland_conf_lua.template \
   /home/yourusername/.config/hypr/hyprland.lua

python3 - << 'PYEOF'
import pathlib
p = pathlib.Path("/home/yourusername/.config/hypr/hyprland.lua")
text = p.read_text()

# Pick ONE of the two GPU_ENV blocks below, matching what you installed in step 13:

# --- AMD ---
gpu_env = '''-- AVALOS_GPU_ENV_START
hl.env("AMD_VULKAN_ICD",    "RADV")
hl.env("VDPAU_DRIVER",      "radeonsi")
hl.env("LIBVA_DRIVER_NAME", "radeonsi")
-- AVALOS_GPU_ENV_END'''

# --- Intel (uncomment instead, and comment out the AMD block above) ---
# gpu_env = '''-- AVALOS_GPU_ENV_START
# hl.env("LIBVA_DRIVER_NAME", "iHD")
# hl.env("VDPAU_DRIVER",      "va_gl")
# -- AVALOS_GPU_ENV_END'''

text = text.replace("%%GPU_ENV%%", gpu_env)
text = text.replace("%%KEYMAP%%", "us")   # your XKB layout name from step 10
p.write_text(text)
PYEOF
```

Edit the `gpu_env`/keymap values in that script to match your hardware before running it (or just run it once, check the result with `grep -n AVALOS_GPU_ENV -A4 /home/yourusername/.config/hypr/hyprland.lua`, and re-run with the other block if you picked wrong — it's idempotent as long as you re-copy the template first).

**SDDM theme** — same idea, template + substitution. The defaults below are the plain English strings; swap them for your own language if you want:

```bash
cp /usr/share/avalos/configs/sddm/Main.qml         /usr/share/sddm/themes/avalos/Main.qml
cp /usr/share/avalos/configs/sddm/metadata.desktop /usr/share/sddm/themes/avalos/metadata.desktop

python3 - << 'PYEOF'
import pathlib
p = pathlib.Path("/usr/share/sddm/themes/avalos/Main.qml")
text = p.read_text()
for k, v in {
    "%%SDDM_USER%%":     "Username",
    "%%SDDM_PASS%%":     "Password",
    "%%SDDM_SIGNIN%%":   "Sign In",
    "%%SDDM_FAIL%%":     "Authentication failed. Try again.",
    "%%SDDM_SESSION%%":  "Session",
    "%%SDDM_SUSPEND%%":  "Suspend",
    "%%SDDM_RESTART%%":  "Restart",
    "%%SDDM_SHUTDOWN%%": "Shutdown",
}.items():
    text = text.replace(k, v)
p.write_text(text)
PYEOF

cat > /etc/sddm.conf.d/hyprland.conf << 'EOF'
[Theme]
Current=avalos

[Wayland]
EnableHiDPI=true

[General]
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
EOF
```

(No need to write `hyprland.desktop`/`hyprland-uwsm.desktop` under `/usr/share/wayland-sessions/` yourself — the official `hyprland` package you installed in step 13 already ships both, kept current by Hyprland's own developers. An older version of this guide had you overwrite them by hand; on real hardware that produced a stale "Hyprland was started without start-hyprland" warning as soon as upstream changed how `uwsm` is invoked.)

**GTK 3/4 theming**, so GTK apps (Thunar, file pickers, etc.) match:

```bash
for gtk_ver in gtk-3.0 gtk-4.0; do
  mkdir -p /home/yourusername/.config/$gtk_ver
  cp /usr/share/avalos/configs/gtk/settings.ini /home/yourusername/.config/$gtk_ver/settings.ini
done
```

**Wayland environment variables**, system-wide (this is what actually makes Qt, Electron, Firefox, etc. prefer Wayland over X11):

```bash
cat > /etc/environment << 'EOF'
QT_QPA_PLATFORM=wayland;xcb
QT_AUTO_SCREEN_SCALE_FACTOR=1
QT_WAYLAND_DISABLE_WINDOWDECORATION=1
GDK_BACKEND=wayland,x11
SDL_VIDEODRIVER=wayland
CLUTTER_BACKEND=wayland
MOZ_ENABLE_WAYLAND=1
ELECTRON_OZONE_PLATFORM_HINT=auto
XDG_SESSION_TYPE=wayland
XDG_SESSION_DESKTOP=Hyprland
XDG_CURRENT_DESKTOP=Hyprland
VDPAU_DRIVER=radeonsi
LIBVA_DRIVER_NAME=radeonsi
__GLX_VENDOR_LIBRARY_NAME=mesa
EOF
```

> **AMD/Intel:** the two `VDPAU_DRIVER`/`LIBVA_DRIVER_NAME` lines above are for AMD. On Intel, use `LIBVA_DRIVER_NAME=iHD` and `VDPAU_DRIVER=va_gl` instead.
>
> **Use `;` not `:` in `QT_QPA_PLATFORM`.** Qt parses this as a `;`-separated list of platform plugins to try in order, with fallback to the next if one fails to load. A `:` (easy typo, and how most other list-style env vars work) makes Qt look for a plugin literally named `wayland:xcb`, fail to find it, and silently lose the Wayland→X11 fallback for every Qt app that reads `/etc/environment`.

Append the same Wayland exports to your user's shell profile, so they're also set for anything launched from a terminal:

```bash
cat >> /home/yourusername/.bashrc << 'EOF'

# ── AvalOS / Wayland ────────────────────────────────
export QT_QPA_PLATFORM=wayland
export MOZ_ENABLE_WAYLAND=1
export ELECTRON_OZONE_PLATFORM_HINT=auto
export XDG_SESSION_TYPE=wayland
EOF
```

**Automatic mirror refresh** (keeps `/etc/pacman.d/mirrorlist` from going stale over time — separate from the one-off optimization you ran in step 6):

```bash
mkdir -p /etc/xdg/reflector
cat > /etc/xdg/reflector/reflector.conf << 'EOF'
--country SV,US,MX,GT,JP
--latest 10
--sort rate
--protocol https
EOF
systemctl enable reflector.timer
```

(Edit `--country` to your own region(s) — the list above is just AvalOS's own default. Country codes are ISO 3166-1 alpha-2, comma-separated, no spaces.)

**Enable lingering** for your user, so PipeWire's user-level audio services actually start reliably (without this, audio can come up inconsistently depending on exactly when/how the user session starts):

```bash
cat > /etc/systemd/system/avalos-enable-linger.service << 'EOF'
[Unit]
Description=Enable linger for yourusername (PipeWire user services)
After=systemd-logind.service
ConditionPathExists=!/var/lib/systemd/linger/yourusername

[Service]
Type=oneshot
ExecStart=/usr/bin/loginctl enable-linger yourusername
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable avalos-enable-linger.service
```

Fix ownership on everything you just wrote into the user's home:

```bash
chown -R yourusername:yourusername /home/yourusername/.config /home/yourusername/.bashrc
```

## 15. Install the AvalOS system tools

AvalOS ships a handful of its own apps — Settings, Wallpaper picker, About, Update, and a pywebview-based Store — as plain scripts rather than packages. None of this is optional if you want feature parity with the graphical installer: skipping it leaves the `SUPER+CTRL+S` / `SUPER+ALT+S` / `SUPER+ALT+U` keybinds already baked into the Hyprland config you set up in step 14 pointing at commands that don't exist.

**The scripts themselves**, plus the Store's app catalog:

```bash
mkdir -p /usr/local/bin
for f in avalos-settings avalos-wallpaper avalos-about avalos-update avalos-update-helper avalos-store; do
  cp "/usr/share/avalos/configs/scripts/$f" "/usr/local/bin/$f"
  chmod 755 "/usr/local/bin/$f"
done
cp /usr/share/avalos/configs/avalos-store-catalog.json /usr/local/bin/avalos-store-catalog.json
```

**Desktop entries**, so they show up in rofi's app launcher and any app menu (`avalos-update` in particular has no launcher entry otherwise — it'd be installed but effectively invisible):

```bash
mkdir -p /usr/share/applications
cp /usr/share/avalos/configs/scripts/avalos-settings.desktop /usr/share/applications/
cp /usr/share/avalos/configs/scripts/avalos-store.desktop    /usr/share/applications/
cp /usr/share/avalos/configs/avalos-update.desktop           /usr/share/applications/
```

**Polkit policies** — `avalos-update`/`avalos-store` both need `pkexec` to elevate for `pacman -S`/`-R`. Without a dedicated policy, `pkexec` falls back to the generic `org.freedesktop.policykit.exec` action, which asks for a password on *every single* install/uninstall instead of remembering the session:

```bash
mkdir -p /usr/share/polkit-1/actions
cp /usr/share/avalos/configs/avalos-update.policy /usr/share/polkit-1/actions/com.avalos.update.policy
cp /usr/share/avalos/configs/avalos-store.policy  /usr/share/polkit-1/actions/com.avalos.store.policy
chmod 644 /usr/share/polkit-1/actions/com.avalos.*.policy
```

**Icons**, so the Store and Update apps don't show a generic "unknown app" placeholder:

```bash
mkdir -p /usr/share/icons/hicolor/scalable/apps
cp /usr/share/avalos/configs/avalos-store.svg  /usr/share/icons/hicolor/scalable/apps/
cp /usr/share/avalos/configs/avalos-update.svg /usr/share/icons/hicolor/scalable/apps/
```

**GPU environment auto-detection**, run once at every boot (before SDDM starts) to keep the `AVALOS_GPU_ENV_START`/`END` block in every user's `hyprland.lua` in sync — useful if you ever swap the GPU in this machine:

```bash
cat > /usr/local/bin/avalos-gpu-env << 'EOF'
#!/bin/bash
set -uo pipefail

if lspci 2>/dev/null | grep -qiE 'amd|radeon|amdgpu'; then
    GPU_BLOCK='hl.env("AMD_VULKAN_ICD",    "RADV")
hl.env("VDPAU_DRIVER",      "radeonsi")
hl.env("LIBVA_DRIVER_NAME", "radeonsi")'
elif lspci 2>/dev/null | grep -qiE 'intel.*(graphics|vga|display)'; then
    GPU_BLOCK='hl.env("LIBVA_DRIVER_NAME", "iHD")
hl.env("VDPAU_DRIVER",      "va_gl")'
else
    exit 0
fi

for hypr_conf in /home/*/.config/hypr/hyprland.lua; do
    [[ -f "$hypr_conf" ]] || continue
    if ! grep -q 'AVALOS_GPU_ENV_START' "$hypr_conf"; then
        continue
    fi
    owner="$(stat -c '%U:%G' "$hypr_conf")"
    mode="$(stat -c '%a' "$hypr_conf")"
    tmp="$(mktemp)"
    awk -v block="$GPU_BLOCK" '
        /-- AVALOS_GPU_ENV_START/ { print; print block; skip=1; next }
        /-- AVALOS_GPU_ENV_END/   { skip=0; print; next }
        skip { next }
        { print }
    ' "$hypr_conf" > "$tmp" && mv "$tmp" "$hypr_conf"
    chown "$owner" "$hypr_conf"
    chmod "$mode" "$hypr_conf"
done
EOF
chmod 755 /usr/local/bin/avalos-gpu-env

cat > /etc/systemd/system/avalos-gpu-detect.service << 'EOF'
[Unit]
Description=AvalOS — GPU Environment Detection
Documentation=https://github.com/jeffreysama/avalos
Before=sddm.service display-manager.service
After=systemd-udev-settle.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/avalos-gpu-env
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
EOF
systemctl enable avalos-gpu-detect.service
```

> **Watch permissions if you ever edit this script or `hyprland.lua` as root later.** The bug this careful owner/mode capture-and-restore avoids: an earlier version of this same script read the file's owner *after* rewriting it (i.e. from the root-owned temp file `mktemp` created, not from the user's original), so every boot silently re-chowned the user's own `hyprland.lua` to `root:root` — which then made Hyprland unable to read its own theme and quietly fall back to defaults.

**UI language and install profile** — small marker files a couple of these tools read to know what you picked, instead of re-detecting it:

```bash
echo "en" > /etc/avalos-lang          # en / es / zh / ja — whichever you're using
: > /etc/avalos-profile               # add "gaming" and/or "bore" lines here if they apply
                                       # (see steps 7 and 21) — one flag per line, or leave empty
date "+%Y-%m-%d %H:%M" > /etc/avalos-install-date
```

## 16. Configure mkinitcpio

Add the `btrfs` hook, and `grub-btrfs-overlayfs` if you're using GRUB (step 17):

```bash
sed -i 's/^HOOKS=(\(.*\)filesystems\(.*\))/HOOKS=(\1btrfs filesystems\2)/' /etc/mkinitcpio.conf
# If using GRUB:
sed -i 's/^HOOKS=(\(.*\)fsck\(.*\))/HOOKS=(\1grub-btrfs-overlayfs fsck\2)/' /etc/mkinitcpio.conf

mkinitcpio -P
```

If `mkinitcpio -P` complains about a `.preset` file pointing at a `vmlinuz` that doesn't exist, it's a leftover from an earlier attempt in this same chroot (e.g. a stray `linux.preset` from before you settled on `linux-avalos`) — safe to delete anything under `/etc/mkinitcpio.d/` that doesn't match the kernel you actually installed in step 7.

## 17. Install the bootloader

**GRUB is the recommended choice** — it's the only one of the three bootloaders AvalOS supports where the Btrfs subvolume gets detected and wired into the boot entry automatically via `grub-mkconfig`. systemd-boot and rEFInd both need `rootflags=subvol=@` added to the kernel command line by hand, which the two procedures below already do for you — just don't lose that flag if you customize either further.

**GRUB, UEFI:**

```bash
pacman -S --needed grub efibootmgr
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=GRUB

sed -i 's/^GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=false/' /etc/default/grub
grep -q "^GRUB_DISABLE_OS_PROBER" /etc/default/grub || echo "GRUB_DISABLE_OS_PROBER=false" >> /etc/default/grub
grep -q "^GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION" /etc/default/grub || \
  echo "GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION=true" >> /etc/default/grub

grub-mkconfig -o /boot/grub/grub.cfg
```

(The `GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION` line matters here specifically because `/boot` isn't a separate partition in this layout — it lives inside the `@` subvolume alongside `/` — which can otherwise confuse `grub-btrfs`'s automatic detection once you set up Snapper in step 18.)

As a safety net against firmware that resets or drops NVRAM boot entries, also install a copy to the fixed fallback path:

```bash
grub-install --target=x86_64-efi --efi-directory=/boot/efi --removable
```

**GRUB, BIOS:**

```bash
pacman -S --needed grub
grub-install --target=i386-pc /dev/sda
grub-mkconfig -o /boot/grub/grub.cfg
```

**systemd-boot**, if you'd rather not use GRUB:

systemd-boot needs `bootctl` to actually write an NVRAM boot entry ("Linux Boot Manager"), and that only works if `bootctl` can touch real EFI variables. Run from a plain `arch-chroot /mnt`, `bootctl` detects it's in a PID namespace and **silently skips the EFI variable step entirely** — it still exits `0`, so nothing looks wrong, but no entry ever shows up in your firmware's boot menu (this is a real, documented systemd behavior — see `systemd/systemd#36174` and `#39002`). The fix is `arch-chroot`'s `-S` flag, which runs the chrooted command in a real systemd context via `systemd-run`/nspawn instead:

```bash
exit                              # step back out of the current chroot for one command
arch-chroot -S /mnt bootctl install --esp-path=/boot/efi
arch-chroot /mnt                  # back in for the rest of this step
```

`-S` was only added to `arch-install-scripts` at some point in 2025 — if your live ISO is older and `arch-chroot` rejects it with "invalid option", drop `-S` and continue; see the Troubleshooting section at the end for a manual fallback if the boot entry then doesn't appear.

Unlike GRUB, systemd-boot reads its kernel/initrd straight off the ESP itself (not from `/boot` on your Btrfs root) — copy them over, using the kernel package name and microcode you picked in step 7:

```bash
KERNEL_NAME=linux-avalos      # or linux-avalos-bore / linux-avalos-compat
UCODE=intel-ucode             # or amd-ucode — leave empty ("") if you skipped microcode

mkdir -p /boot/efi/AvalOS
cp "/boot/vmlinuz-$KERNEL_NAME"        "/boot/efi/AvalOS/vmlinuz-$KERNEL_NAME"
cp "/boot/initramfs-$KERNEL_NAME.img"  "/boot/efi/AvalOS/initramfs-$KERNEL_NAME.img"
[ -n "$UCODE" ] && cp "/boot/$UCODE.img" "/boot/efi/AvalOS/$UCODE.img"

mkdir -p /boot/efi/loader/entries
cat > /boot/efi/loader/loader.conf << 'EOF'
default  avalos.conf
timeout  3
console-mode auto
editor   no
EOF

ROOT_UUID=$(blkid -s UUID -o value /dev/sda2)   # your root partition from step 3
{
  echo "title   AvalOS"
  echo "linux   /AvalOS/vmlinuz-$KERNEL_NAME"
  [ -n "$UCODE" ] && echo "initrd  /AvalOS/$UCODE.img"
  echo "initrd  /AvalOS/initramfs-$KERNEL_NAME.img"
  echo "options root=UUID=$ROOT_UUID rootflags=subvol=@ rw quiet splash loglevel=3"
} > /boot/efi/loader/entries/avalos.conf
```

Add a pacman hook so future kernel updates keep the ESP's copies in sync (otherwise the next `linux-avalos` update updates `/boot` but not `/boot/efi/AvalOS/`, and you boot the old kernel forever):

```bash
mkdir -p /etc/pacman.d/hooks
cat > "/etc/pacman.d/hooks/95-systemd-boot.hook" << EOF
[Trigger]
Type = Package
Target = $KERNEL_NAME
Operation = Install
Operation = Upgrade

[Action]
Description = Updating systemd-boot kernel files
When = PostTransaction
Exec = /usr/bin/bash -c 'cp /boot/vmlinuz-$KERNEL_NAME /boot/efi/AvalOS/vmlinuz-$KERNEL_NAME; cp /boot/initramfs-$KERNEL_NAME.img /boot/efi/AvalOS/initramfs-$KERNEL_NAME.img; [[ -n "$UCODE" ]] && [[ -f /boot/$UCODE.img ]] && cp /boot/$UCODE.img /boot/efi/AvalOS/$UCODE.img || true'
Depends = bash
EOF
```

**rEFInd**, the other alternative:

```bash
pacman -S --needed refind
refind-install

ROOT_UUID=$(blkid -s UUID -o value /dev/sda2)   # your root partition from step 3
cat > /boot/refind_linux.conf << EOF
"AvalOS (normal)"   "root=UUID=$ROOT_UUID rootflags=subvol=@ rw quiet splash loglevel=3"
"AvalOS (verbose)"  "root=UUID=$ROOT_UUID rootflags=subvol=@ rw"
"AvalOS (recovery)" "root=UUID=$ROOT_UUID rootflags=subvol=@ rw single"
EOF

mkdir -p /etc/pacman.d/hooks
cat > /etc/pacman.d/hooks/refind.hook << 'EOF'
[Trigger]
Operation = Upgrade
Type = Package
Target = refind

[Action]
Description = Updating rEFInd on the ESP...
When = PostTransaction
Exec = /usr/bin/refind-install
EOF
```

## 18. Configure Snapper

```bash
umount /.snapshots
rmdir /.snapshots
snapper --no-dbus -c root create-config /
btrfs subvolume delete /.snapshots
mkdir /.snapshots
mount -a
chmod 750 /.snapshots
```

(`--no-dbus`: Snapper defaults to talking to `snapperd` over D-Bus, which isn't running inside a chroot — without this flag `create-config` can hang or fail depending on your ISO's D-Bus setup. `create-config` also always tries to create its **own** `.snapshots` subvolume at this exact path, which fails with "already exists" against the persistent `@snapshots` you already mounted there in step 5 — that's why this deletes it and remounts the real one immediately after, rather than skipping `create-config` entirely.)

AvalOS trims Snapper's default retention (which keeps up to 50 snapshots per category) down to something that won't fill `@snapshots` on smaller disks:

```bash
sed -i \
  -e 's/TIMELINE_LIMIT_HOURLY="10"/TIMELINE_LIMIT_HOURLY="5"/' \
  -e 's/TIMELINE_LIMIT_DAILY="10"/TIMELINE_LIMIT_DAILY="7"/' \
  -e 's/TIMELINE_LIMIT_WEEKLY="0"/TIMELINE_LIMIT_WEEKLY="4"/' \
  -e 's/TIMELINE_LIMIT_MONTHLY="10"/TIMELINE_LIMIT_MONTHLY="3"/' \
  -e 's/TIMELINE_LIMIT_YEARLY="10"/TIMELINE_LIMIT_YEARLY="0"/' \
  -e 's/NUMBER_LIMIT="50"/NUMBER_LIMIT="10"/' \
  -e 's/NUMBER_LIMIT_IMPORTANT="50"/NUMBER_LIMIT_IMPORTANT="10"/' \
  /etc/snapper/configs/root

systemctl enable snapper-timeline.timer
systemctl enable snapper-cleanup.timer
```

**If you installed GRUB** in step 17, wire snapshots into its boot menu and regenerate it (the config only just started existing, so the `grub-mkconfig` you already ran doesn't know about it yet):

```bash
systemctl enable grub-btrfsd
grub-mkconfig -o /boot/grub/grub.cfg
```

**If you installed systemd-boot or rEFInd instead**, skip `grub-btrfsd` — it has nothing to do without GRUB. Your snapshots still exist and `snapper rollback` still works from a live session; they just won't appear as separate entries in your boot menu the way they do with GRUB.

## 19. Enable remaining services

```bash
systemctl enable NetworkManager
systemctl enable bluetooth
systemctl enable sddm
systemctl enable lm_sensors
systemctl enable systemd-oomd
systemctl enable systemd-resolved
systemctl --global enable pipewire pipewire-pulse wireplumber
```

(`avalos-gpu-detect.service` and, if applicable, `grub-btrfsd`/the Snapper timers were already enabled in steps 15 and 18.)

## 20. ZRAM and kernel tuning

```bash
cat > /etc/systemd/zram-generator.conf << 'EOF'
[zram0]
zram-size = min(ram / 2, 8192)
compression-algorithm = zstd
swap-priority = 100
EOF

mkdir -p /etc/sysctl.d
cat > /etc/sysctl.d/80-avalos-memory.conf << 'EOF'
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 500
EOF

cat > /etc/sysctl.d/81-avalos-bbr.conf << 'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
EOF

cat > /etc/sysctl.d/82-avalos-security.conf << 'EOF'
kernel.dmesg_restrict = 1
kernel.kptr_restrict = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.rp_filter = 1
EOF
```

`systemd-oomd` (enabled in step 19) needs its own thresholds — without this file it runs, but on much more conservative defaults:

```bash
cat > /etc/systemd/oomd.conf << 'EOF'
[OOM]
SwapUsedLimit=85%
DefaultMemoryPressureLimit=70%
DefaultMemoryPressureDurationSec=10s
EOF
```

Per-disk-type I/O scheduler (automatically applied by udev as disks are detected — no reboot needed to take effect on disks already present):

```bash
mkdir -p /etc/udev/rules.d
cat > /etc/udev/rules.d/60-avalos-iosched.rules << 'EOF'
ACTION=="add|change", KERNEL=="sd[a-z]*", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"
ACTION=="add|change", KERNEL=="sd[a-z]*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="nvme[0-9n]*", ATTR{queue/scheduler}="kyber"
ACTION=="add|change", KERNEL=="mmcblk[0-9]*", ATTR{queue/scheduler}="mq-deadline"
EOF
```

(HDD → `bfq` for fair, latency-friendly scheduling; SATA SSD → `mq-deadline`; NVMe → `kyber`, tuned for NVMe's low latency; eMMC → `mq-deadline`.)

## 21. (Optional) Gaming stack

```bash
pacman -S --needed steam wine-staging wine-gecko wine-mono winetricks \
  lib32-gnutls lib32-libpulse lib32-alsa-plugins \
  lib32-libx11 lib32-libxext lib32-libxcomposite lib32-libxrandr lib32-libxinerama lib32-libxi \
  lib32-sdl2-compat lib32-freetype2 lib32-gst-plugins-base-libs \
  vkd3d gamemode lib32-gamemode mangohud lib32-mangohud \
  lutris flatpak lib32-pipewire \
  gst-plugins-bad gst-plugins-ugly gst-libav
usermod -aG gamemode yourusername
```

(`lib32-sdl2-compat` and `lib32-gst-plugins-base-libs` are the two packages called out in step 7's caveat — if either comes back `target not found`, drop just that one and continue; most modern Proton/Wine builds don't need them. `gst-plugins-bad`/`-ugly`/`gst-libav` are extra codec support several game engines' video/cutscene playback needs.)

For Proton-GE and Heroic Games Launcher, you'll need an AUR helper. **This has to run as your regular user, not root** — `makepkg` refuses outright to build as root by default, which is exactly what happens if you paste this in as-is while still root from the rest of this guide:

```bash
pacman -S --needed base-devel git

sudo -H -u yourusername bash -c '
  set -euo pipefail
  TMPD=$(mktemp -d)
  git clone --depth=1 https://aur.archlinux.org/yay.git "$TMPD/yay_build"
  cd "$TMPD/yay_build"
  makepkg -si --noconfirm --needed
  rm -rf "$TMPD"
'
```

You'll be prompted for `yourusername`'s password partway through — that's `sudo` inside `makepkg` asking to install build dependencies and, at the end, the built package itself. That's expected; just type it.

```bash
sudo -H -u yourusername yay -S --noconfirm --needed proton-ge-custom-bin heroic-games-launcher-bin
```

GameMode's tuning profile (performance governor, GPU optimizations, and a per-app whitelist so it only engages for actual games):

```bash
cat > /etc/gamemode.ini << 'EOF'
[general]
reaper_freq=5
defaultgov=performance
desiredgov=performance
softrealtime=auto
renice=-10

[gpu]
apply_gpu_optimisations=accept-responsibility
gpu_device=0
amd_performance_level=high

[filter]
whitelist=steam
whitelist=lutris
whitelist=heroic
EOF
```

MangoHud's Tokyo-Night-themed overlay config (already Tokyo-Night-styled to match the rest of AvalOS — toggle in-game with `Shift_R+F12`):

```bash
mkdir -p /etc/MangoHud
cp /usr/share/avalos/configs/mangohud/MangoHud.conf /etc/MangoHud/MangoHud.conf
```

And register Flathub, since `flatpak` itself doesn't come with any remotes configured by default:

```bash
sudo -H -u yourusername flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

## 22. DNS-over-TLS

This is last on purpose — enabling it any earlier (e.g. alongside the other services in step 19) breaks DNS resolution for the rest of the chroot, including the `git clone` against `aur.archlinux.org` in step 21. `systemd-resolved`'s real stub-resolver file doesn't get created until the service actually *runs*, which never happens inside a chroot (`systemctl enable` just arms it for the next real boot) — so pointing `/etc/resolv.conf` at that stub file any sooner leaves every DNS lookup broken until you reboot into the installed system for real.

```bash
cat > /etc/systemd/resolved.conf << 'EOF'
[Resolve]
DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com 8.8.8.8#dns.google 8.8.4.4#dns.google
FallbackDNS=9.9.9.9#dns.quad9.net
DNSOverTLS=yes
DNSSEC=allow-downgrade
Cache=yes
DNSStubListener=yes
EOF

rm -f /etc/resolv.conf
ln -s ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

(`systemd-resolved` itself was already enabled back in step 19 — this just points `resolv.conf` at it and gives it a DNS-over-TLS configuration.)

## 23. Exit and reboot

```bash
exit                    # leave the chroot
umount -R /mnt
reboot
```

Remove the USB drive when the system powers down for the reboot.

---

## Troubleshooting

- **Drops to an emergency shell on first boot (Btrfs install):** almost always a missing `rootflags=subvol=@` (systemd-boot/rEFInd, see step 17) or a leftover `subvolid=` in `/etc/fstab` (step 8).
- **`linux-avalos` "installed" but the system boots the plain Arch `linux` kernel instead (or `pacstrap` in step 7 quietly grabs the wrong kernel):** check `/etc/pacman.conf`'s `IgnorePkg` line before you `pacstrap` — see the callout in step 7. Verify after the fact with `arch-chroot /mnt pacman -Q linux-avalos`.
- **`pacman -S` inside the chroot fails with "target not found" for `linux-avalos-firmware`, any `lib32-*` package, or basically everything:** `/etc/pacman.conf` in a freshly-`pacstrap`ed system doesn't have `[avalos]`/`[multilib]` (or sometimes not even `[core]`/`[extra]`) until you add them yourself — see step 12.
- **`makepkg` refuses to run ("Running makepkg as root is not allowed"):** you're still root. The entire yay bootstrap in step 21 has to run as your regular user via `sudo -H -u yourusername`.
- **`pacstrap`/`pacman` reports `target not found` for a package you know exists:** check you haven't mistyped it, then check whether it's one of the 32-bit multimedia packages called out in step 7 — those specifically have a history of being temporarily pulled from `[multilib]`.
- **`pacstrap` fails with `failed retrieving file` on many packages at once, not "target not found":** a connection/bandwidth issue, not a missing package — see the `ParallelDownloads` fix in step 7.
- **systemd-boot installs fine but no "Linux Boot Manager" entry shows up in your firmware's boot menu:** either `arch-chroot -S` wasn't available on your ISO (see step 17) and the NVRAM write got silently skipped, or your firmware doesn't persist the entry at all. Add one manually from a live session, or rely on the ESP's default fallback path instead:
  ```bash
  efibootmgr --create --disk /dev/sda --part 1 --loader '\EFI\systemd\systemd-bootx64.efi' --label "Linux Boot Manager"
  ```
- **No sound, or GPU acceleration doesn't work:** double check you installed the driver block matching your *actual* GPU vendor in step 13, not the other one — and that `/etc/environment` (step 14) has the matching `VDPAU_DRIVER`/`LIBVA_DRIVER_NAME` pair, not the AMD defaults left over from this guide's example.
- **NVIDIA GPU:** not supported. AvalOS's firmware and driver packages are AMD/Intel only project-wide; installing on NVIDIA hardware will leave you with software rendering at best.

If you hit something not covered here, open an issue on the [AvalOS GitHub repo](https://github.com/jeffreysama/avalos/issues) with the exact error text.
