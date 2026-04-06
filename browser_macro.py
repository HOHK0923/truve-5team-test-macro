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
                 booking_options: dict = None, level_overrides: dict = None,
                 scenario: str = "", tag: str = ""):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("pip install playwright && playwright install chromium")

        self.base_url = base_url.rstrip("/")
        self.level = level
        self.scenario = scenario
        self.tag = tag
        # 레벨 설정 복사 후 오버라이드 적용 (stealth 시나리오용)
        self.cfg = dict(BOT_LEVELS[level])
        if level_overrides:
            self.cfg.update(level_overrides)
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

        self._be = BEDataRecord(
            run_id=self.run_id, bot_profile=f"level_{level}",
            level=level, scenario=scenario, tag=tag,
        )
        self._fe = FEDataRecord(
            run_id=self.run_id, bot_profile=f"level_{level}",
            level=level, scenario=scenario, tag=tag,
        )
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

        # no_viewport=True → 브라우저 창 전체 크기 사용 (--start-maximized와 연동)
        # viewport 설정이 있으면 창 크기와 무관하게 고정되므로, 전체화면 보장을 위해 no_viewport 사용
        ctx_opts = {
            "no_viewport": True,
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

    async def _dismiss_popups(self):
        """
        화면 위에 떠있는 팝업/모달/공연안내 등을 자동으로 닫는다.
        매 스텝 전에 호출하여 클릭 차단 요소를 제거.
        여러 팝업이 겹쳐있을 수 있으므로 반복 시도.
        """
        dismissed = False

        # ── 공연안내 팝업 닫기 (shadcn Dialog) ──
        # 정확한 셀렉터: button[data-slot="dialog-close"]
        # 단, 캡차/VQA/대기열 모달은 절대 닫지 않음

        try:
            result = await self.page.evaluate("""() => {
                // data-slot="dialog-close" 버튼이 있는 모달 찾기
                const closeBtns = document.querySelectorAll('button[data-slot="dialog-close"]');
                if (closeBtns.length === 0) return 'none';

                for (const btn of closeBtns) {
                    // 이 버튼이 속한 모달의 텍스트 확인
                    const modal = btn.closest('[data-slot="dialog-content"], [role="dialog"]');
                    if (!modal) continue;

                    const text = modal.textContent || '';

                    // 캡차/VQA/대기열/결제 모달이면 → 절대 닫지 않음
                    const protect = ['시작하기', '캡차', 'captcha', '대기열',
                                     '대기 중', '접속 중', 'WAITING', '결제하기',
                                     '타일', 'tile', '좌석'];
                    if (protect.some(kw => text.includes(kw))) continue;

                    // 공연안내 등 일반 팝업 → 닫기
                    btn.click();
                    return 'closed';
                }

                // data-slot이 없는 경우 aria-label="Close" 시도
                const ariaClose = document.querySelectorAll('button[aria-label="Close"]');
                for (const btn of ariaClose) {
                    const modal = btn.closest('[role="dialog"]');
                    if (!modal) continue;
                    const text = modal.textContent || '';
                    const protect = ['시작하기', '캡차', 'captcha', '대기열',
                                     '대기 중', '접속 중', 'WAITING', '결제하기',
                                     '타일', 'tile', '좌석'];
                    if (protect.some(kw => text.includes(kw))) continue;
                    btn.click();
                    return 'closed';
                }

                return 'skip';
            }""")

            if result == "closed":
                await asyncio.sleep(0.5)
                print(f"      [팝업] 공연안내 닫기 완료")
                return True

        except Exception:
            pass

        return False

    async def _click_selector(self, selector: str, desc: str = ""):
        """
        CSS 셀렉터로 요소 찾아 클릭.
        팝업 닫기는 여기서 자동 호출하지 않음 (캡차/VQA 모달 오닫기 방지).
        필요한 스텝에서 명시적으로 _dismiss_popups() 호출할 것.
        """
        await self._delay()

        try:
            el = await self.page.wait_for_selector(selector, timeout=10000)

            # 요소가 뷰포트에 보이도록 스크롤
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)

            box = await el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                if desc:
                    print(f"      클릭: {desc}")
                await self.mouse.click_at(cx, cy)
            else:
                if desc:
                    print(f"      클릭(직접): {desc}")
                await el.click(force=True)

        except Exception:
            # force 클릭 재시도
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if desc:
                    print(f"      클릭(force): {desc}")
                await el.click(force=True)
            except Exception as e:
                print(f"      [!] 클릭 실패: {selector} ({type(e).__name__})")
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
        로그인 - 이미 로그인 상태면 스킵
        상단 네비에 "로그인" 버튼이 보이면 → 미로그인 → 로그인 수행
        "로그인" 버튼이 없으면 → 이미 로그인됨 → 스킵
        """
        print(f"\n  [Step 1/8] 로그인 확인")
        self._be.api_call_sequence.append("signin")

        # 먼저 메인 페이지로 이동해서 로그인 상태 확인
        await self.page.goto(f"{self.base_url}/", wait_until="networkidle")
        await asyncio.sleep(1)

        # 상단에 "로그인" 텍스트/버튼이 있는지 확인
        login_btn = await self.page.query_selector(
            'a:has-text("로그인"), button:has-text("로그인")'
        )

        if not login_btn:
            # 로그인 버튼이 없음 = 이미 로그인 상태
            print(f"      -> 이미 로그인 상태, 스킵")
            self._be.login_method = "already_logged_in"
            return

        # 미로그인 → 로그인 수행
        print(f"      미로그인 상태, 로그인 진행")
        await self.page.goto(f"{self.base_url}/signin", wait_until="networkidle")
        await self._delay()

        # [Rule 4] 이메일 마스킹 출력
        print(f"      이메일: {mask_email(email)}")
        await self.keyboard.type_text('input[name="email"]', email)
        await self._delay()

        print(f"      비밀번호 입력 중...")
        await self.keyboard.type_text('input[name="password"]', password)
        await self._delay()

        await self._click_selector(
            'button[type="submit"]',
            "로그인 버튼"
        )

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        print(f"      -> 로그인 완료")
        self._be.login_method = "email"

    # ================================================================
    # Step 2: 공연 상세 → 날짜/회차 선택
    # ================================================================

    async def step2_select_show(self, show_id: int):
        """
        공연 상세 페이지로 이동 + 회차(날짜/시간) 선택
        - /shows/{showId}
        - 캘린더에서 날짜 선택 → 회차 시간 선택
        - schedule_date/schedule_time = None → any (랜덤/첫 번째 가용)
        """
        print(f"\n  [Step 2/8] 공연 페이지 이동 (showId={show_id})")
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
        if target_date and target_date.lower() != "any":
            # 특정 날짜 클릭 (YYYY-MM-DD → DD)
            day = str(int(target_date.split("-")[2]))
            print(f"      날짜 선택: {target_date}")
            try:
                date_btn = await self.page.query_selector(
                    f'button[name="day"]:has-text("{day}")'
                )
                if date_btn:
                    box = await date_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] 날짜 {day}일 못찾음, 기본 유지")
            except Exception:
                print(f"      [!] 날짜 선택 실패, 기본 유지")
        else:
            # any: 공연이 있는 날짜를 찾아서 선택
            print(f"      날짜: any (공연 있는 날짜 탐색)")
            await self._select_available_date()

        await self._delay()

        # ── 회차 시간 선택 ──
        target_time = self.booking.get("schedule_time")
        if target_time and target_time.lower() != "any":
            print(f"      회차 시간 선택: {target_time}")
            try:
                time_btn = await self.page.query_selector(
                    f'button:has-text("{target_time}"), '
                    f'[class*="schedule"]:has-text("{target_time}")'
                )
                if time_btn:
                    box = await time_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] {target_time} 회차 못찾음, 가용 회차 탐색")
                    await self._select_available_schedule()
            except Exception:
                await self._select_available_schedule()
        else:
            # any: 가용 회차 탐색
            print(f"      회차: any (가용 회차 탐색)")
            await self._select_available_schedule()

        print(f"      -> 공연/회차 선택 완료")

    async def _select_available_date(self):
        """
        공연이 있는 날짜를 찾아서 클릭.
        캘린더에서 disabled 아닌 날짜를 하나씩 클릭해보고,
        "선택하신 날짜에 공연이 없습니다" 메시지가 안 뜨는 날짜를 찾는다.
        """
        max_attempts = 15  # 최대 15개 날짜 시도

        # 활성화된(disabled 아닌) 날짜 버튼 수집
        avail_days = await self.page.query_selector_all(
            'button[name="day"]:not([disabled])'
        )
        if not avail_days:
            print(f"      [!] 클릭 가능한 날짜 없음")
            return

        # 랜덤 셔플 (봇 패턴 다양화)
        indices = list(range(len(avail_days)))
        random.shuffle(indices)

        for attempt, idx in enumerate(indices[:max_attempts]):
            day_btn = avail_days[idx]
            box = await day_btn.bounding_box()
            if not box:
                continue

            day_text = await day_btn.text_content()
            await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            await asyncio.sleep(0.8)

            # "공연이 없습니다" 메시지 확인
            no_show = await self.page.query_selector('text=공연이 없습니다')
            if not no_show:
                # 공연 있는 날짜 찾음
                print(f"      -> {day_text}일 선택 (공연 있음, {attempt+1}번째 시도)")
                return

        print(f"      [!] {max_attempts}개 날짜 시도했으나 가용 날짜 없음")

    async def _select_available_schedule(self):
        """
        가용 회차(시간) 찾아서 클릭.
        회차 버튼/리스트에서 클릭 가능한 것을 찾는다.
        """
        # 회차 버튼 후보 셀렉터 (다양한 구조 대응)
        selectors = [
            '[class*="schedule"] button:not([disabled])',
            'button[class*="schedule"]:not([disabled])',
            '[class*="time"] button:not([disabled])',
            'button[class*="round"]:not([disabled])',
            # 일반적인 회차 리스트 아이템
            '[role="radio"]:not([disabled])',
            '[role="option"]:not([disabled])',
        ]

        for sel in selectors:
            btns = await self.page.query_selector_all(sel)
            if btns:
                pick = random.choice(btns)
                box = await pick.bounding_box()
                if box:
                    await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    await asyncio.sleep(0.5)
                picked_text = await pick.text_content()
                print(f"      -> '{picked_text.strip()}' 회차 선택")
                return

        print(f"      [!] 가용 회차를 찾을 수 없음")

    # ================================================================
    # Step 3: 예매하기 버튼 → 캡차
    # ================================================================

    async def step3_captcha(self):
        """
        공연안내 팝업 닫기 → 예매하기 버튼 → 캡차(VQA) 처리
        주의: 캡차 모달은 role="dialog"이므로 _dismiss_popups로 닫으면 안 됨!
              공연안내 팝업만 예매하기 전에 닫는다.
        """
        print(f"\n  [Step 3/8] 예매하기 + 캡차")
        self._be.api_call_sequence.append("captcha")

        # ── 공연안내 팝업 닫기 (예매하기 전에) ──
        # 캡차 모달이 아직 안 떴으므로 여기서만 dismiss 허용
        # 공연안내가 확실히 닫힐 때까지 최대 3회 시도
        for _try in range(3):
            closed = await self._dismiss_popups()
            if not closed:
                break
            await asyncio.sleep(0.5)
        await self._delay()

        # ── 예매하기 버튼 클릭 ──
        await self._click_selector(
            'button:has-text("예매하기")',
            "예매하기 버튼"
        )

        # ── 캡차(VQA) 모달 대기 ──
        # 여기서부터는 _dismiss_popups 절대 호출 금지!
        await asyncio.sleep(2)

        # ── 캡차 타일 선택 (3x2 = 6개 중 1개) ──
        await self._delay()
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
            else:
                print(f"      [!] 캡차 타일 {len(tiles) if tiles else 0}개 발견, 클릭 시도")
                # 폴백: 모달 내부에서 클릭 가능한 div 찾기
                await self.page.evaluate("""() => {
                    const modal = document.querySelector('[role="dialog"]');
                    if (!modal) return;
                    const tiles = modal.querySelectorAll('[class*="aspect-square"], [class*="rounded-xl"]');
                    if (tiles.length > 0) tiles[Math.floor(Math.random() * tiles.length)].click();
                }""")
        except Exception:
            print(f"      [!] 캡차 타일 클릭 실패")

        await self._delay()

        # ── "시작하기" 버튼 클릭 (캡차 모달 내부) ──
        # _click_selector 사용하되 dismiss 안 함 (이미 위에서 제거)
        try:
            await self._click_selector(
                'button:has-text("시작하기")',
                "시작하기 버튼"
            )
        except Exception:
            # 폴백: 모달 내부에서 시작하기 버튼 JS 클릭
            try:
                await self.page.evaluate("""() => {
                    const modal = document.querySelector('[role="dialog"]');
                    if (!modal) return;
                    const btns = modal.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.includes('시작하기') || btn.textContent.includes('접속')) {
                            btn.click(); return;
                        }
                    }
                }""")
                print(f"      -> 시작하기 (JS 클릭)")
            except Exception:
                print(f"      [!] 시작하기 버튼 실패")

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
        print(f"\n  [Step 4/8] 대기열 대기")
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
        좌석 선택 - DOM 기반 (PixiJS Canvas도 폴백 지원)
        스크린샷 확인: 좌석은 일반 DOM 요소 (원형 div/button)
        색상: VIP=보라, R=녹, S=파랑, A=노랑 / 선택시=빨강 / 예매됨=회색
        """
        print(f"\n  [Step 5/8] 좌석 선점")
        self._be.api_call_sequence.append("seat_select")
        await self._dismiss_popups()

        # 좌석 페이지가 아니면 이동
        if "/seat" not in self.page.url:
            await self.page.goto(
                f"{self.base_url}/shows/{show_id}/seat",
                wait_until="networkidle",
            )

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        seat_view_start = time.time()

        d_min, d_max = self.cfg["seat_select_delay_ms"]
        think_time = random.uniform(d_min, d_max)
        print(f"      좌석 고르는 중... ({think_time/1000:.1f}초)")
        await asyncio.sleep(think_time / 1000.0)

        max_seats = self.booking.get("seat_count", 2)
        target_grade = self.booking.get("seat_grade", "any").lower()

        # ── DOM에서 좌석 요소 찾기 (JS로 available 좌석 수집) ──
        available_count = await self.page.evaluate("""(targetGrade) => {
            // PixiJS Canvas 존재 여부 확인
            if (document.querySelector('canvas')) return -1;  // Canvas면 -1

            // DOM 좌석: 클릭 가능한 원형 요소 찾기
            // available 좌석 = 회색(reserved)이 아닌 색상이 있는 좌석
            const allEls = document.querySelectorAll(
                'circle, [class*="seat"], [data-seat], [data-status]'
            );
            return allEls.length;
        }""", target_grade)

        if available_count == -1:
            # Canvas 기반 → Canvas 좌표 클릭
            print(f"      PixiJS Canvas 감지 → Canvas 좌표 클릭")
            return await self._select_seats_canvas(max_seats)

        # ── DOM 기반 좌석 선택 (최대 3회 재시도) ──
        max_attempts = self.cfg.get("max_seat_attempts", 5)
        for attempt in range(max_attempts):
            selected = await self.page.evaluate(f"""(maxSeats) => {{
                // 좌석 후보 셀렉터
                const seatSelectors = [
                    'circle[fill]:not([fill="#aaaaaa"]):not([fill="#f1f1f4"]):not([fill="rgb(170,170,170)"])',
                    '[data-status="available"]',
                    '[class*="seat"]:not([class*="reserved"]):not([class*="unavailable"]):not([class*="sold"])',
                    'g[cursor="pointer"] circle',
                    'circle[cursor="pointer"]',
                    'g[style*="cursor: pointer"] circle',
                ];

                let seats = [];
                for (const sel of seatSelectors) {{
                    const found = document.querySelectorAll(sel);
                    if (found.length > 0) {{
                        seats = [...found];
                        break;
                    }}
                }}

                if (seats.length === 0) {{
                    // 폴백: circle 중 회색 아닌 것
                    const all = document.querySelectorAll('circle, rect');
                    seats = [...all].filter(el => {{
                        const fill = (el.getAttribute('fill') || '').toLowerCase();
                        return fill && fill !== 'none' && fill !== '#ffffff'
                               && !fill.includes('aaa') && !fill.includes('f1f1');
                    }});
                }}

                if (seats.length === 0) return {{found: 0, clicked: 0}};

                // 클릭
                let clicked = 0;
                const toClick = Math.min(maxSeats, seats.length);
                for (let i = 0; i < toClick; i++) {{
                    const seat = seats[i];
                    // 마우스 이벤트 순서대로 발생 (pointerdown → click)
                    seat.dispatchEvent(new PointerEvent('pointerdown', {{bubbles:true}}));
                    seat.dispatchEvent(new PointerEvent('pointerup', {{bubbles:true}}));
                    seat.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
                    clicked++;
                }}
                return {{found: seats.length, clicked: clicked}};
            }}""", max_seats)

            found = selected.get("found", 0) if isinstance(selected, dict) else 0
            clicked = selected.get("clicked", 0) if isinstance(selected, dict) else selected

            if clicked > 0:
                self._be.seat_hold_attempts = clicked
                self._be.seat_view_to_hold_ms = (time.time() - seat_view_start) * 1000
                self._be.selected_seat_ids = list(range(clicked))
                print(f"      -> 좌석 {clicked}석 선택 완료 (DOM, 가용 {found}석, 시도 {attempt+1}회)")
                # 선택 패널에 좌석 수 표시되는지 확인
                await asyncio.sleep(0.5)
                return True

            print(f"      [!] 좌석 선택 실패 (시도 {attempt+1}/{max_attempts}, 가용 {found}석)")
            await asyncio.sleep(1)

        # 최종 폴백: 좌표 클릭
        print(f"      DOM 선택 전부 실패, 좌표 클릭 시도")
        return await self._select_seats_canvas(max_seats)

    async def _select_seats_canvas(self, max_seats: int):
        """Canvas 또는 DOM 폴백: 좌석 영역에서 좌표 클릭"""
        # 페이지에서 좌석 영역 찾기
        canvas = await self.page.query_selector('canvas')
        if canvas:
            box = await canvas.bounding_box()
        else:
            # 전체 페이지 콘텐츠 영역
            box = await self.page.evaluate("""() => {
                const main = document.querySelector('main') || document.body;
                const r = main.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }""")

        if not box:
            print(f"      [!] 좌석 영역을 찾을 수 없음")
            return False

        cx, cy = box["x"], box["y"]
        cw, ch = box["width"], box["height"]

        selected = 0
        for i in range(max_seats):
            # 좌석 영역 (상단 30~60% 범위에 1층 좌석 분포)
            sx = cx + cw * random.uniform(0.2, 0.8)
            sy = cy + ch * random.uniform(0.15, 0.55)

            await self.mouse.click_at(sx, sy)
            selected += 1
            self._be.seat_hold_attempts += 1
            print(f"      좌석 {selected}/{max_seats} 클릭 (x={sx:.0f}, y={sy:.0f})")
            await self._delay()

        print(f"      -> 좌석 {selected}석 클릭 (좌표)")
        return selected > 0

    # ================================================================
    # Step 6: 결제하기 클릭 → 결제 페이지
    # ================================================================

    async def step6_to_payment(self):
        """
        결제하기 버튼 클릭 → /payments 페이지 이동
        - 버튼 텍스트: "N원 결제하기"
        """
        print(f"\n  [Step 6/8] Booking 생성 + 결제 페이지 이동")
        self._be.api_call_sequence.append("to_payment")
        await self._dismiss_popups()

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

        # 실제 결제 페이지로 이동했는지 확인
        if "/payments" not in self.page.url:
            print(f"      [!] 결제 페이지 이동 실패 (현재: {self.page.url})")
            print(f"      [!] 좌석 선점이 안 됐을 수 있음, 직접 이동 시도")
            await self.page.goto(f"{self.base_url}/payments", wait_until="networkidle")
            await asyncio.sleep(1)

        print(f"      -> 결제 페이지 로딩 완료 ({self.page.url})")

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
        print(f"\n  [Step 7/8] Payment-ready + 예약자 정보 입력")
        self._be.api_call_sequence.append("payment")
        # 결제 페이지에서는 dismiss 안 함 (결제 모달 오닫기 방지)

        # ── 1. 예약자 정보 입력 ──
        print(f"      [예약자 정보]")

        fields = [
            ("name", applicant["name"], "이름"),
            ("birth", applicant["birth"], "생년월일"),
            ("email", applicant["email"], "이메일"),
            ("phone", applicant["phone"], "전화번호"),
        ]

        for field_name, value, label in fields:
            display = mask_email(value) if field_name == "email" else value
            print(f"      {label}: {display}")
            await self._fill_form_field(f'input[name="{field_name}"]', value, label)
            await self._delay()

        # 사람 시뮬: 입력 후 스크롤
        if self.level >= 7:
            await self._scroll()

        # ── 2. 티켓 수령 방법 ──
        print(f"      [수령방법] 현장수령")
        try:
            await self._click_selector('text=현장수령', "현장수령 선택")
        except Exception:
            try:
                await self.page.evaluate("""() => {
                    const els = [...document.querySelectorAll('*')];
                    const match = els.find(el =>
                        el.textContent.includes('현장수령') && el.offsetParent !== null
                    );
                    if (match) match.click();
                }""")
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
            # 폴백: JS로 텍스트 매칭 후 강제 클릭
            try:
                await self.page.evaluate(f"""() => {{
                    const els = [...document.querySelectorAll('*')];
                    const match = els.find(el =>
                        el.textContent.includes('{pay_label}') &&
                        el.offsetParent !== null
                    );
                    if (match) match.click();
                }}""")
                print(f"      -> {pay_label} (JS 클릭)")
            except Exception:
                pass
        await self._delay()

        # 사람 시뮬: 결제수단 선택 후 스크롤
        if self.level >= 6:
            await self._scroll()

        # ── 4. 약관 동의 ──
        # 무조건 "전체 동의"만 누름 (개별 먼저 누르면 토글 꼬임)
        print(f"      [약관 동의]")
        try:
            await self._click_selector('text=전체 동의', "전체 동의")
            print(f"      -> 전체 동의 체크 완료")
        except Exception:
            # 폴백: JS로 전체 동의 클릭
            try:
                await self.page.evaluate("""() => {
                    const els = [...document.querySelectorAll('*')];
                    const btn = els.find(el =>
                        el.textContent.includes('전체 동의') &&
                        el.offsetParent !== null &&
                        el.textContent.length < 20
                    );
                    if (btn) btn.click();
                }""")
                print(f"      -> 전체 동의 (JS)")
            except Exception:
                print(f"      [!] 전체 동의 실패")

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

        # Toss Payments 모달/iframe 로딩 대기
        await asyncio.sleep(3)

        # ── 7. Toss SDK 내부 조작 ──
        await self._handle_toss_sdk(pay_method, applicant)

    # ================================================================
    # Toss Payments SDK 내부 조작
    # ================================================================

    async def _get_toss_frame(self):
        """
        Toss SDK 감지 - 최대 10초 대기하며 반복 탐색.
        iframe / 새 탭 / 리다이렉트 / 현재 페이지 내 렌더링 전부 대응.
        """
        for attempt in range(10):  # 1초 간격 10회 = 최대 10초
            # 1. iframe
            for frame in self.page.frames:
                url = frame.url
                if "tosspayments" in url or "toss.im" in url or "brandpay" in url or "payment-gateway" in url:
                    print(f"      [Toss] iframe 감지: {url[:60]}...")
                    return frame

            # 2. 새 탭/팝업
            for p in self.context.pages:
                if p != self.page:
                    url = p.url
                    if "toss" in url or "payment" in url:
                        print(f"      [Toss] 새 탭 감지: {url[:60]}...")
                        return p

            # 3. 현재 페이지가 Toss로 리다이렉트됨
            if "toss" in self.page.url or "payment-gateway" in self.page.url:
                print(f"      [Toss] 리다이렉트 감지: {self.page.url[:60]}...")
                return self.page

            # 4. 현재 페이지 내 Toss 요소
            toss_el = await self.page.query_selector(
                'iframe[src*="toss"], iframe[src*="payment"], [class*="toss"], [id*="toss"]'
            )
            if toss_el:
                tag = await toss_el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "iframe":
                    frame = await toss_el.content_frame()
                    if frame:
                        print(f"      [Toss] iframe 요소 감지")
                        return frame
                print(f"      [Toss] 현재 페이지 내 감지")
                return self.page

            if attempt < 9:
                await asyncio.sleep(1)
                if attempt % 3 == 2:
                    print(f"      [Toss] 대기 중... ({attempt+1}초)")

        return None

    async def _handle_toss_sdk(self, pay_method: str, applicant: dict):
        """
        Toss Payments SDK 모달/iframe 내부 요소 조작

        [카드 결제 (CARD)]
          - 카드사 선택 또는 간편결제(토스페이/카카오페이 등) 선택
          - 카드 정보 입력 (카드번호, 유효기간, CVC 등)

        [무통장 입금 (VIRTUAL_ACCOUNT)]
          - 입금할 은행 선택 (국민, 신한, 우리, 하나 등)
          - 입금자명 입력
          - 현금영수증: 소득공제 / 지출증빙 / 미발행 선택
          - 소득공제 선택 시: 휴대폰번호 입력
          - 결제하기 버튼 클릭
        """
        print(f"\n  [Step 8/8] Toss Payments 결제 처리")
        self._be.api_call_sequence.append("toss_sdk")

        toss = await self._get_toss_frame()
        if not toss:
            print(f"      [!] Toss SDK 10초 대기했으나 감지 실패")
            print(f"      [!] 현재 URL: {self.page.url}")
            print(f"      [!] frames: {[f.url[:50] for f in self.page.frames]}")
            print(f"      [!] pages: {[p.url[:50] for p in self.context.pages]}")
            return

        # ── Toss iframe 내부 폼 로딩 대기 + 중첩 iframe 탐색 ──
        # Toss SDK는 iframe > iframe 중첩 구조일 수 있음
        print(f"      [Toss] 폼 로딩 대기 (중첩 iframe 탐색 포함)...")

        actual_toss = toss  # 실제 폼이 있는 프레임

        for wait_i in range(15):
            # 현재 프레임에서 폼 요소 확인
            try:
                form_count = await actual_toss.evaluate("""() => {
                    const s = document.querySelectorAll('select');
                    const i = document.querySelectorAll('input');
                    return s.length + i.length;
                }""")
                if form_count >= 2:
                    print(f"      [Toss] 폼 로딩 완료 ({form_count}개 요소, {wait_i+1}초)")
                    toss = actual_toss
                    break
            except Exception:
                pass

            # 중첩 iframe 탐색 (모든 frames 순회)
            found_inner = False
            try:
                all_frames = self.page.frames
                for frame in all_frames:
                    url = frame.url
                    if not url or url == "about:blank":
                        continue
                    try:
                        fc = await frame.evaluate("""() => {
                            const s = document.querySelectorAll('select');
                            const i = document.querySelectorAll('input');
                            return s.length + i.length;
                        }""")
                        if fc >= 2:
                            print(f"      [Toss] 중첩 iframe 발견: {url[:60]}... (요소 {fc}개)")
                            actual_toss = frame
                            toss = frame
                            found_inner = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            if found_inner:
                break

            await asyncio.sleep(1)
            if wait_i % 3 == 2:
                print(f"      [Toss] 대기 중... ({wait_i+1}초, frames: {len(self.page.frames)}개)")
        else:
            print(f"      [!] Toss 폼 15초 대기, 요소 부족 (frames: {len(self.page.frames)}개)")
            # 마지막 시도: 모든 프레임 URL 출력
            for f in self.page.frames:
                print(f"        frame: {f.url[:80]}")

        await asyncio.sleep(0.5)

        if pay_method == "VIRTUAL_ACCOUNT":
            await self._toss_virtual_account(toss, applicant)
        else:
            await self._toss_card(toss)

    async def _toss_fill_input(self, toss, selectors: list, value: str, label: str):
        """
        Toss SDK iframe/팝업 안에서 input에 값 입력.
        iframe은 keyboard가 frame 레벨이라 page.keyboard 대신 toss에서 직접 처리.
        """
        for sel in selectors:
            try:
                field = await toss.query_selector(sel)
                if not field:
                    continue
                if not await field.is_visible():
                    continue

                # 방법 1: focus → 전체삭제 → 한 글자씩 입력
                await field.focus()
                await asyncio.sleep(0.1)
                await field.press("Control+A")
                await field.press("Backspace")
                await asyncio.sleep(0.1)

                # 한 글자씩 press (type보다 확실)
                for char in value:
                    await field.press(char)
                    await asyncio.sleep(0.02)

                try:
                    current = await field.input_value()
                    if current and len(current) >= len(value) - 1:
                        print(f"      -> {label} 입력 완료 (press)")
                        return True
                except Exception:
                    pass

                # 방법 2: field.type
                try:
                    await field.click(force=True)
                    await field.press("Control+A")
                    await field.press("Backspace")
                    await field.type(value, delay=30)
                    print(f"      -> {label} 입력 완료 (type)")
                    return True
                except Exception:
                    pass

                # 방법 3: fill
                try:
                    await field.fill(value)
                    print(f"      -> {label} 입력 완료 (fill)")
                    return True
                except Exception:
                    pass

                # 방법 4: JS 직접
                try:
                    await field.evaluate(f"""(el) => {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(el, '{value}');
                        el.dispatchEvent(new Event('input', {{bubbles:true}}));
                        el.dispatchEvent(new Event('change', {{bubbles:true}}));
                    }}""")
                    print(f"      -> {label} 입력 완료 (JS)")
                    return True
                except Exception:
                    pass

            except Exception:
                continue

        print(f"      [!] {label} 입력 실패")
        return False

    async def _toss_click_text(self, toss, text: str, label: str):
        """
        Toss SDK 안에서 텍스트로 요소 클릭.
        사람처럼 마우스로 이동 → 클릭 (가능하면).
        """
        # 방법 1: 텍스트로 찾아서 마우스 클릭 (사람처럼)
        try:
            btn = await toss.query_selector(f'text={text}')
            if btn and await btn.is_visible():
                box = await btn.bounding_box()
                if box:
                    # 마우스로 이동 후 클릭 (사람처럼)
                    await self.mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    await asyncio.sleep(0.3)
                    print(f"      -> {label} 완료 (마우스)")
                    return True
                else:
                    await btn.click(force=True)
                    print(f"      -> {label} 완료")
                    return True
        except Exception:
            pass

        # 방법 2: force 클릭
        try:
            btn = await toss.query_selector(f'text={text}')
            if btn:
                await btn.click(force=True)
                print(f"      -> {label} 완료 (force)")
                return True
        except Exception:
            pass

        # 방법 3: JS 텍스트 매칭
        try:
            clicked = await toss.evaluate(f"""() => {{
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                while (walker.nextNode()) {{
                    if (walker.currentNode.textContent.includes('{text}')) {{
                        const el = walker.currentNode.parentElement;
                        if (el) {{ el.click(); return true; }}
                    }}
                }}
                return false;
            }}""")
            if clicked:
                print(f"      -> {label} 완료 (JS)")
                return True
        except Exception:
            pass

        return False

    async def _toss_virtual_account(self, toss, applicant: dict):
        """
        Toss SDK - 무통장 입금 처리
        내부 구조를 모르므로 폼 요소를 순서대로 전부 처리하는 방식.
        select → input → radio/checkbox → button 순회.
        """
        bank = self.booking.get("bank", "국민")
        depositor = applicant.get("name", "테스트봇")
        phone = applicant.get("phone", "01012345678")

        print(f"      [무통장 입금]")

        # ── 0. Toss iframe 내부 폼 구조 디버그 ──
        try:
            debug = await toss.evaluate("""() => {
                const selects = [...document.querySelectorAll('select')];
                const inputs = [...document.querySelectorAll('input')];
                const buttons = [...document.querySelectorAll('button')];
                const labels = [...document.querySelectorAll('label')];
                return {
                    selects: selects.map(s => ({
                        name: s.name, id: s.id,
                        options: [...s.options].map(o => o.text).slice(0, 5),
                        visible: s.offsetParent !== null,
                    })),
                    inputs: inputs.map(i => ({
                        type: i.type, name: i.name, placeholder: i.placeholder,
                        inputmode: i.inputMode, visible: i.offsetParent !== null,
                    })),
                    buttons: buttons.map(b => ({
                        text: b.textContent.trim().substring(0, 30),
                        type: b.type, visible: b.offsetParent !== null,
                    })),
                    labels: labels.map(l => l.textContent.trim().substring(0, 30)),
                    checkboxes: inputs.filter(i => i.type === 'checkbox').map(c => ({
                        checked: c.checked, visible: c.offsetParent !== null,
                        label: (c.closest('label') || c.parentElement)?.textContent?.trim().substring(0, 30),
                    })),
                };
            }""")
            print(f"      [DEBUG] selects: {debug.get('selects', [])}")
            print(f"      [DEBUG] inputs: {debug.get('inputs', [])}")
            print(f"      [DEBUG] checkboxes: {debug.get('checkboxes', [])}")
            print(f"      [DEBUG] buttons: {[b['text'] for b in debug.get('buttons', []) if b.get('visible')]}")
            print(f"      [DEBUG] labels: {debug.get('labels', [])[:10]}")
        except Exception as e:
            print(f"      [DEBUG] 폼 구조 분석 실패: {type(e).__name__}")

        # ── 1. 모든 select 드롭다운 처리 (은행 선택 등) ──
        print(f"      은행 선택: {bank}")
        await self._delay()
        try:
            selects = await toss.query_selector_all('select')
            for sel in selects:
                if await sel.is_visible():
                    # 은행 이름으로 선택 시도
                    try:
                        await sel.select_option(label=bank)
                        print(f"      -> 은행 선택 완료")
                    except Exception:
                        # 첫 번째 옵션이 아닌 아무거나 선택
                        try:
                            options = await sel.query_selector_all('option')
                            if len(options) > 1:
                                val = await options[1].get_attribute('value')
                                await sel.select_option(value=val)
                                print(f"      -> 은행 선택 완료 (첫 번째)")
                        except Exception:
                            pass
        except Exception:
            await self._toss_click_text(toss, bank, f"은행 {bank}")
        await self._delay()

        # ── 2. 모든 text input 처리 (입금자명, 전화번호 등) ──
        try:
            inputs = await toss.query_selector_all('input[type="text"], input[type="tel"], input:not([type])')
            visible_inputs = []
            for inp in inputs:
                try:
                    if await inp.is_visible():
                        visible_inputs.append(inp)
                except Exception:
                    pass

            # 보이는 input 순서대로: 첫 번째=입금자명, 두 번째=전화번호
            for idx, inp in enumerate(visible_inputs):
                inp_type = await inp.get_attribute('type') or ''
                inp_mode = await inp.get_attribute('inputmode') or ''
                placeholder = await inp.get_attribute('placeholder') or ''

                if inp_type == 'tel' or inp_mode in ('tel', 'numeric') or '010' in placeholder or '번호' in placeholder:
                    # 전화번호 필드
                    print(f"      전화번호 입력: {phone}")
                    await self._toss_type_into(toss, inp, phone, "전화번호")
                else:
                    # 입금자명 또는 기타 텍스트
                    print(f"      입금자명 입력: {depositor}")
                    await self._toss_type_into(toss, inp, depositor, "입금자명")
        except Exception as e:
            print(f"      [!] input 처리 실패: {type(e).__name__}")
        await self._delay()

        # ── 3. 현금영수증: select 드롭다운이면 미발행 선택 ──
        print(f"      현금영수증: 미발행 시도")
        try:
            # 두 번째 select가 현금영수증 유형일 수 있음
            selects = await toss.query_selector_all('select')
            for sel in selects:
                if await sel.is_visible():
                    try:
                        # "미발행" 옵션 시도
                        await sel.select_option(label="미발행")
                        print(f"      -> 현금영수증 미발행 (select)")
                        break
                    except Exception:
                        try:
                            await sel.select_option(label="신청안함")
                            print(f"      -> 현금영수증 신청안함 (select)")
                            break
                        except Exception:
                            pass
        except Exception:
            pass

        # 라디오 버튼 형태일 수도 있음
        no_receipt_texts = ["미발행", "신청안함", "발행안함", "안 함"]
        for txt in no_receipt_texts:
            result = await self._toss_click_text(toss, txt, f"현금영수증 {txt}")
            if result:
                break
        await self._delay()

        # ── 4. 모든 체크박스 체크 (약관 동의 등) ──
        print(f"      약관/동의 체크")
        try:
            checkboxes = await toss.query_selector_all('input[type="checkbox"]')
            for cb in checkboxes:
                try:
                    if await cb.is_visible():
                        checked = await cb.is_checked()
                        if not checked:
                            # 체크박스 자체 또는 부모 label 클릭
                            label = await cb.evaluate("el => el.closest('label')")
                            if label:
                                box = await cb.bounding_box()
                                if box:
                                    await self.mouse.click_at(box["x"] + 10, box["y"] + 10)
                                else:
                                    await cb.click(force=True)
                            else:
                                await cb.click(force=True)
                            await asyncio.sleep(0.2)
                            print(f"      -> 체크박스 체크")
                except Exception:
                    pass
        except Exception:
            pass

        # label 클릭으로도 시도 (체크박스가 숨겨진 경우)
        try:
            await toss.evaluate("""() => {
                const labels = document.querySelectorAll('label');
                for (const label of labels) {
                    const cb = label.querySelector('input[type="checkbox"]');
                    if (cb && !cb.checked) {
                        label.click();
                    }
                }
            }""")
        except Exception:
            pass
        await self._delay()

        # ── 5. 결제하기 버튼 ──
        print(f"      [Toss] 최종 결제 버튼 클릭")
        btn_texts = ["결제하기", "확인", "입금하기", "동의하고 결제하기"]
        for txt in btn_texts:
            result = await self._toss_click_text(toss, txt, "Toss 결제")
            if result:
                break

        await asyncio.sleep(3)
        print(f"      -> 무통장 입금 처리 완료")

    async def _toss_type_into(self, toss, element, value: str, label: str):
        """Toss iframe 내 input 요소에 값 입력 (여러 방법)"""
        try:
            await element.focus()
            await asyncio.sleep(0.1)
            await element.press("Control+A")
            await element.press("Backspace")
            await asyncio.sleep(0.1)

            # 한 글자씩 press
            for char in value:
                await element.press(char)
                await asyncio.sleep(0.02)

            current = await element.input_value()
            if current and len(current) >= len(value) - 1:
                print(f"      -> {label} 입력 완료")
                return

            # fill 폴백
            await element.fill(value)
            print(f"      -> {label} 입력 완료 (fill)")
        except Exception:
            try:
                await element.evaluate(f"""(el) => {{
                    const s = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    s.call(el, '{value}');
                    el.dispatchEvent(new Event('input', {{bubbles:true}}));
                    el.dispatchEvent(new Event('change', {{bubbles:true}}));
                }}""")
                print(f"      -> {label} 입력 완료 (JS)")
            except Exception:
                print(f"      [!] {label} 입력 실패")

    async def _toss_card(self, toss):
        """
        Toss SDK - 카드/간편결제 처리
        카드사 선택 → 카드 정보는 테스트 환경에서 Toss가 처리
        """
        card_company = self.booking.get("card_company", "삼성")

        print(f"      [카드 결제]")
        print(f"      카드사: {card_company}")
        await self._delay()

        # 카드사 선택
        result = await self._toss_click_text(toss, card_company, f"{card_company} 선택")
        if not result:
            # 폴백: 아무 카드사나 클릭
            try:
                first = await toss.query_selector('button, [class*="card"], [role="radio"]')
                if first:
                    await first.click(force=True)
                    print(f"      -> 첫 번째 결제수단 선택")
            except Exception:
                pass

        await self._delay()

        # 결제하기 버튼
        btn_texts = ["결제하기", "다음", "확인", "동의하고 결제하기"]
        for txt in btn_texts:
            result = await self._toss_click_text(toss, txt, "Toss 결제")
            if result:
                break

        await asyncio.sleep(3)
        print(f"      -> 카드 결제 처리 완료")

    async def _fill_form_field(self, selector: str, value: str, label: str):
        """
        결제 폼 필드에 값 입력. inputMode="tel" 등 특수 필드 대응.
        1차: 클릭 → type
        2차: fill
        3차: JS nativeInputValueSetter + React 이벤트
        """
        try:
            el = await self.page.wait_for_selector(selector, timeout=5000)

            await el.click(force=True)
            await asyncio.sleep(0.1)
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(0.1)

            # 방법 1: type
            try:
                await el.type(value, delay=30)
                current = await el.input_value()
                if current == value:
                    return
            except Exception:
                pass

            # 방법 2: fill
            try:
                await el.fill(value)
                current = await el.input_value()
                if current == value:
                    return
            except Exception:
                pass

            # 방법 3: JS 강제
            await self.page.evaluate(f"""(sel) => {{
                const el = document.querySelector(sel);
                if (!el) return;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, '{value}');
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}""", selector)
            print(f"      -> {label} (JS 입력)")

        except Exception as e:
            print(f"      [!] {label} 입력 실패: {type(e).__name__}")

    async def _check_agreements_individually(self):
        """
        약관 3개 개별 체크 (사람처럼 하나씩).
        커스텀 체크마크(✓) 컴포넌트이므로 여러 방법으로 시도.
        """
        agreement_keywords = ["취소 규정", "이용정책", "개인정보"]
        checked = 0

        for keyword in agreement_keywords:
            try:
                # 방법 1: 텍스트 포함 요소의 부모/형제 클릭
                el = await self.page.query_selector(f'text={keyword}')
                if el:
                    # 체크마크는 텍스트 옆에 있으므로 텍스트 자체를 클릭
                    await el.click(force=True)
                    checked += 1
                    await asyncio.sleep(0.3)
                    continue
            except Exception:
                pass

            try:
                # 방법 2: 부모 div 전체를 클릭 (체크마크+텍스트 포함 영역)
                parent = await self.page.evaluate(f"""() => {{
                    const els = [...document.querySelectorAll('*')];
                    const match = els.find(el => el.textContent.includes('{keyword}'));
                    if (match) {{ match.click(); return true; }}
                    return false;
                }}""")
                if parent:
                    checked += 1
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        if checked == 0:
            # 최종 폴백: "전체 동의"를 JS로 강제 클릭
            try:
                await self.page.evaluate("""() => {
                    const els = [...document.querySelectorAll('*')];
                    const agreeAll = els.find(el => el.textContent.includes('전체 동의'));
                    if (agreeAll) agreeAll.click();
                }""")
                print(f"      -> 전체 동의 (JS 강제 클릭)")
                return
            except Exception:
                pass

        print(f"      -> 약관 동의 {checked}/{len(agreement_keywords)}개 체크")

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
        전체 예매 플로우 실행.
        매 run마다 새 브라우저를 열고 닫아서 깨끗한 상태 보장.
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
        print(f"  계정: {mask_email(account['email'])}")
        print(f"  대상: {self.base_url}/shows/{show_id}")
        bk = self.booking
        print(f"  좌석: {bk['seat_grade'].upper()} / {bk['seat_section']} / {bk['seat_count']}매")
        print(f"  결제: {bk['pay_method']}")
        if bk.get("schedule_date"):
            print(f"  날짜: {bk['schedule_date']} {bk.get('schedule_time', '(첫 회차)')}")
        print(f"{'='*60}")

        try:
            # 매번 새 브라우저 (이전 run의 상태/쿠키 영향 제거)
            await self.setup()

            # ── 실제 API 흐름 순서 ──
            # login → show/schedule → captcha → queue → session/seat → booking → payment → toss

            await self.step1_login(account["email"], account["password"])
            await self._collect_fingerprint()
            await self.step2_select_show(show_id)
            await self.step3_captcha()

            queue_ok = await self.step4_queue(show_id)

            if queue_ok:
                seats_ok = await self.step5_select_seats(show_id)

                if not seats_ok:
                    print(f"\n  [!] 좌석 선택 실패 — 결제 진행 불가, 플로우 중단")
                else:
                    # 좌석 패널에 실제로 선택된 좌석이 있는지 확인
                    has_selected = await self.page.evaluate("""() => {
                        const text = document.body.innerText || '';
                        // "선택 좌석 N / 4" 또는 결제 금액이 0이 아닌지 확인
                        const match = text.match(/선택\\s*좌석\\s*(\\d+)/);
                        if (match && parseInt(match[1]) > 0) return true;
                        // "원 결제하기" 버튼에 금액이 있는지
                        const payBtn = text.match(/(\\d[\\d,]+)원\\s*결제/);
                        if (payBtn && parseInt(payBtn[1].replace(/,/g,'')) > 0) return true;
                        return false;
                    }""")

                    if not has_selected:
                        print(f"\n  [!] 좌석 선점 확인 실패 (선택 좌석 0석) — 재시도")
                        # 한번 더 좌석 선택 시도
                        seats_ok = await self.step5_select_seats(show_id)

                    if seats_ok:
                        await self.step6_to_payment()
                        await self.step7_payment(applicant)

            await self._collect_telemetry()
            print(f"\n  [완료] 매크로 플로우 종료")

        except Exception as e:
            print(f"\n  [에러] {type(e).__name__}: {e}")

        finally:
            elapsed = (time.time() - flow_start) * 1000
            self._be.total_flow_duration_ms = elapsed
            self._be.session_duration_ms = elapsed
            self._fe.time_on_page_ms = elapsed
            self._be.user_agent = self.cfg.get("user_agent", "Chromium")

            if self.keyboard:
                paste_count = sum(1 for k in self.keyboard.keystroke_log if k.get("type") == "paste")
                self._fe.paste_event_count = paste_count

            await self.teardown()

        return self._be, self._fe
