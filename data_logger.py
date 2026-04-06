"""
전처리 변수 수집/로깅 모듈
모든 매크로 행동 데이터를 CSV/JSON으로 기록하여 BE/FE 모델 학습용 rawdata 생성

보안 기준:
  - Rule 4: 로그에 Authorization 헤더/크리덴셜 노출 방지, 민감 헤더 자동 제거
  - Rule 0: 출력 파일 경로 검증(Path Traversal 방어)
  - Rule 1: output_dir 입력값 정규화 및 검증
"""

import csv
import json
import os
import re
import stat
import time
import statistics
from datetime import datetime
from dataclasses import dataclass, field, asdict

# [Rule 4] 로그에서 제거해야 할 민감 헤더 키 목록
_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie",
    "x-token", "x-session-ticket", "x-admission-token",
    "refresh-token", "refreshtoken",
})


def _sanitize_headers(headers: dict) -> dict:
    """
    [Rule 4] 민감 헤더 제거 후 반환.
    Authorization, Cookie 등 인증 관련 헤더는 로그/파일에 기록하지 않는다.
    """
    if not headers:
        return {}
    return {
        k: v for k, v in headers.items()
        if k.lower() not in _SENSITIVE_HEADERS
    }


def _validate_output_path(output_dir: str) -> str:
    """
    [Rule 0/1] 출력 경로 검증.
    - Path Traversal 방어 (.. 포함 여부)
    - 절대경로 정규화
    - 허용되지 않은 문자 검증
    """
    # .. 경로 탐색 차단
    normalized = os.path.normpath(output_dir)
    if ".." in normalized.split(os.sep):
        raise ValueError(f"경로 탐색 시도 차단: {output_dir}")

    # 특수문자 제한 (영문, 숫자, 한글, -, _, /, \\, ., 공백 허용)
    if re.search(r'[;&|`$]', output_dir):
        raise ValueError(f"허용되지 않은 문자 포함: {output_dir}")

    return normalized


@dataclass
class BEDataRecord:
    """BE 모델 학습용 rawdata 레코드 (1 예매 플로우 = 1 레코드)"""

    # 메타
    run_id: str = ""
    bot_profile: str = ""  # level_N
    level: int = 0
    scenario: str = ""     # bot / stealth / manual
    tag: str = ""          # 커스텀 태그
    is_bot: int = 1
    timestamp: str = ""

    # 타이밍 변수
    req_intervals_ms: list = field(default_factory=list)
    req_interval_mean_ms: float = 0.0
    req_interval_std_ms: float = 0.0
    req_interval_min_ms: float = 0.0
    req_interval_max_ms: float = 0.0
    queue_poll_intervals_ms: list = field(default_factory=list)
    queue_poll_interval_mean_ms: float = 0.0
    queue_poll_count: int = 0
    total_flow_duration_ms: float = 0.0
    login_to_queue_ms: float = 0.0

    # 요청 패턴 변수
    api_call_sequence: list = field(default_factory=list)
    api_call_count: int = 0
    retry_count: int = 0
    retry_intervals_ms: list = field(default_factory=list)
    error_count: int = 0
    http_status_codes: list = field(default_factory=list)

    # 좌석 선택 변수
    seat_view_to_hold_ms: float = 0.0
    seat_hold_attempts: int = 0
    seat_change_count: int = 0
    selected_seat_ids: list = field(default_factory=list)
    seat_selection_pattern: str = ""

    # 세션 변수
    session_count: int = 0
    heartbeat_interval_ms: float = 0.0
    heartbeat_count: int = 0
    session_duration_ms: float = 0.0

    # 네트워크 변수 (민감정보 제외: IP 미수집)
    user_agent: str = ""
    login_method: str = ""
    token_reissue_count: int = 0

    def compute_stats(self):
        """수집된 raw 데이터로 통계 변수 계산"""
        if len(self.req_intervals_ms) > 0:
            self.req_interval_mean_ms = statistics.mean(self.req_intervals_ms)
            self.req_interval_min_ms = min(self.req_intervals_ms)
            self.req_interval_max_ms = max(self.req_intervals_ms)
            if len(self.req_intervals_ms) > 1:
                self.req_interval_std_ms = statistics.stdev(self.req_intervals_ms)
        if len(self.queue_poll_intervals_ms) > 0:
            self.queue_poll_interval_mean_ms = statistics.mean(self.queue_poll_intervals_ms)
        self.api_call_count = len(self.api_call_sequence)


@dataclass
class FEDataRecord:
    """FE 모델 학습용 rawdata 레코드 (1 예매 플로우 = 1 레코드)"""

    # 메타
    run_id: str = ""
    bot_profile: str = ""
    level: int = 0
    scenario: str = ""
    tag: str = ""
    is_bot: int = 1
    timestamp: str = ""

    # 브라우저 핑거프린트
    webdriver_detected: bool = True
    plugins_count: int = 0
    languages: str = ""
    platform: str = ""
    screen_resolution: str = ""
    viewport_size: str = ""
    color_depth: int = 0
    timezone: str = ""
    canvas_hash: str = ""
    webgl_renderer: str = ""

    # 마우스 행동
    mouse_move_count: int = 0
    mouse_move_speed_avg: float = 0.0
    mouse_move_speed_var: float = 0.0
    mouse_path_linearity: float = 0.0
    mouse_idle_periods: int = 0
    click_count: int = 0
    click_coordinate_variance: float = 0.0
    click_intervals_ms: list = field(default_factory=list)
    click_interval_mean_ms: float = 0.0
    hover_before_click_ms: float = 0.0

    # 키보드 행동
    keystroke_count: int = 0
    keystroke_intervals_ms: list = field(default_factory=list)
    keystroke_interval_mean_ms: float = 0.0
    keystroke_interval_var: float = 0.0
    paste_event_count: int = 0
    key_hold_duration_avg_ms: float = 0.0

    # 스크롤/페이지 행동
    scroll_count: int = 0
    scroll_speed_avg: float = 0.0
    scroll_direction_changes: int = 0
    page_visibility_changes: int = 0
    focus_blur_count: int = 0
    time_on_page_ms: float = 0.0

    # DevTools 탐지
    devtools_open: bool = False
    console_log_detected: bool = False

    def compute_stats(self):
        if len(self.click_intervals_ms) > 0:
            self.click_interval_mean_ms = statistics.mean(self.click_intervals_ms)
        if len(self.keystroke_intervals_ms) > 0:
            self.keystroke_interval_mean_ms = statistics.mean(self.keystroke_intervals_ms)
            if len(self.keystroke_intervals_ms) > 1:
                self.keystroke_interval_var = statistics.variance(self.keystroke_intervals_ms)


class DataLogger:
    """매크로 실행 데이터를 수집하고 파일로 기록"""

    def __init__(self, output_dir: str = "./output"):
        # [Rule 0] 경로 검증
        self.output_dir = _validate_output_path(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.be_records: list[BEDataRecord] = []
        self.fe_records: list[FEDataRecord] = []
        self._request_log: list[dict] = []

    def log_request(self, endpoint: str, method: str, status_code: int,
                    response_time_ms: float, headers: dict = None,
                    error: str = None):
        """
        개별 API 요청 로그.
        [Rule 4] 민감 헤더(Authorization 등)는 자동 제거.
        """
        entry = {
            "timestamp": time.time(),
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            # [Rule 4] 민감 헤더 제거 후 기록
            "headers": _sanitize_headers(headers),
            "error": error,
        }
        self._request_log.append(entry)

    def add_be_record(self, record: BEDataRecord):
        record.compute_stats()
        record.timestamp = datetime.now().isoformat()
        self.be_records.append(record)

    def add_fe_record(self, record: FEDataRecord):
        record.compute_stats()
        record.timestamp = datetime.now().isoformat()
        self.fe_records.append(record)

    def _safe_write_file(self, filepath: str, write_fn) -> str:
        """
        [Rule 0] 안전한 파일 쓰기 래퍼.
        - 경로 재검증
        - owner-only 퍼미션 설정 (0o600)
        """
        # 경로가 output_dir 내부인지 재확인
        abs_output = os.path.abspath(self.output_dir)
        abs_file = os.path.abspath(filepath)
        if not abs_file.startswith(abs_output):
            raise ValueError(f"출력 경로 이탈 차단: {filepath}")

        write_fn(filepath)

        # 파일 퍼미션: owner 읽기/쓰기만 (Windows에서는 best-effort)
        try:
            os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows에서 chmod 제한 시 무시

        return filepath

    def save_be_csv(self) -> str:
        """BE rawdata를 CSV로 저장"""
        filepath = os.path.join(
            self.output_dir, f"be_rawdata_{self.timestamp}.csv"
        )
        if not self.be_records:
            return filepath

        rows = []
        for rec in self.be_records:
            d = asdict(rec)
            for k, v in d.items():
                if isinstance(v, list):
                    d[k] = json.dumps(v)
            rows.append(d)

        def _write(fp):
            with open(fp, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        self._safe_write_file(filepath, _write)
        print(f"[DataLogger] BE rawdata 저장: {filepath} ({len(rows)}건)")
        return filepath

    def save_fe_csv(self) -> str:
        """FE rawdata를 CSV로 저장"""
        filepath = os.path.join(
            self.output_dir, f"fe_rawdata_{self.timestamp}.csv"
        )
        if not self.fe_records:
            return filepath

        rows = []
        for rec in self.fe_records:
            d = asdict(rec)
            for k, v in d.items():
                if isinstance(v, list):
                    d[k] = json.dumps(v)
            rows.append(d)

        def _write(fp):
            with open(fp, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        self._safe_write_file(filepath, _write)
        print(f"[DataLogger] FE rawdata 저장: {filepath} ({len(rows)}건)")
        return filepath

    def save_combined_json(self) -> str:
        """BE + FE 통합 rawdata를 JSON으로 저장"""
        filepath = os.path.join(
            self.output_dir, f"combined_rawdata_{self.timestamp}.json"
        )

        combined = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_be_records": len(self.be_records),
                "total_fe_records": len(self.fe_records),
                "total_api_requests": len(self._request_log),
                "purpose": "매크로 탐지 모델 학습용 봇 행동 데이터",
            },
            "be_records": [asdict(r) for r in self.be_records],
            "fe_records": [asdict(r) for r in self.fe_records],
            # [Rule 4] request_log에는 이미 sanitize된 헤더만 포함
            "request_log": self._request_log,
        }

        def _write(fp):
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2, default=str)

        self._safe_write_file(filepath, _write)
        print(f"[DataLogger] 통합 rawdata 저장: {filepath}")
        return filepath

    def save_all(self) -> dict:
        """모든 형식으로 저장"""
        return {
            "be_csv": self.save_be_csv(),
            "fe_csv": self.save_fe_csv(),
            "combined_json": self.save_combined_json(),
        }

    def print_summary(self):
        """수집 결과 요약 출력 (민감정보 미포함)"""
        print("\n" + "=" * 60)
        print("  매크로 데이터 수집 결과 요약")
        print("=" * 60)
        print(f"  BE 레코드: {len(self.be_records)}건")
        print(f"  FE 레코드: {len(self.fe_records)}건")
        print(f"  총 API 요청: {len(self._request_log)}건")

        if self.be_records:
            valid = [r.req_interval_mean_ms for r in self.be_records if r.req_interval_mean_ms > 0]
            avg_interval = statistics.mean(valid) if valid else 0
            valid_flow = [r.total_flow_duration_ms for r in self.be_records if r.total_flow_duration_ms > 0]
            avg_flow = statistics.mean(valid_flow) if valid_flow else 0
            total_retries = sum(r.retry_count for r in self.be_records)

            print(f"\n  [BE 변수 통계]")
            print(f"  평균 요청 간격: {avg_interval:.1f}ms")
            print(f"  평균 플로우 소요: {avg_flow:.1f}ms")
            print(f"  총 재시도 횟수: {total_retries}회")

        if self.fe_records:
            avg_mouse = statistics.mean([r.mouse_move_count for r in self.fe_records])
            avg_clicks = statistics.mean([r.click_count for r in self.fe_records])
            webdriver_count = sum(1 for r in self.fe_records if r.webdriver_detected)

            print(f"\n  [FE 변수 통계]")
            print(f"  평균 마우스 이동: {avg_mouse:.0f}회")
            print(f"  평균 클릭: {avg_clicks:.0f}회")
            print(f"  webdriver 탐지: {webdriver_count}/{len(self.fe_records)}건")

        print("=" * 60)
