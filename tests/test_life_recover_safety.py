"""LIFE 回復がステラストーン（課金アイテム）を消費しないことの回帰テスト。

背景（2026-07-31 に既遂を確認）:
LIFE不足ダイアログの「回復」は、見出し「ライフが足りません。」のマッチ位置から
固定オフセット ANCH_KINAKO=(128,62) で押していた。ところが **きなこパンが 0 個になると
ダイアログはきなこパン行をグレーアウトせず、行ごと消して上に詰める**。その結果、同じ
オフセットがステラストーンの「回復」ボタン中央に着弾していた。

実機で既に発生済み: ステラ所持が 58 → 55 → 52 と、表示された消費数「3」ちょうどずつ減少。
しかもログには「ステラ不使用」と出るため気づけなかった。

対策: **押す前にきなこパン行が実在することを画像で確認**し、その行を基準に押す。
無ければクリックせず停止する。本テストはその不変条件を固定する。
"""
import os
import sys
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import autolive as AL  # noqa: E402

FRAMES = os.path.join(os.path.dirname(__file__), "frames")
PRESENT = "lifeshort_kinako_present_671x348.png"    # きなこパン 184個
DEPLETED = "lifeshort_kinako_depleted_529x334.png"  # きなこパン 0個（行が消えている）

# 実測したステラストーン「回復」ボタンの矩形（DEPLETED フレーム 529x334 上）
STELLA_BUTTON = (313, 158, 365, 178)   # x0, y0, x1, y1


def load(name):
    """テンプレ照合用に **BGR** で返す（テンプレは cv2.imread=BGR で読まれるため）。"""
    rgb = np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_rgb(name):
    return np.array(Image.open(os.path.join(FRAMES, name)).convert("RGB"))


def detect(frame):
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.templates = AL.load_templates()
    al.win = {"x": 0, "y": 0, "w": frame.shape[1], "h": frame.shape[0]}
    al.content = (38, frame.shape[0] - 9)
    al.verbose = False
    al._last_dark_check = 0.0
    return al.detect(frame)


class TestKinakoRowDetection(unittest.TestCase):
    def test_row_found_when_kinako_in_stock(self):
        """きなこパンがあるときは行を検出できること（検出できないと回復できず周回が止まる）。"""
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(PRESENT), imgs)
        self.assertIsNotNone(pos)
        self.assertGreaterEqual(score, thr, f"きなこパン行を見失った (score={score:.3f})")

    def test_row_absent_when_depleted(self):
        """枯渇時は行が存在せず、閾値を下回ること。

        ここが下回らないと「無いのに有ると誤認」してステラを押す。
        """
        imgs, thr = AL.load_templates()["kinakorow"]
        score, _ = AL.match_best(load(DEPLETED), imgs)
        self.assertLess(score, thr,
                        f"枯渇フレームで誤検出 (score={score:.3f} >= {thr})")

    def test_separation_margin_is_wide(self):
        """有り／無しのスコア差が十分にあること（閾値をまたぐ余裕の確認）。"""
        imgs, _ = AL.load_templates()["kinakorow"]
        present, _ = AL.match_best(load(PRESENT), imgs)
        depleted, _ = AL.match_best(load(DEPLETED), imgs)
        self.assertGreater(present - depleted, 0.30,
                           f"分離が不十分 present={present:.3f} depleted={depleted:.3f}")


class TestClickTargetSafety(unittest.TestCase):
    def test_row_anchor_lands_on_kinako_recover_button(self):
        """きなこパン行を基準にしたオフセットが、その行の「回復」ボタンに当たること。"""
        imgs, _ = AL.load_templates()["kinakorow"]
        _, pos = AL.match_best(load(PRESENT), imgs)
        x = pos[0] + AL.ANCH_KINAKO_ROW[0]
        y = pos[1] + AL.ANCH_KINAKO_ROW[1]
        # 実測したきなこパン「回復」ボタンの矩形（671x348 上）
        self.assertTrue(385 <= x <= 432, f"x={x:.0f} が「回復」ボタンの外")
        self.assertTrue(162 <= y <= 186, f"y={y:.0f} が「回復」ボタンの外")

    def test_old_headline_anchor_would_have_hit_stella(self):
        """旧実装（見出し基準の固定オフセット）が枯渇時にステラを押していたことの記録。

        この不具合が二度と復活しないよう、事故の形を残しておく。**このテストが失敗する
        （＝旧オフセットがステラに当たらなくなる）ことは想定していない**。もし将来
        ダイアログの構造が変わって失敗したら、C-1 の前提が変わったということなので
        docs/screen-flow.md「課金事故を防ぐ設計」を見直すこと。
        """
        frame = load_rgb(DEPLETED)
        state, res = detect(frame)
        self.assertEqual("lifeshort", state)
        cx, cy = res["lifeshort"][2]
        x, y = cx + 128.0, cy + 62.0        # 旧 ANCH_KINAKO
        x0, y0, x1, y1 = STELLA_BUTTON
        self.assertTrue(x0 <= x <= x1 and y0 <= y <= y1,
                        f"旧オフセットの着弾点 ({x:.0f},{y:.0f}) が "
                        f"ステラボタン {STELLA_BUTTON} の外")

    def test_matching_uses_bgr_frames(self):
        """RGB フレームのまま照合すると閾値を割ることの記録（色空間の取り違え防止）。

        テンプレは cv2.imread（BGR）で読まれるので、照合も BGR で行わなければならない。
        RGB のまま渡すとスコアが落ち、閾値付近の判定が静かに壊れる。
        """
        imgs, thr = AL.load_templates()["kinakorow"]
        rgb_score, _ = AL.match_best(load_rgb(PRESENT), imgs)
        bgr_score, _ = AL.match_best(load(PRESENT), imgs)
        self.assertGreater(bgr_score, rgb_score)
        self.assertLess(rgb_score, thr, "RGB照合でも閾値を超えるならこのテストは無意味")

    def test_no_headline_based_kinako_anchor_remains(self):
        """見出し基準の ANCH_KINAKO が復活していないこと。"""
        self.assertFalse(hasattr(AL, "ANCH_KINAKO"),
                         "ANCH_KINAKO（見出し基準）が残っている。枯渇時にステラを押す")


class TestPrefixedKinakoRow(unittest.TestCase):
    """ラベルに接頭辞が付いた行（「11周年きなこパン」）でも「回復」を押せること。

    2026-08-28 実機: イベント配布の **11周年きなこパン**（所持154個）で LIFE 回復が
    6回連続で空振りし、`life_short_persist` で安全停止した。ステラは押していないので
    課金事故ではないが、周回は止まる。

    原因は固定オフセット方式。`kinakorow` テンプレは「きなこパン」部分に一致するため、
    「11周年」の接頭辞があるとマッチ中心が右へずれ、そのぶん着弾点も右へ動いて
    ボタンの右端(x=441)を 2px 外していた（着弾 x=443）。
    **「回復」ボタン自体は両フレームで同一位置** (x=386..441, y=164..185) にあるので、
    ボタンを直接見つけて押せばラベルの文言に依存しなくなる。
    """

    # 実測（両フレームで同一）: きなこパン行の「回復」ボタン
    KINAKO_BUTTON = (386, 164, 441, 185)
    # 実測: ステラストーン行の「回復」ボタン。**ここに入ったら課金事故**
    STELLA_BUTTON_671 = (386, 225, 441, 246)

    def _point(self, name):
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(name), imgs)
        self.assertGreaterEqual(score, thr, f"きなこパン行を見失った (score={score:.3f})")
        return AL.kinako_recover_point(load_rgb(name), pos)

    def test_lands_on_recover_button_with_prefixed_label(self):
        x, y = self._point("lifeshort_kinako_11th_671x348.png")
        x0, y0, x1, y1 = self.KINAKO_BUTTON
        self.assertTrue(x0 <= x <= x1, f"x={x:.0f} が「回復」ボタン({x0}..{x1})の外")
        self.assertTrue(y0 <= y <= y1, f"y={y:.0f} が「回復」ボタン({y0}..{y1})の外")

    def test_lands_on_recover_button_without_prefix(self):
        """接頭辞なしの既存フレームでも同じ関数で当たること（回帰）。"""
        x, y = self._point(PRESENT)
        x0, y0, x1, y1 = self.KINAKO_BUTTON
        self.assertTrue(x0 <= x <= x1, f"x={x:.0f} が「回復」ボタンの外")
        self.assertTrue(y0 <= y <= y1, f"y={y:.0f} が「回復」ボタンの外")

    def test_never_lands_on_stella_row(self):
        """どちらのフレームでも、ステラストーン行の「回復」には絶対に入らないこと。"""
        for name in ("lifeshort_kinako_11th_671x348.png", PRESENT):
            with self.subTest(frame=name):
                _, y = self._point(name)
                y0, y1 = self.STELLA_BUTTON_671[1], self.STELLA_BUTTON_671[3]
                self.assertFalse(y0 <= y <= y1,
                                 f"y={y:.0f} がステラ行のボタン({y0}..{y1})に入った")


KYOMEI = "lifeshort_kinako_kyomei_671x348.png"   # 共鳴のきなこパン（所持 1062）・ステラ 869


class TestKinakoPlusStepper(unittest.TestCase):
    """きなこ行の数量ステッパー「+」（2026-10-20 改訂: 個数は OCR で読んで毎回決める）。

    「+」の点は**きなこ行のテンプレ一致 → その行の「回復」ボタン**から求める。ステラ行は
    0.26h 下にありステッパーを持たない。ここで固定するのは「+」がきなこ行の中・「回復」の左に
    あり、ステラ行から十分離れていること。
    """

    # 実測（671x348）: きなこ行の青いステッパー箱と白い「+」、ステラ行の「回復」
    STEPPER_BOX = (285, 162, 363, 186)
    PLUS_CROSS = (349, 169, 360, 180)
    STELLA_BUTTON_671 = (386, 225, 441, 246)

    def _points(self, name):
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(name), imgs)
        self.assertGreaterEqual(score, thr, f"きなこパン行を見失った (score={score:.3f})")
        rgb = load_rgb(name)
        rec = AL.kinako_recover_point(rgb, pos)
        return pos, rec, AL.kinako_plus_point(rgb, rec)

    def test_kyomei_row_matches_with_measured_score(self):
        """共鳴のきなこパンは閾値 0.80 に対し 0.83 と余裕が小さい（実測の記録）。"""
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(KYOMEI), imgs)
        self.assertGreaterEqual(score, thr)
        self.assertAlmostEqual(341.0, pos[0], delta=2)
        self.assertAlmostEqual(144.5, pos[1], delta=2)

    def test_plus_lies_on_the_cross_inside_the_kinako_stepper(self):
        for name in (KYOMEI, PRESENT, "lifeshort_kinako_11th_671x348.png"):
            with self.subTest(frame=name):
                _, rec, plus = self._points(name)
                self.assertIsNotNone(plus, "きなこ行の「+」が見つからない")
                x, y = plus
                x0, y0, x1, y1 = self.PLUS_CROSS
                self.assertTrue(x0 <= x <= x1 and y0 <= y <= y1,
                                f"「+」({x:.0f},{y:.0f}) が十字 {self.PLUS_CROSS} の外")
                bx0, by0, bx1, by1 = self.STEPPER_BOX
                self.assertTrue(bx0 <= x <= bx1 and by0 <= y <= by1, "ステッパーの箱の外")

    def test_plus_is_left_of_recover_on_the_same_row(self):
        for name in (KYOMEI, PRESENT, "lifeshort_kinako_11th_671x348.png"):
            with self.subTest(frame=name):
                _, rec, plus = self._points(name)
                self.assertLess(plus[0], rec[0] - 20, "「+」が「回復」の左にない")
                self.assertLess(abs(plus[1] - rec[1]), 0.04 * 348, "「+」が「回復」と別の行")

    def test_plus_is_far_from_the_stella_row(self):
        """**「+」はステラ行から十分離れていること**（ステラ行の「回復」の上端より 0.1h 以上上）。"""
        for name in (KYOMEI, PRESENT, "lifeshort_kinako_11th_671x348.png"):
            with self.subTest(frame=name):
                _, _, plus = self._points(name)
                self.assertLess(plus[1], self.STELLA_BUTTON_671[1] - 0.1 * 348,
                                f"「+」y={plus[1]:.0f} がステラ行に近い")

    def test_no_plus_on_the_stella_row(self):
        """ステラ行の「回復」を基準にしても「+」は見つからない（ステラ行にステッパーは無い）。"""
        rgb = load_rgb(KYOMEI)
        x0, y0, x1, y1 = self.STELLA_BUTTON_671
        self.assertIsNone(AL.kinako_plus_point(rgb, ((x0 + x1) / 2, (y0 + y1) / 2)))



# 数量 → その数量を表示している実機フレーム。間の数量は「3 ではない・1 でもない」ものを返す
# （2 は 1 の字形にならないが、ここでは 1/3 以外の扱いが同じになる 7 で代用する）。
QTY_FRAMES = {1: "lifeshort_kinako_kyomei_671x348.png", 3: "lifeshort_kinako_qty3_671x348.png",
              7: "lifeshort_kinako_qty7_671x348.png", 10: "lifeshort_kinako_qty10_671x348.png"}


def _qty_frame(q):
    if q in (1, 3):
        return QTY_FRAMES[q]
    return QTY_FRAMES[10] if q >= 10 else QTY_FRAMES[7]


class _FakeLive(AL.AutoLive):
    """_recover_life を実機なしで回す。撮影は固定フレーム、クリックは記録するだけ。

    qty を与えるとステッパーを模擬する: 「+」(x 340..370) で +1、「−」(x 280..305) で −1、
    撮影は数量に応じた実機フレーム（1/3/7/10。間の数は近い方）を返す。

    OCR 読み取りはメソッド越しに差し替えられる:
    - ``qty``      : 数量欄の読みスタブ（整数）。None なら実フレームの本物の OCR。
    - ``per_pan``  : 1個の回復量のスタブ（None=実フレームの OCR）。
    - ``life``     : 現在 LIFE のスタブ（None=実フレームの OCR）。リストなら
                     _recover_life 呼び出しごとに次の値を返す（回復間の増加を模擬）。
    - ``life_cost``: ライブの LIFE コスト（既定 None → _life_cost() は 100 に縮退）。
    """

    def __init__(self, frames, qty=None, qty_seq=None, per_pan=None, life=None,
                 life_cost=None):
        self.templates = AL.load_templates()
        self.win = {"x": 0, "y": 0, "w": frames[0].shape[1], "h": frames[0].shape[0]}
        self.content = (38, frames[0].shape[0] - 9)
        self.dry_run = False
        self.verbose = False
        self.life_recovers = 1
        self.life_cost = life_cost
        self._kinako_prev_life = None
        self._life_no_gain = 0
        self.dbg_dir = "/tmp/i7dbg_test"
        os.makedirs(self.dbg_dir, exist_ok=True)
        self.t_start = 0.0
        self.loops_done = 0
        self.max_loops = 1
        self._frames = list(frames)
        self._frame_bgr = None
        self.clicks = []
        self.qty = qty
        self._qty_seq = list(qty_seq) if qty_seq else None
        self._seq_i = 0
        self._per_pan_stub = per_pan
        self._life_seq = list(life) if isinstance(life, (list, tuple)) else None
        self._life_stub = None if self._life_seq is not None else life
        self._life_i = 0
        self.recover_qty = None    # 「回復」を押した時の数量

    def _qty_ocr(self, frame, ref):
        if self.qty is not None and self._qty_seq is None:
            return self.qty      # スタブ（整数）
        return AL.kinako_qty_ocr(frame, ref)   # 実フレームの本物の OCR

    def _per_pan_ocr(self, frame, row_pos):
        if self._per_pan_stub is not None:
            return self._per_pan_stub
        return AL.kinako_per_pan_ocr(frame, row_pos)

    def _life_ocr(self, frame, row_pos):
        if self._life_seq is not None:
            i = min(self._life_i, len(self._life_seq) - 1)
            return self._life_seq[i]
        if self._life_stub is not None:
            return self._life_stub
        return AL.dialog_life_ocr(frame, row_pos)

    def _grab(self):
        if self._qty_seq is not None:
            q = self._qty_seq[min(self._seq_i, len(self._qty_seq) - 1)]
            self._seq_i += 1
            self.qty = q      # 「回復」着弾時に数量を記録するため
            return load_rgb(_qty_frame(q))
        if self.qty is not None:
            return load_rgb(_qty_frame(self.qty))
        return self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]

    def _click_screen(self, px, py):
        x, y = px - self.win["x"], py - self.win["y"]
        self.clicks.append((x, y))
        if self.qty is not None and 165 <= y <= 185:
            if 340 <= x <= 370:
                self.qty += 1
            elif 280 <= x <= 305:
                self.qty = max(1, self.qty - 1)
            elif 386 <= x <= 441:
                self.recover_qty = self.qty
                if self._life_seq is not None:
                    self._life_i += 1   # 「回復」着弾＝次のダイアログでは LIFE が増えている想定

    def log(self, msg):
        pass

class TestRecoverFlow(unittest.TestCase):
    """_recover_life のクリック列（実機不要。time.sleep は潰す）。

    2026-10-20 改訂: 個数 n は「1個の回復量・現在 LIFE・コスト」を OCR で読んで
    `ceil((コスト−LIFE)/回復量)`（1..KINAKO_MAX_PER_RECOVER）から毎回決める。
    「+」はダイアログ1回の出現につき1セット（n−数量 回）だけ。数量が n を超える／
    赤い「上限を超えています」が出ているときは「−」で戻し、バッジが出ている間は
    「回復」を押さない。
    """

    def setUp(self):
        self._sleep = AL.time.sleep
        AL.time.sleep = lambda s: None
        self._saved = (AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC,
                       AL.KINAKO_RECOVER_MAX_SEC, AL.KINAKO_LOW_SETTLE_SEC,
                       AL.KINAKO_HIGH_SETTLE_SEC)
        AL.LIFE_CONFIRM_WAIT_SEC = 0.0
        # 実時間のデッドライン自体は残すが、sleep を潰したテストでは照合時間だけが
        # 実時間を消費するので、負荷時でも割れないよう大きく取る
        # （実質「イテレーション数の上限」として働く）。個別のテストで上書き可。
        AL.KINAKO_RECHECK_SEC = 30.0
        AL.KINAKO_RECOVER_MAX_SEC = 30.0

    def tearDown(self):
        AL.time.sleep = self._sleep
        (AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC,
         AL.KINAKO_RECOVER_MAX_SEC, AL.KINAKO_LOW_SETTLE_SEC,
         AL.KINAKO_HIGH_SETTLE_SEC) = self._saved

    def _assert_never_stella(self, clicks):
        sx0, sy0, sx1, sy1 = TestKinakoPlusStepper.STELLA_BUTTON_671
        for x, y in clicks:
            self.assertFalse(sy0 - 10 <= y <= sy1 + 10, f"ステラ行の高さに着弾 ({x:.0f},{y:.0f})")

    def _assert_last_is_kinako_recover(self, clicks):
        kx0, ky0, kx1, ky1 = TestPrefixedKinakoRow.KINAKO_BUTTON
        x, y = clicks[-1]
        self.assertTrue(kx0 <= x <= kx1 and ky0 <= y <= ky1, f"きなこ「回復」の外 ({x:.0f},{y:.0f})")

    def test_depleted_frame_clicks_nothing(self):
        """**枯渇フレームでは撮り直しの間も含めて一切クリックしない**（kinako_missing）。"""
        fr = load_rgb(DEPLETED)
        al = _FakeLive([fr])
        AL.KINAKO_RECHECK_SEC = 0.05
        status, _, _ = al._recover_life(fr)
        self.assertEqual("kinako_missing", status)
        self.assertEqual([], al.clicks, "枯渇時にクリックした（ステラ誤消費の危険）")

    def test_fresh_dialog_plus_twice_then_recover_at_three(self):
        """開いた直後（数量 1）→ 読み値 n=3（回復量30・LIFE20・コスト100）→「+」ちょうど2回
        → 数量 3 を確認して「回復」。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr], qty=1)
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(3, al.recover_qty, "数量 3 で「回復」を押していない")
        self.assertEqual(3, len(al.clicks), al.clicks)
        x0, y0, x1, y1 = TestKinakoPlusStepper.PLUS_CROSS
        for x, y in al.clicks[:2]:
            self.assertTrue(x0 <= x <= x1 and y0 <= y <= y1, f"「+」の外 ({x:.0f},{y:.0f})")
        self._assert_last_is_kinako_recover(al.clicks)
        self._assert_never_stella(al.clicks)

    def test_plus_is_pressed_only_once_per_dialog(self):
        """「+」を押しても数量が n に届かないなら押し直さない。
        数量が確定したまま n 未満で KINAKO_LOW_SETTLE_SEC 経つと、その数量で回復する
        （在庫上限に届いた想定）。unsettled で終わった同じダイアログの再呼び出しでは
        kinako_plus_at が効いて「+」を二度押さない。"""
        fr = load_rgb(KYOMEI)
        # qty_seq=[1,...] は「+」を押しても数量が上がらない出現を模す
        # （撮影は常に数量 1 の kyomei フレームで、数量 OCR も 1 を読む）。
        al = _FakeLive([fr], qty_seq=[1] * 12)
        AL.KINAKO_LOW_SETTLE_SEC = 1.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(1, al.recover_qty, "確定数量 1 で回復していない")
        self.assertEqual(3, len(al.clicks), "「+」2回＋「回復」以外を押した")
        # 「+」を押したのに数量が上がらないまま確定し続ける（反映が極端に遅い想定）:
        # その出現では二度押さず、時間切れで unsettled。再呼び出しでも kinako_plus_at が
        # 残っているうちは「+」を押さない。
        fr2 = load_rgb(KYOMEI)
        al2 = _FakeLive([fr2], qty_seq=[1] * 60)
        AL.KINAKO_RECOVER_MAX_SEC = 6.0
        AL.KINAKO_LOW_SETTLE_SEC = 100.0   # 低数量確定で回復しない＝unsettled まで待つ
        status, _, _ = al2._recover_life(fr2)
        self.assertEqual("unsettled", status)
        self.assertEqual(2, len(al2.clicks), "「+」の回数が違う")
        status, _, _ = al2._recover_life(fr2)
        self.assertEqual("unsettled", status)
        self.assertEqual(2, len(al2.clicks), "同じダイアログで「+」を押し直した")

    def test_overcap_start_backs_off_with_minus_then_recovers_at_three(self):
        """**現在の実機の状態**: 積み増しで数量 10・赤い「上限を超えています」。
        「+」は押さず「−」で読み値 n=3（回復量30・LIFE27・コスト100）まで戻し、
        3 を確認してから「回復」。バッジ中は回復を押さない。"""
        fr = load_rgb("lifeshort_kinako_overcap_671x348.png")
        al = _FakeLive([fr], qty=10)
        AL.KINAKO_RECHECK_SEC = 4.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(3, al.recover_qty)
        self.assertEqual(7, len(al.clicks) - 1, f"「−」の回数が違う: {al.clicks}")
        for x, y in al.clicks[:-1]:
            self.assertTrue(280 <= x <= 305, f"「−」以外を押した ({x:.0f},{y:.0f})")
        self._assert_last_is_kinako_recover(al.clicks)
        self._assert_never_stella(al.clicks)

    def test_overcap_badge_blocks_recover(self):
        """「−」が見つからない（＝戻せない）ままバッジが出ていれば、回復は押さない。"""
        fr = load_rgb("lifeshort_kinako_overcap_671x348.png").copy()
        fr[165:185, 285:305] = (75, 95, 135)       # 「−」を塗り潰す
        al = _FakeLive([fr])
        AL.KINAKO_RECHECK_SEC = 0.2
        AL.KINAKO_RECOVER_MAX_SEC = 2.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("unsettled", status)
        self.assertEqual([], al.clicks)

    def test_banner_frame_is_the_overcap_state(self):
        """2026-10-11 21:52 の停止フレーム（右上に macOS の通知バナー、数量 10・バッジ）。
        行のスコアはバナーの影響を受けず 0.832。停止の原因はキラキラ演出で 0.72〜0.80 に落ちる
        フレームと、やり直しのたびに「+」を積み増したこと。今は「−」で戻して n=3 で回復する。"""
        fr = load_rgb("lifeshort_kinako_banner_671x348.png")
        imgs, thr = AL.load_templates()["kinakorow"]
        self.assertGreaterEqual(AL.match_best(load("lifeshort_kinako_banner_671x348.png"), imgs)[0], thr)
        rec = AL.kinako_recover_point(fr, AL.match_best(load("lifeshort_kinako_banner_671x348.png"), imgs)[1])
        self.assertTrue(AL.kinako_over_cap(fr, rec))
        al = _FakeLive([fr], qty=10)
        AL.KINAKO_RECHECK_SEC = 4.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(3, al.recover_qty)

    def test_sparkle_frames_are_waited_out(self):
        """キラキラ演出で行が割れるフレームが挟まっても、行が2枚続けて見えるフレームで進める。"""
        good = load_rgb("lifeshort_kinako_qty3_671x348.png")
        bad = load_rgb("lifeshort_kinako_sparkle_671x348.png")
        imgs, thr = AL.load_templates()["kinakorow"]
        self.assertLess(AL.match_best(load("lifeshort_kinako_sparkle_671x348.png"), imgs)[0], thr,
                        "演出フレームが閾値を超えるならこのテストは無意味")
        al = _FakeLive([bad, bad, good, bad, good, good, good])
        al.kinako_plus_at = (AL.time.time(), (341.0, 144.5), (354.5, 174.5))   # 「+」は押し済み
        status, _, _ = al._recover_life(bad)
        self.assertEqual("recovered", status)
        self.assertEqual(1, len(al.clicks))
        self._assert_last_is_kinako_recover(al.clicks)

    def test_mid_animation_two_never_triggers_minus(self):
        """「+」×2 の直後のカウントアップで一瞬「2」が見えても「−」を押さない。
        （旧設計では「1でも3でもない」で即「−」に分岐し、数量を戻して「+」済みのまま
        増やせなくなり kinako_unsettled まで止まった。今は同じ読みが連続するまで確定しない。）
        数量列: 1(2読) →「+」×2 → 2,2（演出途中）→ 3,3… で「−」0回・数量3で回復。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr], qty_seq=[1, 1, 2, 2, 3, 3, 3, 3, 3])
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(3, al.recover_qty)
        x0, y0, x1, y1 = TestKinakoPlusStepper.PLUS_CROSS
        plus = [c for c in al.clicks if x0 <= c[0] <= x1 and y0 <= c[1] <= y1]
        minus = [c for c in al.clicks if 280 <= c[0] <= 305]
        self.assertEqual(2, len(plus), f"「+」の回数: {al.clicks}")
        self.assertEqual([], minus, f"演出途中の「2」で「−」を押した: {al.clicks}")
        self._assert_last_is_kinako_recover(al.clicks)
        self._assert_never_stella(al.clicks)

    def test_settled_other_backs_off_with_minus(self):
        """バッジ無しで数量が確定して 3 より多い（積み増し残りの 7）→「−」で 3 まで戻す。"""
        fr = load_rgb("lifeshort_kinako_qty7_671x348.png")
        al = _FakeLive([fr], qty=7)
        AL.KINAKO_RECHECK_SEC = 4.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(3, al.recover_qty)
        for x, y in al.clicks[:-1]:
            self.assertTrue(280 <= x <= 305, f"「−」以外を押した ({x:.0f},{y:.0f})")
        self._assert_last_is_kinako_recover(al.clicks)
        self._assert_never_stella(al.clicks)

    def test_without_plus_falls_back_to_single_recover(self):
        """「+」が見つからない（ステッパーの「+」を塗り潰した）・数量 1 なら「回復」だけを押す。"""
        fr = load_rgb(KYOMEI).copy()
        fr[163:186, 340:363] = (75, 95, 135)
        al = _FakeLive([fr])
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(1, len(al.clicks), al.clicks)
        self._assert_last_is_kinako_recover(al.clicks)

    def test_quantity_readers_on_real_frames(self):
        """数量欄は整数として読む（`kinako_qty_ocr`）。「1」は OCR が落とすので
        `kinako_qty_is_one`（画素判定）で補う。"""
        cases = {KYOMEI: 1, PRESENT: 1,
                 "lifeshort_kinako_11th_671x348.png": 1,
                 "lifeshort_kinako_qty3_671x348.png": 3,
                 "lifeshort_kinako_qty7_671x348.png": 7,
                 "lifeshort_kinako_qty10_671x348.png": 10}
        for name, qty in cases.items():
            with self.subTest(frame=name):
                fr = load_rgb(name)
                _, pos = AL.match_best(load(name), AL.load_templates()["kinakorow"][0])
                rec = AL.kinako_recover_point(fr, pos)
                plus = AL.kinako_plus_point(fr, rec)
                self.assertIsNotNone(plus)
                self.assertEqual(qty == 1, AL.kinako_qty_is_one(fr, plus))
                self.assertEqual(qty, AL.kinako_qty_ocr(fr, plus))
                self.assertEqual(name.endswith(("qty10_671x348.png",)),
                                 AL.kinako_over_cap(fr, rec))

    def test_minus_lies_on_the_kinako_stepper(self):
        fr = load_rgb(KYOMEI)
        _, pos = AL.match_best(load(KYOMEI), AL.load_templates()["kinakorow"][0])
        rec = AL.kinako_recover_point(fr, pos)
        x, y = AL.kinako_minus_point(fr, AL.kinako_plus_point(fr, rec))
        bx0, by0, bx1, by1 = TestKinakoPlusStepper.STEPPER_BOX
        self.assertTrue(bx0 <= x <= bx0 + 20 and by0 <= y <= by1, f"「−」({x:.0f},{y:.0f}) が箱の左端の外")


class TestLifeRecoverOcr(unittest.TestCase):
    """LIFE 回復の OCR 読み取りを実機フィクスチャで固定する（2026-10-20 改訂）。

    - 1個の回復量: きなこ行ラベル `…きなこパン：LIFE N 回復`（`kinako_per_pan_ocr`）。
    - 現在 LIFE  : ダイアログ右上の `LIFE ♥ N`（`dialog_life_ocr`）。
    - 数量欄     : 整数（`kinako_qty_ocr`。1 は `kinako_qty_is_one` で補う）。
    - コスト     : フレンド選択の上部バッジ `♥-N`（`life_cost_ocr`）。

    切り出しはすべて行のテンプレ一致位置（数量欄は「+」位置）基準の相対位置。
    656x341 のフィクスチャは行の一致位置が変わりうるため、明示的な row_pos を渡す。
    """

    def _row_pos(self, name):
        imgs, thr = AL.load_templates()["kinakorow"]
        score, pos = AL.match_best(load(name), imgs)
        self.assertGreaterEqual(score, thr, f"きなこ行を見失った ({name}, {score:.3f})")
        return pos

    def test_per_pan_on_all_kinako_fixtures(self):
        """既知の回復量が読める: 共鳴=30、旧イベント（present/11th）=20。
        **2 種類の回復量がフィクスチャ間に存在すること**（イベント差の実在）。"""
        expected = {"lifeshort_kinako_present_671x348.png": 20,
                    "lifeshort_kinako_11th_671x348.png": 20,
                    "lifeshort_kinako_kyomei_671x348.png": 30,
                    "lifeshort_kinako_qty3_671x348.png": 30,
                    "lifeshort_kinako_qty7_671x348.png": 30,
                    "lifeshort_kinako_qty10_671x348.png": 30,
                    "lifeshort_kinako_overcap_671x348.png": 30,
                    "lifeshort_kinako_banner_671x348.png": 30}
        seen = set()
        for name, want in expected.items():
            with self.subTest(frame=name):
                got = AL.kinako_per_pan_ocr(load_rgb(name), self._row_pos(name))
                self.assertEqual(want, got)
                seen.add(got)
        self.assertGreaterEqual(len(seen), 2,
                                f"回復量のバリエーションが1種類しかない: {seen}")

    def test_per_pan_on_656_fixtures_with_explicit_row_pos(self):
        """656x341 のフィクスチャ（行の一致位置は他タスクの変更で動くため明示渡し）。"""
        for name in ("lifeshort_kinako_qty1_656x341.png",
                     "lifeshort_kinako_qty3_656x341.png"):
            with self.subTest(frame=name):
                got = AL.kinako_per_pan_ocr(load_rgb(name), (329.0, 143.0))
                self.assertEqual(30, got)

    def test_current_life_on_all_kinako_fixtures(self):
        """現在 LIFE が読める（実測値。1桁の「6」は白文字二値化で読む）。

        「0」は Vision が読めない（2026-10-20 実測、二値化しても None）。読めないときの
        _recover_life は n=1 に縮退するので安全側。枯渇フレームはきなこ行が消えており
        LIFE を読む段階に来ないので、ここでは対象にしない。"""
        expected = {"lifeshort_kinako_kyomei_671x348.png": 20,
                    "lifeshort_kinako_qty3_671x348.png": 27,
                    "lifeshort_kinako_qty7_671x348.png": 27,
                    "lifeshort_kinako_qty10_671x348.png": 27,
                    "lifeshort_kinako_overcap_671x348.png": 71,
                    "lifeshort_kinako_banner_671x348.png": 27,
                    "lifeshort_kinako_11th_671x348.png": 14,
                    "lifeshort_kinako_present_671x348.png": 6}
        for name, want in expected.items():
            with self.subTest(frame=name):
                pos = self._row_pos(name)
                got = AL.dialog_life_ocr(load_rgb(name), pos)
                self.assertEqual(want, got)

    def test_current_life_on_656_fixtures_with_explicit_row_pos(self):
        expected = {"lifeshort_kinako_qty1_656x341.png": 50,
                    "lifeshort_kinako_qty3_656x341.png": 97}
        for name, want in expected.items():
            with self.subTest(frame=name):
                self.assertEqual(want,
                                 AL.dialog_life_ocr(load_rgb(name), (329.0, 143.0)))

    def test_qty_on_656_fixtures(self):
        """656x341 の数量欄（ステッパーの「+」から求めた領域）を整数で読む。"""
        expected = {"lifeshort_kinako_qty1_656x341.png": 1,
                    "lifeshort_kinako_qty3_656x341.png": 3}
        imgs, thr = AL.load_templates()["kinakorow"]
        for name, want in expected.items():
            with self.subTest(frame=name):
                fr = load_rgb(name)
                _, pos = AL.match_best(load(name), imgs)
                rec = AL.kinako_recover_point(fr, pos)
                plus = AL.kinako_plus_point(fr, rec)
                self.assertIsNotNone(plus)
                self.assertEqual(want, AL.kinako_qty_ocr(fr, plus))

    def test_cost_badge_on_friendselect_and_formation(self):
        """上部バッジ「♥-N」からコストを読む。バッジの位置は画面と窓サイズで変わる
        （656x341 フレンド選択は y≈0.24、529x334 編成は y≈0.33）。片方だけに合わせた
        切り出しだと、もう片方で黙って None になり KINAKO_ASSUMED_COST(100) に縮退する
        （3倍ブーストの -5/-15 イベントで 20 倍のパンを使う）。"""
        self.assertEqual(100, AL.life_cost_ocr(load_rgb("friendselect_656x341.png")))
        self.assertEqual(5, AL.life_cost_ocr(load_rgb("formation_cost5_529x334.png")))

    def test_cost_badge_absent_reads_none(self):
        """バッジの無い画面ではコストを読まない（LIFE 不足ダイアログの「LIFE 30 回復」等を
        コストと取り違えない）。"""
        self.assertIsNone(AL.life_cost_ocr(load_rgb("lifeshort_kinako_qty3_671x348.png")))


class TestRecoverCountFromOcr(unittest.TestCase):
    """個数 n と枯渇判定（2026-10-20 改訂の中心要件）。OCR 読みはスタブ/実フレーム併用。"""

    def setUp(self):
        self._sleep = AL.time.sleep
        AL.time.sleep = lambda s: None
        self._saved = (AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC,
                       AL.KINAKO_RECOVER_MAX_SEC, AL.KINAKO_LOW_SETTLE_SEC)
        AL.LIFE_CONFIRM_WAIT_SEC = 0.0
        AL.KINAKO_RECHECK_SEC = 30.0
        AL.KINAKO_RECOVER_MAX_SEC = 30.0

    def tearDown(self):
        AL.time.sleep = self._sleep
        (AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC,
         AL.KINAKO_RECOVER_MAX_SEC, AL.KINAKO_LOW_SETTLE_SEC) = self._saved

    def test_two_pans_when_30_50_100(self):
        """回復量 30・LIFE 50・コスト 100 → n=2。「+」1回で数量 2 にして回復。"""
        fr = load_rgb("lifeshort_kinako_qty1_656x341.png")
        al = _FakeLive([fr], qty=1, per_pan=30, life=50, life_cost=100)
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(2, al.recover_qty)
        self.assertEqual(2, len(al.clicks), "「+」1回＋「回復」以外を押した")

    def test_one_pan_when_30_97_100(self):
        """回復量 30・LIFE 97・コスト 100 → n=1。「+」を押さずそのまま回復。"""
        fr = load_rgb("lifeshort_kinako_qty3_656x341.png")
        al = _FakeLive([fr], qty=1, per_pan=30, life=97, life_cost=100)
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(1, al.recover_qty)
        self.assertEqual(1, len(al.clicks), "「回復」以外を押した")

    def test_small_per_pan_needs_many_recovers_no_depleted_stop(self):
        """回復量 5・コスト 100。LIFE が少しずつ増える限り、旧 MAX_LIFE_RECOVERS(6) を
        超えて何回でも回復し、毎回 n=ceil((100−LIFE)/5) 個を使う。
        （フィクスチャの数量 10 のフレームは「上限を超えています」バッジ付きなので、
        n ≤ 9 に収まる LIFE で回す。）"""
        fr = load_rgb(KYOMEI)
        lives = [60, 65, 70, 75, 80, 85, 90, 95]
        al = _FakeLive([fr], per_pan=5, life=lives, life_cost=100)
        for i, life in enumerate(lives):
            al.qty = 1
            status, _, _ = al._recover_life(fr)
            self.assertEqual("recovered", status, f"{i+1}回目で止まった")
            self.assertEqual(-(-(100 - life) // 5), al.recover_qty, f"{i+1}回目 LIFE={life}")

    def test_no_gain_stops_after_max(self):
        """「回復」を押しても現在 LIFE が増えない読みが MAX_LIFE_NO_GAIN 回続くと
        life_no_gain（**その呼び出しでは何も押さない**）。最初のダイアログには比較元が
        無いので、増えない読みが MAX 回たまるのは MAX+1 回目の呼び出し。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr], per_pan=30, life=20, life_cost=100)
        statuses = [al._recover_life(fr)[0] for _ in range(AL.MAX_LIFE_NO_GAIN + 1)]
        self.assertEqual("life_no_gain", statuses[-1])
        self.assertEqual(["recovered"] * AL.MAX_LIFE_NO_GAIN, statuses[:-1])

    def test_unreadable_values_fall_back_to_one_pan(self):
        """回復量・現在 LIFE が読めないときは n=1（従来の1個回復相当）。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr], qty=1)
        al._per_pan_ocr = lambda frame, pos: None   # 読めない
        al._life_ocr = lambda frame, pos: None
        status, _, _ = al._recover_life(fr)
        self.assertEqual("recovered", status)
        self.assertEqual(1, al.recover_qty)
        self.assertEqual(1, len(al.clicks))

    def test_unreadable_qty_never_recovers(self):
        """数量欄が読めないまま「回復」は押さない（unsettled）。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr])
        al._qty_ocr = lambda frame, ref: None
        AL.KINAKO_RECOVER_MAX_SEC = 2.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("unsettled", status)
        self.assertEqual([], al.clicks)

    def test_badge_blocks_recover_until_cleared(self):
        """赤バッジが出続ける間は「−」だけで「回復」は押さない。"""
        fr = load_rgb("lifeshort_kinako_overcap_671x348.png")
        al = _FakeLive([fr], qty=10)
        saved = AL.kinako_over_cap
        AL.kinako_over_cap = lambda frame, rec: True     # バッジが消えない想定
        try:
            AL.KINAKO_RECOVER_MAX_SEC = 2.0
            status, _, _ = al._recover_life(fr)
        finally:
            AL.kinako_over_cap = saved
        self.assertEqual("unsettled", status)
        for x, y in al.clicks:
            self.assertTrue(280 <= x <= 305, f"「−」以外を押した ({x:.0f},{y:.0f})")


class TestLifeCard(unittest.TestCase):
    """「ライフを30回復しました」/「ライフが全回復しました」のカード判定（背景タップで閉じる）。"""

    def test_recovery_card_is_detected(self):
        self.assertTrue(AL.life_card_like(load_rgb("life_recovered_card_671x348.png")))

    def test_dialogs_are_not_cards(self):
        for name in (KYOMEI, DEPLETED, "replay_confirm_dialog_671x348.png",
                     "eventresult_tapscreen_671x348.png", "song_result_score_671x348.png",
                     "songselect_event_671x348.png"):
            with self.subTest(frame=name):
                self.assertFalse(AL.life_card_like(load_rgb(name)))


LIFEFULL = "life_full_modal_671x348.png"    # 「ライフを全回復しました。」(Event Result の上)
LIFEFULL2 = "life_full_modal2_671x348.png"  # 同上 2 枚目（cardx_stuck_163）
LIFEFULL_X = (467.0, 120.0)                 # 実機で手押しが効いた × の位置（671x348）


class TestLifeFullModal(unittest.TestCase):
    """「ライフを全回復しました。」モーダル（2026-10-11 実機）。
    **背景タップでは閉じない**（cardx に流れて P_CARD_DISMISS を約30回踏んで cardx_stuck。
    別の回では楽曲選択の上に出て NEXT を約30回飲み込んだ）。× が必須。"""

    def test_detect_returns_lifefull(self):
        for name in (LIFEFULL, LIFEFULL2):
            with self.subTest(frame=name):
                state, _res = detect(load_rgb(name))
                self.assertEqual("lifefull", state)

    def test_detected_before_songselect_cardx_closex(self):
        order = detect(load_rgb(LIFEFULL))
        self.assertEqual("lifefull", order[0])
        # 楽曲選択やダイアログの上に重なっても lifefull が先に返る並びであること。
        # （songselect は暗い側の救済 return もあるので**明るい側＝最後の出現**で比較する）
        states = ("lifeshort", "lifefull", "songselect", "cardx", "closex")
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                                "autolive.py"), encoding="utf-8").read()
        det = src[src.index("def detect("):src.index("def _grab(")]
        names = [s for _, s in sorted((det.rindex(f'return "{s}"'), s) for s in states)]
        self.assertLess(names.index("lifefull"), names.index("songselect"))
        self.assertLess(names.index("lifefull"), names.index("cardx"))
        self.assertLess(names.index("lifefull"), names.index("closex"))

    def test_x_anchor_lands_on_close_button(self):
        """本文テンプレのマッチ位置 + ANCH_LIFEFULL_X が × の ±6px に入る。"""
        for name in (LIFEFULL, LIFEFULL2):
            with self.subTest(frame=name):
                _state, res = detect(load_rgb(name))
                x = res["lifefull"][2][0] + AL.ANCH_LIFEFULL_X[0]
                y = res["lifefull"][2][1] + AL.ANCH_LIFEFULL_X[1]
                self.assertAlmostEqual(LIFEFULL_X[0], x, delta=6.0)
                self.assertAlmostEqual(LIFEFULL_X[1], y, delta=6.0)

    def test_modal_is_not_other_states(self):
        """きなこ行ダイアログ・回復カード・連続ライブダイアログでは当たらない。"""
        imgs, thr = AL.load_templates()["lifefull"]
        for name in (KYOMEI, DEPLETED, "life_recovered_card_671x348.png",
                     "replay_confirm_dialog_671x348.png",
                     "songselect_event_671x348.png", PRESENT):
            with self.subTest(frame=name):
                sc, _ = AL.match_best(load(name), imgs)
                self.assertLess(sc, thr, f"{name} が全回復モーダルと誤認された ({sc:.3f})")


if __name__ == "__main__":
    unittest.main()
