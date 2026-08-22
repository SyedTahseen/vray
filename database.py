import time
import aiosqlite
from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_link TEXT UNIQUE NOT NULL,
    protocol TEXT NOT NULL,
    server TEXT NOT NULL,
    port INTEGER NOT NULL,
    remark TEXT,
    tls INTEGER NOT NULL DEFAULT 0,
    country TEXT,
    country_code TEXT,
    city TEXT,
    isp TEXT,
    latency_ms INTEGER,
    added_at REAL NOT NULL,
    last_verified REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_country ON verified_configs(country_code);
CREATE INDEX IF NOT EXISTS idx_protocol ON verified_configs(protocol);
"""


async def init_db():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.executescript(SCHEMA)
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='configs'"
        )
        if await cur.fetchone():
            cur = await db.execute("PRAGMA table_info(configs)")
            old_cols = {row[1] for row in await cur.fetchall()}
            if "real_alive" in old_cols:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO verified_configs
                        (raw_link, protocol, server, port, remark, tls,
                         country, country_code, city, isp, latency_ms,
                         added_at, last_verified)
                    SELECT raw_link, protocol, server, port, remark, tls,
                           country, country_code, city, isp, real_latency_ms,
                           added_at, COALESCE(real_last_tested, added_at)
                    FROM configs WHERE real_alive = 1
                    """
                )
            await db.execute("DROP TABLE configs")
        await db.commit()


async def get_known_endpoints() -> set[tuple[str, str, int]]:
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute("SELECT protocol, server, port FROM verified_configs")
        return {(row[0], row[1], row[2]) for row in await cur.fetchall()}


async def add_verified_configs(records: list[dict]) -> int:
    if not records:
        return 0
    now = time.time()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM verified_configs")
        before = (await cur.fetchone())[0]
        await db.executemany(
            """
            INSERT INTO verified_configs
                (raw_link, protocol, server, port, remark, tls,
                 country, country_code, city, isp, latency_ms,
                 added_at, last_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(raw_link) DO NOTHING
            """,
            [
                (r["raw_link"], r["protocol"], r["server"], r["port"],
                 r.get("remark", ""), int(r.get("tls", False)),
                 r.get("country") or None, r.get("country_code") or None,
                 r.get("city") or None, r.get("isp") or None,
                 r.get("latency_ms"), now, now)
                for r in records
            ],
        )
        await db.commit()
        cur = await db.execute("SELECT COUNT(*) FROM verified_configs")
        after = (await cur.fetchone())[0]
        return max(0, after - before)


async def get_all_verified():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute("SELECT id, raw_link FROM verified_configs")
        return await cur.fetchall()


async def update_after_reverify(config_id: int, latency_ms: int | None):
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            "UPDATE verified_configs SET latency_ms = ?, last_verified = ? WHERE id = ?",
            (latency_ms, time.time(), config_id),
        )
        await db.commit()


async def delete_configs(config_ids: list[int]) -> int:
    if not config_ids:
        return 0
    async with aiosqlite.connect(settings.DB_PATH) as db:
        placeholders = ",".join("?" for _ in config_ids)
        cur = await db.execute(
            f"DELETE FROM verified_configs WHERE id IN ({placeholders})", config_ids
        )
        await db.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


async def get_working_configs(limit: int = 500, country_code: str | None = None,
                               protocol: str | None = None):
    query = ("SELECT raw_link, protocol, server, port, country, country_code, "
              "city, latency_ms FROM verified_configs")
    clauses, params = [], []
    if country_code:
        clauses.append("country_code = ?")
        params.append(country_code.upper())
    if protocol:
        clauses.append("protocol = ?")
        params.append(protocol.lower())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY latency_ms ASC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute(query, params)
        return await cur.fetchall()


async def get_country_stats():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute(
            """SELECT country, country_code, COUNT(*) as cnt FROM verified_configs
               WHERE country_code IS NOT NULL
               GROUP BY country_code ORDER BY cnt DESC"""
        )
        return await cur.fetchall()


async def get_stats():
    async with aiosqlite.connect(settings.DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM verified_configs")
        verified = (await cur.fetchone())[0]
        cur = await db.execute("SELECT MAX(last_verified) FROM verified_configs")
        last_verified = (await cur.fetchone())[0]
        return {"verified": verified, "last_verified": last_verified}
