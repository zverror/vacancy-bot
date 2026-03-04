"""Обработчики подписки и оплаты"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from bot import database as db
from bot.config import PLANS, YUKASSA_SHOP_ID

router = Router()
logger = logging.getLogger(__name__)


def _subscribe_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора тарифа"""
    buttons = []
    for plan_id, plan in PLANS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{plan['name']} — {plan['price']}₽ ({plan['stars']}⭐)",
            callback_data=f"sub:{plan_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _payment_method_keyboard(plan_id: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты"""
    buttons = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay:stars:{plan_id}")],
    ]
    if YUKASSA_SHOP_ID:
        buttons.append([
            InlineKeyboardButton(text="💳 Банковская карта (ЮKassa)", callback_data=f"pay:yukassa:{plan_id}")
        ])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="sub:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    await message.answer(
        "💎 <b>Тарифы подписки</b>\n\n"
        "🎁 Пробный период: 7 дней бесплатно\n\n"
        "После пробного периода:\n"
        f"• Неделя — {PLANS['week']['price']}₽\n"
        f"• Месяц — {PLANS['month']['price']}₽\n"
        f"• 3 месяца — {PLANS['quarter']['price']}₽\n\n"
        "Выберите тариф:",
        reply_markup=_subscribe_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "sub:back")
async def on_sub_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 <b>Тарифы подписки</b>\n\nВыберите тариф:",
        reply_markup=_subscribe_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sub:"))
async def on_plan_select(callback: CallbackQuery):
    plan_id = callback.data.replace("sub:", "")
    if plan_id not in PLANS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    plan = PLANS[plan_id]
    await callback.message.edit_text(
        f"💎 <b>{plan['name']}</b> — {plan['price']}₽\n\n"
        "Выберите способ оплаты:",
        reply_markup=_payment_method_keyboard(plan_id),
        parse_mode="HTML"
    )


# --- Telegram Stars ---

@router.callback_query(F.data.startswith("pay:stars:"))
async def on_pay_stars(callback: CallbackQuery):
    plan_id = callback.data.replace("pay:stars:", "")
    plan = PLANS.get(plan_id)
    if not plan:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.answer_invoice(
        title=f"Подписка: {plan['name']}",
        description=f"Доступ к вакансиям на {plan['days']} дней",
        payload=f"sub:{plan_id}",
        currency="XTR",
        prices=[LabeledPrice(label=plan["name"], amount=plan["stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    plan_id = payload.replace("sub:", "")
    plan = PLANS.get(plan_id)
    if not plan:
        await message.answer("Ошибка обработки платежа. Обратитесь к администратору.")
        return

    uid = message.from_user.id
    await db.extend_subscription(uid, plan["days"])
    await db.add_payment(
        user_id=uid,
        plan=plan_id,
        amount=plan["price"],
        method="stars",
        payment_id=str(message.successful_payment.telegram_payment_charge_id)
    )

    logger.info(f"Оплата Stars: user={uid}, plan={plan_id}, amount={plan['stars']} stars")
    await message.answer(
        f"✅ Оплата прошла успешно!\n\n"
        f"Подписка «{plan['name']}» активирована на {plan['days']} дней.\n"
        f"Спасибо! 🎉"
    )


# --- ЮKassa (заглушка, активируется при наличии ключей) ---

@router.callback_query(F.data.startswith("pay:yukassa:"))
async def on_pay_yukassa(callback: CallbackQuery):
    if not YUKASSA_SHOP_ID:
        await callback.answer(
            "Оплата картой временно недоступна. Используйте Telegram Stars.",
            show_alert=True
        )
        return

    plan_id = callback.data.replace("pay:yukassa:", "")
    plan = PLANS.get(plan_id)
    if not plan:
        await callback.answer("Ошибка", show_alert=True)
        return

    # TODO: Создание платежа через ЮKassa API
    # from bot.payments.yukassa import create_payment
    # payment_url = await create_payment(callback.from_user.id, plan_id)
    # await callback.message.answer(f"Оплата: {payment_url}")

    await callback.answer("Оплата картой будет доступна в ближайшее время", show_alert=True)
