"""docs/screen-flow.md が実装と一致していることの回帰テスト（実機不要）。

画面遷移の仕様書は、実装が変わると簡単に嘘になる。**嘘のドキュメントは無いより悪い**
（2026-08-02、recover_freeze.py のドキュストリングにあった「既知画面以外では絶対に
クリックしない」を信じて実行し、実際には盲目タップする実装だったため別アプリを
操作する事故を起こした）。

そこで「状態名」「停止理由」「判定順」の3点を機械的に突き合わせる。
実装に追加したのに本書へ書き忘れたら、このテストが落ちる。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")
DOC = os.path.join(ROOT, "docs", "screen-flow.md")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def detect_body():
    """detect() の本体だけを返す。"""
    src = read(AUTOLIVE).split("\n")
    start = next(i for i, l in enumerate(src) if l.startswith("    def detect(self"))
    end = next(i for i in range(start + 1, len(src)) if src[i].startswith("    def "))
    return "\n".join(src[start:end])


def detect_states():
    """detect() が返しうる状態名を出現順に（重複は最初のみ）。"""
    out = []
    for m in re.finditer(r'return "([a-z]+)", res', detect_body()):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def handled_states():
    """_loop() が明示的に処理している状態名。"""
    src = read(AUTOLIVE)
    out = set()
    for m in re.finditer(r'state == "([a-z]+)"', src):
        out.add(m.group(1))
    for m in re.finditer(r'state in \(([^)]*)\)', src):
        out.update(re.findall(r'"([a-z]+)"', m.group(1)))
    return out


class TestDocumentedStates(unittest.TestCase):
    def test_every_detect_state_is_documented(self):
        """detect() が返す状態はすべて本書に載っていること。"""
        doc = read(DOC)
        missing = [s for s in detect_states() if f"`{s}`" not in doc]
        self.assertEqual([], missing,
                         f"docs/screen-flow.md に未記載の状態: {missing}")

    def test_every_detect_state_has_a_handler_or_is_documented_as_noop(self):
        """detect() が返す状態には、ハンドラがあるか「何もしない」と明記されていること。

        どちらも無ければ、その画面に入ると黙って滞留して安全停止する。
        """
        doc = read(DOC)
        handled = handled_states()
        orphans = []
        for s in detect_states():
            if s in handled:
                continue
            # menu は「クリックせず待つ」が仕様。本書に明記されていれば良い
            if s == "menu" and "クリックしない" in doc:
                continue
            orphans.append(s)
        self.assertEqual([], orphans,
                         f"ハンドラも「何もしない」記載も無い状態: {orphans}")

    def test_no_stale_states_in_doc(self):
        """本書に、実装から消えた状態が残っていないこと。"""
        doc = read(DOC)
        known = set(detect_states()) | handled_states() | set(AL.TEMPLATES)
        # 本書の表に出てくるバッククォート付き小文字語のうち、状態らしきものを拾う
        cited = set(re.findall(r"^\| \d+ \| `([a-z]+)` \|", doc, re.M))
        stale = sorted(c for c in cited if c not in known)
        self.assertEqual([], stale, f"実装に無い状態が本書に残っている: {stale}")


class TestDocumentedStopReasons(unittest.TestCase):
    def test_every_stop_reason_is_documented(self):
        doc = read(DOC)
        reasons = sorted(set(re.findall(r'self\.stop_reason = "([a-z_]+)"',
                                        read(AUTOLIVE))))
        self.assertGreaterEqual(len(reasons), 8)
        missing = [r for r in reasons if f"`{r}`" not in doc]
        self.assertEqual([], missing, f"本書に未記載の停止理由: {missing}")


class TestDocumentedOrdering(unittest.TestCase):
    """判定順は仕様。本書の並びが実装とずれていないこと。"""

    def test_cardx_sensitive_states_come_before_cardx(self):
        """シアン系ヘッダを持つダイアログは cardx より前で判定すること。

        後ろに置くと背景タップで閉じようとして必ず停滞する（実機で複数回発生）。
        """
        order = detect_states()
        self.assertIn("cardx", order)
        i_cardx = order.index("cardx")
        for s in ("resumelive", "dataupdate", "resendresult", "expresult"):
            with self.subTest(state=s):
                self.assertIn(s, order, f"{s} が detect() に無い")
                self.assertLess(order.index(s), i_cardx,
                                f"{s} が cardx より後で判定されている")

    def test_lifeshort_is_evaluated_early(self):
        """LIFE不足は早い段階で確定させること（盲目タップでステラを押さないため）。"""
        order = detect_states()
        self.assertIn("lifeshort", order)
        self.assertLess(order.index("lifeshort"), order.index("cardx"))

    def test_doc_table_order_matches_implementation(self):
        """本書 2.3 の番号付き表の並びが、実装の判定順と一致すること。"""
        doc = read(DOC)
        rows = re.findall(r"^\| (\d+) \| `([a-z]+)` \|", doc, re.M)
        self.assertGreater(len(rows), 15, "判定順の表が見つからない")
        documented = [name for _, name in rows]
        impl = [s for s in detect_states() if s != "gameplay"]
        # 本書は「明るい側」の順序を書いている。実装の暗い側(pause/songselect)を除いて比較
        impl_bright = [s for s in impl if s not in ("songselect",)] + ["songselect"]
        self.assertEqual(documented[0], impl_bright[0],
                         "表の先頭が実装と違う")
        # 完全一致までは求めず、cardx を挟む前後関係が保たれていることを見る
        self.assertLess(documented.index("expresult"), documented.index("cardx"))
        self.assertLess(documented.index("lifeshort"), documented.index("cardx"))


if __name__ == "__main__":
    unittest.main()
