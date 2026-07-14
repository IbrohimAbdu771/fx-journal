"""Server-side chart helpers — inline SVG / plain data (no external JS/CDN)."""
from __future__ import annotations

import calendar as _cal
from datetime import date, datetime
from zoneinfo import ZoneInfo

MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def equity_curve_svg(points: list[dict], width: int = 760, height: int = 220, pad: int = 24) -> str:
    """Cumulative-R equity curve as an inline SVG with a zero baseline."""
    if not points:
        return '<div class="empty">Нет закрытых сделок</div>'
    ys = [p["r_cum"] for p in points]
    xs = list(range(len(points)))
    y_min = min(0.0, min(ys))
    y_max = max(0.0, max(ys))
    span = (y_max - y_min) or 1.0
    x_span = (len(points) - 1) or 1

    def sx(i: int) -> float:
        return pad + (i / x_span) * (width - 2 * pad)

    def sy(v: float) -> float:
        return height - pad - ((v - y_min) / span) * (height - 2 * pad)

    line = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in zip(xs, ys))
    area = f"{sx(0):.1f},{sy(y_min):.1f} " + line + f" {sx(xs[-1]):.1f},{sy(y_min):.1f}"
    zero_y = sy(0.0)
    up = ys[-1] >= 0
    stroke = "#22c55e" if up else "#ef4444"
    fill = "rgba(34,197,94,.12)" if up else "rgba(239,68,68,.12)"
    return (
        f'<svg viewBox="0 0 {width} {height}" class="equity" preserveAspectRatio="none">'
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" '
        f'stroke="#3a4256" stroke-dasharray="4 4"/>'
        f'<polygon points="{area}" fill="{fill}"/>'
        f'<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="2"/>'
        f"</svg>"
    )


def distribution_bars(dist: dict) -> list[dict]:
    """R-multiple distribution → bars data for the template."""
    if not dist:
        return []
    mx = max(dist.values()) or 1
    out = []
    for label, count in dist.items():
        out.append(
            {
                "label": label,
                "count": count,
                "pct": round(count / mx * 100),
                "neg": label.startswith("-") or label.startswith("≤"),
            }
        )
    return out


def build_calendar(daily: list[dict], tz: str, year: int | None = None, month: int | None = None) -> dict:
    """Monthly P&L calendar (green/red/grey days), TradeZella-style."""
    today = datetime.now(ZoneInfo(tz)).date()
    year = year or today.year
    month = month or today.month
    by_date: dict[str, dict] = {d["date"]: d for d in daily}

    weeks: list[list[dict]] = []
    month_r = 0.0
    month_trades = 0
    for week in _cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for day in week:
            in_month = day.month == month
            info = by_date.get(day.isoformat())
            cls = "out" if not in_month else "empty"
            r = trades = 0
            if info and in_month:
                r = info["r"]
                trades = info["trades"]
                cls = "win" if r > 0 else "loss" if r < 0 else "be"
                month_r += r
                month_trades += trades
            row.append(
                {"day": day.day, "date": day.isoformat(), "in_month": in_month,
                 "r": r, "trades": trades, "cls": cls}
            )
        weeks.append(row)
    return {
        "label": f"{MONTHS_RU[month]} {year}",
        "weekdays": WEEKDAYS_RU,
        "weeks": weeks,
        "month_r": round(month_r, 2),
        "month_trades": month_trades,
        "year": year,
        "month": month,
    }
