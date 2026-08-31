import os, tempfile, unittest
from unittest import mock

import session


class SessionTest(unittest.TestCase):
    def test_new_schema(self):
        s = session.new("피케이밸브", "2026-03-31")
        self.assertEqual(s["version"], 1)
        self.assertEqual(s["target"]["name"], "피케이밸브")
        self.assertEqual(s["beta_source"], "kicpa")
        self.assertEqual(s["tax_target"], 0.275)
        self.assertEqual(s["candidates"], {})

    def test_path_sanitizes(self):
        with mock.patch.object(session, "SESSION_DIR", r"C:\x"):
            self.assertEqual(session.path_for("A/B:C", "2026-03-31"), r"C:\x\A_B_C_2026-03-31.json")

    def test_save_load_roundtrip_and_defaults(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(session, "SESSION_DIR", d):
            s = session.new("T", "2026-03-31")
            s["candidates"]["014620"] = {"selected": True, "excluded": False, "reason": ""}
            p = session.save(s)
            back = session.load(p)
        self.assertEqual(back["candidates"]["014620"]["selected"], True)
        self.assertEqual(back["de_method"], "mean")
        # 구버전 파일(키 누락)도 기본값으로 채워진다
        import json
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"target": {"name": "T"}, "as_of": "2026-03-31"}, f)
        old = session.load(p)
        self.assertEqual(old["filters"]["listed_min"], False)
        self.assertEqual(old["target"]["listed"], False)
