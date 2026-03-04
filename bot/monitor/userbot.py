"""Мониторинг чатов-источников вакансий через Bot API.

Бот добавляется в чаты как участник/админ и читает сообщения напрямую.
Не требует Telethon, авторизации по номеру или session-файлов.
"""
import logging
import asyncio
from aiogram import Bot, Router
from aiogram.types import Message

from bot.config import SOURCE_CHATS, ADMIN_IDS
from bot import database as db
from bot.monitor.classifier import classify_vacancy, is_vacancy

logger = logging.getLogger(__name__)

router = Router()


class VacancyMonitor:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._authorized = True  # Bot API не требует авторизации

    async def start(self):
        """Регистрация обработчика — вызывается из main.py"""
        logger.info(f"Мониторинг чатов через Bot API")
        logger.info(f"Чаты-источники: {SOURCE_CHATS}")
        await self._notify_admins(
            f"✅ <b>Мониторинг запущен (Bot API)</b>\n\n"
            f"Чаты ({len(SOURCE_CHATS)}): {', '.join(SOURCE_CHATS)}\n\n"
            f"⚠️ Бот должен быть добавлен в каждый чат как участник/админ."
        )

    async def stop(self):
        logger.info("Мониторинг остановлен")

    async def _notify_admins(self, text: str):
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Не удалось уведомить админа {admin_id}: {e}")


def _is_source_chat(chat_id: int, username: str | None) -> bool:
    """Проверяем, является ли чат источником вакансий"""
    for ref in SOURCE_CHATS:
        if ref.startswith("+"):
            # Invite-link hash — сравниваем по chat_id (после добавления бота)
            continue
        # @username или числовой id
        if username and ref.lstrip("@").lower() == username.lower():
            return True
        try:
            if int(ref) == chat_id:
                return True
        except ValueError:
            pass
    return False


@router.message()
async def on_group_message(message: Message):
    """Обработка всех сообщений из групп — фильтрация вакансий"""
    # Только групповые чаты
    if message.chat.type not in ("group", "supergroup"):
        return

    # Только из чатов-источников
    if not _is_source_chat(message.chat.id, message.chat.username):
        return

    text = message.text or message.caption or ""
    if not text:
        return

    if not is_vacancy(text):
        return

    professions = classify_vacancy(text)
    if not professions:
        return

    # Формируем ссылку
    link = ""
    if message.chat.username:
        link = f"https://t.me/{message.chat.username}/{message.message_id}"

    source = message.chat.username or str(message.chat.id)

    vacancy_id = await db.add_vacancy(
        source_chat=source,
        message_id=message.message_id,
        text=text[:4000],
        professions=professions,
        link=link
    )

    if vacancy_id is None:
        return

    logger.info(f"Новая вакансия #{vacancy_id}: {professions} из {source}")
    await _broadcast_vacancy(message.bot, vacancy_id, text, professions, link)


async def _broadcast_vacancy(bot: Bot, vacancy_id: int, text: str,
                              professions: list[str], link: str):
    """Рассылка вакансии подписчикам"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    user_ids = set()
    for prof in professions:
        users = await db.get_users_by_profession(prof)
        user_ids.update(users)

    if not user_ids:
        return

    prof_tags = " ".join(f"#{p.replace('.', '').replace(' ', '_')}" for p in professions)
    msg_text = f"📌 <b>Новая вакансия</b>\n{prof_tags}\n\n{text[:3500]}"

    keyboard = None
    if link:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Откликнуться", url=link)]
        ])

    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=keyboard)
            await db.mark_vacancy_sent(uid, vacancy_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.debug(f"Не удалось отправить #{vacancy_id} → {uid}: {e}")

    logger.info(f"Вакансия #{vacancy_id}: отправлена {sent}/{len(user_ids)}")
