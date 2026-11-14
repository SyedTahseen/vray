import asyncio
import base64
import logging
import time

import aiohttp

from app.config import github_publish_enabled, github_sub_url, settings
from app.subscription import get_links

log = logging.getLogger("publisher")

API_URL = "https://api.github.com"

_lock = asyncio.Lock()
_last_commit: float | None = None


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "v2ray-verified-bot",
    }


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def links_from_api_content(content: str) -> set[str] | None:
    try:
        outer = base64.b64decode(content or "").decode("utf-8", "ignore").strip()
        inner = base64.b64decode(outer).decode("utf-8", "ignore")
    except Exception:
        return None
    return {line.strip() for line in inner.splitlines() if line.strip()}


def _log_put_failure(status: int, text: str) -> None:
    if status in (401, 403):
        log.error("GitHub token rejected (HTTP %s). It needs Contents read/write on %s. %s",
                  status, settings.GITHUB_REPO, text)
    elif status == 404:
        log.error("GitHub repo/branch not found: %s (%s). Check GITHUB_REPO and GITHUB_BRANCH, "
                  "and that the token can access it.", settings.GITHUB_REPO, settings.GITHUB_BRANCH)
    else:
        log.error("GitHub publish failed: HTTP %s %s", status, text)


async def publish_subscription(allow_empty: bool = False) -> None:
    if not github_publish_enabled():
        return
    async with _lock:
        try:
            links = await get_links(settings.VERIFIED_FILE_LIMIT)
            if not links and not allow_empty:
                log.info("GitHub publish skipped: no verified configs yet")
                return
            await _put_file(links)
        except Exception:
            log.exception("GitHub publish failed")


async def _put_file(links: list[str]) -> None:
    global _last_commit
    path = settings.GITHUB_SUB_PATH.lstrip("/")
    url = f"{API_URL}/repos/{settings.GITHUB_REPO}/contents/{path}"
    timeout = aiohttp.ClientTimeout(total=30)
    body = _b64("\n".join(links))
    wanted = set(links)

    async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as session:
        for attempt in (1, 2):
            sha = None
            async with session.get(url, params={"ref": settings.GITHUB_BRANCH}) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    sha = info.get("sha")
                    if links_from_api_content(info.get("content", "")) == wanted:
                        log.info("GitHub publish: same set of links, nothing to commit")
                        return
                elif resp.status == 404:
                    if not links:
                        return
                else:
                    log.error("GitHub read failed: HTTP %s %s", resp.status, (await resp.text())[:300])
                    return

            min_gap = settings.PUBLISH_MIN_INTERVAL_MINUTES * 60
            if _last_commit is not None and time.monotonic() - _last_commit < min_gap:
                log.info("GitHub publish deferred: last commit was under %d minute(s) ago",
                         settings.PUBLISH_MIN_INTERVAL_MINUTES)
                return

            payload = {
                "message": "Update verified subscription",
                "content": _b64(body),
                "branch": settings.GITHUB_BRANCH,
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, json=payload) as resp:
                if resp.status in (200, 201):
                    _last_commit = time.monotonic()
                    log.info("GitHub publish: updated %s (%d links, %d bytes)",
                             github_sub_url(), len(links), len(body))
                    return
                text = (await resp.text())[:300]
                if resp.status in (409, 422) and attempt == 1:
                    log.warning("GitHub publish conflict (HTTP %s), retrying once", resp.status)
                    continue
                _log_put_failure(resp.status, text)
                return
