"""ノーツ種別対応の前提調査: 各レーンの「到達直前」ROIでノーツ色が取れるか実測（§17.9）。
円(CIRCLE)とARC_CENTERの間の数点でROIを取り、彩度の高いノーツ画素の色を分類して記録する。
タップはしない（純粋観測）。色が分離できる approach fraction を見つける。"""
import sys, time
sys.path.insert(0, 'tools')
import driver, autolive
import numpy as np
from PIL import Image

al = autolive.AutoLive(max_loops=1, dry_run=True, verbose=False)
win = al.win
ARC = autolive.ARC_CENTER
CIR = autolive.CIRCLES
FRACS = [0.5, 0.65, 0.8]   # 中心→円 の途中点
R = int(win["w"] * 0.030)

def roi_px(xf, yf):
    top, bottom = al.content; ch = bottom - top
    cx = int(win["w"] * xf); cy = int(top + yf * ch)
    return cx, cy

def classify(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 90: return "dark"
    if mx - mn < 30: return "white"
    if r >= g and r >= b: return "RED"
    if g >= r and g >= b: return "GREEN"
    return "BLUE"

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 30
t0 = time.time(); hits = 0; saved = 0
counts = {f: {"RED":0,"GREEN":0,"BLUE":0,"white":0} for f in FRACS}
while time.time() - t0 < DUR:
    f = driver.grab(win); st, _ = al.detect(f)
    if st != "gameplay":
        time.sleep(0.05); continue
    h, w = f.shape[:2]
    note_here = False
    for li, (cxf, cyf) in enumerate(CIR):
        for fr in FRACS:
            xf = cxf + (ARC[0]-cxf)*(1-fr)  # fr=1 → 円, fr=0 → 中心
            yf = cyf + (ARC[1]-cyf)*(1-fr)
            cx, cy = roi_px(xf, yf)
            x0,y0,x1,y1 = max(0,cx-R),max(0,cy-R),min(w,cx+R),min(h,cy+R)
            roi = f[y0:y1, x0:x1].reshape(-1,3).astype(int)
            if roi.size == 0: continue
            # 最も明るい数画素の平均色
            bright = roi[roi.max(axis=1) > 120]
            if len(bright) < 8: continue
            r,g,b = bright.mean(axis=0)
            c = classify(r,g,b)
            counts[fr][c] = counts[fr].get(c,0)+1
            if c in ("RED","GREEN","BLUE") and fr==0.65:
                note_here = True
                if saved < 6:
                    saved += 1
                    Image.fromarray(f).save(f"/tmp/i7dbg/color_{saved}_{c}_lane{li}.png")
    if note_here: hits += 1
    time.sleep(0.05)
print("counts by fraction:", counts, flush=True)
print("frames-with-color(@0.65):", hits, "saved:", saved, flush=True)
