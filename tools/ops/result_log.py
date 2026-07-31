"""リザルトの成績欄を周回と並走して蓄積する（受動観測・入力ゼロ）。

打鍵チューニングの効果は1ライブの比較では判断できない（実測で ±5% 程度の
ばらつきがあり、単発比較だと改善と誤差の区別がつかない）。本ツールは各ライブの
PERFECT/GOOD/BAD/MISS と SCORE が写る帯だけを切り出して貯め、まとめて1枚の
モンタージュにする。少ないコンテキストで分布を目視比較するのが目的。

mss で読むだけなのでフォーカスを奪わず、周回を妨げない（PAUSE も誘発しない）。

使い方:
  python -u tools/ops/result_log.py [duration_sec=7200] [tag]
  python -u tools/ops/result_log.py montage [tag]   # 蓄積ぶんを1枚にまとめる

保存先: /tmp/i7dbg/results/<tag>/NNN.png、モンタージュは同ディレクトリの _montage.png
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver  # noqa: E402
import autolive  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

OUT_ROOT = "/tmp/i7dbg/results"
# 成績欄（Ache/EASY+ 行〜SCORE 行）の切り出し範囲。ウィンドウ相対で持ち、機種差に追従する。
STATS_BOX = (0.425, 0.322, 0.812, 0.563)   # (x0f, y0f, x1f, y1f)
COOLDOWN_SEC = 20.0   # 同じリザルトを二重に保存しない
# リザルト検出後、この間隔・回数でバースト撮影して「スコア画面である最後のフレーム」を採る。
# 固定待ち時間だと外す: 待ちが短いとカウントアップ演出の途中、長いと autolive が画面を
# 送ってしまい EXP 画面になる（実測 2.6s では全件 EXP 画面だった）。
BURST_GAP_SEC = 0.35
BURST_N = 8
# スコア画面と EXP 画面の判別。スコア画面は成績欄の背景がクリーム色でほぼ白の画素が多い。
# 実測: スコア画面 0.60 / EXP画面 0.45。絶対閾値だけに頼らず、バースト内の最大値付近の
# フレーム群のうち**最後**（＝カウントアップが終わっている）を選ぶ。
WHITE_FLOOR = 0.52
WHITE_TOL = 0.03


def crop_stats(frame, win=None):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = STATS_BOX
    return Image.fromarray(frame[int(h * y0):int(h * y1), int(w * x0):int(w * x1)])


def white_frac(frame):
    """成績欄のほぼ白な画素比率（スコア画面かどうかの指標）。"""
    c = np.asarray(crop_stats(frame))
    return float((c.min(axis=2) > 200).mean())


def pick_score_frame(frames):
    """バーストからスコア画面の最終フレームを選ぶ。無ければ None。"""
    scored = [(white_frac(f), f) for f in frames]
    best = max(s for s, _ in scored)
    if best < WHITE_FLOOR:
        return None
    chosen = [f for s, f in scored if s >= best - WHITE_TOL]
    return chosen[-1]      # 最後＝カウントアップ確定後


def collect(duration, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    al = autolive.AutoLive.__new__(autolive.AutoLive)
    al.templates = autolive.load_templates()
    al.win = driver.find_window()
    al.content = (38, int(al.win["h"]) - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    n = len([f for f in os.listdir(out_dir) if f.endswith(".png") and f[0].isdigit()])
    t0 = time.time()
    last_saved = 0.0
    print(f"result_log start dur={duration}s out={out_dir} (既存{n}件)", flush=True)
    while time.time() - t0 < duration:
        try:
            frame = driver.grab(al.win)
            state, _ = al.detect(frame)
        except Exception as e:      # 切断・ウィンドウ消失などは致命ではない
            print(f"[warn] {e}", flush=True)
            time.sleep(3.0)
            continue
        if state == "result" and time.time() - last_saved > COOLDOWN_SEC:
            burst = []
            for _ in range(BURST_N):
                try:
                    burst.append(driver.grab(al.win))
                except Exception:
                    break
                time.sleep(BURST_GAP_SEC)
            last_saved = time.time()
            picked = pick_score_frame(burst) if burst else None
            if picked is None:
                print(f"[{time.time()-t0:6.0f}s] スコア画面を捉えられず（見送り）", flush=True)
                continue
            n += 1
            p = os.path.join(out_dir, f"{n:03d}.png")
            crop_stats(picked).save(p)
            print(f"[{time.time()-t0:6.0f}s] saved {p}", flush=True)
        time.sleep(0.4)
    print(f"done ({n}件)", flush=True)


def montage(out_dir, limit=12):
    files = sorted(f for f in os.listdir(out_dir)
                   if f.endswith(".png") and f[0].isdigit())[-limit:]
    if not files:
        print("no results", flush=True)
        return
    ims = [Image.open(os.path.join(out_dir, f)) for f in files]
    w = max(i.width for i in ims)
    sheet = Image.new("RGB", (w, sum(i.height for i in ims)), (0, 0, 0))
    y = 0
    for i in ims:
        sheet.paste(i, (0, y))
        y += i.height
    p = os.path.join(out_dir, "_montage.png")
    sheet.save(p)
    print(f"{p} ({len(files)}件)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "montage":
        tag = sys.argv[2] if len(sys.argv) > 2 else "default"
        montage(os.path.join(OUT_ROOT, tag))
    else:
        dur = float(sys.argv[1]) if len(sys.argv) > 1 else 7200
        tag = sys.argv[2] if len(sys.argv) > 2 else "default"
        collect(dur, os.path.join(OUT_ROOT, tag))
