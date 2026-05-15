"""Window focus & activation manager.

Simulates human window-switching behavior:
- Random delay before activating a window
- Gradual focus (not instant jump)
- Verify window is foreground before acting
"""

import random
import time
import subprocess
from typing import Optional

from ..config import get_config, WindowConfig


class WindowManager:
    """Manages WeChat window focus with human-like delays."""

    def __init__(self, cfg: WindowConfig | None = None):
        self.cfg = cfg or get_config().anti_detect.window
        self._wechat_hwnd: int | None = None

    @property
    def wechat_hwnd(self) -> int | None:
        """Cached WeChat window handle."""
        if self._wechat_hwnd is None:
            self._wechat_hwnd = self._find_wechat_window()
        return self._wechat_hwnd

    def _find_wechat_window(self) -> int | None:
        """Find the WeChat main window handle."""
        import win32gui
        import win32con

        wechat_cfg = get_config().wechat

        def _enum_callback(hwnd: int, results: list) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if wechat_cfg.window_title_contains and wechat_cfg.window_title_contains not in title:
                return True
            # If class filter is configured, check it
            if wechat_cfg.window_class_contains:
                class_name = win32gui.GetClassName(hwnd)
                if wechat_cfg.window_class_contains not in class_name:
                    return True
            results.append(hwnd)
            return True

        results: list = []
        win32gui.EnumWindows(_enum_callback, results)
        return results[0] if results else None

    def _ensure_foreground(self, hwnd: int) -> bool:
        """Bring window to foreground, return True if successful."""
        import win32gui
        import win32con

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Random delay before activation (human "decision time")
        focus_delay = random.randint(*self.cfg.focus_delay_ms) / 1000.0
        time.sleep(focus_delay)

        # Bring to foreground
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # Fallback: use Alt+Tab simulation or just accept
            pass

        time.sleep(0.15)
        foreground = win32gui.GetForegroundWindow()
        return foreground == hwnd

    def focus_wechat(self) -> bool:
        """Activate WeChat window with human-like timing."""
        hwnd = self.wechat_hwnd
        if hwnd is None:
            return False
        return self._ensure_foreground(hwnd)

    def post_click_pause(self) -> None:
        """Random pause after a click, simulating visual processing."""
        delay_ms = random.randint(*self.cfg.post_click_pause_ms)
        time.sleep(delay_ms / 1000.0)

    def is_wechat_foreground(self) -> bool:
        """Check if WeChat is the active foreground window."""
        import win32gui

        hwnd = self.wechat_hwnd
        if hwnd is None:
            return False
        return win32gui.GetForegroundWindow() == hwnd

    def find_wechat_pid(self) -> int | None:
        """Get the WeChat process ID."""
        import win32process
        import win32gui

        hwnd = self.wechat_hwnd
        if hwnd is None:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid

    def is_wechat_running(self) -> bool:
        """Check if WeChat process is running."""
        import win32gui

        return self._find_wechat_window() is not None
