"""Telethon userbot — мониторинг чатов-источников вакансий"""
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat
from aiogram import Bot

from bot.config import API_ID, API_HASH, PHONE, SOURCE_CHATS
from bot import database as db
from bot.monitor.classifier import classify_vacancy, is_vacancy

logger = logging.getLogger(__name__)


class VacancyMonitor:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.client = TelegramClient(
            "vacancy_monitor",
            API_ID,
            API_HASH,
            system_version="4.16.30-vxCUSTOM"
        )
        self._resolved_chats: dict[str, int] = {}

    async def start(self):
        """Запуск Telethon клиента и мониторинга"""
        logger.info("Запуск мониторинга чатов...")

        await self.client.start(phone=PHONE)
        logger.info("Telethon авторизован")

        # Резолвим чаты
        await self._resolve_chats()

        if not self._resolved_chats:
            logger.error("Не удалось подключиться ни к одному чату-источнику!")
            return

        # Регистрируем обработчик новых сообщений
        chat_ids = list(self._resolved_chats.values())

        @self.client.on(events.NewMessage(chats=chat_ids))
        async def on_new_message(event):
            await self._handle_message(event)

        logger.info(f"Мониторинг запущен для {len(chat_ids)} чатов: {list(self._resolved_chats.keys())}")

    async def _resolve_chats(self):
        """Подключаемся к чатам-источникам"""
        for chat_ref in SOURCE_CHATS:
            try:
                if chat_ref.startswith("+"):
                    # Invite link — пробуем получить через хеш
                    from telethon.tl.functions.messages import CheckChatInviteRequest
                    try:
                        result = await self.client(CheckChatInviteRequest(hash=chat_ref.lstrip("+")))
                        if hasattr(result, "chat"):
                            self._resolved_chats[chat_ref] = result.chat.id
                            logger.info(f"Чат {chat_ref}: подключён (id={result.chat.id})")
                        else:
                            logger.warning(f"Чат {chat_ref}: не удалось получить ID, попробуйте вступить вручную")
                    except Exception as e:
                        logger.warning(f"Чат {chat_ref}: ошибка invite — {e}")
                else:
                    entity = await self.client.get_entity(chat_ref)
                    self._resolved_chats[chat_ref] = entity.id
                    logger.info(f"Чат {chat_ref}: подключён (id={entity.id})")
            except Exception as e:
                logger.error(f"Чат {chat_ref}: не удалось подключиться — {e}")

    async def _handle_message(self, event):
        """Обработка нового сообщения из чата"""
        try:
            text = event.message.text or event.message.message or ""
            if not text:
                return

            # Проверяем, похоже ли на вакансию
            if not is_vacancy(text):
                return

            # Классифицируем по профессиям
            professions = classify_vacancy(text)
            if not professions:
                return

            # Определяем источник
            chat = await event.get_chat()
            source = getattr(chat, "username", "") or str(chat.id)

            # Формируем ссылку на оригинал
            if hasattr(chat, "username") and chat.username:
                link = f"https://t.me/{chat.username}/{event.message.id}"
            else:
                link = ""

            # Сохраняем вакансию
            vacancy_id = await db.add_vacancy(
                source_chat=source,
                message_id=event.message.id,
                text=text[:4000],  # обрезаем если слишком длинное
                professions=professions,
                link=link
            )

            if vacancy_id is None:
                return  # дубликат

            logger.info(f"Новая вакансия #{vacancy_id}: {professions} из {source}")

            # Рассылаем подписчикам
            await self._broadcast_vacancy(vacancy_id, text, professions, link)

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

    async def _broadcast_vacancy(self, vacancy_id: int, text: str,
                                  professions: list[str], link: str):
        """Рассылка вакансии подписчикам с нужными профессиями"""
        # Собираем уникальных пользователей
        user_ids = set()
        for prof in professions:
            users = await db.get_users_by_profession(prof)
            user_ids.update(users)

        if not user_ids:
            return

        # Формируем сообщение
        prof_tags = " ".join(f"#{p.replace('.', '').replace(' ', '_')}" for p in professions)
        msg_text = f"📌 <b>Новая вакансия</b>\n{prof_tags}\n\n{text[:3500]}"

        # Кнопка «Откликнуться»
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = None
        if link:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📩 Откликнуться", url=link)]
            ])

        sent = 0
        for uid in user_ids:
            try:
                await self.bot.send_message(uid, msg_text, parse_mode="HTML", reply_markup=keyboard)
                await db.mark_vacancy_sent(uid, vacancy_id)
                sent += 1
                await asyncio.sleep(0.05)  # anti-flood
            except Exception as e:
                logger.debug(f"Не удалось отправить вакансию #{vacancy_id} пользователю {uid}: {e}")

        logger.info(f"Вакансия #{vacancy_id} отправлена {sent}/{len(user_ids)} пользователям")

    async def stop(self):
        """Остановка клиента"""
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Telethon отключён")
