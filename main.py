"""
Truve 매크로 데이터 수집기 - 메인 실행

보안 기준:
  - Rule 1: 모든 CLI 입력값 서버단 검증 (레벨, URL, 횟수 등)
  - Rule 2: 크리덴셜 CLI 평문 전달 최소화, 환경변수 우선
  - Rule 4: 콘솔 로그에 이메일/비밀번호 마스킹, traceback 내부경로 비노출
  - Rule 0: 예외 시 안전한 fallback

사용법:
  # Level 1 (극단적 봇) 로 5회 실행
  python main.py --level 1 --runs 5

  # 모든 레벨로 각 2회씩 실행
  python main.py --level all --runs 2

  # 레벨 비교표만 출력
  python main.py --info

  # 크리덴셜은 .env 파일 또는 환경변수 권장
  # (CLI --email/--password 는 프로세스 목록 노출 위험)
"""

import argparse
import asyncio
import logging
import sys
import time

from config import (
    BOT_LEVELS, BASE_URL, TEST_ACCOUNTS, LEVEL_COMPARISON,
    validate_url, validate_level, validate_runs, validate_show_id,
    mask_email,
)
from data_logger import DataLogger
from browser_macro import TruveMacro, PLAYWRIGHT_AVAILABLE

# [Rule 4] 로깅 설정: 민감정보 노출 방지
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("truve-macro")


def print_banner():
    print("""
 ╔══════════════════════════════════════════════════════════╗
 ║  TRUVE 매크로 데이터 수집기                              ║
 ║  목적: BE/FE 매크로 탐지 모델 학습용 봇 데이터 생성      ║
 ║  실행: 실제 브라우저가 열리고 화면에서 동작이 보임        ║
 ╚══════════════════════════════════════════════════════════╝
    """)


def print_level_info():
    """10단계 봇 레벨 정보 출력"""
    print("\n  [봇 레벨 시스템: Level 1 (봇) -> Level 10 (사람)]")
    print("  " + "-" * 68)

    for lv, cfg in sorted(BOT_LEVELS.items()):
        bar = "#" * lv + "." * (10 - lv)
        label = cfg["name"]
        desc = cfg["description"]
        delay = cfg["action_delay_ms"]
        mouse = cfg["mouse_curve"]
        typing = "paste" if cfg["typing_use_paste"] else f"{cfg['typing_delay_ms'][0]}~{cfg['typing_delay_ms'][1]}ms"

        print(f"  Lv.{lv:2d} [{bar}] {label}")
        print(f"        {desc}")
        print(f"        딜레이: {delay[0]}~{delay[1]}ms | 마우스: {mouse} | 타이핑: {typing}")
        print()

    print("  [전처리 변수별 레벨 차이]")
    print("  " + "-" * 68)
    print(f"  {'변수':<25} {'Lv.1(봇)':<15} {'Lv.5(경계)':<15} {'Lv.10(사람)':<15} {'가중치'}")
    print("  " + "-" * 68)
    for var, info in LEVEL_COMPARISON.items():
        print(f"  {info['description']:<25} {info['lv1']:<15} {info['lv5']:<15} {info['lv10']:<15} {info['weight']}")
    print("  " + "-" * 68)


def parse_level_arg(level_str: str) -> list[int]:
    """
    [Rule 1] 레벨 인자 파싱 + 검증.
    허용 형식: '1', '3-7', 'all'
    """
    level_str = level_str.strip().lower()

    if level_str == "all":
        return list(range(1, 11))

    if "-" in level_str:
        parts = level_str.split("-", maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"잘못된 범위: {level_str}")
        start = int(parts[0])
        end = int(parts[1])
        # 범위 검증
        validate_level(start)
        validate_level(end)
        if start > end:
            raise ValueError(f"잘못된 범위: {start} > {end}")
        return list(range(start, end + 1))

    level = int(level_str)
    validate_level(level)
    return [level]


async def run_macro(base_url: str, level: int, runs: int,
                    accounts: list, show_id: int, schedule_id: int,
                    applicant: dict, data_logger: DataLogger):
    """단일 레벨로 매크로 실행"""
    cfg = BOT_LEVELS[level]

    print(f"\n{'#'*60}")
    print(f"  Level {level}: {cfg['name']}")
    print(f"  {cfg['description']}")
    print(f"  반복: {runs}회")
    print(f"{'#'*60}")

    for run_idx in range(runs):
        account = accounts[run_idx % len(accounts)]
        # [Rule 4] 이메일 마스킹 출력
        print(f"\n  --- Run {run_idx + 1}/{runs} (계정: {mask_email(account['email'])}) ---")

        try:
            macro = TruveMacro(base_url, level, data_logger)
            be_record, fe_record = await macro.run(
                account=account,
                show_id=show_id,
                schedule_id=schedule_id,
                applicant=applicant,
            )

            data_logger.add_be_record(be_record)
            data_logger.add_fe_record(fe_record)

            print(f"\n  Run {run_idx + 1} 결과:")
            print(f"    소요: {be_record.total_flow_duration_ms:.0f}ms")
            print(f"    요청간격 평균: {be_record.req_interval_mean_ms:.0f}ms")
            print(f"    마우스 이동: {fe_record.mouse_move_count}회")
            print(f"    클릭: {fe_record.click_count}회")
            print(f"    키입력: {fe_record.keystroke_count}회")
            print(f"    webdriver: {fe_record.webdriver_detected}")

        except Exception as exc:
            # [Rule 4] 내부 경로/스택 미노출, 에러 유형만 출력
            logger.error("Run %d 실패: %s", run_idx + 1, type(exc).__name__)
            print(f"  [ERROR] Run {run_idx + 1} 실패: {type(exc).__name__}")

        # 연속 실행 간 대기
        if run_idx < runs - 1:
            await asyncio.sleep(2)


async def async_main(args):
    """비동기 메인"""
    levels = parse_level_arg(args.level)
    data_logger = DataLogger(output_dir=args.output)

    # [Rule 2] 계정 설정: 환경변수 우선, CLI 보조
    if args.email and args.password:
        accounts = [{"email": args.email, "password": args.password}]
    elif TEST_ACCOUNTS:
        accounts = TEST_ACCOUNTS
    else:
        print("  [ERROR] 테스트 계정이 설정되지 않았습니다.")
        print("  방법 1: .env 파일에 TRUVE_TEST_ACCOUNTS 설정")
        print("  방법 2: --email / --password 옵션 사용")
        sys.exit(1)

    # 예약자 정보
    applicant = {
        "name": args.applicant_name,
        "birth": args.applicant_birth,
        "email": accounts[0]["email"],
        "phone": args.applicant_phone,
    }

    total_start = time.time()

    for level in levels:
        await run_macro(
            base_url=args.url,
            level=level,
            runs=args.runs,
            accounts=accounts,
            show_id=args.show_id,
            schedule_id=args.schedule_id,
            applicant=applicant,
            data_logger=data_logger,
        )

    total_elapsed = time.time() - total_start

    # 결과 저장
    files = data_logger.save_all()
    data_logger.print_summary()

    print(f"\n  총 소요 시간: {total_elapsed:.1f}초")
    print(f"\n  [출력 파일]")
    for name, path in files.items():
        print(f"    {name}: {path}")

    print(f"\n  데이터 라벨:")
    print(f"    is_bot=1 (봇), bot_profile='level_N' 으로 구분")
    print(f"    사람 데이터(is_bot=0)는 실제 사용자 로그에서 수집 필요")


def main():
    parser = argparse.ArgumentParser(
        description="Truve 매크로 데이터 수집기 (headed 브라우저)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py --level 1 --runs 5
  python main.py --level all --runs 2
  python main.py --info
        """,
    )
    parser.add_argument("--level", default="1", help="봇 레벨 (1~10, 'all', '1-5')")
    parser.add_argument("--runs", type=int, default=1, help="레벨당 반복 횟수 (1~100)")
    parser.add_argument("--url", default=BASE_URL, help="대상 URL")
    parser.add_argument("--show-id", type=int, default=1, help="대상 공연 ID")
    parser.add_argument("--schedule-id", type=int, default=1, help="대상 회차 ID")
    parser.add_argument("--email", default=None, help="로그인 이메일 (.env 권장)")
    parser.add_argument("--password", default=None, help="로그인 비밀번호 (.env 권장)")
    parser.add_argument("--applicant-name", default="테스트봇", help="예약자 이름")
    parser.add_argument("--applicant-birth", default="20000101", help="예약자 생년월일")
    parser.add_argument("--applicant-phone", default="01012345678", help="예약자 전화번호")
    parser.add_argument("--output", default="./output", help="출력 디렉토리")
    parser.add_argument("--info", action="store_true", help="레벨 비교표 출력 후 종료")

    args = parser.parse_args()

    print_banner()

    if args.info:
        print_level_info()
        return

    if not PLAYWRIGHT_AVAILABLE:
        print("  [ERROR] playwright가 설치되지 않았습니다.")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    # [Rule 1] 모든 외부 입력값 검증
    try:
        validate_url(args.url)
        validate_runs(args.runs)
        validate_show_id(args.show_id)
        validate_show_id(args.schedule_id)
        parse_level_arg(args.level)  # 레벨 검증
    except ValueError as e:
        print(f"  [INPUT ERROR] {e}")
        sys.exit(1)

    print(f"  대상: {args.url}")
    print(f"  레벨: {args.level}")
    print(f"  반복: {args.runs}회/레벨")
    print(f"  공연: showId={args.show_id}")

    # [Rule 2] 비밀번호 CLI 전달 시 경고
    if args.password:
        print("  [WARN] --password CLI 전달은 프로세스 목록 노출 위험.")
        print("         .env 파일 사용을 권장합니다.")

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
