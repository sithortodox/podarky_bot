"""Конфигурация бота: всё читается из переменных окружения / .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            ids.add(int(chunk))
    return ids


@dataclass(slots=True)
class Config:
    bot_token: str
    admin_ids: set[int]
    payment_url: str
    payment_amount: str
    payment_webhook_token: str
    webhook_host: str
    webhook_port: int
    db_path: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or ":" not in token:
            raise RuntimeError("BOT_TOKEN не задан — заполните файл .env (см. .env.example)")

        db_path = os.getenv("DB_PATH", "data/bot.db").strip() or "data/bot.db"
        if db_path not in (":memory:",) and db_path != Path(db_path).name:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        return cls(
            bot_token=token,
            admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
            payment_url=os.getenv("PAYMENT_URL", "https://example.com/pay").strip(),
            payment_amount=os.getenv("PAYMENT_AMOUNT", "1 ₽").strip() or "1 ₽",
            payment_webhook_token=os.getenv("PAYMENT_WEBHOOK_TOKEN", "").strip(),
            webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0",
            webhook_port=int(os.getenv("WEBHOOK_PORT", "8081") or 8081),
            db_path=db_path,
        )