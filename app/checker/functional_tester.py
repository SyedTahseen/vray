import asyncio
import json
import logging
import os
import socket
import tempfile
import time

import aiohttp
from aiohttp_socks import ProxyConnector

from app import database as db
from app.checker import parser, xray_outbound
from app.checker.tester import try_connect
from app.config import settings

log = logging.getLogger("functional_tester")

Item = tuple[int, dict]
Entry = tuple[int, str, dict, int]
ProbeResult = tuple[int | None, dict | None]

_xray_lock = asyncio.Lock()


def _free_ports(n: int) -> list[int]:
    socks = []
    try:
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            socks.append(s)
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def _make_entries(items: list[Item]) -> list[Entry]:
    ports = _free_ports(len(items))
    return [
        (key, str(i), outbound, port)
        for i, ((key, outbound), port) in enumerate(zip(items, ports))
    ]


def _build_batch_config(entries: list[Entry]) -> dict:
    inbounds, outbounds, rules = [], [], []
    for _key, suffix, outbound, port in entries:
        in_tag, out_tag = f"in-{suffix}", f"out-{suffix}"
        inbounds.append({
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "socks",
            "settings": {"udp": False, "auth": "noauth"},
            "tag": in_tag,
        })
        outbounds.append({**outbound, "tag": out_tag})
        rules.append({"type": "field", "inboundTag": [in_tag], "outboundTag": out_tag})

    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


async def _wait_for_ports(proc: asyncio.subprocess.Process, ports: list[int], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    pending = list(ports)
    while pending and time.monotonic() < deadline:
        if proc.returncode is not None:
            return False
        results = await asyncio.gather(*(try_connect("127.0.0.1", p, timeout=1) for p in pending))
        pending = [p for p, ok in zip(pending, results) if not ok]
        if pending:
            await asyncio.sleep(0.1)
    return not pending


Check = tuple[str, str, int, int]

LARGE_DOWNLOAD_BYTES = 1_000_000


def _proxy_session(port: int) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=ProxyConnector.from_url(f"socks5://127.0.0.1:{port}", rdns=True)
    )


async def _request_once(port: int, url: str | None = None, expected: int | None = None,
                        min_bytes: int = 0, timeout: float | None = None) -> int | None:
    start = time.monotonic()
    try:
        async with _proxy_session(port) as session:
            async with session.get(
                url or settings.FUNCTIONAL_TEST_URL,
                timeout=aiohttp.ClientTimeout(total=timeout or settings.FUNCTIONAL_TEST_TIMEOUT_SECONDS),
                allow_redirects=True,
            ) as resp:
                body = await resp.read()
                ok = (resp.status == (expected or settings.FUNCTIONAL_TEST_EXPECTED_STATUS)
                      and len(body) >= min_bytes)
    except Exception:
        return None
    return int((time.monotonic() - start) * 1000) if ok else None


def _clean(value) -> str:
    return str(value or "").strip()[:64]


def parse_exit_geo(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    if data.get("success") is False or data.get("status") == "fail":
        return None
    code = _clean(data.get("country_code") or data.get("countryCode")).upper()
    if len(code) != 2 or not code.isalpha():
        return None
    return {
        "country": _clean(data.get("country")),
        "country_code": code,
        "city": _clean(data.get("city")),
    }


async def _exit_geo(port: int) -> dict | None:
    try:
        async with _proxy_session(port) as session:
            async with session.get(
                settings.EXIT_GEO_URL, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                return parse_exit_geo(await resp.json(content_type=None))
    except Exception:
        return None


_download_sem: asyncio.Semaphore | None = None


def _get_download_sem() -> asyncio.Semaphore:
    global _download_sem
    if _download_sem is None:
        _download_sem = asyncio.Semaphore(settings.FUNCTIONAL_TEST_DOWNLOAD_CONCURRENCY)
    return _download_sem


async def _passes_check(port: int, check: Check) -> bool:
    _name, url, expected, min_bytes = check
    if min_bytes >= LARGE_DOWNLOAD_BYTES:
        # Big downloads need a longer timeout, and only a few may run at once so they
        # don't starve each other of bandwidth and make healthy proxies look dead.
        async with _get_download_sem():
            for _ in range(2):
                if await _request_once(port, url, expected, min_bytes,
                                       settings.FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS) is not None:
                    return True
        return False
    for _ in range(2):
        if await _request_once(port, url, expected, min_bytes) is not None:
            return True
    return False


async def _probe_one(sem: asyncio.Semaphore, key: int, port: int, want_geo: bool,
                     checks: tuple | list = ()) -> tuple[int, ProbeResult]:
    async with sem:
        attempts = max(1, settings.FUNCTIONAL_TEST_ATTEMPTS)
        need = min(max(1, settings.FUNCTIONAL_TEST_MIN_PASSES), attempts)
        latencies: list[int] = []
        for i in range(attempts):
            latency = await _request_once(port)
            if latency is not None:
                latencies.append(latency)
            if len(latencies) >= need:
                break
            if len(latencies) + (attempts - i - 1) < need:
                break
        if len(latencies) < need:
            return key, (None, None)

        best = min(latencies)
        ceiling = settings.FUNCTIONAL_TEST_MAX_LATENCY_MS
        if ceiling and best > ceiling:
            return key, (None, None)

        for check in checks:
            if not await _passes_check(port, check):
                return key, (None, None)

        geo = await _exit_geo(port) if want_geo and settings.EXIT_GEO_ENABLED else None
        return key, (best, geo)


def _configured_checks() -> list[Check]:
    if not settings.FUNCTIONAL_TEST_EXTRA_CHECKS:
        return []
    checks: list[Check] = []
    if settings.FUNCTIONAL_TEST_SECOND_URL:
        checks.append(("second-target", settings.FUNCTIONAL_TEST_SECOND_URL, 204, 0))
    if settings.FUNCTIONAL_TEST_DOWNLOAD_URL:
        checks.append(("download", settings.FUNCTIONAL_TEST_DOWNLOAD_URL, 200,
                       settings.FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES))
    return checks


async def _direct_get(url: str, timeout: float | None = None) -> tuple[int, int]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout or settings.FUNCTIONAL_TEST_TIMEOUT_SECONDS)
        ) as resp:
            return resp.status, len(await resp.read())


async def _direct_ok(url: str, expected: int, min_bytes: int) -> bool:
    timeout = settings.FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS if min_bytes >= LARGE_DOWNLOAD_BYTES else None
    try:
        status, size = await _direct_get(url, timeout)
    except Exception:
        return False
    return status == expected and size >= min_bytes


async def _usable_checks() -> list[Check]:
    usable = []
    for check in _configured_checks():
        name, url, expected, min_bytes = check
        if await _direct_ok(url, expected, min_bytes):
            usable.append(check)
        else:
            log.warning("Extra check %r (%s) fails even without a proxy - skipping it this run", name, url)
    return usable


async def _stop(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


def _read_log(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read()[-2000:].decode(errors="ignore")
    except OSError:
        return ""


async def _run_batch(items: list[Item], want_geo: bool, checks: tuple | list = ()) -> dict[int, ProbeResult]:
    entries = _make_entries(items)
    cfg_fd, cfg_path = tempfile.mkstemp(prefix="xray_batch_", suffix=".json")
    log_fd, log_path = tempfile.mkstemp(prefix="xray_batch_", suffix=".log")
    proc = None
    try:
        with os.fdopen(cfg_fd, "w") as f:
            json.dump(_build_batch_config(entries), f)

        with os.fdopen(log_fd, "wb") as log_file:
            proc = await asyncio.create_subprocess_exec(
                settings.XRAY_BIN_PATH, "run", "-c", cfg_path,
                stdout=log_file, stderr=asyncio.subprocess.STDOUT,
            )

        ports = [port for _key, _suffix, _outbound, port in entries]
        if not await _wait_for_ports(proc, ports, settings.FUNCTIONAL_TEST_STARTUP_SECONDS):
            await _stop(proc)
            output = _read_log(log_path)
            if len(items) == 1:
                log.warning(
                    "Config %d failed to start standalone in xray - marking as failed. output: %s",
                    items[0][0], output,
                )
                return {items[0][0]: (None, None)}

            log.warning(
                "Shared xray batch process failed to come up (%d configs) - bisecting to isolate "
                "the bad config(s) instead of failing the whole batch. output: %s",
                len(items), output,
            )
            mid = len(items) // 2
            results: dict[int, ProbeResult] = {}
            for half in (items[:mid], items[mid:]):
                results.update(await _run_batch(half, want_geo, checks))
            return results

        sem = asyncio.Semaphore(settings.FUNCTIONAL_TEST_CONCURRENCY)
        probed = await asyncio.gather(
            *(_probe_one(sem, key, port, want_geo, checks) for key, _suffix, _outbound, port in entries)
        )
        return dict(probed)
    finally:
        if proc is not None:
            await _stop(proc)
        for path in (cfg_path, log_path):
            try:
                os.remove(path)
            except OSError:
                pass


async def _test_all(items: list[Item], want_geo: bool = False) -> dict[int, ProbeResult]:
    chunk_size = settings.FUNCTIONAL_TEST_CHUNK_SIZE
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    log.info(
        "Running real proxy tests on %d config(s) across %d shared xray process(es) "
        "(chunk size=%d, concurrency=%d, attempts=%d)...",
        len(items), len(chunks), chunk_size, settings.FUNCTIONAL_TEST_CONCURRENCY,
        settings.FUNCTIONAL_TEST_ATTEMPTS,
    )

    results: dict[int, ProbeResult] = {}
    async with _xray_lock:
        checks = await _usable_checks()
        for chunk in chunks:
            try:
                results.update(await _run_batch(chunk, want_geo, checks))
            except Exception:
                log.exception("Functional test batch crashed; %d config(s) left untested", len(chunk))
    return results


def _xray_ready() -> bool:
    if not settings.FUNCTIONAL_TEST_ENABLED:
        return False
    if not os.path.exists(settings.XRAY_BIN_PATH):
        log.warning(
            "xray binary not found at %s - skipping functional test. "
            "Rebuild the Docker image so it gets installed.",
            settings.XRAY_BIN_PATH,
        )
        return False
    return True


async def internet_ok() -> bool:
    try:
        await _direct_get(settings.FUNCTIONAL_TEST_URL)
        return True
    except Exception as e:
        log.warning("Direct request to %s failed: %s", settings.FUNCTIONAL_TEST_URL, e)
        return False


OUTAGE_MIN_SAMPLE = 20


async def test_new_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates or not _xray_ready():
        return []

    items, unbuildable = [], []
    for index, candidate in enumerate(candidates):
        outbound = xray_outbound.build_outbound(candidate)
        if outbound is None:
            unbuildable.append(candidate)
        else:
            items.append((index, outbound))

    results = await _test_all(items, want_geo=True) if items else {}
    verified = []
    for index, (latency, geo) in results.items():
        if latency is None:
            continue
        verified.append({**candidates[index], **{k: v for k, v in (geo or {}).items() if v},
                         "latency_ms": latency})
    log.info(
        "Functional testing complete: %d/%d candidate(s) verified (%d unsupported by the "
        "outbound builder)", len(verified), len(candidates), len(unbuildable),
    )
    return verified


_sweep_lock = asyncio.Lock()


async def _recheck(targets: list, label: str) -> int:
    items, unusable = [], []
    for config_id, raw_link in targets:
        parsed = parser.parse_line(raw_link)
        outbound = xray_outbound.build_outbound(parsed) if parsed else None
        if outbound is None:
            unusable.append(config_id)
        else:
            items.append((config_id, outbound))

    results = await _test_all(items)
    passed = {key: latency for key, (latency, _geo) in results.items() if latency is not None}
    failed = [key for key, (latency, _geo) in results.items() if latency is None]

    # Safety net: if (nearly) everything failed the problem is almost certainly this
    # server's connection, not the proxies. Since failures are now deleted for good,
    # don't wipe the list in that case.
    if len(results) >= OUTAGE_MIN_SAMPLE and not passed:
        log.error(
            "%s: all %d tested proxies failed - assuming a local problem, "
            "keeping the list unchanged", label, len(results),
        )
        return 0

    if len(targets) >= OUTAGE_MIN_SAMPLE and len(unusable) > len(targets) // 2:
        log.error(
            "%s: %d of %d configs can no longer be built into an Xray outbound - assuming a "
            "tooling/version mismatch, not removing them", label, len(unusable), len(targets),
        )
        unusable = []

    await db.update_reverified(passed)
    removed = await db.delete_configs(failed + unusable)
    log.info("%s: %d passed, %d failed, %d unusable; %d removed",
             label, len(passed), len(failed), len(unusable), removed)
    return removed


async def _sweep(label: str, get_targets) -> int:
    if not _xray_ready():
        return 0
    async with _sweep_lock:
        targets = await get_targets()
        if not targets:
            log.debug("%s: no configs to check", label)
            return 0
        if not await internet_ok():
            log.warning("%s skipped: no direct internet access, results would be meaningless", label)
            return 0
        return await _recheck(targets, label)


async def reverify_verified_configs() -> int:
    return await _sweep("Reverify sweep", db.get_all_verified)
