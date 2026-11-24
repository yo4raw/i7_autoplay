"""tools/copilot（pi-durable 監視エージェント）の構成回帰テスト（実機・APIキー不要）。"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPILOT = os.path.join(ROOT, "tools", "copilot")


def _find_node():
    search_path = os.pathsep.join(
        filter(None, [os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])
    )
    return shutil.which("node", path=search_path)


class TestCopilotLayout(unittest.TestCase):
    def test_required_files_exist(self):
        for rel in [
            "package.json",
            "src/supervisor.mjs",
            "bin/watch.sh",
            "bin/once.sh",
            "README.md",
            "../../assets/prompts/pi_durable_copilot.md",
        ]:
            self.assertTrue(os.path.isfile(os.path.join(COPILOT, rel)), rel)

    def test_package_json(self):
        with open(os.path.join(COPILOT, "package.json"), encoding="utf-8") as f:
            pkg = json.load(f)
        self.assertEqual("module", pkg.get("type"))
        deps = pkg.get("dependencies", {})
        for name in ("@earendil-works/pi-durable", "@earendil-works/pi-ai"):
            self.assertIn(name, deps)

    def test_shell_wrappers_parse(self):
        for name in ("watch.sh", "once.sh"):
            p = os.path.join(COPILOT, "bin", name)
            r = subprocess.run(["zsh", "-n", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_supervisor_mjs_parses(self):
        node_bin = _find_node()
        if not node_bin:
            self.skipTest("node 未導入")
        if not os.path.isdir(os.path.join(COPILOT, "node_modules")):
            self.skipTest("node_modules 未導入（cd tools/copilot && npm install）")
        r = subprocess.run(
            [node_bin, "--check", os.path.join(COPILOT, "src", "supervisor.mjs")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_prompt_is_ported_decision_table(self):
        """pi_durable_copilot.md が supervisor_loop.md の判断表を引き継いでいること。"""
        with open(os.path.join(ROOT, "assets/prompts/pi_durable_copilot.md"), encoding="utf-8") as f:
            text = f.read()
        for marker in ("きなこパン", "ステラ", "check_status", "end_session", "open_mirroring", "restart_supervisor"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
