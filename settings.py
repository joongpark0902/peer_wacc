"""실행 경로와 config.txt(인증키·KRX 계정)를 다룬다.

exe로 묶으면 __file__ 은 임시 해제 폴더를 가리키므로 실행파일이 놓인 폴더를
기준으로 잡는다(dart_downloader와 같은 규칙).
"""
import os
import sys
import json
import datetime as dt
import shutil

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "config.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
SESSION_DIR = os.path.join(APP_DIR, "peer_sessions")
DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
UI_PREFERENCES_PATH = os.path.join(APP_DIR, "ui-preferences.json")


def source_app_dir():
    """관리 worktree에서도 원본 저장소에 이미 있는 공개 데이터 파일을 찾는다."""
    try:
        with open(os.path.join(APP_DIR, ".git"), encoding="utf-8") as f:
            marker = f.read().strip()
        if not marker.startswith("gitdir:"):
            return APP_DIR
        git_dir = os.path.normpath(os.path.join(APP_DIR, marker.partition(":")[2].strip()))
        with open(os.path.join(git_dir, "commondir"), encoding="utf-8") as f:
            common = os.path.normpath(os.path.join(git_dir, f.read().strip()))
        return os.path.dirname(common)
    except (OSError, UnicodeError):
        return APP_DIR


def load_ui_preferences():
    """표시 설정만 읽는다. 인증정보와 독립적으로 기본은 라이트 모드."""
    try:
        with open(UI_PREFERENCES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        mode = data.get("appearance_mode") if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError):
        mode = None
    return {"appearance_mode": mode if mode in ("light", "dark") else "light"}


def save_ui_preferences(mode):
    if mode not in ("light", "dark"):
        raise ValueError("appearance mode must be light or dark")
    if os.path.exists(UI_PREFERENCES_PATH):
        stamp = dt.datetime.fromtimestamp(os.path.getmtime(UI_PREFERENCES_PATH)).strftime("%Y%m%d_%H%M%S_%f")
        backup = os.path.join(os.path.dirname(UI_PREFERENCES_PATH), f"backup_{stamp}_ui-preferences.json")
        if not os.path.exists(backup):
            shutil.copy2(UI_PREFERENCES_PATH, backup)
    with open(UI_PREFERENCES_PATH, "w", encoding="utf-8") as f:
        json.dump({"appearance_mode": mode}, f, indent=2)
    return UI_PREFERENCES_PATH

KEYS = ("dart_api_key", "krx_id", "krx_pw", "kicpa_path")

CONFIG_HEADER = (
    "# peer_wacc 설정 — 이 파일은 git에 올라가지 않습니다. 남에게 공유하지 마세요.\n"
    "# dart_api_key: DART OpenAPI 인증키 (opendart.fss.or.kr 발급)\n"
    "# krx_id / krx_pw: KRX 정보데이터시스템(data.krx.co.kr) 회원 계정\n"
    "# kicpa_path: 마지막으로 연 한공회 베타 파일 — 있으면 앱 시작 시 자동 로드\n"
)


def _read_kv(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                out[name.strip().lower()] = value.strip()
    except OSError:
        pass
    return out


def load_config():
    """config.txt → {'dart_api_key','krx_id','krx_pw'}. 없는 키는 ''."""
    kv = _read_kv(CONFIG_PATH)
    return {k: kv.get(k, "") for k in KEYS}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(CONFIG_HEADER)
        for k in KEYS:
            f.write(f"{k} = {cfg.get(k, '')}\n")
    return CONFIG_PATH


def ensure_dirs():
    for d in (CACHE_DIR, SESSION_DIR, DOWNLOADS_DIR):
        os.makedirs(d, exist_ok=True)
