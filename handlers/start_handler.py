import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

from shared.services.user_service import register_user

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📝 Catat Pengeluaran"],
        ["📊 Ringkasan Minggu Ini", "📅 Ringkasan Bulan Ini"],
        ["💡 Bantuan"],
    ],
    resize_keyboard=True,
    input_field_placeholder="Ketik atau pilih menu...",
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Auto-register saat /start
    register_user(
        user_id=str(user.id),
        username=user.username or "",
        first_name=user.first_name or "",
    )

    await update.message.reply_text(
        f"👋 Halo *{user.first_name}*!\n\n"
        "Aku *Kedut* — bot pencatat pengeluaranmu. 🤖💰\n\n"
        "Langsung ketik pengeluaranmu, contoh:\n"
        "• `makan siang 35rb`\n"
        "• `bayar listrik 250000`\n"
        "• `beli kopi 15000`\n\n"
        "Atau pilih menu di bawah:",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Cara Pakai Kedut*\n\n"
        "*Catat pengeluaran:*\n"
        "Cukup ketik pengeluaranmu dalam bahasa natural:\n"
        "`makan siang warteg 15rb`\n"
        "`parkir 3000`\n"
        "`beli obat kemarin 45000`\n\n"
        "*Menu:*\n"
        "📊 Ringkasan Minggu Ini — rekap 7 hari\n"
        "📅 Ringkasan Bulan Ini — rekap bulan berjalan\n\n"
        "*Singkatan angka:*\n"
        "• `rb` = ribu (35rb = 35.000)\n"
        "• `jt` = juta (1.5jt = 1.500.000)",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
