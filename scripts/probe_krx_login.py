"""KRX 로그인과 시세 조회가 실제로 되는지 확인한다. 값은 출력하되 계정은 출력하지 않는다."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings, market_data as md

cfg = settings.load_config()
ok = md.krx_login(cfg["krx_id"], cfg["krx_pw"])
print("login:", ok, md.last_error)
if ok:
    s, e = md.window_for("2026-03-31")
    px = md.daily_closes("014620", s, e)
    ix = md.index_closes(s, e)
    print("성광벤드 일수:", len(px), px[0], px[-1])
    print("KOSPI 일수:", len(ix), ix[-1])
    print("시총:", md.market_cap("014620", "2026-03-31"))
