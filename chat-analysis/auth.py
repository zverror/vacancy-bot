"""Авторизация Pyrogram — ручной режим (connect + send_code + sign_in)."""
import asyncio
import sys
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

API_ID = 33225356
API_HASH = "523bd3894be515aed60cd08025b770e4"
PHONE = "+79208693683"

async def auth():
    client = Client(
        name="analyzer_session",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=".",
    )

    await client.connect()
    print(f"Connected. Отправляю код на {PHONE}...")

    try:
        sent = await client.send_code(PHONE)
        code_type = sent.type.name if hasattr(sent.type, 'name') else str(sent.type)
        print(f"Код отправлен! Способ: {code_type}")
        print(f"phone_code_hash: {sent.phone_code_hash}")

        code = input("Введите код: ").strip()

        try:
            await client.sign_in(PHONE, sent.phone_code_hash, code)
        except SessionPasswordNeeded:
            password = input("Требуется 2FA пароль: ").strip()
            await client.check_password(password)

        me = await client.get_me()
        print(f"✅ Авторизован как: {me.first_name} ({me.phone_number})")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

    await client.disconnect()

asyncio.run(auth())
