"""Postgres (Supabase) helper for price caching, watch subscriptions, and favorites.

Подключение задаётся переменной окружения DATABASE_URL (строка подключения Postgres из Supabase).
Пароль в код и в git не попадает.
"""

import os
import time
from typing import Optional, List, Dict, Any

import psycopg
from psycopg.rows import dict_row


def get_connection() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Не задана переменная окружения DATABASE_URL (строка подключения Supabase)")
    # with conn: в конце транзакции делает commit (или rollback при ошибке) и закрывает соединение
    return psycopg.connect(url, row_factory=dict_row)


def init_db() -> None:
    """Таблицы создаются миграцией в Supabase (см. JOURNAL.md, запись 007). Здесь только проверка подключения."""
    with get_connection() as conn:
        conn.execute("SELECT 1")


def cache_get(url: str, ttl: int = 900) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT price, old_price, loyalty_price, volume, unit, updated_at FROM price_cache WHERE url = %s",
            (url,)
        ).fetchone()
        if not row:
            return None
        if time.time() - row["updated_at"] > ttl:
            return None
        return {
            "price": row["price"],
            "old_price": row["old_price"],
            "loyalty_price": row["loyalty_price"],
            "volume": row["volume"],
            "unit": row["unit"] or "",
        }


def cache_set(url: str, data: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO price_cache (url, price, old_price, loyalty_price, volume, unit, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                price = EXCLUDED.price,
                old_price = EXCLUDED.old_price,
                loyalty_price = EXCLUDED.loyalty_price,
                volume = EXCLUDED.volume,
                unit = EXCLUDED.unit,
                updated_at = EXCLUDED.updated_at
            """,
            (
                url,
                data.get("price"),
                data.get("old_price"),
                data.get("loyalty_price"),
                data.get("volume"),
                data.get("unit", ""),
                time.time(),
            )
        )


def add_watch(chat_id: int, product_url: str, title: str, initial_price: int) -> None:
    now = time.time()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (chat_id, product_url, title, initial_price, initial_price, now, now)
        )


def get_watch_by_id(watch_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM watches WHERE id = %s", (watch_id,)).fetchone()
        return dict(row) if row else None


def get_watches_for_monitor() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE last_check < %s",
                            (time.time() - 1800,)).fetchall()
        return [dict(r) for r in rows]


def get_all_watches() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches").fetchall()
        return [dict(r) for r in rows]


def update_watch_price(watch_id: int, new_price: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE watches SET last_price = %s, last_check = %s WHERE id = %s",
            (new_price, time.time(), watch_id)
        )


def add_favorite(chat_id: int, product_url: str, title: str, store: str, price: int,
                 old_price: Optional[int] = None, loyalty_price: Optional[int] = None,
                 volume: Optional[float] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO favorites (chat_id, product_url, title, store, price, old_price, loyalty_price, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id, product_url) DO UPDATE SET
                title = EXCLUDED.title,
                store = EXCLUDED.store,
                price = EXCLUDED.price,
                old_price = EXCLUDED.old_price,
                loyalty_price = EXCLUDED.loyalty_price,
                volume = EXCLUDED.volume
            """,
            (chat_id, product_url, title, store, price, old_price, loyalty_price, volume)
        )


def get_favorites(chat_id: int) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, chat_id, product_url, title, store, price, old_price, loyalty_price, volume "
            "FROM favorites WHERE chat_id = %s ORDER BY id", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_favorite(fav_id: int, chat_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, chat_id, product_url, title, store, price, old_price, loyalty_price, volume "
            "FROM favorites WHERE id = %s AND chat_id = %s", (fav_id, chat_id)
        ).fetchone()
        return dict(row) if row else None


def delete_favorite(fav_id: int, chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM favorites WHERE id = %s AND chat_id = %s", (fav_id, chat_id))
        return cur.rowcount > 0


def update_favorite_prices(fav_id: int, chat_id: int, price: int,
                           old_price: Optional[int], loyalty_price: Optional[int]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE favorites SET price = %s, old_price = %s, loyalty_price = %s WHERE id = %s AND chat_id = %s",
            (price, old_price, loyalty_price, fav_id, chat_id)
        )


def get_watches(chat_id: int) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE chat_id = %s", (chat_id,)).fetchall()
        return [dict(r) for r in rows]
