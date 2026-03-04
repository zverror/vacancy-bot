"""Telethon userbot — мониторинг чатов-источников вакансий.

Авторизация через Telegram-бота (команда /code) — не требует stdin.
"""
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
)
from aiogram import Bot

from bot.config import API_ID, API_HASH, PHONE, SOURCE_CHATS, ADMIN_IDS, DB_PATH
from bot import database as db
from bot.monitor.classifier import classify_vacancy, is_vacancy
from pathlib import Path

logger = logging.getLogger(__name__)


class VacancyMonitor:
    def __init__(self, bot: Bot):
        self.bot = bot
        session_path = str(Path(DB_PATH).parent / "vacancy_monitor")
        self.client = TelegramClient(
            session_path,
            API_ID,
            API_HASH,
            system_version="4.16.30-vxCUSTOM"
        )
        self._resolved_chats: dict[str, int] = {}
        self._auth_code_future: asyncio.Future | None = None
        self._password_future: asyncio.Future | None = None
        self._authorized = False

    async def start(self):
        """Запуск Telethon клиента и мониторинга"""
        logger.info("Запуск мониторинга чатов...")

        await self.client.connect()

        if await self.client.is_user_authorized():
            logger.info("Telethon: сессия активна, авторизация не нужна")
            self._authorized = True
            await self._setup_monitoring()
        else:
            logger.info("Telethon: требуется авторизация. Отправляю запрос кода...")
            await self._request_auth_code()

    async def _request_auth_code(self):
        """Запрашиваем код авторизации и просим админа ввести его через бота"""
        if not PHONE:
            logger.error("PHONE не задан в .env! Мониторинг недоступен.")
            await self._notify_admins(
                "❌ <b>Мониторинг не запущен</b>\n\n"
                "Переменная PHONE не задана. Добавьте номер телефона в настройки."
            )
            return

        try:
            sent = await self.client.send_code_request(PHONE)
            code_type = type(sent.type).__name__
            logger.info(f"Код авторизации отправлен на {PHONE}, тип: {code_type}")

            type_desc = {
                "SentCodeTypeApp": "📱 Код отправлен в приложение Telegram (чат «Telegram»)",
                "SentCodeTypeSms": "📩 Код отправлен по SMS",
                "SentCodeTypeCall": "📞 Код придёт звонком",
                "SentCodeTypeFlashCall": "📞 Код = последние цифры входящего номера",
                "SentCodeTypeMissedCall": "📞 Код = последние цифры пропущенного звонка",
                "SentCodeTypeFragmentSms": "📩 Код отправлен через Fragment SMS",
                "SentCodeTypeEmailCode": "📧 Код отправлен на email",
            }.get(code_type, f"❓ Неизвестный тип: {code_type}")

            await self._notify_admins(
                "🔐 <b>Требуется авторизация Telethon</b>\n\n"
                f"Номер: {PHONE}\n"
                f"{type_desc}\n\n"
                "Введите код командой:\n"
                "<code>/code 12345</code>\n\n"
                "Если потребуется пароль 2FA:\n"
                "<code>/password ваш_пароль</code>"
            )

        except FloodWaitError as e:
            wait = e.seconds
            logger.warning(f"FloodWait: ждём {wait} секунд перед повторным запросом кода")
            await self._notify_admins(
                f"⏳ <b>Telegram требует подождать {wait} сек</b>\n\n"
                f"Повторный запрос кода через {wait} секунд. Ожидайте."
            )
            await asyncio.sleep(wait)
            await self._request_auth_code()

        except Exception as e:
            logger.error(f"Ошибка запроса кода: {e}")
            await self._notify_admins(f"❌ Ошибка авторизации: {e}")

    async def submit_code(self, code: str) -> str:
        """Админ вводит код через бота. Возвращает результат."""
        try:
            await self.client.sign_in(PHONE, code)
            self._authorized = True
            logger.info("Telethon: авторизация успешна!")
            await self._setup_monitoring()
            return "✅ Авторизация успешна! Мониторинг запущен."

        except SessionPasswordNeededError:
            logger.info("Telethon: требуется пароль 2FA")
            return "🔐 Требуется пароль 2FA. Введите:\n<code>/password ваш_пароль</code>"

        except PhoneCodeInvalidError:
            return "❌ Неверный код. Попробуйте ещё раз: /code 12345"

        except PhoneCodeExpiredError:
            await self._request_auth_code()
            return "⏰ Код истёк. Запросил новый — проверьте Telegram."

        except FloodWaitError as e:
            return f"⏳ Telegram требует подождать {e.seconds} сек. Попробуйте позже."

        except Exception as e:
            logger.error(f"Ошибка sign_in: {e}")
            return f"❌ Ошибка: {e}"

    async def submit_password(self, password: str) -> str:
        """Админ вводит пароль 2FA через бота."""
        try:
            await self.client.sign_in(password=password)
            self._authorized = True
            logger.info("Telethon: 2FA авторизация успешна!")
            await self._setup_monitoring()
            return "✅ Авторизация с 2FA успешна! Мониторинг запущен."

        except Exception as e:
            logger.error(f"Ошибка 2FA: {e}")
            return f"❌ Ошибка: {e}"

    async def _setup_monitoring(self):
        """Настройка мониторинга после успешной авторизации"""
        await self._resolve_chats()

        if not self._resolved_chats:
            logger.error("Не удалось подключиться ни к одному чату-источнику!")
            await self._notify_admins("⚠️ Не удалось подключиться ни к одному чату-источнику!")
            return

        chat_ids = list(self._resolved_chats.values())

        @self.client.on(events.NewMessage(chats=chat_ids))
        async def on_new_message(event):
            await self._handle_message(event)

        chat_names = list(self._resolved_chats.keys())
        logger.info(f"Мониторинг запущен для {len(chat_ids)} чатов: {chat_names}")
        await self._notify_admins(
            f"✅ <b>Мониторинг запущен</b>\n\n"
            f"Чаты ({len(chat_ids)}): {', '.join(chat_names)}"
        )

    async def _resolve_chats(self):
        """Подключаемся к чатам-источникам"""
        for chat_ref in SOURCE_CHATS:
            try:
                if chat_ref.startswith("+"):
                    from telethon.tl.functions.messages import CheckChatInviteRequest
                    try:
                        result = await self.client(CheckChatInviteRequest(hash=chat_ref.lstrip("+")))
                        if hasattr(result, "chat"):
                            self._resolved_chats[chat_ref] = result.chat.id
                            logger.info(f"Чат {chat_ref}: подключён (id={result.chat.id})")
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

            if not is_vacancy(text):
                return

            professions = classify_vacancy(text)
            if not professions:
                return

            chat = await event.get_chat()
            source = getattr(chat, "username", "") or str(chat.id)

            if hasattr(chat, "username") and chat.username:
                link = f"https://t.me/{chat.username}/{event.message.id}"
            else:
                link = ""

            vacancy_id = await db.add_vacancy(
                source_chat=source,
                message_id=event.message.id,
                text=text[:4000],
                professions=professions,
                link=link
            )

            if vacancy_id is None:
                return

            logger.info(f"Новая вакансия #{vacancy_id}: {professions} из {source}")
            await self._broadcast_vacancy(vacancy_id, text, professions, link)

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

    async def _broadcast_vacancy(self, vacancy_id: int, text: str,
                                  professions: list[str], link: str):
        """Рассылка вакансии подписчикам"""
        user_ids = set()
        for prof in professions:
            users = await db.get_users_by_profession(prof)
            user_ids.update(users)

        if not user_ids:
            return

        prof_tags = " ".join(f"#{p.replace('.', '').replace(' ', '_')}" for p in professions)
        msg_text = f"📌 <b>Новая вакансия</b>\n{prof_tags}\n\n{text[:3500]}"

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
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.debug(f"Не удалось отправить #{vacancy_id} → {uid}: {e}")

        logger.info(f"Вакансия #{vacancy_id}: отправлена {sent}/{len(user_ids)}")

    async def _notify_admins(self, text: str):
        """Уведомление админов через бота"""
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Не удалось уведомить админа {admin_id}: {e}")

    async def stop(self):
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Telethon отключён")
