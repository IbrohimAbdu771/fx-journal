"""Claude-powered parsing: chart vision + structured extraction via tool use.

Model: claude-sonnet-5 (as specified). We force a single tool call so the model
returns a strict JSON object; extended thinking is disabled because forced
tool_choice is incompatible with it and we don't need it for extraction.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from core import ict

logger = logging.getLogger(__name__)

INTENTS = ["new_trade", "close_trade", "edit_trade", "other"]

SYSTEM_PROMPT = """\
Ты — ассистент трейдингового журнала. Трейдер торгует форекс (EURUSD, GBPUSD) по \
модели ICT: Sweep → MSS → OTE-вход. Ты извлекаешь параметры сделки из текста и/или \
скриншота графика и возвращаешь их СТРОГО одним вызовом инструмента record_trade.

Терминология и контекст (время — Нью-Йорк, NY local):
- Сессии: Asia 20:00–00:00, London 02:00–05:00, NY 07:00–10:00.
- Silver Bullet окна: LO 03:00–04:00, NY AM 10:00–11:00 (sb_window=true если сделка в этих окнах).
- Азия классифицируется как consolidation или expansion (asia_type).
- Sweep — снятие ликвидности (Asia High/Low, PDH/PDL, session high/low).
- MSS — market structure shift (mss_confirmed).
- OTE — optimal trade entry (0.62 / 0.705 / 0.79), либо вход по OB/FVG (ote_level).
- Setup: LO reversal / NY reversal / NY continuation / other.

Определи намерение (intent):
- new_trade — трейдер логирует НОВУЮ сделку (есть пара/направление/вход/стоп или скрин входа).
- close_trade — закрывает сделку («закрыл EURUSD +1.8R», «стоп», «тейк», скрин после).
- edit_trade — правит предыдущую запись («исправь: стоп был 1.0832»).
- other — что-то иное.

Правила:
- Заполняй только то, что реально сказано/видно. Чего нет — оставляй null (для \
  списков — пустой массив). НИЧЕГО не выдумывай.
- Числа — как числа (например 1.0832), без строк.
- Для close_trade извлекай result_r, result_usd, outcome (Win/Loss/Breakeven/Missed/No Trade), pair.
- MAE/MFE (опционально): mae_r — максимальный ход ПРОТИВ позиции, mfe_r — максимальный ход В \
  ПОЛЬЗУ позиции, оба в R и НЕОТРИЦАТЕЛЬНЫЕ (модуль хода). Фразы: «mae 0.4, mfe 2.1», \
  «просело на 0.7R» → mae_r=0.7, «доходило до +2R» → mfe_r=2.0. Если не сказано — null, не 0.
- notes — короткая свободная заметка/дисциплина/эмоции, если трейдер их описал.
- Всегда возвращай ровно один вызов record_trade.
"""


def _enum(values: list[str], nullable: bool = True) -> dict:
    schema: dict[str, Any] = {"type": ["string", "null"] if nullable else "string"}
    schema["enum"] = values + ([None] if nullable else [])
    return schema


def _num() -> dict:
    return {"type": ["number", "null"]}


def _bool() -> dict:
    return {"type": ["boolean", "null"]}


TOOL = {
    "name": "record_trade",
    "description": "Записать распознанные параметры сделки в трейдинг-журнал.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": INTENTS},
            "pair": _enum(ict.PAIRS),
            "direction": _enum(ict.DIRECTIONS),
            "entry": _num(),
            "stop_loss": _num(),
            "take_profit": _num(),
            "lot": _num(),
            "risk_pct": _num(),
            "result_r": _num(),
            "result_usd": _num(),
            "mae_r": _num(),
            "mfe_r": _num(),
            "outcome": _enum(ict.OUTCOMES),
            "session": _enum(ict.SESSIONS),
            "sb_window": _bool(),
            "asia_type": _enum(ict.ASIA_TYPES),
            "setup": _enum(ict.SETUPS),
            "sweep_reference": _enum(ict.SWEEP_REFS),
            "ote_level": _enum(ict.OTE_LEVELS),
            "mss_confirmed": _bool(),
            "news_blackout": _bool(),
            "plan_followed": _enum(ict.PLAN_FOLLOWED),
            "violation_type": {
                "type": "array",
                "items": {"type": "string", "enum": ict.VIOLATION_TYPES},
            },
            "emotion": _enum(ict.EMOTIONS),
            "notes": {"type": ["string", "null"]},
        },
        "required": ["intent"],
    },
}

# canonical field list (everything except intent) used elsewhere
TRADE_FIELDS = [k for k in TOOL["input_schema"]["properties"] if k != "intent"]


def _validate(data: dict) -> dict:
    """Coerce/clean the raw tool input into a normalized trade dict."""
    out: dict[str, Any] = {}
    out["intent"] = data.get("intent") if data.get("intent") in INTENTS else "other"

    enum_map = {
        "pair": ict.PAIRS,
        "direction": ict.DIRECTIONS,
        "outcome": ict.OUTCOMES,
        "session": ict.SESSIONS,
        "asia_type": ict.ASIA_TYPES,
        "setup": ict.SETUPS,
        "sweep_reference": ict.SWEEP_REFS,
        "ote_level": ict.OTE_LEVELS,
        "plan_followed": ict.PLAN_FOLLOWED,
        "emotion": ict.EMOTIONS,
    }
    for key, allowed in enum_map.items():
        val = data.get(key)
        out[key] = val if val in allowed else None

    for key in ("entry", "stop_loss", "take_profit", "lot", "risk_pct",
                "result_r", "result_usd", "mae_r", "mfe_r"):
        val = data.get(key)
        out[key] = float(val) if isinstance(val, (int, float)) else None

    for key in ("sb_window", "mss_confirmed", "news_blackout"):
        val = data.get(key)
        out[key] = bool(val) if isinstance(val, bool) else None

    vt = data.get("violation_type") or []
    out["violation_type"] = [v for v in vt if v in ict.VIOLATION_TYPES] if isinstance(vt, list) else []

    notes = data.get("notes")
    out["notes"] = notes.strip() if isinstance(notes, str) and notes.strip() else None
    return out


class TradeParser:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract(
        self,
        text: str | None = None,
        image_bytes: bytes | None = None,
        image_media_type: str = "image/jpeg",
    ) -> dict:
        """Return a normalized trade dict (with `intent`) from text and/or a chart image."""
        content: list[dict] = []
        if image_bytes:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                    },
                }
            )
        user_text = text.strip() if text else ""
        if not user_text and image_bytes:
            user_text = "Скриншот графика без подписи — распознай контекст входа."
        content.append({"type": "text", "text": user_text or "Пустое сообщение."})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            thinking={"type": "disabled"},
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "record_trade"},
            messages=[{"role": "user", "content": content}],
        )

        tool_input = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "record_trade":
                tool_input = block.input
                break
        if tool_input is None:  # pragma: no cover - forced tool_choice guarantees this
            logger.warning("No tool_use block in Claude response: %s", response.stop_reason)
            return {"intent": "other", **{f: None for f in TRADE_FIELDS}, "violation_type": []}

        parsed = _validate(dict(tool_input))
        logger.info("Extracted intent=%s pair=%s", parsed.get("intent"), parsed.get("pair"))
        return parsed

    async def summarize(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Free-form Claude call (used for the weekly report)."""
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()
