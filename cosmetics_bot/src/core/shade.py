"""Код оттенка: разбор запроса («помада 205», «помада #b22222») и выделение кодов из текста карточки.

Поддерживаются:
- номер: «205», «001», «M02» (1–4 цифры, возможна одна буква в начале или в конце);
- HEX: «#b22222» (только с решёткой, иначе шестизначные числа путаются с номерами).
Название оттенка («Ruby Woo») в этом модуле не выделяется: оно ищется обычными словами запроса.
"""

import re
from typing import List, Optional, Tuple

from cosmetics_bot.src.core.utils import norm

# Номер оттенка: 1–4 цифры, допускается одна буква в начале (M02) или в конце (16a)
CODE_RE = re.compile(r"(?:[a-zа-я]{1,2})?\d{1,4}[a-zа-я]?")
HEX_RE = re.compile(r"#([0-9a-f]{6})\b")
# Объём в тексте карточки («3,5 г», «30 мл»): его цифры не являются кодом
VOLUME_IN_TEXT_RE = re.compile(r"\d+(?:[.,]\s?\d+)?\s*(?:г|мл|g|ml)\b", re.I)
_UNIT_WORDS = {"мл", "ml", "г", "g"}


def _normalize_code(tok: str) -> str:
    """«001» и «1» — один и тот же номер; буквы в коде не трогаем."""
    if tok.isdigit():
        return str(int(tok))
    return tok


def split_shade(query: str) -> Tuple[List[str], str]:
    """Вытаскивает коды оттенка из запроса. Возвращает (коды, остаток запроса).

    «помада 205 30 мл» → (['205'], 'помада 30 мл').
    Объём «30 мл» не считается кодом: число, за которым идёт «мл»/«ml», остаётся в запросе.
    """
    q = (query or "").lower().replace("ё", "е")
    codes: List[str] = []
    rest: List[str] = []
    tokens = q.split()
    for i, raw in enumerate(tokens):
        hm = HEX_RE.fullmatch(raw.strip(",.;:!?()\"'"))
        if hm:
            codes.append("#" + hm.group(1))
            continue
        tok = norm(raw)
        nxt = norm(tokens[i + 1]) if i + 1 < len(tokens) else ""
        if tok and CODE_RE.fullmatch(tok) and nxt not in _UNIT_WORDS:
            codes.append(_normalize_code(tok))
            continue
        rest.append(raw)
    return codes, " ".join(rest)


def codes_in(text: str) -> Tuple[str, ...]:
    """Все коды оттенка, найденные в тексте (названии карточки, подписи, варианте на странице)."""
    t = VOLUME_IN_TEXT_RE.sub(" ", (text or "").lower().replace("ё", "е"))
    found = {"#" + m.group(1) for m in HEX_RE.finditer(t)}
    for tok in norm(HEX_RE.sub(" ", t)).split():
        if CODE_RE.fullmatch(tok):
            found.add(_normalize_code(tok))
    return tuple(sorted(found))


def matches_shade(codes: Optional[Tuple[str, ...]], wanted: List[str]) -> bool:
    """Есть ли у товара все запрошенные коды. None (код неизвестен) — не совпадает."""
    if not codes:
        return False
    return all(w in codes for w in wanted)
