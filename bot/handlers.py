import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)

from config import settings
import database as db
from parser import apply_remark

log = logging.getLogger("handlers")
router = Router()

BOT_COMMANDS = [
    BotCommand(command="start", description="Get latest V2Ray configs"),
]


async def register_commands(bot):
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("Registered %d bot commands with Telegram", len(BOT_COMMANDS))


PROTO_LABEL = {
    "ss": "ss",
    "vmess": "vmess",
    "vless": "vless",
    "trojan": "tr",
}

GET_VERIFIED_CB = "get_config_verified"


def flag_emoji(country_code: str) -> str:
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(ord(c.upper()) - ord("A") + 0x1F1E6) for c in country_code)


def build_remark(protocol: str, country_code: str | None, verified: bool = False) -> str:
    flag = flag_emoji(country_code) if country_code else "🏳️"
    label = PROTO_LABEL.get(protocol, protocol.upper())
    code = country_code.upper() if country_code else "??"
    return f"{flag} {label}-{code} 🔒"


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Download Configs", callback_data=GET_VERIFIED_CB)],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>V2Ray Config Bot</b>\n\n"
        "I continuously pull new proxies from GitHub and only hand out ones "
        "that passed a full end-to-end connection test through a real proxy "
        "session (not just a port check). The verified list keeps growing "
        "as new working proxies are found, and is re-checked every 12 "
        "hours to drop anything that's stopped working.\n\n"
        "Tap the button below to get the latest verified configs.",
        parse_mode="HTML",
        reply_markup=_main_keyboard(),
    )


async def _build_config_file() -> tuple[str, int] | None:
    rows = await db.get_working_configs(limit=settings.VERIFIED_FILE_LIMIT)
    if not rows:
        return None
    lines = []
    for (raw_link, protocol, server, port, country, country_code, city, latency_ms) in rows:
        remark = build_remark(protocol, country_code, verified=True)
        lines.append(apply_remark(raw_link, protocol, remark))
    return "\n".join(lines), len(lines)


@router.callback_query(lambda c: c.data == GET_VERIFIED_CB)
async def cb_get_verified_config(callback: CallbackQuery):
    await callback.answer("Fetching verified configs...")
    result = await _build_config_file()
    if not result:
        await callback.message.answer(
            "No verified configs available yet — the bot is still building up "
            "the list. Please try again shortly."
        )
        return

    file_text, count = result
    file = BufferedInputFile(file_text.encode("utf-8"), filename="v2ray_configs_verified.txt")
    await callback.message.answer_document(
        file,
        caption=f"✅ {count} verified config(s) that passed a full end-to-end connection test.",
    )
