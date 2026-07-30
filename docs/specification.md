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
