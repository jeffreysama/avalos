"""
system/users.py — creación del usuario final y su acceso sudo.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas ~4772-4797, sección "user" de PASOS_IDS). Sin cambios de lógica
respecto al original: mismos grupos, mismo shell, mismo archivo sudoers.

El chpasswd del usuario final reusa el mismo patrón que ya usa
system/locale.py para el chpasswd de root — va por stdin, nunca por
argv (la contraseña no debe aparecer en `ps aux` ni en ningún log de
comandos).
"""
from __future__ import annotations

from avalos_installer.core.config import MOUNT_ROOT
from avalos_installer.core.context import InstallContext
from avalos_installer.core.session import InstallSession


def create_user(session: InstallSession, ctx: InstallContext) -> bool:
    """Crea el usuario final (grupos wheel/audio/video/storage/optical),
    le fija la contraseña, y habilita sudo para el grupo wheel.

    Devuelve True si todo salió bien, False si falló. En caso de falla
    ya se llamó session.clean_mounts() y ya se reportó el error a la UI
    antes de retornar — el llamador (el orquestador) solo necesita
    chequear el retorno y detenerse, igual que con el resto de los
    módulos de system/.
    """
    session.step("user", "active")
    session.status(session.t("status-creating-user"))
    session.log(session.t("log-section-creating-user"), "step")

    rc, _ = session.run_chroot([
        "useradd", "-m", "-G", "wheel,audio,video,storage,optical",
        "-s", "/bin/bash", ctx.username,
    ])
    if rc != 0:
        session.step("user", "error")
        session.error_step(session.t("err-useradd-failed", usuario=ctx.username))
        session.clean_mounts()
        return False

    rc_pw, out_pw = session.run_chroot_stdin(f"{ctx.username}:{ctx.password}\n", ["chpasswd"])
    if rc_pw != 0:
        session.log(
            session.t("log-chpasswd-user-fail", usuario=ctx.username, rc=rc_pw, out=out_pw),
            "err",
        )
        session.clean_mounts()
        return False

    try:
        sudoers = MOUNT_ROOT / "etc" / "sudoers.d" / "wheel"
        sudoers.parent.mkdir(parents=True, exist_ok=True)
        sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
        sudoers.chmod(0o440)
    except OSError as e:
        session.log(session.t("log-sudoers-wheel-fail", e=str(e)), "warn")

    session.step("user", "done", session.t("step-user-created-label", usuario=ctx.username))
    return True
