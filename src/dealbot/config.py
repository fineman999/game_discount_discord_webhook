"""config.yaml + 환경변수(시크릿) 로드/검증."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class WatchItem:
    """watchlist 의 한 항목. title 또는 steam_appid 중 하나로 게임을 지정한다."""

    title: str | None = None
    steam_appid: int | None = None
    target_price: float | None = None  # 이 가격 이하일 때만 알림
    min_discount: int | None = None  # 이 할인율(%) 이상일 때만 알림


@dataclass
class Config:
    country: str
    mode: str  # "watchlist" | "deals"
    watchlist: list[WatchItem] = field(default_factory=list)
    shops: list[str] = field(default_factory=list)
    deals_max_items: int = 1500
    page_title: str = "오늘의 게임 할인"
    page_base_url: str = ""
    api_key: str = ""
    webhook_url: str | None = None


class ConfigError(Exception):
    """설정/시크릿 누락 등 설정 단계 오류."""


def _load_dotenv(path: str | Path = ".env") -> None:
    """`.env` 가 있으면 환경변수로 로드한다 (이미 설정된 값은 덮어쓰지 않음)."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_watchlist(raw: list[dict]) -> list[WatchItem]:
    items: list[WatchItem] = []
    for entry in raw or []:
        items.append(
            WatchItem(
                title=entry.get("title"),
                steam_appid=entry.get("steam_appid"),
                target_price=entry.get("target_price"),
                min_discount=entry.get("min_discount"),
            )
        )
    return items


def load_config(
    path: str | Path = "config.yaml",
    *,
    require_webhook: bool = True,
) -> Config:
    """config.yaml 과 환경변수에서 설정을 읽어 검증한다.

    require_webhook=False (dry-run 등) 이면 DISCORD_WEBHOOK_URL 누락을 허용한다.
    """
    _load_dotenv()

    p = Path(path)
    if not p.exists():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    api_key = os.environ.get("ITAD_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("환경변수 ITAD_API_KEY 가 설정되지 않았습니다.")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip() or None
    if require_webhook and not webhook_url:
        raise ConfigError("환경변수 DISCORD_WEBHOOK_URL 가 설정되지 않았습니다.")

    mode = raw.get("mode", "watchlist")
    if mode not in ("watchlist", "deals", "both"):
        raise ConfigError(f"mode 는 'watchlist' | 'deals' | 'both' 중 하나여야 합니다: {mode!r}")

    deals_cfg = raw.get("deals") or {}
    page_cfg = raw.get("page") or {}

    return Config(
        country=raw.get("country", "US"),
        mode=mode,
        watchlist=_parse_watchlist(raw.get("watchlist") or []),
        shops=[str(s) for s in (raw.get("shops") or [])],
        deals_max_items=int(deals_cfg.get("max_items", 1500)),
        page_title=page_cfg.get("title", "오늘의 게임 할인"),
        page_base_url=(page_cfg.get("base_url") or "").strip(),
        api_key=api_key,
        webhook_url=webhook_url,
    )
