# Бот-агрегатор фрилансерских вакансий

Telegram-бот, который мониторит чаты с вакансиями и рассылает подходящие предложения подписчикам по выбранным профессиям.

## Стек
- **aiogram 3.x** — Telegram Bot API
- **Telethon** — мониторинг чатов (userbot)
- **SQLite** (aiosqlite) — база данных
- **Telegram Stars + ЮKassa** — оплата подписки

## Установка на VPS

### 1. Клонирование и настройка
```bash
cd /opt
git clone <repo> vacancy-bot
cd vacancy-bot

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Конфигурация
cp .env.example .env
nano .env  # заполнить BOT_TOKEN, API_ID, API_HASH, PHONE
```

### 2. Первый запуск (авторизация Telethon)
```bash
python -m bot.main
```
При первом запуске Telethon попросит ввести:
1. Номер телефона (формат +7xxxxxxxxxx)
2. Код из Telegram
3. Пароль 2FA (если включён)

После авторизации создастся файл `vacancy_monitor.session` — **не удаляйте его**.

### 3. Systemd сервис
```bash
sudo nano /etc/systemd/system/vacancy-bot.service
```

```ini
[Unit]
Description=Vacancy Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vacancy-bot
ExecStart=/opt/vacancy-bot/venv/bin/python -m bot.main
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable vacancy-bot
sudo systemctl start vacancy-bot

# Логи
sudo journalctl -u vacancy-bot -f
```

## Профессии
ВебДизайнер, Дизайнер, Таргетолог, СММ, Директолог, Копирайтер, Сторисмейкер, Видеомонтажер, Тех.Спец, Закупщик рекламы

## Чаты-источники
- @profiwork
- @rabota_emik
- @mari_vakansii
- Закрытый чат (invite link)

## Тарифы
- Пробный период: 7 дней бесплатно
- Неделя: 740₽ / 120⭐
- Месяц: 1290₽ / 210⭐
- 3 месяца: 2890₽ / 470⭐

## Команды бота
- `/start` — регистрация и выбор профессий
- `/profile` — профиль и статус подписки
- `/professions` — изменить профессии
- `/subscribe` — оформить подписку
- `/help` — справка

### Админ (ADMIN_IDS в .env)
- `/stats` — статистика
- `/broadcast <текст>` — рассылка всем

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
│   │   ├── subscription.py # оплата
│   │   ├── admin.py       # /stats, /broadcast
│   │   └── help.py        # /help
│   ├── monitor/
│   │   ├── userbot.py     # Telethon мониторинг
│   │   └── classifier.py  # классификация вакансий
│   └── payments/
│       └── yukassa.py     # ЮKassa (заглушка)
├── data/                  # БД + логи (создаётся автоматически)
├── .env                   # секреты
├── .env.example
├── requirements.txt
├── run.sh
└── README.md
```
