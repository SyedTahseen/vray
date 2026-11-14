import os
import time

import aiosqlite

from app.checker.parser import link_key
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
    fail_count INTEGER NOT NULL DEFAULT 0,
    up_since REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_links (
    raw_link TEXT PRIMARY KEY,
    rejected_at REAL NOT NULL
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


_REJECT_SQL = (
    "INSERT INTO rejected_links (raw_link, rejected_at) VALUES (?, ?) "
    "ON CONFLICT(raw_link) DO UPDATE SET rejected_at = excluded.rejected_at"
)


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


async def get_failing() -> list:
    return await _fetch("SELECT id, raw_link FROM verified_configs WHERE fail_count > 0")


async def update_reverified(latencies: dict[int, int | None]) -> None:
    now = time.time()
    await _executemany(
        "UPDATE verified_configs SET latency_ms = ?, "
        "up_since = CASE WHEN fail_count > 0 THEN ? ELSE up_since END, "
        "fail_count = 0 WHERE id = ?",
        [(latency, now, config_id) for config_id, latency in latencies.items()],
    )


async def record_failures(config_ids: list[int], max_fails: int) -> int:
    if not config_ids:
        return 0
    async with _connect() as db:
        await db.executemany(
            "UPDATE verified_configs SET fail_count = fail_count + 1 WHERE id = ?",
            [(i,) for i in config_ids],
        )
        dead = await (await db.execute(
            "SELECT raw_link FROM verified_configs WHERE fail_count >= ?", (max_fails,))).fetchall()
        now = time.time()
        await db.executemany(_REJECT_SQL, [(link_key(row[0]), now) for row in dead])
        cur = await db.execute("DELETE FROM verified_configs WHERE fail_count >= ?", (max_fails,))
        removed = max(cur.rowcount, 0)
        await db.commit()
        return removed


async def add_rejected(raw_links: list[str]) -> None:
    now = time.time()
    await _executemany(_REJECT_SQL, [(link_key(link), now) for link in raw_links])


async def get_recent_rejected(cooldown_seconds: float) -> set[str]:
    cutoff = time.time() - cooldown_seconds
    async with _connect() as db:
        await db.execute("DELETE FROM rejected_links WHERE rejected_at < ?", (cutoff,))
        await db.commit()
        cur = await db.execute("SELECT raw_link FROM rejected_links")
        return {row[0] for row in await cur.fetchall()}


async def get_working_configs(limit: int) -> list:
    return await _fetch(
        "SELECT raw_link, protocol, country_code, country FROM verified_configs "
        "WHERE fail_count = 0 "
        "ORDER BY latency_ms ASC, id ASC LIMIT ?",
        (limit,),
    )


async def get_longest_running(limit: int) -> list:
    return await _fetch(
        """SELECT raw_link, protocol, country, country_code, city, latency_ms,
                  up_since
           FROM verified_configs
           WHERE fail_count = 0
           ORDER BY up_since ASC, latency_ms ASC
           LIMIT ?""",
        (limit,),
    )


async def count_verified() -> int:
    return (await _fetch("SELECT COUNT(*) FROM verified_configs"))[0][0]
