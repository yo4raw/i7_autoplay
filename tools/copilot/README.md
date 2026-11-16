# tools/copilot — pi-durable LLM コパイロット

`assets/prompts/supervisor_loop.md`（Claude Code `/loop` で動かす監視プロンプト）を
[pi-durable](https://github.com/earendil-works/pi)（`@earendil-works/pi-durable`）で実装した
**クラッシュ再開可能な監視エージェント**。周回そのもの（`tools/autolive.py`）は従来どおり
Python が行い、こちらは外側の見張りだけを担う。

## 構成

| ファイル | 役割 |
|---|---|
| `src/supervisor.mjs` | エントリポイント。`watch`（常駐監視）と `once`（1サイクル確認）の2モード |
| `bin/watch.sh` | `supervise_autolive.sh` と並走させる常駐ラッパー |
| `bin/once.sh` | 1サイクルだけ実行して終了（動作確認用） |
| `data/copilot.sqlite` | pi-durable の SQLite ストレージ（会話・タスク状態。`.gitignore` 済み） |
| `data/copilot.log.jsonl` | サイクルごとの報告ログ（1行JSON） |

プロンプトは `assets/prompts/pi_durable_copilot.md`（`supervisor_loop.md` の移植。
判断表は同一）。モデルは `ANTHROPIC_API_KEY` 環境変数で `anthropic/*` を使う。
既定は `claude-sonnet-4-6`、`I7_COPILOT_MODEL` で変更可。

## 動作モデル

- **durable task `i7.supervise`** が `wait → cycle → sleep → cycle …` を回す。
  各サイクルで会話に1入力を submit し、モデルが `check_status` 等のツールを呼んで
  判断・必要なら介入し、1行の状態報告を返す。報告はタスクの `SupervisorControl`
  ドキュメントに保存され、コンソールに `[copilot] cycle N:` で出る。
- プロセスが落ちても SQLite にコミット済みの状態から再開する。`watch` を再実行すれば
  既存タスクを見つけて続きを回す（`requestId` で二重 submit しない）。
- 介入系ツールは `open_mirroring`（ScreenContinuity 起動）と
  `restart_supervisor`（`supervise_autolive.sh` 再始動）のみ。それ以外の副作用操作は
  `run_command` の許可リストで拒否する。
- `end_session` または目標時刻（`--target`）超過でタスクは terminal になり `watch` が終了する。

## 使い方

```bash
cd tools/copilot && npm install

# 常駐監視（supervise_autolive.sh と併走。target_epoch は周回の終了時刻）
tools/copilot/bin/watch.sh $(( $(date +%s) + 7200 )) 600 anthropic/claude-sonnet-4-6

# 1サイクルだけ確認（APIキー必要）
tools/copilot/bin/once.sh anthropic/claude-sonnet-4-5

# APIキーなしのオフライン疎通（faux プロバイダ）
tools/copilot/bin/once.sh --faux
node src/supervisor.mjs watch --target $(( $(date +%s) + 3600 )) --faux --first-delay 3000 --db /tmp/copilot-faux.sqlite
```

注意: pi-durable は experimental で API が破壊的変更されうる。`@earendil-works/*` は
`^1.5.2` に固定してあり、アップグレード時は `data/copilot.sqlite` のマイグレーションに注意。

## 周回側との関係

- copilot は `pgrep`/`tail`/`driver.py info`/`open -b`/`nohup supervise_autolive.sh` しか
  触らない。**ライブ中のタップ・クリック・Mac 入力には一切関与しない**ので、
  PAUSE を誘発する副作用は従来の Claude Code /loop と同じ範囲に留まる。
- 判断に迷う症状は `end_session` で人間に委ねる設計（`supervisor_loop.md` の
  「安全側＝停止して人間に通知」を踏襲）。
