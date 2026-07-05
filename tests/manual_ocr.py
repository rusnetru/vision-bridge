"""Ручной прогон OCR-бэкенда (Этап 2).

Открывает Блокнот, печатает английский текст через UIA, затем читает окно через
OCR (mode форсируем принудительно) и проверяет, что текст распознан.
Запуск: uv run python tests/manual_ocr.py
"""

import subprocess
import sys
import time

from vision_bridge.backends import ocr, uia

MARKER = "VisionBridge OCR fallback works 12345"


def main() -> int:
    subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)

    target = ""
    for cand in ("Notepad", "Блокнот", "Untitled", "Безымян"):
        cap = uia.capture(cand)
        if cap.ok:
            target = cand
            break
    if not target:
        print("Блокнот не найден"); return 1

    doc = next((e for e in cap.elements if e.role in ("document", "textbox")), None)
    if doc is None:
        print("Поле документа не найдено"); return 1
    uia.act(doc.id, "type", MARKER, "")
    time.sleep(0.6)

    print("Tesseract langs:", ocr._lang() if ocr._tesseract_ok() is None else "N/A")
    res = ocr.capture(target)
    print(f"ocr.capture ok={res.ok} method={res.method_used} elements={len(res.elements)}")
    if res.error:
        print("error:", res.error); return 1
    print("--- OCR text (первые 15 строк) ---")
    print("\n".join(res.text.splitlines()[:15]))

    # Проверяем, что маркер (или его заметная часть) распознан.
    joined = res.text.replace("\n", " ")
    hit = "VisionBridge" in joined or "12345" in joined or "works" in joined
    print(f"\nМаркер распознан: {hit}")
    return 0 if hit else 2


if __name__ == "__main__":
    sys.exit(main())
