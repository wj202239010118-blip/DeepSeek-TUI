"""WeChat Moments (朋友圈) poster via Windows UI Automation.

Coordinates use PERCENTAGE of window size (0.0-1.0), so they work
regardless of window position or size. Detected dynamically every operation.
"""

import random
import time
from pathlib import Path
from typing import Optional

from ..anti_detect import MouseSimulator, WindowManager, DelayManager, TemplateEngine
from ..anti_detect.sleep import SleepScheduler
from ..config import get_config


# Percentage coordinates (0.0-1.0 of window width/height).
# Estimated for 1936x1089. Run `python calibrate.py` to refine.
COORDS_PCT = {
    "moments_icon":     (0.013, 0.257),  # Moments tab icon in left sidebar
    "moments_camera":   (0.155, 0.110),  # Camera icon (click=image, long-press=text)
    "moments_text_area":(0.077, 0.230),  # Text input area after clicking camera
    "moments_publish":  (0.775, 0.900),  # "Publish" button (bottom-right)
    "moments_confirm":  (0.362, 0.643),  # Confirmation dialog "Publish" button
}


class MomentsPoster:
    """Posts text/image content to WeChat Moments."""

    def __init__(self):
        self.cfg = get_config()
        self.mouse = MouseSimulator()
        self.window = WindowManager()
        self.delay = DelayManager()
        self.template = TemplateEngine()
        self.sleep = SleepScheduler()
        self.coords = COORDS_PCT
        self._today_post_count = 0

    # ── dynamic coordinate helpers ───────────────────────────

    def _get_window_rect(self) -> tuple[int, int, int, int]:
        """Get WeChat window rect: (left, top, width, height)."""
        import win32gui
        hwnd = self.window.wechat_hwnd
        if hwnd is None:
            raise RuntimeError("WeChat window not found")
        r = win32gui.GetWindowRect(hwnd)
        return r[0], r[1], r[2] - r[0], r[3] - r[1]

    def _abs_coord(self, pct_x: float, pct_y: float) -> tuple[int, int]:
        """Convert percentage coords to absolute screen pixels."""
        ox, oy, w, h = self._get_window_rect()
        return int(ox + w * pct_x), int(oy + h * pct_y)

    def _click_pct(self, key: str) -> None:
        """Click at a named percentage coordinate."""
        px, py = self.coords[key]
        abs_x, abs_y = self._abs_coord(px, py)
        self.mouse.click(abs_x, abs_y)
        self.window.post_click_pause()

    # ── safety checks ────────────────────────────────────────

    def _check_limits(self) -> bool:
        self.sleep.wait_if_sleeping()
        if self._today_post_count >= self.cfg.safety.max_daily_moments:
            print(f"[wx-bot] Daily Moments limit reached ({self.cfg.safety.max_daily_moments})")
            return False
        return True

    # ── main flow ────────────────────────────────────────────

    def post_text(
        self, content: str, tone: str | None = None, randomize: bool = True,
    ) -> bool:
        """Post a text-only moment."""
        if not self._check_limits():
            return False
        if not self.window.focus_wechat():
            print("[wx-bot] Failed to focus WeChat window")
            return False

        self.delay.action_interval()
        self._click_pct("moments_icon")
        self.delay.think_pause()
        self._click_pct("moments_camera")
        self.delay.action_interval()

        if randomize:
            final_content = self.template.randomize(content, tone)
        else:
            final_content = content

        self._click_pct("moments_text_area")
        self.delay.action_interval()
        self.delay.type_text(final_content)
        self.delay.think_pause()

        self._click_pct("moments_publish")
        self.delay.action_interval()

        try:
            self._click_pct("moments_confirm")
        except Exception:
            pass

        self._today_post_count += 1
        print(f"[wx-bot] Posted to Moments: {final_content[:50]}...")
        return True

    def post_with_images(
        self, content: str, image_paths: list[str],
        tone: str | None = None, randomize: bool = True,
    ) -> bool:
        """Post a moment with text and images (max 9)."""
        if not self._check_limits():
            return False
        for p in image_paths:
            if not Path(p).exists():
                print(f"[wx-bot] Image not found: {p}")
                return False
        if len(image_paths) > 9:
            print("[wx-bot] Max 9 images per Moment")
            return False

        if not self.window.focus_wechat():
            return False
        self.delay.action_interval()

        self._click_pct("moments_icon")
        self.delay.think_pause()
        self._click_pct("moments_camera")
        self.delay.action_interval()
        self._add_images_via_clipboard(image_paths)
        self.delay.think_pause()

        if randomize:
            final_content = self.template.randomize(content, tone)
        else:
            final_content = content

        self._click_pct("moments_text_area")
        self.delay.action_interval()
        self.delay.type_text(final_content)
        self.delay.think_pause()

        self._click_pct("moments_publish")
        self.delay.action_interval()
        try:
            self._click_pct("moments_confirm")
        except Exception:
            pass

        self._today_post_count += 1
        print(f"[wx-bot] Posted to Moments (text + {len(image_paths)} images)")
        return True

    def _add_images_via_clipboard(self, image_paths: list[str]) -> None:
        import pyautogui, pyperclip
        for path in image_paths:
            pyperclip.copy(path)
            time.sleep(random.uniform(0.1, 0.3))
            pyautogui.hotkey("ctrl", "v")
            time.sleep(random.uniform(0.5, 1.0))
            pyautogui.press("enter")
            time.sleep(random.uniform(0.3, 0.6))

    def reset_daily_count(self) -> None:
        self._today_post_count = 0
