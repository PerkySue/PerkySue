#!/usr/bin/env python3
"""
PerkySue — Local portable voice assistant.
Main entry point.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# CRITICAL: Add App/ directory to Python path for embedded Python
# Embedded Python does NOT add the script's directory to sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _configure_windows_console_utf8() -> None:
    """Avoid mojibake / tofu for emoji and Unicode in classic cmd.exe (CP 437)."""
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def setup_logging(verbose: bool = False, log_file: Path = None):
    """Configure le logging (console + fichier)."""
    level = logging.DEBUG if verbose else logging.INFO

    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # Log file keeps debug (e.g. hotkey registration) for support
        handlers.append(fh)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


def check_dependencies(paths):
    """Check that all dependencies are installed."""
    print("\n🔍 Checking dependencies...\n")

    deps = [
        ("yaml", "pyyaml", True),
        ("numpy", "numpy", True),
        ("sounddevice", "sounddevice", True),
        ("pynput", "pynput", True),
        ("pyperclip", "pyperclip", True),
        ("faster_whisper", "faster-whisper", True),
        ("httpx", "httpx", True),
        ("openai", "openai", False),
        ("webrtcvad", "webrtcvad", True),
        ("llama_cpp", "llama-cpp-python", False),
    ]

    all_ok = True
    for module, pip_name, required in deps:
        try:
            __import__(module)
            status = "✅"
        except ImportError:
            if required:
                status = "❌ REQUIRED"
                all_ok = False
            else:
                status = "⚠️  optional"
        print(f"  {status:16s} {pip_name}")

    # Check for GGUF models
    print()
    gguf_files = list(paths.models_llm.glob("**/*.gguf"))
    if gguf_files:
        print(f"  ✅ LLM model: {gguf_files[0].name}")
        for f in gguf_files[1:4]:
            print(f"     + {f.name}")
    else:
        print(f"  ⚠️  No GGUF model found in {paths.models_llm}")
        print(f"     → Use Settings → Recommended Models to download, or place a .gguf in Data/Models/LLM/")

    # Paths
    print(f"\n📁 Paths:\n{paths.summary()}")

    # Check configs
    print()
    if paths.defaults_file.exists():
        print(f"  ✅ System defaults: {paths.defaults_file}")
    else:
        print(f"  ❌ System defaults missing: {paths.defaults_file}")
        all_ok = False

    if paths.modes_file.exists():
        print(f"  ✅ System modes: {paths.modes_file}")
    else:
        print(f"  ❌ System modes missing: {paths.modes_file}")
        all_ok = False

    if paths.user_config_file.exists():
        print(f"  ✅ User config: {paths.user_config_file}")
    else:
        print(f"  ⚠️  No user config (using defaults)")

    if paths.custom_modes_file.exists():
        print(f"  ✅ Custom modes: {paths.custom_modes_file}")
    else:
        print(f"  ℹ️  No custom modes (optional)")

    if not all_ok:
        print("\n❌ Issues detected. Fix the items marked ❌ above.")
    else:
        print("\n✅ All good!")

    return all_ok


def list_audio_devices():
    """List available microphones."""
    try:
        from utils.audio import AudioRecorder
        devices = AudioRecorder.list_devices()
        print("\n🎤 Detected microphones:\n")
        for d in devices:
            print(f"  [{d['id']}] {d['name']} ({d['inputs']} channel(s))")
        if not devices:
            print("  No microphone found!")
    except Exception as e:
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="PerkySue — Local voice assistant")
    parser.add_argument("--data", "-d", help="Path to Data folder/")
    parser.add_argument("--check", action="store_true", help="Check dependencies")
    parser.add_argument("--devices", action="store_true", help="List microphones")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug mode")

    args = parser.parse_args()

    _configure_windows_console_utf8()

    # Initialiser les chemins portables AVANT tout autre import
    from paths import get_paths
    paths = get_paths(data_dir=args.data)
    paths.set_env()  # Force HF_HOME, caches, etc. dans Data/

    setup_logging(args.verbose, log_file=paths.log_file)
    log = logging.getLogger(__name__)

    # Stable UUID for this Data/ folder (licensing / perkysue.com) — created on first launch
    from utils.install_id import get_or_create_install_id

    _install_path = paths.configs / "install.id"
    _had_install = _install_path.is_file() and _install_path.stat().st_size > 0
    _iid = get_or_create_install_id(paths.configs)
    if not _had_install:
        log.info("Created Data/Configs/install.id (first run for this folder): %s…", _iid[:8])

    if args.check:
        check_dependencies(paths)
        return

    if args.devices:
        list_audio_devices()
        return

    # Mode normal

    print('''
    ╔═══════════════════════════════════════╗
    ║                                       ║
    ║   PerkySue                            ║
    ║   Your voice assistant, 100% local    ║
    ║   100% portable                       ║
    ║                                       ║
    ╚═══════════════════════════════════════╝

    Created by Jérôme Corbiau | Licensed under Apache 2.0

    ''')

    import time
    time.sleep(2)

    print('''
                          .-"""---.                                     
                        .'  .-.    `.                                   
                      .'  .'  ; `.   \                                  
                     /   /    :   \   \                                 
                    /   /-.___;\   ;   ;                                
                   /   :;--.  .---.:    :                                
                  :    ;:<o>`  <o>  :    :                                
                 ;    : ;          ;    ;                                
                  :   ; :    +     /   .'                                 
                   \  ;  \  ---' .:s-"'                                   
                    "-:.-"`.__.-";                                      
                           :     :                                      
                           ;     :                                      
                    _..+-""._    _"t-.._                                
                 .-"    \    "  '  :    `.                              
                /        `-.______.'      \                             
               :                           ;                            
               ;                           :                            
              :     :                :,     \                           
              ;    /;                 \.   .'\                          
             :'.__/ :            :     :\-'   \                         
             ;   :   ;           ;      :\     \                        
            :    ;   :   `.____.'  .__.'  \     \                       
            ;   :     \              :     \     \                      
           :    ;      ;             ;      \     \    
    ''')
    import time
    time.sleep(1)
    print('''
          ;    :       :            :,-.     \    "-.                  
          :    ;        ;           ;o-.`._   \      `.                
          ;    :        :._____..--";\\--"     ".      `.              
         ;    ;         ;           :._;         "-.     `.            
         ;    :         /      c    ;              "-._    `.          
        ;    ;        /j.            :                  "-.   `.__       
       ;    /        /: :"-+......-jc";                    "-.    ""--.  
      ;    /        / ; ;  ;   ;   ; `:                       `. `.J"-.\ 
     ;    /        : : :   :    ;  :   \                        `---'""" 
    :    /         ; | |    ;   :   ;   \                               
    ;   /         :  ; ;    :    ;  :    \                              
   :   :          ; :  ;     \   :   \    ;                             
  /    ;         :  |  |;     `.  ;   `.  :                             
 /  , /          ;  ;  ::       \ :     \  ;                            
: /: /          :  :    ;;       ; ;     L_l                            
;: ;'           l__;    ::       :_:   .'                               
:J/                L_   J-\  __._;;'""j                                 
J/                   "t"   ""     :   ;                                 
                       \           ; :                                  
                        \          : ;                                  
                         \          Y                                   
                          \         :       

        ____               __             _____               
       / __ \ ___   ____  / /__  __  __  / ___/ __  __ ___    
      / /_/ // _ \ / ___// //_/ / / / /  \__ \ / / / // _ \   
     / ____//  __// /   / , <  / /_/ /  ___/ // /_/ //  __/   
    /_/     \___//_/   /_/|_|  \__, /  /____/ \__,_/ \___/    
                              /____/                          


    100% local • 100% private • 100% portable
    
    ''')



    from orchestrator import Orchestrator

    app = Orchestrator(paths=paths)

    if not app.initialize():
        print("\n⚠️  Some services are not available.")
        print("   Run: Python\\python.exe App\\main.py --check\n")
        response = input("Continue anyway? [Y/n] ").strip().lower()
        if response in ("n", "no"):
            print("👋 Goodbye!")
            return

    app.run(use_gui=True)


if __name__ == "__main__":
    main()
