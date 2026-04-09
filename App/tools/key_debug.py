"""
PerkySue — Key Debug Tool
Affiche les touches détectées par pynput.
Appuie sur des touches pour voir ce qui est capté.
Ctrl+C pour quitter.
"""
import os, sys
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(APP_DIR, ".."))

from pynput import keyboard

pressed = set()

def on_press(key):
    pressed.add(key)
    print(f"  PRESS:   {repr(key):40s}  type={type(key).__name__}  |  Currently held: {len(pressed)} keys")
    
    # Check if we have a combo
    if len(pressed) >= 3:
        print(f"           COMBO: {pressed}")

def on_release(key):
    pressed.discard(key)
    if key == keyboard.Key.esc:
        print("\n  ESC pressed — quitting.")
        return False

print()
print("  =============================================")
print("  PerkySue — Key Debug Tool")
print("  =============================================")
print()
print("  Press any keys to see what pynput detects.")
print("  Try: Ctrl+Shift+T")
print("  Press ESC to quit.")
print()

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
