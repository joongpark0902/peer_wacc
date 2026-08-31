"""한공회(KICPA) 베타 조회 파일 파서.

화면에서 받은 xlsx/csv 를 그대로 읽는다. 열 이름은 부분일치로 찾아 열 순서가
달라도 된다. 단축코드는 엑셀이 숫자로 바꿔 앞 0을 지우는 경우가 흔해 6자리로 되돌린다.
"""
import csv
import datetime as dt
import io

import openpyxl

MIN_POINTS = 104

_COLS = {                       # 내부키: 헤더에 들어 있어야 하는 문자열
    "code": "단축코드", "name": "한글종목명", "base_date": "기준일자", "query_date": "조회일자",
    "market": "시장구분", "close": "종가", "raw": "실질베타", "adjusted": "조정베타", "points": "포인트수",
}
_REQUIRED = ("code", "adjusted")


class FormatError(Exception):
    def __init__(self, columns):
        super().__init__(f"필수 열(단축코드·조정베타)을 찾지 못했습니다: {columns}")
        self.columns = columns


def normalize_code(v):
    s = str(v).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(6) if s.isdigit() else s


def _date(v):
    if v is None or v == "":
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip().replace("-", "").replace("/", "").split(".")[0]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else str(v)


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _decode(raw):
    """한공회·KRX 다운로드는 UTF-8(BOM)일 때도, CP949일 때도 있다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _rows_from_html(text):
    from market_data import _TableParser
    p = _TableParser()
    p.feed(text)
    return p.rows


def _rows_from(path):
    """확장자를 믿지 않고 내용으로 판별: xlsx(PK) / xls(BIFF, xlrd) / HTML 표 / CSV."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"PK":
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        return [[c for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    if raw[:4] == bytes([0xD0, 0xCF, 0x11, 0xE0]):              # OLE2 = 구형 .xls
        import xlrd
        ws = xlrd.open_workbook(path).sheet_by_index(0)
        return [ws.row_values(i) for i in range(ws.nrows)]
    text = _decode(raw)
    if "<table" in text[:4000].lower() or "<html" in text[:200].lower():
        return _rows_from_html(text)
    return [r for r in csv.reader(io.StringIO(text))]


def _find_header(rows):
    for i, r in enumerate(rows[:20]):
        cells = ["" if c is None else str(c).replace(" ", "") for c in r]
        col = {k: next((j for j, c in enumerate(cells) if v in c), None) for k, v in _COLS.items()}
        if all(col[k] is not None for k in _REQUIRED):
            return i, col
    first = ["" if c is None else str(c) for c in (rows[0] if rows else [])]
    raise FormatError(first)


def load(path):
    rows = _rows_from(path)
    h, col = _find_header(rows)
    out = {}

    def get(r, k):
        j = col.get(k)
        return None if j is None or j >= len(r) else r[j]

    for r in rows[h + 1:]:
        code = get(r, "code")
        if code is None or str(code).strip() == "":
            continue
        code = normalize_code(code)
        pts = _num(get(r, "points"))
        pts = int(pts) if pts is not None else None
        out[code] = {
            "name": get(r, "name"), "market": get(r, "market"),
            "base_date": _date(get(r, "base_date")), "query_date": _date(get(r, "query_date")),
            "close": _num(get(r, "close")), "raw": _num(get(r, "raw")),
            "adjusted": _num(get(r, "adjusted")), "points": pts,
            "flags": ["관측치부족"] if pts is not None and pts < MIN_POINTS else [],
        }
    return out
