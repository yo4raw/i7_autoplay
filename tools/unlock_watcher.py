"""「iPhoneのロックを解除してください」プロンプトの解消を待つウォッチャ。
プロンプトのテキストが2回連続で見えなくなったら exit 0（=再接続された）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import driver  # noqa: E402
from autolive import match_multiscale  # noqa: E402

import cv2  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPL = os.path.join(ROOT, "assets", "screens", "mac_unlock_prompt", "id_text.png")


def main():
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 21600.0
    t = cv2.imread(TMPL, cv2.IMREAD_COLOR)
    assert t is not None, TMPL
    misses = 0
    t0 = time.time()
    print("unlock watcher start", flush=True)
    while time.time() - t0 < timeout:
        try:
            f = driver.grab(driver.find_window())
            bgr = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
            s, _ = match_multiscale(bgr, t)
        except Exception as e:
            print(f"[warn] {e}", flush=True)
            time.sleep(60)
            continue
        if s >= 0.8:
            misses = 0
        else:
            misses += 1
            print(f"[{time.time()-t0:5.0f}s] prompt gone ({misses}/2) s={s:.2f}", flush=True)
            if misses >= 2:
                print("unlocked/connected", flush=True)
                return 0
        time.sleep(45)
    print("timeout", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
