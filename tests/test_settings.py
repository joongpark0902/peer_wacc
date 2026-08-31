import os, tempfile, unittest
from unittest import mock

import settings


class LoadConfigTest(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_parses_keys_and_ignores_comments(self):
        p = self._write("# c\ndart_api_key = ABC\nkrx_id = me\nkrx_pw = pw=with=equals\n")
        with mock.patch.object(settings, "CONFIG_PATH", p):
            cfg = settings.load_config()
        self.assertEqual(cfg, {"dart_api_key": "ABC", "krx_id": "me", "krx_pw": "pw=with=equals", "kicpa_path": ""})

    def test_missing_file_gives_empty_strings(self):
        with mock.patch.object(settings, "CONFIG_PATH", r"C:\nope\config.txt"):
            self.assertEqual(settings.load_config(),
                             {"dart_api_key": "", "krx_id": "", "krx_pw": "", "kicpa_path": ""})

    def test_save_then_load_roundtrip(self):
        p = self._write("")
        with mock.patch.object(settings, "CONFIG_PATH", p):
            settings.save_config({"dart_api_key": "K", "krx_id": "i", "krx_pw": "p"})
            self.assertEqual(settings.load_config()["krx_pw"], "p")

    def test_kicpa_path_roundtrip(self):
        p = self._write("")
        with mock.patch.object(settings, "CONFIG_PATH", p):
            settings.save_config({"dart_api_key": "K", "krx_id": "i", "krx_pw": "p", "kicpa_path": r"C:\x\베타.xlsx"})
            self.assertEqual(settings.load_config()["kicpa_path"], r"C:\x\베타.xlsx")

    def test_dart_key_falls_back_to_downloader_config(self):
        p = self._write("# DART\napi_key = FROM_DOWNLOADER\n")
        with mock.patch.object(settings, "DOWNLOADER_CONFIG_PATH", p):
            self.assertEqual(settings.dart_api_key_with_fallback({"dart_api_key": ""}), "FROM_DOWNLOADER")
            self.assertEqual(settings.dart_api_key_with_fallback({"dart_api_key": "MINE"}), "MINE")
