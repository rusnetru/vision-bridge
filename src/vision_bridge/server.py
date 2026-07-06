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
    """Выполнить действие над элементом из capture()/find().

    action: click | double_click | type | set_value | focus | read | scroll.
    text: для action="type" — что напечатать.
    value: для action="set_value" — новое значение поля (заменяет целиком).
    Для action="read" текст возвращается в поле `content`.
    Бэкенд выбирается по префиксу element_id (u=десктоп, o=OCR, b=браузер).
    """
    mod, err = _backend_for_id(element_id)
    if mod is None:
        return ActResult(ok=False, element_id=element_id, action=action,
                         error=err).model_dump()
    return mod.act(element_id, action, text, value).model_dump()


@mcp.tool()
def find(query: str, target: str = "", mode: str = "auto") -> dict:
    """Найти один элемент по описанию (имя/значение содержит query).

    target: окно, либо "browser" для страницы; пусто — активное окно.
    mode: "auto" | "uia" | "ocr" | "browser".
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
    """Дождаться появления/готовности элемента (поллинг до timeout_s секунд)."""
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
    """Перейти по URL в открытом браузере."""
    br = _load("browser")
    if isinstance(br, Exception):
        return {"ok": False, "error": _hint("browser", br)}
    return br.goto(url)


@mcp.tool()
def browser_close() -> dict:
    """Закрыть браузерную сессию слоя."""
    br = _load("browser")
    if isinstance(br, Exception):
        return {"ok": False, "error": _hint("browser", br)}
    return br.close()


def main() -> None:
    """Точка входа для stdio-транспорта (console script `vision-bridge`)."""
    mcp.run()


if __name__ == "__main__":
    main()
