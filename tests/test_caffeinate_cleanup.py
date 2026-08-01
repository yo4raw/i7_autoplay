"""caffeinate が SIGTERM で確実に回収されることの回帰テスト（実機不要）。

背景（2026-08-01）:
autolive は周回中 `caffeinate -dimsu` を起動してスリープを抑止するが、終了処理は
`finally` にしか無かった。supervisor は autolive を `pkill -f tools/autolive.py`
（SIGTERM）で入れ替えるため、既定のハンドラは `finally` を通さずプロセスを終了させる。
結果 **caffeinate が孤児として残り続け、一晩の周回で5個溜まっていた**（周回を止めた後も
Mac がスリープしない状態になる）。

対策: SIGTERM / SIGINT にハンドラを入れて caffeinate を落としてから終了する。
"""
import ast
import os
import signal
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")

# autolive の run() が行う「子プロセス起動＋シグナルハンドラ」を最小再現したもの。
# 本体を実機なしで起動できないため、同じ構造をここで検証する。
CHILD = '''
import subprocess, signal, sys, time
caf = subprocess.Popen(["caffeinate", "-dimsu"])


def _cleanup(signum=None, _frame=None):
    if caf.poll() is None:
        caf.terminate()
    if signum is not None:
        sys.exit(0)


for s in (signal.SIGTERM, signal.SIGINT):
    signal.signal(s, _cleanup)
print("ready %d" % caf.pid, flush=True)
try:
    time.sleep(30)
finally:
    _cleanup()
'''


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TestSigtermReleasesCaffeinate(unittest.TestCase):
    def test_child_is_terminated_on_sigterm(self):
        p = subprocess.Popen([sys.executable, "-u", "-c", CHILD],
                             stdout=subprocess.PIPE, text=True)
        try:
            caf_pid = int(p.stdout.readline().split()[1])
            self.assertTrue(_alive(caf_pid), "caffeinate が起動していない")
            p.terminate()
            p.wait(timeout=10)
            for _ in range(20):            # 終了の反映を待つ
                if not _alive(caf_pid):
                    break
                time.sleep(0.1)
            self.assertFalse(_alive(caf_pid),
                             "SIGTERM 後も caffeinate が残っている（孤児化）")
        finally:
            if p.poll() is None:
                p.kill()


class TestAutoliveInstallsHandler(unittest.TestCase):
    """本体に配線が残っていること（最小再現が通っても本体が外れていたら無意味）。"""

    def setUp(self):
        with open(AUTOLIVE, encoding="utf-8") as fh:
            self.src = fh.read()

    def test_signal_module_imported(self):
        self.assertIn("import signal", self.src)

    def test_handler_registered_for_sigterm(self):
        self.assertIn("signal.SIGTERM", self.src)
        self.assertIn("signal.signal(", self.src)

    def test_cleanup_terminates_caffeinate(self):
        tree = ast.parse(self.src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_cleanup":
                body = ast.dump(node)
                if "terminate" in body:
                    found = True
        self.assertTrue(found, "_cleanup が caffeinate を terminate していない")


if __name__ == "__main__":
    unittest.main()
