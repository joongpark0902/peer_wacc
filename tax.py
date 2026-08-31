"""법인세 한계세율 — 과세표준 구간표(법인세+지방소득세).

2026-01-01 시행분(법인세법 §55, 지방세법 §103조의20). 과세표준 대용으로
DART 손익계산서의 법인세비용차감전순이익을 쓴다(세무조정 전이므로 근사).
"""

# (구간 상한(원), 합계세율). 마지막은 상한 없음
BRACKETS_2026 = [(2e8, 0.110), (200e8, 0.220), (3000e8, 0.242), (float("inf"), 0.275)]
BRACKETS_2025 = [(2e8, 0.099), (200e8, 0.209), (3000e8, 0.231), (float("inf"), 0.264)]
LABELS = ["2억 이하", "2억~200억", "200억~3,000억", "3,000억 초과"]


def brackets_for(year):
    return BRACKETS_2026 if int(year) >= 2026 else BRACKETS_2025


def marginal_rate(pretax, year=2026):
    """(세율, 구간라벨). 결손·None 이면 (None, '결손/미확인')."""
    if pretax is None or pretax <= 0:
        return None, "결손/미확인"
    for (cap, rate), label in zip(brackets_for(year), LABELS):
        if pretax <= cap:
            return rate, label
    return None, "결손/미확인"
