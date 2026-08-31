"""시장 데이터: KIND 상장사 목록, KRX 주가·지수 (로그인 세션).

KIND 목록은 `corpList.do?method=download` 가 주는 EUC-KR HTML 표다(확장자만 xls).
표준 html.parser로 읽어 pandas 의존 없이 처리한다.
"""
import datetime as dt
import json
import os
from html.parser import HTMLParser

import requests

from settings import CACHE_DIR

KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
_UA = {"User-Agent": "Mozilla/5.0"}
_KIND_KEYS = ["name", "market", "code", "industry", "products",
              "listed", "settle_month", "ceo", "homepage", "region"]


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in_cell = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell, self._cell = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def parse_kind_html(raw):
    """KIND 다운로드 바이트 → 상장사 dict 목록. 첫 행(헤더)은 버린다."""
    text = raw.decode("euc-kr", errors="replace")
    p = _TableParser()
    p.feed(text)
    out = []
    for cells in p.rows[1:]:
        if len(cells) < 10:
            continue
        out.append(dict(zip(_KIND_KEYS, cells[:10])))
    return out


def _fetch_kind_bytes():
    r = requests.get(KIND_URL, params={"method": "download", "searchType": "13"},
                     headers=_UA, timeout=60)
    r.raise_for_status()
    return r.content


def _today():
    return dt.date.today().strftime("%Y%m%d")


def load_kind_list(force=False):
    """당일 캐시가 있으면 캐시, 없으면 KIND에서 받아 캐시에 쓴다."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"kind_list_{_today()}.json")
    if not force and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    rows = parse_kind_html(_fetch_kind_bytes())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows

# ── KRX 정보데이터시스템 (로그인 필요) ──────────────────────────────────────

last_error = ""
_KRX_LOCK = __import__("threading").Lock()     # KRX 세션은 동시 요청에 취약 → 직렬화
_KRX_CRED = {"id": "", "pw": ""}


class MarketDataError(Exception):
    pass


def _install_default_timeout():
    """pykrx 는 requests 에 timeout 을 주지 않아 KRX 가 응답을 안 주면 앱이 멈춘다. 기본 30초를 심는다."""
    import requests
    if getattr(requests.Session.request, "_peer_wacc_timeout", False):
        return
    orig = requests.Session.request

    def request(self, method, url, **kw):
        kw.setdefault("timeout", 30)
        return orig(self, method, url, **kw)
    request._peer_wacc_timeout = True
    requests.Session.request = request


_install_default_timeout()


def _krx_call(fn, *args):
    """KRX 호출 직렬화 + 세션 끊김('Expecting value'·LOGOUT)이면 재로그인 후 1회 재시도."""
    global last_error
    with _KRX_LOCK:
        for attempt in (1, 2):
            try:
                return fn(*args)
            except Exception as e:
                msg = str(e)
                if attempt == 1 and ("Expecting value" in msg or "LOGOUT" in msg or "지수명" in msg or "종가" in msg):
                    if _KRX_CRED["id"] and krx_login(_KRX_CRED["id"], _KRX_CRED["pw"], _locked=True):
                        continue
                raise


def krx_login(krx_id, krx_pw, _locked=False):
    """pykrx 전역 세션에 로그인 세션을 심는다. 성공 True."""
    global last_error
    _KRX_CRED.update(id=krx_id or "", pw=krx_pw or "")
    if not (krx_id and krx_pw):
        last_error = "KRX 계정이 설정되지 않았습니다 (config.txt의 krx_id/krx_pw)."
        return False
    try:
        os.environ["KRX_ID"], os.environ["KRX_PW"] = krx_id, krx_pw     # 만료 시 자동 재로그인용
        from pykrx.website.comm.auth import build_krx_session, set_auth_session
        sess = build_krx_session(krx_id, krx_pw)
        if sess is None or not sess.is_authenticated:
            last_error = "KRX 로그인 실패 — 아이디/비밀번호 또는 비밀번호 변경 요구(CD010)를 확인하세요."
            return False
        set_auth_session(sess)
        last_error = ""
        return True
    except Exception as e:               # 네트워크·파싱 등
        last_error = f"KRX 로그인 오류: {e}"
        return False


def _krx_ohlcv(start, end, code):
    from pykrx.website import krx            # 네이버 폴백 없는 내부 모듈, 수정종가
    return krx.get_market_ohlcv_by_date(start, end, code, True)


def _krx_index(start, end, index_code):
    from pykrx import stock
    return stock.get_index_ohlcv_by_date(start, end, index_code)


def _krx_cap(start, end, code):
    from pykrx import stock
    return stock.get_market_cap_by_date(start, end, code)


def window_for(as_of, weeks=104):
    """시세 조회 구간. 끝은 기준일 당일(기준일 종가·시총용), 베타 주간화는 beta.weekly_closes 가 직전 금요일에서 자른다."""
    import beta
    end = dt.date.fromisoformat(as_of)
    start = beta.last_friday_on_or_before(as_of) - dt.timedelta(weeks=weeks + 3)
    start -= dt.timedelta(days=start.weekday())          # 그 주 월요일
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _cached_series(key, fetch):
    px_dir = os.path.join(CACHE_DIR, "px")
    os.makedirs(px_dir, exist_ok=True)
    path = os.path.join(px_dir, f"{key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)]
    df = fetch()
    if df is None or getattr(df, "empty", True):
        raise MarketDataError(f"시세 없음: {key}")
    out = [(idx.strftime("%Y-%m-%d"), float(row["종가"])) for idx, row in df.iterrows()]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def daily_closes(code, start, end):
    return _cached_series(f"{code}_{start}_{end}", lambda: _krx_call(_krx_ohlcv, start, end, code))


def index_closes(start, end, index_code="1001"):
    return _cached_series(f"IDX{index_code}_{start}_{end}", lambda: _krx_call(_krx_index, start, end, index_code))


def market_cap(code, as_of):
    """기준일(휴장이면 직전 거래일)의 종가·시가총액·상장주식수."""
    d = dt.date.fromisoformat(as_of)
    start = (d - dt.timedelta(days=10)).strftime("%Y%m%d")
    df = _krx_call(_krx_cap, start, d.strftime("%Y%m%d"), code)
    if df is None or getattr(df, "empty", True):
        raise MarketDataError(f"시가총액 없음: {code} {as_of}")
    last = None
    for idx, row in df.iterrows():
        if idx.date() <= d:
            last = (idx, row)
    if last is None:
        raise MarketDataError(f"기준일 이전 거래일 없음: {code} {as_of}")
    idx, row = last
    cap, shares = int(row["시가총액"]), int(row["상장주식수"])
    return {"close": cap / shares if shares else None, "cap": cap, "shares": shares,
            "date": idx.strftime("%Y-%m-%d")}


def _krx_cap_all(date_yyyymmdd):
    from pykrx import stock
    return stock.get_market_cap_by_ticker(date_yyyymmdd, market="ALL")


def market_caps_all(as_of):
    """기준일 전종목 시가총액 {종목코드: 원}. 휴장일이면 직전 거래일까지 7일 거슬러 시도. 실패 시 {}."""
    global last_error
    d = dt.date.fromisoformat(as_of)
    for back in range(0, 8):
        try:
            df = _krx_call(_krx_cap_all, (d - dt.timedelta(days=back)).strftime("%Y%m%d"))
            if df is not None and not df.empty:
                return {str(code): int(row["시가총액"]) for code, row in df.iterrows()}
        except Exception as e:
            last_error = f"전종목 시총 조회 오류: {e}"
    return {}
