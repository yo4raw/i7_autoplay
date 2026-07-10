import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE

WIN = {"x": 0, "y": 0, "w": 529, "h": 334}
CONTENT = (38, 325)  # (top, bottom) px


def blank_frame():
    return np.zeros((334, 529, 3), dtype=np.uint8)


def put_blob(frame, xf, yf, rgb, r=4):
    """content相対 (xf,yf) に半径r pxの塗り潰しブロブを置く。"""
    top, bottom = CONTENT
    ch = bottom - top
    cx, cy = int(529 * xf), int(top + yf * ch)
    frame[cy - r:cy + r + 1, cx - r:cx + r + 1] = rgb
    return frame


class TestClassifyColor(unittest.TestCase):
    def test_white(self):
        self.assertEqual(NE.classify_color((230, 225, 220)), "white")

    def test_green(self):
        self.assertEqual(NE.classify_color((90, 220, 120)), "green")

    def test_red(self):
        self.assertEqual(NE.classify_color((230, 90, 90)), "red")

    def test_blue(self):
        self.assertEqual(NE.classify_color((90, 140, 230)), "blue")


class TestAssignLane(unittest.TestCase):
    def test_default_lanes_match_corrected_circles(self):
        self.assertEqual(NE.LANES, [(0.16, 0.63), (0.33, 0.85),
                                    (0.68, 0.85), (0.84, 0.63)])

    def test_blob_toward_lane0(self):
        # スポーンからレーン0（左端）方向の点はレーン0に割当たる
        top, bottom = CONTENT
        ch = bottom - top
        cx = 529 * 0.30
        cy = top + 0.35 * ch
        self.assertEqual(NE.assign_lane(cx, cy, WIN, CONTENT), 0)

    def test_custom_lanes(self):
        # lanes を差し替えると割当も変わる（キャリブレーション後の値を渡せる）
        lanes = [(0.10, 0.60), (0.90, 0.60)]
        cx, cy = 529 * 0.85, CONTENT[0] + 0.5 * (CONTENT[1] - CONTENT[0])
        self.assertEqual(NE.assign_lane(cx, cy, WIN, CONTENT, lanes=lanes), 1)


class TestDetectNotes(unittest.TestCase):
    def test_detects_bright_blob_in_band(self):
        f = put_blob(blank_frame(), 0.40, 0.30, (240, 240, 240))
        notes = NE.detect_notes(f, WIN, CONTENT)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["color"], "white")

    def test_ignores_blob_below_band(self):
        # タップ円帯（FIELD_Y1=0.62 以深）は波紋誤検出防止のため対象外
        f = put_blob(blank_frame(), 0.40, 0.80, (240, 240, 240))
        self.assertEqual(NE.detect_notes(f, WIN, CONTENT), [])


class TestTracker(unittest.TestCase):
    def test_moving_blob_becomes_note_with_lane_and_eta(self):
        trk = NE.Tracker(WIN, CONTENT)
        top, bottom = CONTENT
        ch = bottom - top
        sx, sy = 529 * NE.SPAWN[0], top + NE.SPAWN[1] * ch
        lx, ly = 529 * 0.16, top + 0.63 * ch  # レーン0
        last = []
        for k in range(8):
            t = k * 0.05
            frac = 0.1 + 0.06 * k  # スポーン→レーン0 へ徐々に移動
            x = sx + (lx - sx) * frac
            y = sy + (ly - sy) * frac
            f = blank_frame()
            # 明るい緑（BLOB_MIN_V=110 を全chで超える実ノーツ相当の輝度）
            f[int(y) - 4:int(y) + 5, int(x) - 4:int(x) + 5] = (120, 230, 150)
            last = trk.update(NE.detect_notes(f, WIN, CONTENT), t)
        notes = [a for a in last if a["is_note"]]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["lane"], 0)
        self.assertEqual(notes[0]["type"], "green")
        self.assertIsNotNone(notes[0]["eta"])
        self.assertGreater(notes[0]["eta"], 0)

    def test_static_blob_is_not_note(self):
        trk = NE.Tracker(WIN, CONTENT)
        f = put_blob(blank_frame(), 0.40, 0.30, (240, 240, 240))
        last = []
        for k in range(8):
            last = trk.update(NE.detect_notes(f, WIN, CONTENT), k * 0.05)
        self.assertEqual([a for a in last if a["is_note"]], [])


if __name__ == "__main__":
    unittest.main()
