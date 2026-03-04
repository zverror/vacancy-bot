"""Админские команды: /stats, /broadcast"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot import database as db
from bot.config import ADMIN_IDS

router = Router()
logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Статистика бота"""
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
    """Рассылка всем пользователям"""
    if not _is_admin(message.from_user.id):
        return

    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Использование: /broadcast <текст сообщения>")
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
    logger.info(f"Broadcast: sent={sent}, failed={failed}, by={message.from_user.id}")
