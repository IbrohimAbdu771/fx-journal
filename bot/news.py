"""Forex Factory economic calendar → formatted daily news for the bot.

Uses the free FairEconomy JSON feed (this week). Filters to USD/EUR/GBP and to
high (🔴) / medium (🟡) impact plus bank holidays (⚪️). Times are shown in the
user's local timezone (Tashkent by default).
"""
from __future__ import annotations

import html
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CURRENCIES = {"USD", "EUR", "GBP"}
# red = High, yellow = Medium, gray = Holiday. Low-impact (speeches/minor) is
# filtered as noise; override with NEWS_IMPACTS="High,Medium,Low,Holiday".
DEFAULT_IMPACTS = "High,Medium,Holiday"
IMPACT_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "🟡", "Holiday": "⚪️"}
CCY_FLAG = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧"}
WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _allowed_impacts() -> set[str]:
    return {i.strip() for i in os.getenv("NEWS_IMPACTS", DEFAULT_IMPACTS).split(",") if i.strip()}


async def fetch_calendar(timeout: float = 20.0) -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0 (FX-Journal bot)"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        resp = await client.get(FF_URL)
        resp.raise_for_status()
        return resp.json()


def events_for_day(items: list[dict], tz: str, day: date | None = None,
                   impacts: set[str] | None = None) -> list[dict]:
    tzinfo = ZoneInfo(tz)
    day = day or datetime.now(tzinfo).date()
    allowed = impacts if impacts is not None else _allowed_impacts()
    out: list[dict] = []
    for it in items:
        if it.get("country") not in CURRENCIES:
            continue
        if it.get("impact") not in allowed:
            continue
        try:
            dt = datetime.fromisoformat(it["date"]).astimezone(tzinfo)
        except (KeyError, ValueError):
            continue
        if dt.date() != day:
            continue
        out.append({
            "dt": dt,
            "ccy": it["country"],
            "impact": it["impact"],
            "title": it.get("title", ""),
            "forecast": (it.get("forecast") or "").strip(),
            "previous": (it.get("previous") or "").strip(),
        })
    out.sort(key=lambda e: e["dt"])
    return out


def format_news(events: list[dict], tz: str, day: date | None = None) -> str:
    tzinfo = ZoneInfo(tz)
    day = day or datetime.now(tzinfo).date()
    label = f"{day.strftime('%d.%m')} ({WEEKDAYS_RU[day.weekday()]})"
    tzname = tz.split("/")[-1]
    head = f"📰 <b>Новости дня</b> · {label}\n<i>время по {tzname}</i>"

    if not events:
        return head + "\n\nСегодня по USD / EUR / GBP важных новостей нет. 🌤"

    holidays = [e for e in events if e["impact"] == "Holiday"]
    timed = [e for e in events if e["impact"] != "Holiday"]

    lines = [head, ""]
    for e in timed:
        emoji = IMPACT_EMOJI.get(e["impact"], "•")
        flag = CCY_FLAG.get(e["ccy"], "")
        t = e["dt"].strftime("%H:%M")
        lines.append(f"{emoji} <b>{t}</b>  {flag} {e['ccy']} · {html.escape(e['title'])}")
        detail = []
        if e["forecast"]:
            detail.append(f"прогноз {html.escape(e['forecast'])}")
        if e["previous"]:
            detail.append(f"пред. {html.escape(e['previous'])}")
        if detail:
            lines.append(f"     <i>{' · '.join(detail)}</i>")

    if holidays:
        lines.append("")
        for e in holidays:
            flag = CCY_FLAG.get(e["ccy"], "")
            lines.append(f"⚪️ {flag} {e['ccy']} · {html.escape(e['title'])} <i>(bank holiday)</i>")

    return "\n".join(lines)


async def daily_news_text(tz: str, day: date | None = None) -> str:
    items = await fetch_calendar()
    events = events_for_day(items, tz, day)
    return format_news(events, tz, day)
