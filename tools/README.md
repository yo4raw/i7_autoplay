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
