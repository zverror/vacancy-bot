"""ЮМани — приём платежей через HTTP-уведомления"""
import logging
import hashlib
from aiohttp import web
from aiogram import Bot

from bot.config import YUKASSA_SECRET_KEY
from bot import database as db


logger = logging.getLogger(__name__)


def _check_signature(data: dict, secret: str) -> bool:
    """Проверка подписи уведомления от ЮМани"""
    # Порядок полей для SHA-1: notification_type, operation_id, amount, currency,
    # datetime, sender, codepro, notification_secret, label
    check_string = "&".join([
        data.get("notification_type", ""),
        data.get("operation_id", ""),
        data.get("amount", ""),
        data.get("currency", ""),
        data.get("datetime", ""),
        data.get("sender", ""),
        data.get("codepro", ""),
        secret,
        data.get("label", ""),
    ])
    computed = hashlib.sha1(check_string.encode()).hexdigest()
    return computed == data.get("sha1_hash", "")


async def yumoney_webhook(request: web.Request) -> web.Response:
    """Обработка webhook от ЮМани"""
    try:
        data = await request.post()
        data = dict(data)

        logger.info(f"ЮМани webhook: {data}")

        # Проверяем подпись
        if YUKASSA_SECRET_KEY and not _check_signature(data, YUKASSA_SECRET_KEY):
            logger.warning("ЮМани: невалидная подпись!")
            return web.Response(status=400, text="Invalid signature")

        # Парсим label — формат: "sub:user_id:plan_id"
        label = data.get("label", "")
        if not label.startswith("sub:"):
            logger.warning(f"ЮМани: неизвестный label: {label}")
            return web.Response(status=200, text="OK")

        parts = label.split(":")
        if len(parts) != 3:
            logger.warning(f"ЮМани: невалидный label: {label}")
            return web.Response(status=200, text="OK")

        _, user_id_str, plan_id = parts
        user_id = int(user_id_str)
        plans = await db.get_plans()
        plan = plans.get(plan_id)

        if not plan:
            logger.warning(f"ЮМани: неизвестный тариф: {plan_id}")
            return web.Response(status=200, text="OK")

        # Проверяем сумму
        amount = float(data.get("withdraw_amount", data.get("amount", "0")))
        if amount < plan["price"]:
            logger.warning(f"ЮМани: сумма {amount} < {plan['price']} для тарифа {plan_id}")
            return web.Response(status=200, text="OK")

        # Активируем подписку
        await db.extend_subscription(user_id, plan["days"])
        await db.add_payment(
            user_id=user_id,
            plan=plan_id,
            amount=amount,
            method="yumoney",
            payment_id=data.get("operation_id", "")
        )

        # Уведомляем пользователя
        bot: Bot = request.app["bot"]
        try:
            await bot.send_message(
                user_id,
                f"✅ Оплата через ЮМани прошла!\n\n"
                f"Подписка «{plan['name']}» активирована на {plan['days']} дней.\n"
                f"Спасибо! 🎉"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

        logger.info(f"ЮМани: подписка активирована user={user_id}, plan={plan_id}, amount={amount}")
        return web.Response(status=200, text="OK")

    except Exception as e:
        logger.error(f"ЮМани webhook ошибка: {e}", exc_info=True)
        return web.Response(status=500, text="Error")


def create_yumoney_app(bot: Bot) -> web.Application:
    """Создаёт aiohttp приложение для webhook"""
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/webhook/yumoney", yumoney_webhook)
    # Health check
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app
