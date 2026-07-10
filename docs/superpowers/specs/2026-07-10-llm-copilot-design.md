# LLM copilot 設計書: 廉価モデル（Haiku/Sonnet）による画面判断・監視・ナビゲーション

日付: 2026-07-10 / 承認済みアーキテクチャ: 案C（二層構成）

## 1. 目的

テンプレ・固定座標では追いきれない「画面の意味理解」が必要な場面に廉価な Claude モデルを
組み込み、(1) 未知画面での停止をなくす（自己修復）、(2) 監視・復旧を知能化、
(3) リザルトを自動記録、(4) 起動から完全自動化、を実現する。

**前提と制約**:
- ライブ中のノーツ打鍵は対象外（LLM は vision 込みで1判断 1〜3秒。ミリ秒精度の打鍵は
  現行CVエンジンのまま）。LLM は FSM の「上」に座る。
- モデルは廉価枠: 画面判断・OCR = **Haiku 4.5** (`claude-haiku-4-5`, $1/$5 per MTok)、
  導線計画・複雑な判断 = **Sonnet 5** (`claude-sonnet-5`, $3/$15)。
- **プロンプトは Fable 5 が事前作成済み**（`assets/prompts/`）。実装時はこれを読み込んで使う。
  Fable の知見（仕様書§17・運用メモリ）を蒸留してあるため、実装側で書き直さないこと。

## 2. アーキテクチャ（案C: 二層構成）

- **内側 = copilot モジュール（Haiku 4.5 を API 直呼び）**: 「この画面は何か・どこを押すか」の
  1ショット判断とリザルトOCR。autolive から関数呼び出し。速い・安い・確実。
- **外側 = Claude Code /loop セッション（Haiku/Sonnet）**: プロセス管理・状況別復旧・
  イベント導線ナビ・人間への通知。エージェント的判断が必要な低頻度の仕事。

## 3. 安全設計（ステラ安全の維持 — 絶対要件）

LLM に自由クリックはさせない。多重防御:

1. **構造化出力の強制**: `output_config.format`（json_schema, `additionalProperties: false`）で
   アクションを列挙型に制限（`tap` / `close_x` / `wait` / `stop_and_notify` のみ）。
2. **プロンプトでの禁止**: ステラ（有償通貨）・購入・ショップに関わる操作の絶対禁止を明記。
3. **コード側の検証（LLM を信用しない）**: `tap` のラベル・reason に禁止語
   （ステラ/購入/ショップ/チャージ等）が含まれたら実行拒否。`stella_risk=true` の画面では
   `close_x`/`stop_and_notify` 以外を拒否。1画面あたりの試行回数上限（3回）を超えたら
   従来どおり安全停止→通知。
4. LIFE 回復はきなこパンのみ（既存コードの `lifeshort` ハンドラが処理。copilot は分類して
   返すだけで回復操作はしない）。

## 4. フェーズ分割（各フェーズ = 独立PR）

| Phase | 内容 | プロンプト資産 |
|---|---|---|
| 1 | 未知画面対処＋テンプレ自動収穫: `menu` 安全停止の手前で copilot に照会→許可リスト操作で続行→`template_hint` から変種テンプレを保存し自己修復 | `screen_triage.*` |
| 2 | リザルトOCR: 周回ごとに SCORE/MISS/BAD 等を `/tmp/i7_results.jsonl` に記録 | `result_ocr.*` |
| 3 | 監視・復旧の知能化: supervisor を Claude Code /loop 化（切断→再接続、§17.10→iPhone再起動要請の通知、原因別ログ） | `supervisor_loop.md` |
| 4 | 起動から完全自動: ホーム→イベントリボン→EASY→ブースト3倍→START を vision 確認しながらナビ | `event_navigation.md` + `nav_verify.*` |

## 5. プロンプト資産の構成（`assets/prompts/`）

- `*.system.md` = API の system プロンプト本文（ファイル全体をそのまま渡す）
- `*.schema.json` = 対になる構造化出力スキーマ（`output_config.format.schema` にそのまま渡す）
- `supervisor_loop.md` / `event_navigation.md` = Claude Code セッション（/loop 等）への指示書
- `README.md` = API 呼び出しパラメータ（モデルID・vision・構造化出力・注意点）とコスト見積り

## 6. コスト見積り

スクショ1枚（SE窓 529×334）≈ 1,000〜1,500 トークン。Haiku で1判断 ≈ $0.003。
Phase 1-2 はイベント駆動（未知画面・リザルト時のみ）で一晩数円〜数十円。
Phase 3 の定期監視（5分間隔・スクショ付き）を足しても一晩 $1 未満。

## 7. 実装時の注意（API仕様。詳細は assets/prompts/README.md）

- Haiku 4.5 に `output_config.effort` を送らない（エラーになる）。`temperature` 等も送らない。
- Sonnet 5 は adaptive thinking が既定ON・サンプリングパラメータは 400。
- 構造化出力スキーマは `additionalProperties: false`・全プロパティ required が必須。
- 認証は `ANTHROPIC_API_KEY` または `ant auth login` プロファイル。

## 8. スコープ外

- ノーツ打鍵の LLM 化（レイテンシ的に不可能）
- copilot 障害時のフォールバック変更（API 不達なら従来どおり安全停止するだけ。周回の
  安全性は LLM に依存しない）
