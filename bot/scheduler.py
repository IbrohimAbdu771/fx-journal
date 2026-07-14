"""Scheduler — weekly report + ICT session-open alerts.

Session alerts are anchored to NY time (the ICT model: London killzone 02:00 NY,
NY killzone 07:00 NY) so they stay correct across DST, and the message shows the
user's local (Tashkent) time.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import repository, stats
from core.ict import now_ny
from . import news

logger = logging.getLogger(__name__)

# session, kind, NY hour, NY minute
SESSION_SCHEDULE = [
    ("London", "warn", 1, 30),   # 30 минут до открытия London
    ("London", "open", 2, 0),    # London killzone open
    ("NY", "open", 7, 0),        # NY killzone open
]
SESSION_META = {
    "London": {"emoji": "🇬🇧", "window": "02:00–05:00 NY", "sb": "SB LO · 03:00–04:00 NY"},
    "NY": {"emoji": "🇺🇸", "window": "07:00–10:00 NY", "sb": "SB NY AM · 10:00–11:00 NY"},
}

WEEKLY_SYSTEM = (
    "Ты — наставник по ICT-трейдингу (форекс EURUSD/GBPUSD, модель Sweep→MSS→OTE). "
    "Кратко и по делу проанализируй неделю трейдера: паттерны ошибок, лучшие/худшие "
    "сетапы и сессии, дисциплина, 2–3 конкретные рекомендации на следующую неделю. "
    "Без воды, маркированным списком, по-русски."
)


def _trades_digest(trades: list[dict]) -> str:
    rows = []
    for t in trades:
        rows.append(
            f"- {t.get('pair') or '?'} {t.get('direction') or ''} "
            f"[{t.get('session') or '?'}/{t.get('setup') or '?'}] "
            f"{t.get('outcome') or 'open'} {t.get('result_r')}R "
            f"plan={t.get('plan_followed') or '?'} emo={t.get('emotion') or '?'} "
            f"viol={','.join(t.get('violation_type') or []) or '-'}"
        )
    return "\n".join(rows) if rows else "(нет сделок)"


async def build_weekly_report(cfg, parser) -> str:
    since = now_ny(cfg.timezone) - timedelta(days=7)
    trades = await repository.list_trades(limit=500, since=since)
    s = stats.compute_stats(await repository.stats_dicts(since))
    header = stats.format_stats(s, "📅 Итоги недели")
    if s.total == 0:
        return header + "\n\nНа этой неделе закрытых сделок нет."
    user_prompt = (
        f"Сводка недели:\n{header}\n\nСделки:\n{_trades_digest(trades)}\n\n"
        "Дай анализ и рекомендации."
    )
    try:
        analysis = await parser.summarize(WEEKLY_SYSTEM, user_prompt)
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("Weekly analysis failed: %s", exc)
        analysis = "(анализ Claude недоступен)"
    return f"{header}\n\n🧠 Разбор недели:\n{analysis}"


async def session_alert(cfg, bot, name: str, kind: str) -> None:
    meta = SESSION_META[name]
    local = datetime.now(ZoneInfo(cfg.notify_timezone)).strftime("%H:%M")
    ny = datetime.now(ZoneInfo(cfg.timezone)).strftime("%H:%M")
    tzlabel = cfg.notify_timezone.split("/")[-1]
    if kind == "warn":
        head = f"⏰ <b>{name}</b> {meta['emoji']} через 30 минут"
    else:
        head = f"🔔 <b>{name} session</b> {meta['emoji']} открылась"
    text = (
        f"{head}\n"
        f"🕐 {local} ({tzlabel}) · {ny} NY\n"
        f"⏱ Окно: {meta['window']}\n"
        f"🥈 {meta['sb']}\n\n"
        f"Sweep → MSS → OTE. Не входи вне окна."
    )
    try:
        await bot.send_message(cfg.allowed_user_id, text, parse_mode="HTML")
        logger.info("Session alert sent: %s/%s", name, kind)
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("Session alert failed: %s", exc)


async def release_alert(cfg, bot, ev: dict) -> None:
    """Fire when a red (High-impact) USD/EUR/GBP event is released."""
    flag = news.CCY_FLAG.get(ev["ccy"], "")
    tzlabel = cfg.notify_timezone.split("/")[-1]
    t = ev["dt"].strftime("%H:%M")
    lines = [
        f"🔴 <b>{html.escape(ev['ccy'])} · {html.escape(ev['title'])}</b> {flag}",
        f"🗞 Красная новость вышла · {t} ({tzlabel})",
    ]
    det = []
    if ev["forecast"]:
        det.append(f"прогноз <b>{html.escape(ev['forecast'])}</b>")
    if ev["previous"]:
        det.append(f"пред. {html.escape(ev['previous'])}")
    if det:
        lines.append("📊 " + " · ".join(det))
    lines.append("\nПроверь фактическое (Actual) на графике · вход только по модели.")
    try:
        await bot.send_message(cfg.allowed_user_id, "\n".join(lines), parse_mode="HTML")
        logger.info("Release alert sent: %s %s", ev["ccy"], ev["title"])
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("Release alert failed: %s", exc)


async def schedule_red_releases(scheduler, cfg, bot) -> None:
    """(Re)schedule one-off alerts for today's remaining red USD/EUR/GBP events."""
    try:
        items = await news.fetch_calendar()
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("Release planner fetch failed: %s", exc)
        return
    now = datetime.now(ZoneInfo(cfg.notify_timezone))
    events = news.events_for_day(items, cfg.notify_timezone, now.date(), impacts={"High"})

    for job in list(scheduler.get_jobs()):
        if job.id.startswith("rel_"):
            scheduler.remove_job(job.id)

    scheduled = 0
    for i, ev in enumerate(events):
        if ev["dt"] <= now:  # already released today
            continue
        scheduler.add_job(
            release_alert, "date", run_date=ev["dt"], args=[cfg, bot, ev],
            id=f"rel_{i}_{ev['dt'].strftime('%H%M')}", replace_existing=True,
            misfire_grace_time=300,
        )
        scheduled += 1
    logger.info("Red-news releases scheduled today: %d", scheduled)


def start_scheduler(cfg, bot, parser) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=cfg.timezone)

    async def weekly_job():
        try:
            report = await build_weekly_report(cfg, parser)
            await bot.send_message(cfg.allowed_user_id, report)
            logger.info("Weekly report sent")
        except Exception as exc:  # pragma: no cover
            logger.exception("Weekly report job failed: %s", exc)

    scheduler.add_job(weekly_job, "cron", day_of_week="sun", hour=20, minute=0, id="weekly_report")

    if cfg.session_alerts:
        for name, kind, hour, minute in SESSION_SCHEDULE:
            scheduler.add_job(
                session_alert, "cron", args=[cfg, bot, name, kind],
                day_of_week="mon-fri", hour=hour, minute=minute, id=f"{name}_{kind}",
            )
        logger.info("Session alerts on (display tz: %s)", cfg.notify_timezone)

        async def release_planner():
            await schedule_red_releases(scheduler, cfg, bot)

        # plan today's red releases right after start, then refresh every 6h
        scheduler.add_job(
            release_planner, "interval", hours=6,
            next_run_time=datetime.now(ZoneInfo(cfg.timezone)) + timedelta(seconds=10),
            id="release_planner",
        )

    async def news_job():
        try:
            text = await news.daily_news_text(cfg.notify_timezone)
            await bot.send_message(cfg.allowed_user_id, text, parse_mode="HTML")
            logger.info("Daily news sent")
        except Exception as exc:  # pragma: no cover - network path
            logger.exception("News job failed: %s", exc)

    scheduler.add_job(news_job, "cron", hour=10, minute=0,
                      timezone=cfg.notify_timezone, id="news_daily")

    scheduler.start()
    logger.info("Scheduler started (weekly Sun 20:00 %s)", cfg.timezone)
    return scheduler
