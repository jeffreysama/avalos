# AvalOS

![AvalOS Logo](assets/AvalOS-logo.png)

**AvalOS** is a minimalist, beautiful, and high-performance Arch-based Linux distribution focused on **gaming** and **daily productivity**.

It ships with **Hyprland** (Wayland) as the default desktop environment, delivering a modern, lightweight, and highly customizable experience right out of the box.

---

## ✨ Features

- **Base**: Arch Linux (rolling release)
- **Desktop Environment**: Hyprland (Wayland)
- **Philosophy**: Minimalism, performance, and ease of use
- **Target Users**: Gamers, developers, and power users who want something clean and fast
- **Custom Kernel**: `linux-avalos` (optimized for desktop and gaming)
- **Pre-configured Rice**: Beautiful and functional Hyprland setup included

---

## 📥 Installation

AvalOS ISOs are fully functional and ready for installation.

> **Note**: The automatic installer is currently not working.  
> Please follow the **manual installation** guide below.

### Manual Installation

1. Download the latest ISO from the [Releases](https://github.com/jeffreysama/avalos/releases) page.
2. Flash it to a USB drive (use the included USB maker scripts if you prefer, or any tool like `dd`, Rufus, Ventoy, etc.).
3. Boot from the USB.
4. Follow the [Manual Installation Guide](docs/INSTALL.md) (or the steps in the next section of this README).

---

## 🛠️ Manual Installation Guide (Quick Version)

> Full detailed guide coming soon in `INSTALL.md`.  
> This is a condensed overview of the recommended steps.

1. Boot the AvalOS live ISO.
2. Connect to the internet (`iwctl` or `nmtui`).
3. Partition your disk (`cfdisk` / `fdisk` / `parted`).
4. Format and mount partitions.
5. Install the base system + AvalOS packages.
6. Configure the system (locale, hostname, users, bootloader, etc.).
7. Install and enable the pre-configured Hyprland rice.
8. Reboot into your new AvalOS system.

*(Detailed commands and explanations will be added in the full guide.)*

---

## ⚠️ Current Status

AvalOS is under active development.  
The ISOs work correctly for manual installation.  
The automatic installer is temporarily disabled while it is being fixed.

---

## 🤝 Contributing

Feel free to open issues or pull requests.  
Feedback from gamers and power users is especially welcome.
