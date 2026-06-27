"""ITAD 응답 파싱 테스트 (fixture 기반, 네트워크 없음)."""

from __future__ import annotations

from dealbot.sources.itad import match_shop_ids, parse_deal_item, parse_prices

SHOPS_FIXTURE = [
    {"id": 61, "title": "Steam"},
    {"id": 16, "title": "Epic Game Store"},
    {"id": 35, "title": "GOG"},
    {"id": 36, "title": "GreenManGaming"},
]


def test_match_shop_ids_epic_and_steam():
    assert set(match_shop_ids(SHOPS_FIXTURE, ["steam", "epic"])) == {61, 16}


def test_match_shop_ids_substring_only():
    # "epic" 은 "Epic Game Store" 에만 매칭, GOG/GMG 는 제외
    assert match_shop_ids(SHOPS_FIXTURE, ["epic"]) == [16]


def test_match_shop_ids_no_match():
    assert match_shop_ids(SHOPS_FIXTURE, ["origin"]) == []


# /games/prices/v3 게임 객체 fixture (docs 예시 구조 기반, KRW 로 각색)
PRICES_GAME = {
    "id": "018d937f-012f-73b8-ab2c-898516969e6a",
    "historyLow": {"all": {"amount": 33000.0, "amountInt": 3300000, "currency": "KRW"}},
    "deals": [
        {
            "shop": {"id": 61, "name": "Steam"},
            "price": {"amount": 39600.0, "currency": "KRW"},
            "regular": {"amount": 66000.0, "currency": "KRW"},
            "cut": 40,
            "url": "https://itad.link/steam-deal",
        },
        {
            "shop": {"id": 16, "name": "Epic Game Store"},
            "price": {"amount": 49500.0, "currency": "KRW"},
            "regular": {"amount": 66000.0, "currency": "KRW"},
            "cut": 25,
            "url": "https://itad.link/epic-deal",
        },
        {
            # cut 0 — 할인 아님, 제외돼야 함
            "shop": {"id": 35, "name": "GOG"},
            "price": {"amount": 66000.0, "currency": "KRW"},
            "regular": {"amount": 66000.0, "currency": "KRW"},
            "cut": 0,
            "url": "https://itad.link/gog",
        },
    ],
}


def test_parse_prices_basic():
    deals = parse_prices(PRICES_GAME, title="Elden Ring")
    # cut 0 제외 → 2개
    assert len(deals) == 2
    steam = next(d for d in deals if d.shop_name == "Steam")
    assert steam.price_new == 39600.0
    assert steam.price_old == 66000.0
    assert steam.cut == 40
    assert steam.currency == "KRW"
    assert steam.history_low == 33000.0
    assert steam.url == "https://itad.link/steam-deal"
    assert steam.key == "018d937f-012f-73b8-ab2c-898516969e6a:61"


def test_parse_prices_shop_filter():
    deals = parse_prices(PRICES_GAME, title="Elden Ring", shops=["steam"])
    assert len(deals) == 1
    assert deals[0].shop_name == "Steam"


def test_parse_prices_shop_filter_epic_substring():
    # "epic" 토큰이 ITAD 의 "Epic Game Store" 에 부분 일치해야 한다.
    deals = parse_prices(PRICES_GAME, title="Elden Ring", shops=["epic"])
    assert len(deals) == 1
    assert deals[0].shop_name == "Epic Game Store"


def test_parse_prices_shop_filter_steam_and_epic():
    deals = parse_prices(PRICES_GAME, title="Elden Ring", shops=["steam", "epic"])
    assert {d.shop_name for d in deals} == {"Steam", "Epic Game Store"}


def test_parse_prices_thumbnail_passthrough():
    deals = parse_prices(PRICES_GAME, title="Elden Ring", thumbnail="https://img/box.jpg")
    assert all(d.thumbnail == "https://img/box.jpg" for d in deals)


# /deals/v2 list 항목 fixture
DEAL_ITEM = {
    "id": "018d9584-24d6-7010-b82b-df1f0b154cc7",
    "slug": "baldurs-gate-3",
    "title": "Baldur's Gate 3",
    "assets": {"boxart": "https://assets/bg3.jpg"},
    "deal": {
        "shop": {"id": 61, "name": "Steam"},
        "price": {"amount": 35700.0, "currency": "KRW"},
        "regular": {"amount": 51000.0, "currency": "KRW"},
        "cut": 30,
        "historyLow": {"all": {"amount": 35700.0, "currency": "KRW"}},
        "url": "https://itad.link/bg3",
    },
}


def test_parse_deal_item_basic():
    deal = parse_deal_item(DEAL_ITEM)
    assert deal is not None
    assert deal.title == "Baldur's Gate 3"
    assert deal.cut == 30
    assert deal.shop_name == "Steam"
    assert deal.thumbnail == "https://assets/bg3.jpg"
    assert deal.history_low == 35700.0


def test_parse_deal_item_shop_filter_excludes():
    assert parse_deal_item(DEAL_ITEM, shops=["epic"]) is None


def test_parse_deal_item_no_deal_returns_none():
    assert parse_deal_item({"id": "x", "title": "y"}) is None
