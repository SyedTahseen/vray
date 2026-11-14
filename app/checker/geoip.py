import asyncio
import ipaddress
import logging
import socket

import aiohttp

from app.config import settings

log = logging.getLogger("geoip")

BATCH_URL = "http://ip-api.com/batch"
BATCH_MAX = 100
FIELDS = "status,message,query,country,countryCode,city"
DNS_CONCURRENCY = 50
DNS_TIMEOUT_SECONDS = 5


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def _resolve_host(host: str, sem: asyncio.Semaphore) -> str | None:
    host = host.strip()
    if _is_ip(host):
        return host
    try:
        async with sem:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
                ),
                timeout=DNS_TIMEOUT_SECONDS,
            )
        return infos[0][4][0] if infos else None
    except Exception as e:
        log.debug("DNS resolution failed for host=%s: %s", host, e)
        return None


async def _send_batch(session: aiohttp.ClientSession, chunk: list[tuple[int, str, str]],
                      geo_results: dict[int, dict]) -> bool:
    payload = [{"query": ip, "fields": FIELDS} for _, _, ip in chunk]
    try:
        async with session.post(
            BATCH_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 429:
                ttl = int(resp.headers.get("X-Ttl", "60") or "60")
                log.warning("ip-api rate limit hit, backing off %ds", ttl)
                await asyncio.sleep(ttl + 1)
                return False

            remaining = resp.headers.get("X-Rl")
            ttl = resp.headers.get("X-Ttl")
            for (index, host, ip), entry in zip(chunk, await resp.json()):
                if entry.get("status") == "success":
                    geo_results[index] = {
                        "country": entry.get("country", ""),
                        "country_code": entry.get("countryCode", ""),
                        "city": entry.get("city", ""),
                    }
                else:
                    log.debug("geo lookup failed for host=%s (resolved=%s): %s",
                              host, ip, entry.get("message", "unknown"))

            if remaining is not None and int(remaining) <= 1 and ttl:
                await asyncio.sleep(int(ttl) + 1)
    except Exception as e:
        log.debug("Geo batch lookup failed: %s", e)
    return True


async def geolocate_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    sem = asyncio.Semaphore(DNS_CONCURRENCY)
    ips = await asyncio.gather(*(_resolve_host(c["server"], sem) for c in candidates))
    resolvable = [
        (index, c["server"], ip)
        for index, (c, ip) in enumerate(zip(candidates, ips))
        if ip is not None
    ]

    geo_results: dict[int, dict] = {}
    if resolvable:
        chunks = [resolvable[i:i + BATCH_MAX] for i in range(0, len(resolvable), BATCH_MAX)]
        log.info("Resolving geolocation for %d candidate(s) in %d batch request(s)...",
                 len(resolvable), len(chunks))
        async with aiohttp.ClientSession() as session:
            for chunk in chunks:
                while not await _send_batch(session, chunk, geo_results):
                    pass
                await asyncio.sleep(settings.GEOIP_BATCH_DELAY_SECONDS)

    return [{**c, **geo_results.get(index, {})} for index, c in enumerate(candidates)]
