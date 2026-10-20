"""NOTE_MIN_GAP/NOTE_REARM_FACTOR（速い曲対応の再武装）の回帰テスト。

実機に触れず、`_roi_white_frac` の戻り値をシナリオ化して
「デバウンス内でも一度下がれば次ノーツを拾う」ことを検証する。
2026-10-12: NOTE_DEBOUNCE_SEC=0.18 の固定ゲートで、16分連打（~150ms間隔）の
後続ノーツが発火しなかったことが実機で判明した。
"""
import os
import sys
import time
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL

DEFAULT_CIRCLES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]


def make_al(taps):
    """_gameplay_timing を単体で動かすための最小スタブ。"""
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = {"x": 0, "y": 0, "w": 671.0, "h": 348.0}
    al.content = (38, 348 - 9)
    al.jitter = None
    al.note_roi = AL.NOTE_ROI_RADIUS
    al.note_trigger = AL.NOTE_TRIGGER_FRAC
    al.note_lead = AL.NOTE_ROI_LEAD
    al.note_baseline = [0.05] * 4
    al.note_hi_frames = [0] * 4
    al.note_last_tap = [0.0] * 4
    al.note_rearmed = [True] * 4
    al.note_red_seen = [0.0] * 4
    al.green_px = [0] * 4
    al.green_since = [None] * 4
    al.green_peak = [0] * 4
    al.hold_idx = None
    al.hold_point = None
    al.hold_start = 0.0
    al.hold_max_sec = 8.0
    al.hold_release_at = None
    al.ghold_release_at = None
    al.ghold_transit = 0.0
    al.predict = False
    al.flick = False
    al.green_hold = False
    al.holds = False
    al.tap_count = 0
    al.frame_count = 0
    al.last_input_ts = 0.0
    al.tracker = None
    al.forecast = None
    al._ne = None
    al.verbose = False
    al._keepalive = lambda now: None
    al.click_content = lambda xf, yf: taps.append(al._now)
    al._press = lambda *a, **k: None
    return al


def run_frames(al, script):
    """script: [(t, [wf0..wf3]), ...] を順に流す。"""
    for t, wf in script:
        al._now = t
        al._wf = wf
        with mock.patch.object(al, "_roi_white_frac",
                               side_effect=lambda frame, idx: al._wf[idx]):
            al._gameplay_timing(np.zeros((348, 671, 3), np.uint8), t)


class TestNoteRearm(unittest.TestCase):
    def tearDown(self):
        AL.CIRCLES[:] = list(DEFAULT_CIRCLES)

    def test_second_note_inside_debounce_fires_after_dip(self):
        """デバウンス(0.18s)内でも、白率が一度十分下がれば次ノーツを拾う。

        16分連打（~150ms間隔、180bpm）相当のシナリオ。
        """
        taps = []
        al = make_al(taps)
        AL.CIRCLES[:] = list(DEFAULT_CIRCLES)
        s = [
            (1.000, [0.30, 0.05, 0.05, 0.05]),  # ノーツ到達 → 発火
            (1.050, [0.10, 0.05, 0.05, 0.05]),  # 波紋の残光（0.05+0.06*0.35=0.071より上→未再武装）
            (1.090, [0.05, 0.05, 0.05, 0.05]),  # ベースラインに戻る → 再武装
            (1.140, [0.30, 0.05, 0.05, 0.05]),  # 次ノーツ到達（+140ms < 180ms）
            (1.200, [0.05, 0.05, 0.05, 0.05]),
        ]
        run_frames(al, s)
        self.assertEqual(len(taps), 2)
        self.assertAlmostEqual(taps[1], 1.140, places=3)

    def test_no_dip_means_no_refire(self):
        """下がらずに高いままの場合、デバウンス内は二重発火しない。

        タップ波紋で wf が下がり切らずに残った場合の従来と同じ挙動。
        """
        taps = []
        al = make_al(taps)
        s = [
            (1.000, [0.30, 0.05, 0.05, 0.05]),
            (1.050, [0.10, 0.05, 0.05, 0.05]),  # 0.10 > 0.05+0.06*0.35 → 未再武装
            (1.100, [0.09, 0.05, 0.05, 0.05]),  # 残光が抜けきらない
            (1.150, [0.08, 0.05, 0.05, 0.05]),
            (1.160, [0.30, 0.05, 0.05, 0.05]),  # 再発火を狙うが未再武装
        ]
        run_frames(al, s)
        self.assertEqual(len(taps), 1)

    def test_slow_song_unchanged(self):
        """ゆったりした曲（発火間隔 > 0.18s）は従来どおり1ノーツ1打鍵。"""
        taps = []
        al = make_al(taps)
        s = [
            (1.000, [0.30, 0.05, 0.05, 0.05]),
            (1.050, [0.05, 0.05, 0.05, 0.05]),
            (1.250, [0.30, 0.05, 0.05, 0.05]),  # +250ms > 180ms
        ]
        run_frames(al, s)
        self.assertEqual(len(taps), 2)

    def test_min_gap_floor_blocks_immediate_refire(self):
        """再武装していても NOTE_MIN_GAP_SEC 未満では発火しない。"""
        taps = []
        al = make_al(taps)
        s = [
            (1.000, [0.30, 0.05, 0.05, 0.05]),
            (1.020, [0.05, 0.05, 0.05, 0.05]),  # 下がった → 再武装（この時点で t+20ms）
            (1.050, [0.30, 0.05, 0.05, 0.05]),  # 発火は +50ms < 90ms なので却下
        ]
        run_frames(al, s)
        self.assertEqual(len(taps), 1)


if __name__ == "__main__":
    unittest.main()
