import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
import database as db
import fetcher
import tester
import geoip
import functional_tester
from bot.handlers import router, register_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def background_cycle():
    while True:
        try:
            log.info("=== Starting fetch/test cycle ===")

            candidates = await fetcher.fetch_new_candidates()
            if not candidates:
                log.info("Cycle complete: no new candidates this round")
            else:
                alive = await tester.test_candidates(candidates)
                geolocated = await geoip.geolocate_candidates(alive)

                to_verify = geolocated[:settings.FUNCTIONAL_TEST_BATCH_SIZE]

                verified = await functional_tester.test_new_candidates(to_verify)
                added = await db.add_verified_configs(verified)

                stats = await db.get_stats()
                log.info(
                    "Cycle complete: %d candidate(s) -> %d TCP-alive -> %d real-tested -> "
                    "%d newly verified (%d total verified)",
                    len(candidates), len(alive), len(to_verify), added, stats["verified"],
                )
        except Exception:
            log.exception("Error during background cycle")

        await asyncio.sleep(settings.FETCH_INTERVAL_MINUTES * 60)


async def reverify_cycle():
    while True:
        await asyncio.sleep(settings.REVERIFY_INTERVAL_HOURS * 3600)
        try:
            log.info("=== Starting %.0f-hour verified-list reverify sweep ===", settings.REVERIFY_INTERVAL_HOURS)
            removed = await functional_tester.reverify_verified_configs()
            stats = await db.get_stats()
            log.info(
                "Reverify sweep complete: %d dead proxy(s) removed, %d still verified",
                removed, stats["verified"],
            )
        except Exception:
            log.exception("Error during reverify cycle")


async def main():
    if not settings.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    await db.init_db()

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await register_commands(bot)

    asyncio.create_task(background_cycle())
    asyncio.create_task(reverify_cycle())

    log.info("Bot starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
