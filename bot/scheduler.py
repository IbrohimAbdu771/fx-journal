"""Weekly report scheduler — Sundays 20:00 in the trader's timezone."""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import repository, stats
from core.ict import now_ny

logger = logging.getLogger(__name__)

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


def start_scheduler(cfg, bot, parser) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=cfg.timezone)

    async def job():
        try:
            report = await build_weekly_report(cfg, parser)
            await bot.send_message(cfg.allowed_user_id, report)
            logger.info("Weekly report sent")
        except Exception as exc:  # pragma: no cover
            logger.exception("Weekly report job failed: %s", exc)

    scheduler.add_job(job, "cron", day_of_week="sun", hour=20, minute=0, id="weekly_report")
    scheduler.start()
    logger.info("Scheduler started (weekly report Sun 20:00 %s)", cfg.timezone)
    return scheduler
