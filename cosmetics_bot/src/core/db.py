"""SQLite database helper for price caching, watch subscriptions, and favorites."""

import sqlite3
import os
import time
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "bot.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                url TEXT PRIMARY KEY,
                price INTEGER,
                old_price INTEGER,
                loyalty_price INTEGER,
                volume REAL,
                unit TEXT,
                updated_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                product_url TEXT,
                title TEXT,
                initial_price INTEGER,
                last_price INTEGER,
                created_at REAL,
                last_check REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                chat_id INTEGER,
                product_url TEXT,
                title TEXT,
                store TEXT,
                price INTEGER,
                PRIMARY KEY (chat_id, product_url)
            )
        """)
        # Миграция: старые базы создавались без колонок скидки и цены по карте
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(favorites)")}
        for col, typ in (("old_price", "INTEGER"), ("loyalty_price", "INTEGER"), ("volume", "REAL")):
            if col not in cols:
                conn.execute(f"ALTER TABLE favorites ADD COLUMN {col} {typ}")
        # Миграция: объём отслеживаемого товара нужен для повторной проверки цены
        wcols = {r["name"] for r in conn.execute("PRAGMA table_info(watches)")}
        if "volume" not in wcols:
            conn.execute("ALTER TABLE watches ADD COLUMN volume REAL")
        conn.commit()


def cache_get(url: str, ttl: int = 900) -> Optional[Dict[str, Any]]:
    import time
    with get_connection() as conn:
        row = conn.execute(
            "SELECT price, old_price, loyalty_price, volume, unit, updated_at FROM price_cache WHERE url = ?",
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
    import time
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO price_cache (url, price, old_price, loyalty_price, volume, unit, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                data.get("price"),
                data.get("old_price"),
                data.get("loyalty_price"),
                data.get("volume"),
                data.get("unit", ""),
                time.time()
            )
        )
        conn.commit()


def add_watch(chat_id: int, product_url: str, title: str, initial_price: int,
              volume: Optional[float] = None) -> None:
    now = time.time()
    with get_connection() as conn:
        # Один товар на чат: повторная подписка заменяет старую
        conn.execute("DELETE FROM watches WHERE chat_id = ? AND product_url = ?", (chat_id, product_url))
        conn.execute(
            """
            INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, product_url, title, initial_price, initial_price, now, now, volume)
        )
        conn.commit()


def remove_watch(watch_id: int, chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM watches WHERE id = ? AND chat_id = ?", (watch_id, chat_id))
        conn.commit()
        return cur.rowcount > 0


def get_watch_by_id(watch_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
        return dict(row) if row else None


def get_watches_for_monitor() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE last_check < ?",
                           (time.time() - 1800,)).fetchall()
        return [dict(r) for r in rows]


def get_all_watches() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches").fetchall()
        return [dict(r) for r in rows]


def update_watch_price(watch_id: int, new_price: int) -> None:
    import time
    with get_connection() as conn:
        conn.execute(
            "UPDATE watches SET last_price = ?, last_check = ? WHERE id = ?",
            (new_price, time.time(), watch_id)
        )
        conn.commit()


def add_favorite(chat_id: int, product_url: str, title: str, store: str, price: int,
                 old_price: Optional[int] = None, loyalty_price: Optional[int] = None,
                 volume: Optional[float] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO favorites "
            "(chat_id, product_url, title, store, price, old_price, loyalty_price, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, product_url, title, store, price, old_price, loyalty_price, volume)
        )
        conn.commit()


def get_favorites(chat_id: int) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rowid AS id, * FROM favorites WHERE chat_id = ? ORDER BY rowid", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_favorite(fav_id: int, chat_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT rowid AS id, * FROM favorites WHERE rowid = ? AND chat_id = ?", (fav_id, chat_id)
        ).fetchone()
        return dict(row) if row else None


def delete_favorite(fav_id: int, chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM favorites WHERE rowid = ? AND chat_id = ?", (fav_id, chat_id))
        conn.commit()
        return cur.rowcount > 0


def update_favorite_prices(fav_id: int, chat_id: int, price: int,
                           old_price: Optional[int], loyalty_price: Optional[int]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE favorites SET price = ?, old_price = ?, loyalty_price = ? WHERE rowid = ? AND chat_id = ?",
            (price, old_price, loyalty_price, fav_id, chat_id)
        )
        conn.commit()


def get_watches(chat_id: int) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE chat_id = ?", (chat_id,)).fetchall()
        return [dict(r) for r in rows]
