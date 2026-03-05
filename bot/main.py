"""Точка входа — запуск бота и мониторинга"""
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN, LOG_LEVEL
from bot import database as db
from bot.database import init_db
from bot.monitor.userbot import VacancyMonitor

from bot.handlers import start, profile, subscription, admin, help


def setup_logging():
    log_dir = Path("data")
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/bot.log", encoding="utf-8"),
        ]
    )


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        sys.exit(1)

    logger.info("Инициализация бота...")
    Path("data").mkdir(exist_ok=True)
    await init_db()
    # Загружаем дефолтные источники в БД если пусто
    from bot.config import SOURCE_CHATS
    await db.init_default_sources(SOURCE_CHATS)
    logger.info("БД инициализирована")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Регистрация команд меню (сворачиваемое)
    from aiogram.types import BotCommand, MenuButtonCommands
    await bot.set_my_commands([
        BotCommand(command="start", description="Начало работы"),
        BotCommand(command="profile", description="Профиль и подписка"),
        BotCommand(command="professions", description="Выбор профессий"),
        BotCommand(command="subscribe", description="Оформить подписку"),
        BotCommand(command="help", description="Инструкция"),
    ])
    # Сворачиваемая кнопка меню (Menu → показать/скрыть)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)
    dp.include_router(help.router)

    monitor = VacancyMonitor(bot)
    from bot.handlers.admin import set_monitor
    set_monitor(monitor)

    webhook_runner = None
    try:
        await monitor.start()
        logger.info("Бот запущен!")

        # Webhook ЮМани
        from bot.config import YUKASSA_SHOP_ID
        if YUKASSA_SHOP_ID:
            from aiohttp import web
            from bot.payments.yukassa import create_yumoney_app
            app = create_yumoney_app(bot)
            webhook_runner = web.AppRunner(app)
            await webhook_runner.setup()
            site = web.TCPSite(webhook_runner, "0.0.0.0", 8080)
            await site.start()
            logger.info("Webhook ЮМани на :8080")

        # Фоновые задачи
        reminder_task = asyncio.create_task(_subscription_reminders(bot))
        sub_check_task = asyncio.create_task(_check_subscriptions_loop(monitor))

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("Остановка")
    finally:
        reminder_task.cancel()
        sub_check_task.cancel()
        await monitor.stop()
        if webhook_runner:
            await webhook_runner.cleanup()
        await monitor.stop()
        await bot.session.close()
        logger.info("Бот остановлен")


async def _subscription_reminders(bot: Bot):
    """Фоновая проверка — напоминания об окончании подписки"""
    import time as _time

    # Интервалы напоминаний: (секунды до конца, текст, ключ)
    REMINDERS = [
        (2 * 86400, "2 дня", "2d"),
        (1 * 86400, "1 день", "1d"),
        (3 * 3600, "3 часа", "3h"),
        (1 * 3600, "1 час", "1h"),
    ]

    logger = logging.getLogger("reminders")
    sent_reminders: set[str] = set()  # "user_id:key"

    while True:
        try:
            await asyncio.sleep(300)  # Проверка каждые 5 минут

            now = _time.time()
            all_users = await db.get_all_users()

            for uid in all_users:
                user = await db.get_user(uid)
                if not user:
                    continue

                # Определяем конец подписки
                sub_end = max(user.get("sub_end", 0), user.get("trial_end", 0))
                if sub_end <= now:
                    continue  # Уже истекла

                remaining = sub_end - now

                for threshold, label, key in REMINDERS:
                    reminder_key = f"{uid}:{key}"
                    if reminder_key in sent_reminders:
                        continue

                    # Отправляем если осталось меньше порога, но больше предыдущего
                    if remaining <= threshold:
                        try:
                            await bot.send_message(
                                uid,
                                f"⏰ <b>Подписка истекает через {label}!</b>\n\n"
                                f"Продлите подписку, чтобы не пропустить вакансии.\n"
                                f"/subscribe — продлить",
                                parse_mode="HTML"
                            )
                            sent_reminders.add(reminder_key)
                            logger.info(f"Напоминание {label} → {uid}")
                        except Exception as e:
                            logger.debug(f"Не удалось отправить напоминание {uid}: {e}")
                        break  # Одно напоминание за раз

            # Чистим старые записи (раз в сутки вряд ли переполнится)
            if len(sent_reminders) > 10000:
                sent_reminders.clear()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в напоминаниях: {e}", exc_info=True)
            await asyncio.sleep(60)


async def _check_subscriptions_loop(monitor: VacancyMonitor):
    """Каждые 5 минут проверяет подписку на все группы из БД."""
    slogger = logging.getLogger("sub_check")
    # Ждём 60 сек после старта — дать время авторизоваться
    await asyncio.sleep(60)
    while True:
        try:
            await monitor.check_subscriptions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            slogger.error(f"Ошибка проверки подписок: {e}", exc_info=True)
        await asyncio.sleep(300)  # 5 минут


if __name__ == "__main__":
    asyncio.run(main())
