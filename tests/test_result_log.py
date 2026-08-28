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


class TestScoreTracker(unittest.TestCase):
    """取得方式の回帰（2026-08-06）。

    旧実装は「リザルトを検出してから 0.35s×8 のバースト撮影」で、LIFE不足ダイアログが
    絡む周回では 12ライブ中8件を取り逃がした。取りこぼしが**非ランダム**（遷移がもたつく
    ＝成績の悪いライブほど落ちる）なため、効果判定の分布を実力より綺麗に見せてしまう。
    現行は「見えている間追跡し、消えた直後に最後の1枚を確定」する。
    """

    def setUp(self):
        self.good = load("score_result_671x348.png")
        self.other = load("exp_result_671x348.png")
        self.hi = RL.PERFECT_THRESH + 0.1
        self.lo = RL.PERFECT_THRESH - 0.1

    def test_saves_last_visible_frame_after_it_disappears(self):
        """カウントアップ確定後（＝最後に見えた1枚）を、消えた後に確定すること。"""
        t = RL.ScoreTracker()
        self.assertIsNone(t.feed(self.good, self.hi, 0.0))
        last = self.good.copy()
        self.assertIsNone(t.feed(last, self.hi, 0.5))   # 見えている間は出さない
        self.assertIsNone(t.feed(self.other, self.lo, 0.8))  # 消えた直後はまだ待つ
        out = t.feed(self.other, self.lo, 2.0)          # GONE_SEC 経過で確定
        self.assertIsNotNone(out)
        np.testing.assert_array_equal(out, last)

    def test_never_saves_without_a_score_screen(self):
        """スコア画面を一度も見ていなければ保存しない（誤データを貯めない）。"""
        t = RL.ScoreTracker()
        for i in range(20):
            self.assertIsNone(t.feed(self.other, self.lo, i * 0.3))

    def test_cooldown_suppresses_flicker_double_save(self):
        """一瞬の途切れで二重保存しないこと。"""
        t = RL.ScoreTracker()
        t.feed(self.good, self.hi, 0.0)
        self.assertIsNotNone(t.feed(self.other, self.lo, 2.0))
        t.feed(self.good, self.hi, 3.0)
        self.assertIsNone(t.feed(self.other, self.lo, 5.0))   # cooldown 内なので捨てる

    def test_two_separate_results_are_both_saved(self):
        """クールダウンを越えた別のリザルトは両方保存すること。"""
        t = RL.ScoreTracker()
        t.feed(self.good, self.hi, 0.0)
        self.assertIsNotNone(t.feed(self.other, self.lo, 2.0))
        t.feed(self.good, self.hi, 100.0)
        self.assertIsNotNone(t.feed(self.other, self.lo, 102.0))

    def test_brief_gap_while_visible_does_not_split(self):
        """演出中の一瞬の非マッチでは確定しない（GONE_SEC 未満）。"""
        t = RL.ScoreTracker()
        t.feed(self.good, self.hi, 0.0)
        self.assertIsNone(t.feed(self.other, self.lo, 0.4))
        self.assertIsNone(t.feed(self.good, self.hi, 0.7))


if __name__ == "__main__":
    unittest.main()
