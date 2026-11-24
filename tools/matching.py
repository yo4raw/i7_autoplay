#!/usr/bin/env python3
"""画面認識用の画像処理・マルチスケールテンプレ照合プリミティブ（実機接続不要）。

`autolive.py` や `tools/ops/*` のウォッチャから共通利用する純粋関数群。
ウィンドウ寸法の変化に対するスケール追従（`window_scale`）や、背景写り込みを除外した
明るさ計算（`frame_brightness`）、カードポップアップのヘッダ帯色検出（`detect_card_x`）を担う。
"""
import glob
import os

import cv2
import numpy as np

# コーパス309枚（529x334 と 671x348 の両方）を総当たりして求めた最小スケール構成。
# 0.8 を削ると PAUSE を取りこぼすため削らないこと（tests/test_dark_detect_perf.py）。
SCALES = [0.8, 0.93, 1.0, 1.08]

# 窓スケール係数の基準幅（px）。縦横比 > WIDE_ASPECT_MIN なら iPhone 16 系クラス、
# それ以外は SE クラスとみなす。基準サイズちょうどでは s=1.0。
WIDE_REF_W = 671
SE_REF_W = 529
WIDE_ASPECT_MIN = 1.75

# 明るさゲートの計測条件を固定するための「上端 38 行の置換値」。
# タイトルバー無しウィンドウの上端透過部に背後の明暗が写り込む影響を排除する。
TITLEBAR_ROWS = 38
TITLEBAR_EQUIV = 210.0


def frame_brightness(frame_rgb):
    """明るさゲート用の平均輝度。上端 TITLEBAR_ROWS 行を TITLEBAR_EQUIV に置き換えて平均する。"""
    h = frame_rgb.shape[0]
    top = min(TITLEBAR_ROWS, h)
    body = float(frame_rgb[top:].mean()) if h > top else 0.0
    return (body * (h - top) + TITLEBAR_EQUIV * top) / h


def frame_diff(a_rgb, b_rgb):
    """2フレームの縮小グレー画像の平均絶対差（静止判定用。1回 1ms 未満）。"""
    def small(f):
        g = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY)
        return cv2.resize(g, (max(1, g.shape[1] // 4), max(1, g.shape[0] // 4)),
                          interpolation=cv2.INTER_AREA).astype(np.int16)
    if a_rgb.shape != b_rgb.shape:
        return 255.0
    return float(np.abs(small(a_rgb) - small(b_rgb)).mean())


def detect_card_x(frame_rgb):
    """カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）の閉じる「×」を、ヘッダの
    シアン→グリーン帯（明るい・低赤）から位置特定する（端末非依存）。
    戻り値: × の中心ピクセル (x, y) または None。
    """
    h, w = frame_rgb.shape[:2]
    r_ch = frame_rgb[:, :, 0].astype(int)
    g_ch = frame_rgb[:, :, 1].astype(int)
    b_ch = frame_rgb[:, :, 2].astype(int)
    band = (g_ch > 180) & (r_ch < g_ch - 20) & (b_ch > 120)
    band[:int(0.08 * h)] = False
    band[int(0.55 * h):] = False
    rowsum = band.sum(axis=1)
    rows = np.where(rowsum > 0.18 * w)[0]
    if len(rows) < 2:
        return None
    y0, y1 = rows[0], rows[-1]
    cols = np.where(band[y0:y1 + 1].any(axis=0))[0]
    if len(cols) < 0.2 * w:
        return None
    return (int(cols.max() - 0.012 * w), int(y0 + 0.018 * h))


def load_template_map(templates_spec, template_dir):
    """`{key: (filename, threshold)}` から端末別バリアント `<stem>_*.png` を含む辞書を返す。"""
    out = {}
    for key, (fn, thr) in templates_spec.items():
        stem = fn[:-4] if fn.endswith(".png") else fn
        paths = sorted(glob.glob(os.path.join(template_dir, stem + "*.png")))
        imgs = [cv2.imread(p, cv2.IMREAD_COLOR) for p in paths]
        imgs = [im for im in imgs if im is not None]
        if not imgs:
            print(f"[warn] テンプレート未読込: {fn}")
            continue
        out[key] = (imgs, thr)
    return out


def window_scale_wh(w, h):
    """幅 w・高さ h の全体フレームの窓スケール係数を返す。"""
    ref = WIDE_REF_W if (h > 0 and w / h > WIDE_ASPECT_MIN) else SE_REF_W
    if w == ref:
        return 1.0
    return w / ref


def window_scale(frame):
    """全体フレーム（BGR/RGB どちらでも可）の窓スケール係数。"""
    h, w = frame.shape[:2]
    return window_scale_wh(w, h)


def match_multiscale(frame_bgr, templ, scale=None):
    """マルチスケールでテンプレ照合。最大スコアと一致中心(ピクセル)を返す。"""
    if scale is None:
        scale = window_scale(frame_bgr)
    fh, fw = frame_bgr.shape[:2]
    best = (0.0, None)
    for base in SCALES:
        s = base * scale
        t = templ
        if s != 1.0:
            t = cv2.resize(templ, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th > fh or tw > fw:
            continue
        res = cv2.matchTemplate(frame_bgr, t, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv > best[0]:
            best = (float(maxv), (maxloc[0] + tw / 2, maxloc[1] + th / 2))
    return best


def match_best(frame_bgr, imgs, scale=None):
    """複数テンプレ候補(端末別variant)のうち最良の (score, center_px) を返す。"""
    if scale is None:
        scale = window_scale(frame_bgr)
    best = (0.0, None)
    for im in imgs:
        score, pos = match_multiscale(frame_bgr, im, scale)
        if score > best[0]:
            best = (score, pos)
    return best


def match_in_box(frame_bgr, imgs, box, scale=None):
    """フレームの一部だけを照合して (score, 全画面座標の中心) を返す。

    窓スケール係数は切り出す前の全体フレームから求めて切り出し側へ渡す。
    """
    h, w = frame_bgr.shape[:2]
    if scale is None:
        scale = window_scale_wh(w, h)
    x0, y0, x1, y1 = box
    px0, py0 = int(w * x0), int(h * y0)
    sub = frame_bgr[py0:int(h * y1), px0:int(w * x1)]
    if sub.size == 0:
        return 0.0, None
    score, pos = match_best(sub, imgs, scale)
    if pos is None:
        return score, None
    return score, (pos[0] + px0, pos[1] + py0)


def match_topmost(frame_bgr, imgs, thresh, min_gap_px=18, scale=None):
    """閾値を超えるマッチのうち最も上（yが小さい）の中心を返す: (score, (x, y)) or (0, None)。"""
    if scale is None:
        scale = window_scale(frame_bgr)
    best = (0.0, None)
    for templ in imgs:
        fh, fw = frame_bgr.shape[:2]
        for base in SCALES:
            s = base * scale
            t = templ if s == 1.0 else cv2.resize(templ, None, fx=s, fy=s,
                                                  interpolation=cv2.INTER_AREA)
            th, tw = t.shape[:2]
            if th > fh or tw > fw:
                continue
            res = cv2.matchTemplate(frame_bgr, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= thresh)
            for y, x in zip(ys, xs):
                cy = y + th / 2
                if best[1] is None or cy < best[1][1] - min_gap_px:
                    best = (float(res[y, x]), (x + tw / 2, cy))
    return best
