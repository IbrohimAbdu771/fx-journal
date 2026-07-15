"""Async CRUD over the trades table + fetch helpers for analytics.

Each function manages its own transactional session, so callers (bot handlers,
web routes) just await them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .db import session_scope
from .models import Setting, Trade
from .service import EDITABLE_FIELDS

_SETTABLE = set(EDITABLE_FIELDS) | {"trade_time", "closed_at", "name", "rr_planned"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _apply(trade: Trade, fields: dict) -> None:
    for key, value in fields.items():
        if key in _SETTABLE:
            setattr(trade, key, value)


async def add_trade(
    enriched: dict,
    *,
    chart_before: bytes | None = None,
    chart_before_mime: str | None = None,
) -> dict:
    async with session_scope() as s:
        trade = Trade()
        _apply(trade, enriched)
        if chart_before is not None:
            trade.chart_before = chart_before
            trade.chart_before_mime = chart_before_mime
        if trade.status == "Closed" and trade.closed_at is None:
            trade.closed_at = _utcnow()
        s.add(trade)
        await s.flush()
        return trade.to_dict()


async def get_trade(trade_id: int) -> dict | None:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        return trade.to_dict() if trade else None


async def find_last_open(pair: str | None = None, mode: str = "live") -> dict | None:
    async with session_scope() as s:
        stmt = select(Trade).where(Trade.status == "Open", Trade.mode == mode)
        if pair:
            stmt = stmt.where(Trade.pair == pair)
        stmt = stmt.order_by(Trade.trade_time.desc()).limit(1)
        trade = (await s.execute(stmt)).scalars().first()
        return trade.to_dict() if trade else None


async def get_open_trades(mode: str = "live") -> list[dict]:
    async with session_scope() as s:
        stmt = (
            select(Trade)
            .where(Trade.status == "Open", Trade.mode == mode)
            .order_by(Trade.trade_time.desc())
        )
        return [t.to_dict() for t in (await s.execute(stmt)).scalars().all()]


async def get_last_trade(mode: str = "live") -> dict | None:
    async with session_scope() as s:
        stmt = select(Trade).where(Trade.mode == mode).order_by(Trade.created_at.desc()).limit(1)
        trade = (await s.execute(stmt)).scalars().first()
        return trade.to_dict() if trade else None


async def update_trade(trade_id: int, fields: dict) -> dict | None:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        if not trade:
            return None
        _apply(trade, fields)
        if trade.status == "Closed" and trade.closed_at is None:
            trade.closed_at = _utcnow()
        await s.flush()
        return trade.to_dict()


async def close_trade(
    trade_id: int,
    *,
    result_r: float | None = None,
    result_usd: float | None = None,
    mae_r: float | None = None,
    mfe_r: float | None = None,
    outcome: str | None = None,
    chart_after: bytes | None = None,
    chart_after_mime: str | None = None,
    closed_at: datetime | None = None,
) -> dict | None:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        if not trade:
            return None
        if result_r is not None:
            trade.result_r = result_r
        if result_usd is not None:
            trade.result_usd = result_usd
        if mae_r is not None:
            trade.mae_r = mae_r
        if mfe_r is not None:
            trade.mfe_r = mfe_r
        if outcome is not None:
            trade.outcome = outcome
        elif trade.outcome is None and result_r is not None:
            trade.outcome = "Win" if result_r > 0 else "Loss" if result_r < 0 else "Breakeven"
        trade.status = "Closed"
        trade.closed_at = closed_at or _utcnow()
        if chart_after is not None:
            trade.chart_after = chart_after
            trade.chart_after_mime = chart_after_mime
        await s.flush()
        return trade.to_dict()


async def delete_trade(trade_id: int) -> bool:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        if not trade:
            return False
        await s.delete(trade)
        return True


async def list_trades(limit: int = 200, since: datetime | None = None,
                      mode: str = "live") -> list[dict]:
    async with session_scope() as s:
        stmt = select(Trade).where(Trade.mode == mode)
        if since:
            stmt = stmt.where(Trade.trade_time >= since)
        stmt = stmt.order_by(Trade.trade_time.desc()).limit(limit)
        return [t.to_dict() for t in (await s.execute(stmt)).scalars().all()]


async def stats_dicts(since: datetime | None = None, mode: str = "live") -> list[dict]:
    """Rows shaped for core.stats.compute_stats (oldest→newest)."""
    async with session_scope() as s:
        stmt = select(Trade).where(Trade.mode == mode)
        if since:
            stmt = stmt.where(Trade.trade_time >= since)
        stmt = stmt.order_by(Trade.trade_time.asc())
        return [t.to_stats_dict() for t in (await s.execute(stmt)).scalars().all()]


# --- key/value settings (bot mode etc.) ---------------------------------------
async def get_setting(key: str, default: str | None = None) -> str | None:
    async with session_scope() as s:
        obj = await s.get(Setting, key)
        return obj.value if obj else default


async def set_setting(key: str, value: str) -> None:
    async with session_scope() as s:
        obj = await s.get(Setting, key)
        if obj:
            obj.value = value
        else:
            s.add(Setting(key=key, value=value))


async def set_chart(trade_id: int, which: str, data: bytes, mime: str) -> None:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        if not trade:
            return
        if which == "before":
            trade.chart_before = data
            trade.chart_before_mime = mime
        elif which == "after":
            trade.chart_after = data
            trade.chart_after_mime = mime


async def get_chart(trade_id: int, which: str) -> tuple[bytes, str] | None:
    async with session_scope() as s:
        trade = await s.get(Trade, trade_id)
        if not trade:
            return None
        if which == "before" and trade.chart_before:
            return trade.chart_before, trade.chart_before_mime or "image/jpeg"
        if which == "after" and trade.chart_after:
            return trade.chart_after, trade.chart_after_mime or "image/jpeg"
        return None
