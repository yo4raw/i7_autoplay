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

    def test_ignores_non_notes_and_invalid_lanes(self):
        fc = NE.TypeForecast()
        fc.update([{"id": 9, "is_note": False, "lane": 0, "eta": 0.1,
                    "type": "white", "speed": 0.0, "pos": (0, 0), "pts": []},
                   ann(2, -1, "white", 0.1), ann(3, 4, "white", 0.1)], now=0.0)
        for lane in range(4):
            self.assertIsNone(fc.peek(lane, 0.0))


if __name__ == "__main__":
    unittest.main()
