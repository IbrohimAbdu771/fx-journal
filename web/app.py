"""FastAPI web dashboard (TradeZella-style) + REST for manual trade entry.

Also owns the process lifecycle: it initializes the DB and (optionally) starts
the Telegram bot as a background task, so a single Railway web service runs both.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core import db, ict, repository, service, stats
from core.config import load_config, setup_logging

setup_logging()
logger = logging.getLogger(__name__)
cfg = load_config()

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals["ict"] = ict


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_engine(cfg.database_url, ssl=cfg.db_ssl)
    await db.create_tables()

    bot_task: asyncio.Task | None = None
    if cfg.bot_enabled and os.getenv("RUN_BOT", "1") != "0":
        from bot.main import run_bot

        bot_task = asyncio.create_task(run_bot(cfg))
        logger.info("Telegram bot task launched")
    else:
        logger.info("Telegram bot disabled (missing config or RUN_BOT=0)")

    try:
        yield
    finally:
        if bot_task:
            bot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bot_task
        await db.dispose_engine()


app = FastAPI(title="FX Journal", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=(cfg.web_password or "fx-journal-dev-secret"))
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


# --------------------------------------------------------------------------- #
# auth gate
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if cfg.web_password:
        path = request.url.path
        allowed = path.startswith("/static") or path in {"/login", "/health"}
        if not allowed and not request.session.get("auth"):
            return RedirectResponse("/login", status_code=302)
    return await call_next(request)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, password: str = Form("")):
    if password == cfg.web_password:
        request.session["auth"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Неверный пароль"}, status_code=401
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# --------------------------------------------------------------------------- #
# form helpers
# --------------------------------------------------------------------------- #
def _f(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _s(value: str | None) -> str | None:
    v = (value or "").strip()
    return v or None


def _dt(value: str | None) -> datetime:
    tz = ZoneInfo(cfg.timezone)
    if value:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=tz)
        except ValueError:
            pass
    return datetime.now(tz)


async def _form_to_data(form) -> dict:
    return {
        "pair": _s(form.get("pair")),
        "direction": _s(form.get("direction")),
        "entry": _f(form.get("entry")),
        "stop_loss": _f(form.get("stop_loss")),
        "take_profit": _f(form.get("take_profit")),
        "lot": _f(form.get("lot")),
        "risk_pct": _f(form.get("risk_pct")),
        "result_r": _f(form.get("result_r")),
        "result_usd": _f(form.get("result_usd")),
        "outcome": _s(form.get("outcome")),
        "status": _s(form.get("status")),
        "session": _s(form.get("session")),
        "sb_window": form.get("sb_window") == "on",
        "asia_type": _s(form.get("asia_type")),
        "setup": _s(form.get("setup")),
        "sweep_reference": _s(form.get("sweep_reference")),
        "ote_level": _s(form.get("ote_level")),
        "mss_confirmed": form.get("mss_confirmed") == "on",
        "news_blackout": form.get("news_blackout") == "on",
        "plan_followed": _s(form.get("plan_followed")),
        "violation_type": form.getlist("violation_type"),
        "emotion": _s(form.get("emotion")),
        "notes": _s(form.get("notes")),
    }


async def _read_upload(upload: UploadFile | None) -> tuple[bytes | None, str | None]:
    if upload and upload.filename:
        data = await upload.read()
        if data:
            return data, upload.content_type or "image/jpeg"
    return None, None


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #
def _since(period: str) -> datetime | None:
    now = ict.now_ny(cfg.timezone)
    return {"week": now - timedelta(days=7), "month": now - timedelta(days=30),
            "year": now - timedelta(days=365)}.get(period)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, period: str = "all", y: int | None = None, m: int | None = None):
    from . import charts

    since = _since(period)
    s = stats.compute_stats(await repository.stats_dicts(since))
    recent = await repository.list_trades(limit=12)
    open_trades = await repository.get_open_trades()
    calendar = await _build_calendar(y, m)
    balance = round(cfg.initial_balance + s.net_pnl, 2)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "s": s,
            "recent": recent,
            "open_trades": open_trades,
            "equity_svg": charts.equity_curve_svg(s.equity_curve),
            "dist_bars": charts.distribution_bars(s.r_distribution),
            "calendar": calendar,
            "balance": balance,
            "period": period,
        },
    )


async def _build_calendar(y: int | None, m: int | None):
    """Calendar is computed over ALL trades so month navigation always has data."""
    from . import charts

    daily = stats.compute_stats(await repository.stats_dicts()).daily
    return charts.build_calendar(daily, cfg.timezone, y, m)


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_fragment(request: Request, y: int | None = None, m: int | None = None,
                            period: str = "all"):
    calendar = await _build_calendar(y, m)
    return templates.TemplateResponse(
        "_calendar.html", {"request": request, "calendar": calendar, "period": period}
    )


@app.get("/trades", response_class=HTMLResponse)
async def trades_log(request: Request):
    trades = await repository.list_trades(limit=500)
    return templates.TemplateResponse(
        "trades.html", {"request": request, "trades": trades}
    )


@app.get("/new", response_class=HTMLResponse)
async def new_form(request: Request):
    default_time = ict.now_ny(cfg.timezone).strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(
        "trade_form.html",
        {"request": request, "trade": None, "default_time": default_time, "action": "/trades"},
    )


@app.post("/trades")
async def create_trade(request: Request):
    form = await request.form()
    data = await _form_to_data(form)
    data["raw_message"] = "manual/web"
    trade_time = _dt(form.get("trade_time"))
    enriched = service.enrich(data, trade_time, cfg.timezone)
    enriched["trade_time"] = trade_time
    chart, mime = await _read_upload(form.get("chart_before"))
    trade = await repository.add_trade(enriched, chart_before=chart, chart_before_mime=mime)
    return RedirectResponse(f"/trade/{trade['id']}", status_code=302)


@app.get("/trade/{trade_id}", response_class=HTMLResponse)
async def trade_detail(request: Request, trade_id: int):
    trade = await repository.get_trade(trade_id)
    if not trade:
        return RedirectResponse("/", status_code=302)
    tt = trade.get("trade_time")
    default_time = tt.astimezone(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%dT%H:%M") if tt else ""
    return templates.TemplateResponse(
        "trade_detail.html",
        {"request": request, "trade": trade, "default_time": default_time},
    )


@app.post("/trade/{trade_id}")
async def edit_trade(request: Request, trade_id: int):
    form = await request.form()
    base = await repository.get_trade(trade_id)
    if not base:
        return RedirectResponse("/", status_code=302)
    data = await _form_to_data(form)
    trade_time = _dt(form.get("trade_time"))
    merged = {**base, **data}
    enriched = service.enrich(merged, trade_time, cfg.timezone)
    enriched["trade_time"] = trade_time
    if form.get("action") == "close":
        enriched["status"] = "Closed"
        if not enriched.get("outcome") and enriched.get("result_r") is not None:
            r = enriched["result_r"]
            enriched["outcome"] = "Win" if r > 0 else "Loss" if r < 0 else "Breakeven"
    await repository.update_trade(trade_id, enriched)

    before, before_mime = await _read_upload(form.get("chart_before"))
    if before:
        await repository.set_chart(trade_id, "before", before, before_mime)
    after, after_mime = await _read_upload(form.get("chart_after"))
    if after:
        await repository.set_chart(trade_id, "after", after, after_mime)
    return RedirectResponse(f"/trade/{trade_id}", status_code=302)


@app.post("/trade/{trade_id}/close")
async def close_trade_route(request: Request, trade_id: int):
    form = await request.form()
    after, after_mime = await _read_upload(form.get("chart_after"))
    await repository.close_trade(
        trade_id,
        result_r=_f(form.get("result_r")),
        result_usd=_f(form.get("result_usd")),
        outcome=_s(form.get("outcome")),
        chart_after=after,
        chart_after_mime=after_mime,
    )
    return RedirectResponse(f"/trade/{trade_id}", status_code=302)


@app.post("/trade/{trade_id}/delete")
async def delete_trade_route(trade_id: int):
    await repository.delete_trade(trade_id)
    return RedirectResponse("/trades", status_code=302)


@app.get("/chart/{trade_id}/{which}")
async def chart(trade_id: int, which: str):
    result = await repository.get_chart(trade_id, which)
    if not result:
        return Response(status_code=404)
    data, mime = result
    return Response(content=data, media_type=mime)


@app.get("/api/stats")
async def api_stats(period: str = "all"):
    s = stats.compute_stats(await repository.stats_dicts(_since(period)))
    return s.as_dict()
