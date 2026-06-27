# CLAUDE.md

> 이 파일은 Claude Code가 매 세션 자동 로드한다. **간결하게 유지**할 것.
> 전체 요구사항·데이터 스키마·API 상세는 `SPEC.md` 참고.

## 프로젝트 한 줄 요약

ITAD로 Steam/Epic 할인을 확인해 **watchlist 신규 할인은 Discord로 알림**하고,
**전체 할인은 동적 웹 페이지(GitHub Pages + Cloudflare Worker)** 로 보여주는 봇.
상시 서버 없음 — **GitHub Actions(cron)** 가 스케줄 실행을 담당한다.

## 핵심 아키텍처

```
[A] watchlist 푸시 — Actions(cron)
    config → ITAD → state.json diff → Discord webhook → state.json/watchlist.json commit back
[B] deals 페이지 — 실시간
    브라우저(docs/index.html, Pages) → Worker(ITAD 키 숨김, 엣지캐시 30분) → ITAD
      → 인기순 렌더 (전체/Steam/Epic/찜 탭)
mode: watchlist | deals | both
```

상시 연결(Discord Bot Gateway)은 **쓰지 않는다** — push 알림은 Webhook 으로 충분.

## 기술 스택 (고정)

- **봇**: Python **3.14** (`src/dealbot/`). 의존성 최소화 — `requests`, `pyyaml` 만. 새 라이브러리 추가 전 사유 남길 것.
    - `discord.py` **금지** — Webhook은 그냥 HTTP POST다. 게이트웨이 라이브러리 불필요.
- **페이지**: `docs/index.html` 바닐라 JS (외부 의존성 0, Font Awesome CDN만).
- **Worker**: `worker/` Cloudflare Worker (바닐라 JS) — ITAD 키 숨김 프록시.
- **Lint/Format**: `ruff` (Python). **Test**: `pytest` (+ `worker.js` 는 `node --check`).
- **패키지 레이아웃**: `src/dealbot/`, 엔트리포인트 `python -m dealbot` (`pip install -e .` 필요).

## 자주 쓰는 명령

```bash
# 최초 1회: 가상환경 + 의존성
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                    # python -m dealbot 가 패키지를 찾도록

# 로컬 실행 (.env 로 시크릿 주입)
python -m dealbot                   # 실제 전송
python -m dealbot --dry-run         # 콘솔만 (전송/상태변경 없음)
python -m dealbot --search "elden"  # watchlist 용 title/steam_appid 찾기

# lint / format / test
ruff check . && ruff format --check .
pytest -q
node --check worker/src/worker.js   # Worker JS 문법
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
2. 설계는 `SPEC.md`, 사용법은 `USAGE.md` 참고. Phase 1~3 은 대체로 구현 완료(추가는 다듬기 수준).
3. ITAD API는 **v3 기준**(`prices/v3`, `deals/v2`, `lookup`/`search`/`shops`/`info`), 식별자는 **UUID**. 시그니처/응답이 불확실하면 추측 말고 https://docs.isthereanydeal.com 으로 확인.
4. `docs/index.html`(페이지)과 `worker/`(JS)를 고치면 같은 로직이 양쪽에 있으니 함께 맞춘다. Worker 변경은 `wrangler deploy` 필요.