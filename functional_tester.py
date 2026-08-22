import asyncio
import json
import logging
import os
import socket
import tempfile
import time

import aiohttp
from aiohttp_socks import ProxyConnector

from config import settings
import database as db
import parser
import xray_outbound

log = logging.getLogger("functional_tester")


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


def _build_batch_config(entries: list[tuple[int, str, dict, int]]) -> dict:
    inbounds, outbounds, rules = [], [], []
    for _config_id, suffix, outbound, port in entries:
        in_tag, out_tag = f"in-{suffix}", f"out-{suffix}"
        inbounds.append({
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "socks",
            "settings": {"udp": False, "auth": "noauth"},
            "tag": in_tag,
        })
        outbound = dict(outbound)
        outbound["tag"] = out_tag
        outbounds.append(outbound)
        rules.append({"type": "field", "inboundTag": [in_tag], "outboundTag": out_tag})

    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


async def _wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except OSError:
            await asyncio.sleep(0.1)
    return False


async def _probe_one(sem: asyncio.Semaphore, config_id: int, port: int) -> tuple[int, bool, int | None]:
    async with sem:
        connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{port}")
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    settings.FUNCTIONAL_TEST_URL,
                    timeout=aiohttp.ClientTimeout(total=settings.FUNCTIONAL_TEST_TIMEOUT_SECONDS),
                    allow_redirects=True,
                ) as resp:
                    ok = resp.status < 500
                    await resp.read()
        except Exception:
            return config_id, False, None
        return config_id, ok, (int((time.monotonic() - start) * 1000) if ok else None)


async def _collect_output(proc: asyncio.subprocess.Process) -> str:
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    stdout, stderr = b"", b""
    try:
        stdout = (await proc.stdout.read()) or b""
    except Exception:
        pass
    try:
        stderr = (await proc.stderr.read()) or b""
    except Exception:
        pass
    return (stdout + stderr).decode(errors="ignore")[:2000]


async def _run_batch(entries: list[tuple[int, str, dict, int]], on_result):
    xray_config = _build_batch_config(entries)
    fd, path = tempfile.mkstemp(prefix="xray_batch_", suffix=".json")
    proc = None
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(xray_config, f)

        proc = await asyncio.create_subprocess_exec(
            settings.XRAY_BIN_PATH, "run", "-c", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        first_port = entries[0][3]
        ready = await _wait_for_port(first_port, settings.FUNCTIONAL_TEST_STARTUP_SECONDS)
        if not ready:
            output = await _collect_output(proc)

            if len(entries) == 1:
                config_id = entries[0][0]
                log.warning(
                    "Config %d failed to start standalone in xray — marking "
                    "as failed test. output: %s", config_id, output,
                )
                await on_result(config_id, False, None)
                return

            log.warning(
                "Shared xray batch process failed to come up (%d configs) — "
                "bisecting to isolate the bad config(s) instead of failing "
                "the whole batch. output: %s",
                len(entries), output,
            )
            mid = len(entries) // 2
            for half in (entries[:mid], entries[mid:]):
                new_ports = _free_ports(len(half))
                rebuilt = [
                    (config_id, suffix, outbound, new_port)
                    for (config_id, suffix, outbound, _old_port), new_port in zip(half, new_ports)
                ]
                await _run_batch(rebuilt, on_result=on_result)
            return

        sem = asyncio.Semaphore(settings.FUNCTIONAL_TEST_CONCURRENCY)
        results = await asyncio.gather(
            *(_probe_one(sem, config_id, port) for config_id, _suffix, _ob, port in entries)
        )
        for config_id, ok, latency_ms in results:
            await on_result(config_id, ok, latency_ms)
    finally:
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
        try:
            os.remove(path)
        except OSError:
            pass


def _xray_ready() -> bool:
    if not settings.FUNCTIONAL_TEST_ENABLED:
        return False
    if not os.path.exists(settings.XRAY_BIN_PATH):
        log.warning(
            "xray binary not found at %s — skipping functional test. "
            "Rebuild the Docker image so it gets installed.",
            settings.XRAY_BIN_PATH,
        )
        return False
    return True


async def test_new_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates or not _xray_ready():
        return []

    buildable = []
    for i, c in enumerate(candidates):
        outbound = xray_outbound.build_outbound(c)
        if outbound is not None:
            buildable.append((i, outbound))

    if not buildable:
        return []

    passed: dict[int, int | None] = {}

    async def _on_result(index: int, ok: bool, latency_ms: int | None):
        if ok:
            passed[index] = latency_ms

    chunk_size = settings.FUNCTIONAL_TEST_CHUNK_SIZE
    chunks = [buildable[i:i + chunk_size] for i in range(0, len(buildable), chunk_size)]
    log.info(
        "Running real proxy tests on %d new candidate(s) across %d shared xray process(es) "
        "(chunk size=%d, concurrency=%d)...",
        len(buildable), len(chunks), chunk_size, settings.FUNCTIONAL_TEST_CONCURRENCY,
    )

    for chunk in chunks:
        ports = _free_ports(len(chunk))
        entries = [
            (index, str(i), outbound, port)
            for i, ((index, outbound), port) in enumerate(zip(chunk, ports))
        ]
        try:
            await _run_batch(entries, on_result=_on_result)
        except Exception as e:
            log.debug("Functional test batch crashed: %s", e)

    log.info("Functional testing complete: %d/%d candidate(s) verified", len(passed), len(candidates))
    return [
        {**candidates[index], "latency_ms": latency_ms}
        for index, latency_ms in passed.items()
    ]


async def reverify_verified_configs() -> int:
    if not _xray_ready():
        return 0

    targets = await db.get_all_verified()
    if not targets:
        log.info("Reverify sweep: no verified configs to check")
        return 0

    removed_ids: list[int] = []
    passed: dict[int, int | None] = {}

    async def _on_result(config_id: int, ok: bool, latency_ms: int | None):
        if ok:
            passed[config_id] = latency_ms
        else:
            removed_ids.append(config_id)

    buildable = []
    for config_id, raw_link in targets:
        parsed = parser.parse_line(raw_link)
        outbound = xray_outbound.build_outbound(parsed) if parsed else None
        if outbound is None:
            removed_ids.append(config_id)
        else:
            buildable.append((config_id, outbound))

    chunk_size = settings.FUNCTIONAL_TEST_CHUNK_SIZE
    chunks = [buildable[i:i + chunk_size] for i in range(0, len(buildable), chunk_size)]
    log.info(
        "Reverifying %d verified config(s) across %d shared xray process(es)...",
        len(buildable), len(chunks),
    )

    for chunk in chunks:
        ports = _free_ports(len(chunk))
        entries = [
            (config_id, str(i), outbound, port)
            for i, ((config_id, outbound), port) in enumerate(zip(chunk, ports))
        ]
        try:
            await _run_batch(entries, on_result=_on_result)
        except Exception as e:
            log.debug("Reverify batch crashed: %s", e)
            for config_id, *_ in entries:
                removed_ids.append(config_id)

    for config_id, latency_ms in passed.items():
        await db.update_after_reverify(config_id, latency_ms)

    removed_count = await db.delete_configs(removed_ids)
    log.info("Reverify sweep: removed %d dead proxy(s), %d still verified", removed_count, len(passed))
    return removed_count
