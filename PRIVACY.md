# PerkySue — Privacy Policy

## The short version

**Your voice and transcripts stay on your machine for dictation.** PerkySue does not upload audio or LLM prompts to PerkySue’s servers for the core product.

**If you use the Pro trial or a paid subscription** (when that flow is available), a **small amount of licensing data** is sent to **perkysue.com** (Cloudflare), **Stripe** (payments), and **Brevo** (transactional email such as device transfer). That is **separate** from voice processing and is described below.

---

## What PerkySue does NOT do (core dictation)

|                                | PerkySue core | Typical cloud dictation* |
|--------------------------------|---------------|---------------------------|
| Send audio to remote servers   | **Never**     | Yes                       |
| Store audio recordings on disk | **Never**     | Often                     |
| Send transcripts to PerkySue   | **Never**     | N/A                       |
| Use cookies/tracking in-app    | **No**        | Often in web apps         |
| Train models on your voice     | **Never**     | Sometimes                 |

*Illustrative comparison only.

See also [README.md](README.md) and [ARCHITECTURE.md](ARCHITECTURE.md) for how local processing works.

---

## What happens to your voice (core product)

1. You press a hotkey — PerkySue listens through your microphone.  
2. Audio lives in RAM — not written to disk for retention.  
3. Whisper and the LLM run **locally**.  
4. Text is injected or shown in-app; audio buffers are discarded.  

This path does **not** depend on PerkySue-operated servers.

---

## Text selection & clipboard

When you select text before a hotkey, PerkySue briefly uses the clipboard to read the selection, then restores your previous clipboard. That happens **locally** only.

---

## Pro trial, subscription, and optional network calls

When **post-alpha licensing** is enabled, the following **does not replace** the rules above: **your voice is still not uploaded** for dictation. These services handle **billing and entitlement** only.

### What is sent

| Data | Where | Why |
|------|--------|-----|
| **Email** (trial) | Cloudflare Worker + optional Brevo | One trial per email; transactional messages if you enable them. |
| **install_id** (UUID from `Data/Configs/install.id` when the app creates that file) | Worker | Ties your folder to a subscription record when present in checkout metadata (`install:…` in KV). **The file is specified to contain only the UUID — not your PC name** (hostname is sent separately to `/check` in the target design). **Web-only checkout** (no `install_id`) still sends billing data to **Stripe**; the Worker may store subscription state under a **`sub:…`** key until you link an installation — see the App↔Worker contract in this repository. |
| **Windows computer name** (`COMPUTERNAME`) | Worker | **One device seat** for MVP: stops trivial sharing of the same folder across many PCs. Same PC + USB stick → same name → still works. |
| **Payment details** | **Stripe** | Checkout and subscription; PerkySue does not receive your full card number on its own servers. |
| **IP address** | Worker (short retention) | **Abuse and security** (e.g. unusual volumes). Not used for advertising profiles. Retention kept **short** and **minimal**; exact duration should match what you configure at deploy time and can be stated here when fixed. |
| **OTP / transfer emails** | **Brevo** | Moving your seat to a new PC after you prove control of the **Stripe** email. |

### What is never sent for dictation

- Audio recordings  
- Whisper output as a “telemetry” stream  
- LLM chat content to PerkySue for cloud inference (the product is local LLM)

### Open source caveat

PerkySue is **Apache 2.0**. A developer can modify the client. The licensing model targets **honest use** and **casual abuse** (e.g. sharing one folder to many machines), not unbreakable DRM.

---

## Other network use (setup & updates)

- **`install.bat`** — may contact **python.org** (embedded runtime zip), **bootstrap.pypa.io** (get-pip), **PyPI** (pip packages), and **GitHub** (llama.cpp **llama-server** release zips via bundled scripts). If you bundle zips under **`Assets\`** or **`Data\Cache\`**, repeat installs can stay offline for those steps.  
- **Whisper (STT)** — model weights are typically downloaded on **first run** (e.g. from Hugging Face or the configured source), not “phoned home” to PerkySue for dictation.  
- **LLM (.gguf)** — downloads from **Settings → Recommended Models** or manual placement; the app may also start a **first-run** default model fetch from **Hugging Face** when no GGUF is present (see in-repo `installer_default_models.yaml`).  
- **Optional tooling** — e.g. `App/tools/download_model.py` for developers.  

These flows are **software distribution and local AI weights**, not PerkySue “phone-home” analytics or voice telemetry.

---

## What PerkySue stores on disk (typical)

| Item | Location | Purpose |
|------|-----------|---------|
| Models | `Data/Models/` | STT / LLM weights |
| Config | `Data/Configs/` | Settings, `install.id`, optional `license.json` / `trial.json` |
| Logs | `Data/Logs/` | **Local** debugging only unless you share them |

---

## Stripe & Brevo

- **Stripe** privacy: [https://stripe.com/privacy](https://stripe.com/privacy)  
- **Brevo** privacy: see Brevo’s policy for transactional email.  

PerkySue uses them as **processors** for payment and email, not for selling your dictation content.

---

## Summary

| Question | Answer |
|----------|--------|
| Is my voice sent to PerkySue? | **No**, for dictation. |
| Is my voice stored on disk? | **No** (RAM-only processing for audio). |
| Do I need the internet for Alt+T? | **No**, after models are installed. |
| Does Pro trial/subscription send data? | **Yes — limited licensing data** (email, install ID, device name, payment via Stripe) as above. **Not** your transcripts for STT/LLM. |
| Can I read the client code? | **Yes** — Apache 2.0. |

---

## AI Output Disclaimer

PerkySue uses locally running AI models (speech-to-text via Whisper, text generation via llama.cpp) to process your voice and generate text. These models run entirely on your machine — no data is sent to any server for processing.

However, AI models can and do produce outputs that are inaccurate, incomplete, misleading, biased, or inappropriate. This includes but is not limited to factual errors, fabricated information, inappropriate language, and outputs that may not reflect your intent.

PerkySue is a tool that executes your instructions using third-party open source AI models. Neither PerkySue, its creator Jérôme Corbiau, Paradoxe Productions SRL, nor any contributor to this project can be held responsible for the content generated by these models. The user is solely responsible for reviewing, editing, and validating any output before using it — whether injected at the cursor, spoken aloud via TTS, or displayed in the application.

By using PerkySue, you acknowledge that AI-generated content requires human verification and that you use all outputs at your own risk.

Created by Jérôme Corbiau · Licensed under Apache 2.0  

*Last updated: April 2026 — licensing section aligned with current release notes (Stripe, hostname seat, sliding `license.json`, trial OTP). Setup/network bullets updated for embedded **`install.bat`** (python.org, PyPI, GitHub releases) and Hugging Face for model downloads.*
