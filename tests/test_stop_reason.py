"""安全停止が終了コードに現れることの回帰テスト（実機不要）。

背景:
安全停止はすべて `_loop()` 内の `break` で、`run()` が正常復帰して終了コード 0 だった。
supervisor は rc を条件に使わず8秒後に無条件再起動するため、**同じ画面で止まっては
再起動する空転**を延々と繰り返していた（実測 2026-08-01: 26〜36秒周期で12連続、
ログ全体で「完了: 0 回クリア」71件）。

対策: 安全停止は `stop_reason` を立て、`main()` が `EXIT_SAFE_STOP`(42) で抜ける。
supervisor は rc=42 なら再起動しない。本テストはその配線が外れないことを固定する。
"""
import ast
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import autolive as AL  # noqa: E402

AUTOLIVE = os.path.join(ROOT, "tools", "autolive.py")
SUPERVISOR = os.path.join(ROOT, "tools", "ops", "supervise_autolive.sh")


class TestExitCodes(unittest.TestCase):
    def test_safe_stop_code_is_distinct(self):
        self.assertEqual(0, AL.EXIT_OK)
        self.assertNotEqual(AL.EXIT_OK, AL.EXIT_SAFE_STOP)
        # シェルで扱うので 1..255 の範囲に収まっていること
        self.assertTrue(1 <= AL.EXIT_SAFE_STOP <= 255)

    def test_main_exits_with_safe_stop_code(self):
        """main() が stop_reason を終了コードへ変換していること。"""
        src = open(AUTOLIVE, encoding="utf-8").read()
        self.assertIn("sys.exit(EXIT_SAFE_STOP if reason else EXIT_OK)", src)


class TestEverySafetyStopSetsReason(unittest.TestCase):
    """`[warn] ... 停止` を出して break する箇所が、必ず stop_reason を立てること。

    1箇所でも漏れると、その停止だけ rc=0 になり supervisor が空転を再開する。
    """

    def test_all_warn_breaks_have_reason(self):
        lines = open(AUTOLIVE, encoding="utf-8").read().split("\n")
        missing = []
        for i, ln in enumerate(lines):
            if ln.strip() != "break":
                continue
            # break の直前 8 行を見て、[warn]...停止 のログがあるか
            window = "\n".join(lines[max(0, i - 8):i])
            if "[warn]" not in window or "停止" not in window:
                continue
            if 'self.stop_reason = ' not in window:
                missing.append(i + 1)
        self.assertEqual([], missing,
                         f"stop_reason を立てずに安全停止している行: {missing}")

    def test_reasons_are_unique_and_descriptive(self):
        src = open(AUTOLIVE, encoding="utf-8").read()
        reasons = re.findall(r'self\.stop_reason = "([a-z_]+)"', src)
        self.assertGreaterEqual(len(reasons), 8, "安全停止の理由が想定より少ない")
        self.assertEqual(len(reasons), len(set(reasons)),
                         f"停止理由が重複している（原因の切り分けができない）: {reasons}")


class TestSupervisorRespectsSafeStop(unittest.TestCase):
    def test_supervisor_breaks_on_safe_stop_code(self):
        src = open(SUPERVISOR, encoding="utf-8").read()
        self.assertIn("rc == 42", src, "supervisor が安全停止コードを見ていない")
        # rc==42 の分岐内で break していること
        # ※ `fi` は行として現れるものだけを終端とみなす（`_fired` などに誤マッチさせない）
        m = re.search(r"if \(\( rc == 42 \)\); then\n(.*?)\n\s*fi\s*$",
                      src, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertIn("break", m.group(1),
                      "rc=42 でも supervisor が再起動を続けてしまう")

    def test_supervisor_has_barren_circuit_breaker(self):
        """クリアが増えないまま終了が続いたら諦めること（空転の安全網）。"""
        src = open(SUPERVISOR, encoding="utf-8").read()
        self.assertIn("barren", src)
        self.assertRegex(src, r"barren >= \d+", "空転の打ち切り条件が無い")

    def test_supervisor_script_parses(self):
        r = subprocess.run(["zsh", "-n", SUPERVISOR], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)


class TestStopReasonInitialised(unittest.TestCase):
    def test_attribute_initialised_to_none(self):
        """__init__ で None に初期化されていること（未設定だと AttributeError で落ちる）。"""
        src = open(AUTOLIVE, encoding="utf-8").read()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Attribute) and t.attr == "stop_reason"
                            and isinstance(node.value, ast.Constant)
                            and node.value.value is None):
                        found = True
        self.assertTrue(found, "self.stop_reason = None の初期化が無い")


class TestRunUntilBranches(unittest.TestCase):
    """run_until.sh の分岐を実際に走らせて検証する（シェルは型検査できないため）。

    本番のログ・フラグを壊さないよう、テスト側は I7_RUNNER_LOG / I7_SAFE_FLAG /
    I7_BARREN_FLAG でテンポラリへ隔離する（実際に一度、本番ログを上書きした）。
    """

    def test_shell_integration(self):
        script = os.path.join(ROOT, "tests", "test_run_until.sh")
        r = subprocess.run(["zsh", script], capture_output=True, text=True,
                           cwd=ROOT, timeout=180)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertNotIn("NG", r.stdout, r.stdout)


class TestLiveAbandonedGuard(unittest.TestCase):
    """クリアを挟まずに START が続いたら、**押す前に** live_abandoned で停止すること。

    2026-09-10 実機: 再接続病のセッションで START → PAUSE → 打鍵が「諦める」を踏む →
    楽曲選択 → START が 35 秒周期で 4 回続き、クリア 0・警告 0 で LIFE だけ減った。
    autolive にも supervisor にも止める仕組みが無く、監視シェルで代用していた。
    """

    def formation_block(self):
        lines = open(AUTOLIVE, encoding="utf-8").read().split("\n")
        start = next(i for i, l in enumerate(lines)
                     if l.strip() == 'elif state == "formation":')
        indent = len(lines[start]) - len(lines[start].lstrip())
        for i in range(start + 1, len(lines)):
            l = lines[i]
            if l.strip() and (len(l) - len(l.lstrip())) <= indent:
                return lines[start:i]
        raise AssertionError("formation ブロックの終端が見つからない")

    def test_stops_before_pressing_start(self):
        block = self.formation_block()
        i_reason = next(i for i, l in enumerate(block) if 'self.stop_reason = "live_abandoned"' in l)
        i_click = next(i for i, l in enumerate(block) if "click_match" in l)
        self.assertLess(i_reason, i_click, "停止判定が START 押下より後にある")
        self.assertTrue(any("break" == l.strip() for l in block[i_reason:i_click]),
                        "停止判定の後で break していない")

    def test_counter_resets_on_every_clear(self):
        """クリア計上（was_in_live を下ろす箇所）すべてでカウンタを戻すこと。"""
        src = open(AUTOLIVE, encoding="utf-8").read()
        n_clear = src.count("                    self.was_in_live = False")
        n_reset = src.count("                    self.starts_since_clear = 0")
        self.assertGreaterEqual(n_clear, 3)
        self.assertEqual(n_clear, n_reset, "クリア計上箇所とカウンタリセットの数が合わない")

    def test_threshold_is_two(self):
        self.assertEqual(2, AL.MAX_STARTS_WITHOUT_CLEAR,
                         "2 回目の START で止めないと損失が 1 ライブ分を超える")


class TestTimeLimitNotMidLive(unittest.TestCase):
    """時間上限（--max-seconds）でライブの途中に抜けないこと。

    締め時刻に gameplay のまま break すると、その周回の LIFE が丸ごと無駄になる
    （CLAUDE.md「ライブの途中で autolive を止めないこと」）。
    """

    def test_time_limit_check_is_after_detect_and_skips_gameplay(self):
        src = open(AUTOLIVE, encoding="utf-8").read()
        body = src[src.index("    def _loop(self):"):src.index("\ndef calibrate(")]
        i_detect = body.index("state, res = self.detect(frame)")
        i_limit = body.index("時間上限に到達")
        self.assertLess(i_detect, i_limit, "時間上限の判定は detect() の後に置くこと")
        window = body[body.rfind("if self.max_seconds", 0, i_limit):i_limit]
        self.assertIn("SAFE_EXIT_STATES", window, "安全な画面でだけ抜けること")
        self.assertIn("MAX_SECONDS_GRACE", window, "猶予を超えたら抜ける上限が無い")
        self.assertGreaterEqual(AL.MAX_SECONDS_GRACE, 150, "猶予はライブ 1 本分（約 120 秒）以上")
        for s in ("gameplay", "pause", "menu", "liveassist"):
            self.assertNotIn(s, AL.SAFE_EXIT_STATES, f"{s} で抜けると始まった/始まるライブが無人になる")
        for s in ("result", "songselect", "formation"):
            self.assertIn(s, AL.SAFE_EXIT_STATES)


if __name__ == "__main__":
    unittest.main()
