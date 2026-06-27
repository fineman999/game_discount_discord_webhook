# SPEC — Steam/Epic 할인 Discord 알림 봇

> 이 문서는 설계/구조 스펙이다. **쓰는 법**은 [USAGE.md](USAGE.md) 참고.
> 초기 설계 이후 구현이 발전해, 아래는 **현재 구현 기준**으로 갱신되어 있다.

## 0. 목표

내가 관심 있는 게임이 **Steam / Epic 등에서 할인하면 Discord로 알림**받는다.
- 특정 게임 watchlist 추적 (할인 시작 / 목표가 도달 시 알림) → **Discord 푸시**
- 전체 할인은 **동적 웹 페이지**(GitHub Pages + Cloudflare Worker)로 둘러보기
- 상시 서버 없이 GitHub Actions cron으로 운영, 무료
- 같은 watchlist 할인은 한 번만 알림 (중복 방지)

비목표(현재): 실시간(분 단위) 알림, 슬래시 커맨드, 다수 사용자, 계정/위시리스트 동기화.

---

## 1. 아키텍처

두 경로가 있다 — **푸시(watchlist)** 와 **풀(deals 페이지)**.

```
[A] watchlist 푸시 — GitHub Actions (cron)
    config.yaml → ITAD 가격조회 → state.json diff
      → 신규/개선 할인만 Discord webhook
      → state.json + docs/watchlist.json commit back

[B] deals 페이지 — 항상 실시간
    브라우저(docs/index.html, GitHub Pages)
      → Cloudflare Worker(ITAD 키 숨김, 엣지캐시 30분)
      → ITAD /deals → 인기순 렌더 (Steam/Epic/전체/찜 탭)
    cron 은 deals 모드에서 상점별 "요약 1개"만 Discord 로 추가 전송

mode: watchlist=[A] / deals=[B+요약] / both=[A]+[B+요약]
```

**왜 GitHub Actions인가**: 스케줄 실행 + 외부 POST(Discord)가 필요. Actions cron이 무료·무관리로 맞는다.

**왜 GitHub Pages + Worker인가**: 할인 목록을 git에 쌓지 않고 실시간으로 보여주려면 정적 호스팅(Pages)만으론 부족하고 API 키도 숨겨야 한다. Pages가 페이지를 서빙하고, 무료 Cloudflare Worker가 키를 숨긴 채 ITAD를 중계한다(엣지 캐시로 rate limit 보호).

**왜 ITAD인가**: IsThereAnyDeal API 하나로 Steam·Epic·GOG 등 다수 스토어 가격을 통합 조회. 스토어별로 따로 긁을 필요가 없다.

---

## 2. 데이터 소스 — IsThereAnyDeal (ITAD) API

- Base URL: `https://api.isthereanydeal.com`
- API 키 발급: https://isthereanydeal.com/apps/my/ 에서 앱 등록 (무료)
- 게임 식별자: **UUID** (구버전의 "plain"은 폐기됨)
- `country` 파라미터로 지역가 조회 — 한국 원화는 `KR`. 미지정 시 US로 폴백.
- 인증: 공개 엔드포인트는 API 키(쿼리 `key=` 또는 헤더 `ITAD-API-Key`). OAuth 불필요(공개 가격 조회만).

### 실제 사용 엔드포인트 (현재 구현 기준)

| 용도 | 엔드포인트 | 비고 |
|---|---|---|
| 제목 → UUID (일괄) | `POST /lookup/id/title/v1` | body `["title"]` → `{title: uuid\|null}`. **정확 매칭**(대소문자 민감) |
| 제목 검색 | `GET /games/search/v1` | `title=`, `results=`. title 실패 시 폴백 + `--search` |
| Steam AppID → 게임 | `GET /games/lookup/v1?appid=` | `{found, game:{id,title,assets}}` |
| 상점별 게임ID → UUID | `POST /lookup/id/shop/{shopId}/v1` | Steam 형식 `["app/220"]` (Epic 형식은 미문서) |
| 게임별 현재 가격/딜 | `POST /games/prices/v3` | UUID 배열, `country`, `deals=true` (watchlist용) |
| 전체 딜 목록 | `GET /deals/v2` | `sort=rank`(인기순), `shops=61,16`(콤마=둘다), 게임당 1개(최저가) |
| 상점 목록 | `GET /service/shops/v1` | 이름→ID 해석 (steam=61, epic=16 …) |
| 게임 상세 | `GET /games/info/v2?id=` | `reviews`(Steam 평가%), `stats.rank`, `appid`, `assets` |

> ⚠️ 스키마는 변할 수 있다. 구현/수정 시 https://docs.isthereanydeal.com 으로 검증할 것. 모르면 추측 금지.
> 주의: `/deals/v2` 는 통합(shops 다중) 조회 시 **게임당 1줄(최저가)** 만 준다 → 같은 게임의 양쪽 가격은 상점별 조회로 따로 받아 병합한다.

### ToS (반드시 지킬 것)

- 응답 deal URL의 **affiliate 태그를 제거하지 않는다** (URL 그대로 사용).
- 알림에 ITAD 출처/링크를 표기한다.
- 데이터 변형(가격 조작 등) 금지.

### 대안/폴백 (선택)

- ITAD가 부족하면 스토어 직접 호출: Steam `store.steampowered.com/api/appdetails` (앱별 가격), Epic GraphQL `freeGamesPromotions`(무료 게임). 단 **기본은 ITAD 단일 소스**로 가고, 직접 호출은 필요할 때만 `sources/`에 모듈 추가.

---

## 3. 설정과 시크릿

### `config.yaml` (레포에 커밋, 사용자가 편집)

```yaml
country: KR            # ITAD country 코드 (원화 = KR)
mode: both             # watchlist | deals | both
schedule_note: "매일 09:00 KST"  # 실제 cron은 워크플로에 정의

watchlist:             # 추적할 게임 (title / steam_appid 중 하나만 있어도 됨)
  - steam_appid: 1245620    # Elden Ring (가장 확실)
    target_price: 40000     # 이 가격 이하일 때만 알림 (선택)
  - title: "Hades II"       # Epic 전용 게임도 title 로 가능 (실패 시 검색 폴백)
    min_discount: 20        # 최소 할인율(%) (선택)
  - steam_appid: 3280350    # DEATH STRANDING 2

shops:                 # 감시할 스토어 (비우면 전체). 이름→ITAD ID 로 해석
  - steam
  - epic

deals:                 # mode: deals/both 의 페이지·요약용
  max_items: 1500      # 인기순 상위 N (페이지/요약 집계 범위)

page:                  # GitHub Pages 동적 페이지
  title: "오늘의 게임 할인"
  base_url: ""         # Discord 요약의 페이지 링크용. Worker URL 은 docs/index.html 의 API_BASE
```

> `mode: deals` 는 더 이상 "min_discount 이상 브로드캐스트"가 아니다 — **모든 할인을 페이지**에 보여주고 Discord 엔 상점별 요약만 보낸다.

### 시크릿 (GitHub repo Settings → Secrets, 코드에 절대 하드코딩 X)

| 이름 | 설명 |
|---|---|
| `ITAD_API_KEY` | ITAD 앱 등록 시 발급된 키 |
| `DISCORD_WEBHOOK_URL` | Discord 채널 설정 → 연동 → 웹후크에서 발급한 URL |

로컬 실행용 `.env.example`:

```
ITAD_API_KEY=your-itad-key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

---

## 4. 상태 관리 (중복 알림 방지) — 핵심

`data/state.json` 에 직전에 본 딜을 저장하고, 매 run마다 비교해서 **신규이거나 더 좋아진 딜만** 알린다.

### 키 설계

```
key = f"{game_uuid}:{shop_id}"
```

### 저장 구조 (예시)

```json
{
  "version": 1,
  "deals": {
    "0184abcd-...:steam": {
      "title": "Elden Ring",
      "price_new": 39600,
      "price_old": 66000,
      "cut": 40,
      "url": "https://...",
      "notified_at": "2026-06-27T00:00:00Z"
    }
  }
}
```

### 알림 판정 로직 (순수 함수 — 단위 테스트 대상)

해당 key에 대해 **다음 중 하나면 알림**:
1. state에 없는 새 key (새로 할인 시작)
2. `price_new` 가 저장값보다 **더 내려감** (가격 추가 인하)
3. `cut`(할인율)이 저장값보다 **증가**

watchlist 항목별 추가 조건:
- `target_price` 지정 시 → `price_new <= target_price` 일 때만 알림
- `min_discount` 지정 시 → `cut >= min_discount` 일 때만 알림

할인이 끝난(딜 사라진) key는 state에서 제거. 같은 가격이 유지되면 **재알림하지 않는다.**

---

## 5. Discord 알림 포맷

Webhook으로 `embeds` 배열을 POST한다 (`discord.py` 불필요, `requests.post`).

### 요청 형태

```json
POST {DISCORD_WEBHOOK_URL}
{
  "embeds": [
    {
      "title": "Elden Ring",
      "url": "<ITAD deal url, affiliate 태그 보존>",
      "description": "Steam에서 **40% 할인**",
      "fields": [
        { "name": "현재가", "value": "₩39,600", "inline": true },
        { "name": "정가",   "value": "₩66,000", "inline": true },
        { "name": "역대최저", "value": "₩33,000", "inline": true }
      ],
      "thumbnail": { "url": "<게임 썸네일 if available>" },
      "footer": { "text": "via IsThereAnyDeal" }
    }
  ]
}
```

위는 **watchlist 알림** 포맷(게임당 embed 1개). **deals 모드**는 상점(Steam/Epic)마다
**요약 embed 1개씩** 보낸다: 현재 N개 + 인기 TOP 5(Steam 평가%·리뷰수) + 페이지 링크.

### 주의

- 한 메시지에 **embed 최대 10개**. watchlist 신규 딜이 많으면 10개씩 나눠 전송.
- Discord webhook rate limit 고려 — 전송 사이 약간의 sleep, 429 응답 시 `retry_after` 만큼 대기 후 재시도.
- watchlist 신규 딜이 0개면 **아무것도 보내지 않는다** (조용함이 정상).

---

## 6. GitHub Actions 워크플로

`.github/workflows/notify.yml`

요구사항:
- `on.schedule.cron` 으로 주기 실행. **cron은 UTC** 기준 — 매일 09:00 KST = `0 0 * * *`.
- `on.workflow_dispatch` 도 추가 (수동 트리거/테스트용).
- 단계: checkout → setup-python(**3.14**) → `pip install -r requirements.txt && pip install -e . --no-deps` → `python -m dealbot` (env로 시크릿 주입) → 변경 시 `data/state.json` + `docs/watchlist.json` commit & push.
- 커밋을 위해 `permissions: contents: write`. 봇 신원은 공식 `github-actions[bot]`.
- 커밋 단계는 **변경이 있을 때만** (git diff --quiet 가드로 빈 커밋 방지).

골격:

```yaml
name: deal-notify
on:
  schedule:
    - cron: "0 0 * * *"   # 매일 09:00 KST
  workflow_dispatch:
permissions:
  contents: write
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.14" }
      - run: |
          pip install -r requirements.txt
          pip install -e . --no-deps
      - run: python -m dealbot
        env:
          ITAD_API_KEY: ${{ secrets.ITAD_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
      - name: Commit state
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/state.json docs/watchlist.json
          git diff --staged --quiet || git commit -m "chore: update state [skip ci]"
          git push
```

> deals 페이지(`docs/index.html`)는 정적 셸이라 매 run 커밋 대상이 아니다 — 데이터는 Worker가 실시간 제공. cron이 커밋하는 건 watchlist 관련 `state.json`/`watchlist.json` 뿐.

---

## 7. 프로젝트 구조

```
my_game_discount_bot/
├── CLAUDE.md
├── SPEC.md  README.md  USAGE.md      # 설계 / 설치 / 사용법
├── pyproject.toml                    # 패키지 + ruff (target py314)
├── requirements.txt                  # requests, pyyaml
├── config.yaml  .env.example  .gitignore
├── .github/workflows/notify.yml
├── data/state.json                   # watchlist 중복방지 상태
├── docs/                             # GitHub Pages (main /docs)
│   ├── index.html                    # 동적 페이지 (Worker fetch, 탭/검색/정렬)
│   ├── watchlist.json                # 봇이 생성 — "찜" 탭 데이터
│   └── .nojekyll
├── worker/                           # Cloudflare Worker (ITAD 키 숨김 프록시)
│   ├── src/worker.js                 # /deals (상점ID 해석, 엣지캐시, CORS)
│   ├── wrangler.toml  README.md
├── src/dealbot/
│   ├── __main__.py                   # CLI: --dry-run / --search / -v
│   ├── config.py                     # config.yaml + env (mode watchlist|deals|both)
│   ├── models.py                     # Deal dataclass
│   ├── state.py                      # load/save/diff (순수, 테스트 핵심)
│   ├── notifier.py                   # Discord (watchlist embed + deals 요약)
│   ├── run.py                        # 오케스트레이션 + 검색 헬퍼
│   └── sources/itad.py               # ITAD 클라이언트 + 응답 파싱
└── tests/                            # test_state / test_itad / test_config / test_run
```

> 비즈니스 로직(diff·파싱)과 I/O(`sources/`, `notifier.py`)를 분리. 네트워크 호출은 `sources/`·`notifier`·`worker` 안에만.

---

## 8. 개발 Phase (현황)

### Phase 1 — Watchlist 알림 ✅ 완료
- watchlist(title/steam_appid) → UUID 해석 → `/games/prices/v3` 조회 → state diff → Discord
- `target_price` / `min_discount` 조건, `--dry-run`, cron + commit back 동작

### Phase 2 — deals = 동적 페이지 ✅ 완료 (브로드캐스트 대신 재설계)
- 전체 할인을 **GitHub Pages 동적 페이지**로 (Cloudflare Worker가 ITAD 중계, 키 숨김, 엣지캐시)
- 탭: 전체(인기순, 같은 게임 Steam+Epic 병합) / Steam / Epic / 찜
- Discord 엔 상점별 요약 1개씩

### Phase 3 — 다듬기 ✅ 대부분 완료
- 썸네일/역대최저가/Steam 평가% 보강, `mode: both`
- `--search` 헬퍼 + title 검색 폴백, 상점 이름→ID 해석
- 남은 후보: 에러 알림(run 실패 시 멘션), 무료 게임(Epic weekly free) 전용 처리

---

## 9. 테스트 방침

- `state.py` 의 diff 판정은 **네트워크 없이** 단위 테스트 (신규/가격인하/할인율증가/target_price/min_discount).
- ITAD 응답 파싱(`parse_prices`/`parse_deal_item`/`match_shop_ids`)은 JSON fixture로 테스트.
- config 검증(mode 등), Deal→row 변환도 단위 테스트. 통합 확인은 `--dry-run` + `workflow_dispatch`.
- `worker.js` 는 `node --check` 로 문법 확인.

## 10. 완료 기준 ✅

- [x] watchlist 게임 `--dry-run` 콘솔 출력 정상
- [x] 실제 Webhook으로 Discord embed 도착
- [x] 두 번 연속 실행 시 **중복 알림 안 감** (state 동작)
- [x] Actions cron + commit back 동작 (`github-actions[bot]`)
- [x] deals 동적 페이지 라이브 (Pages + Worker), 전체/Steam/Epic/찜 탭