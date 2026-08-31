"""후보 검색: 키워드 OR 매칭 → 자동 플래그 → 필터. 네트워크 없음.

기존 유사기업 검토 조서의 방식(FIND(키워드, 주요제품) 을 키워드마다 OR)을
그대로 코드로 옮긴 것이다. 제외 판단은 사람이 하고 여기서는 표시만 한다.
"""
import datetime as dt
import re

FLAG_NEW = "상장2년미만"
FLAG_SPAC = "스팩"
FLAG_NON_DEC = "비12월결산"
FLAG_TEMP = "임시코드"
FLAG_MANUAL = "수동추가"

EXCLUDE_REASONS = ["무관업종", "세그먼트 상이", "사업모델 상이(EPC·서비스)", "유통·서비스", "상장 2년 미만", "스팩",
                   "규모 상이", "경영권 이슈", "감사의견 비적정", "기타"]
DEFAULT_EXCLUDE_KEYWORDS = "스팩, 인수합병, 지주, 홀딩스, 유통, 도매, 임대, 리츠"

NEW_LISTING_DAYS = 730
RECOMMEND_TOP = 5


def score(row):
    """추천 점수(v2, 전부 감점제 — 하드 제외는 스팩·임시코드뿐).
    업종 동일 +3 · KSIC 앞4자리 +2 / 앞3자리 +1 · 키워드 적중 +2/개 · 시총 대상 대비 0.2x~5x +2
    · 제외 키워드 적중 -5/개 · 상장 2년 미만 -5 · 비12월 결산 -1 · 스팩·임시코드 -100"""
    s = (3 * bool(row.get("same_industry")) + int(row.get("ksic_level") or 0) + 2 * len(row.get("hits") or [])
         + 2 * bool(row.get("cap_similar")) - 5 * len(row.get("neg_hits") or []))
    fl = row.get("flags") or []
    if FLAG_SPAC in fl or FLAG_TEMP in fl:
        s -= 100
    if FLAG_NEW in fl:
        s -= 5
    if FLAG_NON_DEC in fl:
        s -= 1
    return s


def reason(row):
    """점수 구성 설명. 예: '업종+3 · 키워드 2개(피팅,밸브)+4 · KSIC≈+1 · 시총유사+2 · 신규상장−5 = 5점'"""
    parts = []
    if row.get("same_industry"):
        parts.append("업종+3")
    lvl = int(row.get("ksic_level") or 0)
    if lvl == 2:
        parts.append("KSIC≡+2")
    elif lvl == 1:
        parts.append("KSIC≈+1")
    hits = row.get("hits") or []
    if hits:
        parts.append(f"키워드 {len(hits)}개({','.join(hits[:3])}{'…' if len(hits) > 3 else ''})+{2 * len(hits)}")
    if row.get("cap_similar"):
        parts.append("시총유사+2")
    negs = row.get("neg_hits") or []
    if negs:
        parts.append(f"제외어({','.join(negs)})−{5 * len(negs)}")
    fl = row.get("flags") or []
    if FLAG_SPAC in fl or FLAG_TEMP in fl:
        parts.append("스팩/임시코드 제외")
    if FLAG_NEW in fl:
        parts.append("신규상장−5")
    if FLAG_NON_DEC in fl:
        parts.append("비12월−1")
    return " · ".join(parts) + f" = {score(row)}점"


def rank(rows, top=RECOMMEND_TOP):
    """점수순 정렬 + 상위 top 개(점수 > 0)에 recommended=True. 동점이면 상장 오래된 순(β 관측치 안정), 그다음 목록순."""
    order = sorted(range(len(rows)), key=lambda i: (-score(rows[i]), rows[i].get("listed") or "9999-99-99", i))
    out = []
    for k, i in enumerate(order):
        r = dict(rows[i], score=score(rows[i]))
        r["recommended"] = k < top and r["score"] > 0
        r["reason"] = reason(r)
        out.append(r)
    return out


def parse_keywords(text):
    return [k for k in re.split(r"[,\s]+", (text or "").strip()) if k]


def _days_listed(listed, as_of):
    try:
        d0 = dt.date.fromisoformat(listed)
        d1 = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return None
    return (d1 - d0).days


def _flags(row, as_of):
    flags = []
    days = _days_listed(row.get("listed"), as_of)
    if days is not None and days < NEW_LISTING_DAYS:
        flags.append(FLAG_NEW)
    if "스팩" in (row.get("name") or ""):
        flags.append(FLAG_SPAC)
    if (row.get("settle_month") or "12월") != "12월":
        flags.append(FLAG_NON_DEC)
    if not (row.get("code") or "").isdigit():
        flags.append(FLAG_TEMP)
    return flags


def ksic_level(row_ksic, target_ksic=None, ksic_codes=None):
    """KSIC 일치 수준: 코드군(ksic_codes) 중 하나와 앞 4자리 일치 또는 대상 코드와 앞 4자리 → 2, 앞 3자리 → 1, 아니면 0."""
    k = str(row_ksic or "").strip()
    if not k:
        return 0
    refs = [str(c).strip().upper().lstrip("ABCDEFGHIJKLMNOPQRSTU") for c in list(ksic_codes or []) + ([target_ksic] if target_ksic else []) if str(c).strip()]   # 'C29133' → '29133'
    best = 0
    for ref in refs:
        if len(ref) >= 4 and k[:4] == ref[:4]:
            best = max(best, 2)
        elif len(ref) >= 3 and k[:3] == ref[:3]:
            best = max(best, 1)
    return best


_CORP_NOISE = re.compile(r"\s+|\(주\)|㈜|주식회사")


def _norm_name(s):
    return _CORP_NOISE.sub("", s or "").lower()


def find_names(text, candidates, kind_rows):
    """검색창 입력(회사명·종목코드, 쉼표·탭·줄바꿈 구분 — 회사가 준 피어 리스트 붙여넣기용)을
    후보 표(candidates)와 전체 상장목록(kind_rows)에서 찾는다.

    반환 (matched_codes, addable_rows, missing):
      matched_codes — 후보 표에 있는 종목코드(입력 순, 중복 제거)
      addable_rows  — 후보엔 없지만 상장목록에 있는 KIND 행('후보에 추가' 대상)
      missing       — 어디에도 없는 질의(오타·비상장·상폐 의심)
    """
    matched, addable, missing, seen = [], [], [], set()

    def _find(rows, q, nq):
        return [r for r in rows if nq and (nq in _norm_name(r.get("name")) or q == r.get("code"))]

    for q in (t.strip() for t in re.split(r"[,;\t\n]+", text or "")):
        if not q:
            continue
        nq = _norm_name(q)
        hit = _find(candidates, q, nq)
        if hit:
            matched += [r["code"] for r in hit if r["code"] not in seen and not seen.add(r["code"])]
            continue
        krows = _find(kind_rows, q, nq)
        if krows:
            addable += [r for r in krows if r["code"] not in seen and not seen.add(r["code"])]
        else:
            missing.append(q)
    return matched, addable, missing


def manual_row(kind_row, as_of, caps=None):
    """검색으로 찾아 수동 추가하는 후보 행 — 점수 요소 없이 플래그만 붙인다(추천·정렬 불변)."""
    cap = (caps or {}).get(kind_row.get("code"))
    return dict(kind_row, hits=[], neg_hits=[], flags=_flags(kind_row, as_of) + [FLAG_MANUAL],
                cap_eok=round(cap / 1e8, 1) if cap is not None else None,
                same_ksic=False, ksic_level=0, same_industry=False, cap_similar=False)


def search(rows, keywords, as_of, *, markets=None, cap_min=None, cap_max=None,
           caps=None, target_ksic=None, listed_min_days=None, industry=None,
           exclude_keywords=None, ksic_codes=None, target_cap=None):
    """후보 = (키워드 하나라도 주요제품·업종에 적중) OR (업종 명칭이 `industry`와 동일).
    키워드·업종 둘 다 없으면 빈 목록(전 상장사를 돌려주지 않는다 — 화면이 멈춘다).

    cap_min/cap_max 는 억원 단위. caps 는 {종목코드: 시총(원)}. 시총이 없는 행은
    시총 필터가 걸려 있을 때만 제외된다. 반환 행에 `same_industry` 가 붙는다.
    """
    kws = [k.lower() for k in keywords if k]
    negs = [k for k in (exclude_keywords or []) if k]
    industry = (industry or "").strip() or None
    if not kws and not industry and not ksic_codes:
        return []
    out, seen = [], set()
    for row in rows:
        if row.get("code") in seen:          # KIND 목록의 중복 코드 방지 (표 iid 충돌)
            continue
        seen.add(row.get("code"))
        hay = f"{row.get('products') or ''} {row.get('industry') or ''}".lower()
        hits = [k for k in keywords if k and k.lower() in hay]
        same_ind = bool(industry) and (row.get("industry") or "").strip() == industry
        lvl = ksic_level(row.get("ksic"), target_ksic, ksic_codes)
        if not hits and not same_ind and not (ksic_codes and lvl):
            continue
        neg_hay = f"{row.get('name') or ''} {hay}".lower()
        neg_hits = [k for k in negs if k.lower() in neg_hay]
        if markets and row.get("market") not in markets:
            continue
        days = _days_listed(row.get("listed"), as_of)
        if listed_min_days is not None and (days is None or days < listed_min_days):
            continue
        cap = (caps or {}).get(row.get("code"))
        cap_eok = round(cap / 1e8, 1) if cap is not None else None
        if cap_min is not None and (cap_eok is None or cap_eok < cap_min):
            continue
        if cap_max is not None and (cap_eok is None or cap_eok > cap_max):
            continue
        cap_similar = bool(target_cap) and cap is not None and 0.2 * target_cap <= cap <= 5 * target_cap
        out.append(dict(row, hits=hits, neg_hits=neg_hits, flags=_flags(row, as_of), cap_eok=cap_eok,
                        same_ksic=lvl > 0, ksic_level=lvl, same_industry=same_ind, cap_similar=cap_similar))
    return out
