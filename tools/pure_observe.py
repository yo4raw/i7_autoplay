"""完全受動観測（ゼロ入力）。クリック・タップ・カーソル移動・activate を一切行わず、
mss で画面を読むだけ。ライブ中にポーズが起きるか（=操作しなければポーズにならない説）を検証。"""
import sys, time
sys.path.insert(0, 'tools')
import driver, autolive

al = autolive.AutoLive(max_loops=1, dry_run=True, verbose=False)  # dry_run=True で念のため入力封印
win = al.win
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40
t0 = time.time(); last = None; first_pause = None; gp = 0.0; lastt = t0
print(f"PURE OBSERVE (zero input) dur={DUR}s win={win}", flush=True)
while time.time() - t0 < DUR:
    f = driver.grab(win)              # mss read only（フォーカスを奪わない）
    st, _ = al.detect(f)
    now = time.time()
    if st == 'gameplay':
        gp += now - lastt
    lastt = now
    if st == 'pause' and first_pause is None:
        first_pause = now - t0
    if st != last:
        print(f"[{now-t0:5.1f}s] state={st}", flush=True)
        last = st
    time.sleep(0.3)
print(f"DONE first_pause={first_pause} gameplay_time={gp:.1f}s", flush=True)
