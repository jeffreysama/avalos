# Installing AvalOS Manually

This guide walks you through installing AvalOS **from the live ISO**, by hand, using the same architecture the graphical installer targets: Btrfs with Snapper snapshots, ZRAM, BBR, Hyprland, and the custom `linux-avalos` kernel line. Every value in this guide (package names, mount options, subvolume layout) is taken directly from AvalOS's own installer code, so a manual install ends up equivalent to what the automatic one would produce.

> **Only AMD and Intel hardware is supported.** AvalOS deliberately avoids NVIDIA firmware and drivers project-wide. If you have an NVIDIA GPU, this distribution is not for you yet.

---

## 0. Before you start

- **Back up your data.** This guide erases the target disk.
- **UEFI is recommended.** BIOS/Legacy works but skips Secure Boot entirely (Secure Boot isn't supported either way). This guide assumes UEFI; BIOS-specific commands are called out where they differ.
- **At least 30 GB of free disk space.**
- **A working internet connection** — the installer downloads packages live from Arch's repos plus AvalOS's own kernel repo, it does not ship them on the ISO.
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

This gives a 512 MiB EFI System Partition and a root partition using the rest of the disk. If you plan to use systemd-boot (see step 12), consider bumping the ESP to 1 GiB — 512 MiB gets tight once you have two kernel variants plus fallback images sitting in it.

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

## 7. Install the base system

The live ISO already ships with the `[avalos]` repo and `[multilib]` enabled in `/etc/pacman.conf` — you don't need to add them yourself. Confirm they're there:

```bash
grep -A2 "\[avalos\]" /etc/pacman.conf
grep -A2 "\[multilib\]" /etc/pacman.conf
```

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

Now install. This is the exact base package set AvalOS uses — note that firmware is installed as **individual vendor packages, not the `linux-firmware` meta-package**, specifically to avoid pulling in `linux-firmware-nvidia` as a hard dependency on a project that excludes NVIDIA entirely:

```bash
pacstrap -c --needed /mnt \
  base base-devel \
  linux-avalos linux-avalos-headers \
  intel-ucode \
  linux-firmware-amdgpu linux-firmware-radeon linux-firmware-intel \
  linux-firmware-realtek linux-firmware-atheros linux-firmware-broadcom \
  linux-firmware-cirrus linux-firmware-mediatek linux-firmware-other \
  sof-firmware \
  grub efibootmgr os-prober ntfs-3g networkmanager nm-connection-editor \
  sudo bash bash-completion nano vim git curl wget htop \
  python python-pip man-db man-pages less openssh \
  zip unzip p7zip zram-generator \
  reflector pacman-contrib xdg-utils udiskie \
  fastfetch bat github-cli \
  btrfs-progs snapper snap-pac grub-btrfs inotify-tools
```

(Swap `linux-avalos linux-avalos-headers` for `linux-avalos-compat linux-avalos-compat-headers` if that's what your CPU needs, and `intel-ucode` for `amd-ucode` on AMD. Drop `os-prober`/`ntfs-3g` if you don't need Windows dual-boot detection.)

If `pacstrap` fails partway through with a burst of `failed retrieving file` errors on otherwise-valid packages (not "target not found" — an actual download failure), it's usually a connection that can't handle several large files downloading at once. Lower the parallelism and retry:

```bash
sed -i 's/^ParallelDownloads.*/ParallelDownloads = 1/' /etc/pacman.conf
```

then re-run the same `pacstrap` command — it'll skip anything already installed since `--needed` is set.

> **Known caveat:** `lib32-sdl2-compat` and `lib32-gst-plugins-base-libs` (32-bit multimedia libs, needed for some older Wine/Proton titles) have occasionally been pulled from Arch's official `[multilib]` repo for days-to-weeks at a time following security advisories in that stack. If pacstrap reports these two specifically as `target not found`, that's not a mistake on your end — just drop them from the package list above and continue; most modern Proton/Wine builds don't need them. Install them later once they reappear upstream.

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

```bash
arch-chroot /mnt
```

Everything from here on runs **inside the chroot**, on the new system.

## 10. Timezone, locale, hostname

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

## 11. Root password and user account

```bash
passwd
useradd -m -G wheel,audio,video,storage,optical -s /bin/bash yourusername
passwd yourusername

sed -i 's/^# %wheel ALL=(ALL:ALL) ALL/%wheel ALL=(ALL:ALL) ALL/' /etc/sudoers
```

## 12. Enable the AvalOS repo keyring

The live ISO's keyring for the `[avalos]` repo needs to be populated in the *new* system too, or `pacman -S linux-avalos*` (for future updates) and any AUR-adjacent tooling will fail to verify it:

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
  hyprland xdg-desktop-portal-hyprland xdg-desktop-portal-gtk \
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
  nwg-look nwg-displays papirus-icon-theme lm_sensors acpi capitaine-cursors
```

`noto-fonts-cjk` is the one big download here (~300 MB) — it's what gives full Chinese/Japanese/Korean character coverage instead of the much smaller but incomplete `wqy-microhei`.

## 14. Copy the AvalOS configs and branding

The live ISO ships AvalOS's actual Hyprland/Waybar/Kitty/Rofi/Mako/SDDM/fastfetch configs at `/usr/share/avalos/configs/` — copy them into the new user's home and the system:

```bash
mkdir -p /home/yourusername/.config
cp -r /usr/share/avalos/configs/hyprland   /home/yourusername/.config/hypr
cp -r /usr/share/avalos/configs/waybar     /home/yourusername/.config/waybar
cp -r /usr/share/avalos/configs/kitty      /home/yourusername/.config/kitty
cp -r /usr/share/avalos/configs/rofi       /home/yourusername/.config/rofi
cp -r /usr/share/avalos/configs/mako       /home/yourusername/.config/mako
cp -r /usr/share/avalos/configs/mangohud   /home/yourusername/.config/MangoHud
mkdir -p /etc/fastfetch
cp -r /usr/share/avalos/configs/fastfetch/. /etc/fastfetch/
mkdir -p /usr/share/sddm/themes/avalos
cp -r /usr/share/avalos/configs/sddm/.     /usr/share/sddm/themes/avalos/
cat > /etc/sddm.conf.d/theme.conf << 'EOF'
[Theme]
Current=avalos
EOF

chown -R yourusername:yourusername /home/yourusername/.config
```

If a folder is missing under `/usr/share/avalos/configs/` (this can happen on a partial/older ISO build), skip that one — the corresponding app will just start with its own defaults instead of the AvalOS theme.

## 15. Configure mkinitcpio

Add the `btrfs` hook, and `grub-btrfs-overlayfs` if you're using GRUB (step 16):

```bash
sed -i 's/^HOOKS=(\(.*\)filesystems\(.*\))/HOOKS=(\1btrfs filesystems\2)/' /etc/mkinitcpio.conf
# If using GRUB:
sed -i 's/^HOOKS=(\(.*\)fsck\(.*\))/HOOKS=(\1grub-btrfs-overlayfs fsck\2)/' /etc/mkinitcpio.conf

mkinitcpio -P
```

## 16. Install the bootloader

**GRUB is the recommended choice** — it's the only one of the three bootloaders AvalOS supports where the Btrfs subvolume gets detected and wired into the boot entry automatically via `grub-mkconfig`. If you use systemd-boot or rEFInd instead, you **must** add `rootflags=subvol=@` to the kernel command line yourself, or the system will drop to an emergency shell on first boot (neither of those two reads the subvolume from fstab the way GRUB does).

**GRUB, UEFI:**

```bash
pacman -S --needed grub efibootmgr
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=GRUB

sed -i 's/^GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=false/' /etc/default/grub
grep -q "^GRUB_DISABLE_OS_PROBER" /etc/default/grub || echo "GRUB_DISABLE_OS_PROBER=false" >> /etc/default/grub

grub-mkconfig -o /boot/grub/grub.cfg
```

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

**If you insist on systemd-boot or rEFInd anyway**, remember the `rootflags=subvol=@` requirement above applies to every boot entry you write, in addition to whatever normal setup steps those bootloaders need (`bootctl install`, or `refind-install` + `refind_linux.conf`).

## 17. Configure Snapper

```bash
umount /.snapshots
rm -rf /.snapshots
snapper -c root create-config /
btrfs subvolume delete /.snapshots
mkdir /.snapshots
mount -a
chmod 750 /.snapshots
```

(Snapper's `create-config` wants to create its own `.snapshots` subvolume; since we already mounted our own `@snapshots` there, this dance replaces Snapper's default with the one from fstab.)

## 18. Enable services

```bash
systemctl enable NetworkManager
systemctl enable bluetooth
systemctl enable sddm
systemctl enable lm_sensors
systemctl enable systemd-oomd
systemctl enable systemd-resolved
systemctl enable snapper-timeline.timer
systemctl enable snapper-cleanup.timer
systemctl enable grub-btrfsd
systemctl --global enable pipewire pipewire-pulse wireplumber
```

## 19. ZRAM and kernel tuning

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

## 20. (Optional) Gaming stack

```bash
pacman -S --needed steam wine-staging wine-gecko wine-mono winetricks \
  lib32-gnutls lib32-libpulse lib32-alsa-plugins \
  lib32-libx11 lib32-libxext lib32-libxcomposite lib32-libxrandr lib32-libxinerama lib32-libxi \
  lib32-freetype2 vkd3d gamemode lib32-gamemode mangohud lib32-mangohud \
  lutris flatpak lib32-pipewire
usermod -aG gamemode yourusername
```

For Proton-GE and Heroic Games Launcher, you'll need an AUR helper since those aren't in the official repos:

```bash
pacman -S --needed base-devel git
cd /tmp
git clone https://aur.archlinux.org/yay.git
cd yay
makepkg -si --noconfirm
cd /
sudo -u yourusername yay -S --noconfirm proton-ge-custom-bin heroic-games-launcher-bin
```

(`lib32-sdl2-compat` and `lib32-gst-plugins-base-libs` belong with the rest of the 32-bit gaming libs above — see the caveat in step 7 if either one is unavailable right now.)

## 21. Exit and reboot

```bash
exit                    # leave the chroot
umount -R /mnt
reboot
```

Remove the USB drive when the system powers down for the reboot.

---

## Troubleshooting

- **Drops to an emergency shell on first boot (Btrfs install):** almost always a missing `rootflags=subvol=@` (systemd-boot/rEFInd, see step 16) or a leftover `subvolid=` in `/etc/fstab` (step 8).
- **`pacstrap`/`pacman` reports `target not found` for a package you know exists:** check you haven't mistyped it, then check whether it's one of the 32-bit multimedia packages called out in step 7 — those specifically have a history of being temporarily pulled from `[multilib]`.
- **`pacstrap` fails with `failed retrieving file` on many packages at once, not "target not found":** a connection/bandwidth issue, not a missing package — see the `ParallelDownloads` fix in step 7.
- **No sound, or GPU acceleration doesn't work:** double check you installed the driver block matching your *actual* GPU vendor in step 13, not the other one.
- **NVIDIA GPU:** not supported. AvalOS's firmware and driver packages are AMD/Intel only project-wide; installing on NVIDIA hardware will leave you with software rendering at best.

If you hit something not covered here, open an issue on the [AvalOS GitHub repo](https://github.com/jeffreysama/avalos/issues) with the exact error text.
