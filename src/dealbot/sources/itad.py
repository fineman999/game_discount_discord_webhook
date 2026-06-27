"""IsThereAnyDeal (ITAD) API v2/v3 클라이언트.

스키마 출처: https://docs.isthereanydeal.com (2026-06 기준)
- 타이틀 → UUID:  POST /lookup/id/title/v1   (body: ["title", ...] → {"title": uuid|null})
- AppID → 게임:   GET  /games/lookup/v1?appid=
- 현재 가격/딜:   POST /games/prices/v3       (body: [uuid, ...])
- 전체 딜 목록:   GET  /deals/v2              ({list, hasMore, nextOffset})
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from dealbot.models import Deal

log = logging.getLogger(__name__)

BASE_URL = "https://api.isthereanydeal.com"
_MAX_RETRIES = 3


class ITADError(Exception):
    """ITAD API 호출 실패."""


def _amount(money: dict | None) -> float | None:
    """가격 객체에서 통화 단위 금액(amount)을 꺼낸다."""
    if not money:
        return None
    return money.get("amount")


def parse_prices(
    game: dict,
    title: str,
    thumbnail: str | None = None,
    shops: list[str] | None = None,
) -> list[Deal]:
    """/games/prices/v3 의 게임 객체 하나를 Deal 목록으로 파싱한다 (할인 cut>0 만)."""
    shop_filter = {s.lower() for s in shops} if shops else None
    history_low = _amount((game.get("historyLow") or {}).get("all"))
    out: list[Deal] = []
    for d in game.get("deals", []):
        deal = _parse_deal_obj(
            game_id=game["id"],
            title=title,
            deal_obj=d,
            history_low=history_low,
            thumbnail=thumbnail,
            shop_filter=shop_filter,
        )
        if deal is not None:
            out.append(deal)
    return out


def parse_deal_item(item: dict, shops: list[str] | None = None) -> Deal | None:
    """/deals/v2 의 list 항목 하나를 Deal 로 파싱한다 (할인 cut>0 만)."""
    deal_obj = item.get("deal")
    if not deal_obj:
        return None
    shop_filter = {s.lower() for s in shops} if shops else None
    history_low = _amount((deal_obj.get("historyLow") or {}).get("all"))
    thumbnail = (item.get("assets") or {}).get("boxart")
    return _parse_deal_obj(
        game_id=item["id"],
        title=item.get("title", ""),
        deal_obj=deal_obj,
        history_low=history_low,
        thumbnail=thumbnail,
        shop_filter=shop_filter,
    )


def _parse_deal_obj(
    *,
    game_id: str,
    title: str,
    deal_obj: dict,
    history_low: float | None,
    thumbnail: str | None,
    shop_filter: set[str] | None,
) -> Deal | None:
    cut = deal_obj.get("cut", 0) or 0
    if cut <= 0:
        return None
    shop = deal_obj.get("shop") or {}
    shop_name = shop.get("name", "")
    if shop_filter is not None and shop_name.lower() not in shop_filter:
        return None
    price = deal_obj.get("price") or {}
    regular = deal_obj.get("regular") or {}
    return Deal(
        game_id=game_id,
        title=title,
        shop_id=shop.get("id", 0),
        shop_name=shop_name,
        price_new=_amount(price) or 0.0,
        price_old=_amount(regular) or 0.0,
        cut=int(cut),
        currency=price.get("currency", ""),
        url=deal_obj.get("url", ""),
        history_low=history_low,
        thumbnail=thumbnail,
    )


class ITADClient:
    """ITAD 공개 가격 엔드포인트 클라이언트 (OAuth 불필요)."""

    def __init__(
        self,
        api_key: str,
        country: str = "US",
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.country = country
        self.session = session or requests.Session()

    # --- HTTP ---------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        params = dict(kwargs.pop("params", {}) or {})
        params["key"] = self.api_key
        url = BASE_URL + path
        for attempt in range(_MAX_RETRIES):
            resp = self.session.request(method, url, params=params, timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 5))
                log.warning(
                    "ITAD 429 (rate limit), %ss 대기 후 재시도 (%d/%d)",
                    wait,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                detail = resp.text[:300]
                raise ITADError(f"{method} {path} -> {resp.status_code}: {detail}") from exc
            return resp.json()
        raise ITADError(f"{method} {path}: rate limit 으로 재시도 초과")

    # --- 게임 식별자 해석 ---------------------------------------------------

    def lookup_by_appid(self, appid: int) -> dict | None:
        """Steam AppID → ITAD 게임 객체({id, title, assets, ...}) 또는 None."""
        data = self._request("GET", "/games/lookup/v1", params={"appid": appid})
        if not data.get("found"):
            return None
        return data.get("game")

    def lookup_by_titles(self, titles: list[str]) -> dict[str, str | None]:
        """타이틀 목록 → {title: uuid | None} (정확 매칭 기반)."""
        if not titles:
            return {}
        return self._request("POST", "/lookup/id/title/v1", json=titles)

    # --- 가격/딜 ------------------------------------------------------------

    def get_prices(self, game_ids: list[str]) -> dict[str, dict]:
        """UUID 목록의 현재 딜을 조회한다 → {uuid: game_obj}. 할인(deal)만 요청."""
        if not game_ids:
            return {}
        params = {"country": self.country, "deals": "true"}
        data = self._request("POST", "/games/prices/v3", params=params, json=game_ids)
        return {g["id"]: g for g in data}

    def iter_deals(
        self,
        *,
        sort: str = "rank",
        min_cut: int | None = None,
        limit: int = 200,
        max_items: int = 1500,
    ) -> list[dict]:
        """할인 중인 게임 목록을 페이지네이션으로 모은다 (cut>0 만).

        sort="rank" 는 인기 높은 순. sort="-cut" + min_cut 지정 시 할인율 내림차순으로
        받다가 min_cut 미만이 나오면 조기 종료한다 (정렬이 cut 기준일 때만 유효).
        """
        collected: list[dict] = []
        offset = 0
        while len(collected) < max_items:
            page_limit = min(limit, max_items - len(collected))
            params = {
                "country": self.country,
                "sort": sort,
                "limit": page_limit,
                "offset": offset,
            }
            data = self._request("GET", "/deals/v2", params=params)
            items = data.get("list", [])
            if not items:
                break
            for item in items:
                cut = (item.get("deal") or {}).get("cut", 0) or 0
                if cut <= 0:
                    continue
                if min_cut is not None and sort == "-cut" and cut < min_cut:
                    return collected  # cut 내림차순이므로 이후는 모두 미달
                collected.append(item)
                if len(collected) >= max_items:
                    break
            if not data.get("hasMore"):
                break
            offset = data.get("nextOffset", offset + len(items))
        return collected

    def get_game_info(self, game_id: str) -> dict:
        """게임 상세 정보({reviews, stats, players, appid, ...})를 조회한다."""
        return self._request("GET", "/games/info/v2", params={"id": game_id})


def steam_review(info: dict) -> tuple[int, int] | None:
    """게임 info 의 reviews 에서 Steam 평가 (score%, count) 를 추출한다. 없으면 None."""
    for review in info.get("reviews") or []:
        if review.get("source") == "Steam" and review.get("score") is not None:
            return int(review["score"]), int(review.get("count") or 0)
    return None
