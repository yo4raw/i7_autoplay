"""IOHIDPostEvent の連続カーソル移動が PAUSE を防ぐかをクリーンに検証（§17.8）。
autolive のワープを混ぜず、ウィンドウ内で円を描く実HID移動だけを続け、PAUSE数を測る。"""
import sys, time, math
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver, autolive, idlekeeper
import Quartz

al = autolive.AutoLive(max_loops=1, dry_run=False, verbose=False)
win = al.win
driver.activate(); time.sleep(0.5)
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40
cx = win['x'] + win['w'] * 0.5
cy = win['y'] + win['h'] * 0.30   # 上寄り（ノーツ円から離す）
r = win['w'] * 0.12
t0 = time.time(); pauses = 0; gp = 0.0; lastt = t0; win5 = t0; w5p = 0; i = 0
print(f"hidmove test DUR={DUR}s win={win}", flush=True)
while time.time() - t0 < DUR:
    ang = i * 0.6
    mx, my = cx + r * math.cos(ang), cy + r * math.sin(ang)
    Quartz.CGWarpMouseCursorPosition((mx, my))   # 正確にカーソルを動かす（実証済み）
    # 併せて MouseMoved も送る（NSEvent配送）
    mv = Quartz.CGEventCreateMouseEvent(idlekeeper and None, Quartz.kCGEventMouseMoved, (mx, my), 0)
    Quartz.CGEventSetIntegerValueField(mv, Quartz.kCGMouseEventDeltaX, int(r * math.cos(ang) - r * math.cos((i-1)*0.6)))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, mv)
    i += 1
    f = driver.grab(win); st, _ = al.detect(f)
    now = time.time()
    if st == 'gameplay':
        gp += now - lastt
    lastt = now
    if st == 'pause':
        pauses += 1; w5p += 1
        al.click_window(*autolive.P_RESUME); time.sleep(0.3); lastt = time.time()
    if now - win5 >= 5:
        print(f"[{now-t0:4.0f}s] st={st:9s} pauses_5s={w5p} total={pauses} gp={gp:.0f}s", flush=True)
        win5 = now; w5p = 0
    time.sleep(0.12)
print(f"DONE pauses={pauses} gameplay={gp:.0f}s rate={pauses/gp*60 if gp else 0:.1f}/min", flush=True)
