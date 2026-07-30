"""本物のクリック(トラックパッド)のイベント属性をキャプチャして合成との差分を見る（§17.8）。
CGEventTap(listenOnly)で LeftMouseDown/Up を傍受し、subtype/pressure/source等を出力する。
使い方: 実行後、iPhoneミラーリングのウィンドウ内を数回タップ。Ctrl-C か N件で終了。"""
import sys, time
import Quartz

FIELDS = {
    "subtype": Quartz.kCGMouseEventSubtype,
    "pressure_i": Quartz.kCGMouseEventPressure,
    "buttonNumber": Quartz.kCGMouseEventButtonNumber,
    "clickState": Quartz.kCGMouseEventClickState,
    "eventNumber": Quartz.kCGMouseEventNumber,
    "src_pid": Quartz.kCGEventSourceUnixProcessID,
    "src_stateid": Quartz.kCGEventSourceStateID,
    "src_uid": Quartz.kCGEventSourceUserData,
}
count = [0]
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 6

def cb(proxy, etype, event, refcon):
    name = {Quartz.kCGEventLeftMouseDown: "DOWN", Quartz.kCGEventLeftMouseUp: "UP"}.get(etype, str(etype))
    loc = Quartz.CGEventGetLocation(event)
    parts = [f"{name} ({loc.x:.0f},{loc.y:.0f})"]
    for k, f in FIELDS.items():
        try:
            parts.append(f"{k}={Quartz.CGEventGetIntegerValueField(event, f)}")
        except Exception as e:
            parts.append(f"{k}=ERR")
    try:
        parts.append(f"pressure_f={Quartz.CGEventGetDoubleValueField(event, Quartz.kCGMouseEventPressure):.3f}")
    except Exception:
        pass
    print("  ".join(parts), flush=True)
    if name == "UP":
        count[0] += 1
        if count[0] >= LIMIT:
            Quartz.CFRunLoopStop(Quartz.CFRunLoopGetCurrent())
    return event

mask = (1 << Quartz.kCGEventLeftMouseDown) | (1 << Quartz.kCGEventLeftMouseUp)
tap = Quartz.CGEventTapCreate(Quartz.kCGHIDEventTap, Quartz.kCGHeadInsertEventTap,
                              Quartz.kCGEventTapOptionListenOnly, mask, cb, None)
if not tap:
    print("FAILED to create event tap (need accessibility?)"); sys.exit(1)
src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
Quartz.CGEventTapEnable(tap, True)
print(f"LISTENING for {LIMIT} clicks — tap in the iPhone Mirroring window now...", flush=True)
Quartz.CFRunLoopRun()
print("done", flush=True)
