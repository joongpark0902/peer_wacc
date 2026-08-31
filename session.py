"""후보 선정 작업 상태를 json 으로 저장/복원한다 (제외 사유가 감사 추적이므로 보존)."""
import copy
import json
import os
import re

from settings import SESSION_DIR

_BAD = re.compile(r'[\\/:*?"<>|]')


def new(target_name, as_of):
    return {
        "version": 1,
        "target": {"name": target_name, "listed": False, "code": "", "industry": "", "ksic": ""},
        "as_of": as_of,
        "keywords": [],
        "filters": {"markets": [], "cap_min": None, "cap_max": None, "listed_min": False,
                    "exclude_keywords": ["스팩", "인수합병", "지주", "홀딩스", "유통", "도매", "임대", "리츠"], "ksic_codes": [], "target_cap": None},
        "candidates": {},
        "kicpa_path": "",
        "beta_source": "kicpa",
        "include_lease": True,
        "de_method": "mean",
        "tax_target": 0.275,
        "peer_overrides": {},
    }


def path_for(target_name, as_of):
    safe = _BAD.sub("_", target_name.strip()) or "session"
    return os.path.join(SESSION_DIR, f"{safe}_{as_of}.json")


def save(s):
    os.makedirs(SESSION_DIR, exist_ok=True)
    p = path_for(s["target"]["name"], s["as_of"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    return p


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "candidates" and k != "peer_overrides":
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    base = new(raw.get("target", {}).get("name", ""), raw.get("as_of", ""))
    return _merge(base, raw)
