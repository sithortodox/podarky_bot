"""Админ-панель в Telegram: тексты, подарки, спонсоры, статистика, управление этапами."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from app.bot.texts import DEFAULT_TEXTS, get_text
from app.config import Config
from app.db import db, now

admin = Router(name="admin")


def is_admin(user_id: int) -> bool:
    return user_id in Config.from_env().admin_ids


# ---------- Меню ----------

@admin.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await clear_state(message.from_user.id)
    await message.answer("🛡 <b>Админ-панель</b>", parse_mode=ParseMode.HTML,
                         reply_markup=await menu_kb())


async def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
         InlineKeyboardButton(text="📝 Тексты", callback_data="adm:texts")],
        [InlineKeyboardButton(text="🎁 Подарки", callback_data="adm:gifts"),
         InlineKeyboardButton(text="👥 Спонсоры", callback_data="adm:sponsors")],
        [InlineKeyboardButton(text="🖼 Картинка 6 подарков", callback_data="adm:photo"),
         InlineKeyboardButton(text="💰 Оплата", callback_data="adm:pay")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast"),
         InlineKeyboardButton(text="🔄 Сбросить участника", callback_data="adm:reset")],
    ])


async def stats_text() -> str:
    total = await db.scalar("SELECT COUNT(*) FROM users")
    rolled = await db.scalar("SELECT COUNT(*) FROM users WHERE dice_value IS NOT NULL")
    gifted = await db.scalar("SELECT COUNT(*) FROM users WHERE gift_id IS NOT NULL")
    tasks = await db.scalar("SELECT COUNT(*) FROM users WHERE shots>=10")
    subs = await db.scalar("SELECT COUNT(*) FROM users WHERE stage IN ('offer','paid')")
    paid = await db.scalar("SELECT COUNT(*) FROM users WHERE paid=1")
    cr = f"{paid / total * 100:.1f}%" if total else "0%"
    stages = await db.rows("SELECT stage, COUNT(*) c FROM users GROUP BY stage ORDER BY c DESC")
    by_stage = "\n".join(f"    {r['stage']}: {r['c']}" for r in stages)
    return get_text("admin_stats", total=total, rolled=rolled, gifted=gifted,
                    tasks=tasks, subs=subs, paid=paid, cr=cr) + (
        f"\n\n<b>По этапам:</b>\n{by_stage or '    —'}")


@admin.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await call.message.answer(await stats_text(), parse_mode=ParseMode.HTML,
                              reply_markup=back_kb())


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="adm:menu")]
    ])


@admin.callback_query(F.data == "adm:menu")
async def cb_menu(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.answer()
    await call.message.answer("🛡 <b>Админ-панель</b>", parse_mode=ParseMode.HTML,
                              reply_markup=await menu_kb())


# ---------- Состояния редактирования (in-memory) ----------

state: dict[int, tuple[str, str | None]] = {}


async def get_state(uid: int) -> tuple[str, str | None] | None:
    return state.get(uid)


async def clear_state(uid: int) -> None:
    state.pop(uid, None)


# ---------- Тексты ----------

TEXT_KEYS = list(DEFAULT_TEXTS.keys())


async def texts_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"✏️ {k}", callback_data=f"adm:text:{k}")]
            for k in TEXT_KEYS]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin.callback_query(F.data == "adm:texts")
async def cb_texts(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await call.message.answer("📝 <b>Тексты бота</b>\nНажми, чтобы отредактировать:",
                              parse_mode=ParseMode.HTML, reply_markup=await texts_kb())


@admin.callback_query(F.data.startswith("adm:text:"))
async def cb_text_pick(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    key = call.data.split(":", 2)[2]
    state[call.from_user.id] = ("text", key)
    current = await db.get_setting(f"text_{key}", DEFAULT_TEXTS.get(key, ""))
    await call.answer()
    await call.message.answer(
        f"✏️ <b>{key}</b>\n\nТекущее значение:\n<pre>{html.escape(current)}</pre>\n\n"
        f"Пришли новый текст. HTML-разметка поддерживается. /admin — назад.",
        parse_mode=ParseMode.HTML)


# ---------- Приём отредактированных значений ----------

async def admin_state_filter(event) -> bool:
    if not isinstance(event, Message) or not is_admin(event.from_user.id):
        return False
    return state.get(event.from_user.id) is not None


STATE_FILTER = admin_state_filter


class StateActive(BaseFilter):
    """Пропускает сообщение, только если админ в режиме редактирования."""

    async def __call__(self, message: Message) -> bool:
        if not is_admin(message.from_user.id):
            return False
        return state.get(message.from_user.id) is not None


@admin.message(StateActive(), F.photo)
async def state_photo(message: Message) -> None:
    st = state.get(message.from_user.id)
    if not st:
        return
    kind, key = st
    if kind == "gift_image":
        await db.set_setting("gifts_image", message.photo[-1].file_id)
        await clear_state(message.from_user.id)
        await message.answer("✅ Картинка с 6 подарками обновлена!",
                             reply_markup=await menu_kb())
    else:
        await message.answer("Ожидаю текст. /admin — в меню.")


@admin.message(StateActive(), F.text)
async def state_text(message: Message) -> None:
    st = state.get(message.from_user.id)
    if not st:
        return
    kind, key = st
    if kind == "text":
        await db.set_setting(f"text_{key}", message.text or "")
        await clear_state(message.from_user.id)
        await message.answer(f"✅ Текст «{key}» сохранён.", reply_markup=await texts_kb())
    elif kind == "payment_url":
        url = (message.text or "").strip()
        if not url.startswith("http"):
            await message.answer("URL должен начинаться с http")
            return
        if "{user_id}" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}user_id={{user_id}}"
        await db.set_setting("payment_url", url)
        await clear_state(message.from_user.id)
        await message.answer(f"✅ URL оплаты сохранён:\n{url}", reply_markup=await menu_kb())
    elif kind == "broadcast":
        await clear_state(message.from_user.id)
        users = await db.rows("SELECT user_id FROM users")
        sent = failed = 0
        for u in users:
            try:
                await message.bot.send_message(u["user_id"], message.text)
                sent += 1
            except Exception:
                failed += 1
        await message.answer(f"📢 Рассылка готова: {sent} доставлено, {failed} ошибок.",
                             reply_markup=await menu_kb())
    elif kind == "gift_title":
        await db.execute("UPDATE gifts SET title=? WHERE id=?", (message.text, int(key)))
        await clear_state(message.from_user.id)
        await message.answer(f"✅ Подарок {key} переименован.", reply_markup=await gifts_kb())
    elif kind == "gift_link":
        await db.execute("UPDATE gifts SET link=? WHERE id=?", (message.text, int(key)))
        await clear_state(message.from_user.id)
        await message.answer(f"✅ Ссылка подарка {key} сохранена.", reply_markup=await gifts_kb())
    elif kind == "sponsor_add":
        # формат: chat_id | Название | url
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) < 2:
            await message.answer("Формат: <code>chat_id | Название | ссылка</code>",
                                 parse_mode=ParseMode.HTML)
            return
        chat_id = parts[0].lstrip("@")
        title = parts[1]
        url = parts[2] if len(parts) > 2 else f"https://t.me/{chat_id}"
        await db.execute("INSERT INTO sponsors(chat_id,title,url) VALUES(?,?,?)",
                         (chat_id, title, url))
        await clear_state(message.from_user.id)
        await message.answer(f"✅ Спонсор «{title}» добавлен.", reply_markup=await sponsors_kb())
    elif kind == "reset_user":
        uid = message.text.strip()
        if not uid.isdigit():
            await message.answer("Введи числовой user_id участника.")
            return
        await db.execute("UPDATE users SET stage='start', dice_value=NULL, gift_id=NULL, "
                         "shots=0, paid=0, updated_at=? WHERE user_id=?", (now(), int(uid)))
        await clear_state(message.from_user.id)
        await message.answer(f"✅ Участник {uid} сброшен на начало.", reply_markup=await menu_kb())


# ---------- Подарки ----------

async def gifts_kb() -> InlineKeyboardMarkup:
    gifts = await db.rows("SELECT * FROM gifts ORDER BY id")
    rows = [[InlineKeyboardButton(text=f"{g['id']}️⃣ {g['title']}",
                                  callback_data=f"adm:gift:{g['id']}")] for g in gifts]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def gift_kb(gid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"adm:giftT:{gid}"),
         InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"adm:giftL:{gid}")],
        [InlineKeyboardButton(text="◀️ К подаркам", callback_data="adm:gifts")],
    ])


@admin.callback_query(F.data == "adm:gifts")
async def cb_gifts(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.answer()
    await call.message.answer("🎁 <b>Подарки</b>\nВыбери, что отредактировать:",
                              parse_mode=ParseMode.HTML, reply_markup=await gifts_kb())


@admin.callback_query(F.data.startswith("adm:gift:"))
async def cb_gift(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    gid = int(call.data.split(":")[-1])
    g = await db.one("SELECT * FROM gifts WHERE id=?", (gid,))
    if not g:
        return await call.answer("Подарок не найден", show_alert=True)
    await call.answer()
    await call.message.answer(
        f"🎁 <b>{html.escape(g['title'])}</b>\n\nСсылка: {g['link'] or '—'}",
        parse_mode=ParseMode.HTML, reply_markup=await gift_kb(gid))


@admin.callback_query(F.data.startswith("adm:giftT:"))
async def cb_gift_title(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    gid = call.data.split(":")[-1]
    state[call.from_user.id] = ("gift_title", gid)
    await call.answer("Пришли новое название")
    await call.message.answer(f"✏️ Новое название для подарка {gid}:")


@admin.callback_query(F.data.startswith("adm:giftL:"))
async def cb_gift_link(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    gid = call.data.split(":")[-1]
    state[call.from_user.id] = ("gift_link", gid)
    await call.answer("Пришли новую ссылку")
    await call.message.answer(f"🔗 Новая ссылка для подарка {gid}:")


# ---------- Спонсоры ----------

async def sponsors_kb() -> InlineKeyboardMarkup:
    rows = []
    for s in await db.rows("SELECT * FROM sponsors ORDER BY id"):
        rows.append([InlineKeyboardButton(
            text=f"❌ {s['title']}", callback_data=f"adm:sdel:{s['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить спонсора", callback_data="adm:sadd")])
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin.callback_query(F.data == "adm:sponsors")
async def cb_sponsors(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.answer()
    await call.message.answer(
        "👥 <b>Спонсоры</b>\nНажми на канал, чтобы удалить.",
        parse_mode=ParseMode.HTML, reply_markup=await sponsors_kb())


@admin.callback_query(F.data == "adm:sadd")
async def cb_sadd(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    state[call.from_user.id] = ("sponsor_add", None)
    await call.answer()
    await call.message.answer(
        "➕ Пришли данные нового спонсора в формате:\n"
        "<code>@channel | Название | https://t.me/channel</code>",
        parse_mode=ParseMode.HTML)


@admin.callback_query(F.data.startswith("adm:sdel:"))
async def cb_sdel(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    sid = int(call.data.split(":")[-1])
    await db.execute("DELETE FROM sponsors WHERE id=?", (sid,))
    await call.answer("Удалён")
    await call.message.answer("✅ Спонсор удалён.", reply_markup=await sponsors_kb())


# ---------- Картинка, оплата, рассылка, сброс ----------

@admin.callback_query(F.data == "adm:photo")
async def cb_photo(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    state[call.from_user.id] = ("gift_image", None)
    await call.answer()
    await call.message.answer(
        "🖼 Пришли картинку с 6 подарками — она будет показана при /start.",
        reply_markup=back_kb())


@admin.callback_query(F.data == "adm:pay")
async def cb_pay(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    cfg = Config.from_env()
    url = await db.get_setting("payment_url", cfg.payment_url)
    await call.answer()
    await call.message.answer(
        f"💰 <b>Оплата</b>\n\nСумма: {cfg.payment_amount}\nURL: <code>{html.escape(url)}</code>\n\n"
        f"Пришли новый URL — добавлю <code>{{user_id}}</code>, если его нет.",
        parse_mode=ParseMode.HTML, reply_markup=back_kb())
    state[call.from_user.id] = ("payment_url", None)


@admin.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    state[call.from_user.id] = ("broadcast", None)
    await call.answer()
    await call.message.answer("📢 Приши текст рассылки — он уйдёт всем участникам.")


@admin.callback_query(F.data == "adm:reset")
async def cb_reset(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        return await call.answer()
    state[call.from_user.id] = ("reset_user", None)
    await call.answer()
    await call.message.answer("🔄 Пришли user_id участника для сброса на первый этап.")