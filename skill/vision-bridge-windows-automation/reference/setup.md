# Setup

Requirements: Windows 10/11, Python 3.11+, [uv](https://docs.astral.sh/uv/).

## 1. Install the server

```bash
git clone https://github.com/rusnetru/vision-bridge.git
cd vision-bridge
uv sync --extra desktop      # UI Automation + OCR (uiautomation, pytesseract, mss)
uv sync --extra browser      # optional: browser backend (patchright)
```

OCR needs the Tesseract binary (not only the pip package):

```bash
winget install UB-Mannheim.TesseractOCR
uv run python scripts/download_langs.py          # Russian + English models into ./tessdata
uv run python scripts/download_langs.py deu fra  # any other Tesseract languages
```

A custom models folder can be set with `VISION_BRIDGE_TESSDATA`.

## 2. Connect it to the agent

Stdio MCP server. Replace the path with where you cloned the repo.

Claude Code:
```bash
claude mcp add vision-bridge -- uv run --directory C:\path\to\vision-bridge vision-bridge
```

Claude Desktop / Cursor / Cline / any client with `command` + `args`:
```json
{
  "mcpServers": {
    "vision-bridge": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\vision-bridge", "vision-bridge"]
    }
  }
}
```

Restart the client, then check that the tools `capture`, `act`, `find`, `wait_for`,
`browser_open`, `browser_goto`, `browser_close` are listed.

Debug with the MCP Inspector: `uv run mcp dev src/vision_bridge/server.py`.

## 3. Browser via your own Chrome (CDP)

Close Chrome, then start it with a debug port and a profile folder:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\path\to\profile"
```

The agent then calls `browser_open(mode="cdp", cdp_url="http://localhost:9222")`.
Keep the port bound to localhost; anyone who can reach it controls that browser.
