from datetime import date
from typing import Optional
from shared.database.supabase_client import get_supabase

# ---------------------------------------------------------------------------
# Category cache — loaded once on first use, never changes at runtime.
# Structure: {"Makan & Minum": "1", "Transport": "2", ...}
# ---------------------------------------------------------------------------
_category_cache: dict[str, str] = {}


def _get_category_cache() -> dict[str, str]:
    """Return the category name→id map, loading from DB if not yet cached."""
    global _category_cache
    if _category_cache:
        return _category_cache

    db = get_supabase()
    res = db.table("categories").select("id, name").execute()
    _category_cache = {row["name"]: row["id"] for row in (res.data or [])}

    if not _category_cache:
        raise RuntimeError("Categories table is empty. Please seed the database first.")

    return _category_cache


def _resolve_category_id(category_name: str) -> Optional[str]:
    """Look up category id by name (case-insensitive). Falls back to 'Lainnya'."""
    cache = _get_category_cache()

    # Exact match first
    if category_name in cache:
        return cache[category_name]

    # Case-insensitive fallback
    lower = category_name.lower()
    for name, cid in cache.items():
        if name.lower() == lower:
            return cid

    # Final fallback: Lainnya
    return cache.get("Lainnya")


def add_expense(
    user_id: str,
    amount: float,
    category_name: str,
    note: str = "",
    expense_date: Optional[date] = None,
    transaction_type: str = "expense",
) -> dict:
    """Insert a new transaction row. Returns the created row."""
    db = get_supabase()
    if expense_date is None:
        expense_date = date.today()

    category_id = _resolve_category_id(category_name)

    result = (
        db.table("transactions")
        .insert(
            {
                "user_id": str(user_id),
                "amount": amount,
                "category_id": category_id,
                "note": note,
                "type": transaction_type,
                "transaction_date": expense_date.isoformat(),
            }
        )
        .execute()
    )
    return result.data[0] if result.data else {}


def delete_expense(expense_id: str, user_id: str) -> bool:
    """
    Delete a transaction by id, scoped to user_id for safety.
    Returns True if a row was deleted, False otherwise.
    """
    db = get_supabase()
    result = (
        db.table("transactions")
        .delete()
        .eq("id", expense_id)
        .eq("user_id", str(user_id))
        .execute()
    )
    return bool(result.data)


def get_expenses(user_id: str, start_date: date, end_date: date) -> list[dict]:
    """Fetch expenses only (type='expense') for a user within a date range."""
    db = get_supabase()
    result = (
        db.table("transactions")
        .select("id, amount, note, transaction_date, type, categories(name, icon)")
        .eq("user_id", str(user_id))
        .eq("type", "expense")
        .gte("transaction_date", start_date.isoformat())
        .lte("transaction_date", end_date.isoformat())
        .order("transaction_date", desc=True)
        .execute()
    )
    return result.data or []


def get_transactions(user_id: str, start_date: date, end_date: date) -> list[dict]:
    """Fetch ALL transactions (income + expense) for a user within a date range."""
    db = get_supabase()
    result = (
        db.table("transactions")
        .select("id, amount, note, transaction_date, type, categories(name, icon)")
        .eq("user_id", str(user_id))
        .gte("transaction_date", start_date.isoformat())
        .lte("transaction_date", end_date.isoformat())
        .order("transaction_date", desc=True)
        .execute()
    )
    return result.data or []

def update_expense_category(expense_id: str, user_id: str, category_name: str) -> bool:
    category_id = _resolve_category_id(category_name)
    if not category_id:
        return False
    db = get_supabase()
    result = (
        db.table('transactions')
        .update({'category_id': category_id})
        .eq('id', expense_id)
        .eq('user_id', str(user_id))
        .execute()
    )
    return bool(result.data)


def get_expense(expense_id: str, user_id: str) -> Optional[dict]:
    """Fetch a single transaction by id."""
    db = get_supabase()
    result = (
        db.table("transactions")
        .select("id, amount, note, transaction_date, type, categories(name, icon)")
        .eq("id", expense_id)
        .eq("user_id", str(user_id))
        .execute()
    )
    return result.data[0] if result.data else None
