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
# 注: autolive とは相互利用するため、ここでは **import しない**（循環import回避）。
# autolive 側が note_engine を import する。CLI関数内でのみ autolive を遅延importする。

# --- フィールド模型（content矩形相対の小数） ---
# 4レーンのタップ円（x=ウィンドウ幅相対 / y=content高相対）。
# autolive.CIRCLES（右2円ズレ補正 2026-06-07 済み）と同値。autolive からは
# Tracker(..., lanes=CIRCLES)/detect_notes(..., lanes=CIRCLES) で実値（自動
# キャリブレーション後を含む）が渡されるため、これは単体CLI用の既定値。
LANES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
DARK_THRESH = 65.0  # autolive と同値（live判定用）
# ノーツのスポーン中心（上部中央。実測でノーツ群が湧く位置。content相対）。
# 実測: ノーツ track の開始は y_px≈55（content相対≈0.06）、x≈336（≈0.50）。
SPAWN = (0.50, 0.06)
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


def detect_notes(frame_rgb, win, content, lanes=None):
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
            "lane": assign_lane(cx, cy, win, content, lanes),
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


def assign_lane(cx, cy, win, content, lanes=None):
    """ブロブのスポーンからの方向に最も近いレーンindexを返す（放射移動を仮定）。"""
    W, top, ch = _content_geom(win, content)
    sx, sy = W * SPAWN[0], top + SPAWN[1] * ch
    vx, vy = cx - sx, cy - sy
    if abs(vx) < 1e-6 and abs(vy) < 1e-6:
        return -1
    import math
    ang = math.atan2(vy, vx)
    best, bi = 1e9, -1
    for i, (lxf, lyf) in enumerate(LANES if lanes is None else lanes):
        lx, ly = W * lxf, top + lyf * ch
        la = math.atan2(ly - sy, lx - sx)
        d = abs((ang - la + math.pi) % (2 * math.pi) - math.pi)
        if d < best:
            best, bi = d, i
    return bi


class Tracker:
    """フレーム間でブロブを対応付け、動くノーツだけを抽出してレーン/ETAを推定する。
    静止物(PAUSE/円フチ/端)は変位ゼロなので is_note=False で除外される。"""

    GATE = 34.0          # 対応付け距離ゲート(px)
    MISS_MAX = 2         # この回数連続で未対応なら track 終了
    MOVE_DISP = 30.0     # これ以上動いた track を「動くもの」とみなす
    OUTWARD_MIN = 18.0   # スポーンから外側へこれ以上進んだら note 候補

    def __init__(self, win, content, lanes=None):
        self.win = win
        self.content = content
        self.lanes = list(lanes) if lanes else list(LANES)
        W, top, ch = _content_geom(win, content)
        self.sx, self.sy = W * SPAWN[0], top + SPAWN[1] * ch
        self.lane_px = [(W * xf, top + yf * ch) for xf, yf in self.lanes]
        self.tracks = {}   # id -> dict
        self._nid = 0

    def update(self, blobs, t):
        """blobs(detect_notes出力) と時刻 t で track 群を更新。アクティブ track list を返す。"""
        W, top, ch = _content_geom(self.win, self.content)
        blobs = [b for b in blobs if 8 < b["x"] < W - 8]  # 端の誤検出除外
        used = set()
        for tr in self.tracks.values():
            lx, ly = tr["pts"][-1][1], tr["pts"][-1][2]
            best, bj = self.GATE, -1
            for j, b in enumerate(blobs):
                if j in used:
                    continue
                d = ((b["x"] - lx) ** 2 + (b["y"] - ly) ** 2) ** 0.5
                if d < best:
                    best, bj = d, j
            if bj >= 0:
                b = blobs[bj]
                tr["pts"].append((t, b["x"], b["y"]))
                tr["miss"] = 0
                tr["colors"].append(b["color"])
                used.add(bj)
            else:
                tr["miss"] += 1
        for j, b in enumerate(blobs):
            if j in used:
                continue
            self.tracks[self._nid] = {
                "id": self._nid, "pts": [(t, b["x"], b["y"])],
                "miss": 0, "colors": [b["color"]],
            }
            self._nid += 1
        # 終了 track を回収
        for tid in [k for k, v in self.tracks.items() if v["miss"] > self.MISS_MAX]:
            del self.tracks[tid]
        return [self._annotate(tr) for tr in self.tracks.values()]

    def _annotate(self, tr):
        """track に is_note/lane/eta/速度を付与して返す（参照を汚さずdictコピー）。"""
        pts = tr["pts"]
        p0, p1 = pts[0], pts[-1]
        disp = ((p1[1] - p0[1]) ** 2 + (p1[2] - p0[2]) ** 2) ** 0.5
        d0 = ((p0[1] - self.sx) ** 2 + (p0[2] - self.sy) ** 2) ** 0.5
        d1 = ((p1[1] - self.sx) ** 2 + (p1[2] - self.sy) ** 2) ** 0.5
        is_note = len(pts) >= 3 and disp > self.MOVE_DISP and (d1 - d0) > self.OUTWARD_MIN
        lane, eta, speed = -1, None, 0.0
        if is_note:
            # 速度（直近数点）
            rec = pts[-min(5, len(pts)):]
            dt = rec[-1][0] - rec[0][0]
            if dt > 1e-3:
                vx = (rec[-1][1] - rec[0][1]) / dt
                vy = (rec[-1][2] - rec[0][2]) / dt
                speed = (vx * vx + vy * vy) ** 0.5
                # 速度方向に最も近いレーンへ割当（放射移動）
                import math
                vang = math.atan2(vy, vx)
                best = 1e9
                for i, (lx, ly) in enumerate(self.lane_px):
                    la = math.atan2(ly - self.sy, lx - self.sx)
                    dd = abs((vang - la + math.pi) % (2 * math.pi) - math.pi)
                    if dd < best:
                        best, lane = dd, i
                if lane >= 0 and speed > 1e-3:
                    lx, ly = self.lane_px[lane]
                    rem = ((lx - p1[1]) ** 2 + (ly - p1[2]) ** 2) ** 0.5
                    eta = rem / speed
        # 種別の暫定: track中で最も多い非white色（あれば）
        nonwhite = [c for c in tr["colors"] if c != "white"]
        ntype = max(set(nonwhite), key=nonwhite.count) if nonwhite else "tap"
        return {"id": tr["id"], "pts": pts, "is_note": is_note, "lane": lane,
                "eta": eta, "speed": speed, "type": ntype, "pos": (p1[1], p1[2])}


FORECAST_STALE_SEC = 0.6   # ETA不明の予報を最後の目撃からこの秒数で破棄
FORECAST_GRACE_SEC = 0.35  # 到達予測を過ぎてもこの猶予内は保持（追跡帯を抜けた後の到達待ち）


class TypeForecast:
    """レーン別の「次に到達するノーツ」予報。Tracker の annotation を毎フレーム取り込み、
    roi 発火時に peek/consume で種別と到達予測を返す。予報は「あれば使う」情報で
    発火判定には関与しない（不調時は呼び出し側が通常タップに劣化＝フェイルソフト）。
    注: 追跡帯（FIELD_Y1）を抜けてから円到達まで track は見えないため、
    破棄は last_seen でなく eta_at+grace を優先する。"""

    def __init__(self, n_lanes=4, stale_sec=FORECAST_STALE_SEC,
                 grace_sec=FORECAST_GRACE_SEC):
        self.n_lanes = n_lanes
        self.stale_sec = stale_sec
        self.grace_sec = grace_sec
        self.entries = {}  # track_id -> {"lane","type","eta_at","last_seen"}

    def update(self, annotations, now):
        for a in annotations:
            if not a.get("is_note") or not (0 <= a.get("lane", -1) < self.n_lanes):
                continue
            eta_at = (now + a["eta"]) if a.get("eta") is not None else None
            self.entries[a["id"]] = {"lane": a["lane"], "type": a["type"],
                                     "eta_at": eta_at, "last_seen": now}
        for tid in [t for t, e in self.entries.items() if self._expired(e, now)]:
            del self.entries[tid]

    def _expired(self, e, now):
        if e["eta_at"] is not None:
            return now > e["eta_at"] + self.grace_sec
        return now - e["last_seen"] > self.stale_sec

    def _nearest(self, lane, now):
        best_id, best_key = None, None
        for tid, e in self.entries.items():
            if e["lane"] != lane:
                continue
            key = e["eta_at"] if e["eta_at"] is not None else float("inf")
            if best_key is None or key < best_key:
                best_id, best_key = tid, key
        return best_id

    def peek(self, lane, now):
        tid = self._nearest(lane, now)
        return self.entries[tid] if tid is not None else None

    def consume(self, lane, now):
        tid = self._nearest(lane, now)
        return self.entries.pop(tid) if tid is not None else None

    def next_eta_at(self, lane, now, ntype=None):
        """lane で次に到達するノーツ（ntype 指定時はその種別のみ）の到達予測時刻。
        緑ホールドの解除時刻（対の緑の到達）に使う。無ければ None。"""
        best = None
        for e in self.entries.values():
            if e["lane"] != lane or e["eta_at"] is None:
                continue
            if ntype is not None and e["type"] != ntype:
                continue
            if best is None or e["eta_at"] < best:
                best = e["eta_at"]
        return best


def _track(dirpath):
    """連番フレームを Tracker に通し、検出された動くノーツ（レーン/ETA/種別）を集計。"""
    import glob
    from PIL import Image
    import autolive as A  # 遅延import（循環回避）
    al = A.AutoLive(1, dry_run=True)
    files = sorted(glob.glob(os.path.join(dirpath, "*.png")))
    trk = Tracker(al.win, al.content)
    seen = {}  # id -> last annotation
    DT = 0.05
    for fi, fp in enumerate(files):
        frame = np.array(Image.open(fp).convert("RGB"))
        blobs = detect_notes(frame, al.win, al.content)
        for a in trk.update(blobs, fi * DT):
            if a["is_note"]:
                seen[a["id"]] = a
    notes = list(seen.values())
    import collections
    lane = collections.Counter(a["lane"] for a in notes)
    typ = collections.Counter(a["type"] for a in notes)
    print(f"frames={len(files)} note-tracks={len(notes)} lanes={dict(lane)} types={dict(typ)}")
    for a in sorted(notes, key=lambda x: x["id"])[:25]:
        e = f'{a["eta"]:.2f}s' if a["eta"] is not None else "-"
        print(f'  id{a["id"]:3} lane{a["lane"]} {a["type"]:5} speed{a["speed"]:.0f}px/s eta{e} pos({a["pos"][0]:.0f},{a["pos"][1]:.0f})')


def _live(seconds=60.0):
    """読み取り専用のリアルタイム検証。autolive(タップ周回)の横で動かし、新エンジンが
    実機フレームからノーツを検出・追跡・レーン/ETA推定できているかをログ出力する。
    **クリックは一切しない**ので周回に干渉しない（mssキャプチャのみ）。"""
    import time
    import driver
    import autolive as A  # 遅延import（循環回避）
    al = A.AutoLive(1, dry_run=True)
    win, content = al.win, al.content
    trk = Tracker(win, content)
    reported = set()
    t0 = time.time()
    nframes = 0
    note_total = 0
    print(f"[note_engine.live] {seconds:.0f}s 観測開始（読み取り専用・クリックなし）", flush=True)
    while time.time() - t0 < seconds:
        frame = driver.grab(win)
        if float(frame.mean()) >= DARK_THRESH:
            time.sleep(0.1)  # ライブ中(暗)以外はスキップ
            continue
        nframes += 1
        t = time.time() - t0
        blobs = detect_notes(frame, win, content)
        for a in trk.update(blobs, t):
            # 「確定したノーツ」を一度だけ報告: is_note かつ ETA が短く(到達直前)なった時点
            if a["is_note"] and a["id"] not in reported and a["eta"] is not None \
                    and a["eta"] < 0.25 and a["lane"] >= 0:
                reported.add(a["id"])
                note_total += 1
                print(f"  [{t:5.1f}s] ノーツ確定 lane{a['lane']} 種別{a['type']:5} "
                      f"speed{a['speed']:.0f}px/s pos({a['pos'][0]:.0f},{a['pos'][1]:.0f})",
                      flush=True)
        time.sleep(0.02)
    print(f"[note_engine.live] 終了: gameplayフレーム{nframes} 検出ノーツ{note_total}", flush=True)


def _viz(frame_path, out_path):
    from PIL import Image, ImageDraw
    import autolive as A  # 遅延import（循環回避）
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
    import autolive as A  # 遅延import（循環回避）
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
    elif cmd == "track":
        _track(sys.argv[2])
    elif cmd == "live":
        _live(float(sys.argv[2]) if len(sys.argv) > 2 else 60.0)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
