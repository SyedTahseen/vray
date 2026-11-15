import asyncio
import logging
import random

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import database as db
from app import publisher
from app.bot.handlers import register_commands, router
from app.checker import fetcher, functional_tester, geoip, tester
from app.config import github_publish_enabled, settings, validate_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def fetch_and_test() -> None:
    candidates = await fetcher.fetch_new_candidates()
    if not candidates:
        log.info("Cycle complete: no new candidates this round")
        return

    alive = await tester.test_candidates(candidates)

    # Failed proxies are not remembered, so the same dead ones show up every cycle.
    # Shuffle before taking a batch so they cannot starve the rest of the list.
    random.shuffle(alive)
    to_verify = await geoip.geolocate_candidates(alive[:settings.FUNCTIONAL_TEST_BATCH_SIZE])
    verified = await functional_tester.test_new_candidates(to_verify)
    added = await db.add_verified_configs(verified)

    log.info(
        "Cycle complete: %d candidate(s) -> %d TCP-alive -> %d real-tested -> "
        "%d newly verified (%d total verified)",
        len(candidates), len(alive), len(to_verify), added, await db.count_verified(),
    )


async def reverify() -> None:
    removed = await functional_tester.reverify_verified_configs()
    log.info(
        "Reverify sweep complete: %d dead proxy(s) removed, %d still verified",
        removed, await db.count_verified(),
    )


async def run_periodically(name: str, job, interval_seconds: float, initial_delay: float = 0,
                           allow_empty_publish: bool = False) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            log.info("=== Starting %s ===", name)
            await job()
            await publisher.publish_subscription(allow_empty=allow_empty_publish)
        except Exception:
            log.exception("Error during %s", name)
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    if not settings.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    problems = validate_settings()
    if problems:
        raise SystemExit("Invalid configuration:\n  - " + "\n  - ".join(problems))

    await db.init_db()
    log.info(
        "Test settings: probes need %d/%d passes, max latency %d ms, extra checks=%s, "
        "download >=%d bytes within %gs (max %d at once), reverify every %gh, fetch every %d min",
        settings.FUNCTIONAL_TEST_MIN_PASSES, settings.FUNCTIONAL_TEST_ATTEMPTS,
        settings.FUNCTIONAL_TEST_MAX_LATENCY_MS, settings.FUNCTIONAL_TEST_EXTRA_CHECKS,
        settings.FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES, settings.FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS,
        settings.FUNCTIONAL_TEST_DOWNLOAD_CONCURRENCY, settings.REVERIFY_INTERVAL_HOURS,
        settings.FETCH_INTERVAL_MINUTES,
    )
    if "example/example-repo" in settings.GITHUB_RAW_URL:
        log.error(
            "GITHUB_RAW_URL is still the placeholder from the defaults - no proxies can be fetched. "
            "Set it to the raw URL of the proxy list you want to test."
        )
    if not github_publish_enabled():
        log.warning("GITHUB_REPO / GITHUB_TOKEN not set: the subscription file will NOT be published")

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await register_commands(bot)

    reverify_seconds = settings.REVERIFY_INTERVAL_HOURS * 3600
    tasks = [
        asyncio.create_task(publisher.publish_subscription()),
        asyncio.create_task(
            run_periodically("fetch/test cycle", fetch_and_test, settings.FETCH_INTERVAL_MINUTES * 60)
        ),
        asyncio.create_task(
            run_periodically(
                f"{settings.REVERIFY_INTERVAL_HOURS:g}-hour verified-list reverify sweep",
                reverify, reverify_seconds, initial_delay=reverify_seconds,
                allow_empty_publish=True,
            )
        ),
    ]

    log.info("Bot starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()


def run() -> None:
    asyncio.run(main())
