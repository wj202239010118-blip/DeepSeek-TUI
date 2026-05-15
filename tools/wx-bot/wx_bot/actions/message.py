"""WeChat message sender via Windows UI Automation.

Coordinates use PERCENTAGE of window size (0.0-1.0).
"""

import random
import time
from typing import Optional

from ..anti_detect import MouseSimulator, WindowManager, DelayManager, TemplateEngine
from ..anti_detect.sleep import SleepScheduler
from ..config import get_config


# Percentage coordinates (0.0-1.0 of window width/height).
COORDS_PCT = {
    "search_box":          (0.103, 0.032),  # Search bar at top
    "sidebar_first_chat":  (0.103, 0.087),  # First chat in sidebar after search
    "message_input":       (0.207, 0.900),  # Message input area (bottom)
    "send_button":         (0.868, 0.900),  # Send button (bottom-right)
}


class MessageSender:
    """Sends text messages via WeChat Desktop UI."""

    def __init__(self):
        self.cfg = get_config()
        self.mouse = MouseSimulator()
        self.window = WindowManager()
        self.delay = DelayManager()
        self.template = TemplateEngine()
        self.sleep = SleepScheduler()
        self.coords = COORDS_PCT
        self._today_msg_count = 0

    # ── dynamic coordinate helpers ───────────────────────────

    def _get_window_rect(self) -> tuple[int, int, int, int]:
        import win32gui
        hwnd = self.window.wechat_hwnd
        if hwnd is None:
            raise RuntimeError("WeChat window not found")
        r = win32gui.GetWindowRect(hwnd)
        return r[0], r[1], r[2] - r[0], r[3] - r[1]

    def _abs_coord(self, pct_x: float, pct_y: float) -> tuple[int, int]:
        ox, oy, w, h = self._get_window_rect()
        return int(ox + w * pct_x), int(oy + h * pct_y)

    def _click_pct(self, key: str) -> None:
        px, py = self.coords[key]
        abs_x, abs_y = self._abs_coord(px, py)
        self.mouse.click(abs_x, abs_y)
        self.window.post_click_pause()

    # ── safety ───────────────────────────────────────────────

    def _check_limits(self) -> bool:
        self.sleep.wait_if_sleeping()
        if self._today_msg_count >= self.cfg.safety.max_daily_messages:
            print(f"[wx-bot] Daily message limit reached ({self.cfg.safety.max_daily_messages})")
            return False
        return True

    # ── navigation ───────────────────────────────────────────

    def _search_chat(self, chat_name: str) -> bool:
        import pyautogui
        self._click_pct("search_box")
        self.delay.action_interval()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(random.uniform(0.05, 0.12))
        self.delay.type_text(chat_name)
        self.delay.action_interval()
        self._click_pct("sidebar_first_chat")
        self.delay.action_interval()
        return True

    # ── main flow ────────────────────────────────────────────

    def send_to(
        self, chat_name: str, content: str,
        tone: str | None = None, randomize: bool = True,
    ) -> bool:
        """Send a text message to a specific chat."""
        if not self._check_limits():
            return False
        if not self.window.focus_wechat():
            print("[wx-bot] Failed to focus WeChat window")
            return False

        self.delay.action_interval()
        if not self._search_chat(chat_name):
            print(f"[wx-bot] Chat not found: {chat_name}")
            return False

        if randomize:
            final_content = self.template.randomize(content, tone)
        else:
            final_content = content

        self._click_pct("message_input")
        self.delay.action_interval()
        self.delay.type_text(final_content)
        self.delay.think_pause()

        import pyautogui
        pyautogui.press("enter")
        self.delay.action_interval()

        self._today_msg_count += 1
        print(f"[wx-bot] Sent to '{chat_name}': {final_content[:50]}...")
        return True

    def send_to_multiple(
        self, chats: list[str], content: str,
        tone: str | None = None, randomize: bool = True,
        interval_seconds: tuple = (30, 120),
    ) -> dict[str, bool]:
        results = {}
        for chat in chats:
            if not self._check_limits():
                break
            result = self.send_to(chat, content, tone, randomize)
            results[chat] = result
            if result and chat != chats[-1]:
                interval = random.randint(*interval_seconds)
                print(f"[wx-bot] Waiting {interval}s before next send...")
                time.sleep(interval)
        return results

    def reply_to_last(
        self, chat_name: str, content: str,
        tone: str | None = None, randomize: bool = True,
    ) -> bool:
        return self.send_to(chat_name, content, tone, randomize)

    def reset_daily_count(self) -> None:
        self._today_msg_count = 0
