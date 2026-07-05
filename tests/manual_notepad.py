"""Ручной прогон UIA-бэкенда на реальном Блокноте.

Запуск: uv run python tests/manual_notepad.py
Открывает Notepad, делает capture, находит поле ввода, печатает текст, читает.
"""

import subprocess
import sys
import time

from vision_bridge.backends import uia


def dump(title, obj):
    print(f"\n=== {title} ===")
    print(obj.model_dump_json(indent=2, exclude={"elements"}) if hasattr(obj, "elements")
          else obj.model_dump_json(indent=2))


def main() -> int:
    subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)

    # Заголовок нового Блокнота отличается по локали — пробуем оба.
    target = ""
    for cand in ("Notepad", "Блокнот", "Untitled", "Безымян"):
        cap = uia.capture(cand)
        if cap.ok:
            target = cand
            break
    else:
        print("Окно Блокнота не найдено. capture(''):")
        cap = uia.capture("")

    print(f"\ncapture target='{target}' ok={cap.ok} method={cap.method_used} "
          f"elements={len(cap.elements)}")
    print("--- text dump (первые 40 строк) ---")
    print("\n".join(cap.text.splitlines()[:40]))
    print("--- interactive elements ---")
    for el in cap.elements[:25]:
        print(f"  {el.id:>4} [{el.role}] {el.name!r} bbox={el.bbox} "
              f"enabled={el.state.enabled}")

    # Ищем редактируемое поле документа и печатаем.
    edit = None
    for el in cap.elements:
        if el.role in ("document", "textbox"):
            edit = el
            break
    if edit is None:
        f = uia.find("Text editor", target) or uia.find("Text Editor", target)
        edit = f.element if f and f.ok else None

    if edit is not None:
        print(f"\nПечатаю в {edit.id} [{edit.role}]…")
        r = uia.act(edit.id, "type", "vision-bridge Этап 1 работает", "")
        print("act(type):", r.model_dump_json())
        time.sleep(0.5)
        rd = uia.act(edit.id, "read", "", "")
        print("act(read):", rd.model_dump_json())
    else:
        print("\nРедактируемое поле не найдено среди элементов.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
