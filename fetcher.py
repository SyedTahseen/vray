import logging
import aiohttp

from config import settings
from parser import parse_bulk
import database as db

log = logging.getLogger("fetcher")


async def fetch_raw_text() -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(settings.GITHUB_RAW_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    log.warning("Fetch failed with status %s", resp.status)
                    return None
                return await resp.text()
    except Exception as e:
        log.error("Error fetching config source: %s", e)
        return None


def _dedupe_by_endpoint(parsed: list[dict], known: set[tuple[str, str, int]]) -> list[dict]:
    seen = set(known)
    out = []
    for p in parsed:
        key = (p["protocol"], p["server"], p["port"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


async def fetch_new_candidates() -> list[dict]:
    text = await fetch_raw_text()
    if not text:
        return []
    parsed = parse_bulk(text)
    if not parsed:
        log.warning("No valid configs parsed from source")
        return []

    known = await db.get_known_endpoints()
    deduped = _dedupe_by_endpoint(parsed, known)
    dupes = len(parsed) - len(deduped)
    log.info(
        "Fetched %d config(s) from source, %d already verified/duplicate, %d new candidate(s)",
        len(parsed), dupes, len(deduped),
    )
    return deduped
