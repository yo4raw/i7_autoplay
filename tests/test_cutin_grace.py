"""ライブ中のスキルカットインを明るい側へ流さない件の回帰テスト（実機不要）。

背景（2026-10-20 実機・「Encounter Love Song」10倍）: 1ライブに 30〜40 回、明るさ 65〜83 の
スキルカットインが入り、リングが隠れるフレームが多い。旧判定はこれを明るい側（全段照合
≈1 秒 + menu の待ち 0.3 秒）へ流し、その間は打鍵が止まって 1 ライブ ≈45 秒を失っていた。

要件:
- ライブを確認できた直後（CUTIN_GRACE_SEC 以内）の薄暗いカットインは gameplay。
- 猶予は「確認できたフレーム」でしか延びない（ライブ後の薄暗い画面に居座らない）。
- 猶予中でも PAUSE は PAUSE として検出する（取りこぼすとライブが止まったまま）。
- ライブを確認していなければ従来どおり明るい側で判定する。
"""
import os
import sys
import time
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

FRAMES = os.path.join(os.path.dirname(__file__), "frames")


def load_rgb(name):
    return np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))


def make_al(frame):
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.templates = AL.load_templates()
    al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
    al.content = (38, frame.shape[0] - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    return al


class TestCutinGrace(unittest.TestCase):
    CUTIN = "gameplay_cutin_656x341.png"   # 明るさ 74・リング無し（実機のライブ中フレーム）

    def test_fixture_is_dim_and_ringless(self):
        """前提: このフレームは薄暗く（DARK〜DIM）リングが見えない＝旧判定では明るい側へ落ちる。"""
        fr = load_rgb(self.CUTIN)
        b = AL.frame_brightness(fr)
        self.assertTrue(AL.DARK_THRESH <= b < AL.DIM_THRESH, b)
        self.assertFalse(make_al(fr)._rings_visible(fr))

    def test_cutin_right_after_live_is_gameplay(self):
        fr = load_rgb(self.CUTIN)
        al = make_al(fr)
        al._live_confirmed_ts = time.time()
        self.assertEqual("gameplay", al.detect(fr)[0])

    def test_cutin_without_recent_live_is_not_gameplay(self):
        """ライブを確認していない（起動直後・メニュー中）なら従来どおり明るい側で判定する。"""
        fr = load_rgb(self.CUTIN)
        al = make_al(fr)
        self.assertNotEqual("gameplay", al.detect(fr)[0])

    def test_grace_expires_and_is_not_extended_by_cutin_frames(self):
        """猶予中のカットイン判定では起点を更新しない。CUTIN_GRACE_SEC 経てば明るい側へ戻る。"""
        fr = load_rgb(self.CUTIN)
        al = make_al(fr)
        t0 = time.time() - AL.CUTIN_GRACE_SEC + 0.5
        al._live_confirmed_ts = t0
        self.assertEqual("gameplay", al.detect(fr)[0])
        self.assertEqual(t0, al._live_confirmed_ts, "カットイン判定で猶予が延びた")
        al._live_confirmed_ts = time.time() - AL.CUTIN_GRACE_SEC - 0.1
        self.assertNotEqual("gameplay", al.detect(fr)[0])

    def test_pause_is_still_detected_during_grace(self):
        """猶予中でも PAUSE を取りこぼさない（656x341・明るさ 85・リング無しの実機フレーム）。"""
        fr = load_rgb("pause_656x341.png")
        al = make_al(fr)
        al._live_confirmed_ts = time.time()
        self.assertEqual("pause", al.detect(fr)[0])

    def test_dark_gameplay_refreshes_confirmation(self):
        fr = load_rgb("gameplay_dis_one_671x348.png")
        al = make_al(fr)
        self.assertEqual("gameplay", al.detect(fr)[0])
        self.assertGreater(getattr(al, "_live_confirmed_ts", 0.0), time.time() - 1.0)


if __name__ == "__main__":
    unittest.main()
