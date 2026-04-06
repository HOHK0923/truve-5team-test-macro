"""
Truve 예매 매크로 - Playwright headed 모드
실제 브라우저 화면에서 마우스가 움직이고, 클릭되고, 키보드 입력되는 것이 보임.

프론트엔드 구조 (Next.js App Router):
  /signin                     → 로그인
  /shows/now                  → 공연 목록
  /shows/{showId}             → 공연 상세 (예매하기 버튼 → 캡차 → 대기열)
  /shows/{showId}/seat        → 좌석 선택 (PixiJS Canvas)
  /payments                   → 결제 (예약자 정보 입력 + Toss 결제)

주의: 좌석 선택 페이지는 PixiJS Canvas로 렌더링됨 → Canvas 좌표 클릭 필요
"""

import asyncio
import math
import random
import time
import uuid

from config import BOT_LEVELS, BASE_URL, mask_email
from data_logger import DataLogger, BEDataRecord, FEDataRecord

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARN] playwright 미설치.")
    print("  pip install playwright && playwright install chromium")


class MouseController:
    """레벨별 마우스 움직임 제어 - 화면에서 실제로 보임"""

    def __init__(self, page: Page, level_config: dict):
        self.page = page
        self.cfg = level_config
        self.current_x = 400.0
        self.current_y = 300.0
        self.move_log: list[dict] = []

    async def move_to(self, target_x: float, target_y: float):
        """레벨에 맞는 마우스 이동 - 화면에서 커서가 움직이는 것이 보임"""
        if not self.cfg["mouse_move_to_target"]:
            self.current_x = target_x
            self.current_y = target_y
            return

        steps = self.cfg["mouse_move_steps"]
        speed_ms = self.cfg["mouse_move_speed_ms"]
        curve = self.cfg["mouse_curve"]
        jitter = self.cfg["mouse_jitter_px"]

        sx, sy = self.current_x, self.current_y

        # 베지어 곡선용 제어점 (한 번만 생성)
        ctrl_x = (sx + target_x) / 2 + random.uniform(-80, 80)
        ctrl_y = (sy + target_y) / 2 + random.uniform(-50, 50)

        for i in range(1, steps + 1):
            t = i / steps

            if curve == "none":
                x, y = target_x, target_y
            elif curve == "linear":
                x = sx + (target_x - sx) * t
                y = sy + (target_y - sy) * t
            elif curve == "ease_in_out":
                ease = t * t * (3 - 2 * t)  # smoothstep
                x = sx + (target_x - sx) * ease
                y = sy + (target_y - sy) * ease
            elif curve == "bezier":
                inv = 1 - t
                x = inv*inv*sx + 2*inv*t*ctrl_x + t*t*target_x
                y = inv*inv*sy + 2*inv*t*ctrl_y + t*t*target_y
            elif curve == "human_like":
                ease = t * t * (3 - 2 * t)
                # 끝부분 미세 오버슈트
                if t > 0.85:
                    ease += random.uniform(-0.015, 0.02)
                x = sx + (target_x - sx) * ease
                y = sy + (target_y - sy) * ease
                # 인간형 미세 떨림
                x += random.gauss(0, jitter * 0.3)
                y += random.gauss(0, jitter * 0.3)
            else:
                x = sx + (target_x - sx) * t
                y = sy + (target_y - sy) * t

            # 떨림 추가
            if jitter > 0 and curve != "human_like":
                x += random.uniform(-jitter, jitter)
                y += random.uniform(-jitter, jitter)

            await self.page.mouse.move(x, y)
            self.move_log.append({"x": x, "y": y, "t": time.time()})
            self.current_x, self.current_y = x, y

            if speed_ms > 0:
                # 인간형: 속도 변화 (시작/끝은 느리게)
                if curve == "human_like":
                    factor = 1.0 + 0.5 * math.sin(t * math.pi)
                    await asyncio.sleep(speed_ms * factor / 1000.0)
                else:
                    await asyncio.sleep(speed_ms / 1000.0)

    async def click_at(self, target_x: float, target_y: float):
        """마우스 이동 → 호버 → 클릭 (화면에서 보임)"""
        offset = self.cfg["click_offset_px"]
        hover_min, hover_max = self.cfg["hover_before_click_ms"]

        click_x = target_x + random.uniform(-offset, offset)
        click_y = target_y + random.uniform(-offset, offset)

        await self.move_to(click_x, click_y)

        if hover_max > 0:
            hover = random.uniform(hover_min, hover_max)
            await asyncio.sleep(hover / 1000.0)

        await self.page.mouse.click(click_x, click_y)


class KeyboardController:
    """레벨별 키보드 입력 - 화면에서 글자가 하나씩 입력되는 것이 보임"""

    def __init__(self, page: Page, level_config: dict):
        self.page = page
        self.cfg = level_config
        self.keystroke_log: list[dict] = []

    async def type_text(self, selector: str, text: str):
        """레벨에 맞는 텍스트 입력"""
        if self.cfg["typing_use_paste"]:
            await self.page.fill(selector, text)
            self.keystroke_log.append({"type": "paste", "len": len(text), "t": time.time()})
            return

        await self.page.click(selector)
        await asyncio.sleep(0.05)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.05)

        d_min, d_max = self.cfg["typing_delay_ms"]

        for char in text:
            delay = random.uniform(d_min, d_max)

            # Level 10: 오타 시뮬레이션
            if self.cfg.get("misclick_chance", 0) > 0 and random.random() < 0.02:
                wrong = chr(ord(char) + random.choice([-1, 1]))
                await self.page.keyboard.type(wrong, delay=delay)
                await asyncio.sleep(delay / 1000.0)
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(delay * 2 / 1000.0)

            await self.page.keyboard.type(char, delay=delay)
            self.keystroke_log.append({"char": char, "delay": delay, "t": time.time()})


class TruveMacro:
    """
    Truve 예매 매크로 - headed 모드 (화면에서 실행됨)

    실행하면 실제 브라우저 창이 열리고,
    마우스가 움직이고, 클릭하고, 키보드 입력하는 것이 모두 보임.
    """

    def __init__(self, base_url: str, level: int, logger: DataLogger,
                 booking_options: dict = None):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("pip install playwright && playwright install chromium")

        self.base_url = base_url.rstrip("/")
        self.level = level
        self.cfg = BOT_LEVELS[level]
        self.logger = logger
        self.run_id = str(uuid.uuid4())[:8]
        # 예매 부가 설정 (좌석 등급/구역/매수, 결제 방식, 회차 날짜/시간)
        self.booking = booking_options or {
            "seat_grade": "any",
            "seat_section": "any",
            "seat_count": 2,
            "pay_method": "CARD",
            "schedule_date": None,
            "schedule_time": None,
        }

        self._pw = None
        self.browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.mouse: MouseController = None
        self.keyboard: KeyboardController = None

        self._be = BEDataRecord(run_id=self.run_id, bot_profile=f"level_{level}")
        self._fe = FEDataRecord(run_id=self.run_id, bot_profile=f"level_{level}")
        self._last_action = 0.0

    # ================================================================
    # Setup / Teardown
    # ================================================================

    async def setup(self):
        """브라우저 시작 - 화면에 브라우저 창이 열림"""
        print(f"\n  [Setup] Level {self.level}: {self.cfg['name']}")

        self._pw = await async_playwright().start()

        args = ["--start-maximized", "--disable-infobars"]
        if self.cfg["hide_webdriver"]:
            args.append("--disable-blink-features=AutomationControlled")

        vw, vh = self.cfg["viewport"]
        self.browser = await self._pw.chromium.launch(
            headless=False,  # 항상 화면에 보임
            slow_mo=self.cfg["slow_mo"],
            args=args,
        )

        ctx_opts = {
            "viewport": {"width": vw, "height": vh},
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }
        if self.cfg["user_agent"]:
            ctx_opts["user_agent"] = self.cfg["user_agent"]

        self.context = await self.browser.new_context(**ctx_opts)
        self.page = await self.context.new_page()

        self.mouse = MouseController(self.page, self.cfg)
        self.keyboard = KeyboardController(self.page, self.cfg)

        # webdriver 숨기기 (Level 4+)
        if self.cfg["hide_webdriver"]:
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1,2,3,4,5]
                });
                window.chrome = { runtime: {} };
            """)

        # 텔레메트리 수집기 주입
        await self.page.add_init_script("""
            window.__tel = {
                mouse:[], clicks:[], keys:[], scrolls:[],
                vis:0, focus:0
            };
            document.addEventListener('mousemove', e =>
                window.__tel.mouse.push({x:e.clientX,y:e.clientY,t:Date.now()}));
            document.addEventListener('click', e =>
                window.__tel.clicks.push({x:e.clientX,y:e.clientY,t:Date.now()}));
            document.addEventListener('keydown', e =>
                window.__tel.keys.push({k:e.key,t:Date.now(),d:'dn'}));
            document.addEventListener('keyup', e =>
                window.__tel.keys.push({k:e.key,t:Date.now(),d:'up'}));
            document.addEventListener('scroll', () =>
                window.__tel.scrolls.push({y:window.scrollY,t:Date.now()}));
            document.addEventListener('visibilitychange', () => window.__tel.vis++);
            window.addEventListener('focus', () => window.__tel.focus++);
            window.addEventListener('blur', () => window.__tel.focus++);
        """)

    async def teardown(self):
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    # ================================================================
    # 공통
    # ================================================================

    async def _delay(self):
        """레벨별 동작 간 딜레이"""
        d_min, d_max = self.cfg["action_delay_ms"]
        delay = random.uniform(d_min, d_max)

        # Level 10: 망설임/멍때리기
        if self.cfg.get("random_hesitation") and random.random() < 0.15:
            delay += random.uniform(1000, 5000)
        if self.cfg.get("idle_pause_chance", 0) > 0:
            if random.random() < self.cfg["idle_pause_chance"]:
                p_min, p_max = self.cfg["idle_pause_ms"]
                extra = random.uniform(p_min, p_max)
                delay += extra
                print(f"      (Lv10 시뮬: {extra/1000:.1f}초 멍때림)")

        now = time.time() * 1000
        if self._last_action > 0:
            self._be.req_intervals_ms.append(round(now - self._last_action, 2))
        self._last_action = now

        await asyncio.sleep(delay / 1000.0)

    async def _click_selector(self, selector: str, desc: str = ""):
        """CSS 셀렉터로 요소 찾아 마우스로 클릭 (화면에서 보임)"""
        await self._delay()
        try:
            el = await self.page.wait_for_selector(selector, timeout=10000)
            box = await el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                if desc:
                    print(f"      클릭: {desc}")
                await self.mouse.click_at(cx, cy)
            else:
                await el.click()
        except Exception as e:
            print(f"      [!] 셀렉터 실패: {selector} ({e})")
            raise

    async def _scroll(self):
        """레벨별 스크롤"""
        if not self.cfg["scroll_enabled"]:
            return
        await asyncio.sleep(self.cfg["scroll_delay_ms"] / 1000.0)
        amount = random.randint(200, 500)
        await self.page.evaluate(f"window.scrollBy(0, {amount})")
        if self.level >= 8 and random.random() < 0.3:
            await asyncio.sleep(0.5)
            await self.page.evaluate(f"window.scrollBy(0, -{amount // 2})")

    # ================================================================
    # Step 1: 로그인 (/signin)
    # ================================================================

    async def step1_login(self, email: str, password: str):
        """
        로그인 페이지에서 이메일/비밀번호 입력 후 로그인
        - input name="email", placeholder="techup@gmail.com"
        - input name="password", placeholder="비밀번호 입력하기"
        - button type="submit" text="로그인"
        """
        print(f"\n  [Step 1/7] 로그인")
        self._be.api_call_sequence.append("signin")

        await self.page.goto(f"{self.base_url}/signin", wait_until="networkidle")
        await self._delay()

        # 이메일 입력 (화면에서 글자가 하나씩 타이핑됨)
        # [Rule 4] 이메일 마스킹 출력
        print(f"      이메일: {mask_email(email)}")
        await self.keyboard.type_text('input[name="email"]', email)
        await self._delay()

        # 비밀번호 입력
        print(f"      비밀번호 입력 중...")
        await self.keyboard.type_text('input[name="password"]', password)
        await self._delay()

        # 로그인 버튼 클릭
        await self._click_selector(
            'button[type="submit"]',
            "로그인 버튼"
        )

        # 로그인 완료 대기
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        print(f"      -> 로그인 완료")
        self._be.login_method = "email"

    # ================================================================
    # Step 2: 공연 목록 → 공연 선택
    # ================================================================

    async def step2_select_show(self, show_id: int):
        """
        공연 상세 페이지로 이동 + 회차(날짜/시간) 선택
        - /shows/{showId}
        - 캘린더에서 날짜 선택 → 회차 시간 선택
        """
        print(f"\n  [Step 2/7] 공연 페이지 이동 (showId={show_id})")
        self._be.api_call_sequence.append("show_detail")

        await self.page.goto(
            f"{self.base_url}/shows/{show_id}",
            wait_until="networkidle",
        )
        await self._delay()

        # 사람 시뮬: 공연 정보 둘러보기
        if self.level >= 7:
            await self._scroll()
            await asyncio.sleep(random.uniform(1, 3))
            await self._scroll()

        # ── 회차 날짜 선택 ──
        target_date = self.booking.get("schedule_date")
        if target_date:
            # 캘린더에서 특정 날짜 클릭 (YYYY-MM-DD → DD)
            day = str(int(target_date.split("-")[2]))  # "07" → "7"
            print(f"      날짜 선택: {target_date}")
            try:
                # React Day Picker 날짜 버튼 클릭
                date_btn = await self.page.query_selector(
                    f'button[name="day"]:has-text("{day}")'
                )
                if date_btn:
                    box = await date_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] 날짜 {day}일 버튼을 찾을 수 없음, 기본 선택")
            except Exception:
                print(f"      [!] 날짜 선택 실패, 기본 선택 유지")

        await self._delay()

        # ── 회차 시간 선택 ──
        target_time = self.booking.get("schedule_time")
        if target_time:
            print(f"      회차 시간 선택: {target_time}")
            try:
                # 회차 리스트에서 시간 매칭
                time_btn = await self.page.query_selector(
                    f'button:has-text("{target_time}"), '
                    f'[class*="schedule"]:has-text("{target_time}")'
                )
                if time_btn:
                    box = await time_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] {target_time} 회차를 찾을 수 없음, 첫 번째 회차 선택")
            except Exception:
                print(f"      [!] 회차 선택 실패, 기본 선택 유지")

        print(f"      -> 공연 페이지 로딩 완료")

    # ================================================================
    # Step 3: 예매하기 버튼 → 캡차
    # ================================================================

    async def step3_captcha(self):
        """
        예매하기 버튼 클릭 → 캡차 모달
        - 예매하기 버튼: bg-red-500, text="예매하기"
        - 캡차: 3x2 그리드, 타일 클릭 후 "시작하기"
        """
        print(f"\n  [Step 3/7] 예매하기 + 캡차")
        self._be.api_call_sequence.append("captcha")

        await self._delay()

        # "예매하기" 버튼 클릭
        await self._click_selector(
            'button:has-text("예매하기")',
            "예매하기 버튼"
        )

        await asyncio.sleep(1)  # 모달 열림 대기

        # 캡차: 6타일 중 랜덤 1개 선택
        # 캡차 타일은 aspect-square rounded-xl 클래스
        await self._delay()

        # 타일 그리드에서 랜덤 타일 클릭
        tile_index = random.randint(0, 5)
        try:
            tiles = await self.page.query_selector_all(
                '[class*="aspect-square"][class*="rounded-xl"]'
            )
            if tiles and len(tiles) > tile_index:
                box = await tiles[tile_index].bounding_box()
                if box:
                    print(f"      캡차 타일 {tile_index + 1}/6 선택")
                    await self.mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
        except Exception:
            # 대체: 캡차 영역 직접 클릭
            print(f"      캡차 타일 직접 클릭 시도")
            pass

        await self._delay()

        # "시작하기" 버튼 클릭
        await self._click_selector(
            'button:has-text("시작하기")',
            "시작하기 버튼"
        )

        await asyncio.sleep(1)
        print(f"      -> 캡차 통과")

    # ================================================================
    # Step 4: 대기열
    # ================================================================

    async def step4_queue(self, show_id: int):
        """
        대기열 대기 (QueueStep 모달)
        - 순위 표시: text-5xl font-extrabold text-red-500
        - 자동으로 /shows/{showId}/seat 으로 리다이렉트됨
        """
        print(f"\n  [Step 4/7] 대기열 대기")
        self._be.api_call_sequence.append("queue")

        max_wait = 300  # 최대 5분
        start = time.time()
        poll_count = 0

        while time.time() - start < max_wait:
            poll_start = time.time()
            poll_count += 1

            # 현재 URL 확인 → 좌석 페이지로 이동했으면 통과
            current_url = self.page.url
            if "/seat" in current_url:
                print(f"      -> 대기열 통과! (폴링 {poll_count}회)")
                self._be.queue_poll_count = poll_count
                return True

            # 순위 읽기
            try:
                rank_text = await self.page.evaluate("""() => {
                    const el = document.querySelector('.text-5xl, .text-red-500');
                    return el ? el.textContent.trim() : '?';
                }""")
                if poll_count % 5 == 0:
                    print(f"      대기 중... (순위: {rank_text}, 폴링: {poll_count}회)")
            except Exception:
                pass

            poll_elapsed = (time.time() - poll_start) * 1000
            self._be.queue_poll_intervals_ms.append(round(poll_elapsed, 2))

            # 폴링 간격
            if self.cfg["queue_ignore_server_interval"]:
                p_min, p_max = self.cfg["queue_poll_ms"]
                wait = random.uniform(p_min, p_max)
            else:
                wait = 3000  # 서버 기본값 사용

            await asyncio.sleep(wait / 1000.0)

        self._be.queue_poll_count = poll_count
        print(f"      -> 대기열 타임아웃")
        return False

    # ================================================================
    # Step 5: 좌석 선택 (/shows/{showId}/seat)
    # ================================================================

    async def step5_select_seats(self, show_id: int):
        """
        좌석 선택 - PixiJS Canvas 기반
        - Canvas 배경: bg-[#EDEEF4]
        - 좌석 색상: VIP=purple, R=purple, S=blue, A=green
        - 선택시: 0xf11322 (빨강)
        - 패널: "선택 좌석 N / 4", "결제하기" 버튼

        PixiJS Canvas는 DOM 요소가 아니므로 Canvas 좌표로 클릭해야 함.
        좌석 정보는 API 응답에서 가져와서 Canvas 위의 좌표를 계산.
        """
        print(f"\n  [Step 5/7] 좌석 선택")
        self._be.api_call_sequence.append("seat_select")

        # 좌석 페이지가 아니면 이동
        if "/seat" not in self.page.url:
            await self.page.goto(
                f"{self.base_url}/shows/{show_id}/seat",
                wait_until="networkidle",
            )

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)  # PixiJS 렌더링 대기

        seat_view_start = time.time()

        # 좌석 선택 전 고민 시간 (레벨별)
        d_min, d_max = self.cfg["seat_select_delay_ms"]
        think_time = random.uniform(d_min, d_max)
        print(f"      좌석 고르는 중... ({think_time/1000:.1f}초)")

        # 사람 시뮬: 좌석 배치도 구경
        if self.level >= 6:
            await self._scroll()
            await asyncio.sleep(think_time / 2000.0)
        else:
            await asyncio.sleep(think_time / 1000.0)

        # PixiJS Canvas 찾기
        canvas = await self.page.query_selector('canvas')
        if not canvas:
            print(f"      [!] Canvas 요소를 찾을 수 없음")
            # 대체: DOM 기반 좌석 시도
            return await self._select_seats_dom()

        canvas_box = await canvas.bounding_box()
        if not canvas_box:
            print(f"      [!] Canvas 크기를 알 수 없음")
            return False

        # Canvas 내에서 좌석 클릭
        # PixiJS 좌석은 그리드 형태로 배치됨
        # Canvas 크기 기반으로 좌석 영역 추정
        cx, cy = canvas_box["x"], canvas_box["y"]
        cw, ch = canvas_box["width"], canvas_box["height"]

        # ── 좌석 등급/구역별 Canvas 영역 매핑 ──
        # PixiJS Canvas 좌표 기반 (섹션 레이아웃 추정)
        #   상단: 스테이지 (0~25%)
        #   중앙: 1층 좌석 (25~65%)  ← OP, 1F-A/B/C
        #   하단: 2층 좌석 (65~90%)  ← 2F-A/B/C
        #   좌→우: A구역(15~40%), B구역(40~60%), C구역(60~85%)

        SECTION_MAP = {
            "OP":   (0.30, 0.60, 0.25, 0.35),  # (left%, right%, top%, bottom%)
            "1F-A": (0.15, 0.38, 0.35, 0.60),
            "1F-B": (0.38, 0.62, 0.35, 0.60),
            "1F-C": (0.62, 0.85, 0.35, 0.60),
            "2F-A": (0.15, 0.38, 0.65, 0.85),
            "2F-B": (0.38, 0.62, 0.65, 0.85),
            "2F-C": (0.62, 0.85, 0.65, 0.85),
        }

        # 등급별 Canvas 영역 (등급 = 가격대 → 위치 추정)
        GRADE_MAP = {
            "vip": (0.30, 0.70, 0.25, 0.40),  # VIP: 1층 앞쪽 중앙
            "r":   (0.20, 0.80, 0.35, 0.50),  # R석: 1층 중앙
            "s":   (0.15, 0.85, 0.50, 0.65),  # S석: 1층 뒤쪽
            "a":   (0.15, 0.85, 0.65, 0.85),  # A석: 2층
        }

        target_section = self.booking.get("seat_section", "any").upper()
        target_grade = self.booking.get("seat_grade", "any").lower()
        max_seats = self.booking.get("seat_count", 2)
        strategy = self.cfg["seat_strategy"]

        # 클릭 영역 결정: 구역 > 등급 > 전체
        if target_section != "ANY" and target_section in SECTION_MAP:
            l, r, t, b = SECTION_MAP[target_section]
            print(f"      구역 지정: {target_section}")
        elif target_grade != "any" and target_grade in GRADE_MAP:
            l, r, t, b = GRADE_MAP[target_grade]
            print(f"      등급 지정: {target_grade.upper()}")
        else:
            l, r, t, b = 0.15, 0.85, 0.25, 0.85
            print(f"      구역/등급: 전체 (any)")

        seat_area_left = cx + cw * l
        seat_area_right = cx + cw * r
        seat_area_top = cy + ch * t
        seat_area_bottom = cy + ch * b

        selected_count = 0

        print(f"      전략: {strategy}, 매수: {max_seats}석")

        if strategy in ("first_available", "best_available"):
            for i in range(max_seats):
                row = i // 4
                col = i % 4
                sx = seat_area_left + (seat_area_right - seat_area_left) * (0.3 + col * 0.1)
                sy = seat_area_top + (seat_area_bottom - seat_area_top) * (0.3 + row * 0.15)

                await self.mouse.click_at(sx, sy)
                selected_count += 1
                self._be.seat_hold_attempts += 1
                print(f"      좌석 {selected_count}/{max_seats} 클릭 (x={sx:.0f}, y={sy:.0f})")

                await self._delay()

        elif strategy in ("random_good", "browse_then_pick"):
            if strategy == "browse_then_pick" and self.level >= 8:
                browse_count = random.randint(4, 8)
                for _ in range(browse_count):
                    bx = random.uniform(seat_area_left, seat_area_right)
                    by = random.uniform(seat_area_top, seat_area_bottom)
                    await self.mouse.move_to(bx, by)
                    await asyncio.sleep(random.uniform(0.3, 1.0))

            for i in range(max_seats):
                sx = random.uniform(seat_area_left, seat_area_right)
                sy = random.uniform(seat_area_top, seat_area_bottom)

                await self.mouse.click_at(sx, sy)
                selected_count += 1
                self._be.seat_hold_attempts += 1
                print(f"      좌석 {selected_count}/{max_seats} 클릭 (x={sx:.0f}, y={sy:.0f})")

                await self._delay()

        self._be.seat_view_to_hold_ms = (time.time() - seat_view_start) * 1000
        self._be.selected_seat_ids = list(range(selected_count))

        # Level 10: 잘못 클릭 후 취소/재선택
        if self.cfg.get("misclick_chance", 0) > 0 and random.random() < self.cfg["misclick_chance"]:
            print(f"      (Lv10: 잘못 클릭, 선택 취소 클릭)")
            try:
                await self._click_selector('button:has-text("선택 취소")', "선택 취소")
                self._be.seat_change_count += 1
                # 다시 선택
                sx = random.uniform(seat_area_left, seat_area_right)
                sy = random.uniform(seat_area_top, seat_area_bottom)
                await self.mouse.click_at(sx, sy)
            except Exception:
                pass

        print(f"      -> 좌석 {selected_count}석 선택 완료")
        return selected_count > 0

    async def _select_seats_dom(self):
        """Canvas가 없을 때 DOM 기반 좌석 선택 (폴백)"""
        selectors = [
            '[data-status="AVAILABLE"]',
            '.seat.available',
            'button.seat:not([disabled])',
            '[class*="seat"][class*="available"]',
        ]
        for sel in selectors:
            seats = await self.page.query_selector_all(sel)
            if seats:
                max_seats = min(4, len(seats))
                for i in range(max_seats):
                    box = await seats[i].bounding_box()
                    if box:
                        await self.mouse.click_at(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        await self._delay()
                return True
        return False

    # ================================================================
    # Step 6: 결제하기 클릭 → 결제 페이지
    # ================================================================

    async def step6_to_payment(self):
        """
        결제하기 버튼 클릭 → /payments 페이지 이동
        - 버튼 텍스트: "N원 결제하기"
        """
        print(f"\n  [Step 6/7] 결제 페이지 이동")
        self._be.api_call_sequence.append("to_payment")

        await self._delay()

        try:
            await self._click_selector(
                'button:has-text("결제하기")',
                "결제하기 버튼"
            )
        except Exception:
            # 직접 이동
            await self.page.goto(f"{self.base_url}/payments", wait_until="networkidle")

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        print(f"      -> 결제 페이지 로딩 완료")

    # ================================================================
    # Step 7: 예약자 정보 입력 + 결제
    # ================================================================

    async def step7_payment(self, applicant: dict):
        """
        결제 페이지 (/payments) 전체 폼 처리

        폼 구조:
          [예약자 정보]
            - name (이름): placeholder "홍길동"
            - birth (생년월일): placeholder "19990129" (8자리)
            - email (이메일): placeholder "XXXX@naver.com"
            - phone (전화번호): placeholder "01012345678" (11자리, - 제외)

          [티켓 수령 방법]
            - "현장수령" (value="NONE") — 현재 유일한 옵션

          [결제수단]
            - "간편 결제 · 카드 결제" (value="CARD")
            - "무통장 입금" (value="VIRTUAL_ACCOUNT")
            ※ 무통장 선택 시 → Toss SDK 내부에서 은행선택/입금자명 처리
            ※ 소득공제 = Toss SDK 내부 하드코딩 ("소득공제" 자동 적용)

          [약관 동의] — 커스텀 체크마크 (✓)
            - "이용약관 전체 동의" → 전체 토글
            - "(필수) 취소 규정 안내" — agrees[0], 필수
            - "(필수) 티켓 이용정책 동의" — agrees[1], 필수
            - "개인정보 제 3자 제공 안내" — agrees[2], 선택

          [결제 버튼]
            - "총 N원 결제하기" (bg-[#F93E4B])
            - 제한시간: 7분 카운트다운
        """
        print(f"\n  [Step 7/7] 예약자 정보 입력 + 결제")
        self._be.api_call_sequence.append("payment")

        # ── 1. 예약자 정보 입력 ──
        print(f"      [예약자 정보]")

        # 이름
        print(f"      이름: {applicant['name']}")
        await self.keyboard.type_text('input[name="name"]', applicant["name"])
        await self._delay()

        # 생년월일 (8자리)
        print(f"      생년월일: {applicant['birth']}")
        await self.keyboard.type_text('input[name="birth"]', applicant["birth"])
        await self._delay()

        # 이메일
        # [Rule 4] 이메일 마스킹 출력
        print(f"      이메일: {mask_email(applicant['email'])}")
        await self.keyboard.type_text('input[name="email"]', applicant["email"])
        await self._delay()

        # 전화번호 (11자리, - 제외)
        print(f"      전화번호: {applicant['phone']}")
        await self.keyboard.type_text('input[name="phone"]', applicant["phone"])
        await self._delay()

        # 사람 시뮬: 입력 후 스크롤
        if self.level >= 7:
            await self._scroll()

        # ── 2. 티켓 수령 방법 ──
        print(f"      [수령방법] 현장수령")
        try:
            await self._click_selector('text=현장수령', "현장수령 선택")
        except Exception:
            pass
        await self._delay()

        # ── 3. 결제수단 선택 ──
        pay_method = self.booking.get("pay_method", "CARD")
        if pay_method == "CARD":
            pay_label = "간편 결제"
            pay_desc = "카드/간편결제"
        else:
            pay_label = "무통장 입금"
            pay_desc = "무통장 입금 (은행선택/소득공제는 Toss에서 처리)"

        print(f"      [결제수단] {pay_desc}")
        try:
            await self._click_selector(f'text={pay_label}', f"{pay_label} 선택")
        except Exception:
            pass
        await self._delay()

        # 사람 시뮬: 결제수단 선택 후 스크롤
        if self.level >= 6:
            await self._scroll()

        # ── 4. 약관 동의 (3개 개별 체크) ──
        print(f"      [약관 동의]")

        # 방법 1: "전체 동의" 클릭으로 한번에 처리 (봇 레벨 1~5)
        if self.level <= 5:
            try:
                await self._click_selector('text=전체 동의', "전체 동의 (일괄)")
                print(f"      -> 전체 동의 체크 완료")
            except Exception:
                # 실패 시 개별 체크로 폴백
                await self._check_agreements_individually()
        else:
            # 방법 2: 사람처럼 개별 체크 (레벨 6~10)
            await self._check_agreements_individually()

        await self._delay()

        # ── 5. 결제 전 최종 확인 ──

        # Level 10: 결제 전 망설임
        if self.cfg.get("random_hesitation") and random.random() < 0.2:
            hesitate = random.uniform(1.5, 4.0)
            print(f"      (Lv10: 결제 전 {hesitate:.1f}초 망설임)")
            await asyncio.sleep(hesitate)

        # Level 8+: 금액 확인하듯 스크롤
        if self.level >= 8:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(0.5, 1.5))

        # ── 6. 최종 결제 버튼 클릭 ──
        print(f"      [결제] 최종 결제 버튼 클릭")
        try:
            # "총 N원 결제하기" 버튼 (bg-[#F93E4B])
            await self._click_selector(
                'button:has-text("결제하기")',
                "최종 결제 버튼"
            )
        except Exception as e:
            print(f"      [!] 결제 버튼 클릭 실패: {type(e).__name__}")

        # Toss Payments 모달 로딩 대기
        # - CARD: Toss 카드/간편결제 통합 창
        # - VIRTUAL_ACCOUNT: Toss 가상계좌 발급 창
        #   → 은행 선택, 입금자명 입력은 Toss SDK 내부에서 처리
        #   → 소득공제 = "소득공제" 자동 적용 (하드코딩)
        #   → 유효시간: 24시간
        await asyncio.sleep(3)

        if pay_method == "VIRTUAL_ACCOUNT":
            print(f"      -> Toss 무통장 입금 창 (은행선택/입금자명/소득공제 = Toss 내부)")
        else:
            print(f"      -> Toss 카드/간편결제 창 열림")

        print(f"      -> 결제 요청 완료")

    async def _check_agreements_individually(self):
        """약관 3개 개별 체크 (사람처럼 하나씩)"""
        agreement_labels = [
            ("취소 규정", "(필수) 취소 규정"),
            ("티켓 이용정책", "(필수) 티켓 이용정책"),
            ("개인정보", "개인정보 제 3자 제공"),
        ]

        for label_short, label_text in agreement_labels:
            try:
                await self._click_selector(
                    f'text={label_text}',
                    f"{label_short} 동의"
                )
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.2, 0.8))

        print(f"      -> 약관 개별 동의 완료 (3/3)")

    # ================================================================
    # 데이터 수집
    # ================================================================

    async def _collect_fingerprint(self):
        """브라우저 핑거프린트 수집"""
        try:
            fp = await self.page.evaluate("""() => ({
                wd: navigator.webdriver,
                pl: navigator.plugins.length,
                lang: navigator.languages?.join(',') || '',
                pf: navigator.platform,
                sw: screen.width, sh: screen.height,
                vw: window.innerWidth, vh: window.innerHeight,
                cd: screen.colorDepth,
                tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
            })""")
            self._fe.webdriver_detected = fp.get("wd", True)
            self._fe.plugins_count = fp.get("pl", 0)
            self._fe.languages = fp.get("lang", "")
            self._fe.platform = fp.get("pf", "")
            self._fe.screen_resolution = f"{fp.get('sw')}x{fp.get('sh')}"
            self._fe.viewport_size = f"{fp.get('vw')}x{fp.get('vh')}"
            self._fe.color_depth = fp.get("cd", 0)
            self._fe.timezone = fp.get("tz", "")
        except Exception:
            pass

    async def _collect_telemetry(self):
        """텔레메트리 수집"""
        try:
            tel = await self.page.evaluate("() => window.__tel || {}")

            mouse = tel.get("mouse", [])
            self._fe.mouse_move_count = len(mouse)
            if len(mouse) > 1:
                speeds = []
                for i in range(1, len(mouse)):
                    dx = mouse[i]["x"] - mouse[i-1]["x"]
                    dy = mouse[i]["y"] - mouse[i-1]["y"]
                    dt = max(1, mouse[i]["t"] - mouse[i-1]["t"])
                    speeds.append(math.sqrt(dx*dx + dy*dy) / dt)
                if speeds:
                    self._fe.mouse_move_speed_avg = sum(speeds) / len(speeds)
                    m = self._fe.mouse_move_speed_avg
                    self._fe.mouse_move_speed_var = sum((s-m)**2 for s in speeds) / len(speeds)

                if len(mouse) >= 2:
                    s, e = mouse[0], mouse[-1]
                    straight = math.sqrt((e["x"]-s["x"])**2 + (e["y"]-s["y"])**2)
                    total = sum(
                        math.sqrt((mouse[i]["x"]-mouse[i-1]["x"])**2 +
                                  (mouse[i]["y"]-mouse[i-1]["y"])**2)
                        for i in range(1, len(mouse))
                    )
                    self._fe.mouse_path_linearity = straight / total if total > 0 else 0

            clicks = tel.get("clicks", [])
            self._fe.click_count = len(clicks)
            if len(clicks) > 1:
                self._fe.click_intervals_ms = [
                    clicks[i]["t"] - clicks[i-1]["t"] for i in range(1, len(clicks))
                ]

            keys = [k for k in tel.get("keys", []) if k.get("d") == "dn"]
            self._fe.keystroke_count = len(keys)
            if len(keys) > 1:
                self._fe.keystroke_intervals_ms = [
                    keys[i]["t"] - keys[i-1]["t"] for i in range(1, len(keys))
                ]

            scrolls = tel.get("scrolls", [])
            self._fe.scroll_count = len(scrolls)

            self._fe.page_visibility_changes = tel.get("vis", 0)
            self._fe.focus_blur_count = tel.get("focus", 0)
        except Exception:
            pass

    # ================================================================
    # 전체 플로우 실행
    # ================================================================

    async def run(self, account: dict, show_id: int,
                  schedule_id: int = None, applicant: dict = None) -> tuple:
        """
        전체 예매 플로우 실행
        화면에서 브라우저가 열리고 모든 동작이 보임
        """
        flow_start = time.time()

        if not applicant:
            applicant = {
                "name": "테스트봇",
                "birth": "20000101",
                "email": account["email"],
                "phone": "01012345678",
            }

        print(f"\n{'='*60}")
        print(f"  Truve 매크로 실행")
        print(f"  Level {self.level}: {self.cfg['name']}")
        print(f"  {self.cfg['description']}")
        # [Rule 4] 크리덴셜 마스킹
        print(f"  계정: {mask_email(account['email'])}")
        print(f"  대상: {self.base_url}/shows/{show_id}")
        bk = self.booking
        print(f"  좌석: {bk['seat_grade'].upper()} / {bk['seat_section']} / {bk['seat_count']}매")
        print(f"  결제: {bk['pay_method']}")
        if bk.get("schedule_date"):
            print(f"  날짜: {bk['schedule_date']} {bk.get('schedule_time', '(첫 회차)')}")
        print(f"{'='*60}")

        try:
            await self.setup()

            # Step 1: 로그인
            await self.step1_login(account["email"], account["password"])

            # 핑거프린트 수집
            await self._collect_fingerprint()

            # Step 2: 공연 선택
            await self.step2_select_show(show_id)

            # Step 3: 예매하기 + 캡차
            await self.step3_captcha()

            # Step 4: 대기열
            queue_ok = await self.step4_queue(show_id)

            if queue_ok:
                # Step 5: 좌석 선택
                seats_ok = await self.step5_select_seats(show_id)

                if seats_ok:
                    # Step 6: 결제 페이지 이동
                    await self.step6_to_payment()

                    # Step 7: 예약자 정보 + 결제
                    await self.step7_payment(applicant)

            # 텔레메트리 수집
            await self._collect_telemetry()

            print(f"\n  [완료] 매크로 플로우 종료")

        except Exception as e:
            # [Rule 4] traceback 미노출 - 에러 유형만 기록
            print(f"\n  [에러] {type(e).__name__}: {e}")

        finally:
            elapsed = (time.time() - flow_start) * 1000
            self._be.total_flow_duration_ms = elapsed
            self._be.session_duration_ms = elapsed
            self._fe.time_on_page_ms = elapsed
            self._be.user_agent = self.cfg.get("user_agent", "Chromium")

            # 키보드 데이터
            if self.keyboard:
                paste_count = sum(1 for k in self.keyboard.keystroke_log if k.get("type") == "paste")
                self._fe.paste_event_count = paste_count

            await self.teardown()

        return self._be, self._fe
