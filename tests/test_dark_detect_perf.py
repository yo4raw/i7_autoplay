"""ライブ中の PAUSE 照合を範囲限定にした件の回帰テスト。

背景: ライブ中は DARK_RECHECK_SEC おきに PAUSE/楽曲選択をテンプレ照合していたが、
全画面マルチスケール照合が 1回 147〜246ms かかり、0.25秒間隔だと打鍵ループが
**実測 3.3 FPS**（判定376フレーム/115秒）まで落ちていた。ノーツ到達を最大300ms
遅れて検出するため「反応が遅い」「MISS だらけ」になっていた。

対策: PAUSE 見出しの出現位置は安定している（コーパス37枚すべてで x≈0.50,
y=0.27〜0.36）ので探索範囲を絞る。速くなっても**取りこぼさない**ことが要件。
"""
import glob
import os
import sys
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

CORPUS = os.path.join(os.path.dirname(__file__), "corpus_raw")


def _load_bgr(path):
    return cv2.cvtColor(np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


@unittest.skipUnless(os.path.isdir(os.path.join(CORPUS, "pause")),
                     "実フレームコーパスなし（任意）")
class TestPauseSearchBox(unittest.TestCase):
    def setUp(self):
        self.imgs, self.thr = AL.load_templates()["pause"]

    def test_all_pause_frames_still_detected(self):
        """範囲を絞っても PAUSE を1枚も取りこぼさないこと。

        PAUSE を見逃すとライブが止まったまま復帰できず、周回が死ぬ。
        """
        files = sorted(glob.glob(os.path.join(CORPUS, "pause", "*.png")))
        self.assertGreater(len(files), 0)
        missed = []
        for p in files:
            score, _ = AL.match_in_box(_load_bgr(p), self.imgs, AL.PAUSE_SEARCH_BOX)
            if score < self.thr:
                missed.append(os.path.basename(p))
        self.assertEqual([], missed, f"PAUSE を取りこぼした: {missed}")

    def test_no_false_positive_on_gameplay(self):
        """ライブ中のフレームを PAUSE と誤検出しないこと（誤検出すると打鍵が止まる）。"""
        files = sorted(glob.glob(os.path.join(CORPUS, "gameplay", "*.png")))[:40]
        self.assertGreater(len(files), 0)
        false_pos = []
        for p in files:
            score, _ = AL.match_in_box(_load_bgr(p), self.imgs, AL.PAUSE_SEARCH_BOX)
            if score >= self.thr:
                false_pos.append(os.path.basename(p))
        self.assertEqual([], false_pos, f"gameplay を PAUSE と誤検出: {false_pos}")

    def test_search_box_is_small_enough_to_be_cheap(self):
        """探索面積が全画面の 1/3 未満であること（コスト削減の担保）。"""
        x0, y0, x1, y1 = AL.PAUSE_SEARCH_BOX
        area = (x1 - x0) * (y1 - y0)
        self.assertLess(area, 0.34, f"探索範囲が広すぎる: {area:.2f}")

    def test_observed_pause_positions_are_inside_the_box(self):
        """コーパスで実測した出現位置が探索範囲に十分な余裕をもって収まること。"""
        x0, y0, x1, y1 = AL.PAUSE_SEARCH_BOX
        self.assertLess(x0, 0.45)
        self.assertGreater(x1, 0.55)
        self.assertLess(y0, 0.22)      # 実測 y 下限 0.271 に対し余裕
        self.assertGreater(y1, 0.42)   # 実測 y 上限 0.358 に対し余裕


@unittest.skipUnless(os.path.isdir(os.path.join(CORPUS, "songselect")),
                     "実フレームコーパスなし（任意）")
class TestSongselectSearchBox(unittest.TestCase):
    """楽曲選択(NEXT)の照合を範囲限定にした件の回帰テスト。

    2026-08-28: `songselect` を `cardx` より前へ移した（区切り線の誤検出対策）ところ、
    **明るいフレームごとに全画面マルチスケール照合(238ms)が1回増え**、1周あたりの
    判定時間が 24s → 41s に伸びた。NEXT の位置はコーパス35枚すべてで
    x 0.782..0.853 / y 0.841..0.913 と安定しているので、PAUSE と同じく範囲を絞れる
    （実測 238ms → 24ms）。速くなっても**取りこぼさない**ことが要件。
    """

    def setUp(self):
        self.imgs, self.thr = AL.load_templates()["songselect"]

    def test_all_songselect_frames_still_detected(self):
        """範囲を絞っても楽曲選択を1枚も取りこぼさないこと。

        取りこぼすと NEXT を押せず、連戦後に周回が再開しない。
        """
        files = sorted(glob.glob(os.path.join(CORPUS, "songselect", "*.png")))
        self.assertGreater(len(files), 0)
        missed = []
        for p in files:
            score, _ = AL.match_in_box(_load_bgr(p), self.imgs, AL.SONGSELECT_SEARCH_BOX)
            if score < self.thr:
                missed.append(os.path.basename(p))
        self.assertEqual([], missed, f"楽曲選択を取りこぼした: {missed}")

    def test_event_songselect_frame_still_detected(self):
        """cardx 誤検出の原因になったイベント楽曲リストでも取りこぼさないこと。"""
        p = os.path.join(os.path.dirname(__file__), "frames",
                         "songselect_event_671x348.png")
        score, _ = AL.match_in_box(_load_bgr(p), self.imgs, AL.SONGSELECT_SEARCH_BOX)
        self.assertGreaterEqual(score, self.thr, f"イベント楽曲選択を取りこぼした ({score:.3f})")

    def test_no_false_positive_on_other_screens(self):
        """楽曲選択でない画面で誤検出しないこと（誤って NEXT を押すと制御を失う）。"""
        hits = []
        for d in ("gameplay", "formation", "friendselect", "result", "cardx"):
            for p in sorted(glob.glob(os.path.join(CORPUS, d, "*.png")))[:10]:
                score, _ = AL.match_in_box(_load_bgr(p), self.imgs,
                                           AL.SONGSELECT_SEARCH_BOX)
                if score >= self.thr:
                    hits.append(f"{d}/{os.path.basename(p)}={score:.3f}")
        self.assertEqual([], hits, f"楽曲選択でない画面で誤検出: {hits}")


if __name__ == "__main__":
    unittest.main()
