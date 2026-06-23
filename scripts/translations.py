# ════════════════════════════════════════════════════════════════════════════
#  AvalOS — Módulo de internacionalización (i18n)
#  Idiomas: English (en) · Español (es) · 中文简体 (zh)
#
#  Añadir idioma: copiar el bloque "en", cambiar el código y traducir los values.
#  Añadir string:  añadirlo en los TRES idiomas para mantener consistencia.
# ════════════════════════════════════════════════════════════════════════════

TRANSLATIONS: dict[str, dict[str, str]] = {

    # ── English ──────────────────────────────────────────────────────────────
    "en": {
        # Installer window / meta
        "title":             "AvalOS — Installer",
        "topbar":            "● AvalOS Installer",
        "step-hint":         "Select disk and configure the system",

        # Welcome page
        "welcome-sub":       "Arch Linux · Hyprland · Wayland · Tokyo Night",
        "welcome-desc":      "Welcome to the <strong>AvalOS</strong> installer.<br>"
                             "This wizard will configure and install the system on your chosen disk.",
        "btn-start":         "Start installation →",

        # Config page — section titles
        "sec-disk":          "▸ Destination disk",
        "sec-user":          "▸ User account",
        "sec-host":          "▸ Computer name",
        "sec-lang":          "▸ Language & keyboard",
        "sec-advanced":      "▸ Advanced options",

        # Form labels
        "lbl-user":          "Username",
        "lbl-pass":          "Password",
        "lbl-confirm-pass":  "Confirm password",
        "lbl-show-hide":     "Show/hide",
        "lbl-hostname":      "Hostname",
        "lbl-timezone":      "Time zone",
        "lbl-locale":        "Locale",
        "lbl-keymap":        "Keyboard layout",
        "lbl-bootloader":    "Bootloader",
        "lbl-install-type":  "Installation type",
        "lbl-extras":        "Extras",
        "btn-install":       "▶ Install AvalOS",
        "btn-abort":         "⛔ Abort",
        "btn-retry":         "↺ Retry",
        "btn-reboot":        "⟳ Reboot now",
        "btn-close":         "Close",

        # Bootloader / mode options
        "opt-no-boot":       "No bootloader",
        "opt-pc":            "💾 PC / HDD / SSD",
        "opt-usb":           "🔌 Persistent USB",
        "opt-pc-desc":       "Btrfs with subvolumes — automatic snapshots, rollback from GRUB.",
        "opt-usb-desc":      "ext4 without journal + noatime — minimizes writes on the USB drive.",
        "opt-grub-desc":     "Universal. BIOS + UEFI, dual-boot. Btrfs snapshot menu at boot.",
        "chk-gaming-title":  "🎮 Gaming",
        "chk-gaming-desc":   "Steam · Wine · DXVK · VKD3D · GameMode · MangoHUD · Lutris · Proton-GE (~2.5 GB extra)",
        "chk-bore-title":    "⚡ BORE Scheduler",
        "chk-bore-desc":     "linux-avalos-bore kernel — better responsiveness in games. Requires a CPU with AVX2 (x86-64-v3+); if unsupported, it's ignored and the standard kernel is used.",
        "opt-sdboot-desc":   "UEFI only, fast. Snapshots via terminal — no visual boot menu.",
        "opt-refind-desc":   "UEFI only. Auto-detects kernels. Snapshots require manual config.",
        # Progress overlay
        "log-title":         "▸ Installation log",
        "cd-title":          "⚠ POINT OF NO RETURN",
        "cd-desc":           "The disk will be wiped. This cannot be undone.",
        "cd-confirm":        "Confirm and install",
        "cd-cancel":         "Cancel",
        "err-title":         "⛔ Critical error",
        "done-title":        "AvalOS installed successfully",
        "done-desc":         "Remove the USB drive and reboot. SDDM will ask you to log in — select Hyprland.",

        # Validation messages
        "val-select-disk":   "Select a destination disk",
        "val-invalid-user":  "Enter a valid username (minimum 2 characters)",
        "val-min-user":      "Minimum 2 characters, maximum 32",
        "val-pass-short":    "Password must be at least 8 characters",
        "val-pass-weak":     "Password is too weak — add uppercase letters, numbers or symbols",
        "val-pass-mismatch": "✗ Passwords do not match",
        "val-pass-ok":       "✓ Passwords match",
        "val-reserved-user": "That username is reserved by the system",
        "val-uefi-req":      "requires UEFI and this machine boots in BIOS Legacy. Use GRUB.",
        "val-uefi-warn":     "only works on UEFI. Make sure your computer is not BIOS Legacy.",
        "warn-sdboot-snaps": "<b>⚠ systemd-boot — Snapshots without boot menu</b><br>AvalOS uses <b>Btrfs + snapper</b> for automatic snapshots (pre/post every update). With systemd-boot, snapshots work correctly and <code>snapper rollback &lt;N&gt;</code> lets you restore from terminal.<br><br>What you <b>won't have</b>: a visual snapshot menu at boot like GRUB offers. If the system fails to boot, you'll need to boot from the live USB and run the rollback from there.<br><br>✦ Snapshots are still <b>fully functional</b> — only the visual boot menu is missing.",
        "warn-refind-snaps": "<b>⚠ rEFInd — Snapshots require manual setup</b><br>AvalOS uses <b>Btrfs + snapper</b> for automatic snapshots. With rEFInd, snapshot entries in the boot menu are <b>not generated automatically</b> — each snapshot would need to be added manually to <code>refind.conf</code>.<br><br><code>snapper rollback &lt;N&gt;</code> works from terminal. For the visual menu you'd need to configure rEFInd manually after installation.<br><br>✦ Snapshots are still <b>fully functional</b> — the boot menu integration is manual only.",

        # Status / runtime messages
        "status-error":      "Error — check the log or press Retry",
        "err-timeout":       "Timeout expired. Close and reopen the installer.",

        # Install steps — label (short) and detail (extra info shown below)
        "step-uefi":         "Detecting boot mode",
        "step-uefi-d":       "UEFI / BIOS Legacy",
        "step-net":          "Verifying internet connection",
        "step-net-d":        "Required for pacstrap",
        "step-tools":        "Verifying tools",
        "step-tools-d":      "parted, mkfs, pacstrap…",
        "step-part":         "Partitioning target disk",
        "step-part-d":       "",
        "step-format":       "Formatting partitions",
        "step-format-d":     "FAT32 (EFI) + Btrfs (root)",
        "step-mount":        "Mounting filesystem",
        "step-mount-d":      "",
        "step-mirrors":      "Optimizing mirrors with reflector",
        "step-mirrors-d":    "Selecting fastest mirrors",
        "step-pacstrap":     "Installing base system",
        "step-pacstrap-d":   "pacstrap — may take several minutes",
        "step-fstab":        "Generating fstab",
        "step-fstab-d":      "",
        "step-config":       "Configuring system",
        "step-config-d":     "locale · hostname · timezone · initramfs",
        "step-grub":         "Installing bootloader",
        "step-grub-d":       "",
        "step-services":     "Enabling services",
        "step-services-d":   "NetworkManager · bluetooth · SDDM",
        "step-user":         "Creating system user",
        "step-user-d":       "",
        "step-aur":          "Installing AUR packages (yay)",
        "step-aur-d":        "microsoft-edge-stable-bin",
        "step-hypr":         "Configuring Hyprland + Wayland",
        "step-hypr-d":       "SDDM · Waybar · hyprland.lua",
        "step-umount":       "Unmounting and finalizing",
        "step-umount-d":     "",

        # Fastfetch module keys
        "ff-os":             " OS",
        "ff-host":           "\uf0e4 Host",
        "ff-kernel":         " Kernel",
        "ff-uptime":         "\uf55f Uptime",
        "ff-packages":       "\uf439 Packages",
        "ff-shell":          " Shell",
        "ff-display":        "\uf879 Resolution",
        "ff-wm":             " WM",
        "ff-terminal":       " Terminal",
        "ff-cpu":            " CPU",
        "ff-gpu":            "\uf43f GPU",
        "ff-ram":            "\uf55b RAM",
        "ff-disk":           "\uf4cb Disk",

        # Power menu (powermenu.sh)
        "pm-off":            "  Power Off",
        "pm-reboot":         "  Reboot",
        "pm-suspend":        "  Suspend",
        "pm-logout":         "󰍃  Log Out",
        "pm-lock":           "  Lock",
        "pm-title":          "  Power Menu",
        # SDDM login screen (Main.qml) — usa lbl-user/lbl-pass para los placeholders
        "sddm-signin":       "Sign In",
        "sddm-fail":         "Authentication failed. Try again.",
        "sddm-session":      "Session",
        "sddm-suspend":      "Suspend",
        "sddm-restart":      "Restart",
        "sddm-shutdown":     "Shutdown",
        # Password requirement checklist (pg-config, real-time validation)
        "req-len-ok":        "✓ 8+ characters",
        "req-len-x":         "✗ 8+ characters",
        "req-upper-ok":      "✓ Uppercase",
        "req-upper-x":       "✗ Uppercase",
        "req-lower-ok":      "✓ Lowercase",
        "req-lower-x":       "✗ Lowercase",
        "req-num-ok":        "✓ Number",
        "req-num-x":         "✗ Number",
        "req-sym-ok":        "✓ Symbol",
        "req-sym-x":         "✗ Symbol",
        # Language selection page warning
        "lang-warning":      "⚠  UI language pack only · Mirrors are optimized for SV, US, MX & GT "
                             "— downloads may be slow for mainland China or regions far from these countries.",
    },

    # ── Español ───────────────────────────────────────────────────────────────
    "es": {
        "title":             "AvalOS — Instalador",
        "topbar":            "● AvalOS Installer",
        "step-hint":         "Selecciona disco y configura el sistema",

        "welcome-sub":       "Arch Linux · Hyprland · Wayland · Tokyo Night",
        "welcome-desc":      "Bienvenido al instalador de <strong>AvalOS</strong>.<br>"
                             "Este asistente configurará e instalará el sistema en el disco de tu elección.",
        "btn-start":         "Comenzar instalación →",

        "sec-disk":          "▸ Disco de destino",
        "sec-user":          "▸ Cuenta de usuario",
        "sec-host":          "▸ Nombre del equipo",
        "sec-lang":          "▸ Idioma y teclado",
        "sec-advanced":      "▸ Opciones avanzadas",

        "lbl-user":          "Usuario",
        "lbl-pass":          "Contraseña",
        "lbl-confirm-pass":  "Confirmar contraseña",
        "lbl-show-hide":     "Mostrar/ocultar",
        "lbl-hostname":      "Nombre del equipo",
        "lbl-timezone":      "Zona horaria",
        "lbl-locale":        "Configuración regional",
        "lbl-keymap":        "Distribución de teclado",
        "lbl-bootloader":    "Cargador de arranque",
        "lbl-install-type":  "Tipo de instalación",
        "lbl-extras":        "Extras",

        "btn-install":       "▶ Instalar AvalOS",
        "btn-abort":         "⛔ Abortar",
        "btn-retry":         "↺ Reintentar",
        "btn-reboot":        "⟳ Reiniciar ahora",
        "btn-close":         "Cerrar",

        "opt-no-boot":       "Sin bootloader",
        "opt-pc":            "💾 PC / HDD / SSD",
        "opt-usb":           "🔌 USB Persistente",
        "opt-pc-desc":       "Btrfs con subvolúmenes — snapshots automáticos, rollback desde GRUB.",
        "opt-usb-desc":      "ext4 sin journal + noatime — minimiza escrituras en el pendrive.",
        "opt-grub-desc":     "Universal. BIOS + UEFI, dual-boot. Menú de snapshots Btrfs en el arranque.",
        "chk-gaming-title":  "🎮 Gaming",
        "chk-gaming-desc":   "Steam · Wine · DXVK · VKD3D · GameMode · MangoHUD · Lutris · Proton-GE (~2.5 GB extra)",
        "chk-bore-title":    "⚡ Scheduler BORE",
        "chk-bore-desc":     "Kernel linux-avalos-bore — mejor respuesta en juegos. Requiere CPU con AVX2 (x86-64-v3+); si no es compatible, se ignora y se usa el kernel estándar.",
        "opt-sdboot-desc":   "Solo UEFI, rápido. Snapshots vía terminal, sin menú visual en el arranque.",
        "opt-refind-desc":   "Solo UEFI. Detecta kernels automáticamente. Snapshots requieren config manual.",

        "log-title":         "▸ Log de instalación",
        "cd-title":          "⚠ ZONA DE NO RETORNO",
        "cd-desc":           "El disco será borrado. Esta acción no se puede deshacer.",
        "cd-confirm":        "Confirmar e instalar",
        "cd-cancel":         "Cancelar",
        "err-title":         "⛔ Error crítico",
        "done-title":        "AvalOS instalado correctamente",
        "done-desc":         "Retira el USB y reinicia el equipo. SDDM te pedirá iniciar sesión — selecciona Hyprland.",

        # Mensajes de validación
        "val-select-disk":   "Selecciona un disco de destino",
        "val-invalid-user":  "Escribe un nombre de usuario válido (mínimo 2 caracteres)",
        "val-min-user":      "Mínimo 2 caracteres, máximo 32",
        "val-pass-short":    "La contraseña debe tener al menos 8 caracteres",
        "val-pass-weak":     "La contraseña es demasiado débil — añade letras mayúsculas, números o símbolos",
        "val-pass-mismatch": "✗ Las contraseñas no coinciden",
        "val-pass-ok":       "✓ Las contraseñas coinciden",
        "val-reserved-user": "Ese nombre de usuario está reservado por el sistema",
        "val-uefi-req":      "requiere UEFI y esta máquina arranca en BIOS Legacy. Usa GRUB.",
        "val-uefi-warn":     "solo funciona en UEFI. Asegúrate de que tu equipo no sea BIOS Legacy.",
        "warn-sdboot-snaps": "<b>⚠ systemd-boot — Snapshots sin menú en el arranque</b><br>AvalOS usa <b>Btrfs + snapper</b> para snapshots automáticos (antes/después de cada actualización). Con systemd-boot los snapshots funcionan correctamente y <code>snapper rollback &lt;N&gt;</code> permite restaurar desde la terminal.<br><br>Lo que <b>no tendrás</b>: un menú visual de snapshots en el arranque como GRUB ofrece. Si el sistema no arranca, necesitarás el USB live para hacer el rollback desde ahí.<br><br>✦ Los snapshots siguen siendo <b>completamente funcionales</b> — solo falta el menú visual en el boot.",
        "warn-refind-snaps": "<b>⚠ rEFInd — Snapshots requieren configuración manual</b><br>AvalOS usa <b>Btrfs + snapper</b> para snapshots automáticos. Con rEFInd, las entradas de snapshots en el menú de arranque <b>no se generan automáticamente</b> — cada snapshot habría que añadirlo manualmente a <code>refind.conf</code>.<br><br><code>snapper rollback &lt;N&gt;</code> funciona desde la terminal. Para el menú visual habría que configurar rEFInd manualmente después de la instalación.<br><br>✦ Los snapshots siguen siendo <b>completamente funcionales</b> — solo la integración con el menú de boot es manual.",

        "status-error":      "Error — revisa el log o pulsa Reintentar",
        "err-timeout":       "Tiempo de espera agotado. Cierra y vuelve a abrir el instalador.",

        "step-uefi":         "Detectando modo de arranque",
        "step-uefi-d":       "UEFI / BIOS Legacy",
        "step-net":          "Verificando conexión a internet",
        "step-net-d":        "Requerida para pacstrap",
        "step-tools":        "Verificando herramientas",
        "step-tools-d":      "parted, mkfs, pacstrap…",
        "step-part":         "Particionando disco destino",
        "step-part-d":       "",
        "step-format":       "Formateando particiones",
        "step-format-d":     "FAT32 (EFI) + Btrfs (root)",
        "step-mount":        "Montando sistema de archivos",
        "step-mount-d":      "",
        "step-mirrors":      "Optimizando mirrors con reflector",
        "step-mirrors-d":    "Seleccionando mirrors más rápidos",
        "step-pacstrap":     "Instalando sistema base",
        "step-pacstrap-d":   "pacstrap — puede tardar varios minutos",
        "step-fstab":        "Generando fstab",
        "step-fstab-d":      "",
        "step-config":       "Configurando sistema",
        "step-config-d":     "locale · hostname · timezone · initramfs",
        "step-grub":         "Instalando bootloader",
        "step-grub-d":       "",
        "step-services":     "Habilitando servicios",
        "step-services-d":   "NetworkManager · bluetooth · SDDM",
        "step-user":         "Creando usuario del sistema",
        "step-user-d":       "",
        "step-aur":          "Instalando paquetes AUR (yay)",
        "step-aur-d":        "microsoft-edge-stable-bin",
        "step-hypr":         "Configurando Hyprland + Wayland",
        "step-hypr-d":       "SDDM · Waybar · hyprland.lua",
        "step-umount":       "Desmontando y finalizando",
        "step-umount-d":     "",

        "ff-os":             " OS",
        "ff-host":           "\uf0e4 Host",
        "ff-kernel":         " Kernel",
        "ff-uptime":         "\uf55f Uptime",
        "ff-packages":       "\uf439 Paquetes",
        "ff-shell":          " Shell",
        "ff-display":        "\uf879 Resolución",
        "ff-wm":             " WM",
        "ff-terminal":       " Terminal",
        "ff-cpu":            " CPU",
        "ff-gpu":            "\uf43f GPU",
        "ff-ram":            "\uf55b RAM",
        "ff-disk":           "\uf4cb Disco",

        "pm-off":            "  Apagar",
        "pm-reboot":         "  Reiniciar",
        "pm-suspend":        "  Suspender",
        "pm-logout":         "󰍃  Cerrar Sesión",
        "pm-lock":           "  Bloquear",
        "pm-title":          "  Menú de Energía",
        # Pantalla de login SDDM (Main.qml) — usa lbl-user/lbl-pass para los placeholders
        "sddm-signin":       "Iniciar Sesión",
        "sddm-fail":         "Autenticación fallida. Intenta de nuevo.",
        "sddm-session":      "Sesión",
        "sddm-suspend":      "Suspender",
        "sddm-restart":      "Reiniciar",
        "sddm-shutdown":     "Apagar",
        # Checklist de requisitos de contraseña (pg-config, validación en tiempo real)
        "req-len-ok":        "✓ 8+ caracteres",
        "req-len-x":         "✗ 8+ caracteres",
        "req-upper-ok":      "✓ Mayúscula",
        "req-upper-x":       "✗ Mayúscula",
        "req-lower-ok":      "✓ Minúscula",
        "req-lower-x":       "✗ Minúscula",
        "req-num-ok":        "✓ Número",
        "req-num-x":         "✗ Número",
        "req-sym-ok":        "✓ Símbolo",
        "req-sym-x":         "✗ Símbolo",
        # Advertencia en la pantalla de selección de idioma
        "lang-warning":      "⚠  Solo paquete de idioma · Los mirrors están optimizados para SV, US, MX y GT "
                             "— las descargas pueden ser lentas para China continental o regiones "
                             "alejadas de estos países.",
    },

    # ── 中文简体 ──────────────────────────────────────────────────────────────
    "zh": {
        "title":             "AvalOS — 安装程序",
        "topbar":            "● AvalOS 安装程序",
        "step-hint":         "选择磁盘并配置系统",

        "welcome-sub":       "Arch Linux · Hyprland · Wayland · Tokyo Night",
        "welcome-desc":      "欢迎使用 <strong>AvalOS</strong> 安装程序。<br>"
                             "此向导将在您选择的磁盘上配置并安装系统。",
        "btn-start":         "开始安装 →",

        "sec-disk":          "▸ 目标磁盘",
        "sec-user":          "▸ 用户账户",
        "sec-host":          "▸ 计算机名",
        "sec-lang":          "▸ 语言与键盘",
        "sec-advanced":      "▸ 高级选项",

        "lbl-user":          "用户名",
        "lbl-pass":          "密码",
        "lbl-confirm-pass":  "确认密码",
        "lbl-show-hide":     "显示/隐藏",
        "lbl-hostname":      "主机名",
        "lbl-timezone":      "时区",
        "lbl-locale":        "区域设置",
        "lbl-keymap":        "键盘布局",
        "lbl-bootloader":    "引导程序",
        "lbl-install-type":  "安装类型",
        "lbl-extras":        "附加选项",

        "btn-install":       "▶ 安装 AvalOS",
        "btn-abort":         "⛔ 中止",
        "btn-retry":         "↺ 重试",
        "btn-reboot":        "⟳ 立即重启",
        "btn-close":         "关闭",

        "opt-no-boot":       "无引导程序",
        "opt-pc":            "💾 PC / HDD / SSD",
        "opt-usb":           "🔌 持久化 USB",
        "opt-pc-desc":       "Btrfs 子卷 — 自动快照，可从 GRUB 回滚。",
        "opt-usb-desc":      "ext4 无日志 + noatime — 最大限度减少对 U 盘的写入。",
        "opt-grub-desc":     "通用。BIOS + UEFI，双系统。启动时显示 Btrfs 快照菜单。",
        "chk-gaming-title":  "🎮 游戏",
        "chk-gaming-desc":   "Steam · Wine · DXVK · VKD3D · GameMode · MangoHUD · Lutris · Proton-GE（约 2.5 GB 额外空间）",
        "chk-bore-title":    "⚡ BORE 调度器",
        "chk-bore-desc":     "linux-avalos-bore 内核 — 游戏中响应更灵敏。需要支持 AVX2 的 CPU（x86-64-v3 及以上）；不支持时将被忽略，使用标准内核。",
        "opt-sdboot-desc":   "仅 UEFI，启动快。快照可通过终端使用，启动菜单无可视列表。",
        "opt-refind-desc":   "仅 UEFI。自动检测内核。快照需手动配置。",

        "log-title":         "▸ 安装日志",
        "cd-title":          "⚠ 不可回头点",
        "cd-desc":           "磁盘将被清空，此操作无法撤销。",
        "cd-confirm":        "确认并安装",
        "cd-cancel":         "取消",
        "err-title":         "⛔ 严重错误",
        "done-title":        "AvalOS 安装成功",
        "done-desc":         "请取出 USB 设备并重启电脑。SDDM 将提示登录 — 请选择 Hyprland。",

        # 验证消息
        "val-select-disk":   "请选择目标磁盘",
        "val-invalid-user":  "请输入有效的用户名（至少 2 个字符）",
        "val-min-user":      "最少 2 个字符，最多 32 个",
        "val-pass-short":    "密码至少需要 8 个字符",
        "val-pass-weak":     "密码过于简单 — 请添加大写字母、数字或符号",
        "val-pass-mismatch": "✗ 两次密码不一致",
        "val-pass-ok":       "✓ 密码一致",
        "val-reserved-user": "该用户名已被系统保留",
        "val-uefi-req":      "需要 UEFI，而此机器以 BIOS Legacy 模式启动。请使用 GRUB。",
        "val-uefi-warn":     "仅支持 UEFI。请确认您的电脑不是 BIOS Legacy 模式。",
        "warn-sdboot-snaps": "<b>⚠ systemd-boot — 快照无启动菜单</b><br>AvalOS 使用 <b>Btrfs + snapper</b> 进行自动快照（每次更新前后）。使用 systemd-boot 时，快照正常工作，可通过 <code>snapper rollback &lt;N&gt;</code> 从终端还原。<br><br><b>没有的功能</b>：像 GRUB 那样在启动菜单中显示快照列表。若系统无法启动，需使用 Live USB 进行回滚。<br><br>✦ 快照功能<b>完全可用</b> — 仅缺少启动菜单中的可视化列表。",
        "warn-refind-snaps": "<b>⚠ rEFInd — 快照需手动配置</b><br>AvalOS 使用 <b>Btrfs + snapper</b> 进行自动快照。使用 rEFInd 时，启动菜单中的快照条目<b>不会自动生成</b> — 每个快照都需手动添加到 <code>refind.conf</code>。<br><br><code>snapper rollback &lt;N&gt;</code> 可在终端中使用。如需启动菜单集成，需在安装后手动配置 rEFInd。<br><br>✦ 快照功能<b>完全可用</b> — 仅启动菜单集成需手动操作。",

        "status-error":      "出错 — 请查看日志或点击重试",
        "err-timeout":       "等待超时，请关闭并重新打开安装程序。",

        "step-uefi":         "检测启动模式",
        "step-uefi-d":       "UEFI / BIOS Legacy",
        "step-net":          "验证网络连接",
        "step-net-d":        "pacstrap 所需",
        "step-tools":        "验证工具",
        "step-tools-d":      "parted, mkfs, pacstrap…",
        "step-part":         "分区目标磁盘",
        "step-part-d":       "",
        "step-format":       "格式化分区",
        "step-format-d":     "FAT32 (EFI) + Btrfs (root)",
        "step-mount":        "挂载文件系统",
        "step-mount-d":      "",
        "step-mirrors":      "使用 reflector 优化镜像",
        "step-mirrors-d":    "选择最快的镜像源",
        "step-pacstrap":     "安装基础系统",
        "step-pacstrap-d":   "pacstrap — 可能需要几分钟",
        "step-fstab":        "生成 fstab",
        "step-fstab-d":      "",
        "step-config":       "配置系统",
        "step-config-d":     "locale · hostname · timezone · initramfs",
        "step-grub":         "安装引导程序",
        "step-grub-d":       "",
        "step-services":     "启用服务",
        "step-services-d":   "NetworkManager · bluetooth · SDDM",
        "step-user":         "创建系统用户",
        "step-user-d":       "",
        "step-aur":          "安装 AUR 包 (yay)",
        "step-aur-d":        "microsoft-edge-stable-bin",
        "step-hypr":         "配置 Hyprland + Wayland",
        "step-hypr-d":       "SDDM · Waybar · hyprland.lua",
        "step-umount":       "卸载并完成",
        "step-umount-d":     "",

        "ff-os":             " 系统",
        "ff-host":           "\uf0e4 主机",
        "ff-kernel":         " 内核",
        "ff-uptime":         "\uf55f 运行时间",
        "ff-packages":       "\uf439 软件包",
        "ff-shell":          " Shell",
        "ff-display":        "\uf879 分辨率",
        "ff-wm":             " WM",
        "ff-terminal":       " 终端",
        "ff-cpu":            " CPU",
        "ff-gpu":            "\uf43f GPU",
        "ff-ram":            "\uf55b 内存",
        "ff-disk":           "\uf4cb 磁盘",

        "pm-off":            "  关机",
        "pm-reboot":         "  重启",
        "pm-suspend":        "  睡眠",
        "pm-logout":         "󰍃  注销",
        "pm-lock":           "  锁屏",
        "pm-title":          "  电源",
        # SDDM 登录界面 (Main.qml) — 占位符复用 lbl-user/lbl-pass
        "sddm-signin":       "登录",
        "sddm-fail":         "认证失败，请重试。",
        "sddm-session":      "会话",
        "sddm-suspend":      "睡眠",
        "sddm-restart":      "重启",
        "sddm-shutdown":     "关机",
        # 密码要求清单（pg-config，实时验证）
        "req-len-ok":        "✓ 8+ 字符",
        "req-len-x":         "✗ 8+ 字符",
        "req-upper-ok":      "✓ 大写字母",
        "req-upper-x":       "✗ 大写字母",
        "req-lower-ok":      "✓ 小写字母",
        "req-lower-x":       "✗ 小写字母",
        "req-num-ok":        "✓ 数字",
        "req-num-x":         "✗ 数字",
        "req-sym-ok":        "✓ 符号",
        "req-sym-x":         "✗ 符号",
        # 语言选择页面警告
        "lang-warning":      "⚠  仅界面语言包 · 镜像源已针对萨尔瓦多、美国、墨西哥及危地马拉优化"
                             "——中国大陆及其他较远地区的下载速度可能较慢。",
    },
}


def t(key, lang="en"):
    # type: (str, str) -> str
    """Devuelve el string traducido para key en el idioma lang.
    Fallback: inglés → el propio key si no existe en ningún idioma.

    NOTA: usa comprobación explícita de None (no 'or') para distinguir
    string vacío '' (valor intencional — p.ej. claves step-*-d sin detail)
    de clave ausente (None). Con 'or', '' sería falsy y caería al fallback,
    devolviendo la clave cruda en lugar del string vacío esperado.
    """
    val = TRANSLATIONS.get(lang, {}).get(key)
    if val is not None:
        return val
    val = TRANSLATIONS["en"].get(key)
    if val is not None:
        return val
    return key


SUPPORTED_LANGS = [
    ("en", "English"),
    ("es", "Español"),
    ("zh", "中文简体"),
]

__all__ = ["TRANSLATIONS", "SUPPORTED_LANGS", "t"]
