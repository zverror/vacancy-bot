"""Админские команды: /stats, /broadcast, /code, /password"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot import database as db
from bot.config import ADMIN_IDS

router = Router()
logger = logging.getLogger(__name__)

# Ссылка на VacancyMonitor — устанавливается из main.py
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

    total = await db.get_all_users_count()
    active = await db.get_active_users_count()
    vacancies_today = await db.get_vacancies_today_count()

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей всего: {total}\n"
        f"С активной подпиской: {active}\n"
        f"Вакансий за 24ч: {vacancies_today}",
        parse_mode="HTML"
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not _is_admin(message.from_user.id):
        return

    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Использование: /broadcast <текст сообщения>")
        return

    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ Рассылка завершена: отправлено {sent}, ошибок {failed}")
    logger.info(f"Broadcast: sent={sent}, failed={failed}, by={message.from_user.id}")


@router.message(Command("code"))
async def cmd_code(message: Message):
    """Ввод кода авторизации Telethon"""
    if not _is_admin(message.from_user.id):
        return

    if not _monitor:
        await message.answer("❌ Монитор не инициализирован")
        return

    code = message.text.replace("/code", "", 1).strip()
    if not code:
        await message.answer("Использование: /code 12345")
        return

    result = await _monitor.submit_code(code)
    await message.answer(result, parse_mode="HTML")


@router.message(Command("password"))
async def cmd_password(message: Message):
    """Ввод пароля 2FA для Telethon"""
    if not _is_admin(message.from_user.id):
        return

    if not _monitor:
        await message.answer("❌ Монитор не инициализирован")
        return

    password = message.text.replace("/password", "", 1).strip()
    if not password:
        await message.answer("Использование: /password ваш_пароль")
        return

    result = await _monitor.submit_password(password)
    await message.answer(result, parse_mode="HTML")

    # Удаляем сообщение с паролем для безопасности
    try:
        await message.delete()
    except Exception:
        pass
