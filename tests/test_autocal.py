import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE

WIN = {"x": 0, "y": 0, "w": 529, "h": 334}
CONTENT = (38, 325)


def frame_with_rings(centers, radius=26):
    f = np.zeros((334, 529, 3), dtype=np.uint8)
    top, bottom = CONTENT
    ch = bottom - top
    for xf, yf in centers:
        cx, cy = int(529 * xf), int(top + yf * ch)
        cv2.circle(f, (cx, cy), radius, (235, 235, 235), 3)
    return f


class TestDetectCircles(unittest.TestCase):
    def test_detects_four_rings_near_truth(self):
        truth = NE.LANES
        det = NE.detect_circles(frame_with_rings(truth), WIN, CONTENT)
        self.assertGreaterEqual(len(det), 4)
        matched = NE.match_circles(det, truth)
        self.assertIsNotNone(matched)
        for (mx, my), (tx, ty) in zip(matched, truth):
            self.assertLess(abs(mx - tx), 0.03)
            self.assertLess(abs(my - ty), 0.03)


class TestMatchCircles(unittest.TestCase):
    def test_full_match_returns_in_prior_order(self):
        prior = [(0.2, 0.6), (0.8, 0.6)]
        det = [(0.81, 0.61), (0.21, 0.59)]
        self.assertEqual(NE.match_circles(det, prior), [(0.21, 0.59), (0.81, 0.61)])

    def test_partial_detection_returns_none(self):
        # 1円でも欠けたら None（呼び出し側は現行値を維持＝誤検出で悪化させない）
        prior = [(0.2, 0.6), (0.8, 0.6)]
        self.assertIsNone(NE.match_circles([(0.21, 0.59)], prior))

    def test_out_of_tolerance_returns_none(self):
        prior = [(0.2, 0.6)]
        self.assertIsNone(NE.match_circles([(0.5, 0.6)], prior, tol=0.06))

    def test_device_scale_offset_is_absorbed(self):
        """機種差ぶんのズレ（実測 0.072〜0.074）が既定 tol で吸収されること。

        iPhone16系(671x348)では外側2円が約47px=0.07 ずれており、旧 tol=0.06 では
        match_circles が None を返して補正が不発になった（MISS 51・グレードB）。
        既定 tol はこの実測ズレを吸収できる値でなければならない。
        """
        prior = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
        actual = [(0.228, 0.655), (0.334, 0.824), (0.663, 0.824), (0.771, 0.655)]
        matched = NE.match_circles(list(reversed(actual)), prior)
        self.assertEqual(actual, matched, "実測ズレが既定 tol で吸収されていない")

    def test_neighbouring_ring_is_not_cross_matched(self):
        """tol を緩めても隣の円に誤マッチしないこと（prior の最小間隔は 0.16）。"""
        prior = [(0.16, 0.63), (0.33, 0.85)]
        # 1円目に対応する検出が無く、2円目の実測だけがある状況
        self.assertIsNone(NE.match_circles([(0.334, 0.824)], prior))


class TestConsensusCircles(unittest.TestCase):
    """ライブ中は1フレームで4円そろわないため、時間方向の多数決で確定する。"""

    PRIOR = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
    ACTUAL = [(0.228, 0.655), (0.334, 0.824), (0.663, 0.824), (0.771, 0.655)]

    def _samples(self, per_circle):
        """各実測円のまわりに微小ゆらぎを付けたサンプル列を作る。"""
        out = []
        for i in range(per_circle):
            d = (i - per_circle // 2) * 0.001
            for x, y in self.ACTUAL:
                out.append((x + d, y - d))
        return out

    def test_confirms_after_enough_samples(self):
        got = NE.consensus_circles(self._samples(3), self.PRIOR)
        self.assertIsNotNone(got)
        for (gx, gy), (ax, ay) in zip(got, self.ACTUAL):
            self.assertLess(abs(gx - ax), 0.01)
            self.assertLess(abs(gy - ay), 0.01)

    def test_returns_none_until_enough_samples(self):
        # 1フレームぶん（各円1サンプル）では確定させない
        self.assertIsNone(NE.consensus_circles(self._samples(1), self.PRIOR))

    def test_returns_none_when_one_circle_never_detected(self):
        samples = [s for s in self._samples(5)
                   if abs(s[0] - self.ACTUAL[3][0]) > 0.01]
        self.assertIsNone(NE.consensus_circles(samples, self.PRIOR))

    def test_outlier_samples_do_not_move_result(self):
        samples = self._samples(3) + [(0.50, 0.50)] * 4  # 中央の誤検出（tol外）
        got = NE.consensus_circles(samples, self.PRIOR)
        self.assertIsNotNone(got)
        for (gx, _), (ax, _) in zip(got, self.ACTUAL):
            self.assertLess(abs(gx - ax), 0.01)


if __name__ == "__main__":
    unittest.main()
