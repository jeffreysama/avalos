"""
system/optimize.py — instala los scripts propios de AvalOS (settings,
wallpaper, about, update, update-helper, store + su catálogo, .desktop,
polkit policies, ícono) y aplica el tuning de sistema (ZRAM, systemd-oomd,
sysctl, IO scheduler por tipo de disco, DNS-over-TLS).

Extraído de VentanaInstalador._configurar_optimizaciones en
skill_instalar_usb.py (líneas 2750-3042). Lógica y comentarios
explicativos sin cambios — incluye el razonamiento completo de por qué
cada polkit policy es propia (no la genérica de freedesktop), por qué el
catálogo de la store no lleva el prefijo scripts/, y por qué avalos-lang
existe aparte de LANG del sistema.

Nota: este método hace dos cosas bastante distintas (instalar los
binarios/assets propios de AvalOS, y tunear el sistema) que en el
monolito viven juntas por orden de ejecución, no por diseño. Se dejaron
juntas acá también — separarlas es un cambio de estructura, no una
extracción fiel, y no es lo que se pidió en esta pasada.

Cambios respecto al original (solo de forma, no de lógica):
- `self.X` → `session.X`
- `self._lang` → parámetro `lang`
- `self._install_gaming` / `self._install_bore` (leídos con getattr por si
  no existían todavía en __init__) → parámetros `install_gaming` /
  `install_bore`, con el mismo default False
- `disco_tipo` → `disk_type`
- todos los identificadores restantes → inglés
"""

from __future__ import annotations

import datetime

from avalos_installer.core.config import MOUNT_ROOT, read_config
from avalos_installer.core.session import InstallSession


def configure_optimizations(session: InstallSession, gpu_info: dict, cpu_arch: str,
                             disk_type: str, lang: str,
                             install_gaming: bool = False, install_bore: bool = False):
    """Configura ZRAM+zstd, systemd-oomd, BBR, IO scheduler, sysctl y binarios de sistema."""

    session.log(session.t("log-section-optimizations"), "step")

    _bin_dir = MOUNT_ROOT / "usr/local/bin"
    _bin_dir.mkdir(parents=True, exist_ok=True)
    _gpu_env_bin = _bin_dir / "avalos-gpu-env"
    _gpu_env_bin.write_text(
        "#!/bin/bash\n"
        "# AvalOS: detecta GPU y actualiza el bloque hl.env(...) de hyprland.lua\n"
        "# para cada usuario, entre los marcadores AVALOS_GPU_ENV_START/END.\n"
        "set -uo pipefail\n\n"
        "if lspci 2>/dev/null | grep -qiE 'amd|radeon|amdgpu'; then\n"
        "    GPU_BLOCK='hl.env(\"AMD_VULKAN_ICD\",    \"RADV\")\n"
        "hl.env(\"VDPAU_DRIVER\",      \"radeonsi\")\n"
        "hl.env(\"LIBVA_DRIVER_NAME\", \"radeonsi\")'\n"
        "elif lspci 2>/dev/null | grep -qiE 'intel.*(graphics|vga|display)'; then\n"
        "    GPU_BLOCK='hl.env(\"LIBVA_DRIVER_NAME\", \"iHD\")\n"
        "hl.env(\"VDPAU_DRIVER\",      \"va_gl\")'\n"
        "else\n"
        "    # GPU desconocida: no tocar hyprland.lua, dejar el bloque existente.\n"
        "    exit 0\n"
        "fi\n\n"
        "for hypr_conf in /home/*/.config/hypr/hyprland.lua; do\n"
        "    [[ -f \"$hypr_conf\" ]] || continue\n"
        "    if ! grep -q 'AVALOS_GPU_ENV_START' \"$hypr_conf\"; then\n"
        "        # Marcadores no presentes (instalación antigua o editados por\n"
        "        # el usuario) — no reemplazar a ciegas, evitar corromper el archivo.\n"
        "        continue\n"
        "    fi\n"
        "    # BUG-FIX (permission denied en hyprland.lua tras cada boot):\n"
        "    # owner/modo se leian DESPUES del mv (ver git blame), o sea del\n"
        "    # archivo temporal de mktemp (root:root, 0600 -- este script\n"
        "    # corre como root via avalos-gpu-detect.service, Before=sddm),\n"
        "    # no del hyprland.lua original del usuario. El chown de mas\n"
        "    # abajo terminaba re-confirmando root:root en vez de restaurar\n"
        "    # al usuario real, y el modo 0600 de mktemp quedaba puesto. Con\n"
        "    # este servicio corriendo ANTES de sddm en cada arranque,\n"
        "    # hyprland.lua del usuario quedaba root:root justo antes de que\n"
        "    # el usuario pudiera loguearse -- exactamente 'Permission\n"
        "    # denied' al abrir su propio config (y por eso Hyprland caia a\n"
        "    # sus colores/tema por defecto: nunca llegaba a leer el archivo\n"
        "    # con Tokyo Night). Fix: capturar owner Y modo ANTES de pisar\n"
        "    # el archivo, restaurar los dos despues del mv.\n"
        "    owner=\"$(stat -c '%U:%G' \"$hypr_conf\")\"\n"
        "    mode=\"$(stat -c '%a' \"$hypr_conf\")\"\n"
        "    tmp=\"$(mktemp)\"\n"
        "    awk -v block=\"$GPU_BLOCK\" '\n"
        "        /-- AVALOS_GPU_ENV_START/ { print; print block; skip=1; next }\n"
        "        /-- AVALOS_GPU_ENV_END/   { skip=0; print; next }\n"
        "        skip { next }\n"
        "        { print }\n"
        "    ' \"$hypr_conf\" > \"$tmp\" && mv \"$tmp\" \"$hypr_conf\"\n"
        "    chown \"$owner\" \"$hypr_conf\"\n"
        "    chmod \"$mode\" \"$hypr_conf\"\n"
        "done\n"
    )
    _gpu_env_bin.chmod(0o755)
    session.log(session.t("log-gpu-env-installed"), "ok")

    session.log(session.t("log-installing-scripts"), "info")
    _avalos_scripts = ("avalos-settings", "avalos-wallpaper", "avalos-about",
                       "avalos-update", "avalos-update-helper", "avalos-store")
    for _script_name in _avalos_scripts:
        _content = read_config(f"scripts/{_script_name}")
        if _content:
            _script_path = _bin_dir / _script_name
            _script_path.write_text(_content, encoding="utf-8")
            _script_path.chmod(0o755)
            session.log(session.t("log-script-installed", script=_script_name), "ok")
        else:
            session.log(session.t("log-script-missing", script=_script_name), "warn")

    # Comprobación final: si algún script no quedó en /usr/local/bin, que el log lo diga
    # con nombre en vez de que "no se instaló" se descubra al buscar la app.
    _scripts_faltantes = [n for n in _avalos_scripts if not (_bin_dir / n).is_file()]
    if _scripts_faltantes:
        session.log(session.t("log-scripts-incomplete", names=", ".join(_scripts_faltantes)), "err")

    # avalos-store necesita su catálogo de apps aparte — no es un script
    # ejecutable, es data, así que va directo a configs/ (sin el prefijo
    # "scripts/" que usan los .desktop por el bug histórico de abajo) y
    # sin chmod 755.
    _content = read_config("avalos-store-catalog.json")
    if _content:
        (_bin_dir / "avalos-store-catalog.json").write_text(_content, encoding="utf-8")
        session.log(session.t("log-script-installed", script="avalos-store-catalog.json"), "ok")
    else:
        session.log(session.t("log-script-missing", script="avalos-store-catalog.json"), "warn")

    _apps_dir = MOUNT_ROOT / "usr" / "share" / "applications"
    _apps_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("scripts/avalos-settings.desktop")
    if _content:
        (_apps_dir / "avalos-settings.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-settings-desktop-installed"), "ok")
    else:
        session.log(session.t("log-settings-desktop-missing"), "warn")

    _content = read_config("scripts/avalos-store.desktop")
    if _content:
        (_apps_dir / "avalos-store.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-store-desktop-installed"), "ok")
    else:
        session.log(session.t("log-store-desktop-missing"), "warn")

    # avalos-update no tenía entrada de escritorio: el script se instalaba en
    # /usr/local/bin pero no aparecía en rofi (drun) ni en ningún menú, así que
    # para el usuario "no estaba instalado".
    _content = read_config("avalos-update.desktop")
    if _content:
        (_apps_dir / "avalos-update.desktop").write_text(_content, encoding="utf-8")
        session.log(session.t("log-update-desktop-installed"), "ok")
    else:
        session.log(session.t("log-update-desktop-missing"), "warn")

    # avalos-update necesita pkexec para elevar avalos-update-helper (ver
    # avalos-update.policy) — polkitd + hyprpolkitagent ya corren en el
    # sistema instalado (servicios habilitados / exec-once de Hyprland),
    # así que lo único que falta es que la acción exista donde polkit la
    # busca. 0644, NO ejecutable: polkitd solo necesita leerla.
    _polkit_dir = MOUNT_ROOT / "usr" / "share" / "polkit-1" / "actions"
    _polkit_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("avalos-update.policy")
    if _content:
        _policy_path = _polkit_dir / "com.avalos.update.policy"
        _policy_path.write_text(_content, encoding="utf-8")
        _policy_path.chmod(0o644)
        session.log(session.t("log-polkit-policy-installed"), "ok")
    else:
        session.log(session.t("log-polkit-policy-missing"), "warn")

    # avalos-store: mismo mecanismo de polkit que avalos-update (ver
    # comentario arriba), acción separada (com.avalos.store.policy) para
    # que pkexec pacman -S/-R dentro de avalos-store recuerde la sesión
    # (auth_admin_keep) y muestre mensaje/ícono propios de AvalOS, en vez
    # de caer en la acción genérica org.freedesktop.policykit.exec (sin
    # policy dedicada, pkexec pide contraseña en CADA instalación/
    # desinstalación de la Store, sin recordar nada entre una app y la
    # siguiente — ver avalos-store.policy para el detalle completo).
    _content = read_config("avalos-store.policy")
    if _content:
        _policy_path = _polkit_dir / "com.avalos.store.policy"
        _policy_path.write_text(_content, encoding="utf-8")
        _policy_path.chmod(0o644)
        session.log(session.t("log-store-polkit-policy-installed"), "ok")
    else:
        session.log(session.t("log-store-polkit-policy-missing"), "warn")

    # Ícono de avalos-store en el theme hicolor del sistema, para que
    # Icon=avalos-store (en avalos-store.desktop) resuelva a algo real en
    # vez de caer al ícono genérico de "aplicación desconocida" — mismo
    # spec que ya usa el propio avalos-store para resolver íconos de
    # terceros (_HICOLOR_ROOTS/_HICOLOR_SIZES), aplicado ahora a sí mismo.
    # scalable/ porque es un SVG: un solo archivo cubre todos los tamaños
    # que el spec de FreeDesktop Icon Theme pida, sin necesidad de
    # generar rasters en 48/64/128/256 aparte.
    _icon_dir = MOUNT_ROOT / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    _icon_dir.mkdir(parents=True, exist_ok=True)
    _content = read_config("avalos-store.svg")
    if _content:
        (_icon_dir / "avalos-store.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-store-icon-installed"), "ok")
    else:
        session.log(session.t("log-store-icon-missing"), "warn")

    _content = read_config("avalos-update.svg")
    if _content:
        (_icon_dir / "avalos-update.svg").write_text(_content, encoding="utf-8")
        session.log(session.t("log-update-icon-installed"), "ok")
    else:
        session.log(session.t("log-update-icon-missing"), "warn")

    (MOUNT_ROOT / "etc" / "avalos-install-date").write_text(
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        encoding="utf-8"
    )

    # Idioma real de UI (en/es/zh/ja) elegido en el instalador, para que
    # apps del sistema (avalos-wallpaper, avalos-settings, futuras apps)
    # lo lean directo sin tener que adivinarlo mal desde LANG (que es el
    # locale REGIONAL — es_MX/es_AR/pt_BR/etc, un valor totalmente
    # distinto al idioma de traducción de la UI, y ni siquiera cubre
    # los 4 idiomas soportados: pt_BR o fr_FR no tienen equivalente acá).
    (MOUNT_ROOT / "etc" / "avalos-lang").write_text(
        lang + "\n",
        encoding="utf-8"
    )

    # Perfil de instalación (gaming/bore) para que herramientas
    # post-instalación (avalos-store) sepan qué eligió el usuario acá
    # sin tener que re-detectarlo. Una flag por línea, solo las que
    # quedaron en True — mismo espíritu que avalos-lang: un archivo,
    # una fuente de verdad, nada de parsear config compartida.
    _profile_flags = []
    if install_gaming:
        _profile_flags.append("gaming")
    if install_bore:
        _profile_flags.append("bore")
    (MOUNT_ROOT / "etc" / "avalos-profile").write_text(
        ("\n".join(_profile_flags) + "\n") if _profile_flags else "",
        encoding="utf-8"
    )

    zram_path = MOUNT_ROOT / "etc" / "systemd" / "zram-generator.conf"
    zram_path.parent.mkdir(parents=True, exist_ok=True)
    zram_path.write_text(
        "[zram0]\n"
        "# ZRAM: swap comprimido en RAM — AvalOS\n"
        "# Limita a min(RAM_total/2, 8GB) — estándar zram-generator\n"
        "zram-size = min(ram / 2, 8192)\n"
        "compression-algorithm = zstd\n"
        "swap-priority = 100\n"
    )
    session.log(session.t("log-zram-ok"), "ok")

    oomd_conf = MOUNT_ROOT / "etc" / "systemd" / "oomd.conf"
    oomd_conf.write_text(
        "[OOM]\n"
        "# Mata procesos cuando la presión de swap supera el 85%\n"
        "SwapUsedLimit=85%\n"
        "# o cuando la presión de memoria supera el 70% por más de 10s\n"
        "DefaultMemoryPressureLimit=70%\n"
        "DefaultMemoryPressureDurationSec=10s\n"
    )
    session.run_chroot(["systemctl", "enable", "systemd-oomd"])
    session.log(session.t("log-oomd-ok"), "ok")

    sysctl_dir = MOUNT_ROOT / "etc" / "sysctl.d"
    sysctl_dir.mkdir(parents=True, exist_ok=True)

    (sysctl_dir / "80-avalos-memory.conf").write_text(
        "# AvalOS: memory tuning (conservador, medido)\n"
        "# Reduce agresividad de swap (ZRAM lo maneja)\n"
        "vm.swappiness = 10\n"
        "# Cache de VFS: más agresivo en retener inodos/dentries\n"
        "vm.vfs_cache_pressure = 50\n"
        "# Dirty pages: escribir antes de que sea urgente\n"
        "vm.dirty_ratio = 10\n"
        "vm.dirty_background_ratio = 5\n"
        "# Tiempo máximo de dirty pages antes de flush\n"
        "vm.dirty_expire_centisecs = 3000\n"
        "vm.dirty_writeback_centisecs = 500\n"
    )
    session.log(session.t("log-sysctl-mem-ok"), "ok")

    (sysctl_dir / "81-avalos-bbr.conf").write_text(
        "# AvalOS: BBR congestion control (mainline desde Linux 4.9, muy estable)\n"
        "# FQ como qdisc (requerido por BBR)\n"
        "net.core.default_qdisc = fq\n"
        "# BBR: mejor throughput y latencia que CUBIC\n"
        "net.ipv4.tcp_congestion_control = bbr\n"
        "# Buffers de red razonables\n"
        "net.core.rmem_max = 16777216\n"
        "net.core.wmem_max = 16777216\n"
        "net.ipv4.tcp_rmem = 4096 87380 16777216\n"
        "net.ipv4.tcp_wmem = 4096 65536 16777216\n"
    )
    session.log("  BBR: net.ipv4.tcp_congestion_control=bbr + fq", "ok")

    (sysctl_dir / "82-avalos-security.conf").write_text(
        "# AvalOS: seguridad mínima razonable\n"
        "kernel.dmesg_restrict = 1\n"
        "kernel.kptr_restrict = 1\n"
        "net.ipv4.conf.default.rp_filter = 1\n"
        "net.ipv4.conf.all.rp_filter = 1\n"
    )
    session.log(session.t("log-sysctl-security-ok"), "ok")

    udev_dir = MOUNT_ROOT / "etc" / "udev" / "rules.d"
    udev_dir.mkdir(parents=True, exist_ok=True)
    (udev_dir / "60-avalos-iosched.rules").write_text(
        '# AvalOS: IO scheduler automático por tipo de disco\n'
        '# HDD → bfq  (justo, buena latencia interactiva)\n'
        'ACTION=="add|change", KERNEL=="sd[a-z]*", '
        'ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"\n'
        '# SSD SATA → mq-deadline  (simple, baja latencia)\n'
        'ACTION=="add|change", KERNEL=="sd[a-z]*", '
        'ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"\n'
        '# NVMe → kyber  (diseñado para baja latencia NVMe)\n'
        'ACTION=="add|change", KERNEL=="nvme[0-9n]*", '
        'ATTR{queue/scheduler}="kyber"\n'
        '# eMMC → mq-deadline\n'
        'ACTION=="add|change", KERNEL=="mmcblk[0-9]*", '
        'ATTR{queue/scheduler}="mq-deadline"\n'
    )
    session.log(session.t("log-io-scheduler", disco_tipo=disk_type), "ok")

    # FIX: el bloque DNS-over-TLS vivía acá mismo, corriendo ANTES de
    # create_user()/configure_repos()/install_aur() en el orden real del
    # orquestador (configure_optimizations corre en la línea 291 de
    # core/install.py, install_aur en la 313 — antes, no después). Pisa
    # /etc/resolv.conf con un symlink a .../stub-resolv.conf, un archivo
    # que systemd-resolved recién genera cuando el servicio ARRANCA de
    # verdad — cosa que nunca pasa dentro de un chroot (systemctl enable
    # ahí abajo solo arma el symlink de habilitación para el próximo
    # boot real, no arranca nada). Resultado: desde acá en adelante,
    # CUALQUIER resolución DNS dentro del chroot queda rota — incluido
    # el 'git clone' de yay más adelante, que es exactamente el "Could
    # not resolve host: aur.archlinux.org" que se está viendo. Se saca
    # de acá y se llama aparte (ver enable_dns_over_tls) recién después
    # de install_aur(), para que todo lo que necesita red dentro del
    # chroot durante la instalación siga teniendo un resolv.conf que
    # funciona.

    session.log(
        session.t("log-summary-cpu-gpu-disk", cpu_arch=cpu_arch,
                   gpu_vendor=gpu_info["vendor"].upper(), gpu_model=gpu_info["model"],
                   disco_tipo=disk_type.upper()),
        "ok"
    )


def enable_dns_over_tls(session: InstallSession) -> None:
    """Configura systemd-resolved con DNS-over-TLS para el sistema instalado.

    Se llama DESPUÉS de install_aur() a propósito — ver el comentario
    en configure_optimizations() de por qué no puede ir antes.
    """
    resolved_conf = MOUNT_ROOT / "etc" / "systemd" / "resolved.conf"
    resolved_conf.write_text(
        "[Resolve]\n"
        "# AvalOS: DNS-over-TLS con Cloudflare + Google\n"
        "DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com "
        "8.8.8.8#dns.google 8.8.4.4#dns.google\n"
        "FallbackDNS=9.9.9.9#dns.quad9.net\n"
        "DNSOverTLS=yes\n"
        "DNSSEC=allow-downgrade\n"
        "Cache=yes\n"
        "DNSStubListener=yes\n"
    )

    try:
        (MOUNT_ROOT / "etc" / "resolv.conf").unlink(missing_ok=True)
        (MOUNT_ROOT / "etc" / "resolv.conf").symlink_to(
            "../run/systemd/resolve/stub-resolv.conf"
        )
    except OSError as e:
        session.log(session.t("log-resolvconf-fail", e=e), "warn")
    session.run_chroot(["systemctl", "enable", "systemd-resolved"])
    session.log("  DNS-over-TLS: systemd-resolved (Cloudflare + Google + Quad9)", "ok")
