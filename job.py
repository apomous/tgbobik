"""Разовые задания для GitHub Actions: python job.py morning | joke"""
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import jokes
import os

TZ = timezone(timedelta(hours=5))  # Тюмень
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
CARD = os.environ.get("CARD_NUMBER", "")


def wait_until(hour: int, minute: int = 0) -> None:
    """Если запустились чуть раньше — ждём точного времени (но не дольше 30 минут)."""
    now = datetime.now(TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (target - now).total_seconds()
    if 0 < delta <= 30 * 60:
        print(f"Жду {int(delta)} сек. до {hour:02d}:{minute:02d}")
        time.sleep(delta)


def send(text: str) -> None:
    if not re.fullmatch(r"\d{6,}:[\w-]{30,}", BOT_TOKEN):
        raise SystemExit("BOT_TOKEN в секретах пустой или неверного формата "
                         "(нужен вид 123456789:AAH..., без пробелов и слова bot)")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID в секретах пустой")
    text = text if len(text) <= 4000 else text[:3990] + "\n…"
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text}, timeout=30)
    if not r.ok:
        raise SystemExit(f"Telegram ответил HTTP {r.status_code}: {r.text[:200]}")
    print("Отправлено")


def morning() -> None:
    import modeus_client as modeus  # нужен только утром (требует playwright)
    import tts_client

    today = datetime.now(TZ).date()
    try:
        events = modeus.fetch_events(today, today + timedelta(days=1))
        sched = modeus.format_events(events, f"📅 Сегодня, {today:%d.%m}")
    except Exception as e:
        print("modeus error:", e.__class__.__name__, e)
        sched = f"📅 Расписание не получилось загрузить ({e.__class__.__name__})"
    bal = tts_client.get_balance(CARD)
    text = f"Доброе утро!\n\n{sched}\n\n💳 Баланс карты: {bal}"
    wait_until(8, 0)
    send(text)


def joke() -> None:
    text = jokes.get_joke()
    wait_until(12, 0)
    send(text)


if __name__ == "__main__":
    {"morning": morning, "joke": joke}[sys.argv[1]]()
