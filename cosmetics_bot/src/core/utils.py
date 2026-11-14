"""Utility functions, constants, and helper logic for text processing and query parsing."""

import re
from typing import List, Optional, Set, Tuple

# Configuration Constants
STORE_TIMEOUT = 75         # секунд на один магазин
CARDS_PER_STORE = 50       # сколько карточек из выдачи магазина разбирать
PAGE_SIZE = 3              # сколько вариантов показывать за раз
MIN_RATIO = 0.5            # ниже этой доли совпавших слов - предупреждаем пользователя
RATIO_TOLERANCE = 0.15     # допуск по релевантности между карточками
COMPARE_BY_UNIT = True     # True: сравнивать цену за 1 мл; False: просто цену
# Общая для всех магазинов: если объём не введён, брать цену за максимальный объём.
# False: брать объём, который сайт выбрал по умолчанию (только где его можно определить).
MAX_VOLUME_ONLY = True
SESSION_TTL = 3600         # сколько секунд живут кнопки выбора
RATING_PRIOR = 4.0         # средний рейтинг для сглаживания
RATING_WEIGHT = 50         # "вес" среднего рейтинга (в количестве отзывов)
# Курс евро к тенге для магазинов в евро (Cult Beauty). Обновлять вручную.
# Значение: курс НБ РК на 7.10.2026 (Informburo). Источники расходятся, проверьте актуальный.
EUR_TO_KZT = 509.99

# Synonyms and dictionary mappings
SYNONYMS: List[List[str]] = [
    ["edp", "eau de parfum", "парфюмерная вода", "парфюмированная вода", "парфюмерная"],
    ["edt", "eau de toilette", "туалетная вода", "туалетная"],
    ["edc", "eau de cologne", "одеколон", "cologne"],
    ["ysl", "yves saint laurent", "ив сен лоран", "ив сен-лоран", "сен лоран"],
    ["ck", "calvin klein", "кельвин кляйн", "кэлвин кляйн", "келвин клейн"],
    ["d&g", "dg", "dolce & gabbana", "dolce gabbana", "dolce and gabbana",
     "дольче габбана", "дольче энд габбана", "дольче и габбана"],
    ["jpg", "jean paul gaultier", "жан поль готье", "готье"],
    ["tf", "tom ford", "том форд"],
    ["mfk", "maison francis kurkdjian", "francis kurkdjian", "франсис куркджан"],
    ["pdm", "parfums de marly", "parfum de marly", "де марли", "марли"],
    ["ch", "carolina herrera", "каролина херрера"],
    ["pr", "paco rabanne", "пако рабан"],
    ["hb", "hugo boss", "хуго босс", "хьюго босс"],
    ["gucci", "гуччи"],
    ["chanel", "шанель"],
    ["dior", "christian dior", "диор"],
    ["versace", "версаче"],
    ["armani", "giorgio armani", "джорджио армани", "армани"],
    ["lancome", "lancôme", "ланком"],
    ["burberry", "барберри", "бёрберри", "берберри"],
    ["vs", "vivienne sabo", "вивьен сабо", "вивьенн сабо"],
    ["la roche posay", "lrp", "ля рош позе", "ла рош позе"],
    ["cerave", "церави", "сераве"],
    ["loreal", "l'oreal", "l oreal", "l'oreal paris", "лореаль", "лореаль париж", "лореаль париж"],
    ["maybelline", "maybelline new york", "мейбелин", "мэйбелин"],
]

CATEGORY_WORDS_RAW = """
тушь тушь для ресниц ресницы духи парфюм парфюмерия парфюмерная вода туалетная одеколон
крем кремы сыворотка маска маски гель скраб пенка тоник лосьон молочко мицеллярная вода
шампунь кондиционер бальзам масло спрей мусс мыло дезодорант антиперспирант
помада блеск тени пудра румяна тональный основа консилер праймер хайлайтер контур
подводка карандаш лак лаки набор наборы подарочный средство уход для лица тела волос рук губ глаз
edp edt edc
mascara cream serum mask gel scrub foam toner lotion shampoo conditioner balm oil spray mousse soap
deodorant lipstick gloss shadow powder blush foundation concealer primer highlighter eyeliner pencil
perfume parfum eau de toilette set kit
"""

STOP_WORDS: Set[str] = {"для", "и", "the", "for", "and", "by", "of"}
VOLUME_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:ml|мл)\b", re.I)

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^\w&]+", " ", s).strip()


def translit(s: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in s)


def phon(s: str) -> str:
    """Грубая фонетическая нормализация: 'телескопик' и 'Telescopic' дают одно и то же."""
    s = translit(s)
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = s.replace("ck", "k").replace("c", "k")
    s = s.replace("ph", "f").replace("w", "v").replace("x", "ks").replace("y", "i")
    return re.sub(r"(.)\1+", r"\1", s)


CATEGORY_WORDS: Set[str] = {norm(w) for w in CATEGORY_WORDS_RAW.split()}


def to_float(s: str) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m.group().replace(",", ".")) if m else None


def digits_int(s: str) -> Optional[int]:
    d = re.sub(r"\D", "", s or "")
    return int(d) if d else None


def format_money(n: Optional[int], currency: str = "₸") -> Optional[str]:
    if n is None:
        return None
    return f"{n:,}".replace(",", " ") + f" {currency}"


_PHRASES = sorted(
    ((norm(alt), gi) for gi, group in enumerate(SYNONYMS) for alt in group),
    key=lambda x: len(x[0]),
    reverse=True,
)


def alt_in(alt: str, hay: str) -> bool:
    if not alt:
        return False
    pat = rf"(?<!\w){re.escape(alt)}(?!\w)" if len(alt) < 4 else rf"(?<!\w){re.escape(alt)}"
    return re.search(pat, hay) is not None


def make_hay(text: str, brand: str = "") -> Tuple[str, str, str, str]:
    h = norm(text)
    return h, translit(h), phon(h), norm(brand).replace(" ", "")


def group_hit(group: List[str], hay: Tuple[str, str, str, str]) -> bool:
    h, hl, hp, bc = hay
    for a in group:
        if not a:
            continue
        if alt_in(a, h) or alt_in(a, hl):
            return True
        if len(a) >= 3 and alt_in(phon(a), hp):
            return True
        if len(a) >= 4 and bc and a.replace(" ", "") in bc:
            return True
    return False


def parse_query(query: str) -> Tuple[List[List[str]], Optional[float]]:
    """Возвращает (группы синонимов, запрошенный объём или None)."""
    q = (query or "").lower().replace("ё", "е")

    want_volume = None
    m = VOLUME_RE.search(q)
    if m:
        want_volume = float(m.group(1).replace(",", "."))
        q = VOLUME_RE.sub(" ", q)

    q = norm(q)
    groups: List[List[str]] = []
    used = set()

    for alt, gi in _PHRASES:
        if gi in used or not alt:
            continue
        pat = rf"(?<!\w){re.escape(alt)}(?!\w)"
        if re.search(pat, q):
            groups.append([norm(a) for a in SYNONYMS[gi]])
            used.add(gi)
            q = re.sub(pat, " ", q)

    for tok in q.split():
        if tok in STOP_WORDS:
            continue
        alts = []
        for a in (tok, translit(tok), phon(tok)):
            if a and a not in alts:
                alts.append(a)
        groups.append(alts)

    return groups, want_volume


def relevance(groups: List[List[str]], hay: Tuple[str, str, str, str]) -> float:
    if not groups:
        return 0.0
    return sum(1 for g in groups if group_hit(g, hay)) / len(groups)


def is_generic(group: List[str]) -> bool:
    return any(a in CATEGORY_WORDS for a in group)


def has_specifics(groups: List[List[str]], cands: List) -> bool:
    """Есть ли в запросе бренд / модель / цвет (слово не из категорий, найденное в выдаче)."""
    for g in groups:
        if is_generic(g):
            continue
        if any(group_hit(g, c.hay) for c in cands):
            return True
    return False
