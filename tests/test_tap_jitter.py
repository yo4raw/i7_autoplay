"""着弾点ジッターの統計的性質を固定する（実機不要）。

固定 seed で回すので、統計量を検証しながら結果は決定論的になる。閾値は
docs/superpowers/specs/2026-08-05-tap-jitter-design.md のパラメータから導出した値。
パラメータを変えたら閾値も再計算すること。
"""
import math
import os
import random
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from tap_jitter import TapJitter  # noqa: E402

# 529w 換算の実値（R = 529 × 0.05 = 26.45px に対する 0.10 / 0.18 / 0.60）
BIAS_SIGMA = 2.645
TAP_SIGMA = 4.761
MAX_R = 15.87


def make(seed=1234, n_lanes=4, bias_sigma=BIAS_SIGMA,
         tap_sigma=TAP_SIGMA, max_r=MAX_R):
    return TapJitter(n_lanes, bias_sigma=bias_sigma, tap_sigma=tap_sigma,
                     max_r=max_r, rng=random.Random(seed))


class TestTapJitter(unittest.TestCase):

    def test_tap_noise_sigma(self):
        """1ライブ内の散らばりが tap_sigma の 0.90〜1.05 倍に収まる。

        棄却サンプリングが裾を削るため実効 σ は公称より小さく出る。
        40 seed × 20k サンプルの実測で 0.925〜0.994（許容は両側に余裕を持たせた値）。
        上振れは原理的に起こらないので上側は 1.05 で足りる。
        """
        j = make()
        j.begin_live()
        xs = [j.offset_px(0)[0] for _ in range(20000)]
        sd = statistics.pstdev(xs)
        self.assertGreater(sd, TAP_SIGMA * 0.90)
        self.assertLess(sd, TAP_SIGMA * 1.05)

    def test_bias_sigma(self):
        """begin_live() を繰り返したときのバイアスが bias_sigma の ±10% に収まる。"""
        j = make(tap_sigma=0.0)   # ノイズを消すとオフセット＝バイアスそのもの
        biases = []
        for _ in range(5000):
            j.begin_live()
            biases.append(j.offset_px(0)[0])
        sd = statistics.pstdev(biases)
        self.assertGreater(sd, BIAS_SIGMA * 0.90)
        self.assertLess(sd, BIAS_SIGMA * 1.10)

    def test_never_exceeds_max_r(self):
        """バイアス+ノイズの合計が上限半径を超えない。"""
        j = make()
        for _ in range(200):
            j.begin_live()
            for idx in range(4):
                for _ in range(50):
                    dx, dy = j.offset_px(idx)
                    self.assertLessEqual(math.hypot(dx, dy), MAX_R + 1e-9)

    def test_no_pileup_on_the_boundary_circle(self):
        """上限半径の円周上にオフセットが積み上がらない。

        超過分を切り詰める実装だと、恒常バイアスで中心がずれるぶん境界に当たりやすく、
        **タップの 17% が半径ちょうど max_r の円周上に乗る**（実測）。円周への集中は
        「毎回同じ4点」より不自然な人工物なので、切り詰めではなく棄却で実装すること。
        棄却実装での実測は 0.089%。
        """
        j = make(seed=5)
        j.begin_live()
        n = 20000
        edge = sum(1 for _ in range(n)
                   if math.hypot(*j.offset_px(1)) > MAX_R - 0.05)
        self.assertLess(edge / n, 0.01)

    def test_bias_is_constant_within_a_live(self):
        """同一ライブ内でバイアスは不変、begin_live() で変わる。"""
        j = make(tap_sigma=0.0)
        j.begin_live()
        first = [j.offset_px(0) for _ in range(100)]
        self.assertEqual(len(set(first)), 1)   # ライブ中は完全に同じ点
        j.begin_live()
        self.assertNotEqual(j.offset_px(0), first[0])

    def test_reproducible_with_same_seed(self):
        """同一 seed なら offset_px() の列が完全一致する。"""
        a, b = make(seed=7), make(seed=7)
        a.begin_live()
        b.begin_live()
        for _ in range(500):
            for idx in range(4):
                self.assertEqual(a.offset_px(idx), b.offset_px(idx))

    def test_lanes_have_independent_bias(self):
        """レーンごとに別々のバイアスを持つ。"""
        j = make(tap_sigma=0.0)
        j.begin_live()
        offsets = {j.offset_px(idx) for idx in range(4)}
        self.assertEqual(len(offsets), 4)

    def test_offset_before_begin_live_raises(self):
        """begin_live() を呼ばずに使うと RuntimeError。"""
        j = make()
        with self.assertRaises(RuntimeError):
            j.offset_px(0)

    def test_invalid_params_raise(self):
        """不正なパラメータは ValueError。"""
        with self.assertRaises(ValueError):
            TapJitter(0, bias_sigma=1.0, tap_sigma=1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=-1.0, tap_sigma=1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=1.0, tap_sigma=-1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=1.0, tap_sigma=1.0, max_r=0.0)


import autolive as AL  # noqa: E402


class FakeJitter:
    """固定オフセットを返すスタブ。座標変換だけを切り出して検証するために使う。"""

    def __init__(self, dx, dy):
        self.dx, self.dy = dx, dy

    def begin_live(self):
        pass

    def offset_px(self, idx):
        return self.dx, self.dy


def make_al(circles, jitter, w=671, h=348):
    """実機に触れずに AutoLive を組み立てる（tests/test_roi_scale.py と同じ手口）。"""
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = {"x": 0, "y": 0, "w": w, "h": h}
    al.content = (38, h - 9)
    al.jitter = jitter
    AL.CIRCLES[:] = circles
    return al


class TestTapPoint(unittest.TestCase):

    DEFAULT_CIRCLES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]

    def tearDown(self):
        AL.CIRCLES[:] = list(self.DEFAULT_CIRCLES)

    def test_x_and_y_use_different_denominators(self):
        """x はウィンドウ幅、y は内容矩形高で正規化する（分母の取り違え検出）。

        671x348 では幅 671 に対し内容矩形高は 301。同じ分母を使うと落ちる。
        """
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(10.0, 20.0))
        xf, yf = al._tap_point(0)
        self.assertAlmostEqual(xf, 0.16 + 10.0 / 671, places=9)
        self.assertAlmostEqual(yf, 0.63 + 20.0 / (348 - 9 - 38), places=9)

    def test_follows_in_place_circles_update(self):
        """--auto-circles による CIRCLES の in-place 更新に追従する。

        座標をキャッシュすると、補正が効いた瞬間から古い点を叩き続ける。
        """
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(0.0, 0.0))
        self.assertAlmostEqual(al._tap_point(0)[0], 0.16, places=9)
        AL.CIRCLES[:] = [(0.25, 0.70), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
        self.assertAlmostEqual(al._tap_point(0)[0], 0.25, places=9)

    def test_disabled_returns_exact_circle(self):
        """jitter=None なら素の CIRCLES[idx] と完全一致する。"""
        al = make_al(list(self.DEFAULT_CIRCLES), None)
        for idx in range(4):
            self.assertEqual(al._tap_point(idx), AL.CIRCLES[idx])

    def test_degenerate_window_falls_back_to_exact_circle(self):
        """ウィンドウ寸法が壊れているときは素の座標を返す（ゼロ除算を起こさない）。"""
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(10.0, 20.0))
        al.win = {"x": 0, "y": 0, "w": 0, "h": 0}
        al.content = (38, 38)
        self.assertEqual(al._tap_point(0), AL.CIRCLES[0])


class TestTapSites(unittest.TestCase):
    """打鍵地点が _tap_point() を経由していることをソース上で固定する。

    実機なしでは実際のクリック座標を観測できないため、**素の CIRCLES を
    content_to_screen / click_content に直接渡している箇所が残っていないこと**を
    ソースコードに対して検査する。差し戻しの検出が目的。
    """

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "tools", "autolive.py")
        with open(path, encoding="utf-8") as f:
            self.src = f.read()

    def test_no_raw_circles_in_click_content(self):
        """通常タップが素の円中心を叩いていない。"""
        self.assertNotIn("self.click_content(*CIRCLES[", self.src)

    def test_no_raw_circles_in_content_to_screen(self):
        """フリック開始点とホールド down が素の円中心を使っていない。"""
        self.assertNotIn("self.content_to_screen(*CIRCLES[", self.src)

    def test_keepalive_and_rotate_use_tap_point(self):
        """キープアライブと rotate が素の円中心を叩いていない。

        この2箇所は `cx, cy = CIRCLES[self.circle_i % len(CIRCLES)]` という別の
        書き方をしているので、上の2テストでは捕まらない。
        """
        self.assertNotIn("CIRCLES[self.circle_i", self.src)
        self.assertEqual(self.src.count("self.click_content(*self._tap_point(idx))"), 2)

    def test_roi_still_uses_raw_circles(self):
        """判定 ROI は素の CIRCLES を使い続ける（ジッターを混ぜない）。

        4 箇所ちょうど: _tap_point 自身の読み出し、_circle_roi_px（判定ROI）、
        _approach_red/_approach_green（検色ROI）。assertIn だと1件残るだけで
        パスしてしまい、残り3件のどれかが誤って書き換えられても検出できない
        （例えば _approach_red がジッター混じりに変わっても気づけない）ため、
        件数で固定する。
        """
        self.assertEqual(self.src.count("xf, yf = CIRCLES[idx]"), 4)

    def test_hold_uses_stored_point_for_move_and_up(self):
        """ホールドは down で決めた点を move/up で使い回す（毎回引き直さない）。

        move が 3 箇所、up が 3 箇所。合計 6 箇所すべてが _hold_pt() 経由になる。
        """
        self.assertEqual(
            self.src.count('self._press(*self.content_to_screen(*self._hold_pt(i)), "move")'), 3)
        self.assertEqual(
            self.src.count('self._press(*self.content_to_screen(*self._hold_pt(i)), "up")'), 3)
        self.assertEqual(
            self.src.count("self.hold_point = self._tap_point(i)"), 3)

    def test_hold_point_cleared_on_release(self):
        """hold_point は解除のたびにクリアされる（次のホールドへ持ち越さない）。

        4 箇所ちょうど: __init__ の初期化（Task 2 で追加済み）+ 3 つの解除サイト
        （緑ホールド／predict緑ホールド／輝度長押しの各解除ブロック）。解除サイトの
        どれか1つでもクリアを落とすリファクタが入ると、古い着弾点が次のホールドへ
        漏れてしまう。move/up の呼び出し回数だけを見る既存テストではこの欠落を
        検出できないため、クリア自体の件数を別途固定する。
        """
        self.assertEqual(self.src.count("self.hold_point = None"), 4)


if __name__ == "__main__":
    unittest.main()
