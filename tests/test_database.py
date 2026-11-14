import asyncio, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "t.sqlite3")

from app import database as db
from app.checker.parser import link_key

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
    await db.record_failures([id1], max_fails=2)
    assert len(await db.get_working_configs(100)) == 2
    assert all(r[0] != rec(1)["raw_link"] for r in await db.get_longest_running(100))

    before = time.time()
    await db.update_reverified({id1: 90, id2: 80})
    top = await db.get_longest_running(100)
    since = {r[0]: r[6] for r in top}
    assert since[rec(1)["raw_link"]] >= before
    assert since[rec(2)["raw_link"]] < before
    assert top[0][0] == rec(3)["raw_link"]
    assert (await db._fetch("SELECT fail_count FROM verified_configs WHERE id=?", (id1,)))[0][0] == 0

    assert [r[0] for r in await db.get_failing()] == []
    await db.record_failures([id2], 3)
    assert [r[0] for r in await db.get_failing()] == [id2]

    await db.record_failures([id2], 3); assert await db.record_failures([id2], 3) == 1
    assert link_key(rec(2)["raw_link"]) in await db.get_recent_rejected(3600)

    await db.add_rejected(["vless://dead@9.9.9.9:443?security=tls#name-1"])
    rejected = await db.get_recent_rejected(3600)
    assert link_key("vless://dead@9.9.9.9:443?security=tls#name-2") in rejected
    assert set(await db.get_verified_links()) == {rec(1)["raw_link"], rec(3)["raw_link"]}
    print("database tests: ALL PASSED")

asyncio.run(main())
