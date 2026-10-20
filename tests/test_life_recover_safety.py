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
    """きなこ行の数量ステッパー「+」（2026-10-11, KINAKO_PER_RECOVER 個まとめて回復）。

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

    def test_per_recover_count_is_three(self):
        self.assertEqual(3, AL.KINAKO_PER_RECOVER)


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
    撮影は数量に応じた実機フレーム（1/3/7/10。間の数は近い方）を返す。"""

    def __init__(self, frames, qty=None, qty_seq=None):
        self.templates = AL.load_templates()
        self.win = {"x": 0, "y": 0, "w": frames[0].shape[1], "h": frames[0].shape[0]}
        self.content = (38, frames[0].shape[0] - 9)
        self.dry_run = False
        self.verbose = False
        self.life_recovers = 1
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
        self.recover_qty = None    # 「回復」を押した時の数量

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

    def log(self, msg):
        pass

class TestRecoverFlow(unittest.TestCase):
    """_recover_life のクリック列（実機不要。time.sleep は潰す）。

    ユーザー指定（2026-10-11）: 「+」はダイアログ1回の出現につき**ちょうど2回**（1 → 3）押して
    「回復」。同じダイアログでは二度と押さない。数量が 3 を超えている／赤い「上限を超えています」が
    出ているときは「−」で戻し、バッジが出ている間は「回復」を押さない。
    """

    def setUp(self):
        self._sleep = AL.time.sleep
        AL.time.sleep = lambda s: None
        self._saved = (AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC)
        AL.LIFE_CONFIRM_WAIT_SEC = 0.0
        # 実時間のデッドライン自体は残すが、sleep を潰したテストでは照合時間だけが
        # 実時間を消費するので、負荷時でも割れないよう大きく取る
        # （実質「イテレーション数の上限」として働く）。個別のテストで上書き可。
        AL.KINAKO_RECHECK_SEC = 30.0

    def tearDown(self):
        AL.time.sleep = self._sleep
        AL.LIFE_CONFIRM_WAIT_SEC, AL.KINAKO_RECHECK_SEC = self._saved

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
        """開いた直後（数量 1）→「+」ちょうど2回 → 数量 3 を確認して「回復」。"""
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
        """「+」が効かない（数量が 1 のまま）なら押し直さず、回復も押さずに unsettled。
        次の呼び出し（同じダイアログ）でも「+」は押さない。"""
        fr = load_rgb(KYOMEI)
        al = _FakeLive([fr])           # 数量は常に 1 のまま（模擬しない）
        AL.KINAKO_RECHECK_SEC = 2.0
        status, _, _ = al._recover_life(fr)
        self.assertEqual("unsettled", status)
        self.assertEqual(2, len(al.clicks), "「+」の回数が違う")
        status, _, _ = al._recover_life(fr)
        self.assertEqual("unsettled", status)
        self.assertEqual(2, len(al.clicks), "同じダイアログで「+」を押し直した")

    def test_overcap_start_backs_off_with_minus_then_recovers_at_three(self):
        """**現在の実機の状態**: 積み増しで数量 10・赤い「上限を超えています」。
        「+」は押さず「−」で 3 まで戻し、3 を確認してから「回復」。バッジ中は回復を押さない。"""
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
        status, _, _ = al._recover_life(fr)
        self.assertEqual("unsettled", status)
        self.assertEqual([], al.clicks)

    def test_banner_frame_is_the_overcap_state(self):
        """2026-10-11 21:52 の停止フレーム（右上に macOS の通知バナー、数量 10・バッジ）。
        行のスコアはバナーの影響を受けず 0.832。停止の原因はキラキラ演出で 0.72〜0.80 に落ちる
        フレームと、やり直しのたびに「+」を積み増したこと。今は「−」で戻して 3 で回復する。"""
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
        cases = {KYOMEI: (True, False), PRESENT: (True, False),
                 "lifeshort_kinako_11th_671x348.png": (True, False),
                 "lifeshort_kinako_qty3_671x348.png": (False, True),
                 "lifeshort_kinako_qty7_671x348.png": (False, False),
                 "lifeshort_kinako_qty10_671x348.png": (False, False)}
        for name, (one, three) in cases.items():
            with self.subTest(frame=name):
                fr = load_rgb(name)
                _, pos = AL.match_best(load(name), AL.load_templates()["kinakorow"][0])
                rec = AL.kinako_recover_point(fr, pos)
                plus = AL.kinako_plus_point(fr, rec)
                self.assertIsNotNone(plus)
                self.assertEqual(one, AL.kinako_qty_is_one(fr, plus))
                self.assertEqual(three, AL.kinako_qty_is_three(fr, plus))
                self.assertEqual(name.endswith(("qty10_671x348.png",)), AL.kinako_over_cap(fr, rec))

    def test_minus_lies_on_the_kinako_stepper(self):
        fr = load_rgb(KYOMEI)
        _, pos = AL.match_best(load(KYOMEI), AL.load_templates()["kinakorow"][0])
        rec = AL.kinako_recover_point(fr, pos)
        x, y = AL.kinako_minus_point(fr, AL.kinako_plus_point(fr, rec))
        bx0, by0, bx1, by1 = TestKinakoPlusStepper.STEPPER_BOX
        self.assertTrue(bx0 <= x <= bx0 + 20 and by0 <= y <= by1, f"「−」({x:.0f},{y:.0f}) が箱の左端の外")


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
