"""カードポップアップを閉じる打鍵が、危険なボタンの近くに落ちないことの回帰テスト。

背景（2026-08-29 ユーザー指摘）:
`P_CARD_DISMISS` は「中央のカードを外した**右上の暗い背景**」を叩く設計だった。
しかし右上には画面をまたいで**押してはいけないものが集まっている**:

- BACK ボタン（窓相対 約 (0.906, 0.185)）… 押すと画面が巻き戻り、周回の導線を外れる
- **ステラ所持数の「＋」ボタン（約 (0.872, 0.135)）… 課金導線**
- 上部バーの各種通貨・イベント表示

旧値 (0.86, 0.16) は 671x348 で (577, 56)。「＋」の実測 (585, 47) とは **x で 8px・
y で 9px** しか離れておらず、カードを閉じるたびに課金導線のすぐ隣を叩いていた。

対策は「**上部バーの高さに入らないところまで下げる**」。カードは画面中央に出るので
横位置 0.86 は元からカードの外側であり、縦を下げても背景を叩く性質は変わらない。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

# 実測（窓相対）。**この近くに着弾させてはいけない**もの。
BACK_BUTTON = (0.906, 0.185)
STELLA_PLUS = (0.872, 0.135)   # 課金導線
TOP_BAR_BOTTOM = 0.30          # 上部バー（通貨・BACK・＋）が占める帯の下端


class TestCardDismissPoint(unittest.TestCase):
    def test_is_below_the_top_bar(self):
        """上部バーの帯より下を叩くこと（BACK と課金導線がある帯を避ける）。"""
        self.assertGreater(AL.P_CARD_DISMISS[1], TOP_BAR_BOTTOM,
                           f"y={AL.P_CARD_DISMISS[1]} が上部バーの帯に入っている")

    def test_far_from_back_button(self):
        """BACK ボタンから十分離れていること。"""
        dy = abs(AL.P_CARD_DISMISS[1] - BACK_BUTTON[1])
        self.assertGreater(dy, 0.20, f"BACK との縦距離 {dy:.3f} が近すぎる")

    def test_far_from_stella_purchase_button(self):
        """**課金導線（ステラの＋）から十分離れていること。**"""
        dy = abs(AL.P_CARD_DISMISS[1] - STELLA_PLUS[1])
        self.assertGreater(dy, 0.20, f"ステラ＋との縦距離 {dy:.3f} が近すぎる")

    def test_far_from_start_button(self):
        """編成画面の START から離れていること（誤爆すると LIFE を消費する）。"""
        dy = abs(AL.P_CARD_DISMISS[1] - AL.P_START[1])
        self.assertGreater(dy, 0.20, f"START との縦距離 {dy:.3f} が近すぎる")

    def test_stays_outside_a_centred_card(self):
        """カードは画面中央に出るので、横位置は中央から十分外れていること。

        ここが中央に寄ると、カード本体を叩いてしまい閉じられない
        （実機確認: カードは×ではなく背景タップで閉じる）。
        """
        self.assertGreater(abs(AL.P_CARD_DISMISS[0] - 0.5), 0.30,
                           "横位置が中央のカードに掛かる")

    def test_not_in_bottom_left_corner(self):
        """左下は避けること（カーソルが Dock／ホットコーナー付近へワープして危険）。"""
        x, y = AL.P_CARD_DISMISS
        self.assertFalse(x < 0.3 and y > 0.8, "左下に着弾している")


if __name__ == "__main__":
    unittest.main()
