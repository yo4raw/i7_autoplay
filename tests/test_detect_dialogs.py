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


class TestExpResultScreen(unittest.TestCase):
    """per-song Result の EXP 画面が cardx と誤判定されないこと。

    2026-08-01 実機: この画面はカードの緑ヘッダを持つため detect_card_x が拾い、
    cardx として背景タップで閉じようとして失敗し続け、25秒後に安全停止していた。
    ログ全体の警告87件中34件（最多）がこの「カードポップアップを閉じられず停滞」。
    supervisor が再起動しても同じ画面で止まるため空転トラップになっていた。
    中央タップで送る画面なので result 系として扱う。
    """

    def test_671x348_is_expresult(self):
        state, res = detect_file("exp_result_671x348.png")
        self.assertEqual("expresult", state, f"{state} と誤判定")
        self.assertGreaterEqual(res["expresult"][0], 0.90)

    def test_529x334_is_expresult(self):
        """機種差（SE）でも検出できること（variant テンプレの担保）。"""
        state, res = detect_file("exp_result_529x334.png")
        self.assertEqual("expresult", state, f"{state} と誤判定")
        self.assertGreaterEqual(res["expresult"][0], 0.90)

    def test_genuine_popups_are_not_expresult(self):
        """本物のカードポップアップ／ライブ画面を expresult と誤検出しないこと。

        誤検出すると閉じるべきポップアップを中央タップで送ろうとして進まなくなる。
        """
        import glob
        import cv2
        import autolive as AL
        imgs, thr = AL.load_templates()["expresult"]
        worst = 0.0
        pats = ["closex/*.png", "gameplay/*.png"]
        files = []
        for pat in pats:
            files += sorted(glob.glob(os.path.join(
                os.path.dirname(__file__), "corpus_raw", pat)))[:25]
        if not files:
            self.skipTest("実フレームコーパスなし（任意）")
        for p in files:
            f = cv2.cvtColor(np.array(Image.open(p).convert("RGB")),
                             cv2.COLOR_RGB2BGR)
            worst = max(worst, AL.match_best(f, imgs)[0])
        self.assertLess(worst, thr, f"本物のポップアップ等で誤検出 (max={worst:.3f})")


class TestDataUpdateDialog(unittest.TestCase):
    """「データ更新のためタイトルへ戻ります」を cardx と誤認しないこと。

    2026-08-02 実機: 100周目で出現。シアン系ヘッダを持つため cardx と誤認され、
    背景タップでは閉じられず 25 秒後に安全停止した（12時間周回が3時間41分で停止）。
    """

    def test_detected_as_dataupdate(self):
        state, res = detect_file("data_update_dialog_671x348.png")
        self.assertEqual("dataupdate", state, f"{state} と誤判定")
        self.assertGreaterEqual(res["dataupdate"][0], 0.85)

    def test_anchor_lands_on_yes(self):
        import autolive
        _, res = detect_file("data_update_dialog_671x348.png")
        cx, cy = res["dataupdate"][2]
        x = cx + autolive.ANCH_DATAUPDATE_YES[0]
        y = cy + autolive.ANCH_DATAUPDATE_YES[1]
        # 実測した「はい」ボタンの矩形（671x348）
        self.assertTrue(275 <= x <= 395, f"x={x} が「はい」の外")
        self.assertTrue(255 <= y <= 280, f"y={y} が「はい」の外")


class TestResendResultDialog(unittest.TestCase):
    """「前回のライブ結果の送信が正しく終了しませんでした」で **再送する** を選ぶこと。

    「諦める」を選ぶと直前のライブぶんのイベント pt が失われる。左右を取り違えると
    周回した成果が消えるので、着弾点を実測矩形で固定する。
    """

    def test_detected_as_resendresult(self):
        state, res = detect_file("resend_result_dialog_671x348.png")
        self.assertEqual("resendresult", state, f"{state} と誤判定")
        self.assertGreaterEqual(res["resendresult"][0], 0.85)

    def test_anchor_lands_on_resend_not_giveup(self):
        import autolive
        _, res = detect_file("resend_result_dialog_671x348.png")
        cx, cy = res["resendresult"][2]
        x = cx + autolive.ANCH_RESEND_YES[0]
        y = cy + autolive.ANCH_RESEND_YES[1]
        # 実測: 「諦める」は x≈222..330、「再送する」は x≈345..465
        self.assertTrue(345 <= x <= 465,
                        f"x={x} が「再送する」の外。「諦める」側なら pt を失う")
        self.assertTrue(255 <= y <= 280, f"y={y} がボタンの外")


class TestEventSongSelect(unittest.TestCase):
    """イベント導線の楽曲選択画面を cardx と誤認しないこと。

    2026-08-28 実機: Memorial Party のイベント楽曲リストで、上部の**薄い水色の区切り線**
    （y≈0.16・高さ2px・RGB(157,196,218)）が detect_card_x の「シアン帯」条件を満たし、
    cardx と誤判定された。背景タップでは当然閉じないので 2 秒おきに叩き続け、
    28 秒で `cardx_stuck` 安全停止。NEXT を一度も押せず周回が始まらなかった。
    """

    def test_detected_as_songselect_not_cardx(self):
        state, res = detect_file("songselect_event_671x348.png")
        self.assertEqual("songselect", state,
                         f"songselect と判定されるべきだが {state} だった")
        self.assertGreaterEqual(res["songselect"][0], 0.85)


if __name__ == "__main__":
    unittest.main()
