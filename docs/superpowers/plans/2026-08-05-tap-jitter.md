# タップ座標ジッター Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ライブ中の打鍵の着弾点に人間らしい散らばりを持ち込み、「毎回まったく同じ 4 点」という統計的シグネチャを消す。

**Architecture:** 乱数生成だけを担う純粋モジュール `tools/tap_jitter.py` を新設し、`autolive.py` は `_tap_point(idx)` という 1 つのヘルパ経由でそれを使う。判定 ROI（`_circle_roi_px`）には一切触れず、クリック先だけを動かす。

**Tech Stack:** Python 3.11+ / 標準ライブラリのみ（`random`, `math`）/ unittest

## Global Constraints

- ブランチは `feat/tap-jitter`（作成済み）。`main` で直接作業しない
- テストの実行は `.venv/bin/python -m unittest discover -s tests`
- 新規モジュールは `Quartz` にも `cv2` にも依存しない（実機・画面収録権限・アクセシビリティ権限なしでテストが回ること）
- **`CIRCLES` は `--auto-circles` によって in-place で書き換えられる**（`autolive.py:950` の `CIRCLES[:] = matched`）。座標をキャッシュしてはならない。必ず毎回読み直す
- 座標系: x はウィンドウ幅 `win["w"]` で正規化、y は内容矩形高 `content[1] - content[0]` で正規化。**分母が異なる**
- 判定 ROI を計算する `_circle_roi_px()` は素の `CIRCLES` を使い続ける（ジッターを混ぜない）
- リポジトリにリンタ／フォーマッタは未設定。既存コードのスタイル（日本語 docstring、`# noqa: E402` 付きの遅延 import）に合わせる
- 意図的なミスの注入は**行わない**。ミス率上限 3% の予算は消費ゼロ
- 仕様書: `docs/superpowers/specs/2026-08-05-tap-jitter-design.md`

---

### Task 1: 純粋モジュール `tools/tap_jitter.py`

着弾点オフセットを生成するだけのクラス。ウィンドウ寸法も座標系も知らない。px を受け取って px を返す。

**Files:**
- Create: `tools/tap_jitter.py`
- Test: `tests/test_tap_jitter.py`

**Interfaces:**
- Consumes: なし（標準ライブラリのみ）
- Produces:
  - `TapJitter(n_lanes: int, *, bias_sigma: float, tap_sigma: float, max_r: float, rng: random.Random | None = None)`
  - `TapJitter.begin_live() -> None`
  - `TapJitter.offset_px(idx: int) -> tuple[float, float]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tap_jitter.py` を新規作成:

```python
"""着弾点ジッターの統計的性質を固定する（実機不要）。

固定 seed で回すので、統計量を検証しながら結果は決定論的になる。閾値は
docs/superpowers/specs/2026-08-05-tap-jitter-design.md のパラメータから導出した値。
パラメータを変えたら閾値も再計算すること。
"""
import math
import os
import random
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from tap_jitter import TapJitter  # noqa: E402

# 529w 換算の実値（R = 529 × 0.05 = 26.45px に対する 0.10 / 0.18 / 0.60）
BIAS_SIGMA = 2.645
TAP_SIGMA = 4.761
MAX_R = 15.87


def make(seed=1234, n_lanes=4, bias_sigma=BIAS_SIGMA,
         tap_sigma=TAP_SIGMA, max_r=MAX_R):
    return TapJitter(n_lanes, bias_sigma=bias_sigma, tap_sigma=tap_sigma,
                     max_r=max_r, rng=random.Random(seed))


class TestTapJitter(unittest.TestCase):

    def test_tap_noise_sigma(self):
        """1ライブ内の散らばりが tap_sigma の 0.90〜1.05 倍に収まる。

        棄却サンプリングが裾を削るため実効 σ は公称より小さく出る。
        40 seed × 20k サンプルの実測で 0.925〜0.994（許容は両側に余裕を持たせた値）。
        上振れは原理的に起こらないので上側は 1.05 で足りる。
        """
        j = make()
        j.begin_live()
        xs = [j.offset_px(0)[0] for _ in range(20000)]
        sd = statistics.pstdev(xs)
        self.assertGreater(sd, TAP_SIGMA * 0.90)
        self.assertLess(sd, TAP_SIGMA * 1.05)

    def test_bias_sigma(self):
        """begin_live() を繰り返したときのバイアスが bias_sigma の ±10% に収まる。"""
        j = make(tap_sigma=0.0)   # ノイズを消すとオフセット＝バイアスそのもの
        biases = []
        for _ in range(5000):
            j.begin_live()
            biases.append(j.offset_px(0)[0])
        sd = statistics.pstdev(biases)
        self.assertGreater(sd, BIAS_SIGMA * 0.90)
        self.assertLess(sd, BIAS_SIGMA * 1.10)

    def test_never_exceeds_max_r(self):
        """バイアス+ノイズの合計が上限半径を超えない。"""
        j = make()
        for _ in range(200):
            j.begin_live()
            for idx in range(4):
                for _ in range(50):
                    dx, dy = j.offset_px(idx)
                    self.assertLessEqual(math.hypot(dx, dy), MAX_R + 1e-9)

    def test_no_pileup_on_the_boundary_circle(self):
        """上限半径の円周上にオフセットが積み上がらない。

        超過分を切り詰める実装だと、恒常バイアスで中心がずれるぶん境界に当たりやすく、
        **タップの 17% が半径ちょうど max_r の円周上に乗る**（実測）。円周への集中は
        「毎回同じ4点」より不自然な人工物なので、切り詰めではなく棄却で実装すること。
        棄却実装での実測は 0.089%。
        """
        j = make(seed=5)
        j.begin_live()
        n = 20000
        edge = sum(1 for _ in range(n)
                   if math.hypot(*j.offset_px(1)) > MAX_R - 0.05)
        self.assertLess(edge / n, 0.01)

    def test_bias_is_constant_within_a_live(self):
        """同一ライブ内でバイアスは不変、begin_live() で変わる。"""
        j = make(tap_sigma=0.0)
        j.begin_live()
        first = [j.offset_px(0) for _ in range(100)]
        self.assertEqual(len(set(first)), 1)   # ライブ中は完全に同じ点
        j.begin_live()
        self.assertNotEqual(j.offset_px(0), first[0])

    def test_reproducible_with_same_seed(self):
        """同一 seed なら offset_px() の列が完全一致する。"""
        a, b = make(seed=7), make(seed=7)
        a.begin_live()
        b.begin_live()
        for _ in range(500):
            for idx in range(4):
                self.assertEqual(a.offset_px(idx), b.offset_px(idx))

    def test_lanes_have_independent_bias(self):
        """レーンごとに別々のバイアスを持つ。"""
        j = make(tap_sigma=0.0)
        j.begin_live()
        offsets = {j.offset_px(idx) for idx in range(4)}
        self.assertEqual(len(offsets), 4)

    def test_offset_before_begin_live_raises(self):
        """begin_live() を呼ばずに使うと RuntimeError。"""
        j = make()
        with self.assertRaises(RuntimeError):
            j.offset_px(0)

    def test_invalid_params_raise(self):
        """不正なパラメータは ValueError。"""
        with self.assertRaises(ValueError):
            TapJitter(0, bias_sigma=1.0, tap_sigma=1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=-1.0, tap_sigma=1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=1.0, tap_sigma=-1.0, max_r=1.0)
        with self.assertRaises(ValueError):
            TapJitter(4, bias_sigma=1.0, tap_sigma=1.0, max_r=0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'tap_jitter'`）

- [ ] **Step 3: 最小の実装を書く**

`tools/tap_jitter.py` を新規作成:

```python
"""タップ着弾点のジッター（実機不要・純粋モジュール）。

ライブ中の打鍵は円リング中心の固定4点へ送られており、着弾点の散らばりが厳密ゼロに
なっている。人間の指はリング中心に厳密一致しないので、

  - レーンごとの**恒常バイアス**（端末の持ち方に由来する一貫したズレ。ライブごとに引き直す）
  - タップごとの**ノイズ**

の2段で散らす。毎タップ平均ゼロのノイズだけだと着弾点の重心がリング中心に厳密一致して
しまい、それ自体が不自然になるため、恒常バイアスを重ねている。

**上限半径は切り詰めではなく棄却で与える。** 超過分をその半径へ切り詰めると、恒常バイアスの
ぶん分布の中心が原点からずれるせいで境界に当たりやすく、実測でタップの 17% が半径ちょうど
max_r の円周上に積み上がった。円周への集中は「毎回同じ4点」より不自然な人工物であり、
本モジュールの目的を正面から損なう。棄却実装では 0.089% まで下がる。

半径はすべて **px** で受け取る。ウィンドウ寸法からの換算は呼び出し側（autolive.py）の責務。
このモジュールは座標系を知らない。
"""
from __future__ import annotations

import math
import random

_MAX_TRIES = 16   # 棄却の打ち切り回数（バイアスを max_r/2 に制限しているので実際は届かない）


class TapJitter:
    """レーン別の着弾点オフセットを生成する。"""

    def __init__(self, n_lanes, *, bias_sigma, tap_sigma, max_r, rng=None):
        if n_lanes <= 0:
            raise ValueError(f"n_lanes は 1 以上である必要がある: {n_lanes}")
        if bias_sigma < 0:
            raise ValueError(f"bias_sigma は 0 以上である必要がある: {bias_sigma}")
        if tap_sigma < 0:
            raise ValueError(f"tap_sigma は 0 以上である必要がある: {tap_sigma}")
        if max_r <= 0:
            raise ValueError(f"max_r は正である必要がある: {max_r}")
        self.n_lanes = n_lanes
        self.bias_sigma = bias_sigma
        self.tap_sigma = tap_sigma
        self.max_r = max_r
        self.rng = rng if rng is not None else random.Random()
        self._bias = None

    def begin_live(self):
        """レーン別の恒常バイアスを引き直す。**各ライブの開始時に呼ぶ。**

        バイアスは max_r/2 に制限する。これにより offset_px() の棄却が必ず有限回で終わる。
        """
        lim = self.max_r / 2.0
        self._bias = []
        for _ in range(self.n_lanes):
            bx = self.rng.gauss(0.0, self.bias_sigma)
            by = self.rng.gauss(0.0, self.bias_sigma)
            r = math.hypot(bx, by)
            if r > lim:
                bx *= lim / r
                by *= lim / r
            self._bias.append((bx, by))

    def offset_px(self, idx):
        """レーン idx の、このタップぶんの px オフセット (dx, dy) を返す。

        合計ベクトルが max_r を超えたら**引き直す**（切り詰めない。理由はモジュール
        docstring）。バイアスが max_r/2 に制限されているので必ず有限回で採用される。
        """
        if self._bias is None:
            raise RuntimeError("begin_live() を呼ぶ前に offset_px() が呼ばれた")
        bx, by = self._bias[idx]
        for _ in range(_MAX_TRIES):
            dx = bx + self.rng.gauss(0.0, self.tap_sigma)
            dy = by + self.rng.gauss(0.0, self.tap_sigma)
            if math.hypot(dx, dy) <= self.max_r:
                return dx, dy
        # 到達しない想定の防御的措置（上限を必ず守るため最後の値だけ切り詰める）
        r = math.hypot(dx, dy)
        k = self.max_r / r
        return dx * k, dy * k
```

- [ ] **Step 4: テストを実行して成功を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter -v
```

Expected: PASS（9 tests）

- [ ] **Step 5: 既存テストが壊れていないことを確認**

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: 既存のテストがすべて PASS（新規モジュールは誰からも import されていないので影響なし）

- [ ] **Step 6: コミット**

```bash
git add tools/tap_jitter.py tests/test_tap_jitter.py
git commit -m "feat: 着弾点ジッターの生成モジュールを追加

レーン別の恒常バイアス（ライブごとに引き直す）とタップごとのノイズを
重ね、合計が上限半径を超えたら棄却して引き直す。切り詰めないのは、
バイアスで分布の中心がずれるぶん境界に当たりやすく、実測でタップの
17% が半径ちょうどの円周上に積み上がったため。

ウィンドウ寸法を知らない純粋モジュールなので実機なしでテストできる。"
```

---

### Task 2: `autolive.py` への配線（`_tap_point()` と CLI）

`_tap_point()` を追加し、`AutoLive` が `TapJitter` を保持するようにする。**打鍵地点の差し替えはまだ行わない**ので、このタスク完了時点でも実機の挙動は現行と完全に同一。

**Files:**
- Modify: `tools/autolive.py`（import 追加 / 定数追加 / `__init__` / `_tap_point()` 新設 / `begin_live()` フック / argparse / `main()`）
- Test: `tests/test_tap_jitter.py`（`TestTapPoint` クラスを追記）

**Interfaces:**
- Consumes: Task 1 の `TapJitter(n_lanes, *, bias_sigma, tap_sigma, max_r, rng=None)` / `begin_live()` / `offset_px(idx)`
- Produces:
  - `AutoLive._tap_point(idx: int) -> tuple[float, float]`（content 相対座標）
  - `AutoLive.jitter: TapJitter | None`
  - `AutoLive.hold_point: tuple[float, float] | None`（Task 3 が使う）
  - `AutoLive.__init__` の新パラメータ `tap_jitter: bool = True`
  - モジュール定数 `CIRCLE_R_FRAC` / `JITTER_BIAS_SIGMA_R` / `JITTER_TAP_SIGMA_R` / `JITTER_MAX_R`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tap_jitter.py` の末尾（`if __name__ == "__main__":` の直前）に追記:

```python
import autolive as AL  # noqa: E402


class FakeJitter:
    """固定オフセットを返すスタブ。座標変換だけを切り出して検証するために使う。"""

    def __init__(self, dx, dy):
        self.dx, self.dy = dx, dy

    def begin_live(self):
        pass

    def offset_px(self, idx):
        return self.dx, self.dy


def make_al(circles, jitter, w=671, h=348):
    """実機に触れずに AutoLive を組み立てる（tests/test_roi_scale.py と同じ手口）。"""
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = {"x": 0, "y": 0, "w": w, "h": h}
    al.content = (38, h - 9)
    al.jitter = jitter
    AL.CIRCLES[:] = circles
    return al


class TestTapPoint(unittest.TestCase):

    DEFAULT_CIRCLES = [(0.16, 0.63), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]

    def tearDown(self):
        AL.CIRCLES[:] = list(self.DEFAULT_CIRCLES)

    def test_x_and_y_use_different_denominators(self):
        """x はウィンドウ幅、y は内容矩形高で正規化する（分母の取り違え検出）。

        671x348 では幅 671 に対し内容矩形高は 301。同じ分母を使うと落ちる。
        """
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(10.0, 20.0))
        xf, yf = al._tap_point(0)
        self.assertAlmostEqual(xf, 0.16 + 10.0 / 671, places=9)
        self.assertAlmostEqual(yf, 0.63 + 20.0 / (348 - 9 - 38), places=9)

    def test_follows_in_place_circles_update(self):
        """--auto-circles による CIRCLES の in-place 更新に追従する。

        座標をキャッシュすると、補正が効いた瞬間から古い点を叩き続ける。
        """
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(0.0, 0.0))
        self.assertAlmostEqual(al._tap_point(0)[0], 0.16, places=9)
        AL.CIRCLES[:] = [(0.25, 0.70), (0.33, 0.85), (0.68, 0.85), (0.84, 0.63)]
        self.assertAlmostEqual(al._tap_point(0)[0], 0.25, places=9)

    def test_disabled_returns_exact_circle(self):
        """jitter=None なら素の CIRCLES[idx] と完全一致する。"""
        al = make_al(list(self.DEFAULT_CIRCLES), None)
        for idx in range(4):
            self.assertEqual(al._tap_point(idx), AL.CIRCLES[idx])

    def test_degenerate_window_falls_back_to_exact_circle(self):
        """ウィンドウ寸法が壊れているときは素の座標を返す（ゼロ除算を起こさない）。"""
        al = make_al(list(self.DEFAULT_CIRCLES), FakeJitter(10.0, 20.0))
        al.win = {"x": 0, "y": 0, "w": 0, "h": 0}
        al.content = (38, 38)
        self.assertEqual(al._tap_point(0), AL.CIRCLES[0])
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter.TestTapPoint -v
```

Expected: FAIL（`AttributeError: 'AutoLive' object has no attribute '_tap_point'`）

- [ ] **Step 3: import を追加**

`tools/autolive.py` の `import driver  # noqa: E402`（62 行目付近）の直後に 1 行追加:

```python
import driver  # noqa: E402
import tap_jitter as tap_jitter_module  # noqa: E402
```

別名を付けるのは、`AutoLive.__init__` の引数名 `tap_jitter`（Step 5）がモジュール名を
隠してしまうため。

- [ ] **Step 4: 定数を追加**

`tools/autolive.py` の `HOLD_REL_FACTOR = 0.45` の行（207 行目付近）の直後に追加:

```python

# --- 打鍵の着弾点ジッター ---
# 着弾点が毎回まったく同じ4点だと散らばりが厳密ゼロになり、統計的に人間と即座に区別できる。
# リング内に収まる範囲で散らす。判定 ROI には一切影響を与えない（_circle_roi_px は素の
# CIRCLES を使い続ける）。値はすべて円リング半径 R との比。R は端末で変わるので比で持つ。
CIRCLE_R_FRAC = 0.05          # 円リング半径の目安（ウィンドウ幅相対）。
                              # **note_engine.CIRCLE_R_FRAC と同一値に保つこと。**
JITTER_BIAS_SIGMA_R = 0.10    # レーン別の恒常バイアス σ（≈2.6px@529w）。ライブごとに引き直す
JITTER_TAP_SIGMA_R = 0.18     # タップごとのノイズ σ（≈4.8px@529w）
JITTER_MAX_R = 0.60           # 合計オフセットの上限（≈15.9px@529w）。超えたら棄却して引き直す。
                              # 0.45 では棄却が分布の裾を削りすぎ、実効 σ が seed 次第で
                              # 0.82〜0.93 倍とばらついた（0.60 では 0.93〜0.99 倍）。
```

- [ ] **Step 5: `__init__` に配線する**

`tools/autolive.py:516` のシグネチャ末尾に `tap_jitter=True` を追加:

```python
                 engine="roi", esc_enabled=True, flick=False, predict=False,
                 auto_circles=False, tap_jitter=True):
```

`self.content = (38, int(self.win["h"]) - 9)`（590 行目付近、`__init__` の最終行）の**直後**に追加:

```python
        # --- 打鍵の着弾点ジッター（--no-tap-jitter で無効化） ---
        # 半径は円リング半径 R との比で持つ（端末差の吸収）。R は win 取得後にしか
        # 決まらないので、ここで px へ換算して TapJitter に渡す。
        self.jitter = None
        if tap_jitter:
            r_px = self.win["w"] * CIRCLE_R_FRAC
            self.jitter = tap_jitter_module.TapJitter(
                len(CIRCLES),
                bias_sigma=r_px * JITTER_BIAS_SIGMA_R,
                tap_sigma=r_px * JITTER_TAP_SIGMA_R,
                max_r=r_px * JITTER_MAX_R)
        self.hold_point = None   # ホールド中の着弾点（down で確定し move/up で使い回す）
```

- [ ] **Step 6: `_tap_point()` を追加**

`tools/autolive.py` の `_circle_roi_px()` の定義（795 行目付近）の**直前**に追加:

```python
    def _tap_point(self, idx):
        """CIRCLES[idx] にジッターを乗せた content 相対座標を返す。

        **CIRCLES は --auto-circles で in-place 更新されるため毎回読む（キャッシュ禁止）。**
        x はウィンドウ幅、y は内容矩形高で正規化する（分母が違う）。px 空間で等方な
        散らばりを作ってから変換しないと、着弾点が楕円状に歪む。

        判定 ROI（_circle_roi_px）はこれを使わない。ジッターはクリック先だけの話。
        """
        xf, yf = CIRCLES[idx]
        if self.jitter is None:
            return xf, yf
        top, bottom = self.content
        w = self.win["w"]
        ch = bottom - top
        if w <= 0 or ch <= 0:
            return xf, yf
        dx, dy = self.jitter.offset_px(idx)
        return xf + dx / w, yf + dy / ch
```

- [ ] **Step 7: ライブ開始で `begin_live()` を呼ぶ**

`tools/autolive.py:1577-1578` を差し替える:

```python
                if self.gameplay_since is None:
                    self.gameplay_since = now
                    if self.jitter is not None:
                        self.jitter.begin_live()   # ライブごとに恒常バイアスを引き直す
```

`gameplay_since` は gameplay/pause を抜けたとき（1898 行目付近）に `None` に戻るので、
これでちょうど 1 ライブにつき 1 回呼ばれる。

- [ ] **Step 8: CLI フラグを追加**

`tools/autolive.py` の `--no-esc` の `ap.add_argument(...)` の直後に追加:

```python
    ap.add_argument("--no-tap-jitter", action="store_true",
                    help="打鍵の着弾点ジッターを無効化（既定は有効）。"
                         "従来どおり円中心ちょうどを叩く。A/B 比較用")
```

`main()` の `AutoLive(...)` 呼び出しに引数を追加:

```python
                      green_hold=args.green_hold,
                      hold_max_sec=args.hold_max_sec,
                      tap_jitter=not args.no_tap_jitter).run()
```

- [ ] **Step 9: テストを実行して成功を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter -v
```

Expected: PASS（13 tests: Task 1 の 9 件 + Task 2 の 4 件）

- [ ] **Step 10: 既存テストが壊れていないことを確認**

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: すべて PASS。特に `tests/test_roi_scale.py` は `CIRCLES` を書き換えるので、
テスト間の汚染がないことをここで確認する。

- [ ] **Step 11: 打鍵地点がまだ変わっていないことを確認**

```bash
git diff --stat
grep -n "_tap_point" tools/autolive.py
```

Expected: `_tap_point` の定義 1 箇所のみがヒットする（呼び出し側はまだゼロ）。
このタスクでは実機の挙動は現行と完全に同一。

- [ ] **Step 12: コミット**

```bash
git add tools/autolive.py tests/test_tap_jitter.py
git commit -m "feat: 着弾点ジッターを AutoLive に配線する

_tap_point() と --no-tap-jitter を追加し、ライブ開始時に恒常バイアスを
引き直す。打鍵地点の差し替えは次コミット。この時点では挙動は変わらない。

CIRCLES は --auto-circles で in-place 更新されるため _tap_point() は
毎回読み直す。x/y で正規化の分母が違う点も回帰テストで固定した。"
```

---

### Task 3: 打鍵地点の差し替えとドキュメント更新

すべての打鍵地点を `CIRCLES[i]` → `self._tap_point(i)` に差し替える。ここで初めて実機の挙動が変わる。

**Files:**
- Modify: `tools/autolive.py:1162`（通常タップ）、`:1219`（キープアライブ）、`:868`（フリック）、`:1045,1049,1069,1073,1090,1094,1122,1139,1148`（ホールド）、`:1607`（rotate）
- Modify: `docs/architecture.md`
- Test: `tests/test_tap_jitter.py`（`TestTapSites` クラスを追記）

**Interfaces:**
- Consumes: Task 2 の `AutoLive._tap_point(idx)` / `AutoLive.hold_point` / `AutoLive.jitter`
- Produces: なし（最終タスク）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tap_jitter.py` の末尾（`if __name__ == "__main__":` の直前）に追記:

```python
class TestTapSites(unittest.TestCase):
    """打鍵地点が _tap_point() を経由していることをソース上で固定する。

    実機なしでは実際のクリック座標を観測できないため、**素の CIRCLES を
    content_to_screen / click_content に直接渡している箇所が残っていないこと**を
    ソースコードに対して検査する。差し戻しの検出が目的。
    """

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "tools", "autolive.py")
        with open(path, encoding="utf-8") as f:
            self.src = f.read()

    def test_no_raw_circles_in_click_content(self):
        """通常タップが素の円中心を叩いていない。"""
        self.assertNotIn("self.click_content(*CIRCLES[", self.src)

    def test_no_raw_circles_in_content_to_screen(self):
        """フリック開始点とホールド down が素の円中心を使っていない。"""
        self.assertNotIn("self.content_to_screen(*CIRCLES[", self.src)

    def test_keepalive_and_rotate_use_tap_point(self):
        """キープアライブと rotate が素の円中心を叩いていない。

        この2箇所は `cx, cy = CIRCLES[self.circle_i % len(CIRCLES)]` という別の
        書き方をしているので、上の2テストでは捕まらない。
        """
        self.assertNotIn("CIRCLES[self.circle_i", self.src)
        self.assertEqual(self.src.count("self.click_content(*self._tap_point(idx))"), 2)

    def test_roi_still_uses_raw_circles(self):
        """判定 ROI は素の CIRCLES を使い続ける（ジッターを混ぜない）。"""
        self.assertIn("xf, yf = CIRCLES[idx]", self.src)

    def test_hold_uses_stored_point_for_move_and_up(self):
        """ホールドは down で決めた点を move/up で使い回す（毎回引き直さない）。

        move が 3 箇所、up が 3 箇所。合計 6 箇所すべてが _hold_pt() 経由になる。
        """
        self.assertEqual(
            self.src.count('self._press(*self.content_to_screen(*self._hold_pt(i)), "move")'), 3)
        self.assertEqual(
            self.src.count('self._press(*self.content_to_screen(*self._hold_pt(i)), "up")'), 3)
        self.assertEqual(
            self.src.count("self.hold_point = self._tap_point(i)"), 3)
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter.TestTapSites -v
```

Expected: FAIL（4 件が落ちる: `test_no_raw_circles_in_click_content` /
`test_no_raw_circles_in_content_to_screen` / `test_keepalive_and_rotate_use_tap_point` /
`test_hold_uses_stored_point_for_move_and_up`。`test_roi_still_uses_raw_circles` だけは
最初から PASS する — これは差し戻し検出用のガードで、TDD の駆動役ではない）

- [ ] **Step 3: 通常タップとキープアライブを差し替える**

`tools/autolive.py:1162`:

```python
                self.click_content(*self._tap_point(i))  # 通常タップ（down+up）
```

`tools/autolive.py:1217-1219`（`_keepalive` 内）:

```python
            idx = self.circle_i % len(CIRCLES)
            self.circle_i += 1
            self.click_content(*self._tap_point(idx))
```

`tools/autolive.py:1607-1609`（rotate モード）:

```python
                    idx = self.circle_i % len(CIRCLES)
                    self.circle_i += 1
                    self.click_content(*self._tap_point(idx))
```

- [ ] **Step 4: フリックの開始点を差し替える**

`tools/autolive.py:868`（`_flick` の先頭）:

```python
        sx, sy = self.content_to_screen(*self._tap_point(idx))
```

外向きベクトルの計算（`dx, dy = sx - cxs, sy - cys`）はそのままでよい。ジッターは
最大 ≈15.9px（`max_r = 0.60R`＠529w）でリング半径 26px より小さいため、フリック
方向はほとんど変わらない。

- [ ] **Step 5: ホールドの down で着弾点を確定させる**

ホールド開始は 3 箇所ある（`:1122` 緑ホールド、`:1139` predict 緑、`:1148` 輝度長押し）。
いずれも `self._press(*self.content_to_screen(*CIRCLES[i]), "down")` を次に置き換える:

```python
                self.hold_point = self._tap_point(i)
                self._press(*self.content_to_screen(*self.hold_point), "down")
```

`:1148` の行はコメント付きなので、コメントを保ったまま:

```python
                self.hold_point = self._tap_point(i)
                self._press(*self.content_to_screen(*self.hold_point), "down")  # 離さず保持開始
```

- [ ] **Step 6: ホールドの move / up で確定済みの点を使う**

`move` は 3 箇所（`:1045`, `:1069`, `:1090`）。いずれも次に置き換える:

```python
                self._press(*self.content_to_screen(*self._hold_pt(i)), "move")
```

`up` は 3 箇所（`:1049`, `:1073`, `:1094`）。いずれも次に置き換える:

```python
            self._press(*self.content_to_screen(*self._hold_pt(i)), "up")
```

`_hold_pt()` は `_tap_point()` の定義（795 行目付近）の直後に追加する:

```python
    def _hold_pt(self, idx):
        """ホールド中の着弾点。down で確定した点を move/up で使い回す。

        毎回引き直すと指が微動することになる。ホールドは実機挙動が繊細な領域
        （緑ノーツ対応は実測 3.3% で既定 OFF のまま打ち切られている）なので変えない。
        hold_point が無い場合（ありえないが防御的に）は素の円中心へ落とす。
        """
        return self.hold_point if self.hold_point is not None else CIRCLES[idx]
```

ホールド解除の 3 箇所（`self.hold_idx = None` を設定している行）の直後に、
`self.hold_point = None` を追加する:

```python
            self.hold_idx = None
            self.hold_point = None
```

- [ ] **Step 7: テストを実行して成功を確認**

```bash
.venv/bin/python -m unittest tests.test_tap_jitter -v
```

Expected: PASS（18 tests: Task 1 の 9 件 + Task 2 の 4 件 + Task 3 の 5 件）

- [ ] **Step 8: 全テストを実行**

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: すべて PASS

- [ ] **Step 9: 構文と import を確認**

```bash
.venv/bin/python -c "import sys; sys.path.insert(0, 'tools'); import autolive; print('ok')"
grep -n "CIRCLES\[" tools/autolive.py
```

Expected: `ok` が出る。`grep` の結果に残ってよいのは
`_circle_roi_px`（判定 ROI）、`_approach_red`/`_approach_green`（検色 ROI）、
`_hold_pt` のフォールバック、`_auto_calibrate_circles` のみ。
**`click_content` / `content_to_screen` に素の `CIRCLES[...]` を渡している行が
残っていないこと。**

- [ ] **Step 10: `docs/architecture.md` を更新**

`docs/architecture.md` の打鍵エンジンの節（`しきい値調整` の箇条書きの直後、
`種別の限界（ベストエフォート）` の直前）に追加:

```markdown
  - **着弾点ジッター**: 打鍵の着弾点は円リング中心ちょうどではなく、レーン別の恒常
    バイアス（σ=0.10R、ライブごとに引き直す）とタップごとのノイズ（σ=0.18R）を乗せて
    散らす。上限は 0.60R（≈15.9px@529w）でリング半径 R≈26px の内側に収まる。上限超過は
    切り詰めず**棄却して引き直す**（切り詰めると 17% が円周上に積み上がる）。判定 ROI は
    素の円座標を使い続ける（ジッターはクリック先だけ）。`--no-tap-jitter` で無効化可。
    設計は [`superpowers/specs/2026-08-05-tap-jitter-design.md`](superpowers/specs/2026-08-05-tap-jitter-design.md)。
```

- [ ] **Step 11: コミット**

```bash
git add tools/autolive.py tests/test_tap_jitter.py docs/architecture.md
git commit -m "feat: 打鍵の着弾点にジッターをかける

通常タップ・キープアライブ・rotate・フリック開始点・ホールドの down を
_tap_point() 経由にした。ホールドは down で決めた点を move/up で使い回す。

判定 ROI は素の CIRCLES を使い続ける。素の CIRCLES を click_content /
content_to_screen へ直接渡す行が復活しないよう、ソース検査のテストで固定した。"
```

- [ ] **Step 12: 実機 A/B の手順を残す（実行はユーザー判断）**

このタスクでは**実機を回さない**。ライブ途中で止めると LIFE が無駄になるため、
周回のタイミングはユーザーが決める。以下を PR 本文か作業ログに残す:

**検証ツールの制約に注意。** `tools/ops/result_log.py` はリザルト画面の成績欄
（`STATS_BOX`）を切り出して蓄積し、1枚のモンタージュ画像にまとめるだけで、
PERFECT/GOOD/BAD/MISS の数値集計はしない。したがって下の「±5%」という数値基準は
**このツールでは評価できない**。実際に判定できるのは、モンタージュを並べて
目視したときに MISS の増加が一目で分かる、またはグレードが落ちる（SS→S 以下）
といった粗い変化だけである。数値による ±5% ゲートは、`STATS_BOX` の切り出し範囲
を使って PERFECT/GOOD/BAD/MISS を数値抽出するパイプラインを別途実装するまでの
follow-up とする（本タスクのスコープ外）。

```
A/B 手順:
  1. .venv/bin/python -u tools/ops/result_log.py 7200 jitter-off &
     python tools/autolive.py --loops 50 --flick --auto-circles --no-tap-jitter
  2. .venv/bin/python -u tools/ops/result_log.py 7200 jitter-on &
     python tools/autolive.py --loops 50 --flick --auto-circles

判定（モンタージュの目視比較。spec の「CLI と既定値」表）:
  - MISS の増加・グレード低下が目視で分からない  → 既定 ON を維持
  - MISS の増加やグレード低下が一目で分かる       → JITTER_MAX_R を 0.60 → 0.30 に下げて再測定
  - max_r を下げても目視で分かる悪化が残る        → 既定 OFF に落とし、リング当たり判定の実サイズを測り直す

ベースライン（docs/operations.md）: PERFECT 17 / GOOD 158〜160 / BAD 2〜4 / MISS 5
（モンタージュ上でこの内訳と比べて目に見えて悪化していないかを確認する。
 数値の ±5% はこのベースラインからの比率だが、上記の理由により算出できない）
```

---

## 実装後に残る未検証事項

以下は spec の「未検証事項」そのままで、コードでは解消できない。

- **リング内なら判定が変わらないこと**は未確認。Task 3 Step 12 の A/B で確認するが、
  `result_log.py` はモンタージュ画像を作るだけで数値集計をしないため、確認できるのは
  目視で分かる粗い悪化（MISS の明らかな増加・グレード低下）までであり、「±5%」という
  数値基準は数値抽出パイプライン（follow-up、本タスクのスコープ外）を作るまで評価できない
- `--auto-circles` の補正誤差とジッターが同方向に出た場合のマージン
- `CIRCLE_R_FRAC = 0.05` は検出用の目安値であり、タップ当たり判定の実サイズとは限らない
