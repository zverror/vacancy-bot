"""ЮKassa — создание платежа и проверка (заглушка до получения ключей)"""
import logging
from bot.config import YUKASSA_SHOP_ID, YUKASSA_SECRET_KEY, PLANS
from bot import database as db

logger = logging.getLogger(__name__)


async def create_payment(user_id: int, plan_id: str) -> str | None:
    """
    Создаёт платёж в ЮKassa и возвращает URL для оплаты.
    Активируется только при наличии YUKASSA_SHOP_ID и YUKASSA_SECRET_KEY.
    """
    if not YUKASSA_SHOP_ID or not YUKASSA_SECRET_KEY:
        logger.warning("ЮKassa не настроена: shop_id или secret_key отсутствуют")
        return None

    plan = PLANS.get(plan_id)
    if not plan:
        return None

    try:
        from yookassa import Configuration, Payment
        Configuration.account_id = YUKASSA_SHOP_ID
        Configuration.secret_key = YUKASSA_SECRET_KEY

        payment = Payment.create({
            "amount": {
                "value": f"{plan['price']:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/your_bot"  # TODO: заменить на реального бота
            },
            "capture": True,
            "description": f"Подписка «{plan['name']}» на {plan['days']} дней",
            "metadata": {
                "user_id": str(user_id),
                "plan_id": plan_id
            }
        })

        logger.info(f"ЮKassa: платёж создан id={payment.id}, user={user_id}, plan={plan_id}")
        return payment.confirmation.confirmation_url

    except Exception as e:
        logger.error(f"ЮKassa: ошибка создания платежа — {e}")
        return None


async def handle_webhook(data: dict) -> bool:
    """
    Обработка webhook от ЮKassa (payment.succeeded).
    Вызывается из веб-сервера (aiohttp/fastapi).
    """
    try:
        event_type = data.get("event")
        if event_type != "payment.succeeded":
            return False

        obj = data.get("object", {})
        metadata = obj.get("metadata", {})
        user_id = int(metadata.get("user_id", 0))
        plan_id = metadata.get("plan_id", "")

        if not user_id or plan_id not in PLANS:
            logger.warning(f"ЮKassa webhook: невалидные данные — user={user_id}, plan={plan_id}")
            return False

        plan = PLANS[plan_id]
        await db.extend_subscription(user_id, plan["days"])
        await db.add_payment(
            user_id=user_id,
            plan=plan_id,
            amount=plan["price"],
            method="yukassa",
            payment_id=obj.get("id", "")
        )

        logger.info(f"ЮKassa: подписка активирована user={user_id}, plan={plan_id}")
        return True

    except Exception as e:
        logger.error(f"ЮKassa webhook: ошибка — {e}")
        return False
