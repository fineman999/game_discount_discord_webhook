# SPEC — Steam/Epic 할인 Discord 알림 봇

## 0. 목표

내가 관심 있는 게임이 **Steam / Epic 등에서 할인하면 Discord로 알림**받는다.
- 특정 게임 watchlist 추적 (할인 시작 / 목표가 도달 시 알림)
- 상시 서버 없이 GitHub Actions cron으로 운영, 무료
- 같은 할인은 한 번만 알림 (중복 방지)

비목표(현재): 실시간(분 단위) 알림, 슬래시 커맨드, 웹 UI, 다수 사용자.

---

## 1. 아키텍처

```
┌──────────────────────────────────────────────┐
│  GitHub Actions  (schedule: cron)            │
│                                              │
│   1. config.yaml 로드 (watchlist, 임계값)     │
│   2. data/state.json 로드 (직전 상태)         │
│   3. ITAD API 조회                            │
│   4. diff → 신규/개선된 할인만 추출           │
│   5. Discord Webhook 으로 embed 전송          │
│   6. state.json 갱신 → git commit back        │
└──────────────────────────────────────────────┘
```

**왜 GitHub Actions인가**: 스케줄 실행 + 외부 POST가 필요한데, GitHub Pages(정적)는 둘 다 못 한다. 상시 서버는 하루 1~2회 체크엔 과함. Actions cron이 무료·무관리로 정확히 맞는다.

**왜 ITAD인가**: IsThereAnyDeal API 하나로 Steam·Epic·GOG 등 다수 스토어 가격을 통합 조회. 스토어별로 따로 긁을 필요가 없다.

---

## 2. 데이터 소스 — IsThereAnyDeal (ITAD) API v2

- Base URL: `https://api.isthereanydeal.com`
- API 키 발급: https://isthereanydeal.com/apps/my/ 에서 앱 등록 (무료)
- 게임 식별자: **UUID** (구버전의 "plain"은 폐기됨)
- `country` 파라미터로 지역가 조회 — 한국 원화는 `KR`. 미지정 시 US로 폴백.
- 인증: 공개 엔드포인트는 API 키(쿼리 파라미터 또는 헤더). Waitlist 등 사용자 데이터는 OAuth 필요 → **이 프로젝트는 OAuth 불필요** (공개 가격 조회만 사용).

### 사용할 엔드포인트 (v2 기준 — 호출 전 docs로 최종 확인)

| 용도 | 엔드포인트 | 비고 |
|---|---|---|
| 제목/Steam AppID → ITAD UUID 변환 | `/games/lookup/v1` | watchlist 항목을 UUID로 1회 해석 후 캐시 |
| 게임별 현재 가격/딜 | `/games/prices/v2` | UUID 배열 POST, `country=KR`, `deals` 파라미터로 할인만 |
| 전체 딜 목록 (Phase 2) | `/deals/v2` | shop 필터, 게임당 1개(최저가) 반환 |

> ⚠️ 위 시그니처/응답 형태는 v2 기준이며 변경될 수 있다. 구현 시 https://docs.isthereanydeal.com 의 현재 스키마로 검증할 것. 모르면 추측 금지.

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
mode: watchlist        # watchlist | deals
schedule_note: "매일 09:00 KST"  # 실제 cron은 워크플로에 정의

watchlist:             # 추적할 게임 목록
  - title: "Elden Ring"
    target_price: 40000     # 이 가격 이하로 떨어지면 알림 (선택)
  - title: "Hades II"
    min_discount: 20        # 최소 할인율(%) (선택)
  - steam_appid: 1245620    # 제목 대신 Steam AppID로 지정 가능

shops:                 # 감시할 스토어 (비우면 전체)
  - steam
  - epic

deals:                 # mode: deals 일 때만 사용 (Phase 2)
  min_discount: 50     # 이 할인율 이상만 알림
```

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

### 주의

- 한 메시지에 **embed 최대 10개**. 신규 딜이 많으면 10개씩 나눠 여러 번 전송.
- Discord webhook rate limit(대략 분당 ~30) 고려 — 전송 사이 약간의 sleep, 429 응답 시 `retry_after` 만큼 대기 후 재시도.
- 신규 딜이 0개면 **아무것도 보내지 않는다** (조용함이 정상).

---

## 6. GitHub Actions 워크플로

`.github/workflows/notify.yml`

요구사항:
- `on.schedule.cron` 으로 주기 실행. **cron은 UTC** 기준 — 매일 09:00 KST = `0 0 * * *`.
- `on.workflow_dispatch` 도 추가 (수동 트리거/테스트용).
- 단계: checkout → setup-python(3.12) → `pip install -r requirements.txt` → `python -m dealbot` (env로 시크릿 주입) → 변경 시 state.json commit & push.
- state.json 커밋을 위해 `permissions: contents: write`.
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
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - run: python -m dealbot
        env:
          ITAD_API_KEY: ${{ secrets.ITAD_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
      - name: commit state
        run: |
          git config user.name  "deal-bot"
          git config user.email "bot@users.noreply.github.com"
          git add data/state.json
          git diff --staged --quiet || git commit -m "chore: update state [skip ci]"
          git push
```

---

## 7. 프로젝트 구조

```
steam-epic-deal-bot/
├── CLAUDE.md
├── SPEC.md
├── README.md
├── pyproject.toml          # ruff 설정 포함
├── requirements.txt        # requests, pyyaml
├── config.yaml
├── .env.example
├── .gitignore              # .venv/, .env, __pycache__ 등
├── .github/workflows/notify.yml
├── data/
│   └── state.json          # 초기엔 {"version":1,"deals":{}}
├── src/dealbot/
│   ├── __init__.py
│   ├── __main__.py         # CLI 엔트리: 인자 파싱(--dry-run), run() 호출
│   ├── config.py           # config.yaml + env 로드/검증
│   ├── models.py           # Deal, WatchItem 등 dataclass
│   ├── state.py            # load/save/diff (순수 로직, 테스트 핵심)
│   ├── notifier.py         # Discord webhook 전송 (embed 빌드, rate limit)
│   └── sources/
│       ├── __init__.py
│       └── itad.py         # ITAD 클라이언트 (lookup, prices, deals)
└── tests/
    ├── test_state.py       # diff 판정 로직 (네트워크 없이)
    └── test_itad.py        # 응답 파싱 (fixture 기반)
```

---

## 8. 개발 Phase

### Phase 1 — Watchlist 알림 (MVP) ✅ 먼저 동작시킬 것
- 로컬 venv 셋업: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- `config.yaml` watchlist 로드 → 각 게임 ITAD UUID 해석
- `/games/prices/v2` 로 현재 딜 조회 (country=KR)
- state diff → 신규/개선 딜만 Discord embed 전송
- `target_price` / `min_discount` 조건 반영
- `--dry-run` 로 콘솔 출력 확인 후 실제 Webhook 연결
- GitHub Actions cron 등록, state commit back 확인

### Phase 2 — 전체 deals 모드 (선택)
- `mode: deals` 일 때 `/deals/v2` 로 shops 내 `min_discount` 이상 딜 브로드캐스트
- 노이즈 많으니 할인율 임계값을 높게(예: 50%+) 두는 것을 기본으로

### Phase 3 — 다듬기 (선택)
- 게임 썸네일/역대최저가 필드 보강
- 에러 알림 (run 실패 시 별도 채널/멘션)
- 무료 게임(Epic weekly free) 전용 처리

---

## 9. 테스트 방침

- `state.py` 의 diff 판정은 **네트워크 없이** 단위 테스트 (신규/가격인하/할인율증가/target_price/min_discount 케이스).
- ITAD 응답 파싱은 저장한 JSON fixture로 테스트 (실제 API 호출 X).
- 통합 확인은 `--dry-run` + `workflow_dispatch` 수동 실행으로.

## 10. 완료 기준 (Phase 1)

- [ ] watchlist에 게임 2~3개 등록 후 `--dry-run` 에서 현재 할인이 콘솔에 정상 출력
- [ ] 실제 Webhook으로 Discord 채널에 embed 도착
- [ ] 두 번 연속 실행 시 두 번째엔 **중복 알림이 가지 않음** (state 동작)
- [ ] Actions cron이 스케줄대로 돌고 state.json이 commit back 됨