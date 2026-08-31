"""DART OpenAPI 입력값: 산업분류코드, 주식총수, 재무상태표(이자부부채·비지배지분).

파서(parse_*)는 JSON dict 만 받는 순수 함수라 fixture 로 테스트한다.
fetch_* 는 네트워크. 이자부부채는 계정명 규칙으로 잡으므로 '기타금융부채'에
숨은 차입은 못 본다 — 총부채의 5% 이상이면 확인필요 플래그를 단다.
"""
import datetime as _dt
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile

import requests

from settings import APP_DIR, CACHE_DIR

_BASE = "https://opendart.fss.or.kr/api/"
_DOWNLOADER_CORPCODE = os.path.join(os.path.dirname(APP_DIR), "dart_downloader", "CORPCODE.xml")

DEBT_KEYWORDS = ("차입금", "사채", "리스부채", "유동성장기부채")   # 계정명에 이 중 하나가 들어가면 이자부부채
_DEBT_EXCLUDE = ("매입채무", "미지급", "예수", "충당", "사채발행비", "할인발행차금")
_FIN_LIAB_KEYWORDS = ("금융부채",)                       # 차입금·리스로 안 잡힌 금융부채 → 확인필요 풀
OTHER_FIN_THRESHOLD = 0.05


def _amt(v):
    s = str(v or "").replace(",", "").strip()
    if s in ("", "-"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def report_for(as_of):
    """기준일 직전에 확정·공시된 보고서 (사업연도, reprt_code)."""
    y, m = int(as_of[:4]), int(as_of[5:7])
    if m <= 3:
        return y - 1, "11014"
    if m <= 5:
        return y - 1, "11011"
    if m <= 8:
        return y, "11013"
    if m <= 11:
        return y, "11012"
    return y, "11014"


def _get(api_key, endpoint, **params):
    r = requests.get(_BASE + endpoint, params=dict(crtfc_key=api_key, **params), timeout=30)
    r.raise_for_status()
    return r.json()


# ── 회사코드 맵 ─────────────────────────────────────────────────────────────

_CORP_MAP_CACHE = {}


def load_corp_map(api_key=None):
    """{종목코드: corp_code}. dart_downloader의 CORPCODE.xml 재사용, 없으면 받아 캐시.
    30MB XML 파싱이라 프로세스 안에서 한 번만 한다."""
    if "map" in _CORP_MAP_CACHE:
        return _CORP_MAP_CACHE["map"]
    path = _DOWNLOADER_CORPCODE
    if not os.path.exists(path):
        path = os.path.join(CACHE_DIR, "CORPCODE.xml")
        if not os.path.exists(path):
            os.makedirs(CACHE_DIR, exist_ok=True)
            r = requests.get(_BASE + "corpCode.xml", params={"crtfc_key": api_key}, timeout=60)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                with open(path, "wb") as f:
                    f.write(z.read(z.namelist()[0]))
    out = {}
    for el in ET.parse(path).getroot().iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            out[sc] = el.findtext("corp_code")
    _CORP_MAP_CACHE["map"] = out
    return out


def check_key(api_key):
    """인증키 유효성. (ok, 메시지). 삼성전자 company.json 1회 호출."""
    if not api_key:
        return False, "DART 인증키 없음"
    try:
        js = _get(api_key, "company.json", corp_code="00126380")
    except Exception as e:
        return False, f"DART 접속 실패: {e}"
    return js.get("status") == "000", js.get("message", "")


def fetch_company(api_key, corp_code):
    js = _get(api_key, "company.json", corp_code=corp_code)
    return {k: js.get(k) for k in ("corp_name", "stock_code", "induty_code", "corp_cls")}


# ── 주식총수 ─────────────────────────────────────────────────────────────────

def parse_shares(js):
    out = {"common_issued": 0, "common_treasury": 0, "common_outstanding": 0,
           "pref_issued": 0, "pref_treasury": 0, "pref_outstanding": 0}
    for row in js.get("list", []):
        se = (row.get("se") or "").replace(" ", "")
        key = "common" if se.startswith("보통주") else "pref" if se.startswith("우선주") else None
        if key:
            out[f"{key}_issued"] = _amt(row.get("istc_totqy"))
            out[f"{key}_treasury"] = _amt(row.get("tesstk_co"))
            out[f"{key}_outstanding"] = _amt(row.get("distb_stock_co"))
    return out


def fetch_shares(api_key, corp_code, year, reprt_code):
    """주식총수. 분·반기보고서(11012~11014)는 DART가 '-'만 주는 회사가 많아
    같은 해 → 전년 사업보고서(11011) 순으로 폴백한다. 결과에 `source`("YYYY reprt") 기록."""
    tries = [(year, reprt_code)]
    if reprt_code != "11011":
        tries += [(year, "11011"), (year - 1, "11011")]
    else:
        tries += [(year - 1, "11011")]
    last = None
    for y, rc in tries:
        last = parse_shares(_get(api_key, "stockTotqySttus.json", corp_code=corp_code,
                                 bsns_year=str(y), reprt_code=rc))
        if last["common_outstanding"] > 0:
            last["source"] = f"{y} {rc}"
            return last
    last["source"] = "없음"
    return last


# ── 재무상태표 ───────────────────────────────────────────────────────────────

_PAREN = re.compile(r"\(.*?\)")


def _is_debt(nm):
    """괄호 안 문구('(사채 제외)' 등)는 빼고 판정한다."""
    n = _PAREN.sub("", nm).replace(" ", "")
    return any(k in n for k in DEBT_KEYWORDS) and not any(x in n for x in _DEBT_EXCLUDE)


_LIAB_AGG = ("유동부채", "비유동부채", "부채총계", "부채및자본총계", "자본과부채총계")


def report_candidates(as_of):
    """기간말이 기준일 이하인 보고서를 최신순으로 (사업연도, reprt_code) 최대 4개.
    예: 2026-03-31 → [(2026,'11013'), (2025,'11011'), (2025,'11014'), (2025,'11012')]"""
    d = _dt.date.fromisoformat(as_of)
    ends = []
    for y in (d.year, d.year - 1):
        ends += [(_dt.date(y, 12, 31), (y, "11011")), (_dt.date(y, 9, 30), (y, "11014")),
                 (_dt.date(y, 6, 30), (y, "11012")), (_dt.date(y, 3, 31), (y, "11013"))]
    ends = sorted((e for e in ends if e[0] <= d), key=lambda e: e[0], reverse=True)
    return [e[1] for e in ends[:4]]


def parse_bs(js):
    bs = [x for x in js.get("list", []) if x.get("sj_div") == "BS"]
    items, liab_items, cash_items, total_liab, nci, other = [], [], [], 0, 0, 0
    for x in bs:
        nm = (x.get("account_nm") or "").strip()
        amt = _amt(x.get("thstrm_amount"))
        n = nm.replace(" ", "")
        if "현금및현금성자산" in n and "총" not in n:
            cash_items.append({"name": nm, "amount": amt, "kind": "현금및현금성자산"})
            continue
        if ("단기금융상품" in n or "단기금융자산" in n) and "부채" not in n:
            cash_items.append({"name": nm, "amount": amt, "kind": "단기금융상품"})
            continue
        if n == "부채총계":
            total_liab = amt
            continue
        if n == "비지배지분":
            nci = amt
            continue
        is_debt = _is_debt(nm)
        if is_debt:
            items.append((nm, amt))
        elif any(k in n for k in _FIN_LIAB_KEYWORDS):
            other += amt
        # 부채 상세(사람이 포함 여부를 판단할 후보): 부채 성격 계정 전부, 합계 항목 제외
        if ("부채" in n or is_debt) and "자본" not in n and n not in _LIAB_AGG:
            liab_items.append({"name": nm, "amount": amt, "default": is_debt})
    flags = []
    if total_liab and other / total_liab >= OTHER_FIN_THRESHOLD:
        flags.append(f"확인필요:금융부채 {other / total_liab:.0%}")
    return {"debt_items": items, "debt_total": sum(a for _, a in items), "nci": nci,
            "total_liabilities": total_liab, "other_fin_liab": other, "flags": flags,
            "liab_items": liab_items, "cash_items": cash_items,
            "rcept_no": bs[0].get("rcept_no") if bs else None, "fs_div": None}


def annual_years_for(as_of):
    """세전이익을 찾을 사업연도 후보: 전년(사업보고서가 이미 나왔으면) → 전전년."""
    y = int(as_of[:4])
    return [y - 1, y - 2]


def parse_pretax(js):
    """손익계산서의 법인세비용차감전순이익(손실). 없으면 None. IS 우선, 없으면 CIS."""
    for div in ("IS", "CIS"):
        for x in js.get("list", []):
            if x.get("sj_div") != div:
                continue
            n = (x.get("account_nm") or "").replace(" ", "")
            if (n.startswith("법인세비용차감전") or n.startswith("법인세차감전")) and "이익" in n and "기타포괄" not in n:
                return _amt(x.get("thstrm_amount"))
    return None


def fetch_pretax(api_key, corp_code, year, fs_div="CFS"):
    js = _get(api_key, "fnlttSinglAcntAll.json", corp_code=corp_code,
              bsns_year=str(year), reprt_code="11011", fs_div=fs_div)
    if js.get("status") == "013" and fs_div == "CFS":
        return fetch_pretax(api_key, corp_code, year, "OFS")
    if js.get("status") != "000":
        raise RuntimeError(f"DART {js.get('status')}: {js.get('message')}")
    return parse_pretax(js)


def parse_operating_income(js):
    """손익계산서 영업이익(손실). IS 우선, 없으면 CIS."""
    for div in ("IS", "CIS"):
        for x in js.get("list", []):
            if x.get("sj_div") != div:
                continue
            n = (x.get("account_nm") or "").replace(" ", "")
            if n.startswith("영업이익") or n == "영업손익":
                return _amt(x.get("thstrm_amount"))
    return None


def fetch_operating_income(api_key, corp_code, year, fs_div="CFS"):
    js = _get(api_key, "fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year), reprt_code="11011", fs_div=fs_div)
    if js.get("status") == "013" and fs_div == "CFS":
        return fetch_operating_income(api_key, corp_code, year, "OFS")
    if js.get("status") != "000":
        raise RuntimeError(f"DART {js.get('status')}: {js.get('message')}")
    return parse_operating_income(js)


_ACC_PREFIX = re.compile(r"^[IVX0-9]+\.\s*")             # 'I. 매출액' → '매출액'
_SALES_NAMES = ("매출액", "수익(매출액)", "영업수익", "매출")


def parse_brief(js):
    """[정밀 추천]용 경량 요약 — 한 fnlttSinglAcntAll 응답에서 매출액·영업이익·부채총계·자본총계.
    매출은 sj_div IS→CIS 한정('매출' 접두 검색은 BS 매출채권 오매칭)."""
    sales = op = liab = eq = None
    for div in ("IS", "CIS"):
        for x in js.get("list", []):
            if x.get("sj_div") != div:
                continue
            n = _ACC_PREFIX.sub("", (x.get("account_nm") or "").strip()).replace(" ", "")
            if sales is None and n in _SALES_NAMES:
                sales = _amt(x.get("thstrm_amount"))
            if op is None and (n.startswith(("영업이익", "영업손실")) or n == "영업손익"):
                op = _amt(x.get("thstrm_amount"))
        if sales is not None and op is not None:
            break
    for x in js.get("list", []):
        if x.get("sj_div") != "BS":
            continue
        n = (x.get("account_nm") or "").replace(" ", "")
        if n == "부채총계":
            liab = _amt(x.get("thstrm_amount"))
        elif n == "자본총계":
            eq = _amt(x.get("thstrm_amount"))
    return {"sales": sales, "op_income": op, "total_liab": liab, "total_equity": eq}


def fetch_brief(api_key, corp_code, year, fs_div="CFS"):
    js = _get(api_key, "fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year), reprt_code="11011", fs_div=fs_div)
    if js.get("status") == "013" and fs_div == "CFS":
        return fetch_brief(api_key, corp_code, year, "OFS")
    if js.get("status") != "000":
        raise RuntimeError(f"DART {js.get('status')}: {js.get('message')}")
    return parse_brief(js)


def parse_audit_opinion(js):
    """최근 사업연도(당기) 감사의견 문자열. 없으면 None."""
    for x in js.get("list", []):
        if "당기" in (x.get("bsns_year") or "") or len(js.get("list", [])) == 1:
            return (x.get("adt_opinion") or "").strip() or None
    rows = js.get("list", [])
    return (rows[0].get("adt_opinion") or "").strip() if rows else None


def fetch_audit_opinion(api_key, corp_code, year):
    js = _get(api_key, "accnutAdtorNmNdAdtOpinion.json", corp_code=corp_code, bsns_year=str(year), reprt_code="11011")
    if js.get("status") != "000":
        return None
    return parse_audit_opinion(js)


def fetch_bs(api_key, corp_code, year, reprt_code, fs_div="CFS"):
    js = _get(api_key, "fnlttSinglAcntAll.json", corp_code=corp_code,
              bsns_year=str(year), reprt_code=reprt_code, fs_div=fs_div)
    if js.get("status") == "013" and fs_div == "CFS":
        return fetch_bs(api_key, corp_code, year, reprt_code, "OFS")
    if js.get("status") != "000":
        raise RuntimeError(f"DART {js.get('status')}: {js.get('message')}")
    out = parse_bs(js)
    out["fs_div"] = fs_div
    return out
