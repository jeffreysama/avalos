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

    -- Cliphist: faltaba en el live por accidente (sí está en el template
    -- instalado). Sin esto, mod+V (agregado abajo) no tiene nada que listar.
    hl.exec_cmd("wl-paste --type text  --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")

    -- Instalador gráfico de AvalOS
    -- FIX: /usr/local/bin/avalos-install es un wrapper bash
    -- (#!/bin/bash; export PYTHONPATH=...; exec python3 .../skill_instalar_usb.py),
    -- no un script Python. "python3 /usr/local/bin/avalos-install" hacía que
    -- Python intentara parsear "export PYTHONPATH=..." → SyntaxError inmediato.
    -- Como hl.exec_cmd() es async, el resto del autostart seguía normal y el
    -- usuario llegaba a un escritorio funcional SIN ninguna ventana de
    -- instalador y sin keybind para lanzarlo manualmente. El wrapper ya es
    -- ejecutable (chmod 755, shebang #!/bin/bash) y está en PATH.
    hl.exec_cmd("avalos-install")
end)

-- ── Keybinds ──────────────────────────────────────────────────────
local mod = "SUPER"

-- Apps básicas
hl.bind(mod .. " + Return", hl.dsp.exec_cmd("kitty"))
hl.bind(mod .. " + Space",  hl.dsp.exec_cmd("rofi -show drun"))
hl.bind(mod .. " + E",        hl.dsp.exec_cmd("thunar"))
hl.bind(mod .. " + B",        hl.dsp.exec_cmd("firefox"))
hl.bind(mod .. " + SHIFT + B", hl.dsp.exec_cmd("microsoft-edge-stable"))
hl.bind(mod .. " + V",
        hl.dsp.exec_cmd("cliphist list | rofi -dmenu | cliphist decode | wl-copy"))

-- Gaming
hl.bind(mod .. " + S",        hl.dsp.exec_cmd("steam"))
hl.bind(mod .. " + P",        hl.dsp.exec_cmd("flatpak run com.heroicgameslauncher.hgl"))

-- Ventanas
hl.bind(mod .. " + Q", hl.dsp.window.close())
-- FIX: se quita mode="fullscreen" (valor no confirmado en ningún config
-- real revisado) — hl.dsp.window.fullscreen({action="toggle"}) sin mode
-- es el patrón confirmado funcionando en configs reales de Hyprland 0.56.
hl.bind(mod .. " + F", hl.dsp.window.fullscreen({ action = "toggle" }))
hl.bind(mod .. " + T", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + SHIFT + L",
    -- Sin guard, dos pulsaciones rápidas lanzarían 2 instancias de hyprlock
    -- superpuestas. Mismo patrón que hypridle.conf (lock_cmd / listener 600s).
    hl.dsp.exec_cmd("pidof hyprlock || hyprlock"))

-- Powermenu (con fallback a poweroff si el script no existe)
hl.bind(mod .. " + SHIFT + E",
    hl.dsp.exec_cmd("~/.config/rofi/scripts/powermenu.sh || systemctl poweroff"))

-- Foco — flechas y HJKL
-- FIX: hl.dsp.focus.move(...) no existe en la API real — 'focus' es una
-- función directa que toma {direction=...}, no una tabla con .move
-- adentro. Confirmado contra wiki.hypr.land/Configuring/Basics/Dispatchers.
hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))
hl.bind(mod .. " + H",     hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + L",     hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + K",     hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + J",     hl.dsp.focus({ direction = "down" }))

-- Mover ventanas
-- FIX: mismo problema que foco — window.move() toma {direction=...},
-- no un string suelto como "l"/"r"/"u"/"d".
hl.bind(mod .. " + SHIFT + left",  hl.dsp.window.move({ direction = "left" }))
hl.bind(mod .. " + SHIFT + right", hl.dsp.window.move({ direction = "right" }))
hl.bind(mod .. " + SHIFT + up",    hl.dsp.window.move({ direction = "up" }))
hl.bind(mod .. " + SHIFT + down",  hl.dsp.window.move({ direction = "down" }))

-- Redimensionar con teclado
-- FIX (3 bugs en uno): (1) el dispatcher es hl.dsp.window.resize, no
-- hl.dsp.resize suelto. (2) las claves son x/y, no dx/dy. (3) falta
-- relative=true — sin eso x/y se interpretan como tamaño ABSOLUTO en
-- píxeles, no como cuánto crecer/achicar. Confirmado contra
-- wiki.hypr.land/Configuring/Basics/Binds y forum.hypr.land.
hl.bind(mod .. " + CTRL + right", hl.dsp.window.resize({ x =  30, y =   0, relative = true }), { repeating = true })
hl.bind(mod .. " + CTRL + left",  hl.dsp.window.resize({ x = -30, y =   0, relative = true }), { repeating = true })
hl.bind(mod .. " + CTRL + up",    hl.dsp.window.resize({ x =   0, y = -30, relative = true }), { repeating = true })
hl.bind(mod .. " + CTRL + down",  hl.dsp.window.resize({ x =   0, y =  30, relative = true }), { repeating = true })

-- Workspaces — scroll con ratón y Tab
-- FIX: hl.dsp.workspace.relative() no existe. El patrón real (tomado
-- directo del hyprland.lua de ejemplo oficial de hyprwm/Hyprland) es
-- hl.dsp.focus({workspace="e+1"}) — "e" = salta solo a workspaces
-- existentes (con contenido), no a cualquier número vacío.
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))
hl.bind(mod .. " + Tab",        hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + SHIFT + Tab", hl.dsp.focus({ workspace = "e-1" }))

-- Workspaces 1–9
-- FIX: hl.dsp.workspace.go() no existe. El patrón real es
-- hl.dsp.focus({workspace=N}) — confirmado exacto contra el
-- hyprland.lua de ejemplo oficial (usa el número directo, sin
-- tostring(); Lua/Hyprland lo acepta como número o string por igual).
for i = 1, 9 do
    hl.bind(mod .. " + " .. i,
        hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. i,
        hl.dsp.window.move({ workspace = i }))
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
hl.bind("XF86AudioPlay",
    hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioNext",
    hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPrev",
    hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

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
hl.window_rule({
    match  = { class = "avalos-wallpaper" },
    float  = true,
    center = true,
    size   = { 1000, 700 },
})
