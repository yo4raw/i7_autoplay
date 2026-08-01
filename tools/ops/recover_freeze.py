"""「ライフを全回復しました。」フリーズ（アプリ完全ハング）からの自動復旧。

手順: アイナナを強制終了（⌘1→⌘2→カード上スワイプ）→ Spotlight(⌘3)から再起動 →
テンプレ照合ナビで楽曲選択まで進める。既知画面以外では絶対にクリックしない（安全第一）。

使い方: python -u tools/ops/recover_freeze.py   （成功で exit 0 / 失敗 exit 1）

**注意**: 既知テンプレに一致しないときの中央タップは 2026-08-02 に無効化した
（BLIND_CENTER_TAP=False）。実機で別アプリの画面まで盲目タップしてしまったため。
有効化するとゲーム外の画面を操作しうるので、原則そのままにすること。
前提: supervisor / autolive は停止済みであること（呼び出し側で pkill）。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import driver  # noqa: E402
from autolive import match_multiscale  # noqa: E402

import cv2  # noqa: E402

# 既知画面に一致しないときの中央タップ。**既定で無効**（上のドキュストリング参照）。
BLIND_CENTER_TAP = False
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREENS = os.path.join(ROOT, "assets", "screens")
TEMPLATES = os.path.join(ROOT, "assets", "templates")


def osa(script):
    subprocess.run(["osascript", "-e", script], capture_output=True)


def key_cmd(num):
    osa('tell application "iPhone Mirroring" to activate')
    time.sleep(0.5)
    osa(f'tell application "System Events" to keystroke "{num}" using command down')


def load(path):
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(path)
    return im


def grab_bgr():
    f = driver.grab(driver.find_window())
    return cv2.cvtColor(f, cv2.COLOR_RGB2BGR)


def click_frac(xf, yf):
    driver.click_frac(xf, yf)


def click_px(pos, frame):
    h, w = frame.shape[:2]
    click_frac(pos[0] / w, pos[1] / h)


def force_quit_game():
    print("[recover] force-quit game via app switcher", flush=True)
    key_cmd("1"); time.sleep(2.5)            # iOSホームへ
    key_cmd("2"); time.sleep(2.5)            # アプリスイッチャー
    driver.swipe_frac(0.42, 0.5, 0.42, 0.08) # 先頭カードを上へ＝強制終了
    time.sleep(2.0)
    key_cmd("1"); time.sleep(2.0)            # ホームに戻す


def relaunch_game():
    print("[recover] relaunch via Spotlight", flush=True)
    key_cmd("3"); time.sleep(2.0)
    click_frac(0.13, 0.22)                   # Siri提案の先頭（直近使用アプリ=アイナナ）
    time.sleep(9.0)


STEPS = [
    # (name, template_path, threshold, action)  上から順に照合し、最初に当たったものを実行
    # 【重要】ゴールは**イベント楽曲選択**（通常の楽曲選択ではイベントptが入らない）。
    # イベント楽曲選択の確定条件 = 左下「Normal Live」ボタンが見える。
    ("event_songselect", os.path.join(SCREENS, "event_songselect", "normal_live_btn.png"), 0.85, "DONE"),
    # イベントトップ → 「イベント楽曲」
    ("event_songs", os.path.join(SCREENS, "event_top", "event_songs_btn.png"), 0.85, "CLICK"),
    # イベントトップの「本日の課題」ポップアップ → ×
    ("daily_close", os.path.join(SCREENS, "event_daily_tasks", "close_x.png"), 0.85, "CLICK"),
    # 通常の楽曲選択 → 左下イベントリボンでイベントトップへ
    ("event_ribbon", os.path.join(SCREENS, "songselect", "event_ribbon.png"), 0.80, "CLICK"),
    # 「前回のライブ結果を表示しますか？」（強制終了の後遺症）→ **いいえ**
    # （はい側は連続ライブ再プレイ確認の「はい」とボタンが同形で誤爆し、通常ライブを
    #   開始してしまうため、復旧中のこの種のダイアログは常に「いいえ」で抜ける）
    ("prevres_no", os.path.join(SCREENS, "prev_result_dialog", "id_text.png"), 0.85, "CLICKOFF", (-61, 76)),
    # 連続ライブ再プレイ確認 → いいえ（復旧中に勝手にライブを始めない）
    ("replay_no", os.path.join(TEMPLATES, "replay_title.png"), 0.82, "CLICKOFF", (-39, 125)),
    ("dl_download", os.path.join(SCREENS, "dldialog", "download_btn.png"), 0.85, "CLICK"),
    ("news_close", os.path.join(SCREENS, "news", "close_x.png"), 0.85, "CLICK"),
    ("home_live", os.path.join(SCREENS, "home", "nav_live.png"), 0.85, "CLICK"),
    ("title_tap", os.path.join(TEMPLATES, "tap_screen.png"), 0.80, "CENTER"),
]


def main():
    force_quit_game()
    relaunch_game()
    steps = [(s + ((None,),))[:5] if len(s) == 4 else s for s in STEPS]
    steps = [(n, p, t, a, (o if isinstance(o, tuple) and len(o) == 2 else None))
             for n, p, t, a, o in steps]
    tmpl = {n: load(p) for n, p, _, _, _ in steps if p}
    bright_streak = 0
    t0 = time.time()
    while time.time() - t0 < 300:
        # TAP SCREEN の点滅対策: 2フレームを 0.7s 空けて照合し最大スコアを採用
        frames = [grab_bgr()]
        time.sleep(0.7)
        frames.append(grab_bgr())
        acted = False
        for name, path, thr, action, off in steps:
            if path is None:
                continue
            best = (0.0, None)
            for f in frames:
                s, p = match_multiscale(f, tmpl[name])
                if s > best[0]:
                    best = (s, p)
            score, pos = best
            if score >= thr and pos is not None:
                print(f"[recover] {name} score={score:.2f}", flush=True)
                if action == "DONE":
                    print("[recover] event songselect reached — SUCCESS", flush=True)
                    return 0
                if action == "CLICK":
                    click_px(pos, frames[-1])
                elif action == "CLICKOFF":
                    click_px((pos[0] + off[0], pos[1] + off[1]), frames[-1])
                elif action == "CENTER":
                    click_frac(0.5, 0.55)
                acted = True
                break
        if not acted:
            # 【2026-08-02 無効化】既知テンプレ不一致で中央タップするフォールバックは
            # **危険**。実機でアプリ強制終了に失敗した状態から発火し、盲目タップを
            # 繰り返した結果**ゲームではない別アプリの画面まで操作してしまった**。
            # 「既知画面以外では絶対にクリックしない」という本ツールの前提と矛盾する。
            # 一致しないまま時間切れになったら、黙って諦めて人間に任せる。
            bright_streak += 1
            if BLIND_CENTER_TAP and bright_streak >= 2 and time.time() - t0 > 15:
                bright = float(frames[-1].mean())
                print(f"[recover] no match (bright={bright:.0f}) -> center tap", flush=True)
                click_frac(0.5, 0.55)
                bright_streak = 0
        else:
            bright_streak = 0
        time.sleep(3.0)
    print("[recover] TIMEOUT — manual intervention needed", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
