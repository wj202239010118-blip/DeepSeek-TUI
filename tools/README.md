# DeepSeek TUI — Tools

Bundled companion tools that extend DeepSeek TUI's capabilities.

## Overview

| Tool | Language | Purpose |
|------|----------|---------|
| `page-agent-bridge/` | Node.js | Browser control via Chrome extension (MCP) |
| `wx-bot/` | Python | WeChat automation with anti-detection |
| `screenshot-sentinel/` | Python / Node.js | Auto-save screenshots, clipboard → file path |

---

## page-agent-bridge

HTTP bridge that lets DeepSeek TUI control a Chrome browser through the
[Page Agent](https://github.com/alibaba/page-agent) extension.

### Quick Start

```bash
cd tools/page-agent-bridge
npm install
node port-manager.js &   # background
node deepseek-bridge.js   # foreground
```

Or double-click `start-bridge.bat` on Windows.

### API

Once running, the bridge listens on `http://127.0.0.1:38406`:

```
POST /execute  {"tool":"browser_open_tab", "args":{"url":"https://..."}}
POST /execute  {"tool":"browser_get_map", "args":{}}
POST /execute  {"tool":"browser_click", "args":{"index":3}}
POST /execute  {"tool":"browser_type", "args":{"index":5, "text":"hello"}}
POST /execute  {"tool":"browser_scroll", "args":{"down":true, "numPages":1}}
GET  /health
POST /stop
```

### Requirements

- Node.js 20+
- Page Agent Chrome extension installed and active
- Chrome browser with the extension hub connected

---

## wx-bot

WeChat automation bot with anti-detection safety layer.

### Quick Start

```bash
cd tools/wx-bot
cp config.example.json config.json   # edit wx_cli.exe_path
pip install -r requirements.txt
python run.py --test                 # verify
python run.py                        # start loop
```

Or double-click `start-wx-bot.bat`.

### Features

- **Orchestrator**: Poll wx-cli daemon, make decisions, execute actions
- **Safety Layer**: Bézier mouse curves, human-like delays, night sleep simulator
- **Actions**: Post Moments, send messages
- **Template Engine**: Message variation (synonyms, emojis, tone)

### Safety Design

- Mouse: Bézier trajectory with random waypoints and overshoot
- Timing: Randomized action intervals, typing delays, think time
- Sleep: Configurable night mode (auto-pause during sleep hours)
- Limits: Daily caps on moments and messages, cooldown periods

---

## screenshot-sentinel

Watches for new screenshots and copies the file path to clipboard.

Two implementations:
- **Node.js** (`media-bridge.js`): Folder watcher, auto-GC
- **Python** (`feishu_screenshot_guard.py`): Hotkey listener + clipboard monitor

### Quick Start (Node.js)

```bash
cd tools/screenshot-sentinel
npm install
node media-bridge.js --dir ./screenshots
```

### Quick Start (Python)

```bash
cd tools/screenshot-sentinel
pip install -r requirements.txt
python feishu_screenshot_guard.py --dir ./feishu_uploads
```

Or double-click `start-sentinel.bat`.

### Usage Pattern

1. Take a screenshot (e.g. Ctrl+Shift+A in Feishu/Lark)
2. The tool saves it and replaces clipboard content with the file path
3. Paste (Ctrl+V) anywhere to get the path string

### Options

**Node.js version:**
- `--dir PATH` — Watch directory
- `--max N` — Max files to keep (default: 15)
- `--ext .png,.jpg` — File extensions to watch
- `--path relative|absolute` — Path format
- `--style win|posix|native` — Path separator style
- `--quiet` — Less output

**Python version:**
- `--dir PATH` — Save directory
- `--max N` — Max files to keep (default: 5)
- `--hotkey KEY` — Global hotkey (default: `<ctrl>+<shift>+a`)
- `--timeout N` — Standby timeout seconds (default: 15)
- `--prefix NAME` — Filename prefix (default: feishu)

---

## Memory / Footprint Notes

These tools are designed to be lean:

- **page-agent-bridge**: ~50KB source, ~2MB node_modules (three deps). Runs a persistent Node.js child process (~30MB RSS).
- **wx-bot**: ~35KB source, ~5MB Python deps. Only consumes memory when active.
- **screenshot-sentinel**: ~10KB source each, <2MB deps. Minimal runtime footprint.

All tools are opt-in — they don't load unless explicitly started.
