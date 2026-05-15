"""Bézier curve mouse trajectory simulator.

Generates human-like mouse paths with:
- Cubic Bézier curves with random control points
- Variable speed (slow start, accelerate, decelerate)
- Occasional overshoot & correction
- Micro-jitter in stationary positions
"""

import random
import time
import math
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from ..config import get_config, MouseConfig


@dataclass
class Point:
    x: float
    y: float


class MouseSimulator:
    """Simulates human-like mouse movement using Bézier curves."""

    def __init__(self, cfg: MouseConfig | None = None):
        self.cfg = cfg or get_config().anti_detect.mouse

    # ── core Bézier ──────────────────────────────────────────

    @staticmethod
    def _cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
        """Evaluate cubic Bézier at parameter t."""
        mt = 1 - t
        x = mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x
        y = mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y
        return Point(x, y)

    def _generate_control_points(self, start: Point, end: Point) -> List[Point]:
        """Generate random intermediate Bézier segment endpoints + control points."""
        n_segments = random.randint(*self.cfg.bezier_waypoints)
        if n_segments <= 1:
            return [start, end]

        # Distribute waypoints along a loose arc
        points = [start]
        dx = end.x - start.x
        dy = end.y - start.y
        dist = math.hypot(dx, dy)

        for i in range(1, n_segments):
            frac = i / n_segments
            # Base position on the line
            bx = start.x + dx * frac
            by = start.y + dy * frac
            # Perpendicular offset (arc)
            perp_x = -dy / dist if dist > 0 else 0
            perp_y = dx / dist if dist > 0 else 0
            arc_magnitude = dist * random.uniform(-0.15, 0.15)
            points.append(Point(bx + perp_x * arc_magnitude, by + perp_y * arc_magnitude))

        points.append(end)
        return points

    def _interpolate_path(
        self, waypoints: List[Point], duration: float
    ) -> List[Tuple[float, float]]:
        """Generate dense sample points along the Bézier path."""
        path: List[Tuple[float, float]] = []
        steps_per_segment = max(20, int(duration * 200))

        for i in range(len(waypoints) - 1):
            p0 = waypoints[i]
            p3 = waypoints[i + 1]
            # Random control points for natural curvature
            dx = p3.x - p0.x
            dy = p3.y - p0.y
            p1 = Point(
                p0.x + dx * random.uniform(0.2, 0.4) + random.uniform(-30, 30),
                p0.y + dy * random.uniform(0.2, 0.4) + random.uniform(-30, 30),
            )
            p2 = Point(
                p0.x + dx * random.uniform(0.6, 0.8) + random.uniform(-30, 30),
                p0.y + dy * random.uniform(0.6, 0.8) + random.uniform(-30, 30),
            )

            seg_steps = steps_per_segment // (len(waypoints) - 1)
            for j in range(seg_steps):
                t = j / seg_steps
                pt = self._cubic_bezier(p0, p1, p2, p3, t)
                path.append((round(pt.x), round(pt.y)))

        # Ensure the last point is exactly the target
        path.append((round(waypoints[-1].x), round(waypoints[-1].y)))
        return path

    # ── speed control ────────────────────────────────────────

    def _compute_duration(self, start: Point, end: Point) -> float:
        """Compute movement duration based on distance and human speed."""
        dist = math.hypot(end.x - start.x, end.y - start.y)
        speed = random.randint(self.cfg.speed_min, self.cfg.speed_max)
        base_duration = dist / speed

        # Add variability: ±30%
        variation = random.uniform(0.7, 1.3)
        return max(0.15, base_duration * variation)

    def _speed_profile(self, n_steps: int) -> List[float]:
        """Generate speed weights: slow start, fast middle, slow end."""
        t = np.linspace(0, 1, n_steps)
        # Sigmoid-like: ease-in-out
        weights = 1 / (1 + np.exp(-12 * (t - 0.5)))
        weights = weights / weights.max()
        # Add micro-jitter
        weights += np.random.normal(0, 0.02, n_steps)
        return (weights / weights.sum() * n_steps).tolist()

    # ── overshoot ────────────────────────────────────────────

    def _should_overshoot(self) -> bool:
        return random.random() < self.cfg.overshoot_pct

    def _compute_overshoot(self, start: Point, end: Point) -> Point:
        dx = end.x - start.x
        dy = end.y - start.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return end
        overshoot_dist = random.randint(*self.cfg.overshoot_distance)
        return Point(
            end.x + (dx / dist) * overshoot_dist,
            end.y + (dy / dist) * overshoot_dist,
        )

    # ── public API ───────────────────────────────────────────

    def move_to(self, x: int, y: int, relative: bool = False) -> None:
        """Move mouse to (x, y) using a human-like Bézier trajectory."""
        import pyautogui

        pyautogui.FAILSAFE = False
        current = pyautogui.position()
        start = Point(current.x, current.y)

        if relative:
            end = Point(current.x + x, current.y + y)
        else:
            end = Point(x, y)

        # Generate path
        waypoints = self._generate_control_points(start, end)
        duration = self._compute_duration(start, end)
        path = self._interpolate_path(waypoints, duration)
        speeds = self._speed_profile(len(path))

        # Execute movement with variable speed
        step_duration = duration / len(path)
        for (px, py), speed_w in zip(path, speeds):
            adjusted_delay = step_duration / max(speed_w, 0.3)
            pyautogui.moveTo(px, py, duration=0)
            time.sleep(adjusted_delay)

        # Overshoot & correct
        if self._should_overshoot():
            overshoot = self._compute_overshoot(start, end)
            time.sleep(random.uniform(0.02, 0.06))
            pyautogui.moveTo(int(overshoot.x), int(overshoot.y), duration=0.05)
            time.sleep(random.uniform(0.04, 0.10))
            pyautogui.moveTo(int(end.x), int(end.y), duration=0.06)

    def click(self, x: int | None = None, y: int | None = None) -> None:
        """Click at position, with human-like movement if coordinates given."""
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(random.uniform(0.05, 0.15))
        import pyautogui
        pyautogui.click()

    def double_click(self, x: int | None = None, y: int | None = None) -> None:
        """Double-click with human-like movement."""
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(random.uniform(0.05, 0.12))
        import pyautogui
        pyautogui.doubleClick()

    def drag(
        self, x1: int, y1: int, x2: int, y2: int, duration: float | None = None
    ) -> None:
        """Drag from (x1,y1) to (x2,y2) with Bézier trajectory."""
        self.move_to(x1, y1)
        time.sleep(random.uniform(0.05, 0.15))
        import pyautogui

        pyautogui.mouseDown()
        time.sleep(random.uniform(0.03, 0.08))
        self.move_to(x2, y2)
        time.sleep(random.uniform(0.03, 0.08))
        pyautogui.mouseUp()
