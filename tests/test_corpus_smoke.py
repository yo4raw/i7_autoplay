import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE

CORPUS = os.path.join(os.path.dirname(__file__), "corpus_raw", "gameplay")


@unittest.skipUnless(os.path.isdir(CORPUS), "実フレームコーパスなし（任意）")
class TestCorpusSmoke(unittest.TestCase):
    def test_detect_functions_run_on_real_frames(self):
        from PIL import Image
        files = sorted(glob.glob(os.path.join(CORPUS, "*.png")))[:30]
        self.assertGreater(len(files), 0)
        for fp in files:
            frame = np.array(Image.open(fp).convert("RGB"))
            h, w = frame.shape[:2]
            win = {"x": 0, "y": 0, "w": w, "h": h}
            content = (38, h - 9)
            NE.detect_notes(frame, win, content)     # クラッシュしないこと
            NE.detect_circles(frame, win, content)   # 同上

# 実フレームコーパスの各ディレクトリ名 = そのフレームの正しい状態。
# **例外**: result/092648_enter.png は per-song Result の EXP 画面で、`expresult` が
# 正しい（`expresult` は仕様上 `result` より先に判定される）。
CORPUS_ROOT = os.path.join(os.path.dirname(__file__), "corpus_raw")
STATE_EXCEPTIONS = {"result/092648_enter.png": "expresult"}


@unittest.skipUnless(os.path.isdir(CORPUS_ROOT), "実フレームコーパスなし（任意）")
class TestCorpusStatesUnchanged(unittest.TestCase):
    """実フレームの判定結果を固定する（検出まわりの変更が挙動を変えていないことの歯止め）。

    `SCALES` の段数・テンプレの閾値・`detect()` の判定順は、どれも「速くしたい」「1画面
    直したい」という理由で触られやすい。しかしどれも**全画面の判定に効く**ため、片手落ちの
    変更が別の画面を静かに壊す。ここで実フレームの判定を丸ごと突き合わせておけば、
    その手の巻き添えが必ず落ちる。

    例: 2026-08-29 に `SCALES` を 6段→3段へ削った（実測で使われていない値を除去）。
    削りすぎると閾値を割って検出できなくなるが、その退行はこのテストが捕まえる。
    """

    def test_every_corpus_frame_detects_as_its_directory(self):
        from PIL import Image
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import autolive as AL
        templates = AL.load_templates()
        checked = 0
        wrong = []
        for d in sorted(glob.glob(os.path.join(CORPUS_ROOT, "*"))):
            if not os.path.isdir(d):
                continue
            expected_dir = os.path.basename(d)
            for fp in sorted(glob.glob(os.path.join(d, "*.png")))[:2]:
                rel = f"{expected_dir}/{os.path.basename(fp)}"
                expected = STATE_EXCEPTIONS.get(rel, expected_dir)
                frame = np.array(Image.open(fp).convert("RGB"))
                al = AL.AutoLive.__new__(AL.AutoLive)
                al.templates = templates
                al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
                al.content = (38, frame.shape[0] - 9)
                al.verbose = False
                al._last_dark_check = 0.0
                state, _ = al.detect(frame)
                checked += 1
                if state != expected:
                    wrong.append(f"{rel}: {expected} のはずが {state}")
        self.assertGreater(checked, 20, "コーパスが少なすぎて歯止めにならない")
        self.assertEqual([], wrong, "実フレームの判定が変わった:\n  " + "\n  ".join(wrong))
