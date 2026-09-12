"""
system/locale.py — configuración regional (timezone, locale, keymap),
identidad del sistema (hostname, os-release, GRUB_DISTRIBUTOR), password
de root, y los hooks de mkinitcpio necesarios para arrancar sobre Btrfs
(+ grub-btrfs-overlayfs si el bootloader es GRUB). Corresponde al paso
"config" de _run_instalacion en skill_instalar_usb.py (líneas 4257-4459).

Dos comentarios originales se dejaron completos porque documentan bugs
sutiles ya resueltos: por qué os-release se escribe ANTES de grub (10_linux
de grub-mkconfig lo lee una sola vez al generar el menú), y por qué
GRUB_DISTRIBUTOR en /etc/default/grub —no os-release— es lo que realmente
controla el título "Arch Linux" que aparecía en el menú de GRUB.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`.
`kernel_pkg` (antes `self._kernel_pkg`, fijado durante pacstrap) se recibe
como parámetro — es el valor que ahora devuelve
system.pacstrap.run_pacstrap(). Todos los identificadores → inglés.
"""

from __future__ import annotations

import re

from avalos_installer.core.config import MOUNT_ROOT, VCONSOLE_TO_XKB, AVALOS_REPO
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession


def configure_locale(session: InstallSession, ctx: InstallContext, kernel_pkg: str) -> bool:
    session.step("config", "active")
    session.status(session.t("status-configuring-system"))
    session.log(session.t("log-section-system-config"), "step")

    session.run_chroot(["ln", "-sf", f"/usr/share/zoneinfo/{ctx.timezone}", "/etc/localtime"])
    session.run_chroot(["hwclock", "--systohc"])

    loc = ctx.locale
    loc_gen = f"{loc} UTF-8"
    keymap = ctx.keymap

    loc_gen_extra = "en_US.UTF-8 UTF-8"

    extra_locales = [loc_gen, loc_gen_extra]
    if loc.startswith("zh_") and "zh_CN.UTF-8 UTF-8" not in extra_locales:
        extra_locales.append("zh_CN.UTF-8 UTF-8")

    locale_gen_path = MOUNT_ROOT / "etc" / "locale.gen"
    if locale_gen_path.exists():
        txt = locale_gen_path.read_text()
        for loc_entry in extra_locales:
            txt = txt.replace(f"#{loc_entry}", loc_entry)
            txt = txt.replace(f"# {loc_entry}", loc_entry)
            if loc_entry not in txt:
                txt += f"\n{loc_entry}\n"
        locale_gen_path.write_text(txt)
    else:
        session.log(session.t("log-localegen-missing"), "warn")
        locale_gen_path.parent.mkdir(parents=True, exist_ok=True)
        locale_gen_path.write_text("\n".join(extra_locales) + "\n")

    # Antes esto se llamaba sin capturar rc/output: si locale-gen
    # fallaba (o generaba todo MENOS el locale pedido) quedaba en
    # silencio total -- nada en el log, nada en pantalla -- y recien
    # te enterabas con "setlocale: cannot change locale" ya en el
    # sistema instalado y arrancado, sin ninguna pista de a que paso
    # apuntar. El texto que arma loc_gen/extra_locales de arriba
    # ya se verifico a mano contra un locale.gen real de Arch y
    # contra locale-gen real (genera "es_SV.UTF-8... done" limpio),
    # asi que si esto llega a fallar en un run concreto el problema
    # esta en ESTE chroot puntual, no en la logica -- por eso vale
    # la pena verificar explicitamente en vez de asumir.
    rc_locgen, out_locgen = session.run_chroot(["locale-gen"])
    if rc_locgen != 0:
        session.log(session.t("log-localegen-failed", loc=loc, rc=rc_locgen,
                               out=out_locgen.strip()[-300:]), "err")
    else:
        rc_check, out_check = session.run_chroot(["locale", "-a"])
        loc_norm = loc.replace("-", "").lower()
        if loc_norm not in out_check.replace("-", "").lower():
            session.log(session.t("log-localegen-verify-fail", loc=loc,
                                   out=out_locgen.strip()[-300:]), "err")
        else:
            session.log(session.t("log-localegen-verify-ok", loc=loc), "ok")

    (MOUNT_ROOT / "etc" / "locale.conf").write_text(f"LANG={loc}\n")
    (MOUNT_ROOT / "etc" / "vconsole.conf").write_text(f"KEYMAP={keymap}\n")
    xkb_layout = VCONSOLE_TO_XKB.get(keymap, keymap)
    xorg_kbd_dir = MOUNT_ROOT / "etc" / "X11" / "xorg.conf.d"
    xorg_kbd_dir.mkdir(parents=True, exist_ok=True)
    (xorg_kbd_dir / "00-keyboard.conf").write_text(
        "Section \"InputClass\"\n"
        "    Identifier \"system-keyboard\"\n"
        "    MatchIsKeyboard \"yes\"\n"
        f"    Option \"XkbLayout\" \"{xkb_layout}\"\n"
        "EndSection\n"
    )
    session.log(session.t("log-locale-keymap", loc=loc, keymap=keymap), "ok")
    (MOUNT_ROOT / "etc" / "hostname").write_text(ctx.hostname + "\n")
    (MOUNT_ROOT / "etc" / "hosts").write_text(
        f"127.0.0.1   localhost\n::1         localhost\n127.0.1.1   {ctx.hostname}.localdomain {ctx.hostname}\n"
    )

    # os-release/lsb-release ANTES de grub (paso siguiente): el
    # 10_linux de grub-mkconfig lee NAME/PRETTY_NAME de os-release UNA
    # sola vez, al generar grub.cfg, y hornea ese texto en las
    # entradas del menu. Antes esto se escribia recien en el paso
    # 'hypr' (el ULTIMO paso, dentro de configure_hyprland) -- para
    # ese momento grub-mkconfig ya habia corrido dos veces (bootloader
    # + snapper/grub-btrfs) contra el os-release de fabrica de Arch,
    # asi que el menu quedaba diciendo "Arch Linux" para siempre por
    # mas que el archivo en si ya dijera AvalOS.
    session.write_file("etc/os-release", f"""\
NAME="AvalOS"
PRETTY_NAME="AvalOS"
ID=avalos
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;122;162;247"
HOME_URL="https://github.com/{AVALOS_REPO}"
DOCUMENTATION_URL="https://wiki.archlinux.org"
LOGO=avalos-logo
""")
    session.write_file("etc/lsb-release", """\
LSB_VERSION=1.4
DISTRIB_ID=AvalOS
DISTRIB_RELEASE=rolling
DISTRIB_CODENAME=avalos
DISTRIB_DESCRIPTION="AvalOS"
""")

    # BUG-FIX (GRUB siempre decia "Arch Linux"): GRUB_DISTRIBUTOR en
    # /etc/default/grub -- NO /etc/os-release -- es lo que el
    # 10_linux de grub-mkconfig usa para armar el titulo de cada
    # entrada del menu (literalmente "${GRUB_DISTRIBUTOR} Linux").
    # De fabrica el paquete grub de Arch trae esa linea fija en
    # "Arch" (o resuelta via `lsb_release`, binario que ni siquiera
    # esta instalado aca, cayendo al fallback "Arch Linux"). Escribir
    # os-release antes de grub-mkconfig (arriba) NUNCA iba a arreglar
    # esto porque 10_linux ni lo lee para este proposito -- son dos
    # mecanismos totalmente separados. Se pisa aca, antes de CUALQUIER
    # grub-mkconfig, y sin condicionar a usb_mode: si hay GRUB
    # tiene que decir AvalOS sea instalacion a disco o a USB.
    grub_default_early = MOUNT_ROOT / "etc" / "default" / "grub"
    if grub_default_early.exists():
        try:
            gd_txt = grub_default_early.read_text()
            gd_txt, n_distrib = re.subn(
                r'^GRUB_DISTRIBUTOR=.*$',
                'GRUB_DISTRIBUTOR="AvalOS"',
                gd_txt,
                flags=re.MULTILINE,
            )
            if n_distrib == 0:
                gd_txt += '\nGRUB_DISTRIBUTOR="AvalOS"\n'
            grub_default_early.write_text(gd_txt)
            session.log(session.t("log-grub-distributor-set"), "ok")
        except OSError as e:
            session.log(session.t("log-grub-distributor-fail", e=e), "warn")

    rc_pw, out_pw = session.run_chroot_stdin(f"root:{ctx.password}\n", ["chpasswd"])
    if rc_pw != 0:
        session.log(session.t("log-chpasswd-root-fail", rc=rc_pw, out=out_pw), "err")
        session.clean_mounts()
        return False

    if not ctx.usb_mode:
        mkinit_path = MOUNT_ROOT / "etc" / "mkinitcpio.conf"
        if mkinit_path.exists():
            mkinit_txt = mkinit_path.read_text()

            if "btrfs" not in mkinit_txt:
                mkinit_txt = re.sub(
                    r'^(HOOKS=\([^)]*)\bfilesystems\b',
                    r'\1btrfs filesystems',
                    mkinit_txt,
                    flags=re.MULTILINE
                )
                mkinit_path.write_text(mkinit_txt)
                session.log(session.t("log-mkinitcpio-btrfs-added"), "ok")
            else:
                session.log(session.t("log-mkinitcpio-btrfs-present"), "ok")

            mkinit_txt = mkinit_path.read_text()
            if ("grub-btrfs-overlayfs" not in mkinit_txt
                    and ctx.bootloader == "grub"):
                mkinit_txt = re.sub(
                    r'^(HOOKS=\([^)]*)\bfsck\b',
                    r'\1fsck grub-btrfs-overlayfs',
                    mkinit_txt,
                    flags=re.MULTILINE
                )
                mkinit_path.write_text(mkinit_txt)
                session.log(session.t("log-mkinitcpio-overlayfs-added"), "ok")

        grub_default = MOUNT_ROOT / "etc" / "default" / "grub"
        if grub_default.exists():
            grub_txt = grub_default.read_text()
            grub_btrfs_additions = []
            if "GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION" not in grub_txt:
                grub_btrfs_additions.append(
                    "GRUB_BTRFS_OVERRIDE_BOOT_PARTITION_DETECTION=true"
                )
            if "GRUB_DISABLE_OS_PROBER" not in grub_txt:
                grub_btrfs_additions.append("GRUB_DISABLE_OS_PROBER=false")
            if grub_btrfs_additions:
                grub_txt += "\n# AvalOS Btrfs snapshot support\n"
                grub_txt += "\n".join(grub_btrfs_additions) + "\n"
                grub_default.write_text(grub_txt)
                session.log(session.t("log-grub-btrfs-configured"), "ok")

    # mkinitcpio -P procesa TODOS los .preset que encuentre en
    # mkinitcpio.d/, no solo el del kernel instalado. Si quedó un
    # preset huérfano apuntando a un vmlinuz que no existe (ej.
    # 'linux.preset' -> /boot/vmlinuz-linux, cuando lo único
    # instalado es linux-avalos), falla con "must be readable" —
    # no rompe la transacción de pacman, pero ensucia el log y no
    # debería estar ahí. Se deja solo el preset del kernel real.
    presets_dir = MOUNT_ROOT / "etc" / "mkinitcpio.d"
    if presets_dir.is_dir():
        valid_preset = f"{kernel_pkg}.preset"
        for p in presets_dir.glob("*.preset"):
            if p.name != valid_preset:
                try:
                    p.unlink()
                    session.log(session.t("log-mkinitcpio-stray-preset-removed", preset=p.name), "warn")
                except OSError as e:
                    session.log(session.t("log-mkinitcpio-stray-preset-error", preset=p.name, e=e), "warn")

    session.run_chroot(["mkinitcpio", "-P"])
    session.step("config", "done", "locale · timezone · hostname · initramfs · btrfs-hook"
                 if not ctx.usb_mode else "locale · timezone · hostname · initramfs")
    return True
