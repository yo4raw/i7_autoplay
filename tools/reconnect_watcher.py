"""ミラーリング切断（iPhoneが見つかりません/接続が中断されました）の再接続ウォッチャ。

「やり直す」ボタンをテンプレ照合で見つけた時だけクリック（誤タップ防止）。
ボタンが消え、かつ画面がゲーム/ホーム等に変わったら exit 0（=再接続成功、呼び出し側で周回再開）。
タイムアウトで exit 1。

使い方: python -u tools/reconnect_watcher.py [timeout_sec=14400]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import driver  # noqa: E402
from autolive import match_multiscale  # noqa: E402

import cv2  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETRY_TMPL = os.path.join(ROOT, "assets", "screens", "mac_disconnect", "retry_btn.png")


def main():
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 14400.0
    tmpl = cv2.imread(RETRY_TMPL, cv2.IMREAD_COLOR)
    assert tmpl is not None, RETRY_TMPL
    t0 = time.time()
    misses = 0
    print(f"reconnect watcher start (timeout={timeout}s)", flush=True)
    while time.time() - t0 < timeout:
        try:
            f = driver.grab(driver.find_window())
        except Exception as e:
            print(f"[warn] window? {e}", flush=True)
            time.sleep(60)
            continue
        bgr = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
        score, pos = match_multiscale(bgr, tmpl)
        if score >= 0.85 and pos is not None:
            misses = 0
            h, w = f.shape[:2]
            print(f"[{time.time()-t0:6.0f}s] retry btn ({score:.2f}) -> click", flush=True)
            driver.click_frac(pos[0] / w, pos[1] / h)
            time.sleep(25)  # 接続試行を待つ
        else:
            misses += 1
            if misses >= 2:
                print(f"[{time.time()-t0:6.0f}s] retry btn gone -> reconnected? exit 0", flush=True)
                return 0
            time.sleep(10)
        time.sleep(90)
    print("timeout", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
