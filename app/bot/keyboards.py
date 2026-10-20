"""Кнопки бота. Все callback_data вида <шаг>:<действие>[:<аргумент>]."""
from __future__ import annotations

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                            ReplyKeyboardMarkup, KeyboardButton)

from app.bot.texts import get_text
from app.db import db

STAGES = ("start", "rolled", "gift", "task", "sponsors", "offer", "paid")


async def main_kb(stage: str) -> ReplyKeyboardMarkup:
    """Главная клавиатура — в зависимости от этапа прохождения."""
    rows: list[list[KeyboardButton]] = []
    if stage in ("start",):
        rows.append([KeyboardButton(text="🎲 Бросить кубик")])
    if stage in ("rolled", "gift"):
        rows.append([KeyboardButton(text="🎁 Мой подарок")])
    if stage in ("task",):
        rows.append([KeyboardButton(text="📸 Отправить скриншот")])
    if stage in ("sponsors",):
        rows.append([KeyboardButton(text="✅ Проверить подписку")])
    if stage in ("offer",):
        rows.append([KeyboardButton(text="💳 Оплатить подписку")])
    if stage == "paid":
        rows.append([KeyboardButton(text="🍀 Мой статус")])
    rows.append([
        KeyboardButton(text="📜 Условия"),
        KeyboardButton(text="⭐️ Отзывы"),
        KeyboardButton(text="ℹ️ Помощь"),
    ])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Бросить кубик", callback_data="game:roll")],
        [InlineKeyboardButton(text="⭐️ Посмотреть отзывы", callback_data="info:reviews")],
        [InlineKeyboardButton(text="📜 Условия розыгрыша", callback_data="info:terms")],
    ])


def gift_kb(gift_link: str) -> InlineKeyboardMarkup:
    rows = []
    if gift_link:
        rows.append([InlineKeyboardButton(text=get_text("gift_link_button"), url=gift_link)])
    rows.append([InlineKeyboardButton(text="➡️ Дальше — задание", callback_data="task:intro")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Отправить скриншот", callback_data="task:send")],
        [InlineKeyboardButton(text="➡️ Я всё сделал(а)", callback_data="task:done")],
    ])


async def sponsors_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in await db.rows("SELECT * FROM sponsors ORDER BY id"):
        rows.append([InlineKeyboardButton(text=f"👉 {s['title']}", url=s["url"] or "https://t.me/")])
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="sponsors:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("payment_button", amount=_amount()), url=url)],
        [InlineKeyboardButton(text="⏳ Я оплатил(а)", callback_data="pay:status")],
    ])


def _amount() -> str:
    from app.config import Config
    return Config.from_env().payment_amount


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="admin:menu"),
        ]
    ])