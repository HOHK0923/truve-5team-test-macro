"""
BE 전용 API 직접호출 매크로
requests 기반으로 Truve 예매 플로우를 자동화하고,
사람과 명확히 구분되는 BE 전처리 변수 패턴을 생성한다.

예매 플로우:
  1. 로그인 → accessToken 획득
  2. 공연 정보 조회
  3. 대기열 진입 → 폴링 → admissionToken 획득
  4. 티켓팅 입장 → sessionToken 획득
  5. 좌석 배치도 조회
  6. 좌석 선점 (최대 4석)
  7. 예매 생성
  8. 결제 준비
"""

import time
import uuid
import random
import requests
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor

from config import BASE_URL, BOT_PROFILES, TEST_ACCOUNTS
from data_logger import DataLogger, BEDataRecord


class APIMacro:
    """BE 전용 API 직접호출 매크로"""

    def __init__(self, base_url: str, profile_name: str, logger: DataLogger):
        self.base_url = base_url.rstrip("/")
        self.profile = BOT_PROFILES[profile_name]
        self.profile_name = profile_name
        self.logger = logger
        self.session = requests.Session()
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.admission_token: str = ""
        self.session_ticket: str = ""
        self._last_request_time: float = 0
        self._be_record = BEDataRecord(
            run_id=str(uuid.uuid4())[:8],
            bot_profile=profile_name,
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self, extra: dict = None) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.profile["user_agent"],
        }
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        if self.session_ticket:
            h["X-Session-Ticket"] = self.session_ticket
        if extra:
            h.update(extra)
        return h

    def _wait_interval(self):
        """프로필에 정의된 요청 간격만큼 대기 (봇: 매우 짧음)"""
        interval = self.profile["request_interval_ms"]
        variance = self.profile["request_interval_variance"]
        delay_ms = interval + random.uniform(-variance, variance)
        delay_ms = max(0, delay_ms)
        time.sleep(delay_ms / 1000.0)

    def _record_interval(self):
        """요청 간격을 기록"""
        now = time.time() * 1000
        if self._last_request_time > 0:
            interval = now - self._last_request_time
            self._be_record.req_intervals_ms.append(round(interval, 2))
        self._last_request_time = now

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, extra_headers: dict = None,
                 is_retry: bool = False) -> requests.Response:
        """공통 요청 래퍼 - 모든 요청을 로깅"""
        self._wait_interval()
        self._record_interval()

        url = self._url(path)
        headers = self._headers(extra_headers)

        start = time.time()
        try:
            resp = self.session.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,
                timeout=10,
                allow_redirects=False,
            )
            elapsed_ms = (time.time() - start) * 1000

            self.logger.log_request(
                endpoint=path,
                method=method,
                status_code=resp.status_code,
                response_time_ms=elapsed_ms,
                headers=dict(headers),
            )
            self._be_record.api_call_sequence.append(path)
            self._be_record.http_status_codes.append(resp.status_code)

            if resp.status_code >= 400:
                self._be_record.error_count += 1

            return resp

        except requests.RequestException as e:
            elapsed_ms = (time.time() - start) * 1000
            self.logger.log_request(
                endpoint=path, method=method, status_code=0,
                response_time_ms=elapsed_ms, error=str(e),
            )
            self._be_record.error_count += 1
            raise

    def _retry_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """재시도 로직 - 봇은 공격적으로 재시도"""
        max_retries = self.profile["retry_on_fail"]
        retry_delay = self.profile["retry_delay_ms"]

        for attempt in range(max_retries):
            try:
                resp = self._request(method, path, is_retry=(attempt > 0), **kwargs)
                if resp.status_code < 400:
                    return resp
                # 4xx/5xx 에러시 재시도
                self._be_record.retry_count += 1
                self._be_record.retry_intervals_ms.append(retry_delay)
                time.sleep(retry_delay / 1000.0)
            except requests.RequestException:
                self._be_record.retry_count += 1
                self._be_record.retry_intervals_ms.append(retry_delay)
                time.sleep(retry_delay / 1000.0)

        raise RuntimeError(f"Max retries ({max_retries}) exceeded for {path}")

    # ================================================================
    # Step 1: 로그인
    # ================================================================
    def login(self, email: str, password: str) -> bool:
        """이메일/패스워드 로그인 → accessToken 획득"""
        print(f"  [1/8] 로그인: {email}")
        self._be_record.login_method = "email"
        login_start = time.time()

        resp = self._retry_request(
            "POST", "/api/auth/login",
            json_data={"email": email, "password": password},
        )

        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("data", {}).get("accessToken", "")
            # refreshToken은 Set-Cookie에 있을 수 있음
            if "refreshToken" in self.session.cookies:
                self.refresh_token = self.session.cookies["refreshToken"]

            self._be_record.login_to_queue_ms = (time.time() - login_start) * 1000
            print(f"    -> 로그인 성공 (token: {self.access_token[:20]}...)")
            return True

        print(f"    -> 로그인 실패: {resp.status_code}")
        return False

    # ================================================================
    # Step 2: 공연 정보 조회
    # ================================================================
    def get_show_info(self, show_id: int) -> dict:
        """공연 상세 정보 조회"""
        print(f"  [2/8] 공연 정보 조회: showId={show_id}")
        resp = self._retry_request("GET", f"/api/shows/{show_id}")

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            print(f"    -> {data.get('title', 'N/A')} @ {data.get('venue', {}).get('name', 'N/A')}")
            return data
        return {}

    # ================================================================
    # Step 3: 대기열 진입 + 폴링
    # ================================================================
    def enter_queue(self, show_id: int, user_id: str = None) -> str:
        """대기열 진입"""
        print(f"  [3/8] 대기열 진입: showId={show_id}")
        headers = {}
        if user_id:
            headers["X-User-Id"] = user_id

        resp = self._retry_request(
            "POST", f"/api/queue/{show_id}/enter",
            extra_headers=headers,
        )

        if resp.status_code == 200:
            print("    -> 대기열 진입 성공")
            return "OK"
        return ""

    def poll_queue_status(self, show_id: int, user_id: str = None) -> str:
        """대기열 상태 폴링 - 봇은 서버 권장 간격 무시하고 빠르게 폴링"""
        print(f"  [3/8] 대기열 폴링 시작...")
        headers = {}
        if user_id:
            headers["X-User-Id"] = user_id

        max_polls = 200
        poll_count = 0

        while poll_count < max_polls:
            poll_start = time.time()

            resp = self._request(
                "GET", f"/api/queue/{show_id}/status",
                extra_headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                status = data.get("status", "")
                rank = data.get("rank", -1)
                server_poll_ms = data.get("pollingMs", 3000)
                admission_token = data.get("admissionToken", "")

                poll_count += 1
                poll_elapsed = (time.time() - poll_start) * 1000
                self._be_record.queue_poll_intervals_ms.append(round(poll_elapsed, 2))
                self._be_record.queue_poll_count = poll_count

                if status == "READY" and admission_token:
                    self.admission_token = admission_token
                    print(f"    -> 대기열 통과! (폴링 {poll_count}회)")
                    return admission_token

                if status == "EXPIRE":
                    print(f"    -> 대기열 만료")
                    return ""

                # 봇 폴링 간격: 프로필 설정 사용 (서버 권장 무시 가능)
                if self.profile["queue_poll_ignore_server"]:
                    wait_ms = self.profile["queue_poll_interval_ms"]
                else:
                    wait_ms = server_poll_ms

                print(f"    -> WAITING (순위: {rank}, 대기자: {data.get('waitingUserCount', '?')})")
                time.sleep(wait_ms / 1000.0)
            else:
                poll_count += 1
                time.sleep(self.profile["queue_poll_interval_ms"] / 1000.0)

        print(f"    -> 대기열 폴링 제한 초과 ({max_polls}회)")
        return ""

    # ================================================================
    # Step 4: 티켓팅 입장
    # ================================================================
    def enter_ticketing(self, show_schedule_id: int) -> str:
        """대기열 통과 후 티켓팅 세션 입장"""
        print(f"  [4/8] 티켓팅 입장: scheduleId={show_schedule_id}")

        resp = self._retry_request(
            "POST", f"/api/ticketing/{show_schedule_id}/enter",
            extra_headers={"X-Admission-Token": self.admission_token},
        )

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            self.session_ticket = data.get("sessionToken", "")
            expire_in = data.get("expireIn", 0)
            print(f"    -> 티켓팅 입장 성공 (만료: {expire_in}초)")
            return self.session_ticket
        return ""

    # ================================================================
    # Step 5: 좌석 배치도 조회
    # ================================================================
    def get_seat_map(self, show_schedule_id: int) -> dict:
        """좌석 배치도 조회"""
        print(f"  [5/8] 좌석 배치도 조회")

        resp = self._retry_request(
            "GET", f"/api/ticketing/{show_schedule_id}",
        )

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            sections = data.get("sections", [])
            total_seats = 0
            available = 0
            for sec in sections:
                for row in sec.get("rows", []):
                    for seat in row.get("seats", []):
                        total_seats += 1
                        if seat.get("status") == "AVAILABLE":
                            available += 1
            print(f"    -> 총 {total_seats}석 중 {available}석 예매 가능")
            return data
        return {}

    # ================================================================
    # Step 6: 좌석 선점
    # ================================================================
    def hold_seats(self, show_schedule_id: int, seat_map: dict) -> list:
        """좌석 선점 - 봇은 최대한 빠르게 첫 가용 좌석 선점"""
        print(f"  [6/8] 좌석 선점")
        seat_view_start = time.time()

        # 전략에 따른 좌석 선택
        available_seats = []
        for sec in seat_map.get("sections", []):
            for row in sec.get("rows", []):
                for seat in row.get("seats", []):
                    if seat.get("status") == "AVAILABLE":
                        available_seats.append(seat["seatId"])

        if not available_seats:
            print("    -> 예매 가능한 좌석 없음")
            return []

        strategy = self.profile["seat_selection_strategy"]
        max_seats = min(4, len(available_seats))

        if strategy == "first_available":
            # 순차적으로 첫 N개 선택 (가장 봇스러움)
            selected = available_seats[:max_seats]
            self._be_record.seat_selection_pattern = "sequential"
        elif strategy == "best_available":
            # 가격 높은 순 (실제로는 section 정보 기반)
            selected = available_seats[:max_seats]
            self._be_record.seat_selection_pattern = "targeted"
        elif strategy == "random_good":
            # 랜덤 선택 (스텔스)
            selected = random.sample(available_seats, max_seats)
            self._be_record.seat_selection_pattern = "random"
        else:
            selected = available_seats[:max_seats]
            self._be_record.seat_selection_pattern = "sequential"

        # 좌석 선점 시도
        max_attempts = self.profile["seat_retry_count"]
        for attempt in range(max_attempts):
            resp = self._request(
                "POST", f"/api/ticketing/{show_schedule_id}/hold/seat",
                json_data={"seatIds": selected},
            )

            self._be_record.seat_hold_attempts += 1

            if resp.status_code == 200:
                self._be_record.seat_view_to_hold_ms = (time.time() - seat_view_start) * 1000
                self._be_record.selected_seat_ids = selected
                print(f"    -> 좌석 선점 성공: {selected} (시도: {attempt + 1}회)")
                return selected

            # 실패시 다른 좌석으로 변경 시도
            self._be_record.seat_change_count += 1
            if len(available_seats) > max_seats:
                selected = available_seats[max_seats * (attempt + 1):max_seats * (attempt + 2)]
                if not selected:
                    selected = random.sample(available_seats, max_seats)

        print(f"    -> 좌석 선점 실패 ({max_attempts}회 시도)")
        return []

    # ================================================================
    # Step 7: 예매 생성
    # ================================================================
    def create_booking(self, seat_ids: list, user_id: str = None) -> str:
        """예매 내역 생성"""
        print(f"  [7/8] 예매 생성: seats={seat_ids}")
        headers = {}
        if user_id:
            headers["X-User-Id"] = user_id

        resp = self._retry_request(
            "POST", "/api/bookings",
            json_data={"seatIds": seat_ids},
            extra_headers=headers,
        )

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            reservation = data.get("seatIds", seat_ids)
            print(f"    -> 예매 생성 성공")
            return str(data)
        return ""

    # ================================================================
    # Step 8: 결제 준비
    # ================================================================
    def payment_ready(self, reservation_number: str, applicant: dict) -> bool:
        """예매 결제 준비"""
        print(f"  [8/8] 결제 준비: {reservation_number}")

        resp = self._retry_request(
            "POST", f"/api/bookings/{reservation_number}/payment-ready",
            json_data=applicant,
        )

        if resp.status_code == 200:
            print("    -> 결제 준비 완료")
            return True
        return False

    # ================================================================
    # Heartbeat (세션 유지)
    # ================================================================
    def send_heartbeat(self, show_schedule_id: int):
        """티켓팅 세션 heartbeat"""
        resp = self._request(
            "POST", f"/api/ticketing/{show_schedule_id}/heartbeat",
        )
        self._be_record.heartbeat_count += 1
        return resp.status_code == 200

    # ================================================================
    # 전체 플로우 실행
    # ================================================================
    def run_full_flow(self, account: dict, show_id: int,
                      schedule_id: int, user_id: str = None) -> BEDataRecord:
        """
        전체 예매 매크로 플로우 실행
        모든 단계의 타이밍/행동 데이터를 수집
        """
        flow_start = time.time()
        self._be_record.session_count = 1
        self._be_record.source_ip = "macro_client"
        self._be_record.user_agent = self.profile["user_agent"]

        if not user_id:
            user_id = str(uuid.uuid4())

        try:
            # Step 1: 로그인
            if not self.login(account["email"], account["password"]):
                print("  [!] 로그인 실패 - 플로우 중단")
                self._be_record.total_flow_duration_ms = (time.time() - flow_start) * 1000
                return self._be_record

            # Step 2: 공연 정보 조회
            show_info = self.get_show_info(show_id)

            # Step 3: 대기열
            self.enter_queue(show_id, user_id)
            admission = self.poll_queue_status(show_id, user_id)
            if not admission:
                print("  [!] 대기열 통과 실패 - 플로우 중단")
                self._be_record.total_flow_duration_ms = (time.time() - flow_start) * 1000
                return self._be_record

            # Step 4: 티켓팅 입장
            session = self.enter_ticketing(schedule_id)
            if not session:
                print("  [!] 티켓팅 입장 실패 - 플로우 중단")
                self._be_record.total_flow_duration_ms = (time.time() - flow_start) * 1000
                return self._be_record

            # Step 5: 좌석 조회
            seat_map = self.get_seat_map(schedule_id)

            # Step 6: 좌석 선점
            held_seats = self.hold_seats(schedule_id, seat_map)
            if not held_seats:
                print("  [!] 좌석 선점 실패 - 플로우 중단")
                self._be_record.total_flow_duration_ms = (time.time() - flow_start) * 1000
                return self._be_record

            # Step 7: 예매 생성
            booking = self.create_booking(held_seats, user_id)

            # Step 8: 결제 준비 (테스트 데이터)
            if booking:
                self.payment_ready("TEST-RES-001", {
                    "name": "테스트봇",
                    "birthDate": "2000-01-01",
                    "email": account["email"],
                    "phone": "010-0000-0000",
                })

            print(f"\n  [완료] 전체 플로우 성공!")

        except Exception as e:
            print(f"  [에러] 플로우 중 예외: {e}")

        self._be_record.total_flow_duration_ms = (time.time() - flow_start) * 1000
        self._be_record.session_duration_ms = self._be_record.total_flow_duration_ms
        return self._be_record


class ConcurrentAPIMacro:
    """동시 다중 세션 매크로 - 같은 IP에서 여러 계정으로 동시 예매"""

    def __init__(self, base_url: str, profile_name: str, logger: DataLogger):
        self.base_url = base_url
        self.profile_name = profile_name
        self.profile = BOT_PROFILES[profile_name]
        self.logger = logger

    def run_concurrent(self, accounts: list, show_id: int,
                       schedule_id: int) -> list[BEDataRecord]:
        """여러 계정으로 동시에 매크로 실행"""
        concurrent = self.profile["concurrent_sessions"]
        accounts_to_use = accounts[:concurrent]

        print(f"\n{'='*60}")
        print(f"  동시 매크로 실행: {len(accounts_to_use)}세션")
        print(f"  프로필: {self.profile['name']}")
        print(f"{'='*60}")

        records = []

        with ThreadPoolExecutor(max_workers=concurrent) as executor:
            futures = []
            for i, account in enumerate(accounts_to_use):
                macro = APIMacro(self.base_url, self.profile_name, self.logger)
                macro._be_record.session_count = concurrent
                future = executor.submit(
                    macro.run_full_flow,
                    account, show_id, schedule_id,
                    user_id=str(uuid.uuid4()),
                )
                futures.append(future)

            for future in futures:
                try:
                    record = future.result(timeout=120)
                    records.append(record)
                except Exception as e:
                    print(f"  [에러] 세션 실패: {e}")

        # 동시 세션 수 기록
        for rec in records:
            rec.session_count = len(records)

        return records
