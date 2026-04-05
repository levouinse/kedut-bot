import json
import logging
import os
import re
from datetime import date, timedelta
from io import BytesIO
import math

import google.generativeai as genai

try:
    from google.api_core.exceptions import ResourceExhausted  # type: ignore
except Exception:  # pragma: no cover
    ResourceExhausted = None  # type: ignore

from shared.config import settings

_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
genai.configure(api_key=settings.GEMINI_API_KEY)

_GENERATION_CONFIG = genai.GenerationConfig(response_mime_type="application/json")
_model = genai.GenerativeModel(_MODEL_NAME, generation_config=_GENERATION_CONFIG)

logger = logging.getLogger(__name__)


class GeminiQuotaExceeded(Exception):
    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

SYSTEM_PROMPT = """Kamu adalah asisten keuangan. Tugasmu adalah mengekstrak informasi transaksi keuangan dari pesan pengguna.
Transaksi bisa berupa PENGELUARAN (expense) atau PEMASUKAN (income).

Kembalikan HANYA JSON dengan format ini (tanpa teks tambahan):
{
  "type": "<expense atau income>",
  "amount": <angka float>,
  "category": "<salah satu: Makan & Minum, Transport, Belanja, Kesehatan, Hiburan, Tagihan, Pendidikan, Olahraga, Rumah, Lainnya>",
  "note": "<deskripsi singkat>",
  "date": "<YYYY-MM-DD atau null jika hari ini>"
}

Aturan type:
- Gunakan "income" jika pesan menyebut: gaji, terima, dapet, dapat, masuk, transfer masuk, freelance, honor, bonus, hasil jual, diterima, pendapatan, upah
- Semua transaksi lain adalah "expense"
- Untuk income, category boleh "Lainnya" jika tidak ada konteks yang cocok

Contoh:
- "makan siang 35rb" → {"type": "expense", "amount": 35000, "category": "Makan & Minum", "note": "makan siang", "date": null}
- "bayar listrik 250000" → {"type": "expense", "amount": 250000, "category": "Tagihan", "note": "bayar listrik", "date": null}
- "gajian 5jt" → {"type": "income", "amount": 5000000, "category": "Lainnya", "note": "gaji", "date": null}
- "dapet transfer 500rb dari client" → {"type": "income", "amount": 500000, "category": "Lainnya", "note": "transfer dari client", "date": null}

Aturan angka: 35rb=35000, 1.5jt=1500000, 1jt=1000000"""


RECEIPT_SYSTEM_PROMPT = """Kamu adalah asisten keuangan. Kamu menerima FOTO STRUK/RECEIPT.

Tugasmu: lakukan OCR dan ekstrak SETIAP ITEM dari struk sebagai daftar pengeluaran terpisah.

Kembalikan HANYA JSON (tanpa teks tambahan) dengan format:
{
    "items": [
        {
            "name": "<nama item>",
            "amount": <harga item sebagai float>,
            "category": "<salah satu: Makan, Transport, Belanja, Kesehatan, Hiburan, Tagihan, Pendidikan, Olahraga, Rumah, Lainnya>"
        }
    ],
    "date": "<YYYY-MM-DD atau null>"
}

Aturan:
- Ekstrak SETIAP baris item produk/layanan di struk.
- Jika harga item tidak jelas / tidak terbaca, tetap masukkan item dengan amount=0.
- JANGAN sertakan baris subtotal, diskon, atau grand total sebagai item.
- Pajak (PPN, tax, service charge) WAJIB dimasukkan sebagai item TERPISAH dengan category="Tagihan" dan name sesuai label di struk (misal "PPN 11%", "Service Charge").
- Kategorikan setiap item produk secara individual sesuai konteksnya.
- Jika tanggal tidak jelas, set null.
- Angka Indonesia: 35.000 = 35000; 1.500.000 = 1500000.
"""


# Income keywords — used to detect type before categorising
_INCOME_KEYWORDS = [
    "gaji", "gajian", "slip gaji", "terima", "dapet", "dapat", "masuk",
    "transfer masuk", "diterima", "pendapatan", "pemasukan", "honor",
    "bonus", "freelance", "hasil jual", "upah", "komisi", "dividen",
    "refund", "kembalian transfer",
]

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "Tagihan",
        ["listrik", "air", "pln", "wifi", "internet", "token", "pulsa", "bpjs", "cicilan", "iuran"],
    ),
    (
        "Makan & Minum",
        [
            "makan", "sarapan", "siang", "malam", "nasi", "kopi", "ayam", "bakso",
            "minum", "resto", "restoran", "warung", "cafe", "kafe", "snack", "jajan",
            "pizza", "burger", "mie", "soto", "pecel", "gado", "bubur",
        ],
    ),
    (
        "Transport",
        [
            "gojek", "grab", "ojek", "bensin", "bbm", "parkir", "tol", "taksi",
            "bus", "kereta", "motor", "mobil", "uber", "angkot", "transjakarta",
            "commuter", "krl", "mrt", "lrt",
        ],
    ),
    (
        "Belanja",
        [
            "beli", "belanja", "market", "indomaret", "alfamart", "supermarket",
            "tokopedia", "shopee", "lazada", "toko", "minimarket", "hypermart",
            "carrefour", "ikea",
        ],
    ),
    (
        "Kesehatan",
        ["obat", "dokter", "rs", "rumah sakit", "apotek", "klinik", "vitamin", "suplemen"],
    ),
    (
        "Pendidikan",
        ["buku", "kursus", "kuliah", "sekolah", "les", "kelas", "workshop", "seminar", "udemy"],
    ),
    (
        "Hiburan",
        [
            "nonton", "film", "game", "spotify", "netflix", "hiburan", "bioskop",
            "youtube", "disney", "konser", "event",
        ],
    ),
    (
        "Olahraga",
        ["gym", "fitness", "renang", "futsal", "badminton", "sepatu olahraga", "olahraga"],
    ),
    (
        "Rumah",
        [
            "sewa", "kontrakan", "kos", "perabot", "service", "servis", "listrik rumah",
            "furnitur", "cat", "renovasi",
        ],
    ),
]

# Relative date keywords in Indonesian
_RELATIVE_DATES: list[tuple[list[str], int]] = [
    (["kemarin", "kemaren"], -1),
    (["2 hari lalu", "dua hari lalu"], -2),
    (["3 hari lalu", "tiga hari lalu"], -3),
    (["minggu lalu", "seminggu lalu"], -7),
]


def _guess_type(text: str) -> str:
    """Return 'income' if text contains income keywords, else 'expense'."""
    lowered = text.lower()
    if any(kw in lowered for kw in _INCOME_KEYWORDS):
        return "income"
    return "expense"


def _guess_category(note: str) -> str:
    lowered = note.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Lainnya"


def _parse_relative_date(text: str) -> date:
    """Return a date offset from today if a relative keyword is found, else today."""
    lowered = text.lower()
    for keywords, offset in _RELATIVE_DATES:
        if any(kw in lowered for kw in keywords):
            return date.today() + timedelta(days=offset)
    return date.today()


def _normalize_number_str(num_str: str) -> str:
    """
    Normalize Indonesian/European thousand-separator formats to a plain float string.
    Examples:
      "1.500.000" → "1500000"
      "1.500"     → "1500"    (assumed thousands, not decimal)
      "1,5"       → "1.5"
      "150000"    → "150000"
    """
    dot_count = num_str.count(".")
    comma_count = num_str.count(",")

    if dot_count > 1:
        # e.g. "1.500.000" — dots are thousand separators
        return num_str.replace(".", "")
    if comma_count > 0 and dot_count == 0:
        # e.g. "1,5" or "1,500" — treat comma as decimal separator
        return num_str.replace(",", ".")
    if dot_count == 1 and comma_count == 0:
        # Ambiguous: "1.500" could be 1500 or 1.5
        # If the fractional part has exactly 3 digits → thousand separator
        parts = num_str.split(".")
        if len(parts[1]) == 3:
            return num_str.replace(".", "")
        # Otherwise treat as decimal (e.g. "1.5jt")
        return num_str
    # No separators
    return num_str


def _coerce_amount(value) -> float:
    """Convert model-provided amount value into a float (supports Indonesian separators)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    # Strip common currency markers
    text = re.sub(r"(?i)rp\.?\s*", "", text)
    text = text.replace("IDR", "").replace("idr", "")
    text = re.sub(r"\s+", "", text)
    # Keep only digits and separators
    text = re.sub(r"[^0-9,\.]", "", text)
    if not text:
        return 0.0

    try:
        normalized = _normalize_number_str(text)
        return float(normalized)
    except Exception:
        return 0.0


def _parse_amount_local(text: str) -> tuple[float, str] | tuple[None, None]:
    """
    Return (amount, matched_token) for the most significant amount found in text,
    or (None, None) if nothing is found.

    Strategy: collect all matches, prefer those with an explicit rb/jt suffix
    (they are unambiguous), otherwise take the largest numeric value.
    """
    pattern = re.compile(
        r"(?i)(?P<num>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
        r"\s*(?P<suffix>rb|ribu|jt|juta|k)?\b"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None, None

    candidates: list[tuple[float, str, bool]] = []  # (value, token, has_suffix)
    for m in matches:
        num_str = _normalize_number_str(m.group("num"))
        suffix = (m.group("suffix") or "").lower()
        try:
            value = float(num_str)
        except ValueError:
            continue

        if suffix in {"rb", "ribu", "k"}:
            value *= 1_000
        elif suffix in {"jt", "juta"}:
            value *= 1_000_000

        if value <= 0:
            continue
        candidates.append((float(int(value)), m.group(0), bool(suffix)))

    if not candidates:
        return None, None

    # Prefer suffixed candidates (unambiguous), then pick the largest value
    suffixed = [c for c in candidates if c[2]]
    pool = suffixed if suffixed else candidates
    best = max(pool, key=lambda c: c[0])
    return best[0], best[1]


# Noise words that don't contribute to the expense description.
# These are stripped from the note after removing the amount token.
_NOISE_WORDS = re.compile(
    r"(?i)\b("
    r"aku|saya|gue|gw|ane|w|"
    r"tadi|tadi(?:nya)?|ini|itu|"
    r"harga(?:nya)?|bayar|bayarin|beli(?:in)?|buat|untuk|dgn|dengan|"
    r"sebesar|senilai|seharga|totalnya|total|sebanyak|"
    r"di|ke|dari|yang|yg|dan|juga|udah|sudah|udh|"
    r"nya|lah|deh|dong|nih|sih|ya|yaa|wkwk"
    r")\b"
)


def _clean_note(raw: str) -> str:
    """Remove noise words and tidy up whitespace from a note string."""
    cleaned = _NOISE_WORDS.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip("-–—:;,. ")
    # Capitalize first letter
    return cleaned.capitalize() if cleaned else "pengeluaran"


def _parse_expense_local(text: str) -> dict | None:
    amount, token = _parse_amount_local(text)
    if amount is None or token is None:
        return None

    # Remove the amount token from the note
    note = text
    try:
        note = re.sub(re.escape(token), "", note, count=1, flags=re.IGNORECASE).strip()
    except re.error:
        note = text

    # Strip relative date keywords from note
    for keywords, _ in _RELATIVE_DATES:
        for kw in keywords:
            note = re.sub(re.escape(kw), "", note, flags=re.IGNORECASE)

    tx_type = _guess_type(text)
    note = _clean_note(note)
    if not note:
        note = "Pemasukan" if tx_type == "income" else "Pengeluaran"

    category = _guess_category(note) if tx_type == "expense" else "Lainnya"
    expense_date = _parse_relative_date(text)

    return {
        "type": tx_type,
        "amount": float(amount),
        "category": category,
        "note": note,
        "date": expense_date,
    }


def _extract_json(raw: str) -> str:
    """Best-effort extraction of a JSON object from a model response."""
    cleaned = raw.strip()
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).strip("` \n")
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _extract_retry_after_seconds(message: str) -> int | None:
    """Try to extract suggested retry delay from Gemini error text."""
    m = re.search(r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s", message)
    if not m:
        return None
    try:
        return int(math.ceil(float(m.group(1))))
    except Exception:
        return None


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return True
    if ResourceExhausted is not None and isinstance(exc, ResourceExhausted):
        return True
    return False


def _is_transaction_input(text: str) -> bool:
    """
    Quick guard: return False for obvious non-transaction messages so we don't
    waste a Gemini call or return a false positive.
    """
    NON_TRANSACTION_PATTERNS = [
        r"^\s*(hapus|cancel|batal|keluar|exit|stop|menu|help|bantuan|\?)\s*$",
        r"^\s*(hi|halo|hei|hey|hello|ok|oke|iya|ya|tidak|nggak|ngga)\s*$",
    ]
    lowered = text.strip().lower()
    for pattern in NON_TRANSACTION_PATTERNS:
        if re.match(pattern, lowered, re.IGNORECASE):
            return False
    return True


# Keep old name as alias for backward compatibility
_is_expense_input = _is_transaction_input


def parse_expense(text: str) -> dict | None:
    """
    Parse natural language transaction (expense OR income) from user text.
    Returns dict with type, amount, category, note, date — or None on failure.

    Flow:
      1. Guard against obvious non-transaction messages.
      2. Local parse for common patterns (fast, works offline).
         Only returns early if a suffixed amount (rb/jt/k) is found — unambiguous.
      3. Gemini parse for complex or ambiguous inputs.
      4. Final fallback to local parse if Gemini fails.
    """
    if not _is_transaction_input(text):
        logger.info("Non-transaction input detected, skipping parse: %s", text)
        return None

    # 1) Try local parse — only trust it if there's an explicit suffix
    amount, token = _parse_amount_local(text)
    has_suffix = token is not None and bool(
        re.search(r"(?i)(rb|ribu|jt|juta|k)\b", token)
    )

    if has_suffix:
        local = _parse_expense_local(text)
        if local and local.get("amount", 0) > 0:
            logger.info(
                "Local parse (suffixed) success: type=%s amount=%s category=%s note=%s",
                local.get("type"),
                local["amount"],
                local["category"],
                local["note"],
            )
            return local

    # 2) Gemini parse for ambiguous / complex inputs
    try:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Pesan user: \"{text}\"\n\n"
            f"Hari ini: {date.today().isoformat()}"
        )
        logger.info("Gemini model=%s input=%s", _MODEL_NAME, text)
        response = _model.generate_content(prompt)
        raw = (response.text or "").strip()
        logger.info("Gemini raw response: %s", raw)

        raw_json = _extract_json(raw)
        data = json.loads(raw_json)

        # Parse date — Gemini may return a relative label or ISO string
        tx_date = _parse_relative_date(text)  # prefer local date parse
        if data.get("date") and str(data["date"]).lower() not in ("null", "none", ""):
            try:
                tx_date = date.fromisoformat(str(data["date"]))
            except ValueError:
                tx_date = _parse_relative_date(text)

        # Validate type field from Gemini; fall back to local detection
        gemini_type = str(data.get("type", "")).lower()
        tx_type = gemini_type if gemini_type in ("expense", "income") else _guess_type(text)

        parsed = {
            "type": tx_type,
            "amount": _coerce_amount(data.get("amount", 0)),
            "category": str(data.get("category", "Lainnya")),
            "note": str(data.get("note", "")),
            "date": tx_date,
        }

        if parsed["amount"] <= 0:
            logger.warning("Gemini returned amount <= 0, falling back to local.")
            return _parse_expense_local(text)

        return parsed

    except Exception as e:
        if _is_quota_error(e):
            retry_after = _extract_retry_after_seconds(str(e))
            logger.warning("Gemini quota/rate limit exceeded (text). retry_after=%s error=%s", retry_after, e)
            raise GeminiQuotaExceeded("Gemini quota/rate limit exceeded", retry_after_seconds=retry_after)

        logger.error("Gemini parse failed: %s", e, exc_info=True)
        # Last resort: local parse even without suffix
        return _parse_expense_local(text)


def parse_expense_from_receipt_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    caption: str | None = None,
) -> list[dict] | None:
    """Parse per-item expenses from a receipt image using Gemini vision/OCR.

    Returns a list of dicts [{name, amount, category, date}], or None on failure.
    Items with unclear amounts (amount=0) are included with '?' appended to name
    so the user can edit them.
    """
    if not image_bytes:
        return None

    try:
        try:
            from PIL import Image  # type: ignore
        except Exception as pil_err:
            logger.error("Pillow is required for receipt OCR but not installed: %s", pil_err)
            return None

        today = date.today().isoformat()
        hint = (caption or "").strip()
        prompt = (
            f"{RECEIPT_SYSTEM_PROMPT}\n\n"
            f"Hari ini: {today}\n"
            f"Catatan user (opsional): {hint if hint else 'null'}"
        )

        logger.info(
            "Gemini receipt OCR (per-item) model=%s bytes=%s caption=%s",
            _MODEL_NAME,
            len(image_bytes),
            bool(hint),
        )

        img = Image.open(BytesIO(image_bytes))
        response = _model.generate_content([img, prompt])
        raw = (response.text or "").strip()
        logger.info("Gemini receipt raw response: %s", raw)

        raw_json = _extract_json(raw)
        data = json.loads(raw_json)

        # Parse receipt date
        expense_date: date
        raw_date = data.get("date")
        if raw_date and str(raw_date).lower() not in ("null", "none", ""):
            try:
                expense_date = date.fromisoformat(str(raw_date))
            except ValueError:
                expense_date = date.today()
        else:
            expense_date = _parse_relative_date(hint) if hint else date.today()

        # Parse items list
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list) or not raw_items:
            logger.warning("Gemini receipt returned no items.")
            return None

        results: list[dict] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            amount = _coerce_amount(item.get("amount", 0))
            name = str(item.get("name", "")).strip() or "Item"
            category = str(item.get("category", "Lainnya"))

            # Flag ambiguous items with '?' so user knows to review
            if amount <= 0:
                name = f"{name} (?)"
                amount = 0.0

            results.append({
                "note": name,
                "amount": amount,
                "category": category,
                "date": expense_date,
            })

        return results if results else None

    except Exception as e:
        if _is_quota_error(e):
            retry_after = _extract_retry_after_seconds(str(e))
            logger.warning(
                "Gemini quota/rate limit exceeded (receipt). retry_after=%s error=%s",
                retry_after,
                e,
            )
            raise GeminiQuotaExceeded("Gemini quota/rate limit exceeded", retry_after_seconds=retry_after)

        logger.error("Gemini receipt parse failed: %s", e, exc_info=True)
        return None