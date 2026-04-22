"""
Orchestrateur PerkySue — le cerveau de l'application.
Version portable: tous les chemins passent par l'objet Paths.
"""

import json
import queue
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import yaml

from paths import Paths
from services.stt import create_stt_provider, STTProvider
from services.llm import create_llm_provider, LLMProvider
from modes import load_modes, render_prompt, Mode
from modes.voice_modes import load_voice_mode_overlays
from utils.audio import AudioRecorder, BaseAudioCapture, build_audio_recorder
from utils.hotkeys import HotkeyManager, resolve_hotkey_string, format_hotkey_display
from utils.injector import inject_text, get_active_window, grab_selection, get_window_title, restore_window
from utils.nvidia_stats import get_nvidia_smi_snapshot
from utils.sounds_manager import SoundManager
from utils.strings import s as i18n_s
from utils.voice_payload import split_voice_payload_reply
from utils.skin_paths import normalize_skin_id
from utils.plugin_host import load_plugin_module
from services.tts import TTSManager
from services.tts.chatterbox_tts import (
    clear_blank_cuda_visible_devices,
    normalize_speech_lang,
    speech_language_display_name_en,
)

logger = logging.getLogger("perkysue")

# In-app Help redirect: skip the extra intent-router LLM call for long pasted text without the app name
# (avoids back-to-back heavy requests that can destabilize llama-server; typed Chat often contains "LLM"/STT).
_IN_APP_HELP_ROUTER_SKIP_LEN = 750
# Router only needs the start of the message to classify HELP vs NOHELP.
_HELP_INTENT_ROUTER_TEXT_CAP = 800


def _document_injection_llm_error_message(widget: Any, llm_error_msg: str) -> str:
    """User-facing LLM error for chat / injection: 400 vs transport vs generic.

    Connection drops (e.g. llama-server crash, WinError 10054) must not suggest raising Max input.
    """
    err = llm_error_msg or ""
    if "400" in err or "Bad Request" in err:
        if widget is not None and hasattr(widget, "_get_alert"):
            return str(widget._get_alert("document_injection.llm_error_400"))
        return "LLM error (400) — context too large? Increase Max input (context) in Settings."
    low = err.lower()
    if any(
        n in low
        for n in (
            "connection aborted",
            "connection reset",
            "connection refused",
            "remote end closed",
            "broken pipe",
            "10054",
            "10061",
            "forcibly closed",
        )
    ):
        if widget is not None and hasattr(widget, "_get_alert"):
            return str(widget._get_alert("document_injection.llm_error_connection"))
        return (
            "LLM server connection lost — the model process may have crashed or restarted. "
            "This is not a context limit. Try again; if it repeats, restart PerkySue."
        )
    if widget is not None and hasattr(widget, "_get_alert"):
        return str(widget._get_alert("document_injection.llm_error_generic"))
    return "LLM error — check console. Increase Max input (context) in Settings if using Alt+A."


def skin_character_display_name(skin_active: str) -> Optional[str]:
    """Character / avatar name (canonical id ``Character/Locale`` → Character)."""
    s = (skin_active or "").strip() or "Default"
    if s == "Default":
        return None
    if "/" in s:
        head, _ = s.split("/", 1)
        return head.strip() if head.strip() else None
    return s or None


class Orchestrator:
    def __init__(self, paths: Paths):
        self.paths = paths
        # Internal: optional extension module under Data/Plugins/dev/.
        # Must exist before config normalization (which may query tier gating).
        self._dev_plugin_mod: Optional[Any] = None
        self._dev_plugin_loaded: bool = False
        self._avatar_editor_plugin_mod: Optional[Any] = None
        self._avatar_editor_plugin_loaded: bool = False
        self._brainstorm_plugin_mod: Optional[Any] = None
        self._brainstorm_plugin_loaded: bool = False
        self._voice_mode_overlays = load_voice_mode_overlays(
            self.paths.voice_modes_file,
            self.paths.user_voice_modes_file,
        )
        logger.info(
            "voice_modes: %d mode overlays (bundled %s; Data override %s)",
            len(self._voice_mode_overlays),
            self.paths.voice_modes_file.name,
            self.paths.user_voice_modes_file.name
            if self.paths.user_voice_modes_file.exists()
            else "none",
        )

        # Load config: system defaults merged with user overrides
        self.config = self._load_merged_config()
        self._effective_llm_n_ctx: int = 2048
        self._effective_llm_max_output: int = 2048
        self._recompute_effective_llm_context()
        self._sync_strings_locale_from_config()

        # Inject portable paths for providers
        stt_conf = self.config.get("stt", {})
        stt_conf["_models_dir"] = str(paths.models_whisper)
        stt_conf["_cache_dir"] = str(paths.huggingface)

        llm_conf = self.config.get("llm", {})
        llm_conf["_models_dir"] = str(paths.models_llm)

        self._is_recording = False
        self._is_processing = False  # True during _process_audio (STT+LLM+inject) — blocks new mode shortcuts
        self._cancel_requested = False
        self._lock = threading.Lock()
        self._current_mode: Optional[str] = None
        self._target_window = None  # Handle de la fenêtre active au moment du hotkey
        self._last_inject_payload: Optional[str] = None  # Dernier texte injecté (hors Help) — raccourci reinject_last
        self._suppress_mode_hotkeys_until: float = 0.0
        self._continuous_chat_enabled: bool = False
        self._continuous_chat_thread: Optional[threading.Thread] = None
        self._continuous_tts_cooldown_until: float = 0.0
        # True while a Tk after(0) callback will call play_prepared (worker thread finished before UI ran it).
        self._continuous_gui_tts_pending: bool = False
        self.last_stt_text = ""   # Dernière transcription Whisper (pour page Console)
        self.last_llm_text = ""   # Dernier texte produit par le LLM (pour page Console)
        self.last_llm_reasoning = ""  # Raisonnement séparé (API) — Console uniquement, jamais injecté
        # Code ISO renvoyé par Whisper (détection ou langue forcée) — réutilisé pour le LLM et le panneau Test
        self.last_stt_detected_language: Optional[str] = None

        # Answer mode (Alt+A) history: list of {"q": question, "a": answer}
        self._answer_history: list[dict] = []
        # Number of most recent Q/A kept in context; summary cadence follows this value.
        self._answer_context_n_qa = self._answer_context_keep_from_config(self.config)
        # Help mode (Alt+H) history: list of {"q": question, "a": answer} for the Help tab
        self._help_history: list[dict] = []
        # Summaries of previous answers: list of {"end_index": int, "text": str}
        # Summary k couvre les paires (end_index-7)→end_index, 1-based.
        self._answer_summaries: list[dict] = []
        # When True, Chat tab token bar shows full (max_ctx) so it matches the "context limit reached" alert
        self._answer_context_limit_reached: bool = False
        # When True, Help tab token bar shows full (max_ctx) so it matches truncation alert
        self._help_context_limit_reached: bool = False
        self.stt: Optional[STTProvider] = None
        self.llm: Optional[LLMProvider] = None
        self.recorder: Optional[BaseAudioCapture] = None
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.modes: dict[str, Mode] = {}

        # Skin & Audio manager
        skin_config = self.config.get("skin", {})
        audio_config = self.config.get("audio", {})
        
        self.sound_manager = SoundManager(
            paths=self.paths,
            skin=skin_config.get("active", "Default"),
            volume=audio_config.get("volume", 1.0)
        )

        # TTS (Pro, opt-in — pas de téléchargement tant que l'utilisateur n'installe pas depuis l'onglet Voice)
        self.tts_manager = TTSManager(
            models_dir=self.paths.models_tts,
            cache_dir=self.paths.huggingface,
            paths=self.paths,
        )
        self.tts_manager.load_config(self.config.get("tts", {}))
        self.tts_manager.scan_voice_packs()
        _skin_act = (self.config.get("skin") or {}).get("active", "Default")
        self.tts_manager.on_skin_changed(_skin_act if isinstance(_skin_act, str) else "Default")
        if self.tts_manager.is_installed():
            try:
                self.tts_manager.load_engine()
            except Exception as e:
                logger.warning("TTS engine load at boot failed (non-fatal): %s", e)

        self._rebuild_audio_recorder_from_config()

        # Updates (GitHub public releases) — cached per process/session
        self._update_cache: Optional[dict] = None
        self._update_cache_time: float = 0.0
        self._pending_post_update_info: Optional[dict] = self._read_post_update_marker()
        self._post_update_install_started: bool = False
        self._post_update_install_reason: str = ""

        # Deterministic TTS registry maintenance (safe, local-only migration from existing HF cache).
        try:
            mig = self.tts_manager.run_startup_maintenance()
            if mig:
                logger.info("TTS registry startup maintenance: %s", mig)
        except Exception as e:
            logger.warning("TTS registry startup maintenance failed: %s", e)
        try:
            self._run_pending_post_update_tasks()
        except Exception as e:
            logger.warning("Post-update tasks failed: %s", e)

    def _load_merged_config(self) -> dict:
        """
        Load config by deep-merging system defaults with user overrides.

        App/configs/defaults.yaml  = factory settings (shipped with updates)
        Data/Configs/config.yaml   = user preferences (never overwritten)

        User values override defaults. Missing user values fall back to defaults.
        """
        # Load system defaults
        defaults = {}
        if self.paths.defaults_file.exists():
            with open(self.paths.defaults_file, "r", encoding="utf-8") as f:
                defaults = yaml.safe_load(f) or {}

        # Load user overrides
        user = {}
        if self.paths.user_config_file.exists():
            with open(self.paths.user_config_file, "r", encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}

        # Deep merge: user overrides defaults
        merged = self._deep_merge(defaults, user)
        # Normalize LLM keys so max_input_tokens/max_output_tokens and n_ctx/max_tokens stay in sync
        self._normalize_llm_config(merged)
        self._normalize_audio_config(merged)
        self._normalize_feedback_config(merged)
        self._union_tts_trigger_modes(merged, defaults)
        return merged

    def _normalize_audio_config(self, config: dict) -> None:
        """Normalize audio config and enforce Free-tier STT source policy."""
        audio = config.get("audio")
        if not isinstance(audio, dict):
            audio = {}
            config["audio"] = audio
        raw_mode = str(audio.get("capture_mode") or "mic_only").strip().lower()
        if raw_mode not in ("mic_only", "system_only", "mix"):
            raw_mode = "mic_only"
        # Security/gating hard lock: Free users must stay on mic_only even if config file is edited.
        if (not self.is_effective_pro()) and raw_mode != "mic_only":
            logger.warning(
                "Free tier capture_mode override blocked: requested=%s -> enforced=mic_only",
                raw_mode,
            )
            raw_mode = "mic_only"
        audio["capture_mode"] = raw_mode

    # ── Updates (GitHub public releases) ─────────────────────
    def _parse_version_tuple(self, v: str) -> Tuple[int, int, int]:
        raw = (v or "").strip()
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
        if not m:
            return (0, 0, 0)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def _current_app_semver(self) -> str:
        v = getattr(self, "APP_VERSION", "") or ""
        m = re.search(r"(\d+\.\d+\.\d+)", v)
        return m.group(1) if m else ""

    def _github_request_json(self, url: str) -> Any:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"PerkySueDesktop/{self._current_app_semver() or '0.0.0'}",
            },
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _pick_zip_from_assets(self, assets: Any) -> Tuple[str, str]:
        """Pick best ``browser_download_url`` from release assets (prefer app-style bundles)."""
        zips: List[Tuple[str, str]] = []
        for a in assets or []:
            try:
                name = str((a or {}).get("name") or "")
                dl = str((a or {}).get("browser_download_url") or "")
            except Exception:
                continue
            if not dl or not name or not name.lower().endswith(".zip"):
                continue
            zips.append((name, dl))
        if not zips:
            return "", ""
        prefs = ("perkysue", "windows", "desktop", "bundle", "full", "app", "portable")
        for pref in prefs:
            for name, dl in zips:
                if pref in name.lower():
                    return dl, name
        return zips[0][1], zips[0][0]

    def _post_update_marker_path(self) -> Path:
        return self.paths.cache / "updates" / "post_update_pending.json"

    def _read_post_update_marker(self) -> Optional[dict]:
        p = self._post_update_marker_path()
        if not p.is_file():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _write_post_update_marker(self, payload: dict) -> None:
        p = self._post_update_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    def _clear_post_update_marker(self) -> None:
        p = self._post_update_marker_path()
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    def _run_pending_post_update_tasks(self) -> None:
        marker = self._pending_post_update_info or self._read_post_update_marker()
        if not marker:
            return
        logger.info("Post-update tasks detected: %s", marker)
        tasks = marker.get("tasks") if isinstance(marker, dict) else None
        if not isinstance(tasks, list):
            tasks = []
        done: Dict[str, str] = {}
        if "tts_registry_migration" in tasks:
            try:
                status = self.tts_manager.run_startup_maintenance()
                done["tts_registry_migration"] = f"ok:{status}"
            except Exception as e:
                done["tts_registry_migration"] = f"error:{e}"
        if "runtime_consistency_check" in tasks:
            try:
                status = self._run_post_update_runtime_consistency_check(marker)
                done["runtime_consistency_check"] = status
            except Exception as e:
                done["runtime_consistency_check"] = f"error:{e}"
        self._clear_post_update_marker()
        logger.info("Post-update tasks completed: %s", done)

    def get_model_registry_status(self) -> Dict[str, Any]:
        """Diagnostic helper for About/Support."""
        try:
            return self.tts_manager.get_model_registry_status()
        except Exception as e:
            return {"error": str(e)}

    def _run_post_update_runtime_consistency_check(self, marker: dict) -> str:
        """Post-update targeted runtime checks with install.bat fallback trigger.

        We do not run install.bat on every update. We only trigger it when critical
        runtime pieces are missing/incompatible for this installation.
        """
        root = self.paths.root
        install_bat = root / "install.bat"
        python_exe = self.paths.python_dir / "python.exe"
        backend = (os.environ.get("PERKYSUE_BACKEND") or "").strip().lower() or "cpu"
        backend_bin = self.paths.data / "Tools" / backend / "llama-server.exe"

        missing: List[str] = []
        if not backend_bin.is_file():
            missing.append(f"backend_missing:{backend}")
        if not python_exe.is_file():
            missing.append("python_missing")
        else:
            try:
                # Keep this probe aligned with runtime-critical modules used after updates.
                dep_mods = [
                    "yaml",
                    "numpy",
                    "requests",
                    "pygame",
                    "faster_whisper",
                    "psutil",
                    "webrtcvad",
                ]
                try:
                    audio_cfg = (self.config or {}).get("audio") or {}
                    capture_mode = str(audio_cfg.get("capture_mode") or "mic_only").strip().lower()
                except Exception:
                    capture_mode = "mic_only"
                # PyAudioWPatch is required for WASAPI loopback paths.
                if sys.platform == "win32" and capture_mode in ("system_only", "mix"):
                    dep_mods.append("pyaudiowpatch")
                dep_stmt = ",".join(dep_mods)
                logger.info(
                    "Post-update runtime dependency probe: capture_mode=%s, required=%s",
                    capture_mode,
                    dep_stmt,
                )
                dep_probe = subprocess.run(
                    [
                        str(python_exe),
                        "-c",
                        f"import {dep_stmt}; print('ok')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                if dep_probe.returncode != 0:
                    logger.warning(
                        "Post-update runtime dependency probe failed (rc=%s): %s",
                        dep_probe.returncode,
                        (dep_probe.stderr or dep_probe.stdout or "").strip()[:500],
                    )
                    missing.append("python_deps_incomplete")
            except Exception:
                missing.append("python_dep_probe_failed")

        if not missing:
            return "ok"

        latest_v = str((marker or {}).get("latest_version") or "").strip() or "unknown"
        fail_marker = self.paths.cache / "updates" / f"post_update_runtime_issue_{latest_v}.json"
        try:
            fail_marker.parent.mkdir(parents=True, exist_ok=True)
            fail_marker.write_text(
                json.dumps(
                    {
                        "latest_version": latest_v,
                        "issues": missing,
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "suggested_action": "run_install_bat",
                    },
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        if install_bat.is_file():
            self._post_update_install_reason = ",".join(missing)
            try:
                cmd = f'cmd /c start "" "{install_bat}"'
                subprocess.Popen(cmd, shell=True, cwd=str(root))
                self._post_update_install_started = True
                logger.warning(
                    "Post-update runtime check detected issues (%s). Auto-launching install.bat and requesting app exit.",
                    ", ".join(missing),
                )
                return f"auto_install_started:{','.join(missing)}"
            except Exception as e:
                logger.warning(
                    "Post-update runtime check detected issues (%s) but could not auto-launch install.bat: %s",
                    ", ".join(missing),
                    e,
                )
                return f"needs_install_bat:{','.join(missing)}"

        return f"runtime_issues_no_install_bat:{','.join(missing)}"

    def _max_semver_from_git_tags(self, repo: str) -> Optional[Tuple[Tuple[int, int, int], str, str]]:
        """Return (version_tuple, semver_str, tag_name) for the newest tag whose name contains a semver."""
        try:
            tags = self._github_request_json(
                f"https://api.github.com/repos/{repo}/tags?per_page=100"
            )
        except Exception:
            return None
        if not isinstance(tags, list):
            return None
        best_t = (0, 0, 0)
        best_sem = ""
        best_name = ""
        for t in tags:
            name = str((t or {}).get("name") or "").strip()
            if not name:
                continue
            m = re.search(r"(\d+\.\d+\.\d+)", name)
            if not m:
                continue
            tup = self._parse_version_tuple(m.group(1))
            if tup > best_t:
                best_t = tup
                best_sem = m.group(1)
                best_name = name
        if best_t == (0, 0, 0):
            return None
        return (best_t, best_sem, best_name)

    def check_updates_from_github(self) -> dict:
        """Return update info from GitHub (releases + optional tag zipball). Cached a few minutes."""
        try:
            if self._update_cache and (time.monotonic() - float(self._update_cache_time or 0.0)) < 300:
                return dict(self._update_cache)
        except Exception:
            pass

        raw_repo = (os.environ.get("PERKYSUE_UPDATE_REPO") or "PerkySue/PerkySue").strip().strip("/")
        repo = raw_repo if "/" in raw_repo else "PerkySue/PerkySue"
        api = f"https://api.github.com/repos/{repo}"
        cur = self._current_app_semver()
        cur_t = self._parse_version_tuple(cur)

        try:
            meta = self._github_request_json(api)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {
                    "error": f"GitHub repository not found (check PERKYSUE_UPDATE_REPO): {repo}",
                    "repo": repo,
                    "current_version": cur or getattr(self, "APP_VERSION", ""),
                    "latest_version": "",
                    "tag": "",
                    "html_url": f"https://github.com/{repo}",
                    "zip_url": "",
                    "zip_name": "",
                    "update_available": False,
                }
            return {
                "error": f"GitHub API HTTP {e.code}",
                "repo": repo,
                "current_version": cur or getattr(self, "APP_VERSION", ""),
                "latest_version": "",
                "tag": "",
                "html_url": f"https://github.com/{repo}",
                "zip_url": "",
                "zip_name": "",
                "update_available": False,
            }
        except Exception as e:
            return {
                "error": str(e),
                "repo": repo,
                "current_version": cur or getattr(self, "APP_VERSION", ""),
                "latest_version": "",
                "tag": "",
                "html_url": f"https://github.com/{repo}",
                "zip_url": "",
                "zip_name": "",
                "update_available": False,
            }

        html_base = str((meta or {}).get("html_url") or f"https://github.com/{repo}")

        releases: list = []
        try:
            rel = self._github_request_json(f"{api}/releases?per_page=35")
            if isinstance(rel, list):
                releases = rel
        except urllib.error.HTTPError:
            releases = []
        except Exception:
            releases = []

        best_t = (0, 0, 0)
        best_semver = ""
        best_tag = ""
        for rel in releases:
            tag = str((rel or {}).get("tag_name") or "").strip()
            m = re.search(r"(\d+\.\d+\.\d+)", tag)
            if m:
                t = self._parse_version_tuple(m.group(1))
                if t > best_t:
                    best_t = t
                    best_semver = m.group(1)
                    best_tag = tag

        gt = self._max_semver_from_git_tags(repo)
        if gt:
            gt_t, gt_sv, gt_nm = gt
            if gt_t > best_t:
                best_t = gt_t
                best_semver = gt_sv
                best_tag = gt_nm

        zip_url = ""
        zip_name = ""
        for rel in releases:
            u, n = self._pick_zip_from_assets((rel or {}).get("assets"))
            if u:
                zip_url, zip_name = u, n
                break

        if not zip_url and best_tag and best_semver:
            zip_url = f"https://github.com/{repo}/archive/refs/tags/{quote(best_tag, safe='')}.zip"
            zip_name = f"{best_tag}.zip"

        update_available = bool(best_semver and best_t > cur_t)

        if update_available and not zip_url:
            out = {
                "error": (
                    f"Version {best_semver} exists on GitHub but no .zip download was found. "
                    "Publish a Release with a .zip that contains the App/ folder, or push a git tag "
                    f"so the archive https://github.com/{repo}/archive/refs/tags/… can be used."
                ),
                "repo": repo,
                "current_version": cur or getattr(self, "APP_VERSION", ""),
                "latest_version": best_semver,
                "tag": best_tag,
                "html_url": releases and str((releases[0] or {}).get("html_url") or "") or html_base,
                "zip_url": "",
                "zip_name": "",
                "update_available": False,
            }
            return out

        if not best_semver:
            out = {
                "error": (
                    "No GitHub Release or version tag was found for this repository. "
                    "GitHub’s “latest release” API returns 404 until at least one Release exists; "
                    "push a tag whose name includes the version (e.g. v0.29.0) or publish a Release with a .zip asset."
                ),
                "repo": repo,
                "current_version": cur or getattr(self, "APP_VERSION", ""),
                "latest_version": "",
                "tag": "",
                "html_url": html_base,
                "zip_url": "",
                "zip_name": "",
                "update_available": False,
            }
            return out

        rel_html = ""
        if releases:
            rel_html = str((releases[0] or {}).get("html_url") or "")

        out = {
            "repo": repo,
            "current_version": cur or getattr(self, "APP_VERSION", ""),
            "latest_version": best_semver,
            "tag": best_tag,
            "html_url": rel_html or html_base,
            "zip_url": zip_url,
            "zip_name": zip_name,
            "update_available": update_available,
        }
        try:
            self._update_cache = dict(out)
            self._update_cache_time = time.monotonic()
        except Exception:
            pass
        return out

    def _sync_portable_root_from_bundle(self, bundle_root: Path, dst_root: Path) -> None:
        """Copy launcher/docs from release root (sibling of App/ in zip) onto portable root.

        Keeps install.bat / start.bat / other *.bat and *.md (CHANGELOG, README, …) aligned
        with the shipped version. Only regular files at bundle root; no directories (no Data/Python).
        """
        import shutil

        if not bundle_root.is_dir():
            return
        for src in bundle_root.iterdir():
            if not src.is_file():
                continue
            name = src.name
            low = name.lower()
            suf = src.suffix.lower()
            if suf not in (".bat", ".md") and low not in ("license", "license.txt"):
                continue
            dst_f = dst_root / name
            try:
                shutil.copy2(str(src), str(dst_f))
            except Exception:
                try:
                    shutil.copy(str(src), str(dst_f))
                except Exception:
                    pass

    def download_and_stage_app_update(self, info: dict, progress_cb=None) -> Tuple[bool, str]:
        """Download latest zip, extract, overwrite App/ and portable-root *.bat / *.md / LICENSE."""
        dl_url = (info or {}).get("zip_url") or ""
        if not dl_url:
            return False, "No downloadable .zip asset found on the latest GitHub release."
        latest_v = (info or {}).get("latest_version") or ""
        cache_dir = self.paths.cache / "updates" / (str(latest_v) or "latest")
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        zip_path = cache_dir / "update.zip"

        def _progress(p: float, t: str = ""):
            try:
                if progress_cb:
                    progress_cb(p, t)
            except Exception:
                pass

        _progress(0.08, i18n_s("about.updates.body_downloading", default="Downloading update…"))
        ua = f"PerkySueDesktop/{self._current_app_semver() or '0.0.0'}"
        req = urllib.request.Request(dl_url, method="GET", headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=90) as resp, open(zip_path, "wb") as f:
            total = int(resp.headers.get("Content-Length") or "0") or 0
            read = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if total > 0:
                    _progress(0.08 + 0.62 * (read / total), i18n_s("about.updates.body_downloading", default="Downloading update…"))

        _progress(0.72, "Extracting…")
        import zipfile
        import shutil

        extract_dir = cache_dir / "extracted"
        try:
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            zf.extractall(str(extract_dir))

        app_src = None
        if (extract_dir / "App").exists():
            app_src = extract_dir / "App"
        else:
            for p in extract_dir.glob("**/App"):
                if p.is_dir():
                    app_src = p
                    break
        if app_src is None:
            return False, "Update zip does not contain an App/ folder."

        bundle_root = app_src.parent
        app_dst = self.paths.app_dir
        _progress(0.78, "Installing App/…")
        for root, _dirs, files in os.walk(str(app_src)):
            rel = os.path.relpath(root, str(app_src))
            dst_root = app_dst / rel if rel != "." else app_dst
            dst_root.mkdir(parents=True, exist_ok=True)
            for fn in files:
                src_f = Path(root) / fn
                dst_f = dst_root / fn
                try:
                    shutil.copy2(str(src_f), str(dst_f))
                except Exception:
                    try:
                        shutil.copy(str(src_f), str(dst_f))
                    except Exception:
                        pass

        _progress(0.90, "Updating launcher & docs…")
        try:
            self._sync_portable_root_from_bundle(bundle_root, self.paths.root)
        except Exception:
            pass

        try:
            self._write_post_update_marker(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "latest_version": str(latest_v or ""),
                    "tasks": [
                        "tts_registry_migration",
                        "runtime_consistency_check",
                    ],
                }
            )
        except Exception:
            pass

        _progress(1.0, i18n_s("about.updates.body_ready_restart", default="Update installed. Restart to apply."))
        return True, i18n_s("about.updates.body_ready_restart", default="Update installed. Restart to apply.")

    def clear_answer_context(self) -> None:
        """Vide l'historique Answer (Q/A) et les résumés. Appelé par « New chat » pour ne plus envoyer les anciennes questions au LLM."""
        self._answer_history.clear()
        self._answer_summaries.clear()
        self._answer_context_limit_reached = False

    def clear_help_context(self) -> None:
        """Vide l'historique Help (Q/A) pour l'onglet Help."""
        self._help_history.clear()
        self._help_context_limit_reached = False

    def _translate_user_short_prompt(self, text: str, lang_code: str) -> str:
        """Translate a short *user* message into the target language (first person).
        Used for locked-mode redirects so the Help bubble ('q') is localized for any ISO language.
        Returns original text on failure or when translation is unnecessary.

        NOTE (Alpha 0.28.x):
        Local GGUF models are sometimes chatty (echoes, markdown, preambles). Even with
        robust parsing, translating the *exact* user bubble text ("q" in Help) may still
        fail occasionally. In that case we keep the original bubble text to avoid breaking UX;
        the Help answer itself remains driven by `source_lang`.
        """
        if not text:
            return text
        try:
            llm = getattr(self, "llm", None)
            if not llm or not llm.is_available():
                return text
            if not lang_code:
                return text

            lang = (lang_code or "en").strip().lower()[:2]
            if lang.startswith("en"):
                return text

            lang_names = {
                "fr": "French",
                "de": "German",
                "es": "Spanish",
                "it": "Italian",
                "pt": "Portuguese",
                "nl": "Dutch",
                "pl": "Polish",
                "ru": "Russian",
                "ja": "Japanese",
                "zh": "Chinese",
                "ko": "Korean",
                "ar": "Arabic",
                "hi": "Hindi",
                "tr": "Turkish",
                "sv": "Swedish",
                "da": "Danish",
                "no": "Norwegian",
                "fi": "Finnish",
                "el": "Greek",
                "cs": "Czech",
                "hu": "Hungarian",
                "ro": "Romanian",
            }
            lang_name = lang_names.get(lang, f"language code '{lang}'")

            def _attempt(system_prompt: str) -> str:
                result = llm.process(
                    text=text,
                    system_prompt=system_prompt,
                    temperature=0.0,
                    max_tokens=160,
                )
                raw = self._strip_thinking_blocks((getattr(result, "text", None) or "").strip())
                if not raw:
                    return ""
                logger.info("TRANSLATE raw(target=%s): %d chars (content not logged)", lang, len(raw))

                import re
                text_norm = text.strip().lower()

                # 1) Nettoyer le markdown AVANT toute logique
                cleaned = re.sub(r"\*{1,3}", "", raw)  # bold / italic
                cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)  # headers
                cleaned = re.sub(r"^[\-|=]{3,}$", "", cleaned, flags=re.MULTILINE)  # hr / table seps

                # 2) Supprimer les lignes "meta" (préfixes courants des LLM bavards)
                meta_re = re.compile(
                    r"^\s*(traducción|translation|traduction|verification|"
                    r"verificación|here is|voici|aquí está)\s*[:：]?\s*$",
                    re.IGNORECASE,
                )

                lines: list[str] = []
                for line in cleaned.splitlines():
                    stripped = line.strip().strip('"').strip("'").strip("`").strip()
                    if not stripped:
                        continue
                    if stripped.lower() == text_norm:  # écho anglais
                        continue
                    if meta_re.match(stripped):
                        continue
                    lines.append(stripped)

                # 3) Prendre la dernière ligne non-écho (traduction souvent après écho/meta)
                for candidate in reversed(lines):
                    candidate = re.sub(r"\s+", " ", candidate).strip()
                    if candidate and len(candidate) <= 300:
                        logger.info("TRANSLATE accepted(target=%s): %d chars (content not logged)", lang, len(candidate))
                        return candidate

                logger.info("TRANSLATE nothing left after cleanup(target=%s)", lang)
                return ""

            system_prompt_1 = (
                "You are a professional translator.\n"
                f"TARGET LANGUAGE: {lang_name} ({lang}).\n"
                "Translate the user's message into the target language.\n"
                "Rules:\n"
                "- Use FIRST PERSON.\n"
                "- Keep meaning exactly.\n"
                "- Keep hotkeys and mode labels exactly as written; DO NOT translate words inside single quotes.\n"
                "- Return ONLY the translated sentence (no markdown, no explanations, no echo)."
            )
            translated = _attempt(system_prompt_1)

            # Retry: if we got the original back (English leak), try again with stricter wording.
            if not translated or translated == text:
                system_prompt_2 = (
                    "Strict translation mode.\n"
                    f"TARGET LANGUAGE: {lang_name} ({lang}).\n"
                    "Translate into the target language.\n"
                    "Rules:\n"
                    "- Use FIRST PERSON.\n"
                    "- Never output English.\n"
                    "- Keep hotkeys/mode labels exactly.\n"
                    "- Return ONLY the translated sentence (no markdown, no explanations, no echo)."
                )
                translated = _attempt(system_prompt_2)

            if translated and translated != text:
                logger.info(
                    "Help user-prompt translation: target=%s before_len=%d after_len=%d (content not logged)",
                    lang, len(text), len(translated),
                )
                return translated

            logger.info("Help user-prompt translation failed/unchanged: target=%s", lang)
            return text
        except Exception as e:
            logger.info("Help user-prompt translation failed (%s). Using original.", e)
            return text

    def run_help_text(
        self,
        question: str,
        source_lang: Optional[str] = None,
        translate_user_text: bool = False,
        silent: bool = False,
        *,
        from_answer_redirect: bool = False,
    ) -> None:
        """Run Help mode with the given text (e.g. from Help tab).
        Same pipeline as Alt+H, no STT. Result shown in Help tab only.
        When source_lang is provided (or can be inferred), we set last_stt_detected_language so the Help LLM
        prompt + language rules align with the user's language.
        If translate_user_text=True, we also translate the *user bubble text* itself into source_lang.

        from_answer_redirect: internal — set True when called from Answer→Help redirect while Answer
        ``_process_audio`` is still active; skips the user busy check so Help can start after Answer returns.
        """
        q = (question or "").strip()
        if not q:
            return
        self.stop_voice_output()

        if not from_answer_redirect:
            with self._lock:
                _busy = self._is_processing or self._is_recording
            if _busy:
                try:
                    w = getattr(self, "widget", None)
                    _msg = i18n_s(
                        "chat.pipeline_busy",
                        default="⏳ Wait for recording or the current reply to finish before sending.",
                    )
                    if w and getattr(w, "root", None) and hasattr(w, "_notify"):
                        w.root.after(0, lambda m=_msg, ww=w: ww._notify(m, restore_after_ms=4500))
                except Exception:
                    pass
                return

        # Infer language (used for: 1) Help system prompt language, 2) raw_text_override "result.language").
        lang = (source_lang or "").strip().lower()
        if not lang or lang == "auto":
            identity_cfg = self.config.get("identity") or {}
            first_lang = (identity_cfg.get("first_language") or "auto").strip().lower()
            if first_lang and first_lang != "auto":
                lang = first_lang
            else:
                lang = (getattr(self, "last_stt_detected_language", None) or "en")
        lang = (lang or "en")[:2]
        self.last_stt_detected_language = lang

        # Optionally translate the *user message* itself so the Help bubble is localized for any language.
        if translate_user_text:
            q = self._translate_user_short_prompt(q, lang)

        def _run():
            self._process_audio(
                None,
                "help",
                selected_text="",
                duration=None,
                raw_text_override=q,
                suppress_feedback_sounds=silent,
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ─── Help mode (Alt+H) — params + KB collection & injection ──────

    APP_VERSION = "Beta 0.29.4"

    # ─── Plugin extension point ───────────────────────────────────────

    def _load_dev_plugin(self):
        """Load Data/Plugins/dev/__init__.py once (None if absent/invalid). Internal."""
        if self._dev_plugin_loaded:
            return self._dev_plugin_mod
        self._dev_plugin_loaded = True
        mod = load_plugin_module(
            self.paths.plugins, "dev", import_name="perkysue_dev_plugin", entry_filename="__init__.py"
        )
        self._dev_plugin_mod = mod
        return self._dev_plugin_mod

    def _load_avatar_editor_plugin(self):
        """Load Data/Plugins/avatar_editor/__init__.py once (None if absent/invalid). GUI gate for Avatar Editor."""
        if self._avatar_editor_plugin_loaded:
            return self._avatar_editor_plugin_mod
        self._avatar_editor_plugin_loaded = True
        mod = load_plugin_module(
            self.paths.plugins,
            "avatar_editor",
            import_name="perkysue_avatar_editor_plugin",
            entry_filename="__init__.py",
        )
        self._avatar_editor_plugin_mod = mod
        return self._avatar_editor_plugin_mod

    def _load_brainstorm_plugin(self):
        """Load Data/Plugins/brainstorm/__init__.py once (None if absent/invalid). GUI gate for Brainstorm tab."""
        if self._brainstorm_plugin_loaded:
            return self._brainstorm_plugin_mod
        self._brainstorm_plugin_loaded = True
        mod = load_plugin_module(
            self.paths.plugins,
            "brainstorm",
            import_name="perkysue_brainstorm_plugin",
            entry_filename="__init__.py",
        )
        self._brainstorm_plugin_mod = mod
        return self._brainstorm_plugin_mod

    def _stripe_signed_license_marker_path(self) -> Path:
        """Present after we have persisted a server-signed license; legacy+sub_* is rejected while this exists."""
        return self.paths.configs / "stripe_license_signed_once.marker"

    def _stripe_license_evaluate(
        self, data: dict
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
        """Parse rules for Stripe Pro from license.json dict.

        Returns:
            (accepted_dict_or_none, reject_reason_or_none, signed_ok_for_marker).
            When third is True, caller should write ``stripe_license_signed_once.marker``.
        """
        from utils.stripe_license_file import evaluate_stripe_license_file

        return evaluate_stripe_license_file(data, self.paths.configs)

    def _maybe_log_stripe_license_reject(self, reason: str, data: dict) -> None:
        """One WARNING per process when a Pro-looking license.json is rejected."""
        if getattr(self, "_stripe_license_reject_logged", False):
            return
        looks_pro = bool(
            (isinstance(data.get("subscription_id"), str) and str(data.get("subscription_id")).startswith("sub_"))
            or data.get("license_signature")
            or data.get("license_payload")
        )
        if not looks_pro:
            return
        self._stripe_license_reject_logged = True
        hint_bad_sig = (
            "Signed license proof failed crypto check: if you edited license.json while offline "
            "(e.g. dates), that is expected — go online so /check can rewrite the file. "
            "If you did not edit it, the app build's LICENSE_PUBLIC_KEY_PEM may not match the "
            "Worker's LICENSE_SIGNING_PRIVATE_KEY (distributor fix). "
            "python diagnose_license.py (from App folder); users see TROUBLESHOOTING.md (Pro)."
        )
        if reason and str(reason).startswith("signature_invalid:bad_signature"):
            logger.warning("Stripe license not applied (%s). %s", reason, hint_bad_sig)
        else:
            logger.warning(
                "Stripe license not applied (%s). Run: python diagnose_license.py (from App folder).",
                reason,
            )

    def describe_pro_gate(self) -> str:
        """Human-readable diagnosis: why UI may show Free despite license.json (support / CLI)."""
        lines: list[str] = []
        eff = self.get_effective_tier()
        gate = self.get_gating_tier()
        lines.append(f"effective_tier={eff}")
        lines.append(f"gating_tier={gate}  (UI gating uses gating_tier)")
        dev = self._load_dev_plugin()
        if dev is not None:
            try:
                dev_lines = dev.collect_diagnostics(self.config, self.paths.plugins)
                lines.extend(dev_lines)
            except Exception:
                lines.append("dev plugin present but collect_diagnostics() failed")
        lic = self.paths.configs / "license.json"
        if not lic.exists():
            lines.append("license.json: missing")
            return "\n".join(lines)
        try:
            raw = lic.read_text(encoding="utf-8", errors="ignore").strip()
            data = json.loads(raw or "{}")
        except Exception as e:
            lines.append(f"license.json: read/JSON error: {e}")
            return "\n".join(lines)
        if not isinstance(data, dict):
            lines.append("license.json: root is not a JSON object")
            return "\n".join(lines)
        ok, reason, _signed = self._stripe_license_evaluate(data)
        if ok is None:
            lines.append(f"stripe_license_eval: REJECTED — {reason}")
        else:
            lines.append("stripe_license_eval: accepted")
        return "\n".join(lines)

    def _read_valid_stripe_license(self) -> Optional[Dict[str, Any]]:
        """Data/Configs/license.json only counts as Stripe Pro if install_id matches this folder (see install.id).

        - Signature **ok**: trusted payload (offline date tamper blocked for root fields).
        - **Legacy** (no payload/signature): allowed for sub_* unless ``stripe_license_signed_once.marker`` exists
          (marker is written when a signed license was saved, or removed on the next /check that returns no signature).
        - **Invalid** signature (tampered or wrong key): never accepted.
        """
        p = self.paths.configs / "license.json"
        if not p.exists():
            return None
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw:
                return None
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        marker = self._stripe_signed_license_marker_path()
        ok, reason, signed_ok = self._stripe_license_evaluate(data)
        if ok is None:
            self._maybe_log_stripe_license_reject(reason or "unknown", data)
            return None
        if signed_ok:
            try:
                self.paths.configs.mkdir(parents=True, exist_ok=True)
                marker.write_text("1", encoding="utf-8")
            except OSError:
                pass
        return ok

    def _signed_stripe_license_payload(self) -> Optional[Dict[str, Any]]:
        """When license_signature verifies as ok, return license_payload (trusted for display / anti-tamper)."""
        p = self.paths.configs / "license.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        from utils.install_id import get_or_create_install_id
        from utils.license_signature import verify_stripe_license_signature

        cur = get_or_create_install_id(self.paths.configs).strip()
        try:
            st, _ = verify_stripe_license_signature(data, cur)
        except Exception:
            return None
        if st != "ok":
            return None
        pl = data.get("license_payload")
        return pl if isinstance(pl, dict) else None

    def get_effective_tier(self) -> str:
        """Return the effective tier based on proofs (NOT config preview).

        Values: 'free' | 'pro_alpha' | 'pro' | 'enterprise'
        """
        # 1) Enterprise license/plugin (future) — placeholder
        # 2) Stripe license (post-alpha) — must match current install.id
        try:
            if self._read_valid_stripe_license() is not None:
                return "pro"
        except Exception:
            pass
        # 3) Server-backed trial (local cache file written by POST /trial)
        try:
            if self.trial_active_days_remaining() is not None:
                return "pro"
        except Exception:
            pass
        # 4) Legacy unlock code (deprecated)
        try:
            unlock_file = self.paths.configs / "unlock.txt"
            if unlock_file.exists() and unlock_file.read_text(encoding="utf-8", errors="ignore").strip():
                return "pro_alpha"
        except Exception:
            pass
        # 5) Extension module (internal)
        dev = self._load_dev_plugin()
        if dev is not None:
            try:
                ov = dev.evaluate_entitlement_context(self.config, self.paths.plugins)
                if ov is not None:
                    return ov
            except Exception:
                pass
        return "free"

    def get_gating_tier(self) -> str:
        """Tier used for UI gating during dev/testing.

        - In production: same as effective tier (proof-based).
        - Extension module may adjust for internal testing.
        """
        eff = self.get_effective_tier()
        dev = self._load_dev_plugin()
        if dev is None:
            return eff
        try:
            ov = dev.evaluate_presentation_context(self.config, self.paths.plugins, eff)
            if ov is not None:
                return ov
        except Exception:
            pass
        return eff

    def is_effective_pro(self) -> bool:
        # Note: used for gating decisions in the UI.
        t = self.get_gating_tier()
        return t in ("pro_alpha", "pro", "enterprise")

    def can_use_mode_effective(self, mode_id: str) -> bool:
        """Effective gating for modes (not UI preview)."""
        m = (mode_id or "").strip().lower()
        if not m:
            return False
        # Free: Transcribe + Help + Answer (chat-only, no doc injection, no multi-turn context — see _process_audio)
        if not self.is_effective_pro():
            return m in ("transcribe", "help", "answer")
        # Pro+ : all built-in LLM modes + custom prompts (enterprise handled later)
        return True

    def _parse_iso_datetime_utc(self, raw: str) -> Optional[datetime]:
        s = (raw or "").strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _license_expiry_value_to_datetime(self, raw: Any) -> Optional[datetime]:
        """Parse expiry from license.json or API: ISO string, or Unix seconds/ms."""
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OSError, ValueError, OverflowError):
                return None
        if isinstance(raw, str) and raw.strip():
            s = raw.strip()
            if s.isdigit():
                try:
                    return self._license_expiry_value_to_datetime(int(s))
                except Exception:
                    pass
            return self._parse_iso_datetime_utc(s)
        return None

    def _trial_json_expiry_utc(self) -> Optional[datetime]:
        """Best-effort read of trial end time from Data/Configs/trial.json (future /trial flow)."""
        p = self.paths.configs / "trial.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        for key in ("expires_at", "trial_expires_at", "expires", "expiry"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                parsed = self._parse_iso_datetime_utc(v)
                if parsed is not None:
                    return parsed
        return None

    def has_valid_stripe_license(self) -> bool:
        """True when Data/Configs/license.json is accepted as a Stripe-linked Pro proof for this install."""
        try:
            return self._read_valid_stripe_license() is not None
        except Exception:
            return False

    def is_pro_trial_active(self) -> bool:
        """True when Pro access comes from trial.json only (no valid Stripe license on this install)."""
        try:
            if self._read_valid_stripe_license() is not None:
                return False
        except Exception:
            pass
        try:
            return self.trial_active_days_remaining() is not None
        except Exception:
            return False

    def trial_active_days_remaining(self) -> Optional[int]:
        """If local trial.json shows a future expiry, days left (min 1 on last calendar day). Else None."""
        exp = self._trial_json_expiry_utc()
        if exp is None:
            return None
        now = datetime.now(timezone.utc)
        if now >= exp:
            return None
        delta = exp - now
        d = delta.days
        if d <= 0:
            return 1
        return d

    def is_trial_consumed_for_free_tier(self) -> bool:
        """True when user is Free but must not see the 'start free trial' banner (trial already used / expired)."""
        if (self.paths.configs / "trial_consumed.marker").exists():
            return True
        try:
            lic = (self.config.get("licensing") or {}) if isinstance(self.config, dict) else {}
            if isinstance(lic, dict) and bool(lic.get("trial_consumed")):
                return True
        except Exception:
            pass
        exp = self._trial_json_expiry_utc()
        if exp is not None and datetime.now(timezone.utc) >= exp:
            return True
        return False

    def get_header_banner_spec(self) -> Tuple[str, dict]:
        """i18n key under common.header_banner.* plus optional .format() kwargs for the purple header line."""
        tier = (self.get_gating_tier() or "free").strip().lower()
        # Paid Stripe Pro wins over leftover trial.json (file may remain after upgrading).
        days = self.trial_active_days_remaining()
        if days is not None and not self.has_valid_stripe_license():
            return ("common.header_banner.pro_trial", {"days": days})
        if tier == "enterprise":
            return ("common.header_banner.enterprise", {})
        if tier in ("pro", "pro_alpha"):
            return ("common.header_banner.pro", {})
        if tier == "free":
            if self.is_trial_consumed_for_free_tier():
                return ("common.header_banner.free_after_trial", {})
            return ("common.header_banner.free_invite", {})
        return ("common.header_banner.free_invite", {})

    def _get_plan_display(self) -> str:
        """Plan display used inside the Help prompt.
        - In dev/testing: reflect the emulated plan (config['plan']) so the LLM answers consistently.
        - In production: dev plugin is absent, so this equals the effective/proof tier.
        """
        tier = self.get_gating_tier()
        if tier == "enterprise":
            return "Enterprise"
        if tier == "pro":
            return "Pro"
        if tier == "pro_alpha":
            return "Pro (alpha)"
        return "Free"

    def _collect_help_params(self, user_text: Optional[str] = None) -> str:
        """Collecte les paramètres système pour le mode Help.

        Important: keep this block compact; it competes with KB + completion tokens.
        """
        cfg = self.config
        identity = (cfg.get("identity") or {}) or {}
        stt = cfg.get("stt") or {}
        llm = cfg.get("llm") or {}
        audio = cfg.get("audio") or {}
        skin = cfg.get("skin") or {}
        hotkeys = cfg.get("hotkeys") or {}
        default_hotkeys = {
            "transcribe": "alt+t",
            "improve": "alt+i",
            "professional": "alt+p",
            "translate": "alt+l",
            "console": "alt+c",
            "email": "alt+m",
            "message": "alt+d",
            "social": "alt+x",
            "summarize": "alt+s",
            "genz": "alt+g",
            "answer": "alt+a",
            "help": "alt+h",
            "custom1": "alt+v",
            "custom2": "alt+b",
            "custom3": "alt+n",
            "stop_recording": "alt+q",
            "reinject_last": "alt+r",
        }
        t_user = (user_text or "").strip().lower()
        want_hotkeys = bool(re.search(r"\b(hotkey|hotkeys|raccourci|raccourcis|alt\+|ctrl\+|altgr|shortcut)\b", t_user))
        want_gpu_live = bool(re.search(r"\b(vram|gpu|cuda|nvidia|layers|tok/s|tokens/s|lent|slow|perf|performance)\b", t_user))
        # Snapshot system resources (best-effort)
        cpu_info = ""
        ram_info = ""
        gpu_info = ""
        try:
            import psutil
            cpu_info = f"{psutil.cpu_count(logical=False)} cores / {psutil.cpu_count(logical=True)} threads"
            mem = psutil.virtual_memory()
            ram_info = f"{round(mem.total / (1024**3), 1)} GB total, {round(mem.available / (1024**3), 1)} GB free"
        except Exception:
            pass
        backend = os.environ.get("PERKYSUE_BACKEND", "CPU")
        gpu_type = ""
        try:
            gpu_type = getattr(self, "_gpu_type", None) or self._detect_gpu_type()
            gpu_info = f"type={gpu_type}, backend={backend}"
        except Exception:
            gpu_info = ""
        stt_model = (stt.get("model") or "").strip()
        stt_device = (stt.get("device") or "").strip()
        stt_device_display = "GPU (cuda)" if stt_device == "cuda" else ("CPU" if stt_device == "cpu" else ("Auto" if stt_device == "auto" else stt_device))
        lines = ["Current settings:"]
        lines.append(f"  plan: {self._get_plan_display()}")
        lines.append(
            f"  stt: {stt_model} / {stt_device or 'auto'} ({stt_device_display}) / lang={stt.get('language', '') or 'auto'}"
        )
        lines.append(
            f"  llm: {(llm.get('model', '') or 'auto')} / ctx={llm.get('max_input_tokens') or llm.get('n_ctx') or 'Auto'}"
            f" / out={llm.get('max_output_tokens') or llm.get('max_tokens', '')} / gpu_layers={llm.get('n_gpu_layers', '')}"
        )
        lines.append(f"  audio: silence={audio.get('silence_timeout', '')}s / max={audio.get('max_duration', '')}s")
        if cpu_info:
            lines.append(f"  hw.cpu: {cpu_info}")
        if ram_info:
            lines.append(f"  hw.ram: {ram_info}")
        if gpu_info:
            lines.append(f"  hw.gpu: {gpu_info}")
        if skin.get("active", ""):
            lines.append(f"  skin: {skin.get('active', '')}")
        if (identity.get("name") or "").strip():
            lines.append(f"  identity.name: {(identity.get('name') or '').strip()}")
        if str(identity.get("first_language", "auto")).strip().lower() != "auto":
            lines.append(f"  identity.first_language: {identity.get('first_language', 'auto')}")

        if want_hotkeys:
            for key, default_val in default_hotkeys.items():
                v = (hotkeys.get(key, "") or "").strip().lower()
                if not v:
                    continue
                if v != (default_val or "").strip().lower():
                    lines.append(f"  hotkeys.{key}: {v}")

        lines.append(f"  backend: {backend}")
        lines.append(f"  version: {self.APP_VERSION}")
        # Live NVIDIA stats (VRAM / GPU %) — même logique que la barre pipeline (nvidia-smi).
        # Uniquement si la commande répond : pas de lignes vides sur CPU pur / sans GPU NVIDIA utilisable.
        if want_gpu_live:
            try:
                snap = get_nvidia_smi_snapshot()
                if snap:
                    lines.append(
                        "  gpu.live: "
                        f"util={snap['gpu_pct']}% | "
                        f"vram={snap['vram_used_mb']}/{snap['vram_total_mb']}MB ({snap['vram_pct_used']}%) | "
                        f"free={snap['vram_free_mb']}MB ({snap['vram_pct_free']}%) | "
                        f"temp={snap['temp_c']}C"
                    )
            except Exception:
                pass
        return "\n".join(lines)

    def _get_help_kb_tier(self) -> int:
        """Retourne le tier KB (2048, 4096 ou 8192) selon le contexte effectif (Auto inclus)."""
        n = self.get_effective_llm_n_ctx()
        if n <= 2048:
            return 2048
        if n <= 4096:
            return 4096
        return 8192

    def _is_perkysue_app_question(self, text: str) -> bool:
        """Heuristic: questions clearly about PerkySue / this app → Help (in-app redirect only)."""
        t = (text or "").strip().lower()
        if not t:
            return False
        # PerkySue name alone is not enough (often a greeting).
        mentions_app_name = bool(re.search(r"perkysue|perky sue|perky-sue", t))
        # Short terms as whole words only — substring "llm" matched inside unrelated words / long Chat pastes.
        word_patterns = [
            r"\bwhisper\b",
            r"\bstt\b",
            r"\bllm\b",
            r"\bsettings\b",
            r"\bmicrophone\b",
        ]
        if any(re.search(p, t) for p in word_patterns):
            return True
        phrase_needles = [
            "alt+",
            "hotkey",
            "smart focus",
            "help tab",
            "voice tab",
            "prompt modes",
        ]
        if any(p in t for p in phrase_needles):
            return True
        # If it only mentions the app name, require an app-specific cue to avoid false redirects.
        if mentions_app_name:
            if re.search(
                r"\b(comment|how|where|pourquoi|why|help|aide|bug|probl[eè]me|settings|param|r[eé]glages|raccourci|hotkey|alt\+|whisper|stt|llm|gpu|cuda|vram|license|licen[cs]e|abonnement|subscription|stripe|facturation|billing)\b",
                t,
            ):
                return True
            return False
        # Short words need word boundaries.
        boundary_patterns = [
            r"\bfree\b",
            r"\btrial\b",
            r"\babonnement\b",
            r"\bsubscription\b",
            r"\bbilling\b",
            r"\bstripe\b",
            r"\blicen[cs]e\b",
        ]
        return any(re.search(p, t) for p in boundary_patterns)

    def _llm_intent_should_redirect_to_help(self, user_text: str) -> bool:
        """
        LLM router for Help redirect.
        Returns True when the user message is a real request for Help (PerkySue/app usage),
        otherwise False (tests / statements / "don't redirect" / unrelated chat).
        """
        try:
            llm = getattr(self, "llm", None)
            if not llm or not getattr(llm, "is_available", None) or not llm.is_available():
                # Fallback to previous behavior when router can't run.
                return True

            ut_full = (user_text or "").strip()
            cap = _HELP_INTENT_ROUTER_TEXT_CAP
            if len(ut_full) > cap:
                ut = ut_full[:cap].rstrip() + "\n[…]"
            else:
                ut = ut_full

            system_prompt = (
                "You are an intent classifier for the Windows app PerkySue (local Whisper STT + local LLM).\n"
                "Use ONLY the user's message in this turn. Ignore any hypothetical prior chat or summaries "
                "you were not given.\n\n"
                "Reply with EXACTLY one word on a single line: HELP or NOHELP (no punctuation, no explanation).\n\n"
                "HELP — the user wants app-specific assistance, including ANY of:\n"
                "- What LLM / GGUF / model name is loaded, max tokens, context, GPU layers, backend.\n"
                "- What Whisper / STT model or device (CPU/CUDA) is used, or how to change STT.\n"
                "- Settings, hotkeys (Alt+…), Smart Focus, plans (Free/Pro), microphone, injection, Help tab.\n"
                "- How to use a PerkySue feature, troubleshooting, or explicit request for help with the app.\n"
                "These count as HELP even if the user does NOT say the word 'PerkySue'.\n"
                "IMPORTANT: If the user only says 'PerkySue' as a greeting (e.g. 'Salut PerkySue, ...') but asks for general content\n"
                "(science, writing, translation, etc.) unrelated to the app, that is NOHELP.\n\n"
                "NOHELP — general conversation, jokes, tests, meta instructions like 'do not redirect', "
                "or topics clearly unrelated to PerkySue (other apps, world news, etc.).\n\n"
                "Examples: 'Which Whisper model am I using?' → HELP. "
                "'What LLM model are you running?' (in this app) → HELP. "
                "User wants a machine evaluation / whether their PC can run a bigger local LLM or GGUF in PerkySue "
                "(RAM, VRAM, GPU, 'plus gros LLM', compatibility) → HELP. "
                "'Tell me a joke' → NOHELP.\n"
            )
            router_result = self._run_llm_on_main_thread(
                text=ut,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=8,
                gui_debug_label="help_intent_router",
            )
            raw = self._strip_thinking_blocks((getattr(router_result, "text", None) or "").strip()).upper()
            # First line / first token only (model sometimes adds chatter).
            first_line = (raw.splitlines()[0] if raw else "").strip()
            first_token = (first_line.split()[0] if first_line.split() else "")
            first_token = re.sub(r"[^A-Z]", "", first_token)
            raw_alpha = re.sub(r"[^A-Z]", "", first_line)

            if first_token == "NOHELP" or first_token.startswith("NO"):
                return False
            if first_token == "HELP":
                return True
            if "NOHELP" in raw_alpha:
                return False
            # Avoid "NOTHELP" matching substring HELP
            if raw_alpha == "HELP" or raw_alpha.endswith("HELP") and not raw_alpha.startswith("NO"):
                return True
            return False
        except Exception:
            # Fallback to previous behavior: redirect.
            return True

    def _should_force_help_redirect(self, text: str) -> bool:
        """
        If the LLM router wrongly says NOHELP, still redirect when the user clearly asks PerkySue
        for machine / LLM sizing (RAM, VRAM, bigger model). Uses tight phrases to avoid false positives.
        """
        t = (text or "").strip().lower()
        if not t:
            return False
        if not re.search(r"perkysue|perky sue|perky-sue", t):
            return False
        if "plus gros" in t and "llm" in t:
            return True
        if ("évaluation" in t or "evaluation" in t) and (
            "machine" in t or "système" in t or "system" in t or "ma machine" in t
        ):
            return True
        if re.search(r"\bvram\b", t) or "gguf" in t:
            return True
        if re.search(r"\bram\b", t) and (
            "libre" in t or "combien" in t or " go" in t or " gb" in t or "gigas" in t or "topo" in t
        ):
            return True
        if "gros" in t and "llm" in t and ("modèle" in t or "model" in t or "mettre" in t or "charger" in t):
            return True
        return False

    def _load_help_kb_content(self, tier: int) -> str:
        """Charge le contenu de la KB Help pour le tier donné. Override dans Data/Configs prioritaire."""
        name = f"kb_help_{tier}.md"
        user_path = self.paths.configs / name
        if user_path.exists():
            try:
                out = user_path.read_text(encoding="utf-8", errors="replace").strip()
                logger.info("Help KB loaded from user override: %s (%d chars)", user_path, len(out))
                return out
            except Exception as e:
                logger.warning("Help KB user override %s read failed: %s", user_path, e)
        app_path = self.paths.app_dir / "configs" / name
        if app_path.exists():
            try:
                out = app_path.read_text(encoding="utf-8", errors="replace").strip()
                logger.info("Help KB loaded: %s (%d chars)", app_path, len(out))
                return out
            except Exception as e:
                logger.warning("Help KB %s read failed: %s", app_path, e)
        # Fallback: relative to this file (App/orchestrator.py → App/configs/)
        try:
            from pathlib import Path
            fallback = Path(__file__).resolve().parent / "configs" / name
            if fallback.exists():
                out = fallback.read_text(encoding="utf-8", errors="replace").strip()
                logger.info("Help KB loaded (fallback): %s (%d chars)", fallback, len(out))
                return out
        except Exception as e:
            logger.warning("Help KB fallback read failed: %s", e)
        logger.warning("Help KB not found for tier %s (tried %s, %s)", tier, user_path, app_path)
        return ""

    def _build_help_system_prompt(self, mode: Mode, user_name: str, source_lang: str, user_text: str = "") -> str:
        """Construit le prompt système complet pour le mode Help : paramètres + KB + instructions du mode.
        Si max_input_tokens <= 1024, la KB est tronquée pour tenir dans le contexte (éviter 400 Bad Request).
        """
        max_ctx = self.get_effective_llm_n_ctx()
        params_block = self._collect_help_params(user_text=user_text)
        plan_display = self._get_plan_display()
        # Explicit reminder so the LLM does not suggest sign-up when the user already has Pro
        plan_reminder = (
            f"User's current plan = {plan_display}. "
            "If plan is 'Pro (alpha)', 'Pro', or 'Enterprise', the user ALREADY has Pro access. "
            "Do NOT suggest any unlock-code sign-up flow."
        )
        tier = self._get_help_kb_tier()
        kb_content = self._load_help_kb_content(tier)
        # Petites fenêtres de contexte : tronquer la KB pour laisser de la marge à la question + réponse.
        # - 1024: garder ~700 caractères de KB (~175 tokens) → réserve plus large pour user+réponse.
        # - 2048: garder ~1500 caractères de KB (~375 tokens) pour éviter 400 Bad Request dès la 1re question.
        if max_ctx <= 1024 and len(kb_content) > 700:
            kb_content = kb_content[:700].rstrip() + "\n\n(KB truncated for 1024 context. Increase Max input to 2048+ for full KB.)"
            if self.config.get("feedback", {}).get("console_output", True):
                logger.info("Help: KB truncated to 700 chars for max_ctx=1024")
        elif max_ctx <= 2048 and len(kb_content) > 1350:
            # Slightly tighter than 1500 so system prompt + live GPU line + instructions fit in small ctx.
            kb_content = kb_content[:1350].rstrip() + "\n\n(KB truncated for 2048 context. Increase Max input to 4096+ for full KB.)"
            if self.config.get("feedback", {}).get("console_output", True):
                logger.info("Help: KB truncated to 1350 chars for max_ctx=2048")
        # Help conversation memory (required for follow-ups after redirects).
        # We exclude the last entry if it is still unanswered (a == "") to avoid duplicating the current user question.
        help_hist = getattr(self, "_help_history", []) or []
        recent_pairs: list[dict] = []
        try:
            if help_hist:
                if (help_hist[-1].get("a") or "").strip() == "":
                    candidates = help_hist[:-1]
                else:
                    candidates = help_hist
            else:
                candidates = []
        except Exception:
            candidates = help_hist
        # Keep only a small tail to fit context safely.
        n_help_qa = 4
        recent_pairs = candidates[-n_help_qa:] if len(candidates) > n_help_qa else candidates

        recent_conv_lines: list[str] = []
        for idx, qa in enumerate(recent_pairs, start=1):
            q = (qa.get("q") or "").strip()
            a = (qa.get("a") or "").strip()
            if not q and not a:
                continue
            if q:
                recent_conv_lines.append(f"Q{idx}: {q}")
            if a:
                recent_conv_lines.append(f"A{idx}: {a}")

        recent_conv_block = "\n".join(recent_conv_lines).strip()
        # Hard cap to avoid overflowing small contexts (2048).
        # IMPORTANT: keep the *tail* (most recent turns) so follow-ups can reference
        # the latest user/assistant content.
        max_recent_chars = 900 if max_ctx <= 2048 else 1500
        if recent_conv_block and len(recent_conv_block) > max_recent_chars:
            tail = recent_conv_block[-max_recent_chars:].lstrip()
            recent_conv_block = tail.rstrip() + "\n…(truncated recent help context)"

        modes_config = self.config.get("modes", {})
        base_instructions = render_prompt(
            mode, "",
            source_lang=source_lang or "auto",
            target_lang=modes_config.get("translate_target", "en"),
            selected_text="",
            user_name=user_name or "",
            conversation_context=None,
        )
        parts = [params_block, plan_reminder]
        if kb_content:
            parts.append("--- Knowledge Base ---")
            parts.append(kb_content)
        if recent_conv_block:
            parts.append("--- Recent Help conversation ---")
            parts.append(recent_conv_block)
        parts.append("--- Instructions ---")
        parts.append(base_instructions.strip())
        full = "\n\n".join(p for p in parts if p)
        if self.config.get("feedback", {}).get("console_output", True):
            logger.info(
                "Help: built system prompt params=%d chars, KB=%d chars, total=%d chars (tier=%s, max_ctx=%s, source_lang=%s)",
                len(params_block), len(kb_content), len(full), tier, max_ctx, source_lang,
            )
        return full

    def get_greeting_from_llm(self, lang_code: str, user_name: str, context: str = "chat") -> Optional[str]:
        """Ask the LLM for one short greeting in the given language. context: 'chat' (Answer/conversation tab) or 'help' (Help tab)."""
        if not lang_code or lang_code.strip().lower() == "auto":
            return None
        if not self.llm or not self.llm.is_available():
            return None
        context = "help" if (context or "").strip().lower() == "help" else "chat"
        lang_code = lang_code.strip().lower()[:2]
        lang_names = {
            "en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
            "nl": "Dutch", "pl": "Polish", "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
            "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "sv": "Swedish", "da": "Danish", "no": "Norwegian",
            "fi": "Finnish", "el": "Greek", "cs": "Czech", "hu": "Hungarian", "ro": "Romanian", "uk": "Ukrainian",
            "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "ms": "Malay", "he": "Hebrew", "fa": "Persian",
            "bg": "Bulgarian", "hr": "Croatian", "sk": "Slovak", "sl": "Slovenian", "et": "Estonian", "lv": "Latvian",
            "lt": "Lithuanian", "sr": "Serbian", "ca": "Catalan", "eu": "Basque", "gl": "Galician", "nb": "Norwegian Bokmål",
            "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "ur": "Urdu", "my": "Burmese",
            "km": "Khmer", "lo": "Lao", "ne": "Nepali", "si": "Sinhala", "pa": "Punjabi", "gu": "Gujarati",
            "kn": "Kannada", "ml": "Malayalam",
        }
        lang_name = lang_names.get(lang_code, lang_code)
        name_part = (user_name or "").strip() or "there"
        if context == "help":
            hint = (
                "This greeting is for the Help tab. Say hello using the user's first name and ask if they need help "
                "(e.g. 'Does [name] need any help?' or 'Hi [name], need help with PerkySue?'). Warm and natural, one short sentence."
            )
        else:
            hint = (
                "This greeting is for the Chat tab. Say hello using the user's first name and add a short engagement question "
                "(e.g. what would you like to talk about? what's on your mind? anything you'd like to ask?). One or two short sentences, inviting them to start the conversation."
            )
        system_prompt = (
            "You are PerkySue, a friendly voice assistant app. Your task: generate exactly ONE short greeting (or two very short sentences). "
            f"Language: {lang_name}. User's first name: {name_part}. {hint} "
            "Reply with ONLY the greeting, no explanation, no quotes, no extra lines. "
            "Never output chain-of-thought, 'Thinking Process:', 'Analysis:', or any label before the greeting."
        )
        try:
            result = self.llm.process(
                text="Generate the greeting.",
                system_prompt=system_prompt,
                temperature=0.4,
                max_tokens=80,
            )
            if result and getattr(result, "text", None):
                text = self._strip_thinking_blocks((result.text or "").strip())
                if text:
                    skip_re = re.compile(
                        r"^(thinking|analysis|here\s+is|note:)\b|thinking\s+process",
                        re.IGNORECASE,
                    )
                    chosen = ""
                    for line in text.split("\n"):
                        s = line.strip()
                        if not s or skip_re.search(s):
                            continue
                        chosen = s
                        break
                    if not chosen:
                        chosen = text.split("\n")[0].strip()
                    logger.info("Greeting[%s,%s]: %d chars (content not logged)", context, lang_code, len(chosen))
                    return chosen if chosen else None
            return None
        except Exception as e:
            logger.debug("Greeting LLM failed: %s", e)
            return None

    def get_help_effective_system_prompt(self, prompt_override: Optional[str] = None) -> str:
        """Retourne le prompt système complet qui sera envoyé au LLM pour le mode Help (pour affichage dans la GUI)."""
        mode = self.modes.get("help")
        if not mode:
            return ""
        if prompt_override is not None:
            try:
                mode = Mode(
                    id=mode.id,
                    name=mode.name,
                    description=getattr(mode, "description", ""),
                    needs_llm=getattr(mode, "needs_llm", True),
                    system_prompt=prompt_override,
                    test_inputs=getattr(mode, "test_inputs", None),
                )
            except Exception:
                pass
        identity_cfg = self.config.get("identity", {}) or {}
        user_name = (identity_cfg.get("name") or "").strip()
        modes_config = self.config.get("modes", {})
        raw_sl = getattr(self, "last_stt_detected_language", None) or modes_config.get("translate_source", "auto")
        base = self._build_help_system_prompt(mode, user_name, raw_sl, user_text="")
        return self._append_tts_llm_extension(base, "help", reply_language=raw_sl)

    def _recompute_effective_llm_context(self) -> None:
        """Refresh cached effective n_ctx / max_output from merged config (Auto = 0 in YAML)."""
        from utils.llm_context_resolve import resolve_effective_max_output, resolve_effective_n_ctx

        llm = self.config.get("llm") or {}
        self._effective_llm_n_ctx = resolve_effective_n_ctx(llm)
        self._effective_llm_max_output = resolve_effective_max_output(llm, self._effective_llm_n_ctx)

    def get_effective_llm_n_ctx(self) -> int:
        """Runtime context window (shared prompt + completion). Respects Auto + hardware caps."""
        return max(512, int(getattr(self, "_effective_llm_n_ctx", 2048) or 2048))

    def get_effective_llm_max_output(self) -> int:
        """Max new tokens per completion; Auto scales with get_effective_llm_n_ctx()."""
        return max(256, int(getattr(self, "_effective_llm_max_output", 2048) or 2048))

    def _prepare_llm_conf_for_provider(self, base: Optional[dict] = None) -> dict:
        """Copy llm config with resolved n_ctx / max_tokens for llama.cpp / llama-server."""
        self._recompute_effective_llm_context()
        src = dict((base or self.config.get("llm", {})) or {})
        src["n_ctx"] = self._effective_llm_n_ctx
        src["max_input_tokens"] = self._effective_llm_n_ctx
        src["max_tokens"] = self._effective_llm_max_output
        src["max_output_tokens"] = self._effective_llm_max_output
        src["_models_dir"] = str(self.paths.models_llm)
        return src

    def _normalize_llm_config(self, config: dict) -> None:
        """Ensure llm has n_ctx and max_tokens from max_input_tokens / max_output_tokens (or legacy keys)."""
        llm = config.get("llm")
        if not isinstance(llm, dict):
            return
        # Prefer explicit names; fallback to legacy (n_ctx, max_tokens)
        llm["n_ctx"] = llm.get("max_input_tokens", llm.get("n_ctx", 0))
        llm["max_tokens"] = llm.get("max_output_tokens", llm.get("max_tokens", 2048))
        try:
            rt = int(llm.get("request_timeout", 180))
        except (TypeError, ValueError):
            rt = 180
        llm["request_timeout"] = max(120, min(rt, 360))
        if "thinking" not in llm:
            llm["thinking"] = "off"
        if "thinking_budget" not in llm:
            llm["thinking_budget"] = 512
        try:
            keep = int(llm.get("answer_context_keep", 2))
        except (TypeError, ValueError):
            keep = 2
        llm["answer_context_keep"] = 2 if keep not in (2, 3, 4) else keep
        v = llm.get("inject_all_modes_in_chat", True)
        if isinstance(v, str):
            llm["inject_all_modes_in_chat"] = v.strip().lower() in ("1", "true", "yes", "on")
        else:
            llm["inject_all_modes_in_chat"] = bool(v)

    @staticmethod
    def _answer_context_keep_from_config(config: dict) -> int:
        llm = (config or {}).get("llm") or {}
        try:
            keep = int(llm.get("answer_context_keep", 2))
        except (TypeError, ValueError):
            keep = 2
        return 2 if keep not in (2, 3, 4) else keep

    def _inject_all_modes_in_chat_enabled(self) -> bool:
        llm = (self.config.get("llm") or {})
        v = llm.get("inject_all_modes_in_chat", True)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    def _chat_cross_mode_ids(self) -> set[str]:
        """LLM modes that can be mirrored into Chat history when Pro setting is enabled."""
        return {
            "improve",
            "professional",
            "translate",
            "console",
            "email",
            "message",
            "social",
            "summarize",
            "genz",
            "custom1",
            "custom2",
            "custom3",
        }

    def _should_capture_mode_into_chat(self, mode_id: str) -> bool:
        mid = (mode_id or "").strip().lower()
        if mid == "answer":
            return True
        return bool(
            self.is_effective_pro()
            and self._inject_all_modes_in_chat_enabled()
            and mid in self._chat_cross_mode_ids()
        )

    def _normalize_feedback_config(self, config: dict) -> None:
        fb = config.get("feedback")
        if not isinstance(fb, dict):
            config["feedback"] = {
                "sound_enabled": True,
                "notification_enabled": True,
                "console_output": True,
                "debug_mode": False,
            }
            return
        if "debug_mode" not in fb:
            fb["debug_mode"] = False

    def _sync_strings_locale_from_config(self) -> None:
        """Load i18n YAML for ui.language so orchestrator can use s() (injection labels, etc.)."""
        try:
            from utils.strings import load_strings

            loc = ((self.config.get("ui") or {}).get("language") or "us").strip().lower() or "us"
            load_strings(loc)
        except Exception:
            pass

    def _answer_injection_user_label(self, identity_name: str) -> str:
        n = (identity_name or "").strip()
        if n:
            return n
        self._sync_strings_locale_from_config()
        return i18n_s("chat.user_fallback", default="You")

    def _answer_injection_assistant_label(self) -> str:
        self._sync_strings_locale_from_config()
        return i18n_s("chat.sender_name", default="PerkySue")

    def _feedback_debug_mode(self) -> bool:
        """Settings → Advanced: raw TTS tags in paste/UI, PreviousAnswersSummary in Alt+A injection.

        Full STT + exact LLM system/user (after context fit) go to logger ``perkysue.gui_console`` only
        (Full Console in GUI) — never to ``perkysue`` / disk (perkysue.log must stay free of exchanges).
        """
        try:
            return bool((self.config.get("feedback") or {}).get("debug_mode", False))
        except Exception:
            return False

    def _audio_pipeline_debug(self) -> bool:
        """Mix / VAD / Continuous Chat diagnostics on logger ``perkysue`` (disk) when enabled.

        - ``audio.pipeline_debug: true`` in ``Data/Configs/config.yaml``, or
        - Settings → Advanced → Debug mode (also enables GUI console payload dumps).
        """
        try:
            if self._feedback_debug_mode():
                return True
            return bool((self.config.get("audio") or {}).get("pipeline_debug", False))
        except Exception:
            return False

    def _emit_gui_debug_llm_payload(self, label: str, system_prompt: str, user_text: str, max_tokens: int) -> None:
        """Log exact LLM payload to Full Console only when debug_mode is on (not to disk)."""
        if not self._feedback_debug_mode():
            return
        if not (self.config.get("feedback") or {}).get("console_output", True):
            return
        g = logging.getLogger("perkysue.gui_console")
        g.info(
            "=== LLM [%s] (payload sent to server) ===\n--- SYSTEM ---\n%s\n--- USER ---\n%s\n--- max_tokens=%d ---\n",
            (label or "llm").strip(),
            system_prompt or "",
            user_text or "",
            int(max_tokens),
        )

    # ─── Answer mode (Alt+A) — Q/A history & summaries ──────────────

    def _build_llm_input_with_context(self, mode_id: str, mode: Mode, current_question: str) -> tuple[str, Optional[str], bool]:
        """
        Construit ce qui est envoyé au LLM pour un mode donné.
        - Pour Answer (Alt+A) avec historique : retourne (question_actuelle, contexte_system, hit_max_input).
          Le contexte (Q/R précédents + résumé) est à mettre dans le SYSTEM prompt pour que le modèle
          le voie bien ; le message USER ne contient que la question actuelle.
        - Sans historique ou autre mode : retourne (texte, None, hit_max_input).
        """
        text = (current_question or "").strip()
        hit_max_input = False

        # Answer mode always uses conversation context.
        mode_key = (mode_id or "").strip().lower()
        use_shared_context = (mode_key == "answer") or (
            self.is_effective_pro()
            and self._inject_all_modes_in_chat_enabled()
            and mode_key in self._chat_cross_mode_ids()
        )
        if not use_shared_context:
            return text, None, hit_max_input

        # Free tier: each question is standalone — no summaries / previous Q&A in the LLM prompt.
        if not self.is_effective_pro():
            return text, None, hit_max_input

        history_all = getattr(self, "_answer_history", [])
        summaries = getattr(self, "_answer_summaries", [])
        # Same rule as Help: exclude the last turn if still unanswered — it duplicates the current user message.
        history: list[dict] = list(history_all or [])
        if history and (history[-1].get("a") or "").strip() == "":
            history = history[:-1]
        n_prior = len(history)

        # Aucun historique (hors tour courant) → question brute uniquement, pas de bloc système
        if n_prior == 0:
            return text, None, hit_max_input

        n_qa = self._answer_context_keep_from_config(self.config)
        self._answer_context_n_qa = n_qa
        # Construire le bloc contexte : dernier résumé consolidé + les n_qa derniers Q/R (0.25.1: 4).
        # Chaque snapshot dans _answer_summaries est déjà produit en fusionnant les résumés précédents
        # avec le bloc de Q/R courant — n'injecter que le dernier évite la redondance (Summary 1 + 2 + …).
        ctx_parts: list[str] = []

        if summaries:
            ctx_parts.append("PreviousAnswersSummary (context so far):")
            last_s = summaries[-1] if summaries else None
            t = (last_s.get("text") or "").strip() if last_s else ""
            if t:
                ctx_parts.append(t)
            ctx_parts.append(f"Latest {n_qa} Q/A (most recent exchanges — use these to answer the current question):")
            last_n = history[-n_qa:] if len(history) >= n_qa else history
            for i, qa in enumerate(last_n, start=len(history) - len(last_n) + 1):
                q = qa.get("q", "")
                a = qa.get("a", "")
                if q or a:
                    ctx_parts.append(f"Q{i}: {q}")
                    if a:
                        ctx_parts.append(f"A{i}: {a}")
        else:
            ctx_parts.append("Previous questions and answers:")
            for i, qa in enumerate(history, start=1):
                q = qa.get("q", "")
                a = qa.get("a", "")
                if q or a:
                    ctx_parts.append(f"Q{i}: {q}")
                    if a:
                        ctx_parts.append(f"A{i}: {a}")

        system_context = "\n\n".join(part for part in ctx_parts if part.strip())

        if self.config.get("feedback", {}).get("console_output", True):
            verbatim_in_prompt = min(n_qa, n_prior) if summaries else n_prior
            logger.info(
                "Alt+A: context in SYSTEM prompt (%d chars, %d completed Q/A in memory, %d verbatim Q/A in SYSTEM block; keep_last=%d; pending turn excluded; content not logged)",
                len(system_context), n_prior, verbatim_in_prompt, n_qa,
            )

        # Garde Max input (system_context + question actuelle + marge pour system prompt de base)
        n_ctx_val = self.get_effective_llm_n_ctx()
        char_limit = int(n_ctx_val) * 4 if n_ctx_val > 0 else 0

        def _within_limit(s: str) -> bool:
            return (not char_limit) or (len(s) <= char_limit)

        if _within_limit(system_context + "\n\n" + text):
            return text, system_context, hit_max_input

        # Trop long : réduire à dernier échange + question actuelle
        hit_max_input = True
        if history:
            last_q = history[-1].get("q", "")
            last_a = history[-1].get("a", "")
            parts = [
                "Most recent exchange before the current question:",
                f"Q: {last_q}" if last_q else "",
                f"A: {last_a}" if last_a else "",
            ]
            reduced_ctx = "\n\n".join(p for p in parts if p.strip())
            if _within_limit(reduced_ctx + "\n\n" + text):
                return text, reduced_ctx, hit_max_input

        # Fallback : pas de contexte, question seule
        return text, None, hit_max_input

    def _record_answer_history(self, question: str, answer: str) -> Optional[str]:
        """Enregistre un couple Q/R pour Alt+A et crée un PreviousAnswersSummary tous les n_qa échanges (0.25.1: 4).

        Si la dernière entrée a déjà la même question avec a="", on met à jour cette entrée (affichage en deux temps).
        Retourne le texte du summary fraîchement créé (pour injection éventuelle),
        ou None si aucun summary n'a été créé à ce tour.
        """
        n_qa = self._answer_context_keep_from_config(self.config)
        self._answer_context_n_qa = n_qa
        history = getattr(self, "_answer_history", [])
        q_stripped = (question or "").strip()
        if history and (history[-1].get("a") or "").strip() == "" and (history[-1].get("q") or "").strip() == q_stripped:
            history[-1]["a"] = answer or ""
        else:
            history.append({"q": question, "a": answer})
        n = len(history)
        # Pro+ only: rolling summaries every n_qa exchanges
        if not self.is_effective_pro():
            return None
        # Créer un summary tous les n_qa échanges complétés (1–4, 5–8, …)
        if n % n_qa != 0:
            return None
        block = history[-n_qa:]
        # Pour le 2e résumé et suivants : inclure les résumés précédents + les n_qa nouveaux Q/R
        summaries = getattr(self, "_answer_summaries", [])
        previous_texts = [s.get("text", "").strip() for s in summaries if (s.get("text") or "").strip()]
        summary_text = self._create_previous_answers_summary(block, previous_texts)
        if not summary_text.strip():
            return None
        summaries.append({"end_index": n, "text": summary_text.strip()})
        # Loguer le summary dans la console en tant qu'entrée dédiée.
        w = getattr(self, "widget", None)
        if w and getattr(w, "root", None):
            try:
                txt = f"PreviousAnswersSummary (Q{n - n_qa + 1}–Q{n}):\n{summary_text.strip()}"
                w.root.after(0, lambda: w.append_previous_answers_summary(txt))
            except Exception:
                pass
        return summary_text.strip() or None

    def _create_previous_answers_summary(self, block: list[dict], previous_summaries: Optional[list[str]] = None) -> str:
        """Utilise le mode Summarize (Alt+S) pour produire un résumé.
        - 1er résumé : bloc des n_qa derniers Q/R (0.25.1: 4).
        - 2e et suivants : résumés précédents (concaténés) + les n_qa derniers Q/R, pour un résumé consolidé.
        """
        previous_summaries = previous_summaries or []
        try:
            if not self.llm or not self.llm.is_available():
                # Pas de LLM dispo : fallback texte brut concaténé.
                parts = []
                for i, qa in enumerate(block, start=1):
                    q = qa.get("q", "")
                    a = qa.get("a", "")
                    parts.append(f"Q{i}: {q}")
                    if a:
                        parts.append(f"A{i}: {a}")
                return "\n".join(parts)

            # Mode dédié au résumé d'échanges Q/R (préserve dimension dialogue) ; sinon fallback sur Summarize
            mode = self.modes.get("summarize_qa") or self.modes.get("summarize")
            if not mode:
                parts = []
                for i, qa in enumerate(block, start=1):
                    q = qa.get("q", "")
                    a = qa.get("a", "")
                    parts.append(f"Q{i}: {q}")
                    if a:
                        parts.append(f"A{i}: {a}")
                return "\n".join(parts)

            # Bloc des n_qa derniers Q/R
            lines = []
            for i, qa in enumerate(block, start=1):
                q = qa.get("q", "")
                a = qa.get("a", "")
                if not q and not a:
                    continue
                lines.append(f"Q{i}: {q}")
                if a:
                    lines.append(f"A{i}: {a}")
                lines.append("")
            block_text = "\n".join(lines).strip()

            keep_last = self._answer_context_keep_from_config(self.config)
            # If keep_last is low (2), summaries happen more often: ask for a denser/shorter snapshot.
            factual_guardrails = (
                "CRITICAL FACT RETENTION RULES:\n"
                "- Extract and preserve facts as VARIABLE→VALUE pairs whenever possible.\n"
                "- Keep both sides together: do not keep a variable name without its known value.\n"
                "- Never replace a known value with a vague placeholder (e.g., 'unspecified', 'unknown').\n"
                "- If a VARIABLE already has a VALUE in prior context, keep that exact VALUE unless the user explicitly updates it.\n"
                "- Preserve exact constraints and commitments (timing, counts, deadlines, sequencing).\n"
                "- Prefer factual completeness and consistency over stylistic brevity.\n\n"
            )
            if keep_last <= 2:
                substantial_instruction = (
                    "TASK: Produce a COMPACT but complete summary (about 35-50% of the original length). "
                    "Preserve key facts, constraints, and conclusions so later turns remain understandable. "
                    "Avoid fluff and repetition. Do NOT reduce to one or two short sentences.\n\n"
                )
            else:
                # Instruction pour un résumé ÉTOFFÉ (pas une phrase) : suffisant pour suivre la conversation après
                substantial_instruction = (
                    "TASK: Produce a SUBSTANTIAL summary (about 40-50% of the original length). "
                    "Preserve key arguments, examples, names, and conclusions so the conversation can be followed in later turns. "
                    "Do NOT reduce to one or two short sentences. Include the main ideas and important details.\n\n"
                )
            substantial_instruction = substantial_instruction + factual_guardrails
            # Entrée pour le LLM : résumés précédents (s'il y en a) + les n_qa nouveaux Q/R
            n_qa = len(block)
            if previous_summaries:
                intro = (
                    "Consolidate the following into ONE substantial summary: "
                    f"previous summaries of this conversation, then the latest {n_qa} Q/A pairs. "
                    "Keep key points, arguments, and examples from both. Reply ONLY with the consolidated summary.\n\n"
                )
                prev_block = "\n\n".join(f"Previous summary:\n{t.strip()}" for t in previous_summaries if (t or "").strip())
                summary_input = substantial_instruction + intro + "--- Previous summaries ---\n\n" + prev_block + f"\n\n--- Latest {n_qa} Q/A ---\n\n" + block_text
            else:
                summary_input = substantial_instruction + block_text

            # Même mode Summarize (Alt+S) que l'utilisateur a dans modes.yaml
            modes_config = self.config.get("modes", {})
            identity_cfg = self.config.get("identity", {}) or {}
            user_name = identity_cfg.get("name", "") or ""
            stt_lang = self.last_stt_detected_language or "auto"
            system_prompt = render_prompt(
                mode,
                summary_input,
                source_lang=stt_lang,
                target_lang=modes_config.get("translate_target", "en"),
                selected_text="",
                user_name=user_name,
            )
            # Keep summaries cheaper when keep_last is small to reduce context pressure.
            summary_max_tokens = 768 if keep_last <= 2 else 1024
            llm_result = self._run_llm_on_main_thread(
                text=summary_input,
                system_prompt=system_prompt,
                temperature=self.config.get("llm", {}).get("temperature", 0.3),
                max_tokens=min(summary_max_tokens, self.get_effective_llm_max_output()),
                gui_debug_label="answer_previous_summary",
            )
            return self._strip_thinking_blocks(llm_result.text.strip())
        except Exception as e:
            logger.error("PreviousAnswersSummary failed: %s", e)
            # Fallback sur concaténé
            parts = []
            for i, qa in enumerate(block, start=1):
                q = qa.get("q", "")
                a = qa.get("a", "")
                parts.append(f"Q{i}: {q}")
                if a:
                    parts.append(f"A{i}: {a}")
            return "\n".join(parts)

    def _format_answer_injection(
        self,
        question: str,
        answer: str,
        summary: Optional[str],
        user_name: str = "",
        *,
        include_summary: bool = False,
    ) -> str:
        """Injection Alt+A : libellés user / assistant via i18n (chat.user_fallback, chat.sender_name). Résumé seulement si debug."""
        q = (question or "").strip()
        a = (answer or "").strip()
        u = self._answer_injection_user_label(user_name)
        assistant = self._answer_injection_assistant_label()
        parts = []
        if q:
            parts.append(f"**● {u}:** {q}")
        if a:
            if parts:
                parts.append("")
            parts.append(f"**✦ {assistant}:** {a}")
        if include_summary and (summary or "").strip():
            parts.append("")
            parts.append("**PreviousAnswersSummary:**")
            parts.append((summary or "").strip())
        return "\n".join(parts) + "\n"

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override into base. Override wins on conflicts."""
        result = base.copy()
        for key, value in override.items():
            if (key in result and isinstance(result[key], dict)
                    and isinstance(value, dict)):
                result[key] = Orchestrator._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _union_tts_trigger_modes(merged: dict, defaults: dict) -> None:
        """User config often keeps legacy ``trigger_modes: [answer, help]``, which replaces the
        full factory list after deep-merge and disables TTS for email/improve/… . Union with
        defaults so shipped modes stay eligible unless the user removes them explicitly from
        defaults.yaml (advanced). User order is preserved; missing factory modes are appended.
        """
        m_tts = merged.get("tts")
        d_tts = defaults.get("tts") if isinstance(defaults, dict) else None
        if not isinstance(m_tts, dict) or not isinstance(d_tts, dict):
            return
        u_list = m_tts.get("trigger_modes")
        d_list = d_tts.get("trigger_modes")
        if not isinstance(u_list, list) or not isinstance(d_list, list):
            return
        seen: set[str] = set()
        out: list[str] = []
        for x in u_list:
            k = str(x).strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(str(x).strip())
        for x in d_list:
            k = str(x).strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(str(x).strip())
        m_tts["trigger_modes"] = out

    def _detect_gpu_type(self) -> str:
        """
        Detect GPU vendor without initializing CUDA.
        Returns: "nvidia", "amd", "intel", or "none"
        """
        import shutil
        import subprocess
        
        # Check NVIDIA first (nvidia-smi)
        if shutil.which("nvidia-smi"):
            try:
                result = subprocess.run(
                    ["nvidia-smi", "-L"], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                if result.returncode == 0 and "GPU" in result.stdout:
                    return "nvidia"
            except:
                pass
        
        # Check for AMD/Intel via registry (Windows)
        try:
            import winreg
            # Try to find display adapters
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Video"
            )
            
            # Enumerate subkeys to find GPU info
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    
                    for j in range(winreg.QueryInfoKey(subkey)[0]):
                        try:
                            device_key_name = winreg.EnumKey(subkey, j)
                            device_key = winreg.OpenKey(subkey, device_key_name)
                            
                            # Check device description
                            try:
                                desc, _ = winreg.QueryValueEx(device_key, "DeviceDesc")
                                desc_lower = desc.lower()
                                
                                if "amd" in desc_lower or "radeon" in desc_lower:
                                    return "amd"
                                elif "intel" in desc_lower and "hd" in desc_lower or "uhd" in desc_lower or "iris" in desc_lower:
                                    return "intel"
                            except:
                                pass
                                
                            winreg.CloseKey(device_key)
                        except:
                            pass
                            
                    winreg.CloseKey(subkey)
                except:
                    pass
                    
            winreg.CloseKey(key)
        except:
            pass
        
        # Fallback: check if any Vulkan device exists (for llama-server)
        vulkan_backend = self.paths.data / "Tools" / "vulkan" / "llama-server.exe"
        if vulkan_backend.exists():
            # If vulkan backend exists but no NVIDIA, probably AMD/Intel
            return "unknown_vulkan"
        
        return "none"

    def _restore_disabled_dlls(self):
        """Restore any .disabled DLLs from previous v16 builds."""
        from pathlib import Path
        search_dirs = []
        python_dir = Path(sys.executable).parent
        for base in [python_dir, self.paths.python_dir]:
            for sub in ["Lib/site-packages", "lib/site-packages"]:
                d = base / sub
                if d.exists():
                    search_dirs.append(d)
        for site_dir in search_dirs:
            for pattern in ["llama_cpp/lib/*.disabled", "llama_cpp/*.disabled"]:
                for disabled in site_dir.glob(pattern):
                    original = disabled.with_name(
                        disabled.name.replace(".disabled", "")
                    )
                    if not original.exists():
                        try:
                            disabled.rename(original)
                            logger.info(f"  Restored DLL: {original.name}")
                        except Exception:
                            pass

    def _probe_gpu(self) -> bool:
        """
        Probe GPU compatibility BEFORE any CUDA initialization.

        This MUST run before Whisper/CTranslate2 or llama.cpp load,
        because CUDA_VISIBLE_DEVICES only takes effect before cuInit().

        Returns True if GPU is usable, False if we must use CPU.
        """
        # Cleanup: restore any .disabled DLLs from v16 build
        self._restore_disabled_dlls()

        llm_conf = self.config.get("llm", {})
        n_gpu = llm_conf.get("n_gpu_layers", -1)

        # User explicitly requested CPU
        if n_gpu == 0:
            print("\n🔍 GPU probe: skipped (CPU mode configured)")
            return False

        # Check if NVIDIA GPU exists
        import shutil
        if not shutil.which("nvidia-smi"):
            print("\n🔍 GPU probe: no NVIDIA GPU detected → CPU mode")
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            return False

        # Check for cached result from previous session
        gpu_flag = self.paths.data / "Configs" / ".gpu_status"
        if gpu_flag.exists():
            status = gpu_flag.read_text().strip()
            if status == "cpu_wheel_installed":
                print("\n🔍 GPU probe: CPU wheel active (from previous session)")
                print("   Delete Data/Configs/.gpu_status to re-test GPU")
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
                return False
            elif status == "gpu_ok":
                print("\n🔍 GPU probe: GPU verified (cached)")
                return True

        # Run LLM inference test in subprocess
        print("\n🔍 GPU probe: testing CUDA inference...")
        gpu_ok = self._test_llm_gpu()

        if gpu_ok:
            print("   ✅ GPU works — CUDA acceleration enabled")
            gpu_flag.write_text("gpu_ok")
            return True
        else:
            print("   ⚠️  GPU test failed — installing CPU-only wheel...")
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            # Install CPU-only wheel (replaces the CUDA wheel)
            if self._install_cpu_wheel():
                gpu_flag.write_text("cpu_wheel_installed")
                print("   ✅ CPU wheel installed — LLM will work in CPU mode")
            else:
                print("   ❌ Could not install CPU wheel")
                print("      Fix manually: Python\\python.exe -m pip install llama-cpp-python --force-reinstall")
            return False

    def _install_cpu_wheel(self) -> bool:
        """Install CPU-only llama-cpp-python wheel (no ggml-cuda.dll)."""
        import subprocess
        python_exe = sys.executable
        print("   📦 pip install llama-cpp-python (CPU)...")
        try:
            result = subprocess.run(
                [python_exe, "-m", "pip", "install",
                 "llama-cpp-python", "--force-reinstall", "--no-cache-dir",
                 "--break-system-packages"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                return True
            else:
                logger.warning(f"  pip install failed: {result.stderr[-200:]}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  pip install timed out")
            return False
        except Exception as e:
            logger.warning(f"  pip install error: {e}")
            return False

    def _test_llm_gpu(self) -> bool:
        """
        Test LLM GPU inference in a subprocess.

        CUDA crashes (segfaults in ggml-cuda.cu) kill the Python process.
        A try/except in Python CANNOT catch these C-level crashes.
        Running the test in a subprocess protects the main app.

        Returns True if GPU inference works, False otherwise.
        """
        import subprocess
        from pathlib import Path

        # Find model path from config (self.llm may not exist yet)
        llm_conf = self.config.get("llm", {})
        model_path = None

        # Check explicit model path in config
        model_name = llm_conf.get("model", "")
        models_dir = llm_conf.get("_models_dir", "")

        if model_name:
            p = Path(model_name)
            if p.is_absolute() and p.exists():
                model_path = str(p)
            elif models_dir:
                candidate = Path(models_dir) / model_name
                if candidate.exists():
                    model_path = str(candidate)

        # Auto-detect first GGUF in models dir
        if not model_path and models_dir:
            md = Path(models_dir)
            if md.exists():
                gguf_files = sorted(md.glob("**/*.gguf"))
                if gguf_files:
                    model_path = str(gguf_files[0])

        if not model_path:
            logger.warning("No GGUF model found for GPU test")
            return True  # No model to test — assume GPU OK

        n_gpu = llm_conf.get("n_gpu_layers", -1)
        if n_gpu == 0:
            return True  # Already CPU mode, no test needed

        test_script = self.paths.app_dir / "tools" / "test_gpu.py"
        if not test_script.exists():
            logger.warning("test_gpu.py not found, skipping GPU test")
            return True  # Assume OK (old behavior)

        python_exe = sys.executable
        try:
            result = subprocess.run(
                [python_exe, str(test_script), model_path, str(n_gpu)],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "PERKYSUE_DATA": str(self.paths.data)},
            )
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  GPU test: {line}")

            if result.returncode == 0:
                return True   # GPU works
            elif result.returncode == 2:
                return False  # GPU failed, CPU works
            else:
                logger.warning(f"  GPU test crashed (exit={result.returncode})")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-3:]:
                        logger.warning(f"  {line}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  GPU test timed out (120s)")
            return False
        except Exception as e:
            logger.warning(f"  GPU test error: {e}")
            return True  # Can't test, assume OK

    def initialize(self) -> bool:
        if self._post_update_install_started:
            print("\n⚠️  Post-update runtime mismatch detected.")
            print("   install.bat was started automatically to repair this installation.")
            print("   Please complete install.bat, then relaunch PerkySue.")
            return False
        print("\n" + "=" * 50)
        print("  🎙️  PerkySue — Initializing")
        print("=" * 50)

        print(f"\n📁 Data: {self.paths.data}")
        success = True

        # 0. GPU probe (MUST happen before ANY CUDA initialization)
        #    CUDA_VISIBLE_DEVICES only works if set before cuInit().
        #    Once CTranslate2 (Whisper) or llama.cpp touches CUDA,
        #    changing the env var has no effect.
        
        # Détection du type de GPU pour choisir le mode LLM
        self._gpu_type = self._detect_gpu_type()
        print(f"\n🎮 GPU Type: {self._gpu_type}")
        
        # Forcer server mode pour AMD/Intel (pas de CUDA native)
        if self._gpu_type in ["amd", "intel", "none"]:
            print(f"   → Using server mode (llama-server.exe) for {self._gpu_type.upper()} GPU")
            self.config["llm"]["force_server_mode"] = True
            self._gpu_available = False  # Pas de CUDA direct
        elif self._gpu_type == "nvidia":
            # Check if a CUDA backend (llama-server.exe) is available
            cuda_131 = self.paths.data / "Tools" / "nvidia-cuda-13.1" / "llama-server.exe"
            cuda_124 = self.paths.data / "Tools" / "nvidia-cuda-12.4" / "llama-server.exe"
            if cuda_131.exists() or cuda_124.exists():
                print("   → NVIDIA detected, server backend available — skipping Python probe")
                self.config["llm"]["force_server_mode"] = True
                self._gpu_available = True
            else:
                # No server backend: try direct mode via llama-cpp-python
                print("   → NVIDIA detected, no server backend — testing Python CUDA...")
                self._gpu_available = self._probe_gpu()
        else:
            self._gpu_available = False

        # 1. Modes (system modes + user custom modes)
        print("\n📋 Loading modes...")
        self.modes = load_modes(str(self.paths.modes_file))
        # Merge user custom modes (additive)
        if self.paths.custom_modes_file.exists():
            try:
                custom = load_modes(str(self.paths.custom_modes_file))
                if custom:
                    self.modes.update(custom)
                    print(f"   + {len(custom)} custom mode(s)")
            except Exception:
                pass  # Empty or invalid custom_modes.yaml is fine
        print(f"   ✅ {len(self.modes)} modes loaded")

        # 2. STT (uses GPU if available, CPU otherwise)
        print("\n🔊 Initializing STT...")
        try:
            stt_cfg = dict(self.config.get("stt", {}))
            # Merge system initial_prompt (App/defaults) with user whisper_keywords (Data, max 5)
            system_prompt = stt_cfg.get("initial_prompt") or "PerkySue, Sue"
            user_kw = stt_cfg.get("whisper_keywords") or []
            if isinstance(user_kw, list):
                user_kw = [str(x).strip() for x in user_kw if str(x).strip()][:5]
            else:
                user_kw = []
            parts = [s.strip() for s in (system_prompt or "").split(",") if s.strip()]
            parts.extend(user_kw)
            stt_cfg["initial_prompt"] = ", ".join(parts) if parts else None
            self.stt = create_stt_provider(stt_cfg)
            if self.stt.is_available():
                print(f"   ✅ {self.stt.get_name()}")
                print("   ⏳ Preloading model...")
                # GPU probe may set CUDA_VISIBLE_DEVICES="" for llama CPU fallback; clear before
                # any torch import (Whisper / STT) so PyTorch TTS can still see CUDA later.
                clear_blank_cuda_visible_devices()
                self.stt.warmup()
                print("   ✅ Model ready")
            else:
                print(f"   ❌ {self.stt.get_name()} — not available")
                success = False
        except Exception as e:
            print(f"   ❌ STT error: {e}")
            success = False

        # 3. Vérifier les microphones
        print("\n🎤 Checking microphones...")
        self.mic_warning: str | None = None
        self.mic_warning_open_settings: bool = False
        try:
            devices = AudioRecorder.list_devices()
            if devices:
                print(f"   ✅ {len(devices)} microphone(s)")
                for d in devices[:3]:
                    suffix = " (default)" if d.get("is_default") else ""
                    print(f"      - {d['name']}{suffix}")
                default_dev = next((d for d in devices if d.get("is_default")), None)
                if default_dev:
                    name_low = (default_dev["name"] or "").lower()
                    looks_virtual = any(k in name_low for k in ["iriun", "webcam", "mappeur de sons", "virtual"])
                    has_physical = any("realtek" in (d["name"] or "").lower() or "microphone" in (d["name"] or "").lower()
                                       for d in devices)
                    if looks_virtual and has_physical:
                        print("   ⚠️  Default microphone looks virtual (Iriun / virtual device).")
                        print("      → Use Windows Sound settings to select your real microphone.")
                        self.mic_warning = (
                            "Windows uses a virtual microphone (e.g. Iriun Webcam). "
                            "Open System > Sound and set your hardware mic (e.g. 'Réseau de microphones (Realtek)') as input."
                        )
                        self.mic_warning_open_settings = True
            else:
                print("   ❌ No microphone found!")
                success = False
        except Exception as e:
            print(f"   ⚠️  Microphones: {e}")

        # 4. LLM avec fallback automatique sur serveur si CUDA threading échoue
        print("\n🧠 Initializing LLM...")
        try:
            llm_conf = self._prepare_llm_conf_for_provider()
            llm_raw = self.config.get("llm") or {}
            _rin = llm_raw.get("max_input_tokens", llm_raw.get("n_ctx"))
            _rout = llm_raw.get("max_output_tokens", llm_raw.get("max_tokens"))
            try:
                raw_in_i = int(_rin) if _rin is not None and str(_rin).strip() != "" else 0
            except (TypeError, ValueError):
                raw_in_i = 0
            try:
                raw_out_i = int(_rout) if _rout is not None and str(_rout).strip() != "" else 0
            except (TypeError, ValueError):
                raw_out_i = 0
            _in_auto = " (Auto)" if raw_in_i <= 0 else ""
            _out_auto = " (Auto)" if raw_out_i <= 0 else ""
            print(
                f"   → LLM max input (context window / n_ctx): {self._effective_llm_n_ctx} tokens{_in_auto} "
                f"— shared budget: prompt + completion"
            )
            print(
                f"   → LLM max output (generation cap per reply): {self._effective_llm_max_output} tokens{_out_auto}"
            )

            # Forcer CPU si pas de GPU NVIDIA disponible
            if not self._gpu_available:
                llm_conf["n_gpu_layers"] = 0
                print("   → CPU mode (no NVIDIA GPU)")
            
            # Forcer server mode si AMD/Intel/none (déjà fait plus haut, mais double-check)
            if self._gpu_type in ["amd", "intel", "none", "unknown_vulkan"]:
                llm_conf["force_server_mode"] = True
                print(f"   → Server mode forced for {self._gpu_type} compatibility")
            
            # Vérifier que le modèle existe et sa taille
            model_path = llm_conf.get("model", "")
            if model_path:
                full_path = self.paths.models_llm / model_path
                if not full_path.exists():
                    print(f"   ❌ Model not found: {full_path}")
                    print(f"      → Place your .gguf model in: {self.paths.models_llm}")
                    self.llm = None
                else:
                    size_gb = full_path.stat().st_size / (1024**3)
                    print(f"   📦 Model: {model_path}")
                    print(f"   💾 Size: {size_gb:.1f} GB")
                    
                    # Estimation VRAM nécessaire (approximatif)
                    vram_needed = size_gb * 1.2  # +20% pour les activations
                    print(f"   🎮 VRAM needed: ~{vram_needed:.1f} GB (estimated)")
            
            # Utiliser le fallback automatique (direct → serveur)
            from services.llm import create_llm_provider_with_fallback
            self.llm, used_fallback = create_llm_provider_with_fallback(llm_conf)
            
            if self.llm and self.llm.is_available():
                mode_str = "server fallback" if used_fallback else "direct"
                print(f"   ✅ {self.llm.get_name()} ({mode_str})")
                print("   ⏳ Preloading model...")
                try:
                    self.llm.warmup()
                    print("   ✅ LLM ready")
                except Exception as warm_e:
                    print(f"   ❌ LLM warmup failed: {warm_e}")
                    print("      → Model may be incompatible or too large for your GPU")
                    self.llm = None
                    # Jouer son "LLM incompatible"
                    self.sound_manager.play_system_sound("llm_incompatible")
            else:
                print(f"   ⚠️  LLM not available")
                print("      → Raw transcription still works")
                # Jouer son "pas de LLM"
                self.sound_manager.play_system_sound("no_llm")
                
        except Exception as e:
            print(f"   ⚠️  LLM error: {e}")
            print("      → Raw transcription still works")
            # Jouer son "pas de LLM" en cas d'erreur
            try:
                self.sound_manager.play_system_sound("no_llm")
            except:
                pass
            self.llm = None

        # 5. Hotkeys (RegisterHotKey sur Windows — voir App/utils/hotkeys.py docstring)
        #    stop_recording : skip_altgr=False pour enregistrer Alt+Q ET Ctrl+Alt+Q (AltGr+Q AZERTY).
        #    Per-key listing is deferred to run() after "PerkySue is ready!" so Stop/Cancel appears last.
        print("\n⌨️  Registering hotkeys...")
        self.hotkey_manager = HotkeyManager()
        hotkeys_config = self.config.get("hotkeys", {})
        behavior = hotkeys_config.get("behavior", "toggle")

        for mode_id, hotkey_str in hotkeys_config.items():
            if mode_id == "behavior" or mode_id.endswith("_altgr"):
                continue
            if mode_id in self.modes:
                has_altgr = bool(hotkeys_config.get(mode_id + "_altgr"))
                self._register_mode_hotkey(mode_id, hotkey_str, behavior, skip_altgr=has_altgr)
                altgr_str = hotkeys_config.get(mode_id + "_altgr")
                if altgr_str:
                    self._register_mode_hotkey(mode_id, altgr_str, behavior, skip_altgr=True)

        # Stop recording / cancel LLM — hotkey dédiée (pas un mode LLM). Global : focus peut être ailleurs.
        hk_stop = (hotkeys_config.get("stop_recording") or "alt+q").lower().strip()
        if hk_stop:
            # skip_altgr=False : Alt+Q + Ctrl+Alt+Q (AltGr). Éviter alt+escape (réservé Windows).
            self.hotkey_manager.register(hk_stop, lambda: self._on_escape_hotkey(), skip_altgr=False)
        hk_stop_altgr = (hotkeys_config.get("stop_recording_altgr") or "").lower().strip()
        if hk_stop_altgr:
            self.hotkey_manager.register(hk_stop_altgr, lambda: self._on_escape_hotkey(), skip_altgr=True)
        hk_reinject = (hotkeys_config.get("reinject_last") or "alt+r").lower().strip()
        if hk_reinject:
            self.hotkey_manager.register(hk_reinject, lambda: self._on_reinject_last_hotkey(), skip_altgr=False)
        hk_reinject_altgr = (hotkeys_config.get("reinject_last_altgr") or "").lower().strip()
        if hk_reinject_altgr:
            self.hotkey_manager.register(hk_reinject_altgr, lambda: self._on_reinject_last_hotkey(), skip_altgr=True)
        print("   ✅ Hotkeys registered (full list prints after startup banner)")

        # Message final si pas de LLM
        if not self.llm or not self.llm.is_available():
            print("\n" + "!" * 50)
            print("  ⚠️  NO LLM DETECTED")
            print("!" * 50)
            try:
                from utils.installer_default_model import no_llm_hint_lines

                for line in no_llm_hint_lines(self.paths):
                    print(line)
            except Exception:
                print(f"\n  Add a GGUF model in:\n  {self.paths.models_llm}")
            print("!" * 50 + "\n")

        # Align license.json with GET /check before first GUI tier (tampered root vs payload, stale file).
        lic_path = self.paths.configs / "license.json"
        if lic_path.exists():
            try:
                self.refresh_license_from_remote(timeout_sec=12.0)
            except Exception:
                pass

        return success

    def _print_startup_hotkey_summary(self) -> None:
        """Print hotkey cheat sheet after 'PerkySue is ready!' (includes stop_recording last)."""
        hotkeys_config = self.config.get("hotkeys", {})
        print("\nHotkeys:")
        for mode_id, hotkey_str in hotkeys_config.items():
            if mode_id == "behavior" or mode_id.endswith("_altgr"):
                continue
            if mode_id in self.modes:
                print(f"  {hotkey_str:18s} → {self.modes[mode_id].name}")
                altgr_str = hotkeys_config.get(mode_id + "_altgr")
                if altgr_str:
                    print(f"  {altgr_str + ' (AltGr)':18s} → {self.modes[mode_id].name}")
        hk_stop = (hotkeys_config.get("stop_recording") or "alt+q").lower().strip()
        if hk_stop:
            print(f"  {hk_stop:18s} → Stop recording / Cancel")
        hk_stop_altgr = (hotkeys_config.get("stop_recording_altgr") or "").lower().strip()
        if hk_stop_altgr:
            print(f"  {hk_stop_altgr + ' (AltGr)':18s} → Stop recording / Cancel")
        hk_reinject = (hotkeys_config.get("reinject_last") or "alt+r").lower().strip()
        if hk_reinject:
            label = "Re-inject last result"
            print(f"  {hk_reinject:18s} → {label}")
        hk_reinject_altgr = (hotkeys_config.get("reinject_last_altgr") or "").lower().strip()
        if hk_reinject_altgr:
            label = "Re-inject last result"
            print(f"  {hk_reinject_altgr + ' (AltGr)':18s} → {label}")
        print("\n  AltGr is supported (international keyboards).")

    def reload_stt_keywords(self):
        """Re-merge system initial_prompt + user whisper_keywords and update STT (after GUI save)."""
        if not self.stt or not getattr(self.stt, "set_initial_prompt", None):
            return
        self.config = self._load_merged_config()
        stt_cfg = self.config.get("stt", {})
        system_prompt = stt_cfg.get("initial_prompt") or "PerkySue, Sue"
        user_kw = stt_cfg.get("whisper_keywords") or []
        if isinstance(user_kw, list):
            user_kw = [str(x).strip() for x in user_kw if str(x).strip()][:5]
        else:
            user_kw = []
        parts = [s.strip() for s in (system_prompt or "").split(",") if s.strip()]
        parts.extend(user_kw)
        merged = ", ".join(parts) if parts else None
        self.stt.set_initial_prompt(merged)

    def _rebuild_audio_recorder_from_config(self) -> None:
        """Construit ``self.recorder`` depuis ``self.config`` (même règles que le boot)."""
        audio_config = self.config.get("audio", {})
        stt_conf = self.config.get("stt") or {}
        self._silence_timeout = float(audio_config.get("silence_timeout", 2.0) or 2.0)
        max_dur_cfg = audio_config.get("max_duration")
        if max_dur_cfg is not None:
            try:
                max_duration = float(max_dur_cfg) or 0.0
            except (TypeError, ValueError):
                max_duration = 0.0
        else:
            max_duration = 0.0
        if max_duration <= 0.0:
            backend = os.environ.get("PERKYSUE_BACKEND", "").lower()
            stt_model_name = (stt_conf.get("model") or "").lower()
            if backend.startswith("nvidia-"):
                max_duration = 180.0
            else:
                if stt_model_name == "small":
                    max_duration = 120.0
                else:
                    max_duration = 90.0
        if max_duration > 900.0:
            logger.warning("audio.max_duration=%s exceeds 900s cap — using 900", max_duration)
            max_duration = 900.0
        capture_mode = (audio_config.get("capture_mode") or "mic_only").strip().lower()
        mic_dev = audio_config.get("mic_device")
        lb_dev = audio_config.get("loopback_device")

        def _optional_audio_device_index(v: Any) -> Optional[int]:
            if v is None or v is True or v is False:
                return None
            s2 = str(v).strip()
            if s2 == "" or s2.lower() in ("null", "none"):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        mic_device = _optional_audio_device_index(mic_dev)
        loopback_device = _optional_audio_device_index(lb_dev)
        try:
            mix_mic_gain = float(audio_config.get("mix_mic_gain", 1.0) or 1.0)
        except (TypeError, ValueError):
            mix_mic_gain = 1.0
        try:
            mix_loopback_gain = float(audio_config.get("mix_loopback_gain", 0.8) or 0.8)
        except (TypeError, ValueError):
            mix_loopback_gain = 0.8

        self.recorder = build_audio_recorder(
            sample_rate=audio_config.get("sample_rate", 16000),
            vad_sensitivity=audio_config.get(
                "vad_sensitivity", audio_config.get("vad_aggressiveness", "normal")
            ),
            silence_timeout=self._silence_timeout,
            max_duration=max_duration,
            capture_mode=capture_mode,
            mic_device=mic_device,
            loopback_device=loopback_device,
            mix_mic_gain=mix_mic_gain,
            mix_loopback_gain=mix_loopback_gain,
            on_input_level=self.tts_manager.input_feed_meter,
            on_input_stop=self.tts_manager.reset_input_meter,
            pipeline_debug=self._audio_pipeline_debug(),
        )
        try:
            import sounddevice as sd

            if mic_device is None:
                di, _ = sd.default.device
                ni = sd.query_devices(di, "input")
                mic_line = f"mic=default (sounddevice input #{di} «{(ni.get('name') or '')[:80]}»)"
            else:
                try:
                    ni = sd.query_devices(int(mic_device), "input")
                    mic_line = f"mic=#{mic_device} «{(ni.get('name') or '')[:80]}»"
                except Exception:
                    mic_line = f"mic=#{mic_device} (name lookup failed — check Settings → Microphone)"
            logger.info(
                "Audio capture mode: %s (%s; loopback_output_device=%s)",
                capture_mode,
                mic_line,
                loopback_device,
            )
        except Exception:
            logger.info(
                "Audio capture mode: %s (mic_device=%s loopback_output_device=%s)",
                capture_mode,
                mic_device,
                loopback_device,
            )

    def reload_audio_capture(self) -> tuple[bool, str]:
        """Recharge la source audio STT depuis la config fusionnée (sans redémarrage app)."""
        with self._lock:
            if self._is_processing or self._is_recording:
                return False, "Cannot apply while recording or processing."
        try:
            self.config = self._load_merged_config()
            self._rebuild_audio_recorder_from_config()
            return True, "STT audio source applied."
        except Exception as e:
            logger.exception("Hot-reload audio capture failed: %s", e)
            return False, f"Apply audio failed: {e}"

    def reload_llm_runtime(self):
        """Hot-reload LLM provider from current config without full app restart.

        Returns:
            tuple[bool, str]: (success, message)
        """
        with self._lock:
            if self._is_processing or self._is_recording:
                return False, "Cannot apply while recording or processing."

        old_llm = self.llm
        try:
            # Reload merged config from disk (defaults + user overrides)
            self.config = self._load_merged_config()
            self._sync_strings_locale_from_config()
            self._answer_context_n_qa = self._answer_context_keep_from_config(self.config)
            llm_conf = self._prepare_llm_conf_for_provider()

            # Keep runtime safety rules aligned with init path.
            if not getattr(self, "_gpu_available", False):
                llm_conf["n_gpu_layers"] = 0
            if getattr(self, "_gpu_type", "") in ["amd", "intel", "none", "unknown_vulkan"]:
                llm_conf["force_server_mode"] = True

            model_path = (llm_conf.get("model") or "").strip()
            if model_path:
                full_path = self.paths.models_llm / model_path
                if not full_path.exists():
                    return False, f"Model not found: {model_path}"

            from services.llm import create_llm_provider_with_fallback
            new_llm, used_fallback = create_llm_provider_with_fallback(llm_conf)
            if not new_llm or not new_llm.is_available():
                return False, "LLM provider is not available."

            # Warmup before swapping provider so current session stays stable on failure.
            new_llm.warmup()
            self.llm = new_llm
            mode_str = "server fallback" if used_fallback else "direct"
            return True, f"LLM applied: {new_llm.get_name()} ({mode_str})"
        except Exception as e:
            self.llm = old_llm
            logger.error("Hot-reload LLM failed: %s", e)
            return False, f"Apply LLM failed: {e}"

    # ─── Prompt mode testing (GUI live test box) ──────────────────────

    def test_mode_prompt(
        self,
        mode_id: str,
        text: str,
        selected_text: str = "",
        prompt_override: str | None = None,
        source_lang_override: str | None = None,
    ) -> str:
        """
        Run a single LLM call for a given mode and plain text.

        Used by the Prompt Modes GUI live test box: bypasses audio/STT and
        injects `text` directly into the LLM with the same system prompt
        logic as the main pipeline.
        """
        mode = self.modes.get(mode_id)
        if not mode:
            raise ValueError(f"Unknown mode: {mode_id}")

        # If mode doesn't require LLM, just echo text.
        if not getattr(mode, "needs_llm", False):
            return text

        if self._llm_required_but_missing(mode_id):
            # Reuse the central alert (sound + blinking header).
            self._alert_no_llm()
            raise RuntimeError("LLM not available for testing.")

        # Use merged config (defaults + user) for language / identity.
        self.config = self._load_merged_config()
        self._recompute_effective_llm_context()
        modes_config = self.config.get("modes", {})
        identity_cfg = self.config.get("identity", {}) or {}
        user_name = identity_cfg.get("name", "") or ""

        # If GUI passes a prompt override (unsaved edits), use a temporary copy of the mode.
        mode_for_render = mode
        if prompt_override is not None:
            try:
                mode_for_render = Mode(
                    id=mode.id,
                    name=mode.name,
                    description=mode.description,
                    needs_llm=mode.needs_llm,
                    system_prompt=prompt_override,
                )
            except Exception:
                mode_for_render = mode

        # Run Test: allow explicit source language override from sample selector (EN*/FR*).
        if source_lang_override and str(source_lang_override).strip():
            raw_sl = str(source_lang_override).strip().lower()
        else:
            # Fallback behavior: last Whisper language if available, else config.
            raw_sl = getattr(self, "last_stt_detected_language", None) or modes_config.get(
                "translate_source", "auto"
            )
        raw_tl = modes_config.get("translate_target", "en")
        if (mode_id or "").strip().lower() == "help":
            # Mode Help : prompt système = paramètres + KB + instructions ; message user = texte du test.
            system_prompt = self._build_help_system_prompt(mode_for_render, user_name, raw_sl, user_text=text)
        else:
            system_prompt = render_prompt(
                mode_for_render,
                text,
                source_lang=raw_sl,
                target_lang=raw_tl,
                selected_text=selected_text,
                user_name=user_name,
            )
        system_prompt = self._append_voice_mode_overlay(
            system_prompt,
            (mode_id or "").strip().lower(),
            user_name=user_name,
            stt_lang=raw_sl,
            target_lang=raw_tl,
        )
        system_prompt = self._append_tts_llm_extension(
            system_prompt, (mode_id or "").strip().lower(), reply_language=raw_sl
        )
        # Verify test path uses same substitution as live pipeline; log metadata only (no prompt body).
        try:
            has_sl = "{source_lang}" in (system_prompt or "")
            has_tl = "{target_lang}" in (system_prompt or "")
            logger.info(
                "test_mode_prompt mode_id=%s translate_source=%r translate_target=%r "
                "unresolved_{source_lang}=%s unresolved_{target_lang}=%s system_prompt_len=%d (content not logged)",
                mode_id,
                raw_sl,
                raw_tl,
                has_sl,
                has_tl,
                len(system_prompt or ""),
            )
            if has_sl or has_tl:
                logger.warning(
                    "test_mode_prompt: placeholders still present after render_prompt; check modes/__init__.py"
                )
        except Exception:
            pass

        # Keep status/notifications minimal to avoid interfering with normal UI.
        self._set_status("processing")
        try:
            result = self._run_llm_on_main_thread(
                text=text,
                system_prompt=system_prompt,
                temperature=self.config.get("llm", {}).get("temperature", 0.3),
                max_tokens=self.get_effective_llm_max_output(),
                gui_debug_label="mode_prompt_test",
            )
            return self._strip_thinking_blocks((result.text or "").strip())
        finally:
            self._set_status("ready")

    def pause_hotkeys(self) -> None:
        """Temporarily stop global hotkeys (e.g. while editing a shortcut in Shortcuts Manager)."""
        if self.hotkey_manager:
            self.hotkey_manager.stop()

    def resume_hotkeys(self) -> None:
        """Restart global hotkeys after pause_hotkeys (e.g. after shortcut edit or cancel)."""
        if self.hotkey_manager and self.hotkey_manager._hotkeys:
            t = threading.Thread(target=self.hotkey_manager.start, daemon=True)
            self.hotkey_manager._thread = t
            t.start()

    def _on_escape_hotkey(self) -> None:
        """Hotkey stop_recording (défaut Alt+Q) : arrêt enregistrement ou annulation LLM. GUI sur le thread principal."""
        if self.is_continuous_chat_enabled():
            self.set_continuous_chat_enabled(False)
        w = getattr(self, "widget", None)
        if w and getattr(w, "root", None):
            try:
                if hasattr(w, "_request_escape_global_once"):
                    w._request_escape_global_once()
                else:
                    w.root.after(0, w._on_escape_global)
            except Exception:
                pass

    def is_continuous_chat_enabled(self) -> bool:
        return bool(getattr(self, "_continuous_chat_enabled", False))

    def reset_continuous_chat_listen_blockers(self) -> None:
        """Débloque le réarmement micro du Continuous Chat (cooldown TTS + attente GUI post-injection).

        À appeler quand l'utilisateur interrompt (Alt+Q, annulation) pour ne pas rester coincé derrière
        ``_continuous_gui_tts_pending`` ou un ``_continuous_tts_cooldown_until`` énorme après un TTS arrêté.
        """
        if self._audio_pipeline_debug():
            logger.info("[continuous] reset_listen_blockers (cooldown + gui_tts_pending cleared)")
        self._continuous_tts_cooldown_until = 0.0
        with self._lock:
            self._continuous_gui_tts_pending = False

    def _extend_continuous_tts_cooldown(self, seconds: float) -> None:
        """While Continuous Chat is on, delay the next mic arm after TTS to avoid loopback STT."""
        if not self.is_continuous_chat_enabled():
            return
        try:
            add = max(0.0, float(seconds))
        except Exception:
            add = 0.0
        if add <= 0.0:
            return
        now = time.monotonic()
        cur = float(getattr(self, "_continuous_tts_cooldown_until", 0.0) or 0.0)
        self._continuous_tts_cooldown_until = max(cur, now + add)
        if self._audio_pipeline_debug():
            logger.info(
                "[continuous] tts_cooldown_extend +%.2fs until_mono=%.2f",
                add,
                self._continuous_tts_cooldown_until,
            )

    def _continuous_chat_worker(self) -> None:
        """Hands-free Ask loop: record until silence, process answer, then arm again."""
        logger.info("Continuous Chat worker started")
        was_speaking = False
        _cc_dbg_last = 0.0
        try:
            while self.is_continuous_chat_enabled():
                try:
                    tm = getattr(self, "tts_manager", None)
                    speaking = bool(tm and getattr(tm, "is_speaking", None) and tm.is_speaking())
                except Exception:
                    speaking = False
                now = time.monotonic()
                if speaking:
                    was_speaking = True
                elif was_speaking:
                    # Anti-loopback margin after is_speaking clears (kept modest; schedule below also adds tail).
                    self._extend_continuous_tts_cooldown(0.75)
                    was_speaking = False

                with self._lock:
                    busy = self._is_processing or self._is_recording
                    gui_tts_pending = bool(getattr(self, "_continuous_gui_tts_pending", False))
                cooldown_until = float(getattr(self, "_continuous_tts_cooldown_until", 0.0) or 0.0)
                if speaking or busy or gui_tts_pending or now < cooldown_until:
                    if self._audio_pipeline_debug():
                        t = time.monotonic()
                        if t - _cc_dbg_last >= 1.0:
                            _cc_dbg_last = t
                            logger.info(
                                "[continuous] wait | speaking=%s busy=%s gui_tts_pending=%s "
                                "cooldown_left_sec=%.2f",
                                speaking,
                                busy,
                                gui_tts_pending,
                                max(0.0, cooldown_until - now),
                            )
                    time.sleep(0.15)
                    continue

                try:
                    self.stop_voice_output()
                    with self._lock:
                        if not self._continuous_chat_enabled:
                            break
                        self._is_recording = True
                        self._current_mode = "answer"
                        self._target_window = get_active_window()
                    if self._audio_pipeline_debug():
                        cap = str((self.config.get("audio") or {}).get("capture_mode") or "?")
                        logger.info(
                            "[continuous] arm_turn | capture_mode=%s target_hwnd=%s",
                            cap,
                            getattr(self, "_target_window", None),
                        )
                    self._record_and_process(
                        "answer",
                        selected_text="",
                        from_chat_ui=True,
                        suppress_stt_feedback=True,
                        suppress_no_speech_feedback=True,
                        continuous_chat_turn=True,
                    )
                except Exception as e:
                    logger.exception("Continuous Chat turn failed: %s", e)
                    with self._lock:
                        self._is_recording = False
                    self._set_status("ready")
                    time.sleep(0.35)
                time.sleep(0.08)
        finally:
            self._continuous_chat_thread = None
            with self._lock:
                if not self._is_processing and not self._is_recording:
                    self._set_status("ready")
            logger.info("Continuous Chat worker stopped")

    def set_continuous_chat_enabled(self, enabled: bool) -> tuple[bool, str]:
        """Enable/disable hands-free Ask loop (Chat tab microphone stays logically armed)."""
        want = bool(enabled)
        cur = self.is_continuous_chat_enabled()
        if want == cur:
            return True, "already_on" if want else "already_off"

        if want:
            if self._llm_required_but_missing("answer"):
                self._alert_no_llm()
                return False, "no_llm"
            self.reset_continuous_chat_listen_blockers()
            self._continuous_chat_enabled = True
            if self._audio_pipeline_debug():
                cap = str((self.config.get("audio") or {}).get("capture_mode") or "?")
                logger.info("[continuous] enabled | capture_mode=%s", cap)
            t = threading.Thread(target=self._continuous_chat_worker, daemon=True)
            self._continuous_chat_thread = t
            t.start()
            return True, "started"

        self._continuous_chat_enabled = False
        if self._audio_pipeline_debug():
            logger.info("[continuous] disabled")
        self.reset_continuous_chat_listen_blockers()
        # Stop any current turn immediately so loop can terminate quickly.
        try:
            self.stop_recording()
            self.request_cancel()
        except Exception:
            pass
        return True, "stopped"

    def _mode_hotkeys_suppressed(self) -> bool:
        return time.monotonic() < float(getattr(self, "_suppress_mode_hotkeys_until", 0.0) or 0.0)

    def _interrupt_continuous_for_manual_mode(self, mode_id: str) -> None:
        """Manual mode hotkeys override Continuous Chat immediately."""
        if not self.is_continuous_chat_enabled():
            return
        logger.info("Manual hotkey '%s' overrides Continuous Chat.", (mode_id or "").strip())
        self.set_continuous_chat_enabled(False)
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            rec = getattr(self, "recorder", None)
            rec_active = bool(rec and getattr(rec, "is_recording", False))
            with self._lock:
                busy = bool(self._is_processing or self._is_recording)
            if not busy and not rec_active:
                break
            time.sleep(0.03)

    def _on_reinject_last_hotkey(self) -> None:
        """Hotkey reinject_last (défaut Alt+R) : colle à nouveau le dernier résultat PerkySue (fenêtre active)."""
        with self._lock:
            if self._is_recording:
                return
        # Guard window: ignore accidental mode hotkeys while reinject sends synthetic Ctrl+V.
        self._suppress_mode_hotkeys_until = time.monotonic() + 1.2
        logger.info("Hotkey reinject_last triggered")
        t = threading.Thread(target=self._reinject_last_worker, daemon=True)
        t.start()

    def _reinject_last_worker(self) -> None:
        try:
            self._sync_strings_locale_from_config()
        except Exception:
            pass
        w = getattr(self, "widget", None)
        payload = ""

        def _notify_safe(msg: str, ok: bool):
            if not w or not getattr(w, "root", None):
                return
            try:
                if ok:

                    def _ok():
                        w._notify(msg, restore_after_ms=2200)

                    w.root.after(0, _ok)
                else:

                    def _bad():
                        w._notify(
                            msg,
                            restore_after_ms=4000,
                            blink_times=3,
                            blink_on_ms=300,
                            blink_off_ms=300,
                        )

                    w.root.after(0, _bad)
            except Exception:
                pass

        # Reinject source of truth: latest non-empty finalized log entry from widget console.
        if w is not None:
            try:
                entries = getattr(w, "_console_entries", None) or []
                for entry in reversed(entries):
                    txt = (entry.get("text") or "").strip()
                    if txt:
                        payload = txt
                        # Keep memory cache aligned for diagnostics/legacy reads.
                        self._last_inject_payload = txt
                        break
            except Exception:
                pass

        # Defensive fallback only if widget/logs are unavailable.
        if not payload and w is None:
            payload = (getattr(self, "_last_inject_payload", None) or "").strip()

        if not payload:
            _notify_safe(i18n_s("shortcuts.reinject_empty"), False)
            return

        # Hotkey is triggered while Alt may still be physically down.
        # Give modifiers a brief time to release before sending Ctrl+V.
        time.sleep(0.18)

        try:
            self._target_window = get_active_window()
        except Exception:
            self._target_window = None

        inj = self.config.get("injection", {}) if isinstance(self.config, dict) else {}
        try:
            reinject_restore_delay = float(inj.get("clipboard_restore_delay_sec", 5))
        except (TypeError, ValueError):
            reinject_restore_delay = 5.0
        try:
            ok = inject_text(
                text=payload,
                method=inj.get("method", "clipboard"),
                restore_clipboard=inj.get("restore_clipboard", True),
                delay_ms=inj.get("delay_ms", 100),
                target_window=self._target_window,
                # Reinject is independent from clipboard source, but transport still uses Ctrl+V.
                # Keep same restore window as standard injection for reliability across apps.
                clipboard_restore_delay_sec=reinject_restore_delay,
            )
            _notify_safe(i18n_s("shortcuts.reinject_ok") if ok else i18n_s("shortcuts.reinject_fail"), ok)
        except Exception as e:
            logger.error("reinject_last worker failed: %s", e)
            _notify_safe(i18n_s("shortcuts.reinject_fail"), False)

    def _register_mode_hotkey(self, mode_id, hotkey_str, behavior, skip_altgr: bool = False):
        if behavior == "push_to_talk":
            self.hotkey_manager.register(
                hotkey_str,
                callback=lambda m=mode_id: self._on_hotkey_press(m),
                on_release=lambda m=mode_id: self._on_hotkey_release(m),
                skip_altgr=skip_altgr,
            )
        else:
            self.hotkey_manager.register(
                hotkey_str,
                callback=lambda m=mode_id: self._on_hotkey_toggle(m),
                skip_altgr=skip_altgr,
            )

    def _alert_no_llm(self) -> None:
        """User tried to use an LLM shortcut without an available LLM."""
        try:
            self.sound_manager.play_system_sound("no_llm")
        except Exception:
            pass
        w = getattr(self, "widget", None)
        if w and getattr(w, "root", None):
            try:
                msg = w._get_alert("critical.no_llm")
                w.root.after(0, lambda: w._notify(msg, restore_after_ms=4000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
            except Exception:
                pass

    def _llm_required_but_missing(self, mode_id: str) -> bool:
        try:
            mode = self.modes.get(mode_id)
            if not mode or not getattr(mode, "needs_llm", False):
                return False
            return (not self.llm) or (not self.llm.is_available())
        except Exception:
            return True

    def _redirect_locked_mode_to_help(self, mode_id: str) -> None:
        """When a Pro-only mode is used in Free, redirect user to Help and auto-send a clear question."""
        try:
            w = getattr(self, "widget", None)
            if not w or not getattr(w, "root", None):
                return
            orig_hwnd = getattr(self, "_target_window", None)
            def _do():
                try:
                    hotkeys = (self.config.get("hotkeys") or {}) if isinstance(self.config, dict) else {}
                    hk = hotkeys.get(mode_id, "") or ""
                    label = (mode_id or "").strip()
                    # Build an EN first-person user message, then translate to user's language (any ISO code).
                    preferred = (self.config.get("identity") or {}).get("first_language", "auto")
                    preferred = (preferred or "auto").strip().lower()
                    lang = (self.last_stt_detected_language or "en")[:2] if preferred == "auto" else preferred[:2]
                    # Ensure the greeting (triggered by w._go("help")) uses the right language.
                    # Greeting logic uses orch.last_stt_detected_language when identity.first_language is "auto".
                    try:
                        self.last_stt_detected_language = (lang or "en")[:2]
                    except Exception:
                        pass
                    prompt_en = (
                        f"I'm trying to use the '{label}' mode ({hk})."
                    )
                    # Skip greeting once so the answer is the first bubble.
                    if hasattr(w, "_mark_help_skip_greeting_once"):
                        w._mark_help_skip_greeting_once()
                    w._go("help")
                    # The redirect to Help steals focus. Restore focus so the next Alt+T paste goes to the user's app.
                    try:
                        if orig_hwnd:
                            restore_window(orig_hwnd)
                    except Exception:
                        pass
                    # Auto-send the Help question (no need to touch the type-in)
                    try:
                        self.run_help_text(prompt_en, source_lang=lang, translate_user_text=True, silent=True)
                    except Exception:
                        pass
                    if hasattr(w, "_notify_pro_locked"):
                        w._notify_pro_locked()
                    else:
                        try:
                            self.sound_manager.play_system_sound("llm_error")
                        except Exception:
                            pass
                        msg = w._get_alert(
                            "regular.pro_plan_required_mode",
                            default="This mode is locked on Free — Pro plan required.",
                        )
                        w._notify(msg, restore_after_ms=4000, blink_times=3, blink_on_ms=300, blink_off_ms=300)
                except Exception:
                    pass
            w.root.after(0, _do)
        except Exception:
            pass

    def stop_voice_output(self):
        """Stop TTS playback when starting new voice capture (Alt / mic) or a new Ask/Help turn."""
        try:
            tm = getattr(self, "tts_manager", None)
            if tm:
                tm.stop()
        except Exception:
            pass

    def _on_hotkey_toggle(self, mode_id, from_chat_ui: bool = False):
        try:
            if self._mode_hotkeys_suppressed():
                return
            # Any manual shortcut should temporarily/explicitly take over from Continuous Chat.
            self._interrupt_continuous_for_manual_mode(mode_id)
            self.stop_voice_output()
            with self._lock:
                if self._is_processing:
                    return  # Ignore — prevents LLM crash when Alt+X then Alt+Y pressed consecutively
                if self._is_recording:
                    return  # Ignore — use Alt+Q (stop_recording) or click avatar to stop; prevents pipeline overlap
                self._is_recording = True
                self._current_mode = mode_id
                self._target_window = get_active_window()

            # Plan gating: block Pro-only modes in Free and redirect to Help.
            try:
                if not self.can_use_mode_effective(mode_id):
                    with self._lock:
                        self._is_recording = False
                    self._set_status("ready")
                    self._redirect_locked_mode_to_help(mode_id)
                    return
            except Exception:
                pass

            # If this shortcut requires an LLM but none is available, alert and abort early.
            if self._llm_required_but_missing(mode_id):
                with self._lock:
                    self._is_recording = False
                self._set_status("ready")
                self._alert_no_llm()
                return

            selected_text = ""
            try:
                selected_text = grab_selection()
            except Exception as e:
                logger.warning("grab_selection failed: %s", e)
            if selected_text:
                self._notify(f"📋 Selection: {len(selected_text)} chars")

            # Alt+A: open Chat tab so user can follow the conversation there
            if mode_id == "answer":
                w = getattr(self, "widget", None)
                if w and getattr(w, "root", None):
                    try:
                        w.root.after(0, lambda: w._go("chat"))
                    except Exception:
                        pass
            # Alt+H: open Help tab so user sees the Q/A there
            if mode_id == "help":
                w = getattr(self, "widget", None)
                if w and getattr(w, "root", None):
                    try:
                        w.root.after(0, lambda: w._go("help"))
                    except Exception:
                        pass

            self._record_and_process(mode_id, selected_text, from_chat_ui)
        except Exception as e:
            logger.exception("Hotkey toggle failed: %s", e)
            with self._lock:
                self._is_recording = False
            self._set_status("ready")

    def _on_hotkey_press(self, mode_id):
        try:
            if self._mode_hotkeys_suppressed():
                return
            # Any manual shortcut should temporarily/explicitly take over from Continuous Chat.
            self._interrupt_continuous_for_manual_mode(mode_id)
            self.stop_voice_output()
            with self._lock:
                if self._is_processing:
                    return  # Ignore — prevents LLM crash on consecutive shortcuts
                if self._is_recording:
                    return
                self._is_recording = True
                self._current_mode = mode_id
                self._target_window = get_active_window()

            # Plan gating: block Pro-only modes in Free and redirect to Help.
            try:
                if not self.can_use_mode_effective(mode_id):
                    with self._lock:
                        self._is_recording = False
                    self._set_status("ready")
                    self._redirect_locked_mode_to_help(mode_id)
                    return
            except Exception:
                pass

            # If this shortcut requires an LLM but none is available, alert and abort early.
            if self._llm_required_but_missing(mode_id):
                with self._lock:
                    self._is_recording = False
                self._set_status("ready")
                self._alert_no_llm()
                return

            try:
                self._selected_text = grab_selection()
            except Exception as e:
                logger.warning("grab_selection failed: %s", e)
                self._selected_text = ""
            if self._selected_text:
                self._notify(f"📋 Selection: {len(self._selected_text)} chars")

            self.sound_manager.play_stt_start()
            self.recorder.start()
            self._set_status("listening")
            self._notify("🎙️ Listening...")
        except Exception as e:
            logger.exception("Hotkey press failed: %s", e)
            try:
                self.sound_manager.play_stt_stop()
            except Exception:
                pass
            try:
                if self.recorder and getattr(self.recorder, "is_recording", False):
                    self.recorder.stop()
            except Exception:
                pass
            with self._lock:
                self._is_recording = False
            self._set_status("ready")

    def _on_hotkey_release(self, mode_id):
        try:
            with self._lock:
                if not self._is_recording:
                    return
                self._is_recording = False
            audio = self.recorder.stop()
            self.sound_manager.play_stt_stop()
            duration = len(audio) / float(self.recorder.sample_rate) if len(audio) > 0 else 0.0
            if len(audio) > 0:
                self._process_audio(audio, mode_id, getattr(self, '_selected_text', ''), duration=duration)
            else:
                # Aucune frame audio reçue → problème d'entrée plutôt que simple silence utilisateur
                self._set_status("error")
                self._notify(
                    "Recording failed — no audio captured. Check microphone / Windows devices, "
                    "or audio.capture_mode (system_only = WASAPI loopback on default output)."
                )
                self._set_status("ready")
        except Exception as e:
            logger.exception("Hotkey release failed: %s", e)
            self._set_status("ready")

    def stop_recording(self) -> None:
        """Arrêt manuel de l'enregistrement (ex. clic sur l'avatar dans la GUI)."""
        # Be tolerant to UI/recorder state races: always drop internal recording state,
        # then request recorder stop when available.
        if self._audio_pipeline_debug():
            rec0 = getattr(self, "recorder", None)
            logger.info(
                "[pipeline] stop_recording | orch_is_recording=%s rec_is_recording=%s",
                getattr(self, "_is_recording", None),
                bool(rec0 and getattr(rec0, "is_recording", False)),
            )
        with self._lock:
            self._is_recording = False
        rec = getattr(self, "recorder", None)
        if rec and getattr(rec, "is_recording", False):
            rec.request_stop()

    def reset_cancel_request(self) -> None:
        """Clear the user-cancel flag (e.g. after a Brainstorm plugin session ends)."""
        self._cancel_requested = False

    def request_cancel(self) -> None:
        """Demande d'interruption du traitement (ex. clic avatar pendant processing). Le pipeline sort avant/sans LLM."""
        self._cancel_requested = True
        try:
            tm = getattr(self, "tts_manager", None)
            if tm:
                tm.stop()
        except Exception:
            pass
        if self.is_continuous_chat_enabled():
            self.reset_continuous_chat_listen_blockers()

    def _effective_speech_language_for_tts(self, stt_result) -> str:
        """Language for TTS tag whitelist: current STT result first (same as LLM ``stt_lang``), then last STT, else identity, else en."""
        if stt_result is not None and getattr(stt_result, "language", None):
            return normalize_speech_lang(stt_result.language)
        lang = getattr(self, "last_stt_detected_language", None)
        if lang:
            return normalize_speech_lang(lang)
        ident = self.config.get("identity") or {}
        fl = (ident.get("first_language") or "").strip().lower()
        if fl and fl != "auto":
            return normalize_speech_lang(fl)
        return "en"

    def _assistant_skin_identity_appendix(self, skin_active: str) -> str:
        """Short system prompt clause: user-chosen skin name vs product name PerkySue. Empty if Default."""
        char = skin_character_display_name(skin_active)
        if not char:
            return ""
        return (
            "**Assistant display identity (user-chosen skin)**\n"
            f"The user selected the avatar character **{char}**. When asked your name or addressed in character, "
            f"you are **{char}**, consistent with the speaking personality above. "
            "**PerkySue** is the name of this application — use it when stating what the software is or citing "
            "factual product information from the knowledge base, not as your personal name when the user is "
            f"interacting with **{char}**."
        )

    def _append_tts_llm_extension(
        self,
        system_prompt: str,
        mode_id: str,
        reply_language: Optional[str] = None,
    ) -> str:
        """Append TTS tag palette + personality when Pro TTS is on.

        ``reply_language`` (STT / mode source lang) selects Chatterbox Turbo vs MTL tag list only,
        saving context tokens. If omitted, uses ``last_stt_detected_language`` or ``en``.

        Applied when: effective Pro, ``tts_manager.enabled``, and ``mode_id`` is in
        ``tts_manager.trigger_modes`` (default: ``answer``, ``help``).

        Call sites (keep in sync):
        - Live LLM: ``_process_audio_impl`` after building ``system_prompt`` for any
          ``needs_llm`` mode (no-op when ``mode_id`` not in triggers).
        - Prompt Modes **Run Test**: ``test_mode_prompt`` (same rule).
        - Help prompt preview: ``get_help_effective_system_prompt`` so the GUI matches
          the payload sent to the LLM.

        Intentionally **not** extended (different roles / no spoken user-facing reply
        from these paths): Help intent router (HELP/NOHELP), ``_translate_user_short_prompt``,
        greeting LLM (``get_greeting_from_llm``), Alt+S summarization LLM, STT
        ``initial_prompt`` parsing.

        When the active skin is not Default, a short **Assistant display identity** clause
        is appended after the TTS block (same injection point) so the model uses the skin
        name as the character while keeping **PerkySue** as the software name in KB-style answers.
        """
        tm = getattr(self, "tts_manager", None)
        if not tm or not getattr(tm, "enabled", False) or not self.is_effective_pro():
            return system_prompt
        # Only include tag palette/personality when speech output is expected.
        # If the user turned off auto-speak (and we don't read payload aloud), the extra tokens are wasted.
        try:
            auto_speak = bool(getattr(tm, "auto_speak", False))
        except Exception:
            auto_speak = False
        try:
            read_aloud_payload = bool(getattr(tm, "read_aloud_payload", False))
        except Exception:
            read_aloud_payload = False
        if not auto_speak and not read_aloud_payload:
            return system_prompt
        mid = (mode_id or "").strip().lower()
        try:
            triggers = set(getattr(tm, "trigger_modes", None) or [])
        except Exception:
            triggers = set()
        if mid not in triggers:
            return system_prompt
        try:
            from services.tts.prompt_extension import build_tts_llm_appendix, load_tts_prompt_config

            cfg = load_tts_prompt_config(self.paths)
            skin = (self.config.get("skin") or {}).get("active", "Default")
            try:
                tts_skin = getattr(tm, "_tts_skin_id", None)
                if isinstance(tts_skin, str) and tts_skin.strip():
                    skin = tts_skin.strip()
            except Exception:
                pass
            skin = normalize_skin_id(self.paths, skin)
            eng = getattr(tm, "preferred_engine_id", None) or "chatterbox"
            lang = reply_language
            if not lang or str(lang).strip().lower() in ("", "auto"):
                lang = getattr(self, "last_stt_detected_language", None) or "en"
            block = build_tts_llm_appendix(
                self.paths, str(eng), str(skin), base_cfg=cfg, reply_language=str(lang)
            )
            if not block:
                return system_prompt
            identity = self._assistant_skin_identity_appendix(str(skin))
            if identity:
                block = f"{block}\n\n{identity}"
            return (system_prompt or "").rstrip() + "\n\n---\n\n" + block
        except Exception as e:
            logger.warning("TTS LLM extension skipped: %s", e)
            return system_prompt

    def _voice_payload_globally_on(self) -> bool:
        tm = getattr(self, "tts_manager", None)
        if not tm or not getattr(tm, "enabled", False):
            return False
        if not getattr(tm, "voice_payload_enabled", True):
            return False
        return self.is_effective_pro()

    def _voice_payload_effective(self, mode_id: str) -> bool:
        if not self._voice_payload_globally_on():
            return False
        mid = (mode_id or "").strip().lower()
        vm = self._voice_mode_overlays.get(mid)
        return bool(vm and vm.enabled and (vm.system_prompt or "").strip())

    def _append_voice_mode_overlay(
        self,
        system_prompt: str,
        mode_id: str,
        *,
        user_name: str,
        stt_lang: str,
        target_lang: str,
    ) -> str:
        mid = (mode_id or "").strip().lower()
        if not self._voice_payload_effective(mid):
            return system_prompt
        vm = self._voice_mode_overlays.get(mid)
        if not vm or not (vm.system_prompt or "").strip():
            return system_prompt
        overlay_mode = Mode(
            id=mid,
            name="",
            description="",
            needs_llm=True,
            system_prompt=vm.system_prompt,
        )
        block = render_prompt(
            overlay_mode,
            "",
            source_lang=stt_lang,
            target_lang=target_lang or "en",
            selected_text="",
            user_name=(user_name or "").strip(),
        )
        base = (system_prompt or "").rstrip()
        blk = (block or "").strip()
        # voice_modes.yaml often starts with "--- VOICE OUTPUT FORMAT ..." — do not duplicate the header.
        first_line = blk.splitlines()[0].strip() if blk else ""
        if first_line.upper().startswith("--- VOICE OUTPUT FORMAT"):
            return base + "\n\n" + blk
        return base + "\n\n--- VOICE OUTPUT FORMAT ---\n\n" + blk

    def _record_and_process(
        self,
        mode_id,
        selected_text="",
        from_chat_ui: bool = False,
        suppress_stt_feedback: bool = False,
        suppress_no_speech_feedback: bool = False,
        continuous_chat_turn: bool = False,
    ):
        def _looks_like_meaningful_audio(buf) -> bool:
            try:
                import numpy as np

                if buf is None:
                    return False
                x = np.asarray(buf, dtype=np.float32)
                if x.size == 0:
                    return False
                ax = np.abs(x)
                rms = float(np.sqrt(np.mean(x * x)))
                peak = float(np.max(ax))
                # Require a minimum voiced fraction above floor to avoid STT/LLM spam in idle loops.
                voiced_frac = float(np.mean(ax > 0.01))
                voiced_samples = int(np.sum(ax > 0.01))
                sr = int(getattr(self.recorder, "sample_rate", 16000) or 16000)
                voiced_min_samples = int(0.10 * sr)  # ~100 ms
                return (rms >= 0.008 or peak >= 0.04) and (
                    voiced_frac >= 0.01 or voiced_samples >= voiced_min_samples
                )
            except Exception:
                return True

        try:
            if self._audio_pipeline_debug():
                cap = str((self.config.get("audio") or {}).get("capture_mode") or "?")
                logger.info(
                    "[pipeline] record_start | mode=%s continuous=%s capture_mode=%s "
                    "suppress_no_speech=%s suppress_stt_ui=%s",
                    mode_id,
                    continuous_chat_turn,
                    cap,
                    suppress_no_speech_feedback,
                    suppress_stt_feedback,
                )
            self._set_status("listening")
            if not suppress_stt_feedback:
                self.sound_manager.play_stt_start()
                self._notify(f"🎙️ {self.modes[mode_id].name} — Speak now...")
            audio = self.recorder.record_until_silence()
            if not suppress_stt_feedback:
                self.sound_manager.play_stt_stop()
            with self._lock:
                self._is_recording = False
            duration = len(audio) / float(self.recorder.sample_rate) if len(audio) > 0 else 0.0
            if self._audio_pipeline_debug() and len(audio) > 0:
                try:
                    import numpy as np

                    x = np.asarray(audio, dtype=np.float32)
                    ax = np.abs(x)
                    rms = float(np.sqrt(np.mean(x * x)))
                    peak = float(np.max(ax)) if x.size else 0.0
                    vf = float(np.mean(ax > 0.01)) if x.size else 0.0
                    logger.info(
                        "[pipeline] record_stop | mode=%s continuous=%s duration_sec=%.2f samples=%d "
                        "rms=%.5f peak=%.4f voiced_frac=%.4f",
                        mode_id,
                        continuous_chat_turn,
                        duration,
                        int(x.size),
                        rms,
                        peak,
                        vf,
                    )
                except Exception:
                    logger.info(
                        "[pipeline] record_stop | mode=%s continuous=%s duration_sec=%.2f samples=%d",
                        mode_id,
                        continuous_chat_turn,
                        duration,
                        len(audio),
                    )
            if len(audio) > 0:
                if suppress_no_speech_feedback and not _looks_like_meaningful_audio(audio):
                    # Continuous Chat can carry low-level voice in some headset/mix setups.
                    # Keep the anti-noise guard for very short clips, but do not drop
                    # longer turns before STT has a chance to decide.
                    if not continuous_chat_turn or duration < 0.7:
                        if self._audio_pipeline_debug():
                            logger.info(
                                "[pipeline] skip_idle_low_energy | mode=%s continuous=%s duration_sec=%.2f",
                                mode_id,
                                continuous_chat_turn,
                                duration,
                            )
                        self._set_status("listening")
                        return
                split_raw_text = self._build_dual_mix_raw_text(mode_id=mode_id)
                if split_raw_text is not None:
                    self._process_audio(
                        None,
                        mode_id,
                        selected_text,
                        duration=duration,
                        raw_text_override=split_raw_text,
                        from_chat_ui=from_chat_ui,
                        suppress_no_speech_feedback=suppress_no_speech_feedback,
                        continuous_chat_turn=continuous_chat_turn,
                    )
                else:
                    self._process_audio(
                        audio,
                        mode_id,
                        selected_text,
                        duration=duration,
                        from_chat_ui=from_chat_ui,
                        suppress_no_speech_feedback=suppress_no_speech_feedback,
                        continuous_chat_turn=continuous_chat_turn,
                    )
            else:
                if self._audio_pipeline_debug():
                    logger.info(
                        "[pipeline] empty_buffer | mode=%s continuous=%s",
                        mode_id,
                        continuous_chat_turn,
                    )
                if suppress_no_speech_feedback:
                    # Continuous Chat idle cycle: stay armed/listening without UI flashing.
                    self._set_status("listening")
                else:
                    self._set_status("ready")
                    _msg = self._get_alert_for_log("regular.recording_no_audio")
                    self._notify(_msg)
                    self._notify_header("regular.recording_no_audio", restore_after_ms=4000)
        except Exception as e:
            logger.exception("_record_and_process failed: %s", e)
            try:
                if not suppress_stt_feedback:
                    self.sound_manager.play_stt_stop()
            except Exception:
                pass
            try:
                if self.recorder and getattr(self.recorder, "is_recording", False):
                    self.recorder.stop()
            except Exception:
                pass
            self._set_status("ready")
            self._notify(f"Recording error: {e}")
        finally:
            with self._lock:
                self._is_recording = False

    def _build_dual_mix_raw_text(self, mode_id: str = "") -> Optional[str]:
        """When capture_mode=mix and split tracks are available, STT mic/system separately.

        Returns combined tagged transcript or None to keep legacy single-pass STT.
        """
        try:
            import numpy as np

            audio_cfg = self.config.get("audio") or {}
            mode = str(audio_cfg.get("capture_mode") or "mic_only").strip().lower()
            if mode != "mix":
                return None
            # For transcription-oriented paths, prefer the legacy single-pass STT on the full
            # mixed waveform to avoid edge losses from source segmentation.
            #
            # This currently applies to:
            # - transcribe (Alt+T): raw dictation fidelity is priority
            # - answer (Alt+A / Chat / Continuous): full utterance fidelity is priority
            if str(mode_id or "").strip().lower() in {"transcribe", "answer"}:
                if self._audio_pipeline_debug():
                    logger.info(
                        "[pipeline] mix_dual_track_skipped | reason=single_pass_fidelity mode=%s",
                        (mode_id or "").strip(),
                    )
                return None
            get_tracks = getattr(self.recorder, "get_last_split_capture", None)
            if not callable(get_tracks):
                return None
            tracks = get_tracks() or {}
            mic_audio = tracks.get("mic")
            sys_audio = tracks.get("system")
            sr = int(tracks.get("sample_rate") or getattr(self.recorder, "sample_rate", 16000))
            if mic_audio is None or sys_audio is None:
                return None

            lang = self.config.get("stt", {}).get("language", "auto")
            forced_lang = None if lang == "auto" else lang
            is_transcribe_mode = str(mode_id or "").strip().lower() == "transcribe"
            identity_cfg = self.config.get("identity") or {}
            user_name = str(identity_cfg.get("name") or "").strip()
            mic_label = user_name if user_name else "You"
            system_label = "System audio"
            try:
                if getattr(self, "_target_window", None):
                    title = (get_window_title(self._target_window) or "").strip()
                    is_own_window = False
                    try:
                        w = getattr(self, "widget", None)
                        if w and getattr(w, "root", None):
                            own_hwnd = w.root.winfo_id()
                            is_own_window = bool(own_hwnd and self._target_window == own_hwnd)
                    except Exception:
                        is_own_window = False
                    t_low = title.lower()
                    looks_internal = (
                        "perkysue" in t_low
                        or "listening" in t_low
                        or "processing" in t_low
                        or "ready" in t_low
                    )
                    if title and not is_own_window and not looks_internal:
                        short = title if len(title) <= 70 else (title[:67] + "...")
                        system_label = f"System audio ({short})"
            except Exception:
                pass
            n = min(len(mic_audio), len(sys_audio))
            if n < int(1.0 * sr):
                return None
            mic_tl = mic_audio[:n].astype(np.float32, copy=False)
            sys_tl = sys_audio[:n].astype(np.float32, copy=False)

            # Coarse source timeline from long windows (more stable than per-chunk switches).
            win = max(int(1.2 * sr), 1)
            hop = max(int(0.6 * sr), 1)
            silence_thr = 0.0075
            choose_ratio = 1.25
            switch_ratio = 1.8

            frame_labels: List[str] = []
            frame_starts: List[int] = []
            prev_dom: Optional[str] = None

            for start in range(0, n, hop):
                end = min(start + win, n)
                frame_starts.append(start)
                m = mic_tl[start:end]
                s = sys_tl[start:end]
                if len(m) == 0 or len(s) == 0:
                    frame_labels.append("silence")
                    continue
                rms_m = float(np.sqrt(np.mean(m * m)))
                rms_s = float(np.sqrt(np.mean(s * s)))
                if rms_m < silence_thr and rms_s < silence_thr:
                    frame_labels.append("silence")
                    continue
                ratio = rms_m / (rms_s + 1e-9)
                if prev_dom == "mic":
                    dom = "system" if ratio < (1.0 / switch_ratio) else "mic"
                elif prev_dom == "system":
                    dom = "mic" if ratio > switch_ratio else "system"
                else:
                    if ratio >= choose_ratio:
                        dom = "mic"
                    elif ratio <= (1.0 / choose_ratio):
                        dom = "system"
                    else:
                        dom = "mic" if rms_m >= rms_s else "system"
                frame_labels.append(dom)
                prev_dom = dom

            if not frame_labels:
                return None

            # Build coarse contiguous segments in sample domain.
            coarse_segments: List[tuple[str, int, int]] = []
            cur_lbl: Optional[str] = None
            cur_i = 0
            for i, lbl in enumerate(frame_labels):
                if cur_lbl is None:
                    cur_lbl = lbl
                    cur_i = i
                    continue
                if lbl != cur_lbl:
                    s0 = frame_starts[cur_i]
                    e0 = min(n, frame_starts[i - 1] + win)
                    coarse_segments.append((cur_lbl, s0, e0))
                    cur_lbl = lbl
                    cur_i = i
            if cur_lbl is not None:
                coarse_segments.append((cur_lbl, frame_starts[cur_i], n))

            coarse_segments = [seg for seg in coarse_segments if seg[0] != "silence"]
            if not coarse_segments:
                return None

            # Merge tiny contradictory segments to keep readable chronology.
            min_seg = int(1.5 * sr)
            merged: List[tuple[str, int, int]] = []
            for lbl, s0, e0 in coarse_segments:
                if not merged:
                    merged.append((lbl, s0, e0))
                    continue
                pl, ps, pe = merged[-1]
                if lbl == pl:
                    merged[-1] = (pl, ps, e0)
                    continue
                if (e0 - s0) < min_seg:
                    merged[-1] = (pl, ps, e0)
                    continue
                merged.append((lbl, s0, e0))

            tagged_segments: List[str] = []
            mic_chars = 0
            sys_chars = 0
            min_seg_default = int(0.8 * sr)
            min_seg_edge = int(0.2 * sr)
            for i, (lbl, s0, e0) in enumerate(merged):
                seg_len = int(e0 - s0)
                is_edge = i == 0 or i == (len(merged) - 1)
                # Keep edge segments even when short to avoid chopping the beginning/end of a dictation.
                if seg_len < (min_seg_edge if is_edge else min_seg_default):
                    continue
                src = "MIC" if lbl == "mic" else "SYSTEM"
                audio_seg = mic_tl[s0:e0] if lbl == "mic" else sys_tl[s0:e0]
                res = self.stt.transcribe(audio_seg, sample_rate=sr, language=forced_lang)
                txt = (res.text or "").strip()
                if not txt:
                    continue
                if getattr(res, "language", None) and self.last_stt_detected_language is None:
                    self.last_stt_detected_language = str(res.language).strip().lower() or None
                if is_transcribe_mode:
                    tagged_segments.append(txt)
                else:
                    if src == "MIC":
                        tagged_segments.append(f"[{mic_label}]\n{txt}")
                        mic_chars += len(txt)
                    else:
                        tagged_segments.append(f"[{system_label}]\n{txt}")
                        sys_chars += len(txt)

            if tagged_segments:
                logger.info(
                    "Mix dual-track STT ordered (coarse): segments=%d mic_chars=%d system_chars=%d mode=%s",
                    len(tagged_segments),
                    mic_chars,
                    sys_chars,
                    mode_id or "?",
                )
                return "\n\n".join(tagged_segments).strip()

            # Fallback grouped if chronology pass yielded no useful segment.
            parts: List[str] = []
            if len(mic_tl) > 0:
                mic_res = self.stt.transcribe(mic_tl, sample_rate=sr, language=forced_lang)
                mic_text = (mic_res.text or "").strip()
                if mic_text:
                    parts.append(mic_text if is_transcribe_mode else f"[{mic_label}]\n{mic_text}")
                if getattr(mic_res, "language", None):
                    self.last_stt_detected_language = str(mic_res.language).strip().lower() or None
            if len(sys_tl) > 0:
                sys_res = self.stt.transcribe(sys_tl, sample_rate=sr, language=forced_lang)
                sys_text = (sys_res.text or "").strip()
                if sys_text:
                    parts.append(sys_text if is_transcribe_mode else f"[{system_label}]\n{sys_text}")
                if self.last_stt_detected_language is None and getattr(sys_res, "language", None):
                    self.last_stt_detected_language = str(sys_res.language).strip().lower() or None
            if parts:
                logger.info("Mix dual-track STT fallback: grouped mic/system mode=%s", mode_id or "?")
                return "\n\n".join(parts).strip()
            return None
        except Exception as e:
            logger.warning("Mix dual-track STT fallback to legacy single pass: %s", e)
            return None

    @staticmethod
    def _strip_thinking_blocks(text: str) -> str:
        """Strip thinking / reasoning blocks from model output (safety net if server or model leaks into ``content``)."""
        if not text:
            return text
        t = text
        block_patterns = [
            r"<redacted_thinking>.*?</redacted_thinking>\s*",
            r"<reasoning>.*?</reasoning>\s*",
            r"<thinking>.*?</thinking>\s*",
        ]
        for pat in block_patterns:
            t = re.sub(pat, "", t, flags=re.DOTALL | re.IGNORECASE)
        for open_name in ("redacted_thinking", "reasoning", "thinking"):
            t = re.sub(rf"<{open_name}>.*$", "", t, flags=re.DOTALL | re.IGNORECASE)
        return t.strip()

    def run_answer_text(self, question: str):
        """Run Answer mode with the given text (e.g. from Chat tab). Same pipeline as Alt+A, no STT.
        When called from the Chat UI, the result must never be injected into the type-in (only into chat history).

        Unlike the Alt+A hotkey path, we must not start while the pipeline is already busy: overlapping LLM
        requests to llama-server (e.g. Send while a reply is still generating) can reset the connection.
        """
        q = (question or "").strip()
        if not q:
            return
        self.stop_voice_output()

        with self._lock:
            _busy = self._is_processing or self._is_recording
        if _busy:
            try:
                w = getattr(self, "widget", None)
                _msg = i18n_s(
                    "chat.pipeline_busy",
                    default="⏳ Wait for recording or the current reply to finish before sending.",
                )
                if w and getattr(w, "root", None) and hasattr(w, "_notify"):
                    w.root.after(0, lambda m=_msg, ww=w: ww._notify(m, restore_after_ms=4500))
            except Exception:
                pass
            return

        # Align prompt language with First Language when set (typed path has no Whisper detection).
        identity_cfg = self.config.get("identity") or {}
        _fl = (identity_cfg.get("first_language") or "auto").strip().lower()
        if _fl and _fl != "auto":
            self.last_stt_detected_language = _fl[:2]

        def _run():
            self._process_audio(None, "answer", selected_text="", duration=None, raw_text_override=q, from_chat_ui=True)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _process_audio(
        self,
        audio,
        mode_id,
        selected_text="",
        duration: float | None = None,
        raw_text_override: str | None = None,
        from_chat_ui: bool = False,
        suppress_feedback_sounds: bool = False,
        suppress_no_speech_feedback: bool = False,
        continuous_chat_turn: bool = False,
    ):
        if not self.modes.get(mode_id):
            return
        with self._lock:
            self._is_processing = True
        try:
            self._process_audio_impl(
                audio,
                mode_id,
                selected_text,
                duration,
                raw_text_override,
                from_chat_ui,
                suppress_feedback_sounds,
                suppress_no_speech_feedback,
                continuous_chat_turn,
            )
        finally:
            with self._lock:
                self._is_processing = False

    def _process_audio_impl(
        self,
        audio,
        mode_id,
        selected_text="",
        duration: float | None = None,
        raw_text_override: str | None = None,
        from_chat_ui: bool = False,
        suppress_feedback_sounds: bool = False,
        suppress_no_speech_feedback: bool = False,
        continuous_chat_turn: bool = False,
    ):
        mode = self.modes.get(mode_id)
        if not mode:
            return

        self._cancel_requested = False
        console = self.config.get("feedback", {}).get("console_output", True)

        if raw_text_override is not None:
            raw_text = raw_text_override
            result = type("R", (), {"text": raw_text, "language": self.last_stt_detected_language or "en"})()
            self._set_status("generating" if mode.needs_llm else "processing")
            self._notify("⏳ LLM...")
        else:
            # STT
            if suppress_no_speech_feedback:
                # Continuous Chat: keep stable Listening UI during idle/silence cycles.
                self._set_status("listening")
            else:
                self._set_status("processing")
                self._notify("⏳ Transcription...")
            try:
                lang = self.config.get("stt", {}).get("language", "auto")
                result = self.stt.transcribe(audio, language=None if lang == "auto" else lang)
                raw_text = result.text
                if getattr(result, "language", None):
                    self.last_stt_detected_language = str(result.language).strip().lower() or None
                    if console:
                        logger.info("Whisper language → LLM source_lang: %s", self.last_stt_detected_language)
                elif lang and lang != "auto":
                    self.last_stt_detected_language = str(lang).strip().lower()
            except Exception as e:
                self._set_status("error")
                self._notify(f"❌ STT: {e}")
                return

        if self._cancel_requested:
            self._set_status("ready")
            _msg = self._get_alert_for_log("regular.processing_stopped")
            self._notify(_msg)
            self._notify_header("regular.processing_stopped", restore_after_ms=3000)
            return

        if not raw_text.strip():
            if suppress_no_speech_feedback:
                self._set_status("listening")
                return
            # Si l'enregistrement est nettement plus court que le Silence Timeout configuré,
            # il s'agit probablement d'un problème micro / device plutôt que d'un simple silence utilisateur.
            if duration is not None and duration < max(self._silence_timeout - 0.5, 0.5):
                # Trop court / pas de texte : Ready sous l'avatar, message dans la barre (pas une erreur critique).
                self._set_status("ready")
                _msg = self._get_alert_for_log("regular.recording_too_short")
                self._notify(_msg)
                self._notify_header("regular.recording_too_short", restore_after_ms=4000)
            else:
                self._set_status("no_speech")
                self._notify("No Sound Detected — nothing heard")
            return

        self.last_stt_text = raw_text

        if console:
            hk_disp = format_hotkey_display(resolve_hotkey_string(self.config.get("hotkeys") or {}, mode_id))
            print(f"\n📝 [{mode_id}] {hk_disp} STT: {len(raw_text)} chars (transcript not echoed)")
            if selected_text:
                print(f"📋 Selection: {len(selected_text)} chars (content not echoed)")
        if console and self._feedback_debug_mode():
            g = logging.getLogger("perkysue.gui_console")
            _src = "microphone" if raw_text_override is None else "text_override"
            g.info("=== Transcript [%s] source=%s ===\n%s\n", mode_id, _src, (raw_text or "").strip())
            if (selected_text or "").strip():
                # Full selection is already embedded in SYSTEM in the LLM dump below — avoid duplicating 2× in Full Console.
                g.info(
                    "=== Selection [%s] === %d chars (full text is under SELECTED TEXT / SYSTEM in LLM block below)\n",
                    mode_id,
                    len(selected_text),
                )

        # In-app redirect (strict): if the user asks clearly about PerkySue/app inside Chat UI, move the question to Help.
        if (mode_id or "").strip().lower() == "answer" and self._is_perkysue_app_question(raw_text):
            w = getattr(self, "widget", None)
            # Continuous = voix hors type-in Chat : ne pas traiter comme une question tapée dans l'app.
            in_app = bool(from_chat_ui) and not continuous_chat_turn
            try:
                if not in_app and w and getattr(w, "root", None):
                    our_hwnd = w.root.winfo_id()
                    if our_hwnd and self._target_window == our_hwnd:
                        in_app = True
            except Exception:
                pass
            if in_app and w and getattr(w, "root", None):
                # Option B: avoid false redirects by asking the LLM intent router (HELP vs NOHELP).
                # This router runs only when the regex heuristic already suspects "help about PerkySue/app".
                # Long pasted Chat text (bug reports, logs) often mentions "LLM"/STT without naming PerkySue —
                # skip the extra router call to avoid two heavy llama-server requests in a row (stability).
                rt = (raw_text or "").strip()
                skip_router = (
                    len(rt) > _IN_APP_HELP_ROUTER_SKIP_LEN
                    and not re.search(r"perkysue|perky sue|perky-sue", rt.lower())
                )
                if skip_router:
                    should_redirect = self._should_force_help_redirect(raw_text)
                else:
                    should_redirect = self._llm_intent_should_redirect_to_help(raw_text) or self._should_force_help_redirect(
                        raw_text
                    )
                if not should_redirect:
                    # Keep the user in Chat (answer mode) to avoid unwanted redirects.
                    pass
                else:
                    sl = (self.last_stt_detected_language or "en").lower()
                    redirect_msg = (
                        "↪ Pour toute question sur PerkySue / l’app, j’ai déplacé ça dans l’onglet Help."
                        if sl.startswith("fr")
                        else "↪ For PerkySue/app questions, I moved this to the Help tab."
                    )
                    try:
                        hist = getattr(self, "_answer_history", [])
                        hist.append({"q": (raw_text or "").strip(), "a": redirect_msg})
                        w.root.after(0, lambda: w._refresh_chat_tab())
                        w.root.after(0, lambda: w._chat_scroll_to_bottom())
                    except Exception:
                        pass
                    try:
                        w.root.after(0, lambda: w._go("help"))
                        w.root.after(0, lambda: w._help_input.delete(0, "end") if getattr(w, "_help_input", None) else None)
                        # Auto-redirect: leave Help type-in empty.
                        # We already inject the question into the Help conversation via run_help_text().
                    except Exception:
                        pass
                    try:
                        self.run_help_text(raw_text, from_answer_redirect=True)
                    except Exception:
                        pass
                    self._set_status("ready")
                    return

        # LLM
        final_text = raw_text
        hit_max_input_flag = False  # utilisé après injection pour notifier si contexte a été réduit
        hit_max_output_tokens_flag = False  # réponse tronquée (output) ou vide (input) → alerte + message
        self._last_output_limit_alert = None  # (effective_out, suggested) si troncature output ; None → blink input
        empty_reply_hit_limit = False  # réponse vide alors que le serveur a renvoyé 1024 tokens → même message + notification
        llm_error_occurred = False
        llm_error_msg = ""
        self.last_llm_reasoning = ""
        if mode.needs_llm and self.llm and self.llm.is_available():
            if self._cancel_requested:
                self._set_status("ready")
                _msg = self._get_alert_for_log("regular.processing_stopped")
                self._notify(_msg)
                self._notify_header("regular.processing_stopped", restore_after_ms=3000)
                return
            # One-time disclaimer per session (header alert).
            try:
                if not getattr(self, "_ai_disclaimer_shown", False):
                    self._ai_disclaimer_shown = True
                    self._notify_header("regular.ai_disclaimer", restore_after_ms=8000)
            except Exception:
                pass
            self._set_status("generating")
            self._notify("⏳ LLM...")
            # Affichage en cascade : afficher d'abord la bulle User, laisser la GUI se rafraîchir, puis lancer le LLM
            if self._should_capture_mode_into_chat(mode_id) and (raw_text or "").strip():
                history = getattr(self, "_answer_history", [])
                history.append({"q": raw_text.strip(), "a": ""})
                w = getattr(self, "widget", None)
                if w and getattr(w, "root", None):
                    try:
                        w.root.after(0, lambda: w._refresh_chat_tab())
                        w.root.after(0, lambda: w._chat_scroll_to_bottom())
                    except Exception:
                        pass
                # Courte pause pour que le thread GUI traite le refresh avant qu'on bloque en LLM
                time.sleep(0.4)
            if mode_id == "help" and (raw_text or "").strip():
                help_hist = getattr(self, "_help_history", [])
                help_hist.append({"q": raw_text.strip(), "a": ""})
                w = getattr(self, "widget", None)
                if w and getattr(w, "root", None):
                    try:
                        w.root.after(0, lambda: w._refresh_help_tab())
                        w.root.after(0, lambda: w._help_scroll_to_bottom())
                    except Exception:
                        pass
                time.sleep(0.4)
            # Son de début LLM (désactivé quand TTS est activé — évite conflits audio avec la voix).
            _suppress_llm_sounds_for_tts = False
            try:
                tm = getattr(self, "tts_manager", None)
                if tm and getattr(tm, "enabled", False) and getattr(tm, "auto_speak", False) and self.is_effective_pro():
                    mid = (mode_id or "").strip().lower()
                    triggers = set(getattr(tm, "trigger_modes", None) or [])
                    if mid in triggers:
                        _suppress_llm_sounds_for_tts = True
            except Exception:
                _suppress_llm_sounds_for_tts = False
            if (not suppress_feedback_sounds) and (not _suppress_llm_sounds_for_tts):
                self.sound_manager.play_llm_start()
            try:
                modes_config = self.config.get("modes", {})
                identity_cfg = self.config.get("identity", {}) or {}
                user_name = identity_cfg.get("name", "") or ""
                stt_lang = (result.language or "").strip().lower() or self.last_stt_detected_language or "auto"
                system_context: Optional[str] = None
                _len_after_render = 0
                if (mode_id or "").strip().lower() == "help":
                    # Mode Help : prompt système = paramètres + KB + instructions ; message user = question brute.
                    system_prompt = self._build_help_system_prompt(mode, user_name, stt_lang, user_text=raw_text)
                    text_to_llm = raw_text
                    hit_max_input_flag = False
                else:
                    # Construire texte user + éventuel contexte pour le system (Answer mode).
                    llm_user_message, system_context, hit_max_input = self._build_llm_input_with_context(
                        mode_id=mode_id,
                        mode=mode,
                        current_question=raw_text,
                    )
                    system_prompt = render_prompt(
                        mode, llm_user_message,
                        source_lang=stt_lang,
                        target_lang=modes_config.get("translate_target", "en"),
                        selected_text=selected_text,
                        user_name=user_name,
                        conversation_context=system_context if system_context else None,
                    )
                    _len_after_render = len(system_prompt or "")
                    # Message USER : uniquement la question actuelle. Le contexte est DÉJÀ dans le system prompt
                    if system_context:
                        text_to_llm = "Current question (answer this):\n" + llm_user_message
                    else:
                        text_to_llm = llm_user_message
                    hit_max_input_flag = hit_max_input

                system_prompt = self._append_voice_mode_overlay(
                    system_prompt,
                    (mode_id or "").strip().lower(),
                    user_name=user_name,
                    stt_lang=stt_lang,
                    target_lang=modes_config.get("translate_target", "en"),
                )
                _len_after_voice = len(system_prompt or "")
                system_prompt = self._append_tts_llm_extension(system_prompt, mode_id, reply_language=stt_lang)
                _len_after_tts = len(system_prompt or "")

                # Local prompt token estimate (chars/4) used for truncation heuristics
                sys_chars = len(system_prompt or "")
                user_chars = len(text_to_llm or "")
                approx_prompt_tok_local = (sys_chars + user_chars) // 4

                # Log taille envoyée (input seul) : llama-server exige prompt_tokens + max_tokens ≤ n_ctx (fenêtre partagée).
                if mode_id == "answer" and self.config.get("feedback", {}).get("console_output", True):
                    approx_prompt_tok = approx_prompt_tok_local
                    _lim = self.get_effective_llm_n_ctx()
                    _want_out = self.get_effective_llm_max_output()
                    logger.info(
                        "Alt+A prompt breakdown: selection_chars=%d, conv_context_chars=%d, "
                        "after_render=%d, after_voice_overlay=%d, after_tts=%d; user_message_chars=%d; "
                        "total_prompt≈%d tok (chars/4); n_ctx=%d, max_output_setting≈%d tok "
                        "(prompt + max_new_tokens must fit in n_ctx)",
                        len(selected_text or ""),
                        len(system_context or ""),
                        _len_after_render,
                        _len_after_voice,
                        _len_after_tts,
                        user_chars,
                        approx_prompt_tok,
                        _lim,
                        _want_out,
                    )

                # Never log system/user LLM bodies to disk (perkysue.log); sizes only above.

                # (hit_max_input_flag déjà fixé selon le mode — Help: False, Answer: hit_max_input)
                # (Alerte max input affichée après injection pour être visible — voir plus bas)

                # CRITICAL: Run LLM on main thread to avoid CUDA threading issues
                max_tokens_req = self.get_effective_llm_max_output()
                llm_result = self._run_llm_on_main_thread(
                    text=text_to_llm,
                    system_prompt=system_prompt,
                    temperature=self.config.get("llm", {}).get("temperature", 0.3),
                    max_tokens=max_tokens_req,
                    gui_debug_label=(mode_id or "llm"),
                )
                _rc = getattr(llm_result, "reasoning_content", None)
                self.last_llm_reasoning = (_rc or "").strip() if isinstance(_rc, str) else ""
                final_text = self._strip_thinking_blocks((llm_result.text or "").strip())
                # Answer mode : détecter troncature via finish_reason (API OpenAI / llama-server) ou usage (tokens)
                comp_tok = getattr(llm_result, "completion_tokens", 0)
                total_used = getattr(llm_result, "tokens_used", 0)
                finish_reason = getattr(llm_result, "finish_reason", None) or ""
                approx_out = len(final_text) // 4
                max_ctx = self.get_effective_llm_n_ctx()
                # "length" = arrêt explicite pour limite tokens (contexte ou output) — signal fiable du serveur
                truncated = (
                    (finish_reason == "length")
                    or comp_tok >= max_tokens_req
                    or (comp_tok == 0 and total_used >= max_tokens_req)
                    or (comp_tok == 0 and total_used == 0 and approx_out >= int(max_tokens_req * 0.85))
                )
                # n_ctx = fenêtre partagée : prompt + completion ≤ n_ctx. Si total_used >= n_ctx, la coupure vient du contexte plein.
                context_full = max_ctx > 0 and total_used >= max_ctx
                # finish_reason == "length" but server didn't report token usage:
                # don't assume "context full" (this caused false "context limit reached" alerts).
                # Instead, treat as context-full only when the *prompt itself* is already near the ctx budget.
                if finish_reason == "length" and not (comp_tok or total_used):
                    context_full = bool(max_ctx > 0 and approx_prompt_tok_local >= int(max_ctx * 0.85))
                if mode_id == "answer" and truncated:
                    w = getattr(self, "widget", None)
                    sug = 2048 if max_ctx < 2048 else (4096 if max_ctx < 4096 else (8192 if max_ctx < 8192 else 16384))
                    if (final_text or "").strip():
                        hit_max_output_tokens_flag = True
                        # Coupure par contexte plein (total ≈ n_ctx) → message "Max input" (contexte). Sinon vraie limite output.
                        if context_full:
                            trunc_msg = (w._get_alert("document_injection.chat_context_limit_reached", max_input=max_ctx, suggested=sug) if (w and hasattr(w, "_get_alert")) else f"⚠️ Context limit ({max_ctx}) reached — input and output share this budget. Increase 'Max input' in Settings → Performance to {sug} or higher.")
                            final_text += "\n\n" + trunc_msg
                            self._last_output_limit_alert = None
                            self._answer_context_limit_reached = True  # so Chat tab token bar shows full (2048/2048)
                        else:
                            effective_out = comp_tok if comp_tok > 0 else max_tokens_req
                            if effective_out < 2048:
                                sug_out = 2048
                            elif effective_out < 4096:
                                sug_out = 4096
                            elif effective_out < 8192:
                                sug_out = 8192
                            else:
                                sug_out = 16384
                            trunc_msg = (w._get_alert("document_injection.chat_max_output_reached", max_output=effective_out, suggested=sug_out) if (w and hasattr(w, "_get_alert")) else f"⚠️ Reply was cut off: max output limit ({effective_out}) reached. Increase 'Max output' in Settings → Performance to {sug_out} or higher.")
                            final_text += "\n\n" + trunc_msg
                            self._last_output_limit_alert = (effective_out, sug_out)
                    else:
                        # Réponse vide → limite contexte (input + output partagés)
                        hit_max_output_tokens_flag = True
                        trunc_msg = (w._get_alert("document_injection.chat_max_input_reached", max_input=max_ctx, suggested=sug) if (w and hasattr(w, "_get_alert")) else f"⚠️ You've reached the max input (context) limit ({max_ctx}). Try increasing 'Max input' in Settings → Performance to {sug} or higher.")
                        empty_reply_hit_limit = True
                        final_text = trunc_msg
                        self._last_output_limit_alert = None
                        self._answer_context_limit_reached = True  # so Chat tab token bar shows full (2048/2048)
                # Help mode: truncation detection — always show a visible note in Help (even if model output ended up empty)
                if mode_id == "help" and truncated:
                    w = getattr(self, "widget", None)
                    sug = 2048 if max_ctx < 2048 else (4096 if max_ctx < 4096 else (8192 if max_ctx < 8192 else 16384))
                    if context_full:
                        help_trunc_msg = (w._get_alert("document_injection.chat_context_limit_reached", max_input=max_ctx, suggested=sug) if (w and hasattr(w, "_get_alert")) else f"⚠️ Context limit ({max_ctx}) reached — input and output share this budget. Increase 'Max input' in Settings → Performance to {sug} or higher.")
                        help_trunc_msg += " Or click “New chat” at the top of this Help tab to reset the conversation."
                        self._help_context_limit_reached = True  # so Help tab token bar shows full (max_ctx)
                    else:
                        effective_out = comp_tok if comp_tok > 0 else max_tokens_req
                        sug_out = 2048 if effective_out < 2048 else (4096 if effective_out < 4096 else (8192 if effective_out < 8192 else 16384))
                        help_trunc_msg = (w._get_alert("document_injection.chat_max_output_reached", max_output=effective_out, suggested=sug_out) if (w and hasattr(w, "_get_alert")) else f"⚠️ Reply was cut off (output limit). Increase 'Max output' in Settings → Performance to {sug_out} or higher.")
                    if (final_text or "").strip():
                        final_text += "\n\n" + help_trunc_msg
                    else:
                        final_text = help_trunc_msg
                    # Même UX que Chat : ⚠ sur Help dans le menu + New chat clignote (ou au retour sur l’onglet)
                    try:
                        if w and hasattr(w, "_set_help_reset_indicator_if_outside_help"):
                            w.root.after(100, w._set_help_reset_indicator_if_outside_help)
                    except Exception:
                        pass
            except Exception as e:
                self._set_status("error")
                logger.error(f"LLM: {e}")
                llm_error_occurred = True
                llm_error_msg = str(e)
                self.last_llm_reasoning = ""
            finally:
                # Son de fin LLM (même si erreur)
                if (not suppress_feedback_sounds) and (not _suppress_llm_sounds_for_tts):
                    self.sound_manager.play_llm_stop()

        if console and final_text != raw_text:
            hk_disp = format_hotkey_display(resolve_hotkey_string(self.config.get("hotkeys") or {}, mode_id))
            print(f"✨ [{mode_id}] {hk_disp} | {mode.name}: {len(final_text)} chars (reply not echoed)")

        self.last_llm_text = final_text

        voice_split = None
        if (
            mode.needs_llm
            and self.llm
            and self.llm.is_available()
            and not llm_error_occurred
            and self._voice_payload_effective((mode_id or "").strip().lower())
        ):
            voice_split = split_voice_payload_reply(
                final_text or "",
                read_aloud_payload=bool(getattr(self.tts_manager, "read_aloud_payload", False)),
            )

        tts_text_for_prepare = (
            voice_split.spoken_for_tts if voice_split is not None else final_text
        )

        # Sound feedback when LLM was not used (reuse llm_stop for skin compatibility)
        if (not suppress_feedback_sounds) and (not mode.needs_llm or not self.llm or not self.llm.is_available()):
            self.sound_manager.play_llm_stop()

        # Injection
        self._set_status("injecting")
        inj = self.config.get("injection", {})

        # Pour Alt+A (Answer), injecter question + réponse (et éventuellement un résumé)
        # pour garder la conversation lisible dans Word / Gmail / etc.
        inject_seed = final_text
        if (
            voice_split
            and voice_split.had_payload
            and (mode_id or "").strip().lower() != "help"
            and (
                (mode_id or "").strip().lower() != "answer"
                or not self._voice_payload_effective("answer")
            )
        ):
            inject_seed = voice_split.injectable_plain
        injected_text = inject_seed
        summary_text_for_injection = None
        llm_error_short_msg = ""
        # Valeur réelle Max input (contexte) + suggestion pour les alertes Answer (contexte Q/A qui dépasse la limite)
        max_input_ctx = self.get_effective_llm_n_ctx()
        if max_input_ctx < 2048:
            suggested_input = 2048
        elif max_input_ctx < 4096:
            suggested_input = 4096
        elif max_input_ctx < 8192:
            suggested_input = 8192
        else:
            suggested_input = 16384
        try:
            w = getattr(self, "widget", None)
            # Si le LLM a échoué, n'injecter que le message d'erreur (document_injection = texte collé dans le doc, pas header).
            if llm_error_occurred:
                llm_error_short_msg = _document_injection_llm_error_message(w, llm_error_msg)
                injected_text = f"⚠️ {llm_error_short_msg}\n\n"

            if mode_id == "answer" and not llm_error_occurred:
                use_vp_answer = (
                    self._voice_payload_effective("answer")
                    and voice_split is not None
                )
                # Enregistrer l'historique Q/R et voir si un nouveau summary vient d'être créé.
                if (raw_text or "").strip() and (final_text or "").strip():
                    summary_text_for_injection = self._record_answer_history(raw_text.strip(), final_text.strip())
                    if use_vp_answer:
                        if voice_split.had_payload and (voice_split.injectable_plain or "").strip():
                            injected_text = (voice_split.injectable_plain or "").strip()
                        else:
                            injected_text = ""
                    else:
                        injected_text = self._format_answer_injection(
                            raw_text,
                            final_text,
                            summary_text_for_injection,
                            user_name=user_name,
                            include_summary=self._feedback_debug_mode(),
                        )
                elif (raw_text or "").strip() and not (final_text or "").strip():
                    # Réponse vide en Answer : le contexte (Q/A cumulés) a atteint la limite max input — message avec valeur réelle + suggestion
                    hit_max_output_tokens_flag = True
                    msg_for_chat = (w._get_alert("document_injection.chat_max_input_reached", max_input=max_input_ctx, suggested=suggested_input) if (w and hasattr(w, "_get_alert")) else f"⚠️ You've reached the max input (context) limit ({max_input_ctx}). Try increasing 'Max input' in Settings → Performance to {suggested_input} or higher.")
                    history = getattr(self, "_answer_history", [])
                    if history and (history[-1].get("a") or "").strip() == "" and (history[-1].get("q") or "").strip() == (raw_text or "").strip():
                        history[-1]["a"] = msg_for_chat
                    else:
                        history.append({"q": raw_text.strip(), "a": msg_for_chat})
                    injected_text = ""
                else:
                    if use_vp_answer:
                        injected_text = ""
                    else:
                        injected_text = self._format_answer_injection(
                            raw_text,
                            final_text,
                            summary_text_for_injection,
                            user_name=user_name,
                            include_summary=self._feedback_debug_mode(),
                        )
            elif mode_id == "answer" and llm_error_occurred and (raw_text or "").strip():
                # Remplir la bulle assistant déjà créée avant l'appel LLM (évite doublon Q + message trompeur au compteur).
                history = getattr(self, "_answer_history", [])
                _eq = raw_text.strip()
                _ea = (llm_error_short_msg or "LLM error.").strip()
                if (
                    history
                    and (history[-1].get("q") or "").strip() == _eq
                    and not (history[-1].get("a") or "").strip()
                ):
                    history[-1]["a"] = _ea
                else:
                    history.append({"q": _eq, "a": _ea})
            # Optional Pro behavior: mirror non-Alt+A LLM exchanges into Chat history for follow-up continuity.
            if (
                mode_id != "answer"
                and self._should_capture_mode_into_chat(mode_id)
                and (raw_text or "").strip()
            ):
                history = getattr(self, "_answer_history", [])
                if llm_error_occurred:
                    if history and (history[-1].get("a") or "").strip() == "" and (history[-1].get("q") or "").strip() == (raw_text or "").strip():
                        history[-1]["a"] = llm_error_short_msg
                    else:
                        history.append({"q": raw_text.strip(), "a": llm_error_short_msg})
                elif (final_text or "").strip():
                    # Reuse same rolling-summary logic so context scaling remains stable.
                    self._record_answer_history(raw_text.strip(), final_text.strip())
                w = getattr(self, "widget", None)
                if w and getattr(w, "root", None):
                    try:
                        w.root.after(0, lambda: w._refresh_chat_tab())
                        w.root.after(0, lambda: w._chat_scroll_to_bottom())
                    except Exception:
                        pass

            if mode_id == "help" and (raw_text or "").strip():
                # Mettre à jour la dernière entrée Help avec la réponse (ou l'erreur).
                help_hist = getattr(self, "_help_history", [])
                if help_hist:
                    help_hist[-1]["a"] = llm_error_short_msg if llm_error_occurred else (final_text or "")
        except Exception as e:
            logger.error("Failed to record or format Alt+A history: %s", e)
            injected_text = final_text

        # Si limite max input atteinte : préfixer l'alerte dans le texte injecté (document_injection = collé dans le doc).
        if hit_max_input_flag and injected_text.strip():
            w = getattr(self, "widget", None)
            if w and hasattr(w, "_get_alert"):
                max_input_alert = w._get_alert("document_injection.max_input_reached")
            else:
                max_input_alert = "⚠️ Max input token limit reached — history was reduced. Consider Settings → Max input and your system's capacity.\n\n"
            injected_text = max_input_alert + injected_text

        # Unless debug mode: hide TTS bracket/MOOD markers in external injection (Smart Focus).
        if (
            not self._feedback_debug_mode()
            and not llm_error_occurred
            and (injected_text or "").strip()
            and (
                mode_id in ("answer", "help")
                or (voice_split and voice_split.had_payload)
            )
        ):
            from services.tts.tag_sanitize import strip_all_bracket_tags_for_display

            injected_text = strip_all_bracket_tags_for_display(injected_text)

        # Answer (Alt+A / mic) : ne jamais injecter dans la barre de saisie de l'app (seul Alt+T peut injecter dans le type-in).
        # from_chat_ui = True quand l'envoi vient du type-in Chat (Enter / Send) → ne jamais injecter, résultat déjà dans le chat.
        # Mode continu (continuous_chat_turn) : garder le flux Chat mais injecter aussi là où est le focus à l'instant T.
        # Help (Alt+H) : jamais d'injection, réponse uniquement dans l'onglet Help.
        w = getattr(self, "widget", None)
        # Answer + Voice payload: inject only when the model emitted <PS_PAYLOAD>; else chat+TTS only.
        answer_voice_skip_external = (
            (mode_id or "").strip().lower() == "answer"
            and self._voice_payload_effective("answer")
            and voice_split is not None
            and not llm_error_occurred
            and not (voice_split.had_payload and (voice_split.injectable_plain or "").strip())
        )
        # Free Answer: never inject into external apps — Chat tab only (same as Help: in-app only).
        skip_injection_answer_into_app = (
            (bool(from_chat_ui) and not continuous_chat_turn)
            or (mode_id == "help")
            or (mode_id == "answer" and not self.is_effective_pro())
            or answer_voice_skip_external
        )
        if continuous_chat_turn:
            self._target_window = get_active_window()
        if not skip_injection_answer_into_app and mode_id == "answer" and self._target_window is not None:
            try:
                if w and getattr(w, "root", None):
                    our_hwnd = w.root.winfo_id()
                    if our_hwnd and self._target_window == our_hwnd:
                        skip_injection_answer_into_app = True
                if not skip_injection_answer_into_app:
                    title = get_window_title(self._target_window) or ""
                    if "PerkySue" in title or "perkysue" in title.lower():
                        skip_injection_answer_into_app = True
            except Exception:
                pass
        if (mode_id or "").strip().lower() != "help" and (injected_text or "").strip():
            self._last_inject_payload = (injected_text or "").strip()

        if skip_injection_answer_into_app:
            success = True  # Résultat déjà dans le chat, pas d'injection dans le type-in
        else:
            try:
                delay_sec = float(inj.get("clipboard_restore_delay_sec", 5))
            except (TypeError, ValueError):
                delay_sec = 5.0
            success = inject_text(
                text=injected_text,
                method=inj.get("method", "clipboard"),
                restore_clipboard=inj.get("restore_clipboard", True),
                delay_ms=inj.get("delay_ms", 100),
                target_window=self._target_window,
                clipboard_restore_delay_sec=delay_sec,
            )
        _wants_auto_tts = (
            bool(success)
            and (not llm_error_occurred)
            and self.is_effective_pro()
            and getattr(self.tts_manager, "enabled", False)
            and getattr(self.tts_manager, "auto_speak", False)
            and mode_id in (getattr(self.tts_manager, "trigger_modes", None) or [])
            and bool((tts_text_for_prepare or "").strip())
            and self.tts_manager.is_installed()
        )
        self._set_status(
            "error"
            if (not success or llm_error_occurred)
            else ("generating" if _wants_auto_tts else "ready")
        )
        if skip_injection_answer_into_app:
            if llm_error_occurred:
                self._notify(f"❌ {llm_error_short_msg or 'LLM error'}")
            else:
                self._notify("✅ Ask in chat" if mode_id == "answer" else "✅ Ask in Help tab")
        else:
            self._notify("✅ Injected!" if success else "❌ Injection failed")

        # TTS Pro : pré-synthèse sur ce thread puis bulle + lecture sur le thread GUI (sync visuel / audio)
        tts_prepared = None
        tts_skip_msg = None

        # Engine often missing in RAM even when pip+weights are OK (boot warmup failed, unload after PyTorch CUDA pip, etc.).
        # Try one load here so Chat/Help auto-speak works without forcing a Voice tab visit.
        if (
            self.is_effective_pro()
            and self.tts_manager.enabled
            and self.tts_manager.auto_speak
            and mode_id in self.tts_manager.trigger_modes
            and bool(final_text)
            and not llm_error_occurred
            and self.tts_manager.is_installed()
            and not self.tts_manager.is_loaded()
        ):
            w = getattr(self, "widget", None)
            try:
                if w and getattr(w, "root", None):
                    self._notify_header("regular.tts_loading", restore_after_ms=15000)
                    w.root.after(0, lambda ww=w: ww.set_status("tts_loading"))
            except Exception:
                pass
            try:
                if self.tts_manager.load_engine():
                    logger.info("TTS: engine loaded on demand for auto-speak.")
                else:
                    logger.warning(
                        "TTS: load_engine on demand failed: %s",
                        (self.tts_manager.engine_load_error or "unknown")[:400],
                    )
            except Exception as ex:
                logger.warning("TTS: load_engine on demand raised: %s", ex)
            finally:
                try:
                    if w and getattr(w, "root", None):
                        w.root.after(0, lambda ww=w: ww.set_status("generating"))
                except Exception:
                    pass

        tts_eligible = (
            self.tts_manager.enabled
            and self.tts_manager.auto_speak
            and self.tts_manager.is_loaded()
            and self.is_effective_pro()
            and mode_id in self.tts_manager.trigger_modes
            and bool((tts_text_for_prepare or "").strip())
            and not llm_error_occurred
        )
        # Why Chat/Help sometimes shows text but never plays audio (logs are the only clue otherwise).
        if (
            mode_id in self.tts_manager.trigger_modes
            and bool(final_text)
            and not llm_error_occurred
            and self.tts_manager.enabled
            and self.tts_manager.auto_speak
        ):
            if not self.is_effective_pro():
                logger.info("TTS: auto-speak skipped — Pro tier required for Answer/Help (reply still shown).")
            elif not self.tts_manager.is_loaded():
                logger.info(
                    "TTS: auto-speak skipped — engine not loaded after on-demand retry (Voice tab: install / Retry; see WARNING above if load failed)."
                )
        if tts_eligible:
            try:
                tts_lang = self._effective_speech_language_for_tts(result)
                if not self.tts_manager.is_spoken_language_supported(tts_lang):
                    tpl = i18n_s(
                        "voice.tts.lang_not_supported",
                        default="{lang} is not supported for text-to-speech with the current engine.",
                    )
                    tts_skip_msg = tpl.format(lang=speech_language_display_name_en(tts_lang))
                else:
                    # Chat + Help : ne pas rafraîchir la bulle assistant ici — même timing que Help : texte + audio
                    # dans _post_injection_gui (évite le texte complet puis long silence avant la voix sur l’onglet Chat).
                    show_mtl_wait = self.tts_manager.will_block_for_multilingual_model(tts_lang)
                    if show_mtl_wait and w and getattr(w, "root", None):
                        try:
                            self._notify_header("regular.tts_loading", restore_after_ms=15000)
                        except Exception:
                            pass
                        w.root.after(0, lambda ww=w: ww.set_status("tts_loading"))
                    try:
                        tts_prepared = self.tts_manager.prepare_speak(
                            text=tts_text_for_prepare, language=tts_lang
                        )
                    finally:
                        if show_mtl_wait and w and getattr(w, "root", None):
                            w.root.after(0, lambda ww=w: ww.set_status("generating"))
                    if self.is_continuous_chat_enabled() and tts_prepared is not None:
                        try:
                            audio_dur = float(getattr(tts_prepared, "duration", 0.0) or 0.0)
                        except Exception:
                            audio_dur = 0.0
                        if audio_dur <= 0.05 or bool(getattr(tts_prepared, "already_streamed", False)):
                            est = max(1.5, len(tts_text_for_prepare or "") / 14.0)
                            audio_dur = max(audio_dur, est)
                        # Cooldown anchor is "now" after prepare; do not add prepare duration again.
                        tail = 1.25 if bool(getattr(tts_prepared, "already_streamed", False)) else 0.95
                        self._extend_continuous_tts_cooldown(audio_dur + tail)
            except Exception as _tts_err:
                logger.error("TTS post_output: %s", _tts_err)
        if success and _wants_auto_tts and tts_prepared is None:
            self._set_status("ready")
        if tts_eligible and tts_prepared is None and tts_skip_msg is None:
            logger.warning(
                "TTS: prepare_speak returned no audio for this reply (check ERROR lines above: engine, CUDA/CPU, or sounddevice)."
            )

        # Finalized Logs + Chat/Help refresh (+ TTS play aligné sur l'affichage des bulles)
        w = getattr(self, "widget", None)
        if w and getattr(w, "root", None):
            try:
                # En cas d'erreur LLM, afficher le message d'erreur comme "réponse" dans la console.
                display_final = llm_error_short_msg if (llm_error_occurred and llm_error_short_msg) else final_text
                if (
                    not self._feedback_debug_mode()
                    and mode_id in ("answer", "help")
                    and not llm_error_occurred
                    and (display_final or "").strip()
                ):
                    from services.tts.tag_sanitize import strip_all_bracket_tags_for_display

                    display_final = strip_all_bracket_tags_for_display(display_final)
                r, f, mid = raw_text, display_final, mode_id
                prep = tts_prepared
                skipm = tts_skip_msg
                reason_log = (getattr(self, "last_llm_reasoning", None) or "").strip()

                def _post_injection_gui(rv=r, fv=f, m=mid, p=prep, sk=skipm, rr=reason_log):
                    try:
                        w.append_console_finalized_entries(rv, fv, m, reasoning_text=rr)
                        if m == "answer":
                            w._refresh_chat_tab()
                            if hasattr(w, "_chat_scroll_to_bottom"):
                                w._chat_scroll_to_bottom()
                        elif m == "help":
                            w._refresh_help_tab()
                            if hasattr(w, "_help_scroll_to_bottom"):
                                w._help_scroll_to_bottom()
                        try:
                            w.root.update_idletasks()
                        except Exception:
                            pass
                        if sk:
                            w._notify(sk, restore_after_ms=5500)
                        elif p is not None:
                            self.tts_manager.play_prepared(p, blocking=False)
                    finally:
                        with self._lock:
                            self._continuous_gui_tts_pending = False

                if self.is_continuous_chat_enabled() and prep is not None:
                    with self._lock:
                        self._continuous_gui_tts_pending = True
                w.root.after(0, _post_injection_gui)
            except Exception:
                pass
        elif tts_eligible:
            if tts_skip_msg:
                logger.info("TTS skipped (no GUI): %s", tts_skip_msg)
            elif tts_prepared is not None:
                self.tts_manager.play_prepared(tts_prepared, blocking=False)
        if w and getattr(w, "root", None):
            # Alerte max input : afficher après injection pour être sûr qu'elle s'affiche (thread-safe, visible)
            if hit_max_input_flag:
                try:
                    msg = w._get_alert("critical.max_input_reached")
                    w.root.after(300, lambda: w._notify(msg, restore_after_ms=5000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
                    w.root.after(350, lambda: w._set_chat_reset_indicator_if_outside_chat() if hasattr(w, "_set_chat_reset_indicator_if_outside_chat") else None)
                except Exception:
                    pass
            # Alerte Answer : troncature output (mi-phrase) → message output ; réponse vide → message input
            if hit_max_output_tokens_flag:
                try:
                    alert_data = getattr(self, "_last_output_limit_alert", None)
                    if alert_data is not None:
                        out_val, out_sug = alert_data
                        msg = w._get_alert("critical.max_output_tokens_reached", max_output=out_val, suggested=out_sug)
                    else:
                        msg = w._get_alert("critical.max_input_context_reached", max_input=max_input_ctx, suggested=suggested_input)
                    w.root.after(350, lambda: w._notify(msg, restore_after_ms=5000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
                    # ⚠ Chat + New chat : seulement limite contexte / input (_last_output_limit_alert=None).
                    # Troncature max output → tuple défini plus haut : notifier sans imposer un "reset" comme si n_ctx était plein.
                    if getattr(self, "_last_output_limit_alert", None) is None:
                        w.root.after(400, lambda: w._set_chat_reset_indicator_if_outside_chat() if hasattr(w, "_set_chat_reset_indicator_if_outside_chat") else None)
                except Exception:
                    pass
            # Notification + son d'erreur LLM (400, timeout, etc.) — affichée après injection pour être visible
            if llm_error_occurred:
                try:
                    self.sound_manager.play_system_sound("llm_error")
                except Exception:
                    pass
                try:
                    short_msg = w._get_alert("critical.llm_error_400") if ("400" in llm_error_msg or "Bad Request" in llm_error_msg) else w._get_alert("critical.llm_error_generic")
                    w.root.after(400, lambda: w._notify(short_msg, restore_after_ms=6000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
                except Exception:
                    pass
                # Erreur 400 (contexte trop grand) : Answer → ⚠ Chat ; Help → ⚠ Help + New chat (même UX)
                if "400" in llm_error_msg or "Bad Request" in llm_error_msg:
                    try:
                        if mode_id == "answer":
                            w.root.after(450, lambda: w._set_chat_reset_indicator_if_outside_chat() if hasattr(w, "_set_chat_reset_indicator_if_outside_chat") else None)
                        elif mode_id == "help":
                            w.root.after(450, lambda: w._set_help_reset_indicator_if_outside_help() if hasattr(w, "_set_help_reset_indicator_if_outside_help") else None)
                    except Exception:
                        pass

    def _notify(self, msg):
        logger.info(msg)
        # Ne pas appeler print(msg) : le QueueHandler du logger envoie déjà vers la GUI, sinon doublon en Full Console

    def _get_alert_for_log(self, key: str):
        """Message pour la console (log), depuis header_alerts YAML via le widget."""
        w = getattr(self, "widget", None)
        if w and hasattr(w, "_get_alert"):
            return w._get_alert(key)
        fallbacks = {
            "regular.processing_stopped": "🛑 Processing stopped",
            "regular.recording_stopped": "🛑 Recording stopped",
            "regular.recording_no_audio": "No audio captured — recording stopped or check microphone.",
            "regular.recording_too_short": "Recording too short — no text detected. Check microphone or speak longer.",
        }
        return fallbacks.get(key, key)

    def _notify_header(self, key: str, restore_after_ms: int = 3000):
        """Affiche l’alerte dans la barre header (widget) — ex. quand l’orchestrator détecte un cancel."""
        w = getattr(self, "widget", None)
        if w and getattr(w, "root", None) and hasattr(w, "_get_alert") and hasattr(w, "_notify"):
            msg = w._get_alert(key)
            w.root.after(0, lambda: w._notify(msg, restore_after_ms=restore_after_ms))

    def _set_status(self, status_id: str):
        """Met à jour le statut GUI (listening, processing, injecting, ready, error, crash, no_speech). Toujours sur le thread principal."""
        w = getattr(self, "widget", None)
        if w and hasattr(w, "set_status") and getattr(w, "root", None):
            w.root.after(0, lambda: w.set_status(status_id))

    def _fit_llm_request_to_context(self, system_prompt: str, text: str, want_max_tokens: int) -> tuple[str, int]:
        """llama-server / chat completions: prompt tokens + max_tokens must not exceed n_ctx.

        Char-based token estimate (chars/4) matches existing logging; truncate system prompt when needed.
        """
        n_ctx = self.get_effective_llm_n_ctx()
        margin = 8
        sp = system_prompt or ""
        u = text or ""
        note = "\n\n[System prompt truncated for session context limit — increase Max input in Settings → Performance.]"
        want_max_tokens = max(1, int(want_max_tokens))

        def approx_tok() -> int:
            return max(1, (len(sp) + len(u)) // 4)

        tok = approx_tok()
        max_out = min(want_max_tokens, max(1, n_ctx - margin - tok))

        while tok + max_out > n_ctx - margin or tok >= n_ctx:
            if len(sp) < 200:
                break
            step = max(400, len(sp) // 8)
            sp = sp[: max(200, len(sp) - step)].rstrip() + note
            tok = approx_tok()
            max_out = min(want_max_tokens, max(1, n_ctx - margin - tok))

        max_out = min(want_max_tokens, max(1, n_ctx - margin - tok))
        if max_out < want_max_tokens and self.config.get("feedback", {}).get("console_output", True):
            logger.info(
                "LLM max_tokens clamped %d → %d so prompt + completion fit n_ctx=%d (approx prompt tok=%d)",
                want_max_tokens,
                max_out,
                n_ctx,
                tok,
            )
        if sp != (system_prompt or ""):
            logger.warning(
                "LLM system prompt truncated to fit n_ctx=%d (approx prompt tok=%d, max_tokens=%d)",
                n_ctx,
                tok,
                max_out,
            )
        return sp, max_out

    def _run_llm_on_main_thread(
        self,
        text,
        system_prompt,
        temperature,
        max_tokens,
        *,
        gui_debug_label: Optional[str] = None,
    ):
        """Execute LLM on main thread using queue to avoid CUDA threading issues."""
        result_queue = queue.Queue()
        system_prompt, max_tokens = self._fit_llm_request_to_context(
            system_prompt, text, max_tokens
        )
        if gui_debug_label:
            self._emit_gui_debug_llm_payload(gui_debug_label, system_prompt, text, max_tokens)

        def llm_task():
            try:
                result = self.llm.process(
                    text=text,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                result_queue.put(("success", result))
            except Exception as e:
                result_queue.put(("error", e))
        
        # Execute immediately (same thread)
        llm_task()
        
        status, result = result_queue.get(timeout=60)
        if status == "error":
            raise result
        return result

    def _license_api_base(self) -> Optional[str]:
        """Base URL for remote entitlement HTTP (no shared secrets in the client).

        Default host: https://perkysue.com — override with env PERKYSUE_LICENSE_API when needed.
        Extension module may adjust endpoint resolution.
        """
        env = (os.environ.get("PERKYSUE_LICENSE_API") or "").strip().rstrip("/")
        dev = self._load_dev_plugin()
        if dev is not None:
            try:
                result = dev.resolve_endpoint(self.paths.plugins, env)
                if result is None:
                    logger.error(
                        "Dev plugin: remote guard active but PERKYSUE_LICENSE_API unset; entitlement HTTP skipped."
                    )
                    return None
                if result != "__SKIP__":
                    return result
            except Exception:
                pass
        return env or "https://perkysue.com"

    def _license_http_headers(self, *, json_body: bool = False) -> Dict[str, str]:
        """Headers for Worker calls. Default urllib UA is often blocked by Cloudflare WAF; use browser-like UA + app marker."""
        ver = (getattr(self.__class__, "APP_VERSION", None) or "unknown").replace(" ", "-")
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36 "
            f"PerkySueDesktop/{ver}"
        )
        h: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": ua,
            "X-PerkySue-Client": "desktop",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _license_post_json(self, path: str, payload: dict) -> Tuple[Dict[str, Any], int]:
        base = self._license_api_base()
        if not base:
            return {"error": "license_api_unconfigured", "detail": "remote_base_unset"}, 0
        url = base + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers=self._license_http_headers(json_body=True),
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return (json.loads(raw) if raw.strip() else {}), resp.getcode() or 200
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", errors="replace")
                body = json.loads(raw) if raw.strip() else {"error": e.reason}
            except json.JSONDecodeError:
                body = {"error": raw or str(e)}
            return body, e.code
        except Exception as e:
            return {"error": str(e)}, 0

    def link_subscription_start(self, email: str) -> Tuple[Dict[str, Any], int]:
        from utils.install_id import get_or_create_install_id

        iid = get_or_create_install_id(self.paths.configs)
        return self._license_post_json(
            "/link-subscription/start",
            {"email": (email or "").strip(), "install_id": iid},
        )

    def link_subscription_resend(self, email: str) -> Tuple[Dict[str, Any], int]:
        from utils.install_id import get_or_create_install_id

        iid = get_or_create_install_id(self.paths.configs)
        return self._license_post_json(
            "/link-subscription/resend",
            {"email": (email or "").strip(), "install_id": iid},
        )

    def link_subscription_verify(self, email: str, code: str) -> Tuple[Dict[str, Any], int]:
        from utils.install_id import get_or_create_install_id

        iid = get_or_create_install_id(self.paths.configs)
        return self._license_post_json(
            "/link-subscription/verify",
            {"email": (email or "").strip(), "install_id": iid, "code": (code or "").strip()},
        )

    def _trial_finalize_local_state(
        self,
        d: Dict[str, Any],
        http: int,
        em: str,
        iid: str,
        host: str,
        newsletter_opt_in: bool,
    ) -> Tuple[Dict[str, Any], int]:
        """After POST /trial/verify: write trial.json or trial_consumed.marker from Worker response."""
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        marker = self.paths.configs / "trial_consumed.marker"

        def _extract_trial_expiry(src: Dict[str, Any]) -> Optional[str]:
            for k in ("expires_at", "trial_expires_at", "expires", "expiry"):
                v = src.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return None

        exp = _extract_trial_expiry(d)
        if bool(d.get("activated")) or (bool(d.get("ok")) and exp):
            try:
                self.paths.configs.mkdir(parents=True, exist_ok=True)
                snap = {
                    "email": em,
                    "install_id": iid,
                    "host": host,
                    "newsletter_opt_in": bool(newsletter_opt_in),
                    "checked_at": now_iso,
                    "source": "trial_api",
                }
                if exp:
                    snap["expires_at"] = exp
                trial_path = self.paths.configs / "trial.json"
                trial_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
                if marker.exists():
                    try:
                        marker.unlink()
                    except OSError:
                        pass
            except Exception:
                pass
            return d, http

        code = (d.get("error_code") or d.get("code") or "").strip().lower()
        if code in ("trial_already_used", "trial_consumed", "trial_denied", "trial_ineligible_paid"):
            try:
                self.paths.configs.mkdir(parents=True, exist_ok=True)
                marker.touch(exist_ok=True)
            except Exception:
                pass
        return d, http

    def trial_start(self, email: str) -> Tuple[Dict[str, Any], int]:
        """Send Brevo OTP for free trial (email must be verified before activation)."""
        import socket
        from utils.install_id import get_or_create_install_id

        em = (email or "").strip().lower()
        iid = get_or_create_install_id(self.paths.configs)
        host = (socket.gethostname() or "").strip()[:253]
        payload = {
            "email": em,
            "install_id": iid,
            "host": host,
            "client_version": getattr(self.__class__, "APP_VERSION", ""),
        }
        return self._license_post_json("/trial/start", payload)

    def trial_resend(self, email: str) -> Tuple[Dict[str, Any], int]:
        from utils.install_id import get_or_create_install_id

        em = (email or "").strip().lower()
        iid = get_or_create_install_id(self.paths.configs)
        return self._license_post_json(
            "/trial/resend",
            {"email": em, "install_id": iid},
        )

    def trial_verify(self, email: str, code: str, newsletter_opt_in: bool) -> Tuple[Dict[str, Any], int]:
        """Verify OTP and activate trial; sync local trial.json / markers."""
        import socket
        from utils.install_id import get_or_create_install_id

        em = (email or "").strip().lower()
        iid = get_or_create_install_id(self.paths.configs)
        host = (socket.gethostname() or "").strip()[:253]
        payload = {
            "email": em,
            "install_id": iid,
            "code": (code or "").strip(),
            "newsletter_opt_in": bool(newsletter_opt_in),
            "host": host,
            "client_version": getattr(self.__class__, "APP_VERSION", ""),
        }
        data, http = self._license_post_json("/trial/verify", payload)
        d = data if isinstance(data, dict) else {}
        return self._trial_finalize_local_state(d, http, em, iid, host, newsletter_opt_in)

    def _deep_scan_period_end_raw(self, obj: Any, depth: int = 0) -> Any:
        """Find first non-empty period-end-like value in nested dict/list (Worker / Stripe shapes)."""
        keys = (
            "current_period_end",
            "expires_at",
            "period_end",
            "expiry_date",
            "subscription_end",
        )
        if depth > 8:
            return None
        if isinstance(obj, dict):
            for k in keys:
                if k in obj:
                    v = obj.get(k)
                    if v is not None and v != "":
                        return v
            for v in obj.values():
                found = self._deep_scan_period_end_raw(v, depth + 1)
                if found is not None and found != "":
                    return found
        elif isinstance(obj, list):
            for it in obj[:40]:
                found = self._deep_scan_period_end_raw(it, depth + 1)
                if found is not None and found != "":
                    return found
        return None

    def _extract_expiry_from_check_payload(self, data: Dict[str, Any]) -> Any:
        """Best-effort renewal/end date from GET /check JSON (flat or nested Stripe-style objects)."""
        if not isinstance(data, dict):
            return None
        for k in ("expires_at", "expiry_date", "current_period_end", "period_end", "subscription_end"):
            v = data.get(k)
            if v is not None and v != "":
                return v
        sub = data.get("subscription")
        if isinstance(sub, dict):
            # Prefer period boundary fields; avoid billing_cycle_anchor (cycle start, not renewal).
            for k in ("current_period_end", "period_end", "ended_at", "cancel_at"):
                v = sub.get(k)
                if v is not None and v != "":
                    return v
        for nest_key in ("stripe", "subscription_details", "entitlement", "license"):
            nest = data.get(nest_key)
            if isinstance(nest, dict):
                for k in ("current_period_end", "expires_at", "period_end", "expiry_date"):
                    v = nest.get(k)
                    if v is not None and v != "":
                        return v
        lp = data.get("license_payload")
        if isinstance(lp, dict):
            for k in ("expires_at", "current_period_end", "period_end", "expiry_date"):
                v = lp.get(k)
                if v is not None and v != "":
                    return v
        found = self._deep_scan_period_end_raw(data)
        if found is not None and found != "":
            return found
        return None

    def refresh_license_from_remote(self, *, timeout_sec: float = 30.0) -> bool:
        """GET /check and write Data/Configs/license.json when Stripe Pro is active (seat hostname optional)."""
        import socket
        import urllib.parse

        from utils.install_id import get_or_create_install_id

        iid = get_or_create_install_id(self.paths.configs)
        host = (socket.gethostname() or "").strip()[:253]
        q = urllib.parse.urlencode({"id": iid, "host": host})
        base = self._license_api_base()
        if not base:
            return False
        url = f"{base}/check?{q}"
        req = urllib.request.Request(url, method="GET", headers=self._license_http_headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return False
        if not data.get("active"):
            return False
        tier = (data.get("tier") or "pro").strip().lower()
        if tier in ("trialing", "trial"):
            tier = "pro"
        if tier != "pro":
            return False
        try:
            lic_path = self.paths.configs / "license.json"
            self.paths.configs.mkdir(parents=True, exist_ok=True)
            prev_mail = None
            if lic_path.exists():
                try:
                    old = json.loads(lic_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                    if isinstance(old, dict) and isinstance(old.get("billing_email"), str):
                        prev_mail = old.get("billing_email", "").strip()
                except Exception:
                    pass
            if not prev_mail:
                aux = self.paths.configs / "billing_email.txt"
                if aux.exists():
                    try:
                        ln = aux.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                        cand = (ln[0] if ln else "").strip()
                        if cand and "@" in cand:
                            prev_mail = cand
                    except OSError:
                        pass
            exp = self._extract_expiry_from_check_payload(data)
            if exp is None and lic_path.exists():
                try:
                    old = json.loads(lic_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                    if isinstance(old, dict):
                        sid_new = (data.get("subscription_id") or "").strip()
                        sid_old = (old.get("subscription_id") or "").strip()
                        if sid_new and sid_new == sid_old:
                            oexp = old.get("expires_at") or old.get("current_period_end")
                            if oexp is not None and oexp != "":
                                exp = oexp
                except Exception:
                    pass
            lp = data.get("license_payload")
            ls = data.get("license_signature")
            snap = {
                "tier": "pro",
                "install_id": iid,
                "source": data.get("source") or "stripe",
                "subscription_id": data.get("subscription_id"),
                "expires_at": exp,
                "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "cancel_at_period_end": bool(data.get("cancel_at_period_end")),
            }
            if isinstance(lp, dict):
                pexp = lp.get("expires_at")
                if pexp is not None and str(pexp).strip() != "":
                    snap["expires_at"] = pexp
                if "cancel_at_period_end" in lp:
                    snap["cancel_at_period_end"] = bool(lp.get("cancel_at_period_end"))
            marker = self._stripe_signed_license_marker_path()
            if isinstance(lp, dict) and isinstance(ls, str) and ls.strip():
                snap["license_payload"] = lp
                snap["license_signature"] = ls.strip()
                try:
                    marker.write_text("1", encoding="utf-8")
                except OSError:
                    pass
            else:
                try:
                    if marker.exists():
                        marker.unlink()
                except OSError:
                    pass
            api_mail = None
            for _mk in ("billing_email", "customer_email", "stripe_email", "email"):
                v = data.get(_mk)
                if isinstance(v, str) and v.strip() and "@" in v:
                    api_mail = v.strip()
                    break
            if api_mail:
                snap["billing_email"] = api_mail
            elif prev_mail:
                snap["billing_email"] = prev_mail
            lic_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
            return True
        except OSError:
            return False

    def get_license_billing_email(self) -> Optional[str]:
        d = self._read_valid_stripe_license()
        if d:
            em = d.get("billing_email")
            if isinstance(em, str) and em.strip() and "@" in em:
                return em.strip()
            return None
        lic = self.paths.configs / "license.json"
        if lic.exists():
            try:
                raw = json.loads(lic.read_text(encoding="utf-8", errors="ignore") or "{}")
                if isinstance(raw, dict):
                    em = raw.get("billing_email")
                    if isinstance(em, str) and em.strip() and "@" in em:
                        return em.strip()
            except Exception:
                pass
        aux = self.paths.configs / "billing_email.txt"
        if aux.exists():
            try:
                line = aux.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                em = (line[0] if line else "").strip()
                if em and "@" in em:
                    return em
            except OSError:
                pass
        return None

    def set_license_billing_email(self, email: str) -> None:
        em = (email or "").strip()
        if not em or "@" not in em:
            return
        p = self.paths.configs / "license.json"
        if p.exists():
            data: Dict[str, Any] = {}
            try:
                raw = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
            data["billing_email"] = em
            try:
                p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
            return
        try:
            aux = self.paths.configs / "billing_email.txt"
            aux.parent.mkdir(parents=True, exist_ok=True)
            aux.write_text(em + "\n", encoding="utf-8")
        except OSError:
            pass

    def _merge_license_root_expiry_from_worker_dict(self, src: Dict[str, Any]) -> None:
        """Copy period end from Worker JSON into license.json root for Plan UI (does not touch signed license_payload)."""
        raw: Any = None
        try:
            raw = self._extract_expiry_from_check_payload(src)
        except Exception:
            raw = None
        if raw is None or raw == "":
            return
        dt = self._license_expiry_value_to_datetime(raw)
        if dt is None:
            return
        p = self.paths.configs / "license.json"
        if not p.exists():
            return
        try:
            if self._read_valid_stripe_license() is None:
                return
        except Exception:
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
        except Exception:
            return
        if not isinstance(data, dict):
            return
        iso = dt.isoformat().replace("+00:00", "Z")
        try:
            data["expires_at"] = iso
            data["current_period_end"] = iso
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def request_billing_portal_url(self) -> Tuple[bool, str]:
        """POST /billing-portal — Worker returns { \"url\": \"...\" } (Stripe Customer Portal session)."""
        from utils.install_id import get_or_create_install_id

        iid = get_or_create_install_id(self.paths.configs)
        body, code = self._license_post_json("/billing-portal", {"install_id": iid})
        if code == 200 and isinstance(body, dict):
            u = body.get("url")
            if isinstance(u, str) and u.strip().startswith("http"):
                try:
                    self._merge_license_root_expiry_from_worker_dict(body)
                except Exception:
                    pass
                return True, u.strip()
        err = ""
        if isinstance(body, dict):
            err = str(body.get("error") or body.get("message") or "").strip()
        return False, err or f"HTTP {code}"

    def _license_snapshot_for_expiry_display_loose(self) -> Optional[Dict[str, Any]]:
        """Show renewal date when license.json has expires_at but no install_id yet (legacy file before next /check)."""
        p = self.paths.configs / "license.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        if (data.get("tier") or "pro").strip().lower() not in ("pro", "trialing", "trial"):
            return None
        if data.get("install_id"):
            return None
        if not data.get("expires_at") and not data.get("current_period_end"):
            return None
        return data

    def get_license_cancel_at_period_end(self) -> bool:
        """True when Stripe subscription is set to end at current period end (cancelled but still active until then)."""
        pl = self._signed_stripe_license_payload()
        if pl is not None and "cancel_at_period_end" in pl:
            v = pl.get("cancel_at_period_end")
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return False
        data = self._read_valid_stripe_license()
        if not isinstance(data, dict):
            return False
        v = data.get("cancel_at_period_end")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return False

    def get_license_expires_display(self, locale_tag: Optional[str] = None) -> Optional[str]:
        """Calendar date from license.json (UTC). US → MM/DD/YYYY; GB and other locales → DD/MM/YYYY."""
        data = self._read_valid_stripe_license()
        pl = self._signed_stripe_license_payload()
        # Prefer signed payload when it carries a period end; else full file + deep scan (Worker may
        # omit expires_at in signed payload but still set root fields, or nest Stripe objects).
        raw: Any = None
        if pl is not None:
            raw = self._extract_expiry_from_check_payload(pl)
        if raw is None or raw == "":
            if data is not None:
                raw = self._extract_expiry_from_check_payload(data)
        if raw is None or raw == "":
            loose = self._license_snapshot_for_expiry_display_loose()
            if loose is not None:
                raw = self._extract_expiry_from_check_payload(loose)
        dt = self._license_expiry_value_to_datetime(raw)
        if dt is None:
            return None
        loc = (locale_tag or "").strip().lower()
        if loc == "us":
            return dt.strftime("%m/%d/%Y")
        return dt.strftime("%d/%m/%Y")

    def run(self, use_gui=True):
        print("\n" + "=" * 50)
        print("  ✅ PerkySue is ready!")
        print("=" * 50)
        self._print_startup_hotkey_summary()
        print("\nPress Ctrl+C to quit.\n")
        if getattr(self, "mic_warning", None):
            print("!" * 50)
            print("  ⚠️  Default microphone looks virtual (Iriun / virtual device).")
            print("      → Use Windows Sound settings to select your real microphone.")
            print("!" * 50)
            print()

        # Start GUI if requested
        if use_gui:
            try:
                from gui.widget import PerkySueWidget
                self.widget = PerkySueWidget(self)
                # Run hotkey manager in background thread
                hotkey_thread = threading.Thread(target=self.hotkey_manager.start_background, daemon=True)
                hotkey_thread.start()
                # Run GUI mainloop
                self.widget.run()
            except ImportError as e:
                print(f"⚠️  GUI not available: {e}")
                print("   Falling back to console mode...")
                self._run_console_mode()
        else:
            self._run_console_mode()
    
    def _run_console_mode(self):
        """Mode console sans GUI."""
        try:
            self.hotkey_manager.start()
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")