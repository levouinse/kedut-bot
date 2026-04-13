import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from shared.nlp.gemini_parser import (
    GeminiQuotaExceeded,
    parse_expense,
    parse_expense_from_receipt_image,
)
from shared.services.expense_service import add_expense, delete_expense, update_expense_category, get_expense
from shared.utils.formatters import format_currency, format_expense_confirmation
from shared.middleware.auth import require_registered
from shared.middleware.rate_limit import rate_limited

logger = logging.getLogger(__name__)

# Callback data prefixes
_UNDO_PREFIX = "undo:"
_EDIT_CAT_PREFIX = "edit_cat:"
_SET_CAT_PREFIX = "set_cat:"

# All available categories with emoji icons.
# Names MUST exactly match the `name` column in the `categories` table.
_CATEGORIES: list[tuple[str, str]] = [
    ("Makan & Minum", "🍽️"),
    ("Transport",     "🚗"),
    ("Belanja",       "🛒"),
    ("Kesehatan",     "💊"),
    ("Hiburan",       "🎮"),
    ("Tagihan",       "📋"),
    ("Pendidikan",    "📚"),
    ("Olahraga",      "🏃"),
    ("Rumah",         "🏠"),
    ("Lainnya",       "📌"),
]

_INCOME_CATEGORIES: list[tuple[str, str]] = [
    ("Gaji",      "💼"),
    ("Freelance",  "💻"),
    ("Investasi",  "📈"),
    ("Transfer",   "🔄"),
    ("Lainnya",    "💰"),
]


def _action_keyboard(expense_id: str) -> InlineKeyboardMarkup:
    """Return keyboard with Batalkan + Ganti Kategori buttons."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Batalkan", callback_data=f"{_UNDO_PREFIX}{expense_id}"),
        InlineKeyboardButton("✏️ Ganti Kategori", callback_data=f"{_EDIT_CAT_PREFIX}{expense_id}"),
    ]])


def _category_picker_keyboard(expense_id: str, categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Return a 2-column inline keyboard of provided categories."""
    buttons = [
        InlineKeyboardButton(
            f"{icon} {name}",
            callback_data=f"{_SET_CAT_PREFIX}{expense_id}:{name}",
        )
        for name, icon in categories
    ]
    # Pair buttons into rows of 2, except if odd number last item gets its own row
    rows = [buttons[i:i + 2] for i in range(0, len(buttons) - (1 if len(buttons) % 2 else 0), 2)]
    if len(buttons) % 2 == 1:
        rows.append([buttons[-1]])
    return InlineKeyboardMarkup(rows)


def _quota_error_message(e: GeminiQuotaExceeded) -> str:
    extra = (
        f"\n\nCoba lagi dalam ~{e.retry_after_seconds} detik ya."
        if e.retry_after_seconds
        else "\n\nCoba lagi beberapa saat lagi ya."
    )
    return (
        "😅 Waduh, otakku lagi overload nih!"
        + extra
        + "\n\nSementara itu, kamu bisa catat dulu di Notes terus masukin nanti."
    )

async def _save_multiple_items_and_reply(items: list[dict], message, update: Update, user_id: str, is_photo: bool = False) -> None:
    # Save each item and collect results
    saved: list[tuple[dict, str | None]] = []  # (item, expense_id)
    failed = 0
    for item in items:
        try:
            if item["amount"] <= 0:
                saved.append((item, None))
                continue
            row = add_expense(
                user_id=user_id,
                amount=item["amount"],
                category_name=item["category"],
                note=item["note"],
                expense_date=item["date"],
                transaction_type=item.get("type", "expense")
            )
            saved.append((item, row.get("id")))
        except Exception as e:
            logger.error("Error saving item '%s': %s", item.get("note"), e, exc_info=True)
            failed += 1

    if not saved and failed > 0:
        await message.reply_text("⚠️ Gagal menyimpan transaksi. Coba lagi ya!")
        return

    # Summary header
    valid_items = [(item, eid) for item, eid in saved if item["amount"] > 0]
    total_income = sum(item["amount"] for item, _ in valid_items if item.get("type", "expense") == "income")
    total_expense = sum(item["amount"] for item, _ in valid_items if item.get("type", "expense") == "expense")
    ambiguous_count = sum(1 for item, _ in saved if item["amount"] <= 0)

    emoji = "📷 *Struk berhasil dibaca!*" if is_photo else "✨ *Catatan berhasil!*"
    header_lines = [f"{emoji} ({len(saved)} item)\n"]
    if ambiguous_count:
        header_lines.append(f"⚠️ _{ambiguous_count} item harga tidak terbaca (tandai ?)_\n")
    if total_income > 0:
        header_lines.append(f"🟢 *Total Pemasukan: Rp {total_income:,.0f}*")
    if total_expense > 0:
        header_lines.append(f"🔴 *Total Pengeluaran: Rp {total_expense:,.0f}*")
        
    await message.reply_text("\n".join(header_lines), parse_mode="Markdown")

    for item, expense_id in saved:
        msg = format_expense_confirmation(
            amount=item["amount"],
            category=item["category"],
            note=item["note"],
        )
        type_label = "💸 *Pengeluaran dicatat!*" if item.get("type", "expense") == "expense" else "💰 *Pemasukan dicatat!*"
        msg = f"{type_label}\n{msg}" if not is_photo else msg
        markup = _action_keyboard(expense_id) if expense_id else None
        await message.reply_text(msg, parse_mode="Markdown", reply_markup=markup)

    if failed:
        await message.reply_text(f"⚠️ Gagal menyimpan {failed} item lainnya.")


@require_registered
@rate_limited
async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        parsed = parse_expense(text)
    except GeminiQuotaExceeded as e:
        await update.message.reply_text(_quota_error_message(e))
        return

    items = parsed.get("items", []) if parsed else []

    if not items:
        await update.message.reply_text(
            "❓ Maaf, aku tidak bisa memahami transaksi itu.\n\n"
            "Coba format seperti:\n"
            "`makan siang 35rb`\n"
            "`bayar listrik 250000 dan air 50k`\n"
            "`gajian 5jt`",
            parse_mode="Markdown",
        )
        return

    MAX_ITEMS = 10
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
        await update.message.reply_text(f"Sistemnya maksimal hanya memuat {MAX_ITEMS} transaksi sekaligus.")

    await _save_multiple_items_and_reply(items, update.message, update, user_id, is_photo=False)


@require_registered
@rate_limited
async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    message = update.message
    if not message or not message.photo:
        return

    caption = (message.caption or "").strip()

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        photo = message.photo[-1]  # highest resolution
        tg_file = await context.bot.get_file(photo.file_id)
        data = await tg_file.download_as_bytearray()
        items = parse_expense_from_receipt_image(
            bytes(data), mime_type="image/jpeg", caption=caption
        )
    except GeminiQuotaExceeded as e:
        await message.reply_text(_quota_error_message(e))
        return
    except Exception as e:
        logger.error("Error downloading/parsing receipt photo: %s", e, exc_info=True)
        items = None

    if not items:
        await message.reply_text(
            "❓ Maaf, aku belum bisa membaca struk itu.\n\n"
            "Coba kirim foto yang lebih jelas (tidak blur, rata, terang), atau ketik manual seperti:\n"
            "`makan siang 35rb`",
            parse_mode="Markdown",
        )
        return

    MAX_ITEMS = 10
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
        await message.reply_text(f"Sistemnya maksimal hanya memuat {MAX_ITEMS} transaksi sekaligus.")

    await _save_multiple_items_and_reply(items, message, update, user_id, is_photo=True)


async def handle_undo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ↩️ Batalkan inline button press."""
    query = update.callback_query
    await query.answer()  # dismiss the loading spinner on the button

    if not query.data or not query.data.startswith(_UNDO_PREFIX):
        return

    user_id = str(update.effective_user.id)
    expense_id = query.data[len(_UNDO_PREFIX):]

    try:
        deleted = delete_expense(expense_id=expense_id, user_id=user_id)
    except Exception as e:
        logger.error("Error deleting expense %s: %s", expense_id, e, exc_info=True)
        await query.edit_message_text(
            query.message.text + "\n\n⚠️ Gagal membatalkan. Coba lagi ya!",
            parse_mode="Markdown",
        )
        return

    if deleted:
        # Edit the original confirmation message — remove the undo button and add a note
        original = query.message.text or ""
        await query.edit_message_text(
            original + "\n\n~~Dibatalkan~~",
            parse_mode="Markdown",
        )
    else:
        # Already deleted or belongs to another user
        await query.edit_message_text(
            (query.message.text or "") + "\n\n⚠️ Transaksi tidak ditemukan atau sudah dibatalkan.",
            parse_mode="Markdown",
        )


async def handle_edit_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show category picker when user taps ✏️ Ganti Kategori."""
    query = update.callback_query
    await query.answer()

    if not query.data or not query.data.startswith(_EDIT_CAT_PREFIX):
        return

    expense_id = query.data[len(_EDIT_CAT_PREFIX):]
    user_id = str(update.effective_user.id)
    
    # Fetch transaction to know if it's income or expense
    tx = get_expense(expense_id, user_id)
    tx_type = tx.get("type", "expense") if tx else "expense"
    categories = _INCOME_CATEGORIES if tx_type == "income" else _CATEGORIES

    note = ""
    if query.message and query.message.text:
        # Extract the note line (3rd line of the confirmation message)
        lines = query.message.text.splitlines()
        note = lines[2].replace("📝 ", "").strip() if len(lines) >= 3 else ""

    prompt = f"✏️ Pilih kategori{f' untuk *{note}*' if note else ''}:"
    await query.edit_message_text(
        prompt,
        parse_mode="Markdown",
        reply_markup=_category_picker_keyboard(expense_id, categories),
    )


async def handle_set_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the selected category and update the confirmation message."""
    query = update.callback_query
    await query.answer()

    if not query.data or not query.data.startswith(_SET_CAT_PREFIX):
        return

    user_id = str(update.effective_user.id)
    # Payload format: set_cat:<expense_id>:<category_name>
    payload = query.data[len(_SET_CAT_PREFIX):]
    # Split only on first colon so category names with colons are safe
    parts = payload.split(":", 1)
    if len(parts) != 2:
        await query.answer("⚠️ Format tidak valid.", show_alert=True)
        return

    expense_id, new_category = parts

    try:
        updated = update_expense_category(
            expense_id=expense_id,
            user_id=user_id,
            category_name=new_category,
        )
    except Exception as e:
        logger.error("Error updating category %s: %s", expense_id, e, exc_info=True)
        await query.answer("⚠️ Gagal mengubah kategori. Coba lagi.", show_alert=True)
        return

    if not updated:
        await query.answer("⚠️ Transaksi tidak ditemukan.", show_alert=True)
        return

    # Fetch updated expense to rebuild message accurately
    expense = get_expense(expense_id, user_id)
    if not expense:
        await query.answer("⚠️ Gagal memuat data transaksi.", show_alert=True)
        return

    # Rebuild the confirmation message from scratch
    new_text = format_expense_confirmation(
        amount=float(expense["amount"]),
        category=expense["categories"]["name"],
        note=expense["note"],
    )
    
    icon = expense["categories"]["icon"]
    new_text += f"\n\n✏️ _Kategori diubah ke {icon} {expense['categories']['name']}_"

    await query.edit_message_text(
        new_text,
        parse_mode="Markdown",
        reply_markup=_action_keyboard(expense_id),
    )