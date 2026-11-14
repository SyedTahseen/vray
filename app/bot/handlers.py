import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from app import database as db
from app.config import github_sub_url, settings
from app.bot.formatting import fits_alone, fmt_duration, split_messages
from app.subscription import flag_emoji, get_links, remarked_link

log = logging.getLogger("handlers")
router = Router()

BOT_COMMANDS = [
    BotCommand(command="start", description="Get latest V2Ray configs"),
    BotCommand(command="subscription", description="Get the auto-updating subscription link"),
    BotCommand(command="top", description="Top 15 longest-running proxies"),
]

GET_VERIFIED_CB = "get_config_verified"
GET_TOP_CB = "get_top_proxies"
TOP_COUNT = 15
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
EMPTY_LIST_TEXT = (
    "No verified configs available yet — the bot is still building up "
    "the list. Please try again shortly."
)


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("Registered %d bot commands with Telegram", len(BOT_COMMANDS))


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Download Configs", callback_data=GET_VERIFIED_CB)],
            [InlineKeyboardButton(text="🏆 Top 15 Proxies", callback_data=GET_TOP_CB)],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>V2Ray Config Bot</b>\n\n"
        "I continuously pull new proxies from GitHub and only hand out ones "
        "that passed a real TCP/HTTP test through the proxy (several requests, a "
        "second site and a small download), not just a port check. The list is "
        "re-checked regularly and dead proxies are dropped. "
        "UDP is not tested.\n\n"
        "• Tap <b>Download Configs</b> for the latest verified list\n"
        "• /subscription for an auto-updating link\n"
        "• /top for the 15 longest-running proxies",
        reply_markup=_main_keyboard(),
    )


@router.callback_query(F.data == GET_VERIFIED_CB)
async def cb_get_verified_config(callback: CallbackQuery):
    await callback.answer("Fetching verified configs...")
    if not isinstance(callback.message, Message):
        return
    links = await get_links(settings.VERIFIED_FILE_LIMIT)
    if not links:
        await callback.message.answer(EMPTY_LIST_TEXT)
        return

    file = BufferedInputFile("\n".join(links).encode("utf-8"), filename="v2ray_configs_verified.txt")
    await callback.message.answer_document(
        file,
        caption=f"✅ {len(links)} config(s) that passed the TCP/HTTP proxy test.",
    )


@router.message(Command("subscription"))
async def cmd_subscription(message: Message):
    url = github_sub_url()
    if not url:
        await message.answer("Subscription link is not configured yet.")
        return
    await message.answer(
        "🔗 <b>Subscription link</b>\n\n"
        f"<code>{url}</code>\n\n"
        "Add it in your app as a <b>subscription / subscription group</b> "
        "(v2rayN, v2rayNG, Hiddify, Streisand, Shadowrocket…) and enable "
        "auto-update. It serves the servers that currently pass the checks.\n\n"
        "⚠️ The link is public: anyone who has it can use these servers."
    )


@router.message(Command("top"))
async def cmd_top(message: Message):
    rows = await db.get_longest_running(TOP_COUNT)
    if not rows:
        await message.answer(EMPTY_LIST_TEXT)
        return

    now = time.time()
    header = "🏆 <b>Top proxies by uptime</b>"
    footer = (
        "Expand a proxy and tap the config to copy it, then paste it into your app. "
        "Ranked by how long each proxy has kept passing the re-checks."
    )

    entries, oversized = [], []
    for rank, (raw, protocol, country, cc, city, latency, up_since) in enumerate(rows, start=1):
        place = ", ".join(p for p in (country, city) if p) or "Unknown location"
        link = remarked_link(raw, protocol, cc, country, prefix=f"#{rank} ")
        title = (
            f"{MEDALS.get(rank, f'{rank}.')} {flag_emoji(cc)} {html.escape(place)}\n"
            f"      ⏱ up {fmt_duration(now - up_since)} · ⚡ {latency} ms\n"
        )
        entry = f"{title}<blockquote expandable><code>{html.escape(link)}</code></blockquote>"
        if fits_alone(entry, header, footer):
            entries.append(entry)
        else:
            entries.append(f"{title}(link too long for a message - sent as a file)")
            oversized.append((rank, link))

    for chunk in split_messages(header, entries, footer):
        await message.answer(chunk, link_preview_options=LinkPreviewOptions(is_disabled=True))
    for rank, link in oversized:
        await message.answer_document(BufferedInputFile(link.encode("utf-8"), filename=f"top_{rank}.txt"))


@router.callback_query(F.data == GET_TOP_CB)
async def cb_get_top(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await cmd_top(callback.message)
