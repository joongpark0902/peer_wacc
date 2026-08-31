import datetime as dt
import json, os, tempfile, unittest
from unittest import mock

import market_data as md


class _Df:
    """pykrx DataFrame 흉내: index=날짜, ['종가'] 열만 쓴다."""
    def __init__(self, rows):
        self.index = [dt.datetime.fromisoformat(d) for d, _ in rows]
        self._c = [c for _, c in rows]
        self.empty = not rows
    def __getitem__(self, col):
        assert col == "종가"
        return self._c
    def iterrows(self):
        return iter(zip(self.index, [{"종가": c} for c in self._c]))


class WindowTest(unittest.TestCase):
    def test_window_ends_on_as_of_and_starts_107_weeks_before_last_friday(self):
        s, e = md.window_for("2026-03-31", weeks=104)
        self.assertEqual(e, "20260331")     # 끝은 기준일 당일
        self.assertEqual(s, "20240304")   # 2026-03-27(금) - 107주 → 2024-03-08(금) 그 주 월요일 = 03-04


class DailyClosesTest(unittest.TestCase):
    def test_uses_krx_module_and_caches(self):
        d = tempfile.mkdtemp()
        df = _Df([("2026-03-26", 10000.0), ("2026-03-27", 10100.0)])
        with mock.patch.object(md, "CACHE_DIR", d), \
             mock.patch.object(md, "_krx_ohlcv", return_value=df) as m:
            out = md.daily_closes("014620", "20260323", "20260327")
            self.assertEqual(out, [("2026-03-26", 10000.0), ("2026-03-27", 10100.0)])
            m.assert_called_once_with("20260323", "20260327", "014620")
            out2 = md.daily_closes("014620", "20260323", "20260327")
            self.assertEqual(out2, out)
            m.assert_called_once()              # 두 번째는 캐시
        self.assertTrue(os.path.exists(os.path.join(d, "px", "014620_20260323_20260327.json")))

    def test_empty_raises(self):
        with mock.patch.object(md, "CACHE_DIR", tempfile.mkdtemp()), \
             mock.patch.object(md, "_krx_ohlcv", return_value=_Df([])):
            with self.assertRaises(md.MarketDataError):
                md.daily_closes("0155E0", "20260323", "20260327")


class MarketCapTest(unittest.TestCase):
    def test_takes_last_row_on_or_before_as_of(self):
        class Cap:
            def __init__(self):
                self.index = [dt.datetime(2026, 3, 26), dt.datetime(2026, 3, 27)]
                self.empty = False
            def iterrows(self):
                return iter([(self.index[0], {"시가총액": 100, "상장주식수": 10}),
                             (self.index[1], {"시가총액": 121, "상장주식수": 11})])
        with mock.patch.object(md, "_krx_cap", return_value=Cap()):
            r = md.market_cap("014620", "2026-03-29")
        self.assertEqual(r, {"close": 11.0, "cap": 121, "shares": 11, "date": "2026-03-27"})
