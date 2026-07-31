"""ROI半径のレーン間スケーリングの回帰テスト（実機不要）。

ノーツは ARC_CENTER から各円へ同じ拍で飛ぶので、遠い円ほど速い。ROI半径が固定だと
速いレーンほど時間的に早く発火し、レーン間でタイミングがばらつく（実測 12.1%〜16.2%）。
半径を移動距離に比例させると、発火が「到達までの同じ時間割合」に揃う。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

# 実機実測値（iPhone16系 671x348、自動キャリブレーション後）
CIRCLES_671 = [(0.22801788, 0.65581396), (0.33353205, 0.83122925),
               (0.66259315, 0.82325582), (0.76989573, 0.65581396)]


def make_al(circles, w=671, h=348, scale_by_distance=True):
    AL.ROI_SCALE_BY_DISTANCE = scale_by_distance
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = {"x": 0, "y": 0, "w": w, "h": h}
    al.content = (38, h - 9)
    al.note_roi = AL.NOTE_ROI_RADIUS
    al.note_lead = 0.04
    al._roi_scale_key = None
    al._roi_scales = None
    AL.CIRCLES[:] = circles
    return al


class TestRoiScale(unittest.TestCase):
    """ROI_SCALE_BY_DISTANCE=True のときの挙動を固定する。

    既定はオフ（実測で改善が誤差に埋もれ、実機の体感でも遅いと指摘されたため）。
    有効化したときに理屈どおり動くことは、再度検証するときのために残しておく。
    """

    def tearDown(self):
        AL.CIRCLES[:] = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
        AL.ROI_SCALE_BY_DISTANCE = False

    def test_disabled_by_default_keeps_uniform_radius(self):
        al = make_al(CIRCLES_671, scale_by_distance=False)
        scales = [al._roi_scale(i) for i in range(len(CIRCLES_671))]
        self.assertEqual([1.0] * len(CIRCLES_671), scales)

    def _fire_fractions(self, al):
        """各レーンの「発火位置 ÷ 移動距離」。揃っているほどタイミングが均一。"""
        top, bottom = al.content
        ch = bottom - top
        w = al.win["w"]
        out = []
        for i, (xf, yf) in enumerate(AL.CIRCLES):
            dx = (AL.ARC_CENTER[0] - xf) * w
            dy = (AL.ARC_CENTER[1] - yf) * ch
            dist = (dx * dx + dy * dy) ** 0.5
            x0, y0, x1, y1 = al._circle_roi_px(i)
            r = (x1 - x0) / 2.0
            out.append(r / dist)
        return out

    def test_fire_fraction_is_equal_across_lanes(self):
        al = make_al(CIRCLES_671)
        fr = self._fire_fractions(al)
        self.assertLess(max(fr) - min(fr), 0.005,
                        f"レーン間の発火タイミングが揃っていない: {fr}")

    def test_mean_radius_is_preserved(self):
        """スケーリングは平均を変えない（note_roi の意味を保つ）。"""
        al = make_al(CIRCLES_671)
        scales = [al._roi_scale(i) for i in range(len(CIRCLES_671))]
        self.assertAlmostEqual(sum(scales) / len(scales), 1.0, places=6)

    def test_scale_follows_distance_order(self):
        """遠い円ほど半径が大きい（速さに比例）。"""
        al = make_al(CIRCLES_671)
        scales = [al._roi_scale(i) for i in range(len(CIRCLES_671))]
        # 円0,3 が外側（遠い）、円1,2 が内側（近い）
        self.assertGreater(scales[0], scales[1])
        self.assertGreater(scales[3], scales[2])

    def test_cache_is_invalidated_when_circles_change(self):
        """自動キャリブレーションで CIRCLES が入れ替わったらスケールも作り直すこと。"""
        al = make_al(CIRCLES_671)
        before = al._roi_scale(0)
        AL.CIRCLES[:] = [(0.10, 0.60), (0.33, 0.85), (0.68, 0.85), (0.90, 0.60)]
        after = al._roi_scale(0)
        self.assertNotAlmostEqual(before, after, places=4)


if __name__ == "__main__":
    unittest.main()
