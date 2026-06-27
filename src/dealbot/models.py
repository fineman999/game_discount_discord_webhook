"""도메인 모델 — 네트워크/IO 비의존 순수 dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Deal:
    """특정 게임이 특정 스토어에서 할인 중인 상태 하나."""

    game_id: str  # ITAD UUID
    title: str
    shop_id: int
    shop_name: str
    price_new: float  # 현재가 (할인가)
    price_old: float  # 정가
    cut: int  # 할인율(%)
    currency: str
    url: str  # ITAD deal 링크 (affiliate 태그 보존)
    history_low: float | None = None  # 역대 최저가
    thumbnail: str | None = None
    review_score: int | None = None  # Steam 평가 점수(%) — TOP 하이라이트용
    review_count: int | None = None  # Steam 리뷰 수 — TOP 하이라이트용

    @property
    def key(self) -> str:
        """state.json 에서 이 딜을 식별하는 키."""
        return f"{self.game_id}:{self.shop_id}"
