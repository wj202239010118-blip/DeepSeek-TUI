"""Detect WeChat window position and size."""
import win32gui, ctypes

def enum_cb(hwnd, results):
    if not win32gui.IsWindowVisible(hwnd):
        return True
    title = win32gui.GetWindowText(hwnd)
    cls = win32gui.GetClassName(hwnd)
    if '微信' in title or 'WeChat' in cls or 'wx' in cls.lower():
        r = win32gui.GetWindowRect(hwnd)
        results.append({'hwnd': hwnd, 'title': title, 'class': cls, 'rect': r})
    return True

results = []
win32gui.EnumWindows(enum_cb, results)

if not results:
    print("NO_WECHAT")
else:
    for r in results:
        w = r['rect'][2] - r['rect'][0]
        h = r['rect'][3] - r['rect'][1]
        print(f'WECHAT hwnd={r["hwnd"]} title="{r["title"]}" class="{r["class"]}" left={r["rect"][0]} top={r["rect"][1]} right={r["rect"][2]} bottom={r["rect"][3]} size={w}x{h}')
