"""
desktop/hyprland.py — configuración completa del escritorio (Hyprland,
SDDM, Waybar, Mako, Rofi, Kitty, GTK, fastfetch) del sistema recién
instalado.

Extraído de VentanaInstalador._configurar_hyprland en skill_instalar_usb.py
(líneas 3043-3332). Lógica y comentarios explicativos sin cambios — incluye
el fix de BUG-8 (separador QT_QPA_PLATFORM), el fallback de wallpaper
generado a mano si no hay uno embebido, y la nota sobre por qué se instala
tanto hyprland.desktop como hyprland-uwsm.desktop.

Cambios respecto al original (solo de forma, no de lógica):
- `self.X` → `session.X` (ver core/session.py — InstallSession)
- `self._keymap` → parámetro `keymap` (es config del usuario, no del
  session; hasta que exista InstallContext, el llamador pasa ctx.keymap)
- `self._lang` → parámetro `lang`, mismo motivo
- `_leer_config` (privada del monolito) → `read_config` (core.config)
- todos los identificadores restantes → inglés (usuario→user, etc.)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import translations

from avalos_installer.core.config import MOUNT_ROOT, read_config, VCONSOLE_TO_XKB
from avalos_installer.core.session import InstallSession


def configure_hyprland(session: InstallSession, user: str, gpu_info: dict,
                        keymap: str, lang: str):
    home = f"home/{user}"

    _gpu_vendor = gpu_info.get("vendor", "amd")
    if _gpu_vendor == "intel":
        _gpu_env = "LIBVA_DRIVER_NAME=iHD\nVDPAU_DRIVER=va_gl\n"
    else:
        _gpu_env = "VDPAU_DRIVER=radeonsi\nLIBVA_DRIVER_NAME=radeonsi\n"

    session.write_file("etc/environment", f"""\
# BUG-8 FIX: separador ':' en vez de ';' en QT_QPA_PLATFORM.
# Qt parsea esta variable como lista separada por ';' (no ':') de plugins
# de plataforma a probar en orden, con fallback al siguiente si el primero
# no carga. Con ':', Qt busca un plugin llamado literalmente "wayland:xcb",
# no lo encuentra, y cae a su comportamiento por defecto — rompiendo el
# fallback wayland→xcb para toda app Qt que lea /etc/environment (vía PAM/
# systemd), aunque hl.env() en hyprland.lua sí lo tenga bien con ';'.
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
{_gpu_env}__GLX_VENDOR_LIBRARY_NAME=mesa
""")

    _gpu_env_amd = ('hl.env("AMD_VULKAN_ICD",    "RADV")\n'
                    'hl.env("VDPAU_DRIVER",      "radeonsi")\n'
                    'hl.env("LIBVA_DRIVER_NAME", "radeonsi")')
    _gpu_env_intel = ('hl.env("LIBVA_DRIVER_NAME", "iHD")\n'
                       'hl.env("VDPAU_DRIVER",      "va_gl")')
    _gpu_env_body = _gpu_env_amd if _gpu_vendor == "amd" else _gpu_env_intel
    _gpu_env_str = (
        "-- AVALOS_GPU_ENV_START\n"
        f"{_gpu_env_body}\n"
        "-- AVALOS_GPU_ENV_END"
    )

    _hypr_tmpl = read_config("hyprland/hyprland_conf_lua.template")
    if _hypr_tmpl:
        session.write_file(f"{home}/.config/hypr/hyprland.lua",
                            _hypr_tmpl.replace("%%GPU_ENV%%", _gpu_env_str)
                            .replace("%%KEYMAP%%", VCONSOLE_TO_XKB.get(keymap, keymap)))
    else:
        session.log(session.t("log-hyprland-template-missing"), "err")
        raise RuntimeError(
            "hyprland_conf_lua.template no encontrado en /usr/share/avalos/configs/hyprland/.\n"
            "La imagen ISO está incompleta — reconstruye con build-iso.yml."
        )

    _content = read_config("hyprland/hyprpaper.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hyprpaper.conf", _content)
    else:
        session.write_file(f"{home}/.config/hypr/hyprpaper.conf",
                            "wallpaper {\n    monitor =\n"
                            "    path = ~/.config/hypr/wallpaper.png\n"
                            "    fit_mode = cover\n}\nsplash = false\nipc = on\n")

    wp_path = MOUNT_ROOT / f"{home}/.config/hypr/wallpaper.png"
    _default_wp = Path("/usr/share/avalos/wallpaper-default.png")
    try:
        if _default_wp.is_file():
            wp_path.write_bytes(_default_wp.read_bytes())
            session.log(session.t("log-wallpaper-copied"), "ok")
        else:
            import struct as _struct, zlib as _zlib

            def _make_chunk(tag, data):
                crc = _zlib.crc32(tag + data) & 0xffffffff
                return _struct.pack('>I', len(data)) + tag + data + _struct.pack('>I', crc)

            _w, _h, _r, _g, _b = 1920, 1080, 26, 27, 38
            _rows = (b'\x00' + bytes([_r, _g, _b]) * _w) * _h
            _png = (
                b'\x89PNG\r\n\x1a\n'
                + _make_chunk(b'IHDR', _struct.pack('>IIBBBBB', _w, _h, 8, 2, 0, 0, 0))
                + _make_chunk(b'IDAT', _zlib.compress(_rows, 9))
                + _make_chunk(b'IEND', b'')
            )
            wp_path.write_bytes(_png)
            session.log(session.t("log-wallpaper-fallback"), "warn")
    except Exception as _e:
        session.log(f"  [WARN] wallpaper: {_e}", "warn")

    _content = read_config("hyprland/hypridle.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hypridle.conf", _content)
    else:
        session.log(session.t("log-hypridle-missing"), "warn")

    _content = read_config("hyprland/hyprlock.conf")
    if _content:
        session.write_file(f"{home}/.config/hypr/hyprlock.conf", _content)
    else:
        session.log(session.t("log-hyprlock-missing"), "warn")

    _content = read_config("waybar/config.jsonc")
    if _content:
        session.write_file(f"{home}/.config/waybar/config.jsonc", _content)
    else:
        session.log(session.t("log-waybar-config-missing"), "warn")

    _content = read_config("waybar/style.css")
    if _content:
        session.write_file(f"{home}/.config/waybar/style.css", _content)
    else:
        session.log(session.t("log-waybar-style-missing"), "warn")

    _content = read_config("mako/config")
    if _content:
        session.write_file(f"{home}/.config/mako/config", _content)

    _content = read_config("rofi/config.rasi")
    if _content:
        session.write_file(f"{home}/.config/rofi/config.rasi", _content)

    _content = read_config("rofi/powermenu.sh")
    if _content:
        session.write_file(f"{home}/.config/rofi/scripts/powermenu.sh", _content)
    try:
        (MOUNT_ROOT / f"{home}/.config/rofi/scripts/powermenu.sh").chmod(0o755)
    except OSError as e:
        session.log(session.t("log-chmod-powermenu-fail", e=e), "warn")

    _content = read_config("kitty/kitty.conf")
    if _content:
        session.write_file(f"{home}/.config/kitty/kitty.conf", _content)

    _sddm_qml_tpl = read_config("sddm/Main.qml")
    _sddm_meta = read_config("sddm/metadata.desktop")
    if _sddm_qml_tpl and _sddm_meta:
        _sddm_translations = translations.TRANSLATIONS.get(lang, translations.TRANSLATIONS["en"])
        _sddm_qml = (_sddm_qml_tpl
                     .replace("%%SDDM_USER%%", _sddm_translations.get("lbl-user", "Username"))
                     .replace("%%SDDM_PASS%%", _sddm_translations.get("lbl-pass", "Password"))
                     .replace("%%SDDM_SIGNIN%%", _sddm_translations.get("sddm-signin", "Sign In"))
                     .replace("%%SDDM_FAIL%%", _sddm_translations.get("sddm-fail", "Authentication failed. Try again."))
                     .replace("%%SDDM_SESSION%%", _sddm_translations.get("sddm-session", "Session"))
                     .replace("%%SDDM_SUSPEND%%", _sddm_translations.get("sddm-suspend", "Suspend"))
                     .replace("%%SDDM_RESTART%%", _sddm_translations.get("sddm-restart", "Restart"))
                     .replace("%%SDDM_SHUTDOWN%%", _sddm_translations.get("sddm-shutdown", "Shutdown")))
        _sddm_dir = MOUNT_ROOT / "usr" / "share" / "sddm" / "themes" / "avalos"
        _sddm_dir.mkdir(parents=True, exist_ok=True)
        (_sddm_dir / "metadata.desktop").write_text(_sddm_meta, encoding="utf-8")
        (_sddm_dir / "Main.qml").write_text(_sddm_qml, encoding="utf-8")
        session.log(session.t("log-sddm-theme-installed"), "ok")
    else:
        # No deberia pasar nunca si build-iso.yml copio bien configs/ al
        # live (mismo mecanismo que ya usan kitty.conf, powermenu.sh,
        # etc. mas arriba) -- si aparece, es señal de que configs/sddm/
        # no llego al ISO, no de que el tema este mal.
        session.log("[WARN] configs/sddm/Main.qml o metadata.desktop no encontrados en /usr/share/avalos/configs — tema SDDM no instalado", "warn")

    session.write_file("etc/sddm.conf.d/hyprland.conf", """\
[Theme]
Current=avalos

[Wayland]
EnableHiDPI=true

[General]
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
""")

    session.write_file("usr/share/wayland-sessions/hyprland.desktop", """\
[Desktop Entry]
Name=Hyprland
Comment=An intelligent dynamic tiling Wayland compositor
Exec=Hyprland
Type=Application
""")

    # Sesion administrada por uwsm (Universal Wayland Session Manager):
    # sin esto, SDDM ejecuta el binario Hyprland pelado (arriba) y
    # Hyprland tira el warning "started without start-hyprland" -- desde
    # la 0.5x lo recomendado es siempre uwsm (session/env/autostart via
    # systemd, apagado limpio). "--" separa flags de uwsm del target;
    # "hyprland.desktop" (arriba) queda intacto como lo que uwsm resuelve
    # para saber que binario correr -- confirmado contra log real de
    # sddm (bbs.archlinux.org/viewtopic.php?id=307539): Session
    # ".../hyprland-uwsm.desktop" selected, command: "uwsm start --
    # hyprland.desktop".
    session.write_file("usr/share/wayland-sessions/hyprland-uwsm.desktop", """\
[Desktop Entry]
Name=Hyprland (uwsm)
Comment=An intelligent dynamic tiling Wayland compositor
Exec=uwsm start -- hyprland.desktop
Type=Application
""")

    _gtk_fallback = """\
[Settings]
gtk-theme-name = Adwaita-dark
gtk-icon-theme-name = Papirus-Dark
gtk-font-name = JetBrainsMono Nerd Font 11
gtk-cursor-theme-name = capitaine-cursors-dark
gtk-cursor-theme-size = 24
gtk-application-prefer-dark-theme = true
"""
    for gtk_ver in ("gtk-3.0", "gtk-4.0"):
        # Prioriza configs/gtk/settings.ini del repo (mismo patron que
        # hyprland/waybar/mako/etc mas arriba); si no existe todavia en
        # /usr/share/avalos/configs/gtk/, usa el default de siempre --
        # asi no se rompe nada aunque configs/gtk/ aun no este conectado.
        _gtk_content = read_config("gtk/settings.ini") or _gtk_fallback
        session.write_file(f"{home}/.config/{gtk_ver}/settings.ini", _gtk_content)

    bashrc_extra = """\

# ── AvalOS / Wayland ────────────────────────────────
export QT_QPA_PLATFORM=wayland
export MOZ_ENABLE_WAYLAND=1
export ELECTRON_OZONE_PLATFORM_HINT=auto
export XDG_SESSION_TYPE=wayland
"""
    bashrc_path = MOUNT_ROOT / f"{home}/.bashrc"
    try:
        existing = bashrc_path.read_text(encoding="utf-8") if bashrc_path.exists() else ""
        bashrc_path.write_text(existing + bashrc_extra, encoding="utf-8")
    except OSError as e:
        session.log(f"[WARN] .bashrc: {e}", "warn")

    _content = read_config("fastfetch/config.jsonc")
    if _content:
        _translations = translations.TRANSLATIONS.get(lang, translations.TRANSLATIONS["en"])
        _ff_keys = {
            '" OS"': f'"{_translations.get("ff-os", " OS")}"',
            '"\\uf0e4 Host"': f'"{_translations.get("ff-host", "\\uf0e4 Host")}"',
            '" Kernel"': f'"{_translations.get("ff-kernel", " Kernel")}"',
            '"\\uf55f Uptime"': f'"{_translations.get("ff-uptime", "\\uf55f Uptime")}"',
            '"\\uf439 Packages"': f'"{_translations.get("ff-packages", "\\uf439 Packages")}"',
            '" Shell"': f'"{_translations.get("ff-shell", " Shell")}"',
            '"\\uf879 Resolution"': f'"{_translations.get("ff-display", "\\uf879 Resolution")}"',
            '" WM"': f'"{_translations.get("ff-wm", " WM")}"',
            '" Terminal"': f'"{_translations.get("ff-terminal", " Terminal")}"',
            '" CPU"': f'"{_translations.get("ff-cpu", " CPU")}"',
            '"\\uf43f GPU"': f'"{_translations.get("ff-gpu", "\\uf43f GPU")}"',
            '"\\uf4cb Disk"': f'"{_translations.get("ff-disk", "\\uf4cb Disk")}"',
            '"\\uf55b RAM"': f'"{_translations.get("ff-ram", "\\uf55b RAM")}"',
        }
        for _old_k, _new_k in _ff_keys.items():
            _content = _content.replace(_old_k, _new_k)
        session.write_file(f"{home}/.config/fastfetch/config.jsonc", _content)

    _src_logo = Path("/etc/fastfetch/avalos.txt")
    _dst_logo = MOUNT_ROOT / "etc" / "fastfetch" / "avalos.txt"
    _dst_logo.parent.mkdir(parents=True, exist_ok=True)
    if _src_logo.exists():
        shutil.copy2(_src_logo, _dst_logo)
        session.log(session.t("log-fastfetch-logo-copied"))
    else:
        session.log(session.t("log-fastfetch-logo-missing"), "warn")

    session.chown_r(f"/home/{user}", user)

    ref_conf = MOUNT_ROOT / "etc" / "xdg" / "reflector" / "reflector.conf"
    ref_conf.parent.mkdir(parents=True, exist_ok=True)
    ref_conf.write_text("--country SV,US,MX,GT,JP\n--latest 10\n--sort rate\n--protocol https\n")
    session.run_chroot(["systemctl", "enable", "reflector.timer"])

    linger = MOUNT_ROOT / "etc/systemd/system/avalos-enable-linger.service"
    linger.parent.mkdir(parents=True, exist_ok=True)
    linger.write_text(f"""\
[Unit]
Description=Enable linger for {user} (PipeWire user services)
After=systemd-logind.service
ConditionPathExists=!/var/lib/systemd/linger/{user}

[Service]
Type=oneshot
ExecStart=/usr/bin/loginctl enable-linger {user}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
""")
    session.run_chroot(["systemctl", "enable", "avalos-enable-linger.service"])
    session.log(session.t("log-hyprland-ok"), "ok")
