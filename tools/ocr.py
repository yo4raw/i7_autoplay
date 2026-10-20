#!/usr/bin/env python3
"""macOS Vision フレームワークによる切り出し OCR（ローカル完結・テーマ非依存）。

`autolive.py` の LIFE 回復（きなこパン個数の決定）で使う読み取りを提供する。
実測事実（2026-10-20、docs/device-findings.md 参照）:

- `VNRecognizeTextRequest`・言語 ja-JP/en-US・言語補正 OFF・切り出しを 3 倍拡大。
- 1 切り出しあたり 20〜25 ms。**プロセスで最初の 1 回だけ約 25 秒**かかる
  （モデル読み込み）ので、`warmup()` で空画像を投げておく。
- **1 桁の数字は落ちることがある**（数量欄の「1」、LIFE 表示の「6」「0」）。
  数量欄の「1」は `autolive.kinako_qty_is_one`（画素判定）で補い、
  LIFE 表示は `recognize(..., binarize=True)` の閾値二値化を試す。
- 全画面 OCR は重い（150〜290 ms）。ライブ中のループでは絶対に呼ばない。

Vision が import できない環境（Linux でのテスト等）では AVAILABLE=False になり、
呼び出し側は従来の「1 個で回復」に縮退する。決して例外を上げない。
"""
import cv2
import numpy as np

try:
    import Quartz  # noqa: F401
    import Vision
    from Foundation import NSData
    AVAILABLE = True
except Exception:     # ImportError だけでなく初期化失敗も安全側に倒す
    AVAILABLE = False

OCR_SCALE = 3.0        # 切り出しの拡大倍率（実測で最も読めた設定）
LANGUAGES = ("ja-JP", "en-US")


def _cgimage(arr_rgb):
    """HxWx3 uint8 RGB -> CGImage（参照のために data を保持し返す）。"""
    h, w = arr_rgb.shape[:2]
    rgb = np.ascontiguousarray(arr_rgb)
    nsd = NSData.dataWithBytes_length_(rgb.tobytes(), rgb.nbytes)
    prov = Quartz.CGDataProviderCreateWithCFData(nsd)
    img = Quartz.CGImageCreate(w, h, 8, 24, w * 3,
                               Quartz.CGColorSpaceCreateDeviceRGB(), 0,
                               prov, None, False,
                               Quartz.kCGRenderingIntentDefault)
    return img


def recognize(arr_rgb, scale=OCR_SCALE, binarize=False):
    """RGB 切り出し画像の文字を [(text, x0, y0, x1, y1)] で返す（原画像 px・左上原点）。

    - `scale`: 読み取り前の拡大倍率（小さい文字ほど上げた方が読める）。
    - `binarize=True`: 白文字（min(R,G,B) > 200）だけを残して二値化してから読む。
      「LIFE ♥ 6」のような**色付きピル上の白い小さい数字**向け（素のままだと
      1 桁を落とす）。
    - Vision 未導入・読み取り失敗時は [] を返す（呼び出し側で「読めない」扱い）。
    """
    if not AVAILABLE or arr_rgb is None or arr_rgb.size == 0:
        return []
    try:
        sub = np.ascontiguousarray(arr_rgb)
        if binarize:
            mask = (sub.min(axis=2) > 200).astype(np.uint8) * 255
            sub = cv2.cvtColor(cv2.bitwise_not(mask), cv2.COLOR_GRAY2RGB)
        if scale != 1.0:
            sub = cv2.resize(sub, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
        h, w = sub.shape[:2]
        img = _cgimage(sub)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setRecognitionLanguages_(list(LANGUAGES))
        req.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            img, None)
        handler.performRequests_error_([req], None)
        out = []
        for r in (req.results() or []):
            cands = r.topCandidates_(1)
            if not cands:
                continue
            bb = r.boundingBox()   # 左下原点・正規化
            x0 = bb.origin.x * w / scale
            y1 = (1 - bb.origin.y) * h / scale
            x1 = (bb.origin.x + bb.size.width) * w / scale
            y0 = (1 - bb.origin.y - bb.size.height) * h / scale
            out.append((str(cands[0].string()), x0, y0, x1, y1))
        return out
    except Exception:
        return []


def recognize_texts(arr_rgb, scale=OCR_SCALE, binarize=False):
    """recognize() の文字列だけを返す簡易版。"""
    return [t[0] for t in recognize(arr_rgb, scale=scale, binarize=binarize)]


def warmup():
    """モデル読み込みを済ませる（プロセスで最初の 1 回が約 25 秒かかるため）。
    起動時に**バックグラウンドスレッドから**呼ぶこと（ループを止めない）。"""
    if not AVAILABLE:
        return
    recognize(np.zeros((8, 8, 3), np.uint8))
