# wx-bot

WeChat automation bot with anti-detection safety layer for Windows.

## Architecture

```
wx-cli (Rust daemon)  ←→  Orchestrator  →  Actions (Moments / Message)
                                ↓
                          Safety Layer
                 (mouse / window / delay / sleep / template)
```

- **wx-cli** — Reads WeChat local database (sessions, contacts, messages, Moments)
- **Orchestrator** — Polls wx-cli for new data, makes decisions, executes actions
- **Safety Layer** — Makes automation look human:
  - Bézier curve mouse trajectories
  - Random window focus delays
  - Human-like typing speed
  - Night sleep simulator
  - Content template randomization

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Test safety modules (no WeChat needed)
python run.py --test

# Start the orchestrator loop
python run.py

# One-time actions
python run.py --post "Hello 朋友圈!"
python run.py --send "张三" "你好，在吗？"
```

## Configuration

Edit `config.json` to customize:

- `anti_detect.mouse` — Mouse movement behavior
- `anti_detect.sleep` — Night mode hours
- `anti_detect.template` — Message randomization rates
- `safety` — Daily limits and cooldowns

## Requirements

- Windows 10/11
- WeChat Desktop 4.x logged in
- wx-cli installed and initialized
- Python 3.10+

## Safety First

This tool is designed to **reduce detection risk**, not eliminate it.
Always operate within WeChat's terms of service.
Never use for spam, harassment, or illegal activities.

## License

Part of DeepSeek TUI tools suite.
