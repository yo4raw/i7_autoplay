"""ドキュメントの相対リンクが切れていないことを検証する（実機不要）。"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:")
# docs/superpowers/（設計書・計画書）と docs/archive/ は当時の記録。
# 計画書はコードフェンス内に「他ファイルに貼る想定」のリンク例を含むため、
# その場所からの相対解決は本来成立しない。tests/test_repo_layout.py の
# TestNoStaleToolPaths と同じ理由・同じ除外対象。
EXCLUDE_PREFIXES = ("docs/superpowers/", "docs/archive/")


def _tracked_markdown():
    r = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                       capture_output=True, text=True, check=True)
    return [p for p in r.stdout.splitlines()
            if p and not p.startswith(EXCLUDE_PREFIXES)]


class TestDocsLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for rel in _tracked_markdown():
            path = os.path.join(ROOT, rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
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
