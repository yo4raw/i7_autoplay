# tools/ops/ — 無人運用ウォッチャ

周回そのものではなく、周回を「回し続ける」ための外側の仕組み。人間（または supervisor LLM）が起動する。
運用手順は [`docs/operations.md`](../../docs/operations.md) を参照。

| ファイル | 役割 | 状態 |
|---|---|---|
| `run_until.sh` | 指定時刻まで周回を続ける最上位ラッパー。**ミラーリング切断中は supervisor を回さずに待つ**（切断中は26秒ごとに空回り再起動してしまうため）。長時間の無人運用はこれを使う | 現役 |
| `supervise_autolive.sh` | `autolive.py` がクラッシュ／サイレント死しても目標時刻まで自動再起動する。無人運用の標準入口 | 現役 |
| `freeze_sentinel.sh` | ログを監視し、ハング兆候（cardx 停滞・再起動ループ）を検知したら `recover_freeze.py` で復旧して supervisor を再開 | 現役 |
| `recover_freeze.py` | 「ライフを全回復しました。」フリーズからの自動復旧。強制終了 → 再起動 → 楽曲選択まで復帰 | 現役 |
| `pause_guard.sh` | 直近60秒の PAUSE が閾値を超えたら周回を強制停止。再接続病（`docs/device-findings.md`）の夜間再発で LIFE を浪費しないための保険 | 現役 |
| `reconnect_watcher.py` | ミラーリング切断の「やり直す」ボタンをテンプレ照合で見つけた時だけ押す。再接続成功で exit 0 | 現役 |
| `unlock_watcher.py` | 「iPhoneのロックを解除してください」プロンプトの解消を待つ | 現役 |
| `morning_watcher.sh` | ユーザーが iPhone を触った／再起動した合図（ウィンドウ消失・ID 変化・暗転）を検知する。入力は一切送らない | 現役 |
| `result_log.py` | 周回と並走してリザルトの成績欄（PERFECT/GOOD/BAD/MISS・SCORE）を受動的に蓄積し、`montage` で1枚にまとめる。打鍵チューニングの効果は1ライブでは誤差に埋もれる（実測±5%）ため、分布で比較するための計測基盤 | 現役 |
| `corpus_collector.py` | 周回と並走して画面を受動採取し `tests/corpus_raw/<state>/` へ保存する。**コーパスは `.gitignore` 済み**なので、clone した環境ではこれで採り直す | 現役 |

```bash
# 無人運用の標準手順（target_epoch = 終了する UNIX 時刻）
nohup tools/ops/supervise_autolive.sh $(( $(date +%s) + 7200 )) > /dev/null 2>&1 &
nohup tools/ops/freeze_sentinel.sh   $(( $(date +%s) + 7200 )) > /dev/null 2>&1 &
```
