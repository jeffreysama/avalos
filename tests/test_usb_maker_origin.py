"""USB Maker: Ventoy2Disk.exe se ejecuta como administrador y escribe en un disco, así que solo se baja del repositorio de
releases de Ventoy en GitHub. El sha256.txt se pide de la misma carpeta que el zip: si la URL pudiera apuntar a otro host,
el hash y el zip saldrían del mismo atacante y la verificación no probaría nada."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("avalos_usb_maker_origin_under_test", ROOT / "scripts" / "avalos_usb_maker.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}):
        spec.loader.exec_module(module)
    return module


GOOD = "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip"


class VentoyUrlOrigin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.usb = load()

    def test_only_the_ventoy_release_repository_is_accepted(self):
        self.assertTrue(self.usb._is_ventoy_release_url(GOOD))
        self.assertTrue(self.usb._is_ventoy_release_url("https://github.com/ventoy/Ventoy/releases/download/v1.0.99/ventoy-1.0.99-windows.zip"))
        for bad in ("http://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://evil.example/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://github.com.evil.example/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://github.com@evil.example/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://github.com/evil/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://github.com/ventoy/Ventoy-fork/releases/download/v1.1.18/ventoy-1.1.18-windows.zip",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip?x=1",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip#frag",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/../../evil/x-windows.zip",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-windows.zip\n",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/ventoy-1.1.18-linux.tar.gz",
                    "https://github.com/ventoy/Ventoy/releases/download/v1.1.18/sub/ventoy-1.1.18-windows.zip",
                    "file:///C:/evil/ventoy-1.1.18-windows.zip", "ftp://github.com/x", "", None, 5, ["x"]):
            with self.subTest(bad=bad):
                self.assertFalse(self.usb._is_ventoy_release_url(bad))

    def api_response(self, assets, tag="v1.1.18"):
        body = json.dumps({"tag_name": tag, "assets": assets}).encode()
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = body
        return mock.patch.object(self.usb, "urlopen", return_value=resp)

    def test_the_latest_release_lookup_ignores_assets_hosted_elsewhere_and_falls_back(self):
        evil = {"name": "ventoy-9.9.9-windows.zip", "browser_download_url": "https://evil.example/ventoy-9.9.9-windows.zip"}
        with self.api_response([evil]):
            self.assertEqual(self.usb._get_latest_ventoy_url(), (self.usb.VENTOY_FALLBACK, self.usb.VENTOY_VERSION))
        good = {"name": "ventoy-1.1.18-windows.zip", "browser_download_url": GOOD}
        with self.api_response([evil, good]):
            self.assertEqual(self.usb._get_latest_ventoy_url(), (GOOD, "1.1.18"))

    def test_the_fallback_url_itself_passes_the_check(self):
        self.assertTrue(self.usb._is_ventoy_release_url(self.usb.VENTOY_FALLBACK))

    def test_download_refuses_a_foreign_url_before_downloading_anything(self):
        api = self.usb.AvalAPI(mock.MagicMock())
        with mock.patch.object(self.usb, "_get_latest_ventoy_url", return_value=("https://evil.example/ventoy-9-windows.zip", "9")), \
             mock.patch.object(self.usb, "urlretrieve") as retrieve:
            result = json.loads(api.download_ventoy())
        self.assertFalse(result["ok"])
        self.assertIn("release de Ventoy", result["error"])
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
