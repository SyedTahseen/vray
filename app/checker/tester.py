import asyncio
import logging
import ssl

from app.config import settings

log = logging.getLogger("tester")

ATTEMPTS_PER_CANDIDATE = 2

_TLS_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE


async def try_connect(host: str, port: int, timeout: float, use_tls: bool = False,
                      server_name: str | None = None) -> bool:
    try:
        connection = asyncio.open_connection(
            host,
            port,
            ssl=_TLS_CTX if use_tls else None,
            server_hostname=(server_name or host) if use_tls else None,
        )
        _, writer = await asyncio.wait_for(connection, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _is_reachable(sem: asyncio.Semaphore, host: str, port: int, use_tls: bool,
                        server_name: str | None) -> bool:
    async with sem:
        for _ in range(ATTEMPTS_PER_CANDIDATE):
            if await try_connect(host, port, settings.TCP_TIMEOUT_SECONDS, use_tls, server_name):
                return True
        return False


async def test_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    sem = asyncio.Semaphore(settings.TEST_CONCURRENCY)
    log.info("TCP-testing %d new candidate(s) (concurrency=%d)...", len(candidates), settings.TEST_CONCURRENCY)
    reachable = await asyncio.gather(
        *(_is_reachable(sem, c["server"], c["port"], bool(c.get("tls")), c.get("sni"))
          for c in candidates)
    )

    alive = [c for c, ok in zip(candidates, reachable) if ok]
    log.info("TCP test complete: %d/%d candidate(s) reachable", len(alive), len(candidates))
    return alive
