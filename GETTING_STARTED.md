============================================================
  PerkySue — Getting Started
  Voice-to-text with AI superpowers. 100% local.
============================================================

Created by Jérôme Corbiau  
Licensed under Apache 2.0 — Free to use, modify, and distribute  
Support & premium features: https://patreon.com/perkysue  
Community (announcements, support, bug reports, contributors): https://discord.gg/UaJHEzFgXy

This guide gets you running in about 10 minutes. No programming knowledge required.

⚠️ Outputs may be inaccurate or inappropriate. PerkySue or the developers are not responsible for model outputs. Verify the facts.

**Installer:** The portable setup is driven by **`install.bat`** (currently **v3.6**). It prepares **embedded Python 3.11**, **pip**, **GPU-aware packages**, **llama-server** backends, and optional **VC++** DLLs — you normally **do not** download Python or CUDA binaries by hand.

---

WHICH BUILD DO YOU HAVE?
------------------------

**GitHub / source folder (typical)** — Run **`install.bat` once** from the PerkySue root folder. It performs the full automated setup (see below).

**Patreon / pre-bundled builds** — If your package already includes `Python\`, backends under `Data\Tools\`, and dependencies, you may skip straight to **Launch** after a quick check that `Python\python.exe` exists.

**To start PerkySue after setup:** Double-click **`PerkySue Launch.bat`** (or `start.bat`). Use **`install.bat`** only for first-time setup or repair — not every launch.

**PerkySue Pro (Stripe) — important:** You can open **`https://perkysue.com/pro`** **with or without** an **`install_id`** in the URL. **With** `install_id` (from the app’s **Go Pro** flow), checkout can attach that UUID and the Worker stores state under **`install:<uuid>`**. **Without** it, you can still subscribe in the browser; the Worker may store state under **`sub:<subscription_id>`** until an in-app **“link this PC / I already paid”** flow connects **`Data/Configs/install.id`**. On first launch, the app creates **`install.id`** locally if missing — the website does not write that file. **Safest path** when the app is already installed: start checkout from the app so the URL includes the correct id. If you delete **`Data`**, you get a **new** UUID. Details: `ARCHITECTURE.md` (install_id lifecycle).

---

RECOMMENDED PATH — AUTOMATED INSTALL (GitHub tier)
--------------------------------------------------

### 1. Run the installer

1. Open the PerkySue folder (the one that contains **`install.bat`**).
2. Double-click **`install.bat`**.
3. Wait until you see **Installation Complete** (often **several minutes** on first run: PyPI packages, optional large CUDA wheels for NVIDIA STT, backend zips, etc.).
4. If the installer offers to launch PerkySue, you can accept, or close and use **`PerkySue Launch.bat`** later.

### 2. What `install.bat` does (you usually do nothing else)

- **Embedded Python 3.11.9 (amd64):** Uses, in order: `Assets\python-3.11.9-embed-amd64.zip` → `Data\Cache\` (cached) → **download from python.org** if missing. Extracts into **`Python\`** (portable — does not replace system Python).
- **pip:** `get-pip` + adjusts `python311._pth` so packages work.
- **tkinter (GUI):** Extracts **`Assets\tkinter-3.11-embed.zip`** so the widget can run.
- **Folders:** Creates **`Data\`** layout (Configs, Models, Tools, Logs, Cache, …).
- **GPU detection:** Runs **before** heavy installs where needed; picks **NVIDIA (CUDA 12.4, optional 13.1 path for newer drivers)** / **Vulkan** / **CPU**. RTX **50xx** may select CUDA **12.4** vs **13.1** based on **`nvidia-smi`** “CUDA Version” (driver must report a compatible CUDA level — see `App\tools\driver_supports_cuda13.ps1` in the repo).
- **Python packages:** Core deps, **faster-whisper**, and on NVIDIA **CUDA-enabled** `ctranslate2` wheels (large download ~1 GB+ combined — be patient).
- **llama.cpp backends:** Downloads/extracts **`llama-server`** and friends into **`Data\Tools\`** (e.g. `nvidia-cuda-12.4\`, `vulkan\`, `cpu\`) — **no manual GitHub unzip** in the normal path.
- **VC++ runtime (portable):** If **`Assets\vcredist-x64-portable.zip`** is present, DLLs are copied into backend folders (and `Python\`) so portable runs work without a system VC++ install.
- **Shortcut:** Desktop **`PerkySue.lnk`** → launch batch (when creation succeeds).

### 3. Download an LLM (large language model)

PerkySue needs a **.gguf** model for modes beyond raw transcription (**Alt+T** works without an LLM).

**Option A — GUI (recommended)**  
Launch the app → **Settings → Recommended Models** → choose a model → download.

**Option B — First launch (when applicable)**  
If no LLM is present, the app may start a **default download** from Hugging Face (tier depends on GPU / config — see `App/configs/installer_default_models.yaml`). Requires network access for that download.

**Option C — Manual**  
Place a `.gguf` file under **`Data\Models\LLM\`**.

### 4. Launch and verify

1. Double-click **`PerkySue Launch.bat`** (recommended) or **`start.bat`**.
2. The console runs **hardware checks**, activates the right **llama-server** backend, then starts **`Python\python.exe App\main.py`**.
3. **First run:** Whisper may download its **STT** weights (~1.5 GB) — subsequent starts are faster.
4. You should see the **GUI widget** (Console, Settings, Shortcuts, …).

**Sanity checks**

- **Dependencies:** `Python\python.exe App\main.py --check`
- **Verbose logs:** `Python\python.exe App\main.py --verbose`

If the console says **backend not found**, see **Troubleshooting** → *Manual recovery (llama-server backend)* below.

---

STEP-BY-STEP (SHORT)
--------------------

| Step | Action |
|------|--------|
| 1 | Run **`install.bat`** once and wait for completion. |
| 2 | Get an LLM via **Settings → Recommended Models** (or place a `.gguf` in **`Data\Models\LLM\`**). |
| 3 | Run **`PerkySue Launch.bat`**. |
| 4 | Press **Alt+T** in any app to dictate (Whisper may download on first use). |

---

HOTKEYS (FACTORY DEFAULTS)
--------------------------

Customize in **`Data/Configs/config.yaml`** or **Settings → Shortcuts**.

| Hotkey | Mode | What it does | Needs LLM |
|--------|------|----------------|:---------:|
| Alt+T | Transcribe | Raw transcription | No |
| Alt+I | Improve | Clean up / rewrite selection | Yes |
| Alt+P | Professional | Formal business tone | Yes |
| Alt+L | Translate | Translate to target language | Yes |
| Alt+C | Console | Shell / terminal command | Yes |
| Alt+M | Email | Professional email | Yes |
| Alt+D | Direct Message | Chat apps tone | Yes |
| Alt+X | Social Post | Social / blog tone | Yes |
| Alt+S | Summarize | Key points | Yes |
| Alt+A | Ask | Voice Q&A → cursor / Chat | Yes |
| Alt+G | GenZ | Casual rewrite | Yes |
| Alt+H | Help | PerkySue help (in-app) | Yes |
| Alt+V / B / N | Custom | User-defined prompts (Prompt Modes) | Yes |
| Alt+Q | Stop | Stop recording / cancel LLM | — |

Press **Ctrl+C** in the console to quit the app.

**AltGr:** On European layouts, **AltGr** is treated like **Ctrl+Alt** for many shortcuts — see `App/utils/hotkeys.py`.

---

TEXT SELECTION MODE
-------------------

Select text in any app, then press a mode hotkey (e.g. **Alt+I**). PerkySue combines **selection + your voice** and replaces the selection with the result. If nothing is selected, only your voice is used. The console shows **Selection: X chars** when a selection was read.

---

VOICE SKINS (PATREON SUPPORTER PACK)
------------------------------------

Default skin is built-in. **Sue** and **Mike** are optional Patreon skins: subscribe → download **`.perky`** → **Settings → Import Skin** with the published password. Extracted assets live under **`Data/Skins/<Character>/<Locale>/`** (example: **`Data/Skins/Mike/FR/`** for the French Mike pack). Optional **`Data/Skins/<Character>/tts_personality.yaml`** applies to all locales of that character. **Settings → Appearance** opens with a language filter matching your **UI language** so you do not see every locale at once; use the **All** chip if you want the full grid.

---

PRO TEXT-TO-SPEECH (VOICE TAB)
------------------------------

With **Pro**, **Settings → Voice** installs local **Chatterbox** or **OmniVoice** so **Answer** and **Help** replies can be read aloud. If you have an **NVIDIA GPU** but PyTorch in the bundle is **CPU-only**, use **Install PyTorch CUDA** on that tab (or **`install_pytorch_cuda_cu128.bat`** / **`install_pytorch_cuda_cu124.bat`** in the install folder). **After installing CUDA wheels, close PerkySue completely and launch it again** — TTS may not work reliably until you restart.

**OmniVoice (optional, Windows):** If TorchCodec / FFmpeg errors appear, copy **all DLLs** from a **shared** FFmpeg build (e.g. BtbN **`*-win64-gpl-shared`** → **`bin/`**) into **`Python/`** next to `python.exe` or into **`Data/Tools/ffmpeg-shared/bin/`**. See **`install_ffmpeg_shared_windows.bat`** in the portable root. **`pip install ffmpeg-python`** does not provide those DLLs.

**Reference audio + transcript (any engine, OmniVoice alignment):** beside **`voice_ref.wav`** you may add **`voice_ref.txt`** (UTF-8) with the exact words spoken in that WAV. The sample clip is **`audios/voice_sample/voice_sample.wav`**; optional **`voice_sample.txt`** next to it carries the transcript for OmniVoice (same folder — no per-language **`en.wav`** / **`fr.wav`** filenames).

Details: [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

---

CONFIGURATION
-------------

Edit **`Data/Configs/config.yaml`** (only keys you want to override). Restart after changes for many options. Full factory defaults: **`App/configs/defaults.yaml`** (read-only reference).

---

RTX 50XX AND SERVER MODE
-------------------------

RTX **50xx** cards are detected; the app typically uses **llama-server** mode with the **CUDA 12.4** backend for compatibility. Override options (e.g. `force_server_mode` / `force_direct_mode`) live under **`llm:`** in `config.yaml` — see **`ARCHITECTURE.md`** for details.

---

TROUBLESHOOTING
---------------

**Antivirus blocks `install.bat`**  
Add the PerkySue folder to exclusions. The script downloads from **python.org**, **PyPI**, **GitHub releases** (llama.cpp), and optionally uses only local **`Assets\`** when files are bundled.

**“Module not found” after install**  
Re-run **`install.bat`** to reinstall missing pip packages.

**“Backend not found” / missing `llama-server.exe`**  
Re-run **`install.bat`** so it can download/extract backends into **`Data\Tools\<backend>\`**. If you are offline, run from a machine with internet once, or use **Manual recovery** below.

**Hotkeys do not register**  
Another app may own the same combo (**error 1409**). Close duplicate PerkySue instances or change keys in **`Data/Configs/config.yaml`**.

**Hotkeys: left Alt works, AltGr not**  
See `App/utils/hotkeys.py` — AltGr is usually registered as **Ctrl+Alt+same key**.

**Text selection not detected**  
Some apps (Electron, custom controls) don’t support **WM_COPY**; selection grab may fail.

**Microphone**  
Check Windows **Sound → Input** default device.

**CUDA / crash on NVIDIA**  
Ensure **`Data\Tools\nvidia-cuda-12.4\llama-server.exe`** exists. For RTX 50xx, prefer server mode; see **`TROUBLESHOOTING.md`**.

**Transcription slow**  
Smaller Whisper model in config; on NVIDIA ensure STT uses CUDA (installer message: **Whisper: GPU (CUDA)** at startup when OK).

**LLM slow**  
Normal for large models or first server load; try a smaller GGUF.

---

MANUAL RECOVERY — IF AUTOMATED SETUP FAILED
-------------------------------------------

Use this only when **`install.bat`** could not finish (firewall, partial download, offline restore, etc.).

### A. Embedded Python missing or broken

1. Download **`python-3.11.9-embed-amd64.zip`** from:  
   https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip  
2. Extract **into** **`Python\`** so **`Python\python.exe`** exists (not nested one folder too deep).  
3. Place the same zip under **`Assets\`** or **`Data\Cache\`** for next time.  
4. Re-run **`install.bat`** so pip, tkinter, and packages are applied.

### B. llama-server backend missing (NVIDIA / Vulkan / CPU)

The installer normally downloads **llama.cpp** release **b8188** zips. If you must do it manually:

1. Open: https://github.com/ggml-org/llama.cpp/releases/tag/b8188  
2. For **NVIDIA**, download **both** for **CUDA 12.4** (typical):  
   - `llama-b8188-bin-win-cuda-12.4-x64.zip`  
   - `cudart-llama-bin-win-cuda-12.4-x64.zip`  
3. Extract **both** into **`Data\Tools\nvidia-cuda-12.4\`** so **`llama-server.exe`** is directly in that folder (adjust if your layout uses a subfolder — match what a successful install looks like on another PC).  
4. Vulkan / CPU: use the matching **`win-vulkan`** / **`win-cpu`** zips from the same release into **`Data\Tools\vulkan\`** or **`Data\Tools\cpu\`**.

Then run **`PerkySue Launch.bat`** again.

### C. pip / get-pip

If pip never installed, download **get-pip** from https://bootstrap.pypa.io/get-pip.py , run it with **`Python\python.exe`**, then re-run **`install.bat`**.

---

GETTING MORE HELP
-----------------

- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Pro license, GPU, common errors  
- **[README.md](README.md)** — Product overview  
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Technical layout  
- **[PRIVACY.md](PRIVACY.md)** — Data and online licensing  

```text
Python\python.exe App\main.py --check
Python\python.exe App\main.py --verbose
```

============================================================
  Enjoy PerkySue!

  Created by Jérôme Corbiau | Licensed under Apache 2.0
  https://github.com/PerkySue/PerkySue
============================================================
