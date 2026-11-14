"""Data models for stores, search candidates, and product groups."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .utils import (
    RATING_PRIOR,
    RATING_WEIGHT,
    norm,
)


@dataclass
class Store:
    name: str
    base_url: str
    search_url: str            # с плейсхолдером {query}
    card: str
    brand: str
    name_sel: str              # название товара
    price: str                 # цена в карточке выдачи
    images: List[str]          # селекторы фото (пробуются по очереди)
    link: str
    detail: str                # ключ обработчика страницы товара
    detail_ready: str          # селектор готовности страницы товара
    name_from_attr: bool = False
    type_sel: Optional[str] = None
    label_sel: Optional[str] = None   # элемент, у которого title содержит оттенок/объём
    rating_sel: Optional[str] = None
    reviews_sel: Optional[str] = None
    show_type: bool = False
    # Старая цена лежит внутри элемента цены: брать только собственный текст, иначе склеятся обе
    price_own_text: bool = False
    currency: str = "₸"
    # Валюта цены на сайте. Если не ₸, цена пересчитывается в ₸ по fx_to_kzt,
    # а в сообщении рядом пишется исходная цена.
    price_currency: str = "₸"
    fx_to_kzt: float = 1.0


@dataclass
class Candidate:
    store: Store
    brand: str
    name: str
    type_: str
    label: str
    url: str
    image: str
    rating: Optional[float]
    reviews: int
    list_price: Optional[int]
    price_prefix: str
    pos: int
    ratio: float = 0.0
    list_price_native: Optional[float] = None  # цена в валюте магазина
    hay: Tuple = field(default_factory=tuple, repr=False)

    @property
    def full_title(self) -> str:
        if norm(self.brand) and norm(self.brand) in norm(self.name):
            return self.name
        return f"{self.brand} {self.name}".strip()

    @property
    def key(self) -> str:
        return f"{self.store.name}|{norm(self.full_title)}"

    def pop_key(self) -> Tuple[float, int]:
        """Популярность + оценка: сглаженный рейтинг (учитывает число отзывов)."""
        if self.rating is None:
            # нет рейтинга (Mon Amie): ориентируемся на порядок «по популярности» самого сайта
            return RATING_PRIOR - 0.01 * self.pos, 0
        v = self.reviews
        score = v / (v + RATING_WEIGHT) * self.rating + RATING_WEIGHT / (v + RATING_WEIGHT) * RATING_PRIOR
        return score, v

    def to_result(self) -> Dict:
        return {
            "store": self.store.name,
            "title": self.full_title,
            "subtitle": self.type_ if self.store.show_type else "",
            "ratio": self.ratio,
            "image_url": self.image,
            "product_url": self.url,
            "currency": self.store.currency,
            "rating": self.rating,
            "reviews": self.reviews,
            "volume": None,
            "unit": "",
            "price": None,
            "price_native": None,
            "native_currency": self.store.price_currency,
            "old_price": None,
            "loyalty_price": None,
        }


@dataclass
class Group:
    key: str
    members: List[Candidate]

    @property
    def rep(self) -> Candidate:
        return max(self.members, key=lambda c: c.pop_key())

    @property
    def ratio(self) -> float:
        return max(c.ratio for c in self.members)

    def pop_key(self) -> Tuple[float, int]:
        return self.rep.pop_key()
