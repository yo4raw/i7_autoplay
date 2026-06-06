#!/usr/bin/env python3
"""ノーツ追跡エンジン（実験中・branch: note-tracking-engine）。

目的: ライブ中のノーツを **中心スポーンで検出 → 色/形で種別判定 → レーンへ追跡 →
到達タイミングで種別別操作（タップ/長押し/フリック/スライド）** する新エンジン。
現行の autolive.py（到達点の明るさスパイクでタップ）の限界（到達点では白く色判別不可・
タップ波紋が長押しと交絡）を、スポーン側の情報で克服することを狙う。

**重要: このゲームは4レーン**（中央レーンは無い。SCORE表示と重なる）。
レーンは下部の弧の4箇所、ノーツは上部中央スポーンから放射状に各レーンへ移動する。

現状は段階開発中: まず「検出（NoteDetector）」と「レーン割当」「可視化」を提供する。
追跡・タイミング・操作ディスパッチは順次追加する。autolive 本体には未接続（dry実験用）。

使い方:
    python tools/note_engine.py viz  <frame.png> [out.png]   # 検出結果を重ね描き
    python tools/note_engine.py scan <dir>                    # ディレクトリ内の連番フレームを解析
"""
import os
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(__file__))
import autolive as A  # content矩形やCIRCLESを流用  # noqa: E402

# --- フィールド模型（content矩形相対の小数） ---
# 4レーン = 現行 CIRCLES から中央(index2)を除いた4箇所（左端/左下/右下/右端）。
LANES = [A.CIRCLES[0], A.CIRCLES[1], A.CIRCLES[3], A.CIRCLES[4]]
# ノーツのスポーン中心（上部中央。実測でノーツ群が湧く位置。content相対）。
SPAWN = (0.49, 0.28)
# 検出対象の縦帯（スポーン〜中盤。下部のタップ円の波紋を拾わないよう円より上に限定）。
FIELD_Y0 = 0.05   # content相対。これ未満は上枠/キャラカード
FIELD_Y1 = 0.62   # これ以上はタップ円帯（波紋誤検出を避ける）
# ブロブ（ノーツ）判定
BLOB_MIN_V = 110      # min(R,G,B) > これ を「明るい（ノーツ候補）」画素
BLOB_AREA_MIN = 12
BLOB_AREA_MAX = 500


def _content_geom(win, content):
    top, bottom = content
    return win["w"], top, (bottom - top)


def detect_notes(frame_rgb, win, content):
    """1フレームからノーツ候補ブロブを検出して返す。
    戻り値: list of dict(x,y[px], lane, color, area, rgb)。x,yはフレームpx。"""
    W, top, ch = _content_geom(win, content)
    h, w = frame_rgb.shape[:2]
    mn = frame_rgb.min(axis=2)
    mask = (mn > BLOB_MIN_V).astype(np.uint8)
    y0 = int(top + FIELD_Y0 * ch)
    y1 = int(top + FIELD_Y1 * ch)
    band = np.zeros_like(mask)
    band[max(0, y0):min(h, y1), :] = 1
    mask = mask * band
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lbl, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < BLOB_AREA_MIN or area > BLOB_AREA_MAX:
            continue
        cx, cy = float(cent[i][0]), float(cent[i][1])
        ys, xs = np.where(lbl == i)
        rgb = frame_rgb[ys, xs].mean(0)
        out.append({
            "x": cx, "y": cy, "area": area,
            "rgb": tuple(int(v) for v in rgb),
            "color": classify_color(rgb),
            "lane": assign_lane(cx, cy, win, content),
        })
    return out


def classify_color(rgb):
    """スポーン付近のノーツ色を緑/赤/青/白に大まかに分類（暫定）。
    実測で要較正。白っぽい(低彩度)は 'white'（通常タップ）とみなす。"""
    r, g, b = [float(v) for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 28:
        return "white"
    if g >= r and g >= b:
        return "green"
    if b >= r and b >= g:
        return "blue"
    if r >= g and r >= b:
        return "red"
    return "white"


def assign_lane(cx, cy, win, content):
    """ブロブのスポーンからの方向に最も近いレーンindexを返す（放射移動を仮定）。"""
    W, top, ch = _content_geom(win, content)
    sx, sy = W * SPAWN[0], top + SPAWN[1] * ch
    vx, vy = cx - sx, cy - sy
    if abs(vx) < 1e-6 and abs(vy) < 1e-6:
        return -1
    import math
    ang = math.atan2(vy, vx)
    best, bi = 1e9, -1
    for i, (lxf, lyf) in enumerate(LANES):
        lx, ly = W * lxf, top + lyf * ch
        la = math.atan2(ly - sy, lx - sx)
        d = abs((ang - la + math.pi) % (2 * math.pi) - math.pi)
        if d < best:
            best, bi = d, i
    return bi


def _viz(frame_path, out_path):
    from PIL import Image, ImageDraw
    al = A.AutoLive(1, dry_run=True)
    frame = np.array(Image.open(frame_path).convert("RGB"))
    notes = detect_notes(frame, al.win, al.content)
    im = Image.open(frame_path).convert("RGB")
    d = ImageDraw.Draw(im)
    W, top, ch = _content_geom(al.win, al.content)
    # レーンとスポーンを描画
    for i, (xf, yf) in enumerate(LANES):
        x, y = W * xf, top + yf * ch
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(0, 255, 0), width=2)
        d.text((x + 7, y), f"L{i}", fill=(0, 255, 0))
    sx, sy = W * SPAWN[0], top + SPAWN[1] * ch
    d.ellipse([sx - 4, sy - 4, sx + 4, sy + 4], outline=(255, 0, 0), width=2)
    cmap = {"green": (0, 255, 0), "red": (255, 60, 60), "blue": (80, 160, 255),
            "white": (255, 255, 0)}
    for nt in notes:
        c = cmap.get(nt["color"], (255, 255, 0))
        d.ellipse([nt["x"] - 9, nt["y"] - 9, nt["x"] + 9, nt["y"] + 9], outline=c, width=2)
        d.text((nt["x"] + 9, nt["y"] - 6), f'{nt["color"][0]}{nt["lane"]}', fill=c)
    im.save(out_path)
    print(f"notes={len(notes)} -> {out_path}")
    for nt in notes:
        print(f'  lane{nt["lane"]} {nt["color"]:5} rgb{nt["rgb"]} area{nt["area"]} @({nt["x"]:.0f},{nt["y"]:.0f})')


def _scan(dirpath):
    import glob
    from PIL import Image
    al = A.AutoLive(1, dry_run=True)
    files = sorted(glob.glob(os.path.join(dirpath, "*.png")))
    import collections
    col = collections.Counter()
    lane = collections.Counter()
    for fp in files:
        frame = np.array(Image.open(fp).convert("RGB"))
        for nt in detect_notes(frame, al.win, al.content):
            col[nt["color"]] += 1
            lane[nt["lane"]] += 1
    print(f"frames={len(files)} colors={dict(col)} lanes={dict(lane)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "viz":
        _viz(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "/tmp/i7_note_viz.png")
    elif cmd == "scan":
        _scan(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
