"""실행 경로와 config.txt(인증키·KRX 계정)를 다룬다.

exe로 묶으면 __file__ 은 임시 해제 폴더를 가리키므로 실행파일이 놓인 폴더를
기준으로 잡는다(dart_downloader와 같은 규칙).
"""
import os
import sys

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "config.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
SESSION_DIR = os.path.join(APP_DIR, "peer_sessions")
DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
DOWNLOADER_CONFIG_PATH = os.path.join(os.path.dirname(APP_DIR), "dart_downloader", "config.txt")

KEYS = ("dart_api_key", "krx_id", "krx_pw", "kicpa_path")

CONFIG_HEADER = (
    "# peer_wacc 설정 — 이 파일은 git에 올라가지 않습니다. 남에게 공유하지 마세요.\n"
    "# dart_api_key: DART OpenAPI 인증키 (비우면 ..\\dart_downloader\\config.txt 값을 씁니다)\n"
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


def dart_api_key_with_fallback(cfg):
    """내 키가 비어 있으면 dart_downloader의 config.txt(api_key=)를 읽어 쓴다."""
    if cfg.get("dart_api_key"):
        return cfg["dart_api_key"]
    return _read_kv(DOWNLOADER_CONFIG_PATH).get("api_key", "")


def ensure_dirs():
    for d in (CACHE_DIR, SESSION_DIR, DOWNLOADS_DIR):
        os.makedirs(d, exist_ok=True)
