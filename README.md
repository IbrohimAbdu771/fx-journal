<div align="center">
  <img src="web/static/logo.svg" width="88" alt="FX Journal">
  <h1>FX Journal</h1>
  <p><b>Персональный трейдинг-журнал форекс по модели ICT — в стиле TradeZella.</b><br>
  Веб-дашборд + Telegram-бот, единая база, режимы Live / Backtest, новости и алерты сессий.</p>
</div>

---

## 📌 Что это

Личный журнал сделок для форекс-трейдинга (EURUSD / GBPUSD) по модели **ICT: Sweep → MSS → OTE**.
Проект решает три задачи:

1. **Быстро логировать сделки** — через Telegram-бота: фото графика + голос/текст, а параметры извлекает Claude.
2. **Анализировать результат** — веб-дашборд с метриками уровня TradeZella (Profit Factor, Expectancy, Zella Score, equity curve, календарь P&L, разбивки).
3. **Дисциплина и контекст** — уведомления о старте торговых сессий и новостях дня прямо в Telegram.

Два независимых журнала в одном приложении: **🟢 Live** (боевой) и **🧪 Backtest** (тестовый) — со своей статистикой, календарём и балансом.

> Ввод сделок — и через бота, и вручную на сайте; оба пишут в одну базу (Postgres).

---

## ✨ Возможности

### 🖥 Веб-дашборд
- **KPI-плитки:** Net P&L ($), Total R, Win Rate, Profit Factor, Expectancy, Day Win %, Max Drawdown, Avg Win/Loss, Баланс, **Zella Score (0–100)**.
- **Equity curve** — кумулятивный R (inline SVG, без внешних библиотек).
- **Календарь P&L** — по дням месяца (зелёный/красный/серый), в шапке сумма R и $ по знаку; листается **без перезагрузки страницы** (AJAX).
- **Распределение R** — гистограмма R-мультипликаторов.
- **Разбивки:** по сессиям, сетапам, парам, направлению, дням недели.
- **Zella Score** — прозрачная аппроксимация из 6 факторов (Win Rate, Profit Factor, Avg Win/Loss, Max Drawdown, Recovery Factor, Consistency); точные веса TradeZella не публикует.
- **Открытые позиции** и лента последних сделок — строки кликабельны целиком (и с клавиатуры).
- **Журнал сделок** — полная таблица с фильтром по режиму.
- **Периоды:** всё / неделя / месяц / год.
- **Дизайн:** тёмная тема «Terminal Luxe» — матовое стекло, золотые кромки, ambient-свечение, зерно; шрифты Bricolage Grotesque + IBM Plex Mono + Manrope; адаптив и поддержка `prefers-reduced-motion`.

### 🤖 Telegram-бот (aiogram, long polling)
- **Новая сделка:** фото графика с подписью, или фото + голосовое. Claude (`claude-sonnet-5`, vision + structured tool use) извлекает пару, направление, entry/SL/TP, лот, риск, сессию, SB-окно, sweep, OTE, MSS, сетап, дисциплину, эмоции.
- **Подтверждение перед записью:** бот показывает карточку с inline-кнопками **✅ Сохранить / ✏️ Исправить / ❌ Отмена** — в БД пишется только после подтверждения (защита от тихого misparse цен, который незаметно испортил бы RR и R-метрики).
- **Закрытие:** «закрыл EURUSD +1.8R» (можно приложить скрин после) — находит последнюю открытую по паре и обновляет результат/статус.
- **Правка:** «исправь: стоп был 1.0832» — обновляет последнюю запись.
- **Уточнение:** если не хватает критичных полей (пара/направление/вход/стоп) — бот задаёт один вопрос и мержит ответ.
- **Карточка сделки** — красиво оформленный HTML (моно-блок цен, секции ICT-контекст и дисциплина).
- **Голос** — распознаётся через **Yandex SpeechKit** (Telegram `.ogg`/opus напрямую, без ffmpeg).
- **Кнопки/команды** — переключение режима 🟢 Live / 🧪 Backtest, `📰 Новости дня`, `/stats /last /open /news`.
- **Whitelist** — бот отвечает **только** заданному Telegram user id.

### 🔔 Уведомления (по будням, время показывается по Ташкенту)
| Событие | Триггер (NY) | Что приходит |
|---|---|---|
| ⏰ London за 30 минут | 01:30 | Напоминание перед London killzone |
| 🔔 London открылась | 02:00 | Окно + Silver Bullet LO 03:00–04:00 |
| 🔔 NY открылась | 07:00 | Окно + Silver Bullet NY AM 10:00–11:00 |
| 📰 Новости дня | 10:00 (Ташкент) | Сводка FF: 🔴 High + 🟡 Medium + ⚪️ Bank Holiday по USD/EUR/GBP |
| 🔴 Красная новость вышла | момент события | Прогноз/предыдущее по High-impact USD/EUR/GBP |
| 📅 Итоги недели | Вс 20:00 (NY) | Статистика недели + разбор от Claude (паттерны, сетапы, дисциплина, рекомендации) |

> Сессии привязаны к NY-времени (модель ICT, DST-safe), а отображаются в локальной таймзоне (`NOTIFY_TIMEZONE`, по умолчанию `Asia/Tashkent`).

### 🟢🧪 Режимы Live / Backtest
- У каждой сделки поле `mode` (`live` / `backtest`). Данные **полностью раздельны**: своя статистика, календарь, баланс, журнал.
- **Сайт:** вверху разделы **Лайв** и **Backtest** (два одинаковых дашборда); на «Сделках» — вкладки с раздельными списками; в бэктесте — золотой индикатор-пилл, чтобы не перепутать.
- **Бот:** кнопки 🟢 Live / 🧪 Backtest переключают режим (запоминается в БД, на пользователя); весь ввод и `/stats /last /open` работают в текущем режиме.

---

## 📊 Метрики (core/stats.py)

Считаются как «учтённые» только закрытые сделки с исходом Win / Loss / Breakeven и числовым `result_r`. Missed / No Trade учитываются отдельно (дисциплина).

- **P&L:** Net P&L ($), Total R, Avg R, Expectancy (R/сделка)
- **Форма результата:** Win Rate, Profit Factor, Payoff (avg win / |avg loss|), Avg Win/Loss (R и $), Largest Win/Loss (R и $)
- **Серии:** текущая серия, макс. серия побед/поражений, серия по дням
- **Дни:** торговых дней, выигрышных/проигрышных, Day Win %, средний дневной R/$
- **Риск:** Max Drawdown (R и $), Recovery Factor, **Std R**, **SQN** (System Quality Number = avg R / std R × √N)
- **Zella Score** — 0–100 из 6 факторов (эвристика; витринный агрегат — решения лучше принимать по expectancy и drawdown)
- **Серии данных:** equity curve, распределение R, календарь по дням
- **Разбивки:** по сессии, сетапу, паре, направлению, дню недели

---

## 🧠 ICT-контекст (core/ict.py)

Вся логика сессий — в таймзоне трейдера (`TRADER_TIMEZONE`, по умолчанию `America/New_York`) через `zoneinfo` (DST учитывается), не фиксированный UTC-offset.

- **Сессии (NY local):** Asia 20:00–00:00, London 02:00–05:00, NY 07:00–10:00
- **Silver Bullet окна:** LO 03:00–04:00, NY AM 10:00–11:00
- **Словари полей:** пары, направления, сетапы (LO/NY reversal, NY continuation), sweep reference (Asia High/Low, PDH/PDL…), OTE (0.62/0.705/0.79/OB/FVG), исходы, план, эмоции, типы нарушений
- **RR planned** = |TP − entry| / |entry − SL|

---

## 🗂 Структура проекта

```
journal/
├── core/                  # общий слой (без Telegram/HTTP)
│   ├── config.py          # .env, нормализация DATABASE_URL (async, Neon SSL)
│   ├── db.py              # async engine + сессии + миграции (asyncpg / aiosqlite)
│   ├── models.py          # SQLAlchemy: Trade (+ поле mode), Setting
│   ├── repository.py      # CRUD + выборки для аналитики + key/value настройки
│   ├── service.py         # обогащение сделки: RR, сессия, имя, статус
│   ├── ict.py             # сессии, Silver Bullet, RR, словари полей
│   └── stats.py           # все метрики (TradeZella-style) + Zella Score
├── bot/                   # Telegram (aiogram, long polling)
│   ├── main.py            # хендлеры фото/голоса/текста/команд/кнопок, режимы
│   ├── parser.py          # Claude: vision + извлечение через tool use
│   ├── transcribe.py      # Yandex SpeechKit (голос → текст)
│   ├── news.py            # Forex Factory (FairEconomy JSON) → новости дня
│   └── scheduler.py       # алерты сессий, красные релизы, новости, недельный отчёт
├── web/                   # FastAPI дашборд
│   ├── app.py             # роуты + запуск бота в lifespan
│   ├── charts.py          # equity curve (SVG), календарь, распределение R
│   ├── templates/         # base, dashboard, trades, trade_form, trade_detail, _fields, _result_fields, _calendar, login
│   └── static/            # style.css, app.js, logo.svg
├── tests/                 # pytest: stats, ict, service, парсинг Claude
├── main.py                # локальный запуск (uvicorn)
├── requirements.txt
├── Procfile · railway.json
└── .env.example
```

Один процесс: веб-сервис поднимает FastAPI и запускает бота фоновой задачей в `lifespan` — удобно для Railway (один сервис из репо).

---

## 🛠 Технологии

| Слой | Технологии |
|---|---|
| Backend/API | Python 3.11, FastAPI, Uvicorn, Jinja2 |
| БД | SQLAlchemy 2 (async), asyncpg (Postgres/Neon) / aiosqlite (локально) |
| Бот | aiogram 3 (long polling), APScheduler |
| AI / речь | Anthropic Claude (`claude-sonnet-5`, vision + tool use), Yandex SpeechKit |
| Данные | Forex Factory (FairEconomy JSON-фид) |
| Фронтенд | Server-rendered Jinja + чистый CSS (без фреймворков), inline SVG-графики |
| Деплой | Railway + Neon Postgres |

---

## 🚀 Запуск локально

```bash
cd journal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # заполнить переменные (см. ниже)
python main.py              # → http://localhost:8000
```

Тесты:
```bash
pytest -q
```

- Только веб без бота: `RUN_BOT=0 python main.py`.
- Без `DATABASE_URL` используется локальный SQLite-файл `journal.db`.

---

## ⚙️ Переменные окружения (.env)

| Переменная | Обяз. | Назначение |
|---|:--:|---|
| `DATABASE_URL` | — | Postgres (Neon/Railway). Пусто → локальный SQLite. `postgres://` и параметры `sslmode/channel_binding` нормализуются под asyncpg |
| `TELEGRAM_BOT_TOKEN` | для бота | Токен от @BotFather |
| `ALLOWED_TELEGRAM_USER_ID` | для бота | Твой numeric Telegram id (@userinfobot). Бот отвечает только ему |
| `ANTHROPIC_API_KEY` | для бота | Ключ Claude (vision + извлечение) |
| `CLAUDE_MODEL` | — | По умолчанию `claude-sonnet-5` |
| `YANDEX_SPEECHKIT_API_KEY` | для голоса | Распознавание голосовых |
| `YANDEX_STT_LANG` | — | Язык распознавания, по умолчанию `ru-RU` |
| `WEB_PASSWORD` | — | Пароль на вход в дашборд. Пусто → без логина |
| `WEB_BASE_URL` | — | Публичный URL сайта — бот делает ссылки на сделки |
| `INITIAL_BALANCE` | — | Стартовый баланс для виджета «Баланс» (live) |
| `TRADER_TIMEZONE` | — | Таймзона сессий, по умолчанию `America/New_York` |
| `NOTIFY_TIMEZONE` | — | Локальная таймзона для уведомлений, по умолчанию `Asia/Tashkent` |
| `SESSION_ALERTS` | — | Алерты сессий и красных релизов (`0` — выключить) |
| `NEWS_IMPACTS` | — | Уровни новостей в сводке, по умолчанию `High,Medium,Holiday` |
| `RUN_BOT` | — | `0` — не запускать бота (только веб) |

### Где взять
- **Telegram:** @BotFather → `/newbot`. Свой id — @userinfobot.
- **Anthropic:** console.anthropic.com → API Keys.
- **Yandex SpeechKit:** Yandex Cloud → сервисный аккаунт → API-ключ.
- **Postgres:** Neon (neon.tech) или Railway-плагин Postgres.

---

## ☁️ Деплой на Railway

1. **New Project → Deploy from GitHub** → выбрать репозиторий.
2. Добавить переменные окружения из таблицы выше (Postgres — плагин Railway или строка Neon).
3. Start-команда берётся из `railway.json` / `Procfile`:
   `uvicorn web.app:app --host 0.0.0.0 --port $PORT`
4. Бот стартует внутри того же процесса (long polling); веб доступен по домену.
5. **Public Networking** → Generate Domain → вписать его в `WEB_BASE_URL`.

Проверка: `https://<домен>/health` → `{"ok":true}`.

---

## 🌐 Веб-маршруты

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` `?mode&period&y&m` | Дашборд (Live/Backtest) |
| GET | `/calendar` | Фрагмент календаря (AJAX) |
| GET | `/trades` `?mode` | Журнал сделок |
| GET/POST | `/new` · `/trades` | Форма и создание сделки |
| GET/POST | `/trade/{id}` | Детали и правка/закрытие (`action=save\|close`) |
| POST | `/trade/{id}/delete` | Удаление |
| GET | `/chart/{id}/{before\|after}` | Скриншот сделки |
| GET | `/api/stats` `?period&mode` | Статистика в JSON |
| GET | `/api/trades` `?period&mode&format=json\|csv` | Экспорт сделок (для pandas) |
| GET | `/health` | Healthcheck |
| GET/POST | `/login` · `/logout` | Авторизация (если задан `WEB_PASSWORD`) |

---

## 💬 Примеры сообщений боту

- **Новая:** фото графика + `EURUSD long, вход 1.0850, стоп 1.0832, тейк 1.0905, NY reversal, OTE 0.705, MSS есть`
- Фото без подписи → следом голосовое с описанием.
- **Закрытие:** `закрыл EURUSD +1.8R`
- **Правка:** `исправь: стоп был 1.0832`
- `/stats` — за неделю, `/stats month` — за месяц.

---

## 🗄 Модель данных

**Trade** — сделка: время, пара, направление, entry/SL/TP, лот, риск %, RR planned, result R/$, outcome, status (Open/Closed), **mode (live/backtest)**, ICT-контекст (session, sb_window, asia_type, setup, sweep_reference, ote_level, mss_confirmed, news_blackout), психология (plan_followed, violation_type, emotion, notes), raw_message, скриншоты (before/after хранятся в БД).

**Setting** — key/value (текущий режим бота на пользователя).

---

## ⚠️ Ограничения / заметки

- **Actual в новостях.** Бесплатный фид Forex Factory (FairEconomy) отдаёт только `forecast/previous` — фактического значения (`actual`) в нём нет, а сайт FF за Cloudflare. Поэтому алерт красной новости приходит в момент выхода с прогнозом/предыдущим (без Actual). Живой Actual можно добавить через платный API (напр. JBlanked) — задел в коде есть.
- **Публичный доступ.** Без `WEB_PASSWORD` сайт открыт по ссылке — задай пароль, если не хочешь.
- **Один пользователь.** Бот работает по whitelist одного Telegram id.
- **Скриншоты в БД.** Графики сжимаются (resize ≤1280px + WebP) и хранятся inline в Postgres.

### Операционные заметки
- **Только 1 реплика на Railway** (`numReplicas: 1` в `railway.json`) — иначе два long-polling бота и дубли алертов APScheduler.
- **Пароль на дашборд.** `WEB_PASSWORD` включает логин с 1-часовой сессией; на `/login` стоит примитивный rate-limit (5 попыток / 5 мин на IP).
- **Бэкапы.** У Neon free короткая история восстановления — настрой периодический `pg_dump`.
- **Экспорт.** `GET /api/trades?mode=&period=&format=json|csv` — для анализа в pandas.
- **Целостность ввода.** Бот показывает карточку с кнопками ✅/✏️/❌ и пишет в БД только после подтверждения (защита от тихого misparse цен).

---

<div align="center"><sub>R-based ICT trading log · Sweep → MSS → OTE</sub></div>
