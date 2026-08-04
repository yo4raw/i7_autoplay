"""緑ノーツの長押しの回帰テスト（実機不要）。

背景（2026-08-04 実機3ライブで実測）:
緑ノーツは**2つが緑の帯で繋がって**同じ放射線上を同じ円へ飛ぶ。頭が着いたら押し、
尾が着いたら離すのが正しい操作。従来は頭を1回タップするだけで持続点を捨てていた。

ここで守りたい不変条件:

1. **判定文字「GOOD」を緑と誤認しないこと。** GOOD は緑色で1ライブに約110回出る。
   誤認すると最大 8 秒の偽ホールドを乱発し、その間ほかのレーンを全部落とす
   （合成入力はカーソル1点なので、押しながら別の円は叩けない）
2. **判別は緑画素の「数」で行うこと。** 明るい画素の色平均や白率では GOOD と区別
   できない（実測: 緑ノーツの白率 0.00〜0.40 に対し GOOD 文字 0.37 で完全に重なる）
3. **解除はホールドの長さに依存しないこと。** 実測した長さは 0.3〜0.5 秒だったが、
   曲・イベントによって変わる。「緑が approach から消えた」で判定すれば長さを問わない
4. **既定 OFF。** 実測で MISS/BAD が悪化しないと確認するまで周回に入れない

実機フレームは `tests/frames_green/`（git 管理外）。無い環境では該当テストを skip する。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")
FRAMES = os.path.join(ROOT, "tests", "frames_green")


def read_src():
    with open(AUTOLIVE, encoding="utf-8") as fh:
        return fh.read()


def make_al():
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = {"x": 0.0, "y": 39.0, "w": 671.0, "h": 348.0}
    al.content = (38, 348 - 9)
    al.note_roi = AL.NOTE_ROI_RADIUS
    al.note_roi = AL.NOTE_ROI_RADIUS
    al.green_hold = True
    al.hold_max_sec = AL.HOLD_MAX_SEC
    al.green_since = [None] * len(AL.CIRCLES)
    al.green_px = [0] * len(AL.CIRCLES)
    al.hold_idx = None
    al.hold_start = 0.0
    al.ghold_release_at = None
    al.ghold_transit = 0.0
    al.verbose = False
    al.dry_run = True
    return al


class TestConstants(unittest.TestCase):
    def test_green_uses_its_own_approach_point(self):
        """緑は赤(0.65)と別の検色点を使うこと。

        0.65 では判定文字「GOOD」が ROI に重なる（実測 G-R=53）。0.70 なら外れる。
        """
        self.assertNotEqual(AL.GREEN_APPROACH_FRAC, AL.FLICK_APPROACH_FRAC)
        self.assertGreater(AL.GREEN_APPROACH_FRAC, AL.FLICK_APPROACH_FRAC)

    def test_green_approach_stays_before_whiteout(self):
        """0.75 以上ではノーツが白飛びして色が消える（実測 R-G が 82→29→0）。"""
        self.assertLessEqual(AL.GREEN_APPROACH_FRAC, 0.72)

    def test_threshold_separates_good_text_from_notes(self):
        """判定文字の最大 439px と本物の最低 766px の間にあること（実測）。

        位置(0.70)だけでは避けきれない。文字はタップした円の近くに出るので、
        円によっては ROI に入る。
        """
        self.assertGreater(AL.GREEN_MIN_PX, 439, "判定文字を拾ってしまう")
        self.assertLess(AL.GREEN_MIN_PX, 766, "本物の緑を取り逃す")

    def test_suppressed_after_tapping_the_same_circle(self):
        """判定文字はタップの後にしか出ない。第二の防御。"""
        self.assertGreater(AL.GREEN_SUPPRESS_SEC, 0.0)
        src = read_src()
        self.assertIn("GREEN_SUPPRESS_SEC", src)
        self.assertIn("self.note_last_tap[i] < GREEN_SUPPRESS_SEC", src)

    def test_release_threshold_has_hysteresis(self):
        """解除側を緩くしないと、通過中に一瞬途切れて早期解除する。"""
        self.assertLess(AL.GREEN_REL_PX, AL.GREEN_MIN_PX)

    def test_hold_cap_is_generous(self):
        """曲によってホールドは長い。上限で正常な長押しを切らないこと。"""
        self.assertGreaterEqual(AL.HOLD_MAX_SEC, 7.0)

    def test_default_is_off(self):
        """実測で良化を確認するまで周回に入れない。"""
        src = read_src()
        self.assertIn('"--green-hold", action="store_true"', src)
        self.assertIn("green_hold=False", src)


@unittest.skipUnless(os.path.isdir(FRAMES) and os.listdir(FRAMES),
                     "実機フレームが無い（docs/navigation.md の取得手順を参照）")
class TestApproachGreen(unittest.TestCase):
    """実機フレームでの検出。"""

    @classmethod
    def setUpClass(cls):
        import cv2
        cls.cv2 = cv2
        cls.al = make_al()

    def rgb(self, name):
        path = os.path.join(FRAMES, name)
        if not os.path.exists(path):
            return None
        bgr = self.cv2.imread(path, 1)
        return self.cv2.cvtColor(bgr, self.cv2.COLOR_BGR2RGB)

    def test_real_green_notes_are_detected(self):
        """4 円すべてで実測した緑ノーツを拾えること（実測 766〜1138px）。"""
        for i in range(len(AL.CIRCLES)):
            frame = self.rgb(f"green_c{i}.png")
            if frame is None:
                continue
            with self.subTest(circle=i):
                px = self.al._approach_green(frame, i)
                self.assertGreaterEqual(
                    px, AL.GREEN_MIN_PX,
                    f"円{i} の緑ノーツを取り逃した（{px}px）")

    def test_good_text_is_not_green(self):
        """**最重要の回帰。** 判定文字「GOOD」を緑と誤認しないこと。

        0.65 に戻すと当たってしまう（実測 G-R=53）。誤認すると 8 秒の偽ホールドで
        他レーンを全部落とす。
        """
        frame = self.rgb("good_text_c3.png")
        if frame is None:
            self.skipTest("フレームが無い")
        for i in range(len(AL.CIRCLES)):
            with self.subTest(circle=i):
                px = self.al._approach_green(frame, i)
                self.assertLess(px, AL.GREEN_MIN_PX,
                                f"円{i} で GOOD 文字を緑と誤認した（{px}px）")

    def test_only_the_expected_circle_fires(self):
        """緑ノーツのフレームで、その円以外が発火しないこと。"""
        for i in range(len(AL.CIRCLES)):
            frame = self.rgb(f"green_c{i}.png")
            if frame is None:
                continue
            with self.subTest(circle=i):
                hits = [j for j in range(len(AL.CIRCLES))
                        if self.al._approach_green(frame, j) >= AL.GREEN_MIN_PX]
                self.assertEqual([i], hits, f"想定外の円が発火: {hits}")


@unittest.skipUnless(os.path.isdir(os.path.join(ROOT, "tests", "corpus_raw", "gameplay")),
                     "コーパスが無い")
class TestNoFalsePositivesOnCorpus(unittest.TestCase):
    def test_corpus_gameplay_has_no_green(self):
        """gameplay コーパス全枚 × 4 円で緑の発火が無いこと。

        このコーパスは緑ノーツを含まない別の曲。ここで発火したら誤検出。
        """
        import glob

        import cv2
        al = make_al()
        files = sorted(glob.glob(os.path.join(
            ROOT, "tests", "corpus_raw", "gameplay", "*.png")))
        if not files:
            self.skipTest("フレームが無い")
        bad = []
        for f in files:
            bgr = cv2.imread(f, 1)
            if bgr is None:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            for i in range(len(AL.CIRCLES)):
                px = al._approach_green(rgb, i)
                if px >= AL.GREEN_MIN_PX:
                    bad.append((os.path.basename(f), i, px))
        self.assertEqual([], bad, f"緑の誤検出: {bad}")


class TestHoldStateMachine(unittest.TestCase):
    """状態機械をソースで検査する（実フレームの時系列は実機でしか作れないため）。"""

    def test_release_is_driven_by_green_absence_not_brightness(self):
        """**輝度で解除してはいけない。**

        押下で円が光り続けるので fired が立ちっぱなしになり、次のノーツと区別できない
        （旧 --holds が壊れた原因）。緑の在/不在だけで判断すること。
        """
        src = read_src()
        m = re.search(r"# 2g\).*?\n(.*?)\n        # 2p\)", src, re.S)
        self.assertIsNotNone(m, "緑ホールドの継続ブロックが見つからない")
        body = m.group(1)
        self.assertIn("self.green_since", body, "緑の在/不在を見ていない")
        self.assertNotIn("wf[", body, "輝度で解除しようとしている")
        self.assertNotIn("note_baseline", body, "輝度で解除しようとしている")

    def test_green_is_sampled_every_frame(self):
        """保持中も測り続けること。「居なくなった瞬間」が解除の合図なので。"""
        src = read_src()
        i_sample = src.index("self.green_px[i] = px")
        i_hold = src.index("# 2g)")
        self.assertLess(i_sample, i_hold,
                        "緑の計測が保持ブロックより後にある（保持中に測れない）")

    def test_transit_is_measured_not_hardcoded(self):
        """飛行時間は定数で持たず、ホールドごとに実測すること。

        機種・ウィンドウ寸法・レーン距離の差（実測 1.34 倍）を吸収するため。
        """
        src = read_src()
        self.assertIn("self.ghold_transit = max(0.05, now - self.green_since[i])", src)
        self.assertNotIn("TRANSIT_SEC", src, "飛行時間を定数で持っている")

    def test_hold_is_bounded(self):
        """誤検出しても必ず離すこと。"""
        src = read_src()
        m = re.search(r"# 2g\).*?\n(.*?)\n        # 2p\)", src, re.S)
        body = m.group(1)
        self.assertIn("self.hold_max_sec", body)
        self.assertIn('"up"', body)

    def test_release_reason_is_logged(self):
        """「上限」による解除が混じっていれば検出が効いていない証拠。

        1 ライブ回せば判別できるようにログへ出す。
        """
        src = read_src()
        self.assertIn("ホールド解除 円", src)
        self.assertIn('reason = "上限"', src)
        self.assertIn('reason = "緑が通過し切った"', src)

    def test_green_memory_cleared_on_release(self):
        """終端の緑で即座に再ホールドしないこと。"""
        src = read_src()
        m = re.search(r"# 2g\).*?\n(.*?)\n        # 2p\)", src, re.S)
        body = m.group(1)
        self.assertIn("self.green_since[i] = None", body)


if __name__ == "__main__":
    unittest.main()
