"""Telegram bot (aiogram 3, long polling).

Ingests trades from photo (chart) + text/voice, parses them with Claude, writes
to the shared database, and answers /stats /last /open. Responds ONLY to the
whitelisted user id.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from core import repository, service, stats
from core.ict import now_ny
from .parser import TradeParser
from .transcribe import TranscriptionError, transcribe_ogg

logger = logging.getLogger(__name__)

IMAGE_TTL = 300  # seconds a stashed chart waits for its description


def _fmt(v, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}{suffix}"
    return f"{v}{suffix}"


def format_trade_card(t: dict, title: str = "✅ Записал сделку") -> str:
    lines = [f"{title} #{t['id']} — {t.get('name') or ''}".rstrip()]
    lines.append(f"{t.get('pair') or '—'} {t.get('direction') or ''}  [{t.get('status')}]".strip())
    lines.append(
        f"Entry {_fmt(t.get('entry'))} | SL {_fmt(t.get('stop_loss'))} | "
        f"TP {_fmt(t.get('take_profit'))} | RR {_fmt(t.get('rr_planned'))}"
    )
    if t.get("lot") is not None or t.get("risk_pct") is not None:
        lines.append(f"Lot {_fmt(t.get('lot'))} | Risk {_fmt(t.get('risk_pct'), '%')}")
    ctx = []
    if t.get("session"):
        ctx.append(t["session"])
    if t.get("sb_window"):
        ctx.append("SB")
    if t.get("setup"):
        ctx.append(t["setup"])
    if t.get("sweep_reference"):
        ctx.append(f"sweep {t['sweep_reference']}")
    if t.get("ote_level"):
        ctx.append(f"OTE {t['ote_level']}")
    if t.get("mss_confirmed"):
        ctx.append("MSS✓")
    if ctx:
        lines.append(" · ".join(ctx))
    if t.get("outcome") or t.get("result_r") is not None:
        lines.append(
            f"Результат: {t.get('outcome') or '—'}  "
            f"{_fmt(t.get('result_r'), 'R')}  {_fmt(t.get('result_usd'), '$')}"
        )
    disc = []
    if t.get("plan_followed"):
        disc.append(t["plan_followed"])
    if t.get("emotion"):
        disc.append(t["emotion"])
    if t.get("violation_type"):
        disc.append("нарушения: " + ", ".join(t["violation_type"]))
    if disc:
        lines.append(" · ".join(disc))
    if t.get("notes"):
        lines.append(f"📝 {t['notes']}")
    return "\n".join(lines)


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

    # only the owner
    router.message.filter(F.from_user.id == cfg.allowed_user_id)

    stashed_image: dict[int, tuple[bytes, str, float]] = {}
    pending_clarify: dict[int, int] = {}  # uid -> trade_id awaiting missing fields

    def _link(trade_id: int) -> str:
        return f"\n🔗 {web_base}/trade/{trade_id}" if web_base else ""

    async def _download(message: Message, file) -> bytes:
        buf = await message.bot.download(file)
        return buf.read()

    async def _reply_new(message: Message, data: dict, image: bytes | None, mime: str):
        trade_time = now_ny(cfg.timezone)
        enriched = service.enrich(data, trade_time, cfg.timezone)
        enriched["raw_message"] = data.get("raw_message")
        trade = await repository.add_trade(
            enriched, chart_before=image, chart_before_mime=mime if image else None
        )
        uid = message.from_user.id
        missing = service.missing_critical(enriched)
        text = format_trade_card(trade) + _link(trade["id"])
        if missing:
            pending_clarify[uid] = trade["id"]
            text += f"\n\n❓ Не хватает: {', '.join(missing)}. Ответь одним сообщением, я допишу."
        await message.answer(text)

    async def _reply_close(message: Message, data: dict, image: bytes | None, mime: str):
        pair = data.get("pair")
        target = await repository.find_last_open(pair)
        if not target:
            await message.answer("Не нашёл открытую сделку" + (f" по {pair}." if pair else "."))
            return
        trade = await repository.close_trade(
            target["id"],
            result_r=data.get("result_r"),
            result_usd=data.get("result_usd"),
            outcome=data.get("outcome"),
            chart_after=image,
            chart_after_mime=mime if image else None,
        )
        # extra notes/discipline on close
        extra = {k: data.get(k) for k in ("notes", "plan_followed", "emotion", "violation_type")
                 if data.get(k)}
        if extra:
            trade = await repository.update_trade(trade["id"], extra)
        await message.answer(format_trade_card(trade, "🔒 Закрыл сделку") + _link(trade["id"]))
        # mini weekly summary
        since, _ = _since("week", cfg.timezone)
        s = stats.compute_stats(await repository.stats_dicts(since))
        await message.answer(
            f"За неделю: {s.total_r:+.2f}R · WR {s.winrate * 100:.0f}% · "
            f"серия {s.streak:+d} · Zella {s.zella_score:.0f}"
        )

    async def _reply_edit(message: Message, data: dict):
        last = await repository.get_last_trade()
        if not last:
            await message.answer("Нет записей для правки.")
            return
        fields = {k: data.get(k) for k in service.EDITABLE_FIELDS if data.get(k) not in (None, [], "")}
        merged = {**last, **fields}
        enriched = service.enrich(merged, last.get("trade_time") or now_ny(cfg.timezone), cfg.timezone)
        trade = await repository.update_trade(last["id"], enriched)
        await message.answer(format_trade_card(trade, "✏️ Обновил") + _link(trade["id"]))

    async def _process(message: Message, text: str | None, image: bytes | None, mime: str = "image/jpeg"):
        uid = message.from_user.id

        # 1) clarification merge
        if uid in pending_clarify and text:
            trade_id = pending_clarify.pop(uid)
            data = await parser.extract(text=text, image_bytes=image, image_media_type=mime)
            base = await repository.get_trade(trade_id)
            if base:
                fields = {k: data.get(k) for k in service.EDITABLE_FIELDS
                          if data.get(k) not in (None, [], "")}
                merged = {**base, **fields}
                enriched = service.enrich(merged, base.get("trade_time"), cfg.timezone)
                trade = await repository.update_trade(trade_id, enriched)
                await message.answer(format_trade_card(trade, "✅ Дополнил") + _link(trade_id))
                return

        # 2) stash image without description
        if image and not (text and text.strip()):
            stashed_image[uid] = (image, mime, time.time())
            await message.answer("📸 Фото получил. Добавь описание текстом или голосом.")
            return

        # 3) pull a recently stashed image if this message is text-only
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
                "или /stats, /last, /open."
            )

    # ---- handlers ----
    @router.message(Command("start", "help"))
    async def cmd_start(message: Message):
        await message.answer(
            "📓 FX Journal\n\n"
            "• Новая сделка: фото графика с подписью, или фото + голосовое.\n"
            "• Закрытие: «закрыл EURUSD +1.8R» (можно скрин после).\n"
            "• Правка: «исправь: стоп был 1.0832».\n\n"
            "Команды: /stats [month] · /last · /open"
        )

    @router.message(Command("stats"))
    async def cmd_stats(message: Message):
        period = (message.text or "").partition(" ")[2].strip() or "week"
        since, label = _since(period, cfg.timezone)
        s = stats.compute_stats(await repository.stats_dicts(since))
        await message.answer(stats.format_stats(s, f"📊 Статистика ({label})"))

    @router.message(Command("last"))
    async def cmd_last(message: Message):
        last = await repository.get_last_trade()
        if not last:
            await message.answer("Записей пока нет.")
            return
        await message.answer(format_trade_card(last, "🗒 Последняя") + _link(last["id"]))
        chart = await repository.get_chart(last["id"], "before")
        if chart:
            await message.answer_photo(BufferedInputFile(chart[0], "chart.jpg"))

    @router.message(Command("open"))
    async def cmd_open(message: Message):
        opens = await repository.get_open_trades()
        if not opens:
            await message.answer("Открытых позиций нет.")
            return
        await message.answer("\n\n".join(format_trade_card(t, "🟢 Открыта") for t in opens))

    @router.message(F.photo)
    async def on_photo(message: Message):
        image = await _download(message, message.photo[-1])
        await _process(message, message.caption, image, "image/jpeg")

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


async def run_bot(cfg) -> None:
    """Build the bot, start the weekly scheduler, and poll until cancelled."""
    from .scheduler import start_scheduler  # local import to avoid cycle

    bot, dp = build_dispatcher(cfg)
    parser = TradeParser(cfg.anthropic_api_key, cfg.claude_model)
    scheduler = start_scheduler(cfg, bot, parser)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram bot polling started")
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:  # graceful shutdown from the web lifespan
        logger.info("Telegram bot polling cancelled")
        raise
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
