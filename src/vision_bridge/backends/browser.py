"""Браузер-бэкенд (Этап 3) — незаметная работа без разрыва сессии.

Два режима на выбор под задачу:
  • cdp    — подключение к УЖЕ запущенному реальному Chrome по DevTools-протоколу
             (`connect_over_cdp`). navigator.webdriver=false, настоящий отпечаток
             и живые куки — практически неотличимо от человека. Chrome нужно
             стартовать с `--remote-debugging-port=9222` и своим `--user-data-dir`.
  • stealth — отдельный браузер под управлением слоя через patchright
             (пропатченный Playwright, прячет CDP-утечки типа Runtime.enable) с
             постоянным профилем (persistent context) и каналом реального Chrome.

Восприятие — DOM-снимок интерактивных элементов + плоский текст страницы.
Интерактивные элементы тегируются `data-vb-id`, действия идут по этому локатору —
стабильно в пределах одного снимка (как @ref у Playwright).

Playwright sync API привязан к своему потоку — все вызовы гоним через выделенный
однопоточный executor `_run`.
"""

from __future__ import annotations

import concurrent.futures
import time

from ..models import (
    ActResult,
    Backend,
    CaptureResult,
    Element,
    ElementState,
    FindResult,
)

PREFIX = "b"  # id элементов: b0, b1, …
DEFAULT_CDP = "http://localhost:9222"

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
_BROWSER_TIMEOUT = 30  # таймаут на браузерную операцию (сек)

# Живёт в потоке _pool.
_state: dict = {"pw": None, "browser": None, "context": None, "page": None,
                "mode": None, "backend": Backend.PLAYWRIGHT}


def _run(fn, *args, timeout: float = _BROWSER_TIMEOUT):
    """Выполнить fn в браузерном потоке с таймаутом."""
    return _pool.submit(fn, *args).result(timeout=timeout)


# JS: тегирует интерактивные элементы и возвращает их + текст страницы.
_SCAN_JS = r"""
(prefix) => {
  const sel = 'a,button,input,textarea,select,[role=button],[role=link],' +
    '[role=textbox],[role=checkbox],[role=tab],[role=menuitem],' +
    '[contenteditable=""],[contenteditable=true]';
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    const id = prefix + (i++);
    el.setAttribute('data-vb-id', id);
    const role = el.getAttribute('role') || el.tagName.toLowerCase();
    const name = (el.getAttribute('aria-label') || el.placeholder ||
      el.value || el.innerText || el.textContent || '').trim().slice(0, 200);
    out.push({id, role, name, value: (el.value ?? null),
      bbox: [Math.round(r.x), Math.round(r.y),
             Math.round(r.width), Math.round(r.height)],
      enabled: !el.disabled});
  }
  const text = (document.body ? document.body.innerText : '').slice(0, 8000);
  return {elements: out, text};
}
"""


def _ensure_pw():
    if _state["pw"] is None:
        try:
            from patchright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"patchright недоступен ({type(exc).__name__}: {exc}). "
                "Установи: uv sync --extra browser && uv run patchright install chromium"
            ) from exc
        _state["pw"] = sync_playwright().start()
    return _state["pw"]


def _open(mode: str, url: str, cdp_url: str, user_data_dir: str, channel: str,
          headless: bool) -> dict:
    pw = _ensure_pw()
    _close_session()
    if mode == "cdp":
        browser = pw.chromium.connect_over_cdp(cdp_url or DEFAULT_CDP)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        _state.update(browser=browser, context=context, page=page, mode="cdp",
                      backend=Backend.CDP)
    elif mode == "stealth":
        # Снимаем маркеры автоматизации: убираем --enable-automation и выключаем
        # blink-фичу AutomationControlled, из-за которой navigator.webdriver=true.
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or "./.vb-profile",
            channel=channel or "chrome",
            headless=headless,
            no_viewport=True,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        _state.update(browser=None, context=context, page=page, mode="stealth",
                      backend=Backend.PLAYWRIGHT)
    else:
        return {"ok": False, "error": f"неизвестный режим '{mode}' (cdp|stealth)"}
    if url:
        page.goto(url, wait_until="domcontentloaded")
    return {"ok": True, "mode": mode, "url": page.url, "title": page.title()}


def _goto(url: str) -> dict:
    page = _state["page"]
    if page is None:
        return {"ok": False, "error": "браузер не открыт — вызови browser_open"}
    page.goto(url, wait_until="domcontentloaded")
    return {"ok": True, "url": page.url, "title": page.title()}


def _capture() -> CaptureResult:
    page = _state["page"]
    if page is None:
        return CaptureResult(ok=False, target="browser",
                             error="браузер не открыт — вызови browser_open")
    data = page.evaluate(_SCAN_JS, PREFIX)
    elements = [
        Element(id=e["id"], role=e["role"], name=e["name"], value=e["value"],
                bbox=tuple(e["bbox"]), state=ElementState(enabled=e["enabled"]),
                backend=_state["backend"])
        for e in data["elements"]
    ]
    return CaptureResult(ok=True, target=page.url, method_used=_state["backend"],
                         elements=elements, text=data["text"])


def _locator(page, element_id: str):
    return page.locator(f'[data-vb-id="{element_id}"]').first


def _act(element_id: str, action: str, text: str, value: str) -> ActResult:
    page = _state["page"]
    if page is None:
        return ActResult(ok=False, element_id=element_id, action=action,
                         error="браузер не открыт — вызови browser_open")
    loc = _locator(page, element_id)
    try:
        if loc.count() == 0:
            return ActResult(ok=False, element_id=element_id, action=action,
                             error="element_id не найден на странице — capture() заново")
        if action == "click":
            loc.click()
        elif action == "double_click":
            loc.dblclick()
        elif action == "type":
            loc.click()
            loc.press_sequentially(text)
        elif action == "set_value":
            loc.fill(value)
        elif action == "focus":
            loc.focus()
        elif action == "read":
            content = loc.input_value() if loc.evaluate(
                "el => 'value' in el") else loc.inner_text()
            return ActResult(ok=True, element_id=element_id, action="read",
                             content=content)
        elif action == "scroll":
            loc.scroll_into_view_if_needed()
        else:
            return ActResult(ok=False, element_id=element_id, action=action,
                             error=f"неизвестное действие '{action}'")
        return ActResult(ok=True, element_id=element_id, action=action)
    except Exception as exc:  # noqa: BLE001
        return ActResult(ok=False, element_id=element_id, action=action,
                         error=f"{type(exc).__name__}: {exc}")


def _find(query: str, target: str) -> FindResult:
    cap = _capture()
    if not cap.ok:
        return FindResult(ok=False, error=cap.error)
    needle = query.lower()
    for el in cap.elements:
        if needle in el.name.lower():
            return FindResult(ok=True, element=el)
    return FindResult(ok=False, error=f"элемент '{query}' не найден на странице")


def _wait_for(query: str, target: str, timeout_s: float) -> FindResult:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = _find(query, target)
        if res.ok:
            return res
        time.sleep(0.5)
    return FindResult(ok=False, error=f"'{query}' не появился за {timeout_s} с")


def _close_session() -> None:
    for key in ("context", "browser"):
        obj = _state.get(key)
        if obj is not None:
            try:
                obj.close()
            except Exception:  # noqa: BLE001
                pass
    _state.update(browser=None, context=None, page=None)


def _close() -> dict:
    _close_session()
    return {"ok": True}


# ──────────────────── публичный API (в потоке браузера) ────────────────────

def open_browser(mode: str, url: str, cdp_url: str, user_data_dir: str,
                 channel: str, headless: bool = False) -> dict:
    return _run(_open, mode, url, cdp_url, user_data_dir, channel, headless)


def goto(url: str) -> dict:
    return _run(_goto, url)


def capture(target: str = "browser") -> CaptureResult:
    return _run(_capture)


def act(element_id: str, action: str, text: str, value: str) -> ActResult:
    return _run(_act, element_id, action, text, value)


def find(query: str, target: str) -> FindResult:
    return _run(_find, query, target)


def wait_for(query: str, target: str, timeout_s: float) -> FindResult:
    return _run(_wait_for, query, target, timeout_s)


def close() -> dict:
    return _run(_close)
