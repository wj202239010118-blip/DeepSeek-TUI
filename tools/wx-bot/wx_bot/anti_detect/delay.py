"""Random delay & pause manager.

Simulates human rhythm:
- Variable intervals between actions
- Slower typing (80-250ms per keystroke)
- Occasional "thinking" pauses (2-8s)
- Gaussian distribution around the mean for natural variance
"""

import random
import time
from typing import Optional

from ..config import get_config, DelayConfig


class DelayManager:
    """Injects human-like random delays between automated actions."""

    def __init__(self, cfg: DelayConfig | None = None):
        self.cfg = cfg or get_config().anti_detect.delay

    def action_interval(self) -> None:
        """Random pause between two discrete actions."""
        ms = random.randint(*self.cfg.action_interval_ms)
        time.sleep(ms / 1000.0)

    def typing_delay(self) -> float:
        """Delay between individual keystrokes (returns seconds, does NOT sleep)."""
        ms = random.randint(*self.cfg.typing_delay_ms)
        return ms / 1000.0

    def think_pause(self) -> None:
        """Simulate a human thinking/reading pause."""
        ms = random.randint(*self.cfg.think_time_ms)
        time.sleep(ms / 1000.0)

    def gaussian_delay(
        self, mean_ms: float = 500, std_ms: float = 150, min_ms: float = 50
    ) -> None:
        """Delay sampled from a normal distribution (more natural than uniform)."""
        ms = max(min_ms, random.gauss(mean_ms, std_ms))
        time.sleep(ms / 1000.0)

    def type_text(self, text: str) -> None:
        """Type text with human-like inter-keystroke delays."""
        import pyautogui

        for char in text:
            pyautogui.typewrite(char, interval=0)
            delay = self.typing_delay()
            # Slightly longer delay after punctuation
            if char in ".!?;:,":
                delay *= random.uniform(1.5, 3.0)
            # Longer delay after newlines
            if char == "\n":
                delay *= random.uniform(2.0, 5.0)
            time.sleep(delay)

    def paste_text(self, text: str) -> None:
        """Paste text via clipboard (faster, less human but sometimes needed)."""
        import pyautogui
        import pyperclip

        pyperclip.copy(text)
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.hotkey("ctrl", "v")
