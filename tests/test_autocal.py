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


if __name__ == "__main__":
    unittest.main()
