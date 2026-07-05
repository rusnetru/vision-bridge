# vision-bridge

**One vision layer for AI agents on Windows — a single MCP server that lets any
agent see and act on the screen: native desktop apps, Electron/Chromium windows,
and the browser — undetected.**

Most agent setups end up with a pile of disconnected tools: one for the browser,
one for native windows, one for OCR, each with its own quirks. `vision-bridge`
hides all of that behind **four verbs** — `capture`, `act`, `find`, `wait_for` —
so the agent asks *"what's on screen?"* and *"click this"* the same way
everywhere. The router picks the right backend underneath.

It is designed for **text-only brains too** (e.g. DeepSeek, local LLMs): the screen
is returned as **structured text**, not pixels, so an agent that can't consume
images can still understand and drive the UI.

- 🖥️ **Desktop** — native Win32/WPF/UWP via UI Automation (fast, exact,
  coordinate-free clicks).
- 🧩 **Electron/Chromium** — OCR fallback when the a11y tree is blind.
- 🌐 **Browser, undetected** — drive your **real Chrome over CDP** (live cookies,
  sessions never drop) *or* a **stealth browser** (patchright, persistent profile,
  `navigator.webdriver = false`).
- 🔌 **Standard MCP** — stdio transport, works with Claude Desktop, Cline, Cursor,
  or any custom agent, no code changes.

> Deep-dive design & rationale (RU): [`docs/01_architecture.md`](docs/01_architecture.md)

---

## Why (for humans)

An agent that "sees the screen" usually means gluing Playwright + some UIA library
+ Tesseract together and teaching the model three different mental models. This
project makes that **one contract**. Add a backend, keep the same four tools. The
agent never learns "how" — only "what".

## Why (for agents)

If you are an LLM agent reading this to use the server: call `capture(target)` to
get a list of `Element`s (each with a stable `id`) plus a flat `text` dump of the
screen. Then call `act(element_id, action, ...)`. You never compute coordinates or
CSS selectors — you address elements by the `id` from the last `capture`/`find`.
`id` prefixes tell you the backend (`u`=desktop, `o`=OCR, `b`=browser); the server
routes automatically.

---

## Tools

| Tool | Purpose |
|---|---|
| `capture(target, mode="auto")` | Screen of a target → `{ok, elements[], text, method_used}` |
| `act(element_id, action, text="", value="")` | `click` / `double_click` / `type` / `set_value` / `focus` / `read` / `scroll` |
| `find(query, target="", mode="auto")` | Locate one element by name/value |
| `wait_for(query, target="", timeout_s=10, mode="auto")` | Poll until an element appears |
| `browser_open(mode, url, cdp_url, user_data_dir, channel, headless)` | Connect/launch a browser |
| `browser_goto(url)` | Navigate the open browser |
| `browser_close()` | Close the browser session |

`target`: a window title **substring** for desktop, or `"browser"` for the page.
Empty `target` = foreground window. `mode`: `auto` \| `uia` \| `ocr` \| `browser`.

### `Element`
```jsonc
{
  "id": "u17",                 // stable ref; prefix = backend (u/o/b)
  "role": "button",            // button | textbox | link | text | ...
  "name": "OK",
  "value": null,
  "bbox": [120, 80, 60, 24],   // screen coords [x, y, w, h]
  "state": { "enabled": true, "focused": false, "visible": true, "checked": null },
  "backend": "uia"
}
```

---

## Install

```bash
uv sync                      # core: MCP + pydantic
uv sync --extra desktop      # UIA + OCR (uiautomation, pytesseract, mss)
uv sync --extra browser      # stealth/CDP browser (patchright)
```

OCR needs the **Tesseract-OCR binary** (not the pip package): install it (e.g.
`winget install UB-Mannheim.TesseractOCR`) and, for non-English screens, add the
matching `*.traineddata` to `tessdata`.

## Run

```bash
uv run vision-bridge                          # stdio server
uv run mcp dev src/vision_bridge/server.py    # MCP Inspector
```

## Connect to an agent

Any MCP client with a `command`/`args` config:

```json
{
  "servers": {
    "vision-bridge": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/vision-bridge", "vision-bridge"]
    }
  }
}
```

## Examples

**Desktop:**
```python
capture("Notepad")                      # → elements + text of the window
act("u0", "type", text="hello world")   # type into the document
act("u0", "read")                       # → { content: "hello world" }
```

**Browser, undetected — real Chrome (max stealth, keeps your sessions):**
```bash
# start Chrome with a debug port and your profile first:
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\path\profile"
```
```python
browser_open(mode="cdp", cdp_url="http://localhost:9222")
capture("browser")
act("b3", "type", text="search query")
```

**Browser — standalone stealth profile:**
```python
browser_open(mode="stealth", url="https://example.com",
             user_data_dir="C:\\path\\profile")   # navigator.webdriver = false
```

---

## How routing works

```
              capture(target, mode="auto")
                        │
   target=="browser" ───┼─── desktop window ───────────────┐
        │               │                                  │
   ┌────▼────┐    UI Automation a11y tree            (few elements? →)
   │ browser │    ┌──────────────┐                   ┌──────────────┐
   │ cdp /   │    │     UIA       │  ── fallback ──▶  │  OCR (Tess.) │
   │ stealth │    └──────────────┘                   └──────────────┘
   └─────────┘
```

## Status & limits

Stages 0–3 implemented and tested live on real apps (Notepad, Chrome). Roadmap:
agent skill + scenario tests, optional OmniParser for clickable boxes instead of
plain OCR text.

- Stealth is **not** 100% undetectable (Cloudflare/DataDome evolve) — prefer
  `mode="cdp"` against real Chrome for maximum stealth and session persistence.
- Console output with non-ASCII: run under `PYTHONUTF8=1` (does not affect the
  UTF-8 MCP protocol).

## License

MIT — see [`LICENSE`](LICENSE).

---

### Кратко (RU)

Единый слой зрения для AI-агентов на Windows как **один MCP-сервер**. Четыре
глагола — `capture`, `act`, `find`, `wait_for` — работают одинаково для нативных
окон, Electron/Chromium (через OCR) и браузера. Экран отдаётся **текстом**, поэтому
подходит даже текстовым моделям (DeepSeek и др.). Браузер — незаметно: реальный
Chrome по CDP (живые куки, сессии не рвутся) или стелс-браузер на patchright
(`navigator.webdriver=false`). Архитектура и план — в
[`docs/01_architecture.md`](docs/01_architecture.md).
