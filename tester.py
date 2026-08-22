import asyncio
import logging
import ssl
import time

from config import settings

log = logging.getLogger("tester")

ATTEMPTS_PER_CANDIDATE = 2

_TLS_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE


async def _try_connect(host: str, port: int, use_tls: bool) -> bool:
    try:
        if use_tls:
            conn = asyncio.open_connection(host, port, ssl=_TLS_CTX, server_hostname=host)
        else:
            conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=settings.TCP_TIMEOUT_SECONDS)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _test_one(sem: asyncio.Semaphore, index: int, host: str, port: int, use_tls: bool):
    async with sem:
        start = time.monotonic()
        success = False
        for _attempt in range(ATTEMPTS_PER_CANDIDATE):
            success = await _try_connect(host, port, use_tls)
            if success:
                break
        latency_ms = int((time.monotonic() - start) * 1000) if success else None
        return index, success, latency_ms


async def test_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    sem = asyncio.Semaphore(settings.TEST_CONCURRENCY)
    tasks = [
        _test_one(sem, i, c["server"], c["port"], bool(c.get("tls")))
        for i, c in enumerate(candidates)
    ]
    log.info("TCP-testing %d new candidate(s) (concurrency=%d)...", len(tasks), settings.TEST_CONCURRENCY)
    results = await asyncio.gather(*tasks)

    alive = []
    for index, success, latency_ms in results:
        if success:
            c = dict(candidates[index])
            c["tcp_latency_ms"] = latency_ms
            alive.append(c)
    log.info("TCP test complete: %d/%d candidate(s) reachable", len(alive), len(candidates))
    return alive
