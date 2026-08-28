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
COOLDOWN_SEC = 10.0   # 同じリザルトを二重に保存しない（追跡方式では「消えた」縁が境界になる）
# スコア画面が**見えている間ずっと追跡**し、消えた直後に最後の1枚を確定する。
#
# 旧実装は state=="result" を見てから 0.35s×8 のバースト撮影をしていたが、
# **LIFE不足ダイアログが絡む周回では 12ライブ中8件を取り逃がした**（2026-08-06 実測）。
# しかも取りこぼしは**非ランダム**で、遷移がもたつくライブほど外し、そういうライブは
# 成績も悪い。効果判定に使うツールでこれは致命的で、実際に「良いライブだけが残った
# 綺麗すぎる分布」を作り、緑ホールドの採否判断を一度誤らせた。
# 追跡方式では同一条件で 11/11 取得できた。
GONE_SEC = 1.0        # スコア画面がこの秒数見えなくなったら「通過し切った」とみなす
# スコア画面の判別は「PERFECT」ラベルのテンプレ照合で行う。
# 当初は「ほぼ白の画素比率」で判別していたが、**白背景のアイテム獲得ポップアップを
# スコア画面と誤選択**していた（実測: 蓄積43件がすべてポップアップだった）。
# ラベル照合なら 実測 スコア画面 1.000 / ポップアップ 0.47 / EXP画面 0.52 と明確に分離する。
PERFECT_TEMPLATE = "result_perfect.png"
PERFECT_THRESH = 0.80


def crop_stats(frame, win=None):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = STATS_BOX
    return Image.fromarray(frame[int(h * y0):int(h * y1), int(w * x0):int(w * x1)])


_PERFECT_IMG = None


def _perfect_template():
    global _PERFECT_IMG
    if _PERFECT_IMG is None:
        import cv2
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
            "assets", "templates", PERFECT_TEMPLATE)
        _PERFECT_IMG = [cv2.imread(path, cv2.IMREAD_COLOR)]
    return _PERFECT_IMG


def score_screen_score(frame):
    """「PERFECT」ラベルの一致度。スコア画面かどうかの指標。frame は RGB。"""
    import cv2
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    return float(autolive.match_best(bgr, _perfect_template())[0])


class ScoreTracker:
    """スコア画面を追跡し、消えた直後に「最後に見えた1枚」を確定する（純粋ロジック）。

    毎フレーム `feed()` に渡すだけでよく、撮影タイミングを当てにいく必要がない。
    カウントアップ演出の確定後が自然に採れる（最後に見えた1枚＝演出後）。
    """

    def __init__(self, gone_sec=GONE_SEC, cooldown_sec=COOLDOWN_SEC,
                 thresh=PERFECT_THRESH):
        self.gone_sec = gone_sec
        self.cooldown_sec = cooldown_sec
        self.thresh = thresh
        self._last = None        # 直近にスコア画面が見えたフレーム
        self._last_seen = 0.0
        self._last_saved = -1e9

    def feed(self, frame, score, now):
        """1フレーム投入。確定したら保存すべきフレームを返す。まだなら None。"""
        if score >= self.thresh:
            self._last, self._last_seen = frame, now
            return None
        if self._last is None:
            return None
        if now - self._last_seen <= self.gone_sec:
            return None
        out = self._last
        self._last = None
        if now - self._last_saved < self.cooldown_sec:
            return None          # 直前に保存済み（チラつき）なので捨てる
        self._last_saved = now
        return out


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
    tracker = ScoreTracker()
    print(f"result_log start dur={duration}s out={out_dir} (既存{n}件)", flush=True)
    while time.time() - t0 < duration:
        try:
            frame = driver.grab(al.win)
            score = score_screen_score(frame)
        except Exception as e:      # 切断・ウィンドウ消失などは致命ではない
            print(f"[warn] {e}", flush=True)
            time.sleep(3.0)
            try:
                al.win = driver.find_window()
            except Exception:
                pass
            continue
        picked = tracker.feed(frame, score, time.time())
        if picked is not None:
            n += 1
            p = os.path.join(out_dir, f"{n:03d}.png")
            crop_stats(picked).save(p)
            print(f"[{time.time()-t0:6.0f}s] saved {p}", flush=True)
        time.sleep(0.3)
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
