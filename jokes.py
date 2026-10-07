"""Анекдоты: берём из онлайн-базы, не повторяем (помним уже присланные)."""
import hashlib
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE = HERE / "jokes_state.json"   # хеши уже присланных шуток
LOCAL = HERE / "my_jokes.txt"       # ваши любимые: шутки разделяйте пустой строкой

API = "http://rzhunemogu.ru/RandJSON.aspx?CType={}"
# Типы: 1 анекдот, 3 стишок, 4 афоризм, 5 цитата, 6 тост, 8 статус
TITLES = {1: "😄 Анекдот", 3: "📝 Стишок", 4: "💬 Афоризм", 5: "💬 Цитата", 8: "📱 Статус"}
# Разнообразие по дням недели (0 = понедельник). Остальные дни — анекдот.
WEEK_PLAN = {5: 4, 6: 3}  # суббота — афоризм, воскресенье — стишок

FALLBACK = [
    "— Доктор, я скоро умру? — Не знаю, я же не налоговая.",
    "Купил абонемент в спортзал. Теперь у меня есть повод ходить мимо него с чувством вины.",
    "— Ты почему опоздал? — Ехал на автобусе. — И что? — Он ехал на другом.",
    "Студент — это организм, который превращает кофе в зачёты.",
    "Диета — это когда ешь то, что не хочешь, чтобы стать тем, кем не станешь.",
]


def _hash(text: str) -> str:
    norm = re.sub(r"[^а-яa-z0-9]", "", text.lower())
    return hashlib.md5(norm.encode()).hexdigest()[:10]


def _load() -> list:
    try:
        return [h[:10] for h in json.loads(STATE.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _save(seen: list) -> None:
    try:
        STATE.write_text(json.dumps(seen[-1000:]), encoding="utf-8")
    except Exception:
        pass


def _fetch(ctype: int):
    try:
        r = requests.get(API.format(ctype), timeout=10)
        r.encoding = "windows-1251"
        m = re.search(r'"content"\s*:\s*"(.*)"\s*}', r.text, re.S)
        if not m:
            return None
        text = m.group(1).replace("\r", "").strip()
        if not (60 <= len(text) <= 700) or re.search(r"https?://|www\.", text):
            return None  # слишком короткие/длинные и с рекламой не берём
        return text
    except Exception:
        return None


def _local_pool() -> list:
    pool = list(FALLBACK)
    if LOCAL.exists():
        pool += [p.strip() for p in LOCAL.read_text(encoding="utf-8-sig").split("\n\n") if p.strip()]
    return pool


def get_joke(force_anecdote: bool = False) -> str:
    seen = _load()
    day = datetime.now(timezone(timedelta(hours=5))).weekday()
    ctype = 1 if force_anecdote else WEEK_PLAN.get(day, 1)

    for _ in range(15):  # до 15 попыток найти новую
        text = _fetch(ctype)
        if text and _hash(text) not in seen:
            seen.append(_hash(text))
            _save(seen)
            return f"{TITLES.get(ctype, '😄')}\n\n{text}"

    pool = [t for t in _local_pool() if _hash(t) not in seen] or _local_pool()
    text = random.choice(pool)
    seen.append(_hash(text))
    _save(seen)
    return f"😄 Анекдот\n\n{text}"
