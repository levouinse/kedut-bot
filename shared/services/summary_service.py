from datetime import date, timedelta
from shared.services.expense_service import get_expenses


def _build_summary(user_id: str, start: date, end: date, label: str) -> str:
    rows = get_expenses(user_id, start, end)
    if not rows:
        return f"Belum ada pengeluaran {label}. 🎉"

    daily_totals: dict[str, float] = {}
    daily_items: dict[str, list[str]] = {}
    grand_total = 0.0

    for r in rows:
        edate = r["expense_date"]
        amount = float(r["amount"])
        cat = r.get("categories") or {}
        icon = cat.get("icon", "📌")
        note = r.get("note") or cat.get("name", "Lainnya")
        
        grand_total += amount
        
        if edate not in daily_totals:
            daily_totals[edate] = 0.0
            daily_items[edate] = []
        
        daily_totals[edate] += amount
        daily_items[edate].append(f"• {icon} {note}: *Rp {amount:,.0f}*")

    lines = [f"📊 *Ringkasan {label.capitalize()}*\n"]
    
    # Group by date (get_expenses already sorts by date desc)
    # We'll use the sorted keys to be explicit
    for edate in sorted(daily_totals.keys(), reverse=True):
        dt = date.fromisoformat(edate)
        # Indonesian day names
        days_id = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        day_name = days_id[dt.weekday()]
        
        lines.append(f"📅 *{day_name}, {dt.strftime('%d %b')}*")
        for item in daily_items[edate]:
            lines.append(f"  {item}")
        lines.append(f"  _Total hari ini: Rp {daily_totals[edate]:,.0f}_\n")

    lines.append(f"💰 *Total Keseluruhan: Rp {grand_total:,.0f}*")
    lines.append(f"📅 {start.strftime('%d %b')} – {end.strftime('%d %b %Y')}")
    return "\n".join(lines)


def get_weekly_summary(user_id: str) -> str:
    today = date.today()
    start = today - timedelta(days=today.weekday())  # Monday
    return _build_summary(user_id, start, today, "minggu ini")


def get_monthly_summary(user_id: str) -> str:
    today = date.today()
    start = today.replace(day=1)
    return _build_summary(user_id, start, today, "bulan ini")
