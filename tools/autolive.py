#!/usr/bin/env python3
"""アイドリッシュセブン 累計イベント ライブ自動周回スクリプト。

iPhone ミラーリング経由で、イベントライブを自動で繰り返しクリアし続ける。

設計の要点（実機調査で判明。詳細は docs/specification.md §17.5-17.6）:
- 画面取得は mss（フォーカスを奪わない）。screencapture -l は PAUSE を誘発するため不可。
- ライブ中の打鍵は2モード（--tap-mode, 既定 timing）:
  - timing: 各タップ円に明るいノーツが到達した瞬間を検出してタップ（_gameplay_timing）。
    円ごとのEMAベースライン比較＋デバウンス。取得+クリック遅延のため ROI を中心側へ早撃ち。
    ノーツ無し区間は _keepalive が genuine 入力を出し続け PAUSE を防ぐ。
    ※種別はタップ最適化。フリック/スライド/ロングは頭だけ取得＝部分点（スワイプ非対応）。
    しきい値は --calibrate / --note-* で実機調整可能（docs/specification.md §17.5）。
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

ライブ中の自動PAUSE対策（解決済み・最重要。docs/specification.md §17.6 F）:
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
import os
import subprocess
import sys
import time

import numpy as np
import cv2
import Quartz

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import driver  # noqa: E402

# --- ライブ中の自動PAUSE対策（実機実験で確定。docs/specification.md §17.6 E/F） ---
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
# **ユーザー要件: 必ず EASY で周回する**。NEXT を押す前に EASY(緑・最左)タブをタップして固定。
P_EASY_TAB = (0.644, 0.718)      # EASY タブ中心（窓相対・実測。緑タブ「EASY✦ LIFE 15」）
# 未知の明るい画面で“やむを得ず”触る安全位置（最下端マージン）。ダイアログのボタン帯
# (y≈0.74-0.88) や本文・×を避けるため、ボタンが置かれない最下端だけを軽く叩く。
P_MENU_SAFE = (0.50, 0.97)
# カード型ポップアップ（報酬獲得/アイテム獲得/RANK UP 等）を閉じる位置。これらは**×でなく
# 背景（暗転部）のどこをタップしても閉じる**（実機確認。×自体のクリックでは閉じない）。
# 中央のカードを外した位置を叩くが、**左下はカーソルがDock/ホットコーナー付近へワープして
# 危険**なため（ユーザー指摘）、カード外の**右上の暗い背景**を叩いて閉じる（端末非依存）。
P_CARD_DISMISS = (0.86, 0.16)

# --- 端末非依存のクリック（中央アンカー方式） ---
# ダイアログ/ポップアップは画面中央に同pxサイズで出る（端末間でUIは同サイズ・実測で確認）。
# よって「ゲーム中央 + 固定pxオフセット」で押せば端末非依存になる。オフセットは SE 実測値。
# SE ゲーム中央 = (win中央x=264.5, 内容矩形中央y=(38+325)/2=181.5)。
SE_GAME_CENTER = (264.5, 181.5)
OFF_RESUME = (100.5, 72.5)        # PAUSE メニュー「再開」
OFF_REPLAY_YES = (64.5, 65.5)     # 連続ライブ再プレイ「はい」
OFF_DOWNLOAD = (56.5, 78.5)       # データDL「ダウンロード」
OFF_STORY_NO = (-58.5, 69.5)      # ストーリー遷移「いいえ」
OFF_KINAKO = (76.5, -11.5)        # LIFE不足ダイアログ きなこパン「回復」（上段。ステラ下段は触らない）
OFF_LIFE_CONFIRM = (148.0, -44.5) # 「ライフをN回復しました」確認の×
OFF_RANKUP_X = (159.5, -97.5)     # RANK UP! ×（大型カード右上）
OFF_RESULT_ADV = (0.0, 2.0)       # Result/EVENT RESULT 中央送り
OFF_MENU_SAFE = (0.0, 142.5)      # 未知メニューの安全タップ（中央やや下）
# カード型ポップアップ（報酬獲得/獲得一覧/申請完了/本日の課題 等）の×候補（中央からのpxオフセット）。
# 大型/中型/縦長カードで×位置が異なるため巡回。
CLOSEX_OFFSETS = [(159.5, -97.5), (124.5, -66.5), (148.0, -44.5)]

# --- anchor-offset: テンプレのマッチ位置からの固定pxオフセットでボタンを押す（画像追従・端末非依存） ---
# 各値 = SE実測の (ボタン位置 - テンプレマッチ中心)。UIは端末間で同pxサイズのため px固定で可。
# SEではマッチ位置=SEテンプレ中心なので元のボタン座標を再現（回帰維持）。
ANCH_RESUME = (101.0, 161.0)      # pause_resume 見出し → 再開ボタン
ANCH_REPLAY_YES = (86.0, 125.0)   # 連続ライブ 見出し → はい
ANCH_DOWNLOAD = (55.0, 84.0)      # DL本文 → ダウンロード
ANCH_STORY_NO = (-68.0, 76.0)     # ストーリー本文 → いいえ
ANCH_KINAKO = (128.0, 62.0)       # ライフが足りません → きなこパン「回復」（上段。ステラ下段は触らない）
ANCH_RANKUP_X = (160.0, -56.0)    # RANK UP! 見出し → ×

# ライブのタップ判定円（5箇所, 内容相対小数）。
CIRCLES = [
    (0.16, 0.63), (0.33, 0.85), (0.49, 0.93),
    (0.62, 0.85), (0.74, 0.63),
]

# --- ライブ中の打鍵モード ---
# "timing": 各円にノーツ（明るい光球）が到達した瞬間を検出してタップ（既定）。
# "rotate": 5円を約50Hzで巡回連打（実績あるフォールバック。誤チューニング時の保険）。
TAP_MODE_DEFAULT = "timing"
# タイミング検出のパラメータ（--calibrate と --note-* で実機調整可能。docs/specification.md §17.5）。
ARC_CENTER = (0.49, 0.50)        # ノーツ放射の中心（円ROIを早撃ち方向へ寄せる基準）
NOTE_ROI_RADIUS = 0.035          # 円ROI半径（ウィンドウ幅相対, ~18px@529w）
NOTE_ROI_LEAD = 0.025            # ROIを ARC_CENTER 側へ寄せる量＝取得+クリック遅延の早撃ち補正。
                                 # 実測較正(EASY/SOL TRIGGER): 0.04→0.025 で MISS 12→9・SS昇格・
                                 # スコア+14k。0.015 は早撃ち不足で PERFECT 低下。ループ高速化
                                 # (pause照合間引き=DARK_RECHECK_SEC)でレイテンシ減→leadを縮小。
NOTE_WHITE_V = 170               # min(R,G,B) > これ を「白っぽい（ノーツ）」画素とみなす
NOTE_TRIGGER_FRAC = 0.06         # white割合がベースライン+これ を超えたらタップ発火
NOTE_BASELINE_FRAC = 0.20        # white割合がこれ未満の静穏フレームのみEMAベースラインに取り込む
NOTE_BASELINE_EMA = 0.1          # ベースラインEMAの追従係数
NOTE_DEBOUNCE_SEC = 0.18         # 1ノーツ=1タップ（タップ波紋の再発火も抑止）
# --- ホールド（長押し＝緑ノーツ）対応。色ではなく「明るさが持続」することで検出する ---
# 円ROIがトリガー超えのまま HOLD_SUSTAIN_FRAMES フレーム続いたら長押しノーツとみなし、
# 明るさが続く限り押下を保持（drag で genuine 入力＝PAUSE防止）。タップ波紋の短い持続では
# 発火しないようフレーム数はやや多め。安全のため HOLD_MAX_SEC で必ず離す（誤検出の暴走防止）。
HOLD_SUSTAIN_FRAMES = 14         # この連続フレーム数トリガー超持続で「長押し」と判定（≈0.45s@30fps）。
                                 # タップ波紋は~0.2-0.3s持続するため、誤検出回避に本物の長押し
                                 # (0.5s+)が確実に超える値に設定（6では波紋を誤検出した実測）。
HOLD_MAX_SEC = 2.5               # 1ホールドの最大保持秒（誤検出でも必ず離す上限）
HOLD_REL_FACTOR = 0.45           # 保持解除のしきい（trigger×これ を下回ったら離す＝ヒステリシス）
# --- 実験的トラッキングエンジン(engine=track) ---
TRACK_ARRIVE_PX = 34.0           # ノーツがレーン円のこのpx内に来たら打鍵
TRACK_FORGET_SEC = 6.0           # acted集合を周期クリア（id枯渇/メモリ防止。ライブ跨ぎ）
KEEPALIVE_GAP_SEC = 0.6          # 無検出がこの秒続いたら genuine 入力を1発（PAUSE防止, 0.7s未満）

# テンプレ（assets/templates/*.png）。明るさゲートと併用し高閾値照合する。
# 判定順序は detect() を参照（friendreq → replay → closex → ...）。
TEMPLATES = {
    "pause": ("pause_resume.png", 0.78),       # 「PAUSE」見出し文字（暗背景でも確実）
    "lifeshort": ("life_short.png", 0.85),     # LIFE不足ダイアログ「ライフが足りません。」
    "friendreq": ("friendreq_yes.png", 0.74),  # EVENT RESULT の「申請する」ボタン
    "replay": ("replay_title.png", 0.82),      # 連続ライブ再プレイ確認の「連続ライブ」見出し
    "closex": ("close_x.png", 0.87),           # カード型ポップアップ右上の×（緑, 本物≈0.94）
                                               # ※Result画面の誤検出(≈0.84)を避けるため0.87
    "rankup": ("rankup.png", 0.78),            # 「RANK UP!」文字（× フォールバック用）
    "dldialog": ("dl_dialog.png", 0.85),       # データDL確認ダイアログ本文「をダウンロードします。」
    "story": ("story_dialog.png", 0.85),       # 「ストーリー開放チケット…遷移しますか？」→ いいえ
    # 旧 download_btn.png は「ライブの説明」チュートリアル等を誤検出(0.88)したため撤去。
    # DL確認は dldialog（本文テンプレ, 0.85）でのみ判定する。
    "result": ("result_title.png", 0.55),      # per-song「Result」文字（誤検出は中央タップのみで安全）
    # EVENT RESULT 見出し「-EVENT RESULT-」（緑・大文字・斜体）。per-song Result とは別字形。
    # 申請する押下後は friendreq が消えて未知画面化し停止していたため専用テンプレで送る。
    # KEEP OUT テープが他画面の同高さに出て斜体太字が構造相関する(≈0.67)ため閾値は高め(0.85)。
    "eventresult": ("eventresult_title.png", 0.85),
    "songselect": ("song_select.png", 0.85),   # 楽曲選択画面の「NEXT」ボタン（連戦終了で戻る）
    "friendselect": ("friend_select.png", 0.85),  # フレンド（サポート）選択画面
    "formation": ("formation.png", 0.85),      # 編成画面の「START」ボタン
}

# --- LIFE 回復（ユーザー要件: きなこパンで回復・ステラは絶対に使わない） ---
P_KINAKO_RECOVER = (0.644, 0.508)  # 「ライフが足りません」ダイアログ上段=きなこパンの「回復」
P_LIFE_CONFIRM_X = (0.78, 0.41)    # 「ライフをN回復しました」確認ポップアップの×
# ステラストーンの「回復」は下段(約 (0.644,0.69))にある。**絶対にクリックしない**。
# きなこパン1個で LIFE +20 回復（ライブ消費16を上回る）。在庫切れ時はステラを使わず停止する。
MAX_LIFE_RECOVERS = 6              # 連続でこの回数 LIFE 不足が続いたら（=きなこパン枯渇）停止
# テンプレ照合のスケール候補。端末でUIサイズはほぼ同じ(≈1.0で一致)だが、機種差に備え
# ±20%程度を見て数点を試す（タイトルバー有無の0.86も維持）。
SCALES = [0.8, 0.86, 0.93, 1.0, 1.08, 1.18]
# 明るさ閾値: これ未満ならライブ中（暗い画面）
DARK_THRESH = 65.0
# 暗い画面（gameplay/PAUSE）では、重い pause/songselect テンプレ照合を毎フレームせず
# この秒数おきに間引く。PAUSE・暗いsongselectはタイミング非依存なので数フレーム遅れて
# 検出してよく、間引くぶんノーツ検出のサンプリングレートが上がり打鍵精度が向上する。
DARK_RECHECK_SEC = 0.25
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
# gameplay がこの秒数継続して初めて「ライブ中」とみなす（クリア二重計上防止）。
# リザルト間の暗い遷移は数秒で終わるため、1ライブ(≈115s)未満の閾値にする。
MIN_LIVE_SEC = 20.0


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


def match_best(frame_bgr, imgs):
    """複数テンプレ候補(端末別variant)のうち最良の (score, center_px) を返す。"""
    best = (0.0, None)
    for im in imgs:
        score, pos = match_multiscale(frame_bgr, im)
        if score > best[0]:
            best = (score, pos)
    return best


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


def detect_content_rect(frame_rgb):
    """ウィンドウ画像内の「ゲーム内容矩形」(top,bottom 行) を検出。

    macOS のタイトルバー（明るい帯）を除外。ゲーム上下が暗いことを利用する。
    戻り値: (top, bottom) ピクセル行。横は全幅とみなす。
    """
    H = frame_rgb.shape[0]
    rb = frame_rgb.mean(axis=(1, 2))
    top = 0
    for y in range(H):
        if rb[y] < 70:
            top = y
            break
    bottom = H - 1
    for y in range(H - 1, -1, -1):
        if rb[y] < 70:
            bottom = y
            break
    if bottom - top < H * 0.5:  # 検出失敗時は全体
        return 0, H - 1
    return top, bottom


def match_multiscale(frame_bgr, templ):
    """マルチスケールでテンプレ照合。最大スコアと一致中心(ピクセル)を返す。"""
    fh, fw = frame_bgr.shape[:2]
    best = (0.0, None)
    for s in SCALES:
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


class AutoLive:
    def __init__(self, max_loops, dry_run=False, verbose=False, max_seconds=None,
                 tap_mode=TAP_MODE_DEFAULT, note_trigger=NOTE_TRIGGER_FRAC,
                 note_lead=NOTE_ROI_LEAD, note_roi=NOTE_ROI_RADIUS, holds=False,
                 engine="roi"):
        self.max_loops = max_loops
        self.dry_run = dry_run
        self.verbose = verbose
        self.max_seconds = max_seconds
        self.tap_mode = tap_mode
        self.note_trigger = note_trigger
        self.note_lead = note_lead
        self.note_roi = note_roi
        self.templates = load_templates()
        self.win = driver.find_window()
        self.loops_done = 0
        self.was_in_live = False
        self.circle_i = 0
        self.closex_i = 0           # closex 候補位置の巡回インデックス
        self.life_recovers = 0      # 連続 LIFE 回復回数（きなこパン枯渇検知用）
        self.gameplay_since = None  # gameplay 連続継続の開始時刻（異常検知用）
        # --- タイミング検出（timing モード）用 ---
        self.note_baseline = [None] * len(CIRCLES)  # 円ごとの white割合 EMA ベースライン
        self.note_last_tap = [0.0] * len(CIRCLES)   # 円ごとの直近タップ時刻（デバウンス）
        self.holds = holds          # 長押し（緑）対応の有効/無効
        self.note_hi_frames = [0] * len(CIRCLES)  # 円ごとのトリガー超持続フレーム数（長押し検出）
        self.hold_idx = None        # 現在ホールド中の円index（Noneなら非ホールド）
        self.hold_start = 0.0       # ホールド開始時刻（HOLD_MAX_SEC上限用）
        # --- 実験的トラッキングエンジン（engine="track"）用 ---
        self.engine = engine        # "roi"(既定・現行) / "track"(スポーン検出+追跡)
        self._ne = None             # note_engine モジュール（遅延import）
        self.tracker = None         # note_engine.Tracker
        self.acted = set()          # 既に打鍵したノーツtrack id
        self.last_input_ts = 0.0    # 最後に genuine 入力を出した時刻（キープアライブ用）
        self.esc_since = None       # ESC を押し始めた時刻（長押し停止の判定用）
        self.last_activate = 0.0
        self.t_start = time.time()
        self.menu_since = None      # 同じメニューに留まり始めた時刻
        self.result_since = None    # result/eventresult を送り始めた時刻（無限ループ検知用）
        self._last_dark_check = 0.0  # 暗い画面で pause/songselect を最後に照合した時刻（間引き用）
        self.dbg_dir = "/tmp/i7dbg"
        os.makedirs(self.dbg_dir, exist_ok=True)
        # (top,bottom) px。タイトルバー有り(38,h-9)を初期値とし、暗いゲーム画面で自己補正。
        self.content = (38, int(self.win["h"]) - 9)

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

    def click_center_off(self, off):
        cx, cy = self.game_center_px()
        self._click_screen(cx + off[0], cy + off[1])

    def click_anchor(self, pos_px, off):
        """テンプレのマッチ位置(フレームpx) + 固定pxオフセットでクリック（画像追従・端末非依存）。"""
        self._click_screen(*self.pixel_to_screen(pos_px[0] + off[0], pos_px[1] + off[1]))

    # --- タイミング検出（timing モード） ---
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
        r = self.win["w"] * self.note_roi
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
                if wf[i] < NOTE_BASELINE_FRAC:  # 静穏時のみベースライン取り込み
                    self.note_baseline[i] = base + (wf[i] - base) * NOTE_BASELINE_EMA

        # 2) ホールド継続中: その円が明るい限り押下保持（drag=genuine入力でPAUSE防止）。
        #    明るさが引いた or 上限超で離す（誤検出でも HOLD_MAX_SEC で必ず離れる）。
        if self.holds and self.hold_idx is not None:
            i = self.hold_idx
            base = self.note_baseline[i] or 0.0
            still = (wf[i] - base) > self.note_trigger * HOLD_REL_FACTOR
            if still and (now - self.hold_start) < HOLD_MAX_SEC:
                self._press(*self.content_to_screen(*CIRCLES[i]), "move")
                self.last_input_ts = now
                time.sleep(0.005)
                return
            self._press(*self.content_to_screen(*CIRCLES[i]), "up")
            if self.verbose:
                self.log(f"長押し解除 円{i}（{now - self.hold_start:.2f}s）")
            self.note_last_tap[i] = now
            self.last_input_ts = now
            self.hold_idx = None
            self.note_hi_frames[i] = 0
            time.sleep(0.02)
            return

        # 3) 通常検出: 発火円をタップ。明るさが長く持続していれば長押しへ昇格（押下保持）。
        tapped = False
        for i in range(len(CIRCLES)):
            if now - self.note_last_tap[i] < NOTE_DEBOUNCE_SEC:
                continue
            if not fired[i]:
                continue
            if self.holds and self.note_hi_frames[i] >= HOLD_SUSTAIN_FRAMES:
                self._press(*self.content_to_screen(*CIRCLES[i]), "down")  # 離さず保持開始
                self.hold_idx = i
                self.hold_start = now
                self.last_input_ts = now
                if self.verbose:
                    self.log(f"長押し開始 円{i}")
                tapped = True
                break
            self.click_content(*CIRCLES[i])  # 通常タップ（down+up）
            self.note_last_tap[i] = now
            self.last_input_ts = now
            tapped = True
        if not tapped:
            self._keepalive(now)
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
            cx, cy = CIRCLES[self.circle_i % len(CIRCLES)]
            self.circle_i += 1
            self.click_content(cx, cy)
            self.last_input_ts = now

    def _keep_front(self, interval=0.4):
        now = time.time()
        if now - self.last_activate > interval:
            if not self.dry_run:
                driver.activate_fast()
            self.last_activate = now

    def log(self, msg):
        el = time.time() - self.t_start
        print(f"[{el:6.1f}s][clear {self.loops_done}/{self.max_loops}] {msg}",
              flush=True)

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
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        bright = float(frame_rgb.mean())
        res = {"_bright": (bright, 0, None)}

        def m(key):
            imgs, thr = self.templates[key]
            score, pos = match_best(frame, imgs)
            res[key] = (score, thr, pos)
            return score >= thr

        if bright < DARK_THRESH:
            # 暗い＝gameplay or PAUSE(暗背景)。**打鍵タイミング精度のため、重い pause/songselect
            # 照合は毎フレームせず DARK_RECHECK_SEC おきに間引く**（PAUSE・暗いsongselectは
            # タイミング非依存で数フレーム遅れて検出可）。間引くぶん _gameplay_timing のノーツ
            # 検出サンプリングが速くなり精度が上がる。
            # ※一部の楽曲選択画面はジャケット/KEEP OUTテープで暗くなり閾値(65)を下回る(mean≈61)
            #   ため、暗め域(>50)では songselect(NEXT, 高specific 0.85)を確認して救済する。
            now_t = time.time()
            if now_t - self._last_dark_check >= DARK_RECHECK_SEC:
                self._last_dark_check = now_t
                if m("pause"):
                    return "pause", res
                if bright > 50.0 and m("songselect"):
                    return "songselect", res
            return "gameplay", res
        # --- 明るい画面（タイミング非依存。毎フレーム照合でよい）---
        if m("pause"):
            return "pause", res
        # --- 明るいメニュー画面（順序が重要） ---
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
        # 編成画面（START ボタンが明確に見える）は popup ではない。イベントテーマの帯を
        # detect_card_x が誤ってカードヘッダ扱いし cardx 誤検出→停止していたため、色ヒュー
        # リスティックより先に START テンプレで確定する（modal popup なら START は隠れて落ちる）。
        if m("formation"):
            return "formation", res
        # 汎用カードポップアップ（報酬獲得/アイテム獲得/獲得一覧 等）の×を色検出で閉じる
        # （端末非依存）。専用ダイアログ判定の後・result の前（Result の上に重なって出るため）。
        cardx = detect_card_x(frame_rgb)
        if cardx is not None:
            res["cardx"] = (1.0, 0, cardx)
            return "cardx", res
        if m("closex"):
            return "closex", res
        # EVENT RESULT 見出し（申請する押下後の送り待ち画面）。per-song result より先に判定。
        if m("eventresult"):
            return "eventresult", res
        if m("result"):
            return "result", res
        # 連戦（連続ライブ再プレイ）が終わると楽曲選択画面に戻る。そこから自動で再開する。
        if m("songselect"):
            return "songselect", res
        if m("friendselect"):
            return "friendselect", res
        if m("formation"):
            return "formation", res
        return "menu", res

    def run(self):
        self.log(f"自動周回を開始（前面化, tap-mode={self.tap_mode}）。停止: ESCキー")
        caf = None
        if not self.dry_run:
            driver.activate()
            # システムのアイドル/スリープ/ディスプレイ消灯を抑止（PAUSE対策の補助）。
            try:
                caf = subprocess.Popen(["caffeinate", "-dimsu"])
            except Exception as e:  # caffeinate が無くても続行
                self.log(f"[warn] caffeinate 起動失敗: {e}")
        try:
            self._loop()
        finally:
            if caf is not None:
                caf.terminate()
        self.log(f"完了: {self.loops_done} 回クリア / "
                 f"{time.time() - self.t_start:.0f}s")

    def _loop(self):
        while self.loops_done < self.max_loops:
            # ESC キルスイッチ（長押し）。グローバル検出ゆえ他アプリ向けの ESC タップを拾う
            # ため、ESC を ESC_HOLD_SEC 秒**押し続けた**ときだけ停止する（短タップは無視）。
            if esc_pressed():
                if self.esc_since is None:
                    self.esc_since = time.time()
                elif time.time() - self.esc_since >= ESC_HOLD_SEC:
                    self.log(f"ESC 長押し({ESC_HOLD_SEC}s)検出 → 停止")
                    break
            else:
                self.esc_since = None
            if self.max_seconds and time.time() - self.t_start > self.max_seconds:
                self.log("時間上限に到達 → 終了")
                break
            self._keep_front()
            frame = driver.grab(self.win)
            rect = detect_content_rect(frame)
            # 暗いゲーム画面でのみ正しく取れる。取れたらキャッシュし、明るい画面でも一貫使用。
            if rect[1] - rect[0] < frame.shape[0] - 4:
                self.content = rect
            state, res = self.detect(frame)
            if self.verbose:
                top3 = sorted(((v[0], k) for k, v in res.items()), reverse=True)[:3]
                self.log(f"state={state} top={['%s:%.2f' % (k, s) for s, k in top3]} "
                         f"content={self.content}")

            if state == "pause":
                # 注意: pause_resume.png は「PAUSE」見出し文字に一致する。マッチ位置を
                # クリックすると見出しを叩くだけで再開しない（旧バグ）。PAUSEメニューの
                # 「再開」ボタンは右下の固定位置 P_RESUME にあるためそこをクリックする。
                self.log("PAUSE → 再開")
                self.click_anchor(res["pause"][2], ANCH_RESUME)
                time.sleep(0.4)
            elif state == "lifeshort":
                # LIFE不足ダイアログ。**きなこパンで回復し、ステラは絶対に使わない**。
                # きなこパン1個(+20) → 確認ポップアップ → ×で閉じる、を1手順で行う。
                self.life_recovers += 1
                if self.life_recovers > MAX_LIFE_RECOVERS:
                    fn = os.path.join(self.dbg_dir,
                                      f"life_depleted_{int(time.time()-self.t_start)}.png")
                    from PIL import Image as _I
                    _I.fromarray(frame).save(fn)
                    self.log(f"[warn] LIFE不足が継続（きなこパン枯渇の可能性）→ {fn} 保存。"
                             f"ステラは使わず停止します。")
                    break
                self.log(f"LIFE不足 → きなこパンで回復（{self.life_recovers}回目, ステラ不使用）")
                self.click_anchor(res["lifeshort"][2], ANCH_KINAKO)  # きなこパン「回復」（上段。ステラ不使用）
                time.sleep(1.3)
                self.click_center_off(OFF_LIFE_CONFIRM)  # 「N回復しました」確認の×（直後に出るためテンプレ無し→中央アンカー）
                time.sleep(1.3)
            elif state == "gameplay":
                self.life_recovers = 0  # ライブに入れた＝LIFEは足りた
                now = time.time()
                if self.gameplay_since is None:
                    self.gameplay_since = now
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
                    break
                if self.engine == "track":
                    # 実験: スポーン検出→追跡→レーン/ETAで打鍵（note_engine）。
                    self._gameplay_track(frame, now)
                elif self.tap_mode == "rotate":
                    # フォールバック: 5円を約50Hzで巡回連打。
                    cx, cy = CIRCLES[self.circle_i % len(CIRCLES)]
                    self.circle_i += 1
                    self.click_content(cx, cy)
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
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）")
                self.log("フレンド申請 → 申請する")
                self.click_match(res["friendreq"][2])
                time.sleep(0.8)
            elif state == "replay":
                # 連続ライブ再プレイ確認 → 「はい」で同じ曲を再開（次のループへ）。
                if self.was_in_live:
                    self.loops_done += 1
                    self.was_in_live = False
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）")
                self.log("連続ライブ 再プレイ → はい")
                self.click_anchor(res["replay"][2], ANCH_REPLAY_YES)  # マッチ位置+オフセット（画像追従）
                time.sleep(1.2)
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
                    break
                self.log("カードポップアップ → 背景タップで閉じる")
                self.click_window(*P_CARD_DISMISS)
                time.sleep(0.5)
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
                    break
                self.log("RANK UP → ×")
                self.click_anchor(res["rankup"][2], ANCH_RANKUP_X)
                time.sleep(0.6)
            elif state == "songselect":
                # 連戦が終わって楽曲選択へ戻った → **必ず EASY を選択** してから NEXT。
                # （ユーザー要件: ノーマル等で周回しない。EASY タブを先にタップして固定する。）
                # **ユーザー要件: 楽曲は変更しない**。曲リスト（左側）は絶対にタップせず、現在
                # 選択中の曲のまま進める。ここで触るのは EASY タブ（右下・難易度）と NEXT のみ。
                # NEXTテンプレのマッチ位置を直接クリック（端末非依存）。次状態で再検出して進める。
                self.log("楽曲選択に戻った → EASY 選択 → NEXT（曲は変更しない）")
                self.click_window(*P_EASY_TAB)   # EASY タブを選択（難易度のみ。曲は変えない）
                time.sleep(0.6)
                self.click_match(res["songselect"][2])
                time.sleep(1.6)
            elif state == "friendselect":
                # フレンド（サポート）選択 → アピールスキル ラベル（=フレンド行内）の位置を
                # 直接タップして選択（行全体が選択ボタン。実機で選択→編成へ遷移を確認）。
                self.log("フレンド選択 → フレンド選択")
                self.click_match(res["friendselect"][2])
                time.sleep(1.8)
            elif state == "formation":
                # 編成画面 → START（STARTテンプレのマッチ位置を直接クリック・端末非依存）。
                self.log("編成画面 → START")
                self.click_match(res["formation"][2])
                time.sleep(2.5)
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
            elif state in ("result", "eventresult"):
                # per-song Result / EVENT RESULT。クリア計上し、中央タップで送る。
                now = time.time()
                if self.was_in_live:
                    self.loops_done += 1
                    self.was_in_live = False
                    self.log(f"★ライブ クリア（通算 {self.loops_done}）")
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
                    break
                self.click_center_off(OFF_RESULT_ADV)  # 画面中央タップで送る
                time.sleep(0.5)
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
                    break
                time.sleep(0.3)
            # 進捗のある状態に遷移したら停滞タイマーをリセット。menu/rankup/closex は
            # 同画面ループの可能性があるのでタイマーを維持し watchdog 対象とする。
            if state not in ("menu", "rankup", "closex", "cardx"):
                self.menu_since = None
            # result/eventresult を抜けたら（=進捗）Result停滞タイマーをリセット。
            if state not in ("result", "eventresult"):
                self.result_since = None
            # gameplay タイマーは gameplay/pause（=ライブ中）以外でリセット。
            # 併せて timing 検出のベースラインも次ライブ用にリセットする。
            if state not in ("gameplay", "pause"):
                self.gameplay_since = None
                if any(b is not None for b in self.note_baseline):
                    self.note_baseline = [None] * len(CIRCLES)


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
        rect = detect_content_rect(frame)
        if rect[1] - rect[0] < frame.shape[0] - 4:
            al.content = rect
        if float(frame.mean()) < DARK_THRESH:  # gameplay フレームのみ
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
    ap.add_argument("--engine", choices=["roi", "track"], default="roi",
                    help="ライブ中の打鍵エンジン。roi=現行(到達点の明るさ・安定)、"
                         "track=実験(スポーン検出+追跡)。既定 roi")
    args = ap.parse_args()
    if args.calibrate:
        calibrate()
        return
    AutoLive(args.loops, dry_run=args.dry_run, verbose=args.verbose,
             max_seconds=args.max_seconds, tap_mode=args.tap_mode,
             note_trigger=args.note_trigger, note_lead=args.note_lead,
             note_roi=args.note_roi, holds=args.holds, engine=args.engine).run()


if __name__ == "__main__":
    main()
