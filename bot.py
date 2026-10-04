"""
Телеграм-бот: расписание Модеус по кнопкам + утренняя сводка + баланс ТТС + анекдот в 12:00.

Установка:
    pip install "python-telegram-bot[job-queue]==21.6" requests playwright python-dotenv
    playwright install chromium

Файл .env рядом со скриптом (никому не показывать!):
    BOT_TOKEN=новый токен от @BotFather
    CHAT_ID=902739753
    MODEUS_LOGIN=логин
    MODEUS_PASSWORD=пароль
    CARD_NUMBER=159026464
    BALANCE_URL=адрес запроса баланса ТТС (с {card} вместо номера)
"""
import asyncio
import logging
import os
import random
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters

import modeus_client as modeus
import tts_client

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
CARD_NUMBER = os.environ.get("CARD_NUMBER", "")
BALANCE_URL = os.environ.get("BALANCE_URL", "")

TZ = timezone(timedelta(hours=5))
MORNING_TIME = time(7, 30, tzinfo=TZ)
JOKE_TIME = time(12, 0, tzinfo=TZ)

JOKES = [
    "— Доктор, я скоро умру? — Не знаю, я же не налоговая.",
    "Купил абонемент в спортзал. Теперь у меня есть повод ходить мимо него с чувством вины.",
    "— Ты почему опоздал? — Ехал на автобусе. — И что? — Он ехал на другом.",
    "Будильник — это изобретение, которое превращает утро в личное оскорбление.",
    "Студент — это организм, который превращает кофе в зачёты.",
    "Преподаватель: «Кто не сдал — не расстраивайтесь, пересдача тоже входит в курс».",
    "Диета — это когда ешь то, что не хочешь, чтобы стать тем, кем не станешь.",
]

KEYBOARD = ReplyKeyboardMarkup(
    [["📅 Сегодня", "➡️ Завтра"], ["🗓 Неделя", "🗓 След. неделя"], ["💳 Баланс"]],
    resize_keyboard=True,
)


# ---------- ТТС: баланс ----------
def get_balance() -> str:
    return tts_client.get_balance(CARD_NUMBER)


# ---------- Модеус ----------
async def schedule_text(kind: str) -> str:
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())
    if kind == "today":
        d1, d2, title, by_day = today, today + timedelta(days=1), f"📅 Сегодня, {today:%d.%m}", False
    elif kind == "tomorrow":
        t = today + timedelta(days=1)
        d1, d2, title, by_day = t, t + timedelta(days=1), f"➡️ Завтра, {t:%d.%m}", False
    elif kind == "week":
        d1, d2, title, by_day = monday, monday + timedelta(days=7), "🗓 Эта неделя", True
    else:
        n = monday + timedelta(days=7)
        d1, d2, title, by_day = n, n + timedelta(days=7), "🗓 Следующая неделя", True
    try:
        events = await asyncio.to_thread(modeus.fetch_events, d1, d2)
        return modeus.format_events(events, title, by_day)
    except Exception as e:
        logging.exception("modeus")
        return f"Не получилось получить расписание: {e.__class__.__name__}: {e}"


# ---------- Обработчики ----------
async def on_button(update, context):
    text = update.message.text
    if "Баланс" in text:
        bal = await asyncio.to_thread(get_balance)
        await update.message.reply_text(f"💳 Баланс карты: {bal}")
        return
    kind = ("tomorrow" if "Завтра" in text else
            "nextweek" if "След" in text else
            "week" if "Неделя" in text else "today")
    await update.message.reply_text("Секунду…")
    await update.message.reply_text(await schedule_text(kind))


async def cmd_start(update, context):
    await update.message.reply_text("Привет! Выбери действие 👇", reply_markup=KEYBOARD)


async def cmd_joke(update, context):
    await update.message.reply_text("😄 " + random.choice(JOKES))


async def morning_job(context):
    sched = await schedule_text("today")
    bal = await asyncio.to_thread(get_balance)
    await context.bot.send_message(CHAT_ID, f"Доброе утро!\n\n{sched}\n\n💳 Баланс карты: {bal}",
                                   reply_markup=KEYBOARD)


async def joke_job(context):
    await context.bot.send_message(CHAT_ID, "😄 " + random.choice(JOKES))


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # в логах не светим токен
    app = Application.builder().token(BOT_TOKEN).build()
    me = filters.Chat(CHAT_ID)  # бот отвечает только вам
    app.add_handler(CommandHandler("start", cmd_start, filters=me))
    app.add_handler(CommandHandler("joke", cmd_joke, filters=me))
    app.add_handler(MessageHandler(
        me & filters.TEXT & filters.Regex("Сегодня|Завтра|Неделя|След|Баланс"), on_button))
    app.job_queue.run_daily(morning_job, MORNING_TIME)
    app.job_queue.run_daily(joke_job, JOKE_TIME)
    app.run_polling()


if __name__ == "__main__":
    main()
