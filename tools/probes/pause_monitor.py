"""PAUSE監視（合成keepaliveを送らない）。本物の入力でPAUSEが止まるかの検証用。
PAUSEを検出したら再開だけ行い、5秒ごとにPAUSE回数を出力する。§17.7 調査。"""
import sys, time, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver, autolive

os.environ['I7_CLICK_MODE'] = '0'
al = autolive.AutoLive(max_loops=1, dry_run=False, verbose=False)
driver.activate(); time.sleep(1.0)

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
t0 = time.time(); win_start = t0; pauses = 0; win_pauses = 0
print(f"monitor start dur={DUR}s (NO synthetic keepalive; resume-only)", flush=True)
while time.time() - t0 < DUR:
    f = driver.grab(al.win)
    st, res = al.detect(f)
    if st == 'pause':
        pauses += 1; win_pauses += 1
        al.click_window(*autolive.P_RESUME)
        time.sleep(0.4)
    now = time.time()
    if now - win_start >= 5.0:
        print(f"[{now-t0:5.0f}s] pauses_in_5s={win_pauses}  total={pauses}  state={st}", flush=True)
        win_start = now; win_pauses = 0
    time.sleep(0.22)
print(f"monitor done: total_pauses={pauses} over {DUR:.0f}s", flush=True)
