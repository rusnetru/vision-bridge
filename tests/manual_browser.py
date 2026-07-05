"""Ручной прогон браузер-бэкенда (Этап 3): stealth + CDP.

Проверяет на локальной HTML-странице: capture тегирует элементы, act печатает и
читает, клик работает; navigator.webdriver=false (признак стелса). Затем CDP:
поднимает реальный Chrome с debug-портом, подключается, делает capture, закрывает.

Запуск: uv run python tests/manual_browser.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from vision_bridge.backends import browser

HTML = """<!doctype html><html><head><meta charset=utf-8><title>VB Test</title></head>
<body><h1>VisionBridge browser test</h1>
<input id="q" placeholder="search box">
<button id="go">Go Button</button>
<a href="#x" role="link">MyLink</a>
</body></html>"""


def page_url() -> str:
    f = Path(tempfile.gettempdir()) / "vb_browser_test.html"
    f.write_text(HTML, encoding="utf-8")
    return f.as_uri()


def check_stealth() -> None:
    print("\n########## STEALTH ##########")
    r = browser.open_browser("stealth", page_url(), "", "", "chrome", headless=True)
    print("open:", r)
    if not r.get("ok"):
        return
    cap = browser.capture()
    print(f"capture ok={cap.ok} elements={len(cap.elements)} url={cap.target}")
    for el in cap.elements:
        print(f"  {el.id} [{el.role}] {el.name!r} bbox={el.bbox}")

    q = next((e for e in cap.elements if "search" in e.name.lower()), None)
    if q:
        print("type ->", browser.act(q.id, "type", "hello stealth", "").model_dump_json())
        print("read ->", browser.act(q.id, "read", "", "").model_dump_json())
    go = browser.find("Go", "")
    if go.ok:
        print("click ->", browser.act(go.element.id, "click", "", "").model_dump_json())

    # Признак стелса: в автоматизированном Playwright было бы true.
    wd = browser._run(lambda: browser._state["page"].evaluate("navigator.webdriver"))
    print("navigator.webdriver =", wd, "(ожидаем False/None)")
    browser.close()


def check_cdp() -> int:
    print("\n########## CDP (реальный Chrome) ##########")
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not Path(chrome).exists():
        print("Chrome не найден — пропуск CDP"); return 0
    profile = Path(tempfile.gettempdir()) / "vb_cdp_profile"
    proc = subprocess.Popen([
        chrome, "--remote-debugging-port=9222", f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check", page_url(),
    ])
    time.sleep(3.0)
    try:
        r = browser.open_browser("cdp", "", "http://localhost:9222", "", "", False)
        print("connect:", r)
        if r.get("ok"):
            cap = browser.capture()
            print(f"capture ok={cap.ok} elements={len(cap.elements)} url={cap.target}")
            for el in cap.elements[:6]:
                print(f"  {el.id} [{el.role}] {el.name!r} backend={el.backend}")
        browser.close()
    finally:
        proc.terminate()
    return 0


def main() -> int:
    check_stealth()
    check_cdp()
    return 0


if __name__ == "__main__":
    sys.exit(main())
