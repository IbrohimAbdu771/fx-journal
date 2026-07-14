# FX Journal — трейдинг-журнал (TradeZella-style, ICT)

Персональный журнал форекс-сделок (EURUSD/GBPUSD) по модели ICT **Sweep → MSS → OTE**.
Два способа ввода в одну базу:

- **Веб-дашборд** (FastAPI) — ручной ввод/редактирование сделок, статистика и графики как в TradeZella.
- **Telegram-бот** (aiogram) — быстрый захват: фото графика + голос/текст → Claude парсит параметры → запись в базу.

Хранилище — Postgres (на проде Neon/Railway), локально можно SQLite. **Notion не используется.**

---

## Возможности

**Дашборд** (`/`):
- KPI: Net P&L, Total R, Win %, Profit Factor, Expectancy, Day Win %, Max Drawdown, Avg Win/Loss, баланс, **Zella Score** (0–100).
- Equity curve (кумулятивный R), распределение R-мультипликаторов.
- **Календарь** P&L по дням (зелёный/красный/серый), навигация по месяцам.
- Разбивки: по сессиям, сетапам, парам, направлению, дням недели.
- Открытые позиции и лента последних сделок.
- Zella Score — прозрачная аппроксимация из 6 факторов (Win Rate, Profit Factor, Avg Win/Loss, Max Drawdown, Recovery Factor, Consistency); точные веса TradeZella не публикует.

**Ввод сделок:**
- Веб-форма (`/new`, `/trade/{id}`) со всеми полями ICT + загрузка скринов Chart Before/After.
- Бот: фото графика с подписью, или фото + голосовое. Claude (`claude-sonnet-5`, vision + structured tool use) извлекает: пару, направление, entry/SL/TP, лот, риск, сессию, SB-окно, sweep, OTE, MSS, сетап, дисциплину, эмоции.
- Закрытие: «закрыл EURUSD +1.8R» → находит последнюю открытую по паре, обновляет результат/статус.
- Правка: «исправь: стоп был 1.0832».
- Если не хватает критичных полей (пара/направление/вход/стоп) — бот задаёт один уточняющий вопрос и мержит ответ.

**Команды бота:** `/stats [month]` · `/last` · `/open`
**Еженедельный отчёт:** воскресенье 20:00 (в таймзоне трейдера) — Claude разбирает неделю (паттерны ошибок, лучшие/худшие сетапы, дисциплина, рекомендации).

---

## Структура

```
Journal/
  core/            # общий слой (без Telegram/HTTP)
    config.py      # .env, нормализация DATABASE_URL (async, Neon SSL)
    db.py          # async engine + сессии (asyncpg / aiosqlite)
    models.py      # SQLAlchemy модель Trade (скрины хранятся в БД)
    repository.py  # CRUD + выборки для аналитики
    service.py     # обогащение: RR, сессия, имя, статус
    ict.py         # сессии (NY tz), Silver Bullet, RR, словари полей
    stats.py       # все метрики (TradeZella-style) + Zella Score
  bot/             # Telegram (aiogram, long polling)
    main.py        # хендлеры фото/голоса/текста/команд
    parser.py      # Claude: vision + извлечение через tool use
    transcribe.py  # Yandex SpeechKit (Telegram .ogg/opus, без ffmpeg)
    scheduler.py   # еженедельный отчёт (apscheduler)
  web/             # FastAPI дашборд
    app.py         # роуты + запуск бота в lifespan
    charts.py      # equity curve (SVG), календарь, распределение R
    templates/ static/
  main.py          # локальный запуск (uvicorn)
  tests/           # pytest: stats, ict, service, парсинг Claude
  requirements.txt  Procfile  railway.json  .env.example
```

Один процесс: веб-сервис поднимает FastAPI и запускает бота фоновой задачей в `lifespan` — удобно для Railway (один сервис из репо).

---

## Быстрый старт (локально)

```bash
cd Journal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполнить переменные (см. ниже)
python main.py         # → http://localhost:8000
```

Тесты:
```bash
pytest -q
```

Только веб без бота: `RUN_BOT=0 python main.py` (или не задавать TELEGRAM/ANTHROPIC).

---

## Переменные окружения (`.env`)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | Postgres (`postgresql://…`, в т.ч. Neon). Пусто → локальный SQLite. |
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather. |
| `ALLOWED_TELEGRAM_USER_ID` | Твой numeric Telegram id (@userinfobot). Бот отвечает только ему. |
| `ANTHROPIC_API_KEY` | Ключ Claude (vision + извлечение). |
| `CLAUDE_MODEL` | По умолчанию `claude-sonnet-5`. |
| `YANDEX_SPEECHKIT_API_KEY` | Распознавание голосовых (Yandex SpeechKit). |
| `YANDEX_STT_LANG` | Язык распознавания, по умолчанию `ru-RU`. |
| `WEB_PASSWORD` | Пароль для входа на сайт. Пусто → без логина. |
| `WEB_BASE_URL` | Публичный URL дашборда (бот делает ссылки на сделки). |
| `INITIAL_BALANCE` | Стартовый баланс для виджета «Баланс». |
| `TRADER_TIMEZONE` | По умолчанию `America/New_York` (вся логика сессий). |

> Расчёт сессий — в таймзоне трейдера через `zoneinfo` (DST учитывается), не фиксированный UTC-offset.
> Ключи Claude и SpeechKit переиспользованы из проекта Worka.

### Получить токены
- **Telegram:** @BotFather → `/newbot` → токен. Свой id — @userinfobot.
- **Anthropic:** console.anthropic.com → API Keys.
- **Yandex SpeechKit:** Yandex Cloud → сервисный аккаунт → API-ключ (folder берётся из аккаунта, отдельно не нужен).
- **Postgres:** Neon (neon.tech) или Railway-плагин Postgres — строку положить в `DATABASE_URL`.

---

## Деплой на Railway

1. Подключить репозиторий к Railway (уже планируется).
2. Добавить Postgres (плагин) — Railway создаст `DATABASE_URL` автоматически, либо вставить строку Neon.
3. Прописать переменные окружения из таблицы выше.
4. Start command берётся из `railway.json` / `Procfile`:
   `uvicorn web.app:app --host 0.0.0.0 --port $PORT`
5. Бот стартует внутри того же процесса (long polling), веб доступен по домену Railway. Укажи его в `WEB_BASE_URL`.

Драйвер `asyncpg`: строки вида `postgres://…` и libpq-параметры `sslmode`/`channel_binding` (как в Neon) нормализуются автоматически, SSL включается через `certifi`.

---

## Примеры сообщений боту

- Фото графика + подпись: `EURUSD long, вход 1.0850, стоп 1.0832, тейк 1.0905, NY reversal, OTE 0.705, MSS есть`
- Фото графика без подписи → затем голосовое с описанием.
- Закрытие: `закрыл EURUSD +1.8R` (можно приложить скрин после).
- Правка: `исправь: стоп был 1.0832`
- `/stats` — за неделю, `/stats month` — за месяц.
