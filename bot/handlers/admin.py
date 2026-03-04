"""Админские команды: /stats, /broadcast, /code, /password, /sources, /test_vacancy"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot import database as db
from bot.config import ADMIN_IDS, SOURCE_CHATS

router = Router()
logger = logging.getLogger(__name__)

_monitor = None

def set_monitor(monitor):
    global _monitor
    _monitor = monitor


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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


@router.message(Command("sources"))
async def cmd_sources(message: Message):
    """Список чатов-источников"""
    if not _is_admin(message.from_user.id):
        return

    lines = ["📡 <b>Чаты-источники</b>\n"]
    for ref in SOURCE_CHATS:
        connected = False
        if _monitor and ref in _monitor._resolved_chats:
            connected = True
        status = "✅" if connected else "❌"
        lines.append(f"{status} <code>{ref}</code>")

    lines.append(
        f"\n📊 Подключено: {len(_monitor._resolved_chats) if _monitor else 0}/{len(SOURCE_CHATS)}\n\n"
        "ℹ️ Источники задаются в коде (config.py).\n"
        "Для добавления нового чата — обратитесь к разработчику."
    )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("test_vacancy"))
async def cmd_test_vacancy(message: Message):
    """Отправляет тестовую вакансию админу для проверки"""
    if not _is_admin(message.from_user.id):
        return

    from bot.monitor.classifier import classify_vacancy, is_vacancy

    test_text = (
        "🔥 Ищу таргетолога для настройки рекламы в Instagram!\n\n"
        "Задачи:\n"
        "— Настройка таргетированной рекламы\n"
        "— Ведение рекламного кабинета\n"
        "— Оптимизация кампаний\n\n"
        "Бюджет: от 20 000 руб/мес\n"
        "Формат: удалённо\n"
        "Пишите в ЛС!"
    )

    is_v = is_vacancy(test_text)
    profs = classify_vacancy(test_text)

    await message.answer(
        f"🧪 <b>Тест классификатора</b>\n\n"
        f"Текст:\n<i>{test_text[:500]}</i>\n\n"
        f"Является вакансией: {'✅ Да' if is_v else '❌ Нет'}\n"
        f"Профессии: {', '.join(profs) if profs else 'не определены'}\n\n"
        f"{'✅ Классификатор работает!' if is_v and profs else '⚠️ Проблема с классификатором'}",
        parse_mode="HTML"
    )


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
    logger.info(f"Broadcast: sent={sent}, failed={failed}")


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
        await message.answer("Использование: <code>/password ваш_пароль</code>", parse_mode="HTML")
        return
    result = await _monitor.submit_password(password)
    await message.answer(result, parse_mode="HTML")
    try:
        await message.delete()
    except Exception:
        pass
