import logging
import sys
import os

# Allow sibling imports when running from bot/ directory
sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update
from telegram.error import TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from shared.config import settings
from handlers.start_handler import cmd_start, cmd_help, MAIN_KEYBOARD
from handlers.expense_handler import handle_expense, handle_receipt_photo, handle_undo_callback, handle_edit_cat_callback, handle_set_cat_callback
from handlers.summary_handler import handle_weekly_summary, handle_monthly_summary

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, os.getenv("BOT_LOG_LEVEL", "INFO").upper(), logging.INFO),
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Suppress noisy httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    settings.validate()
    logger.info("Starting Kedut bot...")

    request = HTTPXRequest(
        connect_timeout=20,
        read_timeout=20,
        write_timeout=20,
        pool_timeout=20,
    )
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).request(request).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_undo_callback, pattern=r"^undo:"))
    app.add_handler(CallbackQueryHandler(handle_edit_cat_callback, pattern=r"^edit_cat:"))
    app.add_handler(CallbackQueryHandler(handle_set_cat_callback, pattern=r"^set_cat:"))

    # Menu button text handlers
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^📊 Ringkasan Minggu Ini$"),
            handle_weekly_summary,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^📅 Ringkasan Bulan Ini$"),
            handle_monthly_summary,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^💡 Bantuan$"),
            cmd_help,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^📝 Catat Pengeluaran$"),
            lambda u, c: u.message.reply_text(
                "Ketik pengeluaranmu, contoh:\n`makan siang 35rb`",
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            ),
        )
    )

    # Receipt photo (OCR)
    app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))

    # Fallback: treat any plain text as expense input
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense)
    )

    logger.info("Bot is polling...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except TimedOut:
        logger.error(
            "Telegram request timed out during startup. "
            "This usually means api.telegram.org is unreachable from this machine/network "
            "(proxy/firewall/VPN/DNS/ISP block) or the connection is very slow.",
            exc_info=True,
        )
        raise


if __name__ == "__main__":
    main()