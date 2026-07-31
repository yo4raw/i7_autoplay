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


if __name__ == "__main__":
    unittest.main()
