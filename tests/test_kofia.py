import unittest

import kofia

FINAL = """<?xml version="1.0" encoding="UTF-8"?><root><message><BISComDspDatListDTO>
<BISComDspDatDTO><val1>국고채권(10년)</val1><val2>9년6월~10년</val2><val3>3.864</val3><val4>3.879</val4></BISComDspDatDTO>
<BISComDspDatDTO><val1>회사채(무보증3년)BBB-</val1><val2>2년9월 ~ 3년</val2><val3>9.947</val3><val4>9.961</val4></BISComDspDatDTO>
<BISComDspDatDTO><val1>CD수익률(91일)</val1><val2>80일 ~ 100일</val2><val4>2.82</val4></BISComDspDatDTO>
</BISComDspDatListDTO></message></root>"""

def _row(cat, typ, grade, vals):
    v = "".join(f"<val{i}>{x}</val{i}>" for i, x in enumerate(vals, 1))
    return f"<BISBndSrtPrcDayDTO><largeCategoryMrk>{cat}</largeCategoryMrk><typeNmMrk>{typ}</typeNmMrk><creditRnkMrk>{grade}</creditRnkMrk>{v}</BISBndSrtPrcDayDTO>"

MATRIX = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><root><message><BISBndSrtPrcDayListDTO>"
          + _row("국채", "국고채권", "양곡,외평,재정", [2.644, 2.748, 2.857, 3.056, 3.240, 3.485, 3.508, 3.555, 3.745, 3.771, 3.814, 3.877, 3.899, 3.863, 3.770, 3.674])
          + _row("회사채 I(공모사채)", "무보증", "BBB-", [8.0, 8.5, 8.8, 9.0, 9.2, 9.5, 9.7, 9.961, 10.2, 10.46, 10.9, 11.3, 11.5, 11.6, 11.7, 11.8])
          + _row("회사채 I(공모사채)", "무보증", "AA-", [3.5, 3.6, 3.7, 3.8, 3.9, 4.0, 4.1, 4.166, 4.3, 4.4, 4.6, 4.8, 4.9, 5.0, 5.1, 5.2])
          + "</BISBndSrtPrcDayListDTO></message></root>")


class KofiaParseTest(unittest.TestCase):
    def test_final_quotes_take_day_value(self):
        q = kofia.parse_final_quotes(FINAL)
        self.assertEqual(q["국고채권(10년)"], 3.879)
        self.assertEqual(q["회사채(무보증3년)BBB-"], 9.961)

    def test_matrix_and_summary(self):
        m = kofia.parse_matrix(MATRIX)
        self.assertEqual(len(m), 3)
        self.assertEqual(kofia.pick(m, "회사채 I", "무보증", "BBB-")["5년"], 10.46)
        s = kofia.summarize(kofia.parse_final_quotes(FINAL), m, "2026-03-31")
        self.assertEqual(s["ktb10_final"], 3.879); self.assertEqual(s["ktb10_val"], 3.877)
        self.assertEqual(s["bbb_minus_5y"], 10.46); self.assertEqual(s["bbb_minus_3y"], 9.961); self.assertEqual(s["aa_minus_3y"], 4.166)
        self.assertEqual(s["date_used"], "2026-03-31")

    def test_market_rates_steps_back_over_holiday_and_caches(self):
        import tempfile, json, os
        from unittest import mock
        d = tempfile.mkdtemp()
        calls = []
        def fm(ymd, evaluator=kofia.EVAL_AVG):
            calls.append(ymd)
            return kofia.parse_matrix(MATRIX) if ymd == "20260327" else []
        with mock.patch.object(kofia, "fetch_matrix", fm), mock.patch.object(kofia, "fetch_final_quotes", lambda ymd: kofia.parse_final_quotes(FINAL)):
            r = kofia.market_rates("2026-03-29", cache_dir=d)          # 일요일 → 3/27(금)
        self.assertEqual(r["date_used"], "2026-03-27"); self.assertEqual(calls, ["20260327"])
        self.assertTrue(os.path.exists(os.path.join(d, "kofia_2026-03-29.json")))
        with mock.patch.object(kofia, "fetch_matrix", side_effect=AssertionError("cached!")):
            self.assertEqual(kofia.market_rates("2026-03-29", cache_dir=d)["bbb_minus_5y"], 10.46)

    def test_market_rates_keeps_raw_tables_and_refreshes_old_cache(self):
        import tempfile, json, os
        from unittest import mock
        d = tempfile.mkdtemp()
        fm = lambda ymd, evaluator=kofia.EVAL_AVG: kofia.parse_matrix(MATRIX)
        ff = lambda ymd: kofia.parse_final_quotes(FINAL)
        with mock.patch.object(kofia, "fetch_matrix", fm), mock.patch.object(kofia, "fetch_final_quotes", ff):
            r = kofia.market_rates("2026-03-27", cache_dir=d)
        self.assertEqual(r["final_quotes"]["국고채권(10년)"], 3.879)
        self.assertEqual(kofia.pick(r["matrix"], "회사채 I", "무보증", "BBB-")["5년"], 10.46)
        # 캐시 재로드 후에도 원자료 유지
        r2 = kofia.market_rates("2026-03-27", cache_dir=d)
        self.assertEqual(kofia.pick(r2["matrix"], "회사채 I", "무보증", "BBB-")["5년"], 10.46)
        # 구버전 캐시(원자료 없음)는 무시하고 다시 받아온다
        with open(os.path.join(d, "kofia_2026-03-26.json"), "w", encoding="utf-8") as f:
            json.dump({"date_used": "2026-03-26", "bbb_minus_5y": 10.46}, f)
        with mock.patch.object(kofia, "fetch_matrix", fm), mock.patch.object(kofia, "fetch_final_quotes", ff):
            r3 = kofia.market_rates("2026-03-26", cache_dir=d)
        self.assertIn("matrix", r3)
