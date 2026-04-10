## 📋 Changelog

### Beta 0.28.9 (April 2026) — shipped
- **In-app updates (GitHub):** `check_updates_from_github` no longer relies only on `/releases/latest` (404 when there are no stable releases). Uses **`/releases`** (incl. prereleases), picks a sensible **`.zip`** asset when present, otherwise falls back to the **tag source archive** `…/archive/refs/tags/<tag>.zip` when the tag name contains a semver. Optional **`PERKYSUE_UPDATE_REPO=owner/repo`** for forks. Clearer errors when the repo has no tags/releases yet.
- **Update install scope:** After extracting the bundle, copies **`App/`** as before **and** syncs portable-root **`*.bat`**, **`*.md`**, and **`LICENSE`** from the same bundle root so `install.bat`, `start.bat`, `CHANGELOG.md`, etc. match the shipped version (`orchestrator.download_and_stage_app_update`, `paths.py` doc).
- **Licensing / Worker load:** Passive **`GET /check`** (focus + Settings) uses a **15-minute** cooldown instead of 12 seconds; opening Plan checkout, trial/link wizards, Stripe **Continue**, or billing portal **resets** the cooldown and triggers an immediate sync where appropriate. After opening Stripe (monthly/yearly), a **restart** hint + button helps if Pro does not appear before the next passive sync (`widget.py`; strings `checkout.post_stripe_*` in us/gb/fr).
- **Docs / version:** `README.md`, `ARCHITECTURE.md`, `GETTING_STARTED.md` (GitHub publish steps for updates), `TROUBLESHOOTING.md` (update errors), `KNOWN_ISSUES.md`, KB + `perkysue_kb.md`, `App/configs/kb_help_*.md`, `APP_VERSION` **Beta 0.28.9**, all **`common.window_title`** locales.

### Beta 0.28.8 (April 2026) — shipped
- **Chat + Help (GUI):** Major **Chat** tab redesign — pill-style Chat/Help header, unified input bar (mic + field + send), refreshed assistant/user bubbles and compact model line (internal milestone chain 0.28.7c–0.28.7j).
- **Status UX:** New **`generating`** (⚙️) while the LLM runs and while auto‑TTS is being prepared after injection — avoids a misleading **Ready** flash before speech. **`speaking`** (🔊) while TTS plays (`widget._tts_speaking_poll`). i18n **`common.statuses.generating`** and **`speaking`** in **16** locales (short sidebar labels).
- **Main avatar — audio‑reactive ring:** Outer status ring follows real **PCM** level — **TTS output** (`TTSManager` playback meter) and **microphone** while **Listening** (`AudioRecorder` → `input_feed_meter`). Bipolar offset **−9…+9** px (display), with stronger smoothing (EMA + GUI blend) and slightly slower ring tick (~**40** ms active / **135** ms idle).
- **TTS text hygiene:** **`strip_basic_markdown_for_tts`** in **`App/services/tts/tag_sanitize.py`** strips common Markdown (list markers, emphasis, stray asterisks, etc.) so engines do not read formatting aloud; complements engine-specific bracket-tag sanitization.
- **Skin import / maintainer tooling:** Continued **Skin Importer** / dev-plugin alignment with TTS-safe text (regex-style cleanup goals; shipped behavior centered on **`tag_sanitize`** for Markdown artifacts).
- **README:** Hero banner image **`App/assets/Github/banner.webp`** (see README).
- **Docs / version:** `README.md`, `ARCHITECTURE.md`, `GETTING_STARTED.md`, `TROUBLESHOOTING.md`, `KNOWN_ISSUES.md`, KB + `perkysue_kb.md`, `App/configs/kb_help_*.md`, `APP_VERSION` **Beta 0.28.8**, all **`common.window_title`** locales.
- **Release closure:** Beta **0.28.8** closes this cycle (chat UI, status pipeline, avatar metering, TTS markdown strip, README banner).

### Beta 0.28.7 (April 2026) — shipped
- **Skins — character-first paths (breaking vs older Patreon trees):** Pro content is **`Data/Skins/<Character>/<Locale>/`** (e.g. `Mike/FR/`) with optional **`Data/Skins/<Character>/tts_personality.yaml`**. Config / skin id is **`Character/Locale`** (e.g. `Mike/FR`); legacy **`Locale/Character`** paths and YAML keys are normalized when present. Resolver & teaser discovery: **`App/utils/skin_paths.py`** (`normalize_skin_id`, `resolve_locale_skin_dir`, `iter_teaser_skin_entries`, `iter_voice_ref_pack_dirs`, speech-language locale pick for TTS). **`widget.py`**, **`sounds_manager.py`**, **`tts/manager.py`**, **`tts/prompt_extension.py`**, **`tts/voice_sample_paths.py`**, **`orchestrator.py`** updated accordingly.
- **TTS reference audio:** Under each candidate locale folder: **`voice_ref.wav`** then **`audios/voice_sample/voice_sample.wav`** (+ optional **`voice_sample.txt`** for OmniVoice). Resolution prefers **`Data/Skins/<Character>/<speech-locale>/`** when the speech language differs from the UI-selected pack (e.g. English audio while `Mike/FR` is selected), then the active pack folder, then **`App/Skin/Default/audios/voice_sample/`**. No per-language `en.wav` / `fr.wav` names (pre-launch simplification).
- **Help / Ask + voice persona:** **`Orchestrator._append_tts_llm_extension`** may append **Assistant display identity** so the skin character name is consistent when TTS personality is active; **`Orchestrator.config.skin.active`** is kept in sync on skin change (**`widget.py`**) so personality matches the GUI.
- **Settings → Appearance:** Language filter defaults to **UI language** (not “All”) to avoid duplicate character rows; chips still allow **All** and per-locale filters. If the saved skin is another locale, the filter switches to that locale so the selection stays visible; **All** only as last resort.
- **Updates (GitHub):** New **Check for updates** flow (About) that checks public GitHub releases, shows “New update available …” in the footer, downloads the release zip, and stages an in-place update for `App/` (no touch to `Data/`). Includes a restart prompt.
- **Shortcuts (EU keyboards):** Custom prompt hotkeys switched from **Alt+1/2/3** to **Alt+V/B/N** (and AltGr via Ctrl+Alt). Defaults, fallbacks, UI tips, KB, and docs updated.
- **Installer / first run (CPU & Vulkan):** CPU/Vulkan machines now default to **Whisper Small** on first run (seeded when `Data/Configs/config.yaml` is missing) to avoid downloading Whisper Medium by default.
- **TTS stop / cancellation:** Alt+Q stops TTS audio more aggressively; Chatterbox multilingual cancellation is improved where supported but may still sample in long generations (noted in KNOWN_ISSUES).
- **TTS install (stability):** Fixed a hang/soft-lock when the user clicks install twice (installer refuses concurrent installs). The Voice UI now shows an “install already in progress” message and does not get stuck in “Installing…”.
- **OmniVoice on CPU/Vulkan (UX):** Selecting OmniVoice on incompatible backends now shows a clear warning, and the engine dropdown reverts to Chatterbox to avoid a mismatched dropdown/button state.
- **TTS install (NumPy/Torch ABI repair):** Avoids reloading ML wheels in-process after a NumPy ABI repair (which could trigger `'_has_torch_function' already has a docstring`). Verification/model warmup runs in a fresh subprocess; if a repair occurred, the installer prompts for a full restart to complete setup.
- **Help mode token budget:** Help intent routing + “Current settings” injection were compacted and made conditional to reduce context usage; TTS prompt appendix is injected only when needed.
- **Voice/TTS UX:** Clearer **tts_loading** status vs header notification; OmniVoice forced to clone-only and gated on NVIDIA/CUDA; Windows Hugging Face symlink issues mitigated.
- **Prompt hygiene:** All LLM prompts now include the current local date/time to prevent hallucinated “today”.
- **Disclaimers:** One-time in-app header disclaimer plus documentation disclaimers added/standardized (privacy/docs/KB).
- **Docs / About:** README/KB include “Voice layer for AI” and “Custom prompt machine” use cases; About page includes a quick use-cases card.
- **TTS vs new input:** Any **toggle** hotkey, **push-to-talk** key-down, **Chat/Help microphone** button, or **Ask/Help** text send calls **`Orchestrator.stop_voice_output()`** so ongoing TTS playback/synthesis is stopped immediately (same stack as Alt+Q on voice output).
- **Default TTS engine (NVIDIA):** Factory **`tts.engine: auto`** in **`defaults.yaml`** resolves to **OmniVoice** when **`nvidia-smi`** reports a GPU, else **Chatterbox** (**`TTSManager.load_config`**). Voice tab labels **OmniVoice** with a localized **(recommended)** suffix in that case (**`voice.engine.recommended_suffix`**, 16 locales). User **`config.yaml`** **`engine:`** still overrides when set explicitly.
- **Plan management (Pro):** Fourth marketing bullet **Voice-to-Voice** / **Voix-à-Voix** (and localized equivalents) on the Pro card in Settings → Plan management (**`settings.plan_management.pro.features`** in all **16** string YAMLs).
- **Release closure:** Beta **0.28.7** is **closed** for this cycle — skins path migration, TTS/docs/handoff updates, Appearance filter, plan copy, NVIDIA TTS defaults, and input-driven TTS stop are in this tag.

### Beta 0.28.6 (April 2026)
- **Sue speaks (Pro TTS):** Sue now **comments on what she injects**. Dictate an email (`Alt+M`)? Sue writes it at your cursor and explains her choices aloud. Rewrite text (`Alt+I`)? She tells you what she changed. Ask a question (`Alt+A`)? She answers by voice. The LLM decides when to inject, when to speak, or both — based on context. Default voice included in Pro; additional voice packs on Patreon. Toggle in Settings.
- **OmniVoice — portable Windows / TorchAudio 2.9+ :** TorchAudio routes **`load`/`save`** through **TorchCodec**, which needs **FFmpeg shared DLLs** on Windows. **`App/services/tts/windows_ffmpeg_dlls.py`** registers **`Python/`** and **`Data/Tools/ffmpeg-shared/bin/`** via **`os.add_dll_directory`** + **`PATH`** when **`avutil-*.dll` / `avcodec-*.dll`** are present (e.g. copy all **`bin/*.dll`** from BtbN **`ffmpeg-*-win64-gpl-shared`**). Helper batch: **`install_ffmpeg_shared_windows.bat`** (repo root). **`TTSInstaller`** logs the same hint after OmniVoice install on Windows. **`pip install ffmpeg-python`** does *not* ship those native DLLs.
- **OmniVoice — WAV without TorchCodec (typical voice refs):** **`App/services/tts/omnivoice_tts.py`** monkey-patches **`torchaudio.load`** and **`torchaudio.save`** for **local `.wav` / `.wave` paths** to use **`soundfile`** (already an **omnivoice** dependency). Reduces reliance on TorchCodec for skin / **`voice_sample`** WAVs.
- **OmniVoice — `ref_text` / no Whisper ASR leak:** OmniVoice’s **`_combine_text`** **prepends `ref_text` to the spoken target string**. A dummy English placeholder caused the model to say words like “reference” / “sample”. PerkySue now passes **`ref_text=""`** when only a reference **file path** is provided (skips bundled **`openai/whisper-large-v3-turbo`** ASR, which **`None`** would trigger, without prefixing junk text). Optional real transcripts improve alignment.
- **Voice packs — transcripts:** **`VoiceInfo.ref_transcript`** (`App/services/tts/base.py`). **`voice_ref.txt`** (UTF-8) next to **`voice_ref.wav`** under **`Data/Skins/<lang>/<Skin>/`** is read in **`TTSManager.scan_voice_packs()`**. Per-language samples: **`audios/voice_sample/<code>.txt`** next to **`<code>.wav`** (e.g. **`en.txt`** beside **`en.wav`**) in **`_voice_with_optional_lang_sample()`**; documented in **`voice_sample_paths.py`**.
- **`TTSManager._ensure_torchcodec_for_omnivoice`:** Still allows synthesis when the **soundfile WAV patch** is active; clearer errors if TorchCodec is required and fails.
- **Docs / version:** README, ARCHITECTURE, GETTING_STARTED, TROUBLESHOOTING, `perkysue_kb.md`, `App/configs/kb_help_*.md`, `App/configs/strings/*/common.window_title`, `APP_VERSION` — **Beta 0.28.6**.

> **0.28.7 supersession (skins):** Skin folders on disk and in config use **`Data/Skins/<Character>/<Locale>/`** and id **`Character/Locale`**; TTS reference sample file is **`audios/voice_sample/voice_sample.wav`** (+ **`voice_sample.txt`**). Bullets above that still mention **`Data/Skins/<lang>/<Skin>/`** or per-code **`en.wav`** describe the pre-0.28.7 wording — see **§ Beta 0.28.7** for the canonical layout.
>
> **0.28.8:** Chat/Help UI, **`generating`** / **`speaking`** statuses, PCM-driven avatar ring, TTS Markdown strip (`tag_sanitize`), README banner — see **§ Beta 0.28.8** above.

### Alpha 0.28.4 (April 2026)
- **Windows CMD / launcher:** Early UTF-8 setup in **`App/main.py`** (`PYTHONUTF8`, CP65001, `stdout`/`stderr` reconfigure) plus **`start.bat`** (`chcp 65001`, `PYTHONUTF8=1`) for readable Unicode in the console. **`start.bat` fix:** removed **trailing `\`** on `echo` lines inside `if ( )` blocks (cmd line-continuation bug that split the script into garbage commands); replaced Unicode **`→`** in those `echo` lines with ASCII hyphens; ASCII dashes in REMs; **`PerkySue Launch.bat`** REM normalized.
- **Debug vs dev plugin:** User-visible debug (**verbose LLM logging**, **PreviousAnswersSummary** in Alt+A paste, **TTS bracket tags** in UI) is gated by **`feedback.debug_mode`** (Settings → **Advanced**).
- **Alt+A external injection:** User/assistant labels use i18n **`chat.user_fallback`** / **`chat.sender_name`**; context summary block only when debug; removed trailing **`-\n`** suffix from pasted text.
- **Stop / Alt+Q:** **`tts_manager.stop()`** on cancel and when status is **`tts_loading`** or audio is playing; **`regular.tts_stopped`** alerts (all locale `header_alerts`).
- **Thinking models (llama-server):** Default **`llm.thinking: off`** in **`defaults.yaml`** → **`--reasoning-budget 0`**; Performance GUI toggle. Client-side **`Orchestrator._strip_thinking_blocks`** strips **`<thinking>`**, **`<reasoning>`**, **`<redacted_thinking>`** (multiline regex) if reasoning leaks into `content`; **`LlamaCppServerLLM._parse_chat_completion_choice`** prefers split **`message.content`** + **`reasoning_content`** when the API provides them.
- **TTS tags in user-visible text:** Unless **`feedback.debug_mode`**, **`strip_all_bracket_tags_for_display`** removes **`[MOOD: …]`** variants and all **`[bracket tokens]`** from external Answer/Help injection and finalized console lines; synthesis still uses engine-whitelisted tags from **`tts_prompt_extension.yaml`**.
- **STT / GPU:** No pipeline change — **faster-whisper** + **ctranslate2**; NVIDIA CUDA wheels from **`install.bat`**; RTX 50xx notes remain in **`TROUBLESHOOTING.md`**. TTS GPU path still **PyTorch CUDA** (0.28.3).
- **Docs / version:** README, ARCHITECTURE, GETTING_STARTED, TROUBLESHOOTING, `perkysue_kb.md`, `App/configs/kb_help_*.md`, locale `common.window_title`, `APP_VERSION` — **Alpha 0.28.4**.

### Alpha 0.28.3 (April 2026)
- **TTS + PyTorch CUDA (portable):** Embedded Python may ship **CPU-only** PyTorch while **Chatterbox** / **OmniVoice** need **CUDA** on NVIDIA. **`App/services/tts/pytorch_cuda.py`**: **Blackwell / RTX 50xx** detection (compute capability), **`torch_gpu_runs_basic_kernels()`** so `cuda.is_available()` alone is not trusted when kernels mismatch; **`pytorch_pip_index_url()`** selects **cu128** or **cu124** wheels. **`App/services/tts/manager.py`**: Voice-tab **Install PyTorch CUDA** offer when relevant (including **cu124 installed but GPU kernel probe fails** on e.g. RTX 5090).
- **Safe install path (critical):** After CUDA pip from the GUI, **`TTSInstaller._install_pytorch_cuda_impl`** (**`installer.py`**) **does not** call **`_purge_tts_extension_modules()`** or re-**`import torch`** in the running process (that broke **einops**, caused `RuntimeError: _has_torch_function' already has a docstring`, and left TTS unusable until restart). Post-pip check runs a **subprocess** (`python -c "import torch; …"`). User-facing copy: **fully quit and restart PerkySue** to load the new wheels.
- **GUI:** On successful CUDA pip, **`widget.py`** no longer calls **`tts.unload_engine()` / `tts.load_engine()`** after install. **`voice.pytorch_cuda.done_message`** (**`us.yaml`** / **`fr.yaml`**) states restart is required and TTS may misbehave until then.
- **Root batch helpers:** **`install_pytorch_cuda_cu128.bat`**, **`install_pytorch_cuda_cu124.bat`** (cu124 header warns RTX 50xx → cu128).
- **Docs / version:** README, ARCHITECTURE (Pro TTS + PyTorch CUDA), GETTING_STARTED, TROUBLESHOOTING, `perkysue_kb.md`, `App/configs/kb_help_*.md`, `APP_VERSION` — **Alpha 0.28.3**.

### Alpha 0.28.2 (April 2026)
- **TTS engines:** **OmniVoice** alongside **Chatterbox** (`App/services/tts/omnivoice_tts.py`, Voice tab engine selector).
- **LLM ↔ TTS (Answer + Help):** When Pro TTS is enabled, the system prompt sent to the LLM gains an appendix (after `---`) listing **engine-specific bracket tags** (e.g. laughter/sigh) and **speaking personality**. Config: **`App/configs/tts_prompt_extension.yaml`**. Logic: **`App/services/tts/prompt_extension.py`**. Optional per-skin override: **`tts_personality.yaml`** in **`Data/Skins/<lang>/<Skin>/`** or **`App/Skin/Default/`**. **`get_help_effective_system_prompt()`** includes the same appendix as the live Help pipeline (GUI preview matches LLM).
- **Orchestrator:** **`_append_tts_llm_extension`** docstring lists all call sites and prompts that intentionally do **not** receive the appendix (intent router, translation, greeting, Summarize, etc.).
- **Docs / version:** README (Pro TTS note), ARCHITECTURE § Pro TTS + LLM extension, `perkysue_kb.md`, KB headers, `APP_VERSION` — **Alpha 0.28.2**.

### Alpha 0.28.1 (April 2026)
- **Pro TTS (Chatterbox Turbo):** Shipped under **`App/services/tts/`** (not a separate plugin folder). **`Orchestrator.tts_manager`** loads config from **`tts:`** in merged **`defaults.yaml` + `Data/Configs/config.yaml`**; **`paths.models_tts`** + Hugging Face cache; optional **`voice_ref.wav`** per skin under **`Data/Skins/<lang>/<name>/`**. GUI **Voice** tab (after Help): install via embedded **`pip`**, progress, test speak; auto-speak after Answer/Help when Pro.
- **Commerce URLs vs entitlement base:** When `PERKYSUE_LICENSE_API` is set (internal staging tests), **`/pro`** browser links use the **same HTTPS origin** as licensing HTTP (`App/gui/widget.py` — `_perkysue_site_base_for_commerce_urls`). Avoids Stripe checkout + webhooks writing to **prod** KV while the desktop app calls **`/check`** on **staging** KV.
- **Docs / version:** `APP_VERSION`, locales, README, ARCHITECTURE, KB — **Alpha 0.28.1**.

### Alpha 0.28.0 (April 2026)
- **First-run default LLM (NVIDIA):** Tier selection in `App/configs/installer_default_models.yaml` now keys off **total VRAM** (card size), not **free VRAM** at launch — avoids incorrectly falling back to the 2B default when another process (or a second PerkySue instance) has already allocated most of the GPU.
- **Missing `PERKYSUE_BACKEND`:** If the GUI is started without `start.bat` (env unset), `App/utils/installer_default_model.py` probes **`nvidia-smi`** and applies NVIDIA tier rules instead of treating the machine as CPU-only (2B).
- **Docs / version:** `APP_VERSION`, all `common.window_title` locales, README, ARCHITECTURE, KB headers — **Alpha 0.28.0**.
- **User docs (April 2026):** **`GETTING_STARTED.md`** updated for **`install.bat` v3.6** (embedded Python, automatic llama-server backends, VC++ portable; default path no longer assumes manual Python zip or manual CUDA unzip). **`README.md`** Quick Start, **`ARCHITECTURE.md`** `install.bat` section, and **`PRIVACY.md`** (setup endpoints: python.org, PyPI, GitHub, Hugging Face) aligned. **Manual recovery** subsections retained for broken/partial installs.

### Alpha 0.27.9 (March 2026)
- **Release closure:** Alpha 0.27.8 is closed and validated.
- **Version rollover:** app labels and public docs bumped to **0.27.9** (APP_VERSION, GUI window titles in locale files, README/ARCHITECTURE headers).
- **Plan Management trial→paid fix (app):** Stripe-paid Pro now takes priority over leftover `trial.json` for header/banner/card status and **Manage** action, so paid users are sent to Stripe portal instead of checkout cards.
- **Renew date reliability:** GET /check now reads Stripe subscription period end using additional fallbacks (including expanded invoice lines) and returns non-null expires_at / current_period_end; signed license_payload.expires_at is aligned.

### Alpha 0.27.8 (March 2026)
- **Release closure:** Alpha 0.27.7 is closed and validated.
- **Version rollover:** app labels and public docs bumped to **0.27.8** (`APP_VERSION`, GUI window titles in locale files, README/ARCHITECTURE/KB headers).
- **Documentation consistency:** Help KB chain (`perkysue_kb.md` + `App/configs/kb_help_2048/4096/8192.md`) and root-cleanup references remain aligned.
- **Trial flow (app-side):** Plan Management popup for free trial mirrors **link-subscription**: **email** → Brevo **6-digit OTP** → **Yes/No** newsletter, then activation. App calls Worker `POST /trial/start`, `POST /trial/resend`, `POST /trial/verify` (verify sends `code` + `newsletter_opt_in` + `install_id`, `host`, `client_version`). Trial is not granted until email is verified; same abuse-resistant pattern as subscription relinking.
- **Trial gating:** `get_effective_tier()` now treats an active local `trial.json` as Pro access; banner logic keeps `pro_trial` with remaining days. Trial refusal (`trial_already_used`/`trial_consumed`) writes `trial_consumed.marker` for consistent Free-after-trial UX.

### Alpha 0.27.7 (March 2026).
- **Docs — Help KB:** **`ARCHITECTURE.md`** now defines **Community KB and Help mode** (`perkysue_kb.md` vs `App/configs/kb_help_2048/4096/8192.md`, tier selection, overrides, truncation). **`perkysue_kb.md`** updated for **Free vs Pro Ask (Alt+A)**, **Alt+D / Alt+X**, plan table, and maintainer sync note — aligned with README and shipped `kb_help_*.md`.
- **Ship validation (signed licensing):** Tampering **`license_payload`** while **online** is overwritten by **`GET /check`** → Pro restored from server truth. **Offline** tamper → **Free** until a successful refresh. **Back online without restart:** existing **`refresh_license_from_remote()`** paths (focus return, Settings, startup) can return the UI to **Pro** once `/check` succeeds.
- **Startup sync:** **`Orchestrator.initialize()`** calls **`refresh_license_from_remote(timeout_sec=12)`** when **`Data/Configs/license.json`** exists, so the file aligns with `/check` before first GUI tier where possible.
- **Support tooling:** **`App/tools/generate_license_signing_keys.py`**, **`App/tools/derive_license_public_from_private.py`**, **`App/diagnose_license.py`**; shared gate evaluation **`App/utils/stripe_license_file.py`**; **`Orchestrator.describe_pro_gate()`** for CLI/support.
- **Logging:** One **`bad_signature`** WARNING per process explains **offline edit (expected)** vs **possible public-key / Worker mismatch**; points to **`diagnose_license.py`** and **`TROUBLESHOOTING.md`**.
- **Plan card — cancelled at period end:** When Stripe reports **`cancel_at_period_end`**, Settings → Plan management shows **`status_access_until_cancelled`** (short copy, e.g. *Expires: {date}*) instead of *Renews*. Value from **`GET /check`** / signed payload when present.
- **Date format:** **`get_license_expires_display(locale)`** — **`us`** → **MM/DD/YYYY**; **`gb`** and all other UI locales → **DD/MM/YYYY** (UK convention).
- **Offline policy:** If a signed payload is present, Pro is refused when **`issued_at` + 30 days** has passed (no fresh server proof) or when **`expires_at`** (period end) is in the past — configurable via **`OFFLINE_MAX_DAYS`** in **`license_signature.py`**.
- **Dependency:** **`cryptography`** in **`requirements.txt`** and **`install.bat`** (Ed25519 verify).
- **Docs:** **`TROUBLESHOOTING.md`** — Pro, offline use, and do-not-edit-`license.json` guidance. Technical docs aligned with signing + marker behaviour.

### Alpha 0.27.6 (March 2026)
- **Worker — Stripe Customer Portal:** **`POST /billing-portal`** with body `{ "install_id": "<uuid>" }` → resolves the Stripe customer from KV **`install:*`**, creates a **billing portal session**, returns **`{ "url": "https://billing.stripe.com/..." }`**. Requires **Customer Portal** enabled in the Stripe Dashboard.
- **Worker — `GET /check`:** When the installation is linked to a subscription, the Worker **loads the Stripe subscription** (refresh KV, **`subscriptionPeriodEndIso`**, **`cancel_at_period_end`**, structured errors logged on Stripe failures). Desktop app uses this for accurate renewal labels and plan state.
- **App — manage subscription in browser:** **`Orchestrator.request_billing_portal_url()`** → **`POST /billing-portal`**; Settings → Plan management opens the portal. **`portal_manage_unavailable`** + renewal copy in **`settings.plan_management.*`** (16 locales) when the portal URL cannot be obtained.
- **App — `license.json` vs `install.id`:** Stripe **Pro** is honored only when **`license.json` `install_id`** matches **`Data/Configs/install.id`**; **`refresh_license_from_remote()`** keeps UI + `license.json` in sync (focus return, settings, post-link flows).
- **App — `expires_at` merge:** If **`subscription_id`** is unchanged, **merge** a previous local **`expires_at`** when the server response omits it, avoiding flicker on transient **`/check`** responses.
- **Docs / ops:** document **`/billing-portal`**, enriched **`/check`**, and **WAF** paths including **`/billing-portal`**.
- **Version strings:** `APP_VERSION`, `common.window_title`, `widget.py` fallback → **Alpha 0.27.6**.

### Alpha 0.27.5 (March 2026)
- **Licensing — relink Pro (Stripe e-mail → OTP):** Site **`POST /link-subscription/start`**, **`/resend`**, **`/verify`**: Customer Search by billing e-mail, pick latest **active/trialing** Pro subscription (monthly/yearly price IDs), Brevo OTP (10 min KV session, **30 s resend cooldown**, max **5** verify attempts). On success: **`install:{install_id}`** KV, Stripe **`metadata.install_id`**, delete **`sub:{subscription_id}`** when applicable.
- **App:** Settings → Plan management → **Link existing subscription** (wizard). **`Orchestrator.link_subscription_start/resend/verify`**, **`refresh_license_from_remote()`** → **`GET /check?id=&host=`** and writes **`Data/Configs/license.json`** so **`get_effective_tier()`** shows Pro **without a mandatory restart** (plan cards + header banner refresh in GUI).
- **Licensing HTTP headers:** **`Orchestrator._license_http_headers()`** — browser-like **`User-Agent`** (Chrome/Windows + `PerkySueDesktop/<version>`) and **`X-PerkySue-Client: desktop`** on licensing **`POST`** and **`GET /check`** to avoid Cloudflare WAF blocking default Python `urllib`; production may still require a **WAF Skip** rule on `/link-subscription`, `/check`, `/trial`.
- **Settings — Plan management UI:** Three plan cards + Pro checkout row use **`_PLAN_ROW_THREE_COL_PADX = ((0, 8), (4, 4), (8, 0))`** (same card width as before, +4 px gutters, less outer inset); **“I already have a subscription”** link (FR UI string among locales) uses **`pady=(4, 0)`**. Wizard: **`_plan_link_api_user_message()`** surfaces API errors (including nested Stripe-style JSON) and appends **`(HTTP n)`** when the server gives no usable message.
- **i18n:** **`settings.plan_management.link_subscription.*`** in all **16** locale YAML files (friendly tone; French wizard title and full translations for locales that previously mirrored English on this block).
- **Ops docs (sync):** link-subscription endpoints, **`curl`** smoke test, **Cloudflare WAF** notes for desktop app traffic.
- **Version strings:** `APP_VERSION`, `common.window_title`, `widget.py` fallback → **Alpha 0.27.5**.

### Alpha 0.27.4 (March 2026)
- **Licensing — `install.id`:** `App/utils/install_id.py` with `get_or_create_install_id()`; called from `App/main.py` after logging init so every launch via `start.bat` creates `Data/Configs/install.id` (UUID v4) when missing or empty. Enables future `/pro?install_id=` return URLs and Worker KV linkage. **Full doc list:** see **Alpha 0.27.3** below.
- **GUI — header banner by plan:** The purple header line is no longer a static `header_subtitle`. **`common.header_banner.*`** in each locale (`free_invite`, `free_after_trial`, `pro_trial` with `{days}`, `pro`, `enterprise`) is selected by **`Orchestrator.get_header_banner_spec()`** from `get_gating_tier()`, active **`trial.json`** expiry.
- **GUI — header tips:** Shortened the rotating **Alt+A** tip in all **16** locale files (Pro vs Free, one line; FR was the reference copy).
- **Documentation (Worker `/pro` — March 2026):** updated for **optional `install_id`**, **`?interval=` → Stripe**, KV **`sub:{subscription_id}`** for web-only checkout, and success/cancel copy. App docs aligned with the same behavior.
- **Settings — Recommended Models:** Parameter count in white; star rating (1–3) as emoji (⭐); long model names wrap without breaking the card border; tooltip two-column layout (grey label, white value) with full YAML catalog (author, family, params, quant, thinking, uncensored, languages, size, stars, comment, Alt+A suitability, popularity). *(That UI was first logged historically as **Alpha 0.26.4** in this file; merged under **0.27.4** so the current release note matches the product label.)*
- **Version correction:** Display version was briefly mis-tagged **0.26.4**; corrected to **Alpha 0.27.4** (milestone before this bump = **0.27.3**).
- **Version strings:** `APP_VERSION`, `common.window_title` (all locales), `widget.py` fallback → **Alpha 0.27.4**.

### Alpha 0.27.3 (March 2026)
- **`install.id` — implementation:** New module `App/utils/install_id.py`; `App/main.py` invokes it after `setup_logging`; first creation logged at INFO; stable UUID persists across restarts (regenerated only if the file is missing or empty).
- **Documentation (App repo):** `install_id` product lifecycle notes updated across public docs.
- **Website:** Worker/KV endpoint documentation updated for alignment.
- **Milestone:** Closes the licensing-identification and documentation batch before the public **0.27.4** label.

### Alpha 0.27.2 (March 2026)
- **Chat → Help (in-app):** After regex pre-filter, `_llm_intent_should_redirect_to_help()` classifies **HELP** vs **NOHELP**; `_should_force_help_redirect()` covers PerkySue + machine/LLM sizing phrases if the router misfires. Micro-from-Chat passes `from_chat_ui=True` through `_on_hotkey_toggle` → `_record_and_process` so redirect does not rely on HWND matching alone.
- **Help — live GPU / VRAM:** `App/utils/nvidia_stats.py` (`nvidia-smi`); `Orchestrator._collect_help_params()` appends `system.gpu.live` when a snapshot exists (no empty lines on CPU-only). Help `modes.yaml` rules: **Current settings** telemetry overrides generic KB text for RAM/GPU/VRAM; NVIDIA + CUDA uses VRAM for local LLM.
- **KB budget (2048 ctx):** Help KB truncated at **1350** chars (was 1500) to leave headroom for params + instructions.
- **Documentation:** `README.md` — **Free Ask** = local voice Q&A in Chat tab, **no multi-turn context**; **Pro Ask** = **multi-turn context**, summaries, cursor injection + Smart Focus. `ARCHITECTURE.md` and KB headers aligned to **Alpha 0.27.2** at ship.
- **Version strings (at ship):** `APP_VERSION`, `common.window_title` (all locales), `widget.py` fallback → **Alpha 0.27.2**.

### Alpha 0.27.0 (March 2026)
- **Internationalization baseline shipped:** PerkySue GUI is now international with 16 locale packs wired to the 16 flag selectors (`us`, `gb`, `fr`, `de`, `es`, `it`, `pt`, `nl`, `ja`, `zh`, `ko`, `hi`, `ru`, `id`, `bn`, `ar`).
- **English split:** US and UK now use dedicated locale files (`App/configs/strings/us.yaml`, `App/configs/strings/gb.yaml`) instead of a shared `en_variant` path.
- **Ask Free notice localization:** `chat.free_answer_notice` is present across all active locale files.
- **Documentation:** `README.md`, `ARCHITECTURE.md`, and KB snapshots bumped to Alpha 0.27.0 with updated locale mapping.
- **Version strings in-app:** `common.window_title` in all `App/configs/strings/*.yaml`, `App/orchestrator.py` `APP_VERSION`, and `widget.py` title fallback aligned to **Alpha 0.27.0** (were still 0.26.x in places).

### Alpha 0.26.8 (March 2026)
- **Header Patreon button (Pillow):** Gradient canvas text is not OS font fallback — script-specific font order in `_font_for_canvas_button_text` (Hangul → Malgun, kana → Yu Gothic, Devanagari → Nirmala/Mangal, else YaHei). Mixed **❤** + text uses Segoe UI Emoji + baseline anchor `ls`; fixes tofu for Korean / Hindi labels. Documentation includes i18n rules for this control.
- **GUI strings (i18n):** Final passes for remaining locales (e.g. Korean, Hindi, Dutch); `common.window_title` Alpha **0.26.8** across `App/configs/strings/*.yaml`.
- **Documentation:** `ARCHITECTURE.md`, `README.md`, KB headers aligned to 0.26.8.
- **Interface language (docs):** `README.md` (GUI Widget → **Interface language**), `CHANGELOG.md` (this entry), and `ARCHITECTURE.md` (**GUI strings → Interface language — flag grid**) document the **16** flag buttons (**15** `strings/*.yaml` locale packs + **English** shared by US/UK via `en.yaml` only), flag asset → `ui.language` mapping (`bd` → `bn`, `sa` → `ar`, etc.), and `widget.py` maintenance pointers. Bengali (`bn.yaml`) is listed as planned until the file ships (English fallback when absent).
- **Release:** Alpha **0.26.8** closed — multilingual milestone for this cycle (string YAML + Patreon canvas) complete; next development target **0.26.9**.

### Alpha 0.26.7 (March 2026)
- **GUI strings (i18n):** Extended `App/configs/strings` — dedicated keys for sidebar note under Save & Restart, Patreon header + About link, Appearance **Default** skin label, `modes.registry` names/descriptions for Shortcuts (Mode column) and Prompt Modes cards; **message** / **social** (Alt+D / Alt+X) included in Shortcuts order and registry. French nav label **Prompts**, copy tweaks (e.g. max listen duration, **Éditer** on Shortcuts).
- **About:** Use-cases footer line (“All modes run locally…”) uses the same body style as Smart Focus (14pt, `TXT2`).
- **Documentation:** `ARCHITECTURE.md` (GUI strings / i18n), KB headers aligned.

### Alpha 0.26.6 (March 2026)
- **Changelog split:** `CHANGELOG.md` is the **full** release history (this file). `README.md` keeps only the **latest** alpha notes in its Changelog section, plus a link here. **On each version bump:** ensure the previous README release block is appended here (if missing), mark the new top entry `— current`, remove `— current` from older entries, then replace the README Changelog section with the new version only.
- **Documentation:** Global hotkeys (Windows) — `RegisterHotKey`, default **`Alt+Q`** stop/cancel (`hotkeys.stop_recording`), AltGr covered via **Ctrl+Alt** dual registration, avoid **`alt+escape`**; documented in README, ARCHITECTURE, KB Help (`kb_help_*`, `perkysue_kb`), About (`widget.py`), and factory/user YAML comments. Rule: **Python and inline comments under `App/`** (including `App/configs/*.yaml`) are **English**.

### Alpha 0.26.5 (March 2026)
- **Nav Chat indicator (⚠):** When the Chat tab is active or hovered, the warning triangle now has the same background (SEL_BG) as the menu; when another tab is active, the background stays transparent. Fixes the visual mismatch when the context limit is reached.
- **Alt+A injection format:** Bullet points for speakers: **● User** for the question, **✦ PerkySue** for the answer; blank line between them for better readability in injected documents.

### Alpha 0.26.4 (March 2026)
- **Settings — Recommended Models:** Parameter count now displayed in white for better visibility. Star rating (1–3) shown as emoji (⭐) on each card, right-aligned above the action button. Long model names (e.g. Phi-3.5-mini-instruct) wrap correctly without breaking the card border. Tooltip redesigned with a two-column layout (label in grey, value in white) integrating the full YAML catalog: author, family, params, quant, thinking, uncensored, languages, size, stars, comment, Alt+A suitability, popularity.

### Alpha 0.26.2 (March 2026)
- **Settings — Plan management architecture fix:** The Plan Management UI now updates **in-place** (no card destroy/recreate on click), eliminating cascade relayout glitches in Settings (Appearance/Recommended Models no longer collapse or flash).
- **Settings — Save & Restart visibility:** Changing plan still shows **Save & Restart**, but without forced sidebar scroll to avoid layout side effects.
- **Shortcuts — Free gating enforced:** In Free tier, only **Alt+T** (Transcribe) and **Alt+H** (Help) are editable in Shortcuts Manager. All other shortcuts are grayed and non-editable.
- **Prompt Modes — Free reset policy on downgrade:** When switching from Pro/Enterprise to Free, `Identity & Preferences → Your Name` is cleared and `Whisper STT Keywords` are truncated to the first 3 tags (with live STT keyword reload).
- **Prompt Modes — keyword limits kept strict:** Limits are enforced by plan (Free 3 / Pro 10 / Enterprise unlimited), and limit overflows redirect to Help with plan-aware guidance.

### Alpha 0.25.3 (March 2026)
- **Chat — PerkySue / app questions → Help tab:** A notice in the Chat tab tells users that questions about PerkySue, its creator, or the application cannot be answered there and to use the Help tab. The Ask mode system prompt instructs the LLM to redirect such questions to the Help conversation.

### Alpha 0.25.2 (March 2026)
- **First Language (Settings → Performance):** New setting after STT Device. Options: Auto + many languages (en, fr, de, es, it, pt, nl, pl, ru, ja, zh, ko, ar, hi, tr, sv, da, no, fi, el, cs, hu, ro, uk, vi, th, id, ms, he, bg, hr, sk, sl, et, lv, lt, sr, ca, eu, gl, nb, fa, bn, ta, te, mr, ur, my, km, lo, ne, si, pa, gu, kn, ml). Used for LLM-generated greetings.
- **LLM-generated greetings (Chat & Help):** Greeting is generated by the LLM in the user's First Language with their name. Triggered **only when the user opens** the Chat or Help tab (not before). **Two different greetings:** Chat = welcome + short engagement question; Help = welcome + “does [name] need help?”. Cache per tab; **New chat** clears the Chat greeting cache and requests a new one. While the greeting is loading, the UI shows a small **purple indeterminate bar** (same accent color) in the messages area — it does **not** set the avatar status to “Processing”.

### Alpha 0.25.1 (March 2026)
- **Ask context (0.25.1):** Last **4 Q/A** in context, summary every **4** exchanges (was 8). Reduces context usage.
- **Milestone 0.25.0:** Full **Help** tab (same layout as Chat, welcome 👋 from PerkySue); Help prompt plan-aware (no “sign up for Pro” when user already has Pro); version set to 0.25.0.
- **Alt+H (Help) — free plan, no injection:** Help mode is available on the **free plan**. It does **not** inject into the focused document — the answer is only in the app (Help tab). To use Alt+I (Improve), Alt+C (Console), or other LLM modes that inject at cursor, user must be on Pro. Full Help chat UI (conversation in Help tab) is planned later. Three KB files (`kb_help_2048/4096/8192.md`) document **plans** (Free vs Pro), **available values** (Max input: 1024, 2048, 4096, 8192, 16384, Auto; Max output: 256–8192; STT model/device), and that Alt+H is free and app-only.
- **Chat — reliable truncation signal:** PerkySue now uses the **`finish_reason`** field from the LLM API (OpenAI-compatible / llama-server): when the server returns **`"length"`**, the generation was stopped due to the token limit (context or output). This replaces the previous “last character” heuristic. `LLMResult` has `finish_reason`; llamacpp_server and llamacpp_llm pass it through. Context limit still uses `total_used >= n_ctx` or `finish_reason == "length"` with no usage to show the correct message.
- **New chat clears context:** “New chat” now calls **`orch.clear_answer_context()`**, which clears `_answer_history` and `_answer_summaries` in place so the next Alt+A sends no previous Q/A to the LLM. Ensures a real reset when hitting the context limit.
- **Request size log:** In Ask mode, a console log reports approximate input size: `Alt+A request size: system=X chars, user=Y chars → ~Z input tokens (limit 1024 = input + output being generated)` so you can confirm there is no double send; the 1024 limit is input + **response as it is generated** (shared context window).
- **Chat reset indicator:** If the context or max-output limit is reached while you're not in the Chat tab (e.g. Alt+A from Word), a small **⚠** appears to the right of "Chat" in the sidebar. When you open Chat, **New chat** blinks in red a few times so you know to reset; clicking New chat clears the indicator.

### Alpha 0.25.0 (March 2026)
- **Chat — context vs output limit:** The LLM **context window** (Max input in Settings) is **shared** between prompt and reply. When the reply is cut off and the server reports 1024 tokens **total**, the cause is the **context limit**. PerkySue shows "Context limit (1024) reached — input and output share this budget…" with actual value and suggestion. Request uses **max_output_tokens** from config. New alert `chat_context_limit_reached` in header_alerts.yaml.

### Alpha 0.24.3 (March 2026)
- **Chat page (enhanced):** **Cascade display** — your message appears as soon as you finish speaking, then PerkySue’s reply appears when the LLM responds. **Mic button** in the chat input now correctly shows **Listening** (green) in the sidebar and turns **red** while recording; recording runs in a background thread so the UI stays responsive and STT/LLM sounds play only once. **No injection into the type-in bar** — when you trigger Ask from the Chat page (mic or send), the LLM result is never pasted into the chat input; only Alt+T can inject into that field. **Max output token limit** — when the reply is cut off or empty because the model hit the token limit (e.g. 1024), the chat shows a clear message: “You’ve reached the max output token limit… Increase ‘Max output’ in Settings → Performance,” and the **header bar blinks 3 times** with the same notice. Empty replies without token info show “Reply was empty. Try rephrasing.”
- **Chat (from 0.24.2):** Sidebar **Chat** and **Help** open one page with two tabs. Chat = Alt+A conversation (history + token bar + New chat / Save log + input + mic + send). Alt+A opens the Chat tab. Help tab placeholder for future Alt+H.
- Patreon button hidden for all header notifications and tips. Alerts override tips; recording_no_audio / recording_too_short → Ready + header only.

### Alpha 0.24.0 (March 2026)
- **Shortcuts Manager (sidebar):** New page to view and edit all hotkeys. Two columns per mode: **Hotkey (Alt)** and **Hotkey (AltGr)** with an Edit button each; conflicts are detected and a blinking alert is shown if a shortcut is already in use. **Restore Default Shortcuts** resets to factory defaults (instant display; Save & Restart to apply). Changes require **Save & Restart** in the sidebar.
- **Shortcuts — no trigger while editing:** When you click Edit to reprogram a shortcut, global hotkeys are **paused** until you press the new key or ESC. This prevents the current shortcut (e.g. AltGr+T) from firing while you are re-entering it.
- **Shortcuts — AltGr key capture:** Key capture uses the physical key (keycode) so that AltGr+T is stored correctly; with AltGr, the keysym is used for letter keys to avoid wrong character on some layouts.
- **Header tips at startup:** Tips now appear in the notification bar after launch (e.g. “Tip: Alt+T = Transcribe”, “Tip: Edit shortcuts in Shortcuts (sidebar)”) and rotate every few seconds. The tip cycle was previously not implemented; it is now wired and runs after startup alerts.

### Alpha 0.22.4 (March 2026)
- **Prompt Modes — Test Input samples:** You can select an empty sample (EN2, FR1, FR2, etc.): the pill lights up (gold) and the text box clears; Save then stores the current text in that slot. Fixes the case where EN2/FR1 stayed unlit and Save seemed to go to EN1.

### Alpha 0.22.3 (March 2026)
- **Appearance (Settings):** Golden border only on the avatar photo (no border around the whole cell). No layout shift when clicking skins; label text no longer changes on selection.

### Alpha 0.23.2 (March 2026) — Custom prompts (Alt+V/B/N) & test input save
- **Custom prompt modes:** Three new shortcuts **Alt+V**, **Alt+B**, **Alt+N** for **Custom prompt 1**, **Custom prompt 2**, **Custom prompt 3**. Edit the system prompt and test samples in Prompt Modes like any other mode.
- **Test input saved on Save:** For every mode (including custom), when you click **Save** (prompt), the current **test input** text is saved: it is stored in the active sample cell (EN1/EN2/FR1/FR2 — the one you last selected). All four sample cells are persisted to `Data/Configs/modes.yaml` so they survive restarts.
- **LLM error injection:** If the LLM fails (e.g. `400 Bad Request` due to Max input context), PerkySue injects a clear **⚠️ error message** at the cursor location (where the answer was supposed to be injected) instead of leaving you with nothing or misleading raw text. The GUI also shows a notification (and can play `llm_error` if present).

### Alpha 0.23.0 (March 2026) — Continuous conversation (Alt+A)
- **Conversation continue avec le modèle (Alt+A):** PerkySue permet désormais d'avoir une **conversation à plusieurs tours** avec le LLM chargé. Chaque nouvelle question est envoyée au modèle avec l'historique des questions/réponses précédentes ; tous les 8 échanges, un résumé de la conversation est généré et réinjecté dans le contexte pour les tours suivants. Vous pouvez enchaîner les questions de suivi (« explique ça », « et pour X ? ») sans perdre le fil.
- **Résumés Q/R dédiés:** Nouveau mode **Summarization of Q&A** (`summarize_qa`) dans les modes : résumé pensé pour un échange user/assistant (qui a demandé quoi, ce que l'assistant a apporté, noms et idées clés), utilisé pour les blocs PreviousAnswersSummary. Le mode Summarize classique (Alt+S) reste inchangé.
- **Contexte et modèle:** Contexte (résumés + 8 derniers Q/R) envoyé au LLM en system et en user pour une meilleure prise en compte. Certains modèles sont mieux adaptés que d'autres à ce type d'échange ; le catalogue des modèles recommandés peut indiquer `good_for_qa_conversation: true` pour les modèles conseillés (voir README et `App/configs/recommended_models.yaml`).
- **Config LLM lisible:** Dans les configs, **max_input_tokens** et **max_output_tokens** remplacent les noms ambigus `n_ctx` / `max_tokens` pour clarifier input (contexte) vs output (réponse).

### Alpha 0.22.2 (March 2026)
- **Prompt Modes samples:** Each LLM mode now has four editable test samples (EN1/EN2/FR1/FR2) stored in `App/configs/modes.yaml` (overridable in `Data/Configs/modes.yaml`). The Prompt Modes test panel shows a small “EN1 / EN2 / FR1 / FR2” selector bar; clicking a sample fills the Test input box for that mode, and if the box is empty the first available sample is auto-inserted.
- **Recording duration:** New **Max recording duration (s)** control in Settings → Performance. The default max duration depends on backend and STT model (CPU/Vulkan: 120 s for small, 90 s for medium; NVIDIA/CUDA: 180 s), and users can push up to 240 s. This timer is an app-side safety guard, not a Whisper context limit.
- **Recommended Models robustness:** If a configured LLM model has been deleted from `Data/Models/LLM/`, the Recommended Models section no longer shows it as “Current Model”; the config is cleaned up and the card goes back to “Get”, avoiding ghost models after manual file deletion.

### Alpha 0.22.1 (March 2026)
- **Prompt Modes tab:** Whisper Keywords (up to 5 words, Data), Identity & Preferences (Your Name → {user_name}), Prompt Modes per shortcut (edit prompt, Run Test, live preview). Work in progress.
- **Language handling:** Whisper-detected language passed to LLM and test panel; render_prompt no longer injects literal "auto"; robust placeholder substitution.

### Alpha 0.21.5 (March 2026)
- **Installer (install.bat):** Step [5/6] LLM library — on Vulkan (and any non-CPU / non-NVIDIA) backend, llama-cpp-python is **skipped** (message: "Skipping llama-cpp-python for backend vulkan (server mode only)"). Avoids endless pip backtracking and large downloads on AMD/Intel machines; PerkySue uses llama-server.exe in server mode. When installed (CPU or NVIDIA), version is pinned to `llama-cpp-python==0.3.16` to avoid resolver backtracking.
- **App/services/base.py:** New module that re-exports `STTProvider` and `TranscriptionResult` from `services.stt.base`. Fixes `ModuleNotFoundError: No module named 'services.base'` when `services/__init__.py` (or a deployment copy) imports from `.base`.
- **GUI (widget.py):** Method `_notify(message)` added so avatar click (stop recording / cancel processing) shows a short header notification and restores the normal title after 3 seconds.

### Alpha 0.21.4 (March 2026)
- **About tab:** New section "Why PerkySue exists" (before How It Works) with key messages and emphasis; comparison block renamed to "PerkySue vs. Competition"; prose in grey with bold accent/gold highlights; shorter "Other AI use cases" subtitle; prompt examples in white; responsive labels to fix truncation.
- **Footer:** Discord button added next to GitHub; both open in browser ([Discord](https://discord.gg/UaJHEzFgXy), [GitHub](https://github.com/PerkySue/PerkySue)); logos loaded with aspect ratio preserved, compact button size.
- **Docs:** README aligned with GUI About (Why PerkySue exists, use cases, PerkySue vs. Competition); Discord and community/support section added; version set to 0.21.4.

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

