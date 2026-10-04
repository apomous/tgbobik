"""
Одноразовый ручной вход в кабинет ТТС. Сохраняет сессию для бота.

    py tts_login.py

В открывшемся Chrome войдите в личный кабинет сами (телефон, пароль, галочка
«Запомнить»), дождитесь, когда появится ваша карта с балансом, и нажмите
Enter в терминале. Пароль скрипт не читает и не сохраняет, только cookies сессии.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = "https://oao-tts.ru/ttsfind/"
LK = "https://oao-tts.ru/ttslk/"
SESSION_FILE = HERE / "tts_session.json"  # держите в секрете, как пароль

seen = {}


def on_request(req):
    if "ajax_card.php" in req.url:
        seen["card_url"] = req.url


with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=False, channel="chrome")
    except Exception:
        browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.on("request", on_request)
    page.goto(URL)
    input("Войдите в кабинет, дождитесь своей карты с балансом и нажмите Enter здесь... ")

    if "card_url" not in seen:
        page.goto(LK)
        page.wait_for_timeout(5000)
    cookies = ctx.cookies("https://oao-tts.ru")
    card_url = seen.get("card_url")

    card_resp = ""
    if card_url:
        try:
            card_resp = ctx.request.get(card_url).text()
        except Exception as e:
            card_resp = f"ошибка: {e}"
    (HERE / "tts_card_response.txt").write_text(card_resp, encoding="utf-8")
    browser.close()

SESSION_FILE.write_text(
    json.dumps({"cookies": cookies, "card_url": card_url}, ensure_ascii=False),
    encoding="utf-8")
print("Сессия сохранена в tts_session.json")
print("Адрес данных карты:", card_url or "НЕ НАЙДЕН (напишите мне)")
print("Ответ карты записан в tts_card_response.txt")
input("Нажмите Enter, чтобы закрыть окно... ")
