"""Десктоп-бэкенд через Windows UI Automation (a11y-дерево).

Основной механизм зрения для нативных Win32/WPF/UWP-окон: читает дерево, отдаёт
элементы с экранными координатами и текстовый дамп, умеет кликать/печатать/ждать.
Electron/Chromium частично слепы для UIA — для них будет OCR-fallback (Этап 2).

COM-операции UIA не потокобезопасны: все вызовы гоняем в одном выделенном потоке
через `_run`, чтобы работать из async-контекста MCP-сервера без гонок.
"""

from __future__ import annotations

import concurrent.futures
import time

import uiautomation as auto
from uiautomation import uiautomation as _ua

from ..models import (
    ActResult,
    Backend,
    CaptureResult,
    Element,
    ElementState,
    FindResult,
)

PREFIX = "u"  # id элементов: u0, u1, … (диспетчер маршрутизирует act по префиксу)
MAX_ELEMENTS = 300
MAX_DEPTH = 25
SEARCH_TIMEOUT = 2.0

# Роли UIA, по которым имеет смысл действовать (клик/ввод/выбор).
_INTERACTIVE = {
    "button", "textbox", "link", "checkbox", "radiobutton", "combobox",
    "listitem", "menuitem", "tabitem", "splitbutton", "document", "slider",
    "spinner", "treeitem",
}
_ROLE_ALIAS = {"edit": "textbox", "hyperlink": "link"}

# id элемента → живой UIA-control. Переписывается при каждом capture/find,
# как @ref у Playwright: старые id инвалидируются новым снимком.
_registry: dict[str, auto.Control] = {}
_counter = 0

# Выделенный поток для всех COM/UIA-вызовов.
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="uia")
_UIA_TIMEOUT = 15  # таймаут на UIA-операцию (сек), чтобы не вешать MCP-вызов


def _run(fn, *args, timeout: float = _UIA_TIMEOUT):
    """Выполнить fn в COM-потоке с инициализацией CoInitialize и таймаутом."""

    def _wrapper():
        auto.InitializeUIAutomationInCurrentThread()
        return fn(*args)

    return _pool.submit(_wrapper).result(timeout=timeout)


# ─────────────────────────── вспомогательные ───────────────────────────

def _role(ctrl: auto.Control) -> str:
    t = ctrl.ControlTypeName  # напр. 'ButtonControl'
    role = t[:-7].lower() if t.endswith("Control") else t.lower()
    return _ROLE_ALIAS.get(role, role)


def _rect(ctrl: auto.Control) -> tuple[int, int, int, int]:
    try:
        r = ctrl.BoundingRectangle
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return (0, 0, 0, 0)


def _value(ctrl: auto.Control) -> str | None:
    try:
        vp = ctrl.GetValuePattern()
        if vp is not None:
            return vp.Value
    except Exception:
        pass
    return None


def _text_content(ctrl: auto.Control) -> str:
    """Полный текст элемента: ValuePattern → TextPattern → Name.

    Новые WinUI-редакторы (Блокнот 11) отдают содержимое только через TextPattern.
    """
    val = _value(ctrl)
    if val:
        return val
    try:
        tp = ctrl.GetTextPattern()
        if tp is not None:
            text = tp.DocumentRange.GetText(-1)
            if text:
                return text
    except Exception:
        pass
    return (ctrl.Name or "").strip()


def _state(ctrl: auto.Control) -> ElementState:
    try:
        checked = None
        tp = ctrl.GetTogglePattern()
        if tp is not None:
            checked = tp.ToggleState == auto.ToggleState.On
        return ElementState(
            enabled=bool(ctrl.IsEnabled),
            focused=bool(getattr(ctrl, "HasKeyboardFocus", False)),
            visible=not bool(ctrl.IsOffscreen),
            checked=checked,
        )
    except Exception:
        return ElementState()


def _register(ctrl: auto.Control, role: str) -> Element:
    global _counter
    eid = f"{PREFIX}{_counter}"
    _counter += 1
    _registry[eid] = ctrl
    return Element(
        id=eid,
        role=role,
        name=(ctrl.Name or "").strip(),
        value=_value(ctrl),
        bbox=_rect(ctrl),
        state=_state(ctrl),
        backend=Backend.UIA,
    )


def _find_window(target: str) -> auto.Control | None:
    """Верхнеуровневое окно по подстроке заголовка (регистронезависимо)."""
    if not target:
        try:
            return auto.GetForegroundControl().GetTopLevelControl()
        except Exception:
            return None
    needle = target.lower()
    root = auto.GetRootControl()
    for top in root.GetChildren():
        try:
            if needle in (top.Name or "").lower():
                return top
        except Exception:
            continue
    return None


# ───────────────────────────── операции ─────────────────────────────

def _capture(target: str) -> CaptureResult:
    auto.SetGlobalSearchTimeout(SEARCH_TIMEOUT)
    win = _find_window(target)
    if win is None:
        return CaptureResult(
            ok=False, target=target,
            error=f"окно с заголовком, содержащим '{target}', не найдено",
        )
    _registry.clear()
    elements: list[Element] = []
    lines: list[str] = []

    def walk(ctrl: auto.Control, depth: int) -> None:
        if depth > MAX_DEPTH or len(elements) >= MAX_ELEMENTS:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                role = _role(child)
                name = (child.Name or "").strip()
                val = _value(child)
                label = name or (val or "")
                if label:
                    lines.append("  " * depth + f"[{role}] {label}")
                if role in _INTERACTIVE and len(elements) < MAX_ELEMENTS:
                    elements.append(_register(child, role))
            except Exception:
                pass
            walk(child, depth + 1)

    walk(win, 0)
    return CaptureResult(
        ok=True, target=(win.Name or target), method_used=Backend.UIA,
        elements=elements, text="\n".join(lines),
    )


def _search(query: str, target: str) -> auto.Control | None:
    """Первый интерактивный элемент, чьё имя/значение содержит query."""
    auto.SetGlobalSearchTimeout(SEARCH_TIMEOUT)
    win = _find_window(target)
    if win is None:
        return None
    needle = query.lower()
    found: list[auto.Control] = []

    def walk(ctrl: auto.Control, depth: int) -> None:
        if depth > MAX_DEPTH or found:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                text = ((child.Name or "") + " " + (_value(child) or "")).lower()
                if needle in text and _role(child) in _INTERACTIVE:
                    found.append(child)
                    return
            except Exception:
                pass
            walk(child, depth + 1)
            if found:
                return

    walk(win, 0)
    return found[0] if found else None


def _find(query: str, target: str) -> FindResult:
    ctrl = _search(query, target)
    if ctrl is None:
        return FindResult(ok=False, error=f"элемент '{query}' не найден")
    return FindResult(ok=True, element=_register(ctrl, _role(ctrl)))


def _wait_for(query: str, target: str, timeout_s: float) -> FindResult:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = _find(query, target)
        if res.ok:
            return res
        time.sleep(0.4)
    return FindResult(ok=False, error=f"'{query}' не появился за {timeout_s} с")


def _act(element_id: str, action: str, text: str, value: str) -> ActResult:
    ctrl = _registry.get(element_id)
    if ctrl is None:
        return ActResult(
            ok=False, element_id=element_id, action=action,
            error="element_id неизвестен — сделай capture()/find() заново",
        )
    try:
        if action == "click":
            ip = ctrl.GetInvokePattern()
            if ip is not None:
                ip.Invoke()
            else:
                ctrl.Click(waitTime=0)
        elif action == "double_click":
            ctrl.DoubleClick(waitTime=0)
        elif action == "focus":
            ctrl.SetFocus()
        elif action == "type":
            ctrl.SetFocus()
            ctrl.SendKeys(text, waitTime=0)
        elif action == "set_value":
            vp = ctrl.GetValuePattern()
            if vp is None:
                return ActResult(ok=False, element_id=element_id, action=action,
                                 error="элемент не поддерживает set_value")
            vp.SetValue(value)
        elif action == "read":
            return ActResult(ok=True, element_id=element_id, action="read",
                             content=_text_content(ctrl), new_state=_state(ctrl))
        elif action == "scroll":
            sp = ctrl.GetScrollPattern()
            if sp is not None:
                sp.Scroll(auto.ScrollAmount.NoAmount, auto.ScrollAmount.LargeIncrement)
        else:
            return ActResult(ok=False, element_id=element_id, action=action,
                             error=f"неизвестное действие '{action}'")
        return ActResult(ok=True, element_id=element_id, action=action,
                         new_state=_state(ctrl))
    except Exception as exc:
        return ActResult(ok=False, element_id=element_id, action=action,
                         error=f"{type(exc).__name__}: {exc}")


# ──────────────────── публичный API (потокобезопасный) ────────────────────

def capture(target: str) -> CaptureResult:
    return _run(_capture, target)


# Помощники для координатных бэкендов (OCR): окно и мышь/клавиатура в COM-потоке.

def _window_rect(target: str):
    win = _find_window(target)
    if win is None:
        return None
    return _rect(win), (win.Name or target)


def window_rect(target: str):
    return _run(_window_rect, target)


def _click_xy(x: int, y: int, double: bool = False) -> None:
    if double:
        auto.Click(x, y, waitTime=0)
        auto.Click(x, y, waitTime=0)
    else:
        auto.Click(x, y, waitTime=0)


def click_xy(x: int, y: int, double: bool = False) -> None:
    _run(_click_xy, x, y, double)


def _send_text(text: str) -> None:
    auto.SendKeys(text, waitTime=0)


def send_text(text: str) -> None:
    _run(_send_text, text)


def find(query: str, target: str) -> FindResult:
    return _run(_find, query, target)


def wait_for(query: str, target: str, timeout_s: float) -> FindResult:
    return _run(_wait_for, query, target, timeout_s)


def act(element_id: str, action: str, text: str, value: str) -> ActResult:
    return _run(_act, element_id, action, text, value)
