"""vision-bridge MCP-сервер.

Единый слой зрения за общими инструментами. Роутер выбора бэкенда спрятан внутри:
агент вызывает capture/act/find/wait_for одинаково для любого окна или страницы.

Бэкенды:
  • uia     — десктоп, нативные Win32/WPF/UWP (a11y-дерево);          Этап 1
  • ocr     — резерв для Electron/Chromium-окон, слепых для UIA;      Этап 2
  • browser — реальный Chrome по CDP / стелс-браузер (patchright);   Этап 3

Маршрутизация act/read по префиксу id: u→uia, o→ocr, b→browser.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .models import ActResult, CaptureResult, FindResult

mcp = FastMCP("vision-bridge")

# Если UIA дал меньше стольких интерактивных элементов — пробуем OCR-резерв.
MIN_UIA_ELEMENTS = 2


# ─────────────────────────── ленивые бэкенды ───────────────────────────

def _load(name: str):
    try:
        from importlib import import_module

        return import_module(f".backends.{name}", __package__)
    except Exception as exc:  # noqa: BLE001
        return exc


def _hint(name: str, exc: Exception) -> str:
    extra = "desktop" if name in ("uia", "ocr") else "browser"
    return (f"бэкенд '{name}' недоступен ({type(exc).__name__}: {exc}). "
            f"Установи: uv sync --extra {extra}")


_DISPATCH = {"u": "uia", "o": "ocr", "b": "browser"}


def _backend_for_id(element_id: str):
    name = _DISPATCH.get(element_id[:1])
    if name is None:
        return None, f"неизвестный префикс id '{element_id}'"
    mod = _load(name)
    if isinstance(mod, Exception):
        return None, _hint(name, mod)
    return mod, None


# ─────────────────────────────── tools ───────────────────────────────

@mcp.tool()
def capture(target: str, mode: str = "auto") -> dict:
    """Посмотреть на цель и вернуть её как структуру + текст.

    target: заголовок окна десктоп-приложения (подстрока, регистронезависимо),
        либо "browser" для активной страницы открытого браузера; пусто — активное
        окно на переднем плане.
    mode: "auto" (сам выбирает: UIA → при бедном результате OCR),
        либо принудительно "uia" | "ocr" | "browser".

    Возвращает {ok, elements:[{id,role,name,bbox,...}], text, method_used}. Текстовый
    мозг читает `text`, действует по `elements[].id` через act().
    """
    if target == "browser" or mode == "browser":
        br = _load("browser")
        if isinstance(br, Exception):
            return CaptureResult(ok=False, target=target,
                                 error=_hint("browser", br)).model_dump()
        return br.capture().model_dump()

    if mode == "ocr":
        ocr = _load("ocr")
        if isinstance(ocr, Exception):
            return CaptureResult(ok=False, target=target,
                                 error=_hint("ocr", ocr)).model_dump()
        return ocr.capture(target).model_dump()

    if mode in ("auto", "uia"):
        uia = _load("uia")
        if isinstance(uia, Exception):
            return CaptureResult(ok=False, target=target,
                                 error=_hint("uia", uia)).model_dump()
        res = uia.capture(target)
        # auto: если UIA-дерево бедное (типично для Electron) — пробуем OCR.
        if mode == "auto" and res.ok and len(res.elements) < MIN_UIA_ELEMENTS:
            ocr = _load("ocr")
            if not isinstance(ocr, Exception):
                ocr_res = ocr.capture(target)
                if ocr_res.ok and len(ocr_res.elements) > len(res.elements):
                    return ocr_res.model_dump()
        return res.model_dump()

    return CaptureResult(ok=False, target=target,
                         error=f"неизвестный mode '{mode}'").model_dump()


@mcp.tool()
def act(element_id: str, action: str, text: str = "", value: str = "") -> dict:
    """Perform an action on an element from capture() or find().

    Uses the element's stable id (u-prefix=desktop, o-prefix=OCR,
    b-prefix=browser) — never pass raw coordinates or CSS selectors.

    Args:
        element_id: Element identifier from capture().elements[].id
                    or find().element.id. The prefix routes the action
                    to the correct backend automatically.
        action: One of:
                "click"        — left mouse click.
                "double_click" — double left click.
                "type"         — type text character by character
                                 (use `text` parameter).
                "set_value"    — replace the entire value of a field
                                 (use `value` parameter).
                "focus"        — set keyboard focus to the element.
                "read"         — read current text/value of the element
                                 (returned in `content` field).
                "scroll"       — scroll the element into view.
        text: Text to type for action="type". Supports any characters.
        value: New value for action="set_value". Replaces field content.

    Returns:
        {ok: true} on success.
        For action="read": {ok: true, content: "text content"}.
        On failure: {ok: false, error: "..."}.

    Example:
        >>> r = capture("Notepad")
        >>> act(r.elements[0].id, "type", text="Hello")
        >>> act(r.elements[0].id, "read")
        {"ok": true, "content": "Hello"}
    """
    mod, err = _backend_for_id(element_id)
    if mod is None:
        return ActResult(ok=False, element_id=element_id, action=action,
                         error=err).model_dump()
    return mod.act(element_id, action, text, value).model_dump()


@mcp.tool()
def find(query: str, target: str = "", mode: str = "auto") -> dict:
    """Locate a single UI element by its name or value (substring match).

    Searches the current screen capture for an element whose name or value
    contains `query`. Returns the first match — use when you know the
    exact button label, field name, or text snippet you need.

    Args:
        query: Substring to search for in element names/values.
               Case-insensitive. Examples: "OK", "Submit", "Untitled".
        target: Window title substring for desktop apps, or "browser"
                for the open browser page. Empty = foreground window.
        mode: Backend selector:
              "auto" — UIA first, OCR fallback on failure (recommended).
              "uia"  — Desktop UIA only.
              "ocr"  — OCR (Tesseract) only.
              "browser" — Browser page only.

    Returns:
        {ok, element: {id, role, name, value, bbox, state, backend}}
        On failure: {ok: false, error: "..."}.

        The returned element.id is ready for act() — no coordinate math needed.

    Example:
        >>> find("Save", target="Notepad")
        {"ok": true, "element": {"id": "u5", "role": "button", "name": "Save", ...}}
        >>> act("u5", "click")
    """
    if target == "browser" or mode == "browser":
        name = "browser"
    elif mode == "ocr":
        name = "ocr"
    else:
        name = "uia"
    mod = _load(name)
    if isinstance(mod, Exception):
        return FindResult(ok=False, error=_hint(name, mod)).model_dump()
    res = mod.find(query, target)
    if name == "uia" and mode == "auto" and not res.ok:
        ocr = _load("ocr")
        if not isinstance(ocr, Exception):
            ocr_res = ocr.find(query, target)
            if ocr_res.ok:
                return ocr_res.model_dump()
    return res.model_dump()


@mcp.tool()
def wait_for(query: str, target: str = "", timeout_s: float = 10.0,
             mode: str = "auto") -> dict:
    """Poll until a UI element matching `query` appears or becomes ready.

    Repeatedly searches the screen (using find logic) until the element
    is found or `timeout_s` expires. Essential for dynamic UIs where
    elements appear after animations, network loads, or navigation.

    Args:
        query: Substring to search for in element names/values.
               Case-insensitive. Examples: "Loading...", "Ready", "OK".
        target: Window title substring for desktop apps, or "browser"
                for the browser page. Empty = foreground window.
        timeout_s: Maximum wait time in seconds (default 10.0).
                   Fractional values work: 0.5 = 500ms.
        mode: Backend selector:
              "auto" — UIA first, OCR fallback (recommended).
              "uia" | "ocr" | "browser".

    Returns:
        {ok, element: {id, role, name, value, bbox, state, backend}}
        On timeout: {ok: false, error: "timeout after Ns"}.

    Example:
        >>> wait_for("Install", timeout_s=30)
        {"ok": true, "element": {"id": "u12", "role": "button", "name": "Install", ...}}
        >>> act("u12", "click")
    """
    if target == "browser" or mode == "browser":
        name = "browser"
    elif mode == "ocr":
        name = "ocr"
    else:
        name = "uia"
    mod = _load(name)
    if isinstance(mod, Exception):
        return FindResult(ok=False, error=_hint(name, mod)).model_dump()
    res = mod.wait_for(query, target, timeout_s)
    # auto: если UIA не нашёл — пробуем OCR (аналогично find)
    if name == "uia" and mode == "auto" and not res.ok:
        ocr = _load("ocr")
        if not isinstance(ocr, Exception):
            ocr_res = ocr.wait_for(query, target, timeout_s)
            if ocr_res.ok:
                return ocr_res.model_dump()
    return res.model_dump()


# ─────────────────────── браузер: управление сессией ───────────────────────

@mcp.tool()
def browser_open(mode: str = "stealth", url: str = "", cdp_url: str = "",
                 user_data_dir: str = "", channel: str = "chrome",
                 headless: bool = False) -> dict:
    """Открыть/подключить браузер для незаметной работы.

    mode="cdp": подключиться к УЖЕ запущенному Chrome по DevTools-протоколу
        (cdp_url, по умолчанию http://localhost:9222). Максимальная незаметность,
        живые куки, сессии не рвутся. Chrome нужно стартовать заранее с
        `--remote-debugging-port=9222` и своим `--user-data-dir`.
    mode="stealth": свой браузер под управлением слоя (patchright) с постоянным
        профилем user_data_dir и каналом реального Chrome (channel="chrome").
    url: если задан — сразу перейти. После открытия используй capture("browser").
    """
    br = _load("browser")
    if isinstance(br, Exception):
        return {"ok": False, "error": _hint("browser", br)}
    return br.open_browser(mode, url, cdp_url, user_data_dir, channel, headless)


@mcp.tool()
def browser_goto(url: str) -> dict:
    """Navigate the open browser to a new URL.

    Requires a browser session opened via browser_open(). Navigation is
    synchronous — call capture("browser") afterwards to inspect the page.

    Args:
        url: Full URL to navigate to, including protocol.
             Example: "https://example.com/login"

    Returns:
        {ok: true} on success, {ok: false, error: "..."} on failure
        (e.g., no browser session open, invalid URL, network error).

    Example:
        >>> browser_open(mode="cdp")
        >>> browser_goto("https://github.com")
        >>> capture("browser")
    """
    br = _load("browser")
    if isinstance(br, Exception):
        return {"ok": False, "error": _hint("browser", br)}
    return br.goto(url)


@mcp.tool()
def browser_close() -> dict:
    """Close the active browser session (CDP or stealth).

    Call after you're done with browser automation to free resources.
    Does nothing if no session is open.

    Returns:
        {ok: true} on success, {ok: false, error: "..."} on failure.

    Example:
        >>> browser_close()
        {"ok": true}
    """
    br = _load("browser")
    if isinstance(br, Exception):
        return {"ok": False, "error": _hint("browser", br)}
    return br.close()


def main() -> None:
    """Точка входа для stdio-транспорта (console script `vision-bridge`)."""
    mcp.run()


if __name__ == "__main__":
    main()
