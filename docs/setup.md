# セットアップ

## 2. 前提条件・動作環境

### 2.1 ハードウェア
- Mac 本体（Apple Silicon / Intel いずれも可）
- iPhone 実機（IDOLiSH7 インストール済み、Mac と同一 Apple ID・近接・Bluetooth/Wi‑Fi 有効）

### 2.2 ソフトウェア
- **macOS Sequoia 15.0 以上**（iPhone ミラーリング機能が利用可能なこと）
- **iPhone ミラーリング** アプリ（接続確立済み・実行中・前面表示可能なこと）
- **Python 3.11 以上**

### 2.3 主要依存ライブラリ（詳細は「14.1 推奨ライブラリ」）
`opencv-python` / `numpy` / `Pillow` / `mss` / `pyobjc-framework-Quartz` /
`pyobjc-framework-AppKit` / `ocrmac`（Apple Vision OCR）/ `PyYAML` / `pydantic` /
`typer` / `pynput`

### 2.4 事前セットアップ（権限付与・接続）
本ツールは macOS の TCC 権限を **2つ** 必要とする。付与対象は **本ツールを起動するホスト
プロセス**（Terminal / iTerm / VS Code など）であり、スクリプトファイルではない点に注意。

1. **画面録画（Screen Recording）**: `システム設定 → プライバシーとセキュリティ → 画面収録`
   で実行ホストを許可。→ 画面キャプチャに必要。
2. **アクセシビリティ（Accessibility）**: `システム設定 → プライバシーとセキュリティ →
   アクセシビリティ` で実行ホストを許可。→ 他アプリへの合成クリック（CGEvent）に必要。

> 権限付与後は **実行ホストを再起動**（ターミナル等を開き直す）こと。
> macOS のアップデート後に権限が無効化され、**無言で失敗**することがある（`specification.md` 第16章）。

3. iPhone ミラーリングを起動して接続を確立し、IDOLiSH7 を起動した状態にしておく。

### 2.5 ディスプレイ・ウィンドウ固定（v1 の前提）
テンプレートマッチングは UI の表示サイズに依存するため、**テンプレ画像を取得したときと
同じウィンドウサイズ・ディスプレイ解像度・スケーリング** で運用すること。
v1 ではミラーリングウィンドウのサイズ固定を前提とし、起動時にサイズ不一致を検出した場合は
警告する（マルチスケール対応は将来拡張）。

---

## 14.1 推奨ライブラリ
| 用途 | ライブラリ | 理由 |
|------|-----------|------|
| テンプレマッチング | `opencv-python` | 標準・高速・決定的、テンプレ別閾値が可能 |
| 画像/配列 | `numpy`, `Pillow` | キャプチャ→配列、テンプレ入出力 |
| キャプチャ | `mss`（主） | 高速な領域取得、`CGWindowListCreateImage` 廃止の影響を受けない |
| キャプチャ（将来） | ScreenCaptureKit（pyobjc） | 遮蔽対応・低 CPU、同一 IF 裏で差替可能 |
| ウィンドウ列挙/入力 | `pyobjc-framework-Quartz` | `CGWindowListCopyWindowInfo`、CGEvent（精密な down/drag/up） |
| 最前面化 | `pyobjc-framework-AppKit` / AppleScript | `NSRunningApplication.activate` |
| OCR | `ocrmac`（Apple Vision, `jpn`） | macOS で日本語高精度・追加バイナリ不要 |
| 設定 | `PyYAML` + `pydantic` v2 | 人手編集 YAML ＋ スキーマ検証 |
| CLI | `typer` | サブコマンド・オプション |
| ログ | 標準 `logging` | stdout ＋ ローテーションファイル |
| キルスイッチ | `pynput` | グローバルホットキー（別スレッドでフラグのみ） |
