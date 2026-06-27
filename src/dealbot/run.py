"""오케스트레이션 — 설정 로드 → 가격 조회 → diff → 알림 → 상태 저장."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from dealbot.config import Config, WatchItem, load_config
from dealbot.models import Deal
from dealbot.notifier import build_summary_embed, format_price, send_deals, send_summary
from dealbot.sources.itad import ITADClient, parse_deal_item, parse_prices, steam_review
from dealbot.state import diff, load_state, save_state

log = logging.getLogger(__name__)

STATE_PATH = Path("data/state.json")


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
                gid = title_map.get(w.title)
                if not gid:
                    log.warning("'%s' → ITAD UUID 해석 실패 (정확한 타이틀인지 확인)", w.title)
                    continue
                resolved.append((w, gid, w.title, None))
        except Exception:
            log.exception("watchlist 항목 해석 중 오류: %r", w)
    return resolved


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


def _collect_broadcast_deals(client: ITADClient, cfg: Config) -> list[Deal]:
    """할인 중인 게임을 인기순으로 모아 Deal 목록으로 만든다 (할인율 컷 없음)."""
    log.info("deals 모드: 할인 중인 게임 인기순 최대 %d개 조회 중...", cfg.deals_max_items)
    items = client.iter_deals(sort="rank", max_items=cfg.deals_max_items)
    deals: list[Deal] = []
    for item in items:
        try:
            deal = parse_deal_item(item, cfg.shops)
        except Exception:
            log.exception("딜 파싱 오류: %s", item.get("id"))
            continue
        if deal is not None:
            deals.append(deal)
    return deals


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


# --- watchlist 모드 (Discord 직접 알림) --------------------------------------


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

    if not dry_run:  # dry-run 은 상태를 변경하지 않는다.
        save_state(STATE_PATH, new_state)
        log.info("상태 저장: %s", STATE_PATH)
    return 0


# --- deals 모드 (페이지 생성 + Discord 요약 1개) -----------------------------


def _run_deals(client: ITADClient, cfg: Config, dry_run: bool) -> int:
    """deals 모드: 동적 페이지(Worker)가 목록을 담당하므로 여기선 Discord 요약만 보낸다.

    상태 저장/페이지 생성을 하지 않아 git 에 데이터를 커밋하지 않는다 (no churn).
    """
    deals = _collect_broadcast_deals(client, cfg)
    log.info("할인 %d개", len(deals))

    top = deals[:5]
    _enrich_reviews(client, top)
    embed = build_summary_embed(
        top,
        total=len(deals),
        new_count=0,
        page_url=cfg.page_base_url,
        title=cfg.page_title,
    )

    if dry_run:
        print("\n=== DRY-RUN: deals 요약 (실제 전송 안 함) ===")
        print(f"현재 할인 {len(deals):,}개")
        if not cfg.page_base_url:
            print("※ config.yaml 의 page.base_url 미설정 → Discord 링크 비활성")
        print("인기 TOP 5:")
        for d in top:
            r = f" ⭐{d.review_score}%({d.review_count:,})" if d.review_score is not None else ""
            price = format_price(d.price_new, d.currency)
            print(f"  - {d.title} [{d.shop_name} -{d.cut}% {price}]{r}")
        print("===\n")
    else:
        send_summary(embed, cfg.webhook_url)
    return 0


def run(dry_run: bool = False) -> int:
    """봇 1회 실행. 성공 시 0 반환."""
    cfg = load_config(require_webhook=not dry_run)
    client = ITADClient(cfg.api_key, cfg.country)
    if cfg.mode == "deals":
        return _run_deals(client, cfg, dry_run)
    return _run_watchlist(client, cfg, dry_run)
