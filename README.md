# Truve 매크로 데이터 수집기

Truve 티켓팅 플랫폼의 **매크로 탐지 모델(BE/FE) 학습용** 봇 행동 데이터를 생성하는 도구.

**Playwright headed 모드**로 실제 브라우저가 열리고, 마우스 이동/클릭/타이핑이 화면에 보임.
로그인 → 공연 선택 → 캡차 → 대기열 → 좌석 선택 → 결제 정보 입력 → Toss 결제까지 전체 플로우를 자동화.

---

## 봇 레벨 시스템 (Level 1~10)

| Level | 이름 | 동작 딜레이 | 마우스 경로 | 타이핑 |
|-------|------|-----------|-----------|--------|
| 1 | 극단적 봇 | 30~80ms | 없음 | 붙여넣기 |
| 2 | 공격적 봇 | 80~200ms | 직선 3스텝 | 5~10ms |
| 3 | 일반 봇 | 200~500ms | 직선 5스텝 | 10~25ms |
| 4 | 개선된 봇 | 400~900ms | 직선 8스텝 | 20~50ms |
| 5 | 경계 단계 | 700~1500ms | 가감속 곡선 | 40~80ms |
| 6 | 반자동 | 1~2.5초 | 베지어 곡선 | 50~120ms |
| 7 | 스텔스 봇 | 1.5~3.5초 | 베지어 곡선 | 60~150ms |
| 8 | 고급 스텔스 | 2~5초 | human_like | 80~200ms |
| 9 | 거의 사람 | 3~8초 | human_like | 100~280ms |
| 10 | 사람 시뮬 | 5~15초 | human_like+떨림 | 120~350ms+오타 |

레벨 비교표 확인: `python main.py --info`

---

## 설치

```bash
git clone https://github.com/HOHK0923/truve-5team-test-macro.git
cd truve-5team-test-macro
pip install -r requirements.txt
playwright install chromium
```

## 설정

`.env.example`을 `.env`로 복사 후 편집:

```bash
cp .env.example .env
```

```env
TRUVE_BASE_URL=https://front-nu-tawny.vercel.app
TRUVE_TEST_ACCOUNTS=[{"email":"your@email.com","password":"yourpass"}]
TRUVE_SHOW_ID=1
TRUVE_SCHEDULE_ID=1
```

또는 CLI에서 직접 계정 지정:

```bash
python main.py --email your@email.com --password yourpass
```

---

## 실행 예시

### 기본 실행

```bash
# Level 1 봇으로 1회
python main.py --level 1 --runs 1

# Level 5 경계 단계 3회
python main.py --level 5 --runs 3

# 전 레벨(1~10) 각 2회씩 전체 데이터셋 생성
python main.py --level all --runs 2

# 특정 범위만 (Level 1~5)
python main.py --level 1-5 --runs 3
```

### 좌석 지정

```bash
# VIP석 1층 B구역 4매
python main.py --level 3 --seat-grade VIP --seat-section 1F-B --seat-count 4

# A석 2층 아무구역 1매
python main.py --level 5 --seat-grade A --seat-count 1

# R석 오케스트라피트 2매
python main.py --level 1 --seat-grade R --seat-section OP --seat-count 2
```

### 회차(날짜/시간) 지정

```bash
# 2026년 4월 15일 19시 공연
python main.py --level 3 --schedule-date 2026-04-15 --schedule-time 19:00

# 날짜만 지정 (회차는 랜덤)
python main.py --level 1 --schedule-date 2026-04-20

# 전부 랜덤 (기본값)
python main.py --level 5 --schedule-date any --schedule-time any

# any는 기본값이라 생략 가능
python main.py --level 5
```

### 카드 결제

```bash
# 삼성카드 (기본)
python main.py --level 3 --pay-method CARD --card-company 삼성

# 현대카드
python main.py --level 5 --pay-method CARD --card-company 현대

# KB국민카드
python main.py --level 1 --pay-method CARD --card-company KB국민
```

### 무통장 입금

```bash
# 국민은행 + 소득공제
python main.py --level 3 --pay-method VIRTUAL_ACCOUNT --bank 국민 --cash-receipt 소득공제

# 신한은행 + 미발행
python main.py --level 1 --pay-method VIRTUAL_ACCOUNT --bank 신한 --cash-receipt 미발행

# 카카오뱅크 + 지출증빙
python main.py --level 5 --pay-method VIRTUAL_ACCOUNT --bank 카카오뱅크 --cash-receipt 지출증빙
```

### 풀 옵션

```bash
python main.py \
  --level 5 \
  --runs 3 \
  --show-id 2 \
  --seat-grade VIP \
  --seat-section 1F-B \
  --seat-count 4 \
  --pay-method VIRTUAL_ACCOUNT \
  --bank 카카오뱅크 \
  --cash-receipt 소득공제 \
  --schedule-date 2026-04-15 \
  --schedule-time 19:00 \
  --applicant-name 홍길동 \
  --applicant-birth 19990101 \
  --applicant-phone 01012345678
```

---

## 전체 CLI 옵션

### 기본 옵션

| 옵션 | 설명 | 기본값 |
|------|------|-------|
| `--level` | 봇 레벨 (1~10, `all`, `1-5`) | `1` |
| `--runs` | 레벨당 반복 횟수 (1~100) | `1` |
| `--url` | 대상 프론트엔드 URL | `.env` 값 |
| `--show-id` | 대상 공연 ID | `1` |
| `--schedule-id` | 대상 회차 ID | `1` |
| `--email` | 로그인 이메일 | `.env` 값 |
| `--password` | 로그인 비밀번호 | `.env` 값 |
| `--output` | 출력 디렉토리 | `./output` |
| `--info` | 레벨 비교표 출력 후 종료 | - |

### 예약자 정보

| 옵션 | 설명 | 기본값 |
|------|------|-------|
| `--applicant-name` | 예약자 이름 | `테스트봇` |
| `--applicant-birth` | 생년월일 (YYYYMMDD) | `20000101` |
| `--applicant-phone` | 전화번호 (- 제외 11자리) | `01012345678` |

### 좌석 설정

| 옵션 | 값 | 기본값 |
|------|-----|-------|
| `--seat-grade` | `VIP`, `R`, `S`, `A`, `any` | `any` |
| `--seat-section` | `OP`, `1F-A`, `1F-B`, `1F-C`, `2F-A`, `2F-B`, `2F-C`, `any` | `any` |
| `--seat-count` | 1~4 | `2` |

### 회차 설정

| 옵션 | 형식 | 기본값 |
|------|------|-------|
| `--schedule-date` | `YYYY-MM-DD` 또는 `any` | `any` (랜덤) |
| `--schedule-time` | `HH:MM` 또는 `any` | `any` (랜덤) |

### 결제 설정

| 옵션 | 값 | 기본값 |
|------|-----|-------|
| `--pay-method` | `CARD`, `VIRTUAL_ACCOUNT` | `CARD` |
| `--card-company` | 삼성, 현대, KB국민, 신한, 롯데, 하나, 우리, BC, NH농협 | `삼성` |
| `--bank` | 국민, 신한, 우리, 하나, 농협, 기업, SC제일, 카카오뱅크, 토스뱅크, 케이뱅크 | `국민` |
| `--cash-receipt` | `소득공제`, `지출증빙`, `미발행` | `소득공제` |

---

## 자동화 플로우

매크로가 실행하는 전체 순서:

```
1. 로그인 완료 (/signin)
   └ 이메일/비밀번호 입력 → 로그인 버튼

2. 공연 상세 → 날짜/회차 선택 (/shows/{showId})
   └ 날짜 선택 (--schedule-date, any=랜덤)
   └ 회차 선택 (--schedule-time, any=랜덤)

3. 예매하기 → 캡차 통과
   └ 예매하기 버튼 → 캡차 타일 선택 → 시작하기

4. 대기열 진입 → 폴링 → 입장
   └ queue/enter → queue/status 폴링 → admissionToken 획득

5. 세션 진입 → 좌석 선점/재시도 (/shows/{showId}/seat)
   └ ticketing/enter (세션 토큰)
   └ 좌석 배치도 조회 → 등급/구역 기반 좌석 클릭 (PixiJS Canvas)
   └ ticketing/hold/seat (선점 실패 시 재시도)

6. Booking 생성 + 결제 페이지 이동 (/payments)
   └ POST /bookings → "결제하기" 버튼

7. Payment-ready + 예약자 정보 입력
   ├ 이름/생년월일/이메일/전화번호 입력
   ├ 수령방법: 현장수령
   ├ 결제수단: 카드 또는 무통장 선택
   ├ 약관 동의 (Lv1~5: 전체 / Lv6~10: 개별)
   └ "총 N원 결제하기" 클릭

8. Toss Payments SDK 결제 처리
   ├ [카드] 카드사 선택 (--card-company) → 결제
   └ [무통장] 은행 선택 (--bank) → 입금자명 입력
              → 현금영수증 (--cash-receipt: 소득공제/지출증빙/미발행)
              → 소득공제 시 휴대폰번호 자동 입력 → 결제
```

---

## 출력 데이터

`./output/` 디렉토리에 생성:

| 파일 | 용도 |
|------|------|
| `be_rawdata_*.csv` | BE 모델 학습 (요청 타이밍, 재시도, 좌석 선택 패턴 등) |
| `fe_rawdata_*.csv` | FE 모델 학습 (마우스, 키보드, 스크롤, 브라우저 핑거프린트 등) |
| `combined_rawdata_*.json` | 통합 데이터 (BE + FE + 요청 로그) |

라벨: `is_bot=1` (봇), `bot_profile=level_N` 으로 구분
사람 데이터(`is_bot=0`)는 실제 사용자 로그에서 별도 수집 필요

---

## 프로젝트 구조

```
├── config.py           # 10단계 봇 프로필 + 환경변수 로더 + 입력 검증
├── browser_macro.py    # Playwright headed 매크로 (Toss SDK 포함)
├── api_macro.py        # BE 전용 API 직접호출 매크로 (보조)
├── data_logger.py      # BE/FE rawdata 수집 → CSV/JSON
├── main.py             # CLI 엔트리포인트
├── requirements.txt    # 의존성 (버전 고정)
├── .env.example        # 환경변수 템플릿
└── .gitignore          # .env, output/ 제외
```

## 보안 사항

- 크리덴셜은 `.env` 환경변수에서만 로드 (소스코드 내 하드코딩 금지)
- 콘솔 로그에 이메일 마스킹, 비밀번호 미출력
- 출력 파일에 Authorization 등 민감 헤더 자동 제거
- URL 입력값 HTTPS 강제, 내부 네트워크 주소 차단
- 출력 파일 경로 탐색 방어
- 파일 퍼미션 owner-only (0o600)
- 의존성 버전 고정 (공급망 공격 방어)
