"""El modo rendimiento del Game Center depende de que el usuario esté en el grupo «gamemode» (la regla de
polkit del paquete solo autoriza a sus miembros): el instalador tiene que dejarlo hecho aunque el bootstrap
de AUR falle, y tiene que decir si no pudo; y el Doctor tiene que avisar cuando el usuario no está.

Hallazgo de v38: la configuración de juegos (usermod, gamemode.ini, MangoHud, Flathub) vivía dentro del `else:`
de «yay se instaló bien», así que un fallo del bootstrap de AUR la saltaba entera y en silencio."""
import importlib.machinery
import importlib.util
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translations  # noqa: E402
from avalos_installer.system import aur  # noqa: E402

LANGS = ("en", "es", "zh", "ja")
USER = "jeff"


class FakeSession:
    """Sesión mínima: guarda cada comando del chroot y cada línea del log, y contesta con rc guiados."""

    def __init__(self, yay_rc=0, usermod_rcs=(0,), group_exists=True):
        self.calls, self.logs, self.steps = [], [], []
        self.yay_rc = yay_rc
        self.usermod_rcs = list(usermod_rcs)
        self.group_exists = group_exists

    def t(self, key, **kw):
        return key + ("" if not kw else ":" + ",".join(f"{k}={v}" for k, v in sorted(kw.items())))

    def log(self, msg, level="info"):
        self.logs.append((msg, level))

    def step(self, name, state, label=None):
        self.steps.append((name, state))

    def status(self, msg):
        pass

    def run_chroot(self, cmd, timeout=None):
        self.calls.append(list(cmd))
        if cmd[0] == "usermod":
            return (self.usermod_rcs.pop(0) if self.usermod_rcs else 0), "usermod: salida"
        if cmd[:2] == ["getent", "group"]:
            return (0 if self.group_exists else 2), ""       # getent: 2 = «no encontrado»
        if cmd[0] == "groupadd":
            self.group_exists = True
            return 0, ""
        if "bash" in cmd:                      # el bootstrap de yay (git clone + makepkg)
            return self.yay_rc, "makepkg: fallo simulado"
        return 0, ""


def usermods(session):
    return [c for c in session.calls if c[0] == "usermod"]


class AddUserToGamemodeGroup(unittest.TestCase):
    def test_success_is_logged_as_ok(self):
        s = FakeSession(usermod_rcs=(0,))
        self.assertTrue(aur.add_user_to_gamemode_group(s, USER))
        self.assertEqual(usermods(s), [["usermod", "-aG", "gamemode", USER]])
        self.assertEqual(s.logs[-1], ("log-gamemode-group-ok", "ok"))

    def test_a_missing_group_is_created_and_usermod_retried(self):
        s = FakeSession(usermod_rcs=(6, 0), group_exists=False)     # 6 = «specified group doesn't exist»
        self.assertTrue(aur.add_user_to_gamemode_group(s, USER))
        self.assertEqual([c[0] for c in s.calls], ["usermod", "getent", "groupadd", "usermod"])
        self.assertEqual(s.calls[2], ["groupadd", "-r", "gamemode"])
        self.assertEqual(s.logs[-1][1], "ok")

    def test_a_missing_user_is_not_mistaken_for_a_missing_group(self):
        """usermod devuelve 6 también cuando falta el usuario: con el grupo ya creado no hay que crear nada."""
        s = FakeSession(usermod_rcs=(6,), group_exists=True)
        self.assertFalse(aur.add_user_to_gamemode_group(s, USER))
        self.assertEqual([c[0] for c in s.calls], ["usermod", "getent"])
        msg, level = s.logs[-1]
        self.assertEqual(level, "warn")
        self.assertIn("rc=6", msg)

    def test_any_other_failure_is_reported_and_does_not_create_a_group(self):
        s = FakeSession(usermod_rcs=(1,))
        self.assertFalse(aur.add_user_to_gamemode_group(s, USER))
        self.assertNotIn("groupadd", [c[0] for c in s.calls])
        msg, level = s.logs[-1]
        self.assertEqual(level, "warn")
        self.assertIn("log-gamemode-group-failed", msg)
        self.assertIn("rc=1", msg)

    def test_a_failure_after_creating_the_group_is_still_reported(self):
        s = FakeSession(usermod_rcs=(6, 6), group_exists=False)
        self.assertFalse(aur.add_user_to_gamemode_group(s, USER))
        self.assertEqual([c[0] for c in s.calls], ["usermod", "getent", "groupadd", "usermod"])
        self.assertEqual(s.logs[-1][1], "warn")


class InstallAurFlow(unittest.TestCase):
    """install_aur completo contra una sesión falsa y un MOUNT_ROOT temporal."""

    def run_install(self, gaming=True, yay_rc=0, usermod_rcs=(0,)):
        tmp = Path(tempfile.mkdtemp(prefix="avalos-aur-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "etc" / "sudoers.d").mkdir(parents=True)
        session = FakeSession(yay_rc=yay_rc, usermod_rcs=usermod_rcs)
        ctx = types.SimpleNamespace(username=USER, install_gaming=gaming)
        with mock.patch.object(aur, "MOUNT_ROOT", tmp), mock.patch.object(aur, "read_config", lambda p: None):
            aur.install_aur(session, ctx)
        return session, tmp

    def test_gaming_setup_runs_even_when_the_yay_bootstrap_fails(self):
        s, tmp = self.run_install(yay_rc=1)
        self.assertIn(("aur", "skip"), s.steps)                         # el AUR sí se saltó…
        self.assertEqual(usermods(s), [["usermod", "-aG", "gamemode", USER]])
        self.assertTrue((tmp / "etc" / "gamemode.ini").is_file())
        self.assertTrue(any("remote-add" in c for c in s.calls))
        self.assertFalse((tmp / "etc" / "sudoers.d" / "zz-avalos-aur-build").exists())   # y la limpieza corrió

    def test_gaming_setup_still_runs_when_yay_works(self):
        s, tmp = self.run_install(yay_rc=0)
        self.assertEqual(len(usermods(s)), 1)
        self.assertTrue((tmp / "etc" / "gamemode.ini").is_file())
        self.assertTrue(any("remote-add" in c for c in s.calls))
        self.assertFalse((tmp / "etc" / "sudoers.d" / "zz-avalos-aur-build").exists())

    def test_nothing_gaming_related_without_the_gaming_profile(self):
        for yay_rc in (0, 1):
            s, tmp = self.run_install(gaming=False, yay_rc=yay_rc)
            self.assertEqual(usermods(s), [])
            self.assertFalse((tmp / "etc" / "gamemode.ini").exists())
            self.assertFalse(any("remote-add" in c for c in s.calls))

    def test_a_failed_usermod_is_visible_in_the_install_log(self):
        s, _ = self.run_install(yay_rc=1, usermod_rcs=(1,))
        self.assertTrue(any("log-gamemode-group-failed" in m and lvl == "warn" for m, lvl in s.logs))


class InstallerMessages(unittest.TestCase):
    def test_the_new_log_lines_exist_in_every_language_with_the_same_placeholders(self):
        for key in ("log-gamemode-group-ok", "log-gamemode-group-failed"):
            want = set(re.findall(r"\{(\w+)\}", translations.TRANSLATIONS["en"][key]))
            for lang in LANGS:
                text = translations.TRANSLATIONS[lang].get(key)
                self.assertTrue(text, f"{lang}: falta {key}")
                self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), want, f"{lang}:{key}")
        self.assertEqual(set(re.findall(r"\{(\w+)\}", translations.TRANSLATIONS["en"]["log-gamemode-group-failed"])), {"rc", "out"})


def load_doctor():
    loader = importlib.machinery.SourceFileLoader("avalos_doctor_gm_under_test", str(ROOT / "scripts" / "avalos-doctor"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GamemodeGroupCheck(unittest.TestCase):
    def setUp(self):
        self.doc = load_doctor()
        tmp = Path(tempfile.mkdtemp(prefix="avalos-gm-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.helper = tmp / "cpugovctl"
        self.helper.write_text("#!/bin/sh\n")

    def run_check(self, installed=True, group=(985, ()), uid=1000, gid=1000, session_groups=(998,), pw_gid=1000):
        helpers = (self.helper,) if installed else (self.helper.parent / "no-existe",)
        gr = None if group is None else types.SimpleNamespace(gr_gid=group[0], gr_mem=list(group[1]))
        pw = types.SimpleNamespace(pw_name=USER, pw_uid=uid, pw_gid=pw_gid)

        def getgrnam(name):
            if gr is None:
                raise KeyError(name)
            return gr

        with mock.patch.object(self.doc, "GAMEMODE_HELPERS", helpers), \
                mock.patch.object(self.doc.grp, "getgrnam", getgrnam), \
                mock.patch.object(self.doc.pwd, "getpwuid", lambda u: pw), \
                mock.patch.object(self.doc.os, "getuid", lambda: uid), \
                mock.patch.object(self.doc.os, "getgid", lambda: gid), \
                mock.patch.object(self.doc.os, "getgroups", lambda: list(session_groups)):
            return self.doc.chk_gamemode()

    def test_gamemode_not_installed_is_skipped(self):
        status, key, _, _ = self.run_check(installed=False)
        self.assertEqual((status, key), ("skip", "d-gamemode-skip"))

    def test_root_is_skipped_because_it_never_needs_the_group(self):
        status, key, _, _ = self.run_check(uid=0)
        self.assertEqual((status, key), ("skip", "d-gamemode-root"))
        status, key, _, _ = self.run_check(uid=0, installed=False)       # sin GameMode sigue mandando lo de «no instalado»
        self.assertEqual((status, key), ("skip", "d-gamemode-skip"))

    def test_missing_group_warns_with_its_own_message(self):
        status, key, _, _ = self.run_check(group=None)
        self.assertEqual((status, key), ("warn", "d-gamemode-nogroup"))

    def test_user_in_the_session_groups_is_ok(self):
        status, key, args, _ = self.run_check(session_groups=(998, 985))
        self.assertEqual((status, key, args), ("ok", "d-gamemode-ok", {"user": USER}))

    def test_gamemode_as_primary_group_counts(self):
        status, key, _, _ = self.run_check(group=(1000, ()), gid=1000, session_groups=())
        self.assertEqual((status, key), ("ok", "d-gamemode-ok"))

    def test_member_in_etc_group_but_old_session_asks_to_log_in_again(self):
        status, key, args, _ = self.run_check(group=(985, (USER,)), session_groups=(998,))
        self.assertEqual((status, key, args), ("warn", "d-gamemode-relogin", {"user": USER}))

    def test_not_a_member_warns_and_names_the_user(self):
        status, key, args, _ = self.run_check(group=(985, ("otro",)))
        self.assertEqual((status, key, args), ("warn", "d-gamemode-warn", {"user": USER}))

    def test_registered_in_the_hardware_group(self):
        table = {cid: (group, fn.__name__, net) for cid, group, fn, net in self.doc.CHECKS}
        self.assertEqual(table["gamemode"], ("hardware", "chk_gamemode", False))

    def test_every_text_has_every_language_and_the_same_placeholders(self):
        keys = ("t-gamemode", "d-gamemode-ok", "d-gamemode-relogin", "d-gamemode-warn", "d-gamemode-nogroup", "d-gamemode-skip",
                "d-gamemode-root")
        en = self.doc.STRINGS["en"]
        for key in keys:
            want = set(re.findall(r"\{(\w+)\}", en[key]))
            for lang in LANGS:
                text = self.doc.STRINGS[lang].get(key)
                self.assertTrue(text, f"{lang}: falta {key}")
                self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), want, f"{lang}:{key}")

    def test_the_engine_renders_every_outcome_in_every_language(self):
        outcomes = (dict(installed=False), dict(group=None), dict(session_groups=(985,)),
                    dict(group=(985, (USER,))), dict(group=(985, ())), dict(uid=0))
        for lang in LANGS:
            for kw in outcomes:
                _, key, args, _ = self.run_check(**kw)
                text = self.doc.STRINGS[lang][key].format(**args)
                self.assertTrue(text.strip())
                self.assertNotRegex(text, r"[{}]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
