"""한공회 기업규모위험 프리미엄(SRP) 분위 판정 — '한국의 기업규모위험 프리미엄 연구결과'(2026-06-05).

상장 대상은 시가총액을 5분위 구간 하한과 비교해 판정한다(연구의 분위 자체가 시가총액 기준이라
구간이 겹치지 않는다). 비상장 대상은 순자산 장부금액을 분위별 중위값에 최근접(인접 중위값의
기하평균을 경계)으로 판정한다 — 연구의 순자산 통계는 참고목적(주2)이고 분위 간 Min·Max가
겹쳐 구간 판정이 불가능하기 때문. 단위는 모두 백만원.
"""
import math

# (분위, 프리미엄, 시가총액 구간 하한, 순자산 중위값) — 1분위(대형)부터
_Q = [(1, -0.0051, 1_883_659, 4_424_063),
      (2, -0.0006, 660_757, 875_201),
      (3, 0.0097, 314_243, 381_849),
      (4, 0.0267, 176_001, 234_942),
      (5, 0.0486, 29_568, 115_719)]
_SRC = "한공회 연구결과(260605) 5분위"


def judge(cap_million=None, net_assets_million=None):
    """{quintile, premium, note}. 시가총액(상장) 우선, 없으면 순자산(비상장), 둘 다 없으면 5분위 기본값."""
    if cap_million:
        q, prem = next((q, p) for q, p, cap_min, _na in _Q if cap_million >= cap_min or q == 5)
        return {"quintile": q, "premium": prem,
                "note": f"{_SRC} 중 {q}분위 {prem:.2%} — 대상 시가총액 {cap_million:,.0f}백만원 (분위별 시총 구간 대조)"}
    if net_assets_million:
        q, prem = min(((q, p) for q, p, _c, med in _Q), key=lambda t: _log_dist(net_assets_million, t))
        return {"quintile": q, "premium": prem,
                "note": f"{_SRC} 중 {q}분위 {prem:.2%} — 대상 순자산 {net_assets_million:,.0f}백만원, 분위별 순자산 중위값 최근접(참고목적, 주2)"}
    return {"quintile": 5, "premium": 0.0486,
            "note": f"{_SRC} 4.86% 기본 (3분위 Micro 4.02%) — 대상 시총·순자산 미입력, 분위 판정 없음"}


def _log_dist(value, qp):
    med = next(m for q, _p, _c, m in _Q if q == qp[0])
    return abs(math.log(value) - math.log(med))
