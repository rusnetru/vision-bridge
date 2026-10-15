# Tool reference

## capture(target, mode="auto")
Returns `{ok, target, elements[], text, method_used, error?}`.
- `target`: window title substring (case-insensitive), `""` = foreground window, `"browser"` = open page.
- `mode`: `auto` (UIA, OCR fallback if fewer than 2 elements) | `uia` | `ocr` | `browser`.
- `text`: flat dump of the screen - read this first.

## act(element_id, action, text="", value="")
- `action`: `click` | `double_click` | `type` (uses `text`) | `set_value` (uses `value`,
  replaces content) | `focus` | `read` (returns `content`) | `scroll` (into view).
- Returns `{ok: true}`, `{ok: true, content}` for `read`, or `{ok: false, error}`.

## find(query, target="", mode="auto")
Locate one element whose name or value contains `query` (case-insensitive).
Returns `{ok, element}`. In `auto` mode falls back to OCR if UIA finds nothing.

## wait_for(query, target="", timeout_s=10, mode="auto")
Polls like `find` until the element appears. Returns `{ok, element}` or
`{ok: false, error: "timeout after Ns"}`.

## browser_open(mode="stealth", url="", cdp_url="", user_data_dir="", channel="chrome", headless=False)
- `mode="cdp"`: attach to an already running Chrome (default `http://localhost:9222`).
- `mode="stealth"`: launch Chrome with a persistent profile at `user_data_dir`.
- `url`: navigate right away.

## browser_goto(url)
Navigate the open session. Then `capture("browser")`.

## browser_close()
Close the session. No-op if none is open.

## Element
```jsonc
{
  "id": "u17",                 // u = UIA, o = OCR, b = browser
  "role": "button",            // button | textbox | link | text | ...
  "name": "OK",
  "value": null,
  "bbox": [120, 80, 60, 24],   // x, y, w, h (screen coordinates, informational)
  "state": { "enabled": true, "focused": false, "visible": true, "checked": null },
  "backend": "uia"
}
```
