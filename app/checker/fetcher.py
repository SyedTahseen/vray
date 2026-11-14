import logging

import aiohttp

from app import database as db
from app.checker.parser import dedupe_by_identity, identity_key, link_key, parse_bulk, parse_line
from app.config import settings

log = logging.getLogger("fetcher")


async def fetch_raw_text() -> str | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(settings.GITHUB_RAW_URL) as resp:
                if resp.status != 200:
                    log.warning("Fetch failed with status %s", resp.status)
                    return None
                return await resp.text(errors="ignore")
    except Exception as e:
        log.error("Error fetching config source: %s", e)
        return None


async def _known_identities() -> set[tuple]:
    keys = set()
    for raw_link in await db.get_verified_links():
        parsed = parse_line(raw_link)
        if parsed:
            keys.add(identity_key(parsed))
    return keys


async def fetch_new_candidates() -> list[dict]:
    text = await fetch_raw_text()
    if not text:
        return []

    parsed = parse_bulk(text)
    if not parsed:
        log.warning("No valid configs parsed from source")
        return []

    rejected = await db.get_recent_rejected(settings.REJECT_COOLDOWN_HOURS * 3600)
    fresh = [p for p in parsed if link_key(p["raw_link"]) not in rejected]

    candidates = dedupe_by_identity(fresh, await _known_identities())
    log.info(
        "Fetched %d config(s) from source: %d recently rejected, %d already verified/duplicate, "
        "%d new candidate(s)",
        len(parsed), len(parsed) - len(fresh), len(fresh) - len(candidates), len(candidates),
    )
    return candidates
