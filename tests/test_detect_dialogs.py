"""実フレームでのダイアログ判定の回帰テスト（実機不要）。

イベント装飾でテンプレが崩れて誤判定 → 停止、という事故が繰り返し起きているため、
実際に停止したフレームをそのまま資産化して固定する。
"""
import os
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

FRAMES = os.path.join(os.path.dirname(__file__), "frames")


def detect_file(name):
    """実機接続なしで detect() だけを走らせる。"""
    frame = np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.templates = AL.load_templates()
    al.content = (38, frame.shape[0] - 9)
    al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
    al.verbose = False
    al._last_dark_check = 0.0
    return al.detect(frame)


class TestStoryDialog(unittest.TestCase):
    def test_event_themed_story_dialog_is_not_mistaken_for_cardx(self):
        """「ストーリー開放チケットがあります。」をカードポップアップと誤認しないこと。

        2026-07-31 実機: イベント装飾版のこのダイアログを cardx と誤認し、
        背景タップで閉じようとして10回失敗 → 9周で安全停止した。
        cardx と判定されると「いいえ」を押せず、必ず停滞して止まる。
        """
        state, res = detect_file("story_dialog_event_671x348.png")
        self.assertEqual("story", state,
                         f"story と判定されるべきだが {state} だった")
        self.assertGreaterEqual(res["story"][0], 0.85)


class TestResumeLiveDialog(unittest.TestCase):
    def test_resume_live_dialog_is_detected(self):
        """「前回のライブを再開しますか？」を専用状態として判定すること。

        2026-07-31 実機: アプリ再起動後にこのダイアログが出るが未対応で、
        人手で「はい」を押すまで周回が再開できなかった。シアン系ヘッダを持つため
        cardx と誤認しやすく、その場合は背景タップで閉じられず停滞する。
        """
        state, res = detect_file("resume_live_dialog_671x348.png")
        self.assertEqual("resumelive", state,
                         f"resumelive と判定されるべきだが {state} だった")
        self.assertGreaterEqual(res["resumelive"][0], 0.85)

    def test_yes_button_anchor_lands_on_the_button(self):
        """アンカーオフセットが「はい」ボタン上に落ちること（実測位置と照合）。

        いいえ を押すと消費済み LIFE が丸損になるため、左右を取り違えないこと。
        """
        import autolive
        _, res = detect_file("resume_live_dialog_671x348.png")
        cx, cy = res["resumelive"][2]
        x = cx + autolive.ANCH_RESUME_YES[0]
        y = cy + autolive.ANCH_RESUME_YES[1]
        # 実測した「はい」ボタンの矩形（671x348 フレーム）
        self.assertTrue(345 <= x <= 460, f"x={x} が「はい」ボタンの外")
        self.assertTrue(255 <= y <= 282, f"y={y} が「はい」ボタンの外")


if __name__ == "__main__":
    unittest.main()
