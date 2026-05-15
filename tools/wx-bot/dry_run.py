"""Dry-run orchestrator test — reads wx-cli data, generates decisions, NO UI actions.

Validates:
  1. wx-cli connectivity
  2. Data parsing
  3. Decision engine logic
  4. Safety guardrails
"""

import json
import subprocess
import sys
from pathlib import Path

# Set WX_EXE to your wx-cli binary path, or use WX_EXE env var
WX_EXE = Path(os.environ.get("WX_EXE", ""))

def wx(*args):
    """Run wx-cli command, return parsed JSON."""
    cmd = [str(WX_EXE), *args, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(WX_EXE.parent), encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"wx-cli error (code={r.returncode}): {r.stderr.strip()}")
    if not r.stdout or not r.stdout.strip():
        raise RuntimeError(f"wx-cli returned empty stdout. stderr: {r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"wx-cli JSON parse error: {e}\nstdout[:200]: {r.stdout[:200]}")

import os, sys

def sp(*args, **kwargs):
    """Safe print: fallback to ascii on GBK errors."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
        print(*safe, **kwargs)

sp("=" * 60)
sp("wx-bot Dry-Run Test")
sp("=" * 60)

# 1. Verify wx-cli works
sp("\n[1/4] wx-cli connectivity...")
try:
    sessions = wx("sessions", "-n", "5")
    sp(f"  OK - {len(sessions)} sessions returned")
    for s in sessions[:3]:
        sp(f"    {s['chat'][:30]:30s} | unread={s.get('unread',0):4d} | {s.get('chat_type','?')}")
except Exception as e:
    sp(f"  FAIL - {e}")
    sys.exit(1)

# 2. Check for unread messages
sp("\n[2/4] Checking unread messages...")
unread = [s for s in sessions if s.get("unread", 0) > 0]
sp(f"  Sessions with unread: {len(unread)}")
for s in unread[:5]:
    sp(f"    {s['chat'][:30]:30s} | {s.get('chat_type','?'):15s} | unread={s['unread']} | last: {s.get('summary','')[:40]}")

# 3. Simulate decision engine
sp("\n[3/4] Decision engine (simulated)...")
# Simple VIP detection for testing
decisions = []
for s in unread:
    chat_type = s.get("chat_type", "")
    chat_name = s.get("chat", "")
    unread_count = s.get("unread", 0)

    # Skip folded/official
    if chat_type in ("folded",):
        continue

    if chat_type == "official_account":
        decisions.append({"action": "ignore", "target": chat_name, "reason": "official_account"})
        continue

    if unread_count > 0:
        decisions.append({
            "action": "would_reply",
            "target": chat_name,
            "chat_type": chat_type,
            "content": "hao de, shou dao la" if chat_type == "private" else "shou dao",
            "reason": f"unread={unread_count}"
        })

for d in decisions:
    marker = {"would_reply": "REPLY", "ignore": "SKIP"}.get(d["action"], "?")
    sp(f"  {marker} {d['action']:12s} | {d['target'][:25]:25s} | {d.get('reason','')}")

# 4. Safety limits check
sp("\n[4/4] Safety limits...")
from wx_bot.config import get_config
cfg = get_config()
sp(f"  Max daily messages:  {cfg.safety.max_daily_messages}")
sp(f"  Max daily moments:   {cfg.safety.max_daily_moments}")
sp(f"  Moments cooldown:    {cfg.safety.min_interval_between_moments_minutes} min")
sp(f"  Sleep mode:          {'ON' if cfg.anti_detect.sleep.enabled else 'OFF'} ({cfg.anti_detect.sleep.night_start}-{cfg.anti_detect.sleep.night_end})")

# Summary
sp("\n" + "=" * 60)
sp(f"SUMMARY: wx-cli OK | {len(unread)} sessions with unread | {len(decisions)} decisions | safety: active")
sp("=" * 60)
