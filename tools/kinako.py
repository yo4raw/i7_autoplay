#!/usr/bin/env python3
"""LIFE 回復（きなこパン）・コスト・下部パネル（オート OFF 確認）の画像判定と OCR 読み取り。

課金アイテム（ステラストーン）やブリンドリンクを誤消費しないための純粋関数群。
すべての座標特定は「きなこパン行の実在確認済み位置 (`row_pos`)」を基準とし、
0.26h 下にあるステラストーン行には構造的に届かない帯だけを見る。
"""
import re

import cv2
import numpy as np

from matching import window_scale
import ocr

# きなこパンラベルから同じ行の「回復」ボタンへのフォールバックオフセット（SE/671基準px）
ANCH_KINAKO_ROW = (97.0, 28.5)
# きなこパン行の「回復」ボタンの縦許容（フレーム高に対する比。ステラ行は 0.26h 下）
RECOVER_ROW_TOL_FRAC = 0.13
# 「上限を超えています」バッジとみなす赤画素数（実測 760〜812、平常 0）
KINAKO_OVERCAP_PX = 300
# life_card_like のしきい値（回復カード 0.46〜0.48、他画面 ≤0.38）
LIFE_CARD_MIN = 0.43

_ZEN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# フレンド選択・編成画面の上部「♥-N」コストバッジを探す帯（フレーム比 y0, y1, x0, x1）
_COST_BADGE_BOX = (0.15, 0.42, 0.55, 0.85)

# 楽曲選択・編成画面の下部「ブースト / オート」設定パネルを探す帯（フレーム比 y0, y1, x0, x1）
# 671x348 楽曲選択では (0.50..0.63, 0.78..0.88)、529x334 編成では (0.11..0.28, 0.83..0.93)
_AUTO_PANEL_BOX = (0.75, 0.96, 0.08, 0.66)


def kinako_recover_point(frame_rgb, row_pos):
    """きなこパン行の「回復」ボタン中心 (x, y) をピンク色で直接探して返す。

    必ず「きなこパン行が実在する」確認を通した後に呼ぶこと。
    ラベルの接頭辞（「11周年きなこパン」等）でラベル中心が動いても、ボタン自体を
    見つけることで文言に依存せず着弾させる。
    """
    h, w = frame_rgb.shape[:2]
    r_ch = frame_rgb[:, :, 0].astype(int)
    g_ch = frame_rgb[:, :, 1].astype(int)
    b_ch = frame_rgb[:, :, 2].astype(int)
    pink = ((r_ch > 200) & (g_ch > 90) & (g_ch < 175) & (b_ch > 130) & (b_ch < 200)
            & (r_ch - g_ch > 60)).astype(np.uint8)
    n, _lbl, stats, _cent = cv2.connectedComponentsWithStats(pink, 8)
    tol = RECOVER_ROW_TOL_FRAC * h
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 0.0015 * w * h or bw <= bh:
            continue
        cx, cy = x + bw / 2.0, y + bh / 2.0
        if cx <= row_pos[0] or abs(cy - row_pos[1]) > tol:
            continue
        d = abs(cy - row_pos[1])
        if best is None or d < best[0]:
            best = (d, (cx, cy))
    if best is not None:
        return best[1]
    s = window_scale(frame_rgb)
    return (row_pos[0] + ANCH_KINAKO_ROW[0] * s,
            row_pos[1] + ANCH_KINAKO_ROW[1] * s)


def kinako_plus_point(frame_rgb, recover_pt):
    """きなこパン行の数量ステッパー `[−][ 1 ][+]` の「+」中心 (x, y) を返す。無ければ None。"""
    h, w = frame_rgb.shape[:2]
    band = int(round(0.04 * h))
    cy0 = int(round(recover_pt[1]))
    y0, y1 = max(0, cy0 - band), min(h, cy0 + band + 1)
    x0, x1 = max(0, int(recover_pt[0] - 0.15 * w)), int(recover_pt[0] - 0.04 * w)
    if x1 <= x0 or y1 <= y0:
        return None
    sub = frame_rgb[y0:y1, x0:x1].astype(int)
    r_ch, g_ch, b_ch = sub[..., 0], sub[..., 1], sub[..., 2]
    white = (r_ch > 170) & (g_ch > 170) & (b_ch > 170)
    blue = (b_ch - r_ch > 40) & (b_ch > 110) & (r_ch < 130)
    n, lbl, st, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8), 8)
    lo, hi = 0.009 * w, 0.022 * w
    best = None
    for i in range(1, n):
        x, y, bw, bh, _area = st[i]
        if not (lo <= bw <= hi and lo <= bh <= hi) or abs(int(bw) - int(bh)) > 2:
            continue
        comp = lbl[y:y + bh, x:x + bw] == i
        if comp[bh // 2].sum() < 0.7 * bw or comp[:, bw // 2].sum() < 0.7 * bh:
            continue
        if comp[0, 0] or comp[0, -1] or comp[-1, 0] or comp[-1, -1]:
            continue
        pad = max(2, int(bw) // 3)
        py0, px0 = max(0, y - pad), max(0, x - pad)
        around_white = white[py0:y + bh + pad, px0:x + bw + pad]
        around_blue = blue[py0:y + bh + pad, px0:x + bw + pad]
        if around_blue.sum() < 0.6 * max(1, (~around_white).sum()):
            continue
        cx, cy = x0 + x + bw / 2.0, y0 + y + bh / 2.0
        if best is None or cx > best[0]:
            best = (float(cx), float(cy))
    return best


def _kinako_qty_box(frame_rgb, plus_pt):
    """数量欄（「−」と「+」の間）の切り出し範囲 (x0, x1, y0, y1)。"""
    h, w = frame_rgb.shape[:2]
    return (max(0, int(plus_pt[0] - 0.06 * w)), int(plus_pt[0] - 0.012 * w),
            max(0, int(plus_pt[1] - 0.025 * h)), int(plus_pt[1] + 0.025 * h) + 1)


def kinako_qty_is_one(frame_rgb, plus_pt):
    """きなこ行の数量欄が「1」を表示しているか（画素の細い縦棒判定）。"""
    h, w = frame_rgb.shape[:2]
    x0, x1, y0, y1 = _kinako_qty_box(frame_rgb, plus_pt)
    sub = frame_rgb[y0:y1, x0:x1]
    if sub.size == 0:
        return False
    ys, xs = np.where(sub.min(axis=2) > 140)
    if len(xs) == 0:
        return False
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    return bool(bw <= 0.0045 * w + 0.5 and bh >= 0.015 * h)


def kinako_qty_ocr(frame_rgb, plus_pt):
    """数量欄の整数を OCR で読む（None=読めない。「1」は kinako_qty_is_one で補う）。"""
    if kinako_qty_is_one(frame_rgb, plus_pt):
        return 1
    x0, x1, y0, y1 = _kinako_qty_box(frame_rgb, plus_pt)
    best = None
    for text, _bx0, _by0, _bx1, _by1 in ocr.recognize(
            np.ascontiguousarray(frame_rgb[y0:y1, x0:x1])):
        m = re.fullmatch(r"\s*(\d+)\s*", text.translate(_ZEN_DIGITS))
        if m:
            best = int(m.group(1))
    return best


def kinako_per_pan_ocr(frame_rgb, row_pos):
    """きなこ行ラベル「…きなこパン：LIFE N 回復」から 1 個あたりの回復量 N を読む。"""
    h, w = frame_rgb.shape[:2]
    y0 = max(0, int(row_pos[1] - 0.065 * h))
    y1 = min(h, int(row_pos[1] + 0.055 * h))
    x0 = max(0, int(row_pos[0] - 0.14 * w))
    x1 = min(w, int(row_pos[0] + 0.26 * w))
    texts = ocr.recognize_texts(np.ascontiguousarray(frame_rgb[y0:y1, x0:x1]))
    for text in texts:
        m = re.search(r"LIFE\s*(\d+)\s*回復", text.translate(_ZEN_DIGITS))
        if m:
            return int(m.group(1))
    return None


def dialog_life_ocr(frame_rgb, row_pos):
    """LIFE 不足ダイアログ右上の「LIFE ♥ N」（現在 LIFE）を読む。読めなければ None。"""
    h, w = frame_rgb.shape[:2]
    y0 = max(0, int(row_pos[1] - 0.155 * h))
    y1 = min(h, int(row_pos[1] - 0.068 * h))
    x0 = int(0.549 * w)
    x1 = int(0.701 * w)
    if y1 <= y0 or x1 <= x0:
        return None
    sub = np.ascontiguousarray(frame_rgb[y0:y1, x0:x1])
    texts = ocr.recognize_texts(sub)
    nums = [t for t in texts
            if re.fullmatch(r"\s*\d+\s*", t.translate(_ZEN_DIGITS))]
    if not nums:
        nums = [t for t in ocr.recognize_texts(sub, binarize=True)
                if re.fullmatch(r"\s*\d+\s*", t.translate(_ZEN_DIGITS))]
    if not nums:
        return None
    return int(nums[-1].translate(_ZEN_DIGITS))


def life_cost_ocr(frame_rgb):
    """フレンド選択・編成画面の上部バッジ「♥-N」からライブの LIFE コストを読む。"""
    h, w = frame_rgb.shape[:2]
    fy0, fy1, fx0, fx1 = _COST_BADGE_BOX
    sub = np.ascontiguousarray(
        frame_rgb[int(fy0 * h):int(fy1 * h), int(fx0 * w):int(fx1 * w)])
    for text in ocr.recognize_texts(sub):
        m = re.search(r"[-−]\s*(\d+)", text.translate(_ZEN_DIGITS))
        if m:
            return int(m.group(1))
    return None


def auto_live_on_ocr(frame_rgb):
    """楽曲選択・編成画面の下部パネルが「オート ON」になっているか（CLAUDE.md 絶対規則 5）。

    - 「オート ON」は1ライブにつきブリンドリンク3個を消費するため、検出時は安全停止させる。
    - Vision OCR が使えない環境や読み取れないフレームでは False（誤停止させない）。
    - Vision が「オート ON」を1トークンで返す場合と、「オート」「ON」を別ボックスで
      同じ行に返す場合の両方を扱う（ブースト欄は OFF/2倍/3倍/10倍 で ON を持たない）。
    """
    h, w = frame_rgb.shape[:2]
    fy0, fy1, fx0, fx1 = _AUTO_PANEL_BOX
    sub = np.ascontiguousarray(
        frame_rgb[int(fy0 * h):int(fy1 * h), int(fx0 * w):int(fx1 * w)])
    if sub.size == 0:
        return False
    items = ocr.recognize(sub)
    if not items:
        return False
    for text, _x0, _y0, _x1, _y1 in items:
        norm = text.translate(_ZEN_DIGITS)
        if re.search(r"オート\s*OFF\b", norm, re.I):
            return False
        if re.search(r"オート\s*ON(?![A-Z])", norm, re.I):
            return True
    auto_boxes = [(x0, y0, x1, y1) for t, x0, y0, x1, y1 in items if "オート" in t]
    for ax0, ay0, _ax1, ay1 in auto_boxes:
        acy = (ay0 + ay1) / 2.0
        ah = max(6.0, ay1 - ay0)
        for t, x0, y0, _x1, y1 in items:
            tok = t.strip().upper()
            cy = (y0 + y1) / 2.0
            if x0 >= ax0 and abs(cy - acy) <= ah:
                if tok == "OFF":
                    return False
                if tok == "ON":
                    return True
    return False


def kinako_minus_point(frame_rgb, plus_pt):
    """同じステッパーの「−」中心。白い横棒を「+」と同じ高さ・その左 0.07〜0.11w で探す。"""
    h, w = frame_rgb.shape[:2]
    y0, y1 = max(0, int(plus_pt[1] - 0.015 * h)), int(plus_pt[1] + 0.015 * h) + 1
    x0, x1 = max(0, int(plus_pt[0] - 0.11 * w)), int(plus_pt[0] - 0.07 * w)
    sub = frame_rgb[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    ys, xs = np.where(sub.min(axis=2) > 170)
    if len(xs) < 6:
        return None
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if not (bw >= 0.009 * w and bh <= 0.012 * h + 1):
        return None
    return (float(x0 + (xs.min() + xs.max()) / 2.0), float(y0 + (ys.min() + ys.max()) / 2.0))


def kinako_over_cap(frame_rgb, recover_pt, min_px=KINAKO_OVERCAP_PX):
    """きなこ行の「回復」ボタンの真上に赤い「上限を超えています」バッジが出ているか。"""
    h, w = frame_rgb.shape[:2]
    y0, y1 = max(0, int(recover_pt[1] - 0.10 * h)), max(0, int(recover_pt[1] - 0.02 * h))
    x0, x1 = max(0, int(recover_pt[0] - 0.10 * w)), min(w, int(recover_pt[0] + 0.10 * w))
    s = frame_rgb[y0:y1, x0:x1].astype(int)
    if s.size == 0:
        return False
    red = (s[..., 0] > 180) & (s[..., 1] < 110) & (s[..., 2] < 110)
    return int(red.sum()) >= min_px


def life_card_like(frame_rgb, min_frac=LIFE_CARD_MIN):
    """「ライフを30回復しました」等の LIFE 回復カード（背景タップで閉じる）か。"""
    h, w = frame_rgb.shape[:2]
    s = frame_rgb[int(.30 * h):int(.62 * h), int(.30 * w):int(.70 * w)].astype(np.int16)
    if s.size == 0:
        return False
    m = (s.min(axis=2) > 185) & (s[..., 2] - s[..., 0] >= 12) & (s[..., 2] - s[..., 0] <= 60)
    return float(m.mean()) >= min_frac
