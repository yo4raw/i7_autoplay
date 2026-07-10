# LLM copilot プロンプト資産

Fable 5 が事前作成した、廉価モデル（Haiku 4.5 / Sonnet 5）用のプロンプト一式。
仕様書 §17 と運用メモリのドメイン知識を蒸留してあるため、**実装時に書き直さず
そのまま読み込んで使う**こと。設計書: `docs/superpowers/specs/2026-07-10-llm-copilot-design.md`

## ファイル対応表

| Phase | 用途 | system プロンプト | 出力スキーマ | 呼び出しモデル |
|---|---|---|---|---|
| 1 | 未知画面の分類と安全操作の選択 | `screen_triage.system.md` | `screen_triage.schema.json` | `claude-haiku-4-5` |
| 2 | リザルト画面のOCR | `result_ocr.system.md` | `result_ocr.schema.json` | `claude-haiku-4-5` |
| 3 | 無人運用スーパーバイザー | `supervisor_loop.md`（Claude Code /loop への指示書。API system プロンプトではない） | — | セッション（Haiku/Sonnet） |
| 4 | イベント導線ナビ | `event_navigation.md`（同上・指示書） | — | セッション（Sonnet 5 推奨） |
| 4 | ナビ中の画面確認 | `nav_verify.system.md` | `nav_verify.schema.json` | `claude-haiku-4-5` |

`*.system.md` はファイル全体をそのまま `system` に渡す。`*.schema.json` はそのまま
`output_config.format.schema` に渡す（構造化出力の制約に適合済み:
`additionalProperties: false`・全プロパティ required・数値制約なし）。

## API 呼び出しテンプレート（Python / anthropic SDK）

```python
import base64
import json
import pathlib

import anthropic

PROMPT_DIR = pathlib.Path(__file__).parent.parent / "assets" / "prompts"
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY か `ant auth login` プロファイル

def triage_screen(png_path: str, context_text: str) -> dict:
    """未知画面を Haiku に判断させる（Phase 1）。戻り値はスキーマ準拠 dict。"""
    system = (PROMPT_DIR / "screen_triage.system.md").read_text()
    schema = json.loads((PROMPT_DIR / "screen_triage.schema.json").read_text())
    img = base64.standard_b64encode(pathlib.Path(png_path).read_bytes()).decode()
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png", "data": img}},
                {"type": "text", "text": context_text},
            ],
        }],
    )
    if resp.stop_reason == "refusal":       # まれ。安全停止に劣化
        return {"action": {"type": "stop_and_notify", "label": None, "x": None,
                           "y": None, "reason": "refusal"}}
    return json.loads(next(b.text for b in resp.content if b.type == "text"))
```

`context_text` の例（screen_triage）:
```
直近のFSM状態履歴: gameplay → eventresult → (不明)
この画面での試行回数: 1回目（前回の操作: なし）
```

## モデル別の注意（間違えると 400 エラー）

- **Haiku 4.5** (`claude-haiku-4-5`, $1/$5 per MTok, 200Kコンテキスト):
  - `output_config.effort` を**送らない**（Haiku 4.5 では未対応でエラー）。
  - thinking は使わない（この用途では不要。レイテンシ増になるだけ）。
  - vision 対応。SE ウィンドウ（529×334）のスクショはそのまま送ってよい（≈1,000〜1,500 tok）。
- **Sonnet 5** (`claude-sonnet-5`, $3/$15。2026-08-31 までは $2/$10):
  - `temperature` / `top_p` / `top_k` を**送らない**（非デフォルト値は 400）。
  - `thinking` を省略すると adaptive が既定でONになる（それでよい）。
  - 導線計画など「考える」タスク向け。1ショット判定は Haiku で足りる。
- 共通: 構造化出力を使うので応答は必ずスキーマ準拠 JSON。それでも
  `stop_reason == "refusal"`（まれ）と API 例外（タイムアウト/レート制限）は握って
  **安全停止に劣化**させること（周回の安全性を LLM 可用性に依存させない）。

## コード側で必ず実装する検証（プロンプトを信用しない多重防御）

`screen_triage` / `nav_verify` の応答を実行する前に:

1. `action.type == "tap"` のとき、`label` と `reason` に禁止語
   （`ステラ`, `購入`, `ショップ`, `チャージ`, `パス`）が含まれたら**実行拒否**して安全停止。
2. `stella_risk == true` のとき、許可する操作は `close_x` / `stop_and_notify` のみ。
3. 座標は 0..1 範囲チェック。範囲外は拒否。
4. 同一画面（`screen_id` が同じ）での試行は3回まで。超えたら従来の安全停止→通知。
5. `confidence < 0.5` の tap は実行せず `stop_and_notify` 扱い。

## コスト見積り

Haiku 1判断 ≈ 2K in + 0.3K out ≈ **$0.003〜0.005**。未知画面・リザルト時のみの
イベント駆動なら一晩数円〜数十円。5分間隔のスクショ付き監視を足しても一晩 $1 未満。
system プロンプトに `cache_control` を付けてあるが、Haiku 4.5 の最小キャッシュ長は
4096 トークンのため短いプロンプトではキャッシュされないことがある（コスト影響は軽微）。
