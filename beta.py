"""베타 계산 규약 — 순수 함수만.

2년 주간(104주, 금요일 마감) 수익률 회귀 → Blume(⅔·raw+⅓) → Hamada 언레버 →
피어 평균 → 피어 평균 D/E로 재레버. 엑셀의 SLOPE/RSQ 와 같은 표본 정의를 쓴다.
"""
import datetime as dt
import statistics

MIN_POINTS = 104
DEFAULT_TAX = 0.275


def last_friday_on_or_before(as_of):
    d = dt.date.fromisoformat(as_of)
    return d - dt.timedelta(days=(d.weekday() - 4) % 7)


def _week_key(date_str):
    d = dt.date.fromisoformat(date_str)
    return d.isocalendar()[:2]      # (year, week)


def weekly_closes(daily, as_of, n_weeks=MIN_POINTS):
    """일별 (날짜, 종가) → 주별 마지막 거래일 (날짜, 종가). 기준일 직전 금요일 주까지,
    과거로 n_weeks+1 개(수익률 n_weeks 개를 만들기 위해)."""
    cutoff = last_friday_on_or_before(as_of).isoformat()
    by_week = {}
    for date_str, close in sorted(daily):
        if date_str > cutoff:
            break
        by_week[_week_key(date_str)] = (date_str, close)
    weeks = [by_week[k] for k in sorted(by_week)]
    return weeks[-(n_weeks + 1):]


def returns(weekly):
    out = []
    for (d0, c0), (d1, c1) in zip(weekly, weekly[1:]):
        if c0:
            out.append((d1, c1 / c0 - 1.0))
    return out


def regress(stock_rets, index_rets):
    """날짜 교집합으로 맞춘 뒤 표본 공분산/분산으로 raw β·R²·n."""
    idx = dict(index_rets)
    pairs = [(r, idx[d]) for d, r in stock_rets if d in idx]
    n = len(pairs)
    if n < 3:
        return {"raw": None, "r2": None, "n": n}
    ys = [p[0] for p in pairs]
    xs = [p[1] for p in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return {"raw": None, "r2": None, "n": n}
    return {"raw": sxy / sxx, "r2": (sxy * sxy) / (sxx * syy), "n": n}


def blume(raw):
    return None if raw is None else 2.0 / 3.0 * raw + 1.0 / 3.0


def unlever(beta_l, de, tax):
    return beta_l / (1.0 + (1.0 - tax) * de)


def relever(beta_u, de, tax):
    return beta_u * (1.0 + (1.0 - tax) * de)


def aggregate(peers, method="mean", tax_target=DEFAULT_TAX):
    """include=True 이고 beta_u·de 가 있는 피어만 집계."""
    rows = [p for p in peers if p.get("include") and p.get("beta_u") is not None and p.get("de") is not None]
    if not rows:
        return {"beta_u": None, "de": None, "beta_l_target": None, "n": 0}
    agg = statistics.median if method == "median" else statistics.fmean
    bu = agg([p["beta_u"] for p in rows])
    de = agg([p["de"] for p in rows])
    return {"beta_u": bu, "de": de, "beta_l_target": relever(bu, de, tax_target), "n": len(rows)}
