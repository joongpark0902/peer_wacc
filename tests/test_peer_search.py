import unittest

import peer_search as ps

ROWS = [
    {"name": "성광벤드", "market": "유가", "code": "014620", "industry": "기타 금속 가공제품 제조업",
     "products": "관이음쇠(피팅), 플랜지", "listed": "1997-11-14", "settle_month": "12월"},
    {"name": "키움제6호스팩", "market": "코스닥", "code": "413600", "industry": "금융 지원 서비스업",
     "products": "기업 인수합병", "listed": "2022-04-07", "settle_month": "12월"},
    {"name": "한국파마", "market": "코스닥", "code": "032300", "industry": "의약품 제조업",
     "products": "완제의약품(정신신경계)", "listed": "2020-08-10", "settle_month": "3월"},
    {"name": "해치텍", "market": "코스닥", "code": "0155E0", "industry": "반도체 제조업",
     "products": "지자기센서", "listed": "2026-08-25", "settle_month": "12월"},
    {"name": "밸브코", "market": "유가", "code": "999990", "industry": "밸브 제조업",
     "products": "산업용 VALVE", "listed": "2010-01-01", "settle_month": "12월"},
]


class ParseKeywordsTest(unittest.TestCase):
    def test_split_on_comma_and_whitespace(self):
        self.assertEqual(ps.parse_keywords("피팅, 플랜지  밸브,,"), ["피팅", "플랜지", "밸브"])


class SearchTest(unittest.TestCase):
    def test_keyword_or_match_on_products_and_industry_case_insensitive(self):
        out = ps.search(ROWS, ["피팅", "valve"], "2026-03-31")
        self.assertEqual([r["name"] for r in out], ["성광벤드", "밸브코"])
        self.assertEqual(out[0]["hits"], ["피팅"])
        self.assertEqual(out[1]["hits"], ["valve"])

    def test_industry_text_also_matches(self):
        out = ps.search(ROWS, ["의약품"], "2026-03-31")
        self.assertEqual([r["name"] for r in out], ["한국파마"])

    def test_flags(self):
        out = ps.search(ROWS, ["인수합병", "의약품", "센서"], "2024-04-05")
        by = {r["name"]: r["flags"] for r in out}
        self.assertIn(ps.FLAG_SPAC, by["키움제6호스팩"])
        self.assertIn(ps.FLAG_NEW, by["키움제6호스팩"])       # 2022-04-07 → 729일 (730일 미만)
        self.assertIn(ps.FLAG_NON_DEC, by["한국파마"])
        self.assertIn(ps.FLAG_TEMP, by["해치텍"])
        self.assertIn(ps.FLAG_NEW, by["해치텍"])

    def test_new_listing_boundary_exactly_730_days_is_not_flagged(self):
        out = ps.search(ROWS, ["인수합병"], "2024-04-05")   # 729일
        self.assertIn(ps.FLAG_NEW, out[0]["flags"])
        out = ps.search(ROWS, ["인수합병"], "2024-04-06")   # 정확히 730일 → 플래그 없음
        self.assertNotIn(ps.FLAG_NEW, out[0]["flags"])

    def test_market_and_cap_filters(self):
        caps = {"014620": 3_000e8, "999990": 500e8}
        out = ps.search(ROWS, ["피팅", "valve"], "2026-03-31", markets=["유가"], cap_min=1000, caps=caps)
        self.assertEqual([r["name"] for r in out], ["성광벤드"])
        self.assertEqual(out[0]["cap_eok"], 3000.0)

    def test_same_ksic_prefix3(self):
        rows = [dict(ROWS[0], ksic="25919"), dict(ROWS[4], ksic="28110")]
        out = ps.search(rows, ["피팅", "valve"], "2026-03-31", target_ksic="259")
        self.assertEqual([r["same_ksic"] for r in out], [True, False])
        self.assertEqual([r["ksic_level"] for r in out], [1, 0])
        out = ps.search(rows, ["피팅", "valve"], "2026-03-31", target_ksic="25919")
        self.assertEqual(out[0]["ksic_level"], 2)

    def test_ksic_codes_bring_in_rows_without_keyword_hit(self):
        rows = [dict(ROWS[0], ksic="25919"), dict(ROWS[4], ksic="29133")]
        out = ps.search(rows, [], "2026-03-31", ksic_codes=["C29133", "25100"])
        self.assertEqual([r["name"] for r in out], ["밸브코"]); self.assertEqual(out[0]["ksic_level"], 2)
        self.assertEqual(ps.ksic_level("25919", ksic_codes=["C25900"]), 1)   # 앞3자리 259 일치

    def test_exclude_keywords_and_cap_similarity(self):
        out = ps.search(ROWS, ["인수합병", "피팅"], "2026-03-31", exclude_keywords=["스팩", "인수합병"],
                        caps={"014620": 3_000e8, "413600": 100e8}, target_cap=1_000e8)
        by = {r["name"]: r for r in out}
        self.assertEqual(by["키움제6호스팩"]["neg_hits"], ["스팩", "인수합병"])
        self.assertTrue(by["성광벤드"]["cap_similar"]); self.assertFalse(by["키움제6호스팩"]["cap_similar"])
        self.assertLess(ps.score(by["키움제6호스팩"]), -100)
        self.assertEqual(ps.score(by["성광벤드"]), 2 + 2)          # 키워드 1개 + 시총 유사

    def test_industry_criterion_or_keywords(self):
        out = ps.search(ROWS, [], "2026-03-31", industry="기타 금속 가공제품 제조업")
        self.assertEqual([r["name"] for r in out], ["성광벤드"])
        self.assertTrue(out[0]["same_industry"])
        out = ps.search(ROWS, ["valve"], "2026-03-31", industry="기타 금속 가공제품 제조업")
        self.assertEqual([r["name"] for r in out], ["성광벤드", "밸브코"])
        self.assertFalse(out[1]["same_industry"])

    def test_reason_text(self):
        r = {"same_industry": True, "ksic_level": 1, "hits": ["피팅", "밸브"], "cap_similar": True, "neg_hits": [], "flags": [ps.FLAG_NEW]}
        self.assertEqual(ps.reason(r), "업종+3 · KSIC≈+1 · 키워드 2개(피팅,밸브)+4 · 시총유사+2 · 신규상장−5 = 5점")
        self.assertEqual(ps.rank([r])[0]["reason"], ps.reason(r))

    def test_rank_recommends_top5_and_never_spac(self):
        rows = [dict(name=f"c{i}", hits=["a"], flags=[], same_industry=False, same_ksic=False) for i in range(8)]
        rows[3].update(same_industry=True, same_ksic=True)          # 6점
        rows[5].update(flags=[ps.FLAG_SPAC], same_industry=True)    # 스팩 → 제외
        rows[6].update(same_industry=True)                          # 4점
        out = ps.rank(rows)
        self.assertEqual([r["name"] for r in out[:2]], ["c3", "c6"])
        self.assertTrue(all(r["recommended"] for r in out[:5]))
        self.assertFalse(any(r["recommended"] for r in out[5:]))
        self.assertEqual(out[-1]["name"], "c5"); self.assertFalse(out[-1]["recommended"])
        self.assertEqual(ps.rank([])[:], [])

    def test_duplicate_codes_collapsed(self):
        rows = ROWS + [dict(ROWS[0])]
        self.assertEqual(len(ps.search(rows, ["피팅"], "2026-03-31")), 1)

    def test_no_keywords_and_no_industry_returns_empty(self):
        self.assertEqual(ps.search(ROWS, [], "2026-03-31"), [])
        self.assertEqual(ps.search(ROWS, [], "2026-03-31", industry="  "), [])

    def test_listed_min_days_filter_drops_new(self):
        out = ps.search(ROWS, ["센서", "피팅"], "2026-09-01", listed_min_days=730)
        self.assertEqual([r["name"] for r in out], ["성광벤드"])


class FindNamesTest(unittest.TestCase):
    """검색창: 회사가 준 피어 리스트(쉼표·탭 구분)를 후보 표·전체 상장목록에서 찾기."""
    CANDS = ROWS[:2]                                     # 성광벤드 014620 · 키움제6호스팩 413600

    def test_matches_by_name_fragment_code_and_corp_prefix(self):
        m, add, miss = ps.find_names("성광, 032300, (주)키움제6호스팩", self.CANDS, ROWS)
        self.assertEqual(m, ["014620", "413600"])        # 이름 조각 · '(주)' 무시
        self.assertEqual([r["name"] for r in add], ["한국파마"])   # 코드로 찾음, 후보엔 없음 → 추가 가능
        self.assertEqual(miss, [])

    def test_missing_and_empty(self):
        m, add, miss = ps.find_names("없는회사", self.CANDS, ROWS)
        self.assertEqual((m, add, miss), ([], [], ["없는회사"]))
        self.assertEqual(ps.find_names("  ", self.CANDS, ROWS), ([], [], []))

    def test_dedup_and_tab_newline_split(self):
        m, add, miss = ps.find_names("성광\t성광벤드\n밸브", self.CANDS, ROWS)
        self.assertEqual(m, ["014620"])                  # 같은 회사 두 번 → 한 번
        self.assertEqual([r["name"] for r in add], ["밸브코"])

    def test_manual_row_carries_flags_and_no_score_keys(self):
        r = ps.manual_row(ROWS[2], "2026-03-31", caps={"032300": 1_234e8})
        self.assertIn(ps.FLAG_MANUAL, r["flags"])
        self.assertIn(ps.FLAG_NON_DEC, r["flags"])       # 3월 결산 플래그는 그대로
        self.assertEqual(r["cap_eok"], 1234.0)
        self.assertEqual((r["hits"], r["neg_hits"]), ([], []))
        self.assertFalse(r["same_industry"])
        self.assertEqual(ps.score(r), -1)                # 비12월 −1 외 가감 없음
