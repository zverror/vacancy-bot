"""Обработчики /profile и /professions"""
import time
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from bot import database as db
from bot.handlers.start import _selections, _professions_keyboard

router = Router()
MSK = timezone(timedelta(hours=3))


def _format_date(ts: float) -> str:
    if ts <= 0:
        return "—"
    return datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M")


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Вы ещё не зарегистрированы. Нажмите /start")
        return

    profs = await db.get_user_professions(message.from_user.id)
    now = time.time()

    # Определяем статус подписки
    if now < user["trial_end"] and user["sub_end"] <= 0:
        status = f"🎁 Пробный период (до {_format_date(user['trial_end'])})"
    elif now < user["sub_end"]:
        status = f"✅ Активна (до {_format_date(user['sub_end'])})"
    else:
        status = "❌ Неактивна"

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"Профессии: {', '.join(profs) if profs else 'не выбраны'}\n"
        f"Подписка: {status}\n"
        f"Регистрация: {_format_date(user['created_at'])}\n\n"
        f"/professions — изменить профессии\n"
        f"/subscribe — оформить подписку"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("professions"))
@router.message(F.text == "🔍 Профессии")
async def cmd_professions(message: Message):
    current = await db.get_user_professions(message.from_user.id)
    _selections[message.from_user.id] = set(current)

    await message.answer(
        "Выберите профессии (нажмите для переключения, затем «Готово»):",
        reply_markup=_professions_keyboard(set(current))
    )
