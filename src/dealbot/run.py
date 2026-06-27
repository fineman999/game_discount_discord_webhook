"""오케스트레이션 — 설정 로드 → 가격 조회 → diff → 알림 → 상태 저장."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from dealbot.config import Config, WatchItem, load_config
from dealbot.models import Deal
from dealbot.notifier import build_summary_embed, format_price, send_deals, send_summary
from dealbot.sources.itad import ITADClient, parse_deal_item, parse_prices, steam_review
from dealbot.state import diff, load_state, save_state

log = logging.getLogger(__name__)

STATE_PATH = Path("data/state.json")
WATCHLIST_JSON_PATH = Path("docs/watchlist.json")  # 페이지 "찜" 탭이 읽는 파일


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_watchlist(
    client: ITADClient, watchlist: list[WatchItem]
) -> list[tuple[WatchItem, str, str, str | None]]:
    """watchlist 항목을 (watch, game_id, title, thumbnail) 로 해석한다.

    한 항목 해석이 실패해도 전체를 죽이지 않고 건너뛴다.
    """
    titles = [w.title for w in watchlist if w.title and not w.steam_appid]
    try:
        title_map = client.lookup_by_titles(titles) if titles else {}
    except Exception:
        log.exception("타이틀 일괄 해석 실패")
        title_map = {}

    resolved: list[tuple[WatchItem, str, str, str | None]] = []
    for w in watchlist:
        try:
            if w.steam_appid:
                game = client.lookup_by_appid(w.steam_appid)
                if not game:
                    log.warning("Steam AppID %s 해석 실패", w.steam_appid)
                    continue
                thumb = (game.get("assets") or {}).get("boxart")
                resolved.append((w, game["id"], game.get("title", ""), thumb))
            elif w.title:
                gid = title_map.get(w.title) or _search_first_id(client, w.title)
                if not gid:
                    log.warning("'%s' → ITAD UUID 해석 실패 (정확한 타이틀인지 확인)", w.title)
                    continue
                resolved.append((w, gid, w.title, None))
        except Exception:
            log.exception("watchlist 항목 해석 중 오류: %r", w)
    return resolved


def _search_first_id(client: ITADClient, title: str) -> str | None:
    """정확 매칭 실패 시 검색으로 폴백해 첫 결과의 ITAD id 를 반환한다."""
    try:
        results = client.search(title, results=1)
    except Exception:
        log.exception("검색 폴백 실패: %s", title)
        return None
    if results:
        log.info("'%s' → 검색 폴백으로 해석: %s", title, results[0].get("title"))
        return results[0].get("id")
    return None


def search_games(client: ITADClient, query: str) -> int:
    """게임을 검색해 title 과 steam_appid 를 출력한다 (config.yaml 채우기 보조)."""
    try:
        results = client.search(query, results=8)
    except Exception:
        log.exception("검색 실패")
        return 1
    if not results:
        print(f"'{query}' 검색 결과가 없어요.")
        return 0
    print(f"\n'{query}' 검색 결과 — config.yaml watchlist 에 복사하세요:\n")
    for g in results:
        appid = None
        try:
            appid = client.get_game_info(g["id"]).get("appid")
        except Exception:
            pass
        if appid:
            print(f"  {g.get('title')}")
            print(f"    - steam_appid: {appid}")
        else:
            print(f"  {g.get('title')}   (Steam 외 — title 로 추가)")
            print(f'    - title: "{g.get("title")}"')
    print()
    return 0


def _collect_watchlist_deals(
    client: ITADClient, cfg: Config
) -> tuple[list[Deal], dict[str, WatchItem]]:
    resolved = _resolve_watchlist(client, cfg.watchlist)
    if not resolved:
        log.warning("해석된 watchlist 항목이 없습니다.")
        return [], {}

    game_ids = list({gid for _, gid, _, _ in resolved})
    meta = {gid: (title, thumb) for _, gid, title, thumb in resolved}
    watch_by_id = {gid: w for w, gid, _, _ in resolved}

    prices = client.get_prices(game_ids)
    deals: list[Deal] = []
    for gid in game_ids:
        game = prices.get(gid)
        if not game:
            continue
        title, thumb = meta[gid]
        try:
            deals.extend(parse_prices(game, title, thumb, cfg.shops))
        except Exception:
            log.exception("가격 파싱 오류: %s", gid)
    return deals, watch_by_id


def _collect_shop_deals(client: ITADClient, cfg: Config, token: str) -> list[Deal]:
    """한 상점(token)의 할인을 인기순으로 모은다. 상점 ID 로 서버단 필터링."""
    shop_ids = client.resolve_shop_ids([token]) if token else None
    if token and not shop_ids:
        log.warning("'%s' → ITAD 상점 ID 해석 실패, 이름 부분일치로 폴백", token)
    items = client.iter_deals(sort="rank", shop_ids=shop_ids, max_items=cfg.deals_max_items)
    name_filter = [token] if token else None
    deals: list[Deal] = []
    for item in items:
        try:
            deal = parse_deal_item(item, name_filter)
        except Exception:
            log.exception("딜 파싱 오류: %s", item.get("id"))
            continue
        if deal is not None:
            deals.append(deal)
    return deals


def _review_tag(d: Deal) -> str:
    """dry-run 출력용 Steam 평가 꼬리표 (없으면 빈 문자열)."""
    if d.review_score is None:
        return ""
    return f" ⭐{d.review_score}%({d.review_count:,})"


def _enrich_reviews(client: ITADClient, deals: list[Deal]) -> None:
    """주어진 딜들에 Steam 평가(점수/리뷰수)를 채운다. 실패는 무시(하이라이트용)."""
    for d in deals:
        try:
            info = client.get_game_info(d.game_id)
        except Exception:
            log.warning("게임 정보 조회 실패: %s", d.game_id)
            continue
        review = steam_review(info)
        if review:
            d.review_score, d.review_count = review


# --- watchlist 모드 (Discord 직접 알림 + 페이지 "찜" 탭) ----------------------


def _deal_row(d: Deal) -> dict:
    """Deal 을 페이지가 읽는 행(row) 형식으로 변환한다 (Worker 응답과 동일 스키마)."""
    return {
        "id": d.game_id,
        "title": d.title,
        "shop": d.shop_name,
        "cut": d.cut,
        "price": d.price_new,
        "regular": d.price_old,
        "low": d.history_low,
        "currency": d.currency,
        "url": d.url,
        "thumb": d.thumbnail or "",
        "banner": d.thumbnail or "",
        "start": d.discount_start,
        "expiry": d.discount_end,
    }


def _enrich_assets(client: ITADClient, deals: list[Deal]) -> None:
    """썸네일이 없는 딜(주로 title 기반 항목)에 box art 를 채운다. watchlist 는 작아 저렴."""
    seen: dict[str, str | None] = {}
    for d in deals:
        if d.thumbnail:
            continue
        if d.game_id not in seen:
            try:
                info = client.get_game_info(d.game_id)
                seen[d.game_id] = (info.get("assets") or {}).get("boxart")
            except Exception:
                log.warning("자산 조회 실패: %s", d.game_id)
                seen[d.game_id] = None
        if seen[d.game_id]:
            d.thumbnail = seen[d.game_id]


def _write_watchlist_json(deals: list[Deal], now: str) -> None:
    """watchlist 의 현재 할인들을 페이지용 JSON 으로 기록한다 (작은 파일, 커밋됨)."""
    payload = {"generated_at": now, "count": len(deals), "deals": [_deal_row(d) for d in deals]}
    WATCHLIST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log.info("찜 데이터 기록: %s (%d개)", WATCHLIST_JSON_PATH, len(deals))


def _print_dry(deals: list[Deal]) -> None:
    print(f"\n=== DRY-RUN: 알림 대상 {len(deals)}개 ===")
    for d in deals:
        now = format_price(d.price_new, d.currency)
        old = format_price(d.price_old, d.currency)
        low = f" / 역대최저 {format_price(d.history_low, d.currency)}" if d.history_low else ""
        print(f"  [{d.shop_name}] {d.title} — {d.cut}% off  {now} (정가 {old}){low}")
        print(f"      {d.url}")
    print("=== (실제 전송 안 함) ===\n")


def _run_watchlist(client: ITADClient, cfg: Config, dry_run: bool) -> int:
    deals, watch_by_id = _collect_watchlist_deals(client, cfg)
    state = load_state(STATE_PATH)
    notify, new_state = diff(state, deals, watch_by_id, _utcnow_iso())
    log.info("현재 할인 딜 %d개, 신규/개선 알림 대상 %d개", len(deals), len(notify))

    if not notify:
        log.info("신규/개선 딜 없음 — 알림 보내지 않음 (조용함이 정상)")
    elif dry_run:
        _print_dry(notify)
    else:
        send_deals(notify, cfg.webhook_url)

    if not dry_run:  # dry-run 은 상태/파일을 변경하지 않는다.
        save_state(STATE_PATH, new_state)
        log.info("상태 저장: %s", STATE_PATH)
        _enrich_assets(client, deals)  # 찜 카드 썸네일 보강
        _write_watchlist_json(deals, _utcnow_iso())  # 페이지 "찜" 탭용 (전체 현재 할인)
    return 0


# --- deals 모드 (페이지 생성 + Discord 요약 1개) -----------------------------


def _run_deals(client: ITADClient, cfg: Config, dry_run: bool) -> int:
    """deals 모드: 설정된 상점마다 따로 조회해 Discord 요약을 상점당 1개씩 보낸다.

    동적 페이지(Worker)가 목록을 담당하므로 상태 저장/페이지 생성은 하지 않는다 (git no churn).
    """
    tokens = cfg.shops or [""]  # 상점 미설정 시 전체 1개로 처리
    summaries: list[tuple[str, list[Deal], list[Deal], dict]] = []
    for token in tokens:
        deals = _collect_shop_deals(client, cfg, token)
        if not deals:  # 딜 0개 상점은 요약 생략 (전송 노이즈 방지)
            log.info("[%s] 현재 할인 0개 — 요약 생략", token or "전체")
            continue
        label = deals[0].shop_name
        top = deals[:5]
        _enrich_reviews(client, top)
        anchor = f"#{token}" if token and cfg.page_base_url else ""
        embed = build_summary_embed(
            top,
            total=len(deals),
            new_count=0,
            page_url=(cfg.page_base_url + anchor) if cfg.page_base_url else "",
            title=f"{cfg.page_title} — {label}",
        )
        summaries.append((label, deals, top, embed))
        log.info("[%s] 할인 %d개", label, len(deals))

    if dry_run:
        print("\n=== DRY-RUN: deals 요약 (상점별, 실제 전송 안 함) ===")
        for label, deals, top, _ in summaries:
            print(f"\n[{label}] 현재 할인 {len(deals):,}개 — 인기 TOP 5:")
            for d in top:
                price = format_price(d.price_new, d.currency)
                print(f"  - {d.title} [-{d.cut}% {price}]{_review_tag(d)}")
        if not cfg.page_base_url:
            print("\n※ config.yaml 의 page.base_url 미설정 → Discord 링크 비활성")
        print("===\n")
    else:
        for i, (_label, _deals, _top, embed) in enumerate(summaries):
            send_summary(embed, cfg.webhook_url)
            if i < len(summaries) - 1:
                time.sleep(1.0)
    return 0


def run_search(query: str) -> int:
    """`--search` 진입점: ITAD 에서 게임을 검색해 식별자를 출력한다."""
    cfg = load_config(require_webhook=False)
    client = ITADClient(cfg.api_key, cfg.country)
    return search_games(client, query)


def run(dry_run: bool = False) -> int:
    """봇 1회 실행. mode 에 따라 watchlist/deals 를 실행한다 (both 면 둘 다). 성공 시 0."""
    cfg = load_config(require_webhook=not dry_run)
    client = ITADClient(cfg.api_key, cfg.country)
    rc = 0
    if cfg.mode in ("watchlist", "both"):  # watchlist 는 항상 Discord 로 알림
        rc |= _run_watchlist(client, cfg, dry_run)
    if cfg.mode in ("deals", "both"):
        rc |= _run_deals(client, cfg, dry_run)
    return rc
