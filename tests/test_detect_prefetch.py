"""明るいフレームの並列照合（prefetch）の回帰テスト（実機不要）。

背景（2026-10-11 実測）: 明るい画面の detect() は ~30 キーを1つずつ全画面・4スケールで照合し、
1回 2.5〜3.6 秒かかっていた。result / cardx は判定順の後ろなので、送りタップの実効間隔は
その秒数になっていた。対策として、明るいフレームでは BRIGHT_KEYS の照合を常駐スレッド
プールへ先に投げ、m() はその結果を判定順に読む。

ここで固定すること:
- BRIGHT_KEYS は detect() 本体の m("…") の**出現順と同じ**（投げる順＝待つ順。抜けがあると
  そのキーだけ直列照合に戻るだけだが、順序がずれると先頭の待ちが長くなる）。
- 暗いフレーム（ライブ中）では一切 prefetch しない（打鍵ループの CPU を奪わない）。
- プールはフレームごとに作らない。
- 判定結果（state と res）は直列照合と同一（実フレームで突き合わせる）。
"""
import os
import re
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")
FRAMES = os.path.join(ROOT, "tests", "frames")


def detect_body():
    with open(AUTOLIVE, encoding="utf-8") as fh:
        src = fh.read().split("\n")
    start = next(i for i, l in enumerate(src) if l.startswith("    def detect(self"))
    end = next(i for i in range(start + 1, len(src)) if src[i].startswith("    def "))
    return "\n".join(src[start:end])


def make(frame):
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.templates = AL.load_templates()
    al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
    al.content = (38, frame.shape[0] - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    return al


class _SerialPool:
    """submit() をその場で実行する（＝旧来の直列照合と同じ計算）。"""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *a):
        from concurrent.futures import Future
        self.submitted.append(a)
        f = Future()
        f.set_result(fn(*a))
        return f


class TestBrightKeysOrder(unittest.TestCase):
    def test_bright_keys_follow_m_call_order(self):
        order = []
        for k in re.findall(r'm\("([a-z]+)"\)', detect_body()):
            if k not in order:
                order.append(k)
        self.assertEqual(order, list(AL.BRIGHT_KEYS),
                         "BRIGHT_KEYS が detect() の m() の並びと違う")

    def test_every_bright_key_is_a_template(self):
        self.assertEqual([], [k for k in AL.BRIGHT_KEYS if k not in AL.TEMPLATES])


class TestPrefetchScope(unittest.TestCase):
    def setUp(self):
        self._pool = AL._MATCH_POOL
        self.fake = _SerialPool()
        AL._MATCH_POOL = self.fake

    def tearDown(self):
        AL._MATCH_POOL = self._pool

    def test_no_prefetch_on_dark_frames(self):
        """ライブ中（暗い）のフレームでは BRIGHT_KEYS の照合を投げない。

        暗い側の救済照合（DARK_RESCUE_KEYS → match_in_box）は 0.7s 間引きで
        投げてよい（2026-10-12 の並列化で意図された挙動）。BRIGHT_KEYS の
        match_best が暗いフレームで投げられると打鍵ループの CPU を奪うので
        ここだけは禁じる。"""
        fr = np.array(Image.open(os.path.join(FRAMES, "gameplay_dim_671x348.png")).convert("RGB"))
        state, _ = make(fr).detect(fr)
        self.assertEqual("gameplay", state)
        bright_submits = [a for a in self.fake.submitted
                          if getattr(a[0], "__name__", "") == "match_best"]
        self.assertEqual([], bright_submits, "暗いフレームで bright prefetch を投げた")

    def test_prefetch_on_bright_frames_gives_same_result_as_serial(self):
        """明るいフレームでは prefetch し、結果は直列照合と同一。"""
        fr = np.array(Image.open(os.path.join(FRAMES, "score_result_671x348.png")).convert("RGB"))
        state_p, res_p = make(fr).detect(fr)
        self.assertEqual(len(AL.BRIGHT_KEYS), len(self.fake.submitted))
        AL._MATCH_POOL = None          # 実プール（並列）
        try:
            state_t, res_t = make(fr).detect(fr)
        finally:
            AL._MATCH_POOL = self.fake
        self.assertEqual(state_p, state_t)
        self.assertEqual(res_p, res_t)


class TestPoolIsReused(unittest.TestCase):
    def test_match_pool_is_a_singleton(self):
        self.assertIs(AL.match_pool(), AL.match_pool())
        self.assertEqual(AL.MATCH_WORKERS, AL.match_pool()._max_workers)


if __name__ == "__main__":
    unittest.main()
