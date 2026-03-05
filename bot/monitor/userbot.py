"""Мониторинг чатов-источников вакансий через Pyrogram.

POLLING-режим: каждые 30 секунд обходит все чаты-источники,
собирает новые сообщения через get_chat_history (обычный API-вызов).
Не зависит от dispatcher/on_message — гарантированно работает.
"""
import logging
import asyncio
import hashlib
import re
import time
from pyrogram import Client
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

# Интервал опроса чатов (секунды)
POLL_INTERVAL = 30


def _text_hash(text: str) -> str:
    """Нормализует текст и возвращает SHA-256 хэш для дедупликации."""
    normalized = re.sub(r'\s+', ' ', text.strip().lower())[:500]
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
        # Последний обработанный message_id для каждого чата (антидупликация)
        self._last_msg_ids: dict[int, int] = {}
        self._poll_task: asyncio.Task | None = None

    # ─── Запуск / авторизация ───

    async def start(self):
        """Запуск Pyrogram клиента"""
        logger.info("=== ЗАПУСК МОНИТОРИНГА (POLLING) ===")

        await self.client.connect()
        logger.info("[START] Pyrogram connected")

        if not await self.client.storage.is_bot() and await self.client.storage.user_id():
            try:
                me = await self.client.get_me()
                logger.info(f"[START] Сессия активна: {me.first_name} ({me.phone_number})")
                self._authorized = True
                await self._setup_sources()
                self._start_poll_loop()
            except Exception as e:
                logger.warning(f"[START] Сессия невалидна: {e}")
                await self._request_auth_code()
        else:
            logger.info("[START] Нет сессии, требуется авторизация")
            await self._request_auth_code()

    def _start_poll_loop(self):
        """Запускает фоновый polling-цикл."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[POLL] Polling-цикл запущен (интервал {POLL_INTERVAL}с)")

    async def _poll_loop(self):
        """Основной цикл: обходит чаты каждые POLL_INTERVAL секунд."""
        logger.info("[POLL] === Цикл polling стартовал ===")
        while True:
            try:
                if self._authorized and self._resolved_chats:
                    await self._poll_all_chats()
                else:
                    logger.debug(f"[POLL] Пропуск: authorized={self._authorized}, chats={len(self._resolved_chats)}")
            except asyncio.CancelledError:
                logger.info("[POLL] Цикл отменён")
                break
            except Exception as e:
                logger.error(f"[POLL] Ошибка в цикле: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_all_chats(self):
        """Один проход по всем чатам — собираем новые сообщения."""
        total_new = 0
        total_vacancies = 0

        for chat_ref, chat_id in list(self._resolved_chats.items()):
            try:
                new_msgs, vacancies = await self._poll_chat(chat_ref, chat_id)
                total_new += new_msgs
                total_vacancies += vacancies
            except ChannelPrivate:
                logger.warning(f"[POLL] {chat_ref}: доступ закрыт, пробуем переподписаться")
                await self._try_join(chat_ref)
            except FloodWait as e:
                logger.warning(f"[POLL] FloodWait {e.value}с, пауза...")
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.error(f"[POLL] Ошибка чата {chat_ref}: {e}")

        if total_new > 0:
            logger.info(f"[POLL] Итого: {total_new} новых сообщений, {total_vacancies} вакансий")

    async def _poll_chat(self, chat_ref: str, chat_id: int) -> tuple[int, int]:
        """Опрос одного чата. Возвращает (новых сообщений, найдено вакансий)."""
        last_id = self._last_msg_ids.get(chat_id, 0)

        messages = []
        async for msg in self.client.get_chat_history(chat_id, limit=50):
            if msg.id <= last_id:
                break
            messages.append(msg)

        if not messages:
            return 0, 0

        # Обновляем last_id
        max_id = max(m.id for m in messages)
        self._last_msg_ids[chat_id] = max_id
        logger.info(f"[POLL] {chat_ref}: {len(messages)} новых (id {last_id+1}..{max_id})")

        # Обрабатываем от старых к новым
        vacancies_found = 0
        for msg in reversed(messages):
            text = msg.text or msg.caption or ""
            if not text:
                continue

            text_preview = text[:80].replace('\n', ' ')
            is_v = is_vacancy(text)
            profs = classify_vacancy(text) if is_v else []

            logger.info(
                f"[MSG] {chat_ref} #{msg.id} | "
                f"vacancy={is_v} | profs={profs or '-'} | "
                f"\"{text_preview}...\""
            )

            if not is_v:
                continue
            if not profs:
                logger.info(f"[MSG] {chat_ref} #{msg.id} → вакансия, но профессия не определена, пропуск")
                continue

            # Дедупликация
            t_hash = _text_hash(text)
            if await db.vacancy_hash_exists(t_hash):
                logger.info(f"[MSG] {chat_ref} #{msg.id} → дубликат (hash={t_hash[:8]}), пропуск")
                continue

            # Ссылки
            source = msg.chat.username or str(msg.chat.id)
            msg_link = f"https://t.me/{msg.chat.username}/{msg.id}" if msg.chat.username else ""

            author = ""
            author_link = ""
            if msg.from_user:
                if msg.from_user.username:
                    author = f"@{msg.from_user.username}"
                    author_link = f"https://t.me/{msg.from_user.username}"
                else:
                    author = msg.from_user.first_name or "Аноним"

            vacancy_id = await db.add_vacancy(
                source_chat=source,
                message_id=msg.id,
                text=text[:4000],
                professions=profs,
                link=msg_link,
                text_hash=t_hash
            )

            if vacancy_id is None:
                logger.info(f"[MSG] {chat_ref} #{msg.id} → уже в БД (source+msg_id), пропуск")
                continue

            logger.info(f"[VACANCY] #{vacancy_id} из {chat_ref}: {profs} → рассылка...")
            await self._broadcast_vacancy(vacancy_id, text, profs, msg_link, author, author_link)
            vacancies_found += 1

        return len(messages), vacancies_found

    # ─── Управление источниками ───

    async def _setup_sources(self):
        """Подписка на все чаты из БД при старте."""
        source_chats = await db.get_sources()
        if not source_chats:
            logger.warning("[SETUP] Нет источников в БД! Добавьте через /add_source")
            await self._notify_admins("⚠️ Нет источников! Добавьте через /add_source")
            return

        logger.info(f"[SETUP] Подключаю {len(source_chats)} источников: {source_chats}")
        for chat_ref in source_chats:
            await self._resolve_chat(chat_ref)

        if self._resolved_chats:
            # Инициализируем last_msg_ids — берём текущий последний ID
            for chat_ref, chat_id in self._resolved_chats.items():
                try:
                    async for msg in self.client.get_chat_history(chat_id, limit=1):
                        self._last_msg_ids[chat_id] = msg.id
                        logger.info(f"[SETUP] {chat_ref}: last_msg_id={msg.id}")
                        break
                except Exception as e:
                    logger.warning(f"[SETUP] {chat_ref}: не удалось получить last_msg_id: {e}")

            chat_names = list(self._resolved_chats.keys())
            logger.info(f"[SETUP] Подключено: {len(self._resolved_chats)} чатов: {chat_names}")
            await self._notify_admins(
                f"✅ <b>Мониторинг запущен (polling каждые {POLL_INTERVAL}с)</b>\n\n"
                f"Чаты ({len(self._resolved_chats)}): {', '.join(chat_names)}"
            )
        else:
            logger.error("[SETUP] Не удалось подключиться ни к одному чату!")
            await self._notify_admins("⚠️ Не удалось подключиться ни к одному чату-источнику!")

    async def _resolve_chat(self, chat_ref: str):
        """Подписка + резолв чата."""
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            await self._archive_and_mute(chat.id, chat_ref)
            logger.info(f"[RESOLVE] {chat_ref}: подписались (id={chat.id})")
        except UserAlreadyParticipant:
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
                logger.info(f"[RESOLVE] {chat_ref}: уже подписаны (id={chat.id})")
            except Exception as e:
                logger.error(f"[RESOLVE] {chat_ref}: подписаны, но ошибка резолва — {e}")
        except FloodWait as e:
            logger.warning(f"[RESOLVE] {chat_ref}: FloodWait {e.value}с")
        except (InviteHashExpired, InviteHashInvalid):
            logger.error(f"[RESOLVE] {chat_ref}: ссылка невалидна")
        except ChannelPrivate:
            logger.error(f"[RESOLVE] {chat_ref}: приватный, доступ закрыт")
        except Exception as e:
            logger.error(f"[RESOLVE] {chat_ref}: ошибка — {e}")

    async def reload_sources(self):
        """Перезагрузить источники из БД."""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        self._resolved_chats.clear()
        self._last_msg_ids.clear()
        await self._setup_sources()
        return f"✅ Переподключено чатов: {len(self._resolved_chats)}"

    async def _archive_and_mute(self, chat_id: int, chat_ref: str):
        """Архивировать чат и отключить уведомления, чтобы не мешал владельцу аккаунта."""
        try:
            from pyrogram.raw.functions.folders import EditPeerFolders
            from pyrogram.raw.types import InputFolderPeer
            peer = await self.client.resolve_peer(chat_id)
            await self.client.invoke(
                EditPeerFolders(
                    folder_peers=[InputFolderPeer(peer=peer, folder_id=1)]  # 1 = Archive
                )
            )
            logger.info(f"[ARCHIVE] {chat_ref}: отправлен в архив")
        except Exception as e:
            logger.warning(f"[ARCHIVE] {chat_ref}: ошибка архивации: {e}")

        try:
            from pyrogram.raw.functions.account import UpdateNotifySettings
            from pyrogram.raw.types import InputNotifyPeer, InputPeerNotifySettings
            peer = await self.client.resolve_peer(chat_id)
            await self.client.invoke(
                UpdateNotifySettings(
                    peer=InputNotifyPeer(peer=peer),
                    settings=InputPeerNotifySettings(
                        mute_until=2147483647  # max int32 = мут навсегда
                    )
                )
            )
            logger.info(f"[MUTE] {chat_ref}: уведомления отключены")
        except Exception as e:
            logger.warning(f"[MUTE] {chat_ref}: ошибка мута: {e}")

    async def join_source(self, chat_ref: str) -> str:
        """Подписаться на новый источник."""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            # Ставим last_msg_id на текущее — не шлём старые сообщения
            try:
                async for msg in self.client.get_chat_history(chat.id, limit=1):
                    self._last_msg_ids[chat.id] = msg.id
                    break
            except Exception:
                pass
            # Архивируем и мутим — чтобы не мешало владельцу аккаунта
            await self._archive_and_mute(chat.id, chat_ref)
            logger.info(f"[JOIN] {chat_ref}: подписались (id={chat.id})")
            return f"✅ Подписались на {chat_ref} (📦 в архив, 🔇 без уведомлений)"
        except UserAlreadyParticipant:
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
                # Тоже архивируем на случай если раньше не было
                await self._archive_and_mute(chat.id, chat_ref)
                return f"✅ Уже подписаны на {chat_ref} (📦 в архив)"
            except Exception as e:
                return f"⚠️ Уже подписаны, ошибка резолва: {e}"
        except (InviteHashExpired, InviteHashInvalid):
            return f"❌ Ссылка невалидна: {chat_ref}"
        except ChannelPrivate:
            return f"❌ Приватный канал: {chat_ref}"
        except FloodWait as e:
            return f"⏳ Подождите {e.value}с"
        except Exception as e:
            logger.error(f"[JOIN] {chat_ref}: {e}", exc_info=True)
            return f"❌ Ошибка: {e}"

    async def leave_source(self, chat_ref: str) -> str:
        """Отписаться от источника."""
        if not self._authorized:
            return "❌ Мониторинг не авторизован"
        chat_id = self._resolved_chats.pop(chat_ref, None)
        if chat_id:
            try:
                await self.client.leave_chat(chat_id)
                logger.info(f"[LEAVE] {chat_ref}: отписались")
            except Exception as e:
                logger.warning(f"[LEAVE] {chat_ref}: ошибка leave — {e}")
            self._last_msg_ids.pop(chat_id, None)
        else:
            try:
                chat = await self.client.get_chat(chat_ref)
                await self.client.leave_chat(chat.id)
            except Exception as e:
                logger.warning(f"[LEAVE] {chat_ref}: {e}")
        return f"✅ Отписались от {chat_ref}"

    async def check_subscriptions(self):
        """Проверка подписок (вызывается из фоновой задачи каждые 5 мин)."""
        if not self._authorized:
            return
        sources = await db.get_sources()
        for chat_ref in sources:
            if chat_ref not in self._resolved_chats:
                logger.info(f"[CHECK] {chat_ref}: не подписаны, подписываемся...")
                await self._try_join(chat_ref)

    async def _try_join(self, chat_ref: str):
        """Тихая попытка подписки."""
        try:
            chat = await self.client.join_chat(chat_ref)
            self._resolved_chats[chat_ref] = chat.id
            await self._archive_and_mute(chat.id, chat_ref)
            logger.info(f"[AUTO-JOIN] {chat_ref}: подписались (id={chat.id})")
            await self._notify_admins(f"🔄 Авто-подписка на <code>{chat_ref}</code> (📦🔇)")
        except UserAlreadyParticipant:
            try:
                chat = await self.client.get_chat(chat_ref)
                self._resolved_chats[chat_ref] = chat.id
            except Exception:
                pass
        except FloodWait as e:
            logger.warning(f"[AUTO-JOIN] {chat_ref}: FloodWait {e.value}с")
        except Exception as e:
            logger.warning(f"[AUTO-JOIN] {chat_ref}: не удалось — {e}")

    # ─── Для /recent ───

    async def fetch_recent_from_sources(self, limit: int = 10) -> list[dict]:
        """Получить последние сообщения из чатов-источников."""
        results = []
        for chat_ref, chat_id in self._resolved_chats.items():
            try:
                async for msg in self.client.get_chat_history(chat_id, limit=limit):
                    text = msg.text or msg.caption or ""
                    if text:
                        chat = msg.chat
                        msg_link = f"https://t.me/{chat.username}/{msg.id}" if chat.username else ""
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

    # ─── Рассылка ───

    async def _broadcast_vacancy(self, vacancy_id: int, text: str,
                                  professions: list[str], msg_link: str,
                                  author: str = "", author_link: str = ""):
        """Рассылка вакансии подписчикам."""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        user_ids = set()
        for prof in professions:
            users = await db.get_users_by_profession(prof)
            user_ids.update(users)
            logger.info(f"[BROADCAST] #{vacancy_id} | проф={prof} → {len(users)} подписчиков")

        if not user_ids:
            logger.info(f"[BROADCAST] #{vacancy_id} | нет подписчиков на {professions}")
            return

        prof_tags = " ".join(f"#{p.replace('.', '').replace(' ', '_')}" for p in professions)
        author_text = ""
        if author_link:
            author_text = f"\n\n👤 Автор: <a href=\"{author_link}\">{author}</a>"
        elif author:
            author_text = f"\n\n👤 Автор: {author}"

        msg_text = f"📌 <b>Новая вакансия</b>\n{prof_tags}\n\n{text[:3200]}{author_text}"

        buttons = []
        if msg_link:
            buttons.append([InlineKeyboardButton(text="💬 Сообщение в чате", url=msg_link)])
        if author_link:
            buttons.append([InlineKeyboardButton(text="📩 Написать автору", url=author_link)])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

        sent = 0
        user_list = list(user_ids)
        BATCH_SIZE = 25
        for i in range(0, len(user_list), BATCH_SIZE):
            batch = user_list[i:i + BATCH_SIZE]
            tasks = [self._send_vacancy_to_user(uid, vacancy_id, msg_text, keyboard) for uid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            sent += sum(1 for r in results if r is True)
            if i + BATCH_SIZE < len(user_list):
                await asyncio.sleep(1.0)

        logger.info(f"[BROADCAST] #{vacancy_id} | отправлено {sent}/{len(user_ids)}")

    async def _send_vacancy_to_user(self, uid: int, vacancy_id: int,
                                     msg_text: str, keyboard) -> bool:
        try:
            await self.bot.send_message(
                uid, msg_text, parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            await db.mark_vacancy_sent(uid, vacancy_id)
            logger.info(f"[SEND] #{vacancy_id} → {uid}: ОК")
            return True
        except Exception as e:
            logger.warning(f"[SEND] #{vacancy_id} → {uid}: ОШИБКА — {e}")
            return False

    # ─── Авторизация ───

    async def _request_auth_code(self):
        if not PHONE:
            logger.error("[AUTH] PHONE не задан!")
            await self._notify_admins("❌ <b>Мониторинг не запущен</b>\n\nПеременная PHONE не задана.")
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
                "Введите: <code>/code 12345</code>\n"
                "2FA: <code>/password пароль</code>"
            )
        except FloodWait as e:
            logger.warning(f"[AUTH] FloodWait {e.value}с")
            await self._notify_admins(f"⏳ Подождите {e.value} сек")
            await asyncio.sleep(e.value)
            await self._request_auth_code()
        except Exception as e:
            logger.error(f"[AUTH] Ошибка: {e}", exc_info=True)
            await self._notify_admins(f"❌ Ошибка авторизации: <code>{e}</code>")

    async def submit_code(self, code: str) -> str:
        try:
            await self.client.sign_in(PHONE, self._phone_code_hash, code)
            self._authorized = True
            logger.info("[AUTH] Авторизация успешна!")
            await self._setup_sources()
            self._start_poll_loop()
            return "✅ Авторизация успешна! Мониторинг запущен."
        except SessionPasswordNeeded:
            return "🔐 Требуется 2FA: <code>/password пароль</code>"
        except PhoneCodeInvalid:
            return "❌ Неверный код. /code 12345"
        except PhoneCodeExpired:
            await self._request_auth_code()
            return "⏰ Код истёк. Запросил новый."
        except FloodWait as e:
            return f"⏳ Подождите {e.value}с"
        except Exception as e:
            logger.error(f"[AUTH] sign_in: {e}", exc_info=True)
            return f"❌ Ошибка: <code>{e}</code>"

    async def submit_password(self, password: str) -> str:
        try:
            await self.client.check_password(password)
            self._authorized = True
            logger.info("[AUTH] 2FA авторизация успешна!")
            await self._setup_sources()
            self._start_poll_loop()
            return "✅ Авторизация с 2FA успешна!"
        except Exception as e:
            logger.error(f"[AUTH] 2FA: {e}", exc_info=True)
            return f"❌ Ошибка: <code>{e}</code>"

    # ─── Утилиты ───

    async def _notify_admins(self, text: str):
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Уведомление админу {admin_id}: {e}")

    async def stop(self):
        if self._poll_task:
            self._poll_task.cancel()
            logger.info("[STOP] Polling-цикл остановлен")
        if self.client.is_connected:
            await self.client.disconnect()
            logger.info("[STOP] Pyrogram отключён")
