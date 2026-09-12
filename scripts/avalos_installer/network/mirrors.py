"""
network/mirrors.py — sincronización de hora previa a cualquier operación
de red, y optimización de mirrors (rate-mirrors → reflector → mirrorlist
por defecto). Corresponde al tramo entre el paso "mount" y el paso
"pacstrap" de _run_instalacion en skill_instalar_usb.py (líneas
3843-3918) — el time-sync no tiene su propio PASOS_ID (corre "gratis"
antes de "mirrors"), pero se extrae acá y no en system/mount.py porque su
único propósito documentado en el original es proteger las operaciones de
red que siguen, no el montaje en sí.

Cambios de forma (no de lógica): `self.X` → `session.X`. Todos los
identificadores → inglés.
"""

from __future__ import annotations

import time

from avalos_installer.core.session import InstallSession


def sync_time(session: InstallSession):
    """Sincronización de hora ANTES de cualquier operación de red: si el
    reloj del sistema está mal (batería CMOS muerta, o NTP que no
    alcanzó a sincronizar en el boot), la validación de certificado TLS
    puede fallar igual contra CUALQUIER mirror — no es un problema de
    "este mirror en particular", es la hora local. Forzamos esto antes
    de tocar reflector/pacman."""
    session.log(session.t("log-timesync-start"), "info")
    session.run_cmd(["timedatectl", "set-ntp", "true"], timeout=10)
    for _attempt in range(10):
        rc, out = session.run_cmd(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=5
        )
        if rc == 0 and "yes" in out.strip().lower():
            session.log(session.t("log-timesync-ok"), "ok")
            return
        time.sleep(1)
    else:
        session.log(session.t("log-timesync-timeout"), "warn")


def optimize_mirrors(session: InstallSession):
    """rate-mirrors primero (más rápido y confiable); si falla instalarlo
    o correrlo, cae a reflector; si reflector también falla, se queda con
    el mirrorlist que ya trae el live. En los dos casos de éxito se le
    agrega al final un mirror grande fijo (Rackspace, siempre completo
    incluyendo multilib) como red de seguridad — el comentario de por qué
    es ligeramente distinto en cada rama porque el riesgo que cubre es
    distinto (hueco puntual del mirror elegido por rate-mirrors, vs.
    multilib incompleto/viejo en mirrors regionales de reflector)."""
    session.step("mirrors", "active")
    session.status(session.t("status-optimizing-mirrors"))
    session.log(session.t("log-section-mirrors"), "step")

    rc_rm_install, _ = session.run_cmd(
        ["pacman", "-Sy", "--noconfirm", "--needed", "rate-mirrors"], timeout=120
    )
    mirrors_ok = False
    if rc_rm_install == 0:
        rc_rm, _ = session.run_cmd([
            "rate-mirrors", "arch", "--allow-root", "--save", "/etc/pacman.d/mirrorlist",
        ], timeout=90)
        if rc_rm == 0:
            mirrors_ok = True
            session.step("mirrors", "done", session.t("step-mirrors-optimized"))
            session.log(session.t("log-ratemirrors-ok"), "ok")

    if mirrors_ok:
        try:
            with open("/etc/pacman.d/mirrorlist", "a") as mlf:
                mlf.write(
                    "\n# Fallback agregado por el instalador: mirror grande y "
                    "siempre completo (incluye multilib), por si el mirror "
                    "elegido igual tiene algun hueco\n"
                    "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n"
                )
        except Exception as e:
            session.log(f"[WARN] No se pudo agregar mirror de respaldo: {e}", "warn")
        return

    session.log(session.t("log-ratemirrors-fallback"), "warn")
    rc_refl_install, out_refl_install = session.run_cmd(
        ["pacman", "-Sy", "--noconfirm", "--needed", "reflector"], timeout=120
    )
    if rc_refl_install != 0:
        session.step("mirrors", "skip", session.t("step-mirrors-default"))
        from avalos_installer.core.session import output_indicates_gpg_error
        if output_indicates_gpg_error(out_refl_install):
            session.log(session.t("log-pacman-gpg-signature-issue"), "err")
        else:
            session.log(session.t("log-reflector-install-fail"), "warn")
        return

    rc, _ = session.run_cmd([
        "reflector", "--country", "SV,US,MX,GT,JP",
        "--latest", "10", "--sort", "rate",
        "--protocol", "https", "--save", "/etc/pacman.d/mirrorlist",
    ], timeout=120)
    if rc == 0:
        session.step("mirrors", "done", session.t("step-mirrors-optimized"))
        try:
            with open("/etc/pacman.d/mirrorlist", "a") as mlf:
                mlf.write(
                    "\n# Fallback agregado por el instalador: mirror grande y "
                    "siempre completo (incluye multilib), por si los mirrors "
                    "regionales de reflector tienen multilib incompleto/viejo\n"
                    "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n"
                )
        except Exception as e:
            session.log(f"[WARN] No se pudo agregar mirror de respaldo: {e}", "warn")
    else:
        session.step("mirrors", "skip", session.t("step-mirrors-default"))
        session.log(session.t("log-reflector-fail"), "warn")
