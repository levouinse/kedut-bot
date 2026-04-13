from functools import wraps
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from shared.database.supabase_client import get_supabase

MAX_REQUESTS = 5       # max request per window
WINDOW_MINUTES = 1      # per berapa menit

def rate_limited(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        now = datetime.now(timezone.utc)
        window = now.replace(second=0, microsecond=0) - timedelta(
            minutes=now.minute % WINDOW_MINUTES
        )

        db = get_supabase()
        
        # Increments automatically or inserts 1 using atomic Postgres ON CONFLICT UPSERT
        res = db.rpc("increment_rate_limit", {
            "p_user_id": user_id,
            "p_window_start": window.isoformat()
        }).execute()

        if res.data:
            count = res.data
            if count > MAX_REQUESTS:
                if update.callback_query:
                    await update.callback_query.answer(
                        "😅 Terlalu banyak request. Coba lagi dalam 1 menit ya.", 
                        show_alert=True
                    )
                elif update.message:
                    await update.message.reply_text(
                        "😅 Wah, kamu lagi ngebut banget nih!\n\n"
                        "Tenang dulu sebentar, coba lagi dalam 1 menit ya. 🙏"
                    )
                return

        return await func(update, context)
    return wrapper
