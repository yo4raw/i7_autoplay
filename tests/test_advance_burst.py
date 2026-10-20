"""送り画面の連続タップ（_advance_burst）のガードの回帰テスト（実機不要）。

result / eventresult / expresult / cardx では、右側の背景 P_CARD_DISMISS (0.86, 0.50) を
短い間隔で続けて叩く。1打ごとに安いガードで「まだ同じ送り画面か」を確かめ、
**LIFE不足ダイアログ・連続ライブダイアログ（いいえ/はい）には打ち込まない**ことが要件。

cardx は色検出なので、LIFE不足・連続ライブのダイアログにも当たる（2026-10-11 実測:
detect_card_x が両ダイアログで座標を返す）。ここではそれでもガードが止めることを固定する。
"""
import os
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

FRAMES = os.path.join(ROOT, "tests", "frames")
CARD = "life_recovered_card_671x348.png"          # 「ライフを30回復しました。」
EVENTRESULT = "eventresult_tapscreen_671x348.png"  # Event Result（TAP SCREEN）
SCORE = "song_result_score_671x348.png"           # 曲ごとの Result スコアページ
REPLAY = "replay_confirm_dialog_671x348.png"      # 連続ライブ「いいえ/はい」
LIFESHORT = "lifeshort_kinako_kyomei_671x348.png"  # LIFE不足ダイアログ


def rgb(name):
    return np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))


class _Fake(AL.AutoLive):
    def __init__(self, frames):
        self.templates = AL.load_templates()
        self.win = {"x": 0, "y": 0, "w": 671, "h": 348}
        self.content = (38, 339)
        self.dry_run = False
        self.advance_alt = {}
        self._frames = list(frames)
        self.clicks = []

    def _grab(self):
        return self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]

    def _click_screen(self, px, py):
        self.clicks.append((px, py))

    def log(self, msg):
        pass


class TestGuard(unittest.TestCase):
    def test_cardx_matches_dialogs_by_colour(self):
        """前提の記録: 色検出の cardx は LIFE不足・連続ライブのダイアログにも当たる。"""
        self.assertIsNotNone(AL.detect_card_x(rgb(LIFESHORT)))
        self.assertIsNotNone(AL.detect_card_x(rgb(REPLAY)))

    def test_same_card_is_ok(self):
        al = _Fake([rgb(CARD)])
        self.assertTrue(al._advance_screen_ok("cardx", rgb(CARD), rgb(CARD)))

    def test_cardx_burst_stops_at_lifeshort(self):
        al = _Fake([rgb(CARD)])
        self.assertFalse(al._advance_screen_ok("cardx", rgb(CARD), rgb(LIFESHORT)))
        self.assertFalse(al._advance_screen_ok("cardx", rgb(LIFESHORT), rgb(LIFESHORT)),
                         "LIFE不足ダイアログを cardx の続きとして叩こうとした")

    def test_cardx_burst_stops_at_replay_dialog(self):
        al = _Fake([rgb(CARD)])
        self.assertFalse(al._advance_screen_ok("cardx", rgb(EVENTRESULT), rgb(REPLAY)))
        self.assertFalse(al._advance_screen_ok("cardx", rgb(REPLAY), rgb(REPLAY)),
                         "連続ライブダイアログを cardx の続きとして叩こうとした")

    def test_cardx_burst_stops_when_screen_changes(self):
        """Event Result → 回復カードのように別の画面に替わったら止める（次の detect に任せる）。"""
        al = _Fake([rgb(CARD)])
        self.assertFalse(al._advance_screen_ok("cardx", rgb(EVENTRESULT), rgb(CARD)))

    def test_result_burst_continues_on_result(self):
        al = _Fake([rgb(SCORE)])
        self.assertTrue(al._advance_screen_ok("result", rgb(SCORE), rgb(SCORE)))

    def test_result_burst_stops_at_dialogs(self):
        al = _Fake([rgb(SCORE)])
        for name in (LIFESHORT, REPLAY, CARD):
            with self.subTest(frame=name):
                self.assertFalse(al._advance_screen_ok("result", rgb(SCORE), rgb(name)))


class TestBurst(unittest.TestCase):
    def setUp(self):
        # 上限時間（ADVANCE_BURST_SEC）は実時間で効くので、照合が遅い負荷時（全件実行中）は
        # 6 打目の前に時間切れになり 5 打で終わる（2026-10-20 に偶発失敗）。ここで固定したいのは
        # 「何打叩くか・どこを叩くか」なので、時間の上限は十分大きくして回数の上限だけで止める。
        self._sleep = AL.time.sleep
        AL.time.sleep = lambda s: None
        self._burst_sec = AL.ADVANCE_BURST_SEC
        AL.ADVANCE_BURST_SEC = 600.0

    def tearDown(self):
        AL.time.sleep = self._sleep
        AL.ADVANCE_BURST_SEC = self._burst_sec

    def test_burst_taps_only_the_right_side_point(self):
        al = _Fake([rgb(CARD)])
        n = al._advance_burst("cardx", rgb(CARD))
        self.assertEqual(AL.ADVANCE_BURST_TAPS, n)
        x = al.win["w"] * AL.P_CARD_DISMISS[0]
        y = al.win["h"] * AL.P_CARD_DISMISS[1]
        self.assertEqual([(x, y)] * n, al.clicks)

    def test_burst_never_taps_into_lifeshort(self):
        """回復カード → LIFE不足ダイアログに替わったら1打も叩かない。"""
        al = _Fake([rgb(LIFESHORT)])
        self.assertEqual(0, al._advance_burst("cardx", rgb(CARD)))
        self.assertEqual([], al.clicks)

    def test_burst_never_taps_into_replay_dialog(self):
        al = _Fake([rgb(REPLAY)])
        self.assertEqual(0, al._advance_burst("cardx", rgb(EVENTRESULT)))
        self.assertEqual([], al.clicks)
        al = _Fake([rgb(REPLAY)])
        self.assertEqual(0, al._advance_burst("eventresult", rgb(EVENTRESULT)))
        self.assertEqual([], al.clicks)

    def test_burst_waits_for_a_still_frame(self):
        """動いている（2枚の差が大きい）間は叩かない。"""
        import itertools
        al = _Fake([rgb(CARD)])
        frames = itertools.cycle([rgb(SCORE), rgb(CARD)])
        al._grab = lambda: next(frames)
        self.assertEqual(0, al._advance_burst("cardx", rgb(CARD)))
        self.assertEqual([], al.clicks)


if __name__ == "__main__":
    unittest.main()
