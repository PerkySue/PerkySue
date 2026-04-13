"""
Global hotkey manager for PerkySue.

Windows — RegisterHotKey (Win32)
    Captures and consumes keystrokes (no system “ding”). Each registration uses
    MOD_NOREPEAT. For combos with Alt (without Ctrl), we normally register a
    second hotkey Ctrl+Alt+same_key so that AltGr+key (seen as Ctrl+Alt) works
    on AZERTY/QWERTZ — unless skip_altgr=True (e.g. explicit *_altgr in YAML).

    DO NOT use low-level hooks (WH_KEYBOARD_LL) here for “reserved” combos:
    they can break keyboard input system-wide if mishandled.

    Combos to avoid in config (often fail or fight the shell):
    - alt+escape     — Windows uses Alt+Escape for window cycling; RegisterHotKey unreliable.
    - alt+shift+escape — may clash with system shortcuts on some setups.
    Prefer alt+letter for stop_recording (default alt+q in defaults.yaml).

Other OS: pynput GlobalHotKeys (see _to_pynput_format; navigation keys use <home>, <end>).
"""

import logging
import platform
import threading
from typing import Callable, Optional

logger = logging.getLogger("perkysue.hotkeys")

SYSTEM = platform.system()


# ─── Key name → VK code mapping (Windows) ───

_VK_MAP = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B,
    # Navigation / arrows
    "home": 0x24, "end": 0x23,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}

# Reverse map: physical keycode (VK) -> key name, for capture (keysym is layout-dependent, keycode is physical)
KEYCODE_TO_NAME = {v: k for k, v in _VK_MAP.items()}


def _parse_hotkey(hotkey_str: str):
    """
    Parse "ctrl+shift+t" into (modifiers_bitmask, vk_code).
    Returns (None, None) if parsing fails.
    """
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    parts = hotkey_str.lower().strip().split("+")
    modifiers = MOD_NOREPEAT  # Prevent repeated triggers when held
    vk_code = None

    for part in parts:
        part = part.strip()
        if part in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part in ("cmd", "win", "super"):
            modifiers |= MOD_WIN
        elif part in _VK_MAP:
            vk_code = _VK_MAP[part]
        else:
            logger.warning(f"Unknown key in hotkey: '{part}'")
            return None, None

    if vk_code is None:
        logger.warning(f"No key found in hotkey: '{hotkey_str}'")
        return None, None

    return modifiers, vk_code


class HotkeyManager:
    """
    Cross-platform global hotkey manager.

    On Windows, uses RegisterHotKey to both detect AND suppress key events
    (no "ding" sound). Works with left and right modifier keys.

    Usage:
        manager = HotkeyManager()
        manager.register("ctrl+shift+t", on_transcribe)
        manager.start()  # Blocking
    """

    def __init__(self):
        self._hotkeys: list[tuple[str, Callable]] = []
        self._running = False

    def register(self, hotkey_str: str, callback: Callable,
                 on_release: Optional[Callable] = None, skip_altgr: bool = False) -> None:
        """
        Register a global hotkey.

        skip_altgr=False: also register Ctrl+Alt+key (AltGr on European keyboards).
        skip_altgr=True: only the parsed combo; use when *_altgr is set in YAML.
        """
        self._hotkeys.append((hotkey_str, callback, skip_altgr))
        logger.debug(f"Hotkey registered: {hotkey_str}")

    def start(self) -> None:
        """Start listening for hotkeys (blocking)."""
        if not self._hotkeys:
            logger.warning("No hotkeys registered!")
            return

        self._running = True

        if SYSTEM == "Windows":
            self._start_windows()
        else:
            self._start_pynput()

    def start_background(self) -> threading.Thread:
        """Start listening in a background thread."""
        thread = threading.Thread(target=self.start, daemon=True)
        self._thread = thread
        thread.start()
        return thread

    def stop(self) -> None:
        """Stop listening. On Windows, posts WM_QUIT so the message loop exits."""
        self._running = False
        thread = getattr(self, "_thread", None)
        if thread and thread.is_alive() and SYSTEM == "Windows":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                WM_QUIT = 0x0012
                user32.PostThreadMessageW(ctypes.c_ulong(thread.ident), WM_QUIT, 0, 0)
            except Exception as e:
                logger.debug("Hotkey stop (post quit): %s", e)

    # ─── Windows implementation (RegisterHotKey) ───

    def _start_windows(self):
        """
        Use Win32 RegisterHotKey API.
        This CONSUMES the key events — no more Windows "ding" sound.
        Handles both left and right Ctrl/Shift/Alt automatically.
        """
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        WM_HOTKEY = 0x0312

        # Register each hotkey with a unique ID
        # For Alt+X hotkeys, also register Ctrl+Alt+X to capture AltGr
        # (on European keyboards, AltGr sends Ctrl+Alt, not just Alt)
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002

        id_to_callback = {}
        next_id = 1
        for idx, item in enumerate(self._hotkeys):
            hotkey_str, callback = item[0], item[1]
            skip_altgr = item[2] if len(item) > 2 else False
            hotkey_id = next_id
            next_id += 1
            modifiers, vk_code = _parse_hotkey(hotkey_str)

            if vk_code is None:
                logger.error(f"Could not parse hotkey: {hotkey_str}")
                continue

            success = user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code)
            if success:
                id_to_callback[hotkey_id] = callback
                logger.debug(f"  ✅ RegisterHotKey OK: {hotkey_str} (id={hotkey_id})")
            else:
                error = ctypes.GetLastError()
                logger.error(
                    f"  ❌ RegisterHotKey FAILED: {hotkey_str} "
                    f"(error={error}) — is another app using this hotkey?"
                )

            # AltGr fix: if hotkey uses Alt (without Ctrl), also register Ctrl+Alt (unless skip_altgr, e.g. explicit AltGr in config)
            if not skip_altgr and (modifiers & MOD_ALT) and not (modifiers & MOD_CONTROL):
                altgr_id = next_id
                next_id += 1
                altgr_modifiers = modifiers | MOD_CONTROL
                success = user32.RegisterHotKey(None, altgr_id, altgr_modifiers, vk_code)
                if success:
                    id_to_callback[altgr_id] = callback
                    logger.debug(f"  ✅ RegisterHotKey OK: {hotkey_str} +AltGr (id={altgr_id})")
                else:
                    logger.debug(f"  ℹ️  AltGr variant not registered for {hotkey_str} (may conflict)")

        if not id_to_callback:
            logger.error("No hotkeys could be registered!")
            return

        logger.debug("Hotkey listener started (Win32 RegisterHotKey)...")

        # Windows message loop
        msg = ctypes.wintypes.MSG()
        try:
            while self._running:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == -1 or result == 0:
                    break

                if msg.message == WM_HOTKEY:
                    hotkey_id = msg.wParam
                    cb = id_to_callback.get(hotkey_id)
                    if cb:
                        # Run in separate thread to not block message loop
                        threading.Thread(target=cb, daemon=True).start()
        finally:
            # Unregister all hotkeys
            for hotkey_id in id_to_callback:
                user32.UnregisterHotKey(None, hotkey_id)
            logger.info("Hotkeys unregistered.")

    # ─── Fallback implementation (pynput — macOS/Linux) ───

    def _start_pynput(self):
        """Fallback for macOS/Linux using pynput GlobalHotKeys."""
        from pynput import keyboard

        hotkey_map = {}
        for item in self._hotkeys:
            hotkey_str, callback = item[0], item[1]
            pynput_str = self._to_pynput_format(hotkey_str)

            def make_threaded(cb):
                def threaded():
                    threading.Thread(target=cb, daemon=True).start()
                return threaded

            hotkey_map[pynput_str] = make_threaded(callback)
            logger.info(f"  pynput hotkey: {hotkey_str} -> {pynput_str}")

        logger.info("Hotkey listener started (pynput)...")

        with keyboard.GlobalHotKeys(hotkey_map) as listener:
            self._listener = listener
            listener.join()

    @staticmethod
    def _to_pynput_format(hotkey_str: str) -> str:
        """Convert "ctrl+shift+t" to pynput format "<ctrl>+<shift>+t"."""
        parts = hotkey_str.lower().strip().split("+")
        result = []
        for part in parts:
            part = part.strip()
            if part in ("ctrl", "control"):
                result.append("<ctrl>")
            elif part == "shift":
                result.append("<shift>")
            elif part == "alt":
                result.append("<alt>")
            elif part in ("cmd", "win", "super"):
                result.append("<cmd>")
            elif part in ("end", "home"):
                result.append(f"<{part}>")
            else:
                result.append(part)
        return "+".join(result)


# Fallback when user config omits hotkeys.<mode_id> (keep in sync with App/configs/defaults.yaml)
DEFAULT_HOTKEY_BY_MODE = {
    "transcribe": "alt+t",
    "improve": "alt+i",
    "professional": "alt+p",
    "translate": "alt+l",
    "console": "alt+c",
    "email": "alt+m",
    "message": "alt+d",
    "social": "alt+x",
    "summarize": "alt+s",
    "genz": "alt+g",
    "answer": "alt+a",
    "help": "alt+h",
    "custom1": "alt+v",
    "custom2": "alt+b",
    "custom3": "alt+n",
    "stop_recording": "alt+q",
}


def resolve_hotkey_string(hotkeys_cfg: dict, mode_id: str) -> str:
    """Hotkey string from merged config, or factory default for known mode ids."""
    if not mode_id:
        return ""
    h = (hotkeys_cfg or {}).get(mode_id, "") or ""
    if str(h).strip():
        return str(h).strip()
    return DEFAULT_HOTKEY_BY_MODE.get(mode_id, "") or ""


def format_hotkey_display(hk: str) -> str:
    """alt+d → Alt+D ; alt+shift+a → Alt+Shift+A"""
    if not (hk or "").strip():
        return ""
    parts = []
    for p in hk.lower().strip().split("+"):
        p = p.strip()
        if not p:
            continue
        if len(p) == 1 and p.isalpha():
            parts.append(p.upper())
        elif p in ("alt", "ctrl", "shift", "win"):
            parts.append(p.capitalize())
        else:
            parts.append(p)
    return "+".join(parts)
