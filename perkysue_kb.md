Here is everything you need to know about PerkySue to answer community questions accurately:

**Maintainers:** This file is the long-form canonical source for support and community answers. **Alt+H (Help)** in the app does not read this path; it loads trimmed copies in **`App/configs/kb_help_2048.md`**, **`kb_help_4096.md`**, and **`kb_help_8192.md`**, chosen from **Settings → Performance → Max input (context)** (see **Community KB and Help mode** in **`ARCHITECTURE.md`**). When you change product facts here, update those three files in the same change (or immediately after) so Help mode stays accurate.

WHAT IT IS: PerkySue is a portable, open-source (Apache 2.0) Windows voice-to-text app with local AI. Press a global hotkey anywhere, speak, and text appears at your cursor (Smart Focus / injection). Whisper STT + local LLM run on-device; audio is processed in RAM and discarded. **Pro TTS:** Voice tab → speak replies for **Answer** and **Help** (Chatterbox / OmniVoice). OmniVoice voice refs: optional **`voice_ref.wav`** + **`voice_ref.txt`**; sample clip **`audios/voice_sample/voice_sample.wav`** + optional **`voice_sample.txt`** (per locale folder under **`Data/Skins/<Character>/<Locale>/`**). GPU TTS on NVIDIA may require CUDA PyTorch (install in Voice tab or `install_pytorch_cuda_cu128.bat` / `cu124`, then full restart). OmniVoice on Windows may need FFmpeg shared DLLs (`install_ffmpeg_shared_windows.bat`). Beta 0.29.2. Chat/Help UI refreshed; statuses **generating** (LLM/TTS prep) and **speaking** (TTS); main avatar ring follows playback/mic (PCM). TTS path strips Markdown bullets/asterisks (`tag_sanitize`). Alt+Q stops TTS during prep/playback. **In-app update now includes post-update runtime checks; if critical runtime mismatch is detected, PerkySue can auto-launch `install.bat` and stop normal startup until repair is done.** TTS model governance is deterministic via `App/configs/model_registry.yaml` + `Data/Models/TTS/registry.json`.

NAME & ORIGIN:
- "Perky" means lively and upbeat in English — the name was chosen because it sounds friendly and approachable, not corporate.
- "Sue" is simply a short, human first name — it reinforces the idea of a helpful companion rather than a software product. There is no deeper backstory behind it.
- The name also nods to the desert wildflower nickname “Perky Sue” (a small, daisy-like bloom that survives tough, dry ground).
- The name PerkySue was picked deliberately to avoid the sterile, tech-branded feel of typical productivity tools. Jérôme wanted something that felt like a helpful companion rather than enterprise software.
- PerkySue started as a personal productivity tool Jérôme built for himself in February 2026, not as a product from day one.
- DO NOT speculate, invent, or embellish the origin story beyond these facts. If asked about anything not covered here (e.g., where the "Sue" comes from, a backstory about a specific person or event), say you don't know rather than guessing.

PLANS:

| Plan | Modes |
|------|--------|
| Free | **Alt+T** (transcribe, Smart Focus at cursor). **Alt+A** (Ask): local voice Q&A **in the Chat tab only** — standalone questions, **no** multi-turn memory, **no** Smart Focus injection at the cursor in other apps. **Alt+H** (Help): PerkySue Q&A **in the Help tab only** (no injection into the focused document). |
| Pro | Everything in Free, plus **text selection + voice** for transform modes, **prompt editing**, **Alt+V/B/N** custom slots, and **full Ask**: multi-turn history, Smart Focus injection at cursor, same Chat UI. **Alt+I, P, L, C, M, D, X, S, G** (and custom prompts) for injection modes. |
| Enterprise | Knowledge Base plugin (coming soon) |

**Routing:** Questions about PerkySue, settings, or the app → **Help tab / Alt+H**, not Chat. Chat/Alt+A is for general Q&A (local LLM).

HOTKEYS (WINDOWS) — for accurate troubleshooting:
- PerkySue uses Win32 **RegisterHotKey** only (no production low-level hooks). Implementation: `App/utils/hotkeys.py`.
- **Stop / cancel:** default **`alt+q`** (`hotkeys.stop_recording`). Editable in Shortcuts or YAML. **AltGr+key** is covered by also registering **Ctrl+Alt+key**; do not remove that for the stop shortcut or AZERTY **AltGr+Q** will not work.
- **Avoid** `alt+escape` (Windows reserves it). Prefer `alt+letter` combos.
- **Esc** when the app is focused can stop; **Alt+Q** is global.

SETTINGS — AVAILABLE VALUES:
- Max input (context): Settings → Performance → 1024, 2048, 4096, 8192, 16384, or Auto.
- Max output tokens: 256, 512, 1024, 2048, 4096, 8192.
- STT model: tiny, base, small, medium, large-v3. STT device: auto, cpu, cuda.
- Ask memory (Pro): **Remember last Q/A** = 2, 3, or 4 (`llm.answer_context_keep`). Factory default is **2**.
- Cross-mode chat memory (Pro): **Inject all modes in chat** (`llm.inject_all_modes_in_chat`) controls whether non-Alt+A LLM modes are appended to shared Ask history. Factory default is **On**.
- New-install defaults (0.29.2 closure): `max_input_tokens=4096`, `n_ctx=4096`, `max_output_tokens=4096`.

RECOMMENDED SETTINGS (HEURISTICS):
- **Max input (context)**: if you see “context limit reached”, increase Max input to the next step (e.g. 1024 → 2048 → 4096). Context is shared between prompt + history + answer.
- **CPU-only**: prefer Max input **2048–4096** and Whisper **small** (or base/tiny on older CPUs).
- **NVIDIA (CUDA)**: Max input **4096–8192+**; Whisper **medium** is a good default.
- **AMD/Intel (Vulkan)**: LLM can use Vulkan, but Whisper stays on CPU (upstream); treat STT sizing like CPU (small/base).
- **Max output tokens**: increase only when answers cut off **without** a context-limit warning; otherwise increase Max input first.
  - On Vulkan/AMD/Intel, it’s fine to say: *“I don’t have exact VRAM info on Vulkan, only RAM; use free RAM as your reference.”*

VOICE MODES (15 built-in hotkeys; Free vs Pro as in README):
- Alt+T — Transcribe: raw speech-to-text, no LLM, free forever, Smart Focus at cursor.
- Alt+H — Help (free): questions **about PerkySue**; answers use the Help KB + **Current settings**; **in-app Help tab only** (no injection into external apps). Editable in Prompt Modes.
- Alt+A — Ask: local voice Q&A. **Free:** Chat tab only, one question at a time (no rolling multi-turn context), no Smart Focus to external apps. **Pro:** multi-turn history, **Remember last Q/A (2/3/4)** controls verbatim carry-over, rolling summarization cadence follows that keep value, Smart Focus injection at cursor, Chat mirrors the thread.
- Pro cross-mode continuity: with **Inject all modes in chat = On** (default), LLM exchanges from modes like Alt+M/I/L/C/V/B/N are also stored in Ask history for follow-up.
- **PerkySue / app / creator questions** belong in **Help**, not Chat — the UI shows a notice; the model redirects those to Help.
- Alt+I — Improve (Pro): rewrite selection + voice instruction.
- Alt+P — Professional (Pro): formal business rewrite.
- Alt+L — Translate (Pro): translate to target language.
- Alt+C — Console (Pro): plain-language intent → shell command.
- Alt+M — Email (Pro): dictate → formatted professional email.
- Alt+D — Direct Message (Pro): WhatsApp, Slack, Discord tone — casual/pro as needed.
- Alt+X — Social Post (Pro): LinkedIn, X, YouTube, Reddit — post or reply.
- Alt+S — Summarize (Pro): key points.
- Alt+G — GenZ (Pro): casual, modern rewrite.
- Alt+V/B/N — Custom prompts (Pro): three user-defined slots (Prompt Modes).

KEY FEATURES:
- **Smart Focus** (result lands where the hotkey started): **Alt+T** free; **Pro Ask (Alt+A)** injects at cursor when on Pro. **Free Ask** uses the Chat tab only (no injection into other apps).
- Text selection + voice + prompt (e.g. select then Alt+I) = Pro. Prompt editing and custom prompts (Alt+V/B/N) = Pro.
- Text selection + voice: select text, press hotkey, speak — PerkySue processes both and replaces selection (Pro).
- Smart Focus: hotkey then switch apps; result lands where you started (free). Fire and forget.
- GUI widget: floating CustomTkinter panel with Console (live pipeline status, CPU/RAM/GPU bars, transcription controls, finalized logs, full console), Settings (STT model from tiny to large-v3, STT device Auto/CPU/GPU, **First Language** for greetings, LLM model, max input/output tokens — 1024 to 16384 for context; 256 and 512 removed), Shortcuts reference, Prompt Modes (Whisper keywords, identity/name, per-mode prompt editing with live test and four test samples EN1/EN2/FR1/FR2 saved on Save), Chat and Help (one page, two tabs), and About page. **Chat tab:** mirrors Alt+A conversation (WhatsApp-style bubbles); notice that questions about PerkySue or the app must go to the Help tab; token bar; "New chat" clears history and requests a new greeting; if context limit is hit outside the app, ⚠ on the Chat nav and blinking "New chat". **Help tab:** same layout, greeting and Q/A about the app. Greetings are LLM-generated in the user's First Language when the tab is opened. **Stopping recording or generation:** press **Alt+Q** from any app (global default `stop_recording`), **Esc** when PerkySue has focus, or **click the sidebar profile picture** — useful in noisy environments or to cancel the LLM mid-response.
- Portable: self-contained folder, works from a USB stick, no system installation.
- Works in any app: text injected via clipboard into any text field. After injection, for a configurable delay (default **5 s**, **Settings → Performance → Clipboard paste delay**), **Ctrl+V** can still paste that result before the previous clipboard is restored (skipped if you copied something else). **`Alt+R`** re-pastes the **latest finalized** result any time until restart (**Settings → Shortcuts**); not Help mode.
- AltGr support: works with both left Alt and AltGr on European keyboards (AZERTY, QWERTZ).
- Audio feedback: subtle system sounds for each pipeline step. Premium voice skins (Sue, Mike) available on Patreon.
- Configurable: models, hotkeys, modes, sensitivity — all via YAML files. Custom modes editable in the GUI Prompt Modes tab.
- Dual LLM mode: direct mode (fast) or server mode (RTX 50xx compatible), auto-detected.
- Whisper keywords (custom STT keywords): Free up to 3 keywords, Pro up to 10 keywords, Enterprise unlimited.

PRICING & LICENSING:
- Free tier (forever): Alt+T transcription, **Alt+A in Chat** (local Ask, no multi-turn / no external Smart Focus), and **Alt+H** (Help). Help does not inject into the focused document — answers only in the Help tab. No signup required for Free.
- Pro (when enabled): **30-day Pro trial once per email** (server-side), then **$9.90/mo Stripe**. Paid tier uses a **sliding local license file** (~35 days after each successful online check) + **one Windows device name** bound on the server (transfer via email OTP). Voice still never uploaded for dictation — see PRIVACY.md.
- Pro (post-alpha): $9.90/month via Stripe for full LLM modes (Improve, Professional, Translate, Console, Email, Direct Message, Social Post, Summarize, full Ask with history + Smart Focus, GenZ, Custom 1/2/3).
- Supporter Pack: $4.90/month on Patreon for voice skins Sue & Mike (audio personality packs, separate from Pro features).
- The core STT engine and injection pipeline are and will remain open source under Apache 2.0.

HARDWARE REQUIREMENTS:
- Windows 10/11 (macOS and Linux are on the roadmap, not yet available).
- 6 GB RAM minimum, 16 GB recommended.
- Microphone required.
- NVIDIA GPU optional but recommended — speeds up both Whisper and LLM by 5-10x.
- Supports NVIDIA (CUDA 12.4 for all RTX 20xx through 50xx, auto-detected), AMD/Intel (Vulkan backend), and CPU-only.
- RTX 50xx (Blackwell): works via CUDA 12.4 with PTX JIT compilation. Native sm_120 kernels pending driver 591.86+ with CUDA 13.1 backend.
- No GPU? Transcription (Alt+T) works great on CPU with tiny or small Whisper models. LLM modes are slower on CPU but functional.
- AMD/Intel GPU: Whisper always runs on CPU (no Vulkan backend for ctranslate2 — upstream limitation, not PerkySue's). LLM uses Vulkan backend.

INSTALLATION:
- GitHub tier: run install.bat (downloads embedded Python, pip packages, tkinter, and llama-server backends), then add an LLM (Settings → Recommended Models or manual .gguf), then PerkySue Launch.bat or start.bat.
- Patreon tiers: click-and-launch ZIP, just run start.bat.
- Skins/plugins from ZIP: About tab → **Install from ZIP…** and select the ZIP (can be anywhere: Downloads/Desktop/USB). ZIP contents must be root-relative (e.g. `Data/Skins/Mike/...`).
- No system-wide Python needed. Uses Python 3.11 embedded. VC++ runtime DLLs are bundled — no need to install Visual C++ Redistributable.

STT MODELS: configurable from tiny (fast, works on 4 GB RAM) to large-v3 (studio-grade accuracy). Default is medium. GPU users can enable CUDA-accelerated Whisper (Settings → STT Device → GPU for NVIDIA).

LLM MODELS: GGUF format, stored in Data/Models/LLM/. Download from Settings → Recommended Models or place a .gguf manually. Models range from lightweight CPU-friendly (LFM2-350M) to powerful 12B+ models for NVIDIA GPUs. For continuous Q&A (Alt+A), the catalog can mark models as suited for multi-turn conversation (good_for_qa_conversation).

PRIVACY (key talking points):
- Core dictation: **no audio** sent to PerkySue; processing local. Free tier works offline after setup.
- Pro trial/subscription (when live): **limited** data to Stripe / perkysue.com / Brevo for **billing and seat** — never your voice. See PRIVACY.md.
- No account required for **Free** (Alt+T, Alt+A in Chat, Alt+H, etc.).
- Audio never stored on disk for the pipeline — processed in RAM and discarded.
- Fully open source — anyone can audit the code.
- Voice is biometric data (accent, cadence, emotional state). Cloud tools capture and transmit it. PerkySue doesn't.

VS COMPETITION:
- vs. built-in dictation (Windows, macOS, Google): they transcribe words, PerkySue transcribes AND thinks — 15 modes (including 3 custom slots), text selection, Smart Focus.
- vs. cloud dictation (Wispr Flow $8/mo, Typeless): audio never leaves your machine, no account, no internet, no word limits, works on a plane or USB stick.
- vs. other open-source (Amical, OpenWhispr): they do STT + paste. PerkySue adds a local LLM pipeline with many built-in modes (including Direct Message and Social Post), 3 custom prompts (Alt+V/B/N), text selection + voice instructions, Smart Focus (Pro), Free local Ask in Chat, GUI widget (16 languages), USB portability, and **Pro** multi-turn Ask with history.

COMMUNITY:
- Discord: https://discord.gg/UaJHEzFgXy — announcements, support, bug reports, contributors.
- GitHub: https://github.com/PerkySue/PerkySue
- Patreon: https://patreon.com/perkysue

DISCLAIMER (LLM OUTPUTS):
- Generated content may be incorrect or inappropriate. PerkySue or the developers are not responsible for model outputs. Use PerkySue at your own risk and verify facts.

KNOWN LIMITATIONS (be honest if asked):
- Windows only for now. macOS (Apple Silicon Metal) is on the roadmap. Linux planned.
- Text selection grab (WM_COPY) doesn't work in all apps (some Electron apps, custom controls).
- Some antivirus software may flag llama-server.exe from the Downloads folder — solution: move to C:\PerkySue\ or Documents.
- Small LLM models may add unwanted preamble ("Here is the cleaned text:") — being addressed.
- No Vulkan backend for Whisper (upstream ctranslate2 limitation) — AMD/Intel users have CPU-only STT.
- RTX 50xx runs at ~20 tok/s via PTX JIT on CUDA 12.4; native speed (~80-100 tok/s) requires driver update to 591.86+ and CUDA 13.1 backend.

THINGS NOT TO PROMISE:
- No specific release dates for macOS or Linux.
- No specific date for post-alpha Stripe launch (the alpha runs ~90 days from launch).
- No guarantees about future pricing changes.
- Do not promise features that are in the TODO/backlog as if they exist today.
- Do NOT invent or speculate about Jérôme's personal motivations, backstory, or reasons behind any decision (including the name). If it's not in the NAME & ORIGIN section or elsewhere in this KB, say you don't know.