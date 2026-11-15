import os
import time

import aiosqlite

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_link TEXT UNIQUE NOT NULL,
    protocol TEXT NOT NULL,
    country TEXT,
    country_code TEXT,
    city TEXT,
    latency_ms INTEGER NOT NULL,
    up_since REAL NOT NULL
);
"""


def _connect():
    return aiosqlite.connect(settings.DB_PATH, timeout=30)


async def _fetch(sql: str, params: tuple = ()) -> list:
    async with _connect() as db:
        cur = await db.execute(sql, params)
        return await cur.fetchall()


async def _executemany(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    async with _connect() as db:
        cur = await db.executemany(sql, rows)
        await db.commit()
        return max(cur.rowcount, 0)


async def init_db() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(settings.DB_PATH)), exist_ok=True)
    async with _connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        await db.commit()


async def get_verified_links() -> list[str]:
    return [row[0] for row in await _fetch("SELECT raw_link FROM verified_configs")]


async def add_verified_configs(records: list[dict]) -> int:
    now = time.time()
    return await _executemany(
        """
        INSERT INTO verified_configs
            (raw_link, protocol, country, country_code, city, latency_ms, up_since)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(raw_link) DO NOTHING
        """,
        [
            (r["raw_link"], r["protocol"], r.get("country") or None,
             r.get("country_code") or None, r.get("city") or None,
             r.get("latency_ms"), now)
            for r in records
        ],
    )


async def get_all_verified() -> list:
    return await _fetch("SELECT id, raw_link FROM verified_configs")


async def update_reverified(latencies: dict[int, int | None]) -> None:
    await _executemany(
        "UPDATE verified_configs SET latency_ms = ? WHERE id = ?",
        [(latency, config_id) for config_id, latency in latencies.items()],
    )


async def delete_configs(config_ids: list[int]) -> int:
    return await _executemany("DELETE FROM verified_configs WHERE id = ?", [(i,) for i in config_ids])


async def get_working_configs(limit: int) -> list:
    return await _fetch(
        "SELECT raw_link, protocol, country_code, country FROM verified_configs "
        "ORDER BY latency_ms ASC, id ASC LIMIT ?",
        (limit,),
    )


async def get_longest_running(limit: int) -> list:
    return await _fetch(
        """SELECT raw_link, protocol, country, country_code, city, latency_ms,
                  up_since
           FROM verified_configs
           ORDER BY up_since ASC, latency_ms ASC
           LIMIT ?""",
        (limit,),
    )


async def count_verified() -> int:
    return (await _fetch("SELECT COUNT(*) FROM verified_configs"))[0][0]
