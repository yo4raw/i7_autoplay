# プロジェクト整理（段階1）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tools/` を本番3・運用8・調査12に3分類し、未追跡20ファイルを git 管理下に入れ、`docs/specification.md` 1,056行を実態中心の6ファイル＋アーカイブへ再編する。周回の振る舞いは1ミリも変えない。

**Architecture:** 変更は「ファイル移動」「移動に伴うパス修正」「ドキュメントの機械的な分割」の3種類だけ。`tools/autolive.py` `tools/driver.py` `tools/note_engine.py` の中身には一切触れない。移動で壊れる相対パス解決は、`tests/test_repo_layout.py` という新しい回帰テストで機械的に検証する（実機不要）。ドキュメントのリンク切れは `tests/test_docs_links.py` で検証する。

**Tech Stack:** Python 3.14（`.venv`）、`unittest`（標準ライブラリのみ）、zsh、git

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-07-30-project-cleanup-design.md`
- **`tools/autolive.py` / `tools/driver.py` / `tools/note_engine.py` は1行も変更しない。** 最終検証で `git diff main -- <3ファイル>` が空であること。
- ドキュメントの移設は**原則コピー**。書き換えてよいのは (1) 節参照の張り替え、(2) 移設に伴う見出しレベルの調整、(3) Task 8 で明示的に追記する 2026-07-30 の新知見、の3点のみ。実機で確定した事実の文言は変えない。
- テストは `.venv/bin/python -m unittest discover -s tests` で全件実行できること。実機（iPhone ミラーリング接続）を必要とするテストは追加しない。
- 作業ブランチは `chore/project-cleanup`（設計書コミット `4a749e7` を含む既存ブランチ）。
- コミットメッセージは日本語。末尾に `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` を付ける。

## File Structure

| ファイル | 責務 |
|---|---|
| `tests/test_repo_layout.py`（新規） | `tools/` の3分類・スクリプトの構文・移動後のパス解決・旧パス参照の残存を検証 |
| `tests/test_docs_links.py`（新規） | `docs/` と `CLAUDE.md` の相対リンク先が存在することを検証 |
| `tools/README.md`（新規） | 3分類の説明と本番3本の役割 |
| `tools/ops/README.md`（新規） | 運用ウォッチャ8本の役割・起動方法 |
| `tools/probes/README.md`（新規） | 調査用12本の「答えが出た疑問と結論」 |
| `docs/README.md`（新規） | 索引。どれが真実かを最初に明示 |
| `docs/setup.md`（新規） | 権限・依存・接続 |
| `docs/architecture.md`（新規） | 2層構成・FSM・座標系・テンプレ管理 |
| `docs/device-findings.md`（新規） | 実機知見（PAUSE 調査史・ノーツ仕様） |
| `docs/navigation.md`（新規） | イベント導線・実測座標・LIFE 回復 |
| `docs/operations.md`（新規） | 無人運用・復旧・トラブルシューティング |
| `docs/archive/original-design.md`（新規） | 未実装の当初設計 |
| `docs/specification.md`（20行の案内スタブへ置換） | 上記へ分割。`autolive.py` のコメントが参照するため削除はしない |

---

### Task 1: 未追跡ファイルを現状のままコミットする

移動より先に履歴へ入れる。こうすると Task 2/3 の移動が git 上で rename として記録され、いつでも戻せる。

**Files:**
- Add: `tools/capture_click.py` `tools/color_probe.py` `tools/color_probe2.py` `tools/focus_probe.py` `tools/focus_state_monitor.py` `tools/hidmove_test.py` `tools/idlekeeper.py` `tools/pause_ab.sh` `tools/pause_monitor.py` `tools/pure_observe.py` `tools/result_grab.py` `tools/supervise_autolive.sh` `tools/trigger_test.py` `tools/unlock_watcher.py`
- Add: `assets/screens/mac_inuse/` `assets/screens/mac_unlock_prompt/`
- Modify: `.gitignore`（`tests/corpus_raw/` を除外）

**Interfaces:**
- Consumes: なし
- Produces: 以降のタスクが `git mv` を使える状態

**`tests/corpus_raw/` はコミットしない**（507枚・69MB。ユーザー指示で大量の画像は git に入れない）。
`.gitignore` で除外し、ローカル資産として保持する。`assets/screens/mac_unlock_prompt/` は
数十KB で `unlock_watcher.py` が `id_text.png` をテンプレ照合に使うため、これはコミットする。

- [ ] **Step 1: 未追跡ファイルの一覧を確認する**

```bash
cd /Users/yo4raw/git/i7_autoplay
git status --porcelain
```

期待: 17行の `??` が出る（`tools/` 12本 + `assets/screens/` 2ディレクトリ + `tests/corpus_raw/`）。
`tools/supervise_autolive.sh` と `tools/unlock_watcher.py` が含まれることを目視確認する。

- [ ] **Step 2: `.gitignore` にコーパスの除外を追加する**

`.gitignore` の末尾に追記する。

```gitignore

# 実フレームコーパス（14状態・507枚・69MB。tools/ops/corpus_collector.py で採取する）
# 大きいので git には入れない。無い環境では tests/test_corpus_smoke.py が skip される。
/tests/corpus_raw/
```

追記後、除外が効いていることを確認する。

```bash
git status --porcelain | grep corpus_raw || echo "corpus_raw は除外された"
```

期待: `corpus_raw は除外された`。

- [ ] **Step 3: 残りをステージする**

```bash
git add tools/ assets/screens/mac_inuse assets/screens/mac_unlock_prompt .gitignore
git status --porcelain
git diff --cached --stat | tail -3
```

期待: `A ` （追加）と `.gitignore` の `M ` のみ。stat の合計は 20 ファイル前後
（tools 12 + assets 数枚 + .gitignore）。
**`tools/autolive.py` `tools/driver.py` `tools/note_engine.py` が `M ` で現れないこと** —
本番3ファイルを触っていない証拠。

- [ ] **Step 4: 既存テストが通ることを確認する**

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

期待: `OK`。ローカルには `tests/corpus_raw/` が残っているので `test_corpus_smoke` は
実行される（git には入らないだけ）。

- [ ] **Step 5: コミット**

```bash
git commit -q -F - <<'EOF'
chore: 未追跡の運用スクリプト・調査ツールを取り込み、コーパスを除外する

CLAUDE.md が起動を指示している supervise_autolive.sh を含む tools 12本が
未追跡で、clone した環境では存在しなかった。unlock_watcher.py が参照する
mac_unlock_prompt / mac_inuse の画面資料もあわせて取り込む。

tests/corpus_raw（14状態・507枚・69MB）は大きいので .gitignore で除外し、
ローカル資産として保持する。無い環境では test_corpus_smoke が skip される。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git status --porcelain
```

期待: `git status --porcelain` の出力が空（`tests/corpus_raw/` は無視されるため現れない）。

---

### Task 2: `tools/ops/` へ運用スクリプト8本を移動し、パス解決を直す

**Files:**
- Create: `tests/test_repo_layout.py`
- Move: `tools/{supervise_autolive.sh,freeze_sentinel.sh,morning_watcher.sh,pause_guard.sh,reconnect_watcher.py,recover_freeze.py,unlock_watcher.py,corpus_collector.py}` → `tools/ops/`
- Modify: 上記8本のパス解決とドキュストリング

**Interfaces:**
- Consumes: Task 1 の git 管理下のファイル
- Produces: `tests/test_repo_layout.py` に定数 `ROOT` `TOOLS` `PROD` `OPS` `PROBES` を定義。Task 3・Task 5 がこの同じファイルにテストを追加する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_repo_layout.py` を新規作成:

```python
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
```

`tools/` 直下の本番3本チェックと CWD 依存 `sys.path` のチェックは Task 3 で追加する。
probes が未移動のうちは必ず失敗するので、ここで入れるとコミットがレッドになるため。

- [ ] **Step 2: テストを実行して失敗することを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout -v 2>&1 | tail -20
```

期待: FAIL。`test_ops_scripts_are_under_ops` が `[] != OPS`（`tools/ops/` が存在しない）。
`TestOpsPathResolution.test_asset_paths_resolve` も `ModuleNotFoundError` で ERROR になる。

- [ ] **Step 3: ディレクトリを作って8本を移動する**

```bash
cd /Users/yo4raw/git/i7_autoplay
mkdir -p tools/ops
git mv tools/supervise_autolive.sh tools/freeze_sentinel.sh tools/morning_watcher.sh \
       tools/pause_guard.sh tools/reconnect_watcher.py tools/recover_freeze.py \
       tools/unlock_watcher.py tools/corpus_collector.py tools/ops/
git status --porcelain
```

期待: 8行すべて `R ` （rename）。

- [ ] **Step 4: Python 4本の `sys.path` と `ROOT` を直す**

`tools/ops/reconnect_watcher.py` `tools/ops/recover_freeze.py` `tools/ops/unlock_watcher.py` の3本で、次の行を置換する。

置換前:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```
置換後:
```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
```

置換前:
```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```
置換後:
```python
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`tools/ops/corpus_collector.py` は `ROOT` 変数を持たず、31行目付近で直接組み立てている。

置換前:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```
置換後:
```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
```

置換前:
```python
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "corpus_raw")
```
置換後:
```python
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tests", "corpus_raw")
```

- [ ] **Step 5: シェル3本の作業ディレクトリと内部参照を直す**

`tools/ops/supervise_autolive.sh` と `tools/ops/freeze_sentinel.sh` は
`cd "$(dirname "$0")/.."` でリポジトリルートへ移動している。1階層深くなったので直す。

置換前（両ファイル）:
```zsh
cd "$(dirname "$0")/.."
```
置換後:
```zsh
cd "$(dirname "$0")/../.."
```

`tools/ops/freeze_sentinel.sh` は他スクリプトを旧パスで呼んでいる（49行目・51行目）。

置換前:
```zsh
  if python -u tools/recover_freeze.py >> "$SLOG" 2>&1; then
    slog "recovery OK -> relaunch supervisor"
    nohup tools/supervise_autolive.sh "$TARGET" > /dev/null 2>&1 &
```
置換後:
```zsh
  if python -u tools/ops/recover_freeze.py >> "$SLOG" 2>&1; then
    slog "recovery OK -> relaunch supervisor"
    nohup tools/ops/supervise_autolive.sh "$TARGET" > /dev/null 2>&1 &
```

`tools/ops/morning_watcher.sh` はリポジトリパスをハードコードしている。移動では壊れないが、
他2本と同じ方式に揃えて可搬にする。

置換前:
```zsh
cd /Users/yo4raw/git/i7_autoplay
```
置換後:
```zsh
cd "$(dirname "$0")/../.."
```

`tools/ops/pause_guard.sh` は `cd` を持たずログファイルの絶対パスだけを見るので変更不要。

- [ ] **Step 6: 各スクリプトのドキュストリング内の「使い方」を新パスにする**

| ファイル | 置換前 | 置換後 |
|---|---|---|
| `tools/ops/reconnect_watcher.py` | `使い方: python -u tools/reconnect_watcher.py [timeout_sec=14400]` | `使い方: python -u tools/ops/reconnect_watcher.py [timeout_sec=14400]` |
| `tools/ops/recover_freeze.py` | `使い方: python -u tools/recover_freeze.py   （成功で exit 0 / 失敗 exit 1）` | `使い方: python -u tools/ops/recover_freeze.py   （成功で exit 0 / 失敗 exit 1）` |
| `tools/ops/corpus_collector.py` | `使い方: python -u tools/corpus_collector.py <duration_sec> [out_dir]` | `使い方: python -u tools/ops/corpus_collector.py <duration_sec> [out_dir]` |
| `tools/ops/supervise_autolive.sh` | `# 使い方: tools/supervise_autolive.sh <target_epoch>` | `# 使い方: tools/ops/supervise_autolive.sh <target_epoch>` |
| `tools/ops/freeze_sentinel.sh` | `# 使い方: tools/freeze_sentinel.sh <target_epoch>` | `# 使い方: tools/ops/freeze_sentinel.sh <target_epoch>` |

`tools/ops/unlock_watcher.py` のドキュストリングに「使い方」行は無いので変更不要。

- [ ] **Step 7: テストを実行して ops 関連が通ることを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout -v 2>&1 | tail -20
```

期待: **すべて PASS**（`test_ops_scripts_are_under_ops` `test_python_scripts_compile`
`test_shell_scripts_parse` `test_asset_paths_resolve`）。

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

期待: `OK`。このコミットの時点でスイートは緑であること。

- [ ] **Step 8: 実際に起動して落ち方を確認する**

```bash
.venv/bin/python -u tools/ops/reconnect_watcher.py 1 2>&1 | tail -3
```

期待: ミラーリング未接続なら「ウィンドウが見つからない」系の例外か、タイムアウトで exit 1。
**`ModuleNotFoundError: No module named 'driver'` や `FileNotFoundError` でテンプレを見失う形で落ちないこと**。

- [ ] **Step 9: コミット**

```bash
git add -A tools tests/test_repo_layout.py
git commit -q -F - <<'EOF'
refactor: 運用スクリプト8本を tools/ops/ へ移し、パス解決を修正

移動で1階層深くなるため、Python 4本の sys.path と ROOT、
シェル2本の cd、freeze_sentinel.sh の内部呼び出しを修正。
morning_watcher.sh のハードコードされたリポジトリパスも相対に統一した。
構成とパス解決は tests/test_repo_layout.py で回帰検証する。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `tools/probes/` へ調査用12本を移動し、パス解決を直す

**Files:**
- Move: `tools/{trigger_test.py,idlekeeper.py,capture_click.py,color_probe.py,color_probe2.py,focus_probe.py,focus_state_monitor.py,hidmove_test.py,pause_ab.sh,pause_monitor.py,pure_observe.py,result_grab.py}` → `tools/probes/`
- Modify: `tests/test_repo_layout.py`（probes のアサーションを追加）

**Interfaces:**
- Consumes: Task 2 の `tests/test_repo_layout.py`（`PROBES` 定数は定義済み）
- Produces: `tools/` 直下が本番3本だけになった状態

- [ ] **Step 1: 失敗するテストを追加する**

`tests/test_repo_layout.py` の `TestToolsLayout` クラスに次のメソッドを追加する:

```python
    def test_probe_scripts_are_under_probes(self):
        self.assertEqual(sorted(PROBES), _scripts_in(os.path.join(TOOLS, "probes")))
```

- [ ] **Step 2: テストを実行して失敗することを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestToolsLayout -v 2>&1 | tail -10
```

期待: `test_probe_scripts_are_under_probes` が FAIL（`[] != [...]`）。

- [ ] **Step 3: 12本を移動する**

```bash
cd /Users/yo4raw/git/i7_autoplay
mkdir -p tools/probes
git mv tools/trigger_test.py tools/idlekeeper.py tools/capture_click.py \
       tools/color_probe.py tools/color_probe2.py tools/focus_probe.py \
       tools/focus_state_monitor.py tools/hidmove_test.py tools/pause_ab.sh \
       tools/pause_monitor.py tools/pure_observe.py tools/result_grab.py tools/probes/
ls tools
```

期待: `ls tools` が `README.md` を除き `autolive.py  driver.py  note_engine.py  ops  probes` のみ
（README.md は Task 4 で作る）。

- [ ] **Step 4: CWD 依存の `sys.path` を `__file__` 基準に直す**

`tools/probes/` の8本 — `color_probe.py` `color_probe2.py` `hidmove_test.py`
`focus_state_monitor.py` `pure_observe.py` `pause_monitor.py` `trigger_test.py`
`result_grab.py` — は次の行を持つ。

置換前:
```python
sys.path.insert(0, 'tools')
```
置換後:
```python
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
```

ただし `pause_monitor.py` は既に `import sys, time, os` で `os` を import 済みなので、
`import os` の行は足さず置換後の2行目だけにする。

`tools/probes/idlekeeper.py` は `__main__` ブロックの中（87行目付近）に同じ行がある。
このファイルは冒頭で `import ctypes, ctypes.util, sys, time, subprocess, re` を行っており
`os` を import していないので、`import os` ごと差し替える。

置換前:
```python
        sys.path.insert(0, 'tools')
        import driver
```
置換後:
```python
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import driver
```

`tools/probes/capture_click.py` と `tools/probes/focus_probe.py` は `sys.path` 操作を持たず
`Quartz` / `AppKit` しか使わないので変更不要。

- [ ] **Step 5: `pause_ab.sh` の作業ディレクトリを直す**

置換前:
```zsh
cd "$(dirname "$0")/.."
```
置換後:
```zsh
cd "$(dirname "$0")/../.."
```

- [ ] **Step 6: ドキュストリング内の「使い方」を新パスにする**

| ファイル | 置換前 | 置換後 |
|---|---|---|
| `tools/probes/focus_probe.py` | `使い方: python tools/focus_probe.py [dur] [--tap] [--resume]` | `使い方: python tools/probes/focus_probe.py [dur] [--tap] [--resume]` |

他の11本のドキュストリングに `tools/` 付きのパス表記は無い。

- [ ] **Step 7: テストを実行して全件通ることを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout -v 2>&1 | tail -20
```

期待: すべて PASS。特に `test_production_scripts_stay_at_tools_root`（本番3本のみ）と
`test_no_cwd_relative_syspath`（違反ゼロ）が通ること。

- [ ] **Step 8: 既存テストも通ることを確認する**

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

期待: `OK`。

- [ ] **Step 9: コミット**

```bash
git add -A tools tests/test_repo_layout.py
git commit -q -F - <<'EOF'
refactor: 調査用スクリプト12本を tools/probes/ へ移す

これで tools/ 直下は本番3本（autolive / driver / note_engine）だけになる。
CWD 依存だった sys.path.insert(0, 'tools') を __file__ 基準に統一し、
リポジトリルート以外から実行しても動くようにした。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: 3つの README を書く

**Files:**
- Create: `tools/README.md` `tools/ops/README.md` `tools/probes/README.md`

**Interfaces:**
- Consumes: Task 2・3 で確定したディレクトリ構成
- Produces: `docs/README.md`（Task 6）からリンクされる入口

- [ ] **Step 1: `tools/README.md` を書く**

```markdown
# tools/

| ディレクトリ | 中身 | いつ使うか |
|---|---|---|
| `tools/`（直下） | 本番3本 | 周回そのもの |
| `tools/ops/` | 無人運用ウォッチャ8本 | 長時間の自動周回を回し続けるとき |
| `tools/probes/` | 調査用ワンショット12本 | 過去の調査を再現・追試するとき |

## 本番

| ファイル | 役割 |
|---|---|
| `autolive.py` | 周回 FSM。capture → detect → act のメインループ。詳細は [`docs/architecture.md`](../docs/architecture.md) |
| `driver.py` | 低レベル I/O。ミラーリングウィンドウ検出・`mss` キャプチャ・`CGEventPost` クリック |
| `note_engine.py` | ノーツのスポーン検出・追跡・種別予報（`--predict` / `--auto-circles` 用、既定 OFF） |

```bash
# 周回（イベントライブ開始済み or 楽曲選択画面から）
python tools/autolive.py --loops 50 --max-seconds 7200 --flick

# 手動ナビゲーション・テンプレ取得（座標はウィンドウ相対 0..1）
python tools/driver.py info
python tools/driver.py shot out.png
python tools/driver.py click <xfrac> <yfrac>
```

**この3本を変更する前に [`docs/README.md`](../docs/README.md) を読むこと。** 実機でしか判明しない制約が多数あり、素直に見える変更が周回を止める。
```

- [ ] **Step 2: `tools/ops/README.md` を書く**

```markdown
# tools/ops/ — 無人運用ウォッチャ

周回そのものではなく、周回を「回し続ける」ための外側の仕組み。人間（または supervisor LLM）が起動する。
運用手順は [`docs/operations.md`](../../docs/operations.md) を参照。

| ファイル | 役割 | 状態 |
|---|---|---|
| `supervise_autolive.sh` | `autolive.py` がクラッシュ／サイレント死しても目標時刻まで自動再起動する。無人運用の標準入口 | 現役 |
| `freeze_sentinel.sh` | ログを監視し、ハング兆候（cardx 停滞・再起動ループ）を検知したら `recover_freeze.py` で復旧して supervisor を再開 | 現役 |
| `recover_freeze.py` | 「ライフを全回復しました。」フリーズからの自動復旧。強制終了 → 再起動 → 楽曲選択まで復帰 | 現役 |
| `pause_guard.sh` | 直近60秒の PAUSE が閾値を超えたら周回を強制停止。再接続病（`docs/device-findings.md`）の夜間再発で LIFE を浪費しないための保険 | 現役 |
| `reconnect_watcher.py` | ミラーリング切断の「やり直す」ボタンをテンプレ照合で見つけた時だけ押す。再接続成功で exit 0 | 現役 |
| `unlock_watcher.py` | 「iPhoneのロックを解除してください」プロンプトの解消を待つ | 現役 |
| `morning_watcher.sh` | ユーザーが iPhone を触った／再起動した合図（ウィンドウ消失・ID 変化・暗転）を検知する。入力は一切送らない | 現役 |
| `corpus_collector.py` | 周回と並走して画面を受動採取し `tests/corpus_raw/<state>/` へ保存する。**コーパスは `.gitignore` 済み**なので、clone した環境ではこれで採り直す | 現役 |

```bash
# 無人運用の標準手順（target_epoch = 終了する UNIX 時刻）
nohup tools/ops/supervise_autolive.sh $(( $(date +%s) + 7200 )) > /dev/null 2>&1 &
nohup tools/ops/freeze_sentinel.sh   $(( $(date +%s) + 7200 )) > /dev/null 2>&1 &
```
```

- [ ] **Step 3: `tools/probes/README.md` を書く**

```markdown
# tools/probes/ — 調査用ワンショット

特定の疑問に答えるために書かれたツール。**周回には不要**。結論は
[`docs/device-findings.md`](../../docs/device-findings.md) にあり、ここは再現手段として残している。

同じ調査を繰り返さないために、答えの出た疑問と結論を併記する。

| ファイル | 答えようとした疑問 | 出た結論 |
|---|---|---|
| `pure_observe.py` | 入力を送らなければ PAUSE しないのか？ | いいえ。**完全ゼロ入力でも約1秒で PAUSE する**（idle 起因） |
| `trigger_test.py` | どの入力方式なら PAUSE を防げるか？ mode: activate / warp / click / tap / iohid_click / iohid_move / realclick / touchclick / nothing | 正常時は `tap`（HIDSystemState ソース＋カーソルワープ）で防げる。ただし再接続病の状態では**全方式が無効**（2026-07-30 に `iohid_click` も無効と確定） |
| `focus_probe.py` | PAUSE 直前に最前面がミラーリングから外れているのか？ | 外れていない。フォーカス喪失は主因ではない |
| `focus_state_monitor.py` | PAUSE 時に Mac 側の状態が何か変化するか？ | 有意な変化なし |
| `capture_click.py` | 本物のトラックパッド入力と合成入力のイベント属性の差は？ | subtype / pressure / source が異なる。`touchclick` モードで模倣したが PAUSE は防げず |
| `idlekeeper.py` | `IOHIDPostEvent` なら HIDIdleTime を毎回リセットできるか？ | リセットはできるが、再接続病の状態では PAUSE を防げない |
| `hidmove_test.py` | 実 HID のカーソル移動だけで PAUSE を防げるか？ | 防げない |
| `pause_monitor.py` | 合成 keepalive を送らずに PAUSE 回数を数える | 観測用。単独の結論は無し |
| `pause_ab.sh` | 入力方式ごとの PAUSE 数／クリア数を A/B 集計する | 上記 `trigger_test.py` の結論の根拠データ |
| `color_probe.py` | 到達直前 ROI でノーツ色が取れるか？ | 取れる。approach fraction 0.65 で赤を判別可（`--flick` の根拠） |
| `color_probe2.py` | HSV で緑/青ノーツを通常ノーツと分離できるか？ | 分離は難しい。緑ホールド／青スライドは未実装のまま |
| `result_grab.py` | リザルト画面を受動キャプチャして精度ベースラインを測る | 計測用。`--flick` の効果測定（MISS 14→3）に使用 |

いずれも実行にはミラーリング接続が必要。リポジトリルートから実行する想定だが、
`__file__` 基準でパスを解決するのでどこから実行してもよい。
```

- [ ] **Step 4: リンク先が存在することを目視で確認する**

```bash
cd /Users/yo4raw/git/i7_autoplay
ls docs/architecture.md docs/README.md docs/operations.md docs/device-findings.md 2>&1
```

期待: この時点では4つとも `No such file or directory`。**これは想定どおり**で、
Task 6・7 で作る。Task 10 の最終検証（`tests/test_docs_links.py`）で切れが無いことを保証する。

- [ ] **Step 5: コミット**

```bash
git add tools/README.md tools/ops/README.md tools/probes/README.md
git commit -q -F - <<'EOF'
docs: tools/ の3分類に README を追加

probes/ には「答えを出した疑問と結論」を併記し、同じ調査を
繰り返さないようにした。docs/ へのリンクは Task 6-7 で作る
ファイルを指しており、この時点では未解決。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: `CLAUDE.md` と `assets/prompts/` の参照を新パスへ張り替える

**Files:**
- Modify: `CLAUDE.md:143`
- Modify: `assets/prompts/supervisor_loop.md:35`
- Modify: `tests/test_repo_layout.py`（旧パス残存チェックを追加）

**Interfaces:**
- Consumes: Task 2・3 の新パス
- Produces: `tests/test_repo_layout.py::TestNoStaleToolPaths`

- [ ] **Step 1: 失敗するテストを追加する**

`tests/test_repo_layout.py` の末尾（`if __name__` の直前）に追加する:

```python
class TestNoStaleToolPaths(unittest.TestCase):
    """移動したスクリプトを旧パスで参照している箇所が残っていないこと。

    docs/superpowers/（設計書・計画書）と docs/archive/ は当時の記録なので除外する。
    """

    EXCLUDE_PREFIXES = ("docs/superpowers/", "docs/archive/")

    def test_no_old_tool_paths_referenced(self):
        moved = [f.rsplit(".", 1)[0] for f in OPS + PROBES]
        pattern = r"tools/(" + "|".join(moved) + r")\."
        r = subprocess.run(["git", "grep", "-nE", pattern], cwd=ROOT,
                           capture_output=True, text=True)
        hits = [ln for ln in r.stdout.splitlines()
                if not ln.startswith(self.EXCLUDE_PREFIXES)]
        self.assertEqual([], hits, "\n".join(hits))
```

- [ ] **Step 2: テストを実行して失敗することを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestNoStaleToolPaths -v 2>&1 | tail -15
```

期待: FAIL。少なくとも `CLAUDE.md:143`、`assets/prompts/supervisor_loop.md:35`、
`docs/specification.md` の 890 / 917 / 929-931 / 989 / 1053 行が列挙される。

- [ ] **Step 3: `CLAUDE.md` を直す**

置換前:
```
  従来の `nohup tools/supervise_autolive.sh <target_epoch> &` と併用可（プロセス再起動は
```
置換後:
```
  従来の `nohup tools/ops/supervise_autolive.sh <target_epoch> &` と併用可（プロセス再起動は
```

- [ ] **Step 4: `assets/prompts/supervisor_loop.md` を直す**

置換前:
```
| autolive プロセスが死んでいるだけ（supervisor も死んでいる） | クラッシュ/サイレント死（§17.7） | `nohup tools/supervise_autolive.sh <target_epoch> &` で再起動（ログ: /tmp/i7_supervisor.log） |
```
置換後:
```
| autolive プロセスが死んでいるだけ（supervisor も死んでいる） | クラッシュ/サイレント死（`docs/operations.md`） | `nohup tools/ops/supervise_autolive.sh <target_epoch> &` で再起動（ログ: /tmp/i7_supervisor.log） |
```

`assets/prompts/` は「実装・運用時に書き直さずそのまま使う」方針だが、
これは内容の書き換えではなく参照先の追従なので行う。他のプロンプトファイルに
移動対象スクリプトへの言及は無い（Step 2 の出力で確認済み）。

- [ ] **Step 5: テストを実行する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestNoStaleToolPaths -v 2>&1 | tail -15
```

期待: まだ FAIL。ただし残るヒットは `docs/specification.md` のみ。
このファイルは Task 8 で分割・削除するので、その時点で解消する。
`CLAUDE.md` と `assets/prompts/` が消えていることを確認する。

- [ ] **Step 6: コミット**

```bash
git add CLAUDE.md assets/prompts/supervisor_loop.md tests/test_repo_layout.py
git commit -q -F - <<'EOF'
docs: CLAUDE.md と supervisor プロンプトの参照を tools/ops/ へ追従

旧パスの残存は tests/test_repo_layout.py で回帰検証する。
docs/specification.md の言及は Task 8 の分割で解消する。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: `docs/README.md` `docs/setup.md` `docs/architecture.md` を作る

`docs/specification.md` の該当部分を**内容を書き換えずに**コピーする。
行番号は現時点（1,056行）のもの。

**Files:**
- Create: `docs/README.md` `docs/setup.md` `docs/architecture.md`
- Read: `docs/specification.md`（この時点では削除しない）

**Interfaces:**
- Consumes: なし
- Produces: `docs/README.md` が全ドキュメントの索引。Task 7・8 がここにリンクを足す。

- [ ] **Step 1: 移設元の行範囲を切り出して内容を確認する**

```bash
cd /Users/yo4raw/git/i7_autoplay
sed -n '1,16p'    docs/specification.md   # タイトル + ⚠️重要な注意
sed -n '17,45p'   docs/specification.md   # §1 概要
sed -n '84,104p'  docs/specification.md   # §3 スコープ
sed -n '370,380p' docs/specification.md   # §13 セキュリティ・規約
sed -n '511,513p' docs/specification.md   # §17.3 用語集
sed -n '1040,1056p' docs/specification.md # 改訂履歴
```

- [ ] **Step 2: `docs/README.md` を書く**

冒頭に次の「どれが真実か」ブロックを置き、その下に Step 1 で切り出した各節を
この順（⚠️重要な注意 → §1 概要 → §3 スコープ → §13 セキュリティ・規約 → §17.3 用語集 → 改訂履歴）
で貼る。見出しレベルは `##` に揃える。

```markdown
# i7_autoplay ドキュメント

macOS の iPhone ミラーリング越しに IDOLiSH7 の累計イベントライブを自動周回するツール。

## どれが真実か

このリポジトリの事実は**実機でしか判明しない**。ドキュメントは次の役割に分かれている。

| ファイル | 内容 | 信頼度 |
|---|---|---|
| [`setup.md`](setup.md) | 権限付与・依存ライブラリ・接続手順 | 実機確認済み |
| [`architecture.md`](architecture.md) | 2層構成・FSM・座標系・テンプレート管理 | 実機確認済み |
| [`device-findings.md`](device-findings.md) | 実機知見。PAUSE 調査史・ノーツ仕様・端末非依存 | 実機確認済み。**変更前に必読** |
| [`navigation.md`](navigation.md) | イベント導線・実測座標・LIFE 回復 | 実機確認済み。座標はイベントごとに変わりうる |
| [`operations.md`](operations.md) | 無人運用・停止条件・復旧・トラブルシューティング | 実機確認済み |
| [`screen-transitions.md`](screen-transitions.md) | 画面遷移の観察記録 | 観察記録 |
| [`note-engine-dev.md`](note-engine-dev.md) | ノーツエンジンの開発メモ | 開発メモ |
| [`archive/original-design.md`](archive/original-design.md) | 実装前に書いた当初設計。**未実装**（OCR・設定ファイル・CLI 仕様など） | 履歴。実態ではない |
| [`superpowers/`](superpowers/) | 設計書（specs）と実装計画（plans） | 時点の記録 |

コードの入口は [`../tools/README.md`](../tools/README.md)。
LLM copilot 用のプロンプト資産は [`../assets/prompts/README.md`](../assets/prompts/README.md)。
画面グラフのドラフト素材は `../data/screens_draft.yaml`（`superpowers/specs/2026-06-10-screen-graph-design.md` の観察記録。実装前の参考データ）。

## 実フレームコーパス（git に入っていない）

`tests/corpus_raw/`（14状態・507枚・69MB）は実機なしで `detect()` の回帰を検証できる資産だが、
サイズが大きいので `.gitignore` で除外している。clone した環境には存在しない。

採取するには周回中に次を並走させる。入力を一切送らないので周回を妨げない。

```bash
python -u tools/ops/corpus_collector.py 1800    # 30分ぶん採取
```

`tests/test_corpus_smoke.py` はコーパスが無ければ skip されるので、
`.venv/bin/python -m unittest discover -s tests` はコーパス無しでも通る。
```

- [ ] **Step 3: `docs/setup.md` を書く**

```bash
sed -n '46,83p'   docs/specification.md   # §2 前提条件・動作環境
sed -n '383,397p' docs/specification.md   # §14.1 推奨ライブラリ
```

`# セットアップ` の見出しを付け、上記2ブロックをこの順で貼る。見出しレベルを `##` に揃える。

- [ ] **Step 4: `docs/architecture.md` を書く**

```bash
sed -n '105,158p' docs/specification.md   # §4 システム構成
sed -n '159,165p' docs/specification.md   # §5.1 ライブ周回機能
sed -n '172,190p' docs/specification.md   # §5.3-5.5 ポップアップ/停止条件/進捗
sed -n '191,198p' docs/specification.md   # §6 FSM
sed -n '199,233p' docs/specification.md   # §7 テンプレート管理
sed -n '436,444p' docs/specification.md   # §15 テスト方針
sed -n '458,500p' docs/specification.md   # §17.1 テンプレチェックリスト
sed -n '628,699p' docs/specification.md   # §17.5 実装状況
```

`# アーキテクチャ` の見出しを付け、上記8ブロックをこの順で貼る。
`§5.2 スタミナ回復`（166-171行）は `navigation.md`（Task 7）へ行くのでここには含めない。

- [ ] **Step 5: 貼り漏れが無いことを確認する**

```bash
wc -l docs/README.md docs/setup.md docs/architecture.md
```

期待: 3ファイルの合計が 400 行以上（移設元の合計 = 16+29+21+11+3+17 + 38+15 + 54+7+19+8+35+9+43+72 = 397 行、
これに `docs/README.md` の索引ブロック約 25 行が加わる）。350 行を下回るなら貼り漏れを疑う。

なお `## 17. 付録` の見出し行（456-457行）だけはどこにも移さない。中身のない見出しのため。

- [ ] **Step 6: コミット**

```bash
git add docs/README.md docs/setup.md docs/architecture.md
git commit -q -F - <<'EOF'
docs: 索引・セットアップ・アーキテクチャを specification.md から分離

内容は書き換えず移設。README.md に「どれが真実か」の表を追加し、
未実装の当初設計と実機確認済みの事実を読み手が区別できるようにした。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 7: `docs/device-findings.md` `docs/navigation.md` `docs/operations.md` を作り、2026-07-30 の新知見を追記する

**Files:**
- Create: `docs/device-findings.md` `docs/navigation.md` `docs/operations.md`
- Read: `docs/specification.md`

**Interfaces:**
- Consumes: Task 6 の `docs/README.md`（リンク先として既に列挙済み）
- Produces: `tools/*/README.md` からのリンク先が解決する状態

- [ ] **Step 1: `docs/device-findings.md` を書く**

```bash
sed -n '849,876p'  docs/specification.md   # §17.6 (F) PAUSE の解決策
sed -n '898,933p'  docs/specification.md   # §17.8 PAUSE 多発の真因と修正
sed -n '934,963p'  docs/specification.md   # §17.9 画面構造・ノーツ仕様
sed -n '964,998p'  docs/specification.md   # §17.10 再接続後の PAUSE 再燃
sed -n '999,1028p' docs/specification.md   # §17.11 ハイブリッド打鍵方式
```

`# 実機知見` の見出しを付け、上記5ブロックをこの順で貼る。
節見出しは `## PAUSE の解決策（2026-06-05）` のように内容ベースへ書き換え、
本文中の `§17.x` 参照は新しい見出しへのリンクに置き換える。**本文の事実記述は変えない。**

- [ ] **Step 2: 2026-07-30 の再現記録を `docs/device-findings.md` に追記する**

「再接続後の PAUSE 再燃」節の末尾に追加する:

```markdown
### 2026-07-30 の再現記録（イベント周回セッション）

同じ症状が再現した。以下は今回の切り分けで新たに確定したこと。

- **症状**: ライブ中に約5秒周期で PAUSE →（自動再開）→ カウントダウン → 再び PAUSE。
  1ノーツも処理できず SCORE は `000000000` のまま。`autolive.py` のログは
  `PAUSE → 再開` だけが 5 秒間隔で並ぶ。
- **`_keep_front` は無関係**（activate 連打の件とは別物）。
  `NSWorkspace.frontmostApplication` は一貫して `iPhone Mirroring` を返し、
  再アクティブ化は発生していない。
- **カーソルのワープは機能している**。`CGEventGetLocation` を 0.4 秒間隔でサンプルすると
  タップ円の座標間を移動しており、`CGWarpMouseCursorPosition` は効いている。
- **`iohid_click`（`IOHIDPostEvent` による実 HID クリック）でも防げない**（新規確定）。

  ```
  $ .venv/bin/python -u tools/probes/trigger_test.py iohid_click 40 0.4 --resume
  DONE mode=iohid_click pauses=8 first_pause=0.389
       ptimes=[0.4, 6.0, 11.5, 17.1, 22.6, 28.1, 33.7, 39.2]
  ```

  40 秒間に PAUSE 8 回。既に無効と分かっていた tap / touchclick / realclick / iohid_move に加え、
  **iohid_click も無効**であることが確定した。Mac 側で試せる入力方式は出尽くした。
- **完全無入力では約1秒で PAUSE し、そのまま復帰しない**。idle 起因であることの裏付け。
- **結論は変わらず: 復旧手段は iPhone 本体の電源再投入。**
```

- [ ] **Step 3: `docs/navigation.md` を書く**

```bash
sed -n '514,627p' docs/specification.md   # §17.4 実機ナビゲーション情報
sed -n '700,848p' docs/specification.md   # §17.6 (A)-(E) 座標・LIFE 回復・PAUSE メニュー
sed -n '166,171p' docs/specification.md   # §5.2 スタミナ回復機能
```

`# 実機ナビゲーション` の見出しを付け、上記3ブロックをこの順で貼る。

- [ ] **Step 4: 2026-07-30 のイベント導線を `docs/navigation.md` に追記する**

```markdown
## イベント「BUDDY Night NARRATIVE」の導線（2026-07-30 実測）

開催期間 2026/07/30 17:00 - 2026/08/06 16:59。ホーム左下のイベントリボンから入った後の手順。
座標はすべて**ウィンドウ相対** 0..1（`driver.py click <xfrac> <yfrac>` で押せる系）。

| 手順 | 画面 | 操作 | 座標 |
|---|---|---|---|
| 1 | イベントトップ | 「イベント楽曲」ボタン | `(0.7015, 0.840)` |
| 2 | イベント楽曲選択 | EASY タブ | `(0.663, 0.712)` |
| 3 | 同上 | NEXT | `(0.749, 0.830)` |
| 4 | フレンド選択 | 先頭のフレンド行 | `(0.45, 0.44)` |
| 5 | 編成確認 | START | `(0.700, 0.851)` |

観測時のミラーリングウィンドウは **671 × 348**（横向き、scale 2.0）。
既存の `assets/screens/*/_full.png` は 529 × 334 で撮られており、機種／ウィンドウサイズが異なる。
テンプレ照合は当たったが、座標は端末ごとに取り直す前提で読むこと。

### LIFE 表示はブースト込みの実消費値

**難易度タブに出る LIFE 15 / 30 / 45 / 60 は、ブースト3倍を適用した後の実消費値**（素の消費は 5 / 10 / 15 / 20）。
フレンド選択画面のヘッダも `♥ -15` と 3 倍適用後の値を出す。
「ブーストが効いていないのでは」と誤読しやすいので注意する。
既出の「LIFE 消費 = 16（ブースト3倍時）」も同じ性質の値。

ブーストが設定済みかどうかは、楽曲選択・編成画面の下部パネルが
`ブースト 3倍 / オート OFF` と表示されているかで判断する。

### フレンド選択のタップは1回目が無視されることがある

画面遷移アニメーション中のタップは効かない。フレンド行が3件描画されきってから
もう一度タップすると通る。`autolive.py` は再試行するので実害は無いが、
手動ナビゲーション時は 0.8〜1.5 秒待ってから撮り直すこと。
```

- [ ] **Step 5: `docs/operations.md` を書く**

```bash
sed -n '877,897p'   docs/specification.md   # §17.7 長時間無人運用の運用知見
sed -n '501,510p'   docs/specification.md   # §17.2 トラブルシューティング
sed -n '445,455p'   docs/specification.md   # §16 既知のリスク・制約
sed -n '1029,1039p' docs/specification.md   # 起動方法（PoC）
```

`# 運用` の見出しを付け、上記4ブロックをこの順で貼る。
貼った後、本文中の `tools/supervise_autolive.sh` `tools/recover_freeze.py` などの
旧パスをすべて `tools/ops/...` へ直す（Task 5 のテストがこれを検証する）。

- [ ] **Step 6: 旧パス参照が消えたことを確認する**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestNoStaleToolPaths -v 2>&1 | tail -15
```

期待: まだ FAIL（`docs/specification.md` が残っているため）。
ただし新規作成した `docs/operations.md` `docs/device-findings.md` `docs/navigation.md` が
ヒット一覧に**含まれていない**こと。含まれていたら Step 5 の置換漏れ。

- [ ] **Step 7: コミット**

```bash
git add docs/device-findings.md docs/navigation.md docs/operations.md
git commit -q -F - <<'EOF'
docs: 実機知見・ナビゲーション・運用を specification.md から分離

あわせて 2026-07-30 のイベント周回セッションで判明した事項を追記:
- 再接続後の PAUSE 再燃を再現。iohid_click も無効と確定（40秒で8回）
- イベント「BUDDY Night NARRATIVE」の導線座標
- 難易度タブの LIFE 15/30/45/60 はブースト3倍込みの実消費値

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 8: 当初設計をアーカイブし、`docs/specification.md` を案内スタブに置き換える

**Files:**
- Create: `docs/archive/original-design.md`
- Replace: `docs/specification.md`（1,056行 → 案内スタブ）
- Create: `tests/test_docs_links.py`
- Modify: `docs/screen-transitions.md:5,222,227`

**Interfaces:**
- Consumes: Task 6・7 で作った6ファイル
- Produces: `docs/specification.md` が案内スタブになった状態。`tests/test_docs_links.py::TestDocsLinks`

**なぜ削除ではなくスタブか:** `tools/autolive.py` が6箇所（6・13・29・63・161・849行）のコメントで
`docs/specification.md` を参照している。段階1では本番3ファイルを1行も変更しないと決めているため、
削除するとコードのコメントがリンク切れになる。コメントの更新は段階2（`autolive.py` の分割）で行う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_docs_links.py` を新規作成:

```python
"""ドキュメントの相対リンクが切れていないことを検証する（実機不要）。"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:")


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
```

- [ ] **Step 2: テストを実行して失敗することを確認する**

```bash
.venv/bin/python -m unittest tests.test_docs_links -v 2>&1 | tail -20
```

期待: `test_specification_md_is_a_redirect_stub` が FAIL（1,056行あるため
`assertLess(..., 25)` で落ちる）。`test_relative_links_resolve` の結果も記録しておく
（切れがあれば Step 5 で直す）。

- [ ] **Step 3: 当初設計をアーカイブへ切り出す**

```bash
cd /Users/yo4raw/git/i7_autoplay
mkdir -p docs/archive
{
  echo '# 当初設計（未実装・履歴）'
  echo
  echo '> このファイルは実装前（2026-06-04）に書かれた設計で、**実装されていない**。'
  echo '> 実態は [`../README.md`](../README.md) から辿ること。'
  echo '> ここに書かれた OCR・設定ファイル・ログ／CLI 仕様・プロジェクト構成は現在のコードに存在しない。'
  echo
  sed -n '234,253p'  docs/specification.md   # §8 OCR 仕様
  sed -n '254,333p'  docs/specification.md   # §9 設定ファイル仕様
  sed -n '334,343p'  docs/specification.md   # §10 ログ仕様
  sed -n '344,355p'  docs/specification.md   # §11 エラーハンドリング
  sed -n '356,369p'  docs/specification.md   # §12 CLI 仕様
  sed -n '381,382p'  docs/specification.md   # §14 見出し
  sed -n '398,435p'  docs/specification.md   # §14.2-14.4
} > docs/archive/original-design.md
wc -l docs/archive/original-design.md
```

期待: 180 行前後（20+80+10+12+14+2+38 = 176 行 + 案内5行）。

- [ ] **Step 4: `docs/specification.md` を案内スタブに置き換える**

```bash
cd /Users/yo4raw/git/i7_autoplay
cat > docs/specification.md <<'EOF'
# （このファイルは分割されました）

1,056 行あった仕様書は、実態中心の構成へ再編しました。行き先は
**[`README.md`](README.md)** の索引を見てください。

| 元の章 | 行き先 |
|---|---|
| §1 概要 / §3 スコープ / §13 セキュリティ / §17.3 用語集 / 改訂履歴 | [`README.md`](README.md) |
| §2 前提条件 / §14.1 推奨ライブラリ | [`setup.md`](setup.md) |
| §4 構成 / §5 機能要件 / §6 FSM / §7 テンプレート / §15 テスト方針 / §17.1 / §17.5 | [`architecture.md`](architecture.md) |
| §17.6 (F) / §17.8 / §17.9 / §17.10 / §17.11 | [`device-findings.md`](device-findings.md) |
| §17.4 / §17.6 (A)-(E) / §5.2 | [`navigation.md`](navigation.md) |
| §17.7 / §17.2 / §16 / 起動方法(PoC) | [`operations.md`](operations.md) |
| §8 OCR / §9 設定ファイル / §10 ログ / §11 エラー / §12 CLI / §14.2-14.4（いずれも未実装） | [`archive/original-design.md`](archive/original-design.md) |

`tools/autolive.py` のコメントがまだこのパスを参照しているため、ファイル自体は残しています。
コメントの更新は `autolive.py` の分割（段階2）で行います。
EOF
wc -l docs/specification.md
```

期待: 20 行。

- [ ] **Step 5: `docs/screen-transitions.md` の参照を直す**

3箇所ある（5行目・222行目・227行目）。

置換前:
```
`docs/specification.md`（仕様書）にあった設計時の FSM 概念仕様（S0〜S16）も本書の付録Aに集約した。
```
置換後:
```
旧 `docs/specification.md`（現 [`architecture.md`](architecture.md)）にあった設計時の FSM 概念仕様（S0〜S16）も本書の付録Aに集約した。
```

置換前:
```
- `docs/specification.md` — 全体仕様（§17.6F PAUSE 対策の詳細）
```
置換後:
```
- [`device-findings.md`](device-findings.md) — PAUSE 対策の詳細
- [`README.md`](README.md) — ドキュメント索引
```

置換前:
```
## 付録A. 設計時の FSM 概念仕様（specification.md §6 より移設）
```
置換後:
```
## 付録A. 設計時の FSM 概念仕様（旧 specification.md §6 より移設）
```

- [ ] **Step 6: 両方のテストを実行する**

```bash
.venv/bin/python -m unittest tests.test_docs_links tests.test_repo_layout -v 2>&1 | tail -25
```

期待: すべて PASS。`TestNoStaleToolPaths` も、`docs/specification.md` の本文が
スタブに置き換わったことで解消する。

- [ ] **Step 7: コミット**

```bash
git add docs/archive/original-design.md docs/specification.md \
        docs/screen-transitions.md tests/test_docs_links.py
git commit -q -F - <<'EOF'
docs: 未実装の当初設計を archive へ移し、specification.md を案内スタブに

OCR・設定ファイル・ログ／CLI 仕様・プロジェクト構成は実装されておらず、
実態と混同されていた。docs/archive/original-design.md へ履歴として保存する。

specification.md は削除せず 20 行の案内スタブに置き換えた。
tools/autolive.py が6箇所のコメントでこのパスを参照しており、段階1では
本番3ファイルを変更しないため。コメント更新は段階2で行う。

リンク切れは tests/test_docs_links.py で回帰検証する。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 9: `CLAUDE.md` を入口＋絶対規則に縮約する

現在 148 行。アーキテクチャ詳細・端末非依存の実装方針・テンプレ取得手順は `docs/` へ移したので、
`CLAUDE.md` は「最初に読む1枚」に徹する。

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 6・7 で作った `docs/*.md`
- Produces: なし（最終成果物）

- [ ] **Step 1: 現在の内容を確認する**

```bash
cd /Users/yo4raw/git/i7_autoplay
wc -l CLAUDE.md
grep -n "^#" CLAUDE.md
```

- [ ] **Step 2: `CLAUDE.md` を書き換える**

全文を次で置き換える。

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
（このファイルは、本リポジトリで作業する将来の Claude Code への手引きです。以下は日本語で記述します。）

## 概要

macOS の **iPhone ミラーリング** 越しに **アイドリッシュセブン (IDOLiSH7)** の「累計イベント」
ライブを自動周回するツール。ミラーリングウィンドウをキャプチャ → 現在画面を認識 → 合成タップを
送り、イベントライブを繰り返しクリアする。ビルドシステムは無く、スクリプト＋テンプレ画像＋
ドキュメントから成る。

**真実の情報源は [`docs/README.md`](docs/README.md)。** FSM の全体像、実機で確認した画面遷移、
正確な座標、苦労して判明したプラットフォーム制約はそこから辿れる。挙動を変える前に必ず
[`docs/device-findings.md`](docs/device-findings.md) を読むこと。

コードの入口は [`tools/README.md`](tools/README.md)。

## 絶対規則（破ると課金事故・周回が無意味になる）

1. **LIFE 回復はきなこパンのみ。ステラは絶対に使わない。** ステラのボタン座標は意図的に
   コードに持たせていない。きなこパンが尽きたら**フォールバックせず停止**する。
2. **難易度は必ず EASY。**
3. **イベント楽曲へはホーム左下のイベントリボンから入る。** ホームの「LIVE」ボタンから入ると
   通常ライブで、クリアしてもイベント pt が一切付かない。
4. **ブースト倍率は必ず 3 倍。**
5. **未知の明るい画面ではクリックせず停止する。** 盲目連打はしない（課金ボタンの誤タップ防止）。
6. **合成入力は `kCGHIDEventTap` かつ HIDSystemState ソース＋実カーソルのワープ。**
   これ以外の経路ではゲームが数秒ごとに PAUSE する。実行中は Mac のマウスを操作しないこと。
7. **キャプチャは `mss` を使う。** `screencapture -l<windowid>` はフォーカスを奪い PAUSE させる。
8. **座標系は2つある。** `click_window(xf,yf)` はウィンドウ相対、`click_content(xf,yf)` は
   内容矩形相対。混同すると誤クリックする。

## コマンド

```bash
# セットアップ（Python 3.11+。リポジトリは Python 3.14 の .venv を使用）
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa opencv-python mss numpy Pillow

# 自動周回（ゲームをイベントライブ開始済み or 楽曲選択画面にしてから実行）
python tools/autolive.py --loops 50 --max-seconds 7200 --flick
python tools/autolive.py --loops 3 --verbose          # 短いデバッグ実行
python tools/autolive.py --loops 2 --dry-run          # 判定のみ・クリックしない

# 手動ドライバ（探索／テンプレ取得用。座標はウィンドウ相対 0..1）
python tools/driver.py info
python tools/driver.py shot out.png
python tools/driver.py click <xfrac> <yfrac>

# テスト（実機不要・合成フレームとコーパス）
.venv/bin/python -m unittest discover -s tests
```

事前に一度、**スクリプトを起動するホストプロセス**（Terminal / iTerm / VS Code など。.py ファイル
ではない）へ、システム設定で **画面収録** と **アクセシビリティ** を付与し、そのホストを
再起動すること。macOS のアップデートでこれらは無言で無効化される。
詳細は [`docs/setup.md`](docs/setup.md)。

リンタ／フォーマッタは未設定。デバッグ用スクショは `/tmp/i7dbg/` に保存される。

## LLM copilot（廉価モデル併用の無人運用）

プロンプト資産は `assets/prompts/`（**Fable 5 作成済み。実装・運用時に書き直さずそのまま使う**）。
設計は [`docs/superpowers/specs/2026-07-10-llm-copilot-design.md`](docs/superpowers/specs/2026-07-10-llm-copilot-design.md)。

- **監視・復旧スーパーバイザー**: このリポジトリで Claude Code セッションを開き（Haiku/Sonnet で足りる）
  `assets/prompts/supervisor_loop.md を読み、その指示に従って /loop で監視して` と指示する
  （自己ペース /loop、目安 20 分間隔）。正常周回中は何もしないのが規律。
  `nohup tools/ops/supervise_autolive.sh <target_epoch> &` と併用可。
- **イベント導線ナビ**: ホーム画面にあるとき
  `assets/prompts/event_navigation.md を読み、ホームからイベントライブ開始まで進めて` と指示する。
  ライブが始まったら `python tools/autolive.py --loops N --flick` を起動。
- 認証: `ANTHROPIC_API_KEY` または `ant auth login`。API/LLM が落ちても従来の安全停止に
  劣化するだけで、周回の安全性は LLM に依存しない設計を維持すること。
```

- [ ] **Step 3: 行数とリンクを確認する**

```bash
wc -l CLAUDE.md
.venv/bin/python -m unittest tests.test_docs_links -v 2>&1 | tail -10
```

期待: 90 行前後（148 行から縮小）。`test_relative_links_resolve` が PASS。

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md
git commit -q -F - <<'EOF'
docs: CLAUDE.md を入口＋絶対規則に縮約

アーキテクチャ詳細・端末非依存の実装方針・テンプレ取得手順は docs/ へ
移したので、CLAUDE.md は「最初に読む1枚」に徹する。守らないと課金事故や
無意味な周回になる8項目を絶対規則として先頭に集約した。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 10: 最終検証

設計書 §5 の検証項目5つをすべて実行し、結果を記録する。

**Files:**
- 変更なし（検証のみ）

**Interfaces:**
- Consumes: Task 1-9 のすべて
- Produces: なし

- [ ] **Step 1: 検証項目1 — テストが全件通る**

```bash
cd /Users/yo4raw/git/i7_autoplay
.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -15
```

期待: `OK`。既存4テスト（note_engine / type_forecast / autocal / corpus_smoke）＋
新規2ファイル（repo_layout / docs_links）が実行される。

- [ ] **Step 2: 検証項目2 — 移動した20本がすべて有効**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestScriptsAreValid \
                             tests.test_repo_layout.TestOpsPathResolution -v 2>&1 | tail -10
```

期待: PASS。`py_compile` が全 Python を通し、`zsh -n` が全シェルを通し、
`reconnect_watcher.RETRY_TMPL` / `unlock_watcher.TMPL` / `recover_freeze.SCREENS` /
`recover_freeze.TEMPLATES` がすべて実在するパスを指す。

- [ ] **Step 3: 検証項目3 — 旧パス参照の残存ゼロ**

```bash
.venv/bin/python -m unittest tests.test_repo_layout.TestNoStaleToolPaths -v 2>&1 | tail -10
```

期待: PASS。

- [ ] **Step 4: 検証項目4 — 未追跡ファイルゼロ**

```bash
git status --porcelain
```

期待: 出力が空。

- [ ] **Step 5: 検証項目5 — 本番3ファイルが無変更**

```bash
git diff main --stat -- tools/autolive.py tools/driver.py tools/note_engine.py
```

期待: 出力が空。**1バイトでも差分が出たら段階1の前提が崩れているので、原因を突き止めて戻す。**

- [ ] **Step 6: 変更全体を俯瞰する**

```bash
git diff main --stat | tail -5
git log main..HEAD --oneline
```

期待: 11 コミット（設計書 + 本計画書 + Task 1-9 の9本）。stat のファイル数は 45 前後
（`tests/corpus_raw/` 507枚は `.gitignore` で除外されているため）。

- [ ] **Step 7: PR を作る**

```bash
git push -u origin chore/project-cleanup
gh pr create --title "chore: プロジェクト整理（段階1: 棚卸し＋ドキュメント再編）" --body "$(cat <<'EOF'
## 概要

設計書 `docs/superpowers/specs/2026-07-30-project-cleanup-design.md` の段階1。
**周回の振る舞いは一切変えていない**（`autolive.py` / `driver.py` / `note_engine.py` の diff は空）。

## 変更

- **未追跡20ファイルを取り込み**。`CLAUDE.md` が起動を指示していた `supervise_autolive.sh` が
  未追跡で、clone した環境には存在しなかった。実フレームコーパス（14状態・507枚・69MB）は
  サイズが大きいので `.gitignore` で除外し、採取手順を `docs/README.md` に明記した。
- **`tools/` を3分類**。本番3（直下）/ 運用8（`ops/`）/ 調査12（`probes/`）。
  移動で壊れる相対パス解決（`sys.path`・`ROOT`・シェルの `cd`）を修正。
- **`docs/specification.md` 1,056行を実態中心の6ファイルへ再編**。未実装の当初設計
  （OCR・設定ファイル・CLI 仕様）は `docs/archive/` へ。
- **新知見の記録**: 再接続後の PAUSE 再燃を再現し、`iohid_click` も無効と確定（40秒で8回）。
  イベント「BUDDY Night NARRATIVE」の導線座標。難易度タブの LIFE 表示はブースト3倍込みの実消費値。
- **回帰テスト2本を新設**（実機不要）。`tests/test_repo_layout.py` が構成・構文・パス解決・
  旧パス残存を、`tests/test_docs_links.py` がリンク切れを検証する。

## 検証

- [ ] `.venv/bin/python -m unittest discover -s tests` が `OK`
- [ ] `git diff main -- tools/autolive.py tools/driver.py tools/note_engine.py` が空
- [ ] `git status --porcelain` が空

## 次

- 段階2: `autolive.py` 1,305行の分割（corpus を使った `detect()` 回帰テストの整備が前提）
- 段階3: 運用ウォッチャ7本の統合

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
