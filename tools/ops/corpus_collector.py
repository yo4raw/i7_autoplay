"""周回と並走するパッシブ画面採取（ゼロ入力）。

mss でフレームを読むだけ（クリック・activate を一切しない）なので、autolive の周回を
妨げない。legacy 検出器で状態分類し、状態が変わった瞬間のフレームと定期サンプルを
tests/corpus_raw/<state>/ に保存する。データ駆動化のパリティコーパス＋ assets/screens の
_full.png 原本の材料になる。

使い方: python -u tools/ops/corpus_collector.py <duration_sec> [out_dir]
停止:   /tmp/i7_collector_stop を touch するか duration 経過で終了。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver  # noqa: E402
import autolive  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STOP_FLAG = "/tmp/i7_collector_stop"
MAX_PER_STATE = 40          # 状態ごとの保存上限（ディスク保護）
PERIODIC_SEC = 60.0         # 状態継続中の定期サンプル間隔
INTERVAL = 0.5              # 観測周期（秒）。周回プロセスのCPUを圧迫しない控えめ値


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tests", "corpus_raw")
    os.makedirs(out, exist_ok=True)

    al = autolive.AutoLive(max_loops=1, dry_run=True, verbose=False)  # 入力封印
    counts = {}
    t0 = time.time()
    last_state = None
    last_saved = 0.0
    print(f"collector start dur={dur}s out={out}", flush=True)

    def save(frame, state, tag):
        n = counts.get(state, 0)
        if n >= MAX_PER_STATE:
            return
        d = os.path.join(out, state)
        os.makedirs(d, exist_ok=True)
        ts = time.strftime("%H%M%S")
        path = os.path.join(d, f"{ts}_{tag}.png")
        Image.fromarray(np.asarray(frame)).save(path)
        counts[state] = n + 1
        print(f"[{time.time()-t0:7.1f}s] saved {state}/{os.path.basename(path)}", flush=True)

    while time.time() - t0 < dur and not os.path.exists(STOP_FLAG):
        try:
            f = driver.grab(al.win)
            st, _ = al.detect(f)
        except Exception as e:  # ウィンドウ消失等。採取は止めず再試行
            print(f"[warn] {e}", flush=True)
            time.sleep(5)
            continue
        now = time.time()
        if st != last_state:
            save(f, st, "enter")
            last_state = st
            last_saved = now
        elif now - last_saved >= PERIODIC_SEC:
            save(f, st, "tick")
            last_saved = now
        time.sleep(INTERVAL)

    print(f"collector done counts={counts}", flush=True)


if __name__ == "__main__":
    main()
