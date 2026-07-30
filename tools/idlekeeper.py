"""IOHIDPostEvent で実HID活動を注入し HIDIdleTime を低く保つ（iPhoneミラーリングのPAUSE防止）。
CGEvent は HIDIdleTime を1回しかリセットできないが、IOHIDPostEvent は毎回リセットできる（§17.8）。
NX_NULLEVENT を使い、可能ならカーソルを動かさずに idle のみリセットする。"""
import ctypes, ctypes.util, sys, time, subprocess, re

_iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library('IOKit'))
_libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('System'))

class IOGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int16), ("y", ctypes.c_int16)]

def _open_hidsystem():
    try:
        task = _libc.mach_task_self()
    except Exception:
        task = ctypes.c_uint.in_dll(_libc, 'mach_task_self_').value
    _iokit.IOServiceMatching.restype = ctypes.c_void_p
    _iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
    _iokit.IOServiceGetMatchingService.restype = ctypes.c_uint
    _iokit.IOServiceGetMatchingService.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    svc = _iokit.IOServiceGetMatchingService(0, _iokit.IOServiceMatching(b"IOHIDSystem"))
    conn = ctypes.c_uint(0)
    _iokit.IOServiceOpen.restype = ctypes.c_int
    _iokit.IOServiceOpen.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.POINTER(ctypes.c_uint)]
    rc = _iokit.IOServiceOpen(svc, task, 1, ctypes.byref(conn))  # kIOHIDParamConnectType=1
    if rc != 0:
        raise OSError(f"IOServiceOpen(IOHIDSystem) failed rc={rc}")
    _iokit.IOHIDPostEvent.restype = ctypes.c_int
    _iokit.IOHIDPostEvent.argtypes = [ctypes.c_uint, ctypes.c_uint, IOGPoint, ctypes.c_void_p,
                                      ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    return conn.value

_CONN = None
_DATA = (ctypes.c_uint8 * 128)()

def poke():
    """実HID活動を1回注入して HIDIdleTime をリセットする（カーソルは動かさない）。"""
    global _CONN
    if _CONN is None:
        _CONN = _open_hidsystem()
    # NX_NULLEVENT = 0。位置は現在地不明だが NULLEVENT はカーソル移動を伴わない。
    return _iokit.IOHIDPostEvent(_CONN, 0, IOGPoint(0, 0), ctypes.byref(_DATA), 3, 0, 0)

def move(x, y):
    """IOHIDPostEvent で NX_MOUSEMOVED(=5) を送り、実カーソルを (x,y) へ動かす（実HID移動）。
    ミラーリングウィンドウ内へ送るとポインタ移動として iOS に転送される（はず）。"""
    global _CONN
    if _CONN is None:
        _CONN = _open_hidsystem()
    return _iokit.IOHIDPostEvent(_CONN, 5, IOGPoint(int(x), int(y)), ctypes.byref(_DATA), 3, 0, 0)

# NX event types: NX_LMOUSEDOWN=1, NX_LMOUSEUP=2
# NXEventData.mouse 推定オフセット: click(4..7,int32), pressure(8), buttonNumber(9), subType(10)
def _mouse_data(click=1, pressure=255, button=0, subtype=3):
    d = (ctypes.c_uint8 * 128)()
    ctypes.cast(ctypes.byref(d, 4), ctypes.POINTER(ctypes.c_int32))[0] = click
    d[8] = pressure & 0xFF
    d[9] = button & 0xFF
    d[10] = subtype & 0xFF
    return d

def click(x, y, subtype=3):
    """IOHIDPostEvent で実HIDの左クリック（down/up）を (x,y) に送る。NXEventData に subType を載せる。
    実HID注入(実eventNumber)＋subtype=3 で本物タップに近づけ、ライブ中ポーズ回避を検証。"""
    global _CONN
    if _CONN is None:
        _CONN = _open_hidsystem()
    p = IOGPoint(int(x), int(y))
    move(x, y)
    r1 = _iokit.IOHIDPostEvent(_CONN, 1, p, ctypes.byref(_mouse_data(1, 255, 0, subtype)), 3, 0, 0)
    time.sleep(0.04)
    r2 = _iokit.IOHIDPostEvent(_CONN, 2, p, ctypes.byref(_mouse_data(1, 0, 0, subtype)), 3, 0, 0)
    return (r1, r2)

def _hid_idle():
    out = subprocess.run(['ioreg', '-c', 'IOHIDSystem'], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else None

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "null"   # "null" or "move"
    gap = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0   # 0=無限
    pts = None
    if mode == "move":
        sys.path.insert(0, 'tools')
        import driver
        w = driver.find_window()
        # ミラーリングウィンドウ内の安全な2点（ノーツ円から離れた上辺寄り）を往復
        cx = w["x"] + w["w"] * 0.5
        y = w["y"] + w["h"] * 0.12
        pts = [(cx - w["w"] * 0.12, y), (cx + w["w"] * 0.12, y)]
    t0 = time.time(); n = 0; last = t0; i = 0
    print(f"idlekeeper start mode={mode} gap={gap}s dur={dur or 'inf'}", flush=True)
    while dur == 0 or time.time() - t0 < dur:
        if mode == "move":
            move(*pts[i % 2]); i += 1
        else:
            poke()
        n += 1
        if time.time() - last >= 5:
            print(f"[{time.time()-t0:5.0f}s] n={n} HIDIdleTime={_hid_idle():.2f}", flush=True)
            last = time.time()
        time.sleep(gap)
