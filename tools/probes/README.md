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
