Model brand icons for the Recommended Models section (Settings → GUI).
Place 256×256 PNG files here, one per model family (no icon per parameter size).

Naming examples (used by recommended_models.yaml field icon_file):
  - By family: gemma.png, qwen.png, mistral.png, llama.png, deepseek.png, glm.png, grok.png
  - Layer-1 / base models (single brand, not hybrids): LFM.png (LiquidAI), Phi.png (Microsoft).

Fallback for mix / hybrid / abliterated models (no single brand):
  - hybrid.png   — only for models that blend families (e.g. Mistral+Gemma). Not for LFM or Phi.
  - If icon_file is missing or file absent, GUI falls back to the letter (icon: "G", "Q", etc.).

In recommended_models.yaml:
  icon_file: "gemma.png"   # family logo
  icon_file: "hybrid.png"  # for mix/abliterated models (optional)

Icons are displayed scaled in the model card (e.g. 46×46 px in the UI).
