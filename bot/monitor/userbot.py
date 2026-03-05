"""Мониторинг чатов-источников вакансий через Pyrogram.

Pyrogram userbot подключается к чатам и слушает новые сообщения.
Авторизация через Telegram-бота (команда /code) — не требует stdin.
"""
import logging
import asyncio
import hashlib
import re
from pyrogram import Client, filters
from pyrogram.errors import (
    SessionPasswordNeeded,
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    UserAlreadyParticipant,
    InviteHashExpired,
    InviteHashInvalid,
    ChannelPrivate,
)
from aiogram import Bot

from bot.config import API_ID, API_HASH, PHONE, ADMIN_IDS, DB_PATH
from bot import database as db
from bot.monitor.classifier import classify_vacancy, is_vacancy
from pathlib import Path

logger = logging.getLogger(__name__)


def _text_hash(text: str) -> str:
    """Нормализует текст и возвращает SHA-256 хэш для дедупликации."""
    # Убираем пробелы, переносы, приводим к нижнему регистру
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    # Берём первые 500 символов — достаточно для идентификации
    normalized = normalized[:500]
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]


class VacancyMonitor:
    def __init__(self, bot: Bot):
        self.bot = bot
        session_dir = Path(DB_PATH).parent.resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[INIT] workdir={session_dir}, name=pyrogram_session")
        self.client = Client(
            name="pyrogram_session",
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=str(session_dir),
        )
        self._resolved_chats: dict[str, int] = {}
        self._phone_code_hash: str = ""
        self._authorized = False

    async def start(self):
        """Запуск Pyrogram клиента и мониторинга"""
        logger.info("Запуск мониторинга чатов (Pyrogram)...")

        await self.client.connect()

        if not await self.client.storage.is_bot() and await self.client.storage.user_id():
            # Проверяем, авторизована ли сессия
            try:
                me = await self.client.get_me()
                logger.info(f"Pyrogram: сессия активна, user={me.first_name} ({me.phone_number})")
                self._authorized = True
                await self._setup_monitoring()
            except Exception:
                logger.info("Pyrogram: сессия невалидна, требуется авторизация")
                await self._request_auth_code()
        else:
            logger.info("Pyrogram: требуется авторизация")
            await self._request_auth_code()

    async def _request_auth_code(self):
        """Запрашиваем код авторизации"""
        if not PHONE:
            logger.error("PHONE не задан! Мониторинг недоступен.")
            await self._notify_admins(
                "❌ <b>Мониторинг не запущен</b>\n\n"
                "Переменная PHONE не задана."
            )
            return

        try:
            logger.info(f"[AUTH] Отправляю send_code на {PHONE}...")
            sent = await self.client.send_code(PHONE)
            self._phone_code_hash = sent.phone_code_hash
            code_type = sent.type.name if hasattr(sent.type, 'name') else str(sent.type)
            logger.info(f"[AUTH] Код отправлен! Тип: {code_type}")

            await self._notify_admins(
                "🔐 <b>Требуется авторизация мониторинга</b>\n\n"
                f"Код отправлен на <code>{PHONE}</code>\n"
                f"Способ: {code_type}\n\n"
                "Введите код командой:\n"
                "<code>/code 12345</code>\n\n"
                "Если потребуется пароль 2FA:\n"
                "<code>/password ваш_пароль</code>"
            )

        except FloodWait as e:
            wait = e.value
            logger.warning(f"FloodWait: ждём {wait} сек")
            await self._notify_admins(
                f"⏳ <b>Telegram требует подождать {wait} сек</b>\n"
                f"Повторный запрос через {wait} сек."
            )
            await asyncio.sleep(wait)
            await self._request_auth_code()

        except Exception as e:
            logger.error(f"Ошибка send_code: {e}", exc_info=True)
            await self._notify_admins(f"❌ Ошибка авторизации: <code>{e}</code>")

    async def submit_code(self, code: str) -> str:
        """Админ вводит код через бота."""
        try:
            await self.client.sign_in(PHONE, self._phone_code_hash, code)
            self._authorized = True
            logger.info("Pyrogram: авторизация успешна!")
            await self._setup_monitoring()
            return "✅ Авторизация успешна! Мониторинг запущен."

        except SessionPasswordNeeded:
            logger.info("Pyrogram: требуется пароль 2FA")
            return "🔐 Требуется пароль 2FA. Введите:\n<code>/password ваш_пароль</code>"

        except PhoneCodeInvalid:
            return "❌ Неверный код. Попробуйте ещё раз: /code 12345"

        except PhoneCodeExpired:
            await self._request_auth_code()
            return "⏰ Код истёк. Запросил новый — проверьте Telegram."

        except FloodWait as e:
            return f"⏳ Telegram требует подождать {e.value} сек."

        except Exception as e:
            logger.error(f"Ошибка sign_in: {e}", exc_info=True)
            return f"❌ Ошибка: <code>{e}</code>"

    async def submit_password(self, password: str) -> str:
        """Админ вводит пароль 2FA."""
        try:
            await self.client.check_password(password)
            self._authorized = True
            logger.info("Pyrogram: 2FA авторизация успешна!")
            await self._setup_monitoring()
            return "✅ Авторизация с 2FA успешна! Мониторинг запущен."

        except Exception as e:
            logger.error(f"Ошибка 2FA: {e}", exc_info=True)
            return f"❌ Ошибка: <code>{e}</code>"

    async def reload_sources(self):
        """Перезагрузить источники из БД и переподключиться"""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        self._resolved_chats.clear()
        await self._setup_monitoring()
        return f"✅ Переподключено чатов: {len(self._resolved_chats)}"

    async def join_source(self, chat_ref: str) -> str:
        """Подписаться на группу-источник."""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            logger.info(f"Подписались на {chat_ref} (id={chat.id})")
            # Перерегистрируем обработчик на обновлённый список
            await self._setup_monitoring()
            return f"✅ Подписались на {chat_ref}"
        except UserAlreadyParticipant:
            # Уже подписаны — просто резолвим
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
                await self._setup_monitoring()
                return f"✅ Уже подписаны на {chat_ref}"
            except Exception as e:
                return f"⚠️ Уже подписаны, но ошибка резолва: {e}"
        except (InviteHashExpired, InviteHashInvalid):
            return f"❌ Ссылка-приглашение невалидна: {chat_ref}"
        except ChannelPrivate:
            return f"❌ Приватный канал, доступ закрыт: {chat_ref}"
        except FloodWait as e:
            return f"⏳ Telegram требует подождать {e.value} сек"
        except Exception as e:
            logger.error(f"Ошибка join {chat_ref}: {e}", exc_info=True)
            return f"❌ Не удалось подписаться: {e}"

    async def leave_source(self, chat_ref: str) -> str:
        """Отписаться от группы-источника."""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        chat_id = self._resolved_chats.get(chat_ref)
        if chat_id:
            try:
                await self.client.leave_chat(chat_id)
                logger.info(f"Отписались от {chat_ref} (id={chat_id})")
            except Exception as e:
                logger.warning(f"Ошибка leave {chat_ref}: {e}")
            self._resolved_chats.pop(chat_ref, None)
        else:
            # Пробуем резолвить и уйти
            try:
                chat = await self.client.get_chat(chat_ref)
                await self.client.leave_chat(chat.id)
                logger.info(f"Отписались от {chat_ref}")
            except Exception as e:
                logger.warning(f"Не удалось отписаться от {chat_ref}: {e}")
        await self._setup_monitoring()
        return f"✅ Отписались от {chat_ref}"

    async def check_subscriptions(self):
        """Проверяет подписку на все группы из БД. Подписывается, если не подписан."""
        if not self._authorized:
            return
        sources = await db.get_sources()
        for chat_ref in sources:
            if chat_ref in self._resolved_chats:
                # Проверяем что подписка ещё активна
                try:
                    await self.client.get_chat(self._resolved_chats[chat_ref])
                except ChannelPrivate:
                    logger.warning(f"Потеряли доступ к {chat_ref}, переподключаемся...")
                    await self._try_join(chat_ref)
                except Exception:
                    pass
            else:
                # Не подписаны — подписываемся
                logger.info(f"Не подписаны на {chat_ref}, подписываемся...")
                await self._try_join(chat_ref)

    async def _try_join(self, chat_ref: str):
        """Попытка подписаться на чат (тихо, для фоновой проверки)."""
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            logger.info(f"Авто-подписка: {chat_ref} (id={chat.id})")
            await self._notify_admins(f"🔄 Авто-подписка на <code>{chat_ref}</code>")
        except UserAlreadyParticipant:
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
            except Exception:
                pass
        except FloodWait as e:
            logger.warning(f"FloodWait при join {chat_ref}: {e.value} сек")
        except Exception as e:
            logger.warning(f"Авто-подписка {chat_ref} не удалась: {e}")

    async def fetch_recent_from_sources(self, limit: int = 10) -> list[dict]:
        """Получить последние сообщения из чатов-источников через Pyrogram"""
        results = []
        for chat_ref, chat_id in self._resolved_chats.items():
            try:
                async for msg in self.client.get_chat_history(chat_id, limit=limit):
                    text = msg.text or msg.caption or ""
                    if text:
                        # Ссылка на сообщение
                        chat = msg.chat
                        if chat.username:
                            msg_link = f"https://t.me/{chat.username}/{msg.id}"
                        else:
                            msg_link = ""

                        # Автор
                        author = ""
                        author_link = ""
                        if msg.from_user:
                            author = msg.from_user.first_name or ""
                            if msg.from_user.username:
                                author = f"@{msg.from_user.username}"
                                author_link = f"https://t.me/{msg.from_user.username}"

                        results.append({
                            "source": chat_ref,
                            "text": text[:500],
                            "date": msg.date.strftime("%d.%m %H:%M") if msg.date else "",
                            "is_vacancy": is_vacancy(text),
                            "professions": classify_vacancy(text),
                            "msg_link": msg_link,
                            "author": author,
                            "author_link": author_link,
                        })
            except Exception as e:
                logger.warning(f"Ошибка получения истории {chat_ref}: {e}")
        results.sort(key=lambda x: x.get("date", ""), reverse=True)
        return results[:limit]

    async def _setup_monitoring(self):
        """Настройка мониторинга после авторизации"""
        source_chats = await db.get_sources()
        if not source_chats:
            logger.warning("Нет источников в БД!")
            await self._notify_admins("⚠️ Нет источников! Добавьте через /add_source")
            return

        for chat_ref in source_chats:
            await self._resolve_chat(chat_ref)

        if not self._resolved_chats:
            logger.error("Не удалось подключиться ни к одному чату!")
            await self._notify_admins("⚠️ Не удалось подключиться ни к одному чату-источнику!")
            return

        chat_ids = list(self._resolved_chats.values())

        @self.client.on_message(filters.chat(chat_ids))
        async def on_new_message(client, message):
            await self._handle_message(message)

        chat_names = list(self._resolved_chats.keys())
        logger.info(f"Мониторинг запущен: {len(chat_ids)} чатов: {chat_names}")
        await self._notify_admins(
            f"✅ <b>Мониторинг запущен</b>\n\n"
            f"Чаты ({len(chat_ids)}): {', '.join(chat_names)}"
        )

    async def _resolve_chat(self, chat_ref: str):
        """Подключаемся к чату — всегда пробуем join_chat (подписка + резолв)."""
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            logger.info(f"Чат {chat_ref}: подписались (id={chat.id})")
        except UserAlreadyParticipant:
            # Уже подписаны — просто резолвим
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
                logger.info(f"Чат {chat_ref}: уже подписаны (id={chat.id})")
            except Exception as e:
                logger.error(f"Чат {chat_ref}: подписаны, но ошибка резолва — {e}")
        except FloodWait as e:
            logger.warning(f"Чат {chat_ref}: FloodWait {e.value} сек")
        except (InviteHashExpired, InviteHashInvalid):
            logger.error(f"Чат {chat_ref}: ссылка-приглашение невалидна")
        except ChannelPrivate:
            logger.error(f"Чат {chat_ref}: приватный, доступ закрыт")
        except Exception as e:
            logger.error(f"Чат {chat_ref}: не удалось подключиться — {e}")

    async def _handle_message(self, message):
        """Обработка нового сообщения"""
        try:
            text = message.text or message.caption or ""
            if not text:
                return

            if not is_vacancy(text):
                return

            professions = classify_vacancy(text)
            if not professions:
                return

            chat = message.chat
            source = chat.username or str(chat.id)
            msg_link = f"https://t.me/{chat.username}/{message.id}" if chat.username else ""

            # Автор сообщения
            author = ""
            author_link = ""
            if message.from_user:
                if message.from_user.username:
                    author = f"@{message.from_user.username}"
                    author_link = f"https://t.me/{message.from_user.username}"
                else:
                    author = message.from_user.first_name or "Аноним"

            # Дедупликация по хэшу текста (одна вакансия из разных сообщений)
            t_hash = _text_hash(text)
            if await db.vacancy_hash_exists(t_hash):
                logger.debug(f"Дубликат вакансии (hash={t_hash[:8]}...) из {source}")
                return

            vacancy_id = await db.add_vacancy(
                source_chat=source,
                message_id=message.id,
                text=text[:4000],
                professions=professions,
                link=msg_link,
                text_hash=t_hash
            )

            if vacancy_id is None:
                return

            logger.info(f"Новая вакансия #{vacancy_id}: {professions} из {source}")
            await self._broadcast_vacancy(vacancy_id, text, professions, msg_link, author, author_link)

        except Exception as e:
            logger.error(f"Ошибка обработки: {e}", exc_info=True)

    async def _broadcast_vacancy(self, vacancy_id: int, text: str,
                                  professions: list[str], msg_link: str,
                                  author: str = "", author_link: str = ""):
        """Рассылка вакансии подписчикам"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        user_ids = set()
        for prof in professions:
            users = await db.get_users_by_profession(prof)
            user_ids.update(users)

        if not user_ids:
            return

        prof_tags = " ".join(f"#{p.replace('.', '').replace(' ', '_')}" for p in professions)

        # Формируем текст с автором
        author_text = ""
        if author_link:
            author_text = f"\n\n👤 Автор: <a href=\"{author_link}\">{author}</a>"
        elif author:
            author_text = f"\n\n👤 Автор: {author}"

        msg_text = f"📌 <b>Новая вакансия</b>\n{prof_tags}\n\n{text[:3200]}{author_text}"

        # Кнопки
        buttons = []
        if msg_link:
            buttons.append([InlineKeyboardButton(text="💬 Сообщение в чате", url=msg_link)])
        if author_link:
            buttons.append([InlineKeyboardButton(text="📩 Написать автору", url=author_link)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

        # Параллельная рассылка батчами по 25 (лимит Telegram ~30 msg/sec)
        BATCH_SIZE = 25
        user_list = list(user_ids)
        sent = 0

        for i in range(0, len(user_list), BATCH_SIZE):
            batch = user_list[i:i + BATCH_SIZE]
            tasks = []
            for uid in batch:
                tasks.append(self._send_vacancy_to_user(uid, vacancy_id, msg_text, keyboard))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            sent += sum(1 for r in results if r is True)
            # Пауза между батчами — уважаем лимиты Telegram
            if i + BATCH_SIZE < len(user_list):
                await asyncio.sleep(1.0)

        logger.info(f"Вакансия #{vacancy_id}: отправлена {sent}/{len(user_ids)}")

    async def _send_vacancy_to_user(self, uid: int, vacancy_id: int,
                                     msg_text: str, keyboard) -> bool:
        try:
            await self.bot.send_message(
                uid, msg_text, parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            await db.mark_vacancy_sent(uid, vacancy_id)
            return True
        except Exception as e:
            logger.debug(f"Не удалось отправить #{vacancy_id} → {uid}: {e}")
            return False

    async def _notify_admins(self, text: str):
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Не удалось уведомить админа {admin_id}: {e}")

    async def stop(self):
        if self.client.is_connected:
            await self.client.disconnect()
            logger.info("Pyrogram отключён")
