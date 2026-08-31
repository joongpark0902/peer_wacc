"""화면과 무관한 조립 로직: 피어 1개 로드 → 주간 정렬 → 요약 → 보고서 data.

네트워크는 fetchers dict 로 주입해 테스트에서 가짜 함수를 넣는다.
"""
import re

import beta as B
import dart_inputs as di
import market_data as md
import tax as T

_PAREN = re.compile(r"\(.*?\)")

# (계정명 포함문자열 → 보고서 열). 앞에서부터 첫 일치. 나머지 → 기타
DEBT_MAP = [("리스", "리스부채"), ("사채", "사채"), ("유동성장기", "유동성장기부채"),
            ("비유동", "장기차입금"), ("장기차입금", "장기차입금"), ("장기", "장기차입금"),
            ("차입금", "단기차입금")]

_REPORT_NAMES = {"11011": "사업보고서", "11012": "반기보고서", "11013": "1분기보고서", "11014": "3분기보고서"}


def report_label(year, reprt):
    return f"{year} {_REPORT_NAMES.get(reprt, reprt)}"


def fs_quarter_end(as_of, month):
    """재무 기준일: 기준일 이하의 가장 최근 month(3·6·9·12)월말. month 가 None 이면 None(자동 = 기준일)."""
    if not month:
        return None
    import calendar
    import datetime as _dt
    d = _dt.date.fromisoformat(as_of)
    for y in (d.year, d.year - 1):
        q = _dt.date(y, month, calendar.monthrange(y, month)[1])
        if q <= d:
            return q.isoformat()
    return None


def default_fetchers(api_key):
    return {
        "daily": md.daily_closes,
        "index": lambda s, e: md.index_closes(s, e),
        "cap": md.market_cap,
        "corp_map": lambda: di.load_corp_map(api_key),
        "company": lambda cc: di.fetch_company(api_key, cc),
        "shares": lambda cc, y, r: di.fetch_shares(api_key, cc, y, r),
        "bs": lambda cc, y, r: di.fetch_bs(api_key, cc, y, r),
        "pretax": lambda cc, y: di.fetch_pretax(api_key, cc, y),
        "audit": lambda cc, y: di.fetch_audit_opinion(api_key, cc, y),
        "opinc": lambda cc, y: di.fetch_operating_income(api_key, cc, y),
    }


def _bucket_debt(items):
    out = {"단기차입금": 0, "유동성장기부채": 0, "장기차입금": 0, "사채": 0, "리스부채": 0, "기타": 0}
    for nm, amt in items:
        n = _PAREN.sub("", nm).replace(" ", "")      # '(사채 제외)' 같은 괄호는 분류에서 제외
        for key, col in DEBT_MAP:
            if key in n:
                out[col] += amt
                break
        else:
            out["기타"] += amt
    return out


def apply_debt_selection(p, include_map=None):
    """부채 상세(liab_items)의 포함 여부로 p['debt'] 버킷을 다시 계산한다.
    include_map: {계정명: bool} — 없으면 규칙 판정(default)을 쓴다."""
    include_map = include_map or {}
    chosen = []
    for it in p.get("liab_items", []):
        it["include"] = bool(include_map.get(it["name"], it["default"]))
        if it["include"]:
            chosen.append((it["name"], it["amount"]))
    p["debt"] = _bucket_debt(chosen)
    return p


def load_peer(code, kind_row, as_of, fetchers, *, tax=B.DEFAULT_TAX, kicpa=None, log=print, tax_override=None,
              debt_override=None, fs_as_of=None):
    """tax: 대상 세율(결손·조회실패 시 폴백). tax_override: 사용자가 피어별로 직접 지정한 세율(있으면 우선).
    debt_override: {계정명: bool} 부채 항목 포함 여부(사용자 판단).
    fs_as_of: 재무 기준일 — 주가·종가는 as_of, 재무제표는 이 날짜 이하 최신 보고서(None 이면 as_of와 동일)."""
    p = {"name": kind_row.get("name", code), "code": code, "market": kind_row.get("market", ""), "ksic": "",
         "close_krx": None, "close_kicpa": None, "common_out": 0, "pref_out": 0, "nci": 0,
         "debt": _bucket_debt([]), "tax": tax, "include": False, "flags": [], "rcept_no": None,
         "report_label": "", "fs_div": None, "kicpa": None, "daily": [], "weekly": [],
         "pretax": None, "pretax_year": None, "tax_basis": "대상세율(기본)", "liab_items": [], "cash_items": [],
         "audit_opinion": None, "op_income": None,
         "beta_calc": {"raw": None, "r2": None, "n": 0, "blume": None}, "status": "failed"}
    ok_px = ok_fin = False
    start, end = md.window_for(as_of)
    # 1) 주가
    try:
        p["daily"] = fetchers["daily"](code, start, end)
        p["weekly"] = B.weekly_closes(p["daily"], as_of)
        # 기준일 종가 = 일별 시세에서 기준일 이하 마지막 거래일 (KRX 시가총액 호출은 4초/종목이라 쓰지 않는다)
        last = [(d_, c_) for d_, c_ in p["daily"] if d_ <= as_of]
        if not last:
            raise md.MarketDataError(f"기준일 이전 시세 없음: {code}")
        p["close_krx"], p["close_date"] = last[-1][1], last[-1][0]
        ok_px = True
    except Exception as e:
        p["flags"].append(f"KRX 시세 없음: {e}")
        log(f"[{code}] 시세 실패: {e}")
    # 2) DART
    try:
        cc = fetchers["corp_map"]().get(code)
        if not cc:
            raise RuntimeError("corp_code 없음")
        comp = fetchers["company"](cc)
        p["ksic"] = comp.get("induty_code") or ""
        # 기간말이 재무 기준일 이하인 최신 보고서부터 시도 (예: 3/31 기준이면 1분기보고서 → 없으면 전년 사업보고서)
        bs, year, reprt, last_err = None, None, None, None
        for year, reprt in di.report_candidates(fs_as_of or as_of):
            try:
                bs = fetchers["bs"](cc, year, reprt)
                break
            except Exception as e:
                last_err = e
        if bs is None:
            raise RuntimeError(f"재무상태표 없음 ({last_err})")
        sh = fetchers["shares"](cc, year, reprt)
        p["common_out"], p["pref_out"] = sh["common_outstanding"], sh["pref_outstanding"]
        p["liab_items"] = [dict(it) for it in bs.get("liab_items", [])]
        p["cash_items"] = [dict(it) for it in bs.get("cash_items", [])]
        apply_debt_selection(p, debt_override)
        p["nci"] = bs["nci"]
        p["rcept_no"], p["fs_div"] = bs.get("rcept_no"), bs.get("fs_div")
        p["report_label"] = report_label(year, reprt)
        p["flags"].extend(bs.get("flags", []))
        ok_fin = True
        # 피어별 한계세율: 최신 사업보고서 세전이익(과표 대용) → 구간
        try:
            pre, ay = None, None
            for ay in di.annual_years_for(as_of):
                try:
                    pre = fetchers["pretax"](cc, ay) if "pretax" in fetchers else None
                except Exception:
                    pre = None
                if pre is not None:
                    break
            p["pretax"], p["pretax_year"] = pre, ay
            rate, label = T.marginal_rate(pre, year=int(as_of[:4]))
            if rate is None:
                p["tax_basis"] = f"{ay} 세전이익 {label} → 대상세율"
                p["flags"].append("세율:결손→대상세율")
            else:
                p["tax"], p["tax_basis"] = rate, f"{ay} 세전이익 {label} 한계세율"
        except Exception as e:
            p["tax_basis"] = f"세전이익 조회 실패 → 대상세율 ({e})"
            log(f"[{code}] 세전이익 실패: {e}")
        # 참고 플래그(soft): 감사의견·영업이익 — 추천 점수엔 안 넣고 표시만 한다
        for ay in di.annual_years_for(as_of):
            try:
                op = fetchers["audit"](cc, ay) if "audit" in fetchers else None
            except Exception:
                op = None
            if op:
                p["audit_opinion"] = op
                if not op.startswith("적정"):
                    p["flags"].append(f"감사의견:{op}")
                break
        for ay in di.annual_years_for(as_of):
            try:
                oi = fetchers["opinc"](cc, ay) if "opinc" in fetchers else None
            except Exception:
                oi = None
            if oi is not None:
                p["op_income"] = oi
                if oi < 0:
                    p["flags"].append(f"영업적자(FY{ay})")
                break
    except Exception as e:
        p["flags"].append(f"DART 재무 없음: {e}")
        log(f"[{code}] DART 실패: {e}")
    # 3) 한공회
    if kicpa:
        p["kicpa"] = {k: kicpa.get(k) for k in ("base_date", "close", "raw", "adjusted", "points")}
        p["close_kicpa"] = kicpa.get("close")
        p["flags"].extend(kicpa.get("flags", []))
    if tax_override is not None:
        p["tax"], p["tax_basis"] = tax_override, "사용자 지정"
    p["status"] = "ok" if ok_px and ok_fin else "partial" if (ok_px or ok_fin) else "failed"
    p["include"] = ok_px and ok_fin
    if ok_px:
        try:
            compute_betas([p], fetchers["index"](start, end), as_of)
        except Exception as e:
            p["flags"].append(f"지수 없음: {e}")
            p["include"] = False
    return p


def _index_weekly(index_daily, as_of):
    return B.weekly_closes(index_daily, as_of)


def compute_betas(peers, index_daily, as_of):
    """각 피어의 beta_calc 를 지수 주간수익률로 채운다(제자리 수정)."""
    idx_rets = B.returns(_index_weekly(index_daily, as_of))
    for p in peers:
        if not p["weekly"]:
            continue
        r = B.regress(B.returns(p["weekly"]), idx_rets)
        p["beta_calc"] = dict(r, blume=B.blume(r["raw"]))
        if r["n"] < B.MIN_POINTS and "관측치부족" not in p["flags"]:
            p["flags"].append("관측치부족")
            p["include"] = False
    return peers


def weekly_table(peers, index_daily, as_of):
    wk = _index_weekly(index_daily, as_of)
    dates = [d for d, _ in wk]
    idx = [c for _, c in wk]
    table = {}
    for p in peers:
        wmap = {}
        for d, c in p["weekly"]:
            wmap[B._week_key(d)] = c
        table[p["code"]] = [wmap.get(B._week_key(d)) for d in dates]
    return dates, idx, table


def summarize(peers, *, beta_source, de_method, tax_target, include_lease=True):
    rows = []
    for p in peers:
        e = (p["close_krx"] or 0) * (p["common_out"] + p["pref_out"]) + p["nci"]
        if beta_source == "kicpa" and p.get("kicpa") and p["close_kicpa"]:
            e = p["close_kicpa"] * (p["common_out"] + p["pref_out"]) + p["nci"]
        d = sum(v for k, v in p["debt"].items() if include_lease or k != "리스부채")
        de = d / e if e else None
        if beta_source == "kicpa":
            bl = (p.get("kicpa") or {}).get("adjusted")
            flags = list(p["flags"]) + ([] if bl is not None else ["한공회 없음"])
        else:
            bl = p["beta_calc"].get("blume")
            flags = list(p["flags"])
        bu = B.unlever(bl, de, p["tax"]) if (bl is not None and de is not None) else None
        include = bool(p["include"]) and bu is not None
        rows.append({"name": p["name"], "code": p["code"], "close": p["close_kicpa"] if beta_source == "kicpa" and p["close_kicpa"] else p["close_krx"],
                     "e": e, "d": d, "de": de, "tax": p["tax"],
                     "beta_raw": p["beta_calc"].get("raw"), "beta_blume": p["beta_calc"].get("blume"),
                     "beta_n": p["beta_calc"].get("n"), "beta_r2": p["beta_calc"].get("r2"),
                     "kicpa_raw": (p.get("kicpa") or {}).get("raw"), "kicpa_adj": (p.get("kicpa") or {}).get("adjusted"),
                     "kicpa_points": (p.get("kicpa") or {}).get("points"),
                     "beta_l_used": bl, "beta_u": bu, "include": include, "flags": flags, "status": p["status"]})
    agg = B.aggregate(rows, method=de_method, tax_target=tax_target)
    return rows, agg


def build_report_data(sess, candidates, peers, index_daily, query_date, window, notes, rates=None):
    as_of = sess["as_of"]
    dates, idx, table = weekly_table(peers, index_daily, as_of)
    out_peers = []
    for p in peers:
        q = {k: p[k] for k in ("name", "code", "ksic", "market", "close_krx", "close_kicpa", "common_out", "pref_out",
                                "nci", "debt", "tax", "include", "flags", "rcept_no", "report_label", "fs_div", "kicpa",
                                "pretax", "tax_basis", "liab_items", "cash_items", "audit_opinion", "op_income")}
        out_peers.append(q)
    return {"target": dict(sess["target"]), "as_of": as_of, "fs_as_of": sess.get("fs_as_of"),
            "beta_source": sess["beta_source"],
            "include_lease": bool(sess.get("include_lease", True)),
            "de_method": sess["de_method"], "tax_target": sess["tax_target"], "keywords": list(sess["keywords"]),
            "query_date": query_date, "window": window, "candidates": candidates, "peers": out_peers,
            "weekly_dates": dates, "weekly_index": idx, "weekly": table, "notes": list(notes),
            "rates": dict(rates) if rates else None}
