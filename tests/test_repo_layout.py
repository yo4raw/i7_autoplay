"""リポジトリ構成の回帰テスト（実機不要）。

tools/ の3分類、移動したスクリプトの構文、移動後の相対パス解決、
旧パス参照の残存を機械的に検証する。ミラーリング接続は不要。
"""
import importlib
import os
import py_compile
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

PROD = ["autolive.py", "driver.py", "note_engine.py"]
OPS = ["supervise_autolive.sh", "freeze_sentinel.sh", "morning_watcher.sh",
       "pause_guard.sh", "reconnect_watcher.py", "recover_freeze.py",
       "unlock_watcher.py", "corpus_collector.py"]
PROBES = ["trigger_test.py", "idlekeeper.py", "capture_click.py", "color_probe.py",
          "color_probe2.py", "focus_probe.py", "focus_state_monitor.py",
          "hidmove_test.py", "pause_ab.sh", "pause_monitor.py",
          "pure_observe.py", "result_grab.py"]

# 移動後にアセットを参照するモジュールと、その参照先を持つ属性名
OPS_ASSET_ATTRS = {
    "reconnect_watcher": ["RETRY_TMPL"],
    "unlock_watcher": ["TMPL"],
    "recover_freeze": ["SCREENS", "TEMPLATES"],
}


def _scripts_in(d):
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith((".py", ".sh")))


class TestToolsLayout(unittest.TestCase):
    def test_ops_scripts_are_under_ops(self):
        self.assertEqual(sorted(OPS), _scripts_in(os.path.join(TOOLS, "ops")))


class TestScriptsAreValid(unittest.TestCase):
    def _all_scripts(self):
        for d in (TOOLS, os.path.join(TOOLS, "ops"), os.path.join(TOOLS, "probes")):
            for f in _scripts_in(d):
                yield os.path.join(d, f)

    def test_python_scripts_compile(self):
        for p in self._all_scripts():
            if p.endswith(".py"):
                with self.subTest(script=p):
                    py_compile.compile(p, doraise=True)

    def test_shell_scripts_parse(self):
        for p in self._all_scripts():
            if p.endswith(".sh"):
                with self.subTest(script=p):
                    r = subprocess.run(["zsh", "-n", p], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)


class TestOpsPathResolution(unittest.TestCase):
    """移動で ROOT が1階層ずれていないことを、実際に import して確かめる。"""

    def test_asset_paths_resolve(self):
        opsdir = os.path.join(TOOLS, "ops")
        sys.path.insert(0, opsdir)
        try:
            for name, attrs in OPS_ASSET_ATTRS.items():
                mod = importlib.import_module(name)
                for attr in attrs:
                    p = getattr(mod, attr)
                    with self.subTest(module=name, attr=attr):
                        self.assertTrue(os.path.exists(p), f"{name}.{attr} = {p}")
        finally:
            sys.path.remove(opsdir)


if __name__ == "__main__":
    unittest.main()
