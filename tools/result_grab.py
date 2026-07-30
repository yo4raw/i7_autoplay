"""リザルト画面を受動的にキャプチャ（精度ベースライン計測用）。入力は一切送らない（mss読みのみ）。
result/eventresult を検出したら1リザルトにつき1枚保存する。"""
import sys, time
sys.path.insert(0, 'tools')
import driver, autolive
from PIL import Image

al = autolive.AutoLive(max_loops=1, dry_run=True, verbose=False)
win = al.win
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 360
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6
t0 = time.time(); saved = 0; last_state = None
print(f"result_grab dur={DUR}s want={N}", flush=True)
while time.time() - t0 < DUR and saved < N:
    f = driver.grab(win)
    st, _ = al.detect(f)
    if st == "result" and last_state != "result":
        saved += 1
        p = f"/tmp/i7dbg/result_{saved}.png"
        Image.fromarray(f).save(p)
        print(f"[{time.time()-t0:5.0f}s] saved {p}", flush=True)
    last_state = st
    time.sleep(0.3)
print(f"DONE saved={saved}", flush=True)
