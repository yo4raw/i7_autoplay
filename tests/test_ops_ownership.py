"""運用スクリプト間のプロセス所有権の回帰テスト（実機不要）。

背景（2026-08-01 / 2026-11-24 拡張）:
run_until.sh が最上位に入ったことで、下位のガードや外部コパイロットと所有権が競合していた。

- pause_guard.sh は PAUSE 嵐を検知して supervisor を kill するが、run_until が
  それを検知して**再起動し、停止指示を打ち消していた**
- freeze_sentinel.sh や tools/copilot が自分で supervise_autolive.sh を直接起動すると、
  run_until のものと**二重起動**になる（実際に autolive が2プロセス同時に走る事故が発生）

方針: **プロセスの生殺与奪は run_until.sh に一本化する**。
- pause_guard は最上位（run_until）から順に止める
- freeze_sentinel は autolive だけ落とし、supervisor に任せる
- tools/copilot の restart_supervisor も supervise_autolive.sh を直接叩かず run_until.sh を起動する
"""
import ast
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPS = os.path.join(ROOT, "tools", "ops")
COPILOT_SRC = os.path.join(ROOT, "tools", "copilot", "src", "supervisor.mjs")


def read(name):
    with open(os.path.join(OPS, name), encoding="utf-8") as fh:
        return fh.read()


def kill_targets(src):
    """pkill している対象の一覧（コメント行は除く）。"""
    out = []
    for ln in src.split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        for m in re.finditer(r'pkill\s+-f\s+"?([^"\s;]+)"?', ln):
            out.append(m.group(1))
    return out


class TestFreezeSentinel(unittest.TestCase):
    SRC = None

    def setUp(self):
        self.SRC = read("freeze_sentinel.sh")

    def test_does_not_kill_supervisor_or_runner(self):
        """supervisor / run_until を殺さないこと（殺すと二重起動になる）。"""
        targets = kill_targets(self.SRC)
        self.assertNotIn("supervise_autolive.sh", targets,
                         "supervisor を殺すと run_until が起動し直し二重になる")
        self.assertNotIn("run_until.sh", targets)

    def test_kills_only_autolive(self):
        self.assertIn("autolive.py", kill_targets(self.SRC))

    def test_does_not_launch_supervisor_itself(self):
        """自分で supervisor を起動しないこと（run_until のものと二重になる）。"""
        launches = [ln for ln in self.SRC.split("\n")
                    if not ln.lstrip().startswith("#")
                    and "supervise_autolive.sh" in ln
                    and ("nohup" in ln or re.search(r"^\s*tools/ops/", ln))]
        self.assertEqual([], launches,
                         f"supervisor を自前で起動している: {launches}")


class TestPauseGuard(unittest.TestCase):
    def setUp(self):
        self.SRC = read("pause_guard.sh")

    def test_kills_runner_first(self):
        """最上位の run_until を先に止めること。

        supervisor を先に殺すと run_until が再起動して停止指示が打ち消される。
        """
        src = "\n".join(ln for ln in self.SRC.split("\n")
                        if not ln.lstrip().startswith("#"))
        i_runner = src.find("pkill -f run_until.sh")
        i_sup = src.find("pkill -f supervise_autolive.sh")
        self.assertNotEqual(-1, i_runner, "run_until を止めていない")
        self.assertNotEqual(-1, i_sup)
        self.assertLess(i_runner, i_sup, "run_until より先に supervisor を殺している")

    def test_kills_whole_stack(self):
        targets = kill_targets(self.SRC)
        for t in ("run_until.sh", "supervise_autolive.sh", "autolive.py"):
            self.assertIn(t, targets, f"{t} を止めていない")


class TestOnlyRunnerLaunchesSupervisor(unittest.TestCase):
    def test_single_launch_site(self):
        """supervisor を起動するのは run_until.sh だけであること。"""
        launchers = []
        for name in sorted(os.listdir(OPS)):
            if not name.endswith(".sh") or name == "supervise_autolive.sh":
                continue
            for ln in read(name).split("\n"):
                if ln.lstrip().startswith("#"):
                    continue
                if re.search(r"(nohup\s+)?\S*supervise_autolive\.sh\s+\"?\$", ln):
                    launchers.append(name)
                    break
        self.assertEqual(["run_until.sh"], sorted(set(launchers)),
                         f"supervisor を起動しているスクリプト: {sorted(set(launchers))}")

    def test_copilot_launches_runner_not_supervisor(self):
        """tools/copilot も supervise_autolive.sh を直接叩かず run_until.sh 経由で起動すること。"""
        with open(COPILOT_SRC, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotRegex(
            src,
            r"nohup\s+tools/ops/supervise_autolive\.sh",
            "copilot が supervise_autolive.sh を直接起動している（run_until.sh と二重起動する）",
        )
        self.assertIn("tools/ops/run_until.sh", src)
        self.assertIn("--keep-selection", src)
        self.assertIn(".venv/bin/python", src)


class TestScriptsParse(unittest.TestCase):
    def test_all_ops_scripts_parse(self):
        for name in sorted(os.listdir(OPS)):
            if not name.endswith(".sh"):
                continue
            with self.subTest(script=name):
                r = subprocess.run(["zsh", "-n", os.path.join(OPS, name)],
                                   capture_output=True, text=True)
                self.assertEqual(0, r.returncode, r.stderr)


class TestNoBlindTapping(unittest.TestCase):
    """復旧ツールが既知画面以外を盲目タップしないこと。

    2026-08-02 実機事故: recover_freeze.py はドキュストリングに「既知画面以外では
    絶対にクリックしない」と書かれていたが、実装にはテンプレ不一致が続くと中央を
    タップするフォールバックがあった。アプリの強制終了に失敗した状態でこれが発火し、
    盲目タップを繰り返した結果**ゲームではない別アプリの画面まで操作してしまった**。

    ドキュメントの記述を信用せず、実装が盲目タップしないことを AST で固定する。
    """

    def test_blind_center_tap_is_disabled(self):
        src = read("recover_freeze.py")
        m = re.search(r"^BLIND_CENTER_TAP\s*=\s*(\w+)", src, re.M)
        self.assertIsNotNone(m, "BLIND_CENTER_TAP のフラグが無い")
        self.assertEqual("False", m.group(1),
                         "盲目タップが有効。ゲーム外の画面を操作しうる")

    def test_center_tap_is_gated_by_the_flag(self):
        """不一致フォールバック側の click_frac 呼び出しが BLIND_CENTER_TAP 条件の内側にあること。"""
        src = read("recover_freeze.py")
        tree = ast.parse(src)
        gated_calls = 0
        ungated_fallback_calls = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_dump = ast.dump(node.test)
                if "not acted" in ast.unparse(node.test):
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.If) and "BLIND_CENTER_TAP" in ast.dump(sub.test):
                            for call in ast.walk(sub):
                                if isinstance(call, ast.Call) and "click_frac" in ast.unparse(call.func):
                                    gated_calls += 1
                        elif sub is not node and isinstance(sub, ast.Call) and "click_frac" in ast.unparse(sub.func):
                            # BLIND_CENTER_TAP を持たない直下の click_frac がないか検査
                            if "BLIND_CENTER_TAP" not in test_dump:
                                ungated_fallback_calls += 1
        self.assertGreaterEqual(gated_calls, 1, "不一致分岐の click_frac が見つからない")
        # gated_calls 自身が walk(node) にも現れるため、総 click_frac 数と一致することを確認
        not_acted_ifs = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.If) and "not acted" in ast.unparse(n.test)
        ]
        total_calls = sum(
            1 for n in not_acted_ifs for c in ast.walk(n)
            if isinstance(c, ast.Call) and "click_frac" in ast.unparse(c.func)
        )
        self.assertEqual(gated_calls, total_calls, "BLIND_CENTER_TAP で保護されていない click_frac がある")


if __name__ == "__main__":
    unittest.main()
