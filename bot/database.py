"""База данных (SQLite + aiosqlite)"""
import aiosqlite
import time
from pathlib import Path
from bot.config import DB_PATH


async def get_db() -> aiosqlite.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    """Создание таблиц при первом запуске"""
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
    """)
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
    if row:
        return dict(row)
    return None


async def is_user_active(user_id: int) -> bool:
    """Проверяет, есть ли у пользователя активная подписка или пробный период"""
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


async def get_all_users_count() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    row = await cursor.fetchone()
    await db.close()
    return row[0]


async def get_active_users_count() -> int:
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM users WHERE trial_end > ? OR sub_end > ?", (now, now)
    )
    row = await cursor.fetchone()
    await db.close()
    return row[0]


async def get_all_user_ids() -> list[int]:
    db = await get_db()
    cursor = await db.execute("SELECT user_id FROM users")
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


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
    cursor = await db.execute(
        "SELECT profession FROM user_professions WHERE user_id = ?", (user_id,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [r[0] for r in rows]


async def get_users_by_profession(profession: str) -> list[int]:
    """Возвращает user_id всех активных пользователей с данной профессией"""
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
                      professions: list[str], link: str) -> int | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO vacancies (source_chat, message_id, text, professions, link, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source_chat, message_id, text, ",".join(professions), link, time.time())
        )
        await db.commit()
        vacancy_id = cursor.lastrowid
        await db.close()
        return vacancy_id
    except aiosqlite.IntegrityError:
        await db.close()
        return None


async def mark_vacancy_sent(user_id: int, vacancy_id: int):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO sent_vacancies (user_id, vacancy_id, sent_at) VALUES (?, ?, ?)",
        (user_id, vacancy_id, time.time())
    )
    await db.commit()
    await db.close()


async def get_vacancies_today_count() -> int:
    db = await get_db()
    day_ago = time.time() - 86400
    cursor = await db.execute("SELECT COUNT(*) FROM vacancies WHERE created_at > ?", (day_ago,))
    row = await cursor.fetchone()
    await db.close()
    return row[0]


# --- Платежи ---

async def add_payment(user_id: int, plan: str, amount: float, method: str, payment_id: str = ""):
    db = await get_db()
    await db.execute(
        "INSERT INTO payments (user_id, plan, amount, method, payment_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, plan, amount, method, payment_id, time.time())
    )
    await db.commit()
    await db.close()
