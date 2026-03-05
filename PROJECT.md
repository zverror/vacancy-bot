# PROJECT.md — Быстрая справка для агента

> Читай README.md для полной документации. Этот файл — шпаргалка.

## Что это
Telegram-бот мониторинга вакансий. Парсит фриланс-чаты через Pyrogram userbot, фильтрует спам (~70 regex), классифицирует по профессиям, рассылает подписчикам.

## Ключевые файлы
- `bot/config.py` — **SPAM_SIGNALS** (антиспам), PROFESSIONS, VACANCY_SIGNALS
- `bot/monitor/userbot.py` — Pyrogram polling (каждые 30с), join/leave, broadcast
- `bot/monitor/classifier.py` — is_vacancy() + classify_vacancy()
- `bot/handlers/admin.py` — все админские команды
- `bot/database.py` — SQLite схема + CRUD

## Как добавить антиспам-паттерн
1. Открой `bot/config.py`
2. Добавь regex-строку в `SPAM_SIGNALS` (lowercase, `re.search`)
3. Проверь: `python3 -c "import ast; ast.parse(open('bot/config.py').read())"`
4. `git add -A && git commit -m "Antispam: описание" && git push`
5. Coolify автодеплоит

## Как добавить источники
- Один: `/add_source username`
- Много: `/add_sources` + список (каждая строка = 1)
- Все автоматически архивируются + мутятся

## Креденшелы
- Bot: `@orf_vacancy_bot` / `8701125806:AAEs95J4XeD5yVCP8nqZiN5cWlSlrSdhhCc`
- Pyrogram: API_ID=33225356, phone=+79208693683
- Admin: 5094009390
- GitHub: github.com/zverror/vacancy-bot
- Деплой: vacancy.automateme.ru (Coolify, автодеплой из main)
