"""`--keep-selection`（累計イベント以外の例外運用）の回帰テスト（実機不要）。

このフラグの要点は **「立てたら楽曲選択で何も選び直さない」** の一点に尽きる。
既定（累計イベント）は従来どおり Don't Analyze Me + EASY を固定する。

ここが壊れると静かに事故る:

- フラグを立てたのに EASY 固定タップが残っていると、人が EXPERT 等に合わせた難易度を
  **黙って EASY へ戻す**。ログには何も出ないので気づけない。
- 逆に既定側から EASY 固定が消えると、累計イベントでノーマル等を回してしまう
  （CLAUDE.md 絶対規則 2）。

`_loop()` は実機前提で単体実行できないため、`test_screen_flow_doc.py` と同じく
ソースの分岐構造を機械的に突き合わせる。
"""
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def songselect_block():
    """_loop() の `elif state == "songselect":` ブロックを行リストで返す。"""
    lines = read(AUTOLIVE).split("\n")
    start = next(i for i, l in enumerate(lines)
                 if l.strip() == 'elif state == "songselect":')
    indent = len(lines[start]) - len(lines[start].lstrip())
    for i in range(start + 1, len(lines)):
        l = lines[i]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent:
            return lines[start:i]
    raise AssertionError("songselect ブロックの終端が見つからない")


def branch_split():
    """(keep_selection 側の行, 既定側の行) に割る。"""
    block = songselect_block()
    i_if = next(i for i, l in enumerate(block)
                if l.strip() == "if self.keep_selection:")
    indent = len(block[i_if]) - len(block[i_if].lstrip())
    i_else = next(i for i in range(i_if + 1, len(block))
                  if block[i].strip() == "else:"
                  and (len(block[i]) - len(block[i].lstrip())) == indent)
    return block[i_if + 1:i_else], block[i_else + 1:]


class TestWiring(unittest.TestCase):
    def test_flag_defaults_to_off(self):
        """既定は累計イベントの従来挙動（Don't Analyze Me + EASY）。"""
        sig = inspect.signature(AL.AutoLive.__init__)
        self.assertIn("keep_selection", sig.parameters)
        self.assertIs(False, sig.parameters["keep_selection"].default,
                      "既定で選択をスキップすると累計イベントで難易度が固定されない")

    def test_cli_flag_exists_and_is_wired(self):
        src = read(AUTOLIVE)
        self.assertIn('"--keep-selection"', src, "CLI フラグが無い")
        self.assertIn("keep_selection=args.keep_selection", src,
                      "CLI フラグが AutoLive に配線されていない")

    def test_attribute_is_assigned(self):
        self.assertIn("self.keep_selection = keep_selection", read(AUTOLIVE))


class TestBranchBehaviour(unittest.TestCase):
    def test_keep_selection_branch_taps_nothing(self):
        """フラグ側の枝では、曲も難易度も**一切クリックしない**。"""
        keep, _ = branch_split()
        offenders = [l.strip() for l in keep if "click" in l]
        self.assertEqual([], offenders,
                         f"--keep-selection なのにクリックしている: {offenders}")

    def test_easy_tab_only_in_default_branch(self):
        """EASY 固定タップは既定側の枝にしか無いこと。"""
        keep, default = branch_split()
        self.assertFalse(any("P_EASY_TAB" in l for l in keep),
                         "--keep-selection で難易度を上書きしている")
        self.assertTrue(any("P_EASY_TAB" in l for l in default),
                        "既定から EASY 固定が消えた（絶対規則 2 違反）")

    def test_song_template_only_in_default_branch(self):
        """曲の自動選択も既定側の枝にしか無いこと。"""
        keep, default = branch_split()
        self.assertFalse(any("songdaz" in l for l in keep),
                         "--keep-selection で曲を選び直している")
        self.assertTrue(any("songdaz" in l for l in default),
                        "既定から対象曲の自動選択が消えた")

    def test_next_is_pressed_in_both_branches(self):
        """どちらの枝でも最後に NEXT は押す（押さないと周回が進まない）。"""
        block = songselect_block()
        tail = [l for l in block
                if 'click_match(res["songselect"]' in l
                and (len(l) - len(l.lstrip())) == 16]
        self.assertEqual(1, len(tail),
                         "NEXT が枝の外に1つある形になっていない")


class TestDocumented(unittest.TestCase):
    def test_flag_is_documented(self):
        """挙動を変えるフラグは screen-flow.md に載っていること。"""
        doc = read(os.path.join(ROOT, "docs", "screen-flow.md"))
        self.assertIn("--keep-selection", doc,
                      "docs/screen-flow.md に未記載（嘘のドキュメントは無いより悪い）")


if __name__ == "__main__":
    unittest.main()
