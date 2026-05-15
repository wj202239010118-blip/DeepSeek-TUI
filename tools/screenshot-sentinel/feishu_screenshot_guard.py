import argparse
import hashlib
import os
import shutil
import threading
import time
from datetime import datetime

import pyperclip
from PIL import ImageGrab, Image
from pynput import keyboard


def to_int(v, fallback):
    try:
        n = int(v)
        return n if n >= 0 else fallback
    except Exception:
        return fallback


def ensure_dir(p):
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass


def list_png_files(save_dir):
    try:
        names = os.listdir(save_dir)
    except Exception:
        return []
    out = []
    for name in names:
        if not name.lower().endswith(".png"):
            continue
        p = os.path.join(save_dir, name)
        try:
            st = os.stat(p)
            if not os.path.isfile(p):
                continue
            out.append((p, st.st_mtime))
        except Exception:
            continue
    out.sort(key=lambda x: x[1], reverse=True)
    return [p for (p, _) in out]


def cleanup(save_dir, max_files, quiet):
    files = list_png_files(save_dir)
    if len(files) <= max_files:
        return
    expired = files[max_files:]
    for p in expired:
        try:
            os.remove(p)
            if not quiet:
                print(f"[GC] {os.path.basename(p)}")
        except Exception:
            pass


def format_path(file_path, kind, style):
    abs_path = os.path.abspath(file_path)
    if kind == "absolute":
        out = abs_path
    else:
        out = os.path.relpath(abs_path, os.getcwd())
    if style == "posix":
        out = out.replace("\\", "/")
    elif style == "win":
        out = out.replace("/", "\\")
    return out


def clipboard_signature():
    try:
        obj = ImageGrab.grabclipboard()
    except Exception:
        return (None, None), None
    if isinstance(obj, Image.Image):
        try:
            raw = obj.tobytes()
            h = hashlib.blake2b(raw, digest_size=16).hexdigest()
            return ("image", obj.size, obj.mode, h), obj
        except Exception:
            return ("image", obj.size, obj.mode, None), obj
    if isinstance(obj, list) and obj:
        try:
            norm = tuple(os.path.abspath(p) for p in obj)
        except Exception:
            norm = tuple(obj)
        return ("files", norm), obj
    return (None, None), None


def with_retries(fn, retries, base_sleep_s):
    last_exc = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            time.sleep(base_sleep_s * (i + 1))
    raise last_exc


def save_clipboard_payload(save_dir, prefix, path_kind, path_style, quiet):
    sig, obj = clipboard_signature()
    if sig[0] == "image" and isinstance(obj, Image.Image):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{ts}.png"
        file_path = os.path.join(save_dir, filename)
        try:
            with_retries(lambda: obj.save(file_path, "PNG"), retries=5, base_sleep_s=0.05)
        except Exception:
            if not quiet:
                print("保存失败（剪贴板图片可能不可用）")
            return None
        out_path = format_path(file_path, path_kind, path_style)
        try:
            pyperclip.copy(out_path)
        except Exception:
            if not quiet:
                print("剪贴板写入失败")
        if not quiet:
            print("-------------------------------------------")
            print(f"已保存: {filename}")
            print(f"路径: {out_path}")
        return sig

    if sig[0] == "files" and isinstance(obj, list):
        src = None
        for p in obj:
            ext = os.path.splitext(str(p))[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"]:
                src = p
                break
        if not src:
            if not quiet:
                print("剪贴板未发现图片")
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ext = os.path.splitext(str(src))[1]
        filename = f"{prefix}_{ts}{ext}"
        dst = os.path.join(save_dir, filename)
        try:
            with_retries(lambda: shutil.copy2(src, dst), retries=5, base_sleep_s=0.05)
        except Exception:
            if not quiet:
                print("复制失败（剪贴板文件可能不可用）")
            return None
        out_path = format_path(dst, path_kind, path_style)
        try:
            pyperclip.copy(out_path)
        except Exception:
            if not quiet:
                print("剪贴板写入失败")
        if not quiet:
            print("-------------------------------------------")
            print(f"已保存: {filename}")
            print(f"路径: {out_path}")
        return sig

    if not quiet:
        print("剪贴板未发现图片")
    return None


def build_parser():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--dir", default=os.environ.get("SAVE_DIR", ""), help="保存目录")
    p.add_argument("--max", default=os.environ.get("MAX_FILES", ""), help="最大保留文件数")
    p.add_argument("--hotkey", default=os.environ.get("HOTKEY", ""), help="全局热键")
    p.add_argument("--prefix", default=os.environ.get("PREFIX", "feishu"), help="文件名前缀")
    p.add_argument("--delay", default=os.environ.get("DELAY_S", ""), help="触发后延迟秒数")
    p.add_argument("--timeout", default=os.environ.get("TIMEOUT_S", ""), help="待命超时秒数")
    p.add_argument("--poll", default=os.environ.get("POLL_S", ""), help="轮询间隔秒数")
    p.add_argument(
        "--path",
        default=os.environ.get("PATH_KIND", "absolute"),
        choices=["absolute", "relative"],
        help="写回剪贴板的路径类型",
    )
    p.add_argument(
        "--style",
        default=os.environ.get("PATH_STYLE", "win"),
        choices=["posix", "native", "win"],
        help="路径分隔符风格",
    )
    p.add_argument("--quiet", action="store_true", help="静默输出")
    return p


def main():
    args = build_parser().parse_args()

    save_dir = args.dir or os.path.join(os.getcwd(), "feishu_uploads")
    max_files = to_int(args.max, 5)
    hotkey_str = args.hotkey or "<ctrl>+<shift>+a"
    delay_s = float(args.delay) if str(args.delay).strip() else 0.5
    timeout_s = float(args.timeout) if str(args.timeout).strip() else 15.0
    poll_s = float(args.poll) if str(args.poll).strip() else 0.25
    quiet = bool(args.quiet) or os.environ.get("QUIET", "0") == "1"

    ensure_dir(save_dir)
    cleanup(save_dir=save_dir, max_files=max_files, quiet=True)

    path_kind = args.path.lower()
    path_style = args.style.lower()
    if path_style == "native":
        path_style = "win" if os.name == "nt" else "posix"

    state_lock = threading.Lock()
    state = {"on": False, "token": 0}

    def run_capture():
        last_seen_token = None
        base_sig = (None, None)
        start = None

        while True:
            with state_lock:
                cur_token = state["token"]
            if cur_token != last_seen_token:
                last_seen_token = cur_token
                time.sleep(delay_s)
                base_sig, _ = clipboard_signature()
                start = time.time()
                if not quiet:
                    print("待命：等待新截图进入剪贴板（再次按热键可重置计时）")

            sig, _ = clipboard_signature()
            if sig[0] is not None and sig != base_sig:
                save_clipboard_payload(
                    save_dir=save_dir,
                    prefix=args.prefix,
                    path_kind=path_kind,
                    path_style=path_style,
                    quiet=quiet,
                )
                cleanup(save_dir=save_dir, max_files=max_files, quiet=quiet)
                break

            if start is not None and time.time() - start >= timeout_s:
                if not quiet:
                    print("超时：未检测到新截图")
                break

            time.sleep(poll_s)

        with state_lock:
            state["on"] = False

    def on_activate():
        with state_lock:
            state["token"] += 1
            should_start = not state["on"]
            state["on"] = True
        if should_start:
            t = threading.Thread(target=run_capture, daemon=True)
            t.start()

    if not quiet:
        print("飞书截图哨兵已启动")
        print(f"热键: {hotkey_str}")
        print(f"保存目录: {save_dir}")
        print(f"保留数量: {max_files}")
        print(f"路径输出: {path_kind}/{path_style}")
        print(f"待命超时: {timeout_s}s")
        print(f"轮询间隔: {poll_s}s")
        print("")

    hotkey = keyboard.HotKey(keyboard.HotKey.parse(hotkey_str), on_activate)

    def for_canonical(f):
        return lambda k: f(listener.canonical(k))

    with keyboard.Listener(on_press=for_canonical(hotkey.press), on_release=for_canonical(hotkey.release)) as listener:
        listener.join()


if __name__ == "__main__":
    main()

