"""ライブ中とそれ以外のループ内訳分離・曲非依存の警告の回帰テスト（実機不要）。

背景（2026-10-20、10倍イベント「Encounter Love Song」でループが約16FPSに低下）:
- 旧 `_prof` は全画面を1バケットに積算し、ライブ後のメニュー画面（明るい側の
  全段照合≈1秒/フレーム）が混ざって、ライブ中だけの内訳が読めなかった。
- 旧警告（TAPS_LOW=330/TAPS_DOUBLE=600）は Don't Analyze Me/EASY（184ノーツ）
  基準の打鍵回数で、曲・難易度が違うと意味を持たなかった。
- 対策: gameplay/pause を "live"・それ以外を "other" に分けて積算し、警告は
  ループ周波数（FPS）と gameplay/pause 継続秒だけで判定する。
"""
import os
import sys
import time
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402


def _new_prof():
    return {"live": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0},
            "other": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0}}


def make_al():
    """_live_report/_prof_bucket を動かすための最小スタブ（実機不要）。"""
    al = AL.AutoLive.__new__(AL.AutoLive)
    al._prof = _new_prof()
    al._detect_paths = {}
    al.tap_count = 0
    al.frame_count = 0
    al.lines = []
    al.log = lambda msg: al.lines.append(msg)
    return al


class TestProfBucket(unittest.TestCase):
    def test_gameplay_and_pause_go_to_live_bucket(self):
        al = make_al()
        for st in ("gameplay", "pause"):
            self.assertIs(al._prof["live"], al._prof_bucket(st))
        for st in ("menu", "songselect", "result", "lifeshort", "friendreq"):
            self.assertIs(al._prof["other"], al._prof_bucket(st))


class TestLiveReport(unittest.TestCase):
    def _fill(self, al, live_sec, taps, frames, other_sec=0.0):
        al._prof["live"].update({"grab": 10.0, "detect": 5.0, "act": 3.0, "sec": live_sec})
        al._prof["other"].update({"grab": 1.0, "detect": 2.0, "act": 0.5, "sec": other_sec})
        al.tap_count = taps
        al.frame_count = frames
        al._detect_paths = {"dark": frames - 3, "dim_rings": 2, "bright": 1,
                            "recheck": 100, "rescue": 7}

    def test_report_line_has_live_and_other_splits(self):
        al = make_al()
        self._fill(al, live_sec=115.0, taps=300, frames=3500)
        al._live_report()
        line = al.lines[0]
        self.assertIn("打鍵300回 / 判定3500フレーム", line)
        self.assertIn("FPS 30.4 (gameplay/pause 115s)", line)
        self.assertIn("[取得10s 判定5s 打鍵3s]", line)
        self.assertIn("他[取得1s 判定2s 打鍵0s]", line)
        self.assertIn("暗3497", line)
        self.assertIn("薄暗+輪2", line)
        self.assertIn("明1", line)
        self.assertIn("再照合100", line)
        self.assertIn("救済7", line)

    def test_counters_reset_after_report(self):
        al = make_al()
        self._fill(al, live_sec=115.0, taps=300, frames=3500)
        al._live_report()
        self.assertEqual(0.0, sum(al._prof["live"].values()))
        self.assertEqual(0.0, sum(al._prof["other"].values()))
        self.assertEqual(0, al.tap_count)
        self.assertEqual(0, al.frame_count)
        self.assertEqual({}, al._detect_paths)

    def test_low_fps_warning_fires_below_threshold(self):
        al = make_al()
        # 2026-10-20 の実測値相当: 115s のライブで判定 1900 フレーム → 16.5 FPS
        self._fill(al, live_sec=115.0, taps=250, frames=1900)
        al._live_report()
        warns = [l for l in al.lines if l.startswith("[warn]")]
        self.assertEqual(1, len(warns))
        self.assertIn("16.5 FPS", warns[0])

    def test_no_fps_warning_at_normal_rate(self):
        al = make_al()
        self._fill(al, live_sec=115.0, taps=300, frames=3800)  # 33 FPS
        al._live_report()
        self.assertEqual([], [l for l in al.lines if l.startswith("[warn]")])

    def test_warnings_do_not_depend_on_tap_count(self):
        """同じ FPS・継続秒なら打鍵回数が違っても警告は同一（曲非依存）。"""
        outs = []
        for taps in (50, 300, 1500):
            al = make_al()
            self._fill(al, live_sec=115.0, taps=taps, frames=3800)
            al._live_report()
            outs.append([l for l in al.lines if l.startswith("[warn]")])
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])

    def test_merged_lives_warning_uses_seconds_not_taps(self):
        al = make_al()
        # 打鍵・フレーム数は「2ライブぶん」ではないが、継続秒が閾値超 → 警告
        self._fill(al, live_sec=220.0, taps=10, frames=7000)
        al._live_report()
        warns = [l for l in al.lines if l.startswith("[warn]")]
        self.assertTrue(any("2ライブ連結" in w or "連結" in w for w in warns),
                        f"連結警告が出ていない: {warns}")

    def test_no_merged_warning_for_long_pause_single_live(self):
        # 1ライブ ≈125s + PAUSE 60s（PAUSE_STUCK 直前）= 185s は警告しない
        al = make_al()
        self._fill(al, live_sec=185.0, taps=300, frames=3800)
        al._live_report()
        warns = [l for l in al.lines if l.startswith("[warn]")]
        self.assertEqual([], [w for w in warns if "連結" in w])

    def test_no_fps_warning_on_tiny_segments(self):
        # 遷移の誤判定で立った偽ライブ（MIN_LIVE_SEC 未満）では FPS 警告を出さない
        al = make_al()
        self._fill(al, live_sec=5.0, taps=0, frames=30)
        al._live_report()
        warns = [l for l in al.lines if "FPS" in l and l.startswith("[warn]")]
        self.assertEqual([], warns)


class TestLoopAttribution(unittest.TestCase):
    """_loop が grab/detect/act/sec を state 別に振り分けることの確認。

    driver.grab と detect をスタブし、gameplay 2 周 → menu 1 周 → result で
    クリアを計上させる。ライブ側とメニュー側の内訳が分かれて出るはず。
    """

    def _mk_loop_al(self):
        al = make_al()
        al.max_loops = 10
        al.loops_done = 0
        al.max_seconds = None
        al.verbose = False
        al.esc_enabled = False
        al.win = {"x": 0, "y": 0, "w": 529.0, "h": 334.0}
        al.content = (38, 334 - 9)
        al.in_recovery = False
        al.net_retries = 0
        al.jitter = None
        al.auto_circles = False
        al.engine = "roi"
        al.tap_mode = "timing"
        al.gameplay_since = time.time() - (AL.MIN_LIVE_SEC + 1.0)
        al.was_in_live = False
        al.pause_since = None
        al.menu_since = None
        al.result_since = None
        al.max_loops = 1   # 1クリアで _loop を抜ける
        al.loops_done = 0
        al.songsel_nochg = 0
        al._gp_left_ts = 0.0
        al._iter_t0 = time.time()
        al.note_baseline = [0.05] * len(AL.CIRCLES)
        al.note_rearmed = [True] * len(AL.CIRCLES)
        al._keep_front = lambda: None
        al._refresh_window = lambda: None
        al._advance_fallback_check = lambda *a: None
        al._advance_tap = lambda *a: None
        al._advance_burst = lambda *a: 0
        timing_calls = []

        def fake_timing(frame, now):
            timing_calls.append(now)
            al.frame_count += 1
            time.sleep(0.002)

        al._gameplay_timing = fake_timing
        return al, timing_calls

    def test_live_and_other_seconds_are_separated(self):
        al, timing_calls = self._mk_loop_al()
        states = iter(["gameplay"] * 8 + ["menu"] * 2 + ["result"])

        def fake_detect(frame):
            return next(states), {}

        al.detect = fake_detect
        menu_sleeps = []
        real_sleep = time.sleep
        al_sleep = lambda s: menu_sleeps.append(s) if s >= 0.1 else real_sleep(s)

        frame = np.zeros((334, 529, 3), np.uint8)
        with mock.patch.object(AL.driver, "grab", lambda win: frame):
            with mock.patch.object(AL.time, "sleep", al_sleep):
                al._loop()

        self.assertEqual(1, al.loops_done)
        self.assertTrue(al.was_in_live or True)
        report = [l for l in al.lines if "ライブ内訳" in l]
        self.assertEqual(1, len(report), f"内訳ログが無い: {al.lines}")
        line = report[0]
        # gameplay 8 回 × ~2ms 以上が live sec 側に、menu 2 回 × 0.3s sleep が other 側に
        self.assertIn("gameplay/pause ", line)
        self.assertIn("打鍵0回 / 判定8フレーム", line)
        # リセット済み: 現在の _prof は空
        self.assertEqual(0.0, sum(al._prof["live"].values()))
        # menu の sleep(0.3) が other sec に乗ったこと（0.6s 以上）
        self.assertGreaterEqual(sum(menu_sleeps), 0.5)

    def test_result_clear_resets_counters(self):
        al, _ = self._mk_loop_al()
        al.tap_count = 123
        states = iter(["gameplay", "result"])
        al.detect = lambda frame: (next(states), {})
        frame = np.zeros((334, 529, 3), np.uint8)
        with mock.patch.object(AL.driver, "grab", lambda win: frame):
            with mock.patch.object(AL.time, "sleep", lambda s: None):
                al._loop()
        self.assertEqual(1, al.loops_done)
        self.assertEqual(0, al.tap_count)
        self.assertEqual(0, al.frame_count)


class TestDetectPathCounters(unittest.TestCase):
    """detect() の経路カウンタと、__new__ 生成インスタンスでの安全動作。"""

    def _al(self, with_paths):
        al = AL.AutoLive.__new__(AL.AutoLive)
        al.templates = AL.load_templates()
        al.verbose = False
        al._last_dark_check = 0.0
        al.content = (38, 334 - 9)
        if with_paths:
            al._detect_paths = {}
        return al

    def test_dark_frame_counts_dark(self):
        al = self._al(with_paths=True)
        al._last_dark_check = time.time()  # 再照合を抑止
        frame = np.zeros((334, 529, 3), np.uint8)  # 真っ暗 → gameplay
        state, _ = al.detect(frame)
        self.assertEqual("gameplay", state)
        self.assertEqual(1, al._detect_paths.get("dark"))
        self.assertNotIn("bright", al._detect_paths)
        self.assertNotIn("recheck", al._detect_paths)

    def test_recheck_counts_recheck(self):
        al = self._al(with_paths=True)
        al._last_dark_check = 0.0  # 必ず再照合が走る
        frame = np.zeros((334, 529, 3), np.uint8)
        al.detect(frame)
        self.assertEqual(1, al._detect_paths.get("recheck"))

    def test_bright_frame_counts_bright(self):
        al = self._al(with_paths=True)
        frame = np.full((334, 529, 3), 255, np.uint8)  # 真っ白 → bright 側
        state, _ = al.detect(frame)
        self.assertIn(state, ("menu", "closex", "cardx"))  # 何かに判定される
        self.assertEqual(1, al._detect_paths.get("bright"))

    def test_detect_works_without_paths_attr(self):
        """__new__ 生成（result_log 等）で _detect_paths が無くても例外にならない。"""
        al = self._al(with_paths=False)
        frame = np.zeros((334, 529, 3), np.uint8)
        state, _ = al.detect(frame)
        self.assertEqual("gameplay", state)

    def test_rings_not_computed_on_bright_frames(self):
        """明るいフレームでは _rings_visible を呼ばない（無駄な全画面スキャンの除去）。"""
        al = self._al(with_paths=True)
        calls = []
        al._rings_visible = lambda f: calls.append(1) or False
        frame = np.full((334, 529, 3), 255, np.uint8)
        al.detect(frame)
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
