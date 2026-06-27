"""run 헬퍼 테스트 (순수 변환)."""

from __future__ import annotations

from dealbot.models import Deal
from dealbot.run import _deal_row


def test_deal_row_maps_fields():
    d = Deal(
        game_id="g1",
        title="Elden Ring",
        shop_id=61,
        shop_name="Steam",
        price_new=39600.0,
        price_old=66000.0,
        cut=40,
        currency="KRW",
        url="https://itad.link/x",
        history_low=33000.0,
        thumbnail="https://img/box.jpg",
        discount_start="2026-06-25T00:00:00Z",
        discount_end="2026-07-09T00:00:00Z",
    )
    r = _deal_row(d)
    assert r == {
        "id": "g1",
        "title": "Elden Ring",
        "shop": "Steam",
        "cut": 40,
        "price": 39600.0,
        "regular": 66000.0,
        "low": 33000.0,
        "currency": "KRW",
        "url": "https://itad.link/x",
        "thumb": "https://img/box.jpg",
        "banner": "https://img/box.jpg",
        "start": "2026-06-25T00:00:00Z",
        "expiry": "2026-07-09T00:00:00Z",
    }
