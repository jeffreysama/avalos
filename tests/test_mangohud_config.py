"""MangoHud: la config tiene que quedar donde MangoHud la lee.

El instalador la dejaba en /etc/MangoHud/MangoHud.conf, y MangoHud no mira ahí: solo lee
./MangoHud.conf, $XDG_CONFIG_HOME/MangoHud/ (MangoHud.conf, <app>.conf, wine-<app>.conf) y
$MANGOHUD_CONFIGFILE (wiki de Arch y documentación de MangoHud). El tema Tokyo Night nunca se veía.
Ahora se escribe en ~/.config/MangoHud/ del usuario, con su dueño (el instalador corre como root).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from avalos_installer.system import aur  # noqa: E402

LEGACY = ROOT / "scripts" / "skill_instalar_usb.py"
CONTENT = "# AvalOS\nfps\ngpu_stats\n"


def fake_system(passwd, make_home="jeff"):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "etc").mkdir()
    (root / "etc" / "passwd").write_text(passwd, encoding="utf-8")
    if make_home:
        (root / "home" / make_home).mkdir(parents=True)
    return tmp, root


PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
          "jeffrey:x:1001:1001::/home/jeffrey:/bin/bash\n"
          "jeff:x:1000:985:Jeff:/home/jeff:/bin/bash\n"
          "garbage line\n")


class WritingTheUserConfig(unittest.TestCase):
    def setUp(self):
        self.tmp, self.root = fake_system(PASSWD)
        self.addCleanup(self.tmp.cleanup)

    def test_it_writes_where_mangohud_reads_and_not_in_etc(self):
        with mock.patch.object(aur.os, "chown"):
            target = aur.write_user_mangohud_config(self.root, "jeff", CONTENT)
        self.assertEqual(target, self.root / "home/jeff/.config/MangoHud/MangoHud.conf")
        self.assertEqual(target.read_text(encoding="utf-8"), CONTENT)
        self.assertFalse((self.root / "etc" / "MangoHud").exists())

    def test_what_it_creates_is_handed_to_the_user_but_the_home_itself_is_not_touched(self):
        with mock.patch.object(aur.os, "chown") as chown:
            aur.write_user_mangohud_config(self.root, "jeff", CONTENT)
        owned = [(Path(c.args[0]), c.args[1], c.args[2]) for c in chown.call_args_list]
        home = self.root / "home/jeff"
        self.assertEqual(owned, [(home / ".config", 1000, 985), (home / ".config/MangoHud", 1000, 985),
                                 (home / ".config/MangoHud/MangoHud.conf", 1000, 985)])

    def test_an_existing_config_folder_keeps_its_owner(self):
        (self.root / "home/jeff/.config").mkdir()
        with mock.patch.object(aur.os, "chown") as chown:
            aur.write_user_mangohud_config(self.root, "jeff", CONTENT)
        owned = [Path(c.args[0]).name for c in chown.call_args_list]
        self.assertEqual(owned, ["MangoHud", "MangoHud.conf"])

    def test_the_user_is_matched_exactly_not_by_prefix(self):
        with mock.patch.object(aur.os, "chown") as chown:
            aur.write_user_mangohud_config(self.root, "jeff", CONTENT)
        self.assertTrue(all(c.args[1:] == (1000, 985) for c in chown.call_args_list))
        self.assertFalse((self.root / "home/jeffrey").exists())

    def test_an_unknown_user_writes_nothing(self):
        with mock.patch.object(aur.os, "chown") as chown, self.assertRaises(KeyError):
            aur.write_user_mangohud_config(self.root, "nadie", CONTENT)
        chown.assert_not_called()
        self.assertFalse((self.root / "home/jeff/.config").exists())

    def test_a_missing_home_is_an_error_and_is_not_created_as_root(self):
        tmp, root = fake_system(PASSWD, make_home=None)
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(aur.os, "chown"), self.assertRaises(OSError):
            aur.write_user_mangohud_config(root, "jeff", CONTENT)
        self.assertFalse((root / "home").exists())

    def test_a_system_without_passwd_is_an_error(self):
        (self.root / "etc" / "passwd").unlink()
        with self.assertRaises(OSError):
            aur.write_user_mangohud_config(self.root, "jeff", CONTENT)

    def test_with_the_real_chown_the_files_end_up_owned_by_the_passwd_ids(self):
        passwd = f"jeff:x:{os.getuid()}:{os.getgid()}::/home/jeff:/bin/bash\n"
        tmp, root = fake_system(passwd)
        self.addCleanup(tmp.cleanup)
        target = aur.write_user_mangohud_config(root, "jeff", CONTENT)
        self.assertEqual((target.stat().st_uid, target.stat().st_gid), (os.getuid(), os.getgid()))


class BothInstallersDoTheSame(unittest.TestCase):
    def test_the_legacy_installer_embeds_the_same_code(self):
        """El legado es el modular empaquetado (scripts/build-legacy-installer.py): lleva aur.py tal cual."""
        modular = (ROOT / "scripts/avalos_installer/system/aur.py").read_text(encoding="utf-8")
        self.assertIn(modular, LEGACY.read_text(encoding="utf-8"))

    def test_neither_installer_writes_into_etc_mangohud_any_more(self):
        for path in (ROOT / "scripts/avalos_installer/system/aur.py", LEGACY):
            src = path.read_text(encoding="utf-8")
            self.assertNotRegex(src, r'"etc"\s*/\s*"MangoHud"', path.name)
            self.assertIn("write_user_mangohud_config", src.split("def write_user_mangohud_config", 1)[1], path.name)

    def test_both_call_it_with_the_new_user_and_log_the_result(self):
        modular = (ROOT / "scripts/avalos_installer/system/aur.py").read_text(encoding="utf-8")
        legacy = LEGACY.read_text(encoding="utf-8")
        self.assertIn("write_user_mangohud_config(MOUNT_ROOT, ctx.username, mango_content)", modular)
        self.assertIn("write_user_mangohud_config(MOUNT_ROOT, ctx.username, mango_content)", legacy)
        for src in (modular, legacy):
            self.assertIn("log-mangohud-ok", src)

    def test_a_failure_writing_the_config_never_stops_the_installation(self):
        """Ningún fallo del paso de AUR/gaming detiene la instalación: KeyError (usuario ausente)
        y ValueError (passwd raro) se registran como aviso, no se propagan."""
        modular = (ROOT / "scripts/avalos_installer/system/aur.py").read_text(encoding="utf-8")
        legacy = LEGACY.read_text(encoding="utf-8")
        self.assertIn("except (OSError, KeyError, ValueError) as e:", modular)
        self.assertIn("except (OSError, KeyError, ValueError) as e:", legacy)

    def test_the_default_config_still_ships_with_the_repo(self):
        text = (ROOT / "configs/mangohud/MangoHud.conf").read_text(encoding="utf-8")
        self.assertIn("fps", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
