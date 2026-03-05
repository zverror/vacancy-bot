"""Анализ чатов из Google Sheets — подключение и получение последних сообщений."""
import asyncio
import json
import sys
from pyrogram import Client

API_ID = 33225356
API_HASH = "523bd3894be515aed60cd08025b770e4"

# Чаты для анализа (извлечены из Google Sheets)
CHATS = [
    # Верхняя часть таблицы — invite-ссылки (без названий, нужно зайти посмотреть)
    # Instaboss
    "+klO9xGpEw504Y2Uy",
    "+taqAA30KGd5lNTZi",
    "+qozG9xYe8N4yMDFi",
    "+ZJg6yRSKa1Y5Nzcy",
    # Instadium
    "+mV3ZNm5oxlIyZDJi",
    # Инсталогия
    "+QpUTa_9Y27ozMWQy",
    "+YIG1m3urIB4xZGEy",
    # ФЗ
    # "+1h3h2vhp89BiMWQy",  # duplicate-like
    # Чаты с вакансиями (верхняя часть)
    "+xxPv8gKoffwxNzNi",
    "frilanc",
    "mari_vakansii",
    "worknomer1",
    "+R_KxUQG5hYo5ZjAy",
    "allinfobiz",
    "+mHSeZGSCr6QyNDdi",

    # Нижняя часть — публичные чаты (с названиями)
    "samozanyatosti",
    "webacadem_chat",
    "world_360",
    "rueventjob4at",
    "freelance_work",
    "freelance_vacancii",
    "vakanssii",
    "rabota_esttt",
    "frilanc_topchat",
    "freelance_dvig",
    "frilanc_chat",
    "bisneskontakt",
    "pritulaacademy",
    "infobiznes_vakansii",
    "frilanceforpeople",
    "dren_ro_2020",
    "vpsmm_marketing",
    "na_frilance",
    "easy_fr_cht",
    "diworkchat",
    "rabotadoma_24chat",
    "rabotavakansij",
    "freelance_ads_group",
    "freeassistant",
    "rabota_podrabotka_frilanserom",
    "infobiz_rich",
    "business_group2",
    "getinfobiz",
    "pro_vakansi",
    "infobizzer",
    "infobiz_choogl",
    "avitobust",
    "btvns",
    "freelance_in_telegram",
    "ydalenna800",
    "smmvakancii",
    "udalenka_chatik",
    "freelance_vakansiii",
    "ggfreelancechat",
    "avitochatkosms",
    "jcenterschat",
    "freelansersp",
    "chat_freelanc",
    "infobiz_vakansii",
    "yourfreelancework",
    "birzhha",
    "frilans_chat_udalonka_na_domu",
    "bakansii",
    "freelancervchate",
    "info_biz_ivent",
    "zakazyivakansii",
    "freelance_birzha",
    "chatik1termatrirosova",
    "bomba_freelance",
    "kuznicakadry",
    "frilansinet",
    "beaverbiz_freelance",
    "wolf_vakansii",
    "ksh_freelance",
    "reklamafree007",
    "tofind_pro",
    "workwowinfo",
    "jobfl_chat",
    "newfrelans",
    "itjobonline",
    "rabota_v_setii",
    "chat_frilansa",
    "freeelanceeers",
    "eazy_freelance",
    "freelance_access",
    "workffreelance",
    "freevacations_chat",
    "freelancevpsmm",
    "frilansbirzha",
    "richlance_chat",
    "chatfreelanc",
    "free_chat_for_freelance",
]

# Явно мусорные по названиям — ИСКЛЮЧАЕМ сразу:
TRASH = [
    "kriptobox777",       # BUNG VERIF_ВЕРИФИКАЦИЯ_КРИПТА — крипто-мусор
    "trudogolikii",       # Работа в СПБ — локальный офлайн
    "rabota_qaz",         # Казахстан работа онлайн
    "udalenka365",        # «Удалённая работа» — слишком общее
    "rabota_chatt",       # «Работа чат» — мусор
    "live_good_2023",     # «Работа онлайн» — MLM-вайб
    "avito67online",      # «Заработок в интернете» — спам
    "rabotawwinternete",  # «Работа в интернете» — спам
    "avitoried",          # «Удалёная работа | Чат» — авито-мусор
    "reklama_357",        # «Работа онлайн» — спам
    "knopka_works",       # «Работа в сети | Услуги» — мусор
    "promoutery_moskva",  # «Работа для студентов» — промоутеры
    "work_online_today",  # «РАБОТА ОНЛАЙН | ЧАТ» — спам
    "zarabotai_v_internete_legko",  # название говорит за себя
    "vakansii_seti",      # «ОНЛАЙН РАБОТА» — мусор
    "udalenka2323",       # InSKY — мусор
    "birzhakanalov1",     # «БИРЖА РАБОТЫ» — спам
    "instartgo",          # «Работа с обучением» — MLM
    "it_chat_cz",         # IT Чехия — не РФ
    "galinaproekt",       # «Работа онлайн» — мусор
    "gpt_web3_hackathon", # Хакатон — не вакансии
    "dgsk_udrk",          # Гродно — Беларусь, локальный
    "digitalnomadserbia", # Сербия — не целевая
    "chat_online_jobs",   # «РАБОТА ОНЛАЙН» — мусор
    "job_ua",             # «Работа для всех» — Украина
    "onlinerabota07",     # «Работа ОНЛАЙН» — мусор
    "chatavitotematika",  # «АВИТО ЧАТ» — авито
    "naidispb",           # СПБ — локальный
    "vsem_rabota_spb",    # СПБ — локальный
    "msk_hr",             # Москва — локальный офлайн
    "forex_sales",        # Форекс — мусор
    "emailbase2020",      # Email Base — спам-базы
    "rabotalpr",          # ЛНР — локальный
    "sistematrafika",     # «Клиенты под ключ» — мусор
    "lichnii_bizne",      # «Личный Бизнес» — мусор
    "rabotaxonline",      # «РАБОТА ОНЛАЙН» — мусор
    "predprinimateli_biz", # Предприниматели — не вакансии
    "avito_otzevvvv",     # «ФРИЛАНС ЧАТИК» — авито
    "onlain_bi",          # «Онлайн Бизнес» — мусор
    "krasnodarbusinessmen", # Бизнесмены Краснодар — не вакансии
    "netvorking_chat_ru", # Нетворкинг — не вакансии
    "rabotavvspb",        # СПБ — локальный
    "brendmotion",        # Продакшн/Креативщики — может быть норм, но 26К мусора
    "annkuks",            # Без описания
    "arrowit",            # IT вакансии — может быть норм, но стрелка-формат
    "avitofasst",         # «Чат заработка» — авито
    "schools_online",     # Онлайн-школы — не вакансии
]

async def analyze_chat(client, chat_ref: str, limit: int = 20):
    """Получить последние сообщения из чата и оценить качество."""
    try:
        chat = await client.get_chat(chat_ref)
        title = chat.title or chat_ref
        members = chat.members_count or 0

        messages = []
        async for msg in client.get_chat_history(chat.id, limit=limit):
            text = msg.text or msg.caption or ""
            if text and len(text) > 20:
                messages.append({
                    "text": text[:300],
                    "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
                })

        return {
            "ref": chat_ref,
            "title": title,
            "members": members,
            "messages": messages,
            "count": len(messages),
        }
    except Exception as e:
        return {
            "ref": chat_ref,
            "error": str(e),
        }


async def main():
    client = Client(
        name="analyzer_session",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir="/Users/mac/.openclaw/workspace/projects/vacancy-bot/chat-analysis/",
    )

    await client.start()
    me = await client.get_me()
    print(f"Авторизован как: {me.first_name} ({me.phone_number})")

    results = []
    chats_to_check = [c for c in CHATS if c not in TRASH]
    print(f"\nАнализ {len(chats_to_check)} чатов (из {len(CHATS)} всего, {len(TRASH)} мусорных отброшено)...\n")

    for i, chat_ref in enumerate(chats_to_check, 1):
        print(f"[{i}/{len(chats_to_check)}] {chat_ref}...", end=" ", flush=True)
        result = await analyze_chat(client, chat_ref, limit=20)
        results.append(result)
        if "error" in result:
            print(f"ОШИБКА: {result['error']}")
        else:
            print(f"OK — {result['title']} ({result['members']} уч., {result['count']} сообщ.)")
        await asyncio.sleep(1)  # Уважаем лимиты

    # Сохраняем результаты
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nГотово! Результаты в results.json")
    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
