# Бот-агрегатор фрилансерских вакансий

Telegram-бот, который мониторит чаты с вакансиями и рассылает их подписчикам по выбранным профессиям.

## Стек
- **Python 3.10+**
- **aiogram 3.x** — Telegram бот
- **Telethon** — мониторинг чатов (userbot)
- **SQLite** (aiosqlite) — база данных
- **Telegram Stars + ЮKassa** — оплата подписки

## Профессии
ВебДизайнер, Дизайнер, Таргетолог, СММ, Директолог, Копирайтер, Сторисмейкер, Видеомонтажер, Тех.Спец, Закупщик рекламы

## Тарифы
- 🎁 Пробный период: 7 дней бесплатно
- Неделя: 740₽ (120⭐)
- Месяц: 1290₽ (210⭐)
- 3 месяца: 2890₽ (470⭐)

## Установка на VPS

### 1. Клонирование и настройка
```bash
cd /opt
git clone <repo-url> vacancy-bot
cd vacancy-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Конфигурация
```bash
cp .env.example .env
nano .env
```

Заполните:
- `BOT_TOKEN` — токен бота из @BotFather
- `API_ID`, `API_HASH` — с my.telegram.org
- `PHONE` — номер телефона для Telethon (формат +79xxxxxxxxx)
- `ADMIN_IDS` — ваш Telegram ID
- `YUKASSA_SHOP_ID`, `YUKASSA_SECRET_KEY` — если нужна оплата картой

### 3. Первый запуск (авторизация Telethon)
```bash
source venv/bin/activate
python -m bot.main
```

⚠️ При первом запуске Telethon попросит ввести код из Telegram — это нормально. После авторизации создаётся файл `vacancy_monitor.session`, повторная авторизация не потребуется.

### 4. Systemd сервис
```bash
cp vacancy-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable vacancy-bot
systemctl start vacancy-bot
```

### Управление
```bash
systemctl status vacancy-bot    # статус
systemctl restart vacancy-bot   # перезапуск
journalctl -u vacancy-bot -f    # логи в реальном времени
```

## Команды бота

### Пользователь
- `/start` — регистрация, выбор профессий
- `/profile` — профиль и статус подписки
- `/professions` — изменить профессии
- `/subscribe` — оформить подписку
- `/help` — справка

### Админ (ADMIN_IDS)
- `/stats` — статистика
- `/broadcast <текст>` — рассылка всем пользователям

## Структура
```
vacancy-bot/
├── bot/
│   ├── main.py           # точка входа
│   ├── config.py          # конфигурация
│   ├── database.py        # SQLite
│   ├── handlers/
│   │   ├── start.py       # /start, регистрация
│   │   ├── profile.py     # /profile, /professions
│   │   ├── subscription.py # /subscribe, оплата
│   │   ├── admin.py       # /stats, /broadcast
│   │   └── help.py        # /help
│   ├── monitor/
│   │   ├── userbot.py     # Telethon мониторинг
│   │   └── classifier.py  # классификация вакансий
│   └── payments/
│       └── yukassa.py     # ЮKassa (заглушка)
├── .env.example
├── requirements.txt
├── run.sh
├── vacancy-bot.service    # systemd unit
└── README.md
```

## Чаты-источники
- t.me/profiwork
- t.me/rabota_emik
- t.me/mari_vakansii
- Закрытый чат (invite link)

Аккаунт, используемый для мониторинга (PHONE), должен быть участником всех чатов.
