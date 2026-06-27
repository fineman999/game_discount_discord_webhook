# CLAUDE.md

> 이 파일은 Claude Code가 매 세션 자동 로드한다. **간결하게 유지**할 것.
> 전체 요구사항·데이터 스키마·API 상세는 `SPEC.md` 참고.

## 프로젝트 한 줄 요약

Steam / Epic 게임 할인을 주기적으로 확인해 **신규 할인만** Discord로 알림하는 봇.
상시 서버 없음 — **GitHub Actions(cron)** 가 스케줄 실행을 담당한다.

## 핵심 아키텍처

```
GitHub Actions (cron)
  → ITAD API 조회 (watchlist 게임 가격 / 전체 deals)
  → data/state.json 과 비교, 신규·개선된 할인만 필터
  → Discord Webhook 으로 embed POST
  → state.json 갱신 후 commit back
```

상시 연결(Discord Bot Gateway)은 **쓰지 않는다.** 단순 push 알림이라 Webhook 한 방이면 충분.

## 기술 스택 (고정)

- **언어**: Python 3.12
- **의존성 최소화**: `requests`, `pyyaml` 만. 새 라이브러리 추가 전 반드시 사유를 남길 것.
    - `discord.py` **금지** — Webhook은 그냥 HTTP POST다. 게이트웨이 라이브러리 불필요.
- **Lint/Format**: `ruff` (lint + format 둘 다)
- **Test**: `pytest`
- **패키지 레이아웃**: `src/dealbot/`, 엔트리포인트 `python -m dealbot`

## 자주 쓰는 명령

```bash
# 최초 1회: 가상환경 생성 + 의존성 설치
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 이후 작업 시작할 때마다
source .venv/bin/activate

# 로컬 실행 (.env 로 시크릿 주입)
python -m dealbot

# dry-run: Discord로 실제 전송하지 않고 콘솔에만 출력
python -m dealbot --dry-run

# lint / format / test
ruff check . && ruff format --check .
pytest -q
```

## 코드 컨벤션

- 타입 힌트 필수. public 함수엔 짧은 docstring.
- 네트워크 호출(`requests`)은 `sources/` 와 `notifier.py` 안에만. 비즈니스 로직과 I/O 분리.
- 순수 함수(상태 diff, 필터링)는 네트워크 없이 단위 테스트 가능하게 작성.
- 예외는 삼키지 말고 로깅 후 적절히 전파. 단, **한 게임 조회 실패가 전체 run을 죽이면 안 됨** — 게임 단위로 try/except 후 계속 진행.
- 로그는 표준 `logging` 사용 (print 금지, `--dry-run` 출력 제외).

## 절대 규칙 (가드레일)

- **시크릿 하드코딩 금지.** `ITAD_API_KEY`, `DISCORD_WEBHOOK_URL` 은 환경변수로만. `.env`는 `.gitignore`. 커밋에 `.env.example`만 둔다.
- **run은 idempotent해야 한다.** 같은 할인을 두 번 알림하지 않는다 (state 비교가 핵심). Actions가 중복 실행돼도 안전해야 함.
- **ITAD ToS 준수**: 응답의 deal URL에서 **affiliate 태그를 제거하지 말 것**. 알림 어딘가에 ITAD 출처/링크를 남길 것.
- state.json 커밋은 **변경이 있을 때만** (빈 커밋 금지).

## 작업 시작 전

1. 로컬은 **venv(`.venv/`) 활성화 상태**에서 작업한다. `.venv/`는 `.gitignore`에 포함, 커밋 금지.
2. `SPEC.md` 를 읽고 현재 Phase 범위를 확인한다.
3. ITAD API는 v2 기준이며 게임 식별자는 **UUID**다. 엔드포인트 시그니처/응답 형태가 불확실하면 추측하지 말고 https://docs.isthereanydeal.com 으로 확인할 것.
4. 한 번에 한 Phase씩. Phase 1(watchlist 알림)부터 동작시키고 커밋한다.