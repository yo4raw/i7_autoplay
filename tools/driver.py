#!/usr/bin/env python3
"""iPhone ミラーリング操作ドライバ（テンプレ取得・手動探索用）。

window.py / capture / actuator の原型。ウィンドウ検出・キャプチャ・クリック・
スワイプを、ウィンドウ相対の小数座標（0.0〜1.0）で行えるようにする。
小数座標を使うことでウィンドウサイズ変更に対して頑健に手動ナビゲートできる。

使い方:
    python tools/driver.py info
    python tools/driver.py shot <out.png>
    python tools/driver.py click <xfrac> <yfrac>          # 0..1 のウィンドウ相対
    python tools/driver.py clickshot <xfrac> <yfrac> <out.png>  # クリック後に撮影
    python tools/driver.py swipe <x1> <y1> <x2> <y2>      # 0..1 相対のドラッグ
"""
import sys
import time
import subprocess

import Quartz
import AppKit
import mss as _mss
import numpy as _np
from PIL import Image as _Image

WINDOW_OWNER_KEYS = ("iPhone Mirroring", "iPhoneミラーリング")

# mss は1プロセスで使い回す（毎回生成するとオーバーヘッド大）
_SCT = None


def _get_sct():
    global _SCT
    if _SCT is None:
        _SCT = _mss.mss()
    return _SCT


def find_window():
    """iPhone ミラーリングのウィンドウ情報を返す。

    戻り値: dict(win_id, x, y, w, h)  ※x,y,w,h はポイント単位。
    """
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in wins:
        owner = w.get("kCGWindowOwnerName", "") or ""
        if any(k in owner for k in WINDOW_OWNER_KEYS):
            b = w.get("kCGWindowBounds")
            return {
                "win_id": int(w.get("kCGWindowNumber")),
                "x": float(b["X"]),
                "y": float(b["Y"]),
                "w": float(b["Width"]),
                "h": float(b["Height"]),
                "owner": owner,
            }
    raise RuntimeError("iPhone ミラーリングのウィンドウが見つかりません")


MIRROR_BUNDLE_ID = "com.apple.ScreenContinuity"
_MIRROR_APP = None


def _mirror_app():
    """iPhone ミラーリングの NSRunningApplication をキャッシュして返す。"""
    global _MIRROR_APP
    if _MIRROR_APP is None or _MIRROR_APP.isTerminated():
        apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
        for a in apps:
            if a.bundleIdentifier() == MIRROR_BUNDLE_ID:
                _MIRROR_APP = a
                break
    return _MIRROR_APP


def activate_fast():
    """PyObjC で iPhone ミラーリングを即時最前面化（osascript より高速）。

    ライブ中にフォーカスが外れると iOS アプリがバックグラウンド化して
    ゲームが PAUSE するため、ループ中に頻繁に呼んで前面を維持する。
    """
    app = _mirror_app()
    if app is not None:
        # NSApplicationActivateIgnoringOtherApps = 1<<1
        app.activateWithOptions_(1 << 1)
        return True
    return False


def activate():
    """iPhone ミラーリングを最前面化（合成クリックの前提）。"""
    if not activate_fast():
        subprocess.run(
            ["osascript", "-e", 'tell application "iPhone Mirroring" to activate'],
            capture_output=True,
        )
    time.sleep(0.2)


def grab(win=None):
    """mss でウィンドウ領域を取得し RGB の numpy 配列を返す。

    screencapture -l と異なりウィンドウのフォーカスを奪わないため、
    ライブ中でも PAUSE を誘発しない。返る解像度はポイント等倍
    （Retina の 1x、例: 529x334）。
    """
    if win is None:
        win = find_window()
    region = {
        "top": int(round(win["y"])),
        "left": int(round(win["x"])),
        "width": int(round(win["w"])),
        "height": int(round(win["h"])),
    }
    raw = _np.array(_get_sct().grab(region))  # BGRA
    return raw[:, :, :3][:, :, ::-1]  # -> RGB


def capture(out_path):
    """mss でウィンドウを取得して PNG 保存（フォーカスを奪わない）。"""
    win = find_window()
    rgb = grab(win)
    _Image.fromarray(rgb).save(out_path)
    return win


def frac_to_screen_pt(win, xf, yf):
    """ウィンドウ相対小数(0..1) → 画面ポイント座標(クリック用)。"""
    return (win["x"] + win["w"] * xf, win["y"] + win["h"] * yf)


def click_pt(px, py):
    """画面ポイント座標に左クリックを送る(CGEvent)。"""
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (px, py), Quartz.kCGMouseButtonLeft
    )
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (px, py), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.05)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def click_frac(xf, yf):
    activate()
    win = find_window()
    px, py = frac_to_screen_pt(win, xf, yf)
    # まずカーソルを移動させてからクリック（取りこぼし防止）
    move = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, (px, py), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
    time.sleep(0.08)
    click_pt(px, py)
    return px, py


def swipe_frac(x1, y1, x2, y2, steps=20, hold=0.012):
    activate()
    win = find_window()
    sx, sy = frac_to_screen_pt(win, x1, y1)
    ex, ey = frac_to_screen_pt(win, x2, y2)
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (sx, sy), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.05)
    for i in range(1, steps + 1):
        t = i / steps
        cx = sx + (ex - sx) * t
        cy = sy + (ey - sy) * t
        drag = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDragged, (cx, cy), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, drag)
        time.sleep(hold)
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (ex, ey), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "info":
        win = find_window()
        scr = AppKit.NSScreen.mainScreen()
        win["scale"] = float(scr.backingScaleFactor())
        print(win)
    elif cmd == "shot":
        win = capture(args[1])
        print("captured", args[1], "from win", win["win_id"])
    elif cmd == "click":
        px, py = click_frac(float(args[1]), float(args[2]))
        print(f"clicked frac=({args[1]},{args[2]}) screen_pt=({px:.1f},{py:.1f})")
    elif cmd == "clickshot":
        px, py = click_frac(float(args[1]), float(args[2]))
        time.sleep(float(args[4]) if len(args) > 4 else 1.2)
        capture(args[3])
        print(f"clicked ({args[1]},{args[2]}) -> shot {args[3]}")
    elif cmd == "swipe":
        swipe_frac(float(args[1]), float(args[2]), float(args[3]), float(args[4]))
        print("swiped")
    else:
        print("unknown cmd:", cmd)


if __name__ == "__main__":
    main()
