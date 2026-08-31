import os, unittest

import kicpa_beta as kb

FX = os.path.join(os.path.dirname(__file__), "fixtures")


class NormalizeTest(unittest.TestCase):
    def test_pads_and_handles_float_and_temp(self):
        self.assertEqual(kb.normalize_code(18260), "018260")
        self.assertEqual(kb.normalize_code("18260.0"), "018260")
        self.assertEqual(kb.normalize_code(" 005930 "), "005930")
        self.assertEqual(kb.normalize_code("0155e0"), "0155E0")


class LoadTest(unittest.TestCase):
    def _check(self, data):
        self.assertEqual(set(data), {"018260", "064400", "286940", "307950"})
        s = data["018260"]
        self.assertEqual(s["name"], "삼성에스디에스")
        self.assertEqual(s["base_date"], "2026-06-26")
        self.assertEqual(s["query_date"], "2026-06-30")
        self.assertAlmostEqual(s["close"], 189900)
        self.assertAlmostEqual(s["adjusted"], 0.956492)
        self.assertEqual(s["points"], 104)
        self.assertEqual(s["flags"], [])
        self.assertEqual(data["064400"]["flags"], ["관측치부족"])

    def test_xlsx(self):
        self._check(kb.load(os.path.join(FX, "kicpa_sample.xlsx")))

    def test_csv(self):
        self._check(kb.load(os.path.join(FX, "kicpa_sample.csv")))

    def test_cp949_csv(self):
        self._check(kb.load(os.path.join(FX, "kicpa_sample_cp949.csv")))

    def test_html_disguised_as_xls(self):
        self._check(kb.load(os.path.join(FX, "kicpa_sample_html.xls")))

    def test_format_error_lists_columns(self):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "bad.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("회사,값\nA,1\n")
        with self.assertRaises(kb.FormatError) as cm:
            kb.load(p)
        self.assertEqual(cm.exception.columns, ["회사", "값"])
