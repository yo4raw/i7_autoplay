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
