# ライブ中自動操作ハイブリッド方式 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** roi スパイク発火（実績系・温存）に track ベースの種別先読み（TypeForecast）と円自動キャリブレーションを追加し、既定OFFのフラグ（`--predict` / `--auto-circles`）で有効化できるようにする。

**Architecture:** 新ロジックはすべて `tools/note_engine.py` に置き、`tools/autolive.py` はフラグゲートされた薄い統合のみ。予報は「あれば使う」情報でフェイルソフト（不調時は現行の全タップ＋赤フリックに劣化）。緑ホールドの解除は輝度でなく ETA 予測（旧 `--holds` の波紋交絡を回避）。

**Tech Stack:** Python 3.14 (.venv), numpy, OpenCV (cv2), unittest（標準ライブラリ。依存追加なし）

## Global Constraints

- 新機能フラグは**既定OFF**。フラグOFF時のコードパスは現行と同一であること
- 安全装置（keepalive / watchdog / ステラ安全 / ESC / supervisor）は変更しない
- 実績コード（roi発火・FSM・メニュー処理）の移設・書き換えはしない
- テストは実機（ミラーリングウィンドウ）なしで走ること。`tests/corpus_raw/` は任意（無ければ skip）
- テスト実行: `.venv/bin/python -m unittest discover -s tests -v`

---

### Task 1: note_engine の lanes パラメータ化と LANES 同期

**Files:**
- Modify: `tools/note_engine.py:29-33`（CIRCLES/LANES）, `assign_lane`, `Tracker.__init__`, `detect_notes`
- Test: `tests/test_note_engine.py`（新規）

**Interfaces:**
- Produces: `detect_notes(frame_rgb, win, content, lanes=None)`, `assign_lane(cx, cy, win, content, lanes=None)`, `Tracker(win, content, lanes=None)`。`lanes` は content 相対 `[(xf, yf), ...]`（x はウィンドウ幅相対、y は content 高相対）。既定 `LANES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]`（autolive の補正後 CIRCLES と同値）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_note_engine.py`）

```python
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE

WIN = {"x": 0, "y": 0, "w": 529, "h": 334}
CONTENT = (38, 325)  # (top, bottom) px


def blank_frame():
    return np.zeros((334, 529, 3), dtype=np.uint8)


def put_blob(frame, xf, yf, rgb, r=4):
    """content相対 (xf,yf) に半径r pxの塗り潰しブロブを置く。"""
    top, bottom = CONTENT
    ch = bottom - top
    cx, cy = int(529 * xf), int(top + yf * ch)
    frame[cy - r:cy + r + 1, cx - r:cx + r + 1] = rgb
    return frame


class TestClassifyColor(unittest.TestCase):
    def test_white(self):
        self.assertEqual(NE.classify_color((230, 225, 220)), "white")

    def test_green(self):
        self.assertEqual(NE.classify_color((90, 220, 120)), "green")

    def test_red(self):
        self.assertEqual(NE.classify_color((230, 90, 90)), "red")

    def test_blue(self):
        self.assertEqual(NE.classify_color((90, 140, 230)), "blue")


class TestAssignLane(unittest.TestCase):
    def test_default_lanes_match_corrected_circles(self):
        self.assertEqual(NE.LANES, [(0.16, 0.63), (0.33, 0.85),
                                    (0.68, 0.85), (0.84, 0.63)])

    def test_blob_toward_lane0(self):
        # スポーンからレーン0（左端）方向の点はレーン0に割当たる
        top, bottom = CONTENT
        ch = bottom - top
        cx = 529 * 0.30
        cy = top + 0.35 * ch
        self.assertEqual(NE.assign_lane(cx, cy, WIN, CONTENT), 0)

    def test_custom_lanes(self):
        # lanes を差し替えると割当も変わる（キャリブレーション後の値を渡せる）
        lanes = [(0.10, 0.60), (0.90, 0.60)]
        cx, cy = 529 * 0.85, CONTENT[0] + 0.5 * (CONTENT[1] - CONTENT[0])
        self.assertEqual(NE.assign_lane(cx, cy, WIN, CONTENT, lanes=lanes), 1)


class TestDetectNotes(unittest.TestCase):
    def test_detects_bright_blob_in_band(self):
        f = put_blob(blank_frame(), 0.40, 0.30, (240, 240, 240))
        notes = NE.detect_notes(f, WIN, CONTENT)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["color"], "white")

    def test_ignores_blob_below_band(self):
        # タップ円帯（FIELD_Y1=0.62 以深）は波紋誤検出防止のため対象外
        f = put_blob(blank_frame(), 0.40, 0.80, (240, 240, 240))
        self.assertEqual(NE.detect_notes(f, WIN, CONTENT), [])


class TestTracker(unittest.TestCase):
    def test_moving_blob_becomes_note_with_lane_and_eta(self):
        trk = NE.Tracker(WIN, CONTENT)
        top, bottom = CONTENT
        ch = bottom - top
        sx, sy = 529 * NE.SPAWN[0], top + NE.SPAWN[1] * ch
        lx, ly = 529 * 0.16, top + 0.63 * ch  # レーン0
        last = []
        for k in range(8):
            t = k * 0.05
            frac = 0.1 + 0.06 * k  # スポーン→レーン0 へ徐々に移動
            x = sx + (lx - sx) * frac
            y = sy + (ly - sy) * frac
            f = blank_frame()
            f[int(y) - 4:int(y) + 5, int(x) - 4:int(x) + 5] = (90, 220, 120)
            last = trk.update(NE.detect_notes(f, WIN, CONTENT), t)
        notes = [a for a in last if a["is_note"]]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["lane"], 0)
        self.assertEqual(notes[0]["type"], "green")
        self.assertIsNotNone(notes[0]["eta"])
        self.assertGreater(notes[0]["eta"], 0)

    def test_static_blob_is_not_note(self):
        trk = NE.Tracker(WIN, CONTENT)
        f = put_blob(blank_frame(), 0.40, 0.30, (240, 240, 240))
        last = []
        for k in range(8):
            last = trk.update(NE.detect_notes(f, WIN, CONTENT), k * 0.05)
        self.assertEqual([a for a in last if a["is_note"]], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 失敗を確認** — `.venv/bin/python -m unittest tests.test_note_engine -v` → `LANES` 不一致（旧値）と `lanes` 引数 TypeError で FAIL

- [ ] **Step 3: note_engine.py を修正**

`CIRCLES`/`LANES` 定義（29-33行）を以下へ置換:

```python
# 4レーンのタップ円（content相対小数。x=ウィンドウ幅相対 / y=content高相対）。
# autolive.CIRCLES（右2円ズレ補正 2026-06-07 済み）と同値。autolive からは
# Tracker(..., lanes=CIRCLES) で実値が渡されるため、これは単体CLI用の既定値。
LANES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
```

`detect_notes(frame_rgb, win, content, lanes=None)` — `assign_lane(cx, cy, win, content, lanes)` を呼ぶ。
`assign_lane(cx, cy, win, content, lanes=None)` — `lanes = LANES if lanes is None else lanes` で走査。
`Tracker.__init__(self, win, content, lanes=None)` — `self.lanes = list(lanes) if lanes else list(LANES)`; `lane_px` は `self.lanes` から算出。
旧 `CIRCLES`（5点・中央ダミー入り）は削除（参照箇所を確認して LANES へ）。

- [ ] **Step 4: テスト成功を確認** — 同コマンドで全 PASS
- [ ] **Step 5: Commit** — `note_engine: LANES を補正後円座標に同期し lanes をパラメータ化`

### Task 2: TypeForecast（レーン別種別予報）

**Files:**
- Modify: `tools/note_engine.py`（Tracker の直後にクラス追加）
- Test: `tests/test_type_forecast.py`（新規）

**Interfaces:**
- Consumes: `Tracker.update()` の annotation dict（`id/is_note/lane/eta/type`）
- Produces: `TypeForecast(n_lanes=4, stale_sec=0.6, grace_sec=0.35)` — `update(annotations, now)`, `peek(lane, now) -> dict|None`, `consume(lane, now) -> dict|None`（dict: `{"lane","type","eta_at","last_seen"}`）, `next_eta_at(lane, now, ntype=None) -> float|None`

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_type_forecast.py`）

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE


def ann(tid, lane, ntype, eta):
    return {"id": tid, "is_note": True, "lane": lane, "eta": eta,
            "type": ntype, "speed": 300.0, "pos": (0, 0), "pts": []}


class TestTypeForecast(unittest.TestCase):
    def test_consume_returns_nearest_eta_and_removes(self):
        fc = NE.TypeForecast()
        fc.update([ann(1, 0, "red", 0.9), ann(2, 0, "green", 0.3)], now=10.0)
        e = fc.consume(0, 10.0)
        self.assertEqual(e["type"], "green")   # 到達が近い方
        e2 = fc.consume(0, 10.0)
        self.assertEqual(e2["type"], "red")    # 1ノーツ1予報（取り出し済みは消える）
        self.assertIsNone(fc.consume(0, 10.0))

    def test_lanes_are_independent(self):
        fc = NE.TypeForecast()
        fc.update([ann(1, 1, "red", 0.2)], now=0.0)
        self.assertIsNone(fc.peek(0, 0.0))
        self.assertEqual(fc.peek(1, 0.0)["type"], "red")

    def test_track_updates_refresh_entry(self):
        fc = NE.TypeForecast()
        fc.update([ann(1, 0, "white", 1.0)], now=0.0)
        fc.update([ann(1, 0, "green", 0.5)], now=0.2)  # 同一trackの最新情報で上書き
        e = fc.peek(0, 0.2)
        self.assertEqual(e["type"], "green")
        self.assertAlmostEqual(e["eta_at"], 0.7)

    def test_expiry_by_eta_grace(self):
        # 到達予測+猶予(0.35s)を過ぎた予報は破棄される（誤ジェスチャ防止）
        fc = NE.TypeForecast()
        fc.update([ann(1, 0, "green", 0.3)], now=0.0)  # eta_at=0.3
        fc.update([], now=0.5)   # 0.3+0.35=0.65 までは生存
        self.assertIsNotNone(fc.peek(0, 0.5))
        fc.update([], now=0.7)
        self.assertIsNone(fc.peek(0, 0.7))

    def test_expiry_by_stale_when_no_eta(self):
        fc = NE.TypeForecast()
        fc.update([ann(1, 0, "white", None)], now=0.0)
        fc.update([], now=0.7)   # stale_sec=0.6 超
        self.assertIsNone(fc.peek(0, 0.7))

    def test_next_eta_at_filters_by_type(self):
        fc = NE.TypeForecast()
        fc.update([ann(1, 0, "white", 0.2), ann(2, 0, "green", 0.8)], now=0.0)
        self.assertAlmostEqual(fc.next_eta_at(0, 0.0, ntype="green"), 0.8)
        self.assertIsNone(fc.next_eta_at(1, 0.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 失敗を確認** — `.venv/bin/python -m unittest tests.test_type_forecast -v` → AttributeError で FAIL
- [ ] **Step 3: note_engine.py に実装**

```python
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
```

- [ ] **Step 4: テスト成功を確認**
- [ ] **Step 5: Commit** — `note_engine: TypeForecast（レーン別種別予報）を追加`

### Task 3: 円自動検出（detect_circles / match_circles / circles CLI）

**Files:**
- Modify: `tools/note_engine.py`（関数2つ＋CLI サブコマンド `circles`）
- Test: `tests/test_autocal.py`（新規）

**Interfaces:**
- Produces: `detect_circles(frame_rgb, win, content) -> [(xf, yf), ...]`（content相対）, `match_circles(detected, prior, tol=0.06) -> list|None`（prior と同順・同数のリスト。全一致しなければ None）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_autocal.py`）

```python
import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import note_engine as NE

WIN = {"x": 0, "y": 0, "w": 529, "h": 334}
CONTENT = (38, 325)


def frame_with_rings(centers, radius=26):
    f = np.zeros((334, 529, 3), dtype=np.uint8)
    top, bottom = CONTENT
    ch = bottom - top
    for xf, yf in centers:
        cx, cy = int(529 * xf), int(top + yf * ch)
        cv2.circle(f, (cx, cy), radius, (235, 235, 235), 3)
    return f


class TestDetectCircles(unittest.TestCase):
    def test_detects_four_rings_near_truth(self):
        truth = NE.LANES
        det = NE.detect_circles(frame_with_rings(truth), WIN, CONTENT)
        self.assertGreaterEqual(len(det), 4)
        matched = NE.match_circles(det, truth)
        self.assertIsNotNone(matched)
        for (mx, my), (tx, ty) in zip(matched, truth):
            self.assertLess(abs(mx - tx), 0.03)
            self.assertLess(abs(my - ty), 0.03)


class TestMatchCircles(unittest.TestCase):
    def test_full_match_returns_in_prior_order(self):
        prior = [(0.2, 0.6), (0.8, 0.6)]
        det = [(0.81, 0.61), (0.21, 0.59)]
        self.assertEqual(NE.match_circles(det, prior), [(0.21, 0.59), (0.81, 0.61)])

    def test_partial_detection_returns_none(self):
        # 1円でも欠けたら None（呼び出し側は現行値を維持＝誤検出で悪化させない）
        prior = [(0.2, 0.6), (0.8, 0.6)]
        self.assertIsNone(NE.match_circles([(0.21, 0.59)], prior))

    def test_out_of_tolerance_returns_none(self):
        prior = [(0.2, 0.6)]
        self.assertIsNone(NE.match_circles([(0.5, 0.6)], prior, tol=0.06))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 失敗を確認** — AttributeError で FAIL
- [ ] **Step 3: note_engine.py に実装**

```python
CIRCLE_BAND_Y0 = 0.50      # 円検出の下帯（content相対yの開始）
CIRCLE_MATCH_TOL = 0.06    # prior との許容誤差（content相対距離）
CIRCLE_R_FRAC = 0.05       # 円リング半径の目安（ウィンドウ幅相対。SE実測 ~26px/529w）


def detect_circles(frame_rgb, win, content):
    """下帯からタップ円リングを Hough 検出して content相対 [(xf,yf),...] を返す。
    --auto-circles（機種非依存化）用。誤検出は match_circles 側で弾く。"""
    W, top, ch = _content_geom(win, content)
    h, w = frame_rgb.shape[:2]
    y0 = int(top + CIRCLE_BAND_Y0 * ch)
    band = frame_rgb[max(0, y0):h]
    gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
    gray = cv2.medianBlur(gray, 5)
    r_est = max(8, int(W * CIRCLE_R_FRAC))
    found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2,
                             minDist=int(W * 0.10), param1=120, param2=30,
                             minRadius=int(r_est * 0.6), maxRadius=int(r_est * 1.6))
    out = []
    if found is not None:
        for cx, cy, r in found[0]:
            out.append((float(cx) / W, (float(cy) + y0 - top) / ch))
    return out


def match_circles(detected, prior, tol=CIRCLE_MATCH_TOL):
    """検出円を prior（現行CIRCLES）へ最近傍マッチ。**全 prior が tol 内で1対1に
    埋まったときだけ** prior と同順の補正リストを返す。埋まらなければ None
    （呼び出し側は現行値を維持する）。"""
    result, used = [], set()
    for pxf, pyf in prior:
        best_j, best_d = -1, tol
        for j, (dxf, dyf) in enumerate(detected):
            if j in used:
                continue
            d = ((dxf - pxf) ** 2 + (dyf - pyf) ** 2) ** 0.5
            if d < best_d:
                best_j, best_d = j, d
        if best_j < 0:
            return None
        used.add(best_j)
        result.append(detected[best_j])
    return result
```

CLI: `main()` に `circles` サブコマンドを追加。`_viz` に倣い、`detect_circles` の結果（黄）と `LANES` prior（緑）と `match_circles` 結果（赤）をオーバーレイ描画して保存する `_circles(frame_path, out_path)` を追加。

- [ ] **Step 4: テスト成功を確認**（Hough パラメータで合成リングが4つ取れることを確認。取れない場合は param2 を 20 まで下げて再確認）
- [ ] **Step 5: Commit** — `note_engine: タップ円の自動検出（detect_circles/match_circles + circles CLI）`

### Task 4: autolive 統合 `--predict`（種別先読み: 緑ホールド/赤フリック）

**Files:**
- Modify: `tools/autolive.py` — `__init__`(345-391), `_gameplay_timing`(617-691), CLI(1160-1192)

**Interfaces:**
- Consumes: `note_engine.Tracker(win, content, lanes=...)`, `TypeForecast`, `detect_notes(..., lanes=...)`
- Produces: CLI フラグ `--predict`。`AutoLive(..., predict=False)`

- [ ] **Step 1: `__init__` に状態を追加**（`self.flick = flick` の直後）

```python
        # --- 種別先読み（--predict）。track を並走させ緑ホールド/赤フリックを出し分け ---
        self.predict = predict      # 既定 False（OFF時は現行と同一パス）
        self.forecast = None        # note_engine.TypeForecast（predict時に遅延生成）
        self.hold_release_at = None # 緑ホールドの解除予定時刻（ETA駆動。predict時のみ）
```

シグネチャに `predict=False` を追加。

- [ ] **Step 2: `_update_forecast` メソッドを追加**（`_gameplay_timing` の直前）

```python
    def _update_forecast(self, frame, now):
        """--predict: note_engine の検出＋追跡を1フレーム回し、レーン別種別予報を更新。
        例外時は予報なし（=全タップ）に劣化させ、周回は止めない。"""
        try:
            if self._ne is None:
                import note_engine as NE
                self._ne = NE
            if self.tracker is None or self.forecast is None:
                self.tracker = self._ne.Tracker(self.win, self.content,
                                                lanes=list(CIRCLES))
                self.forecast = self._ne.TypeForecast(n_lanes=len(CIRCLES))
            blobs = self._ne.detect_notes(frame, self.win, self.content,
                                          lanes=list(CIRCLES))
            self.forecast.update(self.tracker.update(blobs, now), now)
        except Exception as e:
            self.forecast = None  # 次フレームで再生成を試みる
            self.tracker = None
            if self.verbose:
                self.log(f"[predict] 予報更新に失敗（タップに劣化）: {e}")
```

- [ ] **Step 3: `_gameplay_timing` に3箇所の predict ゲート追加**

(a) ベースライン更新ループ（634-635行）の直後:

```python
        # 1.4) --predict: track 並走で種別予報を更新（発火判定には関与しない）。
        if self.predict:
            self._update_forecast(frame, now)
```

(b) 既存 `self.holds` ブロック（645-662行）の直前に predict ホールド継続処理:

```python
        # 2p) --predict の緑ホールド継続中: ETA予測時刻まで保持。輝度には依存しない
        #     （旧 --holds がタップ波紋と交絡した失敗要因を回避）。move で genuine 入力維持。
        if self.predict and self.hold_idx is not None:
            i = self.hold_idx
            nxt = self.forecast.next_eta_at(i, now, ntype="green") if self.forecast else None
            if nxt is not None:  # 対の緑のETAが精緻化されたら解除時刻を追従
                self.hold_release_at = min(nxt, self.hold_start + HOLD_MAX_SEC)
            if now < self.hold_release_at and (now - self.hold_start) < HOLD_MAX_SEC:
                self._press(*self.content_to_screen(*CIRCLES[i]), "move")
                self.last_input_ts = now
                time.sleep(0.005)
                return
            self._press(*self.content_to_screen(*CIRCLES[i]), "up")
            if self.verbose:
                self.log(f"ホールド解除 円{i}（{now - self.hold_start:.2f}s, ETA駆動）")
            self.note_last_tap[i] = now
            self.last_input_ts = now
            self.hold_idx = None
            self.hold_release_at = None
            time.sleep(0.02)
            return
```

(c) 発火ディスパッチ（664-688行）の `if self.holds ...` の直前に:

```python
            ntype = None
            if self.predict and self.forecast is not None:
                e = self.forecast.consume(i, now)
                ntype = e["type"] if e else None
            if self.predict and ntype == "green":
                # 緑=次の緑まで長押し（§17.9）。解除は対の緑のETA（無ければ track の
                # 精緻化を待ちつつ上限 HOLD_MAX_SEC）。
                nxt = self.forecast.next_eta_at(i, now, ntype="green")
                self.hold_release_at = min(nxt, now + HOLD_MAX_SEC) if nxt \
                    else now + HOLD_MAX_SEC
                self._press(*self.content_to_screen(*CIRCLES[i]), "down")
                self.hold_idx = i
                self.hold_start = now
                self.last_input_ts = now
                if self.verbose:
                    self.log(f"ホールド開始 円{i}（解除予定 +{self.hold_release_at - now:.2f}s）")
                tapped = True
                break
```

さらに既存のフリック条件（680行）を predict の赤予報でも発火するよう拡張:

```python
            if (self.predict and ntype == "red") or \
                    (self.flick and (now - self.note_red_seen[i]) < FLICK_RED_MEMORY):
```

- [ ] **Step 4: CLI 追加**（1177-1181行付近と AutoLive 呼び出し）

```python
    ap.add_argument("--predict", action="store_true",
                    help="track並走の種別先読みで緑ホールド/赤フリックを出し分け"
                         "（実験的・既定OFF。不調時は自動でタップに劣化）")
```

`AutoLive(...)` に `predict=args.predict` を追加。

- [ ] **Step 5: 構文と回帰チェック** — `.venv/bin/python -m py_compile tools/autolive.py` と全テスト、`git diff` でフラグOFF経路（`if self.predict` の外）に変更が無いことを目視確認
- [ ] **Step 6: Commit** — `autolive: --predict（track種別先読み: 緑ホールドETA解除/赤フリック）`

### Task 5: autolive 統合 `--auto-circles`（円自動キャリブレーション）

**Files:**
- Modify: `tools/autolive.py` — `__init__`, gameplay 分岐（932-936行）, CLI

**Interfaces:**
- Consumes: `note_engine.detect_circles`, `match_circles`
- Produces: CLI フラグ `--auto-circles`。`AutoLive(..., auto_circles=False)`

- [ ] **Step 1: `__init__` に追加**（predict 群の直後）

```python
        self.auto_circles = auto_circles  # ライブ突入時に円座標を画像から自動補正
        self.circles_calibrated = False   # プロセス内で一度だけ実施
```

- [ ] **Step 2: メソッド追加**（`_update_forecast` の直前）

```python
    def _auto_calibrate_circles(self, frame):
        """--auto-circles: ライブ突入時にタップ円リングを検出し CIRCLES を実測へ補正。
        4円すべてが prior の許容誤差内で一致したときだけ in-place 置換し（roi/keepalive/
        rotate 全読者へ反映）、失敗時は現行値を維持する（誤検出で悪化させない）。"""
        self.circles_calibrated = True
        try:
            if self._ne is None:
                import note_engine as NE
                self._ne = NE
            det = self._ne.detect_circles(frame, self.win, self.content)
            matched = self._ne.match_circles(det, list(CIRCLES))
            if matched is None:
                self.log(f"[auto-circles] 検出{len(det)}円が prior と一致せず → 現行値を維持")
                return
            old = list(CIRCLES)
            CIRCLES[:] = matched
            self.log(f"[auto-circles] 円座標を実測へ補正: {old} → {matched}")
        except Exception as e:
            self.log(f"[auto-circles] 失敗（現行値を維持）: {e}")
```

- [ ] **Step 3: gameplay 突入時に呼ぶ**（935-936行）

```python
                if self.gameplay_since is None:
                    self.gameplay_since = now
                    if self.auto_circles and not self.circles_calibrated:
                        self._auto_calibrate_circles(frame)
```

- [ ] **Step 4: CLI 追加** — `--auto-circles`（store_true, 既定OFF）、`AutoLive(..., auto_circles=args.auto_circles)`
- [ ] **Step 5: py_compile＋全テスト＋フラグOFF経路の目視確認**
- [ ] **Step 6: Commit** — `autolive: --auto-circles（ライブ突入時の円自動キャリブレーション）`

### Task 6: 実フレームコーパスのスモークテスト

**Files:**
- Test: `tests/test_corpus_smoke.py`（新規）

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: 実行して PASS（コーパスあり環境）を確認**
- [ ] **Step 3: Commit** — `tests: 実フレームコーパスのスモークテスト（コーパス無し環境ではskip）`

### Task 7: ドキュメント更新と最終確認

**Files:**
- Modify: `docs/specification.md`（§17 に追記＋改訂履歴）, `CLAUDE.md`（打鍵モード節）

- [ ] **Step 1: specification.md に §17.11 を追記** — ハイブリッド方式の要約（設計書 `docs/superpowers/specs/2026-07-10-live-engine-hybrid-design.md` への参照、フラグ既定OFF、実機検証手順）。改訂履歴に 0.14 行を追加
- [ ] **Step 2: CLAUDE.md の「ライブ中の打鍵」節に `--predict` / `--auto-circles` を1-2行で追記**
- [ ] **Step 3: 全テスト＋py_compile を最終実行**
- [ ] **Step 4: Commit** — `docs: ハイブリッド方式（--predict/--auto-circles）を仕様書とCLAUDE.mdに反映`

### Task 8: PR 作成

- [ ] **Step 1:** `git push -u origin feat/live-engine-hybrid`
- [ ] **Step 2:** `gh pr create` — タイトル「ライブ中自動操作のハイブリッド化: track種別先読み（--predict）と円自動キャリブレーション（--auto-circles）」。本文に: 概要 / 既定OFFで無回帰 / 実機検証手順（設計書§8） / テスト結果
