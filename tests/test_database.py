import asyncio, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "t.sqlite3")

from app import database as db

def rec(n, **kw):
    return {"raw_link": f"vless://u{n}@10.0.0.{n}:443?security=tls#x", "protocol": "vless",
            "server": f"10.0.0.{n}", "port": 443, "latency_ms": 100 + n,
            "country": "Germany", "country_code": "DE", "city": "Berlin", **kw}


async def main():
    await db.init_db()
    await db.add_verified_configs([rec(1), rec(2), rec(3)])
    await db._executemany("UPDATE verified_configs SET up_since = ? WHERE raw_link = ?",
                          [(1000.0, rec(3)["raw_link"])])
    ids = {r[1]: r[0] for r in await db.get_all_verified()}
    id1, id2 = ids[rec(1)["raw_link"]], ids[rec(2)["raw_link"]]

    assert len(await db.get_working_configs(100)) == 3
    assert await db.delete_configs([id1]) == 1
    assert len(await db.get_working_configs(100)) == 2
    assert all(r[0] != rec(1)["raw_link"] for r in await db.get_longest_running(100))
    assert await db.delete_configs([]) == 0

    await db.update_reverified({id2: 80})
    assert (await db._fetch("SELECT latency_ms FROM verified_configs WHERE id=?", (id2,)))[0][0] == 80
    top = await db.get_longest_running(100)
    assert top[0][0] == rec(3)["raw_link"]

    # a deleted proxy is gone for good and can be re-added by a later fetch
    assert set(await db.get_verified_links()) == {rec(2)["raw_link"], rec(3)["raw_link"]}
    await db.add_verified_configs([rec(1)])
    assert len(await db.get_working_configs(100)) == 3

    print("database tests: ALL PASSED")

asyncio.run(main())
