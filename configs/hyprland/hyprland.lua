-- ── AvalOS Live — hyprland.lua ────────────────────────────────────
-- Config para el entorno LIVE del USB.
-- El sistema instalado usa hyprland_conf.lua.template (con GPU vars).
--
-- Requiere Hyprland >= 0.55 (API Lua).
-- El .conf anterior se conserva en hyprland.conf.bak durante la transición.
-- ──────────────────────────────────────────────────────────────────

-- ── Monitor ───────────────────────────────────────────────────────
hl.monitor({
    output   = "",          -- "" = cualquier monitor disponible
    mode     = "preferred",
    position = "auto",
    scale    = "auto",
})

-- ── Variables de entorno ──────────────────────────────────────────
-- NOTA: Si usas uwsm como lanzador, mueve QT_*, GDK_*, MOZ_* y
-- ELECTRON_* a ~/.config/uwsm/env en lugar de aquí.
-- Solo AQ_* y HYPR* van en ~/.config/uwsm/env-hyprland.
hl.env("XCURSOR_SIZE",                      "24")
hl.env("XCURSOR_THEME",                     "capitaine-cursors-dark")
hl.env("QT_QPA_PLATFORM",                   "wayland;xcb")
hl.env("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
hl.env("GDK_BACKEND",                       "wayland,x11")
hl.env("MOZ_ENABLE_WAYLAND",                "1")
hl.env("ELECTRON_OZONE_PLATFORM_HINT",      "auto")

-- ── Configuración principal ───────────────────────────────────────
hl.config({
    general = {
        gaps_in          = 5,
        gaps_out         = 10,
        border_size      = 2,
        col = {
            active_border   = { colors = { "rgba(7aa2f7ee)", "rgba(bb9af7ee)" }, angle = 45 },
            inactive_border = "rgba(414868aa)",
        },
        layout           = "dwindle",
        resize_on_border = true,
        allow_tearing    = false,   -- evita tearing en GPUs integradas en el live
    },

    decoration = {
        rounding         = 12,
        active_opacity   = 1.0,
        inactive_opacity = 0.75,
        blur = {
            enabled = true,
            size    = 4,
            passes  = 1,
        },
        shadow = {
            enabled      = true,
            range        = 12,
            render_power = 2,
            color        = "rgba(1a1b2660)",
        },
    },

    animations = {
        enabled = true,
    },

    dwindle = {
        preserve_split = true,
        -- pseudotile eliminado en 0.55
    },

    input = {
        kb_layout    = "latam",   -- layout Wayland correcto para Latinoamérica
        follow_mouse = 1,
        sensitivity  = 0,
        touchpad = {
            natural_scroll = false,
            tap_to_click   = true,
        },
    },

    misc = {
        force_default_wallpaper  = 0,
        disable_hyprland_logo    = true,   -- sin logo animado en el live
        disable_splash_rendering = true,
    },

    debug = {
        vfr = true,   -- Variable Frame Rate: movido de misc: a debug: en 0.55
    },
})

-- ── Animaciones ───────────────────────────────────────────────────
hl.curve("myBezier", { type = "bezier", points = { { 0.08, 0.9 }, { 0.1, 1.05 } } })

hl.animation({ leaf = "windows",    enabled = true, speed = 6, bezier = "myBezier" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 5, bezier = "default",  style = "popin 75%" })
hl.animation({ leaf = "border",     enabled = true, speed = 8, bezier = "default" })
hl.animation({ leaf = "fade",       enabled = true, speed = 6, bezier = "default" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 5, bezier = "default",  style = "slide" })

-- ── Autostart ─────────────────────────────────────────────────────
-- hl.exec_cmd() es asíncrono — no hace falta & al final.
-- NOTA: avalos-gpu-env se eliminó del live. Escribía gpu-env.conf en
-- formato hyprlang que este config Lua nunca carga. Mesa auto-detecta
-- la GPU sin vars explícitas; suficiente para el entorno live/instalador.
-- El sistema instalado tiene las vars de GPU bakeadas en hyprland.lua
-- vía %%GPU_ENV%% por el instalador.
-- Orden: hyprpaper ANTES que waybar (evita error de socket de Wayland).
hl.on("hyprland.start", function()
    -- Fondo de pantalla ANTES que waybar (evita error de socket)
    hl.exec_cmd("hyprpaper")

    -- Resto del entorno
    hl.exec_cmd("waybar")
    hl.exec_cmd("mako")
    hl.exec_cmd("hypridle")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("hyprpolkitagent")   -- necesario en live para diálogos de privilegios

    -- Instalador gráfico de AvalOS
    hl.exec_cmd("python3 /usr/local/bin/avalos-install")
end)

-- ── Keybinds ──────────────────────────────────────────────────────
local mod = "SUPER"

-- Apps básicas
hl.bind(mod .. " + Return", hl.dsp.exec_cmd("kitty"))
hl.bind(mod .. " + Space",  hl.dsp.exec_cmd("rofi -show drun"))

-- Ventanas
hl.bind(mod .. " + Q", hl.dsp.window.close())
hl.bind(mod .. " + F", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
hl.bind(mod .. " + T", hl.dsp.window.float({ action = "toggle" }))

-- Powermenu (con fallback a poweroff si el script no existe)
hl.bind(mod .. " + SHIFT + E",
    hl.dsp.exec_cmd("~/.config/rofi/scripts/powermenu.sh || systemctl poweroff"))

-- Foco — flechas y HJKL
hl.bind(mod .. " + left",  hl.dsp.focus.move("l"))
hl.bind(mod .. " + right", hl.dsp.focus.move("r"))
hl.bind(mod .. " + up",    hl.dsp.focus.move("u"))
hl.bind(mod .. " + down",  hl.dsp.focus.move("d"))
hl.bind(mod .. " + H",     hl.dsp.focus.move("l"))
hl.bind(mod .. " + L",     hl.dsp.focus.move("r"))
hl.bind(mod .. " + K",     hl.dsp.focus.move("u"))
hl.bind(mod .. " + J",     hl.dsp.focus.move("d"))

-- Mover ventanas
hl.bind(mod .. " + SHIFT + left",  hl.dsp.window.move("l"))
hl.bind(mod .. " + SHIFT + right", hl.dsp.window.move("r"))
hl.bind(mod .. " + SHIFT + up",    hl.dsp.window.move("u"))
hl.bind(mod .. " + SHIFT + down",  hl.dsp.window.move("d"))

-- Workspaces — scroll con ratón y Tab
hl.bind(mod .. " + mouse_down", hl.dsp.workspace.relative(1))
hl.bind(mod .. " + mouse_up",   hl.dsp.workspace.relative(-1))
hl.bind(mod .. " + Tab",        hl.dsp.workspace.relative(1))
hl.bind(mod .. " + SHIFT + Tab", hl.dsp.workspace.relative(-1))

-- Workspaces 1–9
for i = 1, 9 do
    hl.bind(mod .. " + " .. i,
        hl.dsp.workspace.go(tostring(i)))
    hl.bind(mod .. " + SHIFT + " .. i,
        hl.dsp.window.move({ workspace = tostring(i) }))
end

-- Captura de pantalla (útil en el live para documentar errores)
hl.bind("Print",
    hl.dsp.exec_cmd("grim ~/screenshot_$(date +%Y%m%d_%H%M%S).png"))
hl.bind(mod .. " + SHIFT + S",
    hl.dsp.exec_cmd('grim -g "$(slurp)" - | wl-copy'))

-- Audio (repeating = true para mantener pulsado)
hl.bind("XF86AudioRaiseVolume",
    hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+"),
    { repeating = true })
hl.bind("XF86AudioLowerVolume",
    hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),
    { repeating = true })
hl.bind("XF86AudioMute",
    hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),
    { locked = true })

-- Brillo (repeating = true para mantener pulsado)
hl.bind("XF86MonBrightnessUp",
    hl.dsp.exec_cmd("brightnessctl set +5%"),
    { repeating = true })
hl.bind("XF86MonBrightnessDown",
    hl.dsp.exec_cmd("brightnessctl set 5%-"),
    { repeating = true })

-- ── Window rules ──────────────────────────────────────────────────
-- El instalador (pywebview) debe aparecer flotante y centrado
hl.window_rule({
    match  = { class = "avalos-install" },
    float  = true,
    center = true,
    size   = { 1000, 700 },
})

hl.window_rule({ match = { class = "pavucontrol" },         float = true })
hl.window_rule({ match = { class = "nm-connection-editor" }, float = true })
