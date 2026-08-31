import json, os, unittest

import dart_inputs as di

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _js(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f)


class ReportForTest(unittest.TestCase):
    def test_quarter_mapping(self):
        self.assertEqual(di.report_for("2026-03-31"), (2025, "11014"))
        self.assertEqual(di.report_for("2026-04-15"), (2025, "11011"))
        self.assertEqual(di.report_for("2026-06-30"), (2026, "11013"))
        self.assertEqual(di.report_for("2026-09-30"), (2026, "11012"))
        self.assertEqual(di.report_for("2026-12-31"), (2026, "11014"))


class ReportCandidatesTest(unittest.TestCase):
    def test_latest_period_end_on_or_before_as_of(self):
        self.assertEqual(di.report_candidates("2026-03-31"), [(2026, "11013"), (2025, "11011"), (2025, "11014"), (2025, "11012")])
        self.assertEqual(di.report_candidates("2026-03-30"), [(2025, "11011"), (2025, "11014"), (2025, "11012"), (2025, "11013")])
        self.assertEqual(di.report_candidates("2026-08-28")[:2], [(2026, "11012"), (2026, "11013")])


class ParseBriefTest(unittest.TestCase):
    """정밀 추천용 경량 파서: fnlttSinglAcntAll 한 응답에서 매출액·영업이익·부채총계·자본총계."""

    def test_parse_brief_from_full_statement(self):
        js = {"status": "000", "list": [
            {"sj_div": "BS", "account_nm": "매출채권", "thstrm_amount": "9,999"},
            {"sj_div": "BS", "account_nm": "부채총계", "thstrm_amount": "1,000"},
            {"sj_div": "BS", "account_nm": "자본총계", "thstrm_amount": "500"},
            {"sj_div": "IS", "account_nm": "I. 매출액", "thstrm_amount": "2,000"},
            {"sj_div": "IS", "account_nm": "영업이익", "thstrm_amount": "300"},
        ]}
        b = di.parse_brief(js)
        self.assertEqual((b["sales"], b["op_income"], b["total_liab"], b["total_equity"]), (2000, 300, 1000, 500))

    def test_parse_brief_cis_revenue_and_missing(self):
        js = {"status": "000", "list": [
            {"sj_div": "CIS", "account_nm": "수익(매출액)", "thstrm_amount": "700"},
            {"sj_div": "CIS", "account_nm": "영업손실", "thstrm_amount": "-50"},
        ]}
        b = di.parse_brief(js)
        self.assertEqual(b["sales"], 700)
        self.assertEqual(b["op_income"], -50)
        self.assertIsNone(b["total_equity"])


class ParseBsTest(unittest.TestCase):
    def setUp(self):
        self.r = di.parse_bs(_js("dart_bs_sample.json"))

    def test_debt_items_and_total(self):
        names = [n for n, _ in self.r["debt_items"]]
        self.assertEqual(names, ["단기차입금", "유동성장기부채", "장기차입금", "사채", "리스부채", "리스부채"])
        self.assertEqual(self.r["debt_total"], 7_500_000_000)

    def test_nci_liabilities_and_flag(self):
        self.assertEqual(self.r["nci"], 250_000_000)
        self.assertEqual(self.r["total_liabilities"], 40_770_818_528)
        self.assertEqual(self.r["other_fin_liab"], 839_800_000)
        self.assertEqual(self.r["flags"], [])          # 8.4억/407억 = 2% < 5%

    def test_other_fin_flag_when_over_threshold(self):
        js = _js("dart_bs_sample.json")
        for x in js["list"]:
            if x["account_nm"] == "기타금융부채":
                x["thstrm_amount"] = "5,000,000,000"
        self.assertEqual(di.parse_bs(js)["flags"], ["확인필요:금융부채 12%"])

    def test_rcept_no_and_ignores_is_rows(self):
        self.assertEqual(self.r["rcept_no"], "20260317000001")

    def test_liab_items_listed_with_default_and_paren_stripped(self):
        js = {"status": "000", "list": [
            {"sj_div": "BS", "account_nm": "유동성 금융기관 차입금(사채 제외)", "thstrm_amount": "82,113,000,000", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "유동금융부채", "thstrm_amount": "6,977,000,000", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "당기법인세부채", "thstrm_amount": "2,390,000,000", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "유동부채", "thstrm_amount": "101,474,000,000", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "부채총계", "thstrm_amount": "103,655,000,000", "rcept_no": "R"},
        ]}
        r = di.parse_bs(js)
        self.assertEqual([n for n, _ in r["debt_items"]], ["유동성 금융기관 차입금(사채 제외)"])
        names = [(x["name"], x["default"]) for x in r["liab_items"]]
        self.assertEqual(names, [("유동성 금융기관 차입금(사채 제외)", True), ("유동금융부채", False), ("당기법인세부채", False)])
        js["list"] += [{"sj_div": "BS", "account_nm": "현금및현금성자산", "thstrm_amount": "5,000", "rcept_no": "R"},
                       {"sj_div": "BS", "account_nm": "단기금융상품", "thstrm_amount": "700", "rcept_no": "R"}]
        r = di.parse_bs(js)
        self.assertEqual([(c["kind"], c["amount"]) for c in r["cash_items"]], [("현금및현금성자산", 5000), ("단기금융상품", 700)])

    def test_variant_debt_names_and_financial_liability_flag(self):
        js = {"status": "000", "list": [
            {"sj_div": "BS", "account_nm": "유동성 차입금", "thstrm_amount": "12,200,000,000", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "비유동성 차입금", "thstrm_amount": "0", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "유동 리스부채", "thstrm_amount": "269,144,668", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "유동금융부채", "thstrm_amount": "6,977,321,066", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "기타비유동금융부채", "thstrm_amount": "3,782,454,287", "rcept_no": "R"},
            {"sj_div": "BS", "account_nm": "부채총계", "thstrm_amount": "42,562,928,572", "rcept_no": "R"},
        ]}
        r = di.parse_bs(js)
        self.assertEqual([n for n, _ in r["debt_items"]], ["유동성 차입금", "비유동성 차입금", "유동 리스부채"])
        self.assertEqual(r["other_fin_liab"], 6_977_321_066 + 3_782_454_287)
        self.assertEqual(r["flags"], ["확인필요:금융부채 25%"])


class CheckKeyTest(unittest.TestCase):
    def test_check_key(self):
        from unittest import mock
        self.assertEqual(di.check_key(""), (False, "DART 인증키 없음"))
        with mock.patch.object(di, "_get", return_value={"status": "010", "message": "등록되지 않은 인증키입니다."}):
            self.assertEqual(di.check_key("X"), (False, "등록되지 않은 인증키입니다."))
        with mock.patch.object(di, "_get", return_value={"status": "000", "message": "정상"}):
            self.assertEqual(di.check_key("X"), (True, "정상"))


class PretaxTest(unittest.TestCase):
    def test_parse_pretax_variants(self):
        js = {"list": [{"sj_div": "CIS", "account_nm": "법인세비용(수익)", "thstrm_amount": "1"},
                       {"sj_div": "CIS", "account_nm": "법인세비용차감전순이익(손실)", "thstrm_amount": "86,192,865,209"}]}
        self.assertEqual(di.parse_pretax(js), 86_192_865_209)
        js = {"list": [{"sj_div": "IS", "account_nm": "법인세비용차감전순이익", "thstrm_amount": "49,481,471,000,000"},
                       {"sj_div": "CIS", "account_nm": "법인세비용차감전순이익", "thstrm_amount": "1"}]}
        self.assertEqual(di.parse_pretax(js), 49_481_471_000_000)     # IS 우선
        self.assertIsNone(di.parse_pretax({"list": []}))

    def test_annual_year_for(self):
        self.assertEqual(di.annual_years_for("2026-03-31"), [2025, 2024])
        self.assertEqual(di.annual_years_for("2026-06-30"), [2025, 2024])


class OpinionAndOpIncomeTest(unittest.TestCase):
    def test_parse_audit_opinion_prefers_current_year(self):
        js = {"list": [{"bsns_year": "제44기\n(당기)", "adt_opinion": "적정의견"}, {"bsns_year": "제43기\n(전기)", "adt_opinion": "한정의견"}]}
        self.assertEqual(di.parse_audit_opinion(js), "적정의견")
        self.assertIsNone(di.parse_audit_opinion({"list": []}))

    def test_parse_operating_income(self):
        js = {"list": [{"sj_div": "CIS", "account_nm": "영업이익(손실)", "thstrm_amount": "38,734,846,446"}]}
        self.assertEqual(di.parse_operating_income(js), 38_734_846_446)


class ParseSharesTest(unittest.TestCase):
    def test_shares(self):
        s = di.parse_shares(_js("dart_shares_sample.json"))
        self.assertEqual(s["common_issued"], 5_919_637_922)
        self.assertEqual(s["common_treasury"], 91_828_987)
        self.assertEqual(s["common_outstanding"], 5_827_808_935)
        self.assertEqual(s["pref_outstanding"], 802_371_203)

    def test_fetch_shares_falls_back_to_annual_when_quarterly_is_dash(self):
        from unittest import mock
        calls = []
        def fake_get(api_key, endpoint, **params):
            calls.append((params["bsns_year"], params["reprt_code"]))
            if params["reprt_code"] == "11014":
                return {"status": "000", "list": [{"se": "합계", "istc_totqy": "-", "tesstk_co": "-", "distb_stock_co": "-"}]}
            return _js("dart_shares_sample.json")
        with mock.patch.object(di, "_get", fake_get):
            s = di.fetch_shares("K", "C", 2025, "11014")
        self.assertEqual(s["common_outstanding"], 5_827_808_935)
        self.assertEqual(s["source"], "2025 11011")
        self.assertEqual(calls, [("2025", "11014"), ("2025", "11011")])

    def test_no_pref_gives_zero(self):
        s = di.parse_shares({"status": "000", "list": [{"se": "보통주", "istc_totqy": "100", "tesstk_co": "-", "distb_stock_co": "100"}]})
        self.assertEqual(s["pref_issued"], 0)
        self.assertEqual(s["common_treasury"], 0)
