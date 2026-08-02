"""アプリ再起動からの自動復帰の回帰テスト（実機不要）。

背景（2026-08-02 実測）:
毎日 4:00 前後に「データ更新のためタイトルへ戻ります」が割り込み、アプリはタイトルへ
戻る。そこから先を detect() が認識できず、未知画面に 25 秒停滞して安全停止し、
朝まで回すつもりの周回が 4:00 で終わっていた。

タイトル → お知らせ → ホーム → イベントトップ → 楽曲選択 の導線を FSM に足した。
ここで守りたい不変条件は3つ:

1. **休憩時間の確認ダイアログで「はい」を押さない。** 休憩時間中はイベント pt が
   一切入らないので、押すと LIFE だけ失う（きなこパン枯渇時のステラ誤消費と同種の
   「気づかず損をする」画面）
2. **breaktime を eventtop より先に判定する。** 休憩ダイアログは「イベント楽曲」
   ボタンを背後に残したまま出るため eventtop_songs が 0.943 で当たる。順序を逆に
   すると、ダイアログの裏のボタンを押し続けて停滞する
3. **固定のウィンドウ相対座標を使わない。** イベントごとにボタン位置が動くので、
   テンプレのマッチ位置を基準にクリックする

実機フレームは 2.8MB あり git に入れていない（.gitignore）。取得手順は
docs/navigation.md「アプリ再起動からの復帰導線」。無い環境では該当テストを skip する。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")
FRAMES = os.path.join(ROOT, "tests", "frames_recovery")

# 復帰導線で追加した状態
RECOVERY_STATES = ("notice", "title", "news", "home", "eventtop", "breaktime")

# 実機で撮ったフレームと、detect() が返すべき状態。
# None は「未検出でよい」（スプラッシュ/ローディング。停滞タイマ内に収まる）。
CASES = [
    ("nav01.png", "notice", "起動時の注意書き"),
    ("nav03_2.png", "title", "タイトル（TAP SCREEN 点灯）"),
    ("nav03.png", "title", "タイトル（TAP SCREEN 消灯・MENU で拾う）"),
    ("nav_title2.png", "title", "4:00 で停滞したタイトル（新イベントの背景）"),
    ("nav_title3.png", "title", "新しいタイトル背景 その1"),
    ("nav_title4.png", "title", "新しいタイトル背景 その2"),
    ("nav04.png", None, "Now Loading"),
    ("nav05.png", "news", "お知らせ"),
    ("nav06.png", "news", "お知らせ（ミラーリングのツールバーあり）"),
    ("nav07.png", "home", "ホーム"),
    ("nav08.png", "eventtop", "イベントトップ"),
    ("nav10.png", "eventtop", "イベントトップ（戻り）"),
    ("nav09.png", "breaktime", "休憩時間の確認ダイアログ"),
]


def read_src():
    with open(AUTOLIVE, encoding="utf-8") as fh:
        return fh.read()


def detect_order():
    """detect() が状態を返す順序（＝判定順。順序が仕様）。"""
    src = read_src().split("\n")
    start = next(i for i, l in enumerate(src) if l.startswith("    def detect(self"))
    end = next(i for i in range(start + 1, len(src)) if src[i].startswith("    def "))
    out = []
    for m in re.finditer(r'return "([a-z]+)", res', "\n".join(src[start:end])):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def handler_body(state, pat=None):
    """_loop() の `elif state == "<state>":` ブロック本文を返す。"""
    src = read_src().split("\n")
    pat = pat or f'elif state == "{state}":'
    start = next((i for i, l in enumerate(src) if l.strip() == pat), None)
    if start is None:
        return None
    indent = len(src[start]) - len(src[start].lstrip())
    body = []
    for line in src[start + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        body.append(line)
    return "\n".join(body)


class TestTemplatesRegistered(unittest.TestCase):
    def test_all_recovery_templates_load(self):
        """6枚のテンプレが読み込めること（ファイル名の打ち間違い検知）。"""
        tpls = AL.load_templates()
        missing = [s for s in RECOVERY_STATES if s not in tpls]
        self.assertEqual([], missing, f"読み込めないテンプレ: {missing}")

    def test_title_has_two_variants(self):
        """タイトルは明背景・暗背景の2枚を束ねること。

        MENU ボタンは不透明だが、背景の映り込みで 0.92 を割ることがある。
        """
        tpls = AL.load_templates()
        self.assertGreaterEqual(len(tpls["title"][0]), 2,
                                "title_menu.png / title_menu_dark.png の両方が要る")

    def test_title_threshold_excludes_formation(self):
        """編成画面にも MENU ボタンがあり 0.889 で当たる（実測 2026-08-03）。

        しきい値を下げると編成画面をタイトルと誤認し、TAP SCREEN の位置＝
        編成画面の別のボタンを押してしまう。
        """
        self.assertGreaterEqual(AL.TEMPLATES["title"][1], 0.92)


class TestDetectOrdering(unittest.TestCase):
    """判定順は仕様。"""

    def test_breaktime_before_eventtop(self):
        """休憩ダイアログは「イベント楽曲」ボタンを背後に残したまま出る。

        eventtop_songs が 0.943 で当たるので、逆順だとダイアログの裏のボタンを
        押し続けて停滞する。
        """
        order = detect_order()
        self.assertIn("breaktime", order)
        self.assertIn("eventtop", order)
        self.assertLess(order.index("breaktime"), order.index("eventtop"))

    def test_recovery_states_before_cardx(self):
        """お知らせ・ホームはシアン〜緑の帯を持ち detect_card_x に誤検出されうる。"""
        order = detect_order()
        self.assertIn("cardx", order)
        i_cardx = order.index("cardx")
        for s in RECOVERY_STATES:
            with self.subTest(state=s):
                self.assertIn(s, order, f"{s} が detect() に無い")
                self.assertLess(order.index(s), i_cardx,
                                f"{s} が cardx より後で判定されている")


class TestBreakTimeSafety(unittest.TestCase):
    """休憩時間中に周回すると LIFE を捨てることになる。"""

    def test_handler_uses_the_no_anchor(self):
        body = handler_body("breaktime")
        self.assertIsNotNone(body, "breaktime ハンドラが無い")
        self.assertIn("ANCH_BREAK_NO", body, "「いいえ」のアンカーを使っていない")

    def test_handler_never_presses_yes(self):
        """「はい」側のアンカーを絶対に使わないこと。"""
        body = handler_body("breaktime")
        for yes in ("ANCH_DATAUPDATE_YES", "ANCH_RESUME_YES",
                    "ANCH_REPLAY_YES", "ANCH_RESEND_YES"):
            self.assertNotIn(yes, body, f"breaktime で {yes} を押している")

    def test_handler_stops(self):
        """押した後は必ず安全停止すること（休憩中に回り続けない）。"""
        body = handler_body("breaktime")
        self.assertIn('self.stop_reason = "break_time"', body)
        self.assertIn("break", body)

    def test_break_no_anchor_points_below_and_left(self):
        """「いいえ」は本文の左下にある（実測 (-73, +100)）。

        符号を取り違えると右下の「はい」を押しかねない。
        """
        self.assertLess(AL.ANCH_BREAK_NO[0], 0, "いいえは本文より左")
        self.assertGreater(AL.ANCH_BREAK_NO[1], 0, "いいえは本文より下")


class TestNoHardcodedCoordinates(unittest.TestCase):
    """イベントごとにボタン位置が動くので、固定座標を持ってはいけない。"""

    def test_navigation_handlers_use_match_positions(self):
        for state in ("home", "eventtop"):
            with self.subTest(state=state):
                body = handler_body(state)
                self.assertIsNotNone(body, f"{state} ハンドラが無い")
                self.assertIn("click_match", body,
                              f"{state} がマッチ位置を使っていない")
                self.assertNotIn("click_window", body,
                                 f"{state} が固定のウィンドウ相対座標を使っている")


class TestRecoverLoopGuard(unittest.TestCase):
    def test_counter_is_initialised(self):
        self.assertIn("self.recovers = 0", read_src())

    def test_title_handler_is_bounded(self):
        """復帰を無限に繰り返さないこと。"""
        src = read_src()
        self.assertIn("_enter_recovery", src)
        self.assertIn("MAX_RECOVERS", src)
        self.assertIn('self.stop_reason = "recover_loop"', src)

    def test_recovery_is_counted_per_episode_not_per_frame(self):
        """フレームごとに数えてはいけない。

        タイトルは白飛びするローディングを挟んで何度も再検出される
        （実測 2026-08-03: ローディングが title として 0.897 で当たる）。
        毎フレーム数えると一瞬で上限に達して周回に戻れない。
        """
        src = read_src()
        self.assertIn("self.in_recovery = False", src)
        self.assertIn("if self.in_recovery:", src)

    def test_title_uses_menu_anchor_not_match_position(self):
        """タイトルは MENU ボタンが目印なので、そこを押してはいけない。

        押すべきは中央下の「TAP SCREEN」。マッチ位置をそのまま押すと
        MENU を開いてしまう。
        """
        body = handler_body("title", 'elif state in ("title", "notice"):')
        self.assertIn("ANCH_TITLE_TAP", body)
        self.assertLess(AL.ANCH_TITLE_TAP[0], 0, "TAP SCREEN は MENU より左")


@unittest.skipUnless(os.path.isdir(FRAMES) and os.listdir(FRAMES),
                     "実機フレームが無い（docs/navigation.md の取得手順を参照）")
class TestDetectOnRealFrames(unittest.TestCase):
    """実機フレームで detect() が期待する状態を返すこと。"""

    @classmethod
    def setUpClass(cls):
        import cv2
        cls.cv2 = cv2
        cls.al = AL.AutoLive.__new__(AL.AutoLive)
        cls.al.templates = AL.load_templates()
        cls.al.win = {"x": 0.0, "y": 39.0, "w": 671.0, "h": 348.0}
        cls.al.content = (38, 348 - 9)
        cls.al.verbose = False
        cls.al._last_dark_check = 0.0

    def test_frames(self):
        import numpy as np
        for fn, want, label in CASES:
            path = os.path.join(FRAMES, fn)
            if not os.path.exists(path):
                continue
            with self.subTest(frame=fn, label=label):
                bgr = self.cv2.imread(path, self.cv2.IMREAD_COLOR)
                self.assertIsNotNone(bgr, f"読めない: {path}")
                rgb = self.cv2.cvtColor(bgr, self.cv2.COLOR_BGR2RGB)
                state, _ = self.al.detect(np.ascontiguousarray(rgb))
                if want is None:
                    # スプラッシュ/ローディングは未検出でよい（停滞タイマ内に収まる）
                    self.assertIn(state, ("menu", "gameplay"),
                                  f"{label}: 誤って {state} と判定した")
                else:
                    self.assertEqual(want, state, f"{label}: {want} を期待")


if __name__ == "__main__":
    unittest.main()
