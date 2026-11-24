"""
CRC Shift Bookmarks: Shift+Numpad bookmark recall -- see README.md.

While a CRC display window is the active window, Shift+Numpad keys recall
bookmarks by typing  ESC  .##  ENTER. The keyboard hook only exists while CRC
is in the foreground, and the script exits as soon as CRC closes.

    pythonw crc_shift_bookmarks.pyw            run silently (no window)
    python  crc_shift_bookmarks.pyw --debug    run with a console log
"""

# =============================================================================
# CONFIG -- edit to taste
# =============================================================================

# Shift + Numpad key  ->  bookmark number to recall.
# Set a key to None to leave Shift + that key alone.
BOOKMARKS = {
    0: 51,  # Shift + Num0
    1: 11,  # Shift + Num1
    2: 12,  # Shift + Num2
    3: 13,  # Shift + Num3
    4: 14,  # Shift + Num4
    5: 15,  # Shift + Num5
    6: 16,  # Shift + Num6
    7: 17,  # Shift + Num7
    8: 18,  # Shift + Num8
    9: 19,  # Shift + Num9
}

# Bookmarks only fire in CRC display windows, titled "CRC : <n>" or
# "CRC : <n> : <window name> : <facility>". Side windows ("Messages",
# "Voice Switch", "CRC Profiles", ...) are always skipped.
#
# Also skip when keyboard focus is inside an embedded Browser display, so a
# bookmark key never types ".51" + ENTER into a web page.
SKIP_BROWSER_DISPLAYS = True

# Seconds to wait for CRC to start if this is run before CRC is open.
STARTUP_TIMEOUT = 300

# Seconds between typed keys. Leave at 0 unless CRC drops characters.
INTER_KEY_DELAY = 0.0

# =============================================================================
# End of config
# =============================================================================

import argparse
import ctypes
import logging
import logging.handlers
import os
import queue
import sys
import tempfile
import threading
import time
from ctypes import wintypes as W

TARGET_EXE_NAME = "crc.exe"
POLL_INTERVAL_MS = 5000  # how often to check whether CRC is still running
LOG_PATH = os.path.join(tempfile.gettempdir(), "crc_shift_bookmarks.log")

# ----------------------------------------------------------------------------
# Win32 constants
# ----------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_TIMER, WM_QUIT = 0x0113, 0x0012
LLKHF_EXTENDED, LLKHF_INJECTED = 0x01, 0x10

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LSHIFT, VK_RSHIFT = 0xA0, 0xA1
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_ESCAPE, VK_RETURN, VK_OEM_PERIOD, VK_NUMLOCK = 0x1B, 0x0D, 0xBE, 0x90

SCAN_RSHIFT = 0x36
SCAN_FAKE_BIT = 0x200  # set on the Shift events Windows synthesizes around Shift+Numpad

# Physical numpad keys (non-extended scan codes). The dedicated arrow/Home/etc.
# keys share these scan codes but carry the extended flag.
NUMPAD_SCANS = {
    0x52: 0, 0x4F: 1, 0x50: 2, 0x51: 3, 0x4B: 4,
    0x4C: 5, 0x4D: 6, 0x47: 7, 0x48: 8, 0x49: 9,
}

MAGIC_EXTRA_INFO = 0xC4C0B00C  # tags our own injected keystrokes

# ----------------------------------------------------------------------------
# Key-handling logic (pure; unit-testable without Windows hooks)
# ----------------------------------------------------------------------------


def normalize_bookmarks(bookmarks):
    """{numpad digit: bookmark} -> {digit: "NN"}, dropping None; validates."""
    out = {}
    for key, value in bookmarks.items():
        if not (isinstance(key, int) and 0 <= key <= 9):
            raise ValueError(f"BOOKMARKS key {key!r} must be a numpad digit 0-9")
        if value is None:
            continue
        text = str(value).strip().lstrip(".")
        if not text.isdigit():
            raise ValueError(f"BOOKMARKS[{key}] = {value!r} is not a bookmark number")
        out[key] = text
    return out


def is_display_window_title(title):
    """True for CRC display windows: "CRC : <n>" or "CRC : <n> : <name> : ..."."""
    parts = [p.strip() for p in title.split(":")]
    return len(parts) >= 2 and parts[0].upper() == "CRC" and parts[1].isdigit()


def is_browser_focus(focus_class, focus_exe, crc_exe):
    """True if keyboard focus is in an embedded web view (WebView2/Chromium)."""
    if not focus_class:
        return False
    return focus_class.startswith("Chrome_") or (bool(focus_exe) and focus_exe != crc_exe)


class KeyLogic:
    """Decides, per low-level key event, whether to pass, swallow, or fire."""

    def __init__(self, bookmarks):
        self.bookmarks = bookmarks
        self.lshift = False
        self.rshift = False
        self.consumed = set()

    def reset(self, lshift, rshift):
        self.lshift, self.rshift = lshift, rshift
        self.consumed.clear()

    @property
    def shift_down(self):
        return self.lshift or self.rshift

    def handle(self, vk, scan, flags, is_down, env):
        """Return (swallow, text_to_send_or_None).

        env provides lazily-evaluated checks: other_mods_down(), window_ok().
        """
        if flags & LLKHF_INJECTED:
            return False, None
        extended = bool(flags & LLKHF_EXTENDED)

        if vk in (VK_LSHIFT, VK_RSHIFT, VK_SHIFT):
            # Windows wraps Shift+Numpad (NumLock on) in fake Shift up/down
            # events, marked with 0x200 in the scan code (0x22A / 0x236); some
            # keyboards instead send an E0-prefixed (extended) left Shift.
            # Only real ones are tracked. Note a real *right* Shift can carry
            # the extended flag, so that flag alone doesn't mean fake.
            is_right = vk == VK_RSHIFT or (scan & 0xFF) == SCAN_RSHIFT
            fake = bool(scan & SCAN_FAKE_BIT) or (extended and not is_right)
            if not fake:
                if is_right:
                    self.rshift = is_down
                else:
                    self.lshift = is_down
            return False, None

        digit = None if extended else NUMPAD_SCANS.get(scan)
        if digit is None:
            return False, None

        if not is_down:
            if scan in self.consumed:
                self.consumed.discard(scan)
                return True, None
            return False, None

        if scan in self.consumed:  # auto-repeat of a key we already handled
            return True, None

        if not self.shift_down or env.other_mods_down():
            return False, None
        text = self.bookmarks.get(digit)
        if text is None or not env.window_ok():
            return False, None

        self.consumed.add(scan)
        return True, text


def build_key_sequence(text, release_l, release_r, restore_l, restore_r):
    """List of (vk, is_up) for: [Shift up] ESC .text ENTER [Shift down]."""
    seq = []
    if release_l:
        seq.append((VK_LSHIFT, True))
    if release_r:
        seq.append((VK_RSHIFT, True))
    for vk in [VK_ESCAPE, VK_OEM_PERIOD] + [ord(c) for c in text] + [VK_RETURN]:
        seq += [(vk, False), (vk, True)]
    if restore_l:
        seq.append((VK_LSHIFT, False))
    if restore_r:
        seq.append((VK_RSHIFT, False))
    return seq


# ----------------------------------------------------------------------------
# Win32 bindings
# ----------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ULONG_PTR), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD),
                ("szExeFile", W.WCHAR * 260)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND),
                ("hwndFocus", W.HWND), ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, W.WPARAM, W.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG,
                                  W.DWORD, W.DWORD)
HANDLER_ROUTINE = ctypes.WINFUNCTYPE(W.BOOL, W.DWORD)


def _sig(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, list(argtypes)


_sig(user32.SetWindowsHookExW, W.HHOOK, ctypes.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
_sig(user32.UnhookWindowsHookEx, W.BOOL, W.HHOOK)
_sig(user32.CallNextHookEx, LRESULT, W.HHOOK, ctypes.c_int, W.WPARAM, W.LPARAM)
_sig(user32.SetWinEventHook, W.HANDLE, W.DWORD, W.DWORD, W.HMODULE, WINEVENTPROC,
     W.DWORD, W.DWORD, W.DWORD)
_sig(user32.UnhookWinEvent, W.BOOL, W.HANDLE)
_sig(user32.GetForegroundWindow, W.HWND)
_sig(user32.GetWindowThreadProcessId, W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
_sig(user32.InternalGetWindowText, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_sig(user32.GetClassNameW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_sig(user32.GetGUIThreadInfo, W.BOOL, W.DWORD, ctypes.POINTER(GUITHREADINFO))
_sig(user32.GetAsyncKeyState, W.SHORT, ctypes.c_int)
_sig(user32.GetKeyState, W.SHORT, ctypes.c_int)
_sig(user32.SendInput, W.UINT, W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_sig(user32.MapVirtualKeyW, W.UINT, W.UINT, W.UINT)
_sig(user32.GetMessageW, W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
_sig(user32.SetTimer, ULONG_PTR, W.HWND, ULONG_PTR, W.UINT, ctypes.c_void_p)
_sig(user32.PostThreadMessageW, W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
_sig(kernel32.GetCurrentThreadId, W.DWORD)
_sig(kernel32.GetModuleHandleW, W.HMODULE, W.LPCWSTR)
_sig(kernel32.OpenProcess, W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_sig(kernel32.QueryFullProcessImageNameW, W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
     ctypes.POINTER(W.DWORD))
_sig(kernel32.CloseHandle, W.BOOL, W.HANDLE)
_sig(kernel32.CreateMutexW, W.HANDLE, ctypes.c_void_p, W.BOOL, W.LPCWSTR)
_sig(kernel32.CreateToolhelp32Snapshot, W.HANDLE, W.DWORD, W.DWORD)
_sig(kernel32.Process32FirstW, W.BOOL, W.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_sig(kernel32.Process32NextW, W.BOOL, W.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_sig(kernel32.SetConsoleCtrlHandler, W.BOOL, HANDLER_ROUTINE, W.BOOL)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_ALREADY_EXISTS = 183


def key_is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def exe_name_of_pid(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = W.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def window_pid(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.InternalGetWindowText(hwnd, buf, len(buf))  # never blocks on a hung app
    return buf.value


def focused_window():
    """The window with keyboard focus on the foreground thread (may be a child)."""
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if user32.GetGUIThreadInfo(0, ctypes.byref(info)):
        return info.hwndFocus
    return None


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def process_running(exe_name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return True  # can't tell; assume running rather than quitting
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def send_keys(seq, inter_key_delay=0.0):
    def make(vk, is_up):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0),
                            dwFlags=KEYEVENTF_KEYUP if is_up else 0, time=0,
                            dwExtraInfo=MAGIC_EXTRA_INFO)
        return inp

    if inter_key_delay <= 0:
        arr = (INPUT * len(seq))(*[make(vk, up) for vk, up in seq])
        return user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT)) == len(seq)
    ok = True
    for vk, up in seq:
        one = (INPUT * 1)(make(vk, up))
        ok &= user32.SendInput(1, one, ctypes.sizeof(INPUT)) == 1
        time.sleep(inter_key_delay)
    return ok


# ----------------------------------------------------------------------------
# The helper
# ----------------------------------------------------------------------------

log = logging.getLogger("crc_numpad")


class _Env:
    """Lazy environment checks handed to KeyLogic from inside the hook."""

    def __init__(self, app):
        self.app = app

    def other_mods_down(self):
        return any(key_is_down(vk) for vk in (VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))

    def window_ok(self):
        return self.app.foreground_allows_bookmarks()


class App:
    def __init__(self, args, bookmarks):
        self.args = args
        self.target = args.target_exe.lower()
        self.rejected_titles = set()
        self.logic = KeyLogic(bookmarks)
        self.env = _Env(self)
        self.hook = None
        self.hook_logged = False
        self.fg_hwnd = None
        self.fg_is_target = False
        self.thread_id = kernel32.GetCurrentThreadId()
        self.hmod = kernel32.GetModuleHandleW(None)
        self.jobs = queue.Queue()
        self.started_at = time.monotonic()
        self.seen_target = False
        # Keep ctypes callbacks referenced for the lifetime of the hooks.
        self._hook_proc = HOOKPROC(self._on_key)
        self._winevent_proc = WINEVENTPROC(self._on_foreground)
        self._ctrl_handler = HANDLER_ROUTINE(self._on_console_ctrl)

    # -- foreground tracking -------------------------------------------------

    def _on_foreground(self, _hook, _event, hwnd, _id_obj, _id_child, _tid, _time):
        try:
            self.update_foreground(hwnd)
        except Exception:
            log.exception("foreground handler failed")

    def update_foreground(self, hwnd):
        if not hwnd:
            return
        changed = hwnd != self.fg_hwnd
        self.fg_hwnd = hwnd
        exe = exe_name_of_pid(window_pid(hwnd))
        self.fg_is_target = exe == self.target
        if changed and self.args.debug:
            log.debug("foreground: exe=%s class=%r title=%r",
                      exe or "?", window_class(hwnd), window_title(hwnd))
        if self.fg_is_target:
            if changed:
                # Re-arm on every switch into a CRC window: Windows silently
                # drops a low-level hook that once responded too slowly.
                self.remove_hook(quiet=True)
            self.install_hook()
        else:
            self.remove_hook()

    def foreground_allows_bookmarks(self):
        # Called from inside the hook, so only look; never touch the hook here.
        hwnd = user32.GetForegroundWindow()
        if hwnd != self.fg_hwnd:
            if exe_name_of_pid(window_pid(hwnd)) != self.target:
                return False
        elif not self.fg_is_target:
            return False
        title = window_title(hwnd)
        if not is_display_window_title(title):
            self._note_rejected(title, "not a CRC display window")
            return False
        if SKIP_BROWSER_DISPLAYS:
            focus = focused_window()
            cls = window_class(focus) if focus else ""
            exe = exe_name_of_pid(window_pid(focus)) if focus else ""
            if self.args.debug:
                log.debug("focus: class=%r exe=%s", cls, exe or "?")
            if is_browser_focus(cls, exe, self.target):
                self._note_rejected(title + " [browser]", "a Browser display has focus")
                return False
        return True

    def _note_rejected(self, key, reason):
        if key not in self.rejected_titles:
            self.rejected_titles.add(key)
            log.info("ignoring Shift+Numpad in window %r (%s)", key, reason)

    # -- keyboard hook -------------------------------------------------------

    def install_hook(self):
        if self.hook:
            return
        self.logic.reset(key_is_down(VK_LSHIFT), key_is_down(VK_RSHIFT))
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, self.hmod, 0)
        if not self.hook:
            log.error("SetWindowsHookExW failed (error %d)", ctypes.get_last_error())
        elif not self.hook_logged:
            self.hook_logged = True
            log.info("CRC active: keyboard hook installed")

    def remove_hook(self, quiet=False):
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
            if not quiet:
                self.hook_logged = False
                log.info("CRC not active: keyboard hook removed")

    def _on_key(self, n_code, w_param, l_param):
        if n_code >= 0:
            try:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                swallow, text = self.logic.handle(kb.vkCode, kb.scanCode, kb.flags,
                                                  is_down, self.env)
                if self.args.debug and not (kb.flags & LLKHF_INJECTED) and (
                        kb.vkCode in (VK_LSHIFT, VK_RSHIFT, VK_SHIFT)
                        or kb.scanCode in NUMPAD_SCANS):
                    log.debug("key vk=0x%02X scan=0x%02X flags=0x%02X %s -> %s%s",
                              kb.vkCode, kb.scanCode, kb.flags,
                              "down" if is_down else "up",
                              "SWALLOW" if swallow else "pass",
                              f" send .{text}" if text else "")
                if text:
                    self.jobs.put(text)
                if swallow:
                    return 1
            except Exception:
                log.exception("key handler failed")
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _sender(self):
        while True:
            text = self.jobs.get()
            if text is None:
                return
            try:
                # Always release both Shifts at the start of the (atomic) batch:
                # Windows re-presses a fake Shift right after the numpad key, so
                # checking the current Shift state first is a race.
                seq = build_key_sequence(
                    text, release_l=True, release_r=True,
                    restore_l=self.logic.lshift, restore_r=self.logic.rshift)
                if send_keys(seq, INTER_KEY_DELAY):
                    log.info("sent ESC .%s ENTER", text)
                else:
                    log.error("SendInput was blocked (error %d); is CRC running as admin?",
                              ctypes.get_last_error())
            except Exception:
                log.exception("send failed")

    # -- lifecycle -----------------------------------------------------------

    def _on_console_ctrl(self, _ctrl_type):
        user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        return True

    def _on_timer(self):
        if process_running(self.target):
            if not self.seen_target:
                log.info("%s is running", self.target)
            self.seen_target = True
        elif self.seen_target:
            log.info("%s has exited; shutting down", self.target)
            return False
        elif time.monotonic() - self.started_at >= self.args.startup_timeout:
            log.info("%s never started; shutting down", self.target)
            return False
        # Safety net in case a foreground event was missed.
        self.update_foreground(user32.GetForegroundWindow())
        return True

    def run(self):
        kernel32.SetConsoleCtrlHandler(self._ctrl_handler, True)
        threading.Thread(target=self._sender, daemon=True).start()
        win_hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._winevent_proc,
            0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        if not win_hook:
            log.error("SetWinEventHook failed (error %d)", ctypes.get_last_error())
            return 1
        if not process_running(self.target):
            log.info("waiting up to %ds for %s to start", self.args.startup_timeout,
                     self.target)
        user32.SetTimer(None, 0, POLL_INTERVAL_MS, None)

        msg = W.MSG()
        try:
            if self._on_timer():
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_TIMER and not self._on_timer():
                        break
        finally:
            self.remove_hook()
            user32.UnhookWinEvent(win_hook)
            self.jobs.put(None)
            log.info("stopped")
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Shift+Numpad bookmark recall for CRC")
    p.add_argument("--debug", action="store_true",
                   help="log window titles and Shift/Numpad key events")
    p.add_argument("--startup-timeout", type=float, default=STARTUP_TIMEOUT,
                   help="seconds to wait for CRC to start (default %(default)s)")
    p.add_argument("--target-exe", default=TARGET_EXE_NAME, help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    mutex = kernel32.CreateMutexW(None, False, "Local\\crc_shift_bookmarks")
    already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    # Only the instance that owns the mutex rewrites the log file.
    handlers = [] if already_running else [
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")]
    if sys.stderr is not None:  # None under pythonw
        handlers.append(logging.StreamHandler())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
    # Log through a queue so the keyboard hook never waits on disk/console I/O
    # (Windows drops a low-level hook that takes too long to respond).
    log_queue = queue.Queue()
    listener = logging.handlers.QueueListener(log_queue, *handlers)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        handlers=[queue_handler])
    listener.start()

    try:
        if already_running:
            log.info("helper already running; exiting")
            return 0
        try:
            bookmarks = normalize_bookmarks(BOOKMARKS)
        except ValueError as e:
            log.error("config error: %s", e)
            return 2
        log.info("bookmarks: %s", ", ".join(
            f"Shift+Num{k}=.{v}" for k, v in sorted(bookmarks.items())))
        return App(args, bookmarks).run()
    finally:
        listener.stop()
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
