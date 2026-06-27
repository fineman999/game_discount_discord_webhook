# Steam/Epic 할인 Discord 알림 봇

관심 게임이 Steam/Epic 등에서 할인하면 **Discord로 알림**받고, 전체 할인은 **웹 페이지**에서 둘러보는 봇.
상시 서버 없이 **GitHub Actions(cron)** 로 운영하고, 같은 watchlist 할인은 한 번만 알린다.

데이터 소스는 [IsThereAnyDeal(ITAD) API](https://docs.isthereanydeal.com) 단일 소스.

> 👉 **쓰는 법(게임 추가·모드·페이지·명령어·FAQ)은 [USAGE.md](USAGE.md) 참고.** 이 문서는 설치·배포 위주.

## 동작 방식

두 경로 — **푸시(watchlist)** 와 **풀(deals 페이지)**.

```
[A] watchlist 푸시 — GitHub Actions (cron)
    config.yaml → ITAD 가격조회 → state.json diff
      → 신규·개선 할인만 Discord webhook
      → state.json + docs/watchlist.json commit back

[B] deals 페이지 — 항상 실시간
    브라우저(docs/index.html, GitHub Pages)
      → Cloudflare Worker(ITAD 키 숨김, 엣지캐시 30분) → ITAD
      → 인기순 렌더 (전체/Steam/Epic/찜 탭)
    cron 은 deals 에서 상점별 "요약 1개"만 Discord 로 추가 전송
```

## 세 가지 모드 (`config.yaml` 의 `mode`)

- **`watchlist`** — 찜한 게임만 추적해 **Discord 로 직접 알림**. 조용하고 정확. `target_price`(목표가) / `min_discount`(최소 할인율) 조건 지원.
- **`deals`** — 할인 중인 게임 **전부**를 **동적 페이지**(GitHub Pages)에서 보여준다. 페이지(`docs/index.html`)가 **Cloudflare Worker** 를 통해 ITAD 데이터를 실시간으로 받아 인기순으로 렌더(검색·정렬 가능)하므로, git 에 데이터가 쌓이지 않는다. 봇은 Discord 에 상점별 **요약 1개씩**(현재 N개 + 인기 TOP 5(Steam 평가%) + 페이지 링크)만 보낸다.
- **`both`** — 위 둘 다 실행 (watchlist 알림 + deals 요약).

> watchlist 알림은 mode 와 무관하게 **항상 Discord 로** 간다. watchlist 의 현재 할인은 페이지 **"찜" 탭**(`docs/watchlist.json`)에도 표시된다.

### deals 모드 데이터 흐름

```
브라우저(docs/index.html) ──fetch──▶ Cloudflare Worker(키 숨김) ──▶ ITAD
                                        └ 엣지 캐시 30분
```

API 키를 브라우저에 노출하지 않으려고 Worker 프록시를 둔다. 설정은 [`worker/README.md`](worker/README.md) 참고.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                      # python -m dealbot 가 패키지를 찾도록

cp .env.example .env                  # 그리고 키 채우기
python -m dealbot --search "elden"    # 게임의 title/steam_appid 찾기 (config 채울 때)
python -m dealbot --dry-run           # 콘솔 출력만 (전송/상태변경 없음)
python -m dealbot                     # 실제 Discord 전송 + state 갱신
```

### 필요한 시크릿

| 이름 | 발급처 |
|---|---|
| `ITAD_API_KEY` | https://isthereanydeal.com/apps/my/ 에서 앱 등록 (무료) |
| `DISCORD_WEBHOOK_URL` | Discord 채널 설정 → 연동 → 웹후크 |

로컬은 `.env`, GitHub Actions 는 repo **Settings → Secrets and variables → Actions** 에 등록.

## GitHub Actions 배포

1. 위 두 시크릿을 repo Secrets 에 등록.
2. `.github/workflows/notify.yml` 의 cron 을 원하는 시각으로 조정 (UTC 기준, 기본 `0 0 * * *` = 09:00 KST).
3. Actions 탭 → **deal-notify** → *Run workflow* 로 수동 실행해 동작 확인.

### deals 모드를 쓰려면 (동적 페이지 설정)

1. **Cloudflare Worker 배포** — [`worker/README.md`](worker/README.md) 의 안내대로 `wrangler deploy`. 발급된 URL 을 `docs/index.html` 상단 `API_BASE` 에 입력.
2. **GitHub Pages 켜기** — repo **Settings → Pages → Source** 를 `Deploy from a branch`, 브랜치 `main`, 폴더 `/docs`.
3. 게시 URL(`https://USER.github.io/REPO/`)을 `config.yaml` 의 `page.base_url` 에 입력 (Discord 요약의 페이지 링크용).
4. `config.yaml` 에서 `mode: deals` (watchlist 알림도 같이 받으려면 `mode: both`).

> 페이지가 데이터를 실시간으로 받으므로 git 에 할인 목록이 커밋되지 않는다. 페이지만 쓸 거면 봇 실행 없이도 페이지는 항상 최신이다.
> 단 페이지 **"찜" 탭**은 봇이 `watchlist`/`both` 모드로 실행돼 `docs/watchlist.json` 을 만들어야 채워진다.

## 개발

```bash
ruff check . && ruff format --check .
pytest -q
```

- `state.py` 의 diff 판정과 ITAD 응답 파싱은 네트워크 없이 단위 테스트한다 (`tests/`).
- 비즈니스 로직(diff/필터)과 I/O(`sources/`, `notifier.py`)를 분리한다.

## ITAD ToS

- 응답 deal URL의 affiliate 태그를 **제거하지 않는다** (그대로 사용).
- 알림 footer 에 `via IsThereAnyDeal` 출처를 표기한다.

자세한 설계는 [`SPEC.md`](SPEC.md) 참고.
