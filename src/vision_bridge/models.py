"""Единый контракт слоя зрения — модели данных.

Всё, что слой отдаёт агенту, — строго JSON-сериализуемо. Мозг агента может быть
текстовым (напр. DeepSeek), поэтому экран описывается текстом/структурой, а не
пикселями.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Backend(str, Enum):
    """Каким механизмом получен/управляется элемент."""

    UIA = "uia"            # Windows UI Automation (a11y-дерево)
    CDP = "cdp"            # реальный Chrome по Chrome DevTools Protocol
    PLAYWRIGHT = "playwright"  # отдельный стелс-браузер (patchright)
    OCR = "ocr"            # скриншот → OCR/детектор (для a11y-слепых окон)


class ElementState(BaseModel):
    enabled: bool = True
    focused: bool = False
    visible: bool = True
    checked: bool | None = None


class Element(BaseModel):
    """Единая модель элемента экрана. Несёт всё, чтобы по нему действовать."""

    id: str = Field(..., description="Стабильная ссылка для агента, напр. 'e17'")
    role: str = Field(..., description="button | textbox | link | text | image | ...")
    name: str = Field("", description="Видимый текст / accessible name")
    value: str | None = Field(None, description="Текущее значение (для полей ввода)")
    bbox: tuple[int, int, int, int] = Field(
        (0, 0, 0, 0), description="Экранные координаты [x, y, w, h]"
    )
    state: ElementState = Field(default_factory=ElementState)
    backend: Backend = Field(..., description="Механизм, которым управляется элемент")
    # Внутренний локатор бэкенда (AutomationId, @ref, селектор…). Агенту не нужен —
    # он адресует элемент по `id`; слой хранит соответствие id → locator.
    locator: Any = Field(None, exclude=True)


class CaptureResult(BaseModel):
    """Результат capture() — полная текстовая картина цели."""

    ok: bool = True
    target: str
    method_used: Backend | None = None
    elements: list[Element] = Field(default_factory=list)
    text: str = Field("", description="Плоский текстовый дамп экрана для чтения")
    error: str | None = None


class ActResult(BaseModel):
    ok: bool
    element_id: str
    action: str
    content: str | None = Field(None, description="Текст элемента для action='read'")
    new_state: ElementState | None = None
    error: str | None = None


class FindResult(BaseModel):
    ok: bool
    element: Element | None = None
    error: str | None = None
