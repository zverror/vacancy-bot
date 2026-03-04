"""Обработчики подписки и оплаты"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from bot import database as db
from bot.config import YUKASSA_SHOP_ID
from urllib.parse import quote

router = Router()
logger = logging.getLogger(__name__)

# Кэш username бота (заполняется при первом вызове)
_bot_username: str = ""


async def _get_bot_username(bot) -> str:
    global _bot_username
    if not _bot_username:
        me = await bot.get_me()
        _bot_username = me.username
    return _bot_username


async def _subscribe_keyboard() -> InlineKeyboardMarkup:
    plans = await db.get_plans()
    buttons = []
    for plan_id, plan in plans.items():
        buttons.append([InlineKeyboardButton(
            text=f"{plan['name']} — {plan['price']}₽ ({plan['stars']}⭐)",
            callback_data=f"sub:{plan_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _payment_method_keyboard(plan_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay:stars:{plan_id}")],
    ]
    if YUKASSA_SHOP_ID:
        buttons.append([
            InlineKeyboardButton(text="💳 Банковская карта", callback_data=f"pay:yukassa:{plan_id}")
        ])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="sub:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("subscribe"))
@router.message(F.text == "💎 Подписка")
async def cmd_subscribe(message: Message):
    plans = await db.get_plans()
    await message.answer(
        "💎 <b>Тарифы подписки</b>\n\n"
        "🎁 Пробный период: 7 дней бесплатно\n\n"
        "После пробного периода:\n"
        f"• {plans['week']['name']} — {plans['week']['price']}₽\n"
        f"• {plans['month']['name']} — {plans['month']['price']}₽\n"
        f"• {plans['quarter']['name']} — {plans['quarter']['price']}₽\n\n"
        "Выберите тариф:",
        reply_markup=await _subscribe_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "sub:back")
async def on_sub_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 <b>Тарифы подписки</b>\n\nВыберите тариф:",
        reply_markup=await _subscribe_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sub:"))
async def on_plan_select(callback: CallbackQuery):
    plan_id = callback.data.replace("sub:", "")
    plans = await db.get_plans()
    if plan_id not in plans:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    plan = plans[plan_id]
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
    plans = await db.get_plans()
    plan = plans.get(plan_id)
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
    plans = await db.get_plans()
    plan = plans.get(plan_id)
    if not plan:
        await message.answer("Ошибка обработки платежа. Обратитесь к администратору.")
        return

    uid = message.from_user.id
    await db.extend_subscription(uid, plan["days"])
    await db.add_payment(
        user_id=uid, plan=plan_id, amount=plan["price"],
        method="stars",
        payment_id=str(message.successful_payment.telegram_payment_charge_id)
    )
    logger.info(f"Оплата Stars: user={uid}, plan={plan_id}")
    await message.answer(
        f"✅ Оплата прошла!\n\n"
        f"Подписка «{plan['name']}» активирована на {plan['days']} дней. 🎉"
    )


# --- ЮМани ---

@router.callback_query(F.data.startswith("pay:yukassa:"))
async def on_pay_yukassa(callback: CallbackQuery):
    if not YUKASSA_SHOP_ID:
        await callback.answer("Оплата картой временно недоступна.", show_alert=True)
        return

    plan_id = callback.data.replace("pay:yukassa:", "")
    plans = await db.get_plans()
    plan = plans.get(plan_id)
    if not plan:
        await callback.answer("Ошибка", show_alert=True)
        return

    uid = callback.from_user.id
    label = f"sub:{uid}:{plan_id}"

    # successURL — ссылка обратно в бота
    bot_uname = await _get_bot_username(callback.bot)
    success_url = quote(f"https://t.me/{bot_uname}")

    targets = quote(f"Подписка «{plan['name']}»")
    pay_url = (
        f"https://yoomoney.ru/quickpay/confirm.xml?"
        f"receiver={YUKASSA_SHOP_ID}"
        f"&quickpay-form=shop"
        f"&targets={targets}"
        f"&paymentType=SC"
        f"&sum={plan['price']}"
        f"&label={label}"
        f"&successURL={success_url}"
    )

    await callback.message.edit_text(
        f"💳 <b>Оплата: {plan['name']} — {plan['price']}₽</b>\n\n"
        f"Нажмите кнопку ниже для перехода к оплате.\n"
        f"После оплаты подписка активируется автоматически.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {plan['price']}₽", url=pay_url)],
            [InlineKeyboardButton(text="← Назад", callback_data="sub:back")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()
