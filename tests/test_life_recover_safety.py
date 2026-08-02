"""LIFE 回復がステラストーン（課金アイテム）を消費しないことの回帰テスト。

背景（2026-07-31 に既遂を確認）:
LIFE不足ダイアログの「回復」は、見出し「ライフが足りません。」のマッチ位置から
固定オフセット ANCH_KINAKO=(128,62) で押していた。ところが **きなこパンが 0 個になると
ダイアログはきなこパン行をグレーアウトせず、行ごと消して上に詰める**。その結果、同じ
オフセットがステラストーンの「回復」ボタン中央に着弾していた。

実機で既に発生済み: ステラ所持が 58 → 55 → 52 と、表示された消費数「3」ちょうどずつ減少。
しかもログには「ステラ不使用」と出るため気づけなかった。

対策: **押す前にきなこパン行が実在することを画像で確認**し、その行を基準に押す。
無ければクリックせず停止する。本テストはその不変条件を固定する。
"""
import os
import sys
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

FRAMES = os.path.join(os.path.dirname(__file__), "frames")
PRESENT = "lifeshort_kinako_present_671x348.png"    # きなこパン 184個
DEPLETED = "lifeshort_kinako_depleted_529x334.png"  # きなこパン 0個（行が消えている）

# 実測したステラストーン「回復」ボタンの矩形（DEPLETED フレーム 529x334 上）
STELLA_BUTTON = (313, 158, 365, 178)   # x0, y0, x1, y1


def load(name):
    """テンプレ照合用に **BGR** で返す（テンプレは cv2.imread=BGR で読まれるため）。"""
    rgb = np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_rgb(name):
    return np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))


def detect(frame):
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.templates = AL.load_templates()
    al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
    al.content = (38, frame.shape[0] - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    return al.detect(frame)


class TestKinakoRowDetection(unittest.TestCase):
    def test_row_found_when_kinako_in_stock(self):
        """きなこパンがあるときは行を検出できること（検出できないと回復できず周回が止まる）。"""
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(PRESENT), imgs)
        self.assertIsNotNone(pos)
        self.assertGreaterEqual(score, thr, f"きなこパン行を見失った (score={score:.3f})")

    def test_row_absent_when_depleted(self):
        """枯渇時は行が存在せず、閾値を下回ること。

        ここが下回らないと「無いのに有ると誤認」してステラを押す。
        """
        imgs, thr = AL.load_templates()["kinakorow"]
        score, _ = AL.match_best(load(DEPLETED), imgs)
        self.assertLess(score, thr,
                        f"枯渇フレームで誤検出 (score={score:.3f} >= {thr})")

    def test_separation_margin_is_wide(self):
        """有り／無しのスコア差が十分にあること（閾値をまたぐ余裕の確認）。"""
        imgs, _ = AL.load_templates()["kinakorow"]
        present, _ = AL.match_best(load(PRESENT), imgs)
        depleted, _ = AL.match_best(load(DEPLETED), imgs)
        self.assertGreater(present - depleted, 0.30,
                           f"分離が不十分 present={present:.3f} depleted={depleted:.3f}")


class TestClickTargetSafety(unittest.TestCase):
    def test_row_anchor_lands_on_kinako_recover_button(self):
        """きなこパン行を基準にしたオフセットが、その行の「回復」ボタンに当たること。"""
        imgs, _ = AL.load_templates()["kinakorow"]
        _, pos = AL.match_best(load(PRESENT), imgs)
        x = pos[0] + AL.ANCH_KINAKO_ROW[0]
        y = pos[1] + AL.ANCH_KINAKO_ROW[1]
        # 実測したきなこパン「回復」ボタンの矩形（671x348 上）
        self.assertTrue(385 <= x <= 432, f"x={x:.0f} が「回復」ボタンの外")
        self.assertTrue(162 <= y <= 186, f"y={y:.0f} が「回復」ボタンの外")

    def test_old_headline_anchor_would_have_hit_stella(self):
        """旧実装（見出し基準の固定オフセット）が枯渇時にステラを押していたことの記録。

        この不具合が二度と復活しないよう、事故の形を残しておく。**このテストが失敗する
        （＝旧オフセットがステラに当たらなくなる）ことは想定していない**。もし将来
        ダイアログの構造が変わって失敗したら、C-1 の前提が変わったということなので
        docs/screen-flow.md「課金事故を防ぐ設計」を見直すこと。
        """
        frame = load_rgb(DEPLETED)
        state, res = detect(frame)
        self.assertEqual("lifeshort", state)
        cx, cy = res["lifeshort"][2]
        x, y = cx + 128.0, cy + 62.0        # 旧 ANCH_KINAKO
        x0, y0, x1, y1 = STELLA_BUTTON
        self.assertTrue(x0 <= x <= x1 and y0 <= y <= y1,
                        f"旧オフセットの着弾点 ({x:.0f},{y:.0f}) が "
                        f"ステラボタン {STELLA_BUTTON} の外")

    def test_matching_uses_bgr_frames(self):
        """RGB フレームのまま照合すると閾値を割ることの記録（色空間の取り違え防止）。

        テンプレは cv2.imread（BGR）で読まれるので、照合も BGR で行わなければならない。
        RGB のまま渡すとスコアが落ち、閾値付近の判定が静かに壊れる。
        """
        imgs, thr = AL.load_templates()["kinakorow"]
        rgb_score, _ = AL.match_best(load_rgb(PRESENT), imgs)
        bgr_score, _ = AL.match_best(load(PRESENT), imgs)
        self.assertGreater(bgr_score, rgb_score)
        self.assertLess(rgb_score, thr, "RGB照合でも閾値を超えるならこのテストは無意味")

    def test_no_headline_based_kinako_anchor_remains(self):
        """見出し基準の ANCH_KINAKO が復活していないこと。"""
        self.assertFalse(hasattr(AL, "ANCH_KINAKO"),
                         "ANCH_KINAKO（見出し基準）が残っている。枯渇時にステラを押す")


if __name__ == "__main__":
    unittest.main()
