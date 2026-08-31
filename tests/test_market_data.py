import json, os, tempfile, unittest
from unittest import mock

import market_data

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "kind_sample.html")


class ParseKindTest(unittest.TestCase):
    def setUp(self):
        with open(FIX, "rb") as f:
            self.rows = market_data.parse_kind_html(f.read())

    def test_row_count_and_keys(self):
        self.assertEqual(len(self.rows), 6)
        self.assertEqual(set(self.rows[0]), {"name", "market", "code", "industry", "products",
                                             "listed", "settle_month", "ceo", "homepage", "region"})

    def test_values_decoded_euc_kr(self):
        r = next(x for x in self.rows if x["code"] == "014620")
        self.assertEqual(r["name"], "성광벤드")
        self.assertEqual(r["industry"], "기타 금속 가공제품 제조업")
        self.assertEqual(r["listed"], "1997-11-14")
        self.assertEqual(r["settle_month"], "12월")

    def test_code_kept_as_text_with_leading_zero_and_temp_code(self):
        codes = {x["code"] for x in self.rows}
        self.assertIn("005930", codes)
        self.assertIn("0155E0", codes)


class CacheTest(unittest.TestCase):
    def test_load_uses_cache_when_present(self):
        d = tempfile.mkdtemp()
        cached = [{"name": "캐시", "code": "000001"}]
        with mock.patch.object(market_data, "CACHE_DIR", d), \
             mock.patch.object(market_data, "_today", lambda: "20260827"):
            with open(os.path.join(d, "kind_list_20260827.json"), "w", encoding="utf-8") as f:
                json.dump(cached, f)
            with mock.patch.object(market_data, "_fetch_kind_bytes", side_effect=AssertionError("network!")):
                self.assertEqual(market_data.load_kind_list(), cached)

    def test_load_fetches_and_writes_cache_when_missing(self):
        d = tempfile.mkdtemp()
        with open(FIX, "rb") as f:
            raw = f.read()
        with mock.patch.object(market_data, "CACHE_DIR", d), \
             mock.patch.object(market_data, "_today", lambda: "20260827"), \
             mock.patch.object(market_data, "_fetch_kind_bytes", return_value=raw):
            rows = market_data.load_kind_list()
        self.assertEqual(len(rows), 6)
        self.assertTrue(os.path.exists(os.path.join(d, "kind_list_20260827.json")))
