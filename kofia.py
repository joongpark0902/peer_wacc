"""금투협 채권정보센터(kofiabond.or.kr) 수익률 조회.

- 최종호가수익률(BISLastAskPrcROPSrchSO.listDay): 국고채 10년 등 대표 만기 — Rf 용
- 시가평가 기준수익률 매트릭스(BISBndSrtPrcSrchSO.selectDay, 평가사 평균): 등급×만기 — Kd(BBB- 5년) 용
휴일·미공시일은 0행이 돌아오므로 기준일에서 최대 7일 거슬러 첫 영업일 값을 쓴다. 결과는 cache/kofia_{date}.json.
"""
import datetime as dt
import json
import os
import xml.etree.ElementTree as ET

import requests

from settings import CACHE_DIR

URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"
_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.kofiabond.or.kr/websquare/websquare.html",
      "Content-Type": "text/xml; charset=UTF-8"}
_MAT = ["3월", "6월", "9월", "1년", "1년6월", "2년", "2년6월", "3년", "4년", "5년", "7년", "10년", "15년", "20년", "30년", "50년"]
EVAL_AVG = "A20000"                      # 평가사 평균(`23.1.9~)


def _body(svc, fn, dto, inner):
    return (f'<?xml version="1.0" encoding="utf-8"?><message><proframeHeader><pfmAppName>BIS-KOFIABOND</pfmAppName>'
            f'<pfmSvcName>{svc}</pfmSvcName><pfmFnName>{fn}</pfmFnName></proframeHeader><systemHeader></systemHeader>'
            f'<{dto}>{inner}</{dto}></message>').encode("utf-8")


def _post(svc, fn, dto, inner):
    r = requests.post(URL, data=_body(svc, fn, dto, inner), headers=_H, timeout=30)
    r.raise_for_status()
    return r.text


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── 파서 (순수) ──────────────────────────────────────────────────────────────

def parse_final_quotes(xml_text):
    """최종호가수익률 listDay → {종목명: 당일 수익률(%)}. val4 = 당일(종가) 수익률."""
    out = {}
    for m in ET.fromstring(xml_text).iter("BISComDspDatDTO"):
        d = {c.tag: (c.text or "").strip() for c in m}
        name, v = d.get("val1"), _num(d.get("val4"))
        if name and v is not None:
            out[name] = v
    return out


def parse_matrix(xml_text):
    """시가평가 매트릭스 selectDay → [{category, type, grade, 만기: 값(%)...}]."""
    rows = []
    for m in ET.fromstring(xml_text).iter("BISBndSrtPrcDayDTO"):
        d = {c.tag: (c.text or "").strip() for c in m}
        if not d.get("largeCategoryMrk") and not d.get("typeNmMrk"):
            continue
        row = {"category": d.get("largeCategoryMrk", ""), "type": d.get("typeNmMrk", ""), "grade": d.get("creditRnkMrk", "")}
        for i, mat in enumerate(_MAT, 1):
            row[mat] = _num(d.get(f"val{i}"))
        rows.append(row)
    return rows


def pick(matrix, category_prefix, type_eq, grade):
    for r in matrix:
        if r["category"].startswith(category_prefix) and r["type"] == type_eq and r["grade"] == grade:
            return r
    return None


def summarize(final_quotes, matrix, date_used):
    """앱·보고서가 쓰는 요약 dict."""
    ktb = pick(matrix, "국채", "국고채권", "양곡,외평,재정") or {}
    bbb = pick(matrix, "회사채 I", "무보증", "BBB-") or {}
    aa = pick(matrix, "회사채 I", "무보증", "AA-") or {}
    return {
        "date_used": date_used,
        "ktb10_final": final_quotes.get("국고채권(10년)"),          # 최종호가 국고 10년 (ECOS 와 동일)
        "ktb10_val": ktb.get("10년"),                                # 시가평가 평가사평균 국고 10년
        "ktb5_val": ktb.get("5년"), "ktb3_val": ktb.get("3년"),
        "bbb_minus_5y": bbb.get("5년"), "bbb_minus_3y": bbb.get("3년"), "bbb_minus_10y": bbb.get("10년"),
        "aa_minus_5y": aa.get("5년"), "aa_minus_3y": aa.get("3년"),
        "bbb_minus_3y_final": final_quotes.get("회사채(무보증3년)BBB-"),
        "aa_minus_3y_final": final_quotes.get("회사채(무보증3년)AA-"),
        "source": "금투협 채권정보센터 — 최종호가수익률(Rf) · 시가평가 기준수익률 평가사 평균(Kd)",
    }


# ── 네트워크 ────────────────────────────────────────────────────────────────

def fetch_final_quotes(yyyymmdd):
    return parse_final_quotes(_post("BISLastAskPrcROPSrchSO", "listDay", "BISComDspDatDTO", f"<val1>{yyyymmdd}</val1>"))


def fetch_matrix(yyyymmdd, evaluator=EVAL_AVG):
    inner = (f"<standardDt>{yyyymmdd}</standardDt><reportCompCd>{evaluator}</reportCompCd><applyGbCd>C00</applyGbCd>"
             "<val1>A10002</val1><val2>A10003</val2><val3>A10004</val3><val4>A10005</val4><val5>A10006</val5>")
    return parse_matrix(_post("BISBndSrtPrcSrchSO", "selectDay", "BISBndSrtPrcDayDTO", inner))


def market_rates(as_of, cache_dir=None, log=None):
    """기준일(휴일이면 직전 영업일)의 Rf·Kd 후보. 실패하면 None."""
    cache_dir = cache_dir or CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"kofia_{as_of}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if "matrix" in cached:                       # 원자료 없는 구버전 캐시는 버리고 다시 받는다(금투협 시트용)
            return cached
    d = dt.date.fromisoformat(as_of)
    for back in range(0, 8):
        day = (d - dt.timedelta(days=back))
        if day.weekday() >= 5:
            continue
        ymd = day.strftime("%Y%m%d")
        try:
            matrix = fetch_matrix(ymd)
            if not matrix:
                continue
            final = fetch_final_quotes(ymd)
        except Exception as e:
            if log:
                log(f"금투협 조회 실패 {ymd}: {e}")
            continue
        out = summarize(final, matrix, day.isoformat())
        out["final_quotes"], out["matrix"] = final, matrix           # 원자료 — 보고서 '금투협' 시트에 그대로 싣는다
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        return out
    return None
