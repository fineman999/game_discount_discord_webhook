"""state.diff 판정 로직 단위 테스트 (네트워크 없음)."""

from __future__ import annotations

from dealbot.config import WatchItem
from dealbot.models import Deal
from dealbot.state import diff, empty_state, is_improved, passes_watch_filter

NOW = "2026-06-27T00:00:00Z"


def make_deal(price_new=39600.0, price_old=66000.0, cut=40, game_id="g1", shop_id=61):
    return Deal(
        game_id=game_id,
        title="Elden Ring",
        shop_id=shop_id,
        shop_name="Steam",
        price_new=price_new,
        price_old=price_old,
        cut=cut,
        currency="KRW",
        url="https://itad.link/abc",
    )


def state_with(deal: Deal, **over) -> dict:
    entry = {
        "title": deal.title,
        "price_new": deal.price_new,
        "price_old": deal.price_old,
        "cut": deal.cut,
        "url": deal.url,
        "notified_at": "2026-06-01T00:00:00Z",
    }
    entry.update(over)
    return {"version": 1, "deals": {deal.key: entry}}


# --- is_improved --------------------------------------------------------------


def test_new_key_is_improved():
    assert is_improved(make_deal(), None) is True


def test_lower_price_is_improved():
    deal = make_deal(price_new=35000)
    prev = {"price_new": 39600, "cut": 40}
    assert is_improved(deal, prev) is True


def test_higher_cut_is_improved():
    deal = make_deal(cut=50)
    prev = {"price_new": 39600, "cut": 40}
    assert is_improved(deal, prev) is True


def test_same_price_not_improved():
    deal = make_deal()
    prev = {"price_new": 39600, "cut": 40}
    assert is_improved(deal, prev) is False


# --- diff: 기본 시나리오 ------------------------------------------------------


def test_new_deal_is_notified():
    deal = make_deal()
    notify, new_state = diff(empty_state(), [deal], {}, NOW)
    assert notify == [deal]
    assert deal.key in new_state["deals"]
    assert new_state["deals"][deal.key]["notified_at"] == NOW


def test_unchanged_deal_not_notified_idempotent():
    deal = make_deal()
    prev = state_with(deal)
    notify, new_state = diff(prev, [deal], {}, NOW)
    assert notify == []
    # 알림 안 했으므로 직전 notified_at 보존
    assert new_state["deals"][deal.key]["notified_at"] == "2026-06-01T00:00:00Z"


def test_price_drop_notified():
    prev = state_with(make_deal(price_new=39600))
    cheaper = make_deal(price_new=35000)
    notify, _ = diff(prev, [cheaper], {}, NOW)
    assert notify == [cheaper]


def test_disappeared_deal_removed_from_state():
    prev = state_with(make_deal())
    notify, new_state = diff(prev, [], {}, NOW)
    assert notify == []
    assert new_state["deals"] == {}


# --- diff: watchlist 필터 -----------------------------------------------------


def test_target_price_gate_blocks_when_above():
    deal = make_deal(price_new=45000)
    watch = {deal.game_id: WatchItem(title="Elden Ring", target_price=40000)}
    notify, _ = diff(empty_state(), [deal], watch, NOW)
    assert notify == []  # 45000 > 40000 → 알림 안 함


def test_target_price_gate_allows_when_below():
    deal = make_deal(price_new=39000)
    watch = {deal.game_id: WatchItem(title="Elden Ring", target_price=40000)}
    notify, _ = diff(empty_state(), [deal], watch, NOW)
    assert notify == [deal]


def test_min_discount_gate():
    low = make_deal(cut=10)
    watch = {low.game_id: WatchItem(title="Elden Ring", min_discount=20)}
    assert passes_watch_filter(low, watch[low.game_id]) is False
    notify, _ = diff(empty_state(), [low], watch, NOW)
    assert notify == []

    high = make_deal(cut=30)
    notify, _ = diff(empty_state(), [high], watch, NOW)
    assert notify == [high]
