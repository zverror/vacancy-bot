"""Админские команды: /stats, /broadcast, /code, /password"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
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


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_admin(message.from_user.id):
        return
    stats = await db.get_stats()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💰 Активных подписок: {stats['active_subs']}\n"
        f"📌 Вакансий найдено: {stats['vacancies']}\n"
        f"📨 Вакансий отправлено: {stats['sent']}\n"
        f"💵 Платежей: {stats['payments']}",
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
