#!/usr/bin/env python3
"""アイドリッシュセブン 累計イベント ライブ自動周回スクリプト。

iPhone ミラーリング経由で、イベントライブを自動で繰り返しクリアし続ける。

設計の要点（実機調査で判明。詳細は docs/architecture.md / docs/device-findings.md）:
- 画面取得は mss（フォーカスを奪わない）。screencapture -l は PAUSE を誘発するため不可。
- ライブ中の打鍵は2モード（--tap-mode, 既定 timing）:
  - timing: 各タップ円に明るいノーツが到達した瞬間を検出してタップ（_gameplay_timing）。
    円ごとのEMAベースライン比較＋デバウンス。取得+クリック遅延のため ROI を中心側へ早撃ち。
    ノーツ無し区間は _keepalive が genuine 入力を出し続け PAUSE を防ぐ。
    ※種別はタップ最適化。フリック/スライド/ロングは頭だけ取得＝部分点（スワイプ非対応）。
    しきい値は --calibrate / --note-* で実機調整可能（docs/architecture.md）。
  - rotate: 5円を約50Hzで巡回連打（フォールバック）。ライブはノーツ全見送りでも完走しRESULTに到達。
- ループは「ライブ → (per-song)Result → EVENT RESULT → 報酬ポップアップ×
  → 連続ライブ再プレイ『はい』 → 次のライブ」をテンプレ駆動で回す（ホーム不要）。
- 状態判定は「明るさゲート＋テンプレ照合」。判定順:
  pause → gameplay(暗) → lifeshort → friendreq → replay → rankup → closex
  → download → result → menu(未知)。

LIFE 回復（ユーザー要件）:
- LIFE 不足ダイアログでは **きなこパン（ライフ回復アイテム）でのみ回復**し、
  **ステラ（ステラストーン）は絶対に使わない**。きなこパン枯渇時はステラに頼らず停止する。

ステラ安全装置:
- 確認ボタンの盲目連打はしない。未知の明るいダイアログ／閉じられないポップアップは
  一定時間で停止＋スクショ（/tmp/i7dbg）。

ライブ中の自動PAUSE対策（解決済み・最重要。docs/device-findings.md）:
- iPhone ミラーリングは genuine な HID 入力が数秒ないと iOS アプリをアイドル化し PAUSE させる。
  通常の合成クリック(source=None)はゲームには効くがアイドル判定をリセットしない。
- 対策: **HIDSystemState のイベントソース**で **実カーソルをワープ + MouseMoved + Down/Up**
  を送る（`_click_screen`）。これで genuine 入力扱いになり PAUSE が起きない（実機で 0 PAUSE）。
  補助として実行中だけ `caffeinate -dimsu` を起動。
- 副作用: 実マウスカーソルがクリック点へワープするため、実行中は Mac のマウス操作を控えること。
- PAUSE を検出した場合は従来どおり即・再開（`P_RESUME`）するフォールバックも残してある。

停止（キルスイッチ）:
- **ESC キーを約1.2秒“長押し”すると停止**する（グローバル検出。フォーカス不問。
  esc_pressed/ESC_KEYCODE/ESC_HOLD_SEC）。グローバル検出ゆえ他アプリ向けの ESC タップを
  拾わないよう長押しにしている。`pkill -f autolive.py` でも停止可。

使い方:
    python tools/autolive.py --loops 50
    python tools/autolive.py --loops 50 --max-seconds 1800
    python tools/autolive.py --loops 3 --verbose
※ 事前に「画面収録」「アクセシビリティ」権限を実行ホストへ付与。iPhone ミラーリングで
  IDOLiSH7 を起動し、イベントライブを1回開始した状態（またはイベント楽曲選択以降）で実行。
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import numpy as np
import cv2
import Quartz

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import driver  # noqa: E402
import ocr  # noqa: E402
import tap_jitter as tap_jitter_module  # noqa: E402

# --- ライブ中の自動PAUSE対策（実機実験で確定。docs/device-findings.md） ---
# iPhone ミラーリングは「genuine な HID 入力」が一定時間ないと iOS アプリをアイドル化し
# ゲームを PAUSE させる。通常の合成クリック（source=None）はこの判定をリセットしないが、
# **HIDSystemState のイベントソース**で実カーソルを動かしながらクリックすると
# genuine な入力として扱われ、PAUSE が起きなくなる（実験で 0 PAUSE / 30s を確認）。
_HID_SRC = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

# --- キルスイッチ: ESC キー“長押し”で停止 ---
# esc_pressed() は **グローバル検出（フォーカス不問）** なので、エディタ/ターミナルで押した
# ESC まで拾ってしまう。作業中の何気ない ESC で周回が止まらないよう、**ESC を連続して
# ESC_HOLD_SEC 秒押し続けた**ときだけ停止する（短いタップでは止まらない）。
ESC_KEYCODE = 53  # macOS の Escape キーコード
ESC_HOLD_SEC = 1.2  # この秒数 ESC を押し続けたら停止（誤爆＝他アプリ向けESC対策）


def esc_pressed():
    """ESC キーが現在押されているか（グローバル。フォーカス不問）。"""
    return bool(Quartz.CGEventSourceKeyState(
        Quartz.kCGEventSourceStateCombinedSessionState, ESC_KEYCODE))

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "templates")

# --- ゲーム内容矩形“相対”の小数座標（タイトルバー無し時に校正） ---
# すべて「ゲーム内容矩形」相対の小数（content_to_screen で補正してクリック）
P_RESUME = (0.69, 0.76)          # PAUSE メニューの「再開」ボタン（右下・固定）
P_DOWNLOAD = (0.607, 0.779)      # データDLダイアログの「ダウンロード」ボタン（窓相対・実測）
P_REPLAY_YES = (0.621, 0.739)    # 連続ライブ再プレイ「はい」（右・ピンク）
P_RANKUP_X = (0.802, 0.251)      # RANK UP! ポップアップ右上の×（窓相対・実測）
# カード型ポップアップ（報酬獲得/獲得一覧/本日の課題/RANK UP/申請完了 等）の×候補位置（窓相対）。
# ポップアップごとに×位置が異なるため巡回クリックで確実に閉じる。closex テンプレの
# マッチ位置は不正確なことがあるので候補を優先する。
CLOSEX_CANDIDATES = [
    (0.802, 0.250),   # 大型カード（報酬獲得/獲得一覧/本日の課題/RANK UP）の×
    (0.735, 0.344),   # 中型カード（フレンド申請完了 等）の×
    (0.78, 0.41),     # LIFE回復確認など縦長カードの×
]
# Result/EVENT RESULT を送る位置。中央タップ（どちらの画面も「画面タップで進む」ため、
# 端のボタンを避けた中央が安全かつ確実）。下端 (0.5,0.93) は per-song Result では効かない。
P_RESULT_ADV = (0.50, 0.55)
# 連戦終了で楽曲選択へ戻ったときのライブ再開ナビ（窓相対・実測）。
P_NEXT = (0.86, 0.91)            # 楽曲選択の「NEXT」
P_FRIEND_FIRST = (0.40, 0.42)    # フレンド選択の先頭フレンド
P_STORY_NO = (0.39, 0.752)       # 「ストーリーに遷移しますか？」の「いいえ」（窓相対・実測）
P_START = (0.785, 0.888)         # 編成画面の「START」ボタン中心（窓相対・実測。右の MENU と混同しない）
# 楽曲選択画面の難易度タブ（左から EASY/NORMAL/HARD/EXPERT, LIFE 15/30/45/60）。
# **旧ユーザー要件（〜2026-10-19）: 必ず EASY で周回する**。既定経路では NEXT の前に EASY(緑・最左)タブを
# タップして固定する。**2026-10-20 から現行運用は `--keep-selection`**（人が選んだ難易度をそのまま継続。
# CLAUDE.md 絶対規則 2）で、その回は**このタブを一切タップしない**。
P_EASY_TAB = (0.644, 0.718)      # EASY タブ中心（窓相対・実測。緑タブ「EASY✦ LIFE 15」）
# 未知の明るい画面で“やむを得ず”触る安全位置（最下端マージン）。ダイアログのボタン帯
# (y≈0.74-0.88) や本文・×を避けるため、ボタンが置かれない最下端だけを軽く叩く。
P_MENU_SAFE = (0.50, 0.97)
# カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）を閉じる位置。これらは**×でなく
# 背景（暗転部）のどこをタップしても閉じる**（実機確認。×自体のクリックでは閉じない）。
# 中央のカードを外した位置を叩く。制約は2つ:
#   - **左下は不可**（カーソルが Dock／ホットコーナー付近へワープして危険。ユーザー指摘）
#   - **右上も不可**（2026-08-29 ユーザー指摘）。右上には BACK (約 0.906,0.185) と
#     **ステラ所持数の「＋」＝課金導線 (約 0.872,0.135)** が並ぶ。旧値 (0.86,0.16) は
#     671x348 で (577,56) となり、「＋」の実測 (585,47) と **x で 8px・y で 9px** しか
#     離れていなかった。カードを閉じるたびに課金導線の隣を叩いていたことになる。
# よって横位置はそのまま（中央のカードの外側）に、**縦だけ上部バーの帯より下げる**。
# カードは画面中央に出るので、縦を下げても「背景を叩く」性質は変わらない。
# 回帰テストは tests/test_card_dismiss_safety.py。
P_CARD_DISMISS = (0.86, 0.50)

# --- 端末非依存のクリック（中央アンカー方式） ---
# ダイアログ/ポップアップは画面中央に同pxサイズで出る（端末間でUIは同サイズ・実測で確認）。
# よって「ゲーム中央 + 固定pxオフセット」で押せば端末非依存になる。オフセットは SE 実測値。
# SE ゲーム中央 = (win中央x=264.5, 内容矩形中央y=(38+325)/2=181.5)。
SE_GAME_CENTER = (264.5, 181.5)
OFF_RESUME = (100.5, 72.5)        # PAUSE メニュー「再開」
OFF_REPLAY_YES = (64.5, 65.5)     # 連続ライブ再プレイ「はい」
OFF_DOWNLOAD = (56.5, 78.5)       # データDL「ダウンロード」
OFF_STORY_NO = (-58.5, 69.5)      # ストーリー遷移「いいえ」
OFF_RANKUP_X = (159.5, -97.5)     # RANK UP! ×（大型カード右上）
OFF_RESULT_ADV = (0.0, 2.0)       # Result/EVENT RESULT 中央送り
OFF_MENU_SAFE = (0.0, 142.5)      # 未知メニューの安全タップ（中央やや下）
# カード型ポップアップ（報酬獲得/獲得一覧/申請完了/本日の課題 等）の×候補（中央からのpxオフセット）。
# 大型/中型/縦長カードで×位置が異なるため巡回。
CLOSEX_OFFSETS = [(159.5, -97.5), (124.5, -66.5), (148.0, -44.5)]

# --- anchor-offset: テンプレのマッチ位置からの固定pxオフセットでボタンを押す（画像追従・端末非依存） ---
# 各値 = SE実測の (ボタン位置 - テンプレマッチ中心)。UIは端末間で同pxサイズのため px固定で可。
# SEではマッチ位置=SEテンプレ中心なので元のボタン座標を再現（回帰維持）。
ANCH_RESUME = (100.0, 176.0)      # pause_resume 見出し → 再開ボタン（iPhone16実測で較正:
                                  # 見出し(337,91)→再開(437,267)。旧161ではボタン上端に外れた）
ANCH_REPLAY_YES = (86.0, 125.0)   # 連続ライブ 見出し → はい
ANCH_DOWNLOAD = (55.0, 84.0)      # DL本文 → ダウンロード
ANCH_IMESSAGE_NO = (-52.5, 123.5)  # iOS「iMessage と FaceTime をオンに」見出し → **使用しない**
ANCH_ICLOUD_NO = (7.5, 105.0)      # iOS「一部の iCloud データは同期して」見出し → **今はしない**（下の青い「同期を再開」は押さない）
                                   # （右の「オンにする」は SMS 送信で課金され得ると明記。絶対に押さない）
ANCH_STORY_NO = (-68.0, 76.0)     # ストーリー本文 → いいえ
ANCH_RESUME_YES = (64.0, 62.0)    # 「前回のライブを再開しますか？」→ はい（消費済みLIFEを回収）
ANCH_DATAUPDATE_YES = (-1.0, 79.0)  # 「データ更新のためタイトルへ戻ります」→ はい
ANCH_RESEND_YES = (68.0, 82.0)      # 「前回のライブ結果の送信が…」→ **再送する**（諦めるとpt消失）
# 【重要・課金事故対策】きなこパンの「回復」は**きなこパン行のラベルを基準に**押す。
# 見出し（ライフが足りません）基準の旧オフセット ANCH_KINAKO=(128,62) は、きなこパンが
# 0個になると破綻する: ダイアログはきなこパン行をグレーアウトせず**行ごと消して上に詰める**
# ため、同じオフセットがステラストーンの「回復」ボタン中央に着弾する。
# 実機で既に発生済み（ステラ所持 58→55→52）。
ANCH_KINAKO_ROW = (97.0, 28.5)    # 「きなこパン」ラベル → 同じ行の「回復」ボタン
ANCH_RANKUP_X = (160.0, -56.0)    # RANK UP! 見出し → ×
ANCH_LIVEASSIST_START = (203.0, 243.0)  # ライブアシスト見出し → START（アシスト未選択のまま開始＝消費なし）
# --- アプリ再起動からの復帰（2026-08-02 実機フレーム上で実測） ---
ANCH_TITLE_TAP = (-277.0, -4.5)   # タイトル右下の MENU → 中央下の「TAP SCREEN」
ANCH_NETERROR_RETRY = (66.0, 79.0)  # 「通信エラーが発生しました。」→ **リトライ**（左の諦めるは押さない）
# 「通信がタイムアウトしました。」は本文テンプレを照合し、マッチ中心から「諦める」ボタンへ
# （本文 (341,196) → ボタン (310,262) = (-31,+66)。ボタンはこれ1個だけ。リトライは無い）。
ANCH_NETTIMEOUT_GIVEUP = (-31.0, 66.0)
ANCH_SUPPORTED_YES = (-21.0, 84.5)  # 「…サポートしました。」→ はい（×が無いので背景タップでは閉じない）
ANCH_DAILYTASK_X = (262.2, -14.2)   # 「本日の課題」見出し → 右上の ×
MAX_NET_RETRIES = 8               # 通信エラーの連続リトライ上限（回線障害で無限に粘らない）
ANCH_NEWS_CLOSE = (207.5, 6.5)    # お知らせヘッダ「お知らせ」 → 右上の ×
ANCH_LIFEFULL_X = (126.0, -75.0)  # 「ライフを全回復しました。」本文 → カード右上の ×
ANCH_BREAK_NO = (-73.0, 100.0)    # 休憩時間の確認本文 → **いいえ**（はいは絶対に押さない）
# 1回の実行で復帰を試みる上限。超えたら安全停止する（同じ所を延々回るのを防ぐ）。
MAX_RECOVERS = 3
# クリアを挟まずに編成画面の START を押せる回数。正常経路では START の後に必ずクリアが
# 計上されるので、2 回目の START は「直前のライブが放棄された」ことを意味する。
# 再接続病のセッションで START → PAUSE → 打鍵が「諦める」を踏む → 楽曲選択 → START が
# 35 秒周期で 4 回続き、クリア 0・警告 0 で LIFE だけ減った（実測 2026-09-10）。
MAX_STARTS_WITHOUT_CLEAR = 2
# ホームの EVENT リボンをこの回数押しても画面が変わらなければ、下部ナビ LIVE → 通常楽曲選択 →
# 左下のイベントバッジ → イベントトップ、で迂回する（2026-09-12 04:13 実機: リボンが 60 回無反応）。
HOME_RIBBON_MAX_TAPS = 5
# --max-seconds の上限に達してもライブ中は抜けない（その周回の LIFE が丸ごと無駄になる）。
# リザルト以降の画面で抜ける。ただし上限をこの秒数以上超えたら（ライブ 1 本 ≈120 秒 + 余裕）諦めて抜ける。
MAX_SECONDS_GRACE = 300.0
# 時間上限で抜けてよい画面。リザルト系〜編成（START 前）まで。ライブ中はもちろん、START 直後や
# LIFE 回復直後のローディング（判定は menu）でも抜けない。2026-09-12 05:56 実測: きなこパンで回復した
# 直後のローディングで抜け、始まったライブが無人になった。
SAFE_EXIT_STATES = ("result", "eventresult", "expresult", "cardx", "closex", "rankup",
                    "friendreq", "replay", "songselect", "friendselect", "formation",
                    "lifeshort", "lifefull")

# ライブのタップ判定円（**4レーン**, 内容相対小数）。中央(0.49,0.93)はSCORE表示と重なる
# ダミーで実在レーンではないため除外（無駄打ち＋SCOREアニメの誤検出を排除）。
# note_engine.LANES と同一値に保つこと。
CIRCLES = [
    (0.16, 0.63), (0.33, 0.85),
    (0.68, 0.85), (0.84, 0.63),   # 右2つ: 実機オーバーレイで左寄りズレを補正(2026-06-07)
]                                  # 旧 (0.62,0.85)/(0.74,0.63) は右リングより左で右レーン取りこぼし多発

# --- ライブ中の打鍵モード ---
# "timing": 各円にノーツ（明るい光球）が到達した瞬間を検出してタップ（既定）。
# "rotate": 5円を約50Hzで巡回連打（実績あるフォールバック。誤チューニング時の保険）。
TAP_MODE_DEFAULT = "timing"
# タイミング検出のパラメータ（--calibrate と --note-* で実機調整可能。docs/architecture.md）。
ARC_CENTER = (0.49, 0.50)        # ノーツ放射の中心（円ROIを早撃ち方向へ寄せる基準）
NOTE_ROI_RADIUS = 0.035          # 円ROI半径（ウィンドウ幅相対, ~18px@529w）
NOTE_ROI_LEAD = 0.02             # ROIを ARC_CENTER 側へ寄せる量＝取得+クリック遅延の早撃ち補正。
                                 # **2026-07-31: 打鍵ループが 3.3FPS しか出ておらず、
                                 # 検出遅れ(最大300ms)を lead で埋めていたため 0.04〜0.05 が
                                 # 最適に見えていた。ループを 26FPS に修正して遅延が ~19ms に
                                 # 減ったので lead も縮める必要がある（要再測定）。**
                                 # 旧実測較正(EASY/SOL TRIGGER): 0.04→0.025 で MISS 12→9・SS昇格・
                                 # スコア+14k。0.015 は早撃ち不足で PERFECT 低下。ループ高速化
                                 # (pause照合間引き=DARK_RECHECK_SEC)でレイテンシ減→leadを縮小。
NOTE_WHITE_V = 170               # min(R,G,B) > これ を「白っぽい（ノーツ）」画素とみなす
NOTE_TRIGGER_FRAC = 0.06         # white割合がベースライン+これ を超えたらタップ発火
NOTE_BASELINE_FRAC = 0.20        # white割合がこれ未満の静穏フレームのみEMAベースラインに取り込む
NOTE_BASELINE_EMA = 0.1          # ベースラインEMAの追従係数
NOTE_DEBOUNCE_SEC = 0.18         # 同一円の再発火ガードの上限。これを超えれば発火可
                                 # （タップ波紋の再発火を抑止する従来どおりの上限）。
NOTE_REARM_FACTOR = 0.35         # トリガー超過分がこの割合まで下がれば「再武装」:
                                 # 次ノーツを NOTE_MIN_GAP_SEC 後から受け付ける。
                                 # 速い曲の16分連打（150ms間隔）を拾うための機構。
                                 # 小さいほど再武装が遅れ密ノーツを見送り、大きいほど
                                 # 波紋の残光で誤再武装→二重打鍵の危険が増える。
NOTE_MIN_GAP_SEC = 0.09          # 再武装済みの場合の最小発火間隔（~16分@400bpm）。

# --- タップ円較正の幾何検証（2026-10-12、誤検出の悪化補正対策） ---
# ゲームの4円はほぼ左右対称（鏡像）。検出が装飾を円と取り違えたとき、多数決の中央値が
# prior からゆっくりずれて「一度誤確定すると以後の補正が誤値を prior にして回り続ける」
# 構造だった。コミット前に対称性を検査して拒否する（実測: 円4 が 27px 外へ確定し、
# 円4のノーツを丸ごと見送った。復旧には手動でキャッシュを消す必要があった）。
AUTOCAL_SYMMETRY_TOL = 0.05      # 円1↔4・円2↔3 の y差と、両対の中心xからの距離差の許容
AUTOCAL_JUMP_TOL = 0.10          # 補正値が prior から一度に動ける最大距離（content相対）。
                                 # 検出の裾野が「装飾」を拾っても、prior からこの距離以上に
                                 # 飛ぶ確定は誤検出とみなす（実測の悪化: 円4 が 0.08 動いた）
# --- ホールド（長押し＝緑ノーツ）対応。色ではなく「明るさが持続」することで検出する ---
# 円ROIがトリガー超えのまま HOLD_SUSTAIN_FRAMES フレーム続いたら長押しノーツとみなし、
# 明るさが続く限り押下を保持（drag で genuine 入力＝PAUSE防止）。タップ波紋の短い持続では
# 発火しないようフレーム数はやや多め。安全のため HOLD_MAX_SEC で必ず離す（誤検出の暴走防止）。
HOLD_SUSTAIN_FRAMES = 14         # この連続フレーム数トリガー超持続で「長押し」と判定（≈0.45s@30fps）。
                                 # タップ波紋は~0.2-0.3s持続するため、誤検出回避に本物の長押し
                                 # (0.5s+)が確実に超える値に設定（6では波紋を誤検出した実測）。
HOLD_MAX_SEC = 8.0               # 1ホールドの最大保持秒（誤検出でも必ず離す上限）。
                                 # 実測した長さは 0.3〜0.5秒だが曲により長い可能性があるので広く取る。
                                 # --hold-max-sec で上書き可。
HOLD_REL_FACTOR = 0.45           # 保持解除のしきい（trigger×これ を下回ったら離す＝ヒステリシス）

# --- ライブ品質の自己診断（曲・難易度に依存しない指標。2026-10-20） ---
# 旧来は打鍵回数の閾値（Don't Analyze Me/EASY・184ノーツ≈370打鍵を基準にした 330/600）
# で異常ライブを警告していたが、曲・難易度が変わると意味を持たない（ノーツ数も
# 打鍵数も曲ごとに違う。10倍イベントの EXPERT+ では警告が無意味だった）。
# 代わりに、曲に依存しない2つの指標でライブ終了時に警告する:
# - ライブ中のループ周波数: 判定フレーム ÷ gameplay/pause に費やした秒。
#   低下するとノーツ到達検出の時間分解能が足りず MISS が増える。
# - gameplay/pause の継続秒: リザルトを見逃して2ライブが1クリアに連結した検出用
#   （旧「打鍵>600」相当を時間で判定する）。
LIVE_FPS_WARN = 25.0        # ライブ中ループ周波数の下限。正常は 26〜37（実測は
                          # docs/device-findings.md）。これ未満＝判定がノーツに追いついていない
LIVE_MERGED_WARN_SEC = 190.0  # gameplay/pause 継続秒の警告線。1ライブは ≈110〜125秒
                          # （PAUSE解決後、GAMEPLAY_TIMEOUT_SEC の注記参照）に PAUSE 1回分
                          # （≦PAUSE_STUCK_SEC=60）を足しても ≈185秒まで。それを超える
                          # gameplay/pause 累積はリザルトを通らず2ライブ走った可能性を疑う。
                          # 連結が gameplay のまま続くと 240 秒で gameplay_timeout が先に
                          # 止めるので、警告が出るのは「合計 190〜240 秒の連結」か
                          # 「間に画面遷移を挟んで gameplay_since が切れた連結」。

# --- 打鍵の着弾点ジッター ---
# 着弾点が毎回まったく同じ4点だと散らばりが厳密ゼロになり、統計的に人間と即座に区別できる。
# リング内に収まる範囲で散らす。判定 ROI には一切影響を与えない（_circle_roi_px は素の
# CIRCLES を使い続ける）。値はすべて円リング半径 R との比。R は端末で変わるので比で持つ。
CIRCLE_R_FRAC = 0.05          # 円リング半径の目安（ウィンドウ幅相対）。
                              # **note_engine.CIRCLE_R_FRAC と同一値に保つこと。**
JITTER_BIAS_SIGMA_R = 0.10    # レーン別の恒常バイアス σ（≈2.6px@529w）。ライブごとに引き直す
JITTER_TAP_SIGMA_R = 0.18     # タップごとのノイズ σ（≈4.8px@529w）
JITTER_MAX_R = 0.60           # 合計オフセットの上限（≈15.9px@529w）。超えたら棄却して引き直す。
                              # 0.45 では棄却が分布の裾を削りすぎ、実効 σ が seed 次第で
                              # 0.82〜0.93 倍とばらついた（0.60 では 0.93〜0.99 倍）。
# --- 実験的トラッキングエンジン(engine=track) ---
TRACK_ARRIVE_PX = 34.0           # ノーツがレーン円のこのpx内に来たら打鍵
TRACK_FORGET_SEC = 6.0           # acted集合を周期クリア（id枯渇/メモリ防止。ライブ跨ぎ）
KEEPALIVE_GAP_SEC = 0.6          # 無検出がこの秒続いたら genuine 入力を1発（PAUSE防止, 0.7s未満）
# フレンド選択→編成の遷移中、イベント装飾の帯を cardx と誤検出して右上の × を
# 押してしまうため、この秒数は cardx を無視して編成画面(START)の出現を待つ。
# ROI半径をレーンの移動距離に比例させるか。理論上はレーン間のタイミングを揃えるが、
# 実測では改善が誤差に埋もれ（P33→P29）、実機の体感でも遅く感じるとの指摘があったため
# **既定オフ**（既知の良好構成＝全レーン固定半径に戻す）。効果を分布で確認できたら既定へ。
ROI_SCALE_BY_DISTANCE = False
CARDX_SUPPRESS_SEC = 3.5
# 終了コード。**supervisor が「再起動してよいか」を判断するために使う**。
# 従来は安全停止も break で正常復帰し rc=0 だったため、supervisor が停止理由に関係なく
# 8秒後に再起動し、同じ画面で26〜36秒周期の空転を延々と繰り返していた
# （実測 2026-08-01: attempt #34〜#45 の12連続、ログ全体で「完了: 0 回クリア」71件）。
EXIT_OK = 0          # 正常終了（loops到達 / max-seconds到達 / ESC）
EXIT_SAFE_STOP = 42  # 安全停止。**人間の確認が必要なので再起動してはいけない**
AUTOCAL_RETRY_SEC = 0.5          # --auto-circles: 補正に成功するまでライブ中この間隔で再試行
AUTOCAL_MAX_SAMPLES = 200        # 多数決に使う検出サンプルの保持上限（古いものから捨てる）
# 補正結果の永続化先。**プロセス再起動をまたいで即座に正しい円で打鍵する**ため。
# 補正はライブ開始から確定まで20秒ほどかかるので、supervisor による再起動のたびに
# 未補正で打鍵する区間が生まれる（実測: 未補正だと MISS 51・グレードB）。
# ウィンドウサイズをキーにするので機種・ウィンドウを変えても混ざらない。
AUTOCAL_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             ".autocal_circles.json")
# --- 赤ノーツ=フリック（§17.9）。到達直前ROIで赤を検出 → タップ＋外向きスワイプ ---
FLICK_APPROACH_FRAC = 0.65       # 円と中心の間の検色点（0=中心,1=円）。0.65で色が出る（白飛び前）
FLICK_RED_MIN_V = 120            # 検色: 明るい画素の閾値
FLICK_RED_DELTA = 40             # 明るい画素平均で R-G,R-B がこれ以上なら「赤ノーツ」
FLICK_RED_MEMORY = 0.35          # 到達直前で赤を見てから、この秒内にタップしたらフリック扱い
FLICK_DIST = 0.06               # フリック移動量（ウィンドウ幅相対, 外向き）
# --- 緑ノーツ（次の緑まで長押し）。2026-08-04 実機3ライブで実測 ---
# 緑は**2つが緑の帯で繋がって**同じ放射線上を同じ円へ飛ぶ。approach 点での緑画素は
# 「立ち上がり→山(頭)→谷(帯)→山(尾)→消失」と推移する。
# **検色点は赤(0.65)と別の 0.70。** 0.65 だと判定文字「GOOD」が ROI に重なる（1ライブに
# 約110回出る）。0.70 なら外れ、しかも色は濃くなる（赤の R-G が 70→82）。0.75 以上は白飛び。
GREEN_APPROACH_FRAC = 0.70
# 判別は**緑画素の「数」**で行う。明るい画素の色平均や白率では GOOD 文字と区別できない
# （実測: 緑ノーツの白率 0.00〜0.40 に対し GOOD 文字 0.37 で完全に重なる）。
# 画素数なら本物 700〜1064 に対しノイズ 21〜85 と 8 倍差がつく。
# **しきい値は実測の分離幅から決めた。** 判定文字「GOOD」は 0.70 でも円によっては ROI に
# 入る（文字はタップした円の近くに出るため、位置をずらすだけでは避けきれない）。
#   判定文字・背景ノイズ: 最大 439px（コーパス78枚×4円）
#   本物の緑ノーツ:       最低 766px（実機4円のピーク）
# 誤検出は最大 8 秒ぶん他レーンを落とすのに対し、取り逃しは従来動作（頭を1回タップ）に
# 戻るだけ。**非対称なので誤検出を避ける側に寄せる。**
GREEN_MIN_PX = 600               # これを超えたら緑ノーツが approach に居る
GREEN_REL_PX = 250               # 解除側のしきい（ヒステリシス。通過中の一瞬の途切れで早期解除しない）
GREEN_MEMORY = 0.35              # 緑を見てから、この秒内に fired したらホールド扱い（赤と同値）
# 判定文字は**タップの後にしか出ない**。同じ円を叩いた直後は緑を見ない（第二の防御）。
# EASY では同じレーンに 0.45 秒以内で続けてノーツが来ることは稀。
GREEN_SUPPRESS_SEC = 0.45
FLICK_STEPS = 3                  # フリックのドラッグ分割数

# テンプレ（assets/templates/*.png）。明るさゲートと併用し高閾値照合する。
# 判定順序は detect() を参照（friendreq → replay → closex → ...）。
TEMPLATES = {
    "pause": ("pause_resume.png", 0.78),       # 「PAUSE」見出し文字（暗背景でも確実）
    "lifeshort": ("life_short.png", 0.85),     # LIFE不足ダイアログ「ライフが足りません。」
    # きなこパン行の存在確認用。**これが無ければ LIFE 回復をクリックしない**（ステラ誤消費防止）。
    # 実測: きなこパン有り 1.000 / 枯渇 0.52 と明確に分離する。
    "kinakorow": ("kinako_row.png", 0.80),
    # per-song Result の EXP 画面（獲得キャラEXP）。カードの緑ヘッダを detect_card_x が
    # 拾って cardx と誤判定し、背景タップでは閉じないため停滞→安全停止していた
    # （実測: 全警告87件中34件が「カードポップアップを閉じられず停滞」）。
    # 中央タップで送る画面なので、cardx より先に専用状態として確定する。
    "expresult": ("exp_result.png", 0.90),
    "friendreq": ("friendreq_yes.png", 0.74),  # EVENT RESULT の「申請する」ボタン
    "replay": ("replay_title.png", 0.82),      # 連続ライブ再プレイ確認の「連続ライブ」見出し
    "closex": ("close_x.png", 0.87),           # カード型ポップアップ右上の×（緑, 本物≈0.94）
                                               # ※Result画面の誤検出(≈0.84)を避けるため0.87
    "rankup": ("rankup.png", 0.78),            # 「RANK UP!」文字（× フォールバック用）
    # しきい値 0.80: 2026-09-15 実機で 0.849 と 0.85 をわずかに割り、色判定の cardx に流れて
    # cardx_stuck で停止した。コーパス上の非DL画面の最大は 0.584 で余裕がある（tests/test_detect_dialogs.py）。
    "dldialog": ("dl_dialog.png", 0.80),       # データDL確認ダイアログ本文「をダウンロードします。」
    "story": ("story_dialog.png", 0.85),       # 「ストーリー開放チケット…遷移しますか？」→ いいえ
    # アプリ再起動後に出る「ライブスタート前にアプリが終了しました。前回のライブを再開
    # しますか？」→ **はい**。LIFE は既に消費済みなので、いいえ を選ぶと丸損になる。
    "resumelive": ("resume_live.png", 0.85),
    # 周回対象曲「Don't Analyze Me」の一覧行（ユーザー指定: 効率が良いので毎回これを選ぶ）。
    # 選択中は緑ハイライト、未選択は暗背景で見た目が変わるため variant を併用する。
    # `--keep-selection` の回は参照されない。
    "songdaz": ("song_dontanalyze.png", 0.85),
    # ゲーム側のデータ更新でタイトルへ戻される。シアン系ヘッダを持つため cardx と
    # 誤認され、背景タップでは閉じられず停滞→安全停止していた（実測 2026-08-02、100周目）。
    "dataupdate": ("data_update.png", 0.85),
    # タイトル復帰後に出る「前回のライブ結果の送信が正しく終了しませんでした」。
    # **再送する**を選ばないと直前のライブぶんの pt が失われる。
    "resendresult": ("resend_result.png", 0.85),
    # 「通信エラーが発生しました。」→ **リトライ**（諦めるとその周回を落とす）。
    # シアン系ヘッダを持つため cardx と誤認され、背景タップでは閉じられず停滞していた
    # （実測 2026-08-03: 1745 回タップして cardx_stuck で停止）。
    "neterror": ("net_error.png", 0.85),
    # 「通信がタイムアウトしました。」→ **諦める**（ボタンはこれ1個だけ・リトライなし）。
    # neterror と同じシアン系ヘッダなので cardx に流れ、背景タップでは閉じられず
    # cardx_stuck で停止した（2026-10-15 03:02 実機、134 クリア後）。
    "nettimeout": ("net_timeout.png", 0.85),
    # 「ライブをN回サポートしました。/ NフレンドptをΩ手に入れました。」→ はい。
    # **×が無く「はい」だけ**なので cardx の背景タップでは閉じられず停滞する
    # （実測 2026-08-03: 4:00 の復帰導線でホーム到達直後に出る）。
    # 数字は毎回変わるので「サポートしました。」の部分だけを見る。
    "supported": ("supported.png", 0.85),
    # イベントトップの「本日の課題 N/4」ポップアップ。**画面が暗く gameplay と誤判定される**
    # （実測 mean 58.2 < DARK_THRESH 65）。判定は暗い側の救済枠で行う（下の detect 参照）。
    # 「1/4」の進捗は変わるので見出しの文字だけを見る。
    "dailytask": ("daily_task.png", 0.85),
    "liveassist": ("live_assist.png", 0.85),   # ライブアシスト選択画面 → 何も選ばず START（消費なし）
    # 旧 download_btn.png は「ライブの説明」チュートリアル等を誤検出(0.88)したため撤去。
    # DL確認は dldialog（本文テンプレ, 0.85）でのみ判定する。
    "result": ("result_title.png", 0.55),      # per-song「Result」文字（誤検出は中央タップのみで安全）
    # EVENT RESULT 見出し「-EVENT RESULT-」（緑・大文字・斜体）。per-song Result とは別字形。
    # 申請する押下後は friendreq が消えて未知画面化し停止していたため専用テンプレで送る。
    # KEEP OUT テープが他画面の同高さに出て斜体太字が構造相関する(≈0.67)ため閾値は高め(0.85)。
    "eventresult": ("eventresult_title.png", 0.85),
    # 「ライフを全回復しました。」モーダル（回復カードと違い**背景タップでは閉じない**。×必須）。
    # **songselect・cardx より先**: 楽曲選択や Event Result の上に重なって出るため、NEXT や
    # closex のテンプレが背後に当たると永遠に閉じない（2026-10-11 実機: NEXT を約30回・
    # cardx の背景タップを約30回踏んで停滞した）。
    "lifefull": ("life_full.png", 0.80),       # 「ライフを全回復しました。」本文（×で閉じる）
    "songselect": ("song_select.png", 0.85),   # 楽曲選択画面の「NEXT」ボタン（連戦終了で戻る）
    "friendselect": ("friend_select.png", 0.85),  # フレンド（サポート）選択画面
    "formation": ("formation.png", 0.85),      # 編成画面の「START」ボタン
    "battery": ("battery_close.png", 0.80),    # iOSバッテリー残量低下警告の「閉じる」ボタン
    # iOS「iMessage と FaceTime をオンにしますか？」の見出し。画面を暗転させ DARK_THRESH を
    # 下回るため暗い側でも照合する（2026-09-16 07:39 実測、編成画面の上に出て gameplay_timeout 停止）。
    "imessage": ("imessage_prompt.png", 0.80),
    # iOS「一部の iCloud データは同期していません」の見出し（2026-09-16 19:43 実測、EVENT RESULT の上）。
    "icloudsync": ("icloud_sync.png", 0.80),
    # --- アプリ再起動からの復帰（4:00 前後のデータ更新後）。2026-08-02 実機で導線を実測 ---
    # いずれも**イベント固有の絵は使わない**。バナーの絵柄は毎イベント変わるが、
    # 「TAP SCREEN」「お知らせ」「EVENT」ラベル帯・「イベント楽曲」・ダイアログ本文は変わらない。
    # 旧 tap_screen.png / event_songs_btn.png は現在の画面に当たらない（実測 0.54 / 0.42）。
    # 起動時の注意書き。「TAP SCREEN」の文字が背景ごと安定している画面（実測 1.000）。
    "notice": ("notice_tap.png", 0.85),
    # タイトル画面。**背景は動画で、しかもイベントごとに差し替わる**ため、背景を含む
    # テンプレは当たらない（実測 2026-08-03: 旧イベントで切った「TAP SCREEN」が新しい
    # タイトルで 0.85 未満となり、4:00 の復帰がここで 25 秒停滞して止まった）。
    # 不透明で位置が動かない**右下の MENU ボタン**を目印にする（ユーザー指摘）。
    # タイトル5フレームで 0.992〜1.000、白飛びするローディングでも 0.734 で当たらない。
    # ただし**編成画面にも MENU がある**（0.889）ので、しきい値は 0.92 とし、
    # 判定順も formation の後ろに置く（二重の防御）。
    "title": ("title_menu.png", 0.92),
    "news": ("news_title.png", 0.85),          # お知らせダイアログのヘッダ「お知らせ」
    "home": ("home_event.png", 0.85),          # ホームの EVENT ラベル帯（ベージュ＝累計イベント側）
    "eventtop": ("eventtop_songs.png", 0.85),  # イベントトップの「イベント楽曲」ボタン
    # 休憩時間中に「イベント楽曲」を押すと出る確認。**「はい」を押すと pt ゼロで LIFE を失う。**
    "breaktime": ("breaktime.png", 0.85),
    # 04:00 リセット直後にホームで出る「LOGIN BONUS」（ログインボーナス／デイリーパス）。
    # ヘッダがピンクで cardx の色検出に掛からず、未知画面で安全停止していた（2026-09-12 04:01）。
    # 2 ページあり、どこをタップしても進む（下部に「TAP SCREEN」）。
    "loginbonus": ("login_bonus.png", 0.85),
    # イベント期間中の「特別ログインボーナス」（1日1回、きなこパン等）。ログインボーナスの後に出る。
    # 下部の定型文「1日1回（最大7回まで）特別ログインボーナスをプレゼントいたします！」を目印にする
    # （報酬カードや背景はイベントで変わる）。画面タップで進む。
    "speciallogin": ("special_login.png", 0.85),
    # 判定順には入れず、ハンドラ内でだけ使うテンプレ:
    # 通常ライブの楽曲選択の左下に出るイベントバッジ（イベントごとに絵が変わるので variant で増やす）。
    # **これが見えている楽曲選択は通常ライブなので NEXT を押さない**（絶対規則 3）。
    "eventbadge": ("event_badge.png", 0.85),
    # ホーム下部ナビの LIVE アイコン（イベント非依存）。EVENT リボンが無反応なときの迂回に使う。
    "navlive": ("nav_live.png", 0.90),
}                                              # ※低電力モードは絶対に押さない（閉じるのみ）

# --- LIFE 回復（ユーザー要件: きなこパンで回復・ステラは絶対に使わない） ---
# ステラストーンの「回復」は下段(約 (0.644,0.69))にある。**絶対にクリックしない**。
# 在庫切れ時はステラを使わず停止する。
# 【枯渇判定 2026-10-20 改訂】旧 MAX_LIFE_RECOVERS(6) の「連続 LIFE 不足回数」は、1個の
# 回復量が小さいイベントで在庫があるのに停止してしまうため廃止。正の信号は
# (a) きなこ行が見つからない（kinako_missing。行ごと消えて上に詰まる＝本当の枯渇）と
# (b) 「回復」を押したのにダイアログの現在 LIFE が増えない、の繰り返し（下記）の2つ。
MAX_LIFE_NO_GAIN = 3               # 「回復」を押したのに現在 LIFE が増えない回数の上限（停止）
# 1回の LIFE 回復で使うきなこパンの個数は**固定値を持たない**。1個あたりの回復量は
# イベントで変わる（ユーザー指定 2026-10-20: 例 共鳴=30, 旧イベント=20,5）。個数は
# `n = ceil((LIFEコスト − 現在LIFE) / 1個の回復量)` を 1..KINAKO_MAX_PER_RECOVER に
# 収めて求め、すべて Vision OCR（tools/ocr.py）で画面から読む。読めないときは n=1
# （従来の「1個ずつ回復」相当）に縮退する。LIFE は上限超えで保持できるので多めは損しない。
KINAKO_MAX_PER_RECOVER = 10        # 1回の回復で積む個数の上限（コスト100・回復量5なら不足分）
KINAKO_ASSUMED_COST = 100          # コストバッジ未取得時の仮定（実測の最大。10倍ブースト）
KINAKO_STEP_GAP = 0.3              # 「+」を押す間隔（秒）
# きなこ行が見つからないときに、**クリックせずに**撮り直して確認し続ける時間（秒）。
# ダイアログの再表示アニメ・通知バナーの重なりで一瞬だけ閾値を割ることがある（上記 19:25）。
# 本当に枯渇しているなら行は消えたままなので、この時間の後に従来どおり停止する。
KINAKO_RECHECK_SEC = 2.0
KINAKO_RECHECK_GAP = 0.25
# 行が安定して見えてから「数量確定 → + → 数量再確定 → 回復」までの予算（秒）。
# KINAKO_RECHECK_SEC(2.0s) は「行を発見する」ための予算で、1反復が ~0.9s（grab+照合+
# sleep）ある実機では数量欄の確定読み（連続2〜3枚）にすら届かず unsettled で空転した
# （2026-10-14 実機: 8回再判定して停止）。行が見えている間はこの予算を使う。
KINAKO_SETTLE_SEC = 10.0
# 「+」/「−」を押した直後の再確定に使う予算（秒）。押下で期限が尽きないよう延ばす。
KINAKO_POST_CLICK_SEC = 4.0
# 行が見え続ける限界（秒）。キラキラ演出等で ok が間欠しても deadline が伸び続ける
# 設計にしたため、無制限に待たない絶対上限を別に設ける。超えたら unsettled でやり直す。
KINAKO_RECOVER_MAX_SEC = 30.0
# 「+」を押したことを覚えておく秒数。この間に同じダイアログへ戻っても「+」を押し直さない
# （「回復」を押せずにやり直すたびに「+」を押して数量が 1→3→5→…→10 と増えた。2026-10-11 実機）。
# 1回の _recover_life は最大 KINAKO_RECOVER_MAX_SEC(30s) 掛かるため、メモリはその数倍必要。
# 20s では同じダイアログをまたぐ再判定で期限切れになり「+」を再押した（2026-10-14）。
KINAKO_PLUS_MEMORY_SEC = 90.0
# 「回復」を押せないまま（何もクリックせずに）lifeshort をやり直す回数の上限。超えたら停止。
# **やり直しは枯渇判定（MAX_LIFE_NO_GAIN）には数えない**（回復を押していないので）。
MAX_LIFE_UNSETTLED = 8
KINAKO_OVERCAP_PX = 300           # 「上限を超えています」バッジとみなす赤画素数（実測 760〜812、平常 0）
KINAKO_MINUS_MAX = 12             # 1回の回復で「−」を押す上限（数量を目標 n へ戻す）
# 「+」済みで数量が目標 n より小さいまま続いたとき、n 未満の確定数量で「回復」してよい
# 猶予（秒）。在庫上限で「+」が効かないケースを unsettled 空転させないため。
KINAKO_LOW_SETTLE_SEC = 4.0
# 「+」済みなのに数量が n より大きい読みが続いたとき「−」を許す猶予（秒）。
# カウントアップ途中の誤読で打ち消さないための安全弁（旧 plus_clicked ハードロックの置換）。
KINAKO_HIGH_SETTLE_SEC = 4.0
# 数量欄の確定に必要な読み取り数。数字が読めるなら連続2回の一致で確定。
# 読めない（None）は3回にする: 「+」の後のカウントアップ（1→2→3）の途中の一瞬の
# 誤読で「−」を押さないため（実機で「+」×2の直後のフレームで起きうる）。
KINAKO_SETTLE_READS = 2
KINAKO_OTHER_READS = 3
# 「NEXT を押しても画面が変わらない」が続く回数の上限（その間に detect は songselect を
# 返し続ける）。2026-10-11 実機: 「ライフを全回復しました。」モーダルが楽曲選択の上に出て
# NEXT を約30回・60秒飲み込んだ。モーダルは lifefull で検出するようになったが、同種の
# 見えない蓋がまた起きても延々と空打ちしないよう、回数で止める（次に detect が
# モーダル等を返した時点でリセットされる）。
SONGSELECT_NOCHANGE_MAX = 6
LIFE_CARD_MIN = 0.43              # life_card_like のしきい値（回復カード 0.46〜0.48、他画面 ≤0.38）
# 「回復」を押した後、LIFE 不足ダイアログが消える（＝確認カードに替わる）のを待つ上限（秒）。
# ダイアログが残ったまま確認カードを閉じにいくと、近くにあるダイアログの×を
# 叩いて回復ごと取り消しうるので、消えたのを見てから押す。
LIFE_CONFIRM_WAIT_SEC = 2.0
# 送り画面（result / eventresult / expresult / cardx）での連続タップ。
# 1回の detect() が 1〜3 秒かかるため、「detect → 1タップ」では送りの実効間隔がその秒数になる。
# 画面が送り画面のままであることを安いガードで確かめながら、短い間隔で続けて叩く。
# Result 系の同じ状態に右側タップで連続この秒数留まったら、右側が効かない画面とみなして
# その状態だけ中央送りへ戻す（1ページは通常 3〜5 秒。RESULT_STUCK_SEC=30 より十分短い）。
ADVANCE_ALT_SEC = 10.0
ADVANCE_BURST_TAPS = 6             # 1回の連続タップの上限回数（その後は通常の detect に戻る）
ADVANCE_BURST_SEC = 4.0            # 1回の連続タップの上限時間（秒）
ADVANCE_BURST_GAP = 0.25           # タップ後、次のガードまでの待ち（秒）
ADVANCE_STABLE_GAP = 0.06          # 安定判定の2枚撮りの間隔（秒）
# 安定判定: 2枚の縮小グレー画像の平均絶対差がこれ未満なら「静止している」。
# ダイアログの出現アニメ・画面遷移の途中では叩かない（実測: 静止したカード 0.1〜0.2、
# Result のカウントアップ 5 秒で 2.6、画面の切り替わり 17〜110）。
ADVANCE_STABLE_DIFF = 3.0
# 「同じ画面のまま」とみなす差の上限。これ以上変わったら別の画面（または画面が進んだ）とみなす
# （実測: 同じ確認カード・同じダイアログ 0.1〜0.2、Event Result → 連続ライブダイアログ 52、
# LIFE不足ダイアログ → 回復の確認カード 40〜43）。
ADVANCE_SAME_DIFF = 8.0
# 連続タップを止めるダイアログ。送り画面の上に重なって出るもの（連続ライブ「いいえ/はい」は
# friendreq テンプレがピンクの「はい」に当たる。実測 2026-10-11）。songselect は範囲限定で別に見る。
ADVANCE_GUARD_KEYS = ("lifeshort", "friendreq", "replay", "rankup", "lifefull")
# 照合を並列に回すワーカー数。cv2 は照合中に GIL を解放するので、同じ BGR フレームに対する
# キー別の match_best をスレッドで並べると、直列と**同一の結果**を短時間で得られる
# （実測 2026-10-11, 10コア: 直列 3.7〜4.2 秒 → 8 ワーカー 1.0〜1.7 秒。4 / 12 ワーカーは遅い）。
MATCH_WORKERS = 8
_MATCH_POOL = None


def match_pool():
    """テンプレ照合用の常駐スレッドプール（フレームごとに作らない）。"""
    global _MATCH_POOL
    if _MATCH_POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _MATCH_POOL = ThreadPoolExecutor(MATCH_WORKERS, thread_name_prefix="i7match")
    return _MATCH_POOL


# 明るいフレームで detect() が m() に渡すキーの並び。**detect() 本体の m("…") の出現順と同じ**
# （tests/test_detect_prefetch.py がソースと突き合わせる）。明るいフレームでは、この順に
# 全キーの照合を match_pool() へ先に投げ、m() はその結果を順に読む。判定順は m() の呼び順の
# ままなので結果は直列と同じで、待ち時間だけが並列になる。
BRIGHT_KEYS = (
    "pause", "imessage", "icloudsync", "battery", "lifeshort", "friendreq", "replay",
    "rankup", "dldialog", "story", "resumelive", "dataupdate", "resendresult", "neterror",
    "nettimeout",
    "supported", "liveassist", "formation", "breaktime", "title", "notice", "news",
    "eventtop", "loginbonus", "speciallogin", "home", "dailytask", "lifefull",
    "expresult", "friendselect", "closex", "eventresult", "result",
)
# テンプレ照合のスケール候補。端末でUIサイズはほぼ同じ(≈1.0で一致)だが、機種差に備え
# ±20%程度を見て数点を試す（タイトルバー有無の0.86も維持）。
# テンプレ照合のスケール段数。**1段増えるごとに全画面照合が1回増える**ので、明るい画面の
# 判定コストにほぼ比例して効く（実測 2026-08-29: 6段 2264ms/フレーム）。
#
# **コーパス309枚（テンプレで判定できる全フレーム。529x334 と 671x348 の両方）を総当たりして
# 求めた最小構成が [0.8, 0.93, 1.0, 1.08]。** 0.86 と 1.18 は、それでしか当たらないフレームが
# 1枚も無い。閾値割れは 0/309 件で、余裕が最小のケース（closex, +0.002）は 6段でも 4段でも
# スコアが同一＝削った段に依存していない。
#
# **削りすぎは即座に周回を殺す。** 一度 [0.93, 1.0, 1.08] まで削ったところ、**PAUSE を
# 37枚中7枚取りこぼした**（0.8 でしか当たらないフレームが3枚ある）。PAUSE を見逃すと
# ライブが止まったまま復帰できない。**少数のフレームを見て決めてはいけない**（この誤りは
# 各ディレクトリ2枚だけ見て起きた）。
# 歯止め: tests/test_dark_detect_perf.py（PAUSE の取りこぼし）と
#         tests/test_corpus_smoke.py::TestCorpusStatesUnchanged（実フレームの判定固定）。
#
# 照合時はこの各段に**窓スケール係数** `window_scale(frame)` を掛けて使う（ミラーリング窓が
# 基準寸法から数%縮むと、どの段でも約2%ずれたまま閾値を割る。実測 2026-10-20: 671x348 →
# 656x341 に縮み、friendselect 0.844 / lifefull 0.669 で周回が停止した）。
SCALES = [0.8, 0.93, 1.0, 1.08]
# 窓スケール係数の基準幅（px）。縦横比 > WIDE_ASPECT_MIN なら iPhone 16 系クラス、
# それ以外は SE クラスとみなす。フレームがちょうど基準幅なら s=1.0 で照合結果は
# 従来とビット単位で同じになる（段数も増えない）。
WIDE_REF_W = 671
SE_REF_W = 529
WIDE_ASPECT_MIN = 1.75
# 明るさ閾値: これ未満ならライブ中（暗い画面）
DARK_THRESH = 65.0
# 明るさゲートの計測条件を固定するための「上端 38 行の置換値」。
# DARK_THRESH とコーパス（507枚）は **macOS のタイトルバー付きウィンドウ**（上端 38 行の
# 平均 209.7）で較正されている。現在のミラーリングウィンドウはタイトルバーが無く、上端は
# 透過して**背後のウィンドウが写り込む**（実測 2026-09-11: 昨夜は暗いページで 28、今朝は白い
# Chrome で 252）。写り込みで平均が ±20 動くと、暗いメニューが gameplay に落ちて盲目打鍵に
# なったり（昨夜）、ライブ中の再照合コストが4倍になったり（今朝）する。上端 38 行を較正時と
# 同じ値に置き換えて平均すれば、帯の中身に依存せず較正どおりの値になる。
TITLEBAR_ROWS = 38
TITLEBAR_EQUIV = 210.0
# 薄暗いフレーム（DARK_THRESH 以上・これ未満）は、タップ円のリングが見えていれば gameplay とみなす。
# ライブ中の内容輝度は曲・演出で動き、実測 2026-09-12 深夜の Dis one. は 35〜52（frame_brightness
# 54〜70）で、約 5% のフレームが 65 を超えて明るい側の全段照合（2.9 秒・打鍵停止）に落ち、
# gameplay の継続時間もリセットされてクリア計上が漏れた。リングは 4 円の固定位置に常に描かれる
# 白い輪で、暗いメニュー・cardx・Result・PAUSE ではコントラスト 15 以下、ライブ中は 70〜100（実測）。
# 上限 90: 明るい MV のライブフレームは実測で frame_brightness 73 まで上がる（2026-09-12 Dis one.）。
# リングが 3 円見えることが条件なので、コーパスの非ライブ画面（n_ok 最大 2）には影響しない。
DIM_THRESH = 90.0
RING_CONTRAST_MIN = 40.0     # リング上の明るさ − 内側の明るさ（max(R,G,B)）
RING_MIN_COUNT = 3           # 4 円中これ以上でリングが見えていれば「ライブ中」
# 暗い画面（gameplay/PAUSE）では、重い pause/songselect テンプレ照合を毎フレームせず
# この秒数おきに間引く。PAUSE・暗いsongselectはタイミング非依存なので数フレーム遅れて
# 検出してよく、間引くぶんノーツ検出のサンプリングレートが上がり打鍵精度が向上する。
DARK_RECHECK_SEC = 0.7
# ライブ中の PAUSE 見出しの出現範囲（実測: コーパス37枚すべてで x≈0.50, y=0.27〜0.36）。
# 余裕を持たせても全画面の 1/4 以下で済み、照合コストが大幅に下がる。
PAUSE_SEARCH_BOX = (0.25, 0.10, 0.75, 0.55)
# 楽曲選択の NEXT ボタンの出現範囲（実測: コーパス34枚＋イベント楽曲1枚のすべてで
# x=0.782〜0.853, y=0.841〜0.913）。**明るい側の判定順で songselect を cardx より前に
# 置いた**（区切り線の cardx 誤検出対策）ため、この照合は明るいフレームごとに走る。
# 全画面マルチスケールのままだと 238ms/回かかり、1周の判定時間が 24s → 41s に伸びた
# （2026-08-28 実測）。範囲を絞ると 24ms/回になる。
SONGSELECT_SEARCH_BOX = (0.58, 0.68, 1.0, 1.0)
# EVENT RESULT 見出し「-EVENT RESULT-」の出現範囲（実測: 529x334 で中心 (0.31,0.18)、
# 671x348 で (0.32,0.21)）。暗い側の救済照合で毎 0.7 秒走るので範囲を絞る。
EVENTRESULT_SEARCH_BOX = (0.05, 0.05, 0.60, 0.40)
# 「本日の課題」見出しの出現範囲（実測: 529x334 で中心 (0.33,0.22)、671x348 で (0.36,0.21)）。
DAILYTASK_SEARCH_BOX = (0.15, 0.08, 0.60, 0.40)
# iOS システムダイアログ（iMessage/FaceTime 確認）の見出し。中央上寄りに固定（実測 x≈0.35-0.64, y≈0.34）。
IMESSAGE_SEARCH_BOX = (0.25, 0.20, 0.75, 0.50)
ICLOUD_SEARCH_BOX = (0.25, 0.15, 0.75, 0.45)      # iCloud 同期ダイアログの見出し（実測 y≈0.30）
# 暗い側の救済照合（DARK_RECHECK_SEC ごとに1回走る枠）の対象キーと探索範囲。
# 判定順はこの並びで、pause の次に確認する。新しい「暗くて gameplay に見える画面」を
# 追加したらここへ登録する（detect() もこのリストを辿る）。
DARK_RESCUE_KEYS = (
    ("songselect", SONGSELECT_SEARCH_BOX),
    ("dailytask", DAILYTASK_SEARCH_BOX),
    ("eventresult", EVENTRESULT_SEARCH_BOX),
    ("imessage", IMESSAGE_SEARCH_BOX),
    ("icloudsync", ICLOUD_SEARCH_BOX),
)
# 未知の明るいダイアログにこの秒数留まったら、ステラ誤使用を避けて停止する。
# （LIFE 回復ダイアログ等の未知画面でボタンを盲目クリックしないための安全装置）
STUCK_STOP_SEC = 25.0
# result/eventresult を連続でこの秒数送り続けても先へ進まないなら異常とみなし停止する。
# 通常の Result→EVENT RESULT 送りは数秒で次状態(cardx/friendreq 等)へ抜けるため、想定外の
# オーバーレイ（例: iOS の「iMessage/FaceTime をオンにしますか？」等のシステムダイアログが
# Result 上に出ると result:0.76 で誤判定し中央タップが効かず無限ループ）を検知して止める。
RESULT_STUCK_SEC = 30.0
# gameplay（暗い画面）がこの秒数続いたら異常とみなす。1ライブは PAUSE 解決後 ≈115-125秒
# なので、余裕を見て 240秒。ミラーリング切断時の暗い「iPhoneが使用されました」オーバーレイ
# を gameplay と誤認して延々タップし続けるのを防ぐ（明るくないので menu watchdog では止まらない）。
GAMEPLAY_TIMEOUT_SEC = 240.0
# PAUSE がこの秒数続いたら異常とみなす。「再開」は毎ループ（≈0.6 秒おき）押しているので、
# 続くのは合成クリックが効かない再接続病か、PAUSE の上に別ダイアログが重なっている場合。
# 実測 2026-09-14: リザルト直後に gameplay を経ず pause へ入ったため gameplay_since が始動せず、
# GAMEPLAY_TIMEOUT が効かないまま 57 分間 0.6 秒周期で PAUSE→再開を繰り返した。
PAUSE_STUCK_SEC = 60.0
# gameplay がこの秒数継続して初めて「ライブ中」とみなす（クリア二重計上防止）。
# リザルト間の暗い遷移は数秒で終わるため、1ライブ(≈115s)未満の閾値にする。
MIN_LIVE_SEC = 20.0
# gameplay/pause 以外の画面がこの秒数だけ続いたら gameplay_since をリセットする。
# それ未満の中断（ライブ中の明るい演出で数秒 menu に落ちる・リザルト間の暗い遷移）は
# 「ライブは続いている」とみなす。2026-10-11 実機: 曲の演出で 5〜15 秒ごとに menu が
# 1〜2 秒挟まり、gameplay_since が毎回リセットされて was_in_live が一切立たず、
# クリアが 1 回も計上されないまま 2 回目の START で live_abandoned 停止した。
# 閾値は「演出の切れ目（実測 1〜3 秒）より十分長く・明るい画面への本格的な離脱
# （result/lifeshort 等は数秒〜十数秒）より十分短い」値にする。
GAMEPLAY_GAP_SEC = 4.0


def frame_brightness(frame_rgb):
    """明るさゲート用の平均輝度。上端 TITLEBAR_ROWS 行を TITLEBAR_EQUIV に置き換えて平均する。

    コーパスと DARK_THRESH の較正条件（タイトルバー付き、上端 38 行 ≈ 210）を再現し、
    ウィンドウ上端の透過部に写り込む背後のウィンドウの明暗に左右されないようにする。
    """
    h = frame_rgb.shape[0]
    top = min(TITLEBAR_ROWS, h)
    body = float(frame_rgb[top:].mean()) if h > top else 0.0
    return (body * (h - top) + TITLEBAR_EQUIV * top) / h


def load_templates():
    """各キーについて、基本ファイル `<stem>.png` に加えて端末別バリアント
    `<stem>_*.png`（例: song_select_16.png）も読み込む。照合はいずれかが当たればよい
    （match_best が最大スコアを採用）＝端末非依存（手動切替なし）。"""
    import glob
    out = {}
    for key, (fn, thr) in TEMPLATES.items():
        stem = fn[:-4] if fn.endswith(".png") else fn
        paths = sorted(glob.glob(os.path.join(TEMPLATE_DIR, stem + "*.png")))
        imgs = [cv2.imread(p, cv2.IMREAD_COLOR) for p in paths]
        imgs = [im for im in imgs if im is not None]
        if not imgs:
            print(f"[warn] テンプレート未読込: {fn}")
            continue
        out[key] = (imgs, thr)
    return out


def window_scale_wh(w, h):
    """幅 w・高さ h の**全体フレーム**の窓スケール係数を返す。

    テンプレは 671x348（iPhone 16 系）と 529x334（SE）の等倍で切り出されている。
    ミラーリング窓は少しずつ縮むことがある（実測 671x348 → 665x345 → 660x343 → 656x341、
    .autocal_circles.json の履歴）。そのとき UI 全体が同じ率で縮むので、SCALES の各段に
    この係数を掛けて照合する。基準サイズのフレームではちょうど 1.0 を返す。
    """
    ref = WIDE_REF_W if (h > 0 and w / h > WIDE_ASPECT_MIN) else SE_REF_W
    if w == ref:
        return 1.0
    return w / ref


def window_scale(frame):
    """全体フレーム（BGR/RGB どちらでも可）の窓スケール係数。"""
    h, w = frame.shape[:2]
    return window_scale_wh(w, h)


def match_best(frame_bgr, imgs, scale=None):
    """複数テンプレ候補(端末別variant)のうち最良の (score, center_px) を返す。

    `frame_bgr` は**必ず全体フレーム**を渡す（窓スケール係数はその幅から求める。
    切り出しで照合するときは match_in_box を使うこと）。切り出し画像を渡すときは
    `scale` に全体フレームから求めた係数を明示する。"""
    if scale is None:
        scale = window_scale(frame_bgr)
    best = (0.0, None)
    for im in imgs:
        score, pos = match_multiscale(frame_bgr, im, scale)
        if score > best[0]:
            best = (score, pos)
    return best


# きなこパン行の「回復」ボタンの縦許容（フレーム高に対する比）。
# ステラストーン行のボタンは実測で 0.26h ぶん離れているので、十分な余裕を持って分離できる。
RECOVER_ROW_TOL_FRAC = 0.13


def kinako_recover_point(frame_rgb, row_pos):
    """きなこパン行の「回復」ボタン中心 (x, y) をピンク色で直接探して返す。

    **必ず「きなこパン行が実在する」確認を通した後に呼ぶこと。**
    この関数は枯渇を判定しない（枯渇の判定は `kinakorow` の照合が担う）。

    固定オフセット方式（`ANCH_KINAKO_ROW`）はラベルのマッチ中心が基準なので、
    ラベルに接頭辞が付くと着弾点がそのぶん横へずれる。実機 2026-08-28、イベント配布の
    **「11周年きなこパン」**（所持154個）で着弾が x=443 となりボタン右端(441)を 2px 外し、
    6回連続で空振り → `life_short_persist` で停止した。**ボタンの位置自体は接頭辞の
    有無で変わらない**（両フレームとも x=386..441, y=164..185）ので、ボタンを直接
    見つけるほうが文言に依存しない。

    候補は「きなこパン行と同じ高さ・ラベルより右にある横長のピンク矩形」に限る。
    見つからなければ従来の固定オフセットへフォールバックする（行の実在は確認済みなので、
    フォールバック先も必ずきなこパン行の中に収まり、ステラ行には届かない）。
    フォールバックのオフセットには窓スケール係数を掛ける（窓が基準幅から縮むと
    UI 全体も同じ率で縮む。実測 2026-10-20: 656x341 では約 6px のずれ）。
    """
    h, w = frame_rgb.shape[:2]
    R = frame_rgb[:, :, 0].astype(int)
    G = frame_rgb[:, :, 1].astype(int)
    B = frame_rgb[:, :, 2].astype(int)
    pink = ((R > 200) & (G > 90) & (G < 175) & (B > 130) & (B < 200)
            & (R - G > 60)).astype(np.uint8)
    n, _lbl, stats, _cent = cv2.connectedComponentsWithStats(pink, 8)
    tol = RECOVER_ROW_TOL_FRAC * h
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 0.0015 * w * h or bw <= bh:      # 横長のボタンだけ
            continue
        cx, cy = x + bw / 2.0, y + bh / 2.0
        if cx <= row_pos[0] or abs(cy - row_pos[1]) > tol:   # 同じ行・ラベルより右
            continue
        d = abs(cy - row_pos[1])
        if best is None or d < best[0]:
            best = (d, (cx, cy))
    if best is not None:
        return best[1]
    s = window_scale(frame_rgb)
    return (row_pos[0] + ANCH_KINAKO_ROW[0] * s,
            row_pos[1] + ANCH_KINAKO_ROW[1] * s)


def kinako_plus_point(frame_rgb, recover_pt):
    """きなこパン行の数量ステッパー `[−][ 1 ][+]` の「+」中心 (x, y) を返す。無ければ None。

    **必ず「きなこパン行が実在する」確認を通し、その行から求めた `recover_pt`
    （`kinako_recover_point` の戻り値＝きなこ行の「回復」ボタン）を渡すこと。**

    探す範囲は「回復」ボタンと**同じ高さの帯（±0.04h）**で、ボタンの**左側**だけに限る。
    ステラストーン行は 0.26h 下にあり、しかもステッパーを持たない（数量欄に数字があるだけ）
    ので、この帯には入らない。条件（実測 2026-10-11, 671x348: 十字 9〜10px 角・
    青い箱 (285..363, 163..186) の中、回復ボタン中心の約 60px 左）:

    - 白い (min(R,G,B) > 170) 連結成分で、ほぼ正方形・幅と高さが 0.009〜0.022w
    - 中央の横一行と縦一列がほぼ埋まり、四隅は空いている（十字の形。数字やラベルの文字を除く）
    - 周囲の白以外の画素の 6 割以上が青（ステッパーの青い箱の中にある）

    候補が複数あれば最も右（＝「回復」に最も近い）を採る。「−」は横棒だけなので
    縦一列の条件で落ちる。
    """
    h, w = frame_rgb.shape[:2]
    band = int(round(0.04 * h))
    cy0 = int(round(recover_pt[1]))
    y0, y1 = max(0, cy0 - band), min(h, cy0 + band + 1)
    x0, x1 = max(0, int(recover_pt[0] - 0.15 * w)), int(recover_pt[0] - 0.04 * w)
    if x1 <= x0 or y1 <= y0:
        return None
    sub = frame_rgb[y0:y1, x0:x1].astype(int)
    R, G, B = sub[..., 0], sub[..., 1], sub[..., 2]
    white = (R > 170) & (G > 170) & (B > 170)
    blue = (B - R > 40) & (B > 110) & (R < 130)
    n, lbl, st, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8), 8)
    lo, hi = 0.009 * w, 0.022 * w
    best = None
    for i in range(1, n):
        x, y, bw, bh, _area = st[i]
        if not (lo <= bw <= hi and lo <= bh <= hi) or abs(int(bw) - int(bh)) > 2:
            continue
        comp = lbl[y:y + bh, x:x + bw] == i
        if comp[bh // 2].sum() < 0.7 * bw or comp[:, bw // 2].sum() < 0.7 * bh:
            continue
        if comp[0, 0] or comp[0, -1] or comp[-1, 0] or comp[-1, -1]:
            continue
        pad = max(2, int(bw) // 3)
        py0, px0 = max(0, y - pad), max(0, x - pad)
        around_white = white[py0:y + bh + pad, px0:x + bw + pad]
        around_blue = blue[py0:y + bh + pad, px0:x + bw + pad]
        if around_blue.sum() < 0.6 * max(1, (~around_white).sum()):
            continue
        cx, cy = x0 + x + bw / 2.0, y0 + y + bh / 2.0
        if best is None or cx > best[0]:
            best = (float(cx), float(cy))
    return best


def _kinako_qty_box(frame_rgb, plus_pt):
    """数量欄（「−」と「+」の間）の切り出し範囲 (x0, x1, y0, y1)。"""
    h, w = frame_rgb.shape[:2]
    return (max(0, int(plus_pt[0] - 0.06 * w)), int(plus_pt[0] - 0.012 * w),
            max(0, int(plus_pt[1] - 0.025 * h)), int(plus_pt[1] + 0.025 * h) + 1)


def kinako_qty_is_one(frame_rgb, plus_pt):
    """きなこ行の数量欄が「1」を表示しているか（ダイアログを開いた直後は 1）。

    数字「1」は縦一本（幅 1〜2px・高さ 7px@671x348）。3 以上は幅 5px 以上ある。
    min(R,G,B) > 140 の画素の外接矩形が細く縦長なら 1 とみなす。判らなければ False。
    """
    h, w = frame_rgb.shape[:2]
    x0, x1, y0, y1 = _kinako_qty_box(frame_rgb, plus_pt)
    sub = frame_rgb[y0:y1, x0:x1]
    if sub.size == 0:
        return False
    ys, xs = np.where(sub.min(axis=2) > 140)
    if len(xs) == 0:
        return False
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    return bool(bw <= 0.0045 * w + 0.5 and bh >= 0.015 * h)


_ZEN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def kinako_qty_ocr(frame_rgb, plus_pt):
    """数量欄の整数を OCR で読む（None=読めない）。

    「1」は Vision OCR が落とすことがある（実測 2026-10-20）ので、先に
    `kinako_qty_is_one`（画素の縦棒判定）を見る。それ以外の数字は OCR が
    「3」「7」「10」等を安定して読む。切り出しは「+」位置基準（行確認済み前提）。
    """
    if kinako_qty_is_one(frame_rgb, plus_pt):
        return 1
    x0, x1, y0, y1 = _kinako_qty_box(frame_rgb, plus_pt)
    best = None
    for text, _bx0, _by0, _bx1, _by1 in ocr.recognize(
            np.ascontiguousarray(frame_rgb[y0:y1, x0:x1])):
        m = re.fullmatch(r"\s*(\d+)\s*", text.translate(_ZEN_DIGITS))
        if m:
            best = int(m.group(1))
    return best


def kinako_per_pan_ocr(frame_rgb, row_pos):
    """きなこ行ラベル「…きなこパン：LIFE N 回復」から 1 個あたりの回復量 N を読む。

    接頭辞（共鳴→共期・共明・バン等）は誤読されるので `LIFE\\s*(\\d+)\\s*回復` の
    数字部分だけを使う（実測 2026-10-20）。ラベルは 2 行（名称＋使用期限）なので
    帯は行の上下に広めに取る。切り出しは**行のテンプレ一致位置基準**
    （固定pxは窓サイズで壊れる）。読めなければ None（呼び出し側で n=1 に縮退）。
    """
    h, w = frame_rgb.shape[:2]
    y0 = max(0, int(row_pos[1] - 0.065 * h))
    y1 = min(h, int(row_pos[1] + 0.055 * h))
    x0 = max(0, int(row_pos[0] - 0.14 * w))
    x1 = min(w, int(row_pos[0] + 0.26 * w))
    texts = ocr.recognize_texts(np.ascontiguousarray(frame_rgb[y0:y1, x0:x1]))
    for text in texts:
        m = re.search(r"LIFE\s*(\d+)\s*回復", text.translate(_ZEN_DIGITS))
        if m:
            return int(m.group(1))
    return None


def dialog_life_ocr(frame_rgb, row_pos):
    """LIFE 不足ダイアログ右上の「LIFE ♥ N」（現在 LIFE）を読む。読めなければ None。

    縦は行基準（ダイアログの上 0.15h 付近）、横はフレーム比で固定。ピルの白い
    1 桁数字（「6」）は素の OCR で落ちるので、読めなければ白文字二値化で読み直す。
    「0」は二値化しても読めない（実測 2026-10-20）→ None（呼び出し側は n=1 に縮退）。
    """
    h, w = frame_rgb.shape[:2]
    y0 = max(0, int(row_pos[1] - 0.155 * h))
    y1 = min(h, int(row_pos[1] - 0.068 * h))
    x0 = int(0.549 * w)
    x1 = int(0.701 * w)
    if y1 <= y0 or x1 <= x0:
        return None
    sub = np.ascontiguousarray(frame_rgb[y0:y1, x0:x1])
    texts = ocr.recognize_texts(sub)
    nums = [t for t in texts
            if re.fullmatch(r"\s*\d+\s*", t.translate(_ZEN_DIGITS))]
    if not nums:
        nums = [t for t in ocr.recognize_texts(sub, binarize=True)
                if re.fullmatch(r"\s*\d+\s*", t.translate(_ZEN_DIGITS))]
    if not nums:
        return None
    return int(nums[-1].translate(_ZEN_DIGITS))


# フレンド選択・編成画面の上部「♥-N」コストバッジを探す帯（フレーム比 y0, y1, x0, x1）。
# バッジの位置は画面・窓サイズで変わる（656x341 フレンド選択 y≈0.24, x≈0.62 /
# 529x334 編成・フレンド選択 y≈0.33, x≈0.69）ので、両方を含む帯で読む。
# 2026-10-20 実測: この帯で 656 の 1 枚は "-100"、コーパス 529 の編成 4 枚・フレンド選択 4 枚は
# すべて "-5"。数字の前に "-" がある語は帯内にこのバッジしか無かった。
_COST_BADGE_BOX = (0.15, 0.42, 0.55, 0.85)


def life_cost_ocr(frame_rgb):
    """フレンド選択・編成画面の上部バッジ「♥-N」からライブの LIFE コストを読む。
    バッジが無い・読めないときは None（呼び出し側は直前の値か KINAKO_ASSUMED_COST）。
    """
    h, w = frame_rgb.shape[:2]
    fy0, fy1, fx0, fx1 = _COST_BADGE_BOX
    sub = np.ascontiguousarray(
        frame_rgb[int(fy0 * h):int(fy1 * h), int(fx0 * w):int(fx1 * w)])
    for text in ocr.recognize_texts(sub):
        m = re.search(r"[-−]\s*(\d+)", text.translate(_ZEN_DIGITS))
        if m:
            return int(m.group(1))
    return None


def kinako_minus_point(frame_rgb, plus_pt):
    """同じステッパーの「−」中心。「−」は青い箱の左端にあり、「+」からの距離は端末間で同じ px
    （実測 671x348: 「−」の白い横棒 x 289..298, y 173..175、「+」中心 (354.5, 174.5)）。
    白い横棒を「+」と同じ高さ・その左 0.07〜0.11w で探す。見つからなければ None。"""
    h, w = frame_rgb.shape[:2]
    y0, y1 = max(0, int(plus_pt[1] - 0.015 * h)), int(plus_pt[1] + 0.015 * h) + 1
    x0, x1 = max(0, int(plus_pt[0] - 0.11 * w)), int(plus_pt[0] - 0.07 * w)
    sub = frame_rgb[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    ys, xs = np.where(sub.min(axis=2) > 170)
    if len(xs) < 6:
        return None
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if not (bw >= 0.009 * w and bh <= 0.012 * h + 1):     # 横長の棒だけ
        return None
    return (float(x0 + (xs.min() + xs.max()) / 2.0), float(y0 + (ys.min() + ys.max()) / 2.0))


def kinako_over_cap(frame_rgb, recover_pt):
    """きなこ行の「回復」ボタンの真上に赤い「上限を超えています」バッジが出ているか。
    数量が多すぎて LIFE 上限を超える時に出る（2026-10-11 実機。赤 R>180,G<110,B<110 が
    約 800px）。探す範囲はきなこ行の「回復」ボタンの上 0.10h・左右 ±0.10w だけ。"""
    h, w = frame_rgb.shape[:2]
    y0, y1 = max(0, int(recover_pt[1] - 0.10 * h)), max(0, int(recover_pt[1] - 0.02 * h))
    x0, x1 = max(0, int(recover_pt[0] - 0.10 * w)), min(w, int(recover_pt[0] + 0.10 * w))
    s = frame_rgb[y0:y1, x0:x1].astype(int)
    if s.size == 0:
        return False
    red = (s[..., 0] > 180) & (s[..., 1] < 110) & (s[..., 2] < 110)
    return int(red.sum()) >= KINAKO_OVERCAP_PX



def life_card_like(frame_rgb):
    """「ライフを30回復しました」等の LIFE 回復**カード**（背景タップで閉じる）か。

    中央に**薄い水色の大きなカード**（min(R,G,B)>185 かつ B−R が 12〜60）を出す。
    画面中央 (0.30..0.70, 0.30..0.62) に占める割合が LIFE_CARD_MIN 以上ならカードとみなす
    （実測 2026-10-11: 回復カード 0.46〜0.48。コーパス・フィクスチャの他画面は最大 0.38＝
    連続ライブダイアログ、LIFE不足ダイアログ 0.31）。背景タップ P_CARD_DISMISS で閉じる。

    **「ライフを全回復しました。」はこれでは拾えない**（白いカードで色が違う＝False。
    しかも背景タップでは閉じない）。あちらはテンプレ照合の `lifefull` で × を押す。
    """
    h, w = frame_rgb.shape[:2]
    s = frame_rgb[int(.30 * h):int(.62 * h), int(.30 * w):int(.70 * w)].astype(np.int16)
    if s.size == 0:
        return False
    m = (s.min(axis=2) > 185) & (s[..., 2] - s[..., 0] >= 12) & (s[..., 2] - s[..., 0] <= 60)
    return float(m.mean()) >= LIFE_CARD_MIN


def frame_diff(a_rgb, b_rgb):
    """2フレームの縮小グレー画像の平均絶対差（静止判定用。1回 1ms 未満）。"""
    def small(f):
        g = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY)
        return cv2.resize(g, (max(1, g.shape[1] // 4), max(1, g.shape[0] // 4)),
                          interpolation=cv2.INTER_AREA).astype(np.int16)
    if a_rgb.shape != b_rgb.shape:
        return 255.0
    return float(np.abs(small(a_rgb) - small(b_rgb)).mean())


def detect_card_x(frame_rgb):
    """カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）の閉じる「×」を、ヘッダの
    シアン→グリーン帯（明るい・低赤）を検出して位置特定する（端末非依存。テンプレ/座標に依存しない）。
    戻り値: × の中心ピクセル (x,y) または None。"""
    h, w = frame_rgb.shape[:2]
    R = frame_rgb[:, :, 0].astype(int)
    G = frame_rgb[:, :, 1].astype(int)
    B = frame_rgb[:, :, 2].astype(int)
    band = (G > 180) & (R < G - 20) & (B > 120)   # 明るいシアン〜グリーンのヘッダ帯
    band[:int(0.08 * h)] = False
    band[int(0.55 * h):] = False
    rowsum = band.sum(axis=1)
    rows = np.where(rowsum > 0.18 * w)[0]          # 横に広い連続帯＝カードのヘッダ
    if len(rows) < 2:
        return None
    y0, y1 = rows[0], rows[-1]
    cols = np.where(band[y0:y1 + 1].any(axis=0))[0]
    if len(cols) < 0.2 * w:
        return None
    # × はヘッダ帯の右端付近・帯の上端付近（中央だと縦長カードでズレるため上端基準）
    return (int(cols.max() - 0.012 * w), int(y0 + 0.018 * h))



def match_multiscale(frame_bgr, templ, scale=None):
    """マルチスケールでテンプレ照合。最大スコアと一致中心(ピクセル)を返す。

    照合段は SCALES の各段 × 窓スケール係数。`scale` 未指定なら渡された
    **全体フレーム**の幅から求める（`frame_bgr` は必ず全体フレームを渡すこと。
    切り出しの照合は match_in_box を使う）。
    """
    if scale is None:
        scale = window_scale(frame_bgr)
    fh, fw = frame_bgr.shape[:2]
    best = (0.0, None)
    for base in SCALES:
        s = base * scale
        t = templ
        if s != 1.0:
            t = cv2.resize(templ, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th > fh or tw > fw:
            continue
        res = cv2.matchTemplate(frame_bgr, t, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv > best[0]:
            best = (float(maxv), (maxloc[0] + tw / 2, maxloc[1] + th / 2))
    return best


def match_in_box(frame_bgr, imgs, box, scale=None):
    """フレームの一部だけを照合して (score, 全画面座標の中心) を返す。

    フレーム全体のマルチスケール照合は重く（実測 246ms/回）、ライブ中に毎 0.25 秒
    走らせると打鍵ループがほぼ止まる（実測 3.3 FPS）。位置が安定している見出しは
    探索範囲を絞れば同じ結果をはるかに安く得られる。

    窓スケール係数は **切り出す前の全体フレームから求めて切り出し側へ渡す**。
    切り出し画像の幅から係数を推定すると誤る（切り出しは box の幅になる）。
    """
    h, w = frame_bgr.shape[:2]
    if scale is None:
        scale = window_scale_wh(w, h)
    x0, y0, x1, y1 = box
    px0, py0 = int(w * x0), int(h * y0)
    sub = frame_bgr[py0:int(h * y1), px0:int(w * x1)]
    if sub.size == 0:
        return 0.0, None
    score, pos = match_best(sub, imgs, scale)
    if pos is None:
        return score, None
    return score, (pos[0] + px0, pos[1] + py0)


def match_topmost(frame_bgr, imgs, thresh, min_gap_px=18, scale=None):
    """閾値を超えるマッチのうち **最も上（yが小さい）** の中心を返す: (score, (x, y)) or (0, None)。

    フレンド一覧のように同じラベルが複数行に並ぶ画面で、「一番上の行」を確実に選ぶために使う。
    match_best は最良スコアの1件しか返さないため、どの行に当たるかが実行ごとに変わる。
    `frame_bgr` は必ず全体フレームを渡す（窓スケール係数はその幅から求める）。
    """
    if scale is None:
        scale = window_scale(frame_bgr)
    best = (0.0, None)
    for templ in imgs:
        fh, fw = frame_bgr.shape[:2]
        for base in SCALES:
            s = base * scale
            t = templ if s == 1.0 else cv2.resize(templ, None, fx=s, fy=s,
                                                  interpolation=cv2.INTER_AREA)
            th, tw = t.shape[:2]
            if th > fh or tw > fw:
                continue
            res = cv2.matchTemplate(frame_bgr, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= thresh)
            for y, x in zip(ys, xs):
                cy = y + th / 2
                if best[1] is None or cy < best[1][1] - min_gap_px:
                    best = (float(res[y, x]), (x + tw / 2, cy))
    return best


class AutoLive:
    def __init__(self, max_loops, dry_run=False, verbose=False, max_seconds=None,
                 tap_mode=TAP_MODE_DEFAULT, note_trigger=NOTE_TRIGGER_FRAC,
                 note_lead=NOTE_ROI_LEAD, note_roi=NOTE_ROI_RADIUS, holds=False,
                 green_hold=False, hold_max_sec=HOLD_MAX_SEC,
                 engine="roi", esc_enabled=True, flick=False, predict=False,
                 auto_circles=False, tap_jitter=True, keep_selection=False):
        self.max_loops = max_loops
        self.dry_run = dry_run
        self.verbose = verbose
        self.max_seconds = max_seconds
        # 楽曲選択で曲・難易度を選び直さない（累計イベント以外の例外運用）。
        # 既定 False = 従来どおり「Don't Analyze Me」+ EASY を固定する。
        self.keep_selection = keep_selection
        self.tap_mode = tap_mode
        self.note_trigger = note_trigger
        self.note_lead = note_lead
        self.note_roi = note_roi
        self.templates = load_templates()
        self.win = driver.find_window()
        self.loops_done = 0
        self.was_in_live = False
        self.starts_since_clear = 0     # クリアを挟まずに押した START の回数（ライブ放棄の検知）
        self.home_taps = 0              # ホームで EVENT リボンを続けて押した回数（無反応の迂回判定）
        self.last_start_ts = 0.0        # 直近の START 押下時刻（同じ画面での押し直しを数えないため）
        self.circle_i = 0
        self.closex_i = 0           # closex 候補位置の巡回インデックス
        self.life_recovers = 0      # 連続 LIFE 回復回数（ログ表示用）
        self.life_cost = None       # ライブの LIFE コスト（friendselect/formation のバッジで読む）
        self._kinako_prev_life = None  # 前回「回復」を押した時点の現在 LIFE（増加判定の比較元）
        self._life_no_gain = 0      # 「回復」を押したのに LIFE が増えない読みの連続回数
        self.advance_alt = {}       # 送り画面ごとに、右側タップが効かなかったら中央へ切り替える印
        self.advance_since = None   # (Result 系の状態, その状態が続き始めた時刻)
        self.recovers = 0           # アプリ再起動からの復帰試行回数（暴走防止）
        self.in_recovery = False    # 復帰導線の途中か（周回に戻ると下りる）
        self.net_retries = 0        # 通信エラーの連続リトライ回数
        self.gameplay_since = None  # gameplay 連続継続の開始時刻（異常検知用）
        self.pause_since = None     # pause 連続継続の開始時刻（「再開」が効かない停滞の検知用）
        # --- タイミング検出（timing モード）用 ---
        self.note_baseline = [None] * len(CIRCLES)  # 円ごとの white割合 EMA ベースライン
        self.note_last_tap = [0.0] * len(CIRCLES)   # 円ごとの直近タップ時刻（デバウンス）
        self.holds = holds          # 長押し（緑）対応の有効/無効（旧・輝度方式）
        self.green_hold = green_hold  # 緑ノーツの長押し（色方式）
        self.hold_max_sec = hold_max_sec
        self.note_hi_frames = [0] * len(CIRCLES)  # 円ごとのトリガー超持続フレーム数（長押し検出）
        self.note_rearmed = [True] * len(CIRCLES)   # 発火後に白率が一度下がると True（次ノーツ受付）
        self.hold_idx = None        # 現在ホールド中の円index（Noneなら非ホールド）
        self.hold_start = 0.0       # ホールド開始時刻（HOLD_MAX_SEC上限用）
        # --- ノーツ種別対応（赤=フリック）。到達直前ROIの色で判定（§17.9） ---
        self.flick = flick          # 赤ノーツでフリック（タップ→外向きスワイプ）を行う
        self.note_red_seen = [0.0] * len(CIRCLES)  # 円ごとに到達直前ROIで赤を見た直近時刻
        # --- 緑ホールド（--green-hold）---
        self.green_since = [None] * len(CIRCLES)   # 緑が approach に現れた時刻（消えたら None）
        self.green_px = [0] * len(CIRCLES)         # 直近フレームの緑画素数
        self.green_peak = [0] * len(CIRCLES)       # 今回の通過でのピーク（ログ用。現在値は着弾前に減る）
        self.ghold_release_at = None               # 解除予定時刻（緑が通過し切ったら入る）
        self.ghold_transit = 0.0                   # このホールドで実測した飛行時間
        # --- 種別先読み（--predict）。track を並走させ緑ホールド/赤フリックを出し分け ---
        self.predict = predict      # 既定 False（OFF時は現行と同一パス）
        self.forecast = None        # note_engine.TypeForecast（predict時に遅延生成）
        self.hold_release_at = None # 緑ホールドの解除予定時刻（ETA駆動。predict時のみ）
        # --- 円自動キャリブレーション（--auto-circles） ---
        self.auto_circles = auto_circles  # ライブ突入時に円座標を画像から自動補正
        self.circles_calibrated = False   # プロセス内で一度だけ実施
        self.autocal_next_try = 0.0       # 次に再試行してよい時刻（成功するまで繰り返す）
        self.autocal_samples = []         # 多数決用に貯める検出サンプル（content相対）
        self.stop_reason = None           # 安全停止の理由（None=正常終了）。終了コードに反映する
        self._last_win_check = 0.0        # ウィンドウ矩形を最後に取り直した時刻
        # ループ内訳を「ライブ中（gameplay/pause）」と「それ以外」に分けて集計する。
        # 旧来は1つのバケットに混ぜていたため、ライブ後のメニュー画面（明るい側の
        # 全段照合≈1秒/フレーム）が混ざり、ライブ中だけの内訳が分からなかった
        # （2026-10-20 の約16FPS 原因調査用）。sec はそのバケットの状態に費やした
        # 実時間（イテレーション周期の和）で、ライブ中FPSの分母と「2ライブ連結」
        # 警告（LIVE_MERGED_WARN_SEC）に使う。
        self._prof = {"live": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0},
                      "other": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0}}
        # detect() がフレームをどの経路で処理したかのカウンタ（ライブ終了時に
        # _live_report で吐いてリセット）。経路: dark(暗い)/dim_rings(薄暗い＋
        # リング確認)/bright(明るい側の全段照合)/recheck(間引き照合が走った)/
        # rescue(救済照合を投げた)。__new__ 生成のインスタンスでは存在しない
        # ことがあるので、加算は _detect_path() 経由（getattr 保護）。
        self._detect_paths = {}
        self._iter_t0 = time.time()  # _prof へ按分するイテレーション開始時刻
        self.suppress_cardx_until = 0.0   # この時刻までは cardx を無視（フレンド選択直後）
        self.tap_count = 0                # 1ライブ中の打鍵回数（検出不足か位置ズレかの切り分け用）
        self.frame_count = 0              # 1ライブ中の判定フレーム数（実効ループ周波数の把握）
        self._roi_scale_key = None        # ROI半径スケールのキャッシュキー（CIRCLES変更で無効化）
        self._roi_scales = None
        # --- 実験的トラッキングエンジン（engine="track"）用 ---
        self.engine = engine        # "roi"(既定・現行) / "track"(スポーン検出+追跡)
        self._ne = None             # note_engine モジュール（遅延import）
        self.tracker = None         # note_engine.Tracker
        self.acted = set()          # 既に打鍵したノーツtrack id
        self.last_input_ts = 0.0    # 最後に genuine 入力を出した時刻（キープアライブ用）
        self.esc_since = None       # ESC を押し始めた時刻（長押し停止の判定用）
        self.esc_enabled = esc_enabled  # False で ESC キルスイッチ無効（自律実行用）
        self.last_activate = 0.0
        self.t_start = time.time()
        if auto_circles:
            self._load_cached_circles()   # 前回の補正結果があれば起動時点で適用（要 t_start）
        self.menu_since = None      # 同じメニューに留まり始めた時刻
        self.result_since = None    # result/eventresult を送り始めた時刻（無限ループ検知用）
        self._last_dark_check = 0.0  # 暗い画面で pause/songselect を最後に照合した時刻（間引き用）
        self.songsel_nochg = 0      # NEXT を押しても画面が変わらなかった連続回数
        self._gp_left_ts = self.t_start  # gameplay/pause を最後に見た時刻（ギャップ許容用）
        self.dbg_dir = "/tmp/i7dbg"
        os.makedirs(self.dbg_dir, exist_ok=True)
        # (top,bottom) px。**固定** (TITLEBAR_ROWS, h-9)。円の較正キャッシュ・OFF_* と同じ基準。
        self.content = (TITLEBAR_ROWS, int(self.win["h"]) - 9)
        # --- 打鍵の着弾点ジッター（--no-tap-jitter で無効化） ---
        # 半径は円リング半径 R との比で持つ（端末差の吸収）。R は win 取得後にしか
        # 決まらないので、ここで px へ換算して TapJitter に渡す。
        self.jitter = None
        if tap_jitter:
            self.jitter = self._build_jitter()
        self.hold_point = None   # ホールド中の着弾点（down で確定し move/up で使い回す）

    # --- 座標変換: 内容相対小数 -> 画面ポイント ---
    def content_to_screen(self, xf, yf):
        top, bottom = self.content
        ch = bottom - top
        px = self.win["x"] + self.win["w"] * xf
        # 内容矩形内の相対yを、ウィンドウ内ピクセル→ポイントへ。grabはポイント等倍なので
        # 行ピクセル=ポイントとみなせる（mssがポイント解像度で返すため）
        py = self.win["y"] + (top + yf * ch)
        return px, py

    def pixel_to_screen(self, px_in_frame, py_in_frame):
        return (self.win["x"] + px_in_frame, self.win["y"] + py_in_frame)

    # --- 低レベル操作 ---
    def _click_screen(self, px, py):
        if self.dry_run:
            return
        mode = os.environ.get("I7_CLICK_MODE", "0")
        if mode != "0":
            return self._click_screen_exp(px, py, mode)
        # 実カーソルをクリック点へワープ + MouseMoved + Down/Up を **HIDSystemState
        # イベントソース**で送る。これにより iPhone ミラーリングが「genuine な入力あり」と
        # 判定し、ライブ中の自動 PAUSE を防ぐ（§17.6 F）。実カーソルが動く点に注意。
        Quartz.CGWarpMouseCursorPosition((px, py))
        mv = Quartz.CGEventCreateMouseEvent(
            _HID_SRC, Quartz.kCGEventMouseMoved, (px, py), 0)
        dn = Quartz.CGEventCreateMouseEvent(
            _HID_SRC, Quartz.kCGEventLeftMouseDown, (px, py), 0)
        up = Quartz.CGEventCreateMouseEvent(
            _HID_SRC, Quartz.kCGEventLeftMouseUp, (px, py), 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, mv)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, dn)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)

    def _click_screen_exp(self, px, py, mode):
        """実験用: genuine入力の方式切替（I7_CLICK_MODE）。PAUSE防止の有効方式探索（§17.7）。"""
        lpx = getattr(self, "_last_px", px)
        lpy = getattr(self, "_last_py", py)
        dx, dy = px - lpx, py - lpy
        self._last_px, self._last_py = px, py
        def moved(x, y, ddx=0, ddy=0, tap=Quartz.kCGHIDEventTap):
            ev = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventMouseMoved, (x, y), 0)
            if ddx or ddy:
                Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventDeltaX, int(ddx))
                Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventDeltaY, int(ddy))
            Quartz.CGEventPost(tap, ev)
        def click(x, y):
            dn = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventLeftMouseDown, (x, y), 0)
            up = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventLeftMouseUp, (x, y), 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, dn)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        if mode == "delta":              # MouseMoved に実delta を載せる
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py, dx, dy)
            click(px, py)
        elif mode == "movepair":         # 2点間を実移動（delta付き）してからクリック
            mid_x, mid_y = (lpx + px) / 2, (lpy + py) / 2
            Quartz.CGWarpMouseCursorPosition((mid_x, mid_y))
            moved(mid_x, mid_y, (px - lpx) / 2, (py - lpy) / 2)
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py, (px - mid_x), (py - mid_y))
            click(px, py)
        elif mode == "drag":             # 指のような Down→ドラッグ→Up
            Quartz.CGWarpMouseCursorPosition((px, py))
            dn = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventLeftMouseDown, (px, py), 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, dn)
            nx, ny = px + 6, py + 6
            Quartz.CGWarpMouseCursorPosition((nx, ny))
            dg = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventLeftMouseDragged, (nx, ny), 0)
            Quartz.CGEventSetIntegerValueField(dg, Quartz.kCGMouseEventDeltaX, 6)
            Quartz.CGEventSetIntegerValueField(dg, Quartz.kCGMouseEventDeltaY, 6)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, dg)
            up = Quartz.CGEventCreateMouseEvent(_HID_SRC, Quartz.kCGEventLeftMouseUp, (nx, ny), 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        elif mode == "scroll":           # クリック + スクロールホイール(genuine活動)
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py, dx, dy)
            click(px, py)
            sc = Quartz.CGEventCreateScrollWheelEvent(_HID_SRC, Quartz.kCGScrollEventUnitPixel, 1, 1)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, sc)
        elif mode == "assoc":            # マウス分離→相対move→再結合→クリック
            Quartz.CGAssociateMouseAndMouseCursorPosition(False)
            moved(px, py, dx if dx else 5, dy if dy else 5)
            Quartz.CGAssociateMouseAndMouseCursorPosition(True)
            Quartz.CGWarpMouseCursorPosition((px, py))
            click(px, py)
        elif mode == "session":          # Session+HID 両tapに送る
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py, dx, dy, tap=Quartz.kCGSessionEventTap)
            moved(px, py, dx, dy)
            click(px, py)
        elif mode == "none":             # F以前の方式: source=None でクリック
            Quartz.CGWarpMouseCursorPosition((px, py))
            for et in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown,
                       Quartz.kCGEventLeftMouseUp):
                ev = Quartz.CGEventCreateMouseEvent(None, et, (px, py), 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        elif mode == "key":              # baselineクリック + F13キー(無害)で genuine 入力
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py, dx, dy)
            click(px, py)
            for down in (True, False):
                ke = Quartz.CGEventCreateKeyboardEvent(_HID_SRC, 105, down)  # F13
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ke)
        else:                            # 不明mode→baseline相当
            Quartz.CGWarpMouseCursorPosition((px, py))
            moved(px, py)
            click(px, py)

    def _press(self, px, py, kind):
        """ホールド用に down/move/up を個別に送る（HIDソース＋ワープで genuine 入力）。
        kind: 'down'(押下開始) / 'move'(押下保持中のドラッグ=PAUSE防止) / 'up'(離す)。"""
        if self.dry_run:
            return
        Quartz.CGWarpMouseCursorPosition((px, py))
        et = {"down": Quartz.kCGEventLeftMouseDown,
              "move": Quartz.kCGEventLeftMouseDragged,
              "up": Quartz.kCGEventLeftMouseUp}[kind]
        ev = Quartz.CGEventCreateMouseEvent(_HID_SRC, et, (px, py), 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def click_content(self, xf, yf):
        self._click_screen(*self.content_to_screen(xf, yf))

    def click_window(self, xf, yf):
        """ウィンドウ相対小数(0..1)でクリック。スクショ実測座標はこちらで扱う
        （スクショは全ウィンドウ＝ウィンドウ相対のため。content補正を掛けない）。"""
        self._click_screen(self.win["x"] + self.win["w"] * xf,
                           self.win["y"] + self.win["h"] * yf)

    def click_match(self, pos_px):
        self._click_screen(*self.pixel_to_screen(*pos_px))

    # --- 端末非依存クリック: ゲーム中央 + 固定pxオフセット ---
    def game_center_px(self):
        """ゲーム描画領域の中央（画面pt）。横は全幅(中央=win幅/2)、縦は内容矩形中央。
        ダイアログは中央配置・UIは端末間で同pxサイズのため、中央+pxオフセットで端末非依存に押せる。"""
        top, bottom = self.content
        return (self.win["x"] + self.win["w"] / 2.0,
                self.win["y"] + (top + bottom) / 2.0)

    def _win_scale(self):
        """クリック用の窓スケール係数。フレーム幅＝win の幅（grab はポイント等倍）から
        求める。`__new__` 生成で win が無い経路では 1.0（従来どおり無補正）。"""
        win = getattr(self, "win", None)
        if not win or not win.get("w"):
            return 1.0
        return window_scale_wh(win["w"], win.get("h") or 0)

    def click_center_off(self, off):
        """ゲーム中央 + 固定pxオフセットでクリック。オフセットは基準窓（671/529 幅）の
        実測値なので、窓スケール係数を掛けてから足す（窓が縮むと UI も同じ率で縮む）。"""
        cx, cy = self.game_center_px()
        s = self._win_scale()
        self._click_screen(cx + off[0] * s, cy + off[1] * s)

    def click_anchor(self, pos_px, off):
        """テンプレのマッチ位置(フレームpx) + 固定pxオフセットでクリック（画像追従・端末非依存）。
        オフセットは基準窓の実測値なので窓スケール係数を掛ける（656x341 では最大約 6px のずれ）。"""
        s = self._win_scale()
        self._click_screen(*self.pixel_to_screen(pos_px[0] + off[0] * s,
                                                 pos_px[1] + off[1] * s))

    def _enter_recovery(self, frame):
        """復帰導線に入ったことを記録する。続行してよければ True。

        **カウントは episode 単位。** タイトル画面は白飛びするローディングを挟んで
        何度も再検出されるので、フレームごとに数えると一瞬で上限に達してしまう
        （実測 2026-08-03: ローディングが title として 0.897 で当たる）。
        周回に戻れたら（gameplay/songselect 等）フラグが下り、次に迷い込んだときが
        2 回目の復帰になる。
        """
        if self.in_recovery:
            return True
        self.in_recovery = True
        self.recovers += 1
        if self.recovers > MAX_RECOVERS:
            from PIL import Image as _I
            fn = os.path.join(self.dbg_dir,
                              f"recover_loop_{int(time.time() - self.t_start)}.png")
            _I.fromarray(frame).save(fn)
            self.log(f"[warn] 復帰を {MAX_RECOVERS} 回試みても周回に戻れない "
                     f"→ {fn} 保存して停止")
            self.stop_reason = "recover_loop"
            return False
        return True

    # --- タイミング検出（timing モード） ---
    def _roi_scale(self, idx):
        """円 idx のROI半径スケール（レーン間のタイミング偏りを打ち消す）。

        ノーツは ARC_CENTER から各円へ**同じ拍で**飛んでくるので、遠い円ほど速い。
        ROI半径が全レーン固定だと「中心から r px 手前で発火」の r が同じでも、
        速いレーンでは r を横切るのに要する**時間が短い**＝時間的に早く発火する。
        実測(671x348): 移動距離は 144.8〜193.6px（1.34倍差）で、発火位置は移動距離比の
        12.1%〜16.2% とレーン間で 4.1 ポイントばらついていた。これが GOOD 過多の一因。

        半径を「その円の移動距離 ÷ 平均移動距離」で伸縮すると r/d が全レーンで一定になり、
        発火が到達までの**同じ時間割合**に揃う。平均は変えないので note_roi の意味は保つ。
        """
        if not ROI_SCALE_BY_DISTANCE:
            return 1.0
        key = tuple(CIRCLES)
        if self._roi_scale_key != key:
            top, bottom = self.content
            ch = bottom - top
            w = self.win["w"]
            dists = []
            for xf, yf in CIRCLES:
                dx = (ARC_CENTER[0] - xf) * w
                dy = (ARC_CENTER[1] - yf) * ch
                dists.append((dx * dx + dy * dy) ** 0.5)
            mean = sum(dists) / len(dists)
            self._roi_scales = [d / mean if mean > 0 else 1.0 for d in dists]
            self._roi_scale_key = key
        return self._roi_scales[idx]

    def _build_jitter(self, win_w=None):
        """CIRCLE_R_FRAC 系の比率定数から、現在のウィンドウ幅で TapJitter を1つ組み立てる。

        半径は円リング半径 R（ウィンドウ幅相対）との比で持つため、ウィンドウ幅が
        変わるたび（_refresh_window 参照）作り直す必要がある。win_w を省略すると
        self.win["w"] を使うが、_refresh_window は self.win をまだ新しい寸法に
        更新する前にこれを呼ぶ必要があるため、新しい幅を明示的に渡せるようにしてある。
        """
        w = win_w if win_w is not None else self.win["w"]
        r_px = w * CIRCLE_R_FRAC
        return tap_jitter_module.TapJitter(
            len(CIRCLES),
            bias_sigma=r_px * JITTER_BIAS_SIGMA_R,
            tap_sigma=r_px * JITTER_TAP_SIGMA_R,
            max_r=r_px * JITTER_MAX_R)

    def _tap_point(self, idx):
        """CIRCLES[idx] にジッターを乗せた content 相対座標を返す。

        **CIRCLES は --auto-circles で in-place 更新されるため毎回読む（キャッシュ禁止）。**
        x はウィンドウ幅、y は内容矩形高で正規化する（分母が違う）。px 空間で等方な
        散らばりを作ってから変換しないと、着弾点が楕円状に歪む。

        判定 ROI（_circle_roi_px）はこれを使わない。ジッターはクリック先だけの話。
        """
        xf, yf = CIRCLES[idx]
        if self.jitter is None:
            return xf, yf
        top, bottom = self.content
        w = self.win["w"]
        ch = bottom - top
        if w <= 0 or ch <= 0:
            return xf, yf
        dx, dy = self.jitter.offset_px(idx)
        return xf + dx / w, yf + dy / ch

    def _hold_pt(self, idx):
        """ホールド中の着弾点。down で確定した点を move/up で使い回す。

        毎回引き直すと指が微動することになる。ホールドは実機挙動が繊細な領域
        （緑ノーツ対応は実測 3.3% で既定 OFF のまま打ち切られている）なので変えない。
        hold_point が無い場合（ありえないが防御的に）は素の円中心へ落とす。
        """
        return self.hold_point if self.hold_point is not None else CIRCLES[idx]

    def _circle_roi_px(self, idx):
        """円 idx の判定ROI（フレームpx）を返す: (x0, y0, x1, y1)。
        円中心を ARC_CENTER 方向へ note_lead ぶん寄せて早撃ち補正する。"""
        xf, yf = CIRCLES[idx]
        # ARC_CENTER 方向へ寄せる（ノーツは中心側から来るので、円の少し中心寄りで先に検知）
        xf += (ARC_CENTER[0] - xf) * (self.note_lead / 0.5)
        yf += (ARC_CENTER[1] - yf) * (self.note_lead / 0.5)
        top, bottom = self.content
        ch = bottom - top
        cx = self.win["w"] * xf
        cy = top + yf * ch
        r = self.win["w"] * self.note_roi * self._roi_scale(idx)
        return (int(cx - r), int(cy - r), int(cx + r), int(cy + r))

    def _roi_white_frac(self, frame, idx):
        """円 idx のROI内で「白っぽい（ノーツ）」画素の割合 [0..1]。"""
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self._circle_roi_px(idx)
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(w, x1); y1 = min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        roi = frame[y0:y1, x0:x1]
        white = (roi.min(axis=2) > NOTE_WHITE_V)
        return float(white.mean())

    def _approach_red(self, frame, idx):
        """円 idx の到達直前ROI（中心寄り FLICK_APPROACH_FRAC）に赤ノーツ（=フリック）が
        あるか。frame は RGB。明るい画素平均で R が G,B より十分大きければ赤とみなす。"""
        h, w = frame.shape[:2]
        xf, yf = CIRCLES[idx]
        xf = xf + (ARC_CENTER[0] - xf) * (1 - FLICK_APPROACH_FRAC)
        yf = yf + (ARC_CENTER[1] - yf) * (1 - FLICK_APPROACH_FRAC)
        top, bottom = self.content; ch = bottom - top
        cx = int(self.win["w"] * xf); cy = int(top + yf * ch)
        r = int(self.win["w"] * self.note_roi)
        x0, y0, x1, y1 = max(0, cx - r), max(0, cy - r), min(w, cx + r), min(h, cy + r)
        if x1 <= x0 or y1 <= y0:
            return False
        roi = frame[y0:y1, x0:x1].reshape(-1, 3).astype(int)
        bright = roi[roi.max(axis=1) > FLICK_RED_MIN_V]
        if len(bright) < 8:
            return False
        rr, gg, bb = bright.mean(axis=0)
        return (rr - gg) > FLICK_RED_DELTA and (rr - bb) > FLICK_RED_DELTA

    def _approach_green(self, frame, idx):
        """円 idx の到達直前ROIに居る「緑画素の数」を返す。frame は RGB。

        **数で判定する理由**: 明るい画素の色平均や白率では判定文字「GOOD」と区別できない
        （実測 2026-08-04: 緑ノーツの白率 0.00〜0.40 に対し GOOD 文字 0.37 で完全に重なる）。
        画素数なら本物 700〜1064 / ノイズ 21〜85 と 8 倍差がつく。

        検色点は赤(FLICK_APPROACH_FRAC=0.65)ではなく GREEN_APPROACH_FRAC(0.70)。
        0.65 だと GOOD 文字が ROI に入る。
        """
        h, w = frame.shape[:2]
        xf, yf = CIRCLES[idx]
        xf = xf + (ARC_CENTER[0] - xf) * (1 - GREEN_APPROACH_FRAC)
        yf = yf + (ARC_CENTER[1] - yf) * (1 - GREEN_APPROACH_FRAC)
        top, bottom = self.content
        ch = bottom - top
        cx = int(self.win["w"] * xf)
        cy = int(top + yf * ch)
        r = int(self.win["w"] * self.note_roi)
        x0, y0, x1, y1 = max(0, cx - r), max(0, cy - r), min(w, cx + r), min(h, cy + r)
        if x1 <= x0 or y1 <= y0:
            return 0
        roi = frame[y0:y1, x0:x1].astype(int)
        R, G, B = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
        return int(((G - R > 25) & (G - B > 25) & (G > 100)).sum())

    def _flick(self, idx):
        """円 idx で フリック: 押下→外向き(中心と反対)へドラッグ→離す。種別=赤ノーツ用。"""
        sx, sy = self.content_to_screen(*self._tap_point(idx))
        # 外向き方向（ARC_CENTER から円へ向かうベクトル）
        cxs, cys = self.content_to_screen(*ARC_CENTER)
        dx, dy = sx - cxs, sy - cys
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        dist = self.win["w"] * FLICK_DIST
        ux, uy = dx / norm * dist, dy / norm * dist
        self._press(sx, sy, "down")
        for s in range(1, FLICK_STEPS + 1):
            self._press(sx + ux * s / FLICK_STEPS, sy + uy * s / FLICK_STEPS, "move")
            time.sleep(0.012)
        self._press(sx + ux, sy + uy, "up")

    def _note_present(self, frame, idx):
        """円 idx にノーツが到達したか（過渡的な明るさの跳ね上がりで判定）。
        円ごとのEMAベースライン（静穏時のみ更新）に対し note_trigger を超えたら True。"""
        wf = self._roi_white_frac(frame, idx)
        base = self.note_baseline[idx]
        if base is None:
            self.note_baseline[idx] = wf
            return False
        fired = (wf - base) > self.note_trigger
        # 静穏フレーム（ノーツ非到達）のみベースラインへ取り込む＝持続的な演出を吸収。
        if wf < NOTE_BASELINE_FRAC and not fired:
            self.note_baseline[idx] = base + (wf - base) * NOTE_BASELINE_EMA
        return fired

    def _autocal_key(self):
        """補正キャッシュのキー。ウィンドウ寸法が変われば別端末/別レイアウトとみなす。"""
        return f'{int(self.win["w"])}x{int(self.win["h"])}'

    def _load_cached_circles(self):
        """前回の補正結果を読み、同じウィンドウ寸法なら起動時点で CIRCLES に適用する。
        壊れたキャッシュは黙って無視する（現行値のまま＝安全側）。"""
        try:
            with open(AUTOCAL_CACHE, encoding="utf-8") as fh:
                cached = json.load(fh).get(self._autocal_key())
            if not cached or len(cached) != len(CIRCLES):
                return
            cand = [(float(x), float(y)) for x, y in cached]
            # キャッシュもコミットと同じ幾何検証を通す（2026-10-12）。
            # 装飾の誤検出で一度悪い値が保存されると、prior として読み込まれて以後の
            # 補正が誤値を基準に回り続けていた（実測: 円4 が 27px 外れた値が復元→再確定）。
            ok, why = self._circles_geometry_ok(cand, list(CIRCLES))
            if not ok:
                self.log(f"[auto-circles] キャッシュを棄却（幾何検証失敗: {why}）: {cand}")
                return
            CIRCLES[:] = cand
            self.circles_calibrated = True
            self.log(f"[auto-circles] 前回の補正値を復元（{self._autocal_key()}）: {CIRCLES}")
        except Exception:
            pass

    def _save_cached_circles(self):
        try:
            data = {}
            if os.path.exists(AUTOCAL_CACHE):
                with open(AUTOCAL_CACHE, encoding="utf-8") as fh:
                    data = json.load(fh)
            data[self._autocal_key()] = [list(c) for c in CIRCLES]
            with open(AUTOCAL_CACHE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except Exception as e:
            self.log(f"[auto-circles] 補正値の保存に失敗（動作には影響なし）: {e}")

    def _circles_geometry_ok(self, circles, prior):
        """較正コミット前の幾何検証（2026-10-12、誤検出で悪化する構造欠陥の対策）。

        i7 のタップ円はほぼ左右対称（鏡像）: 外側ペア(円1,4)の y が揃い、内側ペア(円2,3)の
        y が揃い、x 座標も画面中心からほぼ等距離。装飾・スコア文字を Hough が円と誤検出した
        場合この対称性が崩れる（実測: 円4 が 27px 外れ、円4のノーツを丸ごと見送った）。
        あわせて「prior から一気に大きく動く」補正を弾き、誤確定が次回 prior に
        乗って回り続けるラチェットを断つ。
        """
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = circles
        if abs(y1 - y4) > AUTOCAL_SYMMETRY_TOL:
            return False, f"外側ペアの高さ不一致 |y1-y4|={abs(y1 - y4):.3f}"
        if abs(y2 - y3) > AUTOCAL_SYMMETRY_TOL:
            return False, f"内側ペアの高さ不一致 |y2-y3|={abs(y2 - y3):.3f}"
        outer = abs(abs(x4 - 0.5) - abs(x1 - 0.5))
        inner = abs(abs(x3 - 0.5) - abs(x2 - 0.5))
        if outer > AUTOCAL_SYMMETRY_TOL or inner > AUTOCAL_SYMMETRY_TOL:
            return False, f"左右非対称 outer={outer:.3f} inner={inner:.3f}"
        jump = max(((nx - px) ** 2 + (ny - py) ** 2) ** 0.5
                   for (nx, ny), (px, py) in zip(circles, prior))
        if jump > AUTOCAL_JUMP_TOL:
            return False, f"prior からの跳躍 {jump:.3f} > {AUTOCAL_JUMP_TOL}"
        return True, ""

    def _auto_calibrate_circles(self, frame):
        """--auto-circles: ライブ突入時にタップ円リングを検出し CIRCLES を実測へ補正。
        4円すべてが prior の許容誤差内で一致したときだけ in-place 置換し（roi/keepalive/
        rotate 全読者へ反映）、失敗時は現行値を維持する（誤検出で悪化させない）。
        失敗時は calibrated を立てず、呼び出し側が AUTOCAL_RETRY_SEC 間隔で
        **成功するまでライブ中ずっと再試行**する。"""
        try:
            if self._ne is None:
                import note_engine as NE
                self._ne = NE
            det = self._ne.detect_circles(frame, self.win, self.content)
            # ライブ中は1フレームで4円そろわないため、検出を貯めて多数決で確定する。
            self.autocal_samples.extend(det)
            if len(self.autocal_samples) > AUTOCAL_MAX_SAMPLES:
                del self.autocal_samples[:-AUTOCAL_MAX_SAMPLES]
            matched = self._ne.consensus_circles(self.autocal_samples, list(CIRCLES))
            if matched is None:
                # 同じ内容を毎回出すとログが埋まる（実測 1万行超）。間引く。
                self._autocal_fail_n = getattr(self, "_autocal_fail_n", 0) + 1
                if self._autocal_fail_n <= 3 or self._autocal_fail_n % 100 == 0:
                    self.log(f"[auto-circles] 検出{len(det)}円 "
                             f"(累計{len(self.autocal_samples)}) → まだ確定せず"
                             f"（再試行 {self._autocal_fail_n}回目）")
                return
            old = list(CIRCLES)
            ok, why = self._circles_geometry_ok(matched, old)
            if not ok:
                self.log(f"[auto-circles] 補正値が幾何検証で棄却（現行値を維持）: {why}")
                return
            CIRCLES[:] = matched
            self.circles_calibrated = True
            self.tracker = None   # 旧レーン座標で作られた追跡系を破棄（次フレームで再生成）
            self.forecast = None
            self.log(f"[auto-circles] 円座標を実測へ補正: {old} → {matched}")
            self._save_cached_circles()
        except Exception as e:
            self.log(f"[auto-circles] 失敗（現行値を維持）: {e}")

    def _update_forecast(self, frame, now):
        """--predict: note_engine の検出＋追跡を1フレーム回し、レーン別種別予報を更新。
        例外時は予報なし（=全タップ）に劣化させ、周回は止めない。"""
        try:
            if self._ne is None:
                import note_engine as NE
                self._ne = NE
            if self.tracker is None or self.forecast is None:
                self.tracker = self._ne.Tracker(self.win, self.content,
                                                lanes=list(CIRCLES))
                self.forecast = self._ne.TypeForecast(n_lanes=len(CIRCLES))
            blobs = self._ne.detect_notes(frame, self.win, self.content,
                                          lanes=list(CIRCLES))
            self.forecast.update(self.tracker.update(blobs, now), now)
        except Exception as e:
            self.forecast = None  # 次フレームで再生成を試みる
            self.tracker = None
            if self.verbose:
                self.log(f"[predict] 予報更新に失敗（タップに劣化）: {e}")

    def _gameplay_timing(self, frame, now):
        """各円にノーツ到達を検出したらタップ。長押し（明るさ持続）は押下を保持。
        無検出ならキープアライブ。"""
        # 1) 各円の white割合を毎フレーム評価 → ベースライン更新＋トリガー超の連続フレーム数。
        wf = [self._roi_white_frac(frame, i) for i in range(len(CIRCLES))]
        fired = [False] * len(CIRCLES)
        for i in range(len(CIRCLES)):
            base = self.note_baseline[i]
            if base is None:
                self.note_baseline[i] = wf[i]
                continue
            f = (wf[i] - base) > self.note_trigger
            fired[i] = f
            if f:
                self.note_hi_frames[i] += 1
            else:
                self.note_hi_frames[i] = 0
                # 再武装: トリガー超過分が NOTE_REARM_FACTOR まで下がれば、次ノーツを
                # デバウンスより早く受け付ける。速い曲の16分連打（~150ms）を拾うため。
                # 波紋の残光で誤再武装しないよう、トリガー未満まで十分下げた場合に限る。
                if wf[i] < base + self.note_trigger * NOTE_REARM_FACTOR:
                    self.note_rearmed[i] = True
                if wf[i] < NOTE_BASELINE_FRAC:  # 静穏時のみベースライン取り込み
                    self.note_baseline[i] = base + (wf[i] - base) * NOTE_BASELINE_EMA

        # 1.4) --predict: track 並走で種別予報を更新（発火判定には関与しない）。
        if self.predict:
            self._update_forecast(frame, now)

        # 1.5) 到達直前ROIの色で赤ノーツ（フリック）を先読み。直近で赤を見た円を記録。
        if self.flick:
            for i in range(len(CIRCLES)):
                if self._approach_red(frame, i):
                    self.note_red_seen[i] = now

        # 1.6) 緑の在/不在を毎フレーム更新。**「居なくなった瞬間」が解除の合図**なので、
        #      保持中も測り続ける必要がある（ホールドの長さに依存しない作りの要）。
        if self.green_hold:
            for i in range(len(CIRCLES)):
                # 判定文字（GOOD）はタップの後に出る。叩いた直後は緑を見ない。
                if (self.hold_idx != i
                        and now - self.note_last_tap[i] < GREEN_SUPPRESS_SEC):
                    self.green_px[i] = 0
                    self.green_since[i] = None
                    self.green_peak[i] = 0
                    continue
                px = self._approach_green(frame, i)
                self.green_px[i] = px
                thr = GREEN_REL_PX if self.green_since[i] is not None else GREEN_MIN_PX
                if px >= thr:
                    if self.green_since[i] is None:
                        self.green_since[i] = now   # 緑が現れた（飛行時間の計測開始）
                        self.green_peak[i] = 0
                    self.green_peak[i] = max(self.green_peak[i], px)
                else:
                    self.green_since[i] = None

        # 2g) 緑ホールド継続中（--green-hold）。**輝度は一切使わない。**
        #     押下で円が光り続けるため fired が立ちっぱなしになり「次のノーツ」と区別できない
        #     （旧 --holds が壊れた原因）。approach 点の緑の在/不在だけで判断する。
        if self.green_hold and self.hold_idx is not None and self.ghold_release_at is not None:
            i = self.hold_idx
            held = now - self.hold_start
            if self.green_since[i] is not None:
                # まだ構造（頭＋帯＋尾）が通過中 → 解除予定を先送りして押し続ける
                self.ghold_release_at = now + self.ghold_transit
            if held >= self.hold_max_sec:
                reason = "上限"
            elif now >= self.ghold_release_at:
                reason = "緑が通過し切った"
            else:
                self._press(*self.content_to_screen(*self._hold_pt(i)), "move")
                self.last_input_ts = now
                time.sleep(0.005)
                return
            self._press(*self.content_to_screen(*self._hold_pt(i)), "up")
            self.log(f"ホールド解除 円{i}（{held:.2f}s, {reason}）")
            self.note_last_tap[i] = now
            self.last_input_ts = now
            self.hold_idx = None
            self.hold_point = None
            self.ghold_release_at = None
            self.green_since[i] = None   # 終端の緑で即座に再ホールドしないため明示的に消す
            time.sleep(0.02)
            return

        # 2p) --predict の緑ホールド継続中: ETA予測時刻まで保持。輝度には依存しない
        #     （旧 --holds がタップ波紋と交絡した失敗要因を回避）。move で genuine 入力維持。
        #     hold_release_at の有無で predict 開始のホールドだけを扱う（--holds 併用時、
        #     旧方式が開始したホールドは従来ブロックへ流す）。
        if self.predict and self.hold_idx is not None and self.hold_release_at is not None:
            i = self.hold_idx
            nxt = self.forecast.next_eta_at(i, now, ntype="green") if self.forecast else None
            if nxt is not None:  # 対の緑のETAが精緻化されたら解除時刻を追従
                self.hold_release_at = min(nxt, self.hold_start + HOLD_MAX_SEC)
            if now < self.hold_release_at and (now - self.hold_start) < HOLD_MAX_SEC:
                self._press(*self.content_to_screen(*self._hold_pt(i)), "move")
                self.last_input_ts = now
                time.sleep(0.005)
                return
            self._press(*self.content_to_screen(*self._hold_pt(i)), "up")
            if self.verbose:
                self.log(f"ホールド解除 円{i}（{now - self.hold_start:.2f}s, ETA駆動）")
            self.note_last_tap[i] = now
            self.last_input_ts = now
            self.hold_idx = None
            self.hold_point = None
            self.hold_release_at = None
            time.sleep(0.02)
            return

        # 2) ホールド継続中: その円が明るい限り押下保持（drag=genuine入力でPAUSE防止）。
        #    明るさが引いた or 上限超で離す（誤検出でも HOLD_MAX_SEC で必ず離れる）。
        if self.holds and self.hold_idx is not None:
            i = self.hold_idx
            base = self.note_baseline[i] or 0.0
            still = (wf[i] - base) > self.note_trigger * HOLD_REL_FACTOR
            if still and (now - self.hold_start) < HOLD_MAX_SEC:
                self._press(*self.content_to_screen(*self._hold_pt(i)), "move")
                self.last_input_ts = now
                time.sleep(0.005)
                return
            self._press(*self.content_to_screen(*self._hold_pt(i)), "up")
            if self.verbose:
                self.log(f"長押し解除 円{i}（{now - self.hold_start:.2f}s）")
            self.note_last_tap[i] = now
            self.last_input_ts = now
            self.hold_idx = None
            self.hold_point = None
            self.note_hi_frames[i] = 0
            time.sleep(0.02)
            return

        # 3) 通常検出: 発火円をタップ。明るさが長く持続していれば長押しへ昇格（押下保持）。
        tapped = False
        for i in range(len(CIRCLES)):
            # 発火間隔の制御（2026-10-12、速い曲対応）:
            #   デバウンス期間内でも「一度白率が十分下がった（再武装）」円は新ノーツと
            #   みなし NOTE_MIN_GAP_SEC 以降なら発火する。16分連打（~150ms間隔）を拾う。
            #   再武装していない＝波紋の残光と区別できないので従来どおり弾く。
            dt = now - self.note_last_tap[i]
            if not (dt >= NOTE_DEBOUNCE_SEC
                    or (self.note_rearmed[i] and dt >= NOTE_MIN_GAP_SEC)):
                continue
            if not fired[i]:
                continue
            ntype = None
            if self.predict and self.forecast is not None:
                e = self.forecast.consume(i, now)
                ntype = e["type"] if e else None
            if self.green_hold and self.green_since[i] is not None:
                # 緑がいま approach に居る＝この発火は緑ノーツの頭。押しっぱなしにする。
                # **飛行時間はこのホールド自身で実測する**（定数を持たない）。緑が approach に
                # 現れてから円で発火するまでの差が、そのまま approach→円 の飛行時間。
                # 機種・ウィンドウ寸法・レーン距離の差（実測 1.34 倍）を自動で吸収する。
                self.ghold_transit = max(0.05, now - self.green_since[i])
                self.ghold_release_at = now + self.ghold_transit
                self.hold_point = self._tap_point(i)
                self._press(*self.content_to_screen(*self.hold_point), "down")
                self.hold_idx = i
                self.hold_start = now
                self.last_input_ts = now
                self.note_rearmed[i] = False
                if self.verbose:
                    # ピークを出す。現在値は着弾直前に ROI を抜けかけて下がるため、
                    # そのまま出すとしきい値割れに見えて誤解を招く。
                    self.log(f"ホールド開始 円{i}（緑ピーク{self.green_peak[i]}px, "
                             f"飛行{self.ghold_transit:.2f}s）")
                tapped = True
                break
            if self.predict and ntype == "green":
                # 緑=次の緑まで長押し（§17.9）。解除は対の緑のETA（無ければ track の
                # 精緻化を待ちつつ上限 HOLD_MAX_SEC）。
                nxt = self.forecast.next_eta_at(i, now, ntype="green")
                self.hold_release_at = min(nxt, now + HOLD_MAX_SEC) if nxt \
                    else now + HOLD_MAX_SEC
                self.hold_point = self._tap_point(i)
                self._press(*self.content_to_screen(*self.hold_point), "down")
                self.hold_idx = i
                self.hold_start = now
                self.last_input_ts = now
                self.note_rearmed[i] = False
                if self.verbose:
                    self.log(f"ホールド開始 円{i}（解除予定 +{self.hold_release_at - now:.2f}s）")
                tapped = True
                break
            if self.holds and self.note_hi_frames[i] >= HOLD_SUSTAIN_FRAMES:
                self.hold_point = self._tap_point(i)
                self._press(*self.content_to_screen(*self.hold_point), "down")  # 離さず保持開始
                self.hold_idx = i
                self.hold_start = now
                self.last_input_ts = now
                self.note_rearmed[i] = False
                if self.verbose:
                    self.log(f"長押し開始 円{i}")
                tapped = True
                break
            if (self.predict and ntype == "red") or \
                    (self.flick and (now - self.note_red_seen[i]) < FLICK_RED_MEMORY):
                self._flick(i)  # 赤ノーツ → タップ＋外向きフリック
                if self.verbose:
                    self.log(f"フリック 円{i}（赤検出）")
            else:
                self.click_content(*self._tap_point(i))  # 通常タップ（down+up）
            self.note_last_tap[i] = now
            self.note_rearmed[i] = False   # 発火したので一度下がるまで次を受け付けない
            self.last_input_ts = now
            self.tap_count += 1
            tapped = True
        if not tapped:
            self._keepalive(now)
        self.frame_count += 1
        # **この sleep を外してはいけない。** 「毎フレーム5msの無駄」に見えるが、外して
        # 38→48 FPS にしたところ打鍵精度が有意に悪化した（実測 n=10/11:
        # PERFECT 54.5→37.5（3.5σ）, SCORE 379,675→361,604（3.1σ））。
        # 早撃ち量のズレを疑って lead 0.02→0.012 も試したが PERFECT 37.3 で変わらず、
        # タイミングのオフセットではないと確認済み。機序は未解明だが、合成タップを
        # 詰めて出すと取りこぼしが増えるものと考えられる（ミラーリング側の入力処理か）。
        # 速度は目的ではないので、成績が出る側を採る。
        time.sleep(0.005)

    def _gameplay_track(self, frame, now):
        """実験エンジン: note_engine でノーツをスポーン検出→追跡→レーン/到達判定し打鍵。
        現状は全ノーツ tap（追跡駆動でクリアできるかの検証段階）。種別ジェスチャ（長押し/
        フリック/スライド）は _dispatch_note で順次対応。無検出時はキープアライブで PAUSE 防止。"""
        if self._ne is None:
            import note_engine as NE
            self._ne = NE
            self.tracker = NE.Tracker(self.win, self.content)
            self.acted = set()
        NE = self._ne
        blobs = NE.detect_notes(frame, self.win, self.content)
        anns = self.tracker.update(blobs, now)
        acted_now = False
        for a in anns:
            if not a["is_note"] or a["lane"] < 0 or a["id"] in self.acted:
                continue
            lx, ly = self.tracker.lane_px[a["lane"]]
            dist = ((a["pos"][0] - lx) ** 2 + (a["pos"][1] - ly) ** 2) ** 0.5
            if dist < TRACK_ARRIVE_PX:
                self._dispatch_note(a)
                self.acted.add(a["id"])
                self.last_input_ts = now
                acted_now = True
        if not acted_now:
            self._keepalive(now)
        time.sleep(0.005)

    def _dispatch_note(self, a):
        """ノーツ種別に応じた操作。現状は全て tap（追跡駆動の検証優先）。
        種別判定が信頼できるようになったら green=長押し/red=フリック/blue=スライドを有効化する。"""
        xf, yf = self._ne.LANES[a["lane"]]
        # TODO(type-dispatch): a["type"] が green/red/blue かつ高信頼なら専用ジェスチャ。
        self.click_content(xf, yf)

    def _keepalive(self, now):
        """ノーツ無し区間でも genuine 入力を絶やさず PAUSE を防ぐ。
        rotate と同じ実証済み経路（click_content）で害のない円を1回タップする。"""
        if now - self.last_input_ts >= KEEPALIVE_GAP_SEC:
            idx = self.circle_i % len(CIRCLES)
            self.circle_i += 1
            self.click_content(*self._tap_point(idx))
            self.last_input_ts = now

    def _front_name(self):
        """最前面アプリ名。PAUSE 原因 C（フォーカス奪取）と D（病気セッション）の
        切り分けはこの1語で決まる。詳細は docs/pause-causes.md「1. 原因の識別表」。"""
        try:
            from AppKit import NSWorkspace
            a = NSWorkspace.sharedWorkspace().frontmostApplication()
            return (a.localizedName() or "?") if a else "?"
        except Exception:
            return "?"

    def _mirror_is_front(self):
        """iPhoneミラーリングが最前面か。NSWorkspace の frontmostApplication で判定。"""
        try:
            from AppKit import NSWorkspace
            a = NSWorkspace.sharedWorkspace().frontmostApplication()
            n = (a.localizedName() or "") if a else ""
            return ("Mirroring" in n) or ("ミラーリング" in n)
        except Exception:
            return False

    def _refresh_window(self, interval=2.0):
        """ミラーリングウィンドウの矩形を定期的に取り直す。

        起動時に1回しか取らないと、ウィンドウが移動・リサイズされた後も古い矩形で
        キャプチャし続け、**画面の一部＋デスクトップ壁紙**という不整合なフレームを
        掴んで「未知画面」で安全停止する（実測 2026-08-01: ミラーリングアプリの
        再起動でウィンドウが 671x348 → 318x701 に変わり、空転を繰り返した）。

        寸法が変わったら content 矩形・円キャリブレーションのキャッシュ・ジッター半径
        （px 換算値）も作り直す（いずれもウィンドウ寸法に依存するため）。
        """
        now = time.time()
        if now - self._last_win_check < interval:
            return
        self._last_win_check = now
        try:
            win = driver.find_window()
        except Exception:
            return                      # 切断中など。次回に再試行
        if (int(win["w"]), int(win["h"])) != (int(self.win["w"]), int(self.win["h"])):
            # **縦長＝ミラーリング切断ダイアログ**（ゲームは常に横向き）。切断中に
            # 座標系を作り直すと、円キャリブレーションが「検出0円」を延々と再試行し
            # ログを埋め尽くす（実測 2026-08-02: 1万行超）。切断はゲームの
            # レイアウト変更ではないので、寸法だけ追従して補正はそのまま維持する。
            disconnected = win["w"] < win["h"]
            self.log(f"[warn] ウィンドウ寸法が変化: "
                     f"{int(self.win['w'])}x{int(self.win['h'])} → "
                     f"{int(win['w'])}x{int(win['h'])}"
                     + ("（切断とみなし補正は維持）" if disconnected else " → 座標系を作り直す"))
            self.content = (TITLEBAR_ROWS, int(win["h"]) - 9)
            if not disconnected:
                self._roi_scale_key = None      # ROI スケールを再計算させる
                self.circles_calibrated = False  # 別レイアウトなので円を取り直す
                self.autocal_samples = []
                if self.jitter is not None:
                    # ジッターの半径も win["w"] 基準の比率換算なので、寸法が変わったら
                    # 古い px のまま（0.76R相当に膨らむ等）にならないよう作り直す。
                    # self.win はまだ更新前なので、新しい幅は win["w"] を明示的に渡す。
                    self.jitter = self._build_jitter(win_w=win["w"])
                    # 新インスタンスは begin_live() 未実施で offset_px() が RuntimeError に
                    # なる。gameplay_since は resize では None→now に遷移しない（ライブ中
                    # resize では begin_live() が再呼出しされない）ため、ここで明示的に呼ぶ。
                    self.jitter.begin_live()
        self.win = win

    def _rings_visible(self, frame_rgb):
        """タップ円のリングが RING_MIN_COUNT 個以上見えているか（薄暗いフレームのライブ判定）。

        各円について、半径 0.78〜0.92R の円周上 36 点の max(R,G,B) 平均と、半径 0.45R の
        内側 36 点の平均との差をコントラストとする。CIRCLES は較正後の値を使うので、
        未較正の端末ではリングを外して False になり、従来どおり明るい側の照合へ落ちる。
        """
        # getattr: detect() は result_log 等の外部ツールからも __new__ 生成のインスタンスで
        # 呼ばれる。内容矩形が無ければリング判定はせず、従来どおり明るい側へ落とす。
        content = getattr(self, "content", None)
        if content is None:
            return False
        h, w = frame_rgb.shape[:2]
        top, bottom = content
        ch = bottom - top
        r = CIRCLE_R_FRAC * w
        V = frame_rgb.max(axis=2)
        ang = np.linspace(0.0, 2.0 * np.pi, 36, endpoint=False)
        cos, sin = np.cos(ang), np.sin(ang)

        def samp(cx, cy, rad):
            xs = np.clip(np.rint(cx + rad * cos).astype(int), 0, w - 1)
            ys = np.clip(np.rint(cy + rad * sin).astype(int), 0, h - 1)
            return float(V[ys, xs].mean())

        n = 0
        for xf, yf in CIRCLES:
            cx, cy = w * xf, top + yf * ch
            ring = max(samp(cx, cy, r * k) for k in (0.78, 0.85, 0.92))
            if ring - samp(cx, cy, r * 0.45) > RING_CONTRAST_MIN:
                n += 1
        return n >= RING_MIN_COUNT

    def bgr(self, frame_rgb):
        """テンプレ照合用の BGR フレーム。detect() が変換済みならそれを使い回す。

        detect() は**照合するときだけ**変換する（ライブ中の分解能を削らないため）ので、
        ハンドラから self._frame_bgr を直接見ると None のことがある。必ずこれを通すこと。
        """
        if getattr(self, "_frame_bgr", None) is None:
            self._frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        return self._frame_bgr

    def _keep_front(self, interval=0.4):
        # **最前面なら再アクティブ化しない**。ミラーリングの再アクティブ化(activate)は
        # ライブ中にゲームを PAUSE させるため（端末により顕著）、最前面を失った時だけ復帰させる。
        # 詳細は docs/device-findings.md（PAUSE は activate 連打が主因と判明）。
        now = time.time()
        if now - self.last_activate > interval:
            if not self.dry_run and not self._mirror_is_front():
                driver.activate_fast()
            self.last_activate = now

    def log(self, msg):
        el = time.time() - self.t_start
        print(f"[{el:6.1f}s][clear {self.loops_done}/{self.max_loops}] {msg}",
              flush=True)

    def _detect_path(self, name):
        """detect() がフレームを処理した経路を数える（ライブ終了ログ用）。

        __new__ 生成のインスタンス（result_log・各種テスト）では _detect_paths が
        無いので getattr で保護する。
        """
        paths = getattr(self, "_detect_paths", None)
        if paths is not None:
            paths[name] = paths.get(name, 0) + 1

    def _prof_bucket(self, state):
        """ループ内訳の振り分け先: gameplay/pause → "live"、それ以外 → "other"。

        「ライブ中だけの取得/判定/打鍵時間」を出すための境界。明るい画面への
        誤判定や曲間のメニューは other 側へ流れ、live 側を汚さない。
        """
        return self._prof["live"] if state in ("gameplay", "pause") else self._prof["other"]

    def _live_report(self):
        """クリア計上時に1ライブぶんの計測をログへ出し、カウンタをリセットする。

        警告は曲・難易度に依存しない2指標（LIVE_FPS_WARN / LIVE_MERGED_WARN_SEC の
        コメント参照）。旧来の打鍵回数閾値（330/600）は曲ごとにノーツ数が違うので廃止。
        """
        live = self._prof["live"]
        oth = self._prof["other"]
        live_sec = live["sec"]
        fps = self.frame_count / live_sec if live_sec > 0 else 0.0
        paths = getattr(self, "_detect_paths", {}) or {}
        self.log(f"ライブ内訳 打鍵{self.tap_count}回 / 判定{self.frame_count}フレーム"
                 f" / FPS {fps:.1f} (gameplay/pause {live_sec:.0f}s)"
                 f" [取得{live['grab']:.0f}s 判定{live['detect']:.0f}s 打鍵{live['act']:.0f}s]"
                 f"  他[取得{oth['grab']:.0f}s 判定{oth['detect']:.0f}s 打鍵{oth['act']:.0f}s]"
                 f"  経路[暗{paths.get('dark', 0)} 薄暗+輪{paths.get('dim_rings', 0)}"
                 f" 明{paths.get('bright', 0)} 再照合{paths.get('recheck', 0)}"
                 f" 救済{paths.get('rescue', 0)}]")
        if live_sec > LIVE_MERGED_WARN_SEC:
            self.log(f"[warn] gameplay/pause が {live_sec:.0f}s 続いた"
                     f"（1ライブ長≈110-125s+PAUSE の上限≈{LIVE_MERGED_WARN_SEC:.0f}s超）→"
                     " リザルトを見逃して2ライブ連結した可能性"
                     "（長い PAUSE の繰り返しでも起こりうる）")
        if self.frame_count and live_sec >= MIN_LIVE_SEC and fps < LIVE_FPS_WARN:
            self.log(f"[warn] ライブ中ループ {fps:.1f} FPS < {LIVE_FPS_WARN:.0f} →"
                     " 判定がノーツに追いついていない（打鍵の時間分解能不足。"
                     " 内訳の[判定]と経路[明/再照合]を見て原因を特定する）")
        self._prof = {"live": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0},
                      "other": {"grab": 0.0, "detect": 0.0, "act": 0.0, "sec": 0.0}}
        self._detect_paths = {}
        self.tap_count = 0
        self.frame_count = 0

    def detect(self, frame_rgb):
        """明るさゲート + テンプレ照合で状態を返す。

        1. 「PAUSE」見出しが出ていれば pause（暗背景でも確実）。
        2. 画面が暗ければ gameplay（ライブ中）。
        3. 明るければメニュー。**ステラ誤使用を避けるため確認ボタンの盲目連打はしない**。
           既知の画面だけをテンプレで処理し、未知の明るいダイアログは "menu" として
           安全な送り（TAP SCREEN 位置）のみ行い、長く留まったら停止する（run() 参照）。

        判定順序（重要）:
        - friendreq:  EVENT RESULT の「申請する」。先に処理。
        - replay:     連続ライブ再プレイ確認 → 「はい」。closex より先（×と誤検出するため）。
        - closex:     各種ポップアップ右上の×（RANK UP/獲得一覧/申請完了 など）。
        - rankup:     RANK UP 見出し（closex が×を取れない時のフォールバック）。
        - download:   データDL確認 →「ダウンロード」。
        - result:     EVENT RESULT 本体 → TAP SCREEN で送る。
        """
        # テンプレは cv2.imread（BGR）で読むため、照合は必ず BGR フレームに対して行う
        # （RGB のまま照合するとスコアが落ちる。実測: きなこパン行 1.000→0.729、
        # フレンド行 0.898→0.793）。ただし**変換は照合するときだけ**行う。ライブ中は
        # 大半のフレームで照合しないので、毎フレーム変換すると打鍵の分解能を無駄に削る。
        self._frame_bgr = None
        _rgb = frame_rgb

        def frame_bgr():
            if self._frame_bgr is None:
                self._frame_bgr = cv2.cvtColor(_rgb, cv2.COLOR_RGB2BGR)
            return self._frame_bgr

        bright = frame_brightness(frame_rgb)
        res = {"_bright": (bright, 0, None)}
        # 明るいフレームでは BRIGHT_KEYS の照合を先に並列で投げておき（下の prefetch）、
        # m() はその結果を読む。**判定は m() の呼び順＝下の if の並びで決まる**ので、
        # 直列で1つずつ照合していた頃と state・res は同一（tests/test_detect_prefetch.py）。
        pending = {}

        def stop_prefetch():
            # 状態が決まったら、まだ始まっていない照合を取り消す（次の処理と CPU を奪い合わない）。
            for fut in pending.values():
                fut.cancel()

        def m(key):
            imgs, thr = self.templates[key]
            fut = pending.get(key)
            score, pos = fut.result() if fut is not None else match_best(frame_bgr(), imgs)
            res[key] = (score, thr, pos)
            if score >= thr:
                stop_prefetch()
            return score >= thr

        # 薄暗いフレーム（DARK_THRESH〜DIM_THRESH）はリングが見えていればライブ中とみなす（DIM_THRESH の注記）。
        # リングが見えている＝ライブ中なので、暗い側の救済照合（songselect/dailytask/eventresult）も
        # 省ける（PAUSE 照合だけは常に行う）。実測: 薄暗いライブでは救済 3 件が 0.7 秒ごとに 93ms
        # かかり判定フレームが 3500 → 3100 に落ちていた。
        # リング評価は遅延させる: 必要なのは「薄暗いフレームのライブ判定」（65≦b<90）
        # と暗い側の「救済照合が要るか」（50<b<65 かつリング無し）だけ。旧コードは
        # b>50 の全フレーム（明るいメニュー全てを含む）で _rings_visible の全画面
        # スキャン（実測 2〜3ms）を行っていた。明るい側では値自体が不要なので計算しない。
        # rings は評価後「None=未評価 / True / False」。薄暗い側に入ったなら True。
        rings = None
        if bright < DARK_THRESH:
            self._detect_path("dark")
        elif bright < DIM_THRESH and (rings := self._rings_visible(frame_rgb)):
            self._detect_path("dim_rings")
        else:
            self._detect_path("bright")
        if bright < DARK_THRESH or (bright < DIM_THRESH and rings):
            # 暗い＝gameplay or PAUSE(暗背景)。**打鍵タイミング精度のため、重い pause/songselect
            # 照合は毎フレームせず DARK_RECHECK_SEC おきに間引く**（PAUSE・暗いsongselectは
            # タイミング非依存で数フレーム遅れて検出可）。間引くぶん _gameplay_timing のノーツ
            # 検出サンプリングが速くなり精度が上がる。
            # ※一部の楽曲選択画面はジャケット/KEEP OUTテープで暗くなり閾値(65)を下回る(mean≈61)
            #   ため、暗め域(>50)では songselect(NEXT, 高specific 0.85)を確認して救済する。
            now_t = time.time()
            if now_t - self._last_dark_check >= DARK_RECHECK_SEC:
                self._last_dark_check = now_t
                self._detect_path("recheck")
                # **暗い側の救済照合はすべて範囲限定で行う。** 全画面照合のままだと、
                # ウィンドウ上端の透過部に明るい別ウィンドウが写り込んで輝度が 50 を超えた
                # だけで、0.7 秒ごとの再照合が 26ms → 297ms に跳ね、ライブ中のループ時間の
                # 約4割を失う（実測 2026-09-11: 判定 2136 フレーム・打鍵 301 回・グレード C）。
                # 直列でも 113ms あり「まばたき」の間にノーツを見送る（実測 2026-10-12）。
                # 明るい側と同じく照合をプールへ並列で投げ、結果を判定順に読む。
                _pool = match_pool()
                dark_pending = {
                    "pause": _pool.submit(match_in_box, frame_bgr(),
                                          self.templates["pause"][0], PAUSE_SEARCH_BOX),
                }
                # 救済照合が要るのは「暗めだが真っ暗ではなくリングも見えない」フレームだけ。
                # 真っ暗（bright≤50）やリング確認済みの gameplay では投げない（無駄なCPUを避ける）。
                # 暗い側ではリングをまだ評価していない（上の遅延評価参照）。真っ暗（bright≤50）では
                # 救済しないので評価自体を省く（旧コードの短絡評価と同じ）。
                if rings is None and bright > 50.0:
                    rings = self._rings_visible(frame_rgb)
                need_rescue = bright > 50.0 and not rings
                if need_rescue:
                    self._detect_path("rescue")
                    for _k, _box in DARK_RESCUE_KEYS:
                        dark_pending[_k] = _pool.submit(
                            match_in_box, frame_bgr(), self.templates[_k][0], _box)

                def dark_match(key):
                    imgs, thr = self.templates[key]
                    score, pos = dark_pending[key].result()
                    res[key] = (score, thr, pos)
                    return score >= thr

                if dark_match("pause"):
                    return "pause", res
                # ※一部の楽曲選択画面はジャケット/KEEP OUTテープで暗くなり閾値(65)を下回る(mean≈61)
                #   ため、暗め域(>50)では songselect(NEXT, 高specific 0.85)を確認して救済する。
                # イベントトップの「本日の課題」ポップアップは mean≈58 で暗判定に落ちる。
                # 放置すると打鍵エンジンが動き、円の位置にある「イベント楽曲へ」ボタンを
                # 叩いて制御外の遷移を起こす（実測 2026-08-03）。
                # EVENT RESULT の pt 画面はイベントテーマで暗くなる（実測 2026-09-10、
                # KEEP OUT テーマで mean 57 < DARK_THRESH）。gameplay 扱いにすると円の位置を
                # 盲目打鍵し続け、進むまで 40〜130 秒を浪費し、MIN_LIVE_SEC を超えて
                # **偽クリアを二重計上**する。見出しは左上に固定なので範囲を絞って照合する。
                # iOS のシステムダイアログ（iMessage/FaceTime 有効化確認）は画面を暗転させ
                # mean≈64 < DARK_THRESH に落ちる（実測 2026-09-16 07:39、編成画面の上）。
                # gameplay 扱いのままだと 240 秒で gameplay_timeout 停止 → runner 終了になる。
                if need_rescue:
                    if dark_match("songselect"):
                        return "songselect", res
                    if dark_match("dailytask"):
                        return "dailytask", res
                    if dark_match("eventresult"):
                        return "eventresult", res
                    if dark_match("imessage"):
                        return "imessage", res
                    if dark_match("icloudsync"):
                        return "icloudsync", res
            return "gameplay", res
        # --- 明るい画面（タイミング非依存。毎フレーム照合でよい）---
        # 全キーの照合を判定順に常駐プールへ投げる。暗い側（ライブ中）では投げない
        # （打鍵ループの CPU を奪わない）。
        _bgr = frame_bgr()
        _pool = match_pool()
        for _k in BRIGHT_KEYS:
            if _k in self.templates:
                pending[_k] = _pool.submit(match_best, _bgr, self.templates[_k][0])
        if m("pause"):
            return "pause", res
        # iOS の iMessage/FaceTime 確認は明るい画面の上にも出うる。battery と同じく最優先で閉じる。
        if m("imessage"):
            return "imessage", res
        if m("icloudsync"):
            return "icloudsync", res
        # --- 明るいメニュー画面（順序が重要） ---
        # iOSバッテリー残量低下警告は最優先で「閉じる」（放置すると未知画面で安全停止しループ停止）。
        if m("battery"):
            return "battery", res
        # LIFE不足ダイアログは最優先で判定（誤って盲目タップしステラを押さないため）。
        if m("lifeshort"):
            return "lifeshort", res
        if m("friendreq"):
            return "friendreq", res
        if m("replay"):
            return "replay", res
        # RANK UP は専用の固定×位置で閉じるため closex より先に判定する。
        if m("rankup"):
            return "rankup", res
        # データDL確認ダイアログは close_x が誤マッチ(≈0.93)するため closex より先に判定する。
        if m("dldialog"):
            return "dldialog", res
        # ストーリー遷移確認（×無し・いいえ/はい）も closex より先に判定して「いいえ」で閉じる。
        if m("story"):
            return "story", res
        # アプリ再起動後のライブ再開確認。シアン系ヘッダを持つため cardx より先に判定する
        # （cardx 扱いだと背景タップで閉じようとして必ず停滞する）。
        if m("resumelive"):
            return "resumelive", res
        # データ更新のタイトル復帰と、その後の結果再送確認。いずれもシアン系ヘッダを持つ。
        if m("dataupdate"):
            return "dataupdate", res
        if m("resendresult"):
            return "resendresult", res
        # 通信エラーもシアン系ヘッダを持つので cardx より先に確定する。
        if m("neterror"):
            return "neterror", res
        # 「通信がタイムアウトしました。」も同じシアン系ヘッダ。ボタンは「諦める」1個だけ
        # （リトライは無い）。cardx より先に確定する（2026-10-15 に cardx_stuck で停止した実績）。
        if m("nettimeout"):
            return "nettimeout", res
        # 「…サポートしました。」はシアン系ヘッダを持つうえ×が無い。cardx より先に確定する。
        if m("supported"):
            return "supported", res
        # ライブアシスト選択（formation START 後に出ることがある）。アイテムを選ばず START で
        # 開始すれば消費ゼロ。formation/カード色検出より先に確定する。
        if m("liveassist"):
            return "liveassist", res
        # 編成画面（START ボタンが明確に見える）は popup ではない。イベントテーマの帯を
        # detect_card_x が誤ってカードヘッダ扱いし cardx 誤検出→停止していたため、色ヒュー
        # リスティックより先に START テンプレで確定する（modal popup なら START は隠れて落ちる）。
        if m("formation"):
            return "formation", res
        # --- アプリ再起動からの復帰（4:00 前後のデータ更新後）---
        # すべて cardx より先に置く。お知らせ・ホームはシアン〜緑の帯を持ち、
        # detect_card_x にカードヘッダと誤検出されうるため。
        # **formation より後ろ。** title の目印である MENU ボタンは編成画面にもあり
        # 0.889 で当たる（実測 2026-08-03）。しきい値 0.92 と併せた二重の防御。
        # **breaktime は必ず eventtop より先。** 休憩ダイアログは「イベント楽曲」ボタンを
        # 背後に残したまま出るので eventtop_songs が 0.943 で当たる（実測 2026-08-02）。
        # 逆順にするとダイアログの裏のボタンを押し続けて停滞する。
        if m("breaktime"):
            return "breaktime", res
        if m("title"):
            return "title", res
        if m("notice"):
            return "notice", res
        if m("news"):
            return "news", res
        if m("eventtop"):
            return "eventtop", res
        # ログインボーナスはホームの上に出る。ホーム判定（背後の EVENT 帯が当たる）より先。
        if m("loginbonus"):
            return "loginbonus", res
        if m("speciallogin"):
            return "speciallogin", res
        if m("home"):
            return "home", res
        # 「本日の課題」は生の平均輝度が 58 前後で、frame_brightness() では 78 前後になり
        # 明るい側にも来る（帯の写り込みで揺れる領域）。カード型ポップアップなので cardx より先。
        if m("dailytask"):
            return "dailytask", res
        # 「ライフを全回復しました。」モーダル。きなこ3個回復で LIFE が上限に達すると、
        # 楽曲選択や Event Result の上に重なって出る（回復カードと違い**背景タップでは
        # 閉じず、右上の × が必須**。2026-10-11 実機: cardx に流れて背景タップを約30回
        # 踏んで cardx_stuck 停止。別の回では楽曲選択の上に出て NEXT を約30回飲み込んだ）。
        # **songselect・cardx・closex より先**: 背後の NEXT や closex(0.88) が先に当たると
        # モーダルが消えない画面として誤動作し続ける。
        if m("lifefull"):
            return "lifefull", res
        # 汎用カードポップアップ（報酬獲得/アイテム獲得/獲得一覧 等）の×を色検出で閉じる
        # （端末非依存）。専用ダイアログ判定の後・result の前（Result の上に重なって出るため）。
        # getattr: detect() は result_log 等の外部ツールからも __new__ 生成の
        # インスタンスで呼ばれるため、属性が無くても動くようにする。
        # 連戦（連続ライブ再プレイ）が終わると楽曲選択画面に戻る。そこから自動で再開する。
        # **cardx より先。** イベント楽曲リスト上部の薄い水色の区切り線（高さ2px・
        # RGB(157,196,218)）が detect_card_x の「シアン帯」条件を満たすため cardx と
        # 誤検出され、背景タップでは閉じられず 28 秒で安全停止していた（2026-08-28 実機）。
        # formation と同じ理屈で、モーダルが被っていれば NEXT は隠れて閾値に届かない。
        # **範囲限定で照合する。** 明るいフレームごとに走るので、全画面照合(238ms)のままだと
        # メニュー遷移が目に見えて遅くなる（SONGSELECT_SEARCH_BOX 参照）。
        _ss_imgs, _ss_thr = self.templates["songselect"]
        _ss_score, _ss_pos = match_in_box(frame_bgr(), _ss_imgs, SONGSELECT_SEARCH_BOX)
        res["songselect"] = (_ss_score, _ss_thr, _ss_pos)
        if _ss_score >= _ss_thr:
            stop_prefetch()
            return "songselect", res
        # per-song Result の EXP 画面はカードの緑ヘッダを持つため cardx と誤検出される。
        # 背景タップでは閉じず停滞→安全停止するので、色検出より先に確定させる。
        if m("expresult"):
            return "expresult", res
        # フレンド（サポート）選択は上部の薄い水色の装飾帯（mean RGB≈[182,196,199]、
        # y≈0.11〜0.17）が detect_card_x のシアン帯条件を満たし、cardx に誤判定されて
        # 背景タップ連打→停滞停止していた（実測 2026-09-30、6クリアごとに4連続
        # cardx_stuck。テンプレ側は 0.925 で当たる）。色検出より先に確定する。
        if m("friendselect"):
            return "friendselect", res
        cardx = None if time.time() < getattr(self, "suppress_cardx_until", 0.0) \
            else detect_card_x(frame_rgb)
        if cardx is not None:
            res["cardx"] = (1.0, 0, cardx)
            stop_prefetch()
            return "cardx", res
        if m("closex"):
            return "closex", res
        # EVENT RESULT 見出し（申請する押下後の送り待ち画面）。per-song result より先に判定。
        if m("eventresult"):
            return "eventresult", res
        if m("result"):
            return "result", res
        if m("formation"):
            return "formation", res
        return "menu", res

    # --- 曲間の遷移を詰めるための小道具（2026-10-11）---
    def _grab(self):
        return driver.grab(self.win)

    def _still_frame(self, max_sec, gap=ADVANCE_STABLE_GAP):
        """gap 秒空けた2枚がほぼ同じ（＝静止）になった後者を返す。
        max_sec 以内に静止しなければ None。**クリックはしない。**
        ゆっくり動くアニメ（一覧のスライドイン等）を静止と取り違えないよう、gap は長めにもできる。"""
        end = time.time() + max_sec
        prev = self._grab()
        while True:
            time.sleep(gap)
            cur = self._grab()
            if frame_diff(prev, cur) < ADVANCE_STABLE_DIFF:
                return cur
            if time.time() >= end:
                return None
            prev = cur

    def _wait_change(self, ref, max_sec):
        """画面が ref から ADVANCE_SAME_DIFF 以上変わるまで待つ（最大 max_sec）。変わったら True。

        固定の sleep の代わりに使う。押した直後に同じボタンをもう一度押さないための待ちは
        「画面が変わるまで」で十分で、変わったらすぐ次の判定へ進める。"""
        end = time.time() + max_sec
        while time.time() < end:
            time.sleep(0.1)
            if frame_diff(ref, self._grab()) >= ADVANCE_SAME_DIFF:
                return True
        return False

    def _scores(self, frame_rgb, keys):
        """keys の照合を match_pool() で並列に行い {key: (score, thr, pos)} を返す。"""
        bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        pool = match_pool()
        futs = {k: pool.submit(match_best, bgr, self.templates[k][0])
                for k in keys if k in self.templates}
        out = {}
        for k, fut in futs.items():
            score, pos = fut.result()
            out[k] = (score, self.templates[k][1], pos)
        return out

    def _advance_tap(self, state):
        """送り画面のタップ。既定は右側の背景 P_CARD_DISMISS（窓相対 (0.86, 0.50)）。
        Result 系で右側が効かないと判った画面だけ、従来の中央送り（OFF_RESULT_ADV）に戻す。"""
        if self.advance_alt.get(state):
            self.click_center_off(OFF_RESULT_ADV)
        else:
            self.click_window(*P_CARD_DISMISS)

    def _advance_screen_ok(self, state, ref, cur):
        """連続タップの1打ごとのガード。cur がまだ「state と同じ送り画面」なら True。

        detect() の判定順を写す: 重なるダイアログ（ADVANCE_GUARD_KEYS・楽曲選択）が見えたら止める。
        cardx は色検出でダイアログにも当たる（LIFE不足・連続ライブで実測）ので、detect() が
        識別したときの画面 ref とほぼ同じ見た目のときだけ叩く。Result 系はページが進むので
        ref との一致は求めず、テンプレで送り画面であることを毎回確かめる。
        """
        if state == "cardx" and frame_diff(ref, cur) >= ADVANCE_SAME_DIFF:
            return False
        keys = ADVANCE_GUARD_KEYS + (() if state == "cardx"
                                     else ("expresult", "closex", "eventresult", "result"))
        sc = self._scores(cur, keys)
        if any(sc[k][0] >= sc[k][1] for k in ADVANCE_GUARD_KEYS if k in sc):
            return False
        ss_imgs, ss_thr = self.templates["songselect"]
        if match_in_box(cv2.cvtColor(cur, cv2.COLOR_RGB2BGR), ss_imgs,
                        SONGSELECT_SEARCH_BOX)[0] >= ss_thr:
            return False
        card = detect_card_x(cur)
        if state == "cardx":
            return card is not None

        def hit(k):
            return k in sc and sc[k][0] >= sc[k][1]
        if hit("expresult"):
            return True
        if card is not None or hit("closex"):   # 判定順で result より前（カードが重なった）
            return False
        return hit("eventresult") or hit("result")

    def _advance_burst(self, state, ref):
        """送り画面（result/eventresult/expresult/cardx）を短い間隔で続けて送る。叩いた回数を返す。

        1打ごとに「静止している」「まだ同じ送り画面」（_advance_screen_ok）を確かめてから叩く。
        画面が動いている（遷移・ダイアログの出現アニメ）間は叩かず、別の画面になったら
        すぐやめて通常の detect() に戻す。LIFE不足・連続ライブのダイアログへは打ち込まない。
        """
        taps = 0
        end = time.time() + ADVANCE_BURST_SEC
        while taps < ADVANCE_BURST_TAPS and time.time() < end:
            time.sleep(ADVANCE_BURST_GAP)
            cur = self._still_frame(0.6)
            if cur is None or not self._advance_screen_ok(state, ref, cur):
                return taps
            self._advance_tap(state)
            taps += 1
        return taps

    def _advance_fallback_check(self, state, now):
        """Result 系（result/eventresult/expresult）の同じ状態に ADVANCE_ALT_SEC 以上留まったら、
        右側タップが効かない画面とみなし、以後その状態だけ従来の中央送り（OFF_RESULT_ADV）に戻す。
        cardx は背景タップで閉じることを実機で確認済みなので対象外。"""
        if self.advance_alt.get(state):
            return
        since = self.advance_since
        if since is None or since[0] != state:
            self.advance_since = (state, now)
            return
        if now - since[1] > ADVANCE_ALT_SEC:
            self.advance_alt[state] = True
            self.log(f"[warn] {state}: 右側タップで {now - since[1]:.0f}s 進まない"
                     f" → 以後は中央タップで送る")

    # --- LIFE 回復の読み取り（Vision OCR。テストで差し替えられるようメソッド経由）---
    def _qty_ocr(self, frame, ref):
        return kinako_qty_ocr(frame, ref)

    def _per_pan_ocr(self, frame, row_pos):
        return kinako_per_pan_ocr(frame, row_pos)

    def _life_ocr(self, frame, row_pos):
        return dialog_life_ocr(frame, row_pos)

    def _life_cost(self):
        """ライブの LIFE コスト。フレンド選択/編成で読んだ値か、未取得なら観測最大値。"""
        v = getattr(self, "life_cost", None)
        return v if v else KINAKO_ASSUMED_COST

    def _recover_life(self, frame):
        """LIFE 不足ダイアログで、必要な個数のきなこパンを使って回復する。

        戻り値 (status, kinako_score, frame):
          "recovered"      … きなこ行の「回復」を押した
          "gone"           … ダイアログが消えた（「回復」は押していない）
          "unsettled"      … 押せるフレームが取れず「回復」を押さなかった（次の detect でやり直す）
          "kinako_missing" … KINAKO_RECHECK_SEC 撮り直してもきなこ行が一度も見えない（**何も押していない**）
          "life_no_gain"   … 直前の「回復」で現在 LIFE が増えない読みが MAX_LIFE_NO_GAIN 回
                            続いた（**この呼び出しでは何も押していない**）

        押す点はすべて**きなこ行のテンプレ一致位置から**求める（ステラ行は 0.26h 下・ステッパー無し）。
        - 「回復」: kinako_recover_point（行と同じ高さのピンクのボタン）
        - 「+」  : kinako_plus_point（「回復」と同じ高さ・その左の青い箱の中の白い十字）
        - 「−」  : kinako_minus_point（同じステッパーの左端の白い横棒）

        手順（2026-10-20 改訂。個数は Vision OCR で読んだ値から毎回決める・固定値なし）:
        1. 行が閾値を超えて見え、**行の位置が2枚続けて同じ**フレームを待つ。ダイアログには
           キラキラ演出が約 0.5 秒ごとにきなこ行を横切り、その間スコアは 0.72〜0.80 に落ちる
           （閾値 0.80、平常 0.83）。全画面の静止判定は「+」自身のタップ演出でも崩れるので使わない。
        2. 静止フレームで「1個の回復量」（ラベル `LIFE N 回復`）と「現在 LIFE」（右上 `LIFE ♥ N`）
           を OCR で読み、`n = ceil((コスト − LIFE) / 回復量)` を 1..KINAKO_MAX_PER_RECOVER に
           収めて目標個数にする。コストはフレンド選択・編成画面のバッジで読んだ self.life_cost
           （未取得なら KINAKO_ASSUMED_COST）。回復量・LIFE が読めなければ n = 1。
        3. 直前の「回復」で現在 LIFE が増えていない読みが続いていたら、**何も押さず**
           "life_no_gain" を返す（回復が効いていないときにパンを浪費しない歯止め。
           旧 MAX_LIFE_RECOVERS の連続回数判定の置き換え）。
        4. **「+」はダイアログ1回の出現につき1セットだけ**、数量欄が n より小さいと確定した
           ときに (n − 数量) 回押す。押した事実を self.kinako_plus_at に残し、同じダイアログ
           では二度と押さない。
        5. **数量欄は同じ読みが続くまで確定しない。** 数字は連続 KINAKO_SETTLE_READS(2) 回、
           読めない（None）は KINAKO_OTHER_READS(3) 回。カウントアップ途中の誤読で「−」を
           押さないため。
        6. 赤い「上限を超えています」バッジが出ている間は「−」を押すだけ（「回復」は押さない）。
           バッジ無しで確定数量が n より多ければ「−」で n まで戻す。
        7. 「回復」は**数量欄が n と確定し、バッジが無いときだけ**押す。数量欄が読めない
           まま「回復」は押さない。「+」が見つからない・押せないのに数量が n 未満のまま
           KINAKO_LOW_SETTLE_SEC 続いたときは、その確定数量（≥1）で回復する
           （在庫上限で n に届かない場合の空転防止）。
        """
        ls_imgs, ls_thr = self.templates["lifeshort"]
        k_imgs, k_thr = self.templates["kinakorow"]

        def look(fr):
            bgr = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR)
            f_ls = match_pool().submit(match_best, bgr, ls_imgs)
            ks, kp = match_best(bgr, k_imgs)
            return f_ls.result()[0] >= ls_thr, ks, kp

        now = time.time()
        plus_at = getattr(self, "kinako_plus_at", None)
        plussed = plus_at is not None and now - plus_at[0] < KINAKO_PLUS_MEMORY_SEC
        # このダイアログで「+」を押した事実（呼出をまたいで保持）。直後のカウントアップ
        # 途中の数量読みで「−」を踏むと打ち消してしまうので、q > n の minus 発火に
        # KINAKO_HIGH_SETTLE_SEC の猶予を持たせる判定に使う。
        plus_clicked = plussed and getattr(self, "_kinako_plus_clicked", False)
        if not plussed:
            self.kinako_plus_at = None
            self._kinako_plus_clicked = False
        deadline = now + KINAKO_RECHECK_SEC   # 「行の発見」予算。見えたら settle 予算へ伸びる
        hard_deadline = now + KINAKO_RECOVER_MAX_SEC  # ok が間欠し続けてもここで打ち切る
        cur = frame
        on = True
        ks, kp = match_best(self.bgr(frame), k_imgs)
        best_ks, prev_kp = ks, None
        seen_row = False
        minus_taps = 0
        qty = None              # 「回復」に進むときの説明文字列（実際の個数）
        qty_seq = []            # 数量欄の読み（int / None）の連続列。確定に使う
        just_clicked = False    # 「+」「−」を押した直後（再び2枚揃うのを待つ）
        per_pan = None          # 1個の回復量（この出現で最初に読めた値）
        life = None             # 現在 LIFE（読めた最新値）
        cost = self._life_cost()
        n_target = 1            # 回復量・現在 LIFE が読めるまでの安全側個数
        gain_checked = False    # この呼び出しで「回復後に LIFE が増えたか」を判定済みか
        low_since = None        # 「+」済みで数量が n 未満の確定が続き始めた時刻
        high_since = None       # 「+」済みで数量が n 超過の確定が続き始めた時刻
        while True:
            if not on:
                self.kinako_plus_at = None
                self._kinako_plus_clicked = False
                return "gone", best_ks, cur
            ok = kp is not None and ks >= k_thr
            steady = ok and prev_kp is not None and abs(kp[0] - prev_kp[0]) <= 2 \
                and abs(kp[1] - prev_kp[1]) <= 2
            if ok:
                seen_row = True
                # 行が見えている間は「確定 → + → 再確定 → 回復」の予算を使う。
                # 発見予算(2s)では1反復~0.9sの実機で数量確定に届かず unsettled 空転した
                # （2026-10-14）。上限は hard_deadline が保証する。
                deadline = max(deadline, time.time() + KINAKO_SETTLE_SEC)
            if steady:
                rec = kinako_recover_point(cur, kp)
                plus = kinako_plus_point(cur, rec)
                over = kinako_over_cap(cur, rec)
                # 数量欄の位置は「+」から決まる。「+」が演出に隠れたフレームでは、行（=「回復」）から
                # 求めた既定の相対位置（実測: 「回復」中心の 0.089w 左）を使う。
                ref = plus if plus is not None else (rec[0] - 0.089 * cur.shape[1], rec[1])
                # --- OCR 読み取り（行基準の切り出し。各 ~23ms、ダイアログ上でだけ呼ぶ）---
                if per_pan is None:
                    per_pan = self._per_pan_ocr(cur, kp)
                v = self._life_ocr(cur, kp)
                if v is not None:
                    life = v
                if not gain_checked and life is not None:
                    # 「回復を押したのに現在 LIFE が増えない」が続いたときの歯止め。
                    # このダイアログの LIFE が直前の回復時点より増えていればリセット。
                    gain_checked = True
                    prev = getattr(self, "_kinako_prev_life", None)
                    if prev is not None:
                        if life > prev:
                            self._life_no_gain = 0
                        else:
                            self._life_no_gain = getattr(self, "_life_no_gain", 0) + 1
                            if self._life_no_gain >= MAX_LIFE_NO_GAIN:
                                return "life_no_gain", best_ks, cur
                if per_pan is not None and life is not None:
                    n_target = max(1, min(KINAKO_MAX_PER_RECOVER,
                                          -(-(cost - life) // per_pan)))
                q = self._qty_ocr(cur, ref)
                # 同じ読みが続くまで確定しない（カウントアップ途中の誤読で「−」を押さない）。
                # バッジだけは即座に扱う（読み取りを待つ必要がない）。
                if not qty_seq or qty_seq[-1] != q:
                    qty_seq = [q]
                else:
                    qty_seq.append(q)
                settled = q is not None and len(qty_seq) >= KINAKO_SETTLE_READS
                if over:
                    # **赤いバッジが出ている間は「回復」を押さない**（上の分岐に来ない）。
                    # 数量に関係なく「−」で戻す。
                    low_since = high_since = None
                    minus = kinako_minus_point(cur, ref)
                    if minus is not None and minus_taps < KINAKO_MINUS_MAX:
                        self.click_match(minus)
                        minus_taps += 1
                        self.kinako_plus_at = (time.time(), kp, plus or ref)
                        plussed = True     # 数量は既に 1 より多い。「+」は押さない
                        deadline = max(deadline, time.time() + KINAKO_POST_CLICK_SEC)
                        time.sleep(KINAKO_STEP_GAP)
                        qty_seq = []
                        just_clicked = True   # 押した後は撮り直して2枚揃うのを待つ
                elif settled and q == n_target:
                    qty = f"{q}個（数量欄 {q} を確認）"
                    break
                elif settled and q < n_target:
                    high_since = None
                    if plus is not None and not plussed:
                        for _ in range(n_target - q):
                            self.click_match(plus)
                            time.sleep(KINAKO_STEP_GAP)
                        self.kinako_plus_at = (time.time(), kp, plus)
                        self._kinako_plus_clicked = True
                        plus_clicked = True
                        plussed = True
                        deadline = max(deadline, time.time() + KINAKO_POST_CLICK_SEC)
                        qty_seq = []
                        just_clicked = True
                    elif plus is None and not plussed:
                        qty = f"{q}個（「+」が見つからない）"
                        break
                    else:
                        # plussed なのに n に届かない: 反映待ち。KINAKO_LOW_SETTLE_SEC を
                        # 超えても増えなければ在庫上限とみなし、確定数量（≥1）で回復する
                        # （空転して kinako_unsettled で止めるより 1 個でも進める）。
                        if low_since is None:
                            low_since = time.time()
                        elif time.time() - low_since >= KINAKO_LOW_SETTLE_SEC:
                            qty = f"{q}個（「+」後も n={n_target} に届かず確定数量で回復）"
                            break
                elif settled and q > n_target:
                    low_since = None
                    # 確定数量が目標 n より多い（前回の積み増しが残っている等）→「−」で n に戻す。
                    # 「+」直後の誤読・カウントアップ途中の高読みで打ち消さないよう、
                    # plus_clicked なら KINAKO_HIGH_SETTLE_SEC 続くまで「−」を待つ。
                    minus = kinako_minus_point(cur, ref)
                    if minus is not None and minus_taps < KINAKO_MINUS_MAX \
                            and (not plus_clicked
                                 or (high_since is not None
                                     and time.time() - high_since >= KINAKO_HIGH_SETTLE_SEC)):
                        self.click_match(minus)
                        minus_taps += 1
                        self.kinako_plus_at = (time.time(), kp, plus or ref)
                        plussed = True     # 数量は既に 1 より多い。「+」は押さない
                        deadline = max(deadline, time.time() + KINAKO_POST_CLICK_SEC)
                        time.sleep(KINAKO_STEP_GAP)
                        qty_seq = []
                        just_clicked = True   # 押した後は撮り直して2枚揃うのを待つ
                        high_since = None
                    elif plus_clicked:
                        if high_since is None:
                            high_since = time.time()
                else:
                    low_since = high_since = None
            if time.time() >= deadline or time.time() >= hard_deadline:
                if seen_row:
                    self.log(f"[dbg] kinako未確定: 読み={qty_seq[-6:]} n={n_target} "
                             f"per_pan={per_pan} life={life} cost={cost} "
                             f"plus_clicked={plus_clicked} minus={minus_taps}")
                return ("unsettled" if seen_row else "kinako_missing"), best_ks, cur
            time.sleep(ADVANCE_STABLE_GAP if seen_row else KINAKO_RECHECK_GAP)
            prev_kp = None if just_clicked else (kp if ok else None)
            just_clicked = False
            cur = self._grab()
            on, ks, kp = look(cur)
            best_ks = max(best_ks, ks)
        if minus_taps:
            qty += f"・「−」{minus_taps}回で戻した"
        self.log(f"LIFE不足 → きなこパン{qty}で回復（{self.life_recovers}回目, ステラ不使用・"
                 f"行確認 score={ks:.2f}, 回復量={per_pan}, LIFE={life}, コスト={cost}）")
        try:
            from PIL import Image as _I
            _I.fromarray(cur).save(os.path.join(self.dbg_dir, "kinako_before_recover.png"))
        except Exception:
            pass
        self.click_match(rec)  # きなこパン行の「回復」
        self._kinako_prev_life = life   # 次のダイアログで「LIFE が増えたか」の比較元
        self.kinako_plus_at = None
        self._kinako_plus_clicked = False
        # ダイアログが消えて確認カード（「ライフをN回復しました」）に替わってから閉じる。
        # ダイアログが残ったまま押すと、確認の×の位置はダイアログ右端の×に近い。
        end = time.time() + LIFE_CONFIRM_WAIT_SEC
        lf_imgs, lf_thr = self.templates["lifefull"]
        while time.time() < end:
            time.sleep(0.15)
            card = self._still_frame(0.5)
            if card is None or look(card)[0]:
                continue   # 動いている／LIFE不足ダイアログがまだ出ている
            cbgr = cv2.cvtColor(card, cv2.COLOR_RGB2BGR)
            lsc, lpos = match_best(cbgr, lf_imgs)
            if lsc >= lf_thr:
                # 「ライフを全回復しました。」は背景タップでは閉じない。右上の × を押す。
                self.click_anchor(lpos, ANCH_LIFEFULL_X)
                break
            if life_card_like(card):
                self.click_window(*P_CARD_DISMISS)  # 確認カードは背景タップで閉じる
                break
        return "recovered", ks, cur

    def run(self):
        self.log(f"自動周回を開始（前面化, tap-mode={self.tap_mode}）。停止: ESCキー")
        caf = None
        if not self.dry_run:
            driver.activate()
            # Vision OCR のモデル読み込みは最初の 1 回だけ約 25 秒かかる（実測）。
            # LIFE 不足ダイアログで詰まらないよう、**ループを止めないバックグラウンドで**
            # 空画像を投げて済ませておく。Vision 未導入なら no-op。
            threading.Thread(target=ocr.warmup, daemon=True).start()
            # システムのアイドル/スリープ/ディスプレイ消灯を抑止（PAUSE対策の補助）。
            try:
                caf = subprocess.Popen(["caffeinate", "-dimsu"])
            except Exception as e:  # caffeinate が無くても続行
                self.log(f"[warn] caffeinate 起動失敗: {e}")

        # **SIGTERM でも caffeinate を確実に落とす。** supervisor は autolive を
        # `pkill -f tools/autolive.py`（SIGTERM）で入れ替えるが、既定のハンドラは
        # finally を通さずプロセスを終了させるため caffeinate が孤児として残り続ける。
        # 実測 2026-08-01: 一晩の周回で 5 個溜まり、周回を止めた後も Mac がスリープ
        # しない状態になっていた。
        def _cleanup(signum=None, _frame=None):
            if caf is not None and caf.poll() is None:
                caf.terminate()
            if signum is not None:
                sys.exit(EXIT_OK)

        for _sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(_sig, _cleanup)
            except (ValueError, OSError):
                pass          # メインスレッド以外では設定できない。致命ではない
        try:
            self._loop()
        finally:
            _cleanup()
        self.log(f"完了: {self.loops_done} 回クリア / "
                 f"{time.time() - self.t_start:.0f}s"
                 + (f" / 安全停止: {self.stop_reason}" if self.stop_reason else ""))
        return self.stop_reason

    def _loop(self):
        while self.loops_done < self.max_loops:
            self._iter_t0 = time.time()
            # ESC キルスイッチ（長押し）。グローバル検出ゆえ他アプリ向けの ESC タップを拾う
            # ため、ESC を ESC_HOLD_SEC 秒**押し続けた**ときだけ停止する（短タップは無視）。
            # --no-esc 指定時はキルスイッチ無効（自律実行用。停止は pkill）。
            if self.esc_enabled and esc_pressed():
                if self.esc_since is None:
                    self.esc_since = time.time()
                elif time.time() - self.esc_since >= ESC_HOLD_SEC:
                    self.log(f"ESC 長押し({ESC_HOLD_SEC}s)検出 → 停止")
                    break
            else:
                self.esc_since = None
            self._keep_front()
            self._refresh_window()
            _t = time.time()
            frame = driver.grab(self.win)
            _grab_dt = time.time() - _t
            _t = time.time()
            # 内容矩形は固定 (TITLEBAR_ROWS, h-9)。以前は暗い行から毎フレーム検出していたが、
            # ウィンドウ上端の透過部に写り込む背後のウィンドウの明暗で上端が 0 ⇔ 38、下端が
            # 339 ⇔ 347 と動き、内容相対で持つ円座標が縦に 6〜9px ずれていた（実測 2026-09-11）。
            # 円の較正キャッシュも OFF_* も固定矩形で較正されている。
            state, res = self.detect(frame)
            # 周回の本線に戻れたら復帰 episode は終わり（次に迷い込んだら 2 回目）。
            if state in ("gameplay", "songselect", "friendselect", "formation"):
                self.in_recovery = False
            # 通信エラーが解消したら連続カウントをリセットする（長時間運用では
            # 一時的なエラーが何度も起きうるので、通算ではなく連続で数える）。
            if state != "neterror":
                self.net_retries = 0
            _detect_dt = time.time() - _t
            # 内訳は「ライブ中（gameplay/pause）」と「それ以外」に分けて積む。
            # ライブ中だけの FPS・時間配分を出すため（ライブ後のメニュー画面の
            # 全段照合≈1秒/フレームが混ざるとライブ中の値が読めない）。
            _bucket = self._prof_bucket(state)
            _bucket["grab"] += _grab_dt
            _bucket["detect"] += _detect_dt
            _t = time.time()
            if self.max_seconds and time.time() - self.t_start > self.max_seconds:
                # ライブの途中では止めない（CLAUDE.md「ライブの途中で autolive を止めないこと」）。
                # リザルト以降の画面で抜ける。上限を MAX_SECONDS_GRACE 以上超えたら諦めて抜ける。
                if state in SAFE_EXIT_STATES or \
                        time.time() - self.t_start > self.max_seconds + MAX_SECONDS_GRACE:
                    self.log("時間上限に到達 → 終了"
                             + ("" if state in SAFE_EXIT_STATES else f"（{state} のまま猶予超過）"))
                    break
            if self.verbose:
                top3 = sorted(((v[0], k) for k, v in res.items()), reverse=True)[:3]
                self.log(f"state={state} top={['%s:%.2f' % (k, s) for s, k in top3]} "
                         f"content={self.content}")

            if state == "pause":
                now = time.time()
                if self.pause_since is None:
                    self.pause_since = now
                elif now - self.pause_since > PAUSE_STUCK_SEC:
                    # 「再開」を押し続けても PAUSE が消えない＝合成クリックが効いていない
                    # （再接続病）か PAUSE の上に別ダイアログ。スクショ保存して停止（要・繋ぎ直し）。
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"pause_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] PAUSE が {now - self.pause_since:.0f}s 続き「再開」が効かない"
                             f"（再接続病の可能性）→ {fn} 保存して停止")
                    self.stop_reason = "pause_stuck"
                    break
                # 注意: pause_resume.png は「PAUSE」見出し文字に一致する。マッチ位置を
                # クリックすると見出しを叩くだけで再開しない（旧バグ）。PAUSEメニューの
                # 「再開」ボタンは右下の固定位置 P_RESUME にあるためそこをクリックする。
                # **PAUSE のたびに最前面アプリを残す。** これが無いと原因 C/D を
                # 事後に切り分けられず、iPhone 再起動が要るのか運用の問題なのか判らない
                # （実際に判別できず調査をやり直した。docs/pause-causes.md）。
                fn = self._front_name()
                lost = not (("Mirroring" in fn) or ("ミラーリング" in fn))
                self.log(f"PAUSE → 再開 (front={fn})"
                         + ("  <<< 最前面を奪われている（原因C）" if lost else ""))
                self.click_anchor(res["pause"][2], ANCH_RESUME)
                time.sleep(0.4)
            elif state == "imessage":
                # iOS「iMessage と FaceTime をオンにしますか？」→ **使用しない** のみ押す。
                # 「オンにする」は SMS 送信で課金され得る旨がダイアログに明記されている。
                self.log("iOS iMessage/FaceTime 確認 → 使用しない")
                self.click_anchor(res["imessage"][2], ANCH_IMESSAGE_NO)
                time.sleep(0.8)
            elif state == "icloudsync":
                # iOS「一部の iCloud データは同期していません」→ **今はしない** のみ押す。
                # 「データの同期を再開」は端末の iCloud 設定を変えるので押さない。
                self.log("iOS iCloud 同期確認 → 今はしない")
                self.click_anchor(res["icloudsync"][2], ANCH_ICLOUD_NO)
                time.sleep(0.8)
            elif state == "battery":
                # iOSバッテリー残量低下警告 → 「閉じる」のみ押す（低電力モードは絶対に押さない）。
                self.log("バッテリー警告 → 閉じる（充電推奨）")
                self.click_match(res["battery"][2])
                time.sleep(0.6)
            elif state == "lifeshort":
                # LIFE不足ダイアログ。**きなこパンで回復し、ステラは絶対に使わない**。
                # 個数 n は「1個の回復量・現在 LIFE・LIFE コスト」を OCR で読んで決め、
                # きなこ行の「+」で数量を n へ → 回復 → 確認カードを閉じる、を1手順で
                # 行う（_recover_life）。1個の回復量はイベントで変わるので固定値は持たない。
                self.life_recovers += 1
                # **押す前に「きなこパン行が実在すること」を画像で確認する。**
                # 枯渇時は行が消えて詰まり、旧実装は同じオフセットでステラの「回復」を
                # 押していた（実機で既遂）。KINAKO_RECHECK_SEC 撮り直しても見つからなければ
                # **クリックせず停止**する（撮り直しの間も一切押さない）。
                status, kscore, kframe = self._recover_life(frame)
                if status == "life_no_gain":
                    # 「回復」を押したのに現在 LIFE が増えない読みが続いた。回復が
                    # 効いていない（在庫切れに近い・反映されない等）のにパンを浪費
                    # しないよう、**この呼び出しでは何も押していない**。停止する。
                    fn = os.path.join(self.dbg_dir,
                                      f"life_depleted_{int(time.time()-self.t_start)}.png")
                    from PIL import Image as _I
                    _I.fromarray(kframe).save(fn)
                    self.log(f"[warn] 「回復」を押しても現在 LIFE が増えない読みが "
                             f"{MAX_LIFE_NO_GAIN} 回続いた → {fn} 保存。"
                             f"ステラは使わず停止します。")
                    self.stop_reason = "life_short_persist"
                    break
                if status == "kinako_missing":
                    fn = os.path.join(self.dbg_dir,
                                      f"kinako_missing_{int(time.time()-self.t_start)}.png")
                    from PIL import Image as _I
                    _I.fromarray(kframe).save(fn)
                    self.log(f"[warn] きなこパン行が見つからない（{KINAKO_RECHECK_SEC:.0f}秒撮り直し, "
                             f"score={kscore:.2f}）→ {fn} 保存。"
                             f"**ステラ誤消費を避けるためクリックせず停止**します。")
                    self.stop_reason = "kinako_missing"
                    break
                if status == "recovered":
                    self.life_unsettled = 0
                else:
                    # 「回復」を押していない（ダイアログが消えた／行を確かめ切れなかった）。
                    # **枯渇の判定（MAX_LIFE_NO_GAIN）には数えない。**
                    self.life_recovers -= 1
                if status == "unsettled":
                    # 何もクリックしていないか、「+」だけ押した（「+」は1ダイアログ1回まで）。
                    self.life_unsettled = getattr(self, "life_unsettled", 0) + 1
                    self.log(f"LIFE不足 → きなこ行を確かめ切れず回復を押さずに再判定"
                             f"（{self.life_unsettled}/{MAX_LIFE_UNSETTLED}, score={kscore:.2f}）")
                    if self.life_unsettled >= MAX_LIFE_UNSETTLED:
                        fn = os.path.join(self.dbg_dir,
                                          f"kinako_unsettled_{int(time.time()-self.t_start)}.png")
                        from PIL import Image as _I
                        _I.fromarray(kframe).save(fn)
                        self.log(f"[warn] きなこ行を {MAX_LIFE_UNSETTLED} 回続けて確かめ切れない → "
                                 f"{fn} 保存。**ステラ誤消費を避けるためクリックせず停止**します。")
                        self.stop_reason = "kinako_unsettled"
                        break
            elif state == "gameplay":
                self.life_recovers = 0  # ライブに入れた＝LIFEは足りた
                self._kinako_prev_life = None   # 直前の回復の比較を無効化（増加判定はライブをまたがない）
                self._life_no_gain = 0
                now = time.time()
                if self.gameplay_since is None:
                    self.gameplay_since = now
                    if self.jitter is not None:
                        self.jitter.begin_live()   # ライブごとに恒常バイアスを引き直す
                # 円キャリブレーションは**成功するまでライブ中ずっと再試行**する。
                # ライブ突入の1フレームだけで試すと、リザルト間の暗転など「リングが
                # 描画されていない暗いフレーム」を掴んで検出0円で諦め、そのライブ全体を
                # 未補正のまま打鍵してしまう（実測: 機種差47pxのズレで MISS 51・グレードB）。
                if self.auto_circles and not self.circles_calibrated \
                        and now >= self.autocal_next_try:
                    self.autocal_next_try = now + AUTOCAL_RETRY_SEC
                    self._auto_calibrate_circles(frame)
                # リザルト間の暗い遷移(KEEP OUT等)を一瞬 gameplay と誤認してクリアを
                # 二重計上しないよう、gameplay が一定時間継続して初めて「ライブ中」とみなす。
                if now - self.gameplay_since > MIN_LIVE_SEC:
                    self.was_in_live = True
                if now - self.gameplay_since > GAMEPLAY_TIMEOUT_SEC:
                    # 1ライブの想定を大幅超過 = ミラーリング切断の暗いオーバーレイ等を
                    # gameplay と誤認している可能性。スクショ保存して停止（要・再接続）。
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"gameplay_timeout_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] gameplay が {now - self.gameplay_since:.0f}s 継続（異常/"
                             f"ミラーリング切断の可能性）→ {fn} 保存して停止")
                    self.stop_reason = "gameplay_timeout"
                    break
                if self.engine == "track":
                    # 実験: スポーン検出→追跡→レーン/ETAで打鍵（note_engine）。
                    self._gameplay_track(frame, now)
                elif self.tap_mode == "rotate":
                    # フォールバック: 5円を約50Hzで巡回連打。
                    idx = self.circle_i % len(CIRCLES)
                    self.circle_i += 1
                    self.click_content(*self._tap_point(idx))
                    self.last_input_ts = now
                    time.sleep(0.02)
                else:
                    # 既定: ノーツ到達を検出してタップ（無検出時はキープアライブ）。
                    self._gameplay_timing(frame, now)
            elif state == "friendreq":
                # EVENT RESULT のフレンド「申請する」。クリア計上もここで行う
                # （RESULT に到達した＝直前のライブは完走した）。
                if self.was_in_live:
                    self.loops_done += 1
                    self.was_in_live = False
                    self.starts_since_clear = 0
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）")
                    self._live_report()
                # 実際には連続ライブ「同じライブを同じ条件で再プレイしますか？」の**はい**
                # （friendreq_yes がピンクの「はい」に 0.86 で当たる。2026-10-11 実測）。
                # はいの直後に出る LIFE 不足ダイアログでは、この位置の **6px 上がステラ行の
                # 「回復」**（386..441, 225..246 @671x348）。detect() の数百 ms 前のフレームで
                # 押すと、ダイアログが切り替わった瞬間に着弾しうるので、**押す直前に静止した
                # 新しいフレームで「はい」がまだ同じ位置にあり、LIFE 不足ではないこと**を確かめる。
                fresh = self._still_frame(0.6)
                sc = self._scores(fresh, ("lifeshort", "friendreq")) if fresh is not None else None
                pos0 = res["friendreq"][2]
                if sc is None or sc["lifeshort"][0] >= sc["lifeshort"][1] \
                        or sc["friendreq"][0] < sc["friendreq"][1] \
                        or abs(sc["friendreq"][2][0] - pos0[0]) > 3 \
                        or abs(sc["friendreq"][2][1] - pos0[1]) > 3:
                    continue   # 画面が動いた・変わった。押さずに再判定する
                self.log("フレンド申請 → 申請する")
                self.click_match(sc["friendreq"][2])
                # 二度押し防止の待ちは「画面が変わるまで」（最大 1.5 秒）。旧: 固定 0.5 秒＋次の
                # detect で、はいを 1.4 秒おきに2回押していた（1回目はダイアログの出現アニメ中）。
                self._wait_change(fresh, 1.5)
            elif state == "replay":
                # 連続ライブ再プレイ確認 → 「はい」で同じ曲を再開（次のループへ）。
                if self.was_in_live:
                    self.loops_done += 1
                    self.was_in_live = False
                    self.starts_since_clear = 0
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）")
                    self._live_report()
                self.log("連続ライブ 再プレイ → はい")
                self.click_anchor(res["replay"][2], ANCH_REPLAY_YES)  # マッチ位置+オフセット（画像追従）
                time.sleep(0.9)   # 再プレイ「はい」→ライブ開始まで。詰めすぎると二度押し
            elif state == "lifefull":
                # 「ライフを全回復しました。」モーダル。**背景タップでは閉じない**（実機:
                # cardx に流れて P_CARD_DISMISS を約30回踏んでも残った）。カード右上の × を
                # 本文テンプレのマッチ位置からのオフセットで押す。閉じられず留まる場合は
                # watchdog で停止。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"lifefull_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] 全回復モーダルを閉じられず停滞 → {fn} 保存して停止")
                    self.stop_reason = "lifefull_stuck"
                    break
                self.log("全回復モーダル → × で閉じる")
                self.click_anchor(res["lifefull"][2], ANCH_LIFEFULL_X)
                # 二度押し防止の待ちは「画面が変わるまで」（最大 1.5 秒）。
                self._wait_change(frame, 1.5)
            elif state == "cardx":
                # 汎用カードポップアップ（報酬獲得/アイテム獲得/RANK UP 等）。**×でなく背景の
                # どこをタップしても閉じる**ため、色検出した×位置（背景汚染でばらつく）ではなく
                # 中央カードを外した背景（P_CARD_DISMISS）を叩いて確実に閉じる。閉じられず留まる
                # 場合は watchdog で停止。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"cardx_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] カードポップアップを閉じられず停滞 → {fn} 保存して停止")
                    self.stop_reason = "cardx_stuck"
                    break
                self.log("カードポップアップ → 背景タップで閉じる")
                self.click_window(*P_CARD_DISMISS)
                # 「ライフをN回復しました」や Event Result の pt ページは続けて出るので、同じ画面の
                # ままである間だけ短い間隔で叩き続ける（_advance_burst。LIFE不足・連続ライブの
                # ダイアログに替わったら止まる）。
                n = self._advance_burst("cardx", frame)
                if n:
                    self.log(f"カードポップアップ → 続けて背景タップ {n} 回")
            elif state == "closex":
                # カード型ポップアップ（獲得一覧 / 報酬獲得 / 申請完了 / 本日の課題 等）の×。
                # 閉じられず同じ画面に留まる場合は watchdog で停止（誤クリック無限ループ防止）。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"closex_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] ポップアップを閉じられず停滞 → {fn} 保存して停止")
                    self.stop_reason = "popup_stuck"
                    break
                # ×位置はポップアップ種別で異なる。中央アンカーの既知候補を巡回クリックして
                # 確実に閉じる（カードは中央配置・同pxサイズ＝端末非依存）。
                cand = CLOSEX_OFFSETS[self.closex_i % len(CLOSEX_OFFSETS)]
                self.closex_i += 1
                self.log(f"ポップアップ → ×（候補{cand}）")
                self.click_center_off(cand)
                time.sleep(0.5)
            elif state == "rankup":
                # RANK UP! ポップアップ（プレイヤーランク上昇。LIFE が MAX 回復＆上限増加）。
                # ×は右上の固定位置（窓相対・実測）。閉じられず留まる場合は watchdog で停止。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"rankup_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] RANK UP を閉じられず停滞 → {fn} 保存して停止")
                    self.stop_reason = "rankup_stuck"
                    break
                self.log("RANK UP → ×")
                self.click_anchor(res["rankup"][2], ANCH_RANKUP_X)
                time.sleep(0.6)
            elif state == "songselect":
                # 連戦が終わって楽曲選択へ戻った → 曲と難易度を確定してから NEXT。
                # NEXTテンプレのマッチ位置を直接クリック（端末非依存）。次状態で再検出して進める。
                # **通常ライブの楽曲選択なら NEXT を押さない（絶対規則 3）。** 左下にイベントバッジが
                # あるのは通常ライブ側。押してイベントトップへ移る（2026-09-12: ホームの EVENT リボンが
                # 無反応で、LIVE 経由で入る必要があった。ここで NEXT を押すと pt ゼロの通常ライブを回す）。
                _bs, _bp = match_best(self.bgr(frame), self.templates["eventbadge"][0])
                if _bp is not None and _bs >= TEMPLATES["eventbadge"][1]:
                    self.log(f"通常ライブの楽曲選択 → 左下のイベントバッジでイベントトップへ (score={_bs:.2f})")
                    self.click_match(_bp)
                    time.sleep(2.5)
                    continue
                if self.keep_selection:
                    # **現行運用（--keep-selection, 2026-10-20 ユーザー指定）**: 曲も難易度も選び直さない。
                    # 人が選んだ難易度をそのまま継続する（CLAUDE.md 絶対規則 2）。ここで EASY 固定タップを
                    # 走らせると、人が選んだ難易度を黙って EASY へ戻してしまう。選択状態はゲーム側が
                    # 保持するので、触らないのが安全側。
                    self.log("楽曲選択 → 曲・難易度は変更せず NEXT（--keep-selection）")
                else:
                    # **既定経路（旧運用）: EASY を選択** してから NEXT。人が明示的に選んだときだけ通る。
                    # **ユーザー要件: 楽曲は変更しない**。曲リスト（左側）は絶対にタップせず、現在
                    # 選択中の曲のまま進める。ここで触るのは EASY タブ（右下・難易度）と NEXT のみ。
                    # **ユーザー要件: 毎回「Don't Analyze Me」を選ぶ**（イベント効率が良い曲）。
                    # 一覧行をテンプレで探して当たればタップ。見つからなければ曲は変更しない
                    # （スクロール位置により画面外のことがあるため、無理に探し回らない＝安全側）。
                    sc, pos = match_best(self.bgr(frame), self.templates["songdaz"][0])
                    if pos is not None and sc >= TEMPLATES["songdaz"][1]:
                        self.log(f"楽曲選択 → Don't Analyze Me を選択 (score={sc:.2f})")
                        self.click_match(pos)
                        time.sleep(0.5)
                    else:
                        self.log(f"楽曲選択 → 対象曲が見つからず曲は変更しない (score={sc:.2f})")
                    self.click_window(*P_EASY_TAB)   # EASY タブを選択（難易度）
                    time.sleep(0.5)
                self.click_match(res["songselect"][2])
                # 二度押し防止の待ちは「画面が変わるまで」（最大 1.4 秒＝旧の固定値）。
                if not self._wait_change(frame, 1.4):
                    # 変わらなかった = 見えない蓋（「ライフを全回復しました。」等の
                    # モーダル）に NEXT が飲まれている可能性。2026-10-11 実機では
                    # この状態で NEXT を約30回・60秒空打ちした（当時は滞留の監視が
                    # 無く watchdog も効かなかった）。蓋そのものは lifefull 等の
                    # 専用判定で処理する。ここでは空打ちの回数だけ数え、限度を超えたら
                    # フレームを保存して停止する（蓋が判定不能な新種であるため）。
                    self.songsel_nochg += 1
                    if self.songsel_nochg >= SONGSELECT_NOCHANGE_MAX:
                        from PIL import Image as _I
                        fn = os.path.join(
                            self.dbg_dir,
                            f"songselect_stuck_{int(time.time() - self.t_start)}.png")
                        _I.fromarray(frame).save(fn)
                        self.log(f"[warn] NEXT を {self.songsel_nochg} 回押しても"
                                 f"楽曲選択から進まない → {fn} 保存して停止"
                                 f"（見えないモーダル等の蓋の可能性）")
                        self.stop_reason = "songselect_stuck"
                        break
                else:
                    self.songsel_nochg = 0
            elif state == "friendselect":
                # 上部の「♥-N」コストバッジを読んで覚えておく（LIFE 回復の個数 n の計算に使う。
                # 読めなければ直前の値を維持。未取得なら _life_cost() は KINAKO_ASSUMED_COST）。
                _cost = life_cost_ocr(frame)
                if _cost is not None:
                    self.life_cost = _cost
                # フレンド（サポート）選択 → **必ず一番上の行**（ユーザー要件）。
                # アピールスキル ラベルは全行に出るため、最良スコアではなく最上段を選ぶ。
                # **一覧が静止してから押す。** 遷移アニメ中の1回目のタップは無視され、旧実装は
                # 次の detect（約 2〜4 秒後）で押し直していた（2026-10-11 実測: 4.0 秒差の2回押し）。
                fresh = self._still_frame(1.5, gap=0.25)
                if fresh is None:
                    continue   # 動き続けている。押さずに再判定する
                score, pos = match_topmost(cv2.cvtColor(fresh, cv2.COLOR_RGB2BGR),
                                           self.templates["friendselect"][0],
                                           TEMPLATES["friendselect"][1])
                if pos is None:
                    continue   # 静止した画面にフレンド行が無い（別画面へ移った）。再判定する
                self.log("フレンド選択 → 最上段を選択")
                self.click_match(pos)
                # 直後は編成画面への遷移アニメ中。イベント装飾の帯を cardx と誤検出して
                # 右上の × を押してしまうため、この間は cardx を無視して START を待つ
                # （ユーザー要件: フレンド選択後は余計なタップをせず即 START）。
                self.suppress_cardx_until = time.time() + CARDX_SUPPRESS_SEC
                # 二度押し防止の待ちは「画面が変わるまで」（最大 1.0 秒＝旧の固定値）。
                self._wait_change(fresh, 1.0)
            elif state == "formation":
                # 上部の「♥-N」コストバッジを読んで覚えておく（friendselect と同じ）。
                _cost = life_cost_ocr(frame)
                if _cost is not None:
                    self.life_cost = _cost
                # 編成画面 → START（STARTテンプレのマッチ位置を直接クリック・端末非依存）。
                # **クリア無しで START が続いたら、押さずに停止する**（MAX_STARTS_WITHOUT_CLEAR）。
                # 同じ編成画面での押し直し（タップ無視→数秒後に再検出）は 10 秒以内として数えない。
                now = time.time()
                if now - self.last_start_ts > 10.0:
                    self.starts_since_clear += 1
                self.last_start_ts = now
                if self.starts_since_clear >= MAX_STARTS_WITHOUT_CLEAR:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"live_abandoned_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] クリア無しで START が {self.starts_since_clear} 回目 → "
                             f"直前のライブが放棄された疑い。{fn} 保存して停止"
                             f"（再接続病ならミラーリングを繋ぎ直す）")
                    self.stop_reason = "live_abandoned"
                    break
                self.log("編成画面 → START")
                self.click_match(res["formation"][2])
                time.sleep(2.0)
            elif state in ("dldialog", "download"):
                # データDL確認 → 必ず「ダウンロード」を押す（ユーザー指定）。中央アンカー。
                self.log("DLダイアログ → ダウンロード")
                self.click_anchor(res["dldialog"][2], ANCH_DOWNLOAD)
                time.sleep(1.8)
            elif state == "story":
                # 「ストーリー開放チケット…遷移しますか？」→ いいえ（周回継続）。中央アンカー。
                self.log("ストーリー遷移確認 → いいえ")
                self.click_anchor(res["story"][2], ANCH_STORY_NO)
                time.sleep(0.8)
            elif state == "resumelive":
                # 「前回のライブを再開しますか？」→ はい。中断されたライブの LIFE は
                # 消費済みなので、再開しないと丸損になる。
                self.log("ライブ再開確認 → はい（消費済みLIFEを回収）")
                self.click_anchor(res["resumelive"][2], ANCH_RESUME_YES)
                time.sleep(2.5)
            elif state == "dataupdate":
                # 「データ更新のためタイトルへ戻ります」→ はい。押さないと先に進めない。
                # この後タイトル→ホーム→（結果再送確認）と進む。
                self.log("データ更新 → はい（タイトルへ戻る）")
                self.click_anchor(res["dataupdate"][2], ANCH_DATAUPDATE_YES)
                time.sleep(6.0)
            elif state == "resendresult":
                # 「前回のライブ結果の送信が正しく終了しませんでした」→ **再送する**。
                # 「諦める」を選ぶと直前のライブぶんのイベント pt が失われる。
                self.log("ライブ結果の送信失敗 → 再送する（pt を失わない）")
                self.click_anchor(res["resendresult"][2], ANCH_RESEND_YES)
                time.sleep(6.0)
            elif state in ("title", "notice"):
                # 起動時の注意書き／タイトル。どちらも「TAP SCREEN」を押して先へ進む。
                # スプラッシュとローディングを挟むので待ちを長めに取る（実測 各6〜8秒）。
                if not self._enter_recovery(frame):
                    break
                if state == "notice":
                    # 注意書きは「TAP SCREEN」の文字自体が目印なのでその位置を押す。
                    self.log(f"起動時の注意書き → TAP SCREEN"
                             f"（復帰 {self.recovers}/{MAX_RECOVERS}）")
                    self.click_match(res["notice"][2])
                else:
                    # タイトルは右下の MENU が目印。文字は点滅し背景も動画なので、
                    # MENU からのオフセットで中央下の「TAP SCREEN」を押す。
                    self.log(f"タイトル画面 → TAP SCREEN"
                             f"（復帰 {self.recovers}/{MAX_RECOVERS}）")
                    self.click_anchor(res["title"][2], ANCH_TITLE_TAP)
                time.sleep(2.5)
            elif state == "news":
                # お知らせダイアログ → 右上の × で閉じる。ヘッダからのオフセットで押す。
                self.log("お知らせ → × で閉じる")
                self.click_anchor(res["news"][2], ANCH_NEWS_CLOSE)
                time.sleep(1.5)
            elif state == "home":
                # ホーム → **EVENT リボン**（ベージュのラベル帯＝累計イベント側）。
                # ホームの「LIVE」から入ると通常ライブでイベント pt が一切付かない（絶対規則3）
                # ので、ここでは EVENT ラベルのマッチ位置以外を絶対に押さない。
                self.home_taps += 1
                if self.home_taps > HOME_RIBBON_MAX_TAPS:
                    # EVENT リボンが無反応（2026-09-12 04:13 実機、位置を変えても無反応）。
                    # 下部ナビ LIVE → 通常楽曲選択 → 左下のイベントバッジ → イベントトップ、で迂回する。
                    # 通常楽曲選択では songselect ハンドラがバッジを優先するので NEXT は押されない。
                    _ls, _lp = match_best(self.bgr(frame), self.templates["navlive"][0])
                    if _lp is not None and _ls >= TEMPLATES["navlive"][1]:
                        self.log(f"ホーム → EVENT リボンが {self.home_taps - 1} 回無反応 → 下部ナビ LIVE から迂回")
                        self.click_match(_lp)
                        time.sleep(2.5)
                        continue
                self.log("ホーム → EVENT リボン")
                self.click_match(res["home"][2])
                time.sleep(2.0)
            elif state in ("loginbonus", "speciallogin"):
                # 04:00 リセットの LOGIN BONUS（2 ページ）／イベントの特別ログインボーナス。
                # どちらも画面タップで送る。閉じられなければ停止。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"loginbonus_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] ログインボーナスを閉じられず停滞 → {fn} 保存して停止")
                    self.stop_reason = "loginbonus_stuck"
                    break
                self.log(f"{'特別' if state == 'speciallogin' else ''}ログインボーナス → 画面タップで送る")
                self.click_window(*P_CARD_DISMISS)
                time.sleep(0.8)
            elif state == "eventtop":
                # イベントトップ → 「イベント楽曲」。この後 songselect に合流して周回へ戻る。
                self.log("イベントトップ → イベント楽曲")
                self.click_match(res["eventtop"][2])
                time.sleep(2.0)
            elif state == "breaktime":
                # **休憩時間中はイベント pt が一切入らない。「はい」を押すと LIFE だけ失う。**
                # きなこパン枯渇時のステラ誤消費と同種の「気づかず損をする」画面なので、
                # 必ず「いいえ」で戻ってから停止する。休憩時間帯はゲーム内のユーザー設定で
                # 可変なので、時刻からは判断しない（このダイアログだけが根拠）。
                self.log("[warn] 休憩時間中（pt が入らない）→ いいえ で戻り停止する")
                self.click_anchor(res["breaktime"][2], ANCH_BREAK_NO)
                time.sleep(1.5)
                from PIL import Image as _I
                fn = os.path.join(self.dbg_dir,
                                  f"break_time_{int(time.time() - self.t_start)}.png")
                _I.fromarray(frame).save(fn)
                self.log(f"[warn] 休憩時間帯は {fn} で確認できる")
                self.stop_reason = "break_time"
                break
            elif state == "neterror":
                # 「通信エラーが発生しました。」→ **リトライ**。
                # 「諦める」を選ぶとその周回ぶんを落とす。回線が落ちている場合に
                # 無限に粘らないよう、連続リトライ回数に上限を設ける。
                self.net_retries += 1
                if self.net_retries > MAX_NET_RETRIES:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"net_error_{int(time.time() - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] 通信エラーが {MAX_NET_RETRIES} 回続く "
                             f"→ {fn} 保存して停止（回線を確認すること）")
                    self.stop_reason = "net_error"
                    break
                self.log(f"通信エラー → リトライ（{self.net_retries}/{MAX_NET_RETRIES}）")
                self.click_anchor(res["neterror"][2], ANCH_NETERROR_RETRY)
                time.sleep(3.0)
            elif state == "nettimeout":
                # 「通信がタイムアウトしました。」→ 唯一のボタン「諦める」を押して閉じる。
                # リトライはないので neterror のリトライ上限とは別系（繰り返し出る場合は
                # menu watchdog / safe-stop が止める）。
                self.log("通信タイムアウト → 諦めるで閉じる")
                self.click_anchor(res["nettimeout"][2], ANCH_NETTIMEOUT_GIVEUP)
                time.sleep(2.0)
            elif state == "supported":
                # 「ライブをN回サポートしました。」→ はい。×が無いので背景タップでは閉じない。
                self.log("フレンドサポート通知 → はい")
                self.click_anchor(res["supported"][2], ANCH_SUPPORTED_YES)
                time.sleep(1.5)
            elif state == "dailytask":
                # イベントトップの「本日の課題」→ 右上の × で閉じる。
                # 暗いので gameplay と誤判定されるが、打鍵させてはいけない
                # （円の位置に「イベント楽曲へ」ボタンがある）。
                self.log("本日の課題 → × で閉じる")
                self.click_anchor(res["dailytask"][2], ANCH_DAILYTASK_X)
                time.sleep(1.5)
            elif state == "liveassist":
                # ライブアシスト選択 → **何も選ばず START**（アイテム消費なしでライブ開始）。
                self.log("ライブアシスト → 未選択のままSTART")
                self.click_anchor(res["liveassist"][2], ANCH_LIVEASSIST_START)
                time.sleep(1.2)
            elif state in ("result", "eventresult", "expresult"):
                # per-song Result / EVENT RESULT。クリア計上し、右側の背景タップで送る。
                now = time.time()
                if self.was_in_live:
                    self.loops_done += 1
                    self.was_in_live = False
                    self.starts_since_clear = 0
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）"
                             f" 打鍵{self.tap_count}回 / 判定{self.frame_count}フレーム")
                    # ライブ中だけの内訳・FPS・経路と、曲非依存の警告を出して
                    # カウンタをリセットする（警告の指標は LIVE_FPS_WARN /
                    # LIVE_MERGED_WARN_SEC のコメント参照）。
                    self._live_report()
                    self.result_since = None  # クリア計上＝進捗。停滞タイマーをリセット
                # 想定外オーバーレイ（iOSシステムダイアログ等）で result 誤判定→中央タップが
                # 効かず無限ループするのを検知して停止（スクショ保存）。
                if self.result_since is None:
                    self.result_since = now
                if now - self.result_since > RESULT_STUCK_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir,
                                      f"result_stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] Result送りが {now - self.result_since:.0f}s 進まず停滞 → "
                             f"{fn} 保存して停止（システムダイアログ等のオーバーレイの可能性）。")
                    self.stop_reason = "result_stuck"
                    break
                # 送りタップは右側の背景 P_CARD_DISMISS（カードポップアップと同じ審査済みの点）。
                # 同じ状態に ADVANCE_ALT_SEC 留まったら、その状態だけ従来の中央送りへ戻す。
                self._advance_fallback_check(state, now)
                self._advance_tap(state)
                # 送り画面のままである間は短い間隔で叩き続ける（1回の detect が 1〜3 秒かかるため、
                # 「detect → 1タップ」では送りの実効間隔がその秒数になっていた）。
                n = self._advance_burst(state, frame)
                if n:
                    self.log(f"{state} → 続けて送りタップ {n} 回")
            elif int(self.win["w"]) < int(self.win["h"]):
                # ミラーリング切断ダイアログ（縦長。ゲーム画面は常に横向き）。
                # ゲーム内の未知画面ではないので止めずに待機する。再確認は
                # _refresh_window(2s) が担い、接続が戻れば同じ autolive が続く。
                # 回復が長引くときは runner/supervisor 側が安全停止→再開を請け負う。
                self.menu_since = None
                time.sleep(1.0)
            else:  # menu: 未知の明るい画面（ローディング/遷移/未知ダイアログ）
                # **未知画面ではクリックしない**（誤爆して別画面へ迷い込む＝連鎖暴走やステラ
                # 誤使用を防ぐ）。短い遷移は待てば次状態へ解決する。一定時間抜けられなければ
                # スクショを保存して安全に停止する（テンプレ未対応＝要バリアント追加の合図）。
                now = time.time()
                if self.menu_since is None:
                    self.menu_since = now
                if now - self.menu_since > STUCK_STOP_SEC:
                    from PIL import Image as _I
                    fn = os.path.join(self.dbg_dir, f"stuck_{int(now - self.t_start)}.png")
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] 未知画面に {now - self.menu_since:.0f}s 停滞 → "
                             f"{fn} 保存して安全停止（テンプレ未対応の可能性）。")
                    self.stop_reason = "unknown_screen"
                    break
                time.sleep(0.3)
            if state != "home":
                self.home_taps = 0
            if state != "songselect":
                self.songsel_nochg = 0
            # 進捗のある状態に遷移したら停滞タイマーをリセット。menu/rankup/closex は
            # 同画面ループの可能性があるのでタイマーを維持し watchdog 対象とする。
            if state not in ("menu", "rankup", "closex", "cardx", "lifefull",
                             "loginbonus", "speciallogin"):
                self.menu_since = None
            # result/eventresult を抜けたら（=進捗）Result停滞タイマーをリセット。
            _act_dt = time.time() - _t
            _bucket["act"] += _act_dt
            _bucket["sec"] += time.time() - self._iter_t0
            if state not in ("result", "eventresult"):
                self.result_since = None
            if state not in ("result", "eventresult", "expresult"):
                self.advance_since = None
            if state in ("gameplay", "pause"):
                self._gp_left_ts = time.time()
            elif time.time() - self._gp_left_ts > GAMEPLAY_GAP_SEC:
                # gameplay から外れて GAMEPLAY_GAP_SEC 以上経過＝ライブが本当に終わった。
                # 数秒の明るい演出（menu 誤判定）やリザルト間の暗い遷移では**リセットしない**
                # （演出ごとにリセットされると was_in_live が立たず、クリアが計上されない。
                # 実機でクリア0・警告0のまま live_abandoned まで到達した。2026-10-11）。
                # 併せて timing 検出のベースラインも次ライブ用にリセットする。
                self.gameplay_since = None
                if any(b is not None for b in self.note_baseline):
                    self.note_baseline = [None] * len(CIRCLES)
                    self.note_rearmed = [True] * len(CIRCLES)
            if state != "pause":
                self.pause_since = None


def calibrate(seconds=15.0):
    """各円ROIの white割合 統計を出力（しきい値調整用）。タップはしない。
    ※キャリブ中はユーザーが手動プレイして実タッチで PAUSE を防ぐこと。"""
    al = AutoLive(1, dry_run=True)
    win = al.win
    samples = [[] for _ in CIRCLES]
    t0 = time.time()
    n = 0
    print(f"[calibrate] {seconds}s 計測開始（手動でライブをプレイしてください）", flush=True)
    while time.time() - t0 < seconds:
        frame = driver.grab(win)
        if frame_brightness(frame) < DARK_THRESH:  # gameplay フレームのみ
            for i in range(len(CIRCLES)):
                samples[i].append(al._roi_white_frac(frame, i))
            n += 1
        time.sleep(0.02)
    print(f"[calibrate] gameplay フレーム {n} 件", flush=True)
    for i, s in enumerate(samples):
        if not s:
            print(f"  円{i}: データなし")
            continue
        a = np.sort(np.array(s))
        p = lambda q: float(a[min(len(a) - 1, int(len(a) * q))])
        print(f"  円{i} ({CIRCLES[i]}): min={a[0]:.3f} p50={p(0.5):.3f} "
              f"p95={p(0.95):.3f} max={a[-1]:.3f}")
    print("→ NOTE_BASELINE_FRAC は各円 p50 をやや上回る値、"
          "NOTE_TRIGGER_FRAC は p50〜p95 の差を目安に設定。", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loops", type=int, default=10, help="目標クリア回数")
    ap.add_argument("--dry-run", action="store_true", help="クリックせず判定のみ")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=None, help="実行時間の上限(秒)")
    ap.add_argument("--tap-mode", choices=["timing", "rotate"], default=TAP_MODE_DEFAULT,
                    help="ライブ中の打鍵方式（既定 timing=ノーツ検出, rotate=巡回連打）")
    ap.add_argument("--calibrate", action="store_true",
                    help="円ROIの white割合 統計を出力してしきい値調整（タップしない）")
    ap.add_argument("--note-trigger", type=float, default=NOTE_TRIGGER_FRAC,
                    help="timing: タップ発火のwhite割合しきい値（ベースライン超過分）")
    ap.add_argument("--note-lead", type=float, default=NOTE_ROI_LEAD,
                    help="timing: ROIを中心側へ寄せる早撃ち量")
    ap.add_argument("--note-roi", type=float, default=NOTE_ROI_RADIUS,
                    help="timing: 円ROI半径（ウィンドウ幅相対）")
    ap.add_argument("--holds", action="store_true",
                    help="長押し（緑）対応を有効化（実験的。明るさ持続で検出するがタップ波紋に"
                         "誤反応しやすく既定では無効）")
    ap.add_argument("--flick", action="store_true",
                    help="赤ノーツでフリック（到達直前ROIで赤検出→タップ＋外向きスワイプ）。§17.9")
    ap.add_argument("--green-hold", action="store_true",
                    help="緑ノーツを長押し（approach点の緑画素数で開始・解除を判定）。"
                         "**長押し中は他レーンを取れない**（カーソル1点のため）。既定OFF")
    ap.add_argument("--hold-max-sec", type=float, default=HOLD_MAX_SEC,
                    help=f"1ホールドの最大保持秒（既定 {HOLD_MAX_SEC}）。誤検出でも必ず離す上限")
    ap.add_argument("--predict", action="store_true",
                    help="track並走の種別先読みで緑ホールド/赤フリックを出し分け"
                         "（実験的・既定OFF。不調時は自動でタップに劣化）")
    ap.add_argument("--auto-circles", action="store_true",
                    help="ライブ突入時にタップ円リングを画像検出して円座標を自動補正"
                         "（実験的・既定OFF。4円全一致時のみ置換、失敗時は現行値維持）")
    ap.add_argument("--engine", choices=["roi", "track"], default="roi",
                    help="ライブ中の打鍵エンジン。roi=現行(到達点の明るさ・安定)、"
                         "track=実験(スポーン検出+追跡)。既定 roi")
    ap.add_argument("--no-esc", action="store_true",
                    help="ESC キルスイッチを無効化（自律実行用。停止は pkill -f autolive.py）")
    ap.add_argument("--no-tap-jitter", action="store_true",
                    help="打鍵の着弾点ジッターを無効化（既定は有効）。"
                         "従来どおり円中心ちょうどを叩く。A/B 比較用")
    ap.add_argument("--keep-selection", action="store_true",
                    help="楽曲選択で曲も難易度も選び直さない（累計イベント以外の例外運用）。"
                         "既定は Don't Analyze Me + EASY を固定する")
    args = ap.parse_args()
    if args.calibrate:
        calibrate()
        return
    reason = AutoLive(args.loops, dry_run=args.dry_run, verbose=args.verbose,
                      max_seconds=args.max_seconds, tap_mode=args.tap_mode,
                      note_trigger=args.note_trigger, note_lead=args.note_lead,
                      note_roi=args.note_roi, holds=args.holds, engine=args.engine,
                      esc_enabled=not args.no_esc, flick=args.flick,
                      predict=args.predict, auto_circles=args.auto_circles,
                      green_hold=args.green_hold,
                      hold_max_sec=args.hold_max_sec,
                      tap_jitter=not args.no_tap_jitter,
                      keep_selection=args.keep_selection).run()
    # 安全停止は **人間の確認が必要** なので、supervisor に再起動させないよう
    # 専用の終了コードで抜ける（正常終了と区別できないと空転ループになる）。
    sys.exit(EXIT_SAFE_STOP if reason else EXIT_OK)


if __name__ == "__main__":
    main()
