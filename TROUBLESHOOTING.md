# PerkySue — Troubleshooting

Common issues and solutions. For setup instructions, see [GETTING_STARTED.md](GETTING_STARTED.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).

⚠️ Outputs may be inaccurate or inappropriate. PerkySue or the developers are not responsible for model outputs. Verify the facts.

---

## ⚠️ Antivirus false positives

Some antivirus software may flag PerkySue when running from the Downloads folder. This is a known issue with portable Python applications that use system-level features (hotkeys, clipboard, audio recording).

**Solution:** Move PerkySue to `C:\PerkySue\` or `C:\Users\%USERNAME%\Documents\PerkySue\`. The app uses the Windows TEMP folder for temporary files to minimize false positives.

---

## 🎤 Microphone not detected / wrong device

PerkySue auto-detects your default input device. If it picks a virtual device (e.g., VB-Audio, Voicemeeter) instead of your physical microphone, a banner appears with instructions.

**Fix:** Set your physical microphone as the default recording device in Windows Sound Settings → Input, then restart PerkySue.

See [GETTING_STARTED.md](GETTING_STARTED.md) for details.

---

## 🔇 "No Sound Detected" after pressing a hotkey

PerkySue uses Voice Activity Detection (VAD) to stop recording when you stop talking. If it detects no voice at all:

- Check that your microphone is not muted
- Check that the correct input device is selected (see above)
- Speak clearly within a few seconds of pressing the hotkey — VAD has a silence timeout (configurable in Settings → Silence Timeout)

---

## ⌨️ Hotkeys not working / conflicts

PerkySue uses Win32 `RegisterHotKey` — keystrokes are consumed so you won't hear an error "ding". If a hotkey doesn't register:

- Another application may have claimed the same combination. Check for conflicts with tools like AutoHotkey, PowerToys, or media software.
- **Avoid `Alt+Escape`** — reserved by Windows for window cycling; registration often fails.
- **Avoid `Alt+Shift+Escape`** — can clash with system shortcuts on some machines.
- Prefer `Alt+letter` combinations for custom keys.

**To change hotkeys:** Edit `Data/Configs/config.yaml` → `hotkeys`, or use the **Shortcuts** tab in the GUI (Save & Restart applies changes).

---

## ⌨️ AltGr on European keyboards (AZERTY, QWERTZ…)

PerkySue supports both **left Alt** and **AltGr** for all hotkeys. For each `Alt+letter` mode, PerkySue also registers `Ctrl+Alt+letter` so AltGr works transparently. No configuration needed.

**Technical note:** Optional explicit `*_altgr` lines in `config.yaml` can override the automatic dual registration. The `stop_recording` hotkey also uses dual registration — do not set `skip_altgr=True` for stop, or AltGr+Q (AZERTY) won't fire.

---

## 💥 `start.bat` prints many `'…' is not recognized` errors

This usually means **cmd.exe misparsed** the batch file — often a **trailing backslash** at the end of an **`echo`** line **inside** an `if ( ... )` block (line continuation), or **special characters** in `echo` lines. **Alpha 0.28.4** fixed the shipped **`start.bat`** for the antivirus-instructions block; use an updated copy. **Rule for maintainers:** inside `if ( )`, end path echoes without a trailing `\`, or split across two `echo` lines.

---

## 🖥️ RTX 50xx / CUDA issues

PerkySue auto-detects your GPU and selects the appropriate CUDA backend.

- **RTX 50xx (Blackwell):** Uses `nvidia-cuda-12.4/` backend (same as RTX 20/30/40xx). Performance via PTX JIT compilation (~20 tok/s on driver 576.88). Native sm_120 support expected with driver 580+.
- **RTX 20/30/40xx:** Standard CUDA 12.4 backend, auto-detected.
- **AMD/Intel GPU:** Whisper runs on CPU; the LLM uses the Vulkan backend.
- **No GPU:** Transcription (`Alt+T`) works great on CPU with `tiny` or `small` Whisper models. LLM modes are slower but functional.

If you see *Whisper: CPU* when you have an NVIDIA GPU, check that your NVIDIA drivers are up to date and that CUDA is properly installed. See `install.bat` output for diagnostics.

---

## 🔊 Pro TTS (Chatterbox / OmniVoice) and PyTorch CUDA

The embedded Python bundle may ship with a **CPU-only** PyTorch build. **Chatterbox** and **OmniVoice** need a **CUDA-enabled** PyTorch wheel on NVIDIA GPUs.

- Use **Settings → Voice → Install PyTorch CUDA** when the app offers it, or run **`install_pytorch_cuda_cu128.bat`** (recommended for **RTX 50xx / Blackwell**) or **`install_pytorch_cuda_cu124.bat`** from the repo root.
- **After any CUDA pip install, fully quit PerkySue and start it again.** The app does not reload PyTorch safely inside the same process; staying in the same session can break TTS with errors mentioning **einops**, **`_has_torch_function`**, or failed imports until you restart.

### OmniVoice on Windows — TorchCodec / FFmpeg DLLs (Beta 0.29.0)

**Chatterbox** is the most portable default TTS engine. **OmniVoice** pulls in **TorchAudio** paths that use **TorchCodec**, which loads native **FFmpeg** libraries on Windows.

- **Symptoms:** Errors loading **`libtorchcodec*.dll`** or messages about **FFmpeg** / missing dependencies when using OmniVoice.
- **Fix:** Install a **shared** FFmpeg build for Windows (e.g. [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases) — artifact like **`ffmpeg-master-latest-win64-gpl-shared.zip`**). Open the extracted **`bin/`** folder and copy **all `.dll` files** into **`Python/`** (same folder as **`python.exe`**) **or** into **`Data/Tools/ffmpeg-shared/bin/`** (create folders if needed). Restart PerkySue. Step-by-step: run **`install_ffmpeg_shared_windows.bat`** in the portable root.
- **Note:** **`pip install ffmpeg-python`** is a Python wrapper only — it does **not** ship the FFmpeg DLLs TorchCodec needs.

PerkySue also patches **`torchaudio.load`/`save`** for **local `.wav` files** to use **soundfile**, which covers typical **`voice_ref.wav`** / **`voice_sample`**. Non-WAV or other code paths may still need TorchCodec + FFmpeg.

**Weird extra words in OmniVoice output?** The engine **prepends** **`ref_text`** to the sentence it speaks. Use a real transcript in **`voice_ref.txt`** (next to **`voice_ref.wav`**) or **`voice_sample.txt`** (next to **`audios/voice_sample/voice_sample.wav`**), or leave empty (no dummy English sentence).

See [ARCHITECTURE.md](ARCHITECTURE.md) (*Pro TTS — engines…*) and [CHANGELOG.md](CHANGELOG.md) (Beta 0.29.0 / 0.28.9 / 0.28.8 / 0.28.7).

---

## 🔄 Dual LLM mode — Direct vs Server

PerkySue supports two LLM execution modes, auto-detected at startup:

- **Direct mode** — Fast, uses llama-cpp-python bindings directly. Default for most setups.
- **Server mode** — Uses `llama-server.exe` as a subprocess. Required for RTX 50xx compatibility and some edge cases.

If direct mode fails (missing dependencies, incompatible GPU), PerkySue falls back to server mode automatically. You can force CPU mode with `n_gpu_layers: 0` in `config.yaml`.

---

## 📁 Folder structure

PerkySue separates system files (replaced on update) from user data (preserved forever). See [ARCHITECTURE.md](ARCHITECTURE.md) for the full folder layout.

**To update PerkySue:** use **About → Check for updates** when available, or manually replace the **`App/`** folder from a newer zip. **In-app update (Beta 0.28.9+, fix 0.29.0)** also overwrites portable-root **`*.bat`**, **`*.md`**, and **`LICENSE`** from the downloaded bundle so `install.bat`, `start.bat`, and `CHANGELOG.md` stay aligned. Your settings, models, and unlocked skins stay in **`Data/`** (not replaced).

---

## 📦 In-app update — “Could not check updates” / GitHub message

**Symptom:** About → **Check for updates** fails with text like *No GitHub Release or version tag was found* (or HTTP 404 in logs).

**Cause:** The GitHub repo has **no published release** and **no git tag** whose name contains a semver (**`x.y.z`**), or you are pointing at the wrong repo.

**Fix:**

1. On **https://github.com/PerkySue/PerkySue** (or your fork), ensure a tag exists, e.g. **`v0.29.0`**, on the commit you want users to receive:  
   `git tag v0.29.0 && git push origin v0.29.0`
2. Wait a minute, retry **Check for updates** (the app caches the GitHub response for a few minutes).
3. To test against a **fork**, set environment variable **`PERKYSUE_UPDATE_REPO=YourLogin/PerkySue`** before starting the app.

See **[GETTING_STARTED.md](GETTING_STARTED.md)** (*Publishing a version so “Check for updates” works*).

---

## 🔑 Pro trial / subscription (when the online flow is live)

**Linking an existing subscription to this PC (seat / new machine / reinstall)**  
Use the **in-app** assistant — no need to hunt for a separate “transfer” page on the website:

1. **Settings** → **Plan management** (top of the Settings sidebar).  
2. Click **“I already have a subscription”** (wording may differ slightly by language).  
3. Enter the **email** you use with **Stripe** for PerkySue; request the **verification code**; enter the code when it arrives **by email** (sent via the server’s email provider — see [PRIVACY.md](PRIVACY.md)).  
4. On success, your subscription is tied to **this** PC’s `install_id` and seat (**Windows computer name** / hostname). Pro should appear without reinstalling the app.

**“Pro required” after a reinstall or new folder**  
Trial is **one per email** on the server. Deleting `trial.json` or the folder does **not** reset the trial. Use the same email or subscribe via Stripe when offered. If you **already pay** but this folder has a **new** `install.id`, use **“I already have a subscription”** (steps above).

**“Pro required” on a second computer with the same USB copy**  
Licensing uses **one seat** per subscription: your **Windows computer name** is checked against what the server stored (see [PRIVACY.md](PRIVACY.md)). Copying the folder to **another** PC changes the hostname → the server may refuse Pro until you **move the seat**. Do that **inside PerkySue**: **Settings** → **Plan management** → **“I already have a subscription”** → same Stripe email + OTP (not a separate “go to perkysue.com first” step).

**Renamed my PC and Pro stopped**  
The stored seat name no longer matches the new hostname. Use **Settings** → **Plan management** → **“I already have a subscription”** again with your Stripe email + code, or contact support if it still fails.

**I was Pro, then the app shows Free — but I still pay Stripe**  
1. **Go online** and restart PerkySue — if `license.json` exists, the app runs **one** `GET /check` at startup (short timeout) to realign the file with the server. Opening **Settings** can trigger another refresh in the background. Wait a few seconds if needed.  
2. Do **not** hand-edit `Data/Configs/license.json` to “fix” dates — changing `expires_at` (or any signed field) **without** a new server signature makes the proof **invalid** → the app correctly shows **Free** until a successful refresh writes a **matching** `license_payload` + `license_signature` from `/check`.  
3. If it stays Free: **`install.id`** may no longer match the server (lost file, new folder, copy). Use **Settings** → **Plan management** → **“I already have a subscription”** to re-link, or contact support.

**Offline for a long time — Pro disappeared**  
When the server sends a **signed** license proof, the app only trusts it for a **limited time offline** (about **30 days** after the proof’s `issued_at`). After that you need **internet** once so PerkySue can fetch a fresh proof. Normal use with occasional online sessions avoids this.

**Sliding refresh (general)**  
`license.json` is refreshed when the app successfully talks to the server; details and grace behaviour are described in [ARCHITECTURE.md](ARCHITECTURE.md).

**Console: `Stripe license not applied` … `bad_signature`**  
- **Expected** if you **changed** `license.json` while **offline** (any signed field under `license_payload` no longer matches `license_signature`). Go **online**; opening Settings or waiting for a background refresh re-fetches `/check` and restores Pro — **no reinstall** needed.  
- If you **never** edited the file: the **app build** may ship the wrong embedded public key vs the live Worker (distributor / ops issue). Support: run **`python diagnose_license.py`** from the **`App`** folder (same Python as the app).

---

## 🐛 Still stuck?

Join the [PerkySue Discord](https://discord.gg/UaJHEzFgXy) — the best place to report bugs, ask questions, and get help from the community.
