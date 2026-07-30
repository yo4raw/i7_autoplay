"""ドキュメントの相対リンクが切れていないことを検証する（実機不要）。"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:")


def _strip_code_fences(text):
    """コードフェンス（```/~~~）で囲まれた領域を取り除いたテキストを返す。

    設計書や計画書（docs/superpowers/ 配下など）には、コードフェンス内に
    「他のファイルに貼り付ける想定」のリンク例が書かれていることがあり、
    そのファイル自身の場所からは相対解決できない（＝誤検出になる）。
    フェンス内を丸ごと除去してからリンク抽出することで、ディレクトリ単位の
    除外リストに頼らずに済む。フェンスが閉じられないまま終端した場合は、
    ファイル末尾までをフェンス内とみなす。
    """
    out = []
    fence_marker = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if fence_marker is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence_marker = stripped[:3]
                continue
            out.append(line)
        else:
            if stripped.startswith(fence_marker):
                fence_marker = None
            continue
    return "".join(out)


def _tracked_markdown():
    r = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                       capture_output=True, text=True, check=True)
    return [p for p in r.stdout.splitlines() if p]


class TestDocsLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for rel in _tracked_markdown():
            path = os.path.join(ROOT, rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            text = _strip_code_fences(text)
            for target in LINK.findall(text):
                if target.startswith(SKIP_PREFIXES):
                    continue
                resolved = os.path.normpath(
                    os.path.join(os.path.dirname(path), target))
                if not os.path.exists(resolved):
                    broken.append(f"{rel}: {target}")
        self.assertEqual([], broken, "\n".join(broken))

    def test_specification_md_is_a_redirect_stub(self):
        """1,056行の specification.md は docs/ 配下の6ファイルへ分割した。

        完全削除はしない。tools/autolive.py が6箇所のコメントでこのパスを参照しており、
        本番3ファイルは段階1では1行も変更しないと決めているため。
        代わりに行き先を案内する短いスタブを残す。中身が戻ってきたら失敗する。
        """
        p = os.path.join(ROOT, "docs", "specification.md")
        self.assertTrue(os.path.exists(p))
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        self.assertLess(len(text.splitlines()), 25, "スタブに本文が戻っている")
        self.assertIn("README.md", text)


if __name__ == "__main__":
    unittest.main()
