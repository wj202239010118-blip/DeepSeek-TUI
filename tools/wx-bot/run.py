#!/usr/bin/env python
"""wx-bot — WeChat automation bot with anti-detection safety layer.

Usage:
    python run.py                  # Start orchestrator loop
    python run.py --once           # Run one poll cycle and exit
    python run.py --test           # Test safety modules (no WeChat needed)
    python run.py --post "text"    # Post a Moment directly
    python run.py --send "chat" "msg"  # Send a message directly
"""

import sys
import argparse
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from wx_bot.orchestrator import Orchestrator
from wx_bot.actions import MomentsPoster, MessageSender


def _safe_print(*args, **kwargs):
    """Print safely on Windows (handle GBK encoding issues)."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
        print(*safe_args, **kwargs)


def cmd_test():
    """Test safety modules without WeChat interaction."""
    _safe_print("=" * 60)
    _safe_print("wx-bot Safety Module Test")
    _safe_print("=" * 60)

    from wx_bot.config import get_config
    from wx_bot.anti_detect import TemplateEngine, DelayManager

    cfg = get_config()
    _safe_print(f"\nConfig loaded: {Path(__file__).parent / 'config.json'}")
    _safe_print(f"  Mouse: Bezier {cfg.anti_detect.mouse.bezier_waypoints} waypoints, "
                f"speed {cfg.anti_detect.mouse.speed_min}-{cfg.anti_detect.mouse.speed_max}")
    _safe_print(f"  Window: focus {cfg.anti_detect.window.focus_delay_ms}ms, "
                f"post-click {cfg.anti_detect.window.post_click_pause_ms}ms")
    _safe_print(f"  Delay: action {cfg.anti_detect.delay.action_interval_ms}ms, "
                f"think {cfg.anti_detect.delay.think_time_ms}ms")
    _safe_print(f"  Sleep: {'ON' if cfg.anti_detect.sleep.enabled else 'OFF'} "
                f"({cfg.anti_detect.sleep.night_start}-{cfg.anti_detect.sleep.night_end})")
    _safe_print(f"  Template: synonym={cfg.anti_detect.template.synonym_rate}, "
                f"emoji={cfg.anti_detect.template.emoji_rate}")
    _safe_print(f"  Safety: {cfg.safety.max_daily_moments} moments/day, "
                f"{cfg.safety.max_daily_messages} msgs/day")

    # Test template engine
    _safe_print("\n--- Template Engine ---")
    tpl = TemplateEngine()
    test_text = "好的，没问题，辛苦了"
    for tone in ["casual", "enthusiastic", "neutral"]:
        variants = tpl.generate_variants(test_text, count=3, tone=tone)
        _safe_print(f"  [{tone}] {test_text}")
        for v in variants:
            _safe_print(f"    -> {v}")

    # Test delay manager (no actual sleep)
    delay = DelayManager()
    delays = [delay.typing_delay() for _ in range(10)]
    avg_delay = sum(delays) / len(delays)
    _safe_print(f"\n--- Delay Manager ---")
    _safe_print(f"  Typing delays (10 samples): {[f'{d:.3f}s' for d in delays]}")
    _safe_print(f"  Average: {avg_delay:.3f}s")

    _safe_print("\n[OK] All safety modules loaded successfully")
    _safe_print("  (Mouse/Window modules require WeChat to test)")


def cmd_post(text: str):
    """Post a Moment directly."""
    poster = MomentsPoster()
    poster.post_text(text)


def cmd_send(chat: str, message: str):
    """Send a message directly."""
    sender = MessageSender()
    sender.send_to(chat, message)


def main():
    parser = argparse.ArgumentParser(
        description="wx-bot — WeChat automation with anti-detection"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run one poll cycle and exit"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test safety modules (no WeChat needed)"
    )
    parser.add_argument(
        "--post", type=str, metavar="TEXT",
        help="Post a text Moment directly"
    )
    parser.add_argument(
        "--send", nargs=2, metavar=("CHAT", "MSG"),
        help="Send a message to a chat"
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Poll interval in seconds (default: 300)"
    )

    args = parser.parse_args()

    if args.test:
        cmd_test()
    elif args.post:
        cmd_post(args.post)
    elif args.send:
        cmd_send(args.send[0], args.send[1])
    elif args.once:
        orch = Orchestrator()
        result = orch.run_once()
        print(result)
    else:
        orch = Orchestrator()
        orch.run_loop(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
