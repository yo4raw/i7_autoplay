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


class TestDarkThemeEventResult(unittest.TestCase):
    def test_dark_event_result_is_not_gameplay(self):
        """暗いイベントテーマの EVENT RESULT（pt 画面）を gameplay と誤認しないこと。

        2026-09-10 実機（KEEP OUT テーマ, mean 57 < DARK_THRESH）: 暗い側で eventresult を
        見ていなかったため gameplay 扱いになり、円の位置を盲目打鍵して 1 周あたり
        40〜130 秒を浪費し、MIN_LIVE_SEC 超過で偽クリアを二重計上していた。
        """
        state, res = detect_file("eventresult_dark_671x348.png")
        self.assertEqual("eventresult", state, res.get("eventresult"))
        # 生の平均輝度は 57（暗い側）。frame_brightness() では上端 38 行の置換で 77 になり
        # 明るい側の通常照合でも当たる。どちらの経路でも eventresult になることが要件。
        fr = np.array(Image.open(os.path.join(FRAMES, "eventresult_dark_671x348.png")).convert("RGB"))
        self.assertLess(float(fr.mean()), AL.DARK_THRESH, "生の平均が暗くなければ回帰テストにならない")


class TestBrightnessIgnoresTopStrip(unittest.TestCase):
    """明るさゲートはウィンドウ上端の透過部（背後のウィンドウ）に左右されないこと。

    2026-09-11 実機: 上端 30 行に白い Chrome が写り込み、ライブ中の平均輝度が 31 → 51 に
    上がって 0.7 秒ごとの再照合が 26ms → 297ms になり、判定フレームが 3500 → 2050 に落ちた。
    """

    def _frame(self, strip=None):
        fr = np.array(Image.open(os.path.join(FRAMES, "gameplay_dis_one_671x348.png")).convert("RGB")).copy()
        if strip is not None:
            fr[:30] = strip
        return fr

    def test_live_frame_brightness_is_stable_under_white_or_dark_strip(self):
        b0 = AL.frame_brightness(self._frame())
        b_white = AL.frame_brightness(self._frame(252))
        b_dark = AL.frame_brightness(self._frame(20))
        self.assertLess(abs(b_white - b0), 0.5)
        self.assertLess(abs(b_dark - b0), 0.5)
        self.assertLess(b0, AL.DARK_THRESH)

    def test_matches_corpus_calibration_condition(self):
        """コーパス（タイトルバー付き、上端 38 行 ≈ 210）と同じ値になること。"""
        fr = self._frame(); fr[:38] = 210
        self.assertLess(abs(AL.frame_brightness(fr) - float(fr.mean())), 0.5)


class TestContentRectIsFixed(unittest.TestCase):
    """内容矩形は固定 (TITLEBAR_ROWS, h-9) で、フレームから毎回検出しないこと。

    2026-09-11 実機: 上端の透過部に写り込む背後のウィンドウの明暗で検出結果が
    (0,347) ⇔ (38,347) と動き、内容相対の円座標が縦に 6〜9px ずれて打鍵が 500 → 360 回に落ちた。
    円の較正キャッシュと OFF_* は固定矩形 (38, h-9) で較正されている。
    """

    def test_no_dynamic_content_rect(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "autolive.py"),
                   encoding="utf-8").read()
        self.assertNotIn("detect_content_rect", src)
        self.assertNotIn("self.content = rect", src)
        self.assertEqual(38, AL.TITLEBAR_ROWS)


class TestDimLiveFrameIsGameplay(unittest.TestCase):
    """薄暗いライブフレーム（65 ≦ frame_brightness < 80）はリングが見えていれば gameplay。

    2026-09-12 深夜: Dis one. のライブ中フレームが内容輝度 35〜52 まで上がり、約 5% が 65 を
    超えて明るい側の全段照合（2.9 秒）に落ちた。打鍵が止まり、gameplay の継続時間もリセット
    されてクリア計上が漏れた（打鍵 491 回・判定 4200 フレームが 2 ライブ分として出た）。
    """
    CAL_671 = [(0.228, 0.652), (0.334, 0.823), (0.663, 0.823), (0.770, 0.652)]

    def _with_calibrated_circles(self, fn):
        saved = list(AL.CIRCLES)
        AL.CIRCLES[:] = self.CAL_671
        try:
            return fn()
        finally:
            AL.CIRCLES[:] = saved

    def test_dim_live_frame_with_rings_is_gameplay(self):
        fr = np.array(Image.open(os.path.join(FRAMES, "gameplay_dim_671x348.png")).convert("RGB")).copy()
        fr[38:] = np.clip(fr[38:].astype(int) + 20, 0, 255).astype(np.uint8)   # 内容を明るくして 65 超に
        al = AL.AutoLive.__new__(AL.AutoLive)
        al.templates = AL.load_templates(); al.verbose = False; al._last_dark_check = 0.0
        al.suppress_cardx_until = 0.0
        al.win = {"x": 0, "y": 0, "w": fr.shape[1], "h": fr.shape[0]}
        al.content = (AL.TITLEBAR_ROWS, fr.shape[0] - 9)
        b = AL.frame_brightness(fr)
        self.assertTrue(AL.DARK_THRESH <= b < AL.DIM_THRESH, f"薄暗い帯のフレームでないと回帰テストにならない: {b}")
        state, _ = self._with_calibrated_circles(lambda: al.detect(fr))
        self.assertEqual("gameplay", state)

    def test_dim_menu_without_rings_stays_on_bright_side(self):
        """リングの無い薄暗いメニュー（EVENT RESULT, frame_brightness≈77）は従来どおり明るい側で判定。"""
        state, res = self._with_calibrated_circles(lambda: detect_file("eventresult_dark_671x348.png"))
        self.assertEqual("eventresult", state)
        self.assertTrue(AL.DARK_THRESH <= res["_bright"][0] < AL.DIM_THRESH)


class TestLoginBonus(unittest.TestCase):
    def test_login_bonus_popup_is_recognised(self):
        """04:00 リセットの LOGIN BONUS ポップアップを未知画面にしないこと。

        2026-09-12 04:01 実機: ホームの上にピンクのヘッダで出るため cardx の色検出に掛からず、
        unknown_screen で安全停止して復帰経路が止まった（毎日出る）。
        """
        state, res = detect_file("login_bonus_671x348.png")
        self.assertEqual("loginbonus", state, res.get("loginbonus"))

    def test_special_login_bonus_is_recognised(self):
        """イベント期間の特別ログインボーナス（1 日 1 回）も同様。2026-09-12 04:04 実機で安全停止。"""
        state, res = detect_file("special_login_671x348.png")
        self.assertEqual("speciallogin", state, res.get("speciallogin"))


class TestTitleEventVariant(unittest.TestCase):
    def test_event_key_visual_title_is_title(self):
        """イベント開催中のタイトル（キービジュアル差し替え）でも MENU ボタンで `title` と判定すること。

        2026-09-13 04:02 実機: 04:00 のデータ更新 → 注意書き → タイトルで MENU が 0.872（しきい値 0.92）に
        落ち、unknown_screen で安全停止。runner は未知画面を「切断」と見て 05:00 まで待機し、約 24 ライブぶん
        止まった。variant `title_menu_event.png` を追加（編成画面の MENU には 0.50 で当たらない）。
        """
        state, res = detect_file("title_event_671x348.png")
        self.assertEqual("title", state, res.get("title"))


class TestHomeRibbonVariants(unittest.TestCase):
    def test_orange_event_ribbon_home_is_home_not_cardx(self):
        """イベントごとに色が変わる EVENT ラベル帯（今回はオレンジ）でもホームと判定し、
        明るいキービジュアルのシアン帯を cardx と誤検出しないこと。

        2026-09-12 04:08 実機: 旧イベントのベージュ帯テンプレが 0.717 で外れ、cardx の背景タップを
        25 秒繰り返して cardx_stuck で停止、runner まで終了した。variant `home_event_2.png` を追加。
        """
        state, res = detect_file("home_orange_671x348.png")
        self.assertEqual("home", state, res.get("home"))


class TestNormalSongselectBadge(unittest.TestCase):
    """通常ライブの楽曲選択（左下にイベントバッジ）では NEXT を押さず、バッジでイベントトップへ。

    2026-09-12 04:13 実機: ホームの EVENT リボンが無反応で、LIVE → 通常楽曲選択 → バッジ、の迂回が
    必要だった。通常楽曲選択で NEXT を押すと pt ゼロの通常ライブを回してしまう（絶対規則 3）。
    """

    def _score(self, name):
        fr = np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))
        import cv2
        return AL.match_best(cv2.cvtColor(fr, cv2.COLOR_RGB2BGR), AL.load_templates()["eventbadge"][0])[0]

    def test_badge_present_on_normal_songselect_and_absent_on_event_songselect(self):
        thr = AL.TEMPLATES["eventbadge"][1]
        self.assertGreaterEqual(self._score("songselect_normal_671x348.png"), thr)
        self.assertLess(self._score("songselect_event_671x348.png"), thr)

    def test_songselect_handler_checks_badge_before_next(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "autolive.py"), encoding="utf-8").read()
        block = src[src.index('elif state == "songselect":'):src.index('elif state == "friendselect":')]
        self.assertLess(block.index('"eventbadge"'), block.index("if self.keep_selection:"),
                        "バッジ確認は keep_selection 分岐より前で行うこと")
        self.assertLess(block.index('"eventbadge"'), block.index('res["songselect"][2]'),
                        "バッジ確認は NEXT 押下より前で行うこと")


if __name__ == "__main__":
    unittest.main()
