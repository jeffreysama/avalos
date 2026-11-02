"""USB Maker: la descarga de Ventoy se verifica con el sha256.txt de la misma release.

Antes el zip se extraía tal cual llegara: una descarga cortada o corrupta terminaba en un
Ventoy2Disk.exe roto (que se ejecuta como administrador y escribe en un disco). Ahora, ANTES de
extraer: hash distinto → se descarta y se corta; sin sha256.txt → se avisa y se sigue.

El USB Maker es de Windows (pywebview): acá solo se importan sus funciones, con `webview` falso.
"""
import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
    import avalos_usb_maker as usb  # noqa: E402

# sha256.txt literal de la release v1.1.18 de Ventoy (formato sha256sum).
REAL_LISTING = (
    "d86ff9de63d94c8b8f1f6b14d23c55af4b88e8207bf2893890892a6a97b1ad54  ventoy-1.1.18-linux.tar.gz\n"
    "ee3917bd5a9973c0b2f8f3ef85048bf68ae089ec88f5561ad78b6ad308b51ab5  ventoy-1.1.18-livecd.iso\n"
    "082c478e8c432e1ac653899fcf50e3a4077a2851bc6112b5ddd30545962164a9  ventoy-1.1.18-windows.zip\n"
)
WINDOWS_HASH = "082c478e8c432e1ac653899fcf50e3a4077a2851bc6112b5ddd30545962164a9"
ZIP_URL = "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip"


class ParsingSha256Txt(unittest.TestCase):
    def test_it_reads_the_windows_zip_from_the_real_listing(self):
        self.assertEqual(usb._parse_sha256_listing(REAL_LISTING, "ventoy-1.1.18-windows.zip"), WINDOWS_HASH)
        self.assertEqual(usb._parse_sha256_listing(REAL_LISTING, "ventoy-1.1.18-livecd.iso"),
                         "ee3917bd5a9973c0b2f8f3ef85048bf68ae089ec88f5561ad78b6ad308b51ab5")

    def test_binary_mode_marker_crlf_and_uppercase_are_accepted(self):
        listing = f"{WINDOWS_HASH.upper()} *ventoy-1.1.18-windows.zip\r\n"
        self.assertEqual(usb._parse_sha256_listing(listing, "ventoy-1.1.18-windows.zip"), WINDOWS_HASH)

    def test_unknown_file_or_garbage_gives_none(self):
        self.assertIsNone(usb._parse_sha256_listing(REAL_LISTING, "ventoy-9.9.9-windows.zip"))
        self.assertIsNone(usb._parse_sha256_listing("", "ventoy-1.1.18-windows.zip"))
        self.assertIsNone(usb._parse_sha256_listing("<html>404</html>\n", "ventoy-1.1.18-windows.zip"))
        short = f"{WINDOWS_HASH[:-1]}  ventoy-1.1.18-windows.zip\n"
        self.assertIsNone(usb._parse_sha256_listing(short, "ventoy-1.1.18-windows.zip"))

    def test_the_file_name_must_match_exactly(self):
        listing = f"{WINDOWS_HASH}  other-ventoy-1.1.18-windows.zip\n{WINDOWS_HASH}  ventoy-1.1.18-windows.zip.sig\n"
        self.assertIsNone(usb._parse_sha256_listing(listing, "ventoy-1.1.18-windows.zip"))

    def test_sha256_of_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "x.bin")
            data = b"ventoy" * 400_000                      # más de un bloque de lectura
            path.write_bytes(data)
            self.assertEqual(usb._sha256_of(path), hashlib.sha256(data).hexdigest())


class FetchingTheExpectedHash(unittest.TestCase):
    def fake_urlopen(self, body):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = body
        return mock.patch.object(usb, "urlopen", return_value=resp)

    def test_it_asks_the_same_release_folder_and_returns_the_zip_hash(self):
        with self.fake_urlopen(REAL_LISTING.encode()) as urlopen:
            self.assertEqual(usb._fetch_ventoy_sha256(ZIP_URL), WINDOWS_HASH)
        self.assertEqual(urlopen.call_args.args[0],
                         "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/sha256.txt")
        self.assertIn("timeout", urlopen.call_args.kwargs)

    def test_the_offline_fallback_url_uses_its_own_release_folder(self):
        with self.fake_urlopen(b"") as urlopen:
            usb._fetch_ventoy_sha256(usb.VENTOY_FALLBACK)
        self.assertEqual(urlopen.call_args.args[0],
                         f"https://github.com/ventoy/Ventoy/releases/download/v{usb.VENTOY_VERSION}/sha256.txt")

    def test_network_failure_or_missing_entry_gives_none(self):
        with mock.patch.object(usb, "urlopen", side_effect=OSError("sin red")):
            self.assertIsNone(usb._fetch_ventoy_sha256(ZIP_URL))
        with self.fake_urlopen(b"no es un sha256.txt"):
            self.assertIsNone(usb._fetch_ventoy_sha256(ZIP_URL))


def make_zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ventoy-1.1.18/Ventoy2Disk.exe", b"MZ-fake-exe")
    return buf.getvalue()


class DownloadingVentoy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name)
        self.zip_bytes = make_zip_bytes()
        self.downloaded = []
        self.app = mock.Mock()
        self.api = usb.AvalAPI(self.app)

    def retrieve(self, url, dest, progress=None):
        Path(dest).write_bytes(self.zip_bytes)
        self.downloaded.append(Path(dest))

    def download(self, expected):
        patches = [
            mock.patch.object(usb, "_get_latest_ventoy_url", return_value=(ZIP_URL, "1.1.18")),
            mock.patch.object(usb, "urlretrieve", side_effect=self.retrieve),
            mock.patch.object(usb, "_fetch_ventoy_sha256", return_value=expected),
            mock.patch.object(usb, "_find_exe_dir", return_value=self.dest),
            mock.patch.object(usb, "_find_ventoy_exe",
                              return_value=self.dest / "ventoy-1.1.18" / "Ventoy2Disk.exe"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return json.loads(self.api.download_ventoy())

    def logged(self):
        return [c.args[1] for c in self.app._jsc.call_args_list if c.args[0] == "pyLog"]

    def test_matching_hash_extracts_ventoy(self):
        res = self.download(hashlib.sha256(self.zip_bytes).hexdigest())
        self.assertTrue(res["ok"], res)
        self.assertTrue((self.dest / "ventoy-1.1.18" / "Ventoy2Disk.exe").exists())
        self.assertTrue(any("SHA256 verificado" in ln for ln in self.logged()))
        self.assertFalse(self.downloaded[0].exists(), "el zip temporal se borra al terminar")

    def test_different_hash_stops_before_extracting_and_discards_the_zip(self):
        res = self.download("0" * 64)
        self.assertFalse(res["ok"])
        self.assertIn("SHA256", res["error"])
        self.assertFalse((self.dest / "ventoy-1.1.18").exists(), "no se extrajo nada")
        self.assertFalse(self.downloaded[0].exists(), "el zip sospechoso se descarta")

    def test_without_sha256_txt_it_warns_and_goes_on(self):
        res = self.download(None)
        self.assertTrue(res["ok"], res)
        self.assertTrue((self.dest / "ventoy-1.1.18" / "Ventoy2Disk.exe").exists())
        warnings = [c.args[1] for c in self.app._jsc.call_args_list
                    if c.args[0] == "pyLog" and c.args[2] == "WRN"]
        self.assertTrue(any("sin verificar" in w for w in warnings), warnings)

    def test_the_check_runs_before_anything_is_extracted(self):
        body = Path(usb.__file__).read_text(encoding="utf-8")
        body = body[body.index("def download_ventoy"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertLess(body.index("_fetch_ventoy_sha256("), body.index("extractall("))
        self.assertLess(body.index("_sha256_of("), body.index("extractall("))


if __name__ == "__main__":
    unittest.main(verbosity=2)
