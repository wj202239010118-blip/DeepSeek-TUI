"""Coordinate calibrator - shows mouse position as PERCENTAGE of WeChat window.

Run: python calibrate.py
Hover over key UI elements, note pct=(x,y). Ctrl+C to stop.
"""

import time, sys
import win32gui, pyautogui

pyautogui.FAILSAFE = False

def find_wechat():
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if '\u5fae\u4fe1' in t or 'WeChat' in t:
                results.append(hwnd)
        return True
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd = find_wechat()
if not hwnd:
    print("ERROR: WeChat window not found")
    sys.exit(1)

r = win32gui.GetWindowRect(hwnd)
ox, oy = r[0], r[1]
w, h = r[2] - r[0], r[3] - r[1]

print("WeChat size: %dx%d  origin: (%d,%d)" % (w, h, ox, oy))
print("Hover over UI elements, note pct values. Ctrl+C to stop.")
print("-" * 55)

try:
    while True:
        mx, my = pyautogui.position()
        rx, ry = mx - ox, my - oy
        inside = 0 <= rx < w and 0 <= ry < h
        px = rx / w if w else 0
        py = ry / h if h else 0
        line = "\r%s abs=(%5d,%5d) pct=(%.3f,%.3f) %s" % (
            ">>>" if inside else "   ", mx, my, px, py,
            "INSIDE" if inside else "outside"
        )
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\n\nDone. Copy pct values into COORDS_PCT.")
