# Truve 매크로 데이터 수집기

Truve 티켓팅 플랫폼의 매크로 탐지 모델(BE/FE) 학습용 봇 행동 데이터를 생성하는 도구.

**Playwright headed 모드**로 실제 브라우저가 열리고, 마우스 이동/클릭/타이핑이 화면에 보임.

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

## 설치

```bash
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

## 실행

```bash
# Level 1 봇으로 1회 실행
python main.py --level 1 --runs 1

# Level 5 경계 단계 3회
python main.py --level 5 --runs 3

# 모든 레벨로 각 2회씩 (전체 데이터셋 생성)
python main.py --level all --runs 2

# 특정 범위 레벨만
python main.py --level 1-5 --runs 3

# 레벨 비교표 출력
python main.py --info
```

## 출력 데이터

`./output/` 디렉토리에 생성:

- `be_rawdata_YYYYMMDD_HHMMSS.csv` — BE 모델 학습용 (요청 타이밍, 재시도, 좌석 선택 패턴 등)
- `fe_rawdata_YYYYMMDD_HHMMSS.csv` — FE 모델 학습용 (마우스, 키보드, 스크롤, 브라우저 핑거프린트 등)
- `combined_rawdata_YYYYMMDD_HHMMSS.json` — 통합 데이터

## 프로젝트 구조

```
├── config.py           # 10단계 봇 프로필 + 환경변수 로더 + 입력 검증
├── browser_macro.py    # Playwright headed 매크로 (화면에서 동작)
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
