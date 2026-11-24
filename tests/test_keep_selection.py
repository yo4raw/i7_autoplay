"""`--keep-selection`（現行運用の既定。2026-10-20 ユーザー指定）の回帰テスト（実機不要）。

CLAUDE.md 絶対規則 2「難易度は人が選んだものをそのまま継続する」を既定値で守る:
- `AutoLive` および CLI の既定は `keep_selection=True`（曲も難易度も一切タップしない）。
- 旧運用（Don't Analyze Me + EASY 固定）は `--no-keep-selection` 指定時のみ有効。
- 互換性のため `--keep-selection` フラグ自体も引き続き受け付ける。
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
        ln = lines[i]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            return lines[start:i]
    raise AssertionError("songselect ブロックの終端が見つからない")


def branch_split():
    """(keep_selection 側の行, 旧運用側の行) に割る。"""
    block = songselect_block()
    i_if = next(i for i, l in enumerate(block)
                if l.strip() == "if self.keep_selection:")
    indent = len(block[i_if]) - len(block[i_if].lstrip())
    i_else = next(i for i in range(i_if + 1, len(block))
                  if block[i].strip() == "else:"
                  and (len(block[i]) - len(block[i].lstrip())) == indent)
    return block[i_if + 1:i_else], block[i_else + 1:]


class TestWiring(unittest.TestCase):
    def test_flag_defaults_to_on(self):
        """既定は人が選んだ曲・難易度を維持する（CLAUDE.md 絶対規則 2）。"""
        sig = inspect.signature(AL.AutoLive.__init__)
        self.assertIn("keep_selection", sig.parameters)
        self.assertIs(True, sig.parameters["keep_selection"].default,
                      "既定が True でないと人が選んだ難易度を EASY に戻してしまう")

    def test_cli_flags_exist_and_are_wired(self):
        src = read(AUTOLIVE)
        self.assertIn('"--keep-selection"', src, "CLI フラグ --keep-selection が無い")
        self.assertIn('"--no-keep-selection"', src, "CLI フラグ --no-keep-selection が無い")
        self.assertIn("keep_selection=args.keep_selection", src,
                      "CLI フラグが AutoLive に配線されていない")

    def test_attribute_is_assigned(self):
        self.assertIn("self.keep_selection = keep_selection", read(AUTOLIVE))


class TestBranchBehaviour(unittest.TestCase):
    def test_keep_selection_branch_taps_nothing(self):
        """keep_selection 側の枝では、曲も難易度も**一切クリックしない**。"""
        keep, _ = branch_split()
        offenders = [ln.strip() for ln in keep if "click" in ln]
        self.assertEqual([], offenders,
                         f"--keep-selection なのにクリックしている: {offenders}")

    def test_easy_tab_only_in_legacy_branch(self):
        """EASY 固定タップは旧運用側（--no-keep-selection）の枝にしか無いこと。"""
        keep, legacy = branch_split()
        self.assertFalse(any("P_EASY_TAB" in ln for ln in keep),
                         "--keep-selection で難易度を上書きしている")
        self.assertTrue(any("P_EASY_TAB" in ln for ln in legacy),
                        "旧運用枝から EASY 固定が消えた")

    def test_song_template_only_in_legacy_branch(self):
        """曲の自動選択も旧運用側の枝にしか無いこと。"""
        keep, legacy = branch_split()
        self.assertFalse(any("songdaz" in ln for ln in keep),
                         "--keep-selection で曲を選び直している")
        self.assertTrue(any("songdaz" in ln for ln in legacy),
                        "旧運用枝から対象曲の自動選択が消えた")

    def test_next_is_pressed_in_both_branches(self):
        """どちらの枝でも最後に NEXT は押す（押さないと周回が進まない）。"""
        block = songselect_block()
        tail = [ln for ln in block
                if 'click_match(res["songselect"]' in ln
                and (len(ln) - len(ln.lstrip())) == 16]
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
