"""result_log.py のスコア画面判別の回帰テスト（実機不要）。

背景（2026-08-01）:
当初は成績欄の「ほぼ白の画素比率」でスコア画面を判別していたが、**白背景のアイテム
獲得ポップアップをスコア画面と誤選択**し、蓄積43件がすべてポップアップだった。
チューニングの効果判定に使うツールなので、誤ったデータを貯めると判断を誤る。

対策: 「PERFECT」ラベルのテンプレ照合で判別する。
実測の分離: スコア画面 1.000 / ポップアップ 0.47 / EXP画面 0.52。
"""
import os
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "ops"))
import result_log as RL  # noqa: E402

FRAMES = os.path.join(ROOT, "tests", "frames")


def load(name):
    with Image.open(os.path.join(FRAMES, name)) as im:
        return np.array(im.convert("RGB"))


class TestScoreScreenDetection(unittest.TestCase):
    def test_score_screen_matches(self):
        s = RL.score_screen_score(load("score_result_671x348.png"))
        self.assertGreaterEqual(s, RL.PERFECT_THRESH, f"スコア画面を見失った ({s:.3f})")

    def test_other_result_screens_do_not_match(self):
        """EXP画面・ダイアログをスコア画面と誤認しないこと。"""
        for name in ("exp_result_671x348.png", "resume_live_dialog_671x348.png",
                     "story_dialog_event_671x348.png"):
            with self.subTest(frame=name):
                s = RL.score_screen_score(load(name))
                self.assertLess(s, RL.PERFECT_THRESH, f"{name} を誤認 ({s:.3f})")


class TestPickScoreFrame(unittest.TestCase):
    def test_picks_the_last_score_frame(self):
        """スコア画面が複数あれば最後（カウントアップ確定後）を選ぶこと。"""
        good = load("score_result_671x348.png")
        other = load("exp_result_671x348.png")
        picked = RL.pick_score_frame([other, good, good, other])
        self.assertIsNotNone(picked)
        self.assertGreaterEqual(RL.score_screen_score(picked), RL.PERFECT_THRESH)

    def test_returns_none_without_score_frame(self):
        """スコア画面が無いバーストでは保存を見送ること（誤データを貯めない）。"""
        other = load("exp_result_671x348.png")
        self.assertIsNone(RL.pick_score_frame([other, other]))

    def test_empty_burst_is_safe(self):
        self.assertIsNone(RL.pick_score_frame([]))


if __name__ == "__main__":
    unittest.main()
