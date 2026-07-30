"""緑/青ノーツ判別の実現性確認(HSV)。到達直前ROI(0.65)の明るい画素をHSVで見て、
高彩度の緑/青が通常ノーツ(青白・低彩度)と分離できるか調べる。ラベル付きフレーム保存。"""
import sys, time
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver, autolive
import numpy as np, colorsys
from PIL import Image

al = autolive.AutoLive(max_loops=1, dry_run=True, verbose=False)
win = al.win; ARC = autolive.ARC_CENTER; CIR = autolive.CIRCLES
FR = 0.65; R = int(win["w"]*0.030)
def roi(frame, li):
    xf, yf = CIR[li]
    xf = xf + (ARC[0]-xf)*(1-FR); yf = yf + (ARC[1]-yf)*(1-FR)
    top, bottom = al.content; ch = bottom-top
    cx = int(win["w"]*xf); cy = int(top+yf*ch)
    h, w = frame.shape[:2]
    x0,y0,x1,y1 = max(0,cx-R),max(0,cy-R),min(w,cx+R),min(h,cy+R)
    return frame[y0:y1, x0:x1].reshape(-1,3).astype(float)

DUR = float(sys.argv[1]) if len(sys.argv)>1 else 30
t0=time.time(); buckets={"RED":0,"GREEN":0,"BLUE":0,"WHITE":0,"dark":0}; saved={"GREEN":0,"BLUE":0}
samples=[]
while time.time()-t0<DUR:
    f=driver.grab(win); st,_=al.detect(f)
    if st!='gameplay': time.sleep(0.05); continue
    for li in range(4):
        px=roi(f,li)
        if px.size==0: continue
        bright=px[px.max(axis=1)>120]
        if len(bright)<8: continue
        r,g,b=(bright.mean(axis=0)/255.0)
        h,s,v=colorsys.rgb_to_hsv(r,g,b)
        hue=h*360
        if v<0.45: lab="dark"
        elif s<0.28: lab="WHITE"            # 低彩度=通常(青白)ノーツ
        elif 90<=hue<=170: lab="GREEN"
        elif 170<hue<=265: lab="BLUE"
        elif hue<40 or hue>=320: lab="RED"
        else: lab="WHITE"
        buckets[lab]+=1
        samples.append((round(hue),round(s,2),round(v,2),lab,li))
        if lab in saved and saved[lab]<3:
            saved[lab]+=1; Image.fromarray(f).save(f"/tmp/i7dbg/hsv_{lab}_{saved[lab]}_l{li}.png")
    time.sleep(0.05)
print("buckets:",buckets,flush=True)
# 高彩度サンプルの内訳（緑/青）を一部表示
gb=[x for x in samples if x[3] in ("GREEN","BLUE")]
print("green/blue samples(hue,sat,val,lab,lane):", gb[:20], flush=True)
