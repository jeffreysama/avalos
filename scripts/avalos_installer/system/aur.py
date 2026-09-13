"""
system/aur.py — bootstrap de yay desde AUR (git clone + makepkg -si como
usuario no-root, con sudoers temporal NOPASSWD), instalación de paquetes
AUR, y los extras de gaming (gamemode.ini, MangoHud.conf, flathub) que en
el original solo corren si yay funcionó. Corresponde al paso "aur" de
_run_instalacion en skill_instalar_usb.py (líneas 4857-4956).

Este es el módulo que quedaba pendiente a pedido explícito — el bug ya
diagnosticado (yay se salta intermitentemente) sigue exactamente igual,
sin corregir: la extracción es fiel, no es el lugar para meter el fix.
Hipótesis de esa sesión de diagnóstico, sin cambios: mismo problema de
raíz que los 404 de mirrors ya confirmados como reales (makepkg -s corre
'pacman -S go' internamente), o el propio git clone contra
aur.archlinux.org fallando — la salida real capturada en `out_yay` es lo
que lo confirma cuando vuelva a pasar.

Ningún fallo acá detiene la instalación completa (ni un solo `return` en
todo el bloque original) — yay fallido, AUR parcial, o gaming-extras
fallidos quedan como warnings logueados, igual que repos.py. Los extras
de gaming se quedan acá (no en system/optimize.py) porque en el original
están condicionados al mismo bloque `if` de "yay funcionó", no por
diseño temático — separarlos hubiera sido reorganizar de más.

Cambios de forma (no de lógica): `self.X` → `session.X` / `ctx.X`.
`usuario` → `ctx.username`. Todos los identificadores → inglés.
"""

from __future__ import annotations

from avalos_installer.core.config import MOUNT_ROOT, read_config
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession
from avalos_installer.system.pacstrap import HYPRLAND_AUR_PKGS, GAMING_AUR_PKGS


def install_aur(session: InstallSession, ctx: InstallContext) -> None:
    session.step("aur", "active")
    session.status(session.t("status-installing-aur"))
    session.log("\n── yay + AUR ──\n", "step")

    sudoers_tmp = MOUNT_ROOT / "etc" / "sudoers.d" / "99-aur-build"
    try:
        sudoers_tmp.write_text(f"{ctx.username} ALL=(ALL:ALL) NOPASSWD: ALL\n")
        sudoers_tmp.chmod(0o440)
    except OSError:
        sudoers_tmp = None

    yay_script = (
        "set -euo pipefail; "
        "TMPD=$(mktemp -d) && "
        "git clone --depth=1 https://aur.archlinux.org/yay.git \"$TMPD/yay_build\" && "
        "cd \"$TMPD/yay_build\" && "
        "makepkg -si --noconfirm --needed && "
        "rm -rf \"$TMPD\""
    )
    # Sin captura de output ni reintento, un solo corte de red durante
    # el 'git clone' o durante la descarga de 'go' (makedepend de yay)
    # tira todo el bootstrap sin dejar rastro de POR QUE -- rc se veía
    # pero el output se descartaba (== "_"). Con todo lo que ya vimos
    # de mirrors/red inestables en esta build, vale un reintento igual
    # que el resto de la instalación.
    rc, out_yay = "", ""
    for attempt in range(2):
        rc, out_yay = session.run_chroot(
            ["sudo", "-H", "-u", ctx.username, "bash", "-c", yay_script], timeout=600
        )
        if rc == 0:
            break
        if attempt == 0:
            session.log(session.t("log-yay-retry"), "warn")

    if rc != 0:
        session.log(session.t("log-yay-not-installed", out=out_yay.strip()[-500:]), "warn")
        session.step("aur", "skip", session.t("step-yay-failed-label"))
    else:
        all_aur = HYPRLAND_AUR_PKGS + (GAMING_AUR_PKGS if ctx.install_gaming else [])
        if all_aur:
            rc_aur, out_aur = session.run_chroot(
                ["sudo", "-H", "-u", ctx.username, "yay", "-S", "--noconfirm", "--needed"]
                + all_aur, timeout=1800
            )
            if rc_aur != 0:
                session.log(
                    session.t("log-aur-partial-fail", rc=rc_aur, out=out_aur.strip()[-500:]),
                    "warn"
                )
                session.step("aur", "done", session.t("step-aur-count-warn", n=len(all_aur)))
            else:
                session.step("aur", "done", session.t("step-aur-count", n=len(all_aur)))
        else:
            session.step("aur", "done", session.t("step-aur-count-zero"))

        if ctx.install_gaming:
            session.run_chroot(["usermod", "-aG", "gamemode", ctx.username])

            gamemode_conf = (
                "[general]\n"
                "reaper_freq=5\n"
                "defaultgov=performance\n"
                "desiredgov=performance\n"
                "softrealtime=auto\n"
                "renice=-10\n\n"
                "[gpu]\n"
                "apply_gpu_optimisations=accept-responsibility\n"
                "gpu_device=0\n"
                "amd_performance_level=high\n\n"
                "[filter]\n"
                "whitelist=steam\nwhitelist=lutris\nwhitelist=heroic\n"
            )
            try:
                gm_path = MOUNT_ROOT / "etc" / "gamemode.ini"
                gm_path.write_text(gamemode_conf, encoding="utf-8")
                session.log(session.t("log-gamemode-ini-ok"), "ok")
            except OSError as e:
                session.log(f"[WARN] gamemode.ini: {e}", "warn")

            mango_content = read_config("mangohud/MangoHud.conf")
            if mango_content:
                mango_dir = MOUNT_ROOT / "etc" / "MangoHud"
                mango_dir.mkdir(parents=True, exist_ok=True)
                (mango_dir / "MangoHud.conf").write_text(mango_content, encoding="utf-8")
                session.log(session.t("log-mangohud-ok"), "ok")

            session.run_chroot(
                ["sudo", "-H", "-u", ctx.username, "flatpak", "remote-add",
                 "--if-not-exists", "flathub",
                 "https://dl.flathub.org/repo/flathub.flatpakrepo"],
                timeout=120
            )
            session.log(session.t("log-flathub-ok"), "ok")

    if sudoers_tmp and sudoers_tmp.exists():
        try:
            sudoers_tmp.unlink()
        except OSError:
            pass
