"""상태 관리 + diff 판정 — 네트워크 비의존 순수 로직 (단위 테스트 핵심)."""

from __future__ import annotations

import json
from pathlib import Path

from dealbot.config import WatchItem
from dealbot.models import Deal

STATE_VERSION = 1


def empty_state() -> dict:
    return {"version": STATE_VERSION, "deals": {}}


def load_state(path: str | Path) -> dict:
    """state.json 을 읽는다. 없거나 깨졌으면 빈 상태를 반환한다."""
    p = Path(path)
    if not p.exists():
        return empty_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return empty_state()
    if not isinstance(data, dict) or "deals" not in data:
        return empty_state()
    return data


def save_state(path: str | Path, state: dict) -> None:
    """state 를 파일에 저장한다 (디렉터리 자동 생성, 트레일링 개행 포함)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    p.write_text(text + "\n", encoding="utf-8")


def is_improved(deal: Deal, prev: dict | None) -> bool:
    """직전 상태 대비 새 딜이거나 더 좋아졌는지(가격 인하 또는 할인율 증가) 판정."""
    if prev is None:
        return True  # 새로 등장한 딜
    if deal.price_new < prev.get("price_new", float("inf")):
        return True  # 가격 추가 인하
    if deal.cut > prev.get("cut", -1):
        return True  # 할인율 증가
    return False


def passes_watch_filter(deal: Deal, watch: WatchItem | None) -> bool:
    """watchlist 항목의 target_price / min_discount 조건을 만족하는지 판정."""
    if watch is None:
        return True
    if watch.target_price is not None and deal.price_new > watch.target_price:
        return False
    if watch.min_discount is not None and deal.cut < watch.min_discount:
        return False
    return True


def _entry(deal: Deal, notified_at: str) -> dict:
    return {
        "title": deal.title,
        "price_new": deal.price_new,
        "price_old": deal.price_old,
        "cut": deal.cut,
        "url": deal.url,
        "notified_at": notified_at,
    }


def diff(
    prev_state: dict,
    deals: list[Deal],
    watch_by_id: dict[str, WatchItem],
    now: str,
) -> tuple[list[Deal], dict]:
    """직전 상태와 현재 딜 목록을 비교해 (알림 대상, 새 상태) 를 반환한다.

    - 알림 대상: 신규/개선 딜 AND watchlist 필터 통과.
    - 새 상태: 현재 존재하는 딜만 보존 (사라진 딜은 자동 제거 → 종료된 할인 정리).
    - 같은 가격이 유지되면 재알림하지 않는다 (idempotent).
    """
    prev_deals = prev_state.get("deals", {})
    notify: list[Deal] = []
    new_deals: dict = {}

    for deal in deals:
        key = deal.key
        prev = prev_deals.get(key)
        should_notify = is_improved(deal, prev) and passes_watch_filter(
            deal, watch_by_id.get(deal.game_id)
        )
        if should_notify:
            notified_at = now
        else:
            # 알림하지 않는 경우 직전 알림 시각을 보존 (없으면 현재).
            notified_at = prev.get("notified_at", now) if prev else now
        new_deals[key] = _entry(deal, notified_at)
        if should_notify:
            notify.append(deal)

    return notify, {"version": STATE_VERSION, "deals": new_deals}
