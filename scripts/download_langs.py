"""Скачать языковые модели Tesseract в локальную папку tessdata/.

Не требует прав на C:\\Program Files — модели кладутся рядом с проектом и
подхватываются OCR-бэкендом через --tessdata-dir. Скачивает и eng, и rus, чтобы
работал распознаватель `rus+eng`.

Использование:
    uv run python scripts/download_langs.py            # rus eng (по умолчанию)
    uv run python scripts/download_langs.py rus eng deu
    uv run python scripts/download_langs.py --best rus  # модели tessdata_best

По умолчанию берётся ветка `main` репозитория tesseract-ocr/tessdata (баланс
скорость/качество). Флаг --best — из tessdata_best (точнее, крупнее, медленнее).
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "tessdata"
BASE = "https://github.com/tesseract-ocr/{repo}/raw/main/{lang}.traineddata"


def download(lang: str, best: bool) -> None:
    repo = "tessdata_best" if best else "tessdata"
    url = BASE.format(repo=repo, lang=lang)
    out = DEST / f"{lang}.traineddata"
    print(f"→ {lang}: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vision-bridge"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out, "wb") as f:
        f.write(resp.read())
    print(f"  saved {out} ({out.stat().st_size // 1024} KiB)")


def main(argv: list[str]) -> int:
    best = "--best" in argv
    langs = [a for a in argv if not a.startswith("--")] or ["rus", "eng"]
    DEST.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        try:
            download(lang, best)
        except Exception as exc:  # noqa: BLE001
            print(f"  ОШИБКА для '{lang}': {type(exc).__name__}: {exc}")
            return 1
    print(f"\nГотово. Модели в {DEST}. OCR-бэкенд подхватит их автоматически.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
