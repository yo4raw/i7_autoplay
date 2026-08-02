"""ウィンドウ矩形の再取得の回帰テスト（実機不要）。

背景（docs/improvements.md M-2、2026-08-01 に実害を確認）:
ウィンドウ矩形を起動時に1回しか取らないと、ミラーリングウィンドウが移動・リサイズ
された後も古い矩形でキャプチャし続ける。実測ではミラーリングアプリが再起動して
ウィンドウが 671x348 → 318x701 に変わり、**画面の一部＋デスクトップ壁紙**という
不整合なフレームを掴んで「未知画面」で安全停止 → 再起動 → また停止、を繰り返した。

寸法が変わったら content 矩形・ROI スケール・円キャリブレーションも作り直す必要がある
（いずれもウィンドウ寸法に依存するため、古い値のままだと座標が全部ずれる）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import autolive as AL  # noqa: E402

LAND = {"x": 0.0, "y": 39.0, "w": 671.0, "h": 348.0}   # ゲーム（常に横向き）
PORT = {"x": 0.0, "y": 39.0, "w": 318.0, "h": 701.0}   # 切断ダイアログ（縦長）
LAND2 = {"x": 0.0, "y": 39.0, "w": 529.0, "h": 334.0}  # 別機種（横向き）


def make_al(win):
    al = AL.AutoLive.__new__(AL.AutoLive)
    al.win = dict(win)
    al.content = (38, int(win["h"]) - 9)
    al._last_win_check = 0.0
    al._roi_scale_key = ("stale",)
    al._roi_scales = [1.0, 1.0, 1.0, 1.0]
    al.circles_calibrated = True
    al.autocal_samples = [(0.1, 0.1)]
    al.t_start = 0.0
    al.loops_done = 0
    al.max_loops = 1
    return al


class TestRefreshWindow(unittest.TestCase):
    def test_picks_up_new_geometry(self):
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window", return_value=dict(PORT)):
            al._refresh_window(interval=0.0)
        self.assertEqual(318, int(al.win["w"]))
        self.assertEqual(701, int(al.win["h"]))

    def test_landscape_resize_rebuilds_derived_state(self):
        """**横向きのまま**寸法が変わったら派生状態を作り直すこと（機種/レイアウト変更）。

        作り直さないと、古い寸法基準の座標で打鍵し続ける。
        """
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window", return_value=dict(LAND2)):
            al._refresh_window(interval=0.0)
        self.assertEqual((38, 334 - 9), al.content, "content 矩形が更新されていない")
        self.assertIsNone(al._roi_scale_key, "ROIスケールのキャッシュが残っている")
        self.assertFalse(al.circles_calibrated, "円キャリブレーションが再実行されない")
        self.assertEqual([], al.autocal_samples, "古い検出サンプルが残っている")

    def test_portrait_means_disconnected_and_keeps_calibration(self):
        """縦長になったら**切断**とみなし、円キャリブレーションを捨てないこと。

        ゲームは常に横向きなので、縦長＝切断ダイアログ。ここで補正を捨てると
        切断中ずっと「検出0円」を再試行し続けてログを埋め尽くす
        （実測 2026-08-02: 1万行超）。復帰後も無補正で打鍵してしまう。
        """
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window", return_value=dict(PORT)):
            al._refresh_window(interval=0.0)
        self.assertEqual((38, 701 - 9), al.content, "content は寸法に追従すべき")
        self.assertTrue(al.circles_calibrated, "切断で円キャリブレーションを捨てている")
        self.assertEqual(("stale",), al._roi_scale_key, "切断で ROIスケールを捨てている")

    def test_same_geometry_keeps_calibration(self):
        """寸法が同じなら円キャリブレーションを捨てないこと（毎回捨てると打鍵が乱れる）。"""
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window", return_value=dict(LAND)):
            al._refresh_window(interval=0.0)
        self.assertTrue(al.circles_calibrated)
        self.assertEqual(("stale",), al._roi_scale_key)

    def test_throttled_by_interval(self):
        """毎フレーム呼んでも実際の取得は間引かれること（打鍵ループを遅くしない）。"""
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window",
                               return_value=dict(PORT)) as fw:
            al._refresh_window(interval=0.0)   # 1回目は取得
            al._refresh_window(interval=999)   # 2回目は間引き
            self.assertEqual(1, fw.call_count)

    def test_find_window_failure_is_survivable(self):
        """切断中などで取得に失敗しても落ちず、既存の矩形を保つこと。"""
        al = make_al(LAND)
        with mock.patch.object(AL.driver, "find_window",
                               side_effect=RuntimeError("見つかりません")):
            al._refresh_window(interval=0.0)   # 例外が漏れないこと
        self.assertEqual(671, int(al.win["w"]))

    def test_called_from_main_loop(self):
        """メインループから呼ばれていること（定義しただけでは意味がない）。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "autolive.py"),
            encoding="utf-8").read()
        self.assertIn("self._refresh_window()", src)


if __name__ == "__main__":
    unittest.main()
