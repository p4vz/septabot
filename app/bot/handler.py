"""Telegram update handling.

Slash commands are answered with deterministic, templated text and do not
call Hermes. Free-form messages route through Hermes with a minimal,
intent-filtered data context.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.bot import context as ctx_builder
from app.bot import entities, intent
from app.clients import hermes, telegram
from app.config import settings

log = logging.getLogger(__name__)


HELP_TEXT = (
    "*septabot* — Philly commuter helper\n"
    "\n"
    "Ask me anything about your commute. Examples:\n"
    "• _is there rain this afternoon?_\n"
    "• _any delays on Paoli/Thorndale?_\n"
    "• _how is I-95 looking?_\n"
    "\n"
    "Commands:\n"
    "/status — weather + SEPTA + traffic snapshot\n"
    "/alerts — SEPTA service alerts\n"
    "/trains — delayed Regional Rail trains\n"
    "/weather — short forecast\n"
    "/traffic — traffic events near Center City"
)


SYSTEM_PROMPT = (
    "You are septabot, a concise assistant for Philadelphia commuters.\n"
    "\n"
    "Rules:\n"
    "- Answer ONLY from the JSON snapshot. If the snapshot lacks the answer, "
    "say so in one sentence and don't invent.\n"
    "- When the snapshot has BOTH `drive` and `transit`, give a clear "
    "recommendation (which is faster door-to-door, what the tradeoff is). "
    "Don't just list numbers. Mention disruptions if they'd change the call.\n"
    "- When the snapshot has `disruption`, lead with the line's stuck count "
    "and max delay, then the alert text if present.\n"
    "- Format: 1-4 short lines, plain Telegram text. No Markdown headers, "
    "no bullets. Times in minutes (e.g. '42 min'), distances in miles."
)


async def handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or update.get("channel_post")
    if not msg:
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    try:
        reply = await _route(text)
    except Exception:
        log.exception("septabot handler failed")
        reply = "Sorry, something broke while looking that up. Try again in a moment."

    await telegram.send_message(chat_id, reply)


async def _route(text: str) -> str:
    head = text.split()[0].lower() if text else ""

    if head in {"/start", "/help"}:
        return HELP_TEXT

    if head == "/status":
        ctx = await ctx_builder.build({"weather", "alerts", "trains", "traffic"})
        return _format_status(ctx)

    if head == "/alerts":
        ctx = await ctx_builder.build({"alerts"})
        return _format_alerts(ctx.get("alerts", []))

    if head == "/trains":
        ctx = await ctx_builder.build({"trains"})
        return _format_trains(ctx.get("trains", []))

    if head == "/weather":
        ctx = await ctx_builder.build({"weather"})
        return _format_weather(ctx.get("weather"))

    if head == "/traffic":
        ctx = await ctx_builder.build({"traffic"})
        return _format_traffic(ctx.get("traffic", []))

    # Free-form -> Hermes with intent-filtered context.
    tags = intent.classify(text)
    route = entities.extract_route(text, default_origin=settings.default_origin)
    line = entities.extract_line(text)
    if route and "route" not in tags:
        # "from X to Y" implies route intent even if no keyword tripped.
        tags.add("route")
        tags.add("traffic")
    ctx = await ctx_builder.build(
        tags,
        route_origin=route[0] if route else None,
        route_destination=route[1] if route else None,
        line=line,
    )
    user_prompt = (
        f"User question: {text}\n\n"
        f"Current snapshot (only use this; do not invent data):\n"
        f"{json.dumps(ctx, separators=(',', ':'))}"
    )
    try:
        return await hermes.chat(SYSTEM_PROMPT, user_prompt)
    except hermes.HermesError:
        log.exception("Hermes call failed; falling back to deterministic status")
        return _format_status(ctx)


def _format_status(ctx: dict[str, Any]) -> str:
    parts: list[str] = []
    w = ctx.get("weather")
    if w and w.get("now"):
        n = w["now"]
        pop = f" • {n['pop']}% precip" if n.get("pop") else ""
        parts.append(f"\U0001f324 {n['when']}: {n['temp']}, {n['summary']}{pop}")
    alerts = ctx.get("alerts") or []
    if alerts:
        parts.append(f"\U0001f6a8 SEPTA alerts ({len(alerts)}):")
        for a in alerts[:3]:
            parts.append(f"  • {a['route']} ({a['mode']}): {a['msg']}")
    else:
        parts.append("✅ No SEPTA alerts")
    trains = ctx.get("trains") or []
    if trains:
        parts.append(f"\U0001f686 Delayed trains:")
        for t in trains[:3]:
            parts.append(f"  • #{t['no']} {t['line']} -> {t['dest']}, {t['late_min']}m late")
    traffic = ctx.get("traffic") or []
    if traffic:
        parts.append(f"\U0001f697 Traffic ({len(traffic)}):")
        for e in traffic[:3]:
            parts.append(f"  • {e['road']} {e['dir']}: {e['headline']}")
    return "\n".join(parts) if parts else "Nothing notable right now."


def _format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "No active SEPTA alerts."
    lines = [f"SEPTA alerts ({len(alerts)}):"]
    for a in alerts:
        lines.append(f"• {a['route']} ({a['mode']}): {a['msg']}")
    return "\n".join(lines)


def _format_trains(trains: list[dict]) -> str:
    if not trains:
        return "No trains 5+ minutes late right now."
    lines = ["Delayed Regional Rail:"]
    for t in trains:
        lines.append(f"• #{t['no']} {t['line']} → {t['dest']} ({t['late_min']}m late, next: {t['next']})")
    return "\n".join(lines)


def _format_weather(w: dict | None) -> str:
    if not w or not w.get("now"):
        return "Weather not available."
    n = w["now"]
    head = f"{n['when']}: {n['temp']}, {n['summary']}"
    if n.get("pop"):
        head += f" ({n['pop']}% precip)"
    lines = [head]
    for p in w.get("next", []):
        extra = f" ({p['pop']}% precip)" if p.get("pop") else ""
        lines.append(f"{p['when']}: {p['temp']}, {p['summary']}{extra}")
    return "\n".join(lines)


def _format_traffic(events: list[dict]) -> str:
    if not events:
        return "No traffic events nearby (or 511PA key not configured)."
    lines = [f"Traffic events ({len(events)}):"]
    for e in events:
        lines.append(f"• {e['road']} {e['dir']} — {e['type']}: {e['headline']}")
    return "\n".join(lines)
