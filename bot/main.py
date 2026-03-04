"""Точка входа — запуск бота и мониторинга"""
import asyncio
import logging
import sys
from pathlib import Path

# Добавляем корень проекта в PATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.config import BOT_TOKEN, LOG_LEVEL
from bot.database import init_db
from bot.monitor.userbot import VacancyMonitor

from bot.handlers import start, profile, subscription, admin, help


def setup_logging():
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

    # Создаём директорию для данных
    Path("data").mkdir(exist_ok=True)

    # Инициализация БД
    await init_db()
    logger.info("База данных инициализирована")

    # Бот
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)
    dp.include_router(help.router)

    # Мониторинг чатов
    monitor = VacancyMonitor(bot)

    try:
        # Запускаем мониторинг
        await monitor.start()
        logger.info("Мониторинг чатов запущен")

        # Запускаем бота
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        await monitor.stop()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
