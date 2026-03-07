"""База данных (SQLite + aiosqlite)"""
import aiosqlite
import time
import json
from pathlib import Path
from bot.config import DB_PATH


async def get_db() -> aiosqlite.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at REAL NOT NULL,
            trial_end REAL NOT NULL,
            sub_end REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS user_professions (
            user_id INTEGER NOT NULL,
            profession TEXT NOT NULL,
            PRIMARY KEY (user_id, profession),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chat TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            professions TEXT NOT NULL,
            link TEXT,
            created_at REAL NOT NULL,
            UNIQUE(source_chat, message_id)
        );

        CREATE TABLE IF NOT EXISTS sent_vacancies (
            user_id INTEGER NOT NULL,
            vacancy_id INTEGER NOT NULL,
            sent_at REAL NOT NULL,
            PRIMARY KEY (user_id, vacancy_id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            payment_id TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            chat_ref TEXT PRIMARY KEY,
            added_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    await db.commit()

    # Миграция: добавляем text_hash если колонки нет
    try:
        await db.execute("SELECT text_hash FROM vacancies LIMIT 1")
    except Exception:
        await db.execute("ALTER TABLE vacancies ADD COLUMN text_hash TEXT")
        await db.commit()

    await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_text_hash ON vacancies(text_hash)")
    await db.commit()

    # Таблица отправленных вакансий (дедупликация по пользователю)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sent_vacancies (
            user_id INTEGER NOT NULL,
            vacancy_id INTEGER NOT NULL,
            sent_at REAL NOT NULL,
            PRIMARY KEY (user_id, vacancy_id)
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sent_vacancies_user ON sent_vacancies(user_id)")
    await db.commit()
    await db.close()


# --- Пользователи ---

async def add_user(user_id: int, username: str, full_name: str, trial_days: int = 7):
    db = await get_db()
    now = time.time()
    trial_end = now + trial_days * 86400
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, created_at, trial_end) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, full_name, now, trial_end)
    )
    await db.commit()
    await db.close()


async def get_user(user_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    await db.close()
    return dict(row) if row else None


async def is_user_active(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    now = time.time()
    return now < user["trial_end"] or now < user["sub_end"]


async def extend_subscription(user_id: int, days: int):
    db = await get_db()
    user = await get_user(user_id)
    if not user:
        await db.close()
        return
    now = time.time()
    current_end = max(user["sub_end"], user["trial_end"], now)
    new_end = current_end + days * 86400
    await db.execute("UPDATE users SET sub_end = ? WHERE user_id = ?", (new_end, user_id))
    await db.commit()
    await db.close()


async def get_all_users() -> list[int]:
    db = await get_db()
    cursor = await db.execute("SELECT user_id FROM users")
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


async def get_stats() -> dict:
    db = await get_db()
    now = time.time()

    c = await db.execute("SELECT COUNT(*) FROM users")
    users = (await c.fetchone())[0]

    c = await db.execute("SELECT COUNT(*) FROM users WHERE trial_end > ? OR sub_end > ?", (now, now))
    active_subs = (await c.fetchone())[0]

    c = await db.execute("SELECT COUNT(*) FROM vacancies")
    vacancies = (await c.fetchone())[0]

    c = await db.execute("SELECT COUNT(*) FROM sent_vacancies")
    sent = (await c.fetchone())[0]

    c = await db.execute("SELECT COUNT(*) FROM payments")
    payments = (await c.fetchone())[0]

    await db.close()
    return {"users": users, "active_subs": active_subs, "vacancies": vacancies, "sent": sent, "payments": payments}


# --- Профессии ---

async def set_user_professions(user_id: int, professions: list[str]):
    db = await get_db()
    await db.execute("DELETE FROM user_professions WHERE user_id = ?", (user_id,))
    for prof in professions:
        await db.execute(
            "INSERT INTO user_professions (user_id, profession) VALUES (?, ?)",
            (user_id, prof)
        )
    await db.commit()
    await db.close()


async def get_user_professions(user_id: int) -> list[str]:
    db = await get_db()
    cursor = await db.execute("SELECT profession FROM user_professions WHERE user_id = ?", (user_id,))
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


async def get_users_by_profession(profession: str) -> list[int]:
    db = await get_db()
    now = time.time()
    cursor = await db.execute("""
        SELECT up.user_id FROM user_professions up
        JOIN users u ON u.user_id = up.user_id
        WHERE up.profession = ? AND (u.trial_end > ? OR u.sub_end > ?)
    """, (profession, now, now))
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


# --- Вакансии ---

async def add_vacancy(source_chat: str, message_id: int, text: str,
                      professions: list[str], link: str,
                      text_hash: str = "") -> int | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO vacancies (source_chat, message_id, text, professions, link, text_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_chat, message_id, text, ",".join(professions), link, text_hash, time.time())
        )
        await db.commit()
        vacancy_id = cursor.lastrowid
        await db.close()
        return vacancy_id
    except aiosqlite.IntegrityError:
        await db.close()
        return None


async def vacancy_hash_exists(text_hash: str) -> bool:
    """Проверяет, есть ли вакансия с таким хэшем текста (дедупликация)."""
    if not text_hash:
        return False
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM vacancies WHERE text_hash = ? LIMIT 1", (text_hash,)
    )
    row = await cursor.fetchone()
    await db.close()
    return row is not None


async def mark_vacancy_sent(user_id: int, vacancy_id: int):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO sent_vacancies (user_id, vacancy_id, sent_at) VALUES (?, ?, ?)",
        (user_id, vacancy_id, time.time())
    )
    await db.commit()
    await db.close()


async def was_vacancy_sent(user_id: int, vacancy_id: int) -> bool:
    """Проверяет, отправлялась ли эта вакансия этому пользователю."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM sent_vacancies WHERE user_id = ? AND vacancy_id = ? LIMIT 1",
        (user_id, vacancy_id)
    )
    row = await cursor.fetchone()
    await db.close()
    return row is not None


async def get_recent_vacancies(limit: int = 10) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM vacancies ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


# --- Платежи ---

async def add_payment(user_id: int, plan: str, amount: float, method: str, payment_id: str = ""):
    db = await get_db()
    await db.execute(
        "INSERT INTO payments (user_id, plan, amount, method, payment_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, plan, amount, method, payment_id, time.time())
    )
    await db.commit()
    await db.close()


# --- Источники (хранятся в БД) ---

async def get_sources() -> list[str]:
    db = await get_db()
    cursor = await db.execute("SELECT chat_ref FROM sources ORDER BY added_at")
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


async def add_source(chat_ref: str) -> bool:
    db = await get_db()
    try:
        await db.execute("INSERT INTO sources (chat_ref, added_at) VALUES (?, ?)", (chat_ref, time.time()))
        await db.commit()
        await db.close()
        return True
    except aiosqlite.IntegrityError:
        await db.close()
        return False


async def remove_source(chat_ref: str) -> bool:
    db = await get_db()
    cursor = await db.execute("DELETE FROM sources WHERE chat_ref = ?", (chat_ref,))
    await db.commit()
    deleted = cursor.rowcount > 0
    await db.close()
    return deleted


async def init_default_sources(defaults: list[str]):
    """Добавляет дефолтные источники если таблица пуста"""
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM sources")
    count = (await cursor.fetchone())[0]
    if count == 0:
        now = time.time()
        for ref in defaults:
            await db.execute("INSERT OR IGNORE INTO sources (chat_ref, added_at) VALUES (?, ?)", (ref, now))
        await db.commit()
    await db.close()


# --- Настройки (тарифы и пр.) ---

async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    await db.close()
    return row[0] if row else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await db.commit()
    await db.close()


async def get_plans() -> dict:
    """Возвращает тарифы из БД или дефолтные"""
    raw = await get_setting("plans")
    if raw:
        return json.loads(raw)
    # Дефолтные тарифы
    return {
        "week": {"name": "Неделя", "price": 740, "days": 7, "stars": 120},
        "month": {"name": "Месяц", "price": 1290, "days": 30, "stars": 210},
        "quarter": {"name": "3 месяца", "price": 2890, "days": 90, "stars": 470},
    }


async def set_plans(plans: dict):
    await set_setting("plans", json.dumps(plans, ensure_ascii=False))
