"""
Truve Platform - 매크로 데이터 수집기 설정
목적: BE/FE 매크로 탐지 모델 학습용 봇 데이터 생성

보안 기준:
  - Rule 2 (NO SECRETS): 크리덴셜은 환경변수(.env)에서만 로드
  - Rule 1 (ZERO TRUST INPUT): URL/ID 등 외부 입력값 서버단 검증
  - Rule 6 (OPEN SOURCE): MIT/Apache-2.0 라이선스만 사용

봇 레벨 시스템:
  Level 1  = 극단적 봇 (일반 매크로, 무지성 빠른 클릭)
  Level 2  = 공격적 봇 (빠른 속도, 패턴 단순)
  Level 3  = 일반 봇 (기본 매크로 수준)
  Level 4  = 약간 개선된 봇 (약간의 랜덤성)
  Level 5  = 중간 단계 (봇/사람 경계)
  Level 6  = 반자동 (사람이 보조 도구 사용)
  Level 7  = 스텔스 봇 (탐지 회피 시도)
  Level 8  = 고급 스텔스 (사람 흉내)
  Level 9  = 거의 사람 (약간의 자동화만)
  Level 10 = 사람과 동일 (완전한 사람 시뮬레이션)
"""

import json
import os
import re
import sys
from urllib.parse import urlparse

# ============================================================
# [Rule 2] 크리덴셜 로더 - 환경변수에서만 시크릿 로드
# ============================================================

def _load_env_file() -> None:
    """
    .env 파일이 있으면 환경변수로 로드 (python-dotenv 미사용, 순수 구현).
    라이선스 의존성을 최소화하기 위해 직접 파싱.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 주석/빈 줄 건너뛰기
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # 기존 환경변수가 우선 (이미 설정된 값 덮어쓰지 않음)
            if key not in os.environ:
                os.environ[key] = value


# .env 로드 시도
_load_env_file()


def _get_env(key: str, default: str = "") -> str:
    """환경변수 값 반환 (없으면 기본값)"""
    return os.environ.get(key, default)


def _get_env_required(key: str) -> str:
    """필수 환경변수 값 반환 (없으면 즉시 종료)"""
    val = os.environ.get(key)
    if not val:
        print(f"  [SECURITY] 필수 환경변수 누락: {key}")
        print(f"  .env.example 을 참고하여 .env 파일을 생성하세요.")
        sys.exit(1)
    return val


# ============================================================
# [Rule 1] 입력값 검증 유틸
# ============================================================

# URL 허용 스킴 화이트리스트
_ALLOWED_URL_SCHEMES = {"https"}
# URL 최대 길이 제한 (SSRF 방어)
_MAX_URL_LENGTH = 256


def validate_url(url: str) -> str:
    """
    URL 화이트리스트 검증.
    - HTTPS만 허용 (HTTP 거부)
    - 길이 제한
    - 사설 IP/localhost 차단 (SSRF 방어)
    """
    if not url or len(url) > _MAX_URL_LENGTH:
        raise ValueError(f"URL 길이 초과 (최대 {_MAX_URL_LENGTH}자)")

    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"허용되지 않은 스킴: {parsed.scheme} (HTTPS만 허용)")

    hostname = parsed.hostname or ""
    # SSRF 방어: 내부 네트워크 주소 차단
    _blocked_patterns = [
        r"^localhost$",
        r"^127\.",
        r"^10\.",
        r"^172\.(1[6-9]|2\d|3[01])\.",
        r"^192\.168\.",
        r"^0\.",
        r"^169\.254\.",   # link-local
        r"^\[::1\]$",     # IPv6 loopback
    ]
    for pattern in _blocked_patterns:
        if re.match(pattern, hostname):
            raise ValueError(f"차단된 호스트: {hostname} (내부 네트워크 접근 금지)")

    return url


def validate_show_id(show_id: int) -> int:
    """공연 ID 양의 정수 검증"""
    if not isinstance(show_id, int) or show_id < 1 or show_id > 999999:
        raise ValueError(f"잘못된 공연 ID: {show_id} (1~999999)")
    return show_id


def validate_level(level: int) -> int:
    """봇 레벨 범위 검증"""
    if not isinstance(level, int) or level < 1 or level > 10:
        raise ValueError(f"잘못된 레벨: {level} (1~10)")
    return level


def validate_runs(runs: int) -> int:
    """반복 횟수 상한 검증 (DoS 방지)"""
    if not isinstance(runs, int) or runs < 1 or runs > 100:
        raise ValueError(f"잘못된 반복 횟수: {runs} (1~100)")
    return runs


# ============================================================
# [Rule 4] 민감정보 마스킹 유틸
# ============================================================

def mask_email(email: str) -> str:
    """이메일 마스킹: test@example.com → t***@e*****.com"""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = local[0] + "***" if len(local) > 0 else "***"
    parts = domain.split(".")
    masked_domain = parts[0][0] + "*****" if len(parts[0]) > 0 else "*****"
    return f"{masked_local}@{masked_domain}.{'.'.join(parts[1:])}"


def mask_password(password: str) -> str:
    """비밀번호 마스킹: 무조건 전체 은닉"""
    return "********"


# ============================================================
# 기본 설정 (환경변수 기반)
# ============================================================

BASE_URL = validate_url(_get_env("TRUVE_BASE_URL", "https://front-nu-tawny.vercel.app"))

# [Rule 2] 크리덴셜은 환경변수에서만 로드 - 하드코딩 절대 금지
def load_test_accounts() -> list[dict]:
    """
    환경변수 TRUVE_TEST_ACCOUNTS 에서 테스트 계정 로드.
    형식: JSON 배열 [{"email":"...","password":"..."}]
    미설정 시 빈 리스트 반환 (CLI에서 --email/--password 필수)
    """
    raw = _get_env("TRUVE_TEST_ACCOUNTS", "")
    if not raw:
        return []
    try:
        accounts = json.loads(raw)
        if not isinstance(accounts, list):
            raise ValueError
        for acc in accounts:
            if "email" not in acc or "password" not in acc:
                raise ValueError("email/password 키 필수")
        return accounts
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [WARN] TRUVE_TEST_ACCOUNTS 파싱 실패: {e}")
        return []


TEST_ACCOUNTS = load_test_accounts()
TEST_SHOW_ID = int(_get_env("TRUVE_SHOW_ID", "1"))
TEST_SHOW_SCHEDULE_ID = int(_get_env("TRUVE_SCHEDULE_ID", "1"))

# ============================================================
# 10단계 봇 레벨 프로필
# 모든 레벨은 headed 모드 (실제 화면에서 동작)
# ============================================================

BOT_LEVELS = {
    1: {
        "name": "Lv.1 극단적 봇",
        "description": "일반 매크로. 모든 동작이 기계적, 초고속",
        "level": 1,
        "action_delay_ms": (30, 80),
        "typing_delay_ms": (0, 0),
        "typing_use_paste": True,
        "queue_poll_ms": (100, 150),
        "queue_ignore_server_interval": True,
        "seat_select_delay_ms": (10, 50),
        "mouse_move_to_target": False,
        "mouse_move_steps": 0,
        "mouse_move_speed_ms": 0,
        "mouse_curve": "none",
        "mouse_jitter_px": 0,
        "click_offset_px": 0,
        "hover_before_click_ms": (0, 0),
        "scroll_enabled": False,
        "scroll_delay_ms": 0,
        "headless": False,
        "hide_webdriver": False,
        "viewport": (800, 600),
        "user_agent": None,
        "slow_mo": 0,
        "retry_count": 15,
        "retry_delay_ms": (10, 30),
        "seat_strategy": "first_available",
        "max_seat_attempts": 10,
    },
    2: {
        "name": "Lv.2 공격적 봇",
        "description": "빠른 속도, 최소한의 마우스 이동",
        "level": 2,
        "action_delay_ms": (80, 200),
        "typing_delay_ms": (5, 10),
        "typing_use_paste": True,
        "queue_poll_ms": (200, 400),
        "queue_ignore_server_interval": True,
        "seat_select_delay_ms": (50, 150),
        "mouse_move_to_target": True,
        "mouse_move_steps": 3,
        "mouse_move_speed_ms": 5,
        "mouse_curve": "linear",
        "mouse_jitter_px": 0,
        "click_offset_px": 0,
        "hover_before_click_ms": (0, 10),
        "scroll_enabled": False,
        "scroll_delay_ms": 0,
        "headless": False,
        "hide_webdriver": False,
        "viewport": (1280, 720),
        "user_agent": None,
        "slow_mo": 10,
        "retry_count": 10,
        "retry_delay_ms": (30, 80),
        "seat_strategy": "first_available",
        "max_seat_attempts": 8,
    },
    3: {
        "name": "Lv.3 일반 봇",
        "description": "기본적인 매크로 수준, 직선 마우스",
        "level": 3,
        "action_delay_ms": (200, 500),
        "typing_delay_ms": (10, 25),
        "typing_use_paste": False,
        "queue_poll_ms": (500, 1000),
        "queue_ignore_server_interval": True,
        "seat_select_delay_ms": (200, 500),
        "mouse_move_to_target": True,
        "mouse_move_steps": 5,
        "mouse_move_speed_ms": 8,
        "mouse_curve": "linear",
        "mouse_jitter_px": 1,
        "click_offset_px": 2,
        "hover_before_click_ms": (10, 50),
        "scroll_enabled": True,
        "scroll_delay_ms": 100,
        "headless": False,
        "hide_webdriver": False,
        "viewport": (1920, 1080),
        "user_agent": None,
        "slow_mo": 20,
        "retry_count": 7,
        "retry_delay_ms": (100, 300),
        "seat_strategy": "first_available",
        "max_seat_attempts": 5,
    },
    4: {
        "name": "Lv.4 개선된 봇",
        "description": "약간의 랜덤성 추가, 여전히 기계적",
        "level": 4,
        "action_delay_ms": (400, 900),
        "typing_delay_ms": (20, 50),
        "typing_use_paste": False,
        "queue_poll_ms": (1000, 2000),
        "queue_ignore_server_interval": True,
        "seat_select_delay_ms": (500, 1200),
        "mouse_move_to_target": True,
        "mouse_move_steps": 8,
        "mouse_move_speed_ms": 12,
        "mouse_curve": "linear",
        "mouse_jitter_px": 2,
        "click_offset_px": 3,
        "hover_before_click_ms": (30, 100),
        "scroll_enabled": True,
        "scroll_delay_ms": 300,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 30,
        "retry_count": 5,
        "retry_delay_ms": (200, 600),
        "seat_strategy": "best_available",
        "max_seat_attempts": 4,
    },
    5: {
        "name": "Lv.5 경계 단계",
        "description": "봇과 사람의 경계. 곡선 마우스 시작",
        "level": 5,
        "action_delay_ms": (700, 1500),
        "typing_delay_ms": (40, 80),
        "typing_use_paste": False,
        "queue_poll_ms": (2000, 3000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (1000, 3000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 12,
        "mouse_move_speed_ms": 15,
        "mouse_curve": "ease_in_out",
        "mouse_jitter_px": 3,
        "click_offset_px": 5,
        "hover_before_click_ms": (50, 200),
        "scroll_enabled": True,
        "scroll_delay_ms": 500,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 3,
        "retry_delay_ms": (500, 1500),
        "seat_strategy": "random_good",
        "max_seat_attempts": 3,
    },
    6: {
        "name": "Lv.6 반자동",
        "description": "사람이 보조 도구를 사용하는 수준",
        "level": 6,
        "action_delay_ms": (1000, 2500),
        "typing_delay_ms": (50, 120),
        "typing_use_paste": False,
        "queue_poll_ms": (2500, 4000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (2000, 5000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 15,
        "mouse_move_speed_ms": 18,
        "mouse_curve": "bezier",
        "mouse_jitter_px": 4,
        "click_offset_px": 6,
        "hover_before_click_ms": (100, 400),
        "scroll_enabled": True,
        "scroll_delay_ms": 800,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 2,
        "retry_delay_ms": (1000, 3000),
        "seat_strategy": "random_good",
        "max_seat_attempts": 2,
    },
    7: {
        "name": "Lv.7 스텔스 봇",
        "description": "탐지 회피를 시도하는 고급 봇",
        "level": 7,
        "action_delay_ms": (1500, 3500),
        "typing_delay_ms": (60, 150),
        "typing_use_paste": False,
        "queue_poll_ms": (3000, 5000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (3000, 8000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 20,
        "mouse_move_speed_ms": 16,
        "mouse_curve": "bezier",
        "mouse_jitter_px": 5,
        "click_offset_px": 8,
        "hover_before_click_ms": (200, 600),
        "scroll_enabled": True,
        "scroll_delay_ms": 1000,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 1,
        "retry_delay_ms": (2000, 5000),
        "seat_strategy": "random_good",
        "max_seat_attempts": 2,
    },
    8: {
        "name": "Lv.8 고급 스텔스",
        "description": "사람 행동을 정밀하게 흉내내는 봇",
        "level": 8,
        "action_delay_ms": (2000, 5000),
        "typing_delay_ms": (80, 200),
        "typing_use_paste": False,
        "queue_poll_ms": (3000, 6000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (5000, 15000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 25,
        "mouse_move_speed_ms": 14,
        "mouse_curve": "human_like",
        "mouse_jitter_px": 6,
        "click_offset_px": 10,
        "hover_before_click_ms": (300, 800),
        "scroll_enabled": True,
        "scroll_delay_ms": 1500,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 1,
        "retry_delay_ms": (3000, 8000),
        "seat_strategy": "browse_then_pick",
        "max_seat_attempts": 1,
    },
    9: {
        "name": "Lv.9 거의 사람",
        "description": "약간의 자동화만 있는, 사실상 사람",
        "level": 9,
        "action_delay_ms": (3000, 8000),
        "typing_delay_ms": (100, 280),
        "typing_use_paste": False,
        "queue_poll_ms": (4000, 8000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (8000, 25000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 30,
        "mouse_move_speed_ms": 12,
        "mouse_curve": "human_like",
        "mouse_jitter_px": 8,
        "click_offset_px": 12,
        "hover_before_click_ms": (500, 1500),
        "scroll_enabled": True,
        "scroll_delay_ms": 2000,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 0,
        "retry_delay_ms": (0, 0),
        "seat_strategy": "browse_then_pick",
        "max_seat_attempts": 1,
    },
    10: {
        "name": "Lv.10 사람 시뮬레이션",
        "description": "완전한 사람 행동 재현. 망설임, 실수, 되돌아감 포함",
        "level": 10,
        "action_delay_ms": (5000, 15000),
        "typing_delay_ms": (120, 350),
        "typing_use_paste": False,
        "queue_poll_ms": (5000, 10000),
        "queue_ignore_server_interval": False,
        "seat_select_delay_ms": (15000, 45000),
        "mouse_move_to_target": True,
        "mouse_move_steps": 40,
        "mouse_move_speed_ms": 10,
        "mouse_curve": "human_like",
        "mouse_jitter_px": 10,
        "click_offset_px": 15,
        "hover_before_click_ms": (800, 3000),
        "scroll_enabled": True,
        "scroll_delay_ms": 3000,
        "headless": False,
        "hide_webdriver": True,
        "viewport": (1920, 1080),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "slow_mo": 50,
        "retry_count": 0,
        "retry_delay_ms": (0, 0),
        "seat_strategy": "browse_then_pick",
        "max_seat_attempts": 1,
        "random_hesitation": True,
        "misclick_chance": 0.05,
        "backtrack_chance": 0.03,
        "idle_pause_chance": 0.1,
        "idle_pause_ms": (3000, 10000),
    },
}

# ============================================================
# 전처리 변수 - 레벨별 기대값 비교표
# ============================================================

LEVEL_COMPARISON = {
    "action_delay": {
        "description": "동작 간 딜레이 (ms)",
        "lv1": "30~80", "lv5": "700~1500", "lv10": "5000~15000",
        "weight": "HIGH",
    },
    "typing_speed": {
        "description": "타이핑 딜레이 (ms/char)",
        "lv1": "0 (paste)", "lv5": "40~80", "lv10": "120~350",
        "weight": "HIGH",
    },
    "mouse_path": {
        "description": "마우스 경로 유형",
        "lv1": "없음", "lv5": "ease_in_out", "lv10": "human_like+jitter",
        "weight": "CRITICAL",
    },
    "mouse_steps": {
        "description": "마우스 이동 스텝 수",
        "lv1": "0", "lv5": "12", "lv10": "40",
        "weight": "HIGH",
    },
    "hover_time": {
        "description": "클릭 전 호버 시간 (ms)",
        "lv1": "0", "lv5": "50~200", "lv10": "800~3000",
        "weight": "HIGH",
    },
    "click_precision": {
        "description": "클릭 오프셋 (px)",
        "lv1": "0 (정확)", "lv5": "5", "lv10": "15 (부정확)",
        "weight": "MEDIUM",
    },
    "seat_decision_time": {
        "description": "좌석 선택 소요 시간 (ms)",
        "lv1": "10~50", "lv5": "1000~3000", "lv10": "15000~45000",
        "weight": "CRITICAL",
    },
    "queue_poll_interval": {
        "description": "대기열 폴링 간격 (ms)",
        "lv1": "100~150", "lv5": "서버 준수", "lv10": "서버 준수",
        "weight": "HIGH",
    },
    "webdriver_flag": {
        "description": "webdriver 탐지",
        "lv1": "노출", "lv5": "은닉", "lv10": "은닉",
        "weight": "CRITICAL",
    },
    "retry_count": {
        "description": "실패 재시도 횟수",
        "lv1": "15", "lv5": "3", "lv10": "0",
        "weight": "MEDIUM",
    },
}

# ============================================================
# BE/FE 전처리 변수 목록
# ============================================================

BE_FEATURES = [
    "req_interval_mean_ms",
    "req_interval_std_ms",
    "req_interval_min_ms",
    "queue_poll_count",
    "queue_poll_mean_ms",
    "total_flow_duration_ms",
    "retry_count",
    "error_count",
    "seat_view_to_hold_ms",
    "seat_hold_attempts",
    "api_call_count",
    "session_count",
]

# ============================================================
# 예매 부가 설정 (공연/좌석/결제 상세 옵션)
# ============================================================

# 좌석 등급 (Truve 좌석 체계)
VALID_SEAT_GRADES = {"VIP", "R", "S", "A", "any"}

# 좌석 구역 (Truve 구역 체계)
VALID_SEAT_SECTIONS = {
    "OP",                           # 오케스트라 피트
    "1F-A", "1F-B", "1F-C",         # 1층
    "2F-A", "2F-B", "2F-C",         # 2층
    "any",                          # 아무 구역
}

# 결제 방식
VALID_PAY_METHODS = {"CARD", "VIRTUAL_ACCOUNT"}

# 수령 방식
VALID_RECEIPT_TYPES = {"NONE"}  # 현재 현장수령만 지원

# 은행 목록 (무통장 입금용)
VALID_BANKS = {
    "국민", "신한", "우리", "하나", "농협",
    "기업", "SC제일", "카카오뱅크", "토스뱅크", "케이뱅크",
}

# 카드사 목록 (카드 결제용)
VALID_CARD_COMPANIES = {
    "삼성", "현대", "KB국민", "신한", "롯데",
    "하나", "우리", "BC", "NH농협",
}

# 현금영수증 유형 (무통장 입금 시)
VALID_CASH_RECEIPTS = {"소득공제", "지출증빙", "미발행"}


def build_booking_options(
    seat_grade: str = "any",
    seat_section: str = "any",
    seat_count: int = 2,
    pay_method: str = "CARD",
    bank: str = "국민",
    card_company: str = "삼성",
    cash_receipt: str = "소득공제",
    schedule_date: str = None,
    schedule_time: str = None,
) -> dict:
    """
    [Rule 1] 예매 부가 옵션 검증 및 생성.
    CLI/환경변수에서 받은 값을 검증 후 딕셔너리로 반환.
    """
    # 좌석 등급 검증
    seat_grade = seat_grade.upper()
    if seat_grade != "ANY" and seat_grade not in VALID_SEAT_GRADES:
        raise ValueError(
            f"잘못된 좌석 등급: {seat_grade} (허용: {', '.join(sorted(VALID_SEAT_GRADES))})"
        )

    # 좌석 구역 검증
    seat_section = seat_section.upper()
    if seat_section != "ANY" and seat_section not in VALID_SEAT_SECTIONS:
        raise ValueError(
            f"잘못된 좌석 구역: {seat_section} (허용: {', '.join(sorted(VALID_SEAT_SECTIONS))})"
        )

    # 좌석 수 검증 (1~4석)
    if not isinstance(seat_count, int) or seat_count < 1 or seat_count > 4:
        raise ValueError(f"잘못된 좌석 수: {seat_count} (1~4)")

    # 결제 방식 검증
    pay_method = pay_method.upper()
    if pay_method not in VALID_PAY_METHODS:
        raise ValueError(
            f"잘못된 결제 방식: {pay_method} (허용: {', '.join(VALID_PAY_METHODS)})"
        )

    # 날짜 형식 검증 (YYYY-MM-DD)
    if schedule_date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", schedule_date):
            raise ValueError(f"잘못된 날짜 형식: {schedule_date} (YYYY-MM-DD)")

    # 시간 형식 검증 (HH:MM)
    if schedule_time:
        if not re.match(r"^\d{2}:\d{2}$", schedule_time):
            raise ValueError(f"잘못된 시간 형식: {schedule_time} (HH:MM)")

    # 은행 검증 (무통장 입금 시)
    if pay_method == "VIRTUAL_ACCOUNT" and bank not in VALID_BANKS:
        raise ValueError(
            f"잘못된 은행: {bank} (허용: {', '.join(sorted(VALID_BANKS))})"
        )

    # 카드사 검증 (카드 결제 시)
    if pay_method == "CARD" and card_company not in VALID_CARD_COMPANIES:
        raise ValueError(
            f"잘못된 카드사: {card_company} (허용: {', '.join(sorted(VALID_CARD_COMPANIES))})"
        )

    # 현금영수증 검증
    if cash_receipt not in VALID_CASH_RECEIPTS:
        raise ValueError(
            f"잘못된 현금영수증: {cash_receipt} (허용: {', '.join(VALID_CASH_RECEIPTS)})"
        )

    return {
        "seat_grade": seat_grade.lower(),
        "seat_section": seat_section,
        "seat_count": seat_count,
        "pay_method": pay_method,
        "bank": bank,                     # 무통장 입금 은행
        "card_company": card_company,     # 카드 결제 카드사
        "cash_receipt": cash_receipt,     # 현금영수증 유형
        "schedule_date": schedule_date,
        "schedule_time": schedule_time,
    }


FE_FEATURES = [
    "webdriver_detected",
    "plugins_count",
    "mouse_move_count",
    "mouse_speed_avg",
    "mouse_speed_var",
    "mouse_linearity",
    "click_count",
    "click_interval_mean_ms",
    "hover_before_click_ms",
    "keystroke_interval_mean",
    "keystroke_interval_var",
    "paste_count",
    "scroll_count",
    "scroll_direction_changes",
    "time_on_page_ms",
]
