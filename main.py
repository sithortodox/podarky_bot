"""Точка входа бота: python main.py"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from app.bot.admin import admin
from app.bot.handlers import router as user_router
from app.config import Config
from app.db import db
from app.webhook import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("main")


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    log.info("Бот запущен: @%s (%s)", me.username, me.first_name)


async def main() -> None:
    cfg = Config.from_env()

    await db.connect()
    log.info("БД подключена: %s", cfg.db_path)

    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(admin)      # админка — раньше пользовательского роутера
    dp.include_router(user_router)

    # веб-сервер для подтверждения оплаты с сайта
    app = build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.webhook_host, cfg.webhook_port)
    await site.start()
    log.info(
        "Вебхук оплаты: http://%s:%s/paid?user_id=<id>&token=%s",
        cfg.webhook_host, cfg.webhook_port, (cfg.payment_webhook_token or "<НЕ ЗАДАН>")[:8] + "...",
    )

    await on_startup(bot)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено")