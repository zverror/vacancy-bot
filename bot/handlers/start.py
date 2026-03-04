"""Обработчик /start — регистрация и выбор профессий"""
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot import database as db
from bot.config import PROFESSIONS, TRIAL_DAYS

router = Router()
logger = logging.getLogger(__name__)

# Временное хранилище выбранных профессий (user_id -> set)
_selections: dict[int, set[str]] = {}


def _professions_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    """Клавиатура выбора профессий с галочками"""
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
                f"С возвращением! Ваши профессии: {', '.join(profs)}\n\n"
                "Используйте /profile для просмотра профиля, /professions для смены профессий."
            )
            return

    # Новый пользователь или без профессий
    await db.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
        trial_days=TRIAL_DAYS
    )

    _selections[message.from_user.id] = set()

    await message.answer(
        "👋 Привет! Я бот-агрегатор фрилансерских вакансий.\n\n"
        "Выберите профессии, по которым хотите получать вакансии.\n"
        "Можно выбрать несколько — нажимайте на нужные, затем «Готово».\n\n"
        f"🎁 Вам доступен бесплатный пробный период — {TRIAL_DAYS} дней!",
        reply_markup=_professions_keyboard(set())
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
            f"✅ Отлично! Ваши профессии: {', '.join(sorted(selected))}\n\n"
            "Теперь вы будете получать вакансии по выбранным направлениям.\n\n"
            "/profile — ваш профиль\n"
            "/professions — изменить профессии\n"
            "/subscribe — оформить подписку"
        )
        return

    # Переключение профессии
    if data in _selections[uid]:
        _selections[uid].discard(data)
    else:
        _selections[uid].add(data)

    await callback.message.edit_reply_markup(
        reply_markup=_professions_keyboard(_selections[uid])
    )
    await callback.answer()
