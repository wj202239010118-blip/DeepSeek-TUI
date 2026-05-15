"""Orchestrator: wx-cli data → decision engine → safe action execution.

Core loop:
1. Poll wx-cli daemon for new messages / Moments notifications
2. Apply decision rules (should reply? auto-post?)
3. Execute through safety modules → UI automation

Architecture:
    wx-cli (Rust daemon)  ←→  Orchestrator  →  Actions (Moments/Message)
                                    ↓
                              Safety (mouse/window/delay/sleep/template)
"""

import json
import subprocess
import time
import random
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from .config import get_config
from .anti_detect import MouseSimulator, WindowManager, DelayManager, SleepScheduler, TemplateEngine
from .actions import MomentsPoster, MessageSender


@dataclass
class Decision:
    """Result of a decision engine evaluation."""
    action: str  # "reply", "post_moment", "notify", "ignore"
    target: str  # chat name or empty
    content: str  # message to send
    confidence: float  # 0.0 - 1.0
    reason: str


class WxCliClient:
    """Thin wrapper around wx.exe CLI for reading WeChat data."""

    def __init__(self):
        self.cfg = get_config()
        self._exe = Path(self.cfg.wx_cli.exe_path)

    def _run(self, *args: str, json_output: bool = True) -> dict | str:
        """Run a wx-cli command and return parsed output."""
        cmd = [str(self._exe), *args]
        if json_output:
            cmd.append("--json")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self._exe.parent),
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(f"wx-cli error: {result.stderr.strip()}")

        if json_output:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout

        return result.stdout

    def new_messages(self, state: dict | None = None, limit: int = 200) -> dict:
        """Get new messages since last check."""
        args = ["new-messages", "-n", str(limit)]
        if state:
            # Pass state via stdin (wx-cli new-messages accepts JSON state)
            raise NotImplementedError("Stateful new-messages not yet implemented")
        return self._run(*args)

    def sns_notifications(
        self, limit: int = 50, include_read: bool = False
    ) -> list[dict]:
        """Get Moments interaction notifications."""
        args = ["sns-notifications", "-n", str(limit)]
        if include_read:
            args.append("--include-read")
        result = self._run(*args)
        return result if isinstance(result, list) else []

    def sns_feed(
        self, limit: int = 20, user: str | None = None
    ) -> list[dict]:
        """Get Moments timeline."""
        args = ["sns-feed", "-n", str(limit)]
        if user:
            args.extend(["--user", user])
        result = self._run(*args)
        return result if isinstance(result, list) else []

    def sessions(self, limit: int = 20) -> list[dict]:
        """Get recent chat sessions."""
        result = self._run("sessions", "-n", str(limit))
        return result if isinstance(result, list) else []

    def watch(
        self, config_path: str | None = None, once: bool = False
    ) -> subprocess.Popen:
        """Start watch daemon for continuous monitoring."""
        args = ["watch"]
        if config_path:
            args.extend(["-c", config_path])
        if once:
            args.append("--once")
        return subprocess.Popen(
            [str(self._exe), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self._exe.parent),
        )


class DecisionEngine:
    """Decides what actions to take based on wx-cli data.

    Default rules (configurable / extensible):
    - Reply to messages from VIP contacts
    - Post a daily summary Moment
    - Forward urgent messages
    - Ignore system/group messages unless mentioned
    """

    def __init__(self):
        self.cfg = get_config()
        # VIP contacts that auto-reply is enabled for
        self.vip_contacts: set[str] = set()

    def evaluate_new_messages(self, messages: list[dict]) -> list[Decision]:
        """Evaluate new messages and generate reply decisions."""
        decisions = []

        for msg in messages:
            chat = msg.get("chat", "")
            sender = msg.get("last_sender", "")
            chat_type = msg.get("chat_type", "")
            summary = msg.get("summary", "")
            unread = msg.get("unread", 0)

            # Skip: system messages, folded entries
            if chat_type in ("folded",):
                continue

            # Skip: official accounts (unless VIP)
            if chat_type == "official_account" and chat not in self.vip_contacts:
                continue

            # Skip: no unread messages
            if unread <= 0:
                continue

            # VIP auto-reply
            if chat in self.vip_contacts or sender in self.vip_contacts:
                decisions.append(Decision(
                    action="reply",
                    target=chat,
                    content=self._generate_reply(summary, chat_type),
                    confidence=0.9,
                    reason=f"VIP contact: {chat}",
                ))

        return decisions

    def evaluate_sns_notifications(self, notifications: list[dict]) -> list[Decision]:
        """Evaluate Moments notifications and generate interaction decisions."""
        decisions = []

        for notif in notifications:
            n_type = notif.get("type", "")
            username = notif.get("username", "")

            # Auto-reply to comments from VIPs
            if username in self.vip_contacts and n_type == "comment":
                decisions.append(Decision(
                    action="reply",
                    target=username,
                    content="谢谢！😊",
                    confidence=0.7,
                    reason=f"VIP comment: {username}",
                ))

        return decisions

    def should_post_moment(self, hour: int, last_post_hours: float) -> Decision | None:
        """Decide if it's time to post a scheduled Moment."""
        # Post once during peak hours: 10:00-11:00 or 20:00-21:00
        if last_post_hours < self.cfg.safety.min_interval_between_moments_minutes / 60:
            return None

        peak_morning = 10 <= hour <= 11
        peak_evening = 20 <= hour <= 21

        if peak_morning or peak_evening:
            return Decision(
                action="post_moment",
                target="",
                content=self._generate_moment_content(),
                confidence=0.8,
                reason=f"Peak hour posting ({hour}:00)",
            )

        return None

    def _generate_reply(self, summary: str, chat_type: str) -> str:
        """Generate a context-aware reply."""
        if chat_type == "group":
            return "收到 👍"
        return "好的，收到啦～"

    def _generate_moment_content(self) -> str:
        """Generate a daily Moments post."""
        templates = [
            "今天也是充实的一天 ✨",
            "工作告一段落，周末愉快 🌙",
            "新技能解锁中... 💪",
            "享受当下的每一刻 😊",
        ]
        return random.choice(templates)


class Orchestrator:
    """Main orchestrator: connects wx-cli reading → decision → safe action."""

    def __init__(self):
        self.cfg = get_config()
        self.wx_cli = WxCliClient()
        self.decision = DecisionEngine()
        self.moments = MomentsPoster()
        self.messenger = MessageSender()
        self.sleep = SleepScheduler()
        self._last_moment_post: float = 0  # timestamp

    def run_once(self) -> dict:
        """Run one poll cycle: read → decide → act.

        Returns:
            Summary dict of actions taken
        """
        # Safety: check sleep schedule
        if self.sleep.should_sleep():
            return {"status": "sleeping", "actions": []}

        actions_taken = []

        # 1. Check new messages
        try:
            sessions = self.wx_cli.sessions(limit=30)
        except Exception as e:
            print(f"[orchestrator] wx-cli sessions error: {e}")
            sessions = []

        # 2. Evaluate new messages
        msg_decisions = self.decision.evaluate_new_messages(sessions)
        for d in msg_decisions:
            if d.action == "reply" and d.confidence >= 0.7:
                success = self.messenger.send_to(d.target, d.content, randomize=True)
                actions_taken.append({
                    "action": "reply",
                    "target": d.target,
                    "content": d.content,
                    "success": success,
                    "reason": d.reason,
                })
                time.sleep(random.uniform(5, 15))  # Gap between replies

        # 3. Check Moments notifications
        try:
            notifs = self.wx_cli.sns_notifications(limit=20)
        except Exception as e:
            print(f"[orchestrator] wx-cli sns error: {e}")
            notifs = []

        sns_decisions = self.decision.evaluate_sns_notifications(notifs)
        for d in sns_decisions:
            if d.confidence >= 0.7:
                success = self.messenger.send_to(d.target, d.content, randomize=True)
                actions_taken.append({
                    "action": "sns_reply",
                    "target": d.target,
                    "content": d.content,
                    "success": success,
                    "reason": d.reason,
                })

        # 4. Scheduled Moment posting
        now = time.time()
        hour = time.localtime().tm_hour
        last_hours = (now - self._last_moment_post) / 3600 if self._last_moment_post else 999

        moment_decision = self.decision.should_post_moment(hour, last_hours)
        if moment_decision and moment_decision.confidence >= 0.7:
            success = self.moments.post_text(moment_decision.content, randomize=True)
            if success:
                self._last_moment_post = now
            actions_taken.append({
                "action": "post_moment",
                "target": "",
                "content": moment_decision.content,
                "success": success,
                "reason": moment_decision.reason,
            })

        return {"status": "ok", "actions": actions_taken}

    def run_loop(self, interval_seconds: int = 300):
        """Run continuous poll loop.

        Args:
            interval_seconds: Seconds between poll cycles (default: 5 min)
        """
        print(f"[orchestrator] Starting wx-bot loop (interval={interval_seconds}s)")
        print(f"[orchestrator] wx-cli: {self.wx_cli._exe}")
        print(f"[orchestrator] Safety limits: {self.cfg.safety.max_daily_messages} msgs/day, "
              f"{self.cfg.safety.max_daily_moments} moments/day")
        print(f"[orchestrator] Sleep mode: {'ON' if self.cfg.anti_detect.sleep.enabled else 'OFF'}")
        print()

        while True:
            try:
                result = self.run_once()
                if result["status"] == "sleeping":
                    print("[orchestrator] 💤 Sleep mode — waiting...")
                elif result["actions"]:
                    for a in result["actions"]:
                        status = "✓" if a["success"] else "✗"
                        print(f"  {status} {a['action']:12s} → {a['target'][:20]:20s} | {a['reason']}")
                else:
                    print(f"[orchestrator] No actions — sleeping {interval_seconds}s")

                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                print("\n[orchestrator] Shutting down...")
                break
            except Exception as e:
                print(f"[orchestrator] Error: {e}")
                time.sleep(interval_seconds)


def main():
    """Entry point for standalone orchestrator."""
    orch = Orchestrator()
    orch.run_loop(interval_seconds=300)


if __name__ == "__main__":
    main()
