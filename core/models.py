"""SQLAlchemy models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, LargeBinary, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    # when the trade actually happened (drives session/weekday/daily math)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # instrument / direction
    pair: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # prices / sizing
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rr_planned: Mapped[float | None] = mapped_column(Float, nullable=True)

    # result
    result_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="Open", index=True)

    # ICT context
    session: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sb_window: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    asia_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    setup: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    sweep_reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ote_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mss_confirmed: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    news_blackout: Mapped[bool | None] = mapped_column(default=None, nullable=True)

    # psychology / discipline
    plan_followed: Mapped[str | None] = mapped_column(String(40), nullable=True)
    violation_type: Mapped[list | None] = mapped_column(JSON, default=list)
    emotion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # charts (stored inline so nothing depends on external file storage)
    chart_before: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    chart_before_mime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chart_after: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    chart_after_mime: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ---- serialization ----
    STATS_FIELDS = (
        "result_r", "result_usd", "outcome", "status",
        "session", "setup", "pair", "direction", "trade_time",
    )

    def to_stats_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.STATS_FIELDS}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "trade_time": self.trade_time,
            "closed_at": self.closed_at,
            "name": self.name,
            "pair": self.pair,
            "direction": self.direction,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "lot": self.lot,
            "risk_pct": self.risk_pct,
            "rr_planned": self.rr_planned,
            "result_r": self.result_r,
            "result_usd": self.result_usd,
            "outcome": self.outcome,
            "status": self.status,
            "session": self.session,
            "sb_window": self.sb_window,
            "asia_type": self.asia_type,
            "setup": self.setup,
            "sweep_reference": self.sweep_reference,
            "ote_level": self.ote_level,
            "mss_confirmed": self.mss_confirmed,
            "news_blackout": self.news_blackout,
            "plan_followed": self.plan_followed,
            "violation_type": self.violation_type or [],
            "emotion": self.emotion,
            "notes": self.notes,
            "raw_message": self.raw_message,
            "has_chart_before": self.chart_before is not None,
            "has_chart_after": self.chart_after is not None,
        }
