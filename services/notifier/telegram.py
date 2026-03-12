import logging

from aiogram import Bot
from aiogram.enums import ParseMode

from config import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        token = settings.telegram_bot_token
        logger.info("Creating bot with token: %s...%s (len=%d)", token[:10], token[-4:], len(token))
        _bot = Bot(token=token)
    return _bot


async def send_alert(text: str) -> int | None:
    try:
        message = await _get_bot().send_message(
            chat_id=settings.telegram_channel_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        logger.info("Alert sent to Telegram, message_id: %s", message.message_id)
        return message.message_id
    except Exception:
        logger.exception("Failed to send Telegram alert")
        return None
