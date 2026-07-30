"""PAUSEの真因調査（§17.8）。入力を送らず、PAUSE発生時に Mac 側の状態
（最前面アプリ・iPhoneミラーリングのアクティブ/最前面・カーソル位置）が何か変化するかを観測。
ユーザー指摘『iOSは合成/本物を区別できない→原因はMac側』を検証する。"""
import sys, time
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver, autolive
import Quartz
from AppKit import NSWorkspace, NSRunningApplication

al = autolive.AutoLive(max_loops=1, dry_run=False, verbose=False)
win = al.win
ws = NSWorkspace.sharedWorkspace()

def front_app():
    a = ws.frontmostApplication()
    return a.localizedName() if a else "?"

def mirror_state():
    """iPhoneミラーリングapp の active/frontmost を返す。"""
    for a in ws.runningApplications():
        n = (a.localizedName() or "")
        if "Mirroring" in n or "ミラーリング" in n:
            return {"active": bool(a.isActive()), "name": n}
    return {"active": None, "name": None}

def cursor():
    e = Quartz.CGEventCreate(None); p = Quartz.CGEventGetLocation(e)
    inside = (win["x"] <= p.x <= win["x"]+win["w"]) and (win["y"] <= p.y <= win["y"]+win["h"])
    return (round(p.x), round(p.y), inside)

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 30
RESUME = '--resume' in sys.argv
t0 = time.time(); last_state = None
print(f"focus monitor dur={DUR}s resume={RESUME} win={win}", flush=True)
while time.time() - t0 < DUR:
    f = driver.grab(win); st, res = al.detect(f)
    fa = front_app(); ms = mirror_state(); cx, cy, inside = cursor()
    line = f"[{time.time()-t0:5.1f}s] state={st:9s} front={fa:18s} mirror_active={ms['active']} cursor=({cx},{cy} in={inside})"
    # 状態が変わった時 or PAUSE時は必ず出力、それ以外は1秒毎
    if st != last_state or st == 'pause':
        print(line, flush=True)
    last_state = st
    if st == 'pause' and RESUME:
        al.click_window(*autolive.P_RESUME); time.sleep(0.4)
    time.sleep(0.3)
print("done", flush=True)
