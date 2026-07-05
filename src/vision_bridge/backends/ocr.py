"""OCR-бэкенд (Этап 2) — резервное зрение для окон, слепых для UIA.

Electron/Chromium-приложения (Slack, Discord, VS Code) часто не отдают дерево
через UI Automation. Здесь: скриншот окна → Tesseract → текст со словами и их
экранными координатами. Клик/ввод — по координатам (мышь + клавиатура), через
COM-поток UIA-бэкенда, чтобы не плодить потоки.

Требует установленный бинарник Tesseract-OCR (не pip-пакет). Если его нет —
capture отдаёт понятную ошибку с подсказкой, не роняя сервер.
"""

from __future__ import annotations

import os
import time

from ..models import (
    ActResult,
    Backend,
    CaptureResult,
    Element,
    ElementState,
    FindResult,
)
from . import uia

PREFIX = "o"  # id элементов: o0, o1, …
DESIRED_LANGS = ("rus", "eng")  # берём те, что реально установлены
MIN_CONF = 40  # порог уверенности Tesseract

# Типичные места установки бинарника (UB-Mannheim), если его нет в PATH.
_COMMON_EXE = (
    os.environ.get("VISION_BRIDGE_TESSERACT", ""),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
_lang_cache: str | None = None


def _configure() -> None:
    """Указать pytesseract на бинарник, если он не в PATH."""
    import pytesseract

    cur = pytesseract.pytesseract.tesseract_cmd
    from shutil import which

    if which(cur):
        return
    for cand in _COMMON_EXE:
        if cand and os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            return


def _lang() -> str:
    """Строка языков из реально установленных traineddata (rus+eng / eng / …)."""
    global _lang_cache
    if _lang_cache is not None:
        return _lang_cache
    import pytesseract

    try:
        have = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001
        have = set()
    picked = [ln for ln in DESIRED_LANGS if ln in have] or ["eng"]
    _lang_cache = "+".join(picked)
    return _lang_cache

# id → {"bbox": (x,y,w,h) экранные, "text": str}
_registry: dict[str, dict] = {}
_counter = 0


def _tesseract_ok() -> str | None:
    """None если Tesseract доступен, иначе текст ошибки с подсказкой."""
    try:
        import pytesseract

        _configure()
        pytesseract.get_tesseract_version()
        return None
    except Exception as exc:  # noqa: BLE001
        return (
            f"Tesseract недоступен ({type(exc).__name__}: {exc}). Установи бинарник "
            "Tesseract-OCR (напр. `winget install UB-Mannheim.TesseractOCR`) и/или "
            "укажи pytesseract.pytesseract.tesseract_cmd."
        )


def _grab(bbox: tuple[int, int, int, int]):
    import mss

    x, y, w, h = bbox
    with mss.mss() as sct:
        raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
    from PIL import Image

    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def capture(target: str) -> CaptureResult:
    err = _tesseract_ok()
    if err:
        return CaptureResult(ok=False, target=target, method_used=Backend.OCR, error=err)

    wr = uia.window_rect(target)
    if wr is None:
        return CaptureResult(ok=False, target=target, method_used=Backend.OCR,
                             error=f"окно '{target}' не найдено для OCR")
    (wx, wy, ww, wh), name = wr
    if ww <= 0 or wh <= 0:
        return CaptureResult(ok=False, target=name, method_used=Backend.OCR,
                             error="окно свёрнуто или без площади")

    import pytesseract
    from pytesseract import Output

    img = _grab((wx, wy, ww, wh))
    data = pytesseract.image_to_data(img, lang=_lang(), output_type=Output.DICT)

    _registry.clear()
    global _counter
    elements: list[Element] = []
    # Группируем слова в строки для читаемого текстового дампа.
    lines: dict[tuple, list[str]] = {}
    n = len(data["text"])
    for i in range(n):
        word = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if not word or conf < MIN_CONF:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        # Экранные координаты = координаты в окне + смещение окна.
        bbox = (wx + data["left"][i], wy + data["top"][i],
                data["width"][i], data["height"][i])
        eid = f"{PREFIX}{_counter}"
        _counter += 1
        _registry[eid] = {"bbox": bbox, "text": word}
        elements.append(Element(id=eid, role="text", name=word, bbox=bbox,
                                state=ElementState(), backend=Backend.OCR))

    text = "\n".join(" ".join(ws) for ws in lines.values())
    return CaptureResult(ok=True, target=name, method_used=Backend.OCR,
                         elements=elements, text=text)


def find(query: str, target: str) -> FindResult:
    cap = capture(target)
    if not cap.ok:
        return FindResult(ok=False, error=cap.error)
    needle = query.lower()
    for el in cap.elements:
        if needle in el.name.lower():
            return FindResult(ok=True, element=el)
    return FindResult(ok=False, error=f"текст '{query}' не распознан в окне")


def wait_for(query: str, target: str, timeout_s: float) -> FindResult:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = find(query, target)
        if res.ok:
            return res
        time.sleep(0.5)
    return FindResult(ok=False, error=f"'{query}' не появился за {timeout_s} с")


def act(element_id: str, action: str, text: str, value: str) -> ActResult:
    entry = _registry.get(element_id)
    if entry is None:
        return ActResult(ok=False, element_id=element_id, action=action,
                         error="element_id неизвестен — сделай capture()/find() заново")
    x, y, w, h = entry["bbox"]
    cx, cy = x + w // 2, y + h // 2
    try:
        if action == "click":
            uia.click_xy(cx, cy)
        elif action == "double_click":
            uia.click_xy(cx, cy, double=True)
        elif action == "type":
            uia.click_xy(cx, cy)
            uia.send_text(text)
        elif action == "read":
            return ActResult(ok=True, element_id=element_id, action="read",
                             content=entry["text"])
        else:
            return ActResult(ok=False, element_id=element_id, action=action,
                             error=f"OCR-бэкенд не поддерживает '{action}' "
                                   "(только click/double_click/type/read)")
        return ActResult(ok=True, element_id=element_id, action=action)
    except Exception as exc:  # noqa: BLE001
        return ActResult(ok=False, element_id=element_id, action=action,
                         error=f"{type(exc).__name__}: {exc}")
