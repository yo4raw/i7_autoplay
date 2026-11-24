# tools/

| ディレクトリ | 中身 | いつ使うか |
|---|---|---|
| `tools/`（直下） | 本番7本 | 周回そのもの |
| `tools/ops/` | 無人運用ウォッチャ10本 | 長時間の自動周回を回し続けるとき |
| `tools/copilot/` | pi-durable 製 LLM 監視エージェント（Node.js） | 周回の外側を LLM に見張らせるとき。クラッシュ再開可能 |
| `tools/probes/` | 調査用ワンショット12本 | 過去の調査を再現・追試するとき |

## 本番

| ファイル | 役割 |
|---|---|
| `autolive.py` | 周回 FSM。capture → detect → act のメインループ。詳細は [`docs/architecture.md`](../docs/architecture.md) |
| `driver.py` | 低レベル I/O。ミラーリングウィンドウ検出・`mss` キャプチャ・`HIDSystemState` 合成クリック |
| `matching.py` | 画像認識プリミティブ。窓スケール追従・マルチスケール照合・背景透過補正つき輝度・カード×色検出 |
| `kinako.py` | LIFE 回復（きなこパン行・ステッパー・上限超過・回復カード）・コストバッジ・「オート ON」パネルの判定と OCR |
| `note_engine.py` | タップ円の自動キャリブレーション（`--auto-circles`）とノーツ追跡・種別予報 |
| `ocr.py` | Apple Vision OCR（`VNRecognizeTextRequest`）。未導入・利用不可環境では安全側に縮退 |
| `tap_jitter.py` | 打鍵着弾点の2段ガウスジッター（レーン別バイアス＋タップノイズ、上限半径棄却） |

**無人周回の入口は `tools/ops/run_until.sh`。** 楽曲選択画面から起動する手順・
起動前の確認項目は [`docs/README.md`](../docs/README.md)「周回開始コマンド」。
下の `autolive.py` 直叩きはデバッグ用。

```bash
# 周回（イベントライブ開始済み or 楽曲選択画面から。曲・難易度は既定で変更しない）
python tools/autolive.py --loops 50 --max-seconds 7200 --flick --auto-circles --green-hold

# 手動ナビゲーション・テンプレ取得（座標はウィンドウ相対 0..1）
python tools/driver.py info
python tools/driver.py shot out.png
python tools/driver.py click <xfrac> <yfrac>
```

**本番スクリプトを変更する前に [`docs/README.md`](../docs/README.md) を読むこと。** 実機でしか判明しない制約が多数あり、素直に見える変更が周回を止める。
