"""
system/pacstrap.py — arma la lista de paquetes, resuelve qué variante de
kernel instalar, corre un preflight de disponibilidad (con recorte
automático de extras lib32- caídos y diálogo manual si hace falta), y
ejecuta pacstrap de verdad con reintento bajando el paralelismo de
descargas. Corresponde al paso "pacstrap" de _run_instalacion en
skill_instalar_usb.py (líneas 3922-4210).

Las listas de paquetes (BASE_PKGS, BTRFS_PKGS, HYPRLAND_PKGS, GAMING_PKGS,
etc.) se quedan acá porque es el único lugar que las consume hoy — si en
el futuro existe un profiles/gaming.py real con más lógica que solo la
lista de paquetes, GAMING_PKGS/GAMING_AUR_PKGS se mudan ahí. Por ahora,
moverlas hubiera sido reorganizar de más, no una extracción fiel.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`. La
llamada anidada `_pacman_disponible` del original pasa a ser una función
de módulo `_pacman_package_available`. Todos los identificadores → inglés.

Cambios posteriores (de lógica): se pide 'rofi' en vez del alias 'rofi-wayland'; 'grub-btrfs'
solo se instala con GRUB (ya solo se usaba ahí); y los dos
fatales que retornaban con el root ya montado (kernel sin repo / diálogo de mirror rechazado)
ahora llaman a clean_mounts(), como dice el docstring de run_pacstrap: sin eso el botón
"Reintentar" chocaba con los montajes del intento anterior en el chequeo de partition.py.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import time

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession, output_indicates_gpg_error

BASE_PKGS = [
    "base", "base-devel",
    # El desglose por vendor de linux-firmware (AMD/Intel/red/bluetooth, sin
    # NVIDIA) vive centralizado en el PKGBUILD de linux-avalos-firmware (repo
    # [avalos], pkgs/linux-avalos-firmware/PKGBUILD) en vez de duplicado acá
    # paquete por paquete — evita que esta lista y ese PKGBUILD diverjan con
    # el tiempo (ya pasó: esta lista no traía marvell/mellanox/qcom/qlogic/
    # nfp/liquidio que sí están en el PKGBUILD) y adopta automáticamente
    # cualquier ajuste futuro de Arch al desglose de vendors sin tener que
    # tocar el instalador. 'linux-avalos-firmware' provides+conflicts contra
    # el 'linux-firmware' oficial de Arch, así que nunca coexisten ambos.
    "linux-avalos-firmware",
    "sof-firmware",
    "grub", "efibootmgr", "os-prober", "ntfs-3g", "networkmanager", "nm-connection-editor", "wireless-regdb",
    "sudo", "bash", "bash-completion", "nano", "vim", "git", "curl", "wget", "htop",
    "python", "python-pip", "man-db", "man-pages", "less", "openssh",
    "zip", "unzip", "p7zip", "zram-generator",
    "reflector", "pacman-contrib", "xdg-utils", "udiskie",
    "fastfetch", "bat", "github-cli",
    "btrfs-progs",
]

BTRFS_PKGS = [
    "snapper",
    "snap-pac",
    "grub-btrfs",
    "inotify-tools",
]

HYPRLAND_PKGS = [
    "hyprland", "uwsm", "libnewt", "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk",
    # rofi 2.0+ ya trae el backend Wayland (antes era el paquete aparte 'rofi-wayland', que
    # Arch absorbió en 'rofi'). Se pide 'rofi' directo: si Arch retira el alias, 'rofi-wayland'
    # daría "target not found", que NO es lib32- y por eso no se recorta solo: bloquearía
    # TODAS las instalaciones en el preflight.
    "xdg-user-dirs", "kitty", "waybar", "rofi", "mako",
    "hyprpaper", "hyprlock", "hypridle", "hyprpicker",
    "grim", "slurp", "wl-clipboard", "cliphist",
    "pipewire", "pipewire-alsa", "pipewire-pulse", "pipewire-jack",
    "wireplumber", "pavucontrol",
    "qt5-quickcontrols2",
    "qt5-wayland", "qt6-wayland", "gtk3", "gtk4", "hyprpolkitagent",
    "thunar", "gvfs", "brightnessctl",
    "ttf-font-awesome", "ttf-jetbrains-mono-nerd", "ttf-nerd-fonts-symbols",
    "noto-fonts", "noto-fonts-emoji", "noto-fonts-cjk",
    "sddm", "network-manager-applet", "blueman",
    "playerctl", "firefox", "bluez", "bluez-utils", "libnotify", "sound-theme-freedesktop",
    "file-roller", "thunar-archive-plugin", "thunar-volman",
    "gvfs-mtp", "gvfs-smb", "nwg-look", "nwg-displays", "papirus-icon-theme",
    "lm_sensors", "acpi", "capitaine-cursors",
    "python-pywebview", "python-gobject", "webkit2gtk-4.1",
    # archlinux-appstream-data: catálogo oficial de metadata AppStream de los
    # repos [core]/[extra]/[multilib], con los íconos reales (48/64/128px) de
    # la inmensa mayoría de paquetes empaquetados — no es dependencia de
    # pywebview, es lo que avalos-store usa para mostrar el ícono REAL de una
    # app en la tarjeta ANTES de instalarla (sin esto, apps sin flathub_id en
    # el catálogo solo muestran su ícono real una vez ya instaladas, porque
    # ahí sí lo trae el propio paquete en /usr/share/icons/hicolor/).
    "archlinux-appstream-data",
    # hicolor-icon-theme: casi con certeza llega igual como dependencia
    # transitiva de gtk3/gtk4 (ya en esta lista), pero se deja explícito acá
    # porque es la pieza de la que depende directamente que el propio ícono
    # de avalos-store.svg (instalado por el instalador en hicolor/scalable/
    # apps/) resuelva en el theme — 55KB, sin costo real, sin dejarlo librado
    # a una dependencia transitiva sin confirmar contra el .PKGINFO real.
    "hicolor-icon-theme",
]

HYPRLAND_AUR_PKGS: list[str] = []

GAMING_PKGS = [
    "steam",
    "wine-staging",
    "wine-gecko", "wine-mono",
    "winetricks",
    "lib32-gnutls", "lib32-libpulse", "lib32-alsa-plugins",
    "lib32-libx11", "lib32-libxext", "lib32-libxcomposite",
    "lib32-libxrandr", "lib32-libxinerama", "lib32-libxi",
    "lib32-sdl2-compat", "lib32-freetype2",
    "lib32-gst-plugins-base-libs",
    "vkd3d",
    "gamemode", "lib32-gamemode",
    "mangohud", "lib32-mangohud",
    "lutris",
    "flatpak",
    "lib32-pipewire",
    "gst-plugins-bad", "gst-plugins-ugly", "gst-libav",
]

GAMING_AUR_PKGS = [
    "proton-ge-custom-bin",
    "heroic-games-launcher-bin",
]


def _pacman_package_available(session: InstallSession, pkg: str,
                               attempts: int = 4, wait: int = 6) -> bool:
    last_output = ""
    for i in range(attempts):
        cmd = ["pacman", "-Syi" if i == 0 else "-Syyi", "--noconfirm", pkg]
        rc, last_output = session.run_cmd(cmd, timeout=25, log_cls="info")
        if rc == 0:
            return True
        if i < attempts - 1:
            session.log(
                session.t("log-kernel-retry", pkg=pkg, intento=i + 2, total=attempts), "warn"
            )
            time.sleep(wait)
    if output_indicates_gpg_error(last_output):
        session.log(session.t("log-pacman-gpg-signature-issue"), "err")
    return False


# Índices ya sincronizados del live (pacman -Sy los deja acá).
LIVE_PACMAN_DBPATH = "/var/lib/pacman"

# Tres formas de «esta dependencia no tiene salida» (pacman 6): sin base local previa, con un
# paquete que la rompe, y la advertencia de resolución cuando la dependencia lleva versión.
_DEP_CONFLICT_RE = re.compile(
    r"unable to satisfy dependency '[^']+' required by (?P<a>\S+)"
    r"|installing \S+ \([^)]+\) breaks dependency '[^']+' required by (?P<b>\S+)"
    r'|cannot resolve "[^"]*[<>=][^"]*", a dependency of "(?P<c>[^"]+)"'
)


def _make_preflight_dbpath() -> str | None:
    """Base de datos local VACÍA para el preflight, con los índices (sync) del live.

    pacstrap instala en un root nuevo, o sea con la base local vacía: el preflight tiene que
    resolver contra lo mismo. Con la base local del live, lo que ya trae la ISO (lib32-mesa y
    con él lib32-libelf...) cuenta como instalado y pacman contesta «installing libelf
    (0.197-1) breaks dependency 'libelf=0.196' required by lib32-libelf» por un paquete del
    LIVE: quitar paquetes de la lista del destino no lo arregla nunca (reproducido con pacman
    6.0.2) y el diálogo de mirror reaparecía. Devuelve None si no se pudo armar y el preflight
    sigue como antes, contra la base del live."""
    sync = os.path.join(LIVE_PACMAN_DBPATH, "sync")
    if not os.path.isdir(sync):
        return None
    path = None
    try:
        path = tempfile.mkdtemp(prefix="avalos-preflight-")
        os.makedirs(os.path.join(path, "local"))
        os.symlink(sync, os.path.join(path, "sync"))
    except OSError:
        if path:
            shutil.rmtree(path, ignore_errors=True)
        return None
    return path


def dependency_conflict_packages(output: str) -> list[str]:
    """Paquetes que pacman señala por una dependencia que no se puede satisfacer, en orden de
    aparición y sin repetir. Cubre «unable to satisfy dependency 'X' required by P», «installing
    Y (v) breaks dependency 'X' required by P» y «cannot resolve "X>=v", a dependency of "P"»
    (este último solo si la dependencia lleva versión: sin versión es un paquete que no existe y
    lo trata el recorte de «target not found»)."""
    found: list[str] = []
    for m in _DEP_CONFLICT_RE.finditer(output):
        name = m.group("a") or m.group("b") or m.group("c")
        if name and name not in found:
            found.append(name)
    return found


def _sync_repos(pacman_conf: str, dbpath: str | None, names: list[str]) -> dict[str, str]:
    """{paquete: repo} según los índices sincronizados (pacman -Si). Lo que pacman no conoce
    no aparece. LC_ALL=C: los nombres de los campos se traducen con el locale."""
    if not names:
        return {}
    cmd = ["pacman", "-Si", "--config", pacman_conf] + (["--dbpath", dbpath] if dbpath else []) + names
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return {}
    repos: dict[str, str] = {}
    repo = None
    for line in res.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Repository":
            repo = value
        elif key == "Name" and repo:
            repos[value] = repo
            repo = None
    return repos


def multilib_desync_culprits(pacman_conf: str, dbpath: str | None, output: str,
                             pkgs: list[str]) -> list[str]:
    """Paquetes de NUESTRA lista que están en multilib y que pacman señala como imposibles de
    instalar. Con la base local vacía pacman lista toda la cadena de dependientes hasta los
    paquetes explícitos (lib32-libelf ← lib32-llvm-libs ← lib32-mesa ← steam), así que alcanza
    con cruzar esa lista con `pkgs`."""
    implicated = dependency_conflict_packages(output)
    candidates = [p for p in pkgs if p in implicated]
    repos = _sync_repos(pacman_conf, dbpath, candidates)
    return [p for p in candidates if repos.get(p) == "multilib"]


def preflight_error_summary(output: str, limit: int = 400) -> str:
    """Lo que dijo pacman, sin la barra de progreso de curl (XferCommand) que ensuciaba el
    detalle del diálogo de mirror."""
    pieces = [ln.strip() for ln in re.split(r"[\r\n]+", output)]
    keep: list[str] = []
    for ln in pieces:
        if ln.startswith(("error:", "warning:", "::")) and ln not in keep:
            keep.append(ln)
    if not keep:
        keep = [ln for ln in pieces
                if re.search(r"[A-Za-z]{3}", ln) and not ln.startswith(("%", "Dload"))][-3:]
    text = " · ".join(keep) or output.strip()[-300:]
    return text if len(text) <= limit else text[:limit - 1] + "…"


def multilib_skipped_notice(session: InstallSession) -> str:
    """Bloque HTML para la pantalla final cuando multilib desincronizado obligó a omitir paquetes
    (steam, lib32-mesa...) y el usuario tiene que instalarlos después. Los omitidos por «target not
    found» no cuentan: no hay nada que instalar luego. Vacío si no hubo."""
    skipped = getattr(session, "multilib_skipped", None) or []
    if not skipped:
        return ""
    names = [html.escape(p) for p in skipped]
    return session.t("done-multilib-skipped", pkgs=", ".join(names), cmd=" ".join(names))


def _preflight_packages(session: InstallSession, pkgs: list[str],
                         pacman_conf_target: str) -> tuple[str, list[str]] | None:
    """Preflight de disponibilidad de la lista de paquetes: recorta lo que Arch tiene caído
    (extras lib32- que no existen, paquetes de multilib desincronizado) y, si falla otra cosa,
    deja decidir al usuario en el diálogo de mirror. Quita de `pkgs` (en el lugar) lo omitido.
    Devuelve (salida del preflight que pasó, paquetes omitidos), o None si hay que cortar
    (error ya reportado y clean_mounts() ya llamado)."""
    skipped_pkgs: list[str] = []
    desync_dropped: list[str] = []      # solo lo omitido por multilib desincronizado
    session.multilib_skipped = []
    pf_dbpath = _make_preflight_dbpath()
    pf_opts = ["--dbpath", pf_dbpath] if pf_dbpath else []
    try:
        while True:
            preflight_ok = False
            preflight_out = ""
            for preflight_attempt in range(3):
                pf_cmd = ["pacman", "-Sp" if preflight_attempt == 0 else "-Syyp",
                          "--config", pacman_conf_target, *pf_opts, "--noconfirm"] + pkgs
                pf_rc, preflight_out = session.run_cmd(pf_cmd, timeout=120, log_cls="info")
                if pf_rc == 0:
                    preflight_ok = True
                    break
                # Un conflicto de dependencias es determinista: refrescar los índices UNA vez
                # alcanza (un mirror rezagado sí puede arreglarlo); más vueltas con espera no.
                conflict = bool(dependency_conflict_packages(preflight_out))
                if conflict and preflight_attempt >= 1:
                    break
                if preflight_attempt < 2:
                    session.log(
                        session.t("log-kernel-retry", pkg="multilib",
                                   intento=preflight_attempt + 2, total=3), "warn"
                    )
                    if not conflict:
                        time.sleep(6)
            if preflight_ok:
                session.multilib_skipped = sorted(set(desync_dropped))
                return preflight_out, skipped_pkgs

            # Dos frases distintas de pacman para "esto no existe": 'target
            # not found: X' (típico cuando X está directo en nuestra lista)
            # y 'cannot resolve "X"' (visto en foros reales — CachyOS tuvo
            # este mismo lib32-gst-plugins-base-libs así en abr-may 2026).
            # Se capturan las dos para que el recorte de abajo no dependa
            # de cuál de las dos decida usar pacman.
            missing_pkgs = sorted(set(
                re.findall(r"target not found:\s*(\S+)", preflight_out)
                + re.findall(r'cannot resolve\s*"([^"]+)"', preflight_out)
            ))
            trimmable = [p for p in missing_pkgs if p.startswith("lib32-")]
            if trimmable and all(p in pkgs for p in trimmable):
                # Se puede recortar: son paquetes lib32- explícitos de
                # NUESTRA lista (no dependencias transitivas de otra
                # cosa), así que sacarlos es seguro y no deja nada a
                # medias. Visto en producción (hilo de CachyOS, abr-may
                # 2026, CVE en el stack multimedia lib32): Arch a veces
                # retira paquetes lib32-gst-*/lib32-sdl2* de multilib
                # entero por semanas mientras responde a un CVE — pasa
                # en TODOS los mirrors por igual, así que ni reintentar
                # ni cambiar de mirror lo arregla. Mejor seguir sin
                # ellos que bloquear toda la instalación por un extra
                # de compatibilidad.
                #
                # El recorte queda LIMITADO a lib32- a propósito: un
                # 'target not found' en linux-avalos-firmware, un
                # kernel, o cualquier otro paquete no-lib32 NUNCA se
                # auto-recorta en silencio — cae al diálogo de mirror
                # de abajo, porque faltar ahí sí deja un sistema roto
                # (sin firmware de hardware, sin kernel, etc), a
                # diferencia de un extra de compatibilidad multilib.
                for p in trimmable:
                    pkgs.remove(p)
                skipped_pkgs += trimmable
                session.log(
                    session.t("log-multilib-pkg-dropped", pkgs=", ".join(trimmable)), "warn"
                )
                continue

            # Multilib va detrás de core/extra: un lib32-X pide 'libelf=0.196' y el repo ya
            # publica 0.197 (visto en un cliente: «installing libelf (0.197-1) breaks dependency
            # 'libelf=0.196' required by lib32-libelf»). Pasa en TODOS los mirrors y se arregla
            # solo cuando Arch reconstruye lib32-X, así que reintentar o cambiar de mirror no
            # sirve; seguir sin los paquetes de multilib implicados sí. Solo se omiten paquetes
            # EXPLÍCITOS de NUESTRA lista que estén en multilib: nunca el kernel, el firmware ni
            # nada de core/extra, que cae al diálogo de abajo. Con la base local del live (sin
            # pf_dbpath) el error puede venir de un paquete de la ISO y omitir no lo arregla.
            desync = (multilib_desync_culprits(pacman_conf_target, pf_dbpath, preflight_out, pkgs)
                      if pf_dbpath else [])
            if desync:
                for p in desync:
                    pkgs.remove(p)
                skipped_pkgs += desync
                desync_dropped += desync
                session.log(
                    session.t("log-multilib-desync-dropped", pkgs=", ".join(desync),
                               causa=dependency_conflict_packages(preflight_out)[0]), "warn"
                )
                continue

            # Ya no hay más que recortar y sigue fallando — esto no es
            # "un par de extras caídos", puede ser el mirror/red. Aquí
            # sí conviene que decida el usuario.
            detail = ", ".join(missing_pkgs) if missing_pkgs else preflight_error_summary(preflight_out)
            session.mirror_dialog(detail)
            while not session._mirror_choice_event.wait(timeout=1.0):
                if session._aborted:
                    session.clean_mounts()
                    return None
            session._mirror_choice_event.clear()
            choice = session._mirror_choice
            session._mirror_choice = None
            if session._aborted:
                session.clean_mounts()
                return None
            if choice == "aceptar":
                session.log(session.t("log-mirror-broadening"), "info")
                session.run_cmd(
                    ["reflector", "--latest", "15", "--sort", "rate", "--protocol", "https",
                     "--save", "/etc/pacman.d/mirrorlist"], timeout=120
                )
            elif choice != "reintentar":
                # "rechazar" (o cierre inesperado del diálogo): el
                # usuario prefiere resolverlo por su cuenta — cortamos
                # con el mismo error claro de siempre y lo dejamos usar
                # el botón "Reintentar" global cuando esté listo.
                session.error_fatal(session.t("err-multilib-unreachable", detalle=detail))
                session.clean_mounts()  # el root ya está montado: sin esto "Reintentar" choca con /mnt
                return None
            # "reintentar": vuelve a probar tal cual, con los mismos mirrors

    finally:
        if pf_dbpath:
            shutil.rmtree(pf_dbpath, ignore_errors=True)


def run_pacstrap(session: InstallSession, ctx: InstallContext,
                  cpu_arch: str, gpu_info: dict, ucode: str) -> str | None:
    """Devuelve el nombre del paquete de kernel instalado (ej.
    "linux-avalos") si todo salió bien — lo necesita system/locale.py más
    adelante para saber qué .preset de mkinitcpio conservar — o None si
    falló (con error ya reportado y clean_mounts() ya llamado)."""
    session.step("pacstrap", "active")
    session.status(session.t("status-installing-base"))
    session.label(session.t("label-installing-base"))
    session.log("\n── pacstrap ──\n", "step")

    # El /etc/pacman.conf del live trae 'IgnorePkg = linux-avalos ...'
    # (protección contra 'pacman -S linux-avalos' accidental DENTRO
    # del live — ver build-iso.yml). pacstrap reusa /etc/pacman.conf
    # por defecto si no se le pasa -C, así que sin esta copia limpia
    # ese IgnorePkg queda activo también al pacstrapear MOUNT_ROOT (un
    # root distinto, sin ese riesgo) y linux-avalos deja de contar
    # como proveedor válido de la dependencia virtual 'linux' —
    # pacman cae de vuelta al 'linux' genérico de [core] para
    # satisfacerla. Copia SOLO para el pacstrap del target; el
    # /etc/pacman.conf real del live no se toca.
    pacman_conf_target = "/tmp/avalos_pacman_target.conf"
    try:
        with open("/etc/pacman.conf") as f_conf:
            conf_lines = [l for l in f_conf if not l.lstrip().startswith("IgnorePkg")]
        # 'failed retrieving file' aislado (paquetes grandes tipo
        # noto-fonts-cjk, linux-firmware-*) suele ser UN intento que
        # se corta — no necesariamente el mirror entero está mal.
        # pacman por sí solo no reintenta la MISMA descarga, solo
        # pasa al siguiente mirror. XferCommand delega la descarga a
        # curl, que sí reintenta la misma URL antes de rendirse.
        # Costo: pacman deja de paralelizar descargas (ParallelDownloads
        # se ignora con XferCommand activo) — aceptable acá, porque el
        # retry de más abajo YA asume que menos paralelismo ayuda en
        # conexiones inestables.
        for i_opt, l_opt in enumerate(conf_lines):
            if l_opt.strip() == "[options]":
                conf_lines.insert(
                    i_opt + 1,
                    "XferCommand = /usr/bin/curl -L -C - -f --retry 3 --retry-delay 3 "
                    "--connect-timeout 10 -o %o %u\n"
                )
                break
        with open(pacman_conf_target, "w") as f_conf:
            f_conf.writelines(conf_lines)
    except Exception as e:
        session.log(session.t("log-pacman-conf-target-error", e=e), "warn")
        pacman_conf_target = "/etc/pacman.conf"

    pkgs = list(BASE_PKGS)

    if not ctx.usb_mode:
        pkgs += BTRFS_PKGS
    if ctx.bootloader == 'sd-boot':
        pkgs = [p for p in pkgs if p not in {"grub", "os-prober"}]
    elif ctx.bootloader == 'refind':
        pkgs = [p for p in pkgs if p not in {"grub", "os-prober"}]
    elif ctx.bootloader == 'none':
        pkgs = [p for p in pkgs if p not in {"grub", "efibootmgr", "os-prober"}]
    if ctx.bootloader != 'grub':
        # grub-btrfs (servicio y hook de initramfs) solo se usa con GRUB: services.py y
        # locale.py ya lo condicionan al bootloader. Sin GRUB no hace nada y se instalaba igual.
        pkgs = [p for p in pkgs if p != "grub-btrfs"]

    is_v3_or_higher = cpu_arch in ("x86-64-v3", "x86-64-v4")
    cpu_level_name = "v3/v4 (AVX2+)" if is_v3_or_higher else "baseline (sin AVX2)"
    session.log(session.t("log-cpu-detected", cpu_arch=cpu_arch, nivel=cpu_level_name), "info")

    wants_bore = ctx.install_bore
    if wants_bore and not is_v3_or_higher:
        session.log(
            session.t("log-bore-not-supported", cpu_arch=cpu_arch), "warn"
        )
        wants_bore = False

    session.log(session.t("log-checking-kernel-repo"), "info")

    if wants_bore:
        target_kernel = "linux-avalos-bore"
        target_headers = "linux-avalos-bore-headers"
    elif is_v3_or_higher:
        target_kernel = "linux-avalos"
        target_headers = "linux-avalos-headers"
    else:
        target_kernel = "linux-avalos-compat"
        target_headers = "linux-avalos-compat-headers"

    kernel_pkg = None
    headers_pkg = None

    try:
        if _pacman_package_available(session, target_kernel):
            kernel_pkg, headers_pkg = target_kernel, target_headers
            session.log(session.t("log-kernel-available", kernel_pkg=kernel_pkg), "ok")

        elif wants_bore and _pacman_package_available(session, "linux-avalos"):
            # BORE no publicado — mismo nivel de CPU sin BORE es seguro
            # (mismo -march, solo cambia el scheduler).
            kernel_pkg, headers_pkg = "linux-avalos", "linux-avalos-headers"
            session.log(
                session.t("log-kernel-fallback-no-bore", target=target_kernel,
                           alt=kernel_pkg, cpu_arch=cpu_arch),
                "warn"
            )
        # Si el objetivo es avalos o avalos-compat y no está disponible,
        # NO cambiamos de nivel de CPU — instalar v3 sin AVX2 (o al revés)
        # puede no arrancar. Mejor bloquear con error claro que arriesgar
        # un sistema que no bootea o meter un kernel que no sea AvalOS.

    except Exception as e:
        session.log(session.t("log-kernel-repo-query-error", e=e), "warn")

    if not kernel_pkg:
        session.error_fatal(session.t("err-avalos-repo-unreachable", target=target_kernel))
        session.clean_mounts()  # el root ya está montado (mount_filesystems corre antes)
        return None

    pkgs += [kernel_pkg, headers_pkg]
    pkgs += gpu_info["pkgs"] + HYPRLAND_PKGS + ([ucode] if ucode else [])

    if ctx.install_gaming:
        pkgs += GAMING_PKGS
        session.log(session.t("log-gaming-enabled"), "ok")
    else:
        session.log(session.t("log-gaming-skipped"), "info")
    session.log(session.t("log-gpu-detected", gpu_vendor=gpu_info["vendor"].upper(),
                           drivers=", ".join(gpu_info["pkgs"][:3])), "info")
    session.log(session.t("log-total-packages", total=len(pkgs),
                           preview=", ".join(pkgs[:8]), extra=max(0, len(pkgs) - 8)), "info")

    session.log(session.t("log-checking-multilib"), "info")
    resolved = _preflight_packages(session, pkgs, pacman_conf_target)
    if resolved is None:
        return None
    preflight_out, skipped_pkgs = resolved

    if skipped_pkgs:
        session.log(
            session.t("log-multilib-pkgs-omitidos", pkgs=", ".join(sorted(set(skipped_pkgs)))),
            "warn"
        )

    # Guardia: 'linux'/'linux-headers' genéricos NUNCA deben aparecer
    # resueltos para pacstrap — si aparecen es que algo (una
    # dependencia sin 'provides' correcto en el PKGBUILD del kernel
    # avalos objetivo, un IgnorePkg mal alcanzando este pacman.conf,
    # etc) hizo que pacman los use para satisfacer 'linux' en vez de
    # kernel_pkg. Cortar acá evita gastar minutos bajando un kernel
    # de ~150MB que no queremos y que además suele fallar por mirror.
    intruder_kernels = sorted(set(re.findall(
        r"/(linux(?:-headers)?-\d[^/\s]*)-(?:x86_64|any)\.pkg\.tar", preflight_out
    )))
    if intruder_kernels:
        session.log(
            session.t("log-generic-kernel-detected", pkgs=", ".join(intruder_kernels),
                       target=kernel_pkg), "err"
        )
        session.error_fatal(session.t("err-generic-kernel-in-transaction",
                                       pkgs=", ".join(intruder_kernels)))
        session.clean_mounts()
        return None

    pacstrap_ok = False
    pacstrap_out = ""
    for parallel_downloads in (None, 2, 1):
        if session._aborted:
            session.clean_mounts()
            return None
        if parallel_downloads is not None:
            # Solo llegamos acá si el intento anterior falló con
            # "failed retrieving file" para TODOS/casi todos los
            # paquetes — eso, con el preflight de resolución ya
            # habiendo pasado antes, es la firma típica de una
            # conexión que no aguanta N descargas grandes en
            # paralelo (ParallelDownloads=5 por defecto). Bajar el
            # paralelismo no arregla un mirror caído, pero sí
            # arregla esto — que es lo que se vio en pruebas reales
            # (los .db, chicos, entraban bien; firefox/wine/firmware,
            # grandes, fallaban todos).
            session.run_cmd(
                ["sed", "-i", f"s/^ParallelDownloads.*/ParallelDownloads = {parallel_downloads}/",
                 pacman_conf_target], timeout=10
            )
            session.log(session.t("log-pacstrap-retry-slower", n=parallel_downloads), "warn")
        rc, pacstrap_out = session.run_cmd(
            ["pacstrap", "-C", pacman_conf_target, str(MOUNT_ROOT)] + pkgs,
            timeout=3600, log_cls="info"
        )
        if rc == 0:
            pacstrap_ok = True
            break
        if "failed retrieving file" not in pacstrap_out:
            # Otro tipo de fallo (disco lleno, permisos, etc) —
            # bajar el paralelismo no va a arreglar nada, no vale
            # la pena seguir reintentando.
            break

    if not pacstrap_ok:
        session.step("pacstrap", "error")
        session.error_step(session.t("err-pacstrap-failed"))
        session.clean_mounts()
        return None

    session.step("pacstrap", "done")
    return kernel_pkg
