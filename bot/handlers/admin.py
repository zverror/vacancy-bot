"""Админские команды (только для ADMIN_IDS)"""
import json
import logging
import tempfile
import os
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from bot import database as db
from bot.config import ADMIN_IDS

router = Router()
logger = logging.getLogger(__name__)

_monitor = None

def set_monitor(monitor):
    global _monitor
    _monitor = monitor


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# --- Админ-панель ---

ADMIN_HELP_TEXT = (
    "⚙️ <b>Админ-панель</b>\n\n"
    "<b>📊 Мониторинг:</b>\n"
    "/stats — Статистика бота\n"
    "/sources — Список источников вакансий\n"
    "/add_source &lt;chat&gt; — Добавить источник\n"
    "/del_source &lt;chat&gt; — Удалить источник\n"
    "/recent — 10 последних сообщений из чатов\n"
    "/test_vacancy — Тест классификатора\n"
    "/analyze — Выгрузка 200 сообщений из каждого чата в JSON\n\n"
    "<b>💰 Тарифы:</b>\n"
    "/prices — Текущие тарифы\n"
    "/set_price &lt;plan&gt; &lt;rub&gt; &lt;stars&gt; — Изменить\n\n"
    "<b>📢 Коммуникация:</b>\n"
    "/broadcast &lt;текст&gt; — Рассылка всем\n\n"
    "<b>🔐 Авторизация:</b>\n"
    "/code &lt;код&gt; — Код авторизации Pyrogram\n"
    "/password &lt;пароль&gt; — 2FA пароль"
)


@router.message(Command("admin"))
@router.message(Command("admin_help"))
async def cmd_admin(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(ADMIN_HELP_TEXT, parse_mode="HTML")


# --- Статистика ---

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_admin(message.from_user.id):
        return
    stats = await db.get_stats()
    monitor_status = "✅ Запущен" if (_monitor and _monitor._authorized) else "❌ Не авторизован"
    chats_count = len(_monitor._resolved_chats) if _monitor else 0
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💰 Активных подписок: {stats['active_subs']}\n"
        f"📌 Вакансий найдено: {stats['vacancies']}\n"
        f"📨 Вакансий отправлено: {stats['sent']}\n"
        f"💵 Платежей: {stats['payments']}\n\n"
        f"🔍 Мониторинг: {monitor_status}\n"
        f"📡 Подключено чатов: {chats_count}",
        parse_mode="HTML"
    )


# --- Источники ---

@router.message(Command("sources"))
async def cmd_sources(message: Message):
    if not _is_admin(message.from_user.id):
        return
    sources = await db.get_sources()
    if not sources:
        await message.answer("📡 Нет источников. Добавьте: /add_source @channel_name")
        return

    lines = ["📡 <b>Источники вакансий</b>\n"]
    for ref in sources:
        connected = _monitor and ref in _monitor._resolved_chats
        status = "✅" if connected else "⏳"
        lines.append(f"{status} <code>{ref}</code>")

    lines.append(f"\n/add_source &lt;chat&gt; — добавить\n/del_source &lt;chat&gt; — удалить")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("add_source"))
async def cmd_add_source(message: Message):
    if not _is_admin(message.from_user.id):
        return
    ref = message.text.replace("/add_source", "", 1).strip().lstrip("@")
    if not ref:
        await message.answer("Использование: /add_source @channel_name\nили /add_source +invite_hash")
        return

    added = await db.add_source(ref)
    if not added:
        await message.answer(f"⚠️ Источник <code>{ref}</code> уже существует", parse_mode="HTML")
        return

    # Переподключаем мониторинг
    result = ""
    if _monitor and _monitor._authorized:
        result = await _monitor.reload_sources()

    await message.answer(f"✅ Источник <code>{ref}</code> добавлен\n{result}", parse_mode="HTML")


@router.message(Command("del_source"))
async def cmd_del_source(message: Message):
    if not _is_admin(message.from_user.id):
        return
    ref = message.text.replace("/del_source", "", 1).strip().lstrip("@")
    if not ref:
        await message.answer("Использование: /del_source @channel_name")
        return

    deleted = await db.remove_source(ref)
    if not deleted:
        await message.answer(f"⚠️ Источник <code>{ref}</code> не найден", parse_mode="HTML")
        return

    result = ""
    if _monitor and _monitor._authorized:
        result = await _monitor.reload_sources()

    await message.answer(f"✅ Источник <code>{ref}</code> удалён\n{result}", parse_mode="HTML")


# --- Проверка парсинга ---

@router.message(Command("recent"))
async def cmd_recent(message: Message):
    """Получить последние сообщения из источников"""
    if not _is_admin(message.from_user.id):
        return
    if not _monitor or not _monitor._authorized:
        await message.answer("❌ Мониторинг не авторизован")
        return
    if not _monitor._resolved_chats:
        await message.answer("❌ Нет подключённых чатов")
        return

    await message.answer("⏳ Загружаю последние сообщения...")

    results = await _monitor.fetch_recent_from_sources(10)
    if not results:
        await message.answer("Сообщений не найдено")
        return

    for i, r in enumerate(results, 1):
        is_v = "✅ ВАКАНСИЯ" if r["is_vacancy"] else "—"
        profs = ", ".join(r["professions"]) if r["professions"] else "—"
        author = r.get("author", "—")
        links = ""
        if r.get("msg_link"):
            links += f'\n🔗 <a href="{r["msg_link"]}">Сообщение</a>'
        if r.get("author_link"):
            links += f' | <a href="{r["author_link"]}">Автор</a>'
        await message.answer(
            f"<b>#{i}</b> [{r['source']}] {r['date']}\n"
            f"{is_v} | Профессии: {profs}\n"
            f"👤 {author}{links}\n\n"
            f"<i>{r['text'][:400]}</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )


@router.message(Command("test_vacancy"))
async def cmd_test_vacancy(message: Message):
    if not _is_admin(message.from_user.id):
        return
    from bot.monitor.classifier import classify_vacancy, is_vacancy

    test_text = (
        "🔥 Ищу таргетолога для настройки рекламы в Instagram!\n\n"
        "Задачи: настройка таргетированной рекламы, ведение РК\n"
        "Бюджет: от 20 000 руб/мес. Удалённо. Пишите в ЛС!"
    )
    is_v = is_vacancy(test_text)
    profs = classify_vacancy(test_text)
    await message.answer(
        f"🧪 <b>Тест классификатора</b>\n\n"
        f"<i>{test_text}</i>\n\n"
        f"Вакансия: {'✅' if is_v else '❌'}\n"
        f"Профессии: {', '.join(profs) if profs else '—'}",
        parse_mode="HTML"
    )


# --- Тарифы ---

@router.message(Command("prices"))
async def cmd_prices(message: Message):
    if not _is_admin(message.from_user.id):
        return
    plans = await db.get_plans()
    lines = ["💰 <b>Текущие тарифы</b>\n"]
    for pid, p in plans.items():
        lines.append(f"<b>{p['name']}</b> ({pid}): {p['price']}₽ / {p['stars']}⭐ / {p['days']} дн.")
    lines.append(f"\nИзменить: /set_price &lt;plan&gt; &lt;rub&gt; &lt;stars&gt;")
    lines.append(f"Пример: <code>/set_price week 500 80</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("set_price"))
async def cmd_set_price(message: Message):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    # /set_price week 500 80
    if len(parts) != 4:
        await message.answer(
            "Использование: <code>/set_price plan rub stars</code>\n"
            "Пример: <code>/set_price week 500 80</code>\n\n"
            "Доступные планы: week, month, quarter",
            parse_mode="HTML"
        )
        return

    plan_id, rub, stars = parts[1], parts[2], parts[3]
    plans = await db.get_plans()

    if plan_id not in plans:
        await message.answer(f"❌ План <code>{plan_id}</code> не найден. Доступные: week, month, quarter", parse_mode="HTML")
        return

    try:
        rub = int(rub)
        stars = int(stars)
    except ValueError:
        await message.answer("❌ Цена и звёзды должны быть числами")
        return

    plans[plan_id]["price"] = rub
    plans[plan_id]["stars"] = stars
    await db.set_plans(plans)

    await message.answer(
        f"✅ Тариф <b>{plans[plan_id]['name']}</b> обновлён:\n"
        f"{rub}₽ / {stars}⭐",
        parse_mode="HTML"
    )


# --- Рассылка ---

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not _is_admin(message.from_user.id):
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Использование: /broadcast <текст>")
        return
    users = await db.get_all_users()
    sent, failed = 0, 0
    for uid in users:
        try:
            await message.bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Отправлено: {sent}, ❌ Ошибок: {failed}")


# --- Анализ чатов ---

@router.message(Command("analyze"))
async def cmd_analyze(message: Message):
    """Выгрузить последние 200 сообщений из каждого чата-источника"""
    if not _is_admin(message.from_user.id):
        return
    if not _monitor or not _monitor._authorized:
        await message.answer("❌ Мониторинг не авторизован")
        return
    if not _monitor._resolved_chats:
        await message.answer("❌ Нет подключённых чатов")
        return

    await message.answer("⏳ Выгружаю по 200 сообщений из каждого чата...")

    all_data = {}
    for chat_ref, chat_id in _monitor._resolved_chats.items():
        messages = []
        try:
            async for msg in _monitor.client.get_chat_history(chat_id, limit=200):
                text = msg.text or msg.caption or ""
                if not text or len(text) < 20:
                    continue

                author = ""
                author_username = ""
                if msg.from_user:
                    author = msg.from_user.first_name or ""
                    author_username = msg.from_user.username or ""

                messages.append({
                    "id": msg.id,
                    "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
                    "text": text[:2000],
                    "author": author,
                    "author_username": author_username,
                })
        except Exception as e:
            logger.error(f"Ошибка анализа {chat_ref}: {e}")
            messages = [{"error": str(e)}]

        all_data[chat_ref] = messages

    total = sum(len(v) for v in all_data.values())

    # Сохраняем в файл и отправляем
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(all_data, tmp, ensure_ascii=False, indent=2)
    tmp.close()

    try:
        doc = FSInputFile(tmp.name, filename="chat_analysis.json")
        await message.answer_document(
            doc,
            caption=f"📊 Выгружено {total} сообщений из {len(all_data)} чатов"
        )
    finally:
        os.unlink(tmp.name)


# --- Авторизация Pyrogram ---

@router.message(Command("code"))
async def cmd_code(message: Message):
    if not _is_admin(message.from_user.id):
        return
    if not _monitor:
        await message.answer("❌ Монитор не инициализирован")
        return
    code = message.text.replace("/code", "", 1).strip()
    if not code:
        await message.answer("Использование: <code>/code 12345</code>", parse_mode="HTML")
        return
    result = await _monitor.submit_code(code)
    await message.answer(result, parse_mode="HTML")


@router.message(Command("password"))
async def cmd_password(message: Message):
    if not _is_admin(message.from_user.id):
        return
    if not _monitor:
        await message.answer("❌ Монитор не инициализирован")
        return
    password = message.text.replace("/password", "", 1).strip()
    if not password:
        await message.answer("Использование: <code>/password пароль</code>", parse_mode="HTML")
        return
    result = await _monitor.submit_password(password)
    await message.answer(result, parse_mode="HTML")
    try:
        await message.delete()
    except Exception:
        pass
