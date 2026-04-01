# 🤖 Kedut Bot — Kemana Duitku?

> **Bot Telegram untuk mencatat pengeluaran harian secara natural — cukup ketik atau foto struk, sisanya diurus AI.**

Kedut adalah money tracker yang dibangun live di depan kamera sebagai bagian dari seri konten *build in public*. Bot ini open source sebagai bentuk transparansi dan buat kalian yang pengen belajar atau fork buat project sendiri.

💬 Coba langsung: [t.me/KemanaDuitku_Bot](https://t.me/KemanaDuitku_Bot)

---

## ✨ Fitur

| Fitur | Cara pakai |
|---|---|
| 💬 Catat via teks natural | `"makan siang 35rb"`, `"bensin 80ribu"` |
| 🧾 Scan struk via foto | Kirim foto struk → otomatis terbaca |
| ↩️ Batalkan transaksi | Tombol **Batalkan** muncul setelah catat |
| 📊 Ringkasan mingguan | Ketuk menu **Ringkasan Minggu Ini** |
| 📅 Ringkasan bulanan | Ketuk menu **Ringkasan Bulan Ini** |

---

## 🧱 Tech Stack

- **Python 3.11+**
- **[python-telegram-bot](https://python-telegram-bot.org/) v21** — Telegram Bot API wrapper
- **[Gemini API](https://aistudio.google.com/)** — NLP parsing teks & OCR struk
- **[Supabase](https://supabase.com/)** — Database & auth
- **python-dotenv** — Environment variable management

---

## 🚀 Cara Setup

### 1. Clone repo

```bash
git clone https://github.com/Anwitch/kedut-bot.git
cd kedut-bot
```

### 2. Buat virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup environment variables

```bash
cp .env.example .env
```

Lalu isi `.env` dengan credentials kamu:

```env
TELEGRAM_BOT_TOKEN=   # dari @BotFather
SUPABASE_URL=         # dari Supabase Dashboard → Project Settings → API
SUPABASE_SERVICE_KEY= # dari Supabase Dashboard → Project Settings → API
GEMINI_API_KEY=       # dari https://aistudio.google.com/app/apikey
```

### 5. Jalankan bot

```bash
python main.py
```

---

## 📁 Struktur Folder

```
bot/
├── main.py                      # Entry point
├── requirements.txt
├── .env.example
│
├── handlers/                    # Telegram message handlers
│   ├── expense_handler.py       # Handle input teks & foto struk
│   ├── start_handler.py         # /start, /help, keyboard menu
│   └── summary_handler.py       # Ringkasan mingguan & bulanan
│
└── shared/                      # Logic inti (reusable)
    ├── config.py                # Load & validasi env vars
    ├── database/
    │   └── supabase_client.py   # Singleton Supabase client
    ├── nlp/
    │   └── gemini_parser.py     # Parsing teks & OCR via Gemini
    ├── services/
    │   ├── expense_service.py   # CRUD pengeluaran
    │   └── summary_service.py   # Agregasi ringkasan
    └── utils/
        └── formatters.py        # Format currency, pesan konfirmasi
```

---

## 🗄️ Setup Supabase

Bot ini butuh tabel berikut di Supabase:

```sql
create table categories (
  id          serial primary key,
  name        varchar not null unique,
  icon        varchar default '💰',
  created_at  timestamptz default now()
);

-- Pengeluaran per user
create table expenses (
  id          uuid primary key default gen_random_uuid(),
  user_id     text not null,
  amount      numeric not null,
  category_id int references categories(id),
  note        text,
  expense_date date,
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);

-- Registrasi user
create table users (
  user_id       text primary key,
  username      text,
  first_name    text,
  registered_at timestamptz default now(),
  is_active     boolean default true
);

-- Rate limiting
create table rate_limits (
  user_id     text not null,
  window_start timestamptz not null,
  request_count int default 1,
  primary key (user_id, window_start)
);
```

> Pastikan RLS (Row Level Security) di-setup sesuai kebutuhan deployment kamu.

---

## 🤝 Kontribusi

Bot ini open source dan ide fiturnya sering datang dari komunitas. Kalau kamu punya ide atau nemu bug, buka aja [issue](../../issues) atau langsung PR.

---

## 📺 Build in Public

Proses pembuatan bot ini direkam dan diupload sebagai seri konten. Follow [@andriewijaya._](https://www.instagram.com/andriewijaya._) dan [@andrienih](https://www.tiktok.com/@andrienih) buat ngikutin perjalanannya.

---

## 📄 License

MIT — bebas dipakai, dimodifikasi, dan didistribusikan.
