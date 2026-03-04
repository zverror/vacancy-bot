"""Точка входа — запуск бота и мониторинга"""
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN, LOG_LEVEL
from bot.database import init_db
from bot.monitor.userbot import VacancyMonitor

# Хендлеры
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
        logger.error("BOT_TOKEN не задан в .env!")
        sys.exit(1)

    logger.info("Инициализация бота...")

    # Инициализация БД
    await init_db()
    logger.info("БД инициализирована")

    # Создание бота
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Диспетчер
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)
    dp.include_router(help.router)

    # Мониторинг чатов (Telethon)
    monitor = VacancyMonitor(bot)

    try:
        # Запускаем мониторинг параллельно с ботом
        await monitor.start()
        logger.info("Бот запущен!")

        # Запускаем webhook-сервер для ЮМани (если настроен)
        from bot.config import YUKASSA_SHOP_ID
        webhook_runner = None
        if YUKASSA_SHOP_ID:
            from aiohttp import web
            from bot.payments.yukassa import create_yumoney_app
            app = create_yumoney_app(bot)
            webhook_runner = web.AppRunner(app)
            await webhook_runner.setup()
            site = web.TCPSite(webhook_runner, "0.0.0.0", 8080)
            await site.start()
            logger.info("Webhook-сервер ЮМани запущен на :8080")

        # Запускаем polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        if webhook_runner:
            await webhook_runner.cleanup()
        await monitor.stop()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
