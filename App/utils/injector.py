"""
Injection de texte à la position du curseur.
Avec tracking fiable de la fenêtre active (Windows).

Windows bloque SetForegroundWindow si l'appelant n'est pas au premier plan.
On utilise AttachThreadInput pour contourner cette restriction.
"""

import logging
import platform
import time

logger = logging.getLogger("perkysue.injector")

SYSTEM = platform.system()


# ─── Focus tracking (Windows) ───────────────────────────────

def get_active_window():
    """Retourne le handle de la fenêtre active (Windows)."""
    if SYSTEM != "Windows":
        return None
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def restore_window(hwnd):
    """
    Restaure le focus sur une fenêtre (Windows).
    Utilise AttachThreadInput pour contourner la restriction
    de SetForegroundWindow sur Windows Vista+.
    """
    if SYSTEM != "Windows" or not hwnd:
        return False
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Vérifier que la fenêtre existe encore
        if not user32.IsWindow(hwnd):
            logger.warning("Target window no longer exists")
            return False

        # Si c'est déjà la fenêtre active, rien à faire
        current_fg = user32.GetForegroundWindow()
        if current_fg == hwnd:
            return True

        # Obtenir les thread IDs
        our_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(current_fg, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        # Attacher notre thread au thread de la fenêtre au premier plan
        # Ça nous donne le droit d'appeler SetForegroundWindow
        attached_fg = False
        attached_target = False

        if our_thread != fg_thread:
            attached_fg = user32.AttachThreadInput(our_thread, fg_thread, True)

        if our_thread != target_thread and fg_thread != target_thread:
            attached_target = user32.AttachThreadInput(our_thread, target_thread, True)

        try:
            # Restaurer si minimisée (SW_RESTORE = 9)
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)

            # Amener au premier plan
            user32.BringWindowToTop(hwnd)
            result = user32.SetForegroundWindow(hwnd)

            if not result:
                # Dernier recours : simuler un Alt press pour "activer" notre thread
                # puis réessayer SetForegroundWindow
                user32.keybd_event(0x12, 0, 0, 0)  # Alt press
                user32.keybd_event(0x12, 0, 2, 0)  # Alt release
                time.sleep(0.05)
                result = user32.SetForegroundWindow(hwnd)

            # Attendre que le switch soit effectif
            time.sleep(0.15)

            # Vérifier
            new_fg = user32.GetForegroundWindow()
            if new_fg == hwnd:
                logger.debug("Focus restored successfully")
                return True
            else:
                logger.warning(f"Focus partially restored (fg={new_fg}, target={hwnd})")
                return True  # On tente quand même l'injection

        finally:
            # Détacher les threads
            if attached_fg:
                user32.AttachThreadInput(our_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(our_thread, target_thread, False)

    except Exception as e:
        logger.warning(f"Could not restore window: {e}")
        return False


def get_window_title(hwnd) -> str:
    """Retourne le titre de la fenêtre (debug)."""
    if SYSTEM != "Windows" or not hwnd:
        return "unknown"
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value or "unknown"
    except Exception:
        return "unknown"


# ─── Selection grab ───────────────────────────────────────────

def grab_selection(timeout_ms: int = 500) -> str:
    """
    Grab currently selected text from the active window.

    Instead of simulating Ctrl+C keystrokes (which fails from daemon threads
    due to UIPI and input queue issues), sends WM_COPY directly to the
    focused control. This is the same message Windows sends internally
    when the user presses Ctrl+C.

    Falls back to SendMessage(WM_KEYDOWN) if WM_COPY doesn't work.

    Args:
        timeout_ms: Time to wait for clipboard update
    """
    if SYSTEM != "Windows":
        return ""

    import ctypes
    import ctypes.wintypes
    import pyperclip

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Constants
    WM_COPY = 0x0301
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    VK_CONTROL = 0x11
    VK_C = 0x43

    # Get foreground window
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        logger.debug("No foreground window")
        return ""

    # Attach to target thread to access its input state
    our_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    attached = False
    if our_tid != target_tid:
        attached = user32.AttachThreadInput(our_tid, target_tid, True)

    try:
        # Get the actual focused control WITHIN the foreground window
        # (e.g., the text field inside Chrome, not the Chrome window itself)
        focused = user32.GetFocus()
        target = focused if focused else hwnd

        logger.debug(f"Target hwnd={target} (focused={focused}, parent={hwnd})")

        # Save & clear clipboard
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = ""

        try:
            pyperclip.copy("")
        except Exception:
            pass

        # METHOD 1: WM_COPY — the cleanest approach
        # This tells the control to copy its selection to clipboard
        # No keyboard simulation needed at all
        user32.SendMessageW(target, WM_COPY, 0, 0)

        # Check if it worked
        time.sleep(0.15)
        try:
            selected = pyperclip.paste()
        except Exception:
            selected = ""

        # METHOD 2: If WM_COPY didn't work, try SendMessage with key events
        # Some controls (like web browsers) don't respond to WM_COPY
        # but do respond to WM_KEYDOWN/WM_KEYUP messages
        if not selected:
            logger.debug("WM_COPY didn't work, trying SendMessage WM_KEYDOWN")

            # Clear clipboard again
            try:
                pyperclip.copy("")
            except Exception:
                pass

            # lParam for WM_KEYDOWN: repeat=1, scancode, extended=0
            ctrl_scan = user32.MapVirtualKeyW(VK_CONTROL, 0)
            c_scan = user32.MapVirtualKeyW(VK_C, 0)

            ctrl_lparam_down = (1 | (ctrl_scan << 16))
            c_lparam_down = (1 | (c_scan << 16))
            ctrl_lparam_up = (1 | (ctrl_scan << 16) | (3 << 30))  # bits 30-31 set for keyup
            c_lparam_up = (1 | (c_scan << 16) | (3 << 30))

            user32.SendMessageW(target, WM_KEYDOWN, VK_CONTROL, ctrl_lparam_down)
            user32.SendMessageW(target, WM_KEYDOWN, VK_C, c_lparam_down)
            user32.SendMessageW(target, WM_KEYUP, VK_C, c_lparam_up)
            user32.SendMessageW(target, WM_KEYUP, VK_CONTROL, ctrl_lparam_up)

            # Poll clipboard
            time.sleep(0.1)
            start = time.time()
            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    selected = pyperclip.paste()
                    if selected:
                        break
                except Exception:
                    pass
                time.sleep(0.02)

        # METHOD 3: Last resort — keybd_event (global, not targeted)
        if not selected:
            logger.debug("SendMessage didn't work, trying keybd_event")

            try:
                pyperclip.copy("")
            except Exception:
                pass

            # Release any held modifiers first
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)  # Alt up
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)  # Ctrl up
            user32.keybd_event(0x10, 0, KEYEVENTF_KEYUP, 0)  # Shift up
            time.sleep(0.05)

            user32.keybd_event(VK_CONTROL, 0, 0, 0)  # Ctrl down
            user32.keybd_event(VK_C, 0, 0, 0)  # C down
            user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)  # C up
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)  # Ctrl up

            start = time.time()
            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    selected = pyperclip.paste()
                    if selected:
                        break
                except Exception:
                    pass
                time.sleep(0.02)

        # Restore clipboard
        try:
            pyperclip.copy(old_clipboard)
        except Exception:
            pass

        selected = selected.strip() if selected else ""
        if selected:
            logger.info(f"Selection grabbed: {len(selected)} chars")
        else:
            logger.debug("No text selected (all methods tried)")

        return selected

    finally:
        if attached:
            user32.AttachThreadInput(our_tid, target_tid, False)


# ─── Injection ───────────────────────────────────────────────

def inject_text(text: str, method: str = "clipboard",
                restore_clipboard: bool = True, delay_ms: int = 100,
                target_window=None) -> bool:
    """
    Injecte du texte à la position du curseur.

    Args:
        text: Texte à injecter
        method: "clipboard" ou "keystrokes"
        restore_clipboard: Restaurer le presse-papier original après
        delay_ms: Délai avant paste (ms)
        target_window: Handle de la fenêtre cible (optionnel)

    Returns:
        True si l'injection a réussi
    """
    if not text:
        logger.warning("Nothing to inject (empty text)")
        return False

    try:
        # Restaurer le focus sur la fenêtre cible
        if target_window:
            title = get_window_title(target_window)
            logger.info(f"Restoring focus: '{title}'")
            restore_window(target_window)

        if method == "clipboard":
            return _inject_via_clipboard(text, restore_clipboard, delay_ms)
        elif method == "keystrokes":
            return _inject_via_keystrokes(text, delay_ms)
        else:
            logger.error(f"Unknown method: {method}")
            return False
    except Exception as e:
        logger.error(f"Injection error: {e}")
        return False


def _inject_via_clipboard(text: str, restore: bool, delay_ms: int) -> bool:
    """Injection via copier-coller."""
    import pyperclip
    from pynput.keyboard import Controller, Key

    keyboard = Controller()

    # Sauvegarder le presse-papier
    old_clipboard = None
    if restore:
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = None

    # Copier le texte
    pyperclip.copy(text)
    time.sleep(delay_ms / 1000.0)

    # Ctrl+V (ou Cmd+V sur macOS)
    if SYSTEM == "Darwin":
        keyboard.press(Key.cmd)
        keyboard.press('v')
        keyboard.release('v')
        keyboard.release(Key.cmd)
    else:
        keyboard.press(Key.ctrl)
        keyboard.press('v')
        keyboard.release('v')
        keyboard.release(Key.ctrl)

    time.sleep(0.1)

    # Restaurer le presse-papier
    if restore and old_clipboard is not None:
        time.sleep(0.2)
        try:
            pyperclip.copy(old_clipboard)
        except Exception:
            pass

    logger.info(f"Text injected ({len(text)} chars) via clipboard")
    return True


def _inject_via_keystrokes(text: str, delay_ms: int) -> bool:
    """Injection via simulation de frappes clavier."""
    from pynput.keyboard import Controller

    keyboard = Controller()
    time.sleep(delay_ms / 1000.0)
    keyboard.type(text)

    logger.info(f"Text injected ({len(text)} chars) via keystrokes")
    return True