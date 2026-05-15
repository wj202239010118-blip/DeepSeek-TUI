"""Human sleep pattern simulator.

Simulates realistic daily rhythm:
- Night mode: pause operations between configured hours (e.g., 23:00-07:00)
- Random sleep duration within range (6-8h)
- Weekend sleep-in (extra 0-2h)
- Wakes up at random time within the configured window
"""

import datetime
import random
import time
from typing import Optional

from ..config import get_config, SleepConfig


class SleepScheduler:
    """Simulates human sleep/activity patterns."""

    def __init__(self, cfg: SleepConfig | None = None):
        self.cfg = cfg or get_config().anti_detect.sleep
        self._last_sleep_check: datetime.datetime | None = None
        self._sleeping_until: datetime.datetime | None = None

    @property
    def is_night_time(self) -> bool:
        """Check if current time falls within the configured sleep window."""
        now = datetime.datetime.now()
        night_start_h, night_start_m = map(int, self.cfg.night_start.split(":"))
        night_end_h, night_end_m = map(int, self.cfg.night_end.split(":"))

        night_start = now.replace(hour=night_start_h, minute=night_start_m, second=0)
        night_end = now.replace(hour=night_end_h, minute=night_end_m, second=0)

        # Handle overnight ranges (e.g., 23:00 → 07:00)
        if night_start > night_end:
            # Crosses midnight: True if now >= start OR now <= end
            return now >= night_start or now <= night_end
        else:
            return night_start <= now <= night_end

    @property
    def is_weekend(self) -> bool:
        """Check if today is Saturday or Sunday."""
        return datetime.datetime.now().weekday() >= 5

    def should_sleep(self) -> bool:
        """Determine if the bot should enter sleep mode now."""
        if not self.cfg.enabled:
            return False

        if not self.is_night_time:
            self._sleeping_until = None
            return False

        # Already sleeping — check if sleep is over
        if self._sleeping_until is not None:
            if datetime.datetime.now() >= self._sleeping_until:
                self._sleeping_until = None
                return False
            return True

        # Enter sleep mode
        sleep_hours = random.randint(*self.cfg.sleep_duration_hours)
        if self.is_weekend:
            extra = random.randint(*self.cfg.weekend_sleep_in_hours)
            sleep_hours += extra

        # Wake-up time: random within the night_end window
        night_end_h, night_end_m = map(int, self.cfg.night_end.split(":"))
        now = datetime.datetime.now()
        wake_base = now.replace(hour=night_end_h, minute=night_end_m, second=0)

        # If night_start > night_end, wake is tomorrow
        night_start_h, _ = map(int, self.cfg.night_start.split(":"))
        if night_start_h > night_end_h and now.hour >= night_start_h:
            wake_base += datetime.timedelta(days=1)

        # Add random jitter (±15 minutes)
        jitter = random.randint(-15, 15)
        self._sleeping_until = wake_base + datetime.timedelta(
            hours=random.uniform(0, sleep_hours),
            minutes=jitter,
        )

        return True

    def wait_if_sleeping(self) -> bool:
        """Block until sleep period is over. Returns True if we waited."""
        if not self.should_sleep():
            return False

        if self._sleeping_until is None:
            return False

        remaining = (self._sleeping_until - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            self._sleeping_until = None
            return False

        # Sleep in 5-minute chunks to allow interruption
        while remaining > 0:
            chunk = min(300, remaining)  # 5 minutes max
            time.sleep(chunk)
            remaining = (self._sleeping_until - datetime.datetime.now()).total_seconds()

        self._sleeping_until = None
        return True

    def daily_limit_reached(self, count: int, max_count: int) -> bool:
        """Check if a daily per-action limit has been reached."""
        return count >= max_count
