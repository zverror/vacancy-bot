"""Обработчик /start — онбординг, регистрация, выбор профессий"""
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, ReplyKeyboardMarkup, KeyboardButton
)
from bot import database as db
from bot.config import PROFESSIONS, TRIAL_DAYS

router = Router()
logger = logging.getLogger(__name__)

_selections: dict[int, set[str]] = {}

# Постоянное меню (ReplyKeyboard)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🔍 Профессии")],
        [KeyboardButton(text="💎 Подписка"), KeyboardButton(text="📖 Инструкция")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def _professions_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    buttons = []
    for prof in PROFESSIONS:
        mark = "✅ " if prof in selected else ""
        buttons.append([InlineKeyboardButton(
            text=f"{mark}{prof}",
            callback_data=f"prof:{prof}"
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="prof:done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await db.get_user(message.from_user.id)

    if user:
        profs = await db.get_user_professions(message.from_user.id)
        if profs:
            await message.answer(
                f"С возвращением! 👋\n\n"
                f"Ваши профессии: {', '.join(profs)}\n\n"
                "Используйте меню внизу для навигации.",
                reply_markup=MAIN_MENU
            )
            return

    # Новый пользователь — онбординг
    await db.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
        trial_days=TRIAL_DAYS
    )

    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Я — бот-агрегатор фрилансерских вакансий.\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Вы выбираете свои профессии (можно несколько)\n"
        "2️⃣ Я мониторю крупные чаты с вакансиями 24/7\n"
        "3️⃣ Как только появляется вакансия по вашему профилю — мгновенно отправляю вам\n\n"
        "💡 <b>Больше не нужно</b> сидеть в десятке чатов и листать сотни сообщений.\n"
        "Вы получаете только то, что подходит именно вам.\n\n"
        f"🎁 <b>Пробный период — {TRIAL_DAYS} дней бесплатно!</b>\n\n"
        "Давайте начнём — выберите профессии 👇",
        reply_markup=MAIN_MENU,
        parse_mode="HTML"
    )

    _selections[message.from_user.id] = set()

    await message.answer(
        "🎯 <b>Выберите профессии</b>\n\n"
        "Нажимайте на нужные, затем «Готово»:",
        reply_markup=_professions_keyboard(set()),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("prof:"))
async def on_profession_toggle(callback: CallbackQuery):
    uid = callback.from_user.id
    data = callback.data.replace("prof:", "")

    if uid not in _selections:
        _selections[uid] = set()

    if data == "done":
        selected = _selections.pop(uid, set())
        if not selected:
            await callback.answer("Выберите хотя бы одну профессию!", show_alert=True)
            _selections[uid] = set()
            return

        await db.set_user_professions(uid, list(selected))
        await callback.message.edit_text(
            f"✅ <b>Готово!</b>\n\n"
            f"Ваши профессии: {', '.join(sorted(selected))}\n\n"
            "Теперь я буду отправлять вам подходящие вакансии в реальном времени.\n\n"
            "Используйте меню внизу для навигации 👇",
            parse_mode="HTML"
        )
        return

    if data in _selections[uid]:
        _selections[uid].discard(data)
    else:
        _selections[uid].add(data)

    await callback.message.edit_reply_markup(
        reply_markup=_professions_keyboard(_selections[uid])
    )
    await callback.answer()
