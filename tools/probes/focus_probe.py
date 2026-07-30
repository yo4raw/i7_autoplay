"""ライブ中の「最前面アプリ」と pause/gameplay 状態を時系列で記録する観測専用ツール。
activate も打鍵もしない（--tap で genuine 打鍵を併用可）。PAUSE 直前に最前面が
ミラーリングから外れていないか（=フォーカス喪失が PAUSE 主因か）を切り分ける。

使い方: python tools/probes/focus_probe.py [dur] [--tap] [--resume]
"""
import sys
import time
import os
import Quartz
from AppKit import NSWorkspace
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import autolive
import driver

DUR = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 40.0
TAP = "--tap" in sys.argv
RESUME = "--resume" in sys.argv

al = autolive.AutoLive(max_loops=1, dry_run=False)
win = driver.find_window()


def front_name():
    a = NSWorkspace.sharedWorkspace().frontmostApplication()
    return (a.localizedName() or "?") if a else "?"


def is_mirror(n):
    return ("Mirroring" in n) or ("ミラーリング" in n)


t0 = time.time()
laststate = None
lastfront = None
print(f"FOCUS PROBE dur={DUR}s tap={TAP} resume={RESUME}", flush=True)
circle_i = 0
while time.time() - t0 < DUR:
    if TAP:
        cx, cy = autolive.CIRCLES[circle_i % len(autolive.CIRCLES)]
        circle_i += 1
        al.click_content(cx, cy)
    f = driver.grab(win)
    st, _ = al.detect(f)
    fn = front_name()
    now = time.time() - t0
    if st != laststate or fn != lastfront:
        flag = "" if is_mirror(fn) else "  <<< NOT FRONT"
        print(f"[{now:5.1f}s] state={st:9s} front={fn}{flag}", flush=True)
        laststate = st
        lastfront = fn
    if st == "pause" and RESUME:
        al.click_window(*autolive.P_RESUME)
        time.sleep(0.4)
    time.sleep(0.3)
print("DONE", flush=True)
