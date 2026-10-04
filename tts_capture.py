"""
Ловит запрос проверки баланса на oao-tts.ru.

    py tts_capture.py

Откроется браузер. Введите номер карты, нажмите кнопку проверки, дождитесь
результата с суммой, затем вернитесь в терминал и нажмите Enter.
Результат запишется в tts_requests.txt рядом со скриптом. Пришлите его мне.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://oao-tts.ru/ttsfind/"
OUT = Path(__file__).resolve().parent / "tts_requests.txt"

records = []


def on_response(resp):
    try:
        req = resp.request
        if "oao-tts.ru" not in resp.url:
            return
        if req.resource_type not in ("xhr", "fetch", "document") and req.method != "POST":
            return
        body = ""
        try:
            body = resp.text()[:1500]
        except Exception:
            pass
        records.append(
            f"{req.method} {resp.status} {resp.url}\n"
            f"   type: {req.resource_type}\n"
            f"   post: {(req.post_data or '')[:500]}\n"
            f"   response: {body}\n"
        )
    except Exception:
        pass


with sync_playwright() as p:
    try:
        browser = p.chromium.launch(
            headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"])
    except Exception:  # Chrome не установлен — берём встроенный Chromium
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"])
    page = browser.new_page()
    page.on("response", on_response)
    page.goto(URL)
    input("Введите номер карты, нажмите проверку, дождитесь суммы и нажмите Enter здесь... ")
    browser.close()

text = "\n".join(records) or "(ничего не поймано)"
OUT.write_text(text, encoding="utf-8")
print(f"\nГотово: {OUT}")
input("Нажмите Enter, чтобы закрыть окно... ")
