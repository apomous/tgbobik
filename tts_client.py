"""Баланс карты ТТС: читает данные карты из личного кабинета по вашей сессии (cookie)."""
import html
import logging
import os
import re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
COOKIE_FILE = HERE / "tts_cookie.txt"   # держите в секрете, как пароль
DEBUG_TXT = HERE / "tts_page.txt"
DEFAULT_URL = "https://oao-tts.ru/ttslk/ajax_card.php?id=84597"

NUM = r"(-?\d[\d\s]*(?:[.,]\d+)?)"
RELOGIN = "сессия истекла: войдите в кабинет в Chrome и обновите tts_cookie.txt"


def _to_text(raw: str) -> str:
    t = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def parse_balance(raw: str, card: str):
    text = _to_text(raw)
    idx = text.find(card)
    seg = text[idx: idx + 500] if idx >= 0 else text
    m = re.search(r"Баланс:?\s*" + NUM + r"\s*(?:р|₽|руб)", seg, re.I)
    if not m:
        m = re.search(r'balance"?\s*[:=]\s*"?(-?\d+(?:[.,]\d+)?)', raw, re.I)
    if not m:
        return None
    res = f"{m.group(1).strip()} ₽"
    m2 = re.search(r"доступная для записи:?\s*" + NUM + r"\s*(?:р|₽|руб)", seg, re.I)
    if m2:
        res += f" (доступно для записи: {m2.group(1).strip()} ₽)"
    return res


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _raw():
    """Куки/curl из секрета TTS_COOKIE или из файла tts_cookie.txt."""
    env = os.environ.get("TTS_COOKIE")
    if env:
        return env
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8-sig")
    return None


def _load_cookie() -> str:
    """Понимает 3 формата: строка 'имя=знач; ...', команда curl и таблица из Application → Cookies."""
    raw = (_raw() or "").strip()
    m = (re.search(r"(?:-b|--cookie)\s+(['\"])(.*?)\1", raw, re.S)
         or re.search(r"-H\s+(['\"])\s*cookie:\s*(.*?)\1", raw, re.S | re.I))
    if m:
        return " ".join(m.group(2).split())
    if "curl" not in raw.lower() and "\t" in raw:
        pairs = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and re.fullmatch(r"[\w.\-%]+", parts[0].strip()):
                pairs.append(f"{parts[0].strip()}={parts[1].strip()}")
        if pairs:
            return "; ".join(pairs)
    raw = re.sub(r"^cookie:\s*", "", raw, flags=re.I)
    return " ".join(raw.split())


def _load_ua() -> str:
    """User-Agent из скопированной curl-команды (если есть), иначе стандартный."""
    try:
        raw = _raw() or ""
        m = (re.search(r"-H\s+(['\"])\s*user-agent:\s*(.*?)\1", raw, re.S | re.I)
             or re.search(r"(?:-A|--user-agent)\s+(['\"])(.*?)\1", raw, re.S))
        if m:
            return " ".join(m.group(2).split())
    except Exception:
        pass
    return os.environ.get("TTS_USER_AGENT", UA)


def get_balance(card: str) -> str:
    if _raw() is None:
        return "нет кук ТТС (файл tts_cookie.txt или секрет TTS_COOKIE)"
    try:
        cookie = _load_cookie()
        names = [c.split("=", 1)[0].strip() for c in cookie.split(";") if "=" in c]
        if not names:
            return ("не нашёл кук ТТС. Нужна строка вида имя=значение; имя=значение "
                    "или команда curl целиком (проверьте файл tts_cookie.txt / секрет TTS_COOKIE)")
        r = requests.get(
            os.environ.get("TTS_CARD_URL", DEFAULT_URL),
            headers={"Cookie": cookie,
                     "User-Agent": _load_ua(),
                     "X-Requested-With": "XMLHttpRequest",
                     "Accept": "*/*",
                     "Referer": "https://oao-tts.ru/ttslk/"},
            timeout=25, allow_redirects=False)
        DEBUG_TXT.write_text(
            f"HTTP {r.status_code}\nLocation: {r.headers.get('Location')}\n"
            f"Имена кук ({len(names)}): {names}\n---\n{r.text[:3000]}",
            encoding="utf-8")
        if r.status_code in (301, 302, 303, 307, 308):
            return "сайт перенаправил на вход: кука не принята (см. tts_page.txt)"
        if r.status_code != 200:
            return f"сайт ответил HTTP {r.status_code} (см. tts_page.txt)"
        value = parse_balance(r.text, card)
        if not value:
            return "ответ получен, но баланс в нём не найден (см. tts_page.txt)"
        return value
    except Exception as e:
        logging.exception("tts balance")
        return f"ошибка ({e.__class__.__name__}: {e})"
