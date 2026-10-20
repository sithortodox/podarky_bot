"""Смоук-тест без реального Telegram: БД, тексты, клавиатуры, админка."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("PAYMENT_URL", "https://x.test/pay")
os.environ.setdefault("PAYMENT_WEBHOOK_TOKEN", "t")
os.environ.setdefault("DB_PATH", ":memory:")


async def main() -> None:
    from app.bot import keyboards as kb, texts
    from app.db import db

    try:
        await run(db, kb, texts)
    finally:
        await db.close()
    print("SMOKE_OK")


async def run(db, kb, texts) -> None:
    from app.bot.admin import gifts_kb, menu_kb, sponsors_kb, stats_text, texts_kb
    from app.config import Config

    cfg = Config.from_env()
    print("config ok:", cfg.payment_amount, cfg.admin_ids)

    await db.connect()
    await db.touch_user(1, "vasya", "Вася", "start")
    await db.execute(
        "UPDATE users SET dice_value=4, gift_id=4, stage='task', shots=10 WHERE user_id=1"
    )
    await db.execute(
        "INSERT INTO sponsors(chat_id,title,url) VALUES('mychannel','Канал 1','https://t.me/x')"
    )
    await db.execute(
        "INSERT INTO sponsors(chat_id,title,url) VALUES('ch2','Канал 2','https://t.me/y')"
    )

    u = await db.one("SELECT * FROM users WHERE user_id=1")
    assert u["username"] == "vasya" and u["shots"] == 10, dict(u)
    await db.touch_user(1, None, "", None, log=False)
    u = await db.one("SELECT * FROM users WHERE user_id=1")
    assert u["username"] == "vasya", "username был затёрт!"

    await db.set_setting("text_dice_hint", "Погнали!")
    assert texts.get_text("dice_hint") == "Погнали!"
    assert "Подарок" in texts.get_text("gift_caption", n=3, gift="Робот")
    assert "10 видео" in texts.get_text("task_intro")
    assert texts.get_text("unknown_key") == "unknown_key"

    for stage in ("start", "rolled", "gift", "task", "sponsors", "offer", "paid"):
        assert (await kb.main_kb(stage)).keyboard, stage  # reply-клавиатура
    assert len(kb.gift_kb("https://t.me/x").inline_keyboard) == 2
    sk = await kb.sponsors_kb()
    assert len(sk.inline_keyboard) == 3, "2 спонсора + кнопка проверки"
    assert kb.payment_kb("https://x.test/pay").inline_keyboard[0][0].url.startswith("http")

    stats = await stats_text()
    assert "Всего участников: 1" in stats, stats
    print(stats.splitlines()[0])
    print("menus:", len((await menu_kb()).inline_keyboard), len((await texts_kb()).inline_keyboard),
          len((await gifts_kb()).inline_keyboard), len((await sponsors_kb()).inline_keyboard))


if __name__ == "__main__":
    asyncio.run(main())