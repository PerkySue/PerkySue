## Known issues (Beta 0.29.4)

- **Chatterbox multilingual (MTL) — stop/cancel not immediate during sampling**: on long non-English TTS generations, `Alt+Q` may stop playback but the MTL engine can keep sampling until the current internal step finishes. This is a limitation of the upstream engine API (no reliable cancel hook exposed in our integration yet).

