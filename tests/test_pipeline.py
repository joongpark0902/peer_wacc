import datetime as dt
import unittest

import pipeline as pl


def _daily(start, closes):
    out, d = [], dt.date.fromisoformat(start)
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append((d.isoformat(), float(c)))
        d += dt.timedelta(days=1)
    return out


AS_OF = "2026-03-31"
IDX = _daily("2024-01-01", [1000 + i for i in range(600)])           # 2024-01-01 ~ 2026-04 (600거래일)
STK = _daily("2024-01-01", [100 + (i % 7) for i in range(600)])
NEW = _daily("2026-02-02", [50 + i for i in range(45)])               # 상장 2개월

ROW = {"name": "성광벤드", "market": "유가", "code": "014620", "industry": "금속", "products": "피팅",
       "listed": "1997-11-14", "settle_month": "12월"}


def _fetchers(fail_bs=False, daily=STK):
    return {
        "daily": lambda code, s, e: daily,
        "index": lambda s, e: IDX,
        "cap": lambda code, as_of: {"close": 10000.0, "cap": 10000 * 1000, "shares": 1000, "date": "2026-03-31"},
        "corp_map": lambda: {"014620": "00132318", "0155E0": "00999999"},
        "company": lambda cc: {"corp_name": "성광벤드", "stock_code": "014620", "induty_code": "25919", "corp_cls": "Y"},
        "shares": lambda cc, y, r: {"common_issued": 1100, "common_treasury": 100, "common_outstanding": 1000,
                                    "pref_issued": 0, "pref_treasury": 0, "pref_outstanding": 0},
        "pretax": lambda cc, y: 150e8,                                   # 2억~200억 → 22.0%
        "audit": lambda cc, y: "적정의견", "opinc": lambda cc, y: 30e8,
        "bs": (lambda cc, y, r: (_ for _ in ()).throw(RuntimeError("DART 013"))) if fail_bs else
              (lambda cc, y, r: {"debt_items": [("단기차입금", 100), ("리스부채", 50), ("전환사채", 30)],
                                 "liab_items": [{"name": "단기차입금", "amount": 100, "default": True},
                                                {"name": "리스부채", "amount": 50, "default": True},
                                                {"name": "전환사채", "amount": 30, "default": True},
                                                {"name": "유동금융부채", "amount": 70, "default": False}],
                                 "debt_total": 180, "nci": 20, "total_liabilities": 1000, "other_fin_liab": 70,
                                 "flags": [], "rcept_no": "R1", "fs_div": "CFS"}),
    }


class LoadPeerTest(unittest.TestCase):
    def test_full_load(self):
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(), log=lambda m: None)
        self.assertEqual(p["status"], "ok")
        self.assertEqual(p["ksic"], "25919")
        self.assertEqual(p["close_krx"], [c for d_, c in STK if d_ <= AS_OF][-1])     # 기준일 이하 마지막 종가
        self.assertEqual(p["common_out"], 1000)
        self.assertEqual(p["debt"], {"단기차입금": 100, "유동성장기부채": 0, "장기차입금": 0, "사채": 30, "리스부채": 50, "기타": 0})
        self.assertEqual(p["nci"], 20)
        self.assertEqual(p["rcept_no"], "R1")
        self.assertEqual(p["report_label"], "2026 1분기보고서")     # 3/31 기준 → 1분기보고서(기간말=기준일)
        self.assertEqual(p["beta_calc"]["n"], 104)
        self.assertIsNotNone(p["beta_calc"]["blume"])
        self.assertTrue(p["include"])
        self.assertEqual(p["tax"], 0.22)
        self.assertEqual(p["tax_basis"], "2025 세전이익 2억~200억 한계세율")
        self.assertEqual(p["pretax"], 150e8)

    def test_loss_falls_back_to_target_tax_with_flag(self):
        fx = _fetchers(); fx["pretax"] = lambda cc, y: -1
        p = pl.load_peer("014620", ROW, AS_OF, fx, tax=0.275, log=lambda m: None)
        self.assertEqual(p["tax"], 0.275)
        self.assertIn("세율:결손→대상세율", p["flags"])

    def test_debt_override_includes_financial_liability_and_lease_toggle(self):
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(), debt_override={"유동금융부채": True, "리스부채": False}, log=lambda m: None)
        self.assertEqual(p["debt"], {"단기차입금": 100, "유동성장기부채": 0, "장기차입금": 0, "사채": 30, "리스부채": 0, "기타": 70})
        self.assertTrue(next(x for x in p["liab_items"] if x["name"] == "유동금융부채")["include"])
        p2 = pl.load_peer("014620", ROW, AS_OF, _fetchers(), log=lambda m: None)
        r_in, _ = pl.summarize([p2], beta_source="calc", de_method="mean", tax_target=0.275, include_lease=True)
        r_out, _ = pl.summarize([p2], beta_source="calc", de_method="mean", tax_target=0.275, include_lease=False)
        self.assertEqual(r_in[0]["d"], 180); self.assertEqual(r_out[0]["d"], 130)

    def test_bs_candidates_fall_through_to_older_report(self):
        calls = []
        fx = _fetchers()
        real_bs = fx["bs"]
        def bs(cc, y, r):
            calls.append((y, r))
            if (y, r) == (2026, "11013"):
                raise RuntimeError("DART 013")
            return real_bs(cc, y, r)
        fx["bs"] = bs
        p = pl.load_peer("014620", ROW, AS_OF, fx, log=lambda m: None)
        self.assertEqual(calls[:2], [(2026, "11013"), (2025, "11011")])
        self.assertEqual(p["report_label"], "2025 사업보고서")

    def test_fs_as_of_overrides_financial_report_selection(self):
        """재무 기준일(fs_as_of)을 따로 주면 주가·종가는 기준일, 재무는 fs_as_of 기준으로 고른다."""
        calls = []
        fx = _fetchers()
        real_bs = fx["bs"]
        fx["bs"] = lambda cc, y, r: (calls.append((y, r)), real_bs(cc, y, r))[1]
        p = pl.load_peer("014620", ROW, "2026-06-30", fx, fs_as_of="2026-03-31", log=lambda m: None)
        self.assertEqual(calls[0], (2026, "11013"))          # 반기(11012)가 아니라 1분기보고서
        self.assertEqual(p["report_label"], "2026 1분기보고서")
        self.assertEqual(p["close_date"] <= "2026-06-30", True)

    def test_soft_flags_for_opinion_and_operating_loss(self):
        fx = _fetchers(); fx["audit"] = lambda cc, y: "한정의견"; fx["opinc"] = lambda cc, y: -5e8
        p = pl.load_peer("014620", ROW, AS_OF, fx, log=lambda m: None)
        self.assertIn("감사의견:한정의견", p["flags"]); self.assertIn("영업적자(FY2025)", p["flags"])
        self.assertTrue(p["include"])                                   # soft: 집계에선 빼지 않는다
        p2 = pl.load_peer("014620", ROW, AS_OF, _fetchers(), log=lambda m: None)
        self.assertEqual(p2["audit_opinion"], "적정의견"); self.assertEqual(p2["op_income"], 30e8); self.assertEqual(p2["flags"], [])

    def test_tax_override_wins(self):
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(), tax_override=0.242, log=lambda m: None)
        self.assertEqual(p["tax"], 0.242)
        self.assertEqual(p["tax_basis"], "사용자 지정")

    def test_bs_failure_is_partial_with_flag(self):
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(fail_bs=True), log=lambda m: None)
        self.assertEqual(p["status"], "partial")
        self.assertIn("DART 재무 없음", p["flags"][0])
        self.assertFalse(p["include"])

    def test_new_listing_has_few_points_and_excluded(self):
        p = pl.load_peer("0155E0", dict(ROW, code="0155E0", listed="2026-02-02"), AS_OF, _fetchers(daily=NEW), log=lambda m: None)
        self.assertLess(p["beta_calc"]["n"], 104)
        self.assertIn("관측치부족", p["flags"])
        self.assertFalse(p["include"])

    def test_kicpa_attached(self):
        k = {"base_date": "2026-03-27", "close": 10050.0, "raw": 0.6, "adjusted": 0.73, "points": 104, "flags": []}
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(), kicpa=k, log=lambda m: None)
        self.assertEqual(p["kicpa"]["adjusted"], 0.73)
        self.assertEqual(p["close_kicpa"], 10050.0)


class BucketTest(unittest.TestCase):
    def test_variant_names_bucketed(self):
        out = pl._bucket_debt([("유동성 차입금", 1), ("비유동성 차입금", 2), ("유동성장기차입금", 4), ("전환사채", 8),
                               ("유동 리스부채", 16), ("금융리스부채", 32), ("차입금", 64), ("신주인수권부사채", 128)])
        self.assertEqual(out, {"단기차입금": 1 + 64, "유동성장기부채": 4, "장기차입금": 2, "사채": 8 + 128, "리스부채": 16 + 32, "기타": 0})
        out = pl._bucket_debt([("유동성 금융기관 차입금(사채 제외)", 5), ("비유동성 금융기관 차입금(사채 제외)", 7)])
        self.assertEqual(out["단기차입금"], 5); self.assertEqual(out["장기차입금"], 7); self.assertEqual(out["사채"], 0)


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.p1 = pl.load_peer("014620", ROW, AS_OF, _fetchers(), kicpa={"base_date": "x", "close": 10050.0, "raw": 0.6, "adjusted": 0.73, "points": 104, "flags": []}, log=lambda m: None)
        self.p2 = pl.load_peer("014620", dict(ROW, name="B"), AS_OF, _fetchers(), log=lambda m: None)   # 한공회 없음

    def test_calc_source_uses_blume_for_both(self):
        rows, agg = pl.summarize([self.p1, self.p2], beta_source="calc", de_method="mean", tax_target=0.275)
        self.assertEqual(agg["n"], 2)
        self.assertAlmostEqual(rows[0]["beta_l_used"], self.p1["beta_calc"]["blume"])

    def test_kicpa_source_excludes_missing(self):
        rows, agg = pl.summarize([self.p1, self.p2], beta_source="kicpa", de_method="mean", tax_target=0.275)
        self.assertEqual(agg["n"], 1)
        self.assertAlmostEqual(rows[0]["beta_l_used"], 0.73)
        self.assertIn("한공회 없음", rows[1]["flags"])
        de = 180 / (10050.0 * 1000 + 20)     # 한공회 종가로 E 계산
        self.assertAlmostEqual(rows[0]["de"], de)
        self.assertAlmostEqual(agg["beta_u"], 0.73 / (1 + 0.78 * de))     # 피어 세율 22%(세전이익 150억 구간)


class WeeklyTableTest(unittest.TestCase):
    def test_aligns_on_index_weeks(self):
        p = pl.load_peer("0155E0", dict(ROW, code="0155E0"), AS_OF, _fetchers(daily=NEW), log=lambda m: None)
        dates, idx, table = pl.weekly_table([p], IDX, AS_OF)
        self.assertEqual(len(dates), 105)
        self.assertEqual(len(idx), 105)
        self.assertEqual(dates[-1], "2026-03-27")
        self.assertEqual(len(table["0155E0"]), 105)
        self.assertIsNone(table["0155E0"][0])
        self.assertIsNotNone(table["0155E0"][-1])


class ReportDataTest(unittest.TestCase):
    def test_build_report_data_shape(self):
        import session
        s = session.new("대상", AS_OF)
        s["keywords"] = ["피팅"]
        p = pl.load_peer("014620", ROW, AS_OF, _fetchers(), log=lambda m: None)
        cands = [dict(ROW, hits=["피팅"], flags=[], excluded=False, reason="")]
        d = pl.build_report_data(s, cands, [p], IDX, "2026-08-27", ("20240304", "20260327"), ["메모"])
        self.assertEqual(d["target"]["name"], "대상")
        self.assertEqual(d["peers"][0]["code"], "014620")
        self.assertEqual(len(d["weekly_dates"]), len(d["weekly"]["014620"]))
        self.assertEqual(d["notes"], ["메모"])
        self.assertEqual(pl.report_label(2025, "11011"), "2025 사업보고서")

    def test_build_report_data_carries_fs_as_of(self):
        import session
        s = session.new("대상", "2026-06-30")
        s["fs_as_of"] = "2026-03-31"
        p = pl.load_peer("014620", ROW, "2026-06-30", _fetchers(), log=lambda m: None)
        d = pl.build_report_data(s, [], [p], IDX, "2026-08-31", ("20240701", "20260630"), [])
        self.assertEqual(d["fs_as_of"], "2026-03-31")


class FsQuarterEndTest(unittest.TestCase):
    """재무 기준일 선택(3·6·9·12월말) → 기준일 이하의 가장 최근 해당 분기말."""

    def test_quarter_ends(self):
        self.assertEqual(pl.fs_quarter_end("2026-08-31", 3), "2026-03-31")
        self.assertEqual(pl.fs_quarter_end("2026-08-31", 6), "2026-06-30")
        self.assertEqual(pl.fs_quarter_end("2026-08-31", 9), "2025-09-30")
        self.assertEqual(pl.fs_quarter_end("2026-08-31", 12), "2025-12-31")
        self.assertEqual(pl.fs_quarter_end("2026-03-31", 3), "2026-03-31")   # 기준일이 분기말 당일
        self.assertIsNone(pl.fs_quarter_end("2026-08-31", None))             # 자동(기준일과 동일 취급)
