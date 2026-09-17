"""
system/repos.py — repos [avalos] + [multilib] en el pacman.conf del
chroot, más la importación de la llave GPG de AvalOS al keyring del
target.

Extraído de VentanaInstalador._run_instalacion en skill_instalar_usb.py
(líneas ~4801-4856). Esta sección NO tiene paso propio en PASOS_IDS —
en el original corre en silencio entre "user" y "aur", solo con
llamadas a self._log(...), sin un solo self._step(...). El orquestador
NO debe envolver configure_repos() en su propio session.step()/
progress() — se llama tal cual, entre create_user() y el paso "aur".

Por qué va ANTES de yay/AUR (comentario del original, preservado en
espíritu): yay resuelve dependencias lib32-* contra [multilib], y
pacstrap no copia pacman.conf al target (no se le pasa -P) — sin este
paso, el chroot todavía tendría el pacman.conf de fábrica del paquete
'pacman', sin multilib, y 'yay -S proton-ge-custom-bin' fallaría al
resolver dependencias.

Ningún fallo acá es fatal: ni un solo `return` en todo el bloque
original, solo warnings logueados y la instalación sigue.
"""
from __future__ import annotations

import re

from avalos_installer.core.config import AVALOS_REPO_URL, MOUNT_ROOT
from avalos_installer.core.session import InstallSession

# Fingerprint de la llave GPG de AvalOS. Ya está en el keyring del live
# ISO de fábrica (ver build-iso.yml) — acá solo se exporta desde ahí y
# se reimporta en el keyring nuevo del chroot del target.
AVALOS_GPG_FINGERPRINT = "60FD7887C1DA5B080281B9B8F548844B24E0379D"


def configure_repos(session: InstallSession) -> None:
    """Agrega [avalos] y [multilib] a /etc/pacman.conf del chroot si no
    están ya presentes, e importa la llave GPG de AvalOS al keyring del
    target. No devuelve nada: no hay condición de fallo que deba
    detener la instalación, igual que en el original."""
    session.log(session.t("log-section-repo-setup"), "step")

    avalos_repo_txt = (
        "\n[avalos]\n"
        "SigLevel = Required DatabaseOptional\n"
        f"Server = {AVALOS_REPO_URL}\n"
    )
    multilib_repo_txt = "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n"

    pac_path = MOUNT_ROOT / "etc" / "pacman.conf"
    try:
        existing = pac_path.read_text(encoding="utf-8") if pac_path.exists() else ""
        to_append = ""
        base_changed = False

        # FIX: en al menos una instalación real, el pacman.conf que quedó
        # en el target no tenía ni [options] ni [core]/[extra] — nada más
        # que lo que esta misma función agrega. El comentario de arriba
        # asume que siempre llega el pacman.conf de fábrica completo (vía
        # el paquete 'pacman'); en la práctica no se puede dar por hecho.
        # Sin 'Architecture' definida, pacman revienta hasta en 'pacman -Q'
        # local, contra cualquier mirror con $arch en la URL, real o no.
        # Causa de fondo (por qué pacstrap dejó esto incompleto) todavía
        # sin confirmar — esto reconstruye una base mínima válida si hace
        # falta, en vez de asumir que ya está.
        if "[options]" not in existing:
            existing = (
                "[options]\n"
                "Architecture = auto\n"
                "SigLevel = Required DatabaseOptional\n"
                "LocalFileSigLevel = Optional\n"
                "\n"
                "[core]\n"
                "Include = /etc/pacman.d/mirrorlist\n"
                "\n"
                "[extra]\n"
                "Include = /etc/pacman.d/mirrorlist\n"
                "\n"
            ) + existing
            base_changed = True
        elif not re.search(r'^#?\s*Architecture\s*=', existing, flags=re.MULTILINE):
            # REVISIÓN EXTRA: el elif de abajo solo cubre "Architecture
            # está pero comentada". Si [options] existe pero la línea
            # Architecture no aparece en NINGUNA forma (ni comentada),
            # ese caso quedaba sin cubrir — se insertaba nada y el bug
            # seguía. Se inserta la línea recién creada, justo después
            # del header [options].
            existing = re.sub(
                r'(\[options\]\s*\n)',
                r'\1Architecture = auto\n',
                existing,
                count=1,
            )
            base_changed = True
        elif re.search(r'^#\s*Architecture\s*=\s*auto\s*$', existing, flags=re.MULTILINE):
            existing = re.sub(
                r'^#\s*Architecture\s*=\s*auto\s*$',
                "Architecture = auto",
                existing,
                count=1,
                flags=re.MULTILINE,
            )
            base_changed = True

        needs_avalos = "[avalos]" not in existing
        if needs_avalos:
            to_append += avalos_repo_txt

        if "[multilib]" not in existing:
            existing_new = re.sub(
                r'#\s*\[multilib\]\s*\n#\s*Include\s*=\s*/etc/pacman\.d/mirrorlist',
                "[multilib]\nInclude = /etc/pacman.d/mirrorlist",
                existing,
            )
            if "[multilib]" not in existing_new:
                to_append += multilib_repo_txt
            else:
                existing = existing_new

        # FIX: pacman-key necesita que /etc/pacman.conf YA EXISTA en disco
        # para correr — si se escribe recién al final de la función (como
        # hacía el original), pacman-key --init/--add/--lsign-key revientan
        # los TRES con "pacman configuration file '/etc/pacman.conf' not
        # found" en TODAS las corridas, porque el archivo nunca llegó a
        # existir antes de esas tres llamadas. Se escribe ACÁ, antes de
        # tocar pacman-key para nada.
        if to_append or base_changed:
            pac_path.write_text(existing + to_append, encoding="utf-8")

        if needs_avalos:
            # FIX: el archivo temporal en MOUNT_ROOT/tmp, leído después
            # como /tmp/avalos.gpg DESDE DENTRO del chroot, asumía que
            # ambas rutas son el mismo archivo real. En al menos una
            # instalación real no lo fueron: pacman-key --add reportó
            # "can't open '/tmp/avalos.gpg': No such file or directory"
            # a pesar de que el archivo sí existía y se había verificado
            # del lado host (rc==0 y tamaño > 0) un instante antes.
            # Causa exacta sin confirmar — se elimina el archivo
            # intermedio del todo en vez de seguir dependiendo de esa
            # ruta compartida: un solo pipe que exporta del lado host
            # y lo mete por stdin directo al pacman-key del CHROOT
            # (arch-chroot reenvía stdin al proceso que ejecuta), sin
            # ningún archivo de por medio.
            rc1, out1 = session.run_chroot(["pacman-key", "--init"])
            rc2, out2 = session.run_cmd([
                "bash", "-c",
                f"set -o pipefail; gpg --homedir /etc/pacman.d/gnupg --armor "
                f"--export {AVALOS_GPG_FINGERPRINT} "
                f"| arch-chroot {MOUNT_ROOT} pacman-key --add -",
            ])
            rc3, out3 = session.run_chroot(["pacman-key", "--lsign-key", AVALOS_GPG_FINGERPRINT])
            if rc1 == 0 and rc2 == 0 and rc3 == 0:
                session.log(f"  clave GPG AvalOS ({AVALOS_GPG_FINGERPRINT}) importada al keyring", "ok")
            else:
                session.log(
                    f"  [WARN] pacman-key falló (init={rc1}, add={rc2}, lsign={rc3}) — "
                    f"el repo [avalos] puede fallar por firma no confiable", "warn"
                )

        session.log("  repos [avalos] + [multilib] → pacman.conf", "ok")
    except OSError as e:
        session.log(f"[WARN] pacman.conf: {e}", "warn")
