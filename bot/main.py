"""Telegram bot (aiogram 3, long polling).

Ingests trades from photo (chart) + text/voice, parses them with Claude, writes
to the shared database, and answers /stats /last /open. Responds ONLY to the
whitelisted user id. Trade cards are rendered as formatted HTML.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)

from core import imaging, repository, service, stats
from core.ict import now_ny
from . import news
from .parser import TradeParser
from .transcribe import TranscriptionError, transcribe_ogg

logger = logging.getLogger(__name__)

IMAGE_TTL = 300  # seconds a stashed chart waits for its description
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
NEWS_BTN = "📰 Новости дня"
LIVE_BTN = "🟢 Live"
BT_BTN = "🧪 Backtest"
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=LIVE_BTN), KeyboardButton(text=BT_BTN)],
        [KeyboardButton(text=NEWS_BTN)],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def _mode_title(base: str, mode: str) -> str:
    return f"{base} · 🧪 BACKTEST" if mode == "backtest" else base


CONFIRM_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Сохранить", callback_data="nt:save"),
    InlineKeyboardButton(text="✏️ Исправить", callback_data="nt:edit"),
    InlineKeyboardButton(text="❌ Отмена", callback_data="nt:cancel"),
]])


def _v(x, nd: int | None = None) -> str | None:
    if x is None:
        return None
    if isinstance(x, float):
        return f"{x:.{nd}f}" if nd is not None else f"{x:g}"
    return str(x)


def _esc(x) -> str:
    return html.escape(str(x))


def _clean_excursion(v) -> float | None:
    """MAE/MFE are non-negative modules; drop anything else (None stays None)."""
    return float(v) if isinstance(v, (int, float)) and v >= 0 else None


def format_trade_card(t: dict, title: str = "✅ Сделка записана") -> str:
    """Render a trade (or an unsaved preview without id) as an HTML card."""
    head = f"<b>{title}</b>"
    if t.get("id"):
        head += f"  ·  #{t['id']}"
    L: list[str] = [head]

    pairdir = " · ".join(x for x in [t.get("pair"), (t.get("direction") or "").upper()] if x)
    status = t.get("status") or ""
    dot = "🟢" if status == "Open" else "⚪️"
    head = f"<b>{_esc(pairdir) or '—'}</b>"
    if status:
        head += f"   {dot} {status}"
    L.append(head)

    # result banner (closed / has result)
    if t.get("result_r") is not None or t.get("outcome"):
        r = t.get("result_r")
        emoji = "🏆" if (r or 0) > 0 else ("💔" if (r or 0) < 0 else "➖")
        parts = []
        if r is not None:
            parts.append(f"{r:+.2f}R")
        if t.get("result_usd") is not None:
            parts.append(f"{t['result_usd']:+.2f}$")
        if t.get("outcome"):
            parts.append(t["outcome"])
        L.append(f"{emoji} <b>{' · '.join(parts)}</b>")

    # MAE / MFE excursions (only when at least one is logged)
    if t.get("mae_r") is not None or t.get("mfe_r") is not None:
        mae = f"{t['mae_r']:.2f}R" if t.get("mae_r") is not None else "—"
        mfe = f"{t['mfe_r']:.2f}R" if t.get("mfe_r") is not None else "—"
        L.append(f"<pre>MAE {mae} · MFE {mfe}</pre>")

    # price block (monospace, aligned)
    price = []
    for lbl, key in (("Entry", "entry"), ("Stop", "stop_loss"), ("Take", "take_profit")):
        v = _v(t.get(key))
        if v is not None:
            price.append(f"{lbl:<6}{v}")
    tail = []
    if t.get("rr_planned") is not None:
        tail.append(f"RR {_v(t['rr_planned'])}")
    if t.get("risk_pct") is not None:
        tail.append(f"риск {_v(t['risk_pct'])}%")
    if t.get("lot") is not None:
        tail.append(f"лот {_v(t['lot'])}")
    if tail:
        price.append(("─" * 6) + "  " + "  ".join(tail))
    if price:
        L.append(f"\n<b>💵 Цена</b>\n<pre>{_esc(chr(10).join(price))}</pre>")

    # ICT context
    ict_lines = []
    if t.get("session"):
        s = t["session"] + (" 🥈" if t.get("sb_window") else "")
        ict_lines.append(f"Сессия · {s}")
    if t.get("setup"):
        ict_lines.append(f"Сетап · {_esc(t['setup'])}")
    row = []
    if t.get("sweep_reference"):
        row.append(f"Sweep {t['sweep_reference']}")
    if t.get("ote_level"):
        row.append(f"OTE {t['ote_level']}")
    if t.get("mss_confirmed"):
        row.append("MSS ✓")
    if t.get("asia_type"):
        row.append(f"Asia {t['asia_type']}")
    if row:
        ict_lines.append(" · ".join(row))
    if ict_lines:
        L.append("\n<b>🎯 ICT-контекст</b>")
        L.extend(ict_lines)

    # discipline
    disc = []
    if t.get("plan_followed"):
        disc.append(t["plan_followed"])
    if t.get("emotion"):
        disc.append(t["emotion"])
    if t.get("violation_type"):
        disc.append("⚠️ " + ", ".join(t["violation_type"]))
    if disc:
        L.append("\n<b>🧠 Дисциплина</b>")
        L.append(" · ".join(_esc(d) for d in disc))

    if t.get("notes"):
        L.append(f"\n📝 <i>{_esc(t['notes'])}</i>")
    return "\n".join(L)


def _since(period: str, tz: str):
    now = now_ny(tz)
    if period.startswith("month"):
        return now - timedelta(days=30), "месяц"
    return now - timedelta(days=7), "неделя"


def build_dispatcher(cfg) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=cfg.telegram_bot_token)
    dp = Dispatcher()
    router = Router()
    parser = TradeParser(cfg.anthropic_api_key, cfg.claude_model)
    web_base = os.getenv("WEB_BASE_URL", "").rstrip("/")

    router.message.filter(F.from_user.id == cfg.allowed_user_id)
    router.callback_query.filter(F.from_user.id == cfg.allowed_user_id)

    stashed_image: dict[int, tuple[bytes, str, float]] = {}
    pending_new: dict[int, dict] = {}   # uid -> unsaved trade awaiting confirmation
    awaiting_fix: set[int] = set()      # uid pressed ✏️ — next message is a correction

    def _link(trade_id: int) -> str:
        if not web_base:
            return ""
        return f'\n\n🔗 <a href="{web_base}/trade/{trade_id}">Открыть на сайте</a>'

    async def _card(message: Message, text: str):
        await message.answer(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)

    async def _mode(uid: int) -> str:
        return await repository.get_setting(f"mode:{uid}", "live")

    async def _download(message: Message, file) -> bytes:
        buf = await message.bot.download(file)
        return buf.read()

    async def _send_confirm(message: Message, pend: dict):
        preview = pend["data"]
        mode = preview.get("mode", "live")
        card = format_trade_card(preview, _mode_title("🆕 Проверь и подтверди", mode))
        missing = service.missing_critical(preview)
        if missing:
            card += f"\n\n❓ Не хватает: <b>{', '.join(missing)}</b> — нажми ✏️ и допиши."
        card += "\n\n<i>Проверь цены — Claude мог распознать неточно.</i>"
        await message.answer(card, parse_mode="HTML", reply_markup=CONFIRM_KB,
                             link_preview_options=NO_PREVIEW)

    async def _reply_new(message: Message, data: dict, image: bytes | None, mime: str):
        """Parse → show a confirmation card; write to DB only on ✅."""
        uid = message.from_user.id
        mode = await _mode(uid)
        trade_time = now_ny(cfg.timezone)
        enriched = service.enrich(data, trade_time, cfg.timezone)
        enriched["mode"] = mode
        enriched["raw_message"] = data.get("raw_message")
        pending_new[uid] = {"data": enriched, "image": image, "mime": mime, "trade_time": trade_time}
        awaiting_fix.discard(uid)
        await _send_confirm(message, pending_new[uid])

    async def _reply_close(message: Message, data: dict, image: bytes | None, mime: str):
        mode = await _mode(message.from_user.id)
        pair = data.get("pair")
        target = await repository.find_last_open(pair, mode)
        if not target:
            await message.answer("Не нашёл открытую сделку" + (f" по {pair}." if pair else "."))
            return
        # MAE/MFE are optional; drop invalid (negative) values silently, keep the rest
        mae, mfe = _clean_excursion(data.get("mae_r")), _clean_excursion(data.get("mfe_r"))
        trade = await repository.close_trade(
            target["id"],
            result_r=data.get("result_r"),
            result_usd=data.get("result_usd"),
            mae_r=mae,
            mfe_r=mfe,
            outcome=data.get("outcome"),
            chart_after=image,
            chart_after_mime=mime if image else None,
        )
        extra = {k: data.get(k) for k in ("notes", "plan_followed", "emotion", "violation_type")
                 if data.get(k)}
        if extra:
            trade = await repository.update_trade(trade["id"], extra)
        card = format_trade_card(trade, _mode_title("🔒 Сделка закрыта", mode))
        _, anomalies = service.validate_mae_mfe(trade)
        if anomalies:
            card += "\n\n⚠️ " + "\n⚠️ ".join(_esc(a) for a in anomalies)
        await _card(message, card + _link(trade["id"]))
        since, _ = _since("week", cfg.timezone)
        s = stats.compute_stats(await repository.stats_dicts(since, mode))
        await message.answer(
            f"За неделю: {s.total_r:+.2f}R · WR {s.winrate * 100:.0f}% · "
            f"серия {s.streak:+d} · Zella {s.zella_score:.0f}"
        )

    async def _reply_edit(message: Message, data: dict):
        mode = await _mode(message.from_user.id)
        last = await repository.get_last_trade(mode)
        if not last:
            await message.answer("Нет записей для правки.")
            return
        fields = {k: data.get(k) for k in service.EDITABLE_FIELDS if data.get(k) not in (None, [], "")}
        merged = {**last, **fields}
        enriched = service.enrich(merged, last.get("trade_time") or now_ny(cfg.timezone), cfg.timezone)
        trade = await repository.update_trade(last["id"], enriched)
        card = format_trade_card(trade, _mode_title("✏️ Обновил", mode))
        _, anomalies = service.validate_mae_mfe(trade)
        if anomalies:
            card += "\n\n⚠️ " + "\n⚠️ ".join(_esc(a) for a in anomalies)
        await _card(message, card + _link(trade["id"]))

    async def _process(message: Message, text: str | None, image: bytes | None, mime: str = "image/jpeg"):
        uid = message.from_user.id

        # correction to an UNSAVED pending trade (user pressed ✏️)
        if uid in awaiting_fix and text and uid in pending_new:
            awaiting_fix.discard(uid)
            corr = await parser.extract(text=text)
            pend = pending_new[uid]
            fields = {k: corr.get(k) for k in service.EDITABLE_FIELDS
                      if corr.get(k) not in (None, [], "")}
            merged = {**pend["data"], **fields}
            pend["data"] = service.enrich(merged, pend["trade_time"], cfg.timezone)
            await _send_confirm(message, pend)
            return

        if image and not (text and text.strip()):
            stashed_image[uid] = (image, mime, time.time())
            await message.answer("📸 Фото получил. Добавь описание текстом или голосовым.")
            return

        if not image and uid in stashed_image:
            img, img_mime, ts = stashed_image[uid]
            if time.time() - ts <= IMAGE_TTL:
                image, mime = img, img_mime
            stashed_image.pop(uid, None)

        data = await parser.extract(text=text, image_bytes=image, image_media_type=mime)
        data["raw_message"] = text
        intent = data.get("intent")
        if intent == "close_trade":
            await _reply_close(message, data, image, mime)
        elif intent == "edit_trade":
            await _reply_edit(message, data)
        elif intent == "new_trade" or image:
            await _reply_new(message, data, image, mime)
        else:
            await message.answer(
                "Не понял. Пришли график с подписью, голосовое, «закрыл EURUSD +1.8R» "
                "или команды /stats /last /open."
            )

    def _mode_badge(mode: str) -> str:
        return "🧪 Backtest" if mode == "backtest" else "🟢 Live"

    # ---- handlers ----
    @router.message(Command("start", "help"))
    async def cmd_start(message: Message):
        mode = await _mode(message.from_user.id)
        await message.answer(
            "<b>📓 FX Journal</b>\n"
            "R-based ICT trading log\n\n"
            f"Режим: <b>{_mode_badge(mode)}</b> (переключай кнопками ниже)\n\n"
            "• <b>Новая сделка</b> — фото графика с подписью, или фото + голосовое\n"
            "• <b>Закрытие</b> — «закрыл EURUSD +1.8R» (можно скрин после)\n"
            "• <b>Правка</b> — «исправь: стоп был 1.0832»\n\n"
            "Команды: /stats · /last · /open · /news",
            parse_mode="HTML",
            reply_markup=MAIN_KB,
        )

    @router.message(F.text == LIVE_BTN)
    async def set_live(message: Message):
        await repository.set_setting(f"mode:{message.from_user.id}", "live")
        await message.answer("Режим: 🟢 <b>Live</b>", parse_mode="HTML", reply_markup=MAIN_KB)

    @router.message(F.text == BT_BTN)
    async def set_backtest(message: Message):
        await repository.set_setting(f"mode:{message.from_user.id}", "backtest")
        await message.answer(
            "Режим: 🧪 <b>Backtest</b>\nТестовый журнал, отдельный от лайва — "
            "логируй сделки как обычно, они не смешаются с боевой статистикой.",
            parse_mode="HTML", reply_markup=MAIN_KB,
        )

    @router.message(Command("stats"))
    async def cmd_stats(message: Message):
        mode = await _mode(message.from_user.id)
        period = (message.text or "").partition(" ")[2].strip() or "week"
        since, label = _since(period, cfg.timezone)
        s = stats.compute_stats(await repository.stats_dicts(since, mode))
        await message.answer(stats.format_stats(s, f"📊 Статистика {_mode_badge(mode)} ({label})"))

    @router.message(Command("last"))
    async def cmd_last(message: Message):
        mode = await _mode(message.from_user.id)
        last = await repository.get_last_trade(mode)
        if not last:
            await message.answer(f"Записей в режиме {_mode_badge(mode)} пока нет.")
            return
        await _card(message, format_trade_card(last, _mode_title("🗒 Последняя сделка", mode)) + _link(last["id"]))
        chart = await repository.get_chart(last["id"], "before")
        if chart:
            await message.answer_photo(BufferedInputFile(chart[0], "chart.jpg"))

    @router.message(Command("open"))
    async def cmd_open(message: Message):
        mode = await _mode(message.from_user.id)
        opens = await repository.get_open_trades(mode)
        if not opens:
            await message.answer(f"Открытых позиций ({_mode_badge(mode)}) нет.")
            return
        text = "\n\n".join(format_trade_card(t, _mode_title("🟢 Открыта", mode)) for t in opens)
        await _card(message, text)

    async def _send_news(message: Message):
        try:
            text = await news.daily_news_text(cfg.notify_timezone)
        except Exception as exc:  # pragma: no cover - network path
            logger.exception("News fetch failed: %s", exc)
            text = "Не удалось загрузить новости (Forex Factory недоступен). Попробуй позже."
        await message.answer(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)

    @router.message(Command("news"))
    async def cmd_news(message: Message):
        await _send_news(message)

    @router.message(F.text == NEWS_BTN)
    async def btn_news(message: Message):
        await _send_news(message)

    @router.callback_query(F.data.startswith("nt:"))
    async def on_confirm(cb: CallbackQuery):
        uid = cb.from_user.id
        action = cb.data.split(":", 1)[1]
        pend = pending_new.get(uid)
        if not pend:
            await cb.answer("Сделка уже обработана")
            return
        if action == "cancel":
            pending_new.pop(uid, None)
            awaiting_fix.discard(uid)
            await cb.message.edit_text("❌ Отменено — в базу не записано.")
            await cb.answer("Отменено")
            return
        if action == "edit":
            awaiting_fix.add(uid)
            await cb.answer("Жду исправление")
            await cb.message.answer(
                "✏️ Что исправить? Напиши одним сообщением, напр.: «вход 1.0850, стоп 1.0832»."
            )
            return
        # save
        data, image, mime = pend["data"], pend["image"], pend["mime"]
        pending_new.pop(uid, None)
        awaiting_fix.discard(uid)
        trade = await repository.add_trade(
            data, chart_before=image, chart_before_mime=mime if image else None
        )
        mode = data.get("mode", "live")
        text = format_trade_card(trade, _mode_title("✅ Сохранено", mode)) + _link(trade["id"])
        missing = service.missing_critical(data)
        if missing:
            text += f"\n\n⚠️ Не заполнено: {', '.join(missing)} — допиши на сайте."
        await cb.message.edit_text(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)
        await cb.answer("Записал ✅")

    @router.message(F.photo)
    async def on_photo(message: Message):
        raw = await _download(message, message.photo[-1])
        image, mime = imaging.compress_image(raw)
        await _process(message, message.caption, image, mime)

    @router.message(F.voice)
    async def on_voice(message: Message):
        try:
            audio = await _download(message, message.voice)
            text = await transcribe_ogg(audio, cfg.yandex_speechkit_api_key, cfg.yandex_stt_lang)
        except TranscriptionError as exc:
            await message.answer(f"🎙 {exc}")
            return
        if not text:
            await message.answer("Не распознал речь, повтори или напиши текстом.")
            return
        await message.answer(f"🎙 «{text}»")
        await _process(message, text, None)

    @router.message(F.text)
    async def on_text(message: Message):
        await _process(message, message.text, None)

    dp.include_router(router)
    return bot, dp


BOT_COMMANDS = [
    BotCommand(command="start", description="Меню и помощь"),
    BotCommand(command="news", description="Новости дня (FF)"),
    BotCommand(command="stats", description="Статистика · /stats month"),
    BotCommand(command="last", description="Последняя сделка"),
    BotCommand(command="open", description="Открытые позиции"),
]


async def run_bot(cfg) -> None:
    """Build the bot, register the command menu, start the scheduler, poll."""
    from .scheduler import start_scheduler

    bot, dp = build_dispatcher(cfg)
    parser = TradeParser(cfg.anthropic_api_key, cfg.claude_model)
    scheduler = start_scheduler(cfg, bot, parser)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(BOT_COMMANDS)
        logger.info("Telegram bot polling started")
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        logger.info("Telegram bot polling cancelled")
        raise
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
