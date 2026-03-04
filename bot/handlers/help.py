"""Обработчик /help"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Команды бота</b>\n\n"
        "/start — Регистрация и выбор профессий\n"
        "/profile — Ваш профиль и статус подписки\n"
        "/professions — Изменить профессии\n"
        "/subscribe — Оформить подписку\n"
        "/help — Эта справка\n\n"
        "💡 Бот автоматически отправляет вакансии по выбранным профессиям "
        "из нескольких чатов-источников в реальном времени.",
        parse_mode="HTML"
    )
