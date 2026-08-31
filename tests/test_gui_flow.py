"""화면 흐름 스모크: 검색 → 선택 → 피어 로드(가짜 fetchers) → 요약 → 보고서. 네트워크 없음."""
import datetime as dt
import os, tempfile, unittest
from unittest import mock

import openpyxl


def _daily(start, closes):
    out, d = [], dt.date.fromisoformat(start)
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append((d.isoformat(), float(c)))
        d += dt.timedelta(days=1)
    return out


KIND = [
    {"name": "성광벤드", "market": "유가", "code": "014620", "industry": "기타 금속 가공제품 제조업", "products": "관이음쇠(피팅), 플랜지",
     "listed": "1997-11-14", "settle_month": "12월", "ceo": "", "homepage": "", "region": ""},
    {"name": "태광", "market": "코스닥", "code": "023160", "industry": "기타 금속 가공제품 제조업", "products": "관이음쇠(피팅)",
     "listed": "1994-10-07", "settle_month": "12월", "ceo": "", "homepage": "", "region": ""},
    {"name": "밸브스팩", "market": "코스닥", "code": "400000", "industry": "금융 지원 서비스업", "products": "밸브 기업 인수합병",
     "listed": "2025-06-01", "settle_month": "12월", "ceo": "", "homepage": "", "region": ""},
]
IDX = _daily("2024-01-01", [1000 + i for i in range(600)])
STK = _daily("2024-01-01", [100 + (i % 7) for i in range(600)])
FETCHERS = {
    "daily": lambda code, s, e: STK, "index": lambda s, e: IDX,
    "cap": lambda code, as_of: {"close": 10000.0, "cap": 1e7, "shares": 1000, "date": as_of},
    "corp_map": lambda: {"014620": "A", "023160": "B"},
    "company": lambda cc: {"corp_name": "x", "stock_code": "", "induty_code": "25919", "corp_cls": "Y"},
    "shares": lambda cc, y, r: {"common_issued": 1100, "common_treasury": 100, "common_outstanding": 1000,
                                "pref_issued": 0, "pref_treasury": 0, "pref_outstanding": 0},
    "bs": lambda cc, y, r: {"debt_items": [("단기차입금", 100), ("리스부채", 50)], "debt_total": 150, "nci": 0,
                            "total_liabilities": 1000, "other_fin_liab": 0, "flags": [], "rcept_no": "R", "fs_div": "CFS"},
}


KIND_PARMA = {"name": "한국파마", "market": "코스닥", "code": "032300", "industry": "의약품 제조업",
              "products": "완제의약품", "listed": "2020-08-10", "settle_month": "12월", "ceo": "", "homepage": "", "region": ""}


class SearchBoxTest(unittest.TestCase):
    """후보 표 검색창: 하이라이트 → 후보에 추가 → 일괄 선택 → 재검색에도 수동추가 유지."""

    def test_find_add_select(self):
        import market_data as md, settings
        tmp = tempfile.mkdtemp()
        with mock.patch.object(md, "load_kind_list", return_value=KIND + [KIND_PARMA]), \
             mock.patch("dart_inputs.check_key", return_value=(True, "정상")), \
             mock.patch.object(md, "krx_login", return_value=True), \
             mock.patch.object(md, "market_caps_all", return_value={}), \
             mock.patch.object(settings, "DOWNLOADS_DIR", tmp):
            import app as app_mod, candidate_panel
            with mock.patch.object(candidate_panel.CandidatePanel, "_fetch_target_ksic", lambda self, code: None):
                a = app_mod.PeerApp()
                a.fetchers = FETCHERS
                a.api_key = "K"
                for _ in range(20):
                    a.update()
                    if a.kind_rows:
                        break
                cp = a.candidate_panel
                cp.as_of_var.set("2026-03-31"); cp.kw_var.set("피팅, 밸브")
                cp.search(); a.update()
                self.assertEqual(len(a.candidates), 3)                    # 한국파마는 키워드 미적중
                cp.find_var.set("태광, 한국파마, 없는회사"); cp._on_find_typed()
                self.assertIn("found", cp.tree.item("023160", "tags"))
                self.assertNotIn("found", cp.tree.item("014620", "tags"))
                self.assertEqual([r["name"] for r in cp._addable], ["한국파마"])
                self.assertIn("없는회사", cp.find_label.cget("text"))
                cp.add_found(); a.update()
                self.assertIn("032300", cp.rows_state)
                self.assertIn("수동추가", cp.rows_state["032300"]["row"]["flags"])
                self.assertIn("found", cp.tree.item("032300", "tags"))    # 추가 직후 하이라이트 재적용
                cp.select_found()
                self.assertEqual(sorted(cp.selected_codes()), ["023160", "032300"])
                cp.search(); a.update()                                   # 재검색에도 수동추가·선택 유지
                self.assertIn("032300", [r["code"] for r in a.candidates])
                self.assertEqual(sorted(cp.selected_codes()), ["023160", "032300"])
                # 표 상한(MAX_ROWS) 초과분도 '이미 후보'로 분류 — '후보에 없음' 오분류·추가 무반응 방지
                with mock.patch.object(candidate_panel.CandidatePanel, "MAX_ROWS", 2):
                    cp.search(); a.update()
                    beyond = [r["code"] for r in a.candidates[2:]]
                    self.assertTrue(beyond)                               # 상한 밖 후보가 실제로 존재
                    cp.find_var.set(a.candidates[-1]["name"]); cp._on_find_typed()
                    self.assertIn(a.candidates[-1]["code"], cp._found)
                    self.assertEqual(cp._addable, [])
                    self.assertIn("표 밖", cp.find_label.cget("text"))
                a.destroy()


class KicpaAutoloadTest(unittest.TestCase):
    """한공회 파일을 한 번 열면 config.txt에 경로가 기억되고, 다음 실행 시 자동으로 로드된다."""

    def test_autoload_from_config_and_persist_on_open(self):
        import market_data as md, settings
        tmp = tempfile.mkdtemp()
        kfile = os.path.join(tmp, "한공회베타.xlsx")
        open(kfile, "w").close()
        cfgp = os.path.join(tmp, "config.txt")
        cfg = {"dart_api_key": "", "krx_id": "", "krx_pw": "", "kicpa_path": kfile}
        kbeta = {"014620": {"base_date": "2026-03-31", "close": 10050.0, "raw": 0.6, "adjusted": 0.73, "points": 104}}
        with mock.patch.object(md, "load_kind_list", return_value=KIND), \
             mock.patch("dart_inputs.check_key", return_value=(True, "정상")), \
             mock.patch.object(md, "krx_login", return_value=False), \
             mock.patch.object(settings, "CONFIG_PATH", cfgp), \
             mock.patch.object(settings, "load_config", return_value=dict(cfg)):
            import app as app_mod, candidate_panel, kicpa_beta
            with mock.patch.object(kicpa_beta, "load", return_value=dict(kbeta)), \
                 mock.patch.object(candidate_panel.CandidatePanel, "_fetch_target_ksic", lambda self, code: None):
                a = app_mod.PeerApp()
                for _ in range(20):
                    a.update()
                    if a.kicpa:
                        break
                self.assertIn("014620", a.kicpa)                          # 시작 시 자동 로드
                self.assertIn("한공회베타.xlsx", a.summary_panel.kicpa_label.cget("text"))
                # 처음 여는 파일이면 경로가 config 에 저장된다 (같은 경로면 저장 생략)
                a.cfg["kicpa_path"] = ""
                a.summary_panel._load_kicpa(kfile); a.update()
                self.assertEqual(settings._read_kv(cfgp).get("kicpa_path"), kfile)
                a.destroy()


class GuiFlowTest(unittest.TestCase):
    def test_flow(self):
        import market_data as md, settings
        tmp = tempfile.mkdtemp()
        with mock.patch.object(md, "load_kind_list", return_value=KIND), \
             mock.patch("dart_inputs.check_key", return_value=(True, "정상")), \
             mock.patch.object(md, "krx_login", return_value=True), \
             mock.patch.object(md, "market_caps_all", return_value={}), \
             mock.patch.object(settings, "DOWNLOADS_DIR", tmp):
            import app as app_mod, summary_panel, candidate_panel
            # mainloop 이 없는 테스트에선 백그라운드 스레드가 after() 를 못 부르므로 KSIC 조회는 무력화
            with mock.patch.object(summary_panel, "DOWNLOADS_DIR", tmp),                  mock.patch.object(candidate_panel.CandidatePanel, "_fetch_target_ksic", lambda self, code: None):
                a = app_mod.PeerApp()
                a.fetchers = FETCHERS
                a.api_key = "K"
                for _ in range(20):            # 시작 스레드가 kind_rows 를 채울 때까지
                    a.update()
                    if a.kind_rows:
                        break
                cp, sp = a.candidate_panel, a.summary_panel
                cp.name_var.set("성광"); cp._find_target()
                cp.match_box.selection_set(0); cp._on_pick_target(None)
                a.update()
                cp.as_of_var.set("2026-03-31"); cp.kw_var.set("피팅, 밸브")
                cp.search(); a.update()
                self.assertEqual(sorted(r["name"] for r in a.candidates), ["밸브스팩", "성광벤드", "태광"])
                self.assertEqual(a.candidates[-1]["name"], "밸브스팩")          # 스팩은 추천 제외 → 맨 아래
                self.assertTrue(a.candidates[0]["recommended"])
                self.assertIn("스팩", a.candidates[2]["flags"])
                for code in ("014620", "023160"):
                    cp.rows_state[code]["sel"].set(True); cp._on_select(code)
                cp.rows_state["400000"]["exc"].set(True); cp._on_exclude("400000")
                cp.rows_state["400000"]["reason"].set("스팩"); cp._on_reason("400000")
                self.assertEqual(sorted(cp.selected_codes()), ["014620", "023160"])
                cp.target_cap_var.set("20,000")                      # 대상 시총 2조 → SRP 1분위
                sp.net_assets_var.set("2300"); sp._on_net_assets()   # 순자산도 저장(시총이 우선)
                cp.fs_seg.set("12월말")                               # 재무 기준일: 직전 12월말(2025-12-31)
                a.krx_ok = True
                class _SyncPool:                          # 테스트에선 워커 스레드 없이 순차 실행
                    def __init__(self, *a, **k): pass
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                    def map(self, fn, it): return [fn(x) for x in it]
                with mock.patch.object(summary_panel, "ThreadPoolExecutor", _SyncPool), \
                     mock.patch.object(summary_panel.kofia, "market_rates", lambda as_of, log=None: {"date_used": as_of, "ktb10_final": 3.879, "ktb10_val": 3.877, "bbb_minus_5y": 10.46, "bbb_minus_3y": 9.961}):
                    sp._load_worker(cp.selected_codes())     # 스레드 대신 동기 호출
                a.update(); sp._after_load(); a.update()
                self.assertEqual(len(a.peers_loaded), 2)
                self.assertEqual(a.peers_loaded[0]["status"], "ok")
                sp.src_seg.set("산출(KRX)"); sp._on_source("산출(KRX)"); a.update()
                self.assertIn("βU 평균", sp.agg_label.cget("text"))
                # [정밀 추천]: DART 경량 조회로 재점수 — 흑자·매출유사 가점, 비적정 하드 제외
                cp.target_sales_var.set("100")
                a.fetchers = dict(a.fetchers,
                                  brief=lambda cc, y: {"sales": 500e8, "op_income": (10e8 if cc == "A" else -10e8),
                                                       "total_liab": 100e8, "total_equity": 100e8},
                                  audit=lambda cc, y: ("적정의견" if cc == "A" else "한정"))
                class _SyncThread0:
                    def __init__(self, target=None, args=(), daemon=None, **k): self._t = lambda: target(*args)
                    def start(self): self._t()
                # threading.Thread 전역 패치는 진짜 ThreadPoolExecutor 의 워커 생성까지 막아 큐 대기에 빠진다
                # → 풀도 동기 스텁으로 함께 패치
                with mock.patch.object(candidate_panel, "ThreadPoolExecutor", _SyncPool), \
                     mock.patch.object(candidate_panel.threading, "Thread", _SyncThread0):
                    cp.precise_recommend()
                a.update()
                by = {r["name"]: r for r in a.candidates}
                self.assertEqual(a.candidates[0]["name"], "성광벤드")
                self.assertIn("흑자+1", by["성광벤드"]["reason"]); self.assertIn("매출유사+2", by["성광벤드"]["reason"])
                self.assertIn("감사의견:한정", by["태광"]["flags"]); self.assertFalse(by["태광"]["recommended"])
                class _SyncThread:                        # 보고서 생성 스레드를 동기 실행
                    def __init__(self, target=None, daemon=None, **k): self._t = target
                    def start(self): self._t()
                with mock.patch("os.startfile", create=True), mock.patch("report._excel_recalc", return_value=True),                      mock.patch.object(summary_panel.threading, "Thread", _SyncThread):
                    sp.make_report()
                    a.update()
                path = os.path.join(tmp, "WACC피어_성광벤드_2026-03-31.xlsx")
                self.assertTrue(os.path.exists(path), sp.result_label.cget("text"))
                wb = openpyxl.load_workbook(path)
                self.assertEqual(wb["후보군"]["I4"].value, "스팩")        # 제외 사유
                self.assertEqual({wb["피어"]["A2"].value, wb["피어"]["A3"].value}, {"성광벤드", "태광"})   # 추천순 정렬이라 순서는 유동
                self.assertEqual(wb["요약"]["B4"].value, "산출")
                self.assertEqual(a.sess["target"]["cap_eok"], 20000)
                self.assertEqual(a.sess["target"]["net_assets_eok"], 2300)
                self.assertEqual(a.sess["fs_as_of"], "2025-12-31")
                self.assertEqual(wb["이자부부채 산정내역"]["C5"].value, "2025-12-31")
                self.assertAlmostEqual(wb["WACC"]["C18"].value, -0.0051)   # 시총 2조 → 1분위 -0.51%
                self.assertIn("1분위", wb["WACC"]["D18"].value)
                a.destroy()
