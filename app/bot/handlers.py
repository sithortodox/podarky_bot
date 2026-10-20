"""Пользовательские хендлеры: запуск, кубик, подарок, задание, спонсоры, оплата."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.types import (CallbackQuery, Message, URLInputFile)

from app.bot import keyboards as kb
from app.bot.texts import get_text
from app.config import Config
from app.db import db, now

router = Router(name="user")


async def gift_image_file_id() -> str:
    return await db.get_setting("gifts_image", "")


async def send_stage(bot, user_id: int, stage: str) -> None:
    """Отправить сообщение текущего этапа (используется и из админки)."""
    user = await db.one("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not user:
        return
    await db.touch_user(user_id, user["username"], user["full_name"], stage)
    if stage == "task":
        await bot.send_message(user_id, get_text("task_intro"), reply_markup=await kb.main_kb(stage))
    elif stage == "sponsors":
        await bot.send_message(
            user_id,
            get_text("sponsors_intro", list=await _sponsors_list()),
            reply_markup=await kb.sponsors_kb(),
        )
    elif stage == "offer":
        cfg = Config.from_env()
        await bot.send_message(
            user_id,
            get_text("payment_offer", amount=cfg.payment_amount),
            reply_markup=kb.payment_kb(await payment_url(user_id)),
        )


async def _sponsors_list() -> str:
    rows = await db.rows("SELECT title FROM sponsors ORDER BY id")
    if not rows:
        return "— (список спонсоров пуст)"
    return "\n".join(f"{i}. {html.escape(r['title'])}" for i, r in enumerate(rows, 1))


async def payment_url(user_id: int) -> str:
    cfg = Config.from_env()
    url = await db.get_setting("payment_url", "") or cfg.payment_url
    if "{user_id}" in url:
        url = url.replace("{user_id}", str(user_id))
    elif "tg_user" not in url and str(user_id) not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}tg_user={user_id}"
    return url


@router.message(F.text == "/start")
@router.message(F.text == "Старт")
async def cmd_start(message: Message) -> None:
    u = message.from_user
    await db.touch_user(u.id, u.username, u.full_name)  # этап не сбрасываем
    row = await db.one("SELECT stage FROM users WHERE user_id=?", (u.id,))
    stage = row["stage"] if row else "start"
    await message.answer(get_text("start_caption"), parse_mode=ParseMode.HTML)
    fid = await gift_image_file_id()
    gifts = await db.rows("SELECT id,title FROM gifts ORDER BY id")
    card = "\n".join(f"  {g['id']}️⃣ — {html.escape(g['title'])}" for g in gifts)
    if fid:
        await message.answer_photo(fid, caption=get_text("welcome_image_caption") + "\n\n" + card,
                                   reply_markup=kb.start_kb())
    else:
        await message.answer("🎁 <b>6 подарков на витрине:</b>\n" + card,
                             parse_mode=ParseMode.HTML, reply_markup=kb.start_kb())
    await message.answer(get_text("dice_hint"), reply_markup=await kb.main_kb(stage))


async def _roll_and_reply(bot, user_id: int, value: int | None = None) -> None:
    """Выдаём подарок по числу кубика; если число не передано — бросаем сами."""
    user = await db.one("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not user:
        return
    # подарок уже выдан — повторно не перебрасываем
    if user["dice_value"]:
        value = user["dice_value"]
    elif value is None:
        from random import randint
        value = randint(1, 6)
    gift = await db.one("SELECT * FROM gifts WHERE id=?", (value,))
    first_roll = not user["dice_value"]
    # этап двигаем вперёд, только если пользователь ещё не прошёл дальше
    new_stage = "gift" if user["stage"] in ("start", "rolled") else user["stage"]
    await db.execute(
        "UPDATE users SET dice_value=?, gift_id=?, stage=?, updated_at=? WHERE user_id=?",
        (value, value, new_stage, now(), user_id),
    )
    if first_roll:
        await db.execute("INSERT INTO events(user_id,stage,created_at) VALUES(?,?,?)",
                         (user_id, "gift", now()))
    caption = get_text("gift_caption", n=value, gift=gift["title"] if gift else "—")
    image = gift["image"] if gift else ""
    fid = await gift_image_file_id()
    try:
        if image:
            await bot.send_photo(user_id, URLInputFile(image), caption=caption,
                                 parse_mode=ParseMode.HTML, reply_markup=kb.gift_kb(gift["link"]))
        elif fid:
            await bot.send_photo(user_id, fid, caption=caption, parse_mode=ParseMode.HTML,
                                 reply_markup=kb.gift_kb(gift["link"] if gift else ""))
        else:
            await bot.send_message(user_id, caption, parse_mode=ParseMode.HTML,
                                   reply_markup=kb.gift_kb(gift["link"] if gift else ""))
    except Exception:
        await bot.send_message(user_id, caption, parse_mode=ParseMode.HTML,
                               reply_markup=kb.gift_kb(gift["link"] if gift else ""))


@router.callback_query(F.data == "game:roll")
async def cb_roll(call: CallbackQuery) -> None:
    user = await db.one("SELECT dice_value FROM users WHERE user_id=?", (call.from_user.id,))
    value = None
    if user and user["dice_value"]:
        await call.answer("Твой кубик уже брошен — вот твой подарок 🎁")
    else:
        try:
            dice_msg = await call.message.answer_dice(emoji="🎲")
            value = dice_msg.dice.value if dice_msg and dice_msg.dice else None
        except Exception:
            pass
        await call.answer("Кубик брошен!")
    await _roll_and_reply(call.bot, call.from_user.id, value)


@router.message(F.text == "🎲 Бросить кубик")
async def msg_roll(message: Message) -> None:
    user = await db.one("SELECT dice_value FROM users WHERE user_id=?", (message.from_user.id,))
    value = None
    if user and user["dice_value"]:
        await message.answer("Твой кубик уже брошен — вот твой подарок 🎁")
    else:
        try:
            dice_msg = await message.answer_dice(emoji="🎲")
            value = dice_msg.dice.value if dice_msg and dice_msg.dice else None
        except Exception:
            pass
    await _roll_and_reply(message.bot, message.from_user.id, value)


@router.message(F.text.in_({"🎁 Мой подарок", "Мой подарок"}))
async def msg_gift(message: Message) -> None:
    await _roll_and_reply(message.bot, message.from_user.id)


@router.callback_query(F.data == "task:intro")
async def cb_task_intro(call: CallbackQuery) -> None:
    await db.touch_user(call.from_user.id, call.from_user.username, call.from_user.full_name, "task")
    await call.message.answer(get_text("task_intro"), parse_mode=ParseMode.HTML,
                              reply_markup=kb.task_kb())
    await call.answer()


@router.callback_query(F.data == "task:send")
async def cb_task_send(call: CallbackQuery) -> None:
    await call.answer("Пришли скриншот выполненного задания 📸")


@router.message(F.text == "📸 Отправить скриншот")
async def msg_task_send(message: Message) -> None:
    await message.answer("Пришли скриншот выполненного задания 📸")


@router.message(F.photo)
async def on_photo(message: Message) -> None:
    user = await db.one("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
    if not user or user["stage"] != "task":
        return
    shots = user["shots"] + 1
    await db.execute("UPDATE users SET shots=?, updated_at=? WHERE user_id=?",
                     (shots, now(), message.from_user.id))
    if shots >= 10:
        await db.execute("UPDATE users SET stage='sponsors', updated_at=? WHERE user_id=?",
                         (now(), message.from_user.id))
        await db.execute("INSERT INTO events(user_id,stage,created_at) VALUES(?,?,?)",
                         (message.from_user.id, "sponsors", now()))
        await message.answer(get_text("task_done"), parse_mode=ParseMode.HTML)
        await send_stage(message.bot, message.from_user.id, "sponsors")
    else:
        await message.answer(get_text("task_progress", done=shots), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "task:done")
async def cb_task_done(call: CallbackQuery) -> None:
    user = await db.one("SELECT shots FROM users WHERE user_id=?", (call.from_user.id,))
    if user and user["shots"] >= 10:
        await send_stage(call.bot, call.from_user.id, "sponsors")
        await call.answer()
    else:
        await call.answer("Сначала пришли все 10 скриншотов!", show_alert=True)


async def _check_sponsors(bot, user_id: int) -> tuple[bool, str]:
    """Проверяем членство во всех спонсорских каналах."""
    missing: list[str] = []
    sponsors = await db.rows("SELECT * FROM sponsors ORDER BY id")
    if not sponsors:
        return True, ""
    for s in sponsors:
        chat_id = s["chat_id"]
        member = None
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            member = None  # пользователь не в чате или бот не админ канала
        status = getattr(member, "status", None) if member else None
        is_member = status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
        if not is_member:
            missing.append(s["title"])
    return (not missing), "\n".join(f"  • {m}" for m in missing)


@router.message(F.text == "💳 Оплатить подписку")
async def msg_pay(message: Message) -> None:
    cfg = Config.from_env()
    await message.answer(get_text("payment_offer", amount=cfg.payment_amount),
                         parse_mode=ParseMode.HTML,
                         reply_markup=kb.payment_kb(await payment_url(message.from_user.id)))


@router.callback_query(F.data == "pay:status")
async def cb_pay_status(call: CallbackQuery) -> None:
    user = await db.one("SELECT paid FROM users WHERE user_id=?", (call.from_user.id,))
    if user and user["paid"]:
        await call.answer("Оплата уже подтверждена ✅")
        return
    await call.answer()
    await call.message.answer(get_text("payment_pending"), parse_mode=ParseMode.HTML)


# ---------- Информационные разделы ----------

@router.message(F.text.in_({"📜 Условия", "Условия"}))
async def msg_terms(message: Message) -> None:
    await message.answer(f"{get_text('terms_title')}\n\n{get_text('terms_text')}",
                         parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "info:terms")
async def cb_terms(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.answer(f"{get_text('terms_title')}\n\n{get_text('terms_text')}",
                              parse_mode=ParseMode.HTML)


@router.message(F.text.in_({"⭐️ Отзывы", "Отзывы", "Посмотреть отзывы"}))
async def msg_reviews(message: Message) -> None:
    await message.answer(get_text("reviews_text"), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "info:reviews")
async def cb_reviews(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.answer(get_text("reviews_text"), parse_mode=ParseMode.HTML)


@router.message(F.text.in_({"ℹ️ Помощь", "Помощь", "/help"}))
async def msg_help(message: Message) -> None:
    await message.answer(get_text("help_text"), parse_mode=ParseMode.HTML)


@router.message(F.text == "🍀 Мой статус")
async def msg_status(message: Message) -> None:
    u = await db.one("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
    if not u:
        await message.answer("Нажми /start, чтобы начать.")
        return
    stage_names = {
        "start": "🚀 Запуск",
        "rolled": "🎲 Кубик брошен",
        "gift": "🎁 Подарок получен",
        "task": "📸 Задание",
        "sponsors": "👥 Подписки на спонсоров",
        "offer": "💳 Оплата",
        "paid": "✅ Участие подтверждено",
    }
    paid = "✅ да" if u["paid"] else "нет"
    gift = "—"
    if u["gift_id"]:
        g = await db.one("SELECT title FROM gifts WHERE id=?", (u["gift_id"],))
        gift = g["title"] if g else "—"
    await message.answer(
        f"<b>Твой статус</b>\n\nЭтап: {stage_names.get(u['stage'], u['stage'])}\n"
        f"Выпало число: {u['dice_value'] or '—'}\nПодарок: {gift}\n"
        f"Скриншотов: {u['shots']}/10\nОплата: {paid}",
        parse_mode=ParseMode.HTML,
    )


async def check_sponsors_flow(bot, user_id: int, reply) -> None:
    ok, missing = await _check_sponsors(bot, user_id)
    if ok:
        await reply(get_text("sponsors_ok"), parse_mode=ParseMode.HTML)
        await send_stage(bot, user_id, "offer")
    else:
        await reply(get_text("sponsors_not_all", list=missing), parse_mode=ParseMode.HTML,
                    reply_markup=await kb.sponsors_kb())


@router.callback_query(F.data == "sponsors:check")
async def cb_sponsors_check(call: CallbackQuery) -> None:
    await call.answer()
    await check_sponsors_flow(call.bot, call.from_user.id, call.message.answer)


@router.message(F.text == "✅ Проверить подписку")
async def msg_sponsors_check(message: Message) -> None:
    await check_sponsors_flow(message.bot, message.from_user.id, message.answer)