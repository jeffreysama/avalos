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

        if "[avalos]" not in existing:
            # La llave vive en el keyring del LIVE (host), no del chroot —
            # por eso este export usa session.run_cmd (host), y recién el
            # pacman-key de abajo usa session.run_chroot (target).
            tmp = MOUNT_ROOT / "tmp" / "avalos.gpg"
            rc, _ = session.run_cmd([
                "bash", "-c",
                f"gpg --homedir /etc/pacman.d/gnupg --armor --export "
                f"{AVALOS_GPG_FINGERPRINT} > {tmp} 2>/dev/null",
            ])
            if rc == 0 and tmp.stat().st_size > 0:
                session.run_chroot(["pacman-key", "--init"])
                session.run_chroot(["pacman-key", "--add", "/tmp/avalos.gpg"])
                session.run_chroot(["pacman-key", "--lsign-key", AVALOS_GPG_FINGERPRINT])
                session.log(f"  clave GPG AvalOS ({AVALOS_GPG_FINGERPRINT}) importada al keyring", "ok")
            else:
                session.log("  [WARN] no se pudo exportar la clave GPG de AvalOS desde el live ISO", "warn")
            tmp.unlink(missing_ok=True)
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

        if to_append:
            pac_path.write_text(existing + to_append, encoding="utf-8")
        session.log("  repos [avalos] + [multilib] → pacman.conf", "ok")
    except OSError as e:
        session.log(f"[WARN] pacman.conf: {e}", "warn")
