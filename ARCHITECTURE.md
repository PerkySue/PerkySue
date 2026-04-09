# PerkySue — Architecture

*Version 1.52 — April 2026 — Beta 0.28.8 — Pro licensing: `license.json` + strict `install_id` match; optional **Ed25519** `license_payload` / `license_signature` from `GET /check` (`App/utils/license_signature.py`, `cryptography`); offline max **30 days** after signed `issued_at`; legacy unsigned cache still accepted until refresh; `POST /billing-portal`; link wizard; `_license_http_headers()`; plan UI; header banner (see plan management docs). **Pro TTS:** Chatterbox / OmniVoice, `tts_prompt_extension.yaml`, LLM appendix for Answer+Help when TTS enabled; **PyTorch CUDA** pip from Voice tab or root `.bat` files — **no in-process torch reload** after pip (**full app restart** required). **(Shipped 0.28.7) OmniVoice portable —** `windows_ffmpeg_dlls.py` registers **`Python/`** + **`Data/Tools/ffmpeg-shared/bin/`** for FFmpeg **shared** DLLs (TorchCodec on Windows); `omnivoice_tts.py` patches **`torchaudio.load`/`save`** for local **`.wav`** via **soundfile**; **`ref_text=""`** when no transcript (avoids Whisper ASR + avoids prepending dummy words — OmniVoice **`_combine_text`** prefixes **`ref_text`**); optional **`voice_ref.txt`** / **`audios/voice_sample/<code>.txt`**. **Alpha 0.28.4:** CMD UTF-8; `start.bat` fixes; **`feedback.debug_mode`**; Alt+A / Alt+Q / thinking default off / TTS tag display strip. **Beta 0.28.8:** Chat + Help GUI refresh (pill nav, input bar, bubbles); sidebar statuses **`generating`** / **`speaking`**; main avatar ring modulated by TTS + mic PCM (`TTSManager`, `AudioRecorder`); TTS Markdown strip **`strip_basic_markdown_for_tts`** (`tag_sanitize.py`); README banner **`App/assets/Github/banner.webp`**.*

---

## Overview

PerkySue is a portable, local voice-to-text assistant with AI-powered text enhancement. It runs entirely on the user's machine with zero cloud dependencies.

**Core Principles:**
- 100% local processing (STT + LLM)
- Portable installation (USB-stick friendly)
- System/User separation (updates don't touch user data)
- Dual LLM mode (direct for speed, server for compatibility)
- Antivirus-friendly (uses %TEMP% for temporary files)
- GUI widget (CustomTkinter) for non-technical users
- Open Core model: Alt+T free, 8 LLM modes Pro ($9.90/mo via Stripe post-alpha), skins via Patreon
- Pro gating: post-alpha Stripe license with monthly verification

### GUI strings (i18n)

- **Loader:** `App/utils/strings.py` — `load_strings(lang)` merges the requested language with English fallback (`App/configs/strings/en.yaml`).
- **Access:** `s("dotted.key")` for strings, `s_list("dotted.path")` for lists (e.g. About links), `merge_strings_at("path")` for nested trees (e.g. `header_tips`, `header_alerts`).
- **Header tips & alerts:** All rotating startup tips, header-bar notifications, Run Test hints, and document-injection strings live under **`header_tips`** and **`header_alerts`** in `App/configs/strings/<lang>.yaml`. `App/configs/header_tips.yaml` and `header_alerts.yaml` are stubs (`{}`); optional **`Data/Configs/header_tips.yaml`** / **`header_alerts.yaml`** can still override specific keys without editing the language files.
- **Header banner (single persistent line):** Replaces the old static `common.header_subtitle`. Keys **`common.header_banner.free_invite`**, **`free_after_trial`**, **`pro_trial`** (uses Python `str.format` with **`{days}`**), **`pro`**, **`enterprise`** in each `strings/<lang>.yaml`. **`Orchestrator.get_header_banner_spec()`** returns the i18n key and format args from **`get_gating_tier()`**, **`trial.json`** expiry (if present), and **trial consumed** heuristics (empty marker file **`Data/Configs/trial_consumed.marker`**, **`licensing.trial_consumed`** in user config, or past-dated `trial.json`). **`PerkySueWidget`** in `widget.py` builds the final string in **`_compute_header_banner_text()`** and refreshes it on language change, plan management refresh, and dev tier reload. This UI is **not** fetched from the public website or Worker.
- **Mode labels:** User-visible mode names and one-line descriptions for **Shortcuts** (Mode column) and **Prompt Modes** cards use `modes.registry.<mode_id>.name` and `modes.registry.<mode_id>.description`, with fallback to orchestrator `Mode` data from `modes.yaml` when a key is missing.
- **Sidebar:** Text under **Save & Restart** uses `settings.save_sidebar_note` (separate from the Shortcuts page footnote `shortcuts.restart_note`). **Voice** (`common.nav.voice`) is the Pro TTS tab; strings live in each `strings/<lang>.yaml`.
- **Skins:** The built-in skin id stays `Default`; the grid label uses `settings.appearance.default_skin`.

#### Interface language — flag grid (User tab)

The GUI exposes **16** flag buttons (`FLAG_STEMS_ORDER` in `App/gui/widget.py`). They map to **`ui.language`** and load **`App/configs/strings/<lang>.yaml`** via `load_strings()`.

- **16 locale packs** are active on disk: `us`, `gb`, `fr`, `de`, `es`, `it`, `pt`, `nl`, `ja`, `zh`, `ko`, `hi`, `ru`, `id`, `bn`, `ar`.
- **English split (pre-launch):** US and UK are explicit locales (`us.yaml`, `gb.yaml`).
- **Fallback strategy:** `en.yaml` remains the technical fallback loaded by `App/utils/strings.py` if a key is missing in the active locale file.

| Flag PNG (`App/assets/lang-flags/`) | `ui.language` | Strings file |
|--------------------------------------|---------------|--------------|
| `us.png` | `us` | `us.yaml` |
| `uk.png` | `gb` | `gb.yaml` |
| `fr.png` | `fr` | `fr.yaml` |
| `de.png` | `de` | `de.yaml` |
| `es.png` | `es` | `es.yaml` |
| `it.png` | `it` | `it.yaml` |
| `pt.png` | `pt` | `pt.yaml` |
| `nl.png` | `nl` | `nl.yaml` |
| `jp.png` | `ja` | `ja.yaml` |
| `ko.png` | `ko` | `ko.yaml` |
| `cn.png` | `zh` | `zh.yaml` |
| `in.png` | `hi` | `hi.yaml` |
| `ru.png` | `ru` | `ru.yaml` |
| `id.png` | `id` | `id.yaml` |
| `bd.png` | `bn` | `bn.yaml` |
| `sa.png` | `ar` | `ar.yaml` |

**Maintenance:** When adding a language, update `FLAG_STEMS_ORDER`, `FLAG_STEM_TO_LANG`, `FLAG_STEM_NATIVE_LABEL`, and `_ui_flag_stem()` in `widget.py`, add `App/configs/strings/<lang>.yaml`, and add `App/assets/lang-flags/<stem>.png`.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER LAYER                           │
│  (Persistent across updates)                                │
├─────────────────────────────────────────────────────────────┤
│  Data/Configs/config.yaml       ← User settings             │
│  Data/Configs/unlock.txt        ← (deprecated)               │
│  Data/Configs/license.json      ← Pro license (post-alpha)   │
│  Data/Configs/modes.yaml        ← Custom/override modes     │
│  Data/Models/LLM/               ← GGUF model files          │
│  Data/Models/Whisper/           ← Whisper models (auto)     │
│  Data/Models/TTS/               ← TTS engine weights (Pro; on demand) │
│  Data/Tools/                    ← llama-server.exe + DLLs   │
│  Data/Skins/                    ← Pro skins (Sue, Mike)     │
│  Data/Logs/                     ← Application logs          │
└─────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│                      SYSTEM LAYER                           │
│  (Replaced on every update)                                 │
├─────────────────────────────────────────────────────────────┤
│  App/                                                       │
│    ├── configs/                   ← Factory defaults        │
│    │   ├── defaults.yaml                                    │
│    │   ├── strings/               ← GUI i18n (`<lang>.yaml`; `load_strings` + `s()` / `s_list()` in `App/utils/strings.py`; English fallback file is `en.yaml`) │
│    │   ├── header_alerts.yaml      ← Optional stub / overrides (defaults in strings/<lang>.yaml → header_alerts) │
│    │   ├── header_tips.yaml       ← Optional stub / overrides (defaults in strings/<lang>.yaml → header_tips) │
│    │   ├── modes.yaml             ← 9 built-in modes       │
│    │   ├── recommended_models.yaml  ← LLM catalog (GUI + optional CLI downloader) │
│    │   └── tts_prompt_extension.yaml ← TTS tag palettes + default personality (LLM appendix) │
│    ├── gui/                                                 │
│    │   └── widget.py              ← CustomTkinter GUI (NEW v19.7) │
│    ├── services/                                            │
│    │   ├── base.py                  ← Re-exports STTProvider, TranscriptionResult (0.21.5) │
│    │   ├── stt/                   ← Speech-to-Text          │
│    │   │   └── whisper_stt.py      ← faster-whisper         │
│    │   ├── llm/                   ← LLM providers           │
│    │   │   ├── __init__.py        ← Factory + fallback      │
│    │   │   ├── llamacpp_llm.py     ← Direct mode            │
│    │   │   ├── llamacpp_server.py  ← Server mode            │
│    │   │   ├── ollama_llm.py       ← Ollama provider        │
│    │   │   └── openai_llm.py       ← OpenAI-compatible API  │
│    │   └── tts/                   ← Pro TTS (shipped in App/) │
│    │       ├── manager.py         ← TTSManager + voice packs │
│    │       ├── installer.py       ← pip + HF from GUI       │
│    │       ├── chatterbox_tts.py  ← Chatterbox Turbo (+ MTL where used) │
│    │       ├── omnivoice_tts.py   ← OmniVoice engine        │
│    │       ├── pytorch_cuda.py    ← CUDA wheel index (cu128/cu124), GPU kernel probe │
│    │       └── prompt_extension.py ← LLM appendix (tags + personality) │
│    ├── utils/                                               │
│    │   ├── hotkeys.py              ← Win32 RegisterHotKey   │
│    │   ├── audio.py                ← Recording + VAD        │
│    │   ├── injector.py             ← Text injection + WM_COPY │
│    │   └── sounds_manager.py       ← Skin-aware, fallback   │
│    ├── Skin/Default/              ← Built-in skin assets    │
│    │   ├── audios/                                          │
│    │   └── images/                                          │
│    ├── orchestrator.py             ← Central coordinator    │
│    └── main.py                     ← Entry point            │
└─────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME LAYER                           │
│  (Python embedded, independent)                             │
├─────────────────────────────────────────────────────────────┤
│  Python/                                                    │
│    ├── python.exe                                           │
│    ├── python311._pth             ← Must include Lib, DLLs  │
│    ├── Lib/site-packages/         ← pip dependencies        │
│    │   ├── faster-whisper                                   │
│    │   ├── nvidia-cublas-cu12      ← CUDA runtime (NVIDIA only)
│    │   ├── nvidia-cudnn-cu12       ← cuDNN runtime (NVIDIA only)
│    │   ├── customtkinter          ← GUI framework (NEW v19.7)│
│    │   ├── pillow                 ← Image generation GUI    │
│    │   ├── requests               ← HTTP client             │
│    │   └── ...                                              │
│    └── Lib/tkinter/               ← from Assets ZIP         │
└─────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│                      ASSETS LAYER                           │
│  (Bundled with installer, not user-modifiable)              │
├─────────────────────────────────────────────────────────────┤
│  Assets/                                                    │
│    ├── tkinter-3.11-embed.zip    ← DLLs + Lib/tkinter + tcl │
│    │                                 (extracted into Python/ at setup)
│    └── vcredist-x64-portable.zip ← VC++ runtime (msvcp140, vcruntime140) │
│                                     deployed by install.bat into each    │
│                                     Data/Tools/<backend>/ (Alpha 0.20.2) │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. Orchestrator (`App/orchestrator.py`)

Central coordinator that:
- Loads and merges configurations
- Initializes STT and LLM providers
- Manages hotkey registration
- Coordinates audio → STT → LLM → injection pipeline
- Exposes `stop_recording()` for manual stop (GUI avatar click when ambient noise prevents VAD auto-stop); registers global `hotkeys.stop_recording` (default **`alt+q`**) via `HotkeyManager` → `_on_escape_hotkey()` → GUI `_on_escape_global`

### 2. LLM Provider Factory (`App/services/llm/__init__.py`)

Implements dual-mode architecture:

| Mode | Class | Use Case | Speed |
|------|-------|----------|-------|
| Direct | `LlamaCppLLM` | RTX 30xx/40xx, fast GPUs | ~3s |
| Server | `LlamaCppServerLLM` | RTX 50xx, compatibility | ~11s |
| Ollama | `OllamaLLM` | External Ollama instance | Varies |
| OpenAI | `OpenAICompatibleLLM` | Any OpenAI-compatible API | Varies |

**Auto-detection logic:**
1. Detect RTX 50xx via `nvidia-smi` → force server mode
2. Check `force_direct_mode` override → use direct
3. Check `force_server_mode` override → use server
4. Default to direct, fallback to server on crash

### 3. Hotkey Manager (`App/utils/hotkeys.py`)

Uses Win32 `RegisterHotKey` API:
- Consumes keystrokes (no Windows "ding")
- Supports left/right modifier keys
- Thread-safe callbacks
- AltGr: for `Alt+X` without explicit `*_altgr` in YAML, also registers `Ctrl+Alt+X` so European keyboards work
- **`stop_recording`** (default `alt+q`): registered with **`skip_altgr=False`** so **Alt+Q** and **Ctrl+Alt+Q** (AltGr) both call `_on_escape_hotkey` → widget `_on_escape_global`
- **Avoid in config:** `alt+escape` (Windows reserves it), fragile `alt+shift+escape`; **do not** add low-level hooks here for Escape — risk of system-wide keyboard lockup
- Widget `_on_escape_global` stops on **`recorder.is_recording`** without requiring `status=="listening"` (race: `set_status` is `after(0)`)

See module docstring in `hotkeys.py` and comments in `defaults.yaml` / `orchestrator.py` (hotkey init block).

### 4. Focus Tracking (`App/utils/injector.py`)

Saves active window handle before recording:
- Uses `AttachThreadInput` trick for `SetForegroundWindow`
- Restores focus after LLM processing
- Injects text via clipboard + Ctrl+V
- **NEW v19:** Selection grab via WM_COPY

### 5. Backend Launcher (`start.bat`)

Manages llama-server.exe lifecycle:
- Detects GPU type (NVIDIA/AMD/Intel/CPU)
- Copies appropriate backend to `Data/Tools/active/`
- Sets env vars `PERKYSUE_BACKEND` and `PERKYSUE_GPU_NAME`
- Uses `%TEMP%` as working directory (antivirus workaround)
- Verifies Python imports before launch (auto-installs missing deps)
- Launches llama-server.exe in background
- Launches `App/main.py` which starts orchestrator + GUI

### 6. GUI Widget (`App/gui/widget.py`) — NEW v19.7

CustomTkinter floating widget, always-on-top optional, dark mode native.

**Structure:**
```
PerkySueWidget (CTk window)
├── Header (tk.Canvas)          ← True transparency via Canvas, PIL gradient
│   ├── Title "PerkySue"
│   ├── Badge "Beta"
│   └── ❤️ Patreon button (PIL drop shadow)
├── Sidebar (CTkFrame)          ← Navigation with icons + active violet bar
│   ├── Console
│   ├── Settings
│   ├── Shortcuts
│   ├── Prompt Modes
│   └── About
├── Content (scrollable CTkFrame per tab)
│   ├── [Console]    Finalized / Temporary Logs + Full Console + status indicator
│   ├── [Settings]   Appearance + Performance + Models
│   ├── [Shortcuts]  hotkeys read-only (Transcribe, 8 LLM modes, Custom 1/2/3)
│   ├── [Prompt Modes] (TODO)
│   └── [About / Pro] (TODO)
└── Footer (CTkFrame)           ← GitHub link + version badge
```

**Design System (strict rules — must be followed in all future GUI work):**

| Element | Rule |
|---|---|
| Font | Segoe UI exclusively |
| Section titles | `("Segoe UI", 20, "bold")` |
| Buttons / important text | `("Segoe UI", 14, "bold")` or `16` |
| Secondary text | `("Segoe UI", 12)` or `13` |
| Section title padding | `pady=(20, 10)` |
| Card/box padding | `pady=(0, 20), padx=(0, 28)` |
| **Scrolls (scrollbars)** | **4px from border** — any scrollable section (e.g. Appearance skin grid) must use `padx=(…, 4)` on the right so the scrollbar sits 4px from the container edge, consistent with the main page scroll. |
| **Sub-scroll (zone with images / cells)** | When a scrollable zone (e.g. Appearance skin grid, Console Finalized Logs) contains **images or clickable cells**, bind `<MouseWheel>` to the **same handler** on the scrollable frame **and** on every cell element (frame, image/label, button). At top/bottom of the zone, do **not** return `"break"` so the page scroll takes over. In the page wheel handler, if the pointer is over the zone and the zone can still scroll, do not scroll the page. |
| **Important notifications (blink)** | For notifications that require user action (e.g. “You need to Save & Restart PerkySue”), use `_notify(message, restore_after_ms=4000, blink_times=3, blink_on_ms=300, blink_off_ms=300)`. Message blinks 3× (300 ms on, 300 ms **empty** — do not show the old title during off). Then message stays 4 s; only then restore the normal title. **Simple notifications** (e.g. "Copied to clipboard"): `_notify(message, restore_after_ms=1500)` **without** blink — single display, then restore. |
| **Log-style cells (reusable)** | For lists of cards with text + Copy (Finalized Logs, Shortcuts, Prompt Modes): 1 px separator `#3A3A42` pady=(1,1); card pady=(0,1), CARD border `#3A3A42`; label with **dynamic wraplength** via `<Configure>` (e.g. `wraplength = max(180, event.width - 50)`); one Copy per cell → simple notification 1.5 s; zone scrollbar `scrollbar_fg_color=INPUT`; sub-scroll bound on frame + all children. |
| All cards | `fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42"` |
| Colors | Use global variables only: `BG`, `CARD`, `SIDEBAR`, `TXT`, `TXT2`, `MUTED`, `ACCENT_G` |
| Complex images | PIL `ImageDraw` generator functions (gradients, round avatars, progress bars with text) |

**CustomTkinter workarounds discovered v19.7:**

| Problem | Solution |
|---|---|
| Text with black background on header | `tk.Canvas` for true transparency |
| Smooth gradients | `PIL.ImageDraw`, generated on-the-fly |
| Drop shadows (Patreon button) | `PIL.ImageDraw`, generated on-the-fly |
| Progress bars with superimposed text | PIL generator function |
| Round avatars | PIL circular mask |
| Responsive Appearance section | `grid_columnconfigure` with weights |

**Skin dropdown as marketing tool (Appearance tab):**
- "Default" → selectable, functional
- "Sue" (premium skin, 🔒) → visible, locked
- "Mike" (premium skin, 🔒) → visible, locked
- Click on locked skin → opens browser to Patreon URL
- If `Data/Skins/Sue/profile.png` exists → avatar shown, lock removed
- **Selected skin:** 5px border in the **same colour as the profile picture ring** (sidebar avatar status: Listening = green, Ready = white, etc.) so the selected skin and main avatar are visually aligned. **Locked skins:** lock icon 🔒 larger inside the same badge (pastille size unchanged). **Cursor:** hand2 on skin images, labels, and Patreon button for consistency.

**Profile picture (sidebar avatar):**
- **Outer ring colour** follows the current event/status (Listening = green, Processing = orange, Injecting = violet, Ready = white, etc.). The **black spacing** between the profile image and this outer ring is preserved.
- Avatar is redrawn when status changes so the ring always matches the status indicator below.

**Model cards — 4 visual states:**

| State | Color | Meaning |
|---|---|---|
| Get | Green | Available for download |
| Progress | PIL bar | Download in progress |
| Select | Blue | Present on disk, selectable |
| Current | Greyed | Currently loaded |

### 7. Assets Folder — NEW v19.7

**tkinter:** `Assets/tkinter-3.11-embed.zip` contains the tkinter runtime (DLLs, `Lib/tkinter/`, `tcl/`) needed by Python 3.11 embedded, which does not ship tkinter by default.

**VC++ portable (Alpha 0.20.2):** `Assets/vcredist-x64-portable.zip` contains the Visual C++ Redistributable DLLs (msvcp140, vcruntime140, etc., release x64 only). So that `llama-server.exe` runs on machines without the VC++ Redistributable installed (e.g. portable USB), `install.bat` (step 7b) deploys these DLLs into **each existing backend folder** under `Data/Tools/` (vulkan, cpu, nvidia-cuda-12.4, nvidia-cuda-13.1). The folder `Data/Tools/active/` is **not** populated by install: it is a **runtime** folder that `start.bat` fills at launch by copying the chosen backend (including those DLLs) into `active/` and then running `llama-server.exe` from there.

`install.bat` extracts the tkinter ZIP during setup:
1. Check if tkinter already present
2. Create `Python/Lib/DLLs/` if absent
3. Extract via PowerShell (fallback: `tar`)
4. Final locations: `_tkinter.pyd`, `tcl/`, `tk/`, `Lib/tkinter/`
5. Update `python311._pth` to include `Lib` and `DLLs`

`python311._pth` must contain:
```
python311.zip
.
Lib
DLLs
```

---

## Data Flow

```
User presses Alt+M (or other hotkey)
         │
         ▼
┌─────────────────┐
│  HotkeyManager  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  grab_selection │  ← New v19
│  (WM_COPY msg)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐  ┌──────────┐
│ Audio │  │ selected_│  ← passed-over in pipeline
│Record │  │ text     │
└───┬───┘  └──────────┘
    │
    ▼
┌─────────────────┐
│  Whisper STT    │  ← faster-whisper
│  (GPU/CPU)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  Transcribe     │────→│  No LLM         │  ← needs_llm: false
│  (Alt+T)        │     │  Direct inject  │
└─────────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  Other modes    │────→│  llama.cpp      │  ← needs_llm: true
│  (Alt+I/P/A/M…) │     │  Direct/Server  │
└─────────────────┘     └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌─────────┐  ┌──────────┐  ┌─────────┐
              │  Direct │  │  Server  │  │  Error  │
              │  Mode   │  │  Mode    │  │ Fallback│
              │  (fast) │  │  (compat)│  │         │
              └────┬────┘  └────┬─────┘  └────┬────┘
                   │            │             │
                   └────────────┴─────────────┘
                                │
                                ▼
                      ┌─────────────────┐
                      │  Text Injection │
                      │ Clipboard+Ctrl+V│
                      │  Restore Focus  │
                      └─────────────────┘
```

---

## Backend Architecture

### Folder Structure

```
Data/Tools/
├── nvidia-cuda-12.4/ ← All NVIDIA RTX 20xx-50xx (CUDA 12.4)
│   ├── llama-server.exe
│   ├── ggml-cuda.dll
│   ├── cudart64_12.dll
│   └── cublas64_12.dll...
│
├── nvidia-cuda-13.1/ ← Reserved for future (requires driver 580+)
│   ├── llama-server.exe
│   ├── ggml-cuda.dll
│   ├── cudart64_13.dll
│   └── cublas64_13.dll...
│
├── vulkan/          ← Vulkan backend (AMD/Intel)
│   ├── llama-server.exe
│   ├── ggml-vulkan.dll
│   └── vulkan-1.dll...
│
├── cpu/             ← CPU-only backend
│   ├── llama-server.exe
│   └── ggml-cpu-*.dll...
│
└── active/          ← Runtime folder (populated at launch)
    └── llama-server.exe  ← Copied from detected backend folder
```





### Activation Flow

```
start.bat
    │
    ├── Detect GPU (nvidia-smi / registry)
    │       └── All NVIDIA (RTX 20xx-50xx) → backend = nvidia-cuda-12.4
    │       └── AMD/Intel → backend = vulkan
    │       └── No GPU → backend = cpu
    │
    ├── Check Data/Tools/{backend}/llama-server.exe
    │       └── If missing: Show error (Patreon) or download instructions (GitHub)
    │
    ├── Clean Data/Tools/active/
    ├── Copy all files from {backend}/ to active/
    │
    ├── pushd %TEMP%                    ← Antivirus workaround
    ├── set LINENOISE_HOME=%TEMP%       ← Prevent file creation in protected folders
    ├── start llama-server.exe
    └── popd
```

### Antivirus Workaround

**Problem:** Antivirus (Avast, Bitdefender) blocks llama-server.exe from:
- Writing `linenoise.cpp.txt` to Downloads/Documents
- Creating files in user folders

**Solution:** Use Windows `%TEMP%` folder:

```batch
REM In start.bat
pushd "%TEMP%"
set "LINENOISE_HOME=%TEMP%"
set "HOME=%TEMP%"
start /B "" "%ACTIVE_DIR%\llama-server.exe" --host 127.0.0.1 --port 8080 >nul 2>&1
popd
```

**Benefits:**
- %TEMP% is system-managed and AV-whitelisted
- Files are automatically cleaned by Windows
- No persistent files in user folders

---

## Configuration System

### Deep Merge Strategy

```
App/configs/defaults.yaml  ← System defaults (factory, in App/)
+
Data/Configs/config.yaml   ← User overrides (only file in Data/Configs read for main config)
↓
Merged Config          ← Runtime configuration
```

User values override system values. Missing user values fall back to defaults.

**Important:** The app does **not** read any `defaults.yaml` in `Data/Configs/`. Only `Data/Configs/config.yaml` is used for user preferences. Do not create `Data/Configs/defaults.yaml`; if it exists, you can delete it. Edit `config.yaml` to override STT/LLM/skin etc.

### Recommended LLM models catalog (`App/configs/recommended_models.yaml`)

Single source of truth for recommended Hugging Face GGUF models:

- **Consumers:** GUI Settings → Recommended Models (`widget.py`), and optional console downloader (`App/tools/download_model.py` for contributors). Both read this YAML; no duplicate model lists.
- **Per-model fields:** `id`, `author`, `family`, `name`, `params`, `quant`, `thinking`, `uncensored`, `languages`, `size_hint`, `stars`, `good_for_qa`, `popularity`, `icon`, `icon_file`, `color`, `repo_id`, `filename`, `backends` (e.g. `cpu`, `vulkan`, `nvidia-cuda-12.4`, `nvidia-cuda-13.1`).
- **Localized tooltip one-liners (16 UI languages):** `comment_ar`, `comment_bn`, `comment_de`, `comment_gb`, `comment_us`, `comment_es`, `comment_fr`, `comment_hi`, `comment_id`, `comment_it`, `comment_ja`, `comment_ko`, `comment_nl`, `comment_pt`, `comment_ru`, `comment_zh`. The GUI picks the field that matches `ui.language` (`us`, `gb`, `fr`, …); fallback order: active locale → `comment_us` → `comment_gb` → legacy `comment` if still present.
- **Optional:** `description` — short line for the **console** downloader menu only; if omitted, `download_model.py` uses `comment_us`, then `comment_gb`, then `comment`. Optional: `languages_tooltip` for extra detail. Optional: **`icon_file`** — image under `App/assets/model-icons/` (256×256); if present, the GUI shows this logo instead of the letter `icon`. One icon per **family** where possible.
- **Model icons (logos):** `App/assets/model-icons/` — place 256×256 PNG files here, **one per family** (e.g. `gemma.png`, `qwen.png`, `mistral.png`, `llama.png`, `deepseek.png`, `glm.png`, `grok.png`, `LFM.png`, `Phi.png`). **Layer-1 / base models** (LFM, Phi) have their own icons; **mix/hybrid/abliterated** models use **`hybrid.png`** only. In the YAML, set `icon_file: "Gemma"` (or `"LFM"`, `"Phi"`, etc.); if the file is absent, the GUI falls back to the letter `icon`.
- **Workflow:** When adding or changing a recommended model, edit this file only; then update public documentation (README/ARCHITECTURE) if the change impacts users.

### Community KB and Help mode (`perkysue_kb.md` + `kb_help_*.md`)

- **`perkysue_kb.md` (repo root):** Long-form, canonical facts for **community support** (Discord, FAQs, accurate answers about plans, hardware, privacy). It is **not** read by the runtime; treat it as the **master text** to keep aligned with README / release notes. When product behavior or tier rules change, update this file, then sync the shipped Help KB files below.
- **In-app Help (Alt+H):** `Orchestrator._load_help_kb_content()` loads **`kb_help_{tier}.md`** where `tier` is **`2048`**, **`4096`**, or **`8192`**, chosen by `_get_help_kb_tier()` from `llm.max_input_tokens` / `n_ctx` (≤2048 → `kb_help_2048.md`; ≤4096 → `kb_help_4096.md`; otherwise `kb_help_8192.md`). Files live in **`App/configs/`**; optional **user override:** same filenames in **`Data/Configs/`** (takes precedence).
- **Truncation:** `_build_help_system_prompt()` may truncate KB string length for small context windows (notably **≤1024** and **≤2048** `max_input_tokens`) so the prompt fits the LLM — see `App/orchestrator.py`.
- **Sync workflow:** After editing **`perkysue_kb.md`**, update the three **`App/configs/kb_help_2048.md`** (ultra-compact), **`kb_help_4096.md`** (medium), and **`kb_help_8192.md`** (full) so tier-specific Help prompts stay consistent. The **2048** file is what most low-`Max input` users get; keep it within the orchestrator truncation budget.

### Mode System

```
App/configs/modes.yaml     ← 10 built-in modes
+
Data/Configs/custom_modes.yaml  ← User custom modes
↓
Available Modes        ← Runtime modes
```

Custom modes with same ID override built-in modes.

### Header tips (`header_tips` in `App/configs/strings/<lang>.yaml`)

Tips shown in rotation in the title bar at startup. **Source of truth:** `startup_message`, list `tips`, and timing `delay_before_first_ms`, `display_ms`, `delay_between_ms` under `header_tips` in the language strings file; `merge_strings_at("header_tips")` in `widget.py`. `App/configs/header_tips.yaml` is a stub; optional **`Data/Configs/header_tips.yaml`** overrides the same keys.

### Header alerts (`header_alerts` in `App/configs/strings/<lang>.yaml`)

**Header bar only:** Sections `critical` and `regular` contain only messages that appear in the **title bar** (header). Status under the profile photo (Listening, Processing, Check microphone, etc.) is in `STATUSES` in `widget.py`, not here. One key `llm_error_400` is used both when the main pipeline injects after a 400 and when Prompt Modes Run Test returns 400. **Not header:** `run_test_400_hint` is appended to the Prompt Modes "LLM response (preview)" box when Run Test returns 400. **Document injection:** Section `document_injection` holds strings **pasted into the focused document** (e.g. Word) on LLM error or max context. `App/configs/header_alerts.yaml` is a stub; optional **`Data/Configs/header_alerts.yaml`** overrides the same keys.

### Pro License System

Pro features (8 LLM modes) are gated.

**Stripe License (`Data/Configs/license.json`)**

```json
{
  "license_id": "lic_xxxxx",
  "email": "user@example.com",
  "expiry_date": "2026-12-15",
  "signature": "<issued by server>",
  "tier": "pro"
}
```

**What lives where (important):**  
- **`Data/Configs/install.id`** — **UUID only** (plain text). It does **not** contain the Windows computer name; users cannot “unlock” another PC by editing this file. **Created locally** on first app launch if missing (`App/utils/install_id.py`, called from `App/main.py` when `start.bat` runs) — **perkysue.com does not issue** this value in the normal flow; the Worker only stores **subscription ↔ this UUID** in KV. If `Data` is wiped, a **new** UUID is created and **Pro will not** follow automatically without a **reclaim** flow (email + OTP) or restoring the old file — see the `install_id` product lifecycle and planned GUI flow notes.  
- **`license.json`** — offline **time window** for Pro after a successful server check; **no** hostname field (the authorized machine is enforced **on the server**).  
- **Server (Cloudflare KV)** — **Target (MVP one seat):** each active **trial** or **paid** record should store **`install_id` + `bound_hostname`**. **Frozen rule (spec):** **Trial** — `bound_hostname` is set on successful **`POST /trial/verify`** after OTP (same activation semantics as the legacy single-shot `POST /trial` where it still exists). **Paid Stripe** — webhooks link subscription to `install_id` **without** hostname; **`bound_hostname` is set on the first successful `GET /check`** once the subscription is active and KV has no `bound_hostname` yet; later checks must match. Each license check sends **install_id + hostname**; the Worker should enforce the match. **Effect:** copying the folder to **another** computer (different hostname) does **not** grant Pro until **transfer** (Brevo OTP). **Same PC + USB** → same hostname → OK.  
  **Implementation note (2026-03 / 2026-03-28):** the production Worker at `perkysue.com` **does not yet** read the `host` query parameter on **`GET /check`** and **does not persist `bound_hostname`** in KV objects written by webhooks. Subscription state is updated from Stripe under **`install:<install_id>`** when Checkout included that metadata, or under **`sub:<stripe_subscription_id>`** for **web-only** purchases (`/pro` without `install_id`). Linking a new local `install.id` to an existing `sub:*` record is **not** implemented yet (planned reclaim flow).

**Sliding offline window (~35 days) vs trial (30 calendar days):**  
- **Paid Pro:** After a successful `/check`, the server returns a new **`expiry_date`**, typically **today + 35 days** (sliding from the **check date**, not a fixed “monthly” calendar). While `expiry_date >= today`, the app stays Pro **without network**.  
- **Trial:** **30 calendar days** from server-side activation (`POST /trial/verify` after email proof); tracked in KV by email — not the same mechanism as the 35-day `license.json` refresh.  
- **5-day grace:** Applies only when **`expiry_date` has passed** and the app **cannot reach** the Worker (network down, timeout, transient server error). It does **not** apply when the server responds **subscription inactive** or **hostname mismatch**.

Verification flow (typical):
1. If `license.json` absent → evaluate trial / Free tier
2. If `license.json` present and `expiry_date >= today` → Pro (paid) active, no network check
3. If `license.json` expired or absent for paid path → HTTPS `/check` with **`install_id` + hostname** (see **`PRIVACY.md`**)
   - Subscription active + hostname matches → new `expiry_date` (~+35 days), rewrite `license.json`
   - Inactive or seat rejected → graceful degradation to Free tier
   - Network/server failure → up to **5 days** after `expiry_date` (grace) as implemented in `license.py`
4. **MVP:** **one seat** per subscription (no built-in “two devices”); **Stripe Customer Portal** for billing. See **`PRIVACY.md`** for Stripe, Brevo, and short **IP** logs on the Worker.

**Graceful degradation (both phases):** Alt+T remains functional. Alt+I/M/P/L/C/S/A/G display a GUI notification. No crash, no nag screen.

**Open-source caveat:** A developer can modify the client to send a fake hostname. The model targets **casual abuse** (folder sharing), not determined attackers — same honesty as the rest of the Open Core story.

---

## Skins — layout, IDs, resolution (Beta 0.28.8)

**Canonical config id:** `skin.active` = **`Default`** or **`Character/Locale`** (e.g. **`Mike/FR`**). Legacy **`Locale/Character`** on disk or in old configs is normalized when possible (`App/utils/skin_paths.py`).

**Unlocked Pro content lives under:** `Data/Skins/<Character>/<Locale>/` (example: `Data/Skins/Mike/FR/`).

```
App/Skin/Default/                     ← built-in
  audios/{stt_start|stt_stop|llm_start|llm_stop}/...
  audios/voice_sample/voice_sample.wav   (+ optional voice_sample.txt)
  images/profile.png

App/Skin/Teaser/<Character>/<Locale>/profile.png   ← teaser (locked until Data exists)
  (legacy teaser path Locale/Character still detected)

Data/Skins/<Character>/tts_personality.yaml   ← one file per avatar (optional)
Data/Skins/<Character>/<Locale>/
  profile.png
  voice_ref.wav (+ optional voice_ref.txt)
  audios/{stt_start|...}/...
  audios/voice_sample/voice_sample.wav (+ optional voice_sample.txt for OmniVoice transcript)
```

**Central resolver:** `App/utils/skin_paths.py` — `normalize_skin_id`, `resolve_locale_skin_dir`, character-first locale lookup for TTS speech language (`iter_existing_character_locale_dirs_for_speech`), teaser / `voice_ref` discovery.

**GUI — Appearance:** skin grid filter defaults to **UI language** (maps to pack folder codes FR, EN, …), not “All”. User may switch filter chips or open **All**. Patreon CTA unchanged.

**Orchestrator:** on skin change, `orch.config["skin"]["active"]` stays in sync with saved YAML so TTS/Help personality appendix matches the selected pack (`widget.py`).

**LLM + voice:** when Pro TTS appends tag/personality text, optional **Assistant display identity** clause names the character for “what’s your name?” style questions while **PerkySue** stays the product name (`orchestrator.py` + `prompt_extension.py`).

### Skin Audio Resolution (`sounds_manager.py`)

`SoundManager` resolves `skin_dir` to the active **`Data/Skins/<Character>/<Locale>/`** (or legacy swapped path), then:

For each sound event (`stt_start`, `stt_stop`, `llm_start`, `llm_stop`, `system/*`):

1. Try: `Data/Skins/<Character>/<Locale>/audios/{event}/` (recursive file search)
2. If missing or empty → `App/Skin/Default/audios/{event}/`
3. If Default also empty → silent (no error)

Per-event fallback: a pack may override only some events.

### TTS reference WAV resolution (`voice_sample_paths.py`)

For synthesis, PerkySue picks a reference under the **same character**, prioritizing a **locale folder that matches the speech language** (e.g. `Mike/EN` for English), then the **active pack** folder, then `App/Skin/Default/audios/voice_sample/`. Within each folder: **`voice_ref.wav`**, then **`audios/voice_sample/voice_sample.wav`** (and optional **`voice_sample.txt`**). If no file is found, the engine uses its built-in default (e.g. timbre from another locale may sound “accented” — expected when a language pack is missing).

### Patreon Skin Distribution System

Skins are distributed as `.perky` files (password-protected ZIP archives):

1. Subscriber downloads `Sue_Skin.perky` from Patreon post
2. Password is published in the private Patreon post
3. In the GUI: "Import Skin" button → user selects `.perky` + enters password
4. Python extracts assets under **`Data/Skins/<Character>/<Locale>/`** (e.g. `Data/Skins/Sue/FR/`), plus optional **`Data/Skins/<Character>/tts_personality.yaml`**.

**GUI display logic (circle never empty):**
- Skin unlocked (locale folder under `Data/Skins/` present): avatar from that folder’s `profile.png` (or `images/profile.png`), lock removed, skin selectable. Config id example: `Sue/FR`.
- Skin locked: avatar from **`App/Skin/Teaser/<Character>/<Locale>/profile.png`** (legacy **`Teaser/<Locale>/<Character>/`** still scanned), **lock icon 🔒** bottom-left, click opens Patreon URL.
- Lock state is **dynamic** (scan `Data/Skins/` at load). **Selection = immediate save**: choosing a skin writes `skin.active` to config and calls `sound_manager.set_skin()` so audio and sidebar avatar update without restart.

This design requires no PerkySue-hosted backend for skin distribution.

**Known bug (v19.3, still open):** `config.yaml` may ship with `skin: Sue` but GitHub/Basic tiers don't include Sue audio files → silence. The per-event fallback in `sounds_manager.py` addresses this.

### Pro TTS — engines, PyTorch CUDA, voice ref, LLM prompt extension (0.28.3–0.28.8)

- **Engines:** `TTSManager` selects **`chatterbox`** or **`omnivoice`** (`tts.preferred_engine_id` in merged config). Weights under **`Data/Models/TTS/`** + Hugging Face cache (`paths.models_tts`, `paths.huggingface`). Install and tests from the **Voice** sidebar tab (Pro).
- **PyTorch CUDA vs CPU-only (portable bundle):** TTS stacks (**Chatterbox**, **OmniVoice**) require **torch** with CUDA on NVIDIA when you want GPU synthesis. The embedded environment may have shipped with **CPU-only** wheels. **`App/services/tts/pytorch_cuda.py`** implements **`torch_gpu_runs_basic_kernels()`** (tiny matmul on device 0) because **`torch.cuda.is_available()`** alone is insufficient on some cards (e.g. **Blackwell / RTX 50xx** without matching SASS). **`nvidia_needs_pytorch_cu128()`** / compute-cap heuristics and **`pytorch_pip_index_url()`** choose **`https://download.pytorch.org/whl/cu128`** vs **`cu124`**. **`TTSManager._refresh_pytorch_cuda_install_offer`** surfaces the **Install PyTorch CUDA** action on the Voice tab when appropriate (including **cu124 present but kernel probe fails**).
- **GUI / installer rule (do not break):** **`TTSInstaller.install_pytorch_cuda`** → **`_install_pytorch_cuda_impl`** runs **`pip install --upgrade torch torchvision torchaudio --index-url …`**, then verifies with a **subprocess** using the same **`python.exe`** as portable installs. It **must not** call **`_purge_tts_extension_modules()`** for this path or **`import torch`** in the live app to “reload” — C extensions are not safe to unload/reload; symptoms include **einops** “Tensor type unknown”, **`_has_torch_function` docstring** crashes, and broken **`chatterbox`** imports. **`widget.py`** success handler: **no** **`unload_engine()` / `load_engine()`** after CUDA pip; user strings (**`voice.pytorch_cuda.done_message`**) require a **full quit and restart** of PerkySue.
- **Offline batch helpers (repo root):** **`install_pytorch_cuda_cu128.bat`**, **`install_pytorch_cuda_cu124.bat`** for the same index URLs without the GUI (cu124 script documents RTX 50xx → cu128). **OmniVoice / TorchCodec (Windows):** **`install_ffmpeg_shared_windows.bat`** — instructions to copy **FFmpeg *-gpl-shared*** **`bin/*.dll`** into **`Python/`** or **`Data/Tools/ffmpeg-shared/bin/`**.
- **Voice cloning:** **`voice_ref.wav`** (+ optional **`voice_ref.txt`**) in **`Data/Skins/<Character>/<Locale>/`**; **`TTSManager.scan_voice_packs()`** discovers packs via **`App/utils/skin_paths.iter_voice_ref_pack_dirs`**. Synthesis also uses **`audios/voice_sample/voice_sample.wav`** (+ optional **`voice_sample.txt`**) per § *TTS reference WAV resolution* above; see **`resolve_voice_sample_wav()`** / **`_voice_with_optional_lang_sample()`**.
- **OmniVoice — Windows / TorchAudio / TorchCodec:** TorchAudio 2.9+ uses **TorchCodec** for generic **`load`/`save`**; Windows needs **FFmpeg shared** DLLs (**`avutil-*`**, **`avcodec-*`**, etc.). **`App/services/tts/windows_ffmpeg_dlls.py`** calls **`os.add_dll_directory`** and prepends **`PATH`** for **`paths.python_dir`** and **`Data/Tools/ffmpeg-shared/bin`** when those folders contain the DLLs. User doc: **`install_ffmpeg_shared_windows.bat`**. For **local `.wav` paths**, **`omnivoice_tts._apply_local_wav_torchaudio_patch()`** routes **`torchaudio.load`/`save`** through **soundfile** so typical references work without a working TorchCodec stack.
- **OmniVoice — `ref_text` vs ASR:** Library code **`_combine_text`** prepends **`ref_text`** to the target string read aloud — dummy placeholders are heard as speech. **`ref_text=None`** triggers on-the-fly **Whisper** ASR (~1.6 GB) inside OmniVoice. PerkySue passes **`ref_text=""`** when only a file path is supplied and no **`ref_transcript`**, skipping ASR and skipping a spoken prefix. Real transcripts improve alignment.
- **When the LLM speaks (audio):** After a successful Answer or Help reply, if TTS is enabled, installed, and `mode_id` is in **`tts.trigger_modes`** (default `answer`, `help`), the orchestrator prepares speech from the final assistant text (see `orchestrator` speak path).
- **LLM system prompt appendix (tags + personality):** When **Pro**, **`tts.enabled`**, and the active mode is in **`trigger_modes`**, the orchestrator appends a markdown block to the **system** prompt (separator `---`) so the model knows which **bracket tags** the active TTS engine understands (e.g. Chatterbox Turbo vs MTL vs OmniVoice — lists are maintained in config, not hard-coded in Python). Implementation: **`App/services/tts/prompt_extension.py`** (`load_tts_prompt_config`, `build_tts_llm_appendix`, `resolve_skin_personality_prompt`); data: **`App/configs/tts_prompt_extension.yaml`** (`default_personality`, per-engine tag lists, `skin_personality_filename`). **Skin override:** **`tts_personality.yaml`** at **`Data/Skins/<Character>/tts_personality.yaml`** (character root), with optional legacy copy inside a locale folder; then **`App/Skin/Default/tts_personality.yaml`**. **Display identity:** non-Default skins may append an **Assistant display identity** sentence so the character name matches the pack while **PerkySue** remains the app name in KB-style answers (`orchestrator.py`).
- **GUI parity:** **`get_help_effective_system_prompt()`** applies the same appendix as the live Help pipeline so the displayed system prompt matches what is sent to the LLM.
- **Not extended:** Intent router (HELP/NOHELP), user-message translation for Help bubbles, greeting generator, Summarize (Alt+S), and other modes remain without this block unless the user adds their mode id to **`tts.trigger_modes`** (then both live and Run Test paths pick it up via `_append_tts_llm_extension`).
- **User-visible text vs synthesis (Alpha 0.28.4):** Unless **`feedback.debug_mode`** is true, **`strip_all_bracket_tags_for_display`** (`App/services/tts/tag_sanitize.py`) runs on **external Answer/Help injection** (Smart Focus paste) and on **finalized console** display lines — removing **`[MOOD: …]`** variants and generic **`[bracket tokens]`** so Word/Chrome/etc. do not show TTS markup. **TTS synthesis** still receives text filtered by engine-specific allowed tags (`sanitize_text_for_tts_engine`). The GUI **Chat** tab may still show tags depending on the same debug flag (see **`Orchestrator._feedback_debug_mode()`** / **`widget.py`**).

### LLM — thinking / reasoning (llama-server) (Alpha 0.28.4)

- **Defaults:** `App/configs/defaults.yaml` → **`llm.thinking: off`**, **`thinking_budget: 512`** (used when thinking is enabled). Mapped to **`llama_server_reasoning_budget()`** in **`App/services/llm/__init__.py`**: **off** → **`--reasoning-budget 0`** on the managed server; **on** → positive cap or **-1** (unlimited) from GUI Performance (“Unlimited”).
- **API split:** **`LlamaCppServerLLM._parse_chat_completion_choice`** (`llamacpp_server.py`) prefers assistant text in **`message.content`** and optional **`reasoning_content`** when the backend separates them (e.g. **`--reasoning-format deepseek`**). **`Orchestrator`** stores reasoning for console/UI paths that opt in.
- **Leak safety net:** **`Orchestrator._strip_thinking_blocks`** (static helper) removes **`<thinking>…</thinking>`**, **`<reasoning>…</reasoning>`**, **`<redacted_thinking>…</redacted_thinking>`** with multiline regex, plus unclosed open tags — applied to LLM output on the main pipelines (Answer, Help, summaries, translations, etc.) so reasoning templates do not leak into user-facing text when the server merges fields.

### Feedback — debug mode (Alpha 0.28.4)

- **Config:** **`feedback.debug_mode`** in merged config (`defaults.yaml` default **false**). **GUI:** Settings → **Advanced** → **Debug mode** toggle; persisted with other settings.
- **Effects (high level):** Verbose LLM payload logging; **PreviousAnswersSummary** included in **Alt+A** external injection when enabled; **TTS bracket tags** visible in console finalization and related UI paths; dev plugin **no longer** gates these behaviors (dev stays for **tier / `strict_remote` / licensing** only).

---

## Batch Files Reference

### install.bat (v3.6)
- **Purpose:** One-time (or repair) portable setup — **does not** install system Python.
- **Critical fix:** `cd /d "%~dp0"` at top (correct working directory when launched from Explorer).
- **Embedded Python 3.11.9 (amd64):** Resolution order — `Assets\python-3.11.9-embed-amd64.zip` → `Data\Cache\` → download from **python.org**; legacy names `python-embed.zip` / zip in repo root supported; extract to **`Python\`**. Then **get-pip**, **`python311._pth`** edit.
- **tkinter:** `Assets\tkinter-3.11-embed.zip` extracted into `Python\` (embedded build has no tkinter by default). Section uses `goto` labels (not `( )` blocks — blank lines inside batch `(` `)` cause silent parse failures).
- **GPU detection:** Before heavy backend work: `nvidia-smi` (and helpers) to choose **NVIDIA** vs **Vulkan** vs **CPU**. **RTX 50xx:** may prefer **CUDA 13.1** or **12.4** zip set depending on **driver-reported CUDA** (`App\tools\driver_supports_cuda13.ps1`); on failure or older driver, fallback **12.4**.
- **Architecture / folders:** Creates `Data\Tools\` backends: at least **`nvidia-cuda-12.4`**, **`nvidia-cuda-13.1`** (when used), **`vulkan`**, **`cpu`** as needed; **`install_llama_backend.ps1`** downloads/extracts **llama.cpp** release zips (see `LLAMA_VER` in `install.bat`, e.g. b8188).
- **STT CUDA (NVIDIA):** Installs `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` with `ctranslate2` / `faster-whisper` for GPU Whisper. Non-NVIDIA: CPU STT wheels only — **Whisper does not use Vulkan** (upstream limitation).
- **llama-cpp-python:** Pinned wheel when step runs (CPU/NVIDIA path); **skipped** when backend is Vulkan-only (app uses **llama-server.exe**, not Python bindings).
- **VC++ portable:** If `Assets\vcredist-x64-portable.zip` exists, DLLs deployed into each backend folder under `Data\Tools\` and `Python\` for portable runs.
- **Shortcut:** `PerkySue.lnk` → launch batch; optional `PerkySue.ico` at repo root.
- **End:** May launch **`start.bat`** / PerkySue. **Whisper** weights download on **first app run**, not in `install.bat`. **Default GGUF** may download from GUI first-run (`installer_default_models.yaml`) — **Hugging Face**, not PerkySue servers for model files.

### start.bat (v2.4+)
- **Purpose:** Launch PerkySue (all tiers)
- **Console Unicode:** **`chcp 65001`**, **`set PYTHONUTF8=1`** before Python — pairs with **`App/main.py`** early UTF-8 configuration so startup logs and emoji render reliably in **cmd.exe**.
- **Batch safety (Alpha 0.28.4):** Inside **`if ( … )`** blocks, **do not** end an **`echo`** line with a trailing **`\`** (cmd treats it as line continuation and merges the next line into the command, corrupting the rest of the script). Avoid Unicode **arrows (`→`)** in **`echo`** lines inside parentheses (can be confused with **`>`** redirection). Use ASCII **`-`** in user-facing echo/REM lines when in doubt.
- **GPU detection:** NVIDIA path selects **`nvidia-cuda-12.4`** in this launcher (compatible RTX 20xx through 50xx for **llama-server**); AMD/Intel → **vulkan**; else **cpu**
- **Actions:**
  1. `taskkill` orphaned **`llama-server.exe`** (best effort)
  2. Detect GPU / backend folder name; verify **`Data/Tools/<backend>/llama-server.exe`**
  3. Copy backend into **`Data/Tools/active/`**
  4. Set env: **`HF_*`**, **`PERKYSUE_DATA`**, **`PERKYSUE_BACKEND`**, **`PERKYSUE_GPU_NAME`**
  5. Optional pip dependency check / install
  6. Launch **`Python\python.exe App\main.py`** — **llama-server** lifecycle is managed from Python, not pre-launched here

### App/tools/download_model.py (optional CLI)
- **Purpose:** Interactive LLM model downloader for development/support; the GUI Recommended Models flow is the primary path for users. Same catalog as the GUI.
- **Catalog:** Model list is read from `App/configs/recommended_models.yaml`. Add or edit models there; the console menu and (when wired) the GUI Recommended Models section both use it.
- **Actions (download_model.py):**
  1. Load catalog from `recommended_models.yaml`
  2. Show numbered menu (name, params, size_hint, description)
  3. Option "Custom HuggingFace download" for any repo/filename
  4. Download via `huggingface_hub.hf_hub_download` to `Data/Models/LLM/`

---

## Version History

The canonical **full** changelog (all releases) is [`CHANGELOG.md`](CHANGELOG.md) at the repo root. Below is a technical summary kept in sync; the README shows **only the latest** release notes.

### Beta 0.28.8 (April 2026) — shipped
- **Chat + Help GUI:** Pill-style Chat/Help navigation, unified input bar, refreshed bubbles and model line (`widget.py` and related).
- **Status model:** **`generating`** during LLM and TTS prep (avoids **Ready** before speech); **`speaking`** during playback (`_tts_speaking_poll`); i18n **`common.statuses.*`** (16 locales).
- **Avatar ring:** Real-time PCM-driven outer ring — TTS output meter + microphone path while listening (`TTSManager`, `AudioRecorder` callbacks); smoothing + tick cadence tuned in `widget.py`.
- **TTS sanitization:** **`strip_basic_markdown_for_tts`** in **`tag_sanitize.py`** removes Markdown list markers, emphasis, stray asterisks, etc., before synthesis.
- **Docs / assets:** README banner **`App/assets/Github/banner.webp`**; `APP_VERSION` **Beta 0.28.8**; KB + locale `window_title` aligned.

### Beta 0.28.7 (April 2026) — shipped
- **Skins / disk layout:** **`Data/Skins/<Character>/<Locale>/`**, config **`Character/Locale`**, **`App/utils/skin_paths.py`**; TTS refs **`voice_ref.wav`**, **`audios/voice_sample/voice_sample.wav`**, transcripts **`voice_ref.txt`** / **`voice_sample.txt`**; **Appearance** filter defaults to **UI language**.
- **OmniVoice portable (Windows):** **`windows_ffmpeg_dlls.py`**; **`install_ffmpeg_shared_windows.bat`**; **`torchaudio` WAV patch** (**soundfile**) in **`omnivoice_tts.py`**; **`ref_text` / `ref_transcript`** when no dummy prefix; installer log hint (**`installer.py`**).
- **Docs / version:** `CHANGELOG.md`, README, this file, **`GETTING_STARTED.md`**, **`TROUBLESHOOTING.md`**, KB + `perkysue_kb.md`, `APP_VERSION` was **Beta 0.28.7** (superseded by 0.28.8).

### Alpha 0.28.4 (April 2026)
- **Launcher / CMD:** UTF-8 bootstrap (`main.py`, `start.bat`); **`start.bat`** fixes for **`if ()` / `echo`** (no trailing `\`, ASCII-safe echoes); **`PerkySue Launch.bat`** aligned.
- **Product debug:** **`feedback.debug_mode`** + Settings → **Advanced**; dev manifest decoupled from debug UX.
- **Alt+A / stop:** Injection labels from **`chat.user_fallback`** / **`chat.sender_name`**; summary only if debug; **`request_cancel`** + Alt+Q / avatar stop **TTS** (`tts_loading` + playback); **`regular.tts_stopped`** i18n.
- **LLM thinking:** Default **`thinking: off`**; **`_strip_thinking_blocks`**; server parser **`reasoning_content`** split.
- **TTS display:** **`strip_all_bracket_tags_for_display`** unless debug.

### Alpha 0.28.3 (April 2026)
- **TTS + PyTorch CUDA:** `pytorch_cuda.py` (cu128/cu124 index, Blackwell detection, GPU matmul probe); `manager.py` Voice-tab offer; `installer.py` CUDA pip without in-process torch purge — subprocess verify + **restart app**; `widget.py` no post-pip engine reload; root **`install_pytorch_cuda_cu*.bat`**; i18n **`voice.pytorch_cuda.*`**.
- **Docs / version:** `APP_VERSION` **Alpha 0.28.3**.

### Alpha 0.28.2 (April 2026)
- **TTS ↔ LLM:** `App/configs/tts_prompt_extension.yaml` + `App/services/tts/prompt_extension.py` — when Pro TTS is on, **Answer** and **Help** system prompts gain an appendix (engine-specific audio tag palette + speaking personality). Optional per-skin **`tts_personality.yaml`**. `get_help_effective_system_prompt()` includes the same block as the live Help call. `Orchestrator._append_tts_llm_extension` documents all call sites and paths intentionally excluded.
- **OmniVoice:** Second shipped engine under `App/services/tts/omnivoice_tts.py` (engine switch in Voice tab).
- **Docs / version:** `APP_VERSION` **Alpha 0.28.2**.

### Alpha 0.28.1 (April 2026)
- **Commerce URL base (internal staging):** `App/gui/widget.py` — `_perkysue_site_base_for_commerce_urls()`; when **`PERKYSUE_LICENSE_API`** is set, **`/pro`** opens on that origin so checkout + webhooks and **`GET /check`** share one Worker/KV.
- **Git:** **`start-against-staging.bat`** gitignored; committed **`start-against-staging.bat.example`** (placeholder URL).
- **Docs / version:** `CHANGELOG.md`, KB headers, `APP_VERSION` **Alpha 0.28.1**.

### Alpha 0.28.0 (April 2026)
- **First-run default LLM:** `App/configs/installer_default_models.yaml` + `App/utils/installer_default_model.py` — NVIDIA tier rules use **total VRAM** (`vram_total_mb` from `nvidia-smi`), not free VRAM, so large GPUs are not downgraded to 2B when VRAM is already partially allocated. If **`PERKYSUE_BACKEND`** is unset, **`_effective_backend_for_defaults()`** probes **`get_nvidia_smi_snapshot()`** before applying the CPU fallback.
- **Docs / version:** `CHANGELOG.md`, KB headers, `APP_VERSION` **Alpha 0.28.0**.

### Alpha 0.27.9 (March 2026)
- **Release rollover:** 0.27.8 is closed; labels and docs moved to 0.27.9.
- **Licensing reliability (app + Worker):** Trial-to-paid UX is now deterministic (paid Stripe takes priority for banner/status/Manage), and /check renewal mapping now surfaces Stripe period end in stable fields (expires_at/current_period_end) so Plan Management can show real renew dates for active paid subscriptions.
- **Trial OTP (Sprints A–B shipped):** Worker exposes **`POST /trial/start`**, **`/trial/resend`**, **`/trial/verify`** (Brevo OTP, KV rules, newsletter opt-in on verify). App: **`Orchestrator.trial_start` / `trial_resend` / `trial_verify`**, wizard in **`widget.py`**, local **`trial.json`** + **`trial_consumed.marker`** on refusal. **Sprints C–D** (cache tier, GUI, i18n) closed in app; **Sprint E** = manual QA checklist (`CHANGELOG.md`). WAF: include **`/trial*`** with link-subscription and `/check` if Python traffic is challenged.

### Alpha 0.27.7 (March 2026)
- **Signed license cache:** Worker may attach **`license_payload`** + **`license_signature`** (Ed25519, canonical JSON) to **`GET /check`** when `LICENSE_SIGNING_PRIVATE_KEY` is set. App verifies with embedded **`LICENSE_PUBLIC_KEY_PEM`** in **`utils/license_signature.py`** before `_read_valid_stripe_license()` returns Pro; **`cryptography`** dependency. **Legacy:** missing signature fields → same trust as pre-0.27.7 until next successful `refresh_license_from_remote()` **unless** `stripe_license_signed_once.marker` exists (then legacy `sub_*` rejected until marker removed — see orchestrator). **Marker:** written when a signed payload is saved or verification is `ok`; **deleted** when a successful refresh receives no signature (recovery if Worker stops signing).
- **Behaviour (validated):** Tamper signed fields online → `/check` overwrites `license.json`. Offline tamper → Free until refresh. Back online, **no restart** required for tier recovery when `refresh_license_from_remote()` runs (focus, Settings, **`initialize()`** if `license.json` exists — 12 s timeout).
- **Support / logging:** `utils/stripe_license_file.py`, `diagnose_license.py`, `tools/generate_license_signing_keys.py`, `tools/derive_license_public_from_private.py`; `describe_pro_gate()`. Console WARNING for **`bad_signature`** distinguishes **offline edit (expected)** vs **possible key mismatch** (`TROUBLESHOOTING.md`).
- **Offline:** Reject signed Pro if `issued_at` + 30 days exceeded or `expires_at` (period end) passed (`OFFLINE_MAX_DAYS`).
- **Docs / version:** `CHANGELOG.md`, `TROUBLESHOOTING.md`, `APP_VERSION` **Alpha 0.27.8**.

### Alpha 0.27.6 (March 2026)
- **Worker:** `POST /billing-portal` → Stripe Customer Portal session URL from KV `install:*` + subscription customer. `GET /check` loads Stripe subscription when linked; response includes period end / cancel-at-period-end; KV refresh; structured logging on Stripe errors.
- **App:** `request_billing_portal_url()` / `_plan_open_billing_portal`; `refresh_license_from_remote()` + `license.json` writes include `install_id` aligned with `install.id`; optional merge of prior `expires_at` when `subscription_id` unchanged. Plan UI: renewal strings, `portal_manage_unavailable` (16 locales).
- **HTTP client (licensing API):** `_license_http_headers()` on `GET /check`, link-subscription `POST`, and **`POST /billing-portal`**; WAF **Skip** should include **`/billing-portal`**.
- **Docs / version (at ship):** `CHANGELOG.md`, KB headers, `APP_VERSION` **Alpha 0.27.6**.

### Alpha 0.27.5 (March 2026)
- **Relink Pro (Worker + app):** `POST /link-subscription/start|resend|verify` on perkysue.com Worker; Customer Search + latest active/trialing Pro sub; Brevo OTP; KV `install:*` / `link_tomb:*` / delete `sub:*` when linking web-only checkout. App: `Orchestrator.link_subscription_*`, `refresh_license_from_remote()`; Settings wizard `_open_link_subscription_wizard`; i18n `settings.plan_management.link_subscription.*` (16 locales). **`GET /check?id=&host=`** sets `bound_hostname` once when active.
- **HTTP client (licensing API):** `_license_http_headers()` adds a Chrome-on-Windows–style `User-Agent` with `PerkySueDesktop/<version>` and `X-PerkySue-Client: desktop` on `POST` (link-subscription, billing-portal) and `GET /check` to reduce Cloudflare WAF blocks on Python `urllib`; site ops: WAF **Skip** rules on `/link-subscription`, `/check`, `/trial`, `/billing-portal`.
- **Settings UI:** Plan management three-card row uses `_PLAN_ROW_THREE_COL_PADX = ((0, 8), (4, 4), (8, 0))` (same card width as uniform `padx=4`, +4 px gutters); relink CTA `pady=(4, 0)`; Pro checkout row uses the same column padding. Wizard errors: `_plan_link_api_user_message()` merges `message`/`error`/`detail` and nested Stripe-style errors; falls back to generic + `(HTTP status)` when the body is unhelpful.
- **Docs / version (at ship):** `CHANGELOG.md`, KB headers, `APP_VERSION` **Alpha 0.27.5**.

### Alpha 0.27.4 (March 2026)
- **`install.id`:** `App/utils/install_id.py` — `get_or_create_install_id()` ensures `Data/Configs/install.id` (UUID v4) exists; called from `App/main.py` after logging init. Used for Stripe return URLs and Worker KV. See `CHANGELOG.md` **Alpha 0.27.3** for the full documentation list.
- **Header banner by plan:** `Orchestrator.get_header_banner_spec()` + `common.header_banner.*` in all locale YAMLs; `widget.py` `_compute_header_banner_text()` / `_refresh_header_banner_if_idle()`. Trial consumed = local marker / config / expired `trial.json`; activation and refusal come from **`/trial/*`** responses (0.27.8+).
- **Header tips:** Alt+A Pro vs Free tip shortened across **16** locales.
- **Recommended Models UI:** White param count, ⭐ ratings, wrapped long names, two-column tooltips with full catalog fields (see `CHANGELOG.md` **Alpha 0.27.4** — merged release note).
- **Docs / version:** `README.md`, `CHANGELOG.md`, KB headers, `APP_VERSION` **Alpha 0.27.4**.

### Alpha 0.27.3 (March 2026)
- **Milestone:** Licensing identifier groundwork + documentation alignment (`install_id` lifecycle, `GETTING_STARTED.md`, `PRIVACY.md`). Closed before the **0.27.4** public label; detail in `CHANGELOG.md`.

### Alpha 0.27.2 (March 2026)
- **Chat vs Help (orchestrator):** In-app redirect from **Answer** when `_is_perkysue_app_question()` matches, then `_llm_intent_should_redirect_to_help()` (HELP/NOHELP); `_should_force_help_redirect()` for PerkySue + machine/LLM sizing. `_on_hotkey_toggle(..., from_chat_ui=True)` from Chat mic threads `from_chat_ui` through `_record_and_process` → `_process_audio_impl`.
- **Help params:** `utils/nvidia_stats.get_nvidia_smi_snapshot()` adds `system.gpu.live` to `_collect_help_params()` when `nvidia-smi` succeeds. Help mode `modes.yaml` instructs the LLM to prefer **Current settings** for hardware and to treat NVIDIA VRAM as relevant for local LLM.
- **Help KB truncation:** For `max_input_tokens` ≤ 2048, KB compact file truncated at **1350** chars (see `_build_help_system_prompt()`).
- **Free vs Pro Ask:** `is_effective_pro()` gates `_build_llm_input_with_context()` — Free has **no** prior Q/A in the LLM prompt (standalone questions); Pro gets rolling history + `PreviousAnswersSummary`. UI copy: `chat.free_answer_notice` (**multi-turn context** + Smart Focus = Pro).
- **Docs / version (at ship):** `README.md` (Free local Chat vs Pro), KB headers, `APP_VERSION` **Alpha 0.27.2**.

### Alpha 0.27.0 (March 2026)
- **Internationalization baseline:** PerkySue UI is now international with 16 locale files mapped to the 16 flag selectors (`us`, `gb`, `fr`, `de`, `es`, `it`, `pt`, `nl`, `ja`, `zh`, `ko`, `hi`, `ru`, `id`, `bn`, `ar`).
- **English locale split:** US and UK are no longer `en_variant`; they are now explicit locale files (`App/configs/strings/us.yaml`, `App/configs/strings/gb.yaml`) mapped from `us.png` and `uk.png`.
- **Docs:** `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, and KB snapshots aligned to 0.27.0.
- **Ask — `PreviousAnswersSummary` (rolling Q/A summary):** Generated by `_create_previous_answers_summary()` in `App/orchestrator.py` (mode `summarize_qa`), **not** by the same `max_output_tokens` path as normal Ask replies. The completion budget for that call is **`min(1024, llm.max_tokens)`** (legacy key); **`max_output_tokens` from Settings is not wired to this step**, so a user value such as 8100 does not apply here. **The 1024 cap limits generated (output) tokens only** — the long prompt (previous summaries + latest Q/A block + instructions) still counts toward **Max input** / shared `n_ctx`. If a stored summary ends mid-sentence, the usual cause is **output** hitting that cap (`finish_reason: length`), not the user’s global max-output setting.

### Alpha 0.26.7 (March 2026)
- **Changelog:** `CHANGELOG.md` holds full release history; `README.md` Changelog section shows latest alpha only (see release workflow).
- **GUI i18n:** Sidebar note, Patreon strings, Default skin label, `modes.registry` (including `message` / `social`), Shortcuts table order; French copy (nav **Prompts**, **Éditer**, max listen duration label). About use-cases footer styled like Smart Focus body text.
- **Docs:** Release notes updated; KB / README / widget title bumped to 0.26.7.

### Alpha 0.26.6 (March 2026)
- **Docs:** Global hotkeys (Windows), stop/cancel (`Alt+Q` / `RegisterHotKey`, AltGr, avoid `alt+escape`) documented across README, ARCHITECTURE, KB, About, YAML. **Repo:** inline comments under `App/` in English (documentation rule).
- **GUI i18n (initial pass):** `settings.save_sidebar_note`, `settings.appearance.default_skin`, `about.support_patreon_label`, `modes.registry.*` for Shortcuts + Prompt Modes. See the GUI i18n documentation section in this repo.

### Alpha 0.26.5 (March 2026)
- **Nav Chat indicator (⚠):** When Chat tab is active or hovered, the warning triangle uses the same background (SEL_BG) as the menu; transparent when another tab is active. `_update_chat_nav_indicator()` and `_apply_hover()` updated.
- **Alt+A injection:** Format **● User:** question, **✦ PerkySue:** answer; blank line between them. Bullets in `_format_answer_injection()`.

### Alpha 0.26.2 (March 2026)
- **Settings — Plan management in-place updates:** Plan cards now update in-place (no destroy/recreate), preventing CTkScrollableFrame cascade relayout glitches in Settings (Appearance/Recommended Models stay stable).
- **Settings — Save & Restart behavior:** Switching plan keeps `Save & Restart` visible without forcing scroll to the bottom.
- **Shortcuts — Free policy enforced:** In Free tier, only `transcribe` (Alt+T) and `help` (Alt+H) remain editable; all other shortcut edits are disabled in UI and blocked by handler.
- **Prompt Modes — downgrade reset:** On plan downgrade to Free, `identity.name` is cleared and `stt.whisper_keywords` are truncated to 3 entries, with live STT keyword reload.
- **Prompt Modes — plan keyword limits:** Limits are enforced as Free=3, Pro=10, Enterprise=unlimited, with Help redirection on overflow.

### Alpha 0.25.3 (March 2026)
- **Chat — PerkySue / app questions → Help tab:** Notice in Chat tab: "Questions about PerkySue or the app? Use the Help tab." Ask mode system prompt instructs the LLM to redirect questions about PerkySue, its creator, or the application to the Help tab; no answering such questions in Chat.

### Alpha 0.25.2 (March 2026)
- **First Language (Settings → Performance):** New setting (identity.first_language). Options: Auto + many languages (European, Asian: ja, zh, ko, hi, th, vi, id, ms, bn, ta, te, mr, ur, my, km, lo, ne, si, pa, gu, kn, ml, etc.). Used for LLM-generated greetings.
- **LLM-generated greetings:** Greeting requested only when user opens Chat or Help tab. Two distinct greetings: Chat = welcome + engagement question; Help = welcome + "does [name] need help?". Cache per tab; "New chat" clears Chat greeting cache and requests a new one. get_greeting_from_llm(lang_code, user_name, context="chat"|"help") in orchestrator. While loading, widget shows a small indeterminate **ACCENT (purple) bar** in the messages area (no avatar “Processing” for greetings).

### Alpha 0.25.1 (March 2026)
- **Ask context:** Last **4 Q/A** kept in context (was 8); summary every **4 exchanges** (was 8). Constant `_answer_context_n_qa = 4` in orchestrator; reduces context usage.
- **Milestone 0.25.0:** Full Help tab (same layout as Chat, welcome 👋); Help prompt plan-aware (no sign-up pitch when user has Pro); version set to 0.25.0.
- **Alt+H (Help) — free plan, no injection:** Help mode available on free plan; does not inject into focused document (answer only in app Help tab). Alt+I, Alt+C, etc. require Pro. Help chat UI (conversation in Help tab) planned later. Orchestrator: _collect_help_params(), _load_help_kb_content(tier), _build_help_system_prompt(); KB truncated when max_ctx ≤ 1024. Three KB files (kb_help_2048/4096/8192.md) document plans, available values (Max input 1024–16384 + Auto, Max output 256–8192, STT model/device).
- **Chat — finish_reason:** LLMResult gains `finish_reason` (OpenAI / llama-server). When `finish_reason == "length"`, generation was stopped by token limit; used for truncation detection instead of last-char heuristic. llamacpp_server and llamacpp_llm pass finish_reason and completion_tokens.
- **clear_answer_context():** Orchestrator method clears `_answer_history` and `_answer_summaries` in place; "New chat" calls it so the next Alt+A sends no prior Q/A.
- **Request size log:** Ask mode logs `Alt+A request size: system=X chars, user=Y chars → ~Z input tokens` to confirm no double send (1024 = input + output being generated).
- **Chat reset indicator:** When context or max-output limit is hit and the user is not on the Chat tab (e.g. Alt+A from Word), widget shows a ⚠ label to the right of the "Chat" nav item and, when the user opens Chat, makes the "New chat" button blink red a few times. _set_chat_reset_indicator_if_outside_chat() called from orchestrator after the limit blink; _update_chat_nav_indicator(), _start_chat_new_btn_blink(); clearing on "New chat" click.

### Alpha 0.25.0 (March 2026)
- **Chat — context window shared (n_ctx):** In llama.cpp (and many backends), the context window is **shared** between prompt and completion (prompt_tokens + completion_tokens ≤ n_ctx). When the reply is cut off at ~300–400 tokens and the server reports 1024 tokens **total**, the cause is the **context limit** (Max input), not "max output". Orchestrator now computes `context_full = (max_ctx > 0 and total_used >= max_ctx)`. When truncated and context_full: chat shows `document_injection.chat_context_limit_reached` ("Context limit (X) reached — input and output share this budget. Increase 'Max input'…") with actual value and suggestion (2048, 4096…); blink uses same message. When truncated and not context_full: real output limit → chat_max_output_reached + critical.max_output_tokens_reached with actual max_output and suggested. Empty reply in Ask → context message + blink. LLM request uses `max_output_tokens` from config (user's 8192 sent). Log: `llama-server: X tokens (total)` in llamacpp_server.py. header_alerts.yaml: chat_context_limit_reached, chat_max_input_reached, chat_max_output_reached; critical.max_input_context_reached, critical.max_output_tokens_reached (with placeholders).

### Alpha 0.24.3 (March 2026)
- **Chat page (full):** Cascade display (user bubble first, then LLM bubble). Mic button runs Ask in a background thread so status shows Listening and mic turns red; no double STT/LLM sounds. No injection of LLM result into chat type-in when target is PerkySue (only Alt+T injects into type-in); "Ask in chat" notification. Max output token limit: when reply is truncated or empty with 1024 tokens reported, chat bubble shows "Increase Max output" message and header bar blinks 3× (critical.max_output_tokens_reached). Empty reply without token info → generic "Reply was empty". LLM server: handle null content, total_tokens from prompt_tokens+completion_tokens; LLMResult.completion_tokens for truncation detection. Alert strings in header_alerts.yaml (chat_max_output_tokens, chat_empty_reply).
- **Chat (from 0.24.2):** Sidebar Chat/Help → one page, two tabs. Chat = Alt+A history, token bar, New chat/Save log, input + mic + send; Alt+A opens Chat tab; user name from identity.name or "User"; markdown markers stripped in bubbles; responsive wraplength 300–500 px.

### Alpha 0.24.2 (March 2026)
- **Chat page:** Sidebar **Chat** and **Help** open one page with tabs (Chat = Alt+A Ask conversation UI; Help = placeholder). Token bar, message list from Ask history, input area. Alt+A can switch to Chat tab.
- Notifications: Patreon hidden for all tips/alert; alerts cancel tips; recording_no_audio/recording_too_short → Ready + header only.

### Alpha 0.24.0 (March 2026)
**Shortcuts Manager:** Nouvelle page dans la sidebar pour afficher et éditer tous les raccourcis. Deux colonnes par mode (Hotkey Alt et Hotkey AltGr), bouton Edit par raccourci, détection des conflits, bouton Restore Default Shortcuts. Pause des hotkeys globaux pendant l’édition pour éviter que le raccourci en cours d’édition ne se déclenche. Capture par keycode/keysym pour AltGr correct.
**Header tips au démarrage:** Rotation des tips dans la barre de notification (implémentation de _schedule_tip_cycle et _show_next_tip).

### Alpha 0.22.4 (March 2026)
**Prompt Modes — Test Input samples:** Clic sur un sample vide (EN2, FR1, FR2) met à jour le pill actif (allumé en or) et vide la zone de texte ; Save enregistre bien dans le slot sélectionné.

### Alpha 0.22.3 (March 2026)
**Appearance (Settings):** Bordure dorée uniquement sur la photo (avatar), pas sur la cellule ; pas de jump au clic (libellé inchangé).

### Alpha 0.23.2 (March 2026) — previous
**Custom prompts (Alt+V, Alt+B, Alt+N):** Trois modes personnalisables custom1, custom2, custom3 (Custom prompt 1/2/3). Définis dans `App/configs/modes.yaml` avec raccourcis dans defaults (alt+v, alt+b, alt+n). L'utilisateur édite le system_prompt et les test_inputs dans Prompt Modes comme pour les autres modes.
**Sauvegarde des test inputs:** À chaque Save (prompt), la phrase dans la zone Test input est enregistrée dans la cellule active (EN1/EN2/FR1/FR2 — celle du dernier clic sur un bouton sample). Les quatre cellules test_inputs sont persistées dans `Data/Configs/modes.yaml` avec le system_prompt.
**Règle UX (erreur LLM → injection d'alerte):** Si le LLM échoue (ex. 400 Bad Request quand Max input est trop petit), PerkySue injecte une alerte **⚠️** au curseur (à la place du résultat attendu) + notification header (et son `llm_error` optionnel), pour éviter le “rien ne se passe”.

### Alpha 0.23.0 (March 2026)
**Conversation continue (Alt+A) :** PerkySue permet une **conversation à plusieurs tours** avec le LLM chargé. Historique Q/R conservé en mémoire ; tous les 8 échanges, un résumé de la conversation est généré via le mode **summarize_qa** (Summarization of Q&A) et réinjecté dans le contexte. Contexte envoyé au LLM = tous les résumés + les 8 derniers Q/R ; la question courante est placée en premier dans le message user pour une meilleure prise en compte. Certains modèles sont mieux adaptés à ce type d'échange : le catalogue `App/configs/recommended_models.yaml` peut marquer les modèles conseillés avec `good_for_qa_conversation: true`. Config LLM : **max_input_tokens** et **max_output_tokens** remplacent `n_ctx` / `max_tokens` pour clarifier contexte vs réponse.

### Alpha 0.22.2 (March 2026) — previous
**Prompt Modes tab (widget.py):** Section 3 enrichie avec des **test inputs par mode**. Chaque mode LLM dispose désormais de `test_inputs.EN1/EN2/FR1/FR2` définis dans `App/configs/modes.yaml` et surchargés par `Data/Configs/modes.yaml`. Dans la zone de test, la barre « Test input (samples) » affiche 4 pills EN1 / EN2 / FR1 / FR2 (même style que les filtres backend) qui injectent le sample correspondant dans la textarea. Si la zone est vide à l’ouverture ou avant Run Test, le premier sample non vide (EN1 → EN2 → FR1 → FR2) du mode est injecté automatiquement. Les objets `Mode` exposent désormais `test_inputs` pour que la GUI lise ces valeurs depuis les YAML (source de vérité éditable au bloc-notes).
**Performance Settings (widget.py + orchestrator.py):** Nouveau réglage **Max recording duration (s)** dans la section Performance. La valeur est sauvegardée sous `audio.max_duration` et transmise à `AudioRecorder(max_duration=...)`. Si non configurée, la durée par défaut dépend du backend et du modèle STT : sur CPU/Vulkan, 120 s pour `small` et 90 s pour `medium`; sur NVIDIA (CUDA, RTX 50xx inclus), 180 s par défaut. Les utilisateurs peuvent augmenter jusqu’à 240 s via l’OptionMenu. Le timer de ~2 minutes est donc explicitement un garde‑fou de PerkySue, pas une limite Whisper.
**Recommended Models (widget.py):** La section **Recommended Models** vérifie désormais la présence réelle des fichiers dans `Data/Models/LLM/` au chargement. Si la config pointe vers un `llm.model` supprimé manuellement, la valeur est nettoyée (`llm.model` vidé, dropdown LLM mis à jour) et la carte repasse en état « Get » au lieu de « Current Model ». Le statut « current » n’est attribué qu’aux modèles dont le `.gguf` est effectivement présent, ce qui empêche les modèles fantômes dans l’UI après suppression sur disque.

### Alpha 0.22.1 (March 2026)
**Prompt Modes tab (widget.py):** New page `_mk_modes()` with three sections: (1) **Whisper STT Keywords** — plan-based limits (Free 3, Pro 10, Enterprise unlimited), merged with system terms for Whisper, immediate save and `reload_stt_keywords()`; (2) **Identity & Preferences** — Your Name → `identity.name`, `{user_name}` in LLM prompts (locked in Free); (3) **Prompt Modes (per shortcut)** — one card per LLM mode with editable system_prompt, Edit/Save/Cancel/Test, live test box (Run Test, stt_stop sound from Default skin), language label (Whisper or config). Work in progress.
**Console tab (widget.py):** Page Console structurée en **4 sections** : (1) **Pipeline Status** (deux cards : ligne modèles actifs avec pastilles STT/LLM + 5 barres de ressources CPU/RAM/GPU/VRAM/Temp générées en PIL, 130×38 px, couleurs par métrique avec dégradé vert→ambre→rouge selon l’usage, texte label en bas-gauche et valeur en haut-droite, polling toutes les ~1s via `psutil` pour CPU/RAM et `nvidia-smi` pour GPU/VRAM/Temp quand NVIDIA dispo) ; (2) **Transcription Controls** (card horizontale avec boutons Start/Abort/Save Log + cellule Volume contenant bouton mute et canvas equalizer 16 barres, clic/drag = volume 0–100%) ; (3) **Finalized - Temporary Logs** (CTkScrollableFrame, entrées ajoutées après injection via `append_console_finalized_entries`, cellules type log avec séparateur 1 px + marges verticales pour éviter l’effet “collées”, wraplength dynamique avec marge droite suffisante) ; (4) **Full Console** (card avec CTkTextbox, logs temps réel, pas de `print` en double). **Design rules** : notifications header (blink 3× pour alertes importantes, 1,5s pour feedback simple), log-cells réutilisables (séparateur/marges/paddings fixés), sub-scroll identique à Appearance (wheel sur la zone scrollable avant la page).

### Alpha 0.21.6 (March 2026)
**GUI (widget.py) — 768px support:** Default geometry `820×700`, min height `560px` so the window fits on 768px-tall screens. Left sidebar (avatar, status, nav, Save & Restart) lives inside a `CTkScrollableFrame`; scrollbar is styled to match `SIDEBAR` (discrete). Mouse wheel scrolls the sidebar so the Save button remains reachable on small screens.
**GUI (widget.py) — Performance Settings:** New `Silence Timeout (s)` dropdown (🎙️) persisted to `audio.silence_timeout` in `Data/Configs/config.yaml`. Controls how many seconds of silence `AudioRecorder` waits before auto-stopping in toggle mode.
**Audio (utils/audio.py) — device listing:** `AudioRecorder.list_devices()` now marks the default input device (`is_default`) so diagnostics can detect when Windows routes audio through a virtual device (Iriun, “Mappeur de sons…”) instead of a physical microphone.
**Orchestrator (orchestrator.py) — microphone diagnostics:** During startup, if the default input device name looks virtual (Iriun/Webcam/Mappeur/Virtual) and a physical mic (Realtek/Microphone) is also present, `mic_warning` is set. The GUI uses this to open Windows System → Sound automatically and to show a detailed header alert.
**GUI (widget.py) — header alert for virtual mic:** On GUI init (and when status becomes `no_speech` with `mic_warning` present), the header shows a blocking-style banner text such as “Windows uses a virtual microphone (e.g. Iriun Webcam). Open System > Sound and set your hardware mic (e.g. ‘Réseau de microphones (Realtek)’) as input.” and opens `ms-settings:sound` on Windows to help the user fix the issue.
**GUI (widget.py) — critical microphone dialog:** Modal CTkToplevel "Microphone issue detected" with title "Microphone configuration problem", message (wraplength 400), single OK button (ACCENT). Shown at startup when `mic_warning` and when recording-failure messages are shown. Fixed size `460x220`, non-resizable. Positioned relative to the main window using a shared geometry rule: horizontally shifted left to **triple** the empty space on the right (`x` based on the main window center, then clamped to stay ≥ 20 px from the screen left edge), and vertically offset ~52 px below the top of the main window.
**Orchestrator (orchestrator.py) — console triple warning:** At end of `run()`, if `mic_warning` is set, the same microphone warning is reprinted at the bottom of the console (50 `!`, message, 50 `!`).
**Orchestrator (orchestrator.py) — No Sound vs. recording errors:** `_process_audio` now receives the actual recording duration. If Whisper returns empty text and the duration is significantly shorter than `Silence Timeout`, PerkySue treats this as a recording error (microphone / input problem) instead of a simple “no_speech” case, sets status `error`, and shows an explicit message. `No Sound Detected` is now reserved for recordings long enough to plausibly reflect user silence.

### Alpha 0.21.5 (March 2026)
**install.bat (step [5/6]):** For backends other than CPU and NVIDIA (e.g. Vulkan/AMD/Intel), llama-cpp-python install is **skipped** with message "Skipping llama-cpp-python for backend vulkan (server mode only)" (or the detected backend name). Prevents pip from backtracking through dozens of versions and downloading hundreds of MB; PerkySue uses llama-server.exe for these backends. When step [5/6] does run (CPU or NVIDIA), version is pinned to `llama-cpp-python==0.3.16` to avoid resolver backtracking.
**App/services/base.py:** New file re-exporting `STTProvider` and `TranscriptionResult` from `services.stt.base`. Fixes `ModuleNotFoundError: No module named 'services.base'` when `services/__init__.py` imports from `.base` (e.g. on some deployment copies).
**GUI (widget.py):** `_notify(message)` added for avatar-click feedback (stop recording / cancel processing); shows message in header title then restores normal title after 3s.

### Alpha 0.21.4 (March 2026)
**About tab (GUI):** New section "Why PerkySue exists" before How It Works, with key messages (accent/gold bold), grey prose, and closing line "Your voice stays yours." Comparison block renamed to "PerkySue vs. Competition." Other AI use cases: shorter subtitle ("Each mode works as a voice prompt — here are a few examples"); prompt/result lines use responsive labels (no truncation); prompt text in white. Design: prose TXT2, key phrases ACCENT/GOLD bold.
**Footer (GUI):** Discord button added next to GitHub; both open in browser (Discord: https://discord.gg/UaJHEzFgXy). Logos loaded via PIL with aspect-ratio-preserving scale (max height 24px); compact buttons (height 32), no fixed 320×80.
**Docs:** README aligned with About (Why PerkySue exists with bold key lines, PerkySue vs. Competition, shorter Other AI subtitle). Discord link and "Community & support" section (announcements, support, contributors, bug reports). Version 0.21.4; changelog entry.

### Alpha 0.21.3 (March 2026)
**Sidebar nav (menu latéral):** Icon label has `height=45` so selected/hover background matches button height. Hover: bind Enter/Leave on both icon and button (not only container); on Leave use `after(50, _remove_hover_if_outside)` to avoid flash when moving between icon and label; cancel pending after on Enter. Selected and hover: icon and button both `fg_color=SEL_BG`, `text_color=TXT`. Performance Settings: STT Device icon padding (6px) for alignment. Appearance: bottom spacer in skin grid, margin 32px; selected skin gold border and gold label.

### Alpha 0.21.0 (March 2026)
**Model download UX (major):** Downloads run in background; notifications replace header title; progress bar on card without full grid refresh; tooltip closed on Get click.

### Alpha 0.20.3 (March 2026)
No sound / nothing transcribed: orchestrator sets status `no_speech` (not `error`) with messages "No Sound Detected — check your microphone" and "nothing heard". GUI: status label "No Sound Detected"; header shows temporary alert "Check Your Microphone" with dismiss × (same typography), restores the normal PerkySue header banner on click or status change. Email mode: CRITICAL - Language block in modes.yaml; skins LANG/Name; community audio guidelines. **GUI design (0.20.3):** Scrolls 4px from border; selected skin border = profile picture ring colour; Patreon +4px; Appearance filter pills; skin titles pady 2.

### Alpha 0.20.2 (March 2026)
VC++ portable: `Assets/vcredist-x64-portable.zip`; install.bat step 7b deploys DLLs to backend folders and `Python/` for ctranslate2. PerkySue Launch.bat, install.bat launches start.bat at end. STT initial_prompt (PerkySue, Sue).

### Alpha 0.20.1 (March 2026)
Previous alpha before 0.20.2.
IMPROVED: `install.bat` — after NVIDIA STT install, verify ctranslate2 CUDA; if missing, uninstall + reinstall ctranslate2. Step [5/6] llama-cpp-python: on failure, install scikit-build-core + cmake and retry; if still failing, warn and continue (server mode works without it). Message clarifies direct vs server mode.
IMPROVED: Config docs — only `Data/Configs/config.yaml` is read for user config; do not create `Data/Configs/defaults.yaml`.
IMPROVED: `whisper_stt.py` — Auto device uses non-empty list for ctranslate2 CUDA check; VRAM check (nvidia-smi) in Auto: use GPU only if free VRAM >= 2 GB.
IMPROVED: **Avatar (profile) button** — Inactive in Ready (cursor arrow, click no-op; fixes TypeError: is_recording is property not method). Active only in Listening (click = stop recording) and Processing (click = request_cancel, abort before LLM, "Traitement interrompu"). Cursor hand2 only when listening/processing.
NEW: `Orchestrator.request_cancel()` and `_cancel_requested`; pipeline checks cancel after STT and before LLM to skip inference when user interrupts.
IMPROVED: **GUI profile picture and Appearance** — Sidebar avatar outer ring colour matches event (Listening = green, Processing = orange, etc.); black spacing between image and ring preserved. Selected skin in Appearance: 5px border `#ffc410` directly on image. Lock icon 🔒 larger inside same badge for locked skins. Cursor hand2 on skin cards and Patreon button.

### Alpha 0.20.0 (March 2026)
install.bat v3.0 (GPU before packages, STT CUDA). GUI STT Device, avatar stop, whisper_stt messages, request_stop/stop_recording.

### Alpha 0.19.9 (March 2026) — last alpha before 0.20.0
NEW: Performance Settings — Max input (context) with Auto (backend-based) or 256–16384; Max output (tokens) with 256–8192.
NEW: Config `llm.n_ctx` (0 = Auto, else explicit context size); GUI saves both on Save & Restart.
IMPROVED: Settings labels "Max input (context)" and "Max output (tokens)" for clarity.
NEW: Skin selector — Teaser avatars from `App/Skin/Teaser/{Sue|Mike}/profile.png` when skin folder absent (circle never empty); lock icon 🔒 overlay bottom-left (pastille taille size/4, icône centrée et lisible); lock state dynamic from `Data/Skins/` presence; fallback to Default when saved skin folder removed.
IMPROVED: Skin selection = immediate save to config + `sound_manager.set_skin()` — no Save & Restart needed for skin change (audio and sidebar avatar update at once).
IMPROVED: Avatar circles and lock badge — render at 2x then resize with LANCZOS for smoother edges (anti-aliasing).
IMPROVED: Lock badge — larger background and icon, icon centered in background.
**Next:** Alpha 0.20.0.

### Alpha 0.19.8 (March 2026)
NEW: Recommended LLM models catalog — `App/configs/recommended_models.yaml` as single source for GUI and `download_model.py`; no more hardcoded model list in the downloader.
NEW: LFM2-350M (LiquidAI) in catalog — CPU-friendly, 8 languages (En, Fr, Es, De, Jp, Cn, Arabic, Korean).
NEW: Catalog fields `popularity`, `languages`, `languages_tooltip` for GUI (badge + tooltip on languages covered).
IMPROVED: Doc update policy — when important changes are made, update ARCHITECTURE.md and README.md.

### Alpha 0.19.7 (March 2026)
NEW: GUI widget (`App/gui/widget.py`) — CustomTkinter floating widget with 3 tabs
NEW: Header with `tk.Canvas` for true transparency + PIL gradient
NEW: Sidebar navigation with violet active bar and icons
NEW: Settings tab — Appearance section (skin dropdown as Patreon marketing tool, round PIL avatars)
NEW: Settings tab — Models section with 4 visual states (Get/Progress/Select/Current) via PIL
NEW: Settings tab — "Save & Restart" button with PIL glow effect
NEW: Shortcuts tab — 9 hotkeys read-only
NEW: Skin teaser in dropdown — Sue/Mike visible with lock icons, click → Patreon URL
NEW: `Assets/` folder with `tkinter-3.11-embed.zip` for Python embedded tkinter support
IMPROVED: `install.bat` v2.5 — extracts tkinter from `Assets/`, updates `python311._pth`
IMPROVED: `install.bat` — `cd /d "%~dp0"` fix, goto labels for tkinter section, GPU detection via temp file
IMPROVED: `start.bat` — sets `PERKYSUE_BACKEND` and `PERKYSUE_GPU_NAME` env vars
IMPROVED: `start.bat` — verifies tkinter import before launch
TECH: PIL (Pillow) used throughout GUI for effects CustomTkinter cannot produce natively
TECH: `python311._pth` must include `Lib` and `DLLs` entries for tkinter to function

### Alpha 0.19.4 (March 2026)
FIX: Backend architecture — all NVIDIA GPUs use `nvidia-cuda-12.4/` (nvidia-cuda-13.1/ reserved for driver 580+)
FIX: `start.bat` v2.4 — detects RTX 50xx vs 40xx/30xx, auto-installs missing Python deps
FIX: `install.bat` v2.5 — creates both CUDA folders, adds pygame for MP3 support
FIX: `orchestrator.py` — auto-detects AMD/Intel GPU, forces server mode
FIX: `sounds_manager.py` — removes is_pro check, adds MP3/pygame warning
FIX: Python dependencies check in `start.bat` (requests, pygame, etc.)
BENCHMARK: RTX 5090 + driver 576.88 + CUDA 12.4 = ~20 tok/s (PTX JIT). CUDA 13.1 = CPU fallback (~5 tok/s). Native expected with driver 580+ (~80-100 tok/s).

### Alpha 0.19.3 (February–March 2026)
FIX: Backend folder architecture — split `nvidia/` into `nvidia-cuda-12.4/` and `nvidia-cuda-13.1/`
FIX: GPU detection uses `nvidia-smi -L` (works on all driver versions)
FIX: Batch `if/else` blocks replaced with `label/goto` pattern (silent parse failure fix)
FIX: `install.bat` handles both python-embed.zip naming conventions
NEW: Text selection feature — grab selected text with WM_COPY and send to LLM as context
NEW: Skin system — `App/Skin/Default/` (built-in) + `Data/Skins/` (Pro tier: Sue, Mike)
NEW: System sounds — `no_llm` and `llm_incompatible` audio feedback per skin
NEW: Per-skin personality — character messages when LLM unavailable
NEW: GPU detection — VRAM estimation and model compatibility warnings
NEW: Antivirus workaround — uses `%TEMP%` for llama-server
IMPROVED: `sounds_manager.py` — skin-aware, system sounds support, per-event fallback
IMPROVED: `injector.py` — `grab_selection()` uses WM_COPY (avoids UIPI restrictions)
IMPROVED: `orchestrator.py` — `selected_text` propagated through pipeline
IMPROVED: `modes/__init__.py` — `render_prompt()` appends selected text block

### Alpha 0.18.0 (February 2025)
- Dual LLM mode (direct + server) with auto-detection
- RTX 50xx automatic compatibility (server mode)
- `improve` mode with LLM cleanup
- `transcribe` mode without LLM (instant)
- ASCII art splash screen

### Alpha 0.17.0 (February 2025)
- Initial working version with server fallback
- Basic RTX 50xx support via manual config
- CUDA threading fix (warmup on main thread)
- LLM preload at startup

---

## License

Apache 2.0 — Created by Jérôme Corbiau
