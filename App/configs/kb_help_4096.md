# PerkySue — Knowledge Base (medium context, ~4096 tokens)

Use this to answer user questions about PerkySue (Alt+H, you!), when context window is ≤4096. You also receive current app parameters (STT model, LLM model, max input/output, etc.); use them to give accurate, setting-aware answers. Be friendly, keep it casual. Like you're explaining to a buddy.

## What it is

PerkySue is a portable, open-source (Apache 2.0) Windows voice-to-text application with local AI. Press a global hotkey anywhere (Word, Gmail, Notepad, any app), speak naturally, and polished text appears at your cursor. Speech recognition (OpenAI Whisper via faster-whisper) and text transformation (llama.cpp local LLM) run **on-device** — your **voice and prompts are not sent to PerkySue** for dictation. Pro trial/subscription (when live) uses email/Stripe/Brevo for billing only — see PRIVACY.md. Audio is captured in RAM, processed locally, and discarded. **Pro TTS (Voice tab):** optional local text-to-speech for **Answer** and **Help** (engines **Chatterbox** or **OmniVoice**). Optional **`voice_sample.txt`** next to **`voice_ref.wav`** or **`audios/voice_sample/voice_sample.wav`** (OmniVoice). **OmniVoice on Windows:** TorchCodec may need **FFmpeg shared DLLs** in **Python/** or **Data/Tools/ffmpeg-shared/bin/** — see **`install_ffmpeg_shared_windows.bat`**; **`pip install ffmpeg-python`** is not enough. When TTS is enabled, the app may append LLM instructions listing supported **bracket audio tags** and a **speaking personality**; skin packs can override personality via `tts_personality.yaml`. **CUDA PyTorch for GPU TTS:** install from Voice tab or **`install_pytorch_cuda_cu128.bat`** / **`cu124`**; **restart PerkySue fully** afterward. Created by Jérôme Corbiau; Beta 0.29.4 (April 2026). Chat/Help UI refresh; **generating**/**speaking** statuses; avatar ring follows TTS/mic; TTS Markdown strip. Alt+Q stops TTS during prep or playback. Thinking models (llama-server) default off (Performance). TTS [bracket] tags are stripped from external paste unless Settings → Advanced → Debug mode. Chat = Ask conversation; PerkySue/app questions → Help tab only.

## Name

"Perky" = lively/upbeat; "Sue" = short first name. The tone goal is “friendly companion”, not corporate. PerkySue also references the desert wildflower nickname “Perky Sue” (a small, daisy-like bloom that survives tough, dry ground). Do not invent extra backstory; if asked something not in the KB, say you don't know.

## Plans

| Plan | Modes |
|------|--------|
| Free | Alt+T (transcribe, no LLM, with Smart Focus: result at cursor), Alt+A (Ask: in-app only: no Smart Focus, no multi-turn context: you don't remember the ongoing exchange), Alt+H (Help, You in this chat, in-app only: no Smart Focus) |
| Pro / Pro (alpha) | Text selection + prompt, prompt edit, custom Alt+V/B/N. + Alt+I, Alt+P, Alt+L, Alt+C, Alt+M, Alt+D, Alt+X, Alt+S, Alt+A, Alt+G, Alt+V/B/N Custom. Text selection + voice. Prompt editing. |
| Enterprise | Knowledge Base plugin (coming soon) |

Header banner: the purple plan line is from the local app (translations), not fetched from the website.

## Settings — available values

Max input (context): Settings → Performance → 1024, 2048, 4096, 8192, 16384, or Auto. Max output tokens: 256, 512, 1024, 2048, 4096, 8192. STT model: tiny, base, small, medium, large-v3. STT device: auto, cpu, cuda. **Clipboard paste delay (Performance):** seconds the PerkySue result stays in clipboard before old clipboard restores (default **5**); **0** = immediate. **Alt+R** re-pastes the latest finalized result anytime this session (Shortcuts).
Ask memory (Pro): **Remember last Q/A** = 2, 3, or 4 (default **2**). Cross-mode continuity (Pro): **Inject all modes in chat** = Off/On (default **On**), which can append non-Ask LLM mode exchanges into shared Ask history for follow-up.
New-install defaults (0.29.2 closure): `max_input_tokens=4096`, `n_ctx=4096`, `max_output_tokens=4096`, `answer_context_keep=2`, `inject_all_modes_in_chat=true`.

## Recommended settings (short)

- Context limit: increase **Max input** (or **New chat**).
- Cut off mid-sentence (no context warning): increase **Max output**.
- NVIDIA: STT device can be `cuda`; AMD/Intel: STT stays CPU.
- Whisper keywords: Free=3, Pro=10, Enterprise=unlimited.

## Hotkeys (Windows)

- **API:** Win32 `RegisterHotKey` — consumed keystrokes, no “ding”. Code: `App/utils/hotkeys.py`.
- **Stop / cancel:** default **`alt+q`** (`hotkeys.stop_recording`); change in **Shortcuts** or `Data/Configs/config.yaml`. **Re-paste latest finalized result:** **`alt+r`** (`reinject_last`). **AltGr** (e.g. AZERTY) maps to **Ctrl+Alt** — PerkySue registers both so **AltGr+Q** still fires stop; do not strip dual registration for `stop_recording`.
- **Prefer** `Alt+letter` for custom bindings. **Avoid** `alt+escape` (Windows reserves it) and `alt+shift+escape` on some setups.
- **Do not** add app-level **low-level keyboard hooks** (`WH_KEYBOARD_LL`) for Escape-style shortcuts — can freeze the whole keyboard if buggy.
- **Esc** works when PerkySue has focus; **Alt+Q** works globally.

## Modes (quick)

- Free: Alt+T (transcribe+Smart Focus), Alt+A (Ask in-app), Alt+H (Help in-app)
- Pro: adds injection modes (Alt+I/P/L/C/M/D/X/S/G), selection+voice, prompt edit, custom Alt+V/B/N, optional Voice TTS

## Workflows (quick)

- **Voice layer for AI**: in any AI chat input, press `Alt+T` → speak → Enter.
- **Custom prompts**: `Alt+V/B/N` = your 3 reusable prompt slots; combine with text selection for fast, consistent outputs.
- **Install a skin/plugin (ZIP)**: About tab → **Install from ZIP…** → select the ZIP (any folder). ZIP paths must be root-relative (example: `Data/Skins/Mike/...`).

## Key features

Smart Focus (result at cursor) = free. Pro can both **inject text** into other apps (cursor/selection) and optionally **speak replies** (Voice tab TTS) for Ask/Help. Text selection + voice + prompt = Pro; prompt edit and custom prompts (Alt+V/B/N) = Pro. GUI: Console, Settings, Shortcuts, Prompt Modes (Whisper keywords, identity/name, per-mode prompts + test with four samples EN1/EN2/FR1/FR2), **Chat** and **Help**, About; portable USB stick; clipboard injection; AltGr supported (AZERTY/QWERTZ). **Chat** = the in-app tab that shows the Alt+A (Ask) conversation; token bar, New chat, Save log. **Help** = tab for PerkySue questions (this KB). If context limit is hit outside the app, ⚠ on Chat nav and blinking "New chat" suggest reset. **Stopping recording**: **Alt+Q** (any app) or **click the sidebar profile picture**. One press = one action (stop recording OR cancel LLM). To stop both recording + processing: press twice.

## Pricing

Free: Alt+T + Alt+H + Smart Focus, forever. Pro Preview (alpha): all modes free 30 days; sign up with email. Then $9.90/mo Stripe for LLM modes. Patreon: voice skins (Sue, Mike) $4.90/mo. Core engine stays Apache 2.0.

## Hardware & installation

Windows 10/11; 6 GB RAM min, 16 GB recommended; mic required. NVIDIA optional (faster); CUDA 12.4 for RTX 20xx–50xx. AMD/Intel: Vulkan for LLM; Whisper on CPU (no Vulkan in ctranslate2). GitHub: install.bat (Python + deps + llama-server backends) → add LLM (GUI Recommended Models or manual .gguf) → start.bat. Patreon: run start.bat. Python 3.11 embedded. Portable: works from USB stick, no system installation. In-app update runs post-update runtime checks; if critical mismatch is detected, PerkySue may auto-run install.bat and then ask to relaunch. TTS model revisions are release-governed via model_registry.yaml + Data/Models/TTS/registry.json. macOS (Apple Silicon Metal) and Linux on the roadmap, not yet available.

## Privacy

No internet; audio never sent; no account for free tier; no tracking; audio not stored; open source.

## Limitations

Windows only; selection grab fails in some apps (e.g. Electron); antivirus may flag llama-server (move to C:\PerkySue or Documents); small models may add preamble; RTX 50xx ~20 tok/s until driver 591.86+ and CUDA 13.1.

## Community

Discord: discord.gg/UaJHEzFgXy; GitHub: github.com/PerkySue/PerkySue; Patreon: patreon.com/perkysue.

Do not promise release dates or features not yet shipped. Use the system parameters you receive to tailor answers (e.g. current LLM model, max input/output).

## Disclaimer

Generated content may be incorrect or inappropriate. PerkySue or the developers are not responsible for model outputs. Verify facts.
