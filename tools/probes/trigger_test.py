"""どの操作がポーズを引き起こすか切り分け（§17.8）。ライブ中に1種類の操作だけを繰り返し、
ポーズ発生を観測する。mode: activate / warp / click / tap / nothing。"""
import sys, time
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver, autolive
import Quartz

mode = sys.argv[1] if len(sys.argv) > 1 else "nothing"
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 30
gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.4
al = autolive.AutoLive(max_loops=1, dry_run=False, verbose=False)
win = al.win
HID = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
from AppKit import NSWorkspace
_ws = NSWorkspace.sharedWorkspace()
def _front():
    a = _ws.frontmostApplication(); return (a.localizedName() if a else "?")
# activate は行わない（activate がポーズ主因か切り分けるため）。ナビ直後の前面状態を引き継ぐ。
# ウィンドウ内の安全な点（ノーツ円のひとつ）
sx = win["x"] + win["w"] * 0.16
sy = win["y"] + win["h"] * 0.50

def do_action():
    if mode == "activate":
        driver.activate_fast()
    elif mode == "warp":
        Quartz.CGWarpMouseCursorPosition((sx, sy))
    elif mode == "click":  # source=None クリック（ワープなし）
        for et in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            ev = Quartz.CGEventCreateMouseEvent(None, et, (sx, sy), 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    elif mode == "tap":    # autolive実体: warp+HID move+down+up
        al._click_screen(sx, sy)
    elif mode == "iohid_click":  # IOHIDPostEvent 実HIDクリック
        import idlekeeper
        idlekeeper.click(sx, sy)
    elif mode == "iohid_move":   # IOHIDPostEvent 実HID移動のみ
        import idlekeeper
        idlekeeper.move(sx, sy)
    elif mode == "realclick":    # 本物に近い: ワープ+down+遅延+up（押下時間を持たせる）
        Quartz.CGWarpMouseCursorPosition((sx, sy)); time.sleep(0.02)
        dn = Quartz.CGEventCreateMouseEvent(HID, Quartz.kCGEventLeftMouseDown, (sx, sy), 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, dn)
        time.sleep(0.06)
        up = Quartz.CGEventCreateMouseEvent(HID, Quartz.kCGEventLeftMouseUp, (sx, sy), 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    elif mode == "touchclick":   # 本物タップの属性を再現: subtype=3, src_pid=0, eventNumber連番
        global _EVNUM
        try:
            _EVNUM
        except NameError:
            _EVNUM = 1000
        _EVNUM += 1
        Quartz.CGWarpMouseCursorPosition((sx, sy)); time.sleep(0.01)
        for et, pr in ((Quartz.kCGEventLeftMouseDown, 1.0), (Quartz.kCGEventLeftMouseUp, 0.0)):
            ev = Quartz.CGEventCreateMouseEvent(HID, et, (sx, sy), 0)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventSubtype, 3)       # MOUSE_TOUCH
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventNumber, _EVNUM)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGEventSourceUnixProcessID, 0)
            Quartz.CGEventSetDoubleValueField(ev, Quartz.kCGMouseEventPressure, pr)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            if et == Quartz.kCGEventLeftMouseDown:
                time.sleep(0.04)
    # nothing: 何もしない

RESUME = '--resume' in sys.argv
t0 = time.time(); last = None; pauses = 0; first = None; laststate = 'gameplay'; ptimes = []
print(f"TRIGGER TEST mode={mode} dur={DUR}s gap={gap}s resume={RESUME}", flush=True)
while time.time() - t0 < DUR:
    do_action()
    f = driver.grab(win); st, _ = al.detect(f)
    now = time.time()
    if st == 'pause' and laststate != 'pause':
        pauses += 1; ptimes.append(round(now - t0, 1))
        if first is None:
            first = now - t0
        if RESUME:
            al.click_window(*autolive.P_RESUME); time.sleep(0.4)
    laststate = st
    if st != last:
        print(f"[{now-t0:5.1f}s] state={st}", flush=True)
        last = st
    time.sleep(gap)
print(f"DONE mode={mode} pauses={pauses} first_pause={first} ptimes={ptimes}", flush=True)
