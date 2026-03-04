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
