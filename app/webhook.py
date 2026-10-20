"""Лёгкий aiohttp-сервер: сайт оплаты дёргает GET /paid, чтобы подтвердить участие.

Вызов со стороны платёжного сайта:
    GET /paid?user_id=123456&token=PAYMENT_WEBHOOK_TOKEN

Ответ JSON: {"ok": true}
"""
from __future__ import annotations

import logging

from aiohttp import web

from app.bot.texts import get_text
from app.config import Config
from app.db import db, now

log = logging.getLogger("webhook")


async def handle_paid(request: web.Request) -> web.Response:
    cfg = Config.from_env()
    token = request.query.get("token", "")
    if not cfg.payment_webhook_token or token != cfg.payment_webhook_token:
        return web.json_response({"ok": False, "error": "bad token"}, status=403)

    raw_uid = request.query.get("user_id", "")
    if not raw_uid.isdigit():
        return web.json_response({"ok": False, "error": "bad user_id"}, status=400)
    user_id = int(raw_uid)

    user = await db.one("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not user:
        return web.json_response({"ok": False, "error": "unknown user"}, status=404)

    already = bool(user["paid"])
    if not already:
        await db.execute(
            "UPDATE users SET paid=1, stage='paid', updated_at=? WHERE user_id=?",
            (now(), user_id),
        )
        await db.execute("INSERT INTO events(user_id,stage,created_at) VALUES(?,?,?)",
                         (user_id, "paid", now()))

    # уведомляем участника и администраторов только при первой оплате
    if not already:
        try:
            await request.app["bot"].send_message(user_id, get_text("payment_success"))
        except Exception as exc:  # пользователь мог заблокировать бота
            log.warning("notify %s failed: %s", user_id, exc)

        for admin_id in cfg.admin_ids:
            try:
                await request.app["bot"].send_message(
                    admin_id,
                    f"💰 Оплата подтверждена: user_id={user_id} "
                    f"(@{user['username'] or '—'}), этап=offer→paid",
                )
            except Exception:
                pass

    return web.json_response({"ok": True, "already": already})


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/paid", handle_paid)
    app.router.add_get("/health", lambda r: web.json_response({"ok": True}))
    return app