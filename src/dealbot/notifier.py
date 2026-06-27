"""Discord Webhook 전송 — embed 빌드 + rate limit 처리."""

from __future__ import annotations

import logging
import time

import requests

from dealbot.models import Deal

log = logging.getLogger(__name__)

EMBED_LIMIT = 10  # Discord: 한 메시지당 embed 최대 10개
_MAX_RETRIES = 5

_SYMBOLS = {"KRW": "₩", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_NO_DECIMAL = {"KRW", "JPY"}


def format_price(amount: float, currency: str) -> str:
    """통화에 맞춰 가격 문자열을 만든다 (예: ₩39,600 / $19.99)."""
    symbol = _SYMBOLS.get(currency, "")
    if currency in _NO_DECIMAL:
        body = f"{round(amount):,}"
    else:
        body = f"{amount:,.2f}"
    return f"{symbol}{body}" if symbol else f"{body} {currency}".strip()


def build_embed(deal: Deal) -> dict:
    """딜 하나를 Discord embed dict 로 변환한다 (affiliate URL 보존)."""
    fields = [
        {"name": "현재가", "value": format_price(deal.price_new, deal.currency), "inline": True},
        {"name": "정가", "value": format_price(deal.price_old, deal.currency), "inline": True},
    ]
    if deal.history_low is not None:
        fields.append(
            {
                "name": "역대최저",
                "value": format_price(deal.history_low, deal.currency),
                "inline": True,
            }
        )
    embed: dict = {
        "title": deal.title,
        "description": f"{deal.shop_name}에서 **{deal.cut}% 할인**",
        "fields": fields,
        "footer": {"text": "via IsThereAnyDeal"},
    }
    if deal.url:
        embed["url"] = deal.url
    if deal.thumbnail:
        embed["thumbnail"] = {"url": deal.thumbnail}
    return embed


def send_deals(
    deals: list[Deal],
    webhook_url: str,
    *,
    session: requests.Session | None = None,
    sleep_between: float = 1.0,
) -> None:
    """딜 목록을 10개씩 나눠 Discord Webhook 으로 전송한다. 비어 있으면 아무것도 안 함."""
    if not deals:
        return
    session = session or requests.Session()
    chunks = [deals[i : i + EMBED_LIMIT] for i in range(0, len(deals), EMBED_LIMIT)]
    for idx, chunk in enumerate(chunks):
        payload = {"embeds": [build_embed(d) for d in chunk]}
        _post_webhook(session, webhook_url, payload)
        log.info("Discord 전송: embed %d개 (%d/%d 배치)", len(chunk), idx + 1, len(chunks))
        if idx < len(chunks) - 1:
            time.sleep(sleep_between)


def build_summary_embed(
    top_deals: list[Deal],
    *,
    total: int,
    new_count: int,
    page_url: str,
    title: str,
) -> dict:
    """deals 모드 요약 embed: 현재/신규 개수 + 인기 TOP + 페이지 링크."""
    desc = f"현재 **{total:,}개** 할인 중"
    if new_count:
        desc += f" · 신규 {new_count:,}개"
    if page_url:
        desc += f"\n👉 [전체 할인 보기]({page_url})"

    fields = []
    for d in top_deals:
        rating = ""
        if d.review_score is not None:
            rating = f" · ⭐{d.review_score}%"
            if d.review_count:
                rating += f"({d.review_count:,})"
        value = (
            f"[{d.shop_name} -{d.cut}% · {format_price(d.price_new, d.currency)}]({d.url}){rating}"
        )
        fields.append({"name": d.title, "value": value, "inline": False})

    embed: dict = {
        "title": f"🎮 {title}",
        "description": desc,
        "footer": {"text": "via IsThereAnyDeal"},
    }
    if page_url:
        embed["url"] = page_url
    if fields:
        embed["fields"] = fields
    return embed


def send_summary(embed: dict, webhook_url: str, *, session: requests.Session | None = None) -> None:
    """단일 요약 embed 를 전송한다."""
    session = session or requests.Session()
    _post_webhook(session, webhook_url, {"embeds": [embed]})
    log.info("Discord 요약 전송 완료")


def _post_webhook(session: requests.Session, url: str, payload: dict) -> None:
    for attempt in range(_MAX_RETRIES):
        resp = session.post(url, json=payload, timeout=30)
        if resp.status_code == 429:
            wait = _retry_after(resp)
            log.warning(
                "Discord 429 (rate limit), %ss 대기 후 재시도 (%d/%d)",
                wait,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return
    raise RuntimeError("Discord webhook: rate limit 으로 재시도 초과")


def _retry_after(resp: requests.Response) -> float:
    """429 응답에서 대기 시간을 추출한다 (JSON body 우선, 없으면 헤더)."""
    try:
        body = resp.json()
        if isinstance(body, dict) and "retry_after" in body:
            return float(body["retry_after"])
    except ValueError, TypeError:
        pass
    return float(resp.headers.get("Retry-After", 1))
