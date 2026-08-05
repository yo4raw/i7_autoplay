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
        if not 0 <= idx < self.n_lanes:
            raise IndexError(
                f"idx は 0..{self.n_lanes - 1} の範囲である必要がある: {idx}")
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
