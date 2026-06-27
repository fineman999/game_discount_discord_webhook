# 사용 방법

게임 할인을 **Discord로 알림** 받고, **웹 페이지**에서 둘러보는 봇 사용 가이드.

- 웹 페이지: https://fineman999.github.io/game_discount_discord_webhook/
- 설치·배포는 [README](README.md) 참고. 이 문서는 "쓰는 법" 위주.

---

## 1. 한눈에

- **찜한 게임**이 할인하면 → **Discord 알림** (한 번 본 할인은 다시 안 옴)
- **전체 할인**은 → 웹 페이지에서 Steam/Epic 별로 둘러보기 (실시간)
- 설정은 `config.yaml` 하나, 실행은 `python -m dealbot`

---

## 2. 찜 목록에 게임 추가하기 (`config.yaml` 의 `watchlist`)

게임은 **`steam_appid`** 또는 **`title`** 중 하나로 지정합니다 (둘 중 하나만 있어도 됨).

```yaml
watchlist:
  - steam_appid: 1245620    # Elden Ring (가장 확실)
    target_price: 40000     # (선택) 이 가격(원) 이하일 때만 알림
  - title: "Hades II"       # 제목으로도 가능
    min_discount: 20        # (선택) 이 할인율(%) 이상일 때만 알림
  - steam_appid: 3280350    # DEATH STRANDING 2
```

### 식별자 찾는 법 — `--search` 가 제일 쉬움

```bash
python -m dealbot --search "elden ring"
#   Elden Ring
#     - steam_appid: 1245620      ← 이 줄을 watchlist 에 복사
#   ELDEN RING NIGHTREIGN
#     - steam_appid: 2622380
```

수동으로 찾으려면:

| 항목 | 찾는 법 |
|---|---|
| `steam_appid` | Steam 스토어 URL `…/app/`**`1245620`**`/…` 의 숫자 |
| `title` | 정확한 영문 제목. ITAD가 표기·대소문자에 민감하므로 **Steam 게임은 `steam_appid` 권장** |

> Epic 전용 게임은 `title` 로 추가하세요 (예: `- title: "Alan Wake 2"`). 제목이 안 맞아도 자동으로 검색 폴백을 시도합니다.

### 선택 조건

- `target_price: 40000` — 현재가가 4만원 **이하**일 때만 알림
- `min_discount: 20` — 할인율이 **20% 이상**일 때만 알림
- 둘 다 없으면 → **할인이 시작/개선될 때마다** 알림

---

## 3. 모드 (`config.yaml` 의 `mode`)

| mode | 동작 |
|---|---|
| `watchlist` | 찜한 게임만 Discord 알림 (조용함) |
| `deals` | 전체 할인을 페이지에 + Discord에 상점별 요약 1개씩 |
| `both` | 위 둘 다 |

> **찜(watchlist) 알림은 항상 Discord로** 갑니다. `deals`/`both` 에서도 동일.

---

## 4. 웹 페이지 보는 법

상단 탭으로 전환합니다.

| 탭 | 내용 |
|---|---|
| **전체** | 인기순으로 Steam·Epic 섞어서. 같은 게임이 양쪽에서 할인 중이면 **한 카드에 두 가격** (`Steam+Epic` 태그) |
| **Steam** | Steam 할인만 |
| **Epic** | Epic 할인만 |
| **찜** | 내 watchlist 게임 중 현재 할인 중인 것 |

- 🔍 **검색**: 게임 이름 일부 입력
- **정렬**: 인기순 / 할인율 높은순 / 가격 낮은순
- **Biggest Steals**: 할인율이 가장 큰 게임 가로 슬라이드
- 데이터는 실시간(엣지 캐시 30분). "찜" 탭은 봇이 마지막으로 돈 시점 기준.

---

## 5. 자주 쓰는 명령

```bash
# 게임 식별자 검색 (config 채울 때)
python -m dealbot --search "hades"

# 실제 전송 없이 콘솔로만 미리보기 (상태 변경 안 함)
python -m dealbot --dry-run

# 실제 실행 (Discord 전송 + 상태 갱신)
python -m dealbot

# 자세한 로그
python -m dealbot --dry-run -v
```

> 로컬 실행 전: `source .venv/bin/activate` 후 `.env` 에 `ITAD_API_KEY` / `DISCORD_WEBHOOK_URL` 필요. (자세히는 [README](README.md))

---

## 6. 자동 실행

- GitHub Actions가 **매일 09:00 KST** 에 자동 실행 (`.github/workflows/notify.yml` 의 cron).
- 수동 실행: GitHub repo → **Actions → deal-notify → Run workflow**.
- 같은 할인은 `data/state.json` 으로 중복 방지 → **두 번 알림 안 감**.

---

## 7. 자주 묻는 것

**Q. 찜한 게임을 추가했는데 알림이 안 와요.**
→ 그 게임이 **지금 할인 중이 아닐 수** 있어요. `--dry-run` 으로 현재 할인 여부를 확인하세요. `target_price`/`min_discount` 조건이 너무 빡빡한지도 확인.

**Q. `title` 로 넣었는데 "해석 실패" 로그가 떠요.**
→ 제목 표기가 ITAD와 다를 수 있어요. `--search` 로 정확한 이름/`steam_appid` 를 찾아 넣으세요.

**Q. "찜" 탭이 비어 있어요.**
→ 봇이 `watchlist`/`both` 모드로 한 번 실행돼야 `docs/watchlist.json` 이 생깁니다. 또는 찜한 게임이 현재 할인 중이 아닐 수 있어요.

**Q. Discord 알림이 너무 많아요.**
→ `mode: watchlist` 로 바꾸면 찜한 게임만 와요. `deals`/`both` 는 상점별 요약도 보냅니다.

**Q. 다른 나라 가격으로 보고 싶어요.**
→ `config.yaml` 의 `country` 를 바꾸세요 (예: `US`, `JP`). 페이지는 Worker 쪽 `country` 파라미터 기준.
