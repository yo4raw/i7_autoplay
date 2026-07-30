# 実機知見

## PAUSE の解決策（2026-06-05）

[navigation.md](navigation.md)「(E) ゲームプレイ中の自動 PAUSE は intrinsic（最重要・実験で確定）」で「Mac 側の合成入力では PAUSE を防げない」としたが、**原因と解決策を特定した**。

**原因**: iPhone ミラーリングは「**genuine な HID 入力**」が数秒ないと iOS アプリをアイドル化し
PAUSE させる。通常の `CGEventCreateMouseEvent(None, ...)`（イベントソース=None）で送る合成
クリックは、ゲームには届く（タップは効く）が、ミラーリングのアイドル判定をリセットしない。

**解決策（実装済み, `autolive.py` `_click_screen`）**: クリックを以下の形で送る。
1. `CGEventSourceCreate(kCGEventSourceStateHIDSystemState)` で**イベントソースを作成**。
2. 各クリックで **`CGWarpMouseCursorPosition` で実カーソルをクリック点へ移動** →
   `MouseMoved` → `LeftMouseDown` → `LeftMouseUp` を、上記ソース付きで `kCGHIDEventTap` に Post。
3. 補助として `caffeinate -dimsu` を実行中だけ起動（アイドル/スリープ/表示消灯の抑止）。

**検証（実機・切り分け）**:
- 通常合成クリック(None): 30秒で PAUSE 約6回（baseline）。
- caffeinate のみ / 実カーソル移動のみ: 効果なし（各 7〜9回）。
- **HIDSystemState ソース + 実カーソルワープ + caffeinate: 30秒で PAUSE 0回**。
- これを autolive に実装して周回: **PAUSE 0 のまま 1ライブ≈115秒で完走→クリア計上→
  きなこパン自動回復（ステラ不使用）→次ライブ、を無人で確認**（pauses=0, clears 加算, life 加算）。

**副作用と注意**:
- **実マウスカーソルがクリック点へ次々ワープする**（ユーザーのカーソルと競合する）。実行中は
  Mac のマウス操作を控えること。これは genuine 入力として認識させるための必須挙動。
- ゲームが連続再生されるため**タップ円が実際にノーツに当たる**ようになり、GRADE/スコアが
  上がる（全ミスではなくなる＝コンボ・スコア課題にも寄与）。
- メニュー画面でもカーソルがワープするが無害。`--dry-run` 時はクリックしない（ワープも無し）。

## PAUSE 多発の真因と修正（2026-06-07）

**症状（修正前）**: ライブ中に約4.5秒ごとに PAUSE↔再開を繰り返し、ノーツが再開カウントダウンで
流れて全 MISS・クリア0 になっていた。

**真因**: autolive の `_keep_front()` が **0.4秒ごとに無条件で `driver.activate_fast()`
（= iPhone ミラーリングアプリの再アクティブ化）を呼んでいた**こと。**既に最前面のアプリを
再アクティブ化すると、その都度ミラー中の iOS アプリが resignActive→becomeActive 相当となり、
ゲームが PAUSE メニューを出す**。`_keep_front` はもともと「ミラーリングを最前面に保ち合成クリックを
届かせる」ための補助だったが、最前面のまま呼び続けたことが裏目に出ていた。

**修正（実装済み）**: `_keep_front` を **「最前面でない時だけ activate する」** に変更
（`_mirror_is_front()` を `NSWorkspace.frontmostApplication` で判定）。ライブ中はミラーリングが
最前面のままなので再アクティブ化が起きず、PAUSE しなくなる。最前面を失った時だけ復帰させる。

**検証**: iPhone SE で **PAUSE 1回 / 120秒・★ライブクリア確認**（修正前は ≈30回/120秒・0クリア）。
合成クリック（HIDソース+ワープ, 本書「PAUSE の解決策（2026-06-05）」の `_click_screen`）はそのままで問題なく打鍵・クリアできる。

**切り分けで確認した事実（再発時の参考）**:
- **完全ゼロ入力なら PAUSE しない**（`tools/probes/pure_observe.py`）。検出する "pause" は本物の PAUSE メニュー
  （誤検出ではない。pause_score≈1.0, 明るさ≈74）。
- `driver.activate()`（ミラーリング再アクティブ化）は単発でも PAUSE を誘発する。
- 本物のトラックパッドタップは PAUSE しない。本物タップは CGEvent 上 `subtype=3`(NX_SUBTYPE_MOUSE_TOUCH)・
  `src_pid=0`(実機由来)、合成は `src_pid` が投稿プロセスPIDになる（偽装不可）が、**これは主因ではなかった**
  （activate を連打しなければ合成クリックでもクリアできる）。
- ※調査途中に立てた「HIDIdleTime 要求／合成入力フィルタ／端末依存／要ハード・仮想HID」などの仮説は
  すべて**誤り**だった（真因は上記 activate 連打）。

**再発時の確認**: ライブ中に再び PAUSE 多発したら、まず `_keep_front` が無条件 activate に戻っていないか、
他アプリが頻繁に最前面を奪っていないかを確認する。

**検証/調査用ツール（任意）**: `tools/probes/pure_observe.py`(ゼロ入力観測), `tools/probes/trigger_test.py`(操作種別の
切り分け), `tools/probes/capture_click.py`(本物/合成のイベント属性比較), `tools/probes/idlekeeper.py`(IOHIDPostEvent),
`tools/probes/pause_ab.sh`。`autolive.py` の `_click_screen` 冒頭に実験用 `I7_CLICK_MODE` 環境変数ディスパッチが
あるが、**未設定なら通常動作**（本番運用では設定しない）。

## 画面構造・ノーツ仕様・画面遷移（2026-06-07）

**ライブのノーツ機構（放射型）**: ノーツは**画面中央でスポーンし、4つの判定円（左上/左下/右上/右下）へ
放射状に飛ぶ**。中央=白い球で出現→飛行→判定円で命中。
- **色は飛行中なら判別可能**（拡大で赤ノーツは明確に赤く光る）。**判定円（到達点）では白飛びして色判別不可**。
  → 種別/色の判定は「飛行中に色検出＋追跡」（= `note_engine.py` の track エンジン方式）が必要で、
  現行 timing エンジンの到達点ROIだけでは色を取れない（だから現行は全部タップ＝部分点）。
- 現行 timing エンジンは各円ROIの白割合スパイクでタップ。`--holds` で明るさ持続=長押しを近似可能
  （色非依存）。

**ノーツ種別と必要操作（ユーザー仕様。チェーン構造）**:
- 🔴 **赤**: タップ→フリック（方向不問）。
- 🟢 **緑**: 長押し開始。**次のノーツまで保持**し、その終端ノーツの種別で離し方が決まる
  （次が緑→そのまま/次が赤→フリックで離す 等）。
- 🔵 **青**: スライドしながら長押し。**次の青ノーツまで**保持して離す。
- ＝緑/青は単発でなく「次のノーツへ繋がるチェーン」。終端ノーツ種別でジェスチャが変わる。
- 未対応だと フリック/スライド/ロングは頭だけ＝部分点 or MISS になる（精度が頭打ち）。

**リザルト画面（精度の読取り）**: per-song Result に `PERFECT / GOOD / BAD / MISS`・`COMBO`・`SCORE`・
グレード(S/SS等) が出る。**ベースライン実測（SE・PAUSE修正後）: PERFECT 59 / GOOD 15 / BAD 3 /
MISS 45 / SCORE 124,172 / SS**。MISS が多く、種別対応（特に hold/flick/slide）と timing 調整が削減課題。

**画面遷移（無人周回で観測した実機フロー）**: ライブ→（per-song）Result→（カード型ポップアップを
背景タップで閉じる）→ EVENT RESULT「申請する」（フレンド申請）→ 連続ライブ再プレイ確認「はい」→
（DLダイアログ/ストーリー遷移ダイアログがあれば処理）→ 次ライブ。LIFE不足時はきなこパンで回復
（ステラ厳禁）。再開/開始時は「3・2・1」カウントダウン（暗い=gameplay 扱い）。

**ミラーリングウィンドウ実測サイズ**: iPhone SE ≈ 529×334(スケール2.0, ≈16:9・レターボックス有)、
iPhone 16 ≈ 671×348(≈19.5:9・全画面)。座標は内容矩形相対＋テンプレ機種別variantで吸収。

## 再接続後の PAUSE 再燃（2026-06-08）

**症状**: 夜間に iPhone ミラーリングが切断（「iPhoneが使用されました」等）→朝に再接続した後、
本書「PAUSE 多発の真因と修正（2026-06-07）」の修正（`_keep_front` 条件付き activate）が入っているにもかかわらず、ライブ中に
**約5秒ごとに PAUSE↔再開**が再燃。全 MISS・実質クリア進まず。

**重要: 本書「PAUSE 多発の真因と修正（2026-06-07）」の真因（activate 連打）とは別物**。今回は activate していない（`_mirror_is_front()`=True を確認、
`_keep_front` は発火していない）のに PAUSE する。**この再接続セッションでは、あらゆる合成入力が
ミラーリングの「genuine 入力」アイドル判定をリセットしない**のが原因。

**切り分けで潰した仮説（すべて×＝原因でない）**:
- 低電力モード（ユーザーが OFF を確認後も PAUSE）。
- Mac 側権限/再起動: **同一 Mac 起動セッション**（昨夜の成功〜今朝の失敗で再起動なし、uptime で確認）。
  画面収録/アクセシビリティは不変。ホストは VS Code。
- **入力方式を総当たりしても全滅**（`tools/probes/trigger_test.py` で gap0.4〜0.5s・--resume、各〜5秒ごとに PAUSE）:
  `tap`(autolive実体=warp+HID move/down/up)・`touchclick`(本物タップ属性 subtype=3/src_pid=0/pressure/eventNumber 偽装)・
  `realclick`(押下時間あり)・`iohid_move`(IOHIDPostEvent=HID層注入)。UI クリックは効く（カード閉じ/START 等は反応）
  のに、gameplay の PAUSE アイドルだけはどれもリセットできない。
- **iPhone ミラーリングのクリーン再起動でも×**（`osascript -e 'quit app "iPhone Mirroring"'`→
  `open -b com.apple.ScreenContinuity`。認証不要で再接続したが PAUSE 継続）。
- **activate/フォーカス喪失でもない（本書「PAUSE 多発の真因と修正（2026-06-07）」とは別物だと計測で確定）**: PAUSE 検出時に最前面アプリを
  ログしたところ **15回中15回 front=iPhoneミラーリング**。つまりミラーリングは最前面のままで
  `_keep_front` の activate は一度も発火していない。私(assistant)が監視 Bash を一切打たない
  「完全放置」でも約4.5秒周期で PAUSE（29回/150秒）。周期が iOS アイドルタイムアウト一定値で
  揃う＝ランダムなフォーカス奪取ではなく**アイドル判定が合成入力を genuine と数えていない**こと。
  （切り分けツール: `tools/probes/focus_probe.py` = 最前面とpause状態の時系列観測）。

**結論**: 残る変数は **iPhone 本体側の状態**のみ。再接続でミラーリングの HID/Continuity 入力チャネルが
「合成入力を genuine と見なさない」状態に落ちたと考えられる。**復旧には iPhone 本体の電源再投入
（リスタート）が最有力**。Mac 側ソフトの打ち手は出尽くした。

**昨夜なぜ動いていたか**は未解明（同一コード・同一 Mac 起動で、切断前は本書「PAUSE の解決策（2026-06-05）」の合成入力で PAUSE 0、
切断後は全滅）。再接続セッションの個体差/iPhone 状態依存の可能性。**再発時はまず iPhone を再起動**し、
ダメなら本セクションの総当たり結果を踏まえ Mac 側ではなく iPhone/ミラーリング側を疑うこと。

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

## ハイブリッド打鍵方式（2026-07-10）

設計書: `docs/superpowers/specs/2026-07-10-live-engine-hybrid-design.md`（承認済み・案B）。
打鍵の「いつ」は実績ある roi スパイク検出（[architecture.md](architecture.md) §17.5, lead=0.025 較正済み）を温存し、
「なに」を `note_engine` の track（スポーン検出→追跡→色種別/レーン/ETA 推定）で先読みする。
**両フラグとも既定OFF**で、OFF時のコードパスは従来と同一（無回帰）。

- **`--predict`（種別先読み）**: `Tracker`＋`TypeForecast`（レーン別予報）を roi と同じ
  フレームで並走させ、roi 発火時に種別で出し分ける。
  - 赤 → フリック（`_flick`。`--flick` の到達直前検色と OR）
  - 緑 → **次の緑まで長押し**（本書「画面構造・ノーツ仕様・画面遷移（2026-06-07）」のチェーン仕様）。解除は保持中の輝度でなく
    **対の緑の ETA 予測時刻**（旧 `--holds` がタップ波紋と交絡した失敗要因を回避）。
    上限 `HOLD_MAX_SEC` で必ず離す。単一カーソル制約によりホールド中は他レーンを
    叩けない（EASY では並行ノーツは稀・チェーン尻尾の MISS 削減の利得が勝る想定）
  - 青/白/予報なし/予報が古い → 通常タップ（現行動作）
  - 予報は eta_at+猶予0.35s で破棄（追跡帯 `FIELD_Y1`=0.62 を抜けた後の到達待ちに対応）。
    track の例外・欠落は全て通常タップに劣化し周回は止めない（フェイルソフト）
- **`--auto-circles`（機種非依存化）**: ライブ突入時に下帯（content y≥0.50）の円リングを
  `HoughCircles` で検出し、prior（現行 `CIRCLES`）と**4円すべて**が許容誤差
  （content相対 0.06）内で一致したときだけ実測値へ in-place 置換。失敗時は現行値を維持し
  次のライブ突入時に再試行（SE実フレーム78枚の実測で単発フルマッチ率 86%）。
  精度不良の主因＝CIRCLES ズレ（改訂 0.10）への恒久対策。
  オフライン確認: `python tools/note_engine.py circles <frame.png> [out.png]`
- **テスト**: `tests/`（unittest, 実機不要の合成フレーム）＋実フレームコーパス
  `tests/corpus_raw/`（未コミット・あればスモーク）。実行:
  `.venv/bin/python -m unittest discover -s tests`
- **実機検証手順**（マージ前に実施。設計書 §8）: ①フラグなしで無回帰確認 →
  ②`note_engine.py live 120` で予報精度観測（読み取り専用）→ ③`--predict` でリザルト比較 →
  ④`--auto-circles` の補正ログ確認 → ⑤supervisor へ反映

