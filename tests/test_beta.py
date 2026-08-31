import datetime as dt
import unittest

import beta


def _daily(start, closes):
    """월~금 연속 거래일 가정으로 일별 시계열을 만든다(주말 건너뜀)."""
    out, d = [], dt.date.fromisoformat(start)
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append((d.isoformat(), c))
        d += dt.timedelta(days=1)
    return out


class FridayTest(unittest.TestCase):
    def test_last_friday(self):
        self.assertEqual(beta.last_friday_on_or_before("2026-03-31"), dt.date(2026, 3, 27))  # 화 → 전주 금
        self.assertEqual(beta.last_friday_on_or_before("2026-03-27"), dt.date(2026, 3, 27))  # 금 그대로


class WeeklyTest(unittest.TestCase):
    def test_weekly_takes_last_trading_day_of_each_week_and_cuts_at_friday(self):
        daily = _daily("2026-03-02", list(range(1, 25)))          # 3/2(월)~4/2(목) 24거래일
        w = beta.weekly_closes(daily, "2026-03-31", n_weeks=3)
        self.assertEqual([x[0] for x in w], ["2026-03-06", "2026-03-13", "2026-03-20", "2026-03-27"])
        self.assertEqual([x[1] for x in w], [5, 10, 15, 20])

    def test_holiday_week_uses_thursday(self):
        daily = [d for d in _daily("2026-03-02", list(range(1, 11))) if d[0] != "2026-03-06"]
        w = beta.weekly_closes(daily, "2026-03-13", n_weeks=2)
        self.assertEqual(w[0], ("2026-03-05", 4))

    def test_returns(self):
        r = beta.returns([("w1", 100.0), ("w2", 110.0), ("w3", 99.0)])
        self.assertEqual(r[0][0], "w2")
        self.assertAlmostEqual(r[0][1], 0.10)
        self.assertAlmostEqual(r[1][1], -0.10)


class RegressTest(unittest.TestCase):
    def test_slope_matches_excel(self):
        # 엑셀: SLOPE({0.02,-0.01,0.03,0.00},{0.01,-0.02,0.02,0.01}) = 0.8888888889, RSQ = 0.7111111111
        idx = [("a", 0.01), ("b", -0.02), ("c", 0.02), ("d", 0.01)]
        stk = [("a", 0.02), ("b", -0.01), ("c", 0.03), ("d", 0.00)]
        r = beta.regress(stk, idx)
        self.assertAlmostEqual(r["raw"], 0.8888888889, places=9)
        self.assertAlmostEqual(r["r2"], 0.7111111111, places=9)
        self.assertEqual(r["n"], 4)

    def test_intersection_only(self):
        r = beta.regress([("a", 0.1), ("b", 0.2), ("z", 9.0)], [("a", 0.1), ("b", 0.2), ("c", 0.3)])
        self.assertEqual(r["n"], 2)

    def test_blume(self):
        self.assertAlmostEqual(beta.blume(0.5788), 2 / 3 * 0.5788 + 1 / 3)


class HamadaTest(unittest.TestCase):
    def test_roundtrip(self):
        bu = beta.unlever(1.2, de=0.5, tax=0.275)
        self.assertAlmostEqual(bu, 1.2 / (1 + 0.725 * 0.5))
        self.assertAlmostEqual(beta.relever(bu, de=0.5, tax=0.275), 1.2)

    def test_aggregate_mean_and_median_skip_excluded(self):
        peers = [{"beta_u": 0.6, "de": 0.2, "include": True},
                 {"beta_u": 0.8, "de": 0.4, "include": True},
                 {"beta_u": 5.0, "de": 9.0, "include": False},
                 {"beta_u": 1.0, "de": 0.3, "include": True}]
        m = beta.aggregate(peers, method="mean", tax_target=0.275)
        self.assertAlmostEqual(m["beta_u"], 0.8)
        self.assertAlmostEqual(m["de"], 0.3)
        self.assertAlmostEqual(m["beta_l_target"], 0.8 * (1 + 0.725 * 0.3))
        self.assertEqual(m["n"], 3)
        md = beta.aggregate(peers, method="median")
        self.assertAlmostEqual(md["beta_u"], 0.8)
        self.assertAlmostEqual(md["de"], 0.3)

    def test_aggregate_empty(self):
        self.assertEqual(beta.aggregate([])["n"], 0)
        self.assertIsNone(beta.aggregate([])["beta_u"])
