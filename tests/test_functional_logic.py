import asyncio, os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for name in ("aiohttp", "aiohttp_socks", "aiosqlite"):
    if name not in sys.modules:
        try: __import__(name)
        except ImportError: sys.modules[name] = types.SimpleNamespace(ClientSession=None, ClientTimeout=None, ProxyConnector=None)
from app.checker import functional_tester as ft
from app.config import settings

g = ft.parse_exit_geo({"success": True, "country": "Germany", "country_code": "de", "city": "Berlin"})
assert g == {"country": "Germany", "country_code": "DE", "city": "Berlin"}, g
g = ft.parse_exit_geo({"status": "success", "country": "France", "countryCode": "FR", "city": "Paris"})
assert g["country_code"] == "FR" and g["city"] == "Paris"
assert ft.parse_exit_geo({"success": False, "message": "rate limited"}) is None
assert ft.parse_exit_geo({"status": "fail"}) is None
assert ft.parse_exit_geo({"country_code": "ZZZ"}) is None
assert ft.parse_exit_geo(["not", "a", "dict"]) is None

calls = []
def script(results):
    it = iter(results)
    async def fake(port, url=None, expected=None, min_bytes=0):
        calls.append(url); return next(it)
    return fake
GEO = {"country": "Germany", "country_code": "DE", "city": ""}
async def fake_geo(port): return GEO
ft._exit_geo = fake_geo

async def probe(results, want_geo=False, checks=()):
    calls.clear(); ft._request_once = script(results)
    return await ft._probe_one(asyncio.Semaphore(1), 7, 1234, want_geo, checks)

assert (settings.FUNCTIONAL_TEST_ATTEMPTS, settings.FUNCTIONAL_TEST_MIN_PASSES) == (3, 2)
assert settings.FUNCTIONAL_TEST_MAX_LATENCY_MS == 1000
assert asyncio.run(probe([250, 90], True)) == (7, (90, GEO)) and len(calls) == 2
assert asyncio.run(probe([None, 120, 140])) == (7, (120, None)) and len(calls) == 3
assert asyncio.run(probe([None, 120, None])) == (7, (None, None))
assert asyncio.run(probe([None, None])) == (7, (None, None)) and len(calls) == 2
assert asyncio.run(probe([1500, 2000])) == (7, (None, None))
assert asyncio.run(probe([900, 2000])) == (7, (900, None))

CHECKS = [("second-target", "https://b/204", 204, 0), ("download", "https://b/dl", 200, 500000)]
assert asyncio.run(probe([100, 100, 1, 1], True, CHECKS)) == (7, (100, GEO))
assert asyncio.run(probe([100, 100, None, 1, 1], False, CHECKS)) == (7, (100, None))
assert asyncio.run(probe([100, 100, 1, None, None], True, CHECKS)) == (7, (None, None))
assert calls[-1] == "https://b/dl"

async def _chk(total, passed, internet):
    async def fake(): return internet
    ft.internet_ok = fake
    return await ft.should_cache_rejections(total, passed)
assert asyncio.run(_chk(5, 0, False)) is True
assert asyncio.run(_chk(50, 3, False)) is True
assert asyncio.run(_chk(50, 0, True)) is True
assert asyncio.run(_chk(50, 0, False)) is False
print("outage guard tests: ALL PASSED")
