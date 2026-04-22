import json
import math
import os
import random
import re
import shutil
import sys
import time
import types
import yaml
import subprocess
import zipfile
from datetime import datetime
import webbrowser
import logging
from urllib.parse import quote
import queue
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional


def _ctk_entry_keep_placeholder_until_keystroke(entry: Any) -> None:
    """CustomTkinter clears placeholder on <FocusIn>; keep hint visible until first keystroke."""
    def _patched_focus_in(self, event=None):
        self._is_focused = True

    entry._entry_focus_in = types.MethodType(_patched_focus_in, entry)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from ..paths import Paths
    from ..utils.audio import BaseAudioCapture
    from ..utils.hotkeys import KEYCODE_TO_NAME, resolve_hotkey_string, format_hotkey_display
    from ..utils.plugin_host import PluginHostContext
    from ..utils.strings import load_strings, merge_strings_at, s, s_list
    from ..utils.skin_paths import (
        _find_tts_personality_yaml,
        normalize_skin_id,
        resolve_character_root,
        resolve_locale_skin_dir,
        iter_data_skins_for_appearance,
        iter_teaser_skin_entries,
        unlocked_skin,
        skin_pack_lang_from_ui,
        skin_locale_codes_match,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from App.paths import Paths
    from App.utils.audio import BaseAudioCapture
    from App.utils.hotkeys import KEYCODE_TO_NAME, resolve_hotkey_string, format_hotkey_display
    from App.utils.plugin_host import PluginHostContext
    from App.utils.strings import load_strings, merge_strings_at, s, s_list
    from App.utils.skin_paths import (
        _find_tts_personality_yaml,
        normalize_skin_id,
        resolve_character_root,
        resolve_locale_skin_dir,
        iter_data_skins_for_appearance,
        iter_teaser_skin_entries,
        unlocked_skin,
        skin_pack_lang_from_ui,
        skin_locale_codes_match,
    )

try:
    import customtkinter as ctk
    from customtkinter import (
        CTk, CTkFrame, CTkLabel, CTkButton, CTkTextbox, CTkEntry,
        CTkOptionMenu, CTkProgressBar, CTkScrollableFrame, CTkImage,
        CTkToplevel, CTkTabview, CTkSwitch, CTkSlider,
    )
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter", "--quiet"])
    import customtkinter as ctk
    from customtkinter import (
        CTk, CTkFrame, CTkLabel, CTkButton, CTkTextbox, CTkEntry,
        CTkOptionMenu, CTkProgressBar, CTkScrollableFrame, CTkImage,
        CTkToplevel, CTkTabview, CTkSwitch, CTkSlider,
    )

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ─── Colors ──────────────────────────────────────────────────
BG       = "#1F1F23" 
SIDEBAR  = "#26262B"
CONTENT  = "#1F1F23"
CARD     = "#2D2D35"
INPUT    = "#18181B"
HEADER_L = "#4F2683" 
HEADER_R = "#D33660" 
# Dégradé rouge (alertes clignotantes — remplace le mauve le temps de la notification)
HEADER_ALERT_L = "#5C0F0F"
HEADER_ALERT_R = "#F87171"
TXT      = "#FFFFFF"
TXT2     = "#A1A1AA"
MUTED    = "#71717A"
SEL_BG   = "#3F3F46"
GOLD     = "#D4AF37"
SKIN_SELECTED_BORDER = "#ffc410"  # contour or du skin sélectionné (Appearance)
ACCENT   = "#8B5CF6"
BLUE     = "#3B82F6"
GREEN_BT = "#22C55E"  # same green as Listening avatar ring + About “free / success” accents
GREEN_HV = "#16A34A"

# Sidebar nav — libellés via common.nav.* (trois espaces entre icône et texte)
_BASE_NAV_PAGE_IDS = (
    "console",
    "shortcuts",
    "settings",
    "modes",
    "chat",
    "help",
    "user",
    "about",
)
NAV_PAGE_IDS = _BASE_NAV_PAGE_IDS  # compat ; ordre réel = self._nav_page_ids après _build_body


def _build_nav_page_ids(_orchestrator) -> tuple:
    """Insère l'onglet voice après help (toujours visible : teaser Free / Voice Pro)."""
    ids = list(_BASE_NAV_PAGE_IDS)
    insert_after = "help"
    idx = ids.index(insert_after) + 1 if insert_after in ids else len(ids) - 2
    ids.insert(idx, "voice")
    # Avatar Editor — uniquement si plugin Data/Plugins/avatar_editor + manifest enabled
    if _orchestrator is not None:
        try:
            mod = _orchestrator._load_avatar_editor_plugin()
            if mod is not None:
                chk = getattr(mod, "check_enabled", None)
                enabled = True
                if callable(chk):
                    enabled = bool(chk(_orchestrator.paths.plugins))
                if enabled:
                    try:
                        ia = ids.index("about")
                    except ValueError:
                        ia = len(ids)
                    ids.insert(ia, "avatar_editor")
        except Exception:
            pass
        # Brainstorm — plugin panel (A/B scenario engine), Pro-only by design.
        try:
            mod = _orchestrator._load_brainstorm_plugin()
            if mod is not None:
                chk = getattr(mod, "check_enabled", None)
                enabled = True
                if callable(chk):
                    enabled = bool(chk(_orchestrator.paths.plugins))
                if enabled and bool(getattr(_orchestrator, "is_effective_pro", lambda: False)()):
                    try:
                        ih = ids.index("help")
                    except ValueError:
                        ih = len(ids)
                    ids.insert(ih, "brainstorm")
        except Exception:
            pass
    return tuple(ids)


def _ctk_switch_is_on(sw) -> bool:
    """CTkSwitch.get() peut renvoyer 0/1 ou 'on'/'off' selon la version."""
    v = sw.get()
    if isinstance(v, str):
        return v.lower() in ("on", "true", "1")
    return bool(v)

# PNG stem in App/assets/lang-flags/ → strings file (<lang>.yaml).
# Stems may differ from ISO 639-1 when one flag represents a language (bd→bn Bengali, sa→ar Arabic).
FLAG_STEMS_ORDER = (
    "us", "uk", "fr", "de", "es", "it", "pt", "nl", "jp", "ko", "cn", "in",
    "ru", "id", "bd", "sa",
)
FLAG_STEM_TO_LANG = {
    "us": ("us", None),
    "uk": ("gb", None),
    "fr": ("fr", None),
    "de": ("de", None),
    "es": ("es", None),
    "it": ("it", None),
    "pt": ("pt", None),
    "nl": ("nl", None),
    "jp": ("ja", None),
    "ko": ("ko", None),
    "cn": ("zh", None),
    "in": ("hi", None),
    "ru": ("ru", None),
    "id": ("id", None),
    "bd": ("bn", None),
    "sa": ("ar", None),
}

# Libellés autonymes (affichés tels quels quelle que soit la langue UI) — pas de clés i18n
FLAG_STEM_NATIVE_LABEL = {
    "us": "English (US)",
    "uk": "English (UK)",
    "fr": "français",
    "de": "Deutsch",
    "es": "español",
    "it": "italiano",
    "pt": "português",
    "nl": "Nederlands",
    "jp": "日本語",
    "ko": "한국어",
    "cn": "中文",
    "in": "हिन्दी",
    "ru": "Русский",
    "id": "Bahasa Indonesia",
    "bd": "বাংলা",
    "sa": "العربية",
}

# Status sous l'avatar : id -> (emoji, color) — labels from common.statuses.*
_STATUS_META = {
    "listening": ("🎙️", GREEN_BT),
    "processing": ("⚡", "#F59E0B"),
    "generating": ("⚙️", "#64748B"),
    "injecting": ("✨", ACCENT),
    "tts_loading": ("🔥", "#F59E0B"),
    "speaking": ("🔊", GOLD),
    "ready": ("✅", TXT),
    "error": ("⚠️", "#F59E0B"),
    "crash": ("❌", "#EF4444"),
    "no_speech": ("🔇", MUTED),
}


def _status_tuple(status_id: str):
    sid = status_id if status_id in _STATUS_META else "ready"
    emoji, color = _STATUS_META[sid]
    label = s(f"common.statuses.{sid}")
    return (emoji, label, color)
# Couleurs secondaires pour l'animation (Listening / Processing)
STATUS_PULSE = {
    "listening": (GREEN_BT, "#16A34A"),
    "processing": ("#F59E0B", "#FBBF24"),
    "generating": ("#64748B", "#94A3B8"),
    "tts_loading": ("#F59E0B", "#FBBF24"),
    "speaking": (GOLD, "#FCD34D"),
}

# Fallback si header_tips.yaml absent ou invalide (tips + shortcuts/custom)
HEADER_TIPS_DEFAULT = [
    "Tip · Place your cursor where you write emails, then press Alt+M to dictate a full email.",
    "Tip · Select any text and press Alt+I to instantly improve the wording.",
    "Tip · Select a paragraph and press Alt+P to make it more professional.",
    "Tip · After a long meeting, press Alt+S to get a concise summary.",
    "Tip: Edit shortcuts in Shortcuts (sidebar).",
    "Tip: Alt+V/B/N = Custom prompts.",
    "Tip: Alt+T = Transcribe (no LLM).",
]


def _all_descendants(w):
    """Return widget w and all its descendants (for binding tooltip to whole card)."""
    out = [w]
    try:
        for c in w.winfo_children():
            out.extend(_all_descendants(c))
    except tk.TclError:
        pass
    return out


def _all_winfo_ids(w):
    """Collect winfo_id() of w and all descendants."""
    ids = set()
    try:
        ids.add(w.winfo_id())
        for c in w.winfo_children():
            ids.update(_all_winfo_ids(c))
    except tk.TclError:
        pass
    return ids


class Tooltip:
    """
    Hover tooltip: by default bound to card + descendants; or only to bind_widgets (e.g. Select/Download).

    Recommended Models guideline: keep bind_widgets=[action_btn] so the rich tooltip shows only over the
    action button. CustomTkinter uses inner Tk widgets whose winfo_id may not match descendant sets;
    _bind_roots + _is_allowed_widget() (master-chain) fixes "tooltip never shows". The throttled global
    <Motion> guard fixes stuck/missed Leave. Keep this behavior aligned with ARCHITECTURE.md (Models section).
    """
    _current = None  # tooltip actuellement visible (pour le fermer au clic Get)
    _guard_installed_on = set()  # root widget path(s) where motion guard is installed

    def __init__(self, card, text="", delay_ms=100, bind_widgets=None, content_builder=None):
        self.card = card
        self.text = (text or "").strip()
        self._content_builder = content_builder
        self.delay_ms = delay_ms
        self._job = None
        self._hide_job = None
        self._tw = None
        self._hovered_widget = None
        self._bind_roots = []
        if bind_widgets is not None:
            self._card_ids = set()
            for bw in bind_widgets:
                self._bind_roots.append(bw)
                self._card_ids.update(_all_winfo_ids(bw))
                for w in _all_descendants(bw):
                    try:
                        w.bind("<Enter>", self._on_enter)
                        w.bind("<Leave>", self._on_leave)
                    except tk.TclError:
                        pass
        else:
            self._card_ids = _all_winfo_ids(card)
            for w in _all_descendants(card):
                try:
                    w.bind("<Enter>", self._on_enter)
                    w.bind("<Leave>", self._on_leave)
                except tk.TclError:
                    pass

    def _is_allowed_widget(self, widget):
        """True if the pointer is over bind_widgets or an inner child (CTk: walk master chain, see class doc)."""
        if widget is None:
            return False
        try:
            w = widget
            while w is not None:
                if w in self._bind_roots:
                    return True
                w = getattr(w, "master", None)
        except Exception:
            pass
        try:
            return getattr(widget, "winfo_id", None) and widget.winfo_id() in self._card_ids
        except Exception:
            return False

    @classmethod
    def _install_motion_guard(cls, root):
        """
        Install a single, lightweight global <Motion> guard on the given root.
        Purpose: CustomTkinter can occasionally miss <Leave> on fast pointer moves,
        so we close any visible tooltip whenever the pointer is not over an allowed widget.
        """
        try:
            root_key = str(root)
        except Exception:
            return
        if root_key in cls._guard_installed_on:
            return
        cls._guard_installed_on.add(root_key)

        def _on_motion(_e=None):
            cur = Tooltip._current
            if not cur:
                return
            try:
                if not cur.card.winfo_exists():
                    cur._hide()
                    return
                rx = root.winfo_rootx()
                ry = root.winfo_rooty()
                px = root.winfo_pointerx()
                py = root.winfo_pointery()
                w = root.winfo_containing(px - rx, py - ry)
                if cur._is_allowed_widget(w):
                    return
            except Exception:
                pass
            Tooltip.hide_current()

        # Throttle: at most one check per 50ms.
        state = {"job": None}

        def _throttled_motion(_e=None):
            if state["job"] is not None:
                return
            try:
                state["job"] = root.after(50, lambda: (state.__setitem__("job", None), _on_motion()))
            except Exception:
                state["job"] = None

        try:
            root.bind_all("<Motion>", _throttled_motion, add="+")
        except Exception:
            try:
                root.bind("<Motion>", _throttled_motion)
            except Exception:
                pass

    def _on_enter(self, e):
        try:
            if not self.card.winfo_exists():
                return
            root = self.card.winfo_toplevel()
        except tk.TclError:
            return
        Tooltip._install_motion_guard(root)
        self._hovered_widget = e.widget
        if self._hide_job:
            root.after_cancel(self._hide_job)
            self._hide_job = None
        if self._job:
            return
        self._job = root.after(self.delay_ms, self._show)

    def _on_leave(self, e):
        try:
            if not self.card.winfo_exists():
                return
            root = self.card.winfo_toplevel()
        except tk.TclError:
            return
        if self._job:
            root.after_cancel(self._job)
            self._job = None
        self._hide_job = root.after(80, self._hide_if_outside)

    def _hide_if_outside(self):
        self._hide_job = None
        try:
            if not self.card.winfo_exists():
                return
            root = self.card.winfo_toplevel()
        except tk.TclError:
            return
        try:
            rx = root.winfo_rootx()
            ry = root.winfo_rooty()
            px = root.winfo_pointerx()
            py = root.winfo_pointery()
            w = root.winfo_containing(px - rx, py - ry)
            if self._is_allowed_widget(w):
                return
        except (tk.TclError, AttributeError, TypeError):
            pass
        self._hide()

    def _show(self):
        self._job = None
        if self._tw:
            return
        try:
            if not self.card.winfo_exists():
                return
            root = self.card.winfo_toplevel()
        except tk.TclError:
            return
        Tooltip._install_motion_guard(root)
        Tooltip._current = self
        self._tw = tk.Toplevel(root)
        self._tw.wm_overrideredirect(True)
        self._tw.configure(bg=CARD)
        if self._content_builder:
            self._content_builder(self._tw)
        else:
            lbl = tk.Label(
                self._tw, text=self.text,
                font=("Segoe UI", 11), bg=CARD, fg=TXT,
                relief="solid", borderwidth=1, highlightbackground="#3A3A42",
                padx=10, pady=6, justify=tk.LEFT,
            )
            lbl.pack()
        anchor = self._hovered_widget if (self._hovered_widget and getattr(self._hovered_widget, "winfo_exists", None) and self._hovered_widget.winfo_exists()) else self.card
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        except tk.TclError:
            x = self.card.winfo_rootx()
            y = self.card.winfo_rooty() + self.card.winfo_height() + 4
        self._tw.wm_geometry(f"+{x}+{y}")

    def _hide(self):
        if self._tw:
            try:
                self._tw.destroy()
            except tk.TclError:
                pass
            self._tw = None
        if Tooltip._current == self:
            Tooltip._current = None

    @classmethod
    def hide_current(cls):
        """Ferme le tooltip visible (ex. au clic sur Get)."""
        if cls._current:
            cls._current._hide()
            cls._current = None


# ─── Model catalog (fallback if YAML missing) ─────────────────
MODELS = [
    {"name": "Mistral-Neral-Nemo", "desc": "Instruct-2407", "letter": "M", "color": "#E35A24", "status": "get"},
    {"name": "Deepseeker-Kunou", "desc": "Kunou-Qwen", "letter": "D", "color": "#4F46E5", "status": "progress", "pct": 25},
    {"name": "Llama-3-8B-Instruct", "desc": "Q4_K_M", "letter": "L", "color": "#10B981", "status": "select"},
    {"name": "Qwen-2.5-7B", "desc": "Chat-Q4", "letter": "Q", "color": "#F59E0B", "status": "current"},
]

# (Garde tes autres fonctions get_avatar_path, create_gradient_img, etc... et ajoute celle-ci en dessous :)

def create_progress_img(width, height, progress, radius=6):
    """Génère une barre de progression (fond opaque pour affichage fiable sous Windows)."""
    if not HAS_PIL: return None
    # Fond opaque (couleur carte) pour éviter barre invisible avec transparence
    card_rgb = tuple(int(CARD.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    img = Image.new("RGB", (width, height), card_rgb)
    draw = ImageDraw.Draw(img)
    
    # Fond de la barre (gris foncé)
    bg_color = tuple(int(INPUT.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=bg_color)
    
    # Remplissage (Vert)
    if progress > 0:
        fill_width = max(radius*2, int(width * (progress / 100.0)))
        fill_color = tuple(int(GREEN_BT.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        draw.rounded_rectangle((0, 0, fill_width, height), radius=radius, fill=fill_color)
        
    # Texte du pourcentage
    try: fnt = ImageFont.truetype("seguiemj.ttf", 13) 
    except: fnt = ImageFont.load_default()
    text = f"{progress}%"
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width-tw)/2, (height-th)/2 - 1), text, font=fnt, fill="white")
    
    return img


def _resource_bar_color(label: str, pct: int, is_temp: bool = False) -> str:
    """Color for a resource bar based on usage percentage and metric type.

    - Base color depends on label (CPU, RAM, GPU, VRAM, Temp)
    - High usage overrides base with amber / red according to thresholds.
    """
    lbl = (label or "").upper()
    # Base colors per metric (low usage)
    if lbl == "VRAM":
        base = ACCENT  # violet / mauve
    elif lbl == "GPU":
        base = "#0EA5E9"  # cyan / blue
    elif lbl == "RAM":
        base = GREEN_BT
    elif lbl == "CPU":
        base = GREEN_BT
    elif lbl == "TEMP":
        base = "#22C55E"  # start green, will amber/red when hot
    else:
        base = GREEN_BT

    if is_temp:
        # Gradient temperature palette (~CPU/GPU temps in °C)
        # < 40° = green, <50° = gold, <60° = orange, <70° = light red, >=70° = deep red.
        if pct < 40:
            return "#22C55E"  # green
        if pct < 50:
            return "#EAB308"  # gold
        if pct < 60:
            return "#F97316"  # orange
        if pct < 70:
            return "#FB7185"  # light red
        return "#B91C1C"      # dark red

    if pct < 70:
        return base
    if pct < 90:
        return "#F59E0B"
    return "#EF4444"


def create_resource_bar_img(width, height, pct, label, color=None, unit="%", radius=6):
    """Génère une barre de ressource compacte (fond INPUT, remplissage coloré, label+valeur superposés).
    Style ComfyUI : label en bas-gauche (regular), valeur en haut-droite (bold)."""
    if not HAS_PIL:
        return None
    bg_rgb = tuple(int(INPUT.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    if color is None:
        color = GREEN_BT
    fill_rgb = tuple(int(color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

    img = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Fond arrondi avec marge intérieure pour éviter tout clipping visuel
    inset = 2
    inner_left = inset
    inner_top = inset
    inner_right = width - inset - 1
    inner_bottom = height - inset - 1
    draw.rounded_rectangle((inner_left, inner_top, inner_right, inner_bottom), radius=radius, fill=bg_rgb)

    # Remplissage proportionnel
    clamped = max(0, min(100, pct))
    if clamped > 0:
        span = inner_right - inner_left
        fill_w = max(radius * 2, int(span * clamped / 100))
        draw.rounded_rectangle(
            (inner_left, inner_top, inner_left + fill_w, inner_bottom),
            radius=radius,
            fill=fill_rgb,
        )

    # Polices : essayer plusieurs chemins Windows pour Segoe UI
    fnt_label = None
    fnt_value = None
    for font_regular, font_bold in [("segoeui.ttf", "segoeuib.ttf"), ("Segoe UI", "Segoe UI Bold")]:
        try:
            fnt_label = ImageFont.truetype(font_regular, 12)
            fnt_value = ImageFont.truetype(font_bold, 13)
            break
        except Exception:
            continue
    if fnt_label is None:
        try:
            fnt_label = ImageFont.truetype("seguiemj.ttf", 12)
            fnt_value = fnt_label
        except Exception:
            fnt_label = ImageFont.load_default()
            fnt_value = fnt_label

    text_val = f"{pct}{unit}"

    # Label en bas-gauche (padding gauche important pour qu'il reste lisible)
    lbl_bbox = draw.textbbox((0, 0), label, font=fnt_label)
    lbl_h = lbl_bbox[3] - lbl_bbox[1]
    draw.text(
        (inner_left + 25, inner_bottom - lbl_h - 6),
        label,
        font=fnt_label,
        fill="white",
    )

    # Valeur en haut-droite (bold)
    val_bbox = draw.textbbox((0, 0), text_val, font=fnt_value)
    val_w = val_bbox[2] - val_bbox[0]
    draw.text(
        (inner_right - val_w - 25, inner_top + 1),
        text_val,
        font=fnt_value,
        fill="white",
    )

    return img


def create_record_icon(size: int = 18):
    """Icône Start: cercle rouge plein entouré d'un anneau blanc, fond transparent."""
    if not HAS_PIL:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    outer_r = size // 2 - 1
    gap = 2
    inner_r = outer_r - gap
    # Anneau blanc
    draw.ellipse(
        (cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r),
        outline=(255, 255, 255, 255),
        width=2,
    )
    # Cercle rouge plein
    draw.ellipse(
        (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r),
        fill=(239, 68, 68, 255),
    )
    try:
        return CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None


def create_abort_icon(size: int = 18):
    """Icône Abort: carré noir plein aux coins très légèrement arrondis, fond transparent."""
    if not HAS_PIL:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    inset = 3
    r = 2
    draw.rounded_rectangle(
        (inset, inset, size - inset, size - inset),
        radius=r,
        fill=(15, 15, 18, 255),  # quasi noir, reste lisible sur SEL_BG
    )
    try:
        return CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None


def _get_nvidia_stats():
    """Query nvidia-smi for GPU utilization, VRAM, temperature. Returns dict or None."""
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) >= 4:
                gpu_util = int(parts[0].strip())
                vram_used = int(parts[1].strip())
                vram_total = int(parts[2].strip())
                temp = int(parts[3].strip())
                return {
                    "gpu_pct": gpu_util,
                    "vram_used_mb": vram_used,
                    "vram_total_mb": vram_total,
                    "vram_pct": int(vram_used / vram_total * 100) if vram_total > 0 else 0,
                    "temp_c": temp,
                }
    except Exception:
        pass
    return None


# ─── Utilitaires PIL pour UI Parfaite ─────────────────────────

def split_skin_id(skin_id):
    """
    skin_id = "Default" | "Character/Locale" canonique (ex. ``Mike/FR``).
    Retourne (character, locale_ou_None) : ``(None, "Default")`` ou ``("Mike", "FR")``.
    """
    if not skin_id or skin_id == "Default":
        return None, "Default"
    if "/" in skin_id:
        parts = skin_id.split("/", 1)
        return parts[0].strip(), (parts[1].strip() or None)
    return skin_id, None


def get_avatar_path(skin_id, use_teaser_if_locked=True, paths: Optional[Paths] = None):
    """
    Chemin profile.png : Default, ``Data/Skins/<Character>/<Locale>/`` (ou ``images/profile.png``),
    ancien ``<Locale>/<Character>``, puis **racine personnage** ``Data/Skins/<Character>/profile.png``
    (avatar partagé si le dossier locale n’en a pas), ou Teaser si pack verrouillé.
    """
    if paths is None:
        try:
            paths = Paths()
        except Exception:
            paths = None
    base_dir = Path(__file__).resolve().parent.parent.parent
    if skin_id == "Default":
        p = base_dir / "App" / "Skin" / "Default" / "images" / "profile.png"
        return str(p) if p.exists() else None
    character, loc = split_skin_id(skin_id)
    if character is None:
        return None

    def _try_dir(skin_dir: Path) -> Optional[str]:
        if not skin_dir.is_dir():
            return None
        for candidate in (skin_dir / "images" / "profile.png", skin_dir / "profile.png"):
            if candidate.exists():
                return str(candidate)
        return None

    if paths is not None and loc:
        resolved = resolve_locale_skin_dir(paths, f"{character}/{loc}")
        if resolved:
            got = _try_dir(resolved)
            if got:
                return got

    if loc:
        for skin_dir in (
            base_dir / "Data" / "Skins" / character / loc,
            base_dir / "Data" / "Skins" / loc / character,
        ):
            got = _try_dir(skin_dir)
            if got:
                return got
        # Avatar au niveau personnage (ex. tts_personality.yaml + profile.png sous <Character>/, locale dans <Character>/EN/)
        char_root = None
        if paths is not None:
            try:
                char_root = resolve_character_root(paths, skin_id)
            except Exception:
                char_root = None
        if char_root is None:
            char_root = base_dir / "Data" / "Skins" / character
        if char_root.is_dir():
            got = _try_dir(char_root)
            if got:
                return got

    flat = base_dir / "Data" / "Skins" / character
    if flat.is_dir() and not loc:
        got = _try_dir(flat)
        if got:
            return got

    if use_teaser_if_locked and loc:
        troot = base_dir / "App" / "Skin" / "Teaser"
        for teaser in (
            troot / character / loc / "profile.png",
            troot / loc / character / "profile.png",
        ):
            if teaser.is_file():
                return str(teaser)
    return None


def skin_folder_exists(skin_id, paths: Optional[Paths] = None):
    """True si le skin Pro est présent sous Data/Skins (layout nouveau ou legacy)."""
    if skin_id == "Default":
        return True
    if paths is None:
        try:
            paths = Paths()
        except Exception:
            paths = None
    if paths is not None:
        if resolve_locale_skin_dir(paths, skin_id):
            return True
    character, loc = split_skin_id(skin_id)
    if character is None:
        return False
    base_dir = Path(__file__).resolve().parent.parent.parent
    if loc and (base_dir / "Data" / "Skins" / character / loc).exists():
        return True
    if loc and (base_dir / "Data" / "Skins" / loc / character).exists():
        return True
    return (base_dir / "Data" / "Skins" / character).exists()


def discover_skins(paths: Paths):
    """
    Skins pour Apparence : ``App/Skin/Teaser`` (plaquette) **et** packs **uniquement** sous
    ``Data/Skins`` (``tts_personality.yaml`` + ``profile.png`` à la racine personnage + au moins un sous-dossier locale).
    Dédupliqués par id canonique ; ``unlocked`` passe à True si le pack existe sous ``Data/Skins`` (même id déjà vu via Teaser).
    """
    if paths is None:
        return []
    by_id: dict[str, dict] = {}

    def _append(char: str, loc: str) -> None:
        sid = normalize_skin_id(paths, f"{char}/{loc}")
        if sid == "Default" or "/" not in sid:
            return
        name, lang = sid.split("/", 1)
        unlocked = unlocked_skin(paths, name, lang)
        if sid in by_id:
            if unlocked:
                by_id[sid]["unlocked"] = True
            return
        by_id[sid] = {
            "id": sid,
            "lang": lang,
            "name": name,
            "unlocked": unlocked,
        }

    for char, loc, _profile in iter_teaser_skin_entries(paths):
        _append(char, loc)
    for char, loc, _profile in iter_data_skins_for_appearance(paths):
        _append(char, loc)

    result = list(by_id.values())
    result.sort(key=lambda x: ((x.get("name") or "").upper(), (x.get("lang") or "").upper()))
    return result

def create_gradient_img(width, height, color1, color2):
    if not HAS_PIL: return None
    base = Image.new('RGB', (width, height), color1)
    top = Image.new('RGB', (width, height), color2)
    mask = Image.new('L', (width, height))
    mask_data = [int(255 * (x / width)) for y in range(height) for x in range(width)]
    mask.putdata(mask_data)
    base.paste(top, (0, 0), mask)
    return ImageTk.PhotoImage(base)

def _text_needs_cjk_or_devanagari(s: str) -> bool:
    """True if label needs a CJK / Indic-capable face (not Segoe UI alone)."""
    if not s:
        return False
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            return True
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            return True
        if 0xAC00 <= o <= 0xD7AF:
            return True
        if 0x0900 <= o <= 0x097F:
            return True
    return False


def _text_has_hangul(s: str) -> bool:
    """Hangul syllables / jamo — must not use YaHei-first stack or Pillow often shows tofu for Korean."""
    if not s:
        return False
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7AF:
            return True
        if 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            return True
    return False


def _text_has_japanese_kana(s: str) -> bool:
    """Hiragana / Katakana — prefer Yu Gothic before YaHei for header canvas text."""
    if not s:
        return False
    for ch in s:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            return True
    return False


def _text_has_devanagari(s: str) -> bool:
    """Devanagari (Hindi, etc.) — YaHei-first stack often shows tofu; Nirmala / Mangal cover script."""
    if not s:
        return False
    for ch in s:
        o = ord(ch)
        if 0x0900 <= o <= 0x097F:
            return True
    return False


def _font_for_canvas_button_text(size: int = 19, text: str = ""):
    """
    PIL font for gradient header buttons (e.g. Patreon). For Latin + emoji, **Segoe UI Emoji**
    (seguiemj) must come before segoeui.ttf — otherwise ❤ renders as a box in Pillow. CJK/Devanagari:
    **Order matters**: msyh (YaHei) first is wrong for Korean (Malgun), Japanese kana (Yu Gothic),
    and Hindi/Devanagari (Nirmala/Mangal) — Pillow uses the first font that loads, not OS fallback.
    """
    if not HAS_PIL:
        return ImageFont.load_default()
    candidates = []
    if sys.platform == "win32":
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        segoe_ui = os.path.join(fonts_dir, "segoeui.ttf")
        segoe_emoji = os.path.join(fonts_dir, "seguiemj.ttf")
        malgun = os.path.join(fonts_dir, "malgun.ttf")
        malgun_bd = os.path.join(fonts_dir, "malgunbd.ttf")
        yu_gothic = os.path.join(fonts_dir, "YuGothM.ttc")
        msyh = os.path.join(fonts_dir, "msyh.ttc")
        msyh_bd = os.path.join(fonts_dir, "msyhbd.ttc")
        nirmala = os.path.join(fonts_dir, "Nirmala.ttf")
        nirmala_ui = os.path.join(fonts_dir, "NirmalaUI.ttf")
        mangal = os.path.join(fonts_dir, "Mangal.ttf")
        if _text_needs_cjk_or_devanagari(text):
            if _text_has_hangul(text):
                candidates = [
                    (malgun, None),
                    (malgun_bd, None),
                    (msyh, 0),
                    (msyh_bd, 0),
                    (yu_gothic, 0),
                    (nirmala, None),
                    (segoe_ui, None),
                ]
            elif _text_has_japanese_kana(text):
                candidates = [
                    (yu_gothic, 0),
                    (msyh, 0),
                    (msyh_bd, 0),
                    (malgun, None),
                    (malgun_bd, None),
                    (nirmala, None),
                    (segoe_ui, None),
                ]
            elif _text_has_devanagari(text):
                candidates = [
                    (nirmala, None),
                    (nirmala_ui, None),
                    (mangal, None),
                    (msyh, 0),
                    (msyh_bd, 0),
                    (malgun, None),
                    (malgun_bd, None),
                    (yu_gothic, 0),
                    (segoe_ui, None),
                ]
            else:
                candidates = [
                    (msyh, 0),
                    (msyh_bd, 0),
                    (malgun, None),
                    (malgun_bd, None),
                    (yu_gothic, 0),
                    (nirmala, None),
                    (segoe_ui, None),
                ]
        else:
            # Latin + ❤ : Segoe UI **.ttf** often draws U+2764 as tofu under PIL; original build used **seguiemj** first.
            # Order: emoji face → Segoe UI → CJK fallback.
            candidates = [
                (segoe_emoji, None),
                (segoe_ui, None),
                (os.path.join(fonts_dir, "msyh.ttc"), 0),
            ]
    for path, idx in candidates:
        try:
            if not path or not os.path.isfile(path):
                continue
            if idx is not None:
                return ImageFont.truetype(path, size, index=idx)
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    for rel in ("seguiemj.ttf",):
        try:
            p = os.path.abspath(rel)
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_segoe_emoji_font(size: int = 19):
    """Segoe UI Emoji — glyphes couleur (❤) ; les polices CJK ne les ont souvent pas sous Pillow."""
    if not HAS_PIL:
        return None
    if sys.platform == "win32":
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguiemj.ttf")
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return None


def _canvas_text_has_heart(s: str) -> bool:
    return "\u2764" in s


def _layout_mixed_heart_canvas_segments(text: str, fnt_cjk, fnt_emoji):
    """
    Bbox d'ensemble des segments posés en ligne. **anchor=\"ls\"** (ligne de base gauche) pour tous :
    l'ancre par défaut \"la\" (ascender) mélange mal Segoe UI Emoji (cœur) et police CJK — le texte
    japonais paraît « couler » sous le cœur alors que le glyphe emoji reste visuellement haut dans sa boîte.
    """
    im = Image.new("RGBA", (1, 1))
    dr = ImageDraw.Draw(im)
    min_l = float("inf")
    min_t = float("inf")
    max_r = float("-inf")
    max_b = float("-inf")
    cx = 0
    baseline_y = 0.0
    segments = []
    for part in re.split("(\u2764\uFE0F?)", text):
        if not part:
            continue
        fnt = fnt_emoji if part.startswith("\u2764") else fnt_cjk
        bbox = dr.textbbox((cx, baseline_y), part, font=fnt, anchor="ls")
        min_l = min(min_l, bbox[0])
        min_t = min(min_t, bbox[1])
        max_r = max(max_r, bbox[2])
        max_b = max(max_b, bbox[3])
        segments.append((cx, part, fnt))
        cx = bbox[2]
    tw = max_r - min_l
    th = max_b - min_t
    return tw, th, min_l, min_t, segments


def _draw_mixed_heart_canvas_segments(draw, segments, x_draw: float, y_draw: float, fill):
    """y_draw = ordonnée de la ligne de base commune (anchor ls)."""
    for cx, part, fnt in segments:
        xy = (cx + x_draw, y_draw)
        draw.text(xy, part, font=fnt, anchor="ls", fill=fill)
        draw.text((xy[0] + 0.5, xy[1]), part, font=fnt, anchor="ls", fill=fill)


def create_canvas_btn(text, width, height, radius, hex_top, hex_bottom, hex_shadow):
    """Bouton Patreon avec Vrai Dégradé vertical et Ombre portée"""
    if not HAS_PIL: return None
    img = Image.new("RGBA", (width, height + 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. Ombre portée
    c_sh = tuple(int(hex_shadow.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    draw.rounded_rectangle((0, 4, width, height + 4), radius=radius, fill=c_sh)
    
    # 2. Création du dégradé
    grad = Image.new("RGBA", (width, height), (0,0,0,0))
    c1 = tuple(int(hex_top.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    c2 = tuple(int(hex_bottom.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    for y in range(height):
        r = int(c1[0] + (c2[0] - c1[0]) * (y / height))
        g = int(c1[1] + (c2[1] - c1[1]) * (y / height))
        b = int(c1[2] + (c2[2] - c1[2]) * (y / height))
        ImageDraw.Draw(grad).line([(0, y), (width, y)], fill=(r, g, b, 255))
        
    # 3. Masque arrondi
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)
    
    # 4. Texte (police UI multilingue — pas seulement seguiemj, sinon CJK → tofu)
    fnt = _font_for_canvas_button_text(19, text)
    fnt_emoji = _load_segoe_emoji_font(19)
    # ❤ + japonais/coreen : une seule police CJK n'a souvent pas U+2764 sous Pillow → rendu mixte.
    if _text_needs_cjk_or_devanagari(text) and _canvas_text_has_heart(text) and fnt_emoji is not None:
        tw, th, min_l, min_t, segments = _layout_mixed_heart_canvas_segments(text, fnt, fnt_emoji)
        x_draw = (width - tw) / 2 - min_l
        y_draw = (height - th) / 2 + 3 - min_t
        _draw_mixed_heart_canvas_segments(draw, segments, x_draw, y_draw, "white")
    else:
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # Centrer l'encre (bbox Pillow peut commencer hors (0,0)) — même règle que le rendu mixte.
        x = (width - tw) / 2 - bbox[0]
        y = (height - th) / 2 + 3 - bbox[1]
        draw.text((x, y), text, font=fnt, fill="white")
        draw.text((x + 0.5, y), text, font=fnt, fill="white")
    return ImageTk.PhotoImage(img)

def create_avatar_circle(size, border_color, border_width, is_main=False, img_path=None, show_lock=False, accent_color=None, ring_offset_px: int = 0):
    """Crée l'avatar avec l'image PNG découpée en cercle. Si show_lock=True, ajoute un cadenas 🔒 en bas à gauche.
    Pour is_main=True, accent_color = couleur du contour externe (event: listening=vert, etc.) ; l'espacement noir est conservé.
    ring_offset_px (main only): décalage radial de l'anneau de statut en px affichage, bipolaire [-9, +9]
    (négatif = rayon plus petit, positif = plus grand), piloté par le mètre PCM (TTS ou micro)."""
    if not HAS_PIL: return None
    scale = 2
    S_base = size * scale

    if is_main:
        ring_offset_px = max(-9, min(9, int(ring_offset_px)))
        ring_max_pos = 9
        pad_scaled = ring_max_pos * scale
        S_canvas = S_base + 2 * pad_scaled
        o = pad_scaled
        e = ring_offset_px * scale
        img = Image.new("RGBA", (S_canvas, S_canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        outer_ring_color = (accent_color if accent_color else "#D1D5DB")
        draw.ellipse((4 + o - e, 4 + o - e, (S_base - 6) + o + e, (S_base - 6) + o + e), fill="#1F1F23", outline=outer_ring_color, width=16)
        draw.ellipse((28 + o, 28 + o, (S_base - 30) + o, (S_base - 30) + o), fill="#FFFFFF", outline="#111827", width=8)
        img_bbox = (36 + o, 36 + o, (S_base - 38) + o, (S_base - 38) + o)
    else:
        S = S_base
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((16, 16, S-18, S-18), fill="#1F1F23", outline="#3F3F46", width=4)
        img_bbox = (20, 20, S-22, S-22)

    if img_path and os.path.exists(img_path):
        try:
            profile = Image.open(img_path).convert("RGBA")
            w = img_bbox[2] - img_bbox[0]
            profile = profile.resize((w, w), Image.LANCZOS)
            mask = Image.new("L", (w, w), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, w, w), fill=255)
            img.paste(profile, (img_bbox[0], img_bbox[1]), mask)
        except Exception:
            pass

    # Contour 5px pour le skin sélectionné : même couleur que la bague de la photo de profil (statut)
    if not is_main and border_color and border_color != "#52525B":
        draw.ellipse(img_bbox, outline=border_color, width=5 * scale)

    if show_lock:
        # Pastille cadenas : même taille qu'avant (size/4) ; seule l'icône 🔒 est agrandie dans ce carré
        pad = 6
        lw_raw = max(28, size // 4)
        lh_raw = max(28, size // 4)
        lw_raw, lh_raw = lw_raw - 1, lh_raw - 1
        left = (pad + 16 - 7) * scale
        top = (size - pad - lh_raw - 16) * scale
        lw, lh = lw_raw * scale, lh_raw * scale
        draw.rounded_rectangle((left, top, left + lw, top + lh), radius=8, fill=(0, 0, 0, 200), outline=(255, 255, 255, 180), width=2)
        try:
            # Icône cadenas plus grande dans le même carré : utiliser presque toute la hauteur de la pastille
            fnt_size = max(18, (lh_raw * 10) // 11)
            fnt = ImageFont.truetype("seguiemj.ttf", fnt_size)
        except Exception:
            fnt = ImageFont.load_default()
        # Centrer l'icône 🔒 dans la pastille
        bbox = draw.textbbox((0, 0), "🔒", font=fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = int(left + (lw - tw) / 2)
        ty = int(top + (lh - th) / 2)
        draw.text((tx, ty), "🔒", font=fnt, embedded_color=True)

    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def create_lang_flag_circle(size, border_color, img_path=None):
    """Drapeau circulaire (page Utilisateur). Anneau de sélection doré **à l'extérieur** du disque du drapeau, pas sur le bord intérieur."""
    if not HAS_PIL:
        return None
    scale = 2
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse((16, 16, S - 18, S - 18), fill="#1F1F23", outline="#3F3F46", width=4)
    img_bbox = (20, 20, S - 22, S - 22)

    if img_path and os.path.exists(img_path):
        try:
            profile = Image.open(img_path).convert("RGBA")
            w = img_bbox[2] - img_bbox[0]
            profile = profile.resize((w, w), Image.LANCZOS)
            mask = Image.new("L", (w, w), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, w, w), fill=255)
            img.paste(profile, (img_bbox[0], img_bbox[1]), mask)
        except Exception:
            pass

    # Anneau extérieur : ellipse plus grande que le disque du drapeau (pas de contour sur img_bbox).
    # Trait plus fin que les skins (~moitié de 5*scale) pour la petite taille des drapeaux.
    if border_color and border_color != "#52525B":
        x0, y0, x1, y1 = img_bbox
        ring_w = max(2, int(2.5 * scale))
        pad = max(int(3 * scale), int(ring_w // 2) + 2 * scale)
        outer = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        draw.ellipse(outer, outline=border_color, width=ring_w)

    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))

# ─── Handler de Logs ──────────────────────────────────────────

class QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter('%(message)s'))
    def emit(self, rec):
        try: self.q.put(self.format(rec))
        except: pass

# ══════════════════════════════════════════════════════════
#  CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════

class PerkySueWidget:

    def __init__(self, orchestrator=None):
        self.orch = orchestrator
        self.paths = orchestrator.paths if orchestrator else Paths()
        self.cfg = self._load_cfg()
        load_strings(self._strings_locale_from_cfg(self.cfg))
        self.log_q = queue.Queue()
        self._log_lines = []
        self._setup_log()

        self._page = None
        # Tips rotation (header notifications) — loaded from YAML, cached
        self._header_tips_config = None
        self._header_alerts_config = None
        self._tips_shown = set()
        self._tip_timer_id = None
        self._tip_restore_id = None
        self._tip_active = False
        self._last_alert_time = 0.0
        self._thinking_dot_timers: dict = {"chat": {}, "help": {}}
        # Alt+Q / Échap : un seul after(0) à la fois pour éviter saturation GUI si rafales sur stop.
        self._escape_stop_coalesce_id = None

        ctk.set_appearance_mode("dark")
        self.root = CTk()
        self.root.title(self._default_window_title())
        self.root.geometry("820x950")
        self.root.minsize(780, 800)
        self.root.configure(fg_color=BG)

        self._build_header()
        self._build_body()
        self._build_footer()

        # Auto-check updates once per session (public GitHub releases).
        self._update_auto_checked = False
        try:
            self.root.after(2500, self._maybe_auto_check_updates)
        except Exception:
            pass
        self._poll_logs()
        self._last_license_sync_time = None
        self._license_focus_after_id = None
        self._go("settings")
        # Alerte micro si l'orchestrateur a détecté un micro virtuel par défaut (ex. Iriun)
        try:
            if getattr(self.orch, "mic_warning", None):
                self._show_header_alert("Check your Windows microphone")
                # Notif + boîte de dialogue critique dès le démarrage
                self._notify(self.orch.mic_warning, restore_after_ms=8000)
                try:
                    self._show_critical_mic_dialog(self.orch.mic_warning)
                except Exception:
                    pass
                if getattr(self.orch, "mic_warning_open_settings", False):
                    import os, sys
                    if sys.platform.startswith("win"):
                        # Ouvrir les paramètres Son pour aider l'utilisateur à changer de micro.
                        try:
                            self.root.after(1500, lambda: os.startfile("ms-settings:sound"))
                        except Exception:
                            pass
        except Exception:
            pass

        # Alerte "No LLM" au démarrage (blink) si aucun modèle GGUF n'est disponible.
        # Règle UI: notification importante = blink 3× puis 4s.
        try:
            llm_ok = bool(getattr(self.orch, "llm", None) and self.orch.llm.is_available())
        except Exception:
            llm_ok = False
        if not llm_ok:
            msg = self._get_alert("critical.no_llm")
            delay = 2500 if getattr(self.orch, "mic_warning", None) else 500
            try:
                self.root.after(delay, lambda: self._notify(msg, restore_after_ms=4000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
            except Exception:
                pass

        # Planifier les tips de démarrage (alt+T puis rotation), seulement quand tout est stable.
        try:
            self._schedule_tip_cycle(initial=True)
        except Exception:
            pass

        # First-run: télécharger le GGUF par défaut (installer_default_models.yaml) si dossier LLM vide
        self._first_run_llm_download_active = False
        self._first_run_llm_entry = None
        try:
            self.root.after(4500, self._first_run_maybe_download_default_llm)
        except Exception:
            pass

        # Checkout web : GET /check au retour sur la fenêtre (navigateur → app) ; l’onglet Paramètres déclenche aussi /check.
        try:
            self._bind_license_sync_on_focus()
        except Exception:
            pass

    def _reset_license_sync_cooldown(self):
        """Next passive sync (focus / Settings) may run immediately; use after explicit commerce / verify actions."""
        self._last_license_sync_time = None

    def _request_license_remote_sync(self, ignore_cooldown: bool = False):
        """GET /check → license.json, puis rafraîchit plan / bannière / e-mail facturation."""
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "refresh_license_from_remote"):
            return
        min_gap = float(getattr(self, "_LICENSE_REMOTE_SYNC_MIN_GAP_SEC", 15 * 60))
        if not ignore_cooldown and self._last_license_sync_time is not None:
            if (time.monotonic() - self._last_license_sync_time) < min_gap:
                return
        # Forced sync (Stripe / wizards) must not start a 15 min passive throttle window, or return-from-browser
        # FocusIn would be blocked until the user restarts. Passive syncs record the throttle timestamp only.
        if ignore_cooldown:
            self._last_license_sync_time = None
        else:
            self._last_license_sync_time = time.monotonic()

        def _run():
            try:
                orch.refresh_license_from_remote()
            except Exception:
                pass

            def _ui():
                try:
                    if hasattr(self, "_refresh_plan_cards"):
                        self._refresh_plan_cards()
                except Exception:
                    pass
                try:
                    # Plan change should also unlock/lock shortcut editing immediately if user is on that page.
                    if hasattr(self, "_refresh_shortcuts_plan_restrictions"):
                        self._refresh_shortcuts_plan_restrictions()
                except Exception:
                    pass
                try:
                    # Keep Prompt Modes actions consistent with current tier after /check.
                    if hasattr(self, "_refresh_prompt_modes_plan_restrictions"):
                        self._refresh_prompt_modes_plan_restrictions()
                except Exception:
                    pass
                try:
                    self._refresh_header_banner_if_idle()
                except Exception:
                    pass
                try:
                    self._refresh_user_billing_email_display()
                except Exception:
                    pass

            try:
                self.root.after(0, _ui)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _bind_license_sync_on_focus(self):
        """FocusIn relance GET /check avec cooldown long (réduit la charge Worker); après Stripe, le cooldown est réinitialisé."""

        def _debounced_focus(_evt=None):
            jid = getattr(self, "_license_focus_after_id", None)
            if jid is not None:
                try:
                    self.root.after_cancel(jid)
                except Exception:
                    pass
            self._license_focus_after_id = self.root.after(450, _do)

        def _do():
            self._license_focus_after_id = None
            try:
                self._request_license_remote_sync(ignore_cooldown=False)
            except Exception:
                pass

        try:
            self.root.bind("<FocusIn>", _debounced_focus, add=True)
        except Exception:
            pass

    def _load_cfg(self):
        p = self.paths.user_config_file
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _effective_skin(self):
        """Skin réel : id canonique ``Character/Locale`` ; dossier absent → Default (persisté)."""
        raw = (self.cfg.get("skin") or {}).get("active", "Default")
        if not raw or raw == "Default":
            return "Default"
        nid = normalize_skin_id(self.paths, raw)
        if not skin_folder_exists(nid, self.paths):
            self._save_config({"skin": {"active": "Default"}})
            self.cfg = self._load_cfg()
            if getattr(self, "orch", None) and getattr(self.orch, "sound_manager", None) and self.orch.sound_manager:
                self.orch.sound_manager.set_skin("Default")
            tm = getattr(getattr(self, "orch", None), "tts_manager", None)
            if tm:
                tm.on_skin_changed("Default")
            orch = getattr(self, "orch", None)
            if orch and isinstance(getattr(orch, "config", None), dict):
                orch.config.setdefault("skin", {})["active"] = "Default"
            return "Default"
        if nid != raw:
            self._save_config({"skin": {"active": nid}})
            self.cfg = self._load_cfg()
            orch = getattr(self, "orch", None)
            if orch and isinstance(getattr(orch, "config", None), dict):
                orch.config.setdefault("skin", {})["active"] = nid
        return nid

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Recursively merge override into base. Override wins."""
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _strings_locale_from_cfg(self, cfg=None) -> str:
        """YAML locale id for load_strings (e.g. us, gb, fr, ja)."""
        cfg = cfg or getattr(self, "cfg", None) or {}
        return ((cfg.get("ui") or {}).get("language") or "us").strip().lower() or "us"

    def _recommended_model_comment(self, m: dict) -> str:
        """
        One-liner for Settings → Recommended Models tooltip from recommended_models.yaml.
        Uses comment_<locale> matching ui.language (16 UI locales). Fallback: active → US → GB → legacy comment.
        """
        if not isinstance(m, dict):
            return ""
        loc = self._strings_locale_from_cfg()
        key_for_ui = {
            "us": "comment_us",
            "gb": "comment_gb",
            "fr": "comment_fr",
            "de": "comment_de",
            "es": "comment_es",
            "it": "comment_it",
            "pt": "comment_pt",
            "nl": "comment_nl",
            "ja": "comment_ja",
            "ko": "comment_ko",
            "zh": "comment_zh",
            "hi": "comment_hi",
            "ru": "comment_ru",
            "id": "comment_id",
            "ar": "comment_ar",
            "bn": "comment_bn",
        }.get(loc, "comment_us")
        for key in (key_for_ui, "comment_us", "comment_gb", "comment"):
            v = m.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    def _default_window_title(self) -> str:
        return s("common.window_title", default="PerkySue — Beta 0.29.4")

    def _ui_flag_stem(self) -> str:
        """Which lang-flags/*.png is selected."""
        ui = (getattr(self, "cfg", None) or {}).get("ui") or {}
        lang = (ui.get("language") or "us").strip().lower()
        return {
            "us": "us",
            "gb": "uk",
            "fr": "fr",
            "de": "de",
            "es": "es",
            "it": "it",
            "pt": "pt",
            "nl": "nl",
            "ja": "jp",
            "ko": "ko",
            "zh": "cn",
            "hi": "in",
            "ru": "ru",
            "id": "id",
            "bn": "bd",
            "ar": "sa",
        }.get(lang, "us")

    def _apply_language_from_flag_stem(self, stem: str):
        pair = FLAG_STEM_TO_LANG.get(stem)
        if not pair:
            return
        lang, _variant = pair
        self._save_config({"ui": {"language": lang}})

    def _compute_header_banner_text(self) -> str:
        """Purple header line from tier + trial state (common.header_banner.*)."""
        key, kw = ("common.header_banner.free_invite", {})
        orch = getattr(self, "orch", None)
        if orch is not None and hasattr(orch, "get_header_banner_spec"):
            try:
                key, kw = orch.get_header_banner_spec()
            except Exception:
                key, kw = ("common.header_banner.free_invite", {})
        raw = s(key, default="PerkySue Beta — Free · Try Pro (30 days, no card)")
        if kw:
            try:
                return raw.format(**kw)
            except (KeyError, ValueError, TypeError):
                return raw
        return raw

    def _refresh_header_banner_if_idle(self):
        """Recompute banner line after tier/trial changes; skip if a tip, notify, or mic alert owns the header."""
        self._hdr_normal_text = self._compute_header_banner_text()
        if getattr(self, "_tip_active", False):
            return
        if getattr(self, "_notify_restore_id", None):
            return
        if getattr(self, "_hdr_alert_x_id", None):
            return
        try:
            self._set_header_title_text(self._hdr_normal_text)
        except (tk.TclError, AttributeError):
            pass

    def _apply_header_i18n(self):
        """After load_strings: banner text + Patreon canvas buttons."""
        self._hdr_normal_text = self._compute_header_banner_text()
        pat_txt = s("about.support_patreon_label")
        if HAS_PIL:
            self.btn_normal = create_canvas_btn(pat_txt, 220, 42, 8, "#E11D48", "#9F1239", "#4C0519")
            self.btn_hover = create_canvas_btn(pat_txt, 220, 42, 8, "#F43F5E", "#BE123C", "#4C0519")
            try:
                if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                    self.hdr.itemconfig(self.patreon_btn, image=self.btn_normal)
            except (tk.TclError, AttributeError):
                pass
        try:
            self._set_header_title_text(self._hdr_normal_text)
        except (tk.TclError, AttributeError):
            pass

    def _rebuild_ui_after_language_change(self):
        """Reload strings, rebuild body+footer, restore page and status. Brief flash is OK."""
        prev_page = getattr(self, "_page", None) or "settings"
        nav_ids = _build_nav_page_ids(getattr(self, "orch", None))
        if prev_page not in nav_ids:
            prev_page = "settings"
        prev_status = getattr(self, "_status_id", "ready")
        prev_chat_ind = getattr(self, "_chat_needs_reset_indicator", False)
        prev_help_ind = getattr(self, "_help_needs_reset_indicator", False)

        for attr in ("_tip_timer_id", "_tip_restore_id", "_notify_restore_id"):
            tid = getattr(self, attr, None)
            if tid:
                try:
                    self.root.after_cancel(tid)
                except (tk.TclError, AttributeError):
                    pass
                setattr(self, attr, None)
        self._tip_active = False
        self._notify_patreon_hidden = False

        self.cfg = self._load_cfg()
        load_strings(self._strings_locale_from_cfg(self.cfg))
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "_sync_strings_locale_from_config"):
                self.orch._sync_strings_locale_from_config()
        except Exception:
            pass
        self._header_tips_config = None
        self._header_alerts_config = None

        self._apply_header_i18n()

        try:
            if getattr(self, "_body_frame", None):
                self._body_frame.destroy()
            if getattr(self, "_footer_frame", None):
                self._footer_frame.destroy()
        except (tk.TclError, AttributeError):
            pass

        self._page = None
        self._build_body()
        self._build_footer()

        self._chat_needs_reset_indicator = prev_chat_ind
        self._help_needs_reset_indicator = prev_help_ind
        self._cached_greeting_chat = None
        self._cached_greeting_key_chat = None
        self._cached_greeting_help = None
        self._cached_greeting_key_help = None

        self.set_status(prev_status)
        self._go(prev_page)
        try:
            self._schedule_tip_cycle(initial=False)
        except Exception:
            pass

    def _on_user_flag_click(self, stem: str):
        self._apply_language_from_flag_stem(stem)
        self._rebuild_ui_after_language_change()

    def _save_config(self, updates: dict):
        """Write updates into Data/Configs/config.yaml (merge with existing)."""
        p = self.paths.user_config_file
        p.parent.mkdir(parents=True, exist_ok=True)
        current = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    current = yaml.safe_load(f) or {}
            except Exception:
                pass
        merged = self._deep_merge(current, updates)
        # Keep only clear LLM keys in the file (max_input_tokens, max_output_tokens); drop n_ctx, max_tokens
        if "llm" in merged and isinstance(merged["llm"], dict):
            merged["llm"].pop("n_ctx", None)
            merged["llm"].pop("max_tokens", None)
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _on_avatar_click(self, event=None):
        """Clic sur l'avatar : arrêt enregistrement (listening) ou interruption du traitement (processing). Inactif en Ready."""
        if not getattr(self, "orch", None):
            return
        status = getattr(self, "_status_id", None)
        # Continuous Chat must be stoppable from avatar at any time (even when status is temporarily "ready").
        try:
            if getattr(self.orch, "is_continuous_chat_enabled", None) and self.orch.is_continuous_chat_enabled():
                self.orch.set_continuous_chat_enabled(False)
                self._notify(s("chat.continuous_stopped", default="Continuous Chat stopped."), restore_after_ms=2500)
                self.set_status("ready")
                return
        except Exception:
            pass
        # Stop TTS when avatar is clicked during speaking/loading states.
        try:
            tm = getattr(self.orch, "tts_manager", None)
            if tm and (status == "tts_loading" or status == "speaking" or tm.is_speaking()):
                self.orch.stop_voice_output()
                self._notify(self._get_alert("regular.tts_stopped"), restore_after_ms=3000)
                self.set_status("ready")
                return
        except Exception:
            pass
        # En Ready et pas en train d'écouter/traiter : ne rien faire (bouton inactif)
        if status == "ready":
            return
        if getattr(self.orch, "recorder", None) and self.orch.recorder.is_recording:
            self.orch.stop_recording()
            self._notify(self._get_alert("regular.recording_stopped"), restore_after_ms=3000)
            self.set_status("ready")
            return
        # Defensive fallback for rare state desyncs: UI says listening but recorder flag already dropped.
        if status == "listening" or bool(getattr(self.orch, "_is_recording", False)):
            self.orch.stop_recording()
            self._notify(self._get_alert("regular.recording_stopped"), restore_after_ms=3000)
            self.set_status("ready")
            return
        if getattr(self, "_status_id", None) in ("processing", "generating"):
            self.orch.request_cancel()
            self._notify(self._get_alert("regular.processing_stopped"), restore_after_ms=3000)
            self.set_status("ready")

    def _on_save_restart(self):
        """Sauvegarde la config puis relance l’app (sans alerte)."""
        updates = self._collect_settings_updates()
        if not updates:
            return
        try:
            cur_keep = int(((self.cfg.get("llm") or {}).get("answer_context_keep", 2)) or 2)
        except (TypeError, ValueError):
            cur_keep = 2
        try:
            new_keep = int((((updates.get("llm") or {}).get("answer_context_keep", 2)) or 2))
        except (TypeError, ValueError):
            new_keep = 2
        if cur_keep not in (2, 3, 4):
            cur_keep = 2
        if new_keep not in (2, 3, 4):
            new_keep = 2
        if new_keep != cur_keep:
            logging.getLogger("perkysue").info(
                "Settings: Ask keep-last exchanges changed %d -> %d (save & restart).",
                cur_keep,
                new_keep,
            )
        stt_device = ((updates.get("stt") or {}).get("device") or "auto")
        self._save_config(updates)
        self.cfg = self._load_cfg()
        self._refresh_models_grid()
        app_root = Path(__file__).resolve().parent.parent.parent
        main_py = app_root / "App" / "main.py"
        python_exe = app_root / "Python" / "python.exe"
        if not python_exe.exists():
            python_exe = sys.executable
        try:
            self.root.destroy()
        except Exception:
            pass
        import subprocess
        # Passage a STT GPU (NVIDIA) : lancer install.bat pour installer les paquets CUDA STT
        if stt_device == "cuda" and getattr(self, "_is_nvidia_stt", False):
            install_bat = app_root / "install.bat"
            if install_bat.exists():
                subprocess.Popen(["cmd", "/c", str(install_bat)], cwd=str(app_root), shell=False)
                sys.exit(0)
        subprocess.Popen([str(python_exe), str(main_py)], cwd=str(app_root))
        sys.exit(0)

    def _perf_mic_build_option_data(
        self, audio_cfg: dict
    ) -> tuple[list[str], dict[str, Optional[int]], str]:
        """Entrées micro pour Paramètres : (libellés menu, map libellé -> index sounddevice, libellé courant cfg)."""
        _mic_default_lbl = s("settings.performance.mic_windows_default", default="Windows default microphone")
        label_to_index: dict[str, Optional[int]] = {_mic_default_lbl: None}
        mic_sel_opts = [_mic_default_lbl]
        try:
            for dev in BaseAudioCapture.list_devices():
                try:
                    did = int(dev.get("id", -1))
                except (TypeError, ValueError):
                    continue
                if did < 0:
                    continue
                nm = str(dev.get("name") or "?").replace("\n", " ").strip()
                if len(nm) > 72:
                    nm = nm[:69] + "…"
                dfl = " (default)" if dev.get("is_default") else ""
                # ASCII seulement dans le libellé (CTkOptionMenu / encodages Windows).
                row_lbl = f"#{did} - {nm}{dfl}"
                label_to_index[row_lbl] = did
                mic_sel_opts.append(row_lbl)
        except Exception as e:
            logging.getLogger("perkysue").warning("Could not enumerate microphones for Settings: %s", e, exc_info=True)

        mic_cfg_raw = (audio_cfg or {}).get("mic_device")
        mic_ix: Optional[int] = None
        if mic_cfg_raw is not None and str(mic_cfg_raw).strip().lower() not in ("", "null", "none"):
            try:
                mic_ix = int(float(mic_cfg_raw))
            except (TypeError, ValueError):
                mic_ix = None
        mic_cur_lbl = _mic_default_lbl
        if mic_ix is not None:
            found_lbl = None
            for _k, _v in label_to_index.items():
                if _v == mic_ix:
                    found_lbl = _k
                    break
            if found_lbl is not None:
                mic_cur_lbl = found_lbl
            else:
                orphan = f"#{mic_ix} - ({s('settings.performance.mic_orphan', default='not in current list')})"
                label_to_index[orphan] = mic_ix
                mic_sel_opts.append(orphan)
                mic_cur_lbl = orphan
        return mic_sel_opts, label_to_index, mic_cur_lbl

    def _refresh_perf_mic_device_menu(self) -> None:
        """Re-remplit le menu micro après que Tk / PortAudio soient prêts (corrige liste vide au premier build)."""
        om = getattr(self, "_perf_mic_device_om", None)
        var = getattr(self, "_perf_mic_device", None)
        if om is None or var is None:
            return
        try:
            audio_cfg = (getattr(self, "cfg", None) or {}).get("audio") or {}
            opts, label_map, preferred = self._perf_mic_build_option_data(audio_cfg)
            self._perf_mic_label_to_device_index = label_map
            cur = (var.get() or "").strip()
            if cur not in opts:
                var.set(preferred if preferred in opts else opts[0])
            om.configure(values=opts)
        except Exception as e:
            logging.getLogger("perkysue").warning("Mic menu refresh failed: %s", e, exc_info=True)

    def _collect_settings_updates(self):
        """Collect normalized Settings payload for config persistence."""
        if not getattr(self, "_perf_stt", None):
            return None
        stt_model = self._perf_stt.get().strip().lower()
        stt_device_raw = getattr(self, "_perf_stt_device", None) and self._perf_stt_device.get() or "Auto"
        stt_device = "cuda" if stt_device_raw == "GPU" else ("cpu" if stt_device_raw == "CPU" else "auto")
        llm_model = self._perf_llm.get().strip()
        if not llm_model or llm_model == s("settings.performance.no_gguf"):
            llm_model = ""
        _mt_raw = (self._perf_max_tokens.get() or "").strip()
        if _mt_raw.lower() == "auto":
            max_tok = 0
        else:
            try:
                max_tok = int(_mt_raw)
            except (ValueError, TypeError):
                max_tok = 2048
        _pv = getattr(self, "_perf_llm_request_timeout", None)
        try:
            req_timeout = int(_pv.get()) if _pv else 180
        except (ValueError, TypeError, AttributeError):
            req_timeout = 180
        req_timeout = max(120, min(req_timeout, 360))
        _ack_var = getattr(self, "_perf_answer_context_keep", None)
        try:
            answer_context_keep = int(_ack_var.get()) if _ack_var else 2
        except (ValueError, TypeError, AttributeError):
            answer_context_keep = 2
        if answer_context_keep not in (2, 3, 4):
            answer_context_keep = 2
        _iamc_var = getattr(self, "_perf_inject_all_modes_chat", None)
        inject_all_modes_in_chat = True if _iamc_var is None else bool(_iamc_var.get() == "On")
        max_in = self._perf_max_input.get().strip()
        n_ctx = 0 if max_in == "Auto" else (int(max_in) if max_in.isdigit() else 0)
        try:
            sil_timeout = float(self._perf_silence_timeout.get())
        except (ValueError, TypeError, AttributeError):
            sil_timeout = 3.0
        try:
            max_duration = float(self._perf_max_duration.get())
        except (ValueError, TypeError, AttributeError):
            max_duration = 120.0
        _cap_var = getattr(self, "_perf_capture_mode", None)
        if _cap_var and getattr(self, "_perf_capture_display_to_cfg", None):
            capture_mode = self._perf_capture_display_to_cfg.get(_cap_var.get(), "mic_only")
        else:
            capture_mode = "mic_only"
        if capture_mode not in ("mic_only", "system_only", "mix"):
            capture_mode = "mic_only"
        try:
            _is_pro = bool(self.orch.is_effective_pro()) if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro") else False
        except Exception:
            _is_pro = False
        if not _is_pro:
            capture_mode = "mic_only"
        first_lang_raw = getattr(self, "_perf_first_language", None) and self._perf_first_language.get() or "Auto"
        first_lang = first_lang_raw.strip().lower() if first_lang_raw else "auto"
        if first_lang == "auto":
            first_lang = "auto"
        else:
            first_lang = first_lang[:2] if len(first_lang) >= 2 else "auto"
        ident = dict(self.cfg.get("identity") or {})
        ident["first_language"] = first_lang
        think_on = getattr(self, "_perf_thinking", None) and self._perf_thinking.get() == "On"
        _tb_raw = (getattr(self, "_perf_thinking_budget", None) and self._perf_thinking_budget.get()) or "512"
        if str(_tb_raw).strip() == "Unlimited":
            thinking_budget = -1
        else:
            try:
                thinking_budget = int(_tb_raw)
            except (TypeError, ValueError):
                thinking_budget = 512
        inj_prev = dict(self.cfg.get("injection") or {})
        _cbd_om = getattr(self, "_perf_clipboard_paste_delay", None)
        try:
            clip_delay = int(_cbd_om.get()) if _cbd_om else int(inj_prev.get("clipboard_restore_delay_sec", 5))
        except (TypeError, ValueError, AttributeError):
            clip_delay = 10
        clip_delay = max(0, min(clip_delay, 60))
        inj_prev["clipboard_restore_delay_sec"] = clip_delay
        mic_dev_cfg = None
        _mic_map = getattr(self, "_perf_mic_label_to_device_index", None)
        _mic_var = getattr(self, "_perf_mic_device", None)
        if _mic_map is not None and _mic_var is not None:
            _lbl = (_mic_var.get() or "").strip()
            if _lbl in _mic_map:
                mic_dev_cfg = _mic_map[_lbl]
            elif _lbl.startswith("#"):
                import re as _re_mic

                _m = _re_mic.match(r"#\s*(\d+)", _lbl)
                if _m:
                    try:
                        mic_dev_cfg = int(_m.group(1))
                    except ValueError:
                        mic_dev_cfg = None
        _vad_var = getattr(self, "_perf_vad_sensitivity", None)
        _vad_d2c = getattr(self, "_perf_vad_display_to_cfg", None)
        if _vad_var is not None and _vad_d2c:
            vad_sensitivity = _vad_d2c.get((_vad_var.get() or "").strip(), "normal")
        else:
            vad_sensitivity = "normal"
        if vad_sensitivity not in ("quiet_room", "normal", "noisy"):
            vad_sensitivity = "normal"
        out = {
            "stt": {"model": stt_model, "device": stt_device},
            "llm": {
                "model": llm_model,
                "max_input_tokens": n_ctx,
                "max_output_tokens": max_tok,
                "request_timeout": req_timeout,
                "thinking": "on" if think_on else "off",
                "thinking_budget": thinking_budget,
                "answer_context_keep": answer_context_keep,
                "inject_all_modes_in_chat": inject_all_modes_in_chat,
            },
            "audio": {
                "silence_timeout": sil_timeout,
                "max_duration": max_duration,
                "capture_mode": capture_mode,
                "mic_device": mic_dev_cfg,
                "vad_sensitivity": vad_sensitivity,
            },
            "identity": ident,
            "injection": inj_prev,
        }
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if tts is not None:
            out["tts"] = tts.to_config_dict()
        fb = dict((self.cfg.get("feedback") or {}))
        dbg_var = getattr(self, "_feedback_debug_mode_var", None)
        if dbg_var is not None:
            fb["debug_mode"] = dbg_var.get() == "On"
        out["feedback"] = fb
        return out

    def _settings_change_flags(self, updates: dict) -> Optional[dict]:
        """Compare les réglages Performance du formulaire à ``self.cfg``. Retourne None si ``updates`` invalide."""
        if not isinstance(updates, dict):
            return None
        cur_stt = self.cfg.get("stt") or {}
        cur_audio = self.cfg.get("audio") or {}
        cur_ident = self.cfg.get("identity") or {}
        cur_llm = self.cfg.get("llm") or {}
        new_stt = updates.get("stt") or {}
        new_audio = updates.get("audio") or {}
        new_ident = updates.get("identity") or {}
        new_llm = updates.get("llm") or {}
        stt_changed = (
            str(cur_stt.get("model", "")).strip().lower() != str(new_stt.get("model", "")).strip().lower()
            or str(cur_stt.get("device", "auto")).strip().lower() != str(new_stt.get("device", "auto")).strip().lower()
        )
        def _norm_audio_mic_index(v) -> Optional[int]:
            if v is None or isinstance(v, bool):
                return None
            s = str(v).strip().lower()
            if s in ("", "null", "none"):
                return None
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None

        def _canon_vad_sensitivity(ad: dict) -> str:
            vs = ad.get("vad_sensitivity")
            if isinstance(vs, str):
                k = vs.strip().lower()
                if k in ("quiet_room", "normal", "noisy"):
                    return k
            va = ad.get("vad_aggressiveness")
            if va is not None and not isinstance(va, bool):
                try:
                    av = max(0, min(3, int(float(va))))
                except (TypeError, ValueError):
                    return "normal"
                return {0: "quiet_room", 1: "quiet_room", 2: "normal", 3: "noisy"}.get(av, "normal")
            return "normal"

        audio_changed = (
            float(cur_audio.get("silence_timeout", 3.0) or 3.0) != float(new_audio.get("silence_timeout", 3.0) or 3.0)
            or float(cur_audio.get("max_duration", 120.0) or 120.0) != float(new_audio.get("max_duration", 120.0) or 120.0)
            or str(cur_audio.get("capture_mode", "mic_only")).strip().lower()
            != str(new_audio.get("capture_mode", "mic_only")).strip().lower()
            or _norm_audio_mic_index(cur_audio.get("mic_device")) != _norm_audio_mic_index(new_audio.get("mic_device"))
            or _canon_vad_sensitivity(cur_audio) != _canon_vad_sensitivity(new_audio)
        )
        ident_changed = str(cur_ident.get("first_language", "auto")).strip().lower() != str(new_ident.get("first_language", "auto")).strip().lower()

        def _llm_max_out_token(llm: dict) -> int:
            v = llm.get("max_output_tokens")
            if v is None:
                v = llm.get("max_tokens")
            try:
                return int(v) if v is not None and str(v).strip() != "" else 0
            except (TypeError, ValueError):
                return 0

        def _llm_thinking_on(llm: dict) -> bool:
            t = str(llm.get("thinking", "off")).strip().lower()
            return t in ("on", "true", "1", "yes")

        def _llm_inject_all_modes_chat_on(llm: dict) -> bool:
            v = llm.get("inject_all_modes_in_chat", True)
            if isinstance(v, str):
                return v.strip().lower() in ("on", "true", "1", "yes")
            return bool(v)

        def _llm_thinking_budget(llm: dict) -> int:
            try:
                return int(llm.get("thinking_budget", 512))
            except (TypeError, ValueError):
                return 512

        llm_changed = (
            str(cur_llm.get("model", "")).strip() != str(new_llm.get("model", "")).strip()
            or int(cur_llm.get("max_input_tokens", cur_llm.get("n_ctx", 0)) or 0) != int(new_llm.get("max_input_tokens", 0) or 0)
            or _llm_max_out_token(cur_llm) != _llm_max_out_token(new_llm)
            or int(cur_llm.get("request_timeout", 120) or 120) != int(new_llm.get("request_timeout", 120) or 120)
            or int(cur_llm.get("answer_context_keep", 2) or 2) != int(new_llm.get("answer_context_keep", 2) or 2)
            or _llm_inject_all_modes_chat_on(cur_llm) != _llm_inject_all_modes_chat_on(new_llm)
            or _llm_thinking_on(cur_llm) != _llm_thinking_on(new_llm)
            or _llm_thinking_budget(cur_llm) != _llm_thinking_budget(new_llm)
        )
        cur_fb = self.cfg.get("feedback") or {}
        new_fb = updates.get("feedback") or {}
        feedback_changed = bool(cur_fb.get("debug_mode")) != bool(new_fb.get("debug_mode"))
        cur_inj = self.cfg.get("injection") or {}
        new_inj = updates.get("injection") or {}

        def _clip_delay_sec(d: dict) -> float:
            try:
                return float(d.get("clipboard_restore_delay_sec", 5))
            except (TypeError, ValueError):
                return 5.0

        injection_changed = _clip_delay_sec(cur_inj) != _clip_delay_sec(new_inj)
        return {
            "stt_changed": stt_changed,
            "audio_changed": audio_changed,
            "ident_changed": ident_changed,
            "llm_changed": llm_changed,
            "feedback_changed": feedback_changed,
            "injection_changed": injection_changed,
        }

    def _is_hot_reload_settings_change(self, updates: dict) -> bool:
        """True si seuls LLM et/ou audio (Performance) changent — bouton Update sans redémarrage."""
        flags = self._settings_change_flags(updates)
        if not flags:
            return False
        if (
            flags["stt_changed"]
            or flags["ident_changed"]
            or flags["injection_changed"]
            or flags["feedback_changed"]
        ):
            return False
        return bool(flags["llm_changed"] or flags["audio_changed"])

    def _on_apply_hot_reload(self):
        """Enregistre LLM et/ou audio, recharge runtime sans redémarrage complet."""
        updates = self._collect_settings_updates()
        if not updates:
            return
        try:
            cur_keep = int(((self.cfg.get("llm") or {}).get("answer_context_keep", 2)) or 2)
        except (TypeError, ValueError):
            cur_keep = 2
        try:
            new_keep = int((((updates.get("llm") or {}).get("answer_context_keep", 2)) or 2))
        except (TypeError, ValueError):
            new_keep = 2
        if cur_keep not in (2, 3, 4):
            cur_keep = 2
        if new_keep not in (2, 3, 4):
            new_keep = 2
        flags = self._settings_change_flags(updates)
        if not flags or not self._is_hot_reload_settings_change(updates):
            return
        patch: dict = {}
        if flags["llm_changed"]:
            patch["llm"] = dict((updates.get("llm") or {}))
            if isinstance(updates.get("feedback"), dict):
                patch["feedback"] = dict(updates["feedback"])
        if flags["audio_changed"]:
            patch["audio"] = dict((updates.get("audio") or {}))
        if not patch:
            return
        self._save_config(patch)
        if "llm" in patch:
            if "llm" not in self.cfg:
                self.cfg["llm"] = {}
            self.cfg["llm"].update(patch["llm"])
            if new_keep != cur_keep:
                logging.getLogger("perkysue").info(
                    "Settings: Ask keep-last exchanges changed %d -> %d (apply now).",
                    cur_keep,
                    new_keep,
                )
        if isinstance(patch.get("feedback"), dict):
            self.cfg.setdefault("feedback", {}).update(patch["feedback"])
            try:
                if getattr(self, "orch", None):
                    self.orch.config.setdefault("feedback", {}).update(patch["feedback"])
            except Exception:
                pass
        if "audio" in patch:
            self.cfg.setdefault("audio", {}).update(patch["audio"])

        ok_all = True
        msgs: list[str] = []
        orch = getattr(self, "orch", None)
        try:
            if flags["llm_changed"] and orch and hasattr(orch, "reload_llm_runtime"):
                ok, msg = orch.reload_llm_runtime()
                ok_all = ok_all and ok
                msgs.append(msg)
            if flags["audio_changed"] and orch and hasattr(orch, "reload_audio_capture"):
                ok, msg = orch.reload_audio_capture()
                ok_all = ok_all and ok
                msgs.append(msg)
        except Exception as e:
            ok_all = False
            msgs.append(str(e))
        if ok_all:
            try:
                self._refresh_console_pipeline_status()
            except Exception:
                pass
            self._notify(" · ".join(m for m in msgs if m), restore_after_ms=2500)
            try:
                self._save_frame.pack_forget()
            except Exception:
                pass
        else:
            self._notify(" · ".join(m for m in msgs if m), restore_after_ms=4500, blink_times=3, blink_on_ms=300, blink_off_ms=300)

    def _setup_log(self):
        h = QueueHandler(self.log_q)
        h.setLevel(logging.INFO)
        logging.getLogger("perkysue").addHandler(h)
        # Full Console only: full STT / LLM payloads when Settings → Advanced → debug_mode is on.
        # propagate=False so nothing reaches the root logger (Data/Logs/perkysue.log stays exchange-free).
        gui_log = logging.getLogger("perkysue.gui_console")
        gui_log.setLevel(logging.DEBUG)
        gui_log.propagate = False
        if not gui_log.handlers:
            gh = QueueHandler(self.log_q)
            gh.setLevel(logging.DEBUG)
            gui_log.addHandler(gh)
        self._old_out = sys.stdout
        sys.stdout = self

    def write(self, t):
        if t.strip(): self.log_q.put(t.strip())
        if hasattr(self, '_old_out'): self._old_out.write(t)

    def flush(self): pass

# ── HEADER ────────────────────────────────────────────────
    def _build_header(self):
        self.hdr = tk.Canvas(self.root, height=70, bg=BG, highlightthickness=0)
        self.hdr.pack(fill="x")
        
        self.grad_img = create_gradient_img(2500, 70, HEADER_L, HEADER_R)
        self.grad_img_alert = None  # créé à la demande (alerte rouge)
        self._hdr_bg_img_id = self.hdr.create_image(0, 0, image=self.grad_img, anchor="nw")
        
        # Titre (id stocké pour pouvoir le remplacer par l'alerte micro)
        self._hdr_normal_text = self._compute_header_banner_text()
        self._hdr_title_id = self.hdr.create_text(
            18, 33, text=self._hdr_normal_text,
            fill="white", font=("Segoe UI", 16, "bold"), anchor="w"
        )
        self._hdr_alert_x_id = None  # id du "×" de fermeture quand alerte affichée

        _patreon_btn_txt = s("about.support_patreon_label")
        self.btn_normal = create_canvas_btn(_patreon_btn_txt, 220, 42, 8, "#E11D48", "#9F1239", "#4C0519")
        self.btn_hover = create_canvas_btn(_patreon_btn_txt, 220, 42, 8, "#F43F5E", "#BE123C", "#4C0519")
        
        try:
            _pw = self.root.winfo_width()
        except Exception:
            _pw = 800
        if _pw < 100:
            _pw = 800
        # Comportement d’origine : anchor=e sur le bord droit, y=36 (aligné titre ~33)
        self.patreon_btn = self.hdr.create_image(max(0, _pw - 30), 36, image=self.btn_normal, anchor="e")
        self.hdr.tag_bind(self.patreon_btn, "<Enter>", lambda e: (self.hdr.itemconfig(self.patreon_btn, image=self.btn_hover), self.hdr.config(cursor="hand2")))
        self.hdr.tag_bind(self.patreon_btn, "<Leave>", lambda e: (self.hdr.itemconfig(self.patreon_btn, image=self.btn_normal), self.hdr.config(cursor="")))
        self.hdr.tag_bind(self.patreon_btn, "<Button-1>", lambda e: webbrowser.open("https://patreon.com/PerkySue"))
        
        self.root.bind("<Configure>", self._on_resize)

    def _show_header_alert(self, message: str = "Check Your Microphone"):
        """Affiche une alerte dans la bannière (ex. micro) avec une croix pour fermer. Même typo que le titre."""
        try:
            self.hdr.itemconfig(self._hdr_title_id, text=message)
            if self._hdr_alert_x_id is not None:
                try:
                    self.hdr.delete(self._hdr_alert_x_id)
                except tk.TclError:
                    pass
                self._hdr_alert_x_id = None
            # Petite croix à droite du message (même police, fermeture au clic)
            self._hdr_alert_x_id = self.hdr.create_text(
                320, 33, text=" ×",
                fill="white", font=("Segoe UI", 16, "bold"), anchor="w", tags=("dismiss_alert",)
            )
            self.hdr.tag_bind("dismiss_alert", "<Button-1>", lambda e: self._dismiss_header_alert())
            self.hdr.tag_bind("dismiss_alert", "<Enter>", lambda e: self.hdr.config(cursor="hand2"))
            self.hdr.tag_bind("dismiss_alert", "<Leave>", lambda e: self.hdr.config(cursor=""))
        except (tk.TclError, AttributeError):
            pass

    def _dismiss_header_alert(self):
        """Restaure le titre normal et supprime la croix."""
        try:
            self.hdr.itemconfig(self._hdr_title_id, text=self._hdr_normal_text)
            if self._hdr_alert_x_id is not None:
                self.hdr.delete(self._hdr_alert_x_id)
                self._hdr_alert_x_id = None
        except (tk.TclError, AttributeError):
            pass

    def _set_header_title_text(self, text: str):
        """Met à jour le texte du titre (même typo que le titre). Utilisé pour toutes les notifications (micro, téléchargement)."""
        try:
            self.hdr.itemconfig(self._hdr_title_id, text=text)
        except (tk.TclError, AttributeError):
            pass

    def _set_header_gradient_alert(self, alert: bool):
        """True = dégradé rouge (alerte), False = dégradé mauve normal."""
        if not HAS_PIL or not getattr(self, "hdr", None):
            return
        try:
            bid = getattr(self, "_hdr_bg_img_id", None)
            if bid is None:
                return
            if alert:
                if getattr(self, "grad_img_alert", None) is None:
                    self.grad_img_alert = create_gradient_img(2500, 70, HEADER_ALERT_L, HEADER_ALERT_R)
                self.hdr.itemconfig(bid, image=self.grad_img_alert)
            else:
                self.hdr.itemconfig(bid, image=self.grad_img)
        except (tk.TclError, AttributeError):
            pass

    def _notify(self, message: str, restore_after_ms: int = 3000, blink_times: int = 0, blink_on_ms: int = 500, blink_off_ms: int = 500, use_alert_gradient: bool = False):
        """Affiche un message dans le titre du header puis restaure le texte normal après restore_after_ms.
        Si blink_times > 0 : clignote (afficher blink_on_ms, masquer blink_off_ms) × blink_times, puis reste affiché restore_after_ms.
        use_alert_gradient : dégradé rouge dans la barre (alerte) puis retour au mauve à la fin."""
        # Les alertes écrasent immédiatement les tips : annuler le tip en cours et le prochain prévu.
        try:
            if getattr(self, "_tip_timer_id", None):
                try:
                    self.root.after_cancel(self._tip_timer_id)
                except (tk.TclError, AttributeError):
                    pass
                self._tip_timer_id = None
            if getattr(self, "_tip_restore_id", None):
                try:
                    self.root.after_cancel(self._tip_restore_id)
                except (tk.TclError, AttributeError):
                    pass
                self._tip_restore_id = None
            if getattr(self, "_tip_active", False):
                # Restore normal title and Patreon button if a tip was active.
                normal_text = getattr(self, "_hdr_normal_text", "PerkySue Beta")
                self._set_header_title_text(normal_text)
                if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                    try:
                        w = self.hdr.winfo_width()
                        self.hdr.coords(self.patreon_btn, max(0, w - 30), 36)
                    except Exception:
                        pass
                self._tip_active = False
        except Exception:
            self._tip_timer_id = None
            self._tip_restore_id = None
            self._tip_active = False

        # Restore Patreon button position when a new notify starts (in case a previous one left it off-screen).
        try:
            if getattr(self, "_notify_patreon_hidden", False):
                if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                    try:
                        w = self.hdr.winfo_width()
                        self.hdr.coords(self.patreon_btn, max(0, w - 30), 36)
                    except Exception:
                        pass
                self._notify_patreon_hidden = False
        except Exception:
            self._notify_patreon_hidden = False

        if getattr(self, "_notify_restore_id", None):
            try:
                self.root.after_cancel(self._notify_restore_id)
            except (tk.TclError, AttributeError):
                pass
            self._notify_restore_id = None
        # Boîte de dialogue critique pour les erreurs micro / device
        lower = message.lower()
        if any(kw in lower for kw in ["virtual microphone", "recording failed", "no audio captured", "too short — check your microphone", "input device"]):
            self._show_critical_mic_dialog(message)

        normal_text = getattr(self, "_hdr_normal_text", "PerkySue Beta")
        self._notify_use_alert_gradient = bool(use_alert_gradient)
        if use_alert_gradient:
            self._set_header_gradient_alert(True)
        # Marquer l'heure de la dernière notification (utile pour retarder les tips).
        try:
            self._last_alert_time = time.time()
        except Exception:
            self._last_alert_time = 0.0

        # Masquer le bouton Patreon (hors écran) pour laisser la place au message et éviter les collisions.
        try:
            if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                self.hdr.coords(self.patreon_btn, -1000, 36)
                self._notify_patreon_hidden = True
        except Exception:
            self._notify_patreon_hidden = False

        def _restore():
            try:
                if getattr(self, "_notify_patreon_hidden", False):
                    if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                        try:
                            w = self.hdr.winfo_width()
                            self.hdr.coords(self.patreon_btn, max(0, w - 30), 36)
                        except Exception:
                            pass
                    self._notify_patreon_hidden = False
            except Exception:
                self._notify_patreon_hidden = False
            self._set_header_title_text(normal_text)
            self._notify_restore_id = None
            if getattr(self, "_notify_use_alert_gradient", False):
                self._set_header_gradient_alert(False)
                self._notify_use_alert_gradient = False
            # Reprendre la rotation des tips après l’alerte.
            try:
                self._schedule_tip_cycle(initial=False)
            except Exception:
                pass

        if blink_times <= 0:
            self._set_header_title_text(message)
            self._notify_restore_id = self.root.after(restore_after_ms, _restore)
            return

        # Séquence blink : afficher (nouvelle notif), masquer (rien — pas l’ancien titre), × blink_times, puis afficher et rester restore_after_ms ; l’ancien titre ne revient qu’à la fin
        step = [0]

        def _blink_step():
            self._notify_restore_id = None
            if step[0] < blink_times * 2:
                if step[0] % 2 == 0:
                    self._set_header_title_text(message)
                    self._notify_restore_id = self.root.after(blink_on_ms, _blink_step)
                else:
                    self._set_header_title_text("")
                    self._notify_restore_id = self.root.after(blink_off_ms, _blink_step)
                step[0] += 1
            else:
                self._set_header_title_text(message)
                self._notify_restore_id = self.root.after(restore_after_ms, _restore)

        self._set_header_title_text(message)
        step[0] = 1
        self._notify_restore_id = self.root.after(blink_on_ms, _blink_step)

    def _notify_pro_locked(self):
        """Play LLM error sound and show a blinking Pro-required header alert."""
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "sound_manager"):
                self.orch.sound_manager.play_system_sound("llm_error")
        except Exception:
            pass
        msg = self._get_alert(
            "regular.pro_plan_required_mode",
            default="This mode is locked on Free — Pro plan required.",
        )
        self._notify(
            msg,
            restore_after_ms=4000,
            blink_times=3,
            blink_on_ms=300,
            blink_off_ms=300,
        )

    def _load_header_tips_config(self):
        """Tips: primary copy in App/configs/strings/<lang>.yaml (header_tips); optional Data/Configs/header_tips.yaml overrides."""
        default_startup = "Tip · Place your cursor in Word, Gmail, Slack… then press Alt+T."
        out = {
            "startup_message": default_startup,
            "tips": list(HEADER_TIPS_DEFAULT),
            "delay_before_first_ms": 5500,
            "display_ms": 5000,
            "delay_between_ms": 8000,
        }
        merged = merge_strings_at("header_tips")
        if isinstance(merged, dict):
            sm = merged.get("startup_message")
            if sm is not None and str(sm).strip():
                out["startup_message"] = str(sm).strip()
            tips = merged.get("tips")
            if isinstance(tips, list) and len(tips) > 0:
                out["tips"] = [str(t).strip() for t in tips if str(t).strip()]
            for tk in ("delay_before_first_ms", "display_ms", "delay_between_ms"):
                v = merged.get(tk)
                if isinstance(v, (int, float)):
                    out[tk] = max(0, int(v))
        paths = getattr(self, "orch", None) and getattr(self.orch, "paths", None)
        if not paths:
            return out
        for yaml_path in [paths._app / "configs" / "header_tips.yaml", paths.configs / "header_tips.yaml"]:
            if not yaml_path.exists():
                continue
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if data.get("startup_message") is not None:
                    out["startup_message"] = str(data["startup_message"]).strip() or default_startup
                if isinstance(data.get("tips"), list) and data["tips"]:
                    out["tips"] = [str(t).strip() for t in data["tips"] if str(t).strip()]
                if isinstance(data.get("delay_before_first_ms"), (int, float)):
                    out["delay_before_first_ms"] = max(0, int(data["delay_before_first_ms"]))
                if isinstance(data.get("display_ms"), (int, float)):
                    out["display_ms"] = max(0, int(data["display_ms"]))
                if isinstance(data.get("delay_between_ms"), (int, float)):
                    out["delay_between_ms"] = max(0, int(data["delay_between_ms"]))
            except Exception:
                pass
        return out

    def _load_header_alerts_config(self):
        """Alerts: primary copy in App/configs/strings/<lang>.yaml (header_alerts); optional Data/Configs/header_alerts.yaml overrides."""
        defaults = {
            "critical": {
                "no_llm": "No LLM detected. Download one in Settings.",
                "save_restart": "You need to Save & Restart PerkySue",
                "shortcut_in_use": "This shortcut is already in use ({other_name}). Choose another.",
                "llm_error_400": "LLM error (400) — context too large? Increase Max input in Settings.",
                "llm_error_generic": "LLM error — check console. Increase Max input (context) in Settings if using Alt+A.",
                "max_input_reached": "Max input token limit reached — history was reduced.",
                "max_input_context_reached": "Max input (context) limit ({max_input}) reached. Try increasing to {suggested} in Settings → Performance.",
                "max_output_tokens_reached": "Max output limit ({max_output}) reached. Increase to {suggested} in Settings → Performance.",
                "llm_request_timeout": "LLM request timed out — in Settings → Performance raise LLM request timeout (e.g. 240–360s) for long prompts or slow CPU; ensure GPU llama-server if you have an NVIDIA card.",
            },
            "regular": {
                "recording_stopped": "🛑 Recording stopped",
                "processing_stopped": "🛑 Processing stopped",
                "tts_stopped": "🛑 Voice output stopped",
                "recording_no_audio": "No audio captured — recording stopped or check microphone.",
                "recording_too_short": "Recording too short — no text detected. Check microphone or speak longer.",
                "copied_to_clipboard": "Copied to clipboard",
                "llm_not_available": "LLM orchestrator not available.",
                "no_logs_to_save": "No logs to save",
                "all_logs_copied": "All logs copied to clipboard",
                "download_success": "✓ Successfully downloaded.",
                "download_progress": "⏳ Downloading {name}… {pct}%",
                "pytorch_cuda_progress": "⏳ {name}… {pct}%",
            },
            "run_test_400_hint": "→ 400 Bad Request usually means context exceeds the model limit. Increase Max input in Settings → Performance.",
            "run_test_timeout_hint": "→ The model did not finish in time. In Settings → Performance, set LLM request timeout to 240–360 seconds on slower PCs or very long system prompts.",
            "document_injection": {
                "llm_error_400": "LLM error (400) — context too large? Increase Max input (context) in Settings.",
                "llm_error_connection": "LLM server connection lost (process may have crashed or closed). Not a context limit — try again or restart PerkySue.",
                "llm_error_generic": "LLM error — check console. Increase Max input (context) in Settings.",
                "max_input_reached": "⚠️ Max input token limit reached — history was reduced. Consider Settings → Max input and your system's capacity.\n\n",
                "chat_max_input_reached": "⚠️ You've reached the max input (context) limit ({max_input}). Try increasing 'Max input' in Settings → Performance to {suggested} or higher.",
                "chat_context_limit_reached": "⚠️ Context limit ({max_input}) reached — input and output share this budget. Increase 'Max input' in Settings → Performance to {suggested} or higher.",
                "chat_max_output_reached": "⚠️ Reply was cut off: max output limit ({max_output}) reached. Increase 'Max output' in Settings → Performance to {suggested} or higher.",
                "chat_empty_reply": "— Reply was empty. Try rephrasing or check the console.",
            },
        }
        out = {k: dict(v) if isinstance(v, dict) else v for k, v in defaults.items()}
        merged = merge_strings_at("header_alerts")
        if isinstance(merged, dict):
            for section in ("critical", "regular", "document_injection"):
                sub = merged.get(section)
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        if v is not None:
                            out.setdefault(section, {})[k] = str(v)
            for k in ("run_test_400_hint", "run_test_timeout_hint"):
                if merged.get(k) is not None:
                    out[k] = str(merged[k])
        paths = getattr(self, "orch", None) and getattr(self.orch, "paths", None)
        if not paths:
            return out
        for yaml_path in [paths._app / "configs" / "header_alerts.yaml", paths.configs / "header_alerts.yaml"]:
            if not yaml_path.exists():
                continue
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for section in ("critical", "regular", "document_injection"):
                    if isinstance(data.get(section), dict):
                        for k, v in data[section].items():
                            if v is not None:
                                out.setdefault(section, {})[k] = str(v)
                if data.get("run_test_400_hint") is not None:
                    out["run_test_400_hint"] = str(data["run_test_400_hint"])
                if data.get("run_test_timeout_hint") is not None:
                    out["run_test_timeout_hint"] = str(data["run_test_timeout_hint"])
            except Exception:
                pass
        return out

    def _get_alert(self, key: str, **kwargs):
        """Retourne le message pour la clé (critical.xxx, regular.xxx, document_injection.xxx ou run_test_400_hint). Placeholders formatés via kwargs."""
        if getattr(self, "_header_alerts_config", None) is None:
            self._header_alerts_config = self._load_header_alerts_config()
        cfg = self._header_alerts_config
        msg = None
        if key.startswith("critical."):
            msg = (cfg.get("critical") or {}).get(key.replace("critical.", ""))
        elif key.startswith("regular."):
            msg = (cfg.get("regular") or {}).get(key.replace("regular.", ""))
        elif key.startswith("document_injection."):
            msg = (cfg.get("document_injection") or {}).get(key.replace("document_injection.", ""))
        else:
            msg = cfg.get(key)
        if msg is None:
            return key
        try:
            return msg.format(**kwargs) if kwargs else msg
        except (KeyError, ValueError):
            return msg

    def _schedule_tip_cycle(self, initial: bool = False):
        """Planifie l'affichage des tips : au démarrage d'abord startup_message (fixe), puis rotation des tips."""
        self._header_tips_config = self._load_header_tips_config()
        try:
            if getattr(self, "_tip_timer_id", None):
                try:
                    self.root.after_cancel(self._tip_timer_id)
                except (tk.TclError, AttributeError):
                    pass
                self._tip_timer_id = None
        except Exception:
            pass
        cfg = self._header_tips_config
        delay = cfg["delay_before_first_ms"] if initial else cfg["delay_between_ms"]
        if initial and (cfg.get("startup_message") or "").strip():
            self._tip_timer_id = self.root.after(delay, self._show_startup_message)
        else:
            self._tip_timer_id = self.root.after(delay, self._show_next_tip)

    def _show_startup_message(self):
        """Affiche une seule fois le message de démarrage fixe (ex. Press Alt+T…), puis lance la rotation des tips."""
        self._tip_timer_id = None
        try:
            if getattr(self, "_tip_restore_id", None):
                try:
                    self.root.after_cancel(self._tip_restore_id)
                except (tk.TclError, AttributeError):
                    pass
                self._tip_restore_id = None
        except Exception:
            pass
        if not self._header_tips_config:
            self._header_tips_config = self._load_header_tips_config()
        msg = (self._header_tips_config.get("startup_message") or "").strip()
        if not msg:
            self._schedule_tip_cycle(initial=False)
            return
        self._tips_shown.add(msg)
        self._tip_active = True
        try:
            if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                self.hdr.coords(self.patreon_btn, -1000, 36)
        except Exception:
            pass
        self._set_header_title_text(msg)
        display_ms = self._header_tips_config.get("display_ms", 5000)
        self._tip_restore_id = self.root.after(display_ms, self._tip_restore_and_schedule_next)

    def _show_next_tip(self):
        """Affiche le prochain tip dans le header puis planifie la restauration et le tip suivant."""
        self._tip_timer_id = None
        try:
            if getattr(self, "_tip_restore_id", None):
                try:
                    self.root.after_cancel(self._tip_restore_id)
                except (tk.TclError, AttributeError):
                    pass
                self._tip_restore_id = None
        except Exception:
            pass
        if not self._header_tips_config:
            self._header_tips_config = self._load_header_tips_config()
        tips_list = self._header_tips_config.get("tips") or []
        if not tips_list:
            return
        tips_shown = getattr(self, "_tips_shown", set())
        next_tip = None
        for t in tips_list:
            if t not in tips_shown:
                next_tip = t
                break
        if next_tip is None:
            self._tips_shown.clear()
            next_tip = tips_list[0]
        self._tips_shown.add(next_tip)
        self._tip_active = True
        try:
            if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                self.hdr.coords(self.patreon_btn, -1000, 36)
        except Exception:
            pass
        self._set_header_title_text(next_tip)
        display_ms = self._header_tips_config.get("display_ms", 5000)
        self._tip_restore_id = self.root.after(display_ms, self._tip_restore_and_schedule_next)

    def _tip_restore_and_schedule_next(self):
        """Restaure le titre normal et le bouton Patreon après un tip, puis planifie le prochain."""
        self._tip_restore_id = None
        self._tip_active = False
        try:
            if getattr(self, "hdr", None) and getattr(self, "patreon_btn", None):
                w = self.hdr.winfo_width()
                self.hdr.coords(self.patreon_btn, max(0, w - 30), 36)
        except Exception:
            pass
        try:
            normal = getattr(self, "_hdr_normal_text", "PerkySue Beta")
            self._set_header_title_text(normal)
        except Exception:
            pass
        self._schedule_tip_cycle(initial=False)

    def _show_critical_mic_dialog(self, message: str):
        """Affiche une boîte de dialogue modale pour les erreurs micro critiques (OK obligatoire).

        NOTE DESIGN (référence pour les futurs dialogs critiques) :
        - Utiliser un CTkToplevel 460x220, non redimensionnable, frame CARD corner_radius=12, texte Segoe UI.
        - Positionner la boîte avec le même schéma que ci-dessous : x décalé à gauche pour tripler l’espace à droite
          par rapport au centre de la fenêtre principale, y = root_y + 52 px.
        - Pour toute nouvelle boîte critique (licence, crash, etc.), réutiliser ce pattern ou factoriser un helper commun.
        Voir aussi la section « Boîtes de dialogue critiques » dans ARCHITECTURE.md.
        """
        # Ne montrer qu'une seule boîte à la fois
        if getattr(self, "_critical_mic_dialog", None):
            try:
                if self._critical_mic_dialog.winfo_exists():
                    return
            except Exception:
                self._critical_mic_dialog = None
        try:
            dlg = CTkToplevel(self.root)
            dlg.title("Microphone issue detected")
            dlg.geometry("460x220")
            dlg.resizable(False, False)
            dlg.transient(self.root)
            try:
                dlg.grab_set()
            except Exception:
                pass
            self._critical_mic_dialog = dlg

            frame = CTkFrame(dlg, fg_color=CARD, corner_radius=12)
            frame.pack(fill="both", expand=True, padx=20, pady=20)
            CTkLabel(frame, text="Microphone configuration problem", font=("Segoe UI", 18, "bold"), text_color=TXT).pack(anchor="w", pady=(4, 10))
            CTkLabel(frame, text=message, font=("Segoe UI", 13), text_color=TXT2, justify="left", wraplength=400).pack(anchor="w", pady=(0, 18))

            def _close():
                try:
                    dlg.destroy()
                except Exception:
                    pass
                self._critical_mic_dialog = None

            btn = CTkButton(frame, text="OK", font=("Segoe UI", 14, "bold"), fg_color=ACCENT, hover_color=SEL_BG, command=_close, width=80)
            btn.pack(pady=(0, 4))
            # Centrer verticalement ; décaler à gauche pour tripler l'espace à droite
            def _center():
                try:
                    dlg.update_idletasks()
                    root_x = self.root.winfo_rootx()
                    root_y = self.root.winfo_rooty()
                    root_w = self.root.winfo_width()
                    root_h = self.root.winfo_height()
                    dlg_w = dlg.winfo_width()
                    dlg_h = dlg.winfo_height()
                    half_gap = (root_w - dlg_w) // 2
                    # Triple l'offset droit : décaler à gauche de 2*half_gap par rapport au centre
                    x = root_x + half_gap - 2 * half_gap
                    x = max(20, x)
                    # Offset vertical depuis le haut (ancienne valeur ~52 px), pas de centrage
                    offset_top_px = 52
                    y = root_y + offset_top_px
                    dlg.geometry(f"+{x}+{y}")
                except Exception:
                    pass
            try:
                dlg.after(10, _center)
            except Exception:
                _center()
        except Exception:
            pass

    def _on_resize(self, event):
        if event.widget == self.root and not getattr(self, "_notify_patreon_hidden", False):
            try:
                self.hdr.coords(self.patreon_btn, event.width - 30, 36)
            except Exception:
                pass

    # ── BODY ──────────────────────────────────────────────────
    def _build_body(self):
        body = CTkFrame(self.root, fg_color="transparent", corner_radius=0)
        self._body_frame = body
        body.pack(fill="both", expand=True)

        sb = CTkFrame(body, width=270, fg_color=SIDEBAR, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Tooltip safety: moving from a model button to the sidebar can miss <Leave>
        # on the hovered widget (CustomTkinter edge case). Ensure any visible tooltip
        # closes as soon as the pointer enters the sidebar.
        try:
            sb.bind("<Enter>", lambda e: Tooltip.hide_current())
        except Exception:
            pass

        # Sidebar scrollable (768px): scrollbar discrète même couleur que SIDEBAR
        self._sidebar_scroll = CTkScrollableFrame(
            sb, fg_color="transparent", width=270, height=700,
            scrollbar_fg_color=SIDEBAR, scrollbar_button_color=SIDEBAR, scrollbar_button_hover_color=SIDEBAR,
        )
        self._sidebar_scroll.pack(fill="both", expand=True)
        try:
            self._sidebar_scroll.bind("<Enter>", lambda e: Tooltip.hide_current())
            c = getattr(self._sidebar_scroll, "_parent_canvas", None)
            if c:
                c.bind("<Enter>", lambda e: Tooltip.hide_current())
        except Exception:
            pass

        af = CTkFrame(self._sidebar_scroll, fg_color="transparent")
        af.pack(fill="x", pady=(40, 0))
        
        current_skin = self._effective_skin()
        main_path = get_avatar_path(current_skin, paths=self.paths)
        status_color = _STATUS_META["ready"][1]
        self.main_avatar_img = create_avatar_circle(180, "", 0, is_main=True, img_path=main_path, accent_color=status_color)
        self._main_avatar_label = CTkLabel(af, text="", image=self.main_avatar_img, cursor="arrow")
        self._main_avatar_label.pack()
        self._main_avatar_label.bind("<Button-1>", self._on_avatar_click)

        # Statut sous l'avatar (toutes les pages) — même typo que "Recommended Models"
        self._status_id = "ready"
        status_fr = CTkFrame(self._sidebar_scroll, fg_color="transparent")
        status_fr.pack(fill="x", pady=(12, 16))
        emoji, label, color = _status_tuple(self._status_id)
        self._status_lbl = CTkLabel(
            status_fr, text=f"{emoji} {label}",
            font=("Segoe UI", 20, "bold"), text_color=color,
        )
        self._status_lbl.pack()
        self._status_anim_job = None
        # TTS: anneau d'avatar modulé par le PCM réel (via TTSManager), offset [-5..+7] px affichage
        self._main_avatar_ring_offset_smooth = 0.0
        self._main_avatar_ring_last_offset = 0

        # Poll TTS speaking state to expose a proper "speaking" status (gold avatar ring).
        self._tts_speaking_poll_job = None
        self._tts_speaking_poll()
        try:
            self.root.after(50, self._main_avatar_ring_anim_tick)
        except Exception:
            pass

        self._nav = {}
        self._nav_hover_after = {}
        self._chat_needs_reset_indicator = False
        self._nav_chat_indicator = None
        self._help_needs_reset_indicator = False
        self._nav_help_indicator = None
        self._chat_new_btn_blink_job = None
        self._help_new_btn_blink_job = None
        self._tabview_internal_set = False  # guard to avoid recursion when _go() calls tabview.set()
        self._cached_greeting_chat = None
        self._cached_greeting_key_chat = None  # (name, lang) for Chat tab
        self._cached_greeting_help = None
        self._cached_greeting_key_help = None  # (name, lang) for Help tab
        self._chat_greeting_loading = False
        self._help_greeting_loading = False
        nf = CTkFrame(self._sidebar_scroll, fg_color="transparent")
        nf.pack(fill="x", pady=(10, 0))

        self._nav_page_ids = _build_nav_page_ids(getattr(self, "orch", None))
        for pid in self._nav_page_ids:
            label = s(f"common.nav.{pid}")
            if not label or label == f"common.nav.{pid}":
                _nav_lbl_fb = {"voice": "🔊   Voice", "avatar_editor": "🎨   Avatar Editor", "brainstorm": "🧠   Brainstorm"}
                label = _nav_lbl_fb.get(pid, f"🔌   {pid.title()}")
            row_f = CTkFrame(nf, fg_color="transparent", height=45)
            row_f.pack(fill="x", pady=2)
            row_f.pack_propagate(False)
            bar = CTkFrame(row_f, width=4, fg_color=SIDEBAR, corner_radius=0)
            bar.pack(side="left", fill="y")
            cell_f = CTkFrame(row_f, fg_color="transparent")
            cell_f.pack(side="left", fill="both", expand=True)
            icon_part, _, text_part = label.partition("   ")
            icon_lbl = CTkLabel(cell_f, text=icon_part or " ", font=("Segoe UI", 16), text_color=TXT2, width=32, height=45, fg_color="transparent")
            icon_lbl.pack(side="left", padx=(0, 0))
            if pid == "chat":
                nav_chat_ind = CTkLabel(cell_f, text="", font=("Segoe UI", 14), text_color="#F59E0B", fg_color="transparent")
                nav_chat_ind.place(relx=1.0, rely=0.5, anchor="e", x=-8)  # place() évite de réduire la largeur du btn (pack réservait ~10px)
                self._nav_chat_indicator = nav_chat_ind
            elif pid == "help":
                nav_help_ind = CTkLabel(cell_f, text="", font=("Segoe UI", 14), text_color="#F59E0B", fg_color="transparent")
                nav_help_ind.place(relx=1.0, rely=0.5, anchor="e", x=-8)
                self._nav_help_indicator = nav_help_ind
            btn = CTkButton(
                cell_f, text=text_part.strip() or label, anchor="w",
                font=("Segoe UI", 16), fg_color="transparent", text_color=TXT2,
                hover_color=SEL_BG, height=45, corner_radius=0,
                command=lambda p=pid: self._go(p)
            )
            btn.pack(side="left", fill="both", expand=True)
            icon_lbl.bind("<Button-1>", lambda e, p=pid: self._go(p))
            icon_lbl.configure(cursor="hand2")

            def _apply_hover(pid_=pid, on=True):
                if self._page == pid_:
                    return
                nav_tup = self._nav[pid_]
                bar_, btn_, icon_ = nav_tup[0], nav_tup[1], nav_tup[2]
                ind_ = nav_tup[3] if len(nav_tup) > 3 else None
                if on:
                    icon_.configure(fg_color=SEL_BG, text_color=TXT)
                    btn_.configure(fg_color=SEL_BG, text_color=TXT)
                    if ind_:
                        needs = False
                        if pid_ == "chat":
                            needs = getattr(self, "_chat_needs_reset_indicator", False)
                        elif pid_ == "help":
                            needs = getattr(self, "_help_needs_reset_indicator", False)
                        if needs:
                            ind_.configure(fg_color=SEL_BG)
                else:
                    icon_.configure(fg_color="transparent", text_color=TXT2)
                    btn_.configure(fg_color="transparent", text_color=TXT2)
                    if ind_:
                        ind_.configure(fg_color="transparent")

            def _remove_hover_if_outside(pid_=pid):
                self._nav_hover_after[pid_] = None
                try:
                    wx = self.root.winfo_pointerx() - self.root.winfo_rootx()
                    wy = self.root.winfo_pointery() - self.root.winfo_rooty()
                    w = self.root.winfo_containing(wx, wy)
                except Exception:
                    w = None
                nav_tup = self._nav[pid_]
                bar_, btn_, icon_ = nav_tup[0], nav_tup[1], nav_tup[2]
                ind_ = nav_tup[3] if len(nav_tup) > 3 else None
                while w:
                    if w in (btn_, icon_) or (ind_ and w == ind_):
                        return
                    w = getattr(w, "master", None)
                _apply_hover(pid_=pid_, on=False)

            def _on_enter(pid_=pid):
                if self._nav_hover_after.get(pid_):
                    try:
                        self.root.after_cancel(self._nav_hover_after[pid_])
                    except Exception:
                        pass
                    self._nav_hover_after[pid_] = None
                _apply_hover(pid_=pid_, on=True)

            def _on_leave(pid_=pid):
                self._nav_hover_after[pid_] = self.root.after(50, lambda: _remove_hover_if_outside(pid_=pid_))

            bind_targets = [icon_lbl, btn]
            if pid == "chat" and getattr(self, "_nav_chat_indicator", None):
                bind_targets.append(self._nav_chat_indicator)
                self._nav_chat_indicator.bind("<Button-1>", lambda e, p=pid: self._go(p))
                self._nav_chat_indicator.configure(cursor="hand2")
            if pid == "help" and getattr(self, "_nav_help_indicator", None):
                bind_targets.append(self._nav_help_indicator)
                self._nav_help_indicator.bind("<Button-1>", lambda e, p=pid: self._go(p))
                self._nav_help_indicator.configure(cursor="hand2")
            for w in bind_targets:
                w.bind("<Enter>", lambda e, p=pid: _on_enter(pid_=p))
                w.bind("<Leave>", lambda e, p=pid: _on_leave(pid_=p))
            if pid == "chat" and getattr(self, "_nav_chat_indicator", None):
                self._nav[pid] = (bar, btn, icon_lbl, self._nav_chat_indicator)
            elif pid == "help" and getattr(self, "_nav_help_indicator", None):
                self._nav[pid] = (bar, btn, icon_lbl, self._nav_help_indicator)
            else:
                self._nav[pid] = (bar, btn, icon_lbl)

        # Espace entre menu (About) et bouton Save pour le design
        _save_spacer = CTkFrame(self._sidebar_scroll, fg_color="transparent", height=28)
        _save_spacer.pack(fill="x", pady=(16, 0))
        _save_spacer.pack_propagate(False)

    # --- BOUTON SAVE & RESTART (Caché par défaut) ---
        self._save_frame = CTkFrame(self._sidebar_scroll, fg_color="transparent", height=80)
        self._save_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        self._save_frame.pack_propagate(False)

        # Effet Glow (dégradé violet/bleu/vert comme mockup)
        self._glow_bg = CTkFrame(self._save_frame, corner_radius=10, fg_color=ACCENT)
        self._glow_bg.pack(fill="x", pady=(5, 5))
        self._save_btn = CTkButton(
            self._glow_bg, text=s("settings.save_restart"), font=("Segoe UI", 14, "bold"),
            fg_color=SIDEBAR, hover_color=SEL_BG, height=36, corner_radius=8,
            command=self._on_save_restart,
        )
        self._save_btn.pack(fill="both", expand=True, padx=2, pady=2)
        self._save_note = CTkLabel(self._save_frame, text=s("settings.save_sidebar_note"), font=("Segoe UI", 11), text_color=MUTED)
        self._save_note.pack()
        self._save_frame.pack_forget()

        # Molette sur la sidebar : faire défiler le contenu (accès au bouton Save sur petits écrans)
        try:
            c = getattr(self._sidebar_scroll, "_parent_canvas", None)
            if c:
                def _sidebar_wheel(e, canvas=c):
                    try:
                        canvas.yview_scroll(int(-e.delta / 120), "units")
                    except Exception:
                        pass
                self._sidebar_scroll.bind("<MouseWheel>", _sidebar_wheel)
        except Exception:
            pass

        self.content = CTkFrame(body, fg_color=CONTENT, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True, padx=(30, 2), pady=25)

        self.pages: Dict[str, CTkFrame] = {}
        self._mk_settings()
        self._mk_about()
        self._mk_user()
        self._mk_console()
        self._mk_modes()
        self._mk_shortcuts()
        self._mk_chat()
        self._mk_voice()
        if "brainstorm" in getattr(self, "_nav_page_ids", ()):
            self._mk_brainstorm()
        if "avatar_editor" in getattr(self, "_nav_page_ids", ()):
            self._mk_avatar_editor()
        self._bind_content_wheel_fast()
        self.root.after(400, self._lift_main_window)

    def _lift_main_window(self):
        """Remet la fenêtre principale au premier plan (au-dessus de la console)."""
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(50, lambda: self.root.attributes("-topmost", False))
        except (tk.TclError, AttributeError):
            pass

    def _widget_under(self, w, parent):
        """True si w est parent ou un descendant de parent."""
        while w:
            if w == parent:
                return True
            w = getattr(w, "master", None)
        return False

    def _bind_content_wheel_fast(self):
        """bind_all: roulette sur la zone de contenu droite = scroll rapide (40-120 u) du canvas de la page visible."""
        if getattr(self, "_global_wheel_escape_bound", False):
            return
        self._global_wheel_escape_bound = True

        def _content_wheel(event):
            try:
                w = event.widget
                if not self._widget_under(w, self.content):
                    return
                # Cas particulier : si la souris est dans la zone Appearance/skins,
                # on laisse d'abord cette zone consommer la molette tant qu'elle peut encore défiler.
                if getattr(self, "_is_widget_under_skin_area", None) and self._is_widget_under_skin_area(w):
                    canvas_skin = getattr(self.inner_skin, "_parent_canvas", None)
                    if canvas_skin:
                        y0, y1 = canvas_skin.yview()
                        at_top = y0 <= 0.0
                        at_bottom = y1 >= 1.0
                        going_up = event.delta > 0
                        going_down = event.delta < 0
                        if (going_up and not at_top) or (going_down and not at_bottom):
                            return
                # Même logique pour Finalized / Temporary Logs (page Console)
                if getattr(self, "_is_widget_under_finalized_logs_area", None) and self._is_widget_under_finalized_logs_area(w):
                    canvas_fin = getattr(self._console_finalized_inner, "_parent_canvas", None)
                    if canvas_fin:
                        y0, y1 = canvas_fin.yview()
                        at_top = y0 <= 0.0
                        at_bottom = y1 >= 1.0
                        going_up = event.delta > 0
                        going_down = event.delta < 0
                        if (going_up and not at_top) or (going_down and not at_bottom):
                            return
                # Same logic for Recommended Models sub-scroll (Settings page)
                if getattr(self, "_is_widget_under_models_area", None) and self._is_widget_under_models_area(w):
                    canvas_models = getattr(getattr(self, "inner_models", None), "_parent_canvas", None)
                    if canvas_models:
                        y0, y1 = canvas_models.yview()
                        at_top = y0 <= 0.0
                        at_bottom = y1 >= 1.0
                        going_up = event.delta > 0
                        going_down = event.delta < 0
                        if (going_up and not at_top) or (going_down and not at_bottom):
                            return
                page = self.pages.get(self._page)
                if not page or not getattr(page, "_parent_canvas", None):
                    return
                c = page._parent_canvas
                y0, y1 = c.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = event.delta > 0
                going_down = event.delta < 0
                if at_top and going_up:
                    return
                if at_bottom and going_down:
                    return
                if c.yview() == (0.0, 1.0):
                    return
                step = 80
                u = -step if (event.delta > 0) else step
                Tooltip.hide_current()
                c.yview("scroll", u, "units")
                return "break"
            except (tk.TclError, AttributeError):
                pass
        self.root.bind_all("<MouseWheel>", _content_wheel, add="+")
        # Escape: cancel shortcut listen, or stop recording, or stop generation (only when app has focus)
        self.root.bind_all("<Escape>", self._request_escape_global_once, add="+")

    def _request_escape_global_once(self, event=None):
        """Planifie au plus un traitement Échap/Alt+Q par cycle — évite des dizaines de after(0) si stop répété."""
        if getattr(self, "_escape_stop_coalesce_id", None) is not None:
            return

        def _run():
            try:
                self._on_escape_global()
            finally:
                self._escape_stop_coalesce_id = None

        try:
            self._escape_stop_coalesce_id = self.root.after(0, _run)
        except (tk.TclError, AttributeError):
            self._escape_stop_coalesce_id = None

    def _on_escape_global(self, event=None):
        """Raccourci stop (défaut Alt+Q via orchestrateur) ou Échap : écoute raccourcis, arrêt micro, ou annulation LLM.
        Arrêt micro : on se base sur recorder.is_recording (pas sur status==listening) car set_status est async."""
        if getattr(self, "_shortcuts_listening_mode", None) is not None:
            self._on_shortcut_cancel_listen()
            return
        status = getattr(self, "_status_id", None)
        orch = getattr(self, "orch", None)
        if not orch:
            return
        cont = bool(getattr(orch, "is_continuous_chat_enabled", None) and orch.is_continuous_chat_enabled())
        # Ne pas exiger status=="listening" : set_status() est async (after(0)) — race où le micro
        # enregistre déjà mais l’avatar est encore "ready". Même logique que Abort / clic avatar.
        rec = getattr(orch, "recorder", None)
        if rec and rec.is_recording:
            orch.stop_recording()
            if cont and hasattr(orch, "reset_continuous_chat_listen_blockers"):
                orch.reset_continuous_chat_listen_blockers()
            self.set_status("ready")
            self._notify(self._get_alert("regular.recording_stopped"), restore_after_ms=3000)
            return
        # Defensive fallback: if UI still says listening (or orchestrator still marks recording),
        # force the same stop path even when recorder.is_recording already flipped.
        if status == "listening" or bool(getattr(orch, "_is_recording", False)):
            orch.stop_recording()
            if cont and hasattr(orch, "reset_continuous_chat_listen_blockers"):
                orch.reset_continuous_chat_listen_blockers()
            self.set_status("ready")
            self._notify(self._get_alert("regular.recording_stopped"), restore_after_ms=3000)
            return
        tm = getattr(orch, "tts_manager", None)
        if tm:
            try:
                if status == "tts_loading" or tm.is_speaking():
                    orch.stop_voice_output()
                    if cont and hasattr(orch, "reset_continuous_chat_listen_blockers"):
                        orch.reset_continuous_chat_listen_blockers()
                    self.set_status("ready")
                    self._notify(self._get_alert("regular.tts_stopped"), restore_after_ms=3000)
                    return
            except Exception:
                pass
        if status in ("processing", "generating") and orch:
            if getattr(orch, "_cancel_requested", False):
                if cont and hasattr(orch, "reset_continuous_chat_listen_blockers"):
                    orch.reset_continuous_chat_listen_blockers()
                return
            orch.request_cancel()
            self._notify(self._get_alert("regular.processing_stopped"), restore_after_ms=3000)
            self.set_status("ready")
            return
        # Chat continu : Alt+Q sans branche ci-dessus (ex. état coincé) — débloquer micro / pending TTS.
        if cont and hasattr(orch, "reset_continuous_chat_listen_blockers"):
            orch.reset_continuous_chat_listen_blockers()

    # ── PAGE ABOUT ─────────────────────────────────────────
    def _mk_about(self):
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["about"] = pg
        # Scroll rapide (40-120 u par cran)
        try:
            c = pg._parent_canvas
            def _wheel_fast(e, frame=pg):
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    canv.yview("scroll", u, "units")
                return "break"
            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass
        rpad = (0, 28)  # standard right padding for cards

        # ── Helper: responsive label (wraplength adapts to container width) ──
        def _responsive_label(parent, text, font=("Segoe UI", 14), text_color=TXT2, padx=25, pady=(0, 6), anchor="w", justify="left"):
            lbl = CTkLabel(parent, text=text, font=font, text_color=text_color,
                           wraplength=380, justify=justify, anchor=anchor)
            lbl.pack(anchor="w", fill="x", padx=padx, pady=pady)
            lbl._last_wrap_w = 0
            def _on_resize(e, l=lbl, px=padx):
                pad = px if isinstance(px, int) else (px[0] + px[1]) if isinstance(px, tuple) else 0
                new_w = max(100, e.width - pad - 30)  # 30px safety margin (card border + CTkLabel internal)
                if abs(new_w - l._last_wrap_w) < 5:
                    return
                l._last_wrap_w = new_w
                try:
                    l.configure(wraplength=new_w)
                except (tk.TclError, AttributeError):
                    pass
            parent.bind("<Configure>", lambda e: _on_resize(e, lbl, padx))
            return lbl

        # ── Helper: section title ──
        def _title(text, top=20):
            CTkLabel(pg, text=text, font=("Segoe UI", 20, "bold"), text_color=TXT).pack(anchor="w", pady=(top, 10))

        # ── Helper: standard card ──
        def _card(top=0, bottom=20):
            c = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
            c.pack(fill="x", pady=(top, bottom), padx=rpad)
            return c

        # ── UPDATES (top box) ────────────────────────────────
        _title(s("about.updates.title", default="Updates"), top=20)
        updates_card = _card(top=0)
        updates_inner = CTkFrame(updates_card, fg_color="transparent")
        updates_inner.pack(fill="x", padx=20, pady=16)
        updates_inner.grid_columnconfigure(0, weight=1)
        self._about_updates_body = CTkLabel(
            updates_inner,
            text=s("about.updates.body_idle", default="Check GitHub for the latest version."),
            font=("Segoe UI", 13),
            text_color=TXT2,
            justify="left",
            anchor="w",
        )
        self._about_updates_body.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        btn_row = CTkFrame(updates_inner, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        self._about_updates_btn = CTkButton(
            btn_row,
            text=s("about.updates.btn_check", default="Check for updates"),
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            height=40,
            corner_radius=8,
            width=220,
            command=self._open_update_wizard,
        )
        self._about_updates_btn.grid(row=0, column=0, sticky="", pady=(0, 0))

        # ── PLUGIN / SKIN INSTALL (ZIP) ──────────────────────
        _title(s("about.zip_install.section_title", default="Install a plugin (ZIP)"), top=10)
        zip_card = _card(top=0)
        zip_inner = CTkFrame(zip_card, fg_color="transparent")
        zip_inner.pack(fill="x", padx=20, pady=16)
        zip_inner.grid_columnconfigure(0, weight=1)
        _responsive_label(
            zip_inner,
            s(
                "about.zip_install.body",
                default="Select a ZIP from your Downloads folder and PerkySue will install it into the right place.\n\nExpected layout inside the ZIP (root-relative):\n- Data/Skins/Mike/...\n- Data/Plugins/<YourPlugin>/...\n\nTip: the ZIP must start at the root (no extra top-level folder).",
            ),
            font=("Segoe UI", 13),
            text_color=TXT2,
            padx=0,
            pady=(0, 12),
        )

        btn_row2 = CTkFrame(zip_inner, fg_color="transparent")
        btn_row2.pack(fill="x")
        btn_row2.grid_columnconfigure(0, weight=1)
        self._about_zip_install_btn = CTkButton(
            btn_row2,
            text=s("about.zip_install.btn", default="Install from ZIP…"),
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            height=40,
            corner_radius=8,
            width=240,
            command=self._about_install_zip_from_downloads,
        )
        self._about_zip_install_btn.pack(pady=(0, 0))

        # ══════════════════════════════════════════════════
        #   HERO (strings: App/configs/strings/en.yaml)
        # ══════════════════════════════════════════════════
        hero = _card(top=20)
        if HAS_PIL:
            try:
                gw, gh = 500, 6
                grad = Image.new("RGB", (gw, gh))
                draw = ImageDraw.Draw(grad)
                for x in range(gw):
                    r = int(79 + (211 - 79) * x / gw)
                    g = int(38 + (54 - 38) * x / gw)
                    b = int(131 + (96 - 131) * x / gw)
                    draw.line([(x, 0), (x, gh)], fill=(r, g, b))
                grad_img = CTkImage(light_image=grad, dark_image=grad, size=(gw, gh))
                grad_lbl = CTkLabel(hero, text="", image=grad_img, height=gh)
                grad_lbl.pack(fill="x")
                grad_lbl.image_ref = grad_img
            except Exception:
                pass
        CTkLabel(hero, text=s("about.hero.title"), font=("Segoe UI", 28, "bold"), text_color=TXT).pack(
            anchor="w", padx=25, pady=(18, 0)
        )
        _responsive_label(
            hero,
            s("about.hero.tagline"),
            font=("Segoe UI", 16, "bold"),
            text_color=ACCENT,
            pady=(4, 0),
        )
        _responsive_label(
            hero,
            s("about.hero.subtitle"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(6, 20),
        )

        # ══════════════════════════════════════════════════
        #   WHY PERKYSUE EXISTS
        # ══════════════════════════════════════════════════
        _title(s("about.why_exists.section_title"), top=24)
        why_exists = _card()
        _responsive_label(
            why_exists,
            s("about.why_exists.line_1"),
            font=("Segoe UI", 14, "bold"),
            text_color=ACCENT,
            pady=(18, 4),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_2"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(0, 6),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_3"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(0, 6),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_4"),
            font=("Segoe UI", 14, "bold"),
            text_color=ACCENT,
            pady=(8, 4),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_5"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(0, 6),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_6"),
            font=("Segoe UI", 14, "bold"),
            text_color=GOLD,
            pady=(8, 4),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_7"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(0, 6),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_8"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(8, 4),
        )
        _responsive_label(
            why_exists,
            s("about.why_exists.line_9"),
            font=("Segoe UI", 14, "bold"),
            text_color=ACCENT,
            pady=(0, 18),
        )

        # ══════════════════════════════════════════════════
        #   HOW IT WORKS
        # ══════════════════════════════════════════════════
        _title(s("about.how_it_works.section_title"))
        hw_card = _card()
        steps = [
            ("1", s("about.how_it_works.step1_title"), None),
            ("2", s("about.how_it_works.step2_title"), s("about.how_it_works.step2_description")),
            ("3", s("about.how_it_works.step3_title"), s("about.how_it_works.step3_description")),
            ("4", s("about.how_it_works.step4_title"), s("about.how_it_works.step4_description")),
        ]
        for i, (num, title, desc) in enumerate(steps):
            row = CTkFrame(hw_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=(16 if i == 0 else 6, 16 if i == len(steps) - 1 else 0))
            badge = CTkFrame(row, width=32, height=32, corner_radius=16, fg_color=ACCENT)
            badge.pack(side="left", padx=(0, 14), anchor="n", pady=(2, 0))
            badge.pack_propagate(False)
            CTkLabel(badge, text=num, font=("Segoe UI", 14, "bold"), text_color=TXT).place(relx=0.5, rely=0.5, anchor="center")
            text_f = CTkFrame(row, fg_color="transparent")
            text_f.pack(side="left", fill="x", expand=True)
            CTkLabel(text_f, text=title, font=("Segoe UI", 16, "bold"), text_color=TXT, anchor="w").pack(anchor="w")
            if desc is None:
                _responsive_label(text_f, s("about.how_it_works.step1_description"),
                                  font=("Segoe UI", 14), text_color=TXT2, padx=0, pady=(2, 4))
                hk_flow = CTkFrame(text_f, fg_color="transparent")
                hk_flow.pack(anchor="w", pady=(0, 0))
                for hk_text, hk_desc in [("Alt+T", "Transcribe"), ("Alt+M", "Email"), ("Alt+I", "Improve text…")]:
                    CTkLabel(hk_flow, text=hk_text, font=("Segoe UI", 12, "bold"), text_color=TXT,
                             fg_color=ACCENT, corner_radius=4, width=44, height=22).pack(side="left", padx=(0, 3))
                    CTkLabel(hk_flow, text=hk_desc,
                             font=("Segoe UI", 14), text_color=TXT2).pack(side="left", padx=(0, 10))
            else:
                _responsive_label(text_f, desc, font=("Segoe UI", 14), text_color=TXT2, padx=0, pady=(2, 0))
            if i < len(steps) - 1:
                CTkFrame(hw_card, height=1, fg_color="#3A3A42").pack(fill="x", padx=20, pady=(6, 0))

        # ══════════════════════════════════════════════════
        #   WHAT PEOPLE USE IT FOR
        # ══════════════════════════════════════════════════
        _title(s("about.features.section_title"))

        f1 = _card()
        CTkLabel(f1, text=s("about.features.transcribe.card_title"), font=("Segoe UI", 16, "bold"), text_color=GREEN_BT).pack(anchor="w", padx=25, pady=(18, 0))
        CTkLabel(f1, text=s("about.features.transcribe.badge"),
                 font=("Segoe UI", 12, "bold"), text_color=TXT, fg_color=ACCENT,
                 corner_radius=4, width=44, height=22).pack(anchor="w", padx=25, pady=(8, 0))
        _responsive_label(f1, s("about.features.transcribe.description"),
              font=("Segoe UI", 14), pady=(8, 18))

        f2 = _card()
        CTkLabel(f2, text=s("about.features.improve.card_title"), font=("Segoe UI", 16, "bold"), text_color=ACCENT).pack(anchor="w", padx=25, pady=(18, 0))
        CTkLabel(f2, text=s("about.features.improve.badge"),
                 font=("Segoe UI", 12, "bold"), text_color=TXT, fg_color=ACCENT,
                 corner_radius=4, width=44, height=22).pack(anchor="w", padx=25, pady=(8, 0))
        _responsive_label(f2, s("about.features.improve.description"),
              font=("Segoe UI", 14), pady=(8, 4))
        CTkLabel(f2, text=s("about.features.improve.prompt"),
                 font=("Segoe UI", 12), text_color=TXT).pack(anchor="w", padx=25, pady=(4, 0))
        CTkLabel(f2, text=s("about.features.improve.result"),
                 font=("Segoe UI", 12), text_color=GREEN_BT).pack(anchor="w", padx=25, pady=(2, 18))

        f3 = _card()
        CTkLabel(f3, text=s("about.features.professional.card_title"), font=("Segoe UI", 16, "bold"), text_color=ACCENT).pack(anchor="w", padx=25, pady=(18, 0))
        CTkLabel(f3, text=s("about.features.professional.badge"),
                 font=("Segoe UI", 12, "bold"), text_color=TXT, fg_color=ACCENT,
                 corner_radius=4, width=44, height=22).pack(anchor="w", padx=25, pady=(8, 0))
        _responsive_label(f3, s("about.features.professional.description"),
              font=("Segoe UI", 14), pady=(8, 4))
        CTkLabel(f3, text=s("about.features.professional.prompt"),
                 font=("Segoe UI", 12), text_color=TXT).pack(anchor="w", padx=25, pady=(4, 0))
        CTkLabel(f3, text=s("about.features.professional.result"),
                 font=("Segoe UI", 12), text_color=GREEN_BT).pack(anchor="w", padx=25, pady=(2, 18))

        _title(s("about.use_cases.section_title"), top=10)
        CTkLabel(
            pg,
            text=s("about.use_cases.intro"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))

        uc_card = _card()
        use_cases = s_list("about.use_cases.items")
        for i, uc in enumerate(use_cases):
            badge_text = uc.get("badge", "")
            name = uc.get("name", "")
            prompt_line = uc.get("prompt", "")
            result_line = uc.get("result", "")
            bw = max(44, len(badge_text) * 9)
            block = CTkFrame(uc_card, fg_color="transparent")
            block.pack(fill="x", padx=25, pady=(16 if i == 0 else 8, 16 if i == len(use_cases) - 1 else 0))
            hdr = CTkFrame(block, fg_color="transparent")
            hdr.pack(anchor="w")
            CTkLabel(hdr, text=badge_text, font=("Segoe UI", 12, "bold"), text_color=TXT,
                     fg_color=ACCENT, corner_radius=4, width=bw, height=22).pack(side="left", padx=(0, 8))
            CTkLabel(hdr, text=name, font=("Segoe UI", 14, "bold"), text_color=TXT).pack(side="left")
            _responsive_label(
                block,
                prompt_line,
                font=("Segoe UI", 12),
                text_color=TXT,
                padx=0,
                pady=(6, 0),
            )
            _responsive_label(
                block,
                result_line,
                font=("Segoe UI", 12),
                text_color=GREEN_BT,
                padx=0,
                pady=(2, 0),
            )
            if i < len(use_cases) - 1:
                CTkFrame(uc_card, height=1, fg_color="#3A3A42").pack(fill="x", padx=25, pady=(8, 0))

        _responsive_label(
            uc_card,
            s("about.use_cases.footer"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            padx=25,
            pady=(12, 16),
        )

        _title(s("about.smart_focus.section_title"), top=10)
        f4 = _card()
        CTkLabel(f4, text=s("about.smart_focus.card_title"), font=("Segoe UI", 16, "bold"), text_color="#F59E0B").pack(anchor="w", padx=25, pady=(18, 0))
        _responsive_label(f4, s("about.smart_focus.description"),
              font=("Segoe UI", 14), pady=(8, 18))

        _title(s("about.voice_modes.section_title"))
        modes_card = _card()
        modes = s_list("about.voice_modes.modes")
        for i, m in enumerate(modes):
            hotkey = m.get("hotkey", "")
            name = m.get("name", "")
            desc = m.get("description", "")
            needs_llm = bool(m.get("needs_llm", True))
            color = GREEN_BT if not needs_llm else TXT2
            row = CTkFrame(modes_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=(12 if i == 0 else 4, 12 if i == len(modes) - 1 else 0))
            CTkLabel(row, text=hotkey, font=("Segoe UI", 12, "bold"), text_color=TXT,
                     fg_color=ACCENT, corner_radius=4, width=44, height=22).pack(side="left", padx=(0, 12))
            CTkLabel(row, text=name, font=("Segoe UI", 14, "bold"), text_color=color, width=120, anchor="w").pack(side="left")
            CTkLabel(row, text=desc, font=("Segoe UI", 13), text_color=MUTED, anchor="w").pack(side="left", padx=(8, 0), fill="x", expand=True)
            if needs_llm:
                CTkLabel(row, text="LLM", font=("Segoe UI", 10), text_color=ACCENT,
                         fg_color="#2E1065", corner_radius=4, width=36, height=20).pack(side="right")
            else:
                CTkLabel(row, text="FREE", font=("Segoe UI", 10, "bold"), text_color="#166534",
                         fg_color="#052E16", corner_radius=4, width=40, height=20).pack(side="right")
            if i < len(modes) - 1:
                CTkFrame(modes_card, height=1, fg_color="#3A3A42").pack(fill="x", padx=20)

        _title(s("about.competition.section_title"))
        why_card = _card()
        comparisons = s_list("about.competition.items")
        for i, comp in enumerate(comparisons):
            title = comp.get("title", "")
            examples = comp.get("examples", "")
            desc = comp.get("description", "")
            block = CTkFrame(why_card, fg_color="transparent")
            block.pack(fill="x", padx=25, pady=(16 if i == 0 else 6, 16 if i == len(comparisons) - 1 else 0))
            CTkLabel(block, text=title, font=("Segoe UI", 16, "bold"), text_color=TXT, anchor="w").pack(anchor="w")
            CTkLabel(block, text=examples, font=("Segoe UI", 12), text_color=MUTED, anchor="w").pack(anchor="w")
            _responsive_label(block, desc, font=("Segoe UI", 14), text_color=TXT2, padx=0, pady=(4, 0))
            if i < len(comparisons) - 1:
                CTkFrame(why_card, height=1, fg_color="#3A3A42").pack(fill="x", padx=25, pady=(6, 0))

        _title(s("about.privacy.section_title"))
        priv_card = _card()
        priv_items = s_list("about.privacy.items")
        for i, item in enumerate(priv_items):
            icon = item.get("icon", "")
            ptitle = item.get("title", "")
            pdesc = item.get("description", "")
            row = CTkFrame(priv_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=(14 if i == 0 else 6, 14 if i == len(priv_items) - 1 else 0))
            CTkLabel(row, text=icon, font=("Segoe UI", 18), width=36).pack(side="left", padx=(0, 10))
            tf = CTkFrame(row, fg_color="transparent")
            tf.pack(side="left", fill="x", expand=True)
            CTkLabel(tf, text=ptitle, font=("Segoe UI", 14, "bold"), text_color=TXT, anchor="w").pack(anchor="w")
            CTkLabel(tf, text=pdesc, font=("Segoe UI", 13), text_color=MUTED, anchor="w").pack(anchor="w")

        _title(s("about.why_i_built_it.section_title"), top=24)
        origin_card = _card()
        _responsive_label(
            origin_card,
            s("about.why_i_built_it.paragraph_1"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(18, 6),
        )
        _responsive_label(
            origin_card,
            s("about.why_i_built_it.paragraph_2"),
            font=("Segoe UI", 14),
            text_color=TXT2,
            pady=(0, 18),
        )

        _title(s("about.links.section_title"), top=10)
        links_card = _card(bottom=40)
        links = s_list("about.links.items")
        for i, link in enumerate(links):
            label = link.get("label", "")
            url = (link.get("url") or "").strip()
            if "patreon.com" in url.lower():
                label = s("about.support_patreon_label", default=label)
            row = CTkFrame(links_card, fg_color="transparent")
            row.pack(fill="x", padx=25, pady=(12 if i == 0 else 4, 12 if i == len(links) - 1 else 0))
            color = GOLD if "Patreon" in label else BLUE
            lbl = CTkLabel(row, text=f"→  {label}", font=("Segoe UI", 14), text_color=color, cursor="hand2", anchor="w")
            lbl.pack(anchor="w")
            if url:
                lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        CTkLabel(pg, text=s("about.links.credit"),
                 font=("Segoe UI", 12), text_color=MUTED).pack(pady=(0, 30))

    def _mk_user(self):
        """Page Utilisateur : Identity (Your Name), User Settings (langue principale), langue UI (drapeaux)."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["user"] = pg
        rpad = (0, 28)
        try:
            c = pg._parent_canvas

            def _wheel_fast(e, frame=pg):
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    canv.yview("scroll", u, "units")
                return "break"

            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass

        # Gating (Identity — même règle qu’avant sur Prompt Modes)
        tier = "free"
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                tier = self.orch.get_gating_tier() or "free"
        except Exception:
            tier = "free"
        identity_edit_enabled = str(tier).lower() != "free"
        self._identity_edit_enabled = identity_edit_enabled

        # ─── Identity & Preferences (ex. Prompt Modes) ─────────────────
        CTkLabel(
            pg, text=s("modes.identity.section_title"),
            font=("Segoe UI", 20, "bold"), text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        id_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        id_card.pack(fill="x", pady=(0, 20), padx=rpad)
        id_inner = CTkFrame(id_card, fg_color="transparent")
        id_inner.pack(fill="x", padx=20, pady=16)
        id_inner.grid_columnconfigure(1, weight=1)
        CTkLabel(
            id_inner,
            text=s("modes.identity.title"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 4))
        identity_cfg = self.cfg.get("identity", {}) or {}
        self._identity_name_var = ctk.StringVar(value=str(identity_cfg.get("name", "") or ""))
        name_entry = ctk.CTkEntry(
            id_inner,
            textvariable=self._identity_name_var,
            placeholder_text=s("modes.identity.placeholder"),
            font=("Segoe UI", 13),
            height=36,
            fg_color=INPUT,
            border_color="#3A3A42",
        )
        self._identity_name_entry = name_entry
        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        if identity_edit_enabled:
            name_entry.bind("<FocusOut>", self._on_identity_name_change)
            name_entry.bind("<Return>", self._on_identity_name_change)
        else:
            try:
                name_entry.configure(state="disabled", text_color=MUTED, fg_color=CARD, cursor="arrow")
            except Exception:
                pass
        CTkLabel(
            id_inner,
            text=s("modes.identity.help"),
            font=("Segoe UI", 11),
            text_color=TXT2,
            wraplength=540,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ─── User Settings (ex. Performance — langue principale ; autres contrôles plus tard) ───
        CTkLabel(
            pg, text=s("user.settings.title"),
            font=("Segoe UI", 20, "bold"), text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        user_set_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        user_set_card.pack(fill="x", pady=(0, 20), padx=rpad)
        us_inner = CTkFrame(user_set_card, fg_color="transparent")
        us_inner.pack(fill="x", padx=20, pady=14)
        row_fl = CTkFrame(us_inner, fg_color="transparent")
        row_fl.pack(fill="x", pady=14)
        CTkLabel(row_fl, text="🌐", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            row_fl, text=s("settings.performance.first_language"),
            font=("Segoe UI", 14), text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        fl_opts = getattr(self, "_first_language_opts", None) or ["Auto", "en", "fr"]
        CTkOptionMenu(
            row_fl,
            variable=self._perf_first_language,
            values=fl_opts,
            width=220,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            button_color=SIDEBAR,
            button_hover_color=SEL_BG,
        ).pack(side="right")

        row_bill = CTkFrame(us_inner, fg_color="transparent")
        row_bill.pack(fill="x", pady=(12, 0))
        CTkLabel(row_bill, text="📧", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            row_bill,
            text=s("user.billing.label"),
            font=("Segoe UI", 14),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._user_billing_email_val = CTkLabel(
            row_bill,
            text=s("user.billing.empty"),
            font=("Segoe UI", 13),
            text_color=MUTED,
            anchor="e",
        )
        self._user_billing_email_val.pack(side="right")
        CTkLabel(
            us_inner,
            text=s("user.billing.hint"),
            font=("Segoe UI", 11),
            text_color=TXT2,
            wraplength=540,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        # Interface language (drapeaux) — alignement Settings → Appearance
        title_row = CTkFrame(pg, fg_color="transparent")
        title_row.pack(fill="x", pady=(20, 10), padx=(0, 28))
        title_row.grid_columnconfigure(1, weight=1)
        CTkLabel(
            title_row, text=s("user.section.language_title"),
            font=("Segoe UI", 20, "bold"), text_color=TXT,
        ).grid(row=0, column=0, sticky="w")
        CTkLabel(
            title_row, text=s("user.section.language_hint"),
            font=("Segoe UI", 13), text_color=MUTED,
        ).grid(row=0, column=1, sticky="e", pady=(4, 0))

        lang_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        lang_card.pack(fill="x", pady=(0, 20), padx=rpad)

        grid_fr = CTkFrame(lang_card, fg_color="transparent")
        # Espacements en quarts d’un pas 16px (U=4) : gouttières horizontales homogènes entre les 4 colonnes
        _U = 4
        _gutter_x = 4 * _U  # 16px entre axes de colonnes ; moitié à gauche/droite de chaque interstice
        _h_half = _gutter_x // 2
        grid_fr.pack(fill="x", padx=6 * _U, pady=(5 * _U, 7 * _U))
        cols = 4
        for col in range(cols):
            grid_fr.grid_columnconfigure(col, weight=1, uniform="lang_flags")

        sel = self._ui_flag_stem()
        assets = self.paths.app_dir / "assets" / "lang-flags"
        flag_px = 60
        for i, stem in enumerate(FLAG_STEMS_ORDER):
            r, c = divmod(i, cols)
            cell = CTkFrame(grid_fr, fg_color="transparent", cursor="hand2")
            pl = 0 if c == 0 else _h_half
            pr = 0 if c == cols - 1 else _h_half
            cell.grid(
                row=r, column=c, sticky="nsew",
                padx=(pl, pr),
                pady=(2 * _U, 2 * _U),
            )
            is_sel = stem == sel
            border_c = SKIN_SELECTED_BORDER if is_sel else "#52525B"
            p = assets / f"{stem}.png"
            path_str = str(p) if p.exists() else ""
            if HAS_PIL:
                ctk_flag = create_lang_flag_circle(flag_px, border_c, path_str or None)
            else:
                ctk_flag = None
            if ctk_flag:
                lbl_img = CTkLabel(cell, text="", image=ctk_flag, cursor="hand2")
            else:
                lbl_img = CTkLabel(
                    cell, text=stem.upper(), fg_color=INPUT, width=flag_px, height=flag_px,
                    font=("Segoe UI", 11), text_color=MUTED, cursor="hand2",
                )
            if ctk_flag:
                lbl_img.image_ref = ctk_flag
            lbl_img.pack()
            native = FLAG_STEM_NATIVE_LABEL.get(stem, stem)
            name_color = SKIN_SELECTED_BORDER if is_sel else TXT
            name_lbl = CTkLabel(
                cell, text=native, font=("Segoe UI", 12), text_color=name_color,
                cursor="hand2", wraplength=110, justify="center",
            )
            name_lbl.pack(pady=(_U // 2, 0))

            def _click(_e=None, s=stem):
                self._on_user_flag_click(s)

            cell.bind("<Button-1>", _click)
            lbl_img.bind("<Button-1>", _click)
            name_lbl.bind("<Button-1>", _click)

        try:
            self._refresh_user_billing_email_display()
        except Exception:
            pass

    # ── PAGE CONSOLE ─────────────────────────────────────────
    def _mk_console(self):
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["console"] = pg
        rpad = (0, 28)
        try:
            c = pg._parent_canvas
            def _wheel_fast(e, frame=pg):
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    canv.yview("scroll", u, "units")
                return "break"
            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass

        def _section(title: str):
            CTkLabel(pg, text=title, font=("Segoe UI", 20, "bold"), text_color=TXT).pack(anchor="w", pady=(20, 10), padx=rpad)

        def _console_card(height: int, text_ref: list, copy_getter=None):
            """Crée une carte avec CTkTextbox et bouton Copy. text_ref = [str] pour le contenu affiché; si copy_getter est fourni, il est utilisé pour Copy au lieu de text_ref[0]."""
            card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
            card.pack(fill="x", pady=(0, 20), padx=rpad)
            card.grid_columnconfigure(0, weight=1)
            txt = CTkTextbox(card, height=height, font=("Consolas", 12), fg_color=INPUT, text_color=TXT, wrap="word", state="disabled")
            txt.pack(fill="x", padx=20, pady=(20, 10))
            btn_row = CTkFrame(card, fg_color="transparent")
            btn_row.pack(fill="x", padx=20, pady=(0, 20))
            btn_row.grid_columnconfigure(0, weight=1)

            def _copy():
                content = (copy_getter() if copy_getter else (text_ref[0] if text_ref else "")) or ""
                if content:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(content)
                    self.root.update()
                    self._notify(self._get_alert("regular.copied_to_clipboard"), restore_after_ms=1500)

            copy_btn = CTkButton(btn_row, text=s("console.copy"), width=80, height=28, corner_radius=6, font=("Segoe UI", 13, "bold"),
                                 fg_color=ACCENT, hover_color=SEL_BG, command=_copy)
            copy_btn.pack(side="right")
            return card, txt, text_ref

        # ── PIPELINE STATUS ───────────────────────────────────────
        _section(s("console.pipeline_status"))

        # Card modèles actifs (STT + LLM)
        model_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        model_card.pack(fill="x", pady=(0, 10), padx=rpad)
        model_row = CTkFrame(model_card, fg_color="transparent")
        model_row.pack(fill="x", padx=16, pady=12)

        # STT : "Whisper STT:" (bold) + dot + model name (regular)
        stt_name = "—"
        stt_active = False
        try:
            if self.orch and self.orch.stt and self.orch.stt.is_available():
                stt_name = self.orch.stt.get_name()
                stt_active = True
        except Exception:
            pass

        stt_f = CTkFrame(model_row, fg_color="transparent")
        stt_f.pack(side="left", padx=(0, 28))
        CTkLabel(stt_f, text=s("console.whisper_stt"), font=("Segoe UI", 13, "bold"), text_color=TXT).pack(side="left", padx=(0, 8))
        stt_dot_color = GREEN_BT if stt_active else "#EF4444"
        stt_dot = CTkFrame(stt_f, width=12, height=12, corner_radius=6, fg_color=stt_dot_color)
        stt_dot.pack(side="left", padx=(0, 7))
        stt_dot.pack_propagate(False)
        stt_display = stt_name if stt_active else s("console.no_stt")
        self._pipeline_stt_lbl = CTkLabel(stt_f, text=stt_display, font=("Segoe UI", 13), text_color=TXT if stt_active else MUTED)
        self._pipeline_stt_lbl.pack(side="left")

        # LLM : "Local LLM:" (bold) + dot + model name (regular) ou "No LLM detected" (muted)
        llm_name = "—"
        llm_active = False
        eff_free = False
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro"):
                eff_free = not bool(self.orch.is_effective_pro())
        except Exception:
            eff_free = False
        try:
            if self.orch and self.orch.llm and self.orch.llm.is_available():
                llm_name = self.orch.llm.get_name()
                llm_active = True
        except Exception:
            pass

        llm_f = CTkFrame(model_row, fg_color="transparent")
        llm_f.pack(side="left")
        CTkLabel(llm_f, text=s("console.local_llm"), font=("Segoe UI", 13, "bold"), text_color=TXT).pack(side="left", padx=(0, 8))
        # Free plan: LLM may be installed but features are locked
        llm_dot_color = "#F59E0B" if (eff_free and llm_active) else (GREEN_BT if llm_active else "#EF4444")
        llm_dot = CTkFrame(llm_f, width=12, height=12, corner_radius=6, fg_color=llm_dot_color)
        llm_dot.pack(side="left", padx=(0, 7))
        llm_dot.pack_propagate(False)
        self._pipeline_llm_dot = llm_dot
        # In Free, LLM can still be installed/loaded for Help; show it as informational ("Help only")
        if eff_free and llm_active:
            llm_display = f"{llm_name} {s('console.help_only_suffix')}"
            llm_col = MUTED
        else:
            llm_display = llm_name if llm_active else s("console.no_llm")
            llm_col = TXT if llm_active else MUTED
        self._pipeline_llm_lbl = CTkLabel(llm_f, text=llm_display, font=("Segoe UI", 13), text_color=llm_col)
        self._pipeline_llm_lbl.pack(side="left")

        # Card barres de ressources (CPU, RAM, GPU, VRAM, Temp)
        res_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        res_card.pack(fill="x", pady=(0, 20), padx=rpad)
        res_row = CTkFrame(res_card, fg_color="transparent")
        res_row.pack(fill="x", padx=12, pady=12)
        for i in range(5):
            res_row.grid_columnconfigure(i, weight=1)

        # Créer les 5 labels pour les barres (PIL) — on les garde en attributs pour le polling
        self._res_bar_labels = []
        self._res_bar_imgs = []  # garder les refs PIL pour éviter le GC
        bar_defs = [
            ("CPU", 0, "%"),
            ("RAM", 0, "%"),
            ("GPU", 0, "%"),
            ("VRAM", 0, "%"),
            ("Temp", 0, "°"),
        ]
        for idx, (label, pct, unit) in enumerate(bar_defs):
            color = _resource_bar_color(label, pct, is_temp=(label == "Temp"))
            pil_img = create_resource_bar_img(130, 38, pct, label, color=color, unit=unit)
            if pil_img:
                tk_img = ImageTk.PhotoImage(pil_img)
                self._res_bar_imgs.append(tk_img)
                bar_lbl = tk.Label(res_row, image=tk_img, bg=CARD, bd=0, highlightthickness=0)
            else:
                self._res_bar_imgs.append(None)
                bar_lbl = CTkLabel(res_row, text=f"{label}: {pct}{unit}", font=("Segoe UI", 11), text_color=TXT2)
            bar_lbl.grid(row=0, column=idx, padx=3, pady=0, sticky="ew")
            self._res_bar_labels.append(bar_lbl)

        # Lancer le polling des ressources
        self._poll_resources_active = True
        self.root.after(1000, self._poll_resources)

        # ── TRANSCRIPTION CONTROLS ────────────────────────────────
        _section(s("console.transcription_controls"))
        ctrl_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        ctrl_card.pack(fill="x", pady=(0, 20), padx=rpad)
        ctrl_row = CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=16, pady=12)

        # Icônes Start / Abort (PIL) pour respecter le design (rond rouge + carré arrondi)
        self._ctrl_start_icon = create_record_icon(18)
        self._ctrl_abort_icon = create_abort_icon(18)

        # Start button — neutre au repos, prendra la couleur listening quand actif
        self._ctrl_start_btn = CTkButton(
            ctrl_row, text=s("console.start"), width=110, height=36, corner_radius=8,
            font=("Segoe UI", 14, "bold"), fg_color=SEL_BG, hover_color=MUTED,
            text_color=TXT, command=self._on_start_click,
            image=self._ctrl_start_icon, compound="left",
        )
        self._ctrl_start_btn.pack(side="left", padx=(0, 8))

        # Abort button
        self._ctrl_abort_btn = CTkButton(
            ctrl_row, text=s("console.abort"), width=110, height=36, corner_radius=8,
            font=("Segoe UI", 14, "bold"), fg_color=SEL_BG, hover_color=MUTED,
            text_color=TXT2, command=self._on_abort_click,
            image=self._ctrl_abort_icon, compound="left",
        )
        self._ctrl_abort_btn.pack(side="left", padx=(0, 8))

        # Copy Log — copies finalized console entries to the clipboard
        self._ctrl_save_btn = CTkButton(
            ctrl_row, text=s("console.copy_log"), width=110, height=36, corner_radius=8,
            font=("Segoe UI", 14), fg_color=SEL_BG, hover_color=MUTED,
            text_color=TXT, command=self._on_save_log_click,
        )
        self._ctrl_save_btn.pack(side="left", padx=(0, 12))

        # Volume — cellule bordée contenant icône + equalizer
        vol_cell = CTkFrame(ctrl_row, fg_color=INPUT, corner_radius=8, width=240, height=36)
        vol_cell.pack(side="left", padx=(0, 0))
        vol_cell.pack_propagate(False)
        vol_inner = CTkFrame(vol_cell, fg_color="transparent")
        vol_inner.pack(fill="both", expand=True, padx=6, pady=4)

        # Mute/unmute button (compact)
        self._vol_muted = False
        init_vol = 1.0
        try:
            if self.orch and self.orch.sound_manager:
                init_vol = self.orch.sound_manager.volume
        except Exception:
            pass
        self._vol_level = init_vol  # 0.0 – 1.0
        self._vol_mute_btn = CTkButton(
            vol_inner, text="🔊", width=26, height=26, corner_radius=4,
            font=("Segoe UI", 13), fg_color="transparent", hover_color=SEL_BG,
            text_color=TXT, command=self._on_mute_toggle,
        )
        self._vol_mute_btn.pack(side="left", padx=(0, 6))

        # Equalizer canvas (16 barres fines, large zone)
        self._vol_num_bars = 16
        self._vol_canvas_w = 190
        self._vol_canvas_h = 26
        self._vol_canvas = tk.Canvas(
            vol_inner, width=self._vol_canvas_w, height=self._vol_canvas_h,
            bg=INPUT, bd=0, highlightthickness=0,
        )
        self._vol_canvas.pack(side="left", fill="x", expand=True)
        self._vol_canvas.bind("<Button-1>", self._on_volume_click)
        self._vol_canvas.bind("<B1-Motion>", self._on_volume_click)
        self._update_volume_display()
        # Appliquer le volume initial + installer le monkey-patch _play_file
        self._apply_volume(self._vol_level)
        # Redessiner après le rendu effectif du canvas (pour utiliser la vraie largeur)
        self.root.after(200, self._update_volume_display)

        # Section Finalized / Temporary Logs — même design que Full Console : CARD + zone intérieure INPUT (scroll + entrées avec liner + Copy)
        _section(s("console.finalized_logs"))
        self._console_entries = []
        finalized_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        finalized_card.pack(fill="x", pady=(0, 20), padx=rpad)
        finalized_card.grid_columnconfigure(0, weight=1)
        self._console_finalized_inner = CTkScrollableFrame(
            finalized_card, fg_color=INPUT, corner_radius=8, height=280,
            scrollbar_fg_color=INPUT, scrollbar_button_color=MUTED, scrollbar_button_hover_color=TXT2,
        )
        self._console_finalized_inner.pack(fill="both", expand=True, padx=20, pady=20)
        self._console_finalized_inner.grid_columnconfigure(0, weight=1)
        self._console_finalized_inner.bind("<MouseWheel>", self._on_finalized_logs_wheel)

        # Section Full Console
        _section(s("console.full_console"))

        def _full_copy_getter():
            return "\n".join(getattr(self, "_log_lines", []))

        self._console_full_card, self._console_full_text, _ = _console_card(280, [], copy_getter=_full_copy_getter)
        self._refresh_console_full_box()

    def _whisper_kw_tags_counter_text(self, count: int) -> str:
        """Counter label for Whisper STT keywords (e.g. 2 / 10 tags)."""
        lim = getattr(self, "_whisper_kw_limit", None)
        lim_s = "∞" if lim is None else str(lim)
        return s("modes.stt_keywords.tags_counter").format(count=count, limit=lim_s)

    def _token_counter_display(self, tab_prefix: str, current: int, max_ctx: int) -> str:
        """Chat/Help token row: `{current} / {max}` from chat.* or help.* strings."""
        return s(f"{tab_prefix}.token_counter").format(current=current, max=max_ctx)

    def _localized_mode_name(self, mode_id: str, mode) -> str:
        fb = ""
        if mode is not None and getattr(mode, "name", None):
            fb = str(mode.name)
        if not fb:
            fb = mode_id.replace("_", " ").title()
        return s(f"modes.registry.{mode_id}.name", default=fb) or fb

    def _localized_mode_description(self, mode_id: str, mode) -> str:
        fb = ""
        if mode is not None and getattr(mode, "description", None):
            fb = str(mode.description)
        return s(f"modes.registry.{mode_id}.description", default=fb) or fb

    def _mk_modes(self):
        """Page Prompt Modes : Whisper Keywords, Identity & Preferences, Prompt Modes (éditables)."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["modes"] = pg
        rpad = (0, 28)

        # Plan gating (UI emulation in dev mode, proof-based in production).
        tier = "free"
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                tier = self.orch.get_gating_tier() or "free"
        except Exception:
            tier = "free"

        # Whisper STT keywords limit by plan:
        # - Free: 3 keywords
        # - Pro: 10 keywords (includes Pro alpha)
        # - Enterprise: unlimited
        self._whisper_kw_tier = str(tier).lower()
        if str(tier).lower() == "free":
            self._whisper_kw_limit = 3
        elif str(tier).lower() == "enterprise":
            self._whisper_kw_limit = None  # unlimited
        else:
            self._whisper_kw_limit = 10

        identity_edit_enabled = str(tier).lower() != "free"
        self._identity_edit_enabled = identity_edit_enabled

        def _section(title):
            lbl = CTkLabel(pg, text=title, font=("Segoe UI", 20, "bold"), text_color=TXT)
            lbl.pack(anchor="w", pady=(20, 10))
            return lbl

        # ─── SECTION 1: Whisper STT Keywords (limit plan-based) ──────
        if self._whisper_kw_limit is None:
            kw_title_lbl = _section(s("modes.stt_keywords.title_unlimited"))
        else:
            kw_title_lbl = _section(s("modes.stt_keywords.title_limit").format(limit=self._whisper_kw_limit))
        self._whisper_kw_title_lbl = kw_title_lbl
        self._whisper_kw_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        self._whisper_kw_card.pack(fill="x", pady=(0, 20), padx=rpad)
        self._whisper_kw_card.grid_columnconfigure(0, weight=1)

        kw_inner = CTkFrame(self._whisper_kw_card, fg_color="transparent")
        kw_inner.pack(fill="x", padx=20, pady=16)
        kw_inner.grid_columnconfigure(0, weight=1)

        self._whisper_keywords = list(self.cfg.get("stt", {}).get("whisper_keywords") or [])
        if not isinstance(self._whisper_keywords, list):
            self._whisper_keywords = []
        # Keep the full saved list; plan tier only limits adding (and shows the counter/redirect).
        self._whisper_keywords = [str(x).strip() for x in self._whisper_keywords if str(x).strip()]

        self._whisper_kw_entry = ctk.CTkEntry(
            kw_inner, placeholder_text=s("modes.stt_keywords.placeholder"),
            font=("Segoe UI", 13), height=36, fg_color=INPUT, border_color="#3A3A42",
        )
        self._whisper_kw_entry.pack(fill="x", pady=(0, 10))
        self._whisper_kw_entry.bind("<Return>", self._on_whisper_kw_add)

        self._whisper_kw_tags_frame = CTkFrame(kw_inner, fg_color="transparent")
        self._whisper_kw_tags_frame.pack(fill="x", pady=(0, 6))
        self._whisper_kw_tags_pack_opts = {"fill": "x", "pady": (0, 6)}
        self._whisper_kw_count_lbl = CTkLabel(
            kw_inner,
            text=self._whisper_kw_tags_counter_text(0),
            font=("Segoe UI", 12),
            text_color=MUTED,
        )
        self._whisper_kw_count_lbl.pack(anchor="w")
        # Premier rendu des tags après que la page ait fini de se layout,
        # pour éviter que la largeur trop petite au démarrage ne force un empilement vertical.
        if self._whisper_keywords:
            try:
                self.root.after(50, self._rebuild_whisper_kw_tags)
            except Exception:
                self._rebuild_whisper_kw_tags()
        else:
            self._rebuild_whisper_kw_tags()

        # ─── SECTION 2: Prompt Modes (per shortcut) — Identity & Preferences → User page ───
        _section(s("modes.prompt_modes.title"))
        pm_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        pm_card.pack(fill="both", pady=(0, 20), padx=rpad)

        pm_inner = CTkFrame(pm_card, fg_color="transparent")
        pm_inner.pack(fill="both", expand=True, padx=20, pady=16)
        pm_inner.grid_columnconfigure(0, weight=1)

        CTkLabel(
            pm_inner,
            text=s("modes.prompt_modes.edit_hint"),
            font=("Segoe UI", 12),
            text_color=TXT2,
            wraplength=540,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        # Build cards per hotkey → mode.
        self._mode_ui = {}
        hotkeys_cfg = {}
        if self.orch and getattr(self.orch, "config", None):
            hotkeys_cfg = dict(self.orch.config.get("hotkeys", {}))
        else:
            hotkeys_cfg = dict(self.cfg.get("hotkeys", {}))
        # Ensure custom1/2/3 appear for existing configs that don't have them yet
        for k, v in [("help", "alt+h"), ("custom1", "alt+v"), ("custom2", "alt+b"), ("custom3", "alt+n"), ("message", "alt+d"), ("social", "alt+x")]:
            if k not in hotkeys_cfg:
                hotkeys_cfg[k] = v

        self._mode_active_sample = getattr(self, "_mode_active_sample", {}) or {}
        row = 1
        for mode_id, hk in hotkeys_cfg.items():
            if mode_id == "behavior":
                continue
            mode = None
            if self.orch and getattr(self.orch, "modes", None):
                mode = self.orch.modes.get(mode_id)
            if not mode:
                continue
            # Skip non-LLM modes (e.g. Alt+T transcription only).
            if not getattr(mode, "needs_llm", False):
                continue

            if mode_id == "answer":
                info_card = CTkFrame(pm_inner, fg_color=CARD, corner_radius=8, border_width=1, border_color="#3A3A42")
                info_card.grid(row=row, column=0, sticky="ew", pady=(0, 10))
                row += 1
                CTkLabel(
                    info_card,
                    text=f"{hk.upper()}  —  {s('modes.registry.answer_free.name')}",
                    font=("Segoe UI", 14, "bold"),
                    text_color=TXT,
                ).pack(anchor="w", padx=10, pady=(12, 4))
                CTkLabel(
                    info_card,
                    text=s("modes.registry.answer_free.description"),
                    font=("Segoe UI", 11),
                    text_color=TXT2,
                    wraplength=540,
                    justify="left",
                ).pack(fill="x", padx=10, pady=(0, 12))

            card = CTkFrame(pm_inner, fg_color=CARD, corner_radius=8, border_width=0)
            card.grid(row=row, column=0, sticky="ew", pady=(0, 14))
            row += 1

            header = CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", pady=(8, 4), padx=10)

            mode_title = self._localized_mode_name(mode_id, mode)
            if mode_id == "answer":
                mode_title = self._localized_mode_name("answer_pro", mode)
            title_lbl = CTkLabel(
                header,
                text=f"{hk.upper()}  —  {mode_title}",
                font=("Segoe UI", 14, "bold"),
                text_color=TXT,
            )
            title_lbl.pack(side="left", anchor="w")

            desc_txt = self._localized_mode_description(mode_id, mode)
            if mode_id == "answer":
                desc_txt = self._localized_mode_description("answer_pro", mode)
            if desc_txt:
                CTkLabel(
                    card,
                    text=desc_txt,
                    font=("Segoe UI", 11),
                    text_color=TXT2,
                    wraplength=540,
                    justify="left",
                ).pack(fill="x", padx=10, pady=(0, 4))

            btn_bar = CTkFrame(header, fg_color="transparent")
            btn_bar.pack(side="right")

            btn_w = 78
            btn_h = 28

            # Header actions — unified size, bold font, emojis, standard colors
            # Padding between emoji and label harmonized avec les boutons "↓ Get".
            edit_text = f"✏ {s('modes.prompt_modes.edit')}"
            save_text = f"💾 {s('modes.prompt_modes.save')}"
            cancel_text = f"✖ {s('modes.prompt_modes.cancel')}"
            test_text = f"🧪 {s('modes.prompt_modes.test')}"
            edit_btn = CTkButton(
                btn_bar,
                text=edit_text,
                width=btn_w,
                height=btn_h,
                font=("Segoe UI", 12, "bold"),
                fg_color=INPUT,
                hover_color=SEL_BG,
                text_color=TXT,
                command=lambda m=mode_id: self._on_mode_edit(m),
            )
            edit_btn.pack(side="left", padx=(0, 6))

            save_btn = CTkButton(
                btn_bar,
                text=save_text,
                width=btn_w,
                height=btn_h,
                font=("Segoe UI", 12, "bold"),
                fg_color=GREEN_BT,
                hover_color=GREEN_HV,
                text_color="white",
                command=lambda m=mode_id: self._on_mode_save(m),
            )
            cancel_btn = CTkButton(
                btn_bar,
                text=cancel_text,
                width=btn_w,
                height=btn_h,
                font=("Segoe UI", 12, "bold"),
                fg_color="#5A5A66",
                hover_color="#3A3A42",
                text_color="white",
                command=lambda m=mode_id: self._on_mode_cancel(m),
            )
            # Initially hidden
            save_btn.pack_forget()
            cancel_btn.pack_forget()

            test_btn = CTkButton(
                btn_bar,
                text=test_text,
                width=btn_w,
                height=btn_h,
                font=("Segoe UI", 12, "bold"),
                fg_color=ACCENT,
                hover_color=SEL_BG,
                text_color="white",
                command=lambda m=mode_id: self._on_mode_test(m),
            )
            # Visible au départ (ouvre la zone de test), puis caché après premier clic.
            test_btn.pack(side="left", padx=(0, 6))

            # Prompt editor (read-only by default, dark when editing).
            prompt_box = CTkTextbox(
                card,
                height=160,
                font=("Consolas", 12),
                fg_color=CARD,  # grey when read-only; black (INPUT) in edit mode
                text_color=TXT,
                border_width=1,
                border_color="#3A3A42",
                wrap="word",
            )
            prompt_box.pack(fill="x", padx=10, pady=(0, 2))
            initial_prompt = getattr(mode, "system_prompt", "") or ""
            prompt_box.insert("1.0", initial_prompt)
            # Locked (non-selectable) in view mode; only editable in Edit mode.
            self._set_prompt_box_readonly(prompt_box)

            # Live test box (hidden by default)
            test_frame = CTkFrame(card, fg_color="#1E1E24", corner_radius=8)
            # not packed initially

            # Help mode: clarify that the prompt box above is only the instructions; system prompt = params + KB + that.
            if (mode_id or "").strip().lower() == "help":
                help_note = CTkLabel(
                    test_frame,
                    text=s("modes.prompt_modes.system_prompt_help"),
                    font=("Segoe UI", 10),
                    text_color=MUTED,
                    wraplength=520,
                    justify="left",
                )
                help_note.pack(anchor="w", padx=10, pady=(8, 4))

            input_row = CTkFrame(test_frame, fg_color="transparent")
            input_row.pack(fill="x", padx=10, pady=(8, 2))
            input_lbl = CTkLabel(
                input_row,
                text=s("modes.prompt_modes.test_input_label"),
                font=("Segoe UI", 11),
                text_color=TXT2,
            )
            input_lbl.pack(side="left", anchor="w")

            # Sample selector buttons (EN1, EN2, FR1, FR2) — small pills similar to filters/lang badges.
            samples_row = CTkFrame(input_row, fg_color="transparent")
            samples_row.pack(side="left", padx=(10, 0))
            sample_btns = {}
            for code in ("EN1", "EN2", "FR1", "FR2"):
                btn = CTkButton(
                    samples_row,
                    text=code,
                    width=0,
                    height=22,
                    corner_radius=6,
                    fg_color=INPUT,
                    hover_color=SEL_BG,
                    font=("Segoe UI", 11, "bold"),
                    text_color=TXT2,
                    command=lambda c=code, m=mode_id: self._on_mode_sample_click(m, c),
                )
                btn.pack(side="left", padx=(0, 6))
                sample_btns[code] = btn
            # Appliquer le style actif (or + blanc) au pill sélectionné dès la construction.
            self._update_mode_sample_pills(mode_id)
            test_lang_lbl = CTkLabel(
                input_row,
                text="",
                font=("Segoe UI", 10),
                text_color=MUTED,
            )
            test_lang_lbl.pack(side="right", anchor="e")

            # Test input + bouton Paste aligné à droite de la cellule de texte.
            test_input_row = CTkFrame(test_frame, fg_color="transparent")
            test_input_row.pack(fill="x", padx=10, pady=(0, 6))
            test_input = CTkTextbox(
                test_input_row,
                height=90,
                font=("Segoe UI", 12),
                fg_color=INPUT,
                text_color=TXT,
                wrap="word",
            )
            test_input.pack(side="left", fill="both", expand=True, padx=(0, 6))
            paste_btn = CTkButton(
                test_input_row,
                text=s("modes.prompt_modes.paste"),
                width=56,
                height=24,
                corner_radius=6,
                font=("Segoe UI", 11),
                fg_color=SEL_BG,
                hover_color=MUTED,
                text_color=TXT,
                command=lambda m=mode_id: self._on_mode_test_input_paste(m),
            )
            paste_btn.pack(side="right", anchor="ne")

            output_lbl = CTkLabel(
                test_frame,
                text=s("modes.prompt_modes.test_response_label"),
                font=("Segoe UI", 11),
                text_color=TXT2,
            )
            output_lbl.pack(anchor="w", padx=10, pady=(6, 2))

            # LLM response preview + bouton Copy aligné à droite.
            test_output_row = CTkFrame(test_frame, fg_color="transparent")
            test_output_row.pack(fill="x", padx=10, pady=(0, 6))
            test_output = CTkTextbox(
                test_output_row,
                height=110,
                font=("Segoe UI", 12),
                fg_color=INPUT,
                text_color=TXT,
                wrap="word",
            )
            test_output.pack(side="left", fill="both", expand=True, padx=(0, 6))
            test_output.configure(state="disabled")
            copy_preview_btn = CTkButton(
                test_output_row,
                text=s("modes.prompt_modes.copy"),
                width=56,
                height=24,
                corner_radius=6,
                font=("Segoe UI", 11),
                fg_color=SEL_BG,
                hover_color=MUTED,
                text_color=TXT,
                command=lambda m=mode_id: self._on_mode_test_output_copy(m),
            )
            copy_preview_btn.pack(side="right", anchor="ne")

            hint_lbl = CTkLabel(
                test_frame,
                text=s("modes.prompt_modes.test_hint"),
                font=("Segoe UI", 10),
                text_color=MUTED,
                justify="right",
                anchor="e",
            )
            hint_lbl.pack(fill="x", padx=10, pady=(0, 4))

            # Inner button to actually run the test with current input.
            run_btn = CTkButton(
                test_frame,
                text=s("modes.prompt_modes.run_test"),
                width=btn_w,
                height=btn_h,
                font=("Segoe UI", 12),
                fg_color=ACCENT,
                hover_color=SEL_BG,
                command=lambda m=mode_id: self._on_mode_run_test(m),
            )
            run_btn.pack(anchor="e", padx=10, pady=(0, 8))

            # Sub-scroll rule: the mouse wheel over these text areas should scroll
            # their own content first, then let the page scroll at top/bottom.
            for w in (prompt_box, test_input, test_output):
                try:
                    w.bind("<MouseWheel>", self._on_prompt_modes_wheel)
                except Exception:
                    pass

            # Resize handle (bottom-right) to let user grow/shrink the prompt box height.
            resize_handle = CTkLabel(
                card,
                text="◢",
                font=("Segoe UI", 14),
                text_color=TXT2,
                fg_color="transparent",
                cursor="bottom_right_corner",
            )
            # Légèrement décalé vers la gauche et vers le haut pour mieux coller au coin du prompt.
            resize_handle.pack(anchor="se", padx=12, pady=(0, 18))

            def _start_resize(e, m=mode_id, box=prompt_box):
                self._resize_mode_id = m
                try:
                    self._resize_start_y = e.y_root
                    self._resize_start_h = int(box.cget("height"))
                except Exception:
                    self._resize_start_y = e.y_root
                    self._resize_start_h = 160

            def _do_resize(e, m=mode_id, box=prompt_box):
                if getattr(self, "_resize_mode_id", None) != m:
                    return
                dy = e.y_root - getattr(self, "_resize_start_y", e.y_root)
                base_h = getattr(self, "_resize_start_h", 160)
                new_h = max(80, min(600, int(base_h + dy)))
                try:
                    box.configure(height=new_h)
                except Exception:
                    pass

            def _end_resize(e):
                self._resize_mode_id = None

            resize_handle.bind("<Button-1>", _start_resize)
            resize_handle.bind("<B1-Motion>", _do_resize)
            resize_handle.bind("<ButtonRelease-1>", _end_resize)

            self._mode_ui[mode_id] = {
                "card": card,
                "prompt_box": prompt_box,
                "initial_prompt": initial_prompt,
                "edit_btn": edit_btn,
                "save_btn": save_btn,
                "cancel_btn": cancel_btn,
                "test_btn": test_btn,
                "test_frame": test_frame,
                "test_input": test_input,
                "test_output": test_output,
                "run_btn": run_btn,
                "hint_lbl": hint_lbl,
                "test_lang_lbl": test_lang_lbl,
                "sample_btns": sample_btns,
            }

        # Apply plan-based lock state for Prompt Modes actions on first build.
        try:
            self._refresh_prompt_modes_plan_restrictions()
        except Exception:
            pass

    def _mk_shortcuts(self):
        """Page Shortcuts Manager: table Hotkey (éditable) | Mode | What it does | Needs LLM; Restore Default; effet Listening + capture clavier."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["shortcuts"] = pg
        self._shortcuts_listening_mode = None
        self._shortcuts_hotkey_btns = {}
        self._shortcuts_key_bind_id = None

        # Order and metadata for each shortcut row (include custom1, custom2, custom3)
        mode_order = [
            "transcribe", "improve", "professional", "translate", "console", "email",
            "message", "social",
            "summarize", "genz", "answer_free", "answer_pro", "help", "custom1", "custom2", "custom3",
        ]
        hotkeys_cfg = {}
        if getattr(self, "orch", None) and getattr(self.orch, "config", None):
            hotkeys_cfg = dict(self.orch.config.get("hotkeys", {}))
        else:
            hotkeys_cfg = dict(self.cfg.get("hotkeys", {}))
        for k, v in [
            ("help", "alt+h"),
            ("custom1", "alt+v"),
            ("custom2", "alt+b"),
            ("custom3", "alt+n"),
            ("stop_recording", "alt+q"),
            ("reinject_last", "alt+r"),
            ("message", "alt+d"),
            ("social", "alt+x"),
        ]:
            if k not in hotkeys_cfg:
                hotkeys_cfg[k] = v

        title = CTkLabel(pg, text=s("shortcuts.title"), font=("Segoe UI", 20, "bold"), text_color=TXT)
        title.pack(anchor="w", padx=(0, 28), pady=(20, 16))

        card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        card.pack(fill="x", padx=(0, 28), pady=(0, 20))
        inner = CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=20)

        def _format_display_hotkey(hk: str) -> str:
            if not hk:
                return ""
            return "+".join(p.capitalize() for p in hk.lower().strip().split("+"))

        def _derive_altgr_display(main_hk: str) -> str:
            if not main_hk:
                return ""
            parts = main_hk.lower().strip().split("+")
            if "ctrl" in parts or "control" in parts:
                return _format_display_hotkey(main_hk)
            return "Ctrl+" + _format_display_hotkey(main_hk)

        col_w = 160
        hdr = CTkFrame(inner, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 2))
        CTkLabel(hdr, text=s("shortcuts.col_hotkey_alt"), font=("Segoe UI", 13, "bold"), text_color=MUTED, width=col_w).pack(side="left")
        CTkLabel(hdr, text=s("shortcuts.col_hotkey_altgr"), font=("Segoe UI", 13, "bold"), text_color=MUTED, width=col_w).pack(side="left")
        CTkLabel(hdr, text=s("shortcuts.col_mode"), font=("Segoe UI", 13, "bold"), text_color=MUTED, width=col_w).pack(side="left")

        # Hotkey cell: raccourci + Edit (46 px pour libellés type « Ändern ») ; 4 px entre colonne Alt et AltGr.
        def _cell(row_fr, disp: str, m: str, slot: str, editable: bool, pack_padx=(0, 0)):
            c = CTkFrame(row_fr, fg_color="transparent", width=col_w, height=45)
            c.pack(side="left", padx=pack_padx)
            c.pack_propagate(False)
            if editable:
                b_fg = INPUT
                b_hover = SEL_BG
                b_txt = TXT
                b_cursor = "hand2"
            else:
                b_fg = CARD
                b_hover = CARD
                b_txt = MUTED
                b_cursor = "arrow"

            b = CTkButton(
                c, text=disp or "—", width=108, height=28, corner_radius=6,
                font=("Segoe UI", 12, "bold"),
                fg_color=b_fg, hover_color=b_hover, text_color=b_txt,
            )
            b.pack(side="left")

            if editable:
                e_cmd = (lambda mi=m, sl=slot: self._on_shortcut_edit_click(mi, sl))
                e_text_color = TXT2
                e_fg = INPUT
                e_hover = SEL_BG
                e_cursor = "hand2"
            else:
                e_cmd = (lambda: None)
                e_text_color = MUTED
                e_fg = INPUT
                e_hover = INPUT
                e_cursor = "arrow"

            e = CTkButton(
                c, text=s("shortcuts.edit"), width=46, height=28, corner_radius=6,
                font=("Segoe UI", 12),
                fg_color=e_fg, hover_color=e_hover, text_color=e_text_color,
                command=e_cmd,
            )
            try:
                e.configure(cursor=e_cursor)
            except Exception:
                pass
            e.pack(side="left", padx=(4, 0))
            return b, e

        for idx, mode_id in enumerate(mode_order):
            if mode_id == "behavior":
                continue
            real_mode_id = mode_id
            if mode_id in ("answer_free", "answer_pro"):
                real_mode_id = "answer"
            mode = getattr(self, "orch", None) and getattr(self.orch, "modes", None) and self.orch.modes.get(real_mode_id)
            display_name = self._localized_mode_name(mode_id, mode)
            hk_main = hotkeys_cfg.get(real_mode_id, "")
            hk_altgr = hotkeys_cfg.get(real_mode_id + "_altgr", "")
            altgr_display = _format_display_hotkey(hk_altgr) if hk_altgr else _derive_altgr_display(hk_main)

            row = CTkFrame(inner, fg_color="transparent", height=45)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)

            # Plan gating for shortcut editing:
            # Free => only Alt+T (transcribe) and Alt+H (help) editable.
            editable = self._is_shortcut_editable_for_tier(real_mode_id)

            main_btn, main_edit = _cell(row, _format_display_hotkey(hk_main), real_mode_id, "main", editable=editable, pack_padx=(0, 0))
            altgr_btn, altgr_edit = _cell(row, altgr_display, real_mode_id, "altgr", editable=editable, pack_padx=(4, 0))
            self._shortcuts_hotkey_btns[mode_id] = {"main": (main_btn, main_edit), "altgr": (altgr_btn, altgr_edit)}

            mode_cell = CTkFrame(row, fg_color="transparent", width=col_w, height=45)
            mode_cell.pack(side="left")
            mode_cell.pack_propagate(False)
            mode_lbl = CTkLabel(mode_cell, text=display_name, font=("Segoe UI", 13), text_color=TXT)
            mode_lbl.place(relx=0.5, rely=0.5, anchor="center")

            if idx < len(mode_order) - 1:
                CTkFrame(inner, height=1, fg_color="#4A4A52").pack(fill="x", pady=(6, 6))

        # ─── Section Stop listening (éditable, même disposition que les modes) ───
        CTkFrame(inner, height=1, fg_color="#4A4A52").pack(fill="x", pady=(12, 6))
        mode_id = "stop_recording"
        hk_main = hotkeys_cfg.get(mode_id, "alt+q")
        hk_altgr = hotkeys_cfg.get(mode_id + "_altgr", "")
        altgr_display = _format_display_hotkey(hk_altgr) if hk_altgr else _derive_altgr_display(hk_main)
        row = CTkFrame(inner, fg_color="transparent", height=45)
        row.pack(fill="x", pady=0)
        row.pack_propagate(False)
        main_btn, main_edit = _cell(row, _format_display_hotkey(hk_main), mode_id, "main", editable=True, pack_padx=(0, 0))
        altgr_btn, altgr_edit = _cell(row, altgr_display, mode_id, "altgr", editable=True, pack_padx=(4, 0))
        self._shortcuts_hotkey_btns[mode_id] = {"main": (main_btn, main_edit), "altgr": (altgr_btn, altgr_edit)}
        mode_cell = CTkFrame(row, fg_color="transparent", width=col_w, height=45)
        mode_cell.pack(side="left")
        mode_cell.pack_propagate(False)
        CTkLabel(mode_cell, text=s("shortcuts.stop_task"), font=("Segoe UI", 13), text_color=TXT).place(relx=0.5, rely=0.5, anchor="center")

        CTkFrame(inner, height=1, fg_color="#4A4A52").pack(fill="x", pady=(12, 6))
        mode_id = "reinject_last"
        hk_main = hotkeys_cfg.get(mode_id, "alt+r")
        hk_altgr = hotkeys_cfg.get(mode_id + "_altgr", "")
        altgr_display = _format_display_hotkey(hk_altgr) if hk_altgr else _derive_altgr_display(hk_main)
        row = CTkFrame(inner, fg_color="transparent", height=45)
        row.pack(fill="x", pady=0)
        row.pack_propagate(False)
        main_btn, main_edit = _cell(row, _format_display_hotkey(hk_main), mode_id, "main", editable=True, pack_padx=(0, 0))
        altgr_btn, altgr_edit = _cell(row, altgr_display, mode_id, "altgr", editable=True, pack_padx=(4, 0))
        self._shortcuts_hotkey_btns[mode_id] = {"main": (main_btn, main_edit), "altgr": (altgr_btn, altgr_edit)}
        mode_cell = CTkFrame(row, fg_color="transparent", width=col_w, height=45)
        mode_cell.pack(side="left")
        mode_cell.pack_propagate(False)
        CTkLabel(mode_cell, text=s("shortcuts.reinject_last_task"), font=("Segoe UI", 13), text_color=TXT).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        # Hint when listening
        self._shortcuts_listen_hint = CTkLabel(pg, text="", font=("Segoe UI", 13), text_color=MUTED)
        self._shortcuts_listen_hint.pack(anchor="w", padx=(0, 28), pady=(4, 0))

        # Bottom buttons
        bot = CTkFrame(pg, fg_color="transparent")
        bot.pack(fill="x", padx=(0, 28), pady=(20, 30))
        restore_btn = CTkButton(
            bot,
            text=s("shortcuts.restore_defaults"),
            height=36,
            corner_radius=8,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            hover_color=SEL_BG,
            text_color=TXT,
            command=self._on_shortcuts_restore_default,
        )
        restore_btn.pack(side="left")
        CTkLabel(bot, text=s("shortcuts.restart_note"), font=("Segoe UI", 12), text_color=MUTED).pack(side="left", padx=(16, 0))

    def _mk_chat(self):
        """Page Chat + Help: one frame with two tabs. Chat = Alt+A conversation UI; Help = placeholder."""
        pg = CTkFrame(self.content, fg_color="transparent")
        pg.pack(fill="both", expand=True)
        self.pages["chat"] = pg
        self.pages["help"] = pg

        # Custom pill tabs (Chat / Help), to match design mock.
        pg.grid_columnconfigure(0, weight=1)
        pg.grid_rowconfigure(1, weight=1)

        rpad_chat = 34  # +30px right margin vs standard (requested)

        pills_row = CTkFrame(pg, fg_color="transparent")
        pills_row.grid(row=0, column=0, sticky="ew", padx=(16, rpad_chat), pady=(20, 10))
        pills_row.grid_columnconfigure(0, weight=1)

        # No stroke / no background block behind pills (match mock).
        pills = CTkFrame(pills_row, fg_color="transparent")
        pills.pack(side="left")

        self._chat_tab_caption = s("chat.title")
        self._help_tab_caption = s("help.title")

        def _pill_on(pid: str):
            self._go(pid)

        # Selected pill: subtle mauve (~10%) background, purple text.
        # NOTE: CustomTkinter doesn't support alpha; use a dark mauve blend.
        pill_selected_bg = "#2A2236"

        self._chat_pill_btn = CTkButton(
            pills,
            text=self._chat_tab_caption,
            width=90,
            height=30,
            corner_radius=14,
            font=("Segoe UI", 13, "bold"),
            fg_color=pill_selected_bg,
            hover_color=pill_selected_bg,
            text_color=ACCENT,
            command=lambda: _pill_on("chat"),
        )
        self._chat_pill_btn.pack(side="left", padx=(0, 10))
        self._help_pill_btn = CTkButton(
            pills,
            text=self._help_tab_caption,
            width=90,
            height=30,
            corner_radius=14,
            font=("Segoe UI", 13, "bold"),
            fg_color="transparent",
            hover_color=SEL_BG,
            text_color=TXT2,
            command=lambda: _pill_on("help"),
        )
        self._help_pill_btn.pack(side="left")

        # Content stack: show either Chat panel or Help panel (sidebar entries still separate).
        content = CTkFrame(pg, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(0, 20))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        chat_tab = CTkFrame(content, fg_color="transparent")
        help_tab = CTkFrame(content, fg_color="transparent")
        chat_tab.grid(row=0, column=0, sticky="nsew")
        help_tab.grid(row=0, column=0, sticky="nsew")
        self._chat_panel = chat_tab
        self._help_panel = help_tab

        # ─── Chat tab: row 0 = titre Chat (gauche) + New chat / Save log (droite, gris bordure) ───
        chat_tab.grid_columnconfigure(0, weight=1)
        chat_tab.grid_rowconfigure(3, weight=1)  # scroll messages

        top_row = CTkFrame(chat_tab, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=(16, rpad_chat), pady=(16, 8))
        top_row.grid_columnconfigure(0, weight=1)
        CTkLabel(top_row, text=self._chat_tab_caption, font=("Segoe UI", 18, "bold"), text_color=TXT).grid(row=0, column=0, sticky="w")
        act_fr = CTkFrame(top_row, fg_color="transparent")
        act_fr.grid(row=0, column=1, sticky="e")
        self._chat_new_btn = CTkButton(act_fr, text=s("chat.new_chat"), width=100, height=32, corner_radius=8, font=("Segoe UI", 13),
                  fg_color=CARD, hover_color=SEL_BG, text_color=TXT, border_width=1, border_color="#3A3A42",
                  command=self._on_chat_new)
        self._chat_new_btn.pack(side="left", padx=(0, 8))
        CTkButton(act_fr, text=s("chat.save_log"), width=100, height=32, corner_radius=8, font=("Segoe UI", 13),
                  fg_color=CARD, hover_color=SEL_BG, text_color=TXT, border_width=1, border_color="#3A3A42",
                  command=self._on_chat_save_log).pack(side="left")

        # Row 1: compact model line (green dot + name) + ctx usage (right)
        token_fr = CTkFrame(chat_tab, fg_color="transparent")
        token_fr.grid(row=1, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 8))
        token_fr.grid_columnconfigure(0, weight=1)
        left = CTkFrame(token_fr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        CTkLabel(left, text="●", font=("Segoe UI", 12), text_color="#22C55E").pack(side="left", padx=(0, 8))
        self._chat_model_lbl = CTkLabel(left, text="—", font=("Segoe UI", 12), text_color=MUTED)
        self._chat_model_lbl.pack(side="left")
        self._chat_token_lbl = CTkLabel(token_fr, text="—", font=("Segoe UI", 11), text_color=MUTED)
        self._chat_token_lbl.grid(row=0, column=1, sticky="e")

        # Row 2: Free-tier Ask notice — fixed above the scroll (not inside message list); shown when ≥2 Q/A in session
        self._chat_free_notice_fr = CTkFrame(chat_tab, fg_color="#2A2A32", corner_radius=8, border_width=1, border_color="#3F3F46")
        self._chat_free_notice_fr.grid_columnconfigure(0, weight=1)
        self._chat_free_notice_lbl = CTkLabel(
            self._chat_free_notice_fr,
            text=s("chat.free_answer_notice"),
            font=("Segoe UI", 12),
            text_color=TXT2,
            wraplength=520,
            justify="left",
        )
        self._chat_free_notice_lbl.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        self._chat_free_notice_fr.grid_remove()

        # Row 3: messages (scrollable si contenu, placeholder vide sinon pour ne pas afficher la scrollbar)
        self._chat_messages_placeholder = CTkFrame(chat_tab, fg_color=CONTENT)
        self._chat_messages_placeholder.grid(row=3, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))
        self._chat_messages_placeholder.grid_remove()
        self._chat_messages_inner = CTkScrollableFrame(chat_tab, fg_color=CONTENT, scrollbar_fg_color=CONTENT,
                                                       scrollbar_button_color=MUTED, scrollbar_button_hover_color=TXT2)
        self._chat_messages_inner.grid(row=3, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))
        self._chat_messages_inner.grid_columnconfigure(0, weight=1)
        self._chat_bubble_labels = []  # labels des bulles (contenu) pour mise à jour responsive du wraplength
        self._chat_messages_inner.bind("<Configure>", lambda e: self._update_chat_bubble_wraplengths())

        # Row 4: notice — questions about PerkySue / app → use Help tab
        chat_notice_fr = CTkFrame(chat_tab, fg_color="transparent")
        chat_notice_fr.grid(row=4, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 4))
        chat_notice_fr.grid_columnconfigure(0, weight=1)
        CTkLabel(chat_notice_fr, text=s("chat.help_redirect"),
                 font=("Segoe UI", 11), text_color=MUTED).grid(row=0, column=0, sticky="w")
        # Row 5: unified input bar (mic + entry + send inside one rounded box)
        input_outer = CTkFrame(chat_tab, fg_color="transparent")
        input_outer.grid(row=5, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 8))
        input_outer.grid_columnconfigure(0, weight=1)

        input_bar = CTkFrame(input_outer, fg_color=INPUT, corner_radius=12, border_width=1, border_color="#3A3A42")
        input_bar.grid(row=0, column=0, sticky="ew")
        input_bar.grid_columnconfigure(1, weight=1)

        self._chat_mic_btn = CTkButton(
            input_bar,
            text="🎤",
            width=42,
            height=56,
            corner_radius=10,
            font=("Segoe UI", 16),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            command=self._on_chat_mic,
        )
        self._chat_mic_btn.grid(row=0, column=0, padx=(8, 6), pady=6, sticky="w")

        self._chat_input = ctk.CTkEntry(
            input_bar,
            placeholder_text=s("chat.placeholder"),
            font=("Segoe UI", 14),
            height=56,
            fg_color=INPUT,
            border_width=0,
        )
        self._chat_input.grid(row=0, column=1, padx=(0, 10), pady=6, sticky="ew")
        self._chat_input.bind("<Return>", self._on_chat_send)

        self._chat_send_btn = CTkButton(
            input_bar,
            text="➤",
            width=54,
            height=56,
            corner_radius=12,
            font=("Segoe UI", 16),
            fg_color=INPUT,
            hover_color=SEL_BG,
            text_color=TXT,
            command=self._on_chat_send_click,
        )
        self._chat_send_btn.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="e")

        chat_bottom = CTkFrame(chat_tab, fg_color="transparent")
        chat_bottom.grid(row=6, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 16))
        chat_bottom.grid_columnconfigure(1, weight=1)
        self._chat_hint_lbl = CTkLabel(
            chat_bottom,
            text=s("chat.hint", default="Alt+A to speak · Enter to send · Alt+Q to stop"),
            font=("Segoe UI", 11),
            text_color=ACCENT,
        )
        self._chat_continuous_switch = CTkSwitch(
            chat_bottom,
            text=s("chat.continuous_label", default="Continuous Chat (beta)"),
            font=("Segoe UI", 12),
            text_color=TXT2,
            command=self._on_chat_continuous_toggle,
        )
        self._chat_continuous_switch.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self._chat_hint_lbl.grid(row=0, column=1, sticky="e")
        self._chat_hint_lbl.configure(anchor="e")

        # ─── Help tab: same layout as Chat, starts with PerkySue welcome (👋) ───
        help_tab.grid_columnconfigure(0, weight=1)
        help_tab.grid_rowconfigure(2, weight=1)
        help_top = CTkFrame(help_tab, fg_color="transparent")
        help_top.grid(row=0, column=0, sticky="ew", padx=(16, rpad_chat), pady=(16, 8))
        help_top.grid_columnconfigure(0, weight=1)
        CTkLabel(help_top, text=self._help_tab_caption, font=("Segoe UI", 18, "bold"), text_color=TXT).grid(row=0, column=0, sticky="w")
        help_act = CTkFrame(help_top, fg_color="transparent")
        help_act.grid(row=0, column=1, sticky="e")
        self._help_new_btn = CTkButton(help_act, text=s("help.new_chat"), width=100, height=32, corner_radius=8, font=("Segoe UI", 13),
                  fg_color=CARD, hover_color=SEL_BG, text_color=TXT, border_width=1, border_color="#3A3A42",
                  command=self._on_help_new)
        self._help_new_btn.pack(side="left", padx=(0, 8))
        CTkButton(help_act, text=s("help.save_log"), width=100, height=32, corner_radius=8, font=("Segoe UI", 13),
                  fg_color=CARD, hover_color=SEL_BG, text_color=TXT, border_width=1, border_color="#3A3A42",
                  command=self._on_help_save_log).pack(side="left")
        help_token_fr = CTkFrame(help_tab, fg_color="transparent")
        help_token_fr.grid(row=1, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 8))
        help_token_fr.grid_columnconfigure(0, weight=1)
        hleft = CTkFrame(help_token_fr, fg_color="transparent")
        hleft.grid(row=0, column=0, sticky="w")
        CTkLabel(hleft, text="●", font=("Segoe UI", 12), text_color="#22C55E").pack(side="left", padx=(0, 8))
        self._help_model_lbl = CTkLabel(hleft, text="—", font=("Segoe UI", 12), text_color=MUTED)
        self._help_model_lbl.pack(side="left")
        self._help_token_lbl = CTkLabel(help_token_fr, text="—", font=("Segoe UI", 11), text_color=MUTED)
        self._help_token_lbl.grid(row=0, column=1, sticky="e")
        self._help_messages_placeholder = CTkFrame(help_tab, fg_color=CONTENT)
        self._help_messages_placeholder.grid(row=2, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))
        self._help_messages_placeholder.grid_remove()
        self._help_messages_inner = CTkScrollableFrame(help_tab, fg_color=CONTENT, scrollbar_fg_color=CONTENT,
                                                       scrollbar_button_color=MUTED, scrollbar_button_hover_color=TXT2)
        self._help_messages_inner.grid(row=2, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))
        self._help_messages_inner.grid_columnconfigure(0, weight=1)
        self._help_bubble_labels = []
        self._help_messages_inner.bind("<Configure>", lambda e: self._update_help_bubble_wraplengths())
        help_input_outer = CTkFrame(help_tab, fg_color="transparent")
        help_input_outer.grid(row=3, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 8))
        help_input_outer.grid_columnconfigure(0, weight=1)

        help_input_bar = CTkFrame(help_input_outer, fg_color=INPUT, corner_radius=12, border_width=1, border_color="#3A3A42")
        help_input_bar.grid(row=0, column=0, sticky="ew")
        help_input_bar.grid_columnconfigure(1, weight=1)

        self._help_mic_btn = CTkButton(
            help_input_bar,
            text="🎤",
            width=42,
            height=56,
            corner_radius=10,
            font=("Segoe UI", 16),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            command=self._on_help_mic,
        )
        self._help_mic_btn.grid(row=0, column=0, padx=(8, 6), pady=6, sticky="w")

        self._help_input = ctk.CTkEntry(
            help_input_bar,
            placeholder_text=s("help.placeholder"),
            font=("Segoe UI", 14),
            height=56,
            fg_color=INPUT,
            border_width=0,
        )
        self._help_input.grid(row=0, column=1, padx=(0, 10), pady=6, sticky="ew")
        self._help_input.bind("<Return>", self._on_help_send)

        self._help_send_btn = CTkButton(
            help_input_bar,
            text="➤",
            width=54,
            height=56,
            corner_radius=12,
            font=("Segoe UI", 16),
            fg_color=INPUT,
            hover_color=SEL_BG,
            text_color=TXT,
            command=self._on_help_send_click,
        )
        self._help_send_btn.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="e")

        self._help_hint_lbl = CTkLabel(
            help_tab,
            text=s("help.hint", default="Alt+H to speak · Enter to send · Alt+Q to stop"),
            font=("Segoe UI", 11),
            text_color=ACCENT,
        )
        self._help_hint_lbl.grid(row=4, column=0, sticky="ew", padx=(16, rpad_chat), pady=(0, 16))
        self._help_hint_lbl.configure(anchor="center")
        # Initial welcome message from PerkySue (👋) is shown in _refresh_help_tab when history is empty
        self._refresh_help_tab()

    def _persist_tts_cfg(self):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if tts:
            self._save_config({"tts": tts.to_config_dict()})

    def _schedule_persist_tts_cfg(self, delay_ms: int = 450):
        """Évite d'écrire config.yaml à chaque pas du slider."""
        tid = getattr(self, "_tts_persist_after_id", None)
        if tid:
            try:
                self.root.after_cancel(tid)
            except Exception:
                pass
        self._tts_persist_after_id = self.root.after(delay_ms, self._persist_tts_cfg_run)

    def _persist_tts_cfg_run(self):
        self._tts_persist_after_id = None
        self._persist_tts_cfg()

    def _voice_apply_inner_wrap(self, inner, *labels):
        """CTkScrollableFrame + wraplength fixe → texte rogné ; caler wraplength sur la largeur réelle (comme Identity)."""
        try:
            w = inner.winfo_width()
            if w < 80:
                return
            wl = max(220, w - 32)
            for lb in labels:
                if lb is None:
                    continue
                try:
                    if lb.winfo_exists():
                        lb.configure(wraplength=wl)
                except Exception:
                    pass
        except Exception:
            pass

    def _voice_pack_engine_action_buttons(self, show_retry: bool, show_pytorch: bool):
        """Pack order (right side of engine row): [status][PyTorch CUDA?][Retry?]."""
        for w in (
            getattr(self, "_voice_engine_retry_btn", None),
            getattr(self, "_voice_pytorch_cuda_btn", None),
            getattr(self, "_voice_engine_status", None),
        ):
            if w is None:
                continue
            try:
                w.pack_forget()
            except Exception:
                pass
        if show_retry and getattr(self, "_voice_engine_retry_btn", None):
            self._voice_engine_retry_btn.pack(side="right", padx=(8, 0))
        if show_pytorch and getattr(self, "_voice_pytorch_cuda_btn", None):
            self._voice_pytorch_cuda_btn.pack(side="right", padx=(8, 0))
        if getattr(self, "_voice_engine_status", None):
            self._voice_engine_status.pack(side="right")

    def _open_voice_pytorch_cuda_prompt_dialog(self, tts):
        """Custom modal (same chrome as Plan → link subscription): Yes/No row + full-width never-ask."""
        if not tts:
            return
        if getattr(self, "_voice_pytorch_cuda_prompt_dlg", None):
            try:
                if self._voice_pytorch_cuda_prompt_dlg.winfo_exists():
                    self._voice_pytorch_cuda_prompt_dlg.lift()
                    return
            except Exception:
                pass

        link_gold = SKIN_SELECTED_BORDER
        link_gold_hover = "#d9a60f"
        inner_pad = 16
        content_pad_top = inner_pad + 5
        title = s("voice.pytorch_cuda.dialog_title", default="Accelerate text-to-speech (GPU)")
        body = s(
            "voice.pytorch_cuda.dialog_body",
            default=s(
                "voice.pytorch_cuda.dialog_message",
                default=(
                    "PerkySue's Python has a CPU-only PyTorch build, so Chatterbox and OmniVoice "
                    "cannot use your NVIDIA GPU. Whisper and the LLM server are unchanged.\n\n"
                    "Install CUDA-enabled PyTorch now? Large download (~2+ GB); may take several minutes — stay online."
                ),
            ),
        )

        dlg = CTkToplevel(self.root)
        self._voice_pytorch_cuda_prompt_dlg = dlg
        dlg.title(title)
        dlg.geometry("440x300")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        try:
            dlg.configure(fg_color=BG)
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

        def _close():
            try:
                dlg.destroy()
            except Exception:
                pass
            self._voice_pytorch_cuda_prompt_dlg = None

        def _center():
            try:
                dlg.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                x = max(20, rx + (rw - dw) // 2)
                y = max(20, ry + 52)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

        def _on_yes():
            _close()
            self._voice_start_pytorch_cuda_install(tts)

        def _on_no():
            _close()

        def _on_never():
            tts.pytorch_cuda_offer_never = True
            self._schedule_persist_tts_cfg()
            _close()
            try:
                self.root.after(0, self._refresh_voice_tab)
            except Exception:
                pass

        try:
            dlg.protocol("WM_DELETE_WINDOW", _on_no)
        except Exception:
            pass

        shell = CTkFrame(dlg, fg_color=CARD, corner_radius=18, border_width=2, border_color=link_gold)
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        content = CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=inner_pad, pady=(content_pad_top, inner_pad))

        headline_lbl = CTkLabel(
            content,
            text=title,
            font=("Segoe UI", 18, "bold"),
            text_color=TXT,
            anchor="center",
            justify="center",
        )
        headline_lbl.pack(fill="x", pady=(0, 12))
        body_lbl = CTkLabel(
            content,
            text=body,
            font=("Segoe UI", 13),
            text_color=TXT,
            justify="center",
            anchor="center",
            wraplength=390,
        )
        body_lbl.pack(fill="x", pady=(0, 18))

        btn_row = CTkFrame(content, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 10))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        yes_btn = CTkButton(
            btn_row,
            text=s("voice.pytorch_cuda.btn_yes", default="Yes, install"),
            font=("Segoe UI", 13, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=40,
            corner_radius=10,
            command=_on_yes,
        )
        yes_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        no_btn = CTkButton(
            btn_row,
            text=s("voice.pytorch_cuda.btn_no", default="Not now"),
            font=("Segoe UI", 12, "bold"),
            fg_color="transparent",
            hover_color=SEL_BG,
            text_color=link_gold,
            height=40,
            corner_radius=10,
            border_width=1,
            border_color=link_gold,
            command=_on_no,
        )
        no_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        never_btn = CTkButton(
            content,
            text=s("voice.pytorch_cuda.btn_never_ask", default="Don't ask again"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
            command=_on_never,
        )
        never_btn.pack(fill="x")

        dlg.after(10, _center)

    def _open_gold_shell_ok_modal(self, title: str, message: str, *, is_error: bool = False) -> None:
        """Same chrome as Plan → link subscription / PyTorch CUDA prompt: gold frame, one OK (no system messagebox)."""
        attr = "_voice_pytorch_result_dlg"
        prev = getattr(self, attr, None)
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.destroy()
            except Exception:
                pass
            setattr(self, attr, None)

        link_gold = SKIN_SELECTED_BORDER
        link_gold_hover = "#d9a60f"
        inner_pad = 16
        content_pad_top = inner_pad + 5
        body_color = "#F87171" if is_error else TXT

        dlg = CTkToplevel(self.root)
        setattr(self, attr, dlg)
        dlg.title(title)
        _h = 300 if is_error and len(message or "") > 220 else 260
        dlg.geometry(f"440x{_h}")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        try:
            dlg.configure(fg_color=BG)
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

        def _close():
            try:
                dlg.destroy()
            except Exception:
                pass
            setattr(self, attr, None)

        def _center():
            try:
                dlg.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                x = max(20, rx + (rw - dw) // 2)
                y = max(20, ry + 52)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

        try:
            dlg.protocol("WM_DELETE_WINDOW", _close)
        except Exception:
            pass

        shell = CTkFrame(dlg, fg_color=CARD, corner_radius=18, border_width=2, border_color=link_gold)
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        content = CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=inner_pad, pady=(content_pad_top, inner_pad))

        CTkLabel(
            content,
            text=title,
            font=("Segoe UI", 18, "bold"),
            text_color=TXT,
            anchor="center",
            justify="center",
        ).pack(fill="x", pady=(0, 12))
        CTkLabel(
            content,
            text=message,
            font=("Segoe UI", 13),
            text_color=body_color,
            justify="center",
            anchor="center",
            wraplength=390,
        ).pack(fill="x", pady=(0, 18))

        CTkButton(
            content,
            text=s("voice.pytorch_cuda.modal_ok", default="OK"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
            command=_close,
        ).pack(fill="x")

        dlg.after(10, _center)

    def _voice_maybe_prompt_pytorch_cuda(self, tts):
        self._voice_pytorch_cuda_prompt_pending = False
        if getattr(self, "_voice_pytorch_cuda_auto_prompt_done_this_visit", True):
            return
        self._voice_pytorch_cuda_auto_prompt_done_this_visit = True
        if not tts or not getattr(tts, "_pytorch_cuda_install_recommended", False):
            return
        if getattr(tts, "pytorch_cuda_offer_never", False):
            return
        try:
            self._open_voice_pytorch_cuda_prompt_dialog(tts)
        except Exception:
            pass

    def _voice_start_pytorch_cuda_install(self, tts):
        url = getattr(tts, "_pytorch_cuda_install_index_url", None) if tts else None
        if not url or not tts:
            return
        if tts.installer.is_running:
            return

        prog_name = s("voice.pytorch_cuda.progress_name", default="PyTorch CUDA")

        def on_progress(_state, pct, msg):
            def u():
                try:
                    self._voice_engine_status.configure(
                        text=("⏳ " + (msg or ""))[:140],
                        text_color="#F59E0B",
                    )
                    self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=False)
                except Exception:
                    pass
                try:
                    p = int(pct) if pct is not None else 0
                    tpl = self._get_alert("regular.pytorch_cuda_progress")
                    self._set_header_title_text(tpl.format(name=prog_name, pct=max(0, min(100, p))))
                    self._update_download_progress_ui(max(0, min(100, p)), prog_name)
                except Exception:
                    pass

            try:
                self.root.after(0, u)
            except Exception:
                pass

        def on_done(success, err):
            def fin():
                try:
                    self._set_header_title_text(getattr(self, "_hdr_normal_text", "PerkySue"))
                except Exception:
                    pass
                if success:
                    try:
                        self._trigger_save(scroll_to_bottom=False)
                        self._save_note.configure(
                            text=s(
                                "voice.pytorch_cuda.restart_sidebar_note",
                                default="Restart PerkySue to load the new PyTorch (CUDA).",
                            )
                        )
                    except Exception:
                        pass
                    try:
                        self._open_gold_shell_ok_modal(
                            s("voice.pytorch_cuda.done_title", default="PyTorch"),
                            s("voice.pytorch_cuda.done_message", default=""),
                            is_error=False,
                        )
                    except Exception:
                        pass
                else:
                    try:
                        self._open_gold_shell_ok_modal(
                            s("voice.pytorch_cuda.error_title", default="Install failed"),
                            (err or "")[:900],
                            is_error=True,
                        )
                    except Exception:
                        pass
                try:
                    self._refresh_voice_tab()
                except Exception:
                    pass

            try:
                self.root.after(0, fin)
            except Exception:
                pass

        try:
            self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=False)
            self._voice_engine_status.configure(
                text="⏳ " + s("voice.pytorch_cuda.progress_start", default="Installing PyTorch CUDA…"),
                text_color="#F59E0B",
            )
            tpl0 = self._get_alert("regular.pytorch_cuda_progress")
            self._set_header_title_text(tpl0.format(name=prog_name, pct=0))
            self._update_download_progress_ui(0, prog_name)
        except Exception:
            pass
        tts.installer.install_pytorch_cuda(url, on_progress=on_progress, on_done=on_done)

    def _on_voice_install_pytorch_cuda(self):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if not tts:
            return
        self._voice_start_pytorch_cuda_install(tts)

    def _mk_voice(self):
        """Onglet Voice — même gabarit que User / Settings : titres de section 20 bold, cartes CARD, libellés 13 comme Identity."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["voice"] = pg
        try:
            c = pg._parent_canvas

            def _wheel_fast(e, frame=pg):
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    canv.yview("scroll", u, "units")
                return "break"

            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass

        rpad = (0, 28)
        tts0 = getattr(getattr(self, "orch", None), "tts_manager", None)
        meta = tts0.get_engine_meta() if tts0 else {}
        self._voice_engine_meta_name = meta.get("name", "Chatterbox Turbo")

        # ─── État Free ─────────────────────────────────────────────
        self._voice_locked = CTkFrame(pg, fg_color="transparent")
        CTkLabel(
            self._voice_locked,
            text=s("voice.locked.section_title", default="Text-to-speech"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        lock_card = CTkFrame(self._voice_locked, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        lock_card.pack(fill="x", pady=(0, 20), padx=rpad)
        lock_inner = CTkFrame(lock_card, fg_color="transparent")
        lock_inner.pack(fill="x", padx=20, pady=16)
        lock_inner.grid_columnconfigure(0, weight=1)
        self._voice_locked_body_lbl = CTkLabel(
            lock_inner,
            text=s("voice.locked.body", default=""),
            font=("Segoe UI", 13),
            text_color=TXT,
            justify="left",
            anchor="w",
        )
        self._voice_locked_body_lbl.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        CTkLabel(
            lock_inner,
            text=s("voice.locked.pro_note", default="Available with Pro"),
            font=("Segoe UI", 13),
            text_color=GOLD,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))
        CTkButton(
            lock_inner,
            text=s("voice.locked.upgrade", default="Upgrade to Pro"),
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            height=40,
            corner_radius=8,
            width=200,
            command=lambda: self._go("settings"),
        ).grid(row=2, column=0, sticky="", pady=(0, 0))
        lock_inner.bind(
            "<Configure>",
            lambda e: self._voice_apply_inner_wrap(lock_inner, self._voice_locked_body_lbl),
        )

        # ─── État Pro : install moteur ─────────────────────────────
        self._voice_install = CTkFrame(pg, fg_color="transparent")
        CTkLabel(
            self._voice_install,
            text=s("voice.install.section_title", default="Add a voice to PerkySue"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        inst_card = CTkFrame(self._voice_install, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        inst_card.pack(fill="x", pady=(0, 20), padx=rpad)
        inst_inner = CTkFrame(inst_card, fg_color="transparent")
        inst_inner.pack(fill="x", padx=20, pady=16)
        self._voice_install_inner = inst_inner
        inst_inner.grid_columnconfigure(1, weight=1)

        self._voice_install_body_lbl = CTkLabel(
            inst_inner,
            text=s("voice.install.body", default=""),
            font=("Segoe UI", 13),
            text_color=TXT,
            justify="left",
            anchor="w",
        )
        self._voice_install_body_lbl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        try:
            from ..services.tts.manager import TTSManager as _VoiceTTSManager
        except ImportError:
            try:
                from App.services.tts.manager import TTSManager as _VoiceTTSManager
            except ImportError:
                _VoiceTTSManager = None
        _known_pairs = list(_VoiceTTSManager.KNOWN_ENGINES.items()) if _VoiceTTSManager else []
        try:
            from ..services.tts.pytorch_cuda import nvidia_gpu_likely_present as _nv_tts_probe
        except ImportError:
            try:
                from App.services.tts.pytorch_cuda import nvidia_gpu_likely_present as _nv_tts_probe
            except ImportError:
                def _nv_tts_probe():
                    return False
        try:
            _nvidia_voice_menu = bool(_nv_tts_probe())
        except Exception:
            _nvidia_voice_menu = False
        _rec_suffix = (
            s("voice.engine.recommended_suffix", default=" (recommended)")
            if _nvidia_voice_menu
            else ""
        )
        self._voice_engine_id_by_display = {}
        self._voice_engine_display_by_id = {}
        _model_opts = []
        if _known_pairs:
            for eid, meta in _known_pairs:
                base = meta.get("name", "?")
                label = f"{base}{_rec_suffix}" if (eid == "omnivoice" and _rec_suffix) else base
                _model_opts.append(label)
                self._voice_engine_id_by_display[label] = eid
                self._voice_engine_display_by_id[eid] = label
        if not _model_opts:
            _model_opts = ["Chatterbox Turbo"]
            self._voice_engine_id_by_display = {"Chatterbox Turbo": "chatterbox"}
            self._voice_engine_display_by_id = {"chatterbox": "Chatterbox Turbo"}
        tts0 = getattr(getattr(self, "orch", None), "tts_manager", None)
        _cfg_eng = str(
            getattr(tts0, "preferred_engine_id", None)
            or (self.cfg.get("tts") or {}).get("engine")
            or "chatterbox",
        ).strip().lower()
        if _VoiceTTSManager and _cfg_eng in _VoiceTTSManager.KNOWN_ENGINES:
            _init_name = self._voice_engine_display_by_id.get(_cfg_eng) or _VoiceTTSManager.KNOWN_ENGINES[
                _cfg_eng
            ].get("name", _model_opts[0])
        else:
            _init_name = _model_opts[0]
        self._voice_model_var = ctk.StringVar(value=_init_name)
        # Même rangée que Settings → Performance : icône, libellé 14, menu 220 à droite
        model_row = CTkFrame(inst_inner, fg_color="transparent")
        model_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        CTkLabel(model_row, text="🗣️", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(
            side="left", padx=(0, 10),
        )
        CTkLabel(
            model_row,
            text=s("voice.install.model_label", default="Choose a model"),
            font=("Segoe UI", 14),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_model_menu = CTkOptionMenu(
            model_row,
            variable=self._voice_model_var,
            values=_model_opts,
            width=220,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            button_color=SIDEBAR,
            button_hover_color=SEL_BG,
            command=self._on_voice_model_selected,
        )
        self._voice_model_menu.pack(side="right")

        self._voice_install_meta_lbl = CTkLabel(
            inst_inner,
            text="",
            font=("Segoe UI", 11),
            text_color=TXT2,
            justify="left",
            anchor="w",
        )
        self._voice_install_meta_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self._voice_chatterbox_warn_lbl = CTkLabel(
            inst_inner,
            text="",
            font=("Segoe UI", 11),
            text_color="#F59E0B",
            justify="left",
            anchor="w",
        )
        self._voice_chatterbox_warn_lbl.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        btn_wrap = CTkFrame(inst_inner, fg_color="transparent")
        btn_wrap.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        btn_wrap.grid_columnconfigure(0, weight=1)
        btn_wrap.grid_columnconfigure(1, weight=0)
        btn_wrap.grid_columnconfigure(2, weight=1)
        self._voice_install_btn = CTkButton(
            btn_wrap,
            text=s("voice.install.button", default="Install engine"),
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            height=40,
            corner_radius=8,
            width=220,
            command=self._on_voice_install,
        )
        self._voice_install_btn.grid(row=0, column=1)
        self._voice_progress_frame = CTkFrame(inst_inner, fg_color="transparent")
        self._voice_progress_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._voice_progress_frame.grid_remove()
        self._voice_progress_bar = CTkProgressBar(
            self._voice_progress_frame, mode="indeterminate", height=6, corner_radius=3,
        )
        self._voice_progress_bar.pack(fill="x", pady=(0, 6))
        self._voice_progress_label = CTkLabel(
            self._voice_progress_frame, text="", font=("Segoe UI", 11), text_color=TXT2, anchor="w",
        )
        self._voice_progress_label.pack(anchor="w")
        inst_inner.bind(
            "<Configure>",
            lambda e: self._voice_apply_inner_wrap(
                inst_inner,
                self._voice_install_body_lbl,
                self._voice_install_meta_lbl,
                self._voice_chatterbox_warn_lbl,
            ),
        )

        # ─── État Pro : prêt (sections comme User) ─────────────────
        self._voice_ready = CTkFrame(pg, fg_color="transparent")

        CTkLabel(
            self._voice_ready,
            text=s("voice.output.section_title", default="Output"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        out_card = CTkFrame(self._voice_ready, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        out_card.pack(fill="x", pady=(0, 20), padx=rpad)
        out_inner = CTkFrame(out_card, fg_color="transparent")
        out_inner.pack(fill="x", padx=20, pady=16)

        row_en = CTkFrame(out_inner, fg_color="transparent")
        row_en.pack(fill="x", pady=(0, 12))
        CTkLabel(row_en, text="🔊", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            row_en,
            text=s("voice.output.enabled", default="Enabled"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_enabled_switch = CTkSwitch(
            row_en,
            text="",
            font=("Segoe UI", 13),
            text_color=TXT2,
            command=self._on_voice_toggle,
        )
        self._voice_enabled_switch.pack(side="right")

        row_eng = CTkFrame(out_inner, fg_color="transparent")
        row_eng.pack(fill="x", pady=(0, 0))
        CTkLabel(row_eng, text="⚙", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            row_eng,
            text=s("voice.output.engine_label", default="Engine"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 10))
        self._voice_engine_name_lbl = CTkLabel(
            row_eng,
            text=self._voice_engine_meta_name,
            font=("Segoe UI", 13),
            text_color=TXT,
        )
        self._voice_engine_name_lbl.pack(side="left", padx=(0, 12))
        eng_right = CTkFrame(row_eng, fg_color="transparent")
        eng_right.pack(side="right")
        self._voice_engine_retry_btn = CTkButton(
            eng_right,
            text=s("voice.output.retry_engine", default="Retry load"),
            width=88,
            height=28,
            font=("Segoe UI", 12),
            fg_color="#3A3A42",
            hover_color="#4B4B55",
            command=self._on_voice_retry_engine,
        )
        self._voice_pytorch_cuda_btn = CTkButton(
            eng_right,
            text=s("voice.pytorch_cuda.button", default="Install PyTorch CUDA"),
            width=148,
            height=28,
            font=("Segoe UI", 12),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self._on_voice_install_pytorch_cuda,
        )
        self._voice_engine_status = CTkLabel(
            eng_right,
            text="",
            font=("Segoe UI", 13),
            text_color=TXT2,
            anchor="e",
            wraplength=220,
            justify="right",
        )
        self._voice_pytorch_cuda_auto_prompt_done_this_visit = True
        self._voice_pytorch_cuda_prompt_pending = False
        self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=False)

        row_eng2 = CTkFrame(out_inner, fg_color="transparent")
        row_eng2.pack(fill="x", pady=(8, 8))
        CTkLabel(row_eng2, text="🔁", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(
            side="left", padx=(0, 10),
        )
        CTkLabel(
            row_eng2,
            text=s("voice.output.engine_switch_label", default="TTS engine"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_ready_engine_menu = CTkOptionMenu(
            row_eng2,
            variable=self._voice_model_var,
            values=_model_opts,
            width=220,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            button_color=SIDEBAR,
            button_hover_color=SEL_BG,
            command=self._on_voice_model_selected,
        )
        self._voice_ready_engine_menu.pack(side="right")

        self._voice_ready_perf_warn_fr = CTkFrame(out_inner, fg_color="transparent")
        self._voice_ready_perf_warn_fr.pack(fill="x", pady=(0, 4))
        self._voice_ready_perf_warn_lbl = CTkLabel(
            self._voice_ready_perf_warn_fr,
            text="",
            font=("Segoe UI", 11),
            text_color="#F59E0B",
            justify="left",
            anchor="w",
        )

        self._voice_omni_fr = CTkFrame(out_inner, fg_color="transparent")
        omni_inner = CTkFrame(self._voice_omni_fr, fg_color="transparent")
        omni_inner.pack(fill="x", pady=(0, 4))
        CTkLabel(
            omni_inner,
            text=s("voice.omnivoice.section_title", default="OmniVoice"),
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(0, 8))
        # OmniVoice: clone-only for now (design mode hidden until ready).
        try:
            if getattr(self.orch, "tts_manager", None):
                self.orch.tts_manager.omnivoice_mode = "clone"
        except Exception:
            pass
        CTkLabel(
            omni_inner,
            text=s("voice.omnivoice.mode_clone", default="Clone"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(anchor="w", pady=(0, 8))
        _sl = [
            s("voice.omnivoice.steps_16", default="16"),
            s("voice.omnivoice.steps_32", default="32"),
            s("voice.omnivoice.steps_48", default="48"),
        ]
        self._voice_omni_steps_to_n = {_sl[0]: 16, _sl[1]: 32, _sl[2]: 48}
        self._voice_omni_n_to_steps = {v: k for k, v in self._voice_omni_steps_to_n.items()}
        try:
            _sn = int((self.cfg.get("tts") or {}).get("omnivoice_num_step") or 32)
        except (TypeError, ValueError):
            _sn = 32
        if _sn <= 20:
            _sn_l = _sl[0]
        elif _sn <= 40:
            _sn_l = _sl[1]
        else:
            _sn_l = _sl[2]
        step_row = CTkFrame(omni_inner, fg_color="transparent")
        step_row.pack(fill="x", pady=(0, 0))
        CTkLabel(
            step_row,
            text=s("voice.omnivoice.steps_label", default="Quality / speed"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_omni_steps_menu = CTkOptionMenu(
            step_row,
            values=_sl,
            width=200,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            button_color=SIDEBAR,
            button_hover_color=SEL_BG,
            command=self._on_voice_omni_steps_change,
        )
        self._voice_omni_steps_menu.set(_sn_l)
        self._voice_omni_steps_menu.pack(side="right")
        self._voice_omni_fr.pack(fill="x", pady=(0, 8))
        self._voice_omni_fr.pack_forget()

        CTkLabel(
            self._voice_ready,
            text=s("voice.playback.section_title", default="Playback"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        play_card = CTkFrame(self._voice_ready, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        play_card.pack(fill="x", pady=(0, 20), padx=rpad)
        play_inner = CTkFrame(play_card, fg_color="transparent")
        play_inner.pack(fill="x", padx=20, pady=16)

        vol_row = CTkFrame(play_inner, fg_color="transparent")
        vol_row.pack(fill="x", pady=(0, 12))
        vol_row.grid_columnconfigure(1, weight=1)
        CTkLabel(
            vol_row,
            text=s("voice.playback.volume", default="Volume"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._voice_vol_label = CTkLabel(vol_row, text="80%", font=("Segoe UI", 13), text_color=TXT2, width=44)
        self._voice_vol_label.grid(row=0, column=2, sticky="e")
        self._voice_vol_slider = CTkSlider(
            vol_row, from_=0, to=100, number_of_steps=20, command=self._on_voice_volume,
        )
        self._voice_vol_slider.set(80)
        self._voice_vol_slider.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        spd_row = CTkFrame(play_inner, fg_color="transparent")
        spd_row.pack(fill="x", pady=(0, 12))
        spd_row.grid_columnconfigure(1, weight=1)
        CTkLabel(
            spd_row,
            text=s("voice.playback.speed", default="Speed"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._voice_spd_label = CTkLabel(spd_row, text="1.0x", font=("Segoe UI", 13), text_color=TXT2, width=44)
        self._voice_spd_label.grid(row=0, column=2, sticky="e")
        self._voice_spd_slider = CTkSlider(
            spd_row, from_=50, to=200, number_of_steps=30, command=self._on_voice_speed,
        )
        self._voice_spd_slider.set(100)
        self._voice_spd_slider.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        auto_row = CTkFrame(play_inner, fg_color="transparent")
        auto_row.pack(fill="x", pady=(0, 0))
        CTkLabel(auto_row, text="🔔", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            auto_row,
            text=s("voice.playback.auto_speak", default="Auto-speak"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_auto_switch = CTkSwitch(
            auto_row,
            text=s("voice.playback.auto_speak_hint", default="After Answer and Help modes"),
            font=("Segoe UI", 13),
            text_color=TXT2,
            command=self._on_voice_auto_toggle,
        )
        self._voice_auto_switch.pack(side="right")

        vp_row = CTkFrame(play_inner, fg_color="transparent")
        vp_row.pack(fill="x", pady=(12, 0))
        CTkLabel(vp_row, text="🗣️", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            vp_row,
            text=s("voice.playback.voice_payload", default="Payload layout (PS_PAYLOAD)"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_payload_switch = CTkSwitch(
            vp_row,
            text=s("voice.playback.voice_payload_hint", default="Inject only <PS_PAYLOAD> when Voice is on (see voice_modes.yaml)"),
            font=("Segoe UI", 13),
            text_color=TXT2,
            command=self._on_voice_payload_toggle,
        )
        self._voice_payload_switch.pack(side="right")

        rap_row = CTkFrame(play_inner, fg_color="transparent")
        rap_row.pack(fill="x", pady=(8, 0))
        CTkLabel(rap_row, text="📢", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(
            rap_row,
            text=s("voice.playback.read_aloud_payload", default="Read payload aloud"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(side="left", padx=(0, 12))
        self._voice_read_payload_switch = CTkSwitch(
            rap_row,
            text=s("voice.playback.read_aloud_payload_hint", default="TTS also speaks injectable text (default: spoken wrapper only)"),
            font=("Segoe UI", 13),
            text_color=TXT2,
            command=self._on_voice_read_payload_toggle,
        )
        self._voice_read_payload_switch.pack(side="right")

        CTkLabel(
            self._voice_ready,
            text=s("voice.packs.section_title", default="Voice packs"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        packs_card = CTkFrame(self._voice_ready, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        packs_card.pack(fill="x", pady=(0, 20), padx=rpad)
        packs_inner = CTkFrame(packs_card, fg_color="transparent")
        packs_inner.pack(fill="x", padx=20, pady=16)
        packs_inner.grid_columnconfigure(0, weight=1)
        self._voice_packs_label = CTkLabel(
            packs_inner,
            text=s("voice.packs.default_body", default=""),
            font=("Segoe UI", 11),
            text_color=TXT2,
            justify="left",
            anchor="w",
        )
        self._voice_packs_label.grid(row=0, column=0, sticky="ew")
        packs_inner.bind(
            "<Configure>",
            lambda e: self._voice_apply_inner_wrap(packs_inner, self._voice_packs_label),
        )

        CTkLabel(
            self._voice_ready,
            text=s("voice.test.section_title", default="Test"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
        ).pack(anchor="w", pady=(20, 10), padx=(0, 28))
        test_card = CTkFrame(self._voice_ready, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        test_card.pack(fill="x", pady=(0, 28), padx=rpad)
        test_inner = CTkFrame(test_card, fg_color="transparent")
        test_inner.pack(fill="x", padx=20, pady=16)
        CTkLabel(
            test_inner,
            text=s("voice.test.field_label", default="Sample phrase"),
            font=("Segoe UI", 13),
            text_color=TXT,
        ).pack(anchor="w", pady=(0, 6))
        self._voice_test_input = CTkTextbox(
            test_inner, height=72, font=("Segoe UI", 13),
            fg_color=INPUT, text_color=TXT, corner_radius=8, border_color="#3A3A42", border_width=1,
        )
        self._voice_test_input.pack(fill="x", pady=(0, 12))
        self._voice_test_input.insert("0.0", s("voice.test.sample_text", default="Hello! This is a test of PerkySue text-to-speech."))
        btn_row = CTkFrame(test_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 0))
        self._voice_speak_btn = CTkButton(
            btn_row,
            text=s("voice.test.speak", default="▶  Speak"),
            font=("Segoe UI", 13, "bold"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            height=36,
            corner_radius=8,
            width=120,
            command=self._on_voice_test_speak,
        )
        self._voice_speak_btn.pack(side="left")
        self._voice_stop_btn = CTkButton(
            btn_row,
            text=s("voice.test.stop", default="■  Stop"),
            font=("Segoe UI", 13),
            fg_color=INPUT,
            hover_color=SEL_BG,
            height=36,
            corner_radius=8,
            width=100,
            command=self._on_voice_test_stop,
        )
        self._voice_stop_btn.pack(side="left", padx=(8, 0))
        self._voice_test_status = CTkLabel(btn_row, text="", font=("Segoe UI", 11), text_color=TXT2, anchor="e")
        self._voice_test_status.pack(side="right")

        self._on_voice_model_selected()

    def _mk_avatar_editor(self):
        """Avatar Editor — actif seulement si Data/Plugins/avatar_editor (manifest enabled)."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["avatar_editor"] = pg
        try:
            c = pg._parent_canvas

            def _wheel_fast(e, frame=pg):
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    canv.yview("scroll", u, "units")
                return "break"

            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass
        try:
            from .avatar_editor_page import mount_avatar_editor_page
        except ImportError:
            from App.gui.avatar_editor_page import mount_avatar_editor_page

        self._avatar_editor_ui = mount_avatar_editor_page(self, pg)

    def _brainstorm_list_skins(self) -> list[dict]:
        out: list[dict] = []
        paths = getattr(self, "paths", None)
        try:
            for skin in discover_skins(paths):
                sid = str(skin.get("id") or "").strip()
                if not sid:
                    continue
                char = str(skin.get("name") or "").strip()
                loc = str(skin.get("lang") or "").strip()
                sid_canon = normalize_skin_id(paths, sid) if paths is not None else sid
                pers_path: Optional[str] = None
                if paths is not None:
                    char_root = resolve_character_root(paths, sid_canon)
                    if char_root is not None:
                        p_yaml = _find_tts_personality_yaml(char_root)
                        if p_yaml is not None:
                            pers_path = str(p_yaml)
                    if pers_path is None:
                        loc_dir = resolve_locale_skin_dir(paths, sid_canon)
                        if loc_dir is not None:
                            p_yaml = _find_tts_personality_yaml(loc_dir)
                            if p_yaml is not None:
                                pers_path = str(p_yaml)
                out.append(
                    {
                        "id": sid,
                        "character": char,
                        "locale": loc,
                        "display_name": sid,
                        "personality_yaml_path": pers_path,
                    }
                )
        except Exception:
            return []
        return out

    def _brainstorm_invoke_llm(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 400,
        mode_hint: str = "brainstorm",
    ) -> str:
        orch = getattr(self, "orch", None)
        if orch is None or not getattr(orch, "llm", None) or not orch.llm.is_available():
            raise RuntimeError("LLM unavailable")
        if hasattr(orch, "is_effective_pro") and not bool(orch.is_effective_pro()):
            raise PermissionError("Brainstorm is Pro-only")
        if getattr(orch, "_cancel_requested", False):
            raise RuntimeError("brainstorm_llm_cancelled")
        result = orch._run_llm_on_main_thread(
            text=str(user or ""),
            system_prompt=str(system or ""),
            temperature=0.6,
            max_tokens=max(64, min(int(max_tokens or 400), 1024)),
            gui_debug_label=f"plugin:{mode_hint}",
        )
        if getattr(orch, "_cancel_requested", False):
            raise RuntimeError("brainstorm_llm_cancelled")
        text = getattr(result, "text", "") if result is not None else ""
        return str(text or "").strip()

    def _mk_brainstorm(self):
        """Brainstorm plugin page — mounted only when plugin is present + enabled + Pro."""
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["brainstorm"] = pg
        orch = getattr(self, "orch", None)
        if orch is None:
            return
        try:
            mod = orch._load_brainstorm_plugin()
            if mod is None:
                return
            register_gui = getattr(mod, "register_gui", None)
            if not callable(register_gui):
                return
            ctx = PluginHostContext(
                paths=getattr(orch, "paths", None),
                get_orchestrator=lambda: getattr(self, "orch", None),
                invoke_llm=self._brainstorm_invoke_llm,
                list_skins=self._brainstorm_list_skins,
                emit_progress=lambda _event: None,
                is_effective_pro=lambda: bool(getattr(self, "orch", None) and self.orch.is_effective_pro()),
            )
            spec = register_gui(ctx) or {}
            factory = spec.get("page_factory")
            if not callable(factory):
                return
            self._brainstorm_gui_spec = spec
            self._brainstorm_ui = factory(pg)
        except Exception:
            logging.getLogger("perkysue").exception("Brainstorm plugin mount failed")

    @staticmethod
    def _voice_tts_manager_class():
        try:
            from ..services.tts.manager import TTSManager as _M
            return _M
        except ImportError:
            try:
                from App.services.tts.manager import TTSManager as _M
                return _M
            except ImportError:
                return None

    def _voice_meta_for_display_name(self, display_name: str) -> Optional[dict]:
        cls = self._voice_tts_manager_class()
        if not cls or not display_name:
            return None
        eid = (getattr(self, "_voice_engine_id_by_display", None) or {}).get(display_name.strip())
        if eid and eid in cls.KNOWN_ENGINES:
            return dict(cls.KNOWN_ENGINES[eid])
        for meta in cls.KNOWN_ENGINES.values():
            if meta.get("name") == display_name:
                return dict(meta)
        return None

    @staticmethod
    def _voice_format_engine_meta_line(meta: dict) -> str:
        if not meta:
            return ""
        return (
            f"{meta.get('name', '?')} · {meta.get('parameters', '?')} parameters · "
            f"{meta.get('license', '?')} license · ~{meta.get('model_size_mb', '?')} MB download"
        )

    def _voice_install_chatterbox_warnings(self) -> str:
        """Avertissements sous le sélecteur de modèle (carte install) si Chatterbox est choisi."""
        display = ""
        if getattr(self, "_voice_model_var", None):
            display = (self._voice_model_var.get() or "").strip()
        meta = self._voice_meta_for_display_name(display)
        if not meta or meta.get("id") != "chatterbox":
            return ""
        parts = []
        orch = getattr(self, "orch", None)
        lang = (getattr(orch, "last_stt_detected_language", None) or "").strip().lower()
        if lang and lang != "auto" and not lang.startswith("en"):
            t = s("voice.engine.chatterbox_last_stt_not_english", default="")
            if t:
                parts.append(t)
        ui = self._strings_locale_from_cfg()
        if ui not in ("us", "gb"):
            t = s("voice.engine.chatterbox_ui_locale_hint", default="")
            if t:
                parts.append(t)
        return "\n".join(parts)

    def _voice_ready_performance_warning_text(self, tts) -> str:
        """Avertissements CPU / MTL dans la carte Output (onglet Voix) quand le moteur est chargé."""
        if not tts:
            return ""
        parts = []
        engine = tts.get_active_engine()
        eid = str(getattr(tts, "preferred_engine_id", "") or "").lower()
        dev = (getattr(engine, "_device", "") or "").lower() if engine else ""
        ready = bool(engine and engine.is_available())
        orch = getattr(self, "orch", None)
        lang = (getattr(orch, "last_stt_detected_language", None) or "").strip().lower()
        if ready and dev == "cpu":
            pcb = getattr(engine, "_pytorch_cuda_built", None)
            if pcb is False:
                ver = getattr(engine, "_pytorch_version", "") or "?"
                tpl = s("voice.engine.tts_pytorch_cpu_only", default="")
                try:
                    t = tpl.format(version=ver) if tpl else ""
                except (KeyError, ValueError):
                    t = (tpl or "").replace("{version}", ver)
                if t:
                    parts.append(t)
            else:
                if eid == "chatterbox":
                    t = s("voice.engine.tts_cpu_chatterbox", default="")
                else:
                    t = s("voice.engine.tts_cpu_generic", default="")
                if t:
                    parts.append(t)
        if eid == "chatterbox" and lang and lang != "auto" and not lang.startswith("en"):
            t = s("voice.engine.chatterbox_last_stt_not_english", default="")
            if t and t not in parts:
                parts.append(t)
        return "\n".join(parts)

    def _on_voice_model_selected(self, choice=None):
        """Moteur choisi : sync preferred_engine_id, métadonnées, avertissements Chatterbox MTL."""
        if choice is None and getattr(self, "_voice_model_var", None):
            choice = self._voice_model_var.get()
        display = (choice or "").strip()
        eid = (getattr(self, "_voice_engine_id_by_display", None) or {}).get(display)
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        # OmniVoice currently requires NVIDIA/CUDA in our distribution (CPU/Vulkan machines should not offer it).
        try:
            if eid == "omnivoice":
                orch = getattr(self, "orch", None)
                gpu_type = ""
                try:
                    gpu_type = getattr(orch, "_gpu_type", None) or (orch._detect_gpu_type() if orch else "")
                except Exception:
                    gpu_type = ""
                backend = (os.environ.get("PERKYSUE_BACKEND") or "").strip().lower()
                if str(gpu_type).strip().lower() != "nvidia" or "nvidia" not in backend:
                    msg = self._get_alert("regular.omnivoice_requires_nvidia")
                    if msg == "regular.omnivoice_requires_nvidia":
                        msg = "OmniVoice requires NVIDIA/CUDA (not available on CPU/Vulkan)."
                    try:
                        self._notify(f"⚠ {msg}", restore_after_ms=9000)
                    except Exception:
                        pass
                    # Revert selection to Chatterbox and keep menus/buttons consistent.
                    fallback = getattr(self, "_voice_engine_display_by_id", {}) or {}
                    fb_name = fallback.get("chatterbox")
                    if fb_name and getattr(self, "_voice_model_var", None):
                        self._voice_model_var.set(fb_name)
                        try:
                            if getattr(self, "_voice_model_menu", None) and self._voice_model_menu.get() != fb_name:
                                self._voice_model_menu.set(fb_name)
                        except Exception:
                            pass
                        try:
                            if getattr(self, "_voice_ready_engine_menu", None) and self._voice_ready_engine_menu.get() != fb_name:
                                self._voice_ready_engine_menu.set(fb_name)
                        except Exception:
                            pass
                        # Continue flow as if the user selected the fallback, so meta/install state refreshes.
                        display = fb_name
                        eid = "chatterbox"
        except Exception:
            pass
        if tts and eid and getattr(tts, "preferred_engine_id", None) != eid:
            tts.preferred_engine_id = eid
            if getattr(tts, "_detect_install_state", None):
                tts._detect_install_state()
            self._schedule_persist_tts_cfg()
            orch = getattr(self, "orch", None)
            if orch and orch.is_effective_pro() and tts.is_installed():
                if tts.is_loaded() and getattr(tts, "_active_engine_id", None) != eid:
                    tts.unload_engine()
                    if getattr(tts, "_detect_install_state", None):
                        tts._detect_install_state()

                def _reload():
                    try:
                        tts.load_engine()
                    finally:
                        try:
                            self.root.after(0, self._refresh_voice_tab)
                        except Exception:
                            pass

                threading.Thread(target=_reload, daemon=True).start()

        if getattr(self, "_voice_ready_engine_menu", None) and choice:
            try:
                if self._voice_ready_engine_menu.get() != choice:
                    self._voice_ready_engine_menu.set(choice)
            except Exception:
                pass
        if getattr(self, "_voice_model_menu", None) and choice:
            try:
                if self._voice_model_menu.get() != choice:
                    self._voice_model_menu.set(choice)
            except Exception:
                pass

        if not getattr(self, "_voice_install_meta_lbl", None):
            return
        meta = self._voice_meta_for_display_name(display)
        if not meta:
            meta = dict(tts.get_engine_meta()) if tts else {}
        line1 = self._voice_format_engine_meta_line(meta)
        if meta.get("id") == "chatterbox" or meta.get("name") == "Chatterbox Turbo":
            hint = s("voice.engine.chatterbox_multilingual_hint", default="")
            self._voice_install_meta_lbl.configure(text=f"{line1}\n{hint}" if hint else line1)
        else:
            self._voice_install_meta_lbl.configure(text=line1)

        extra = ""
        if meta.get("id") == "chatterbox" or (meta.get("name") == "Chatterbox Turbo"):
            extra = self._voice_install_chatterbox_warnings()
        if getattr(self, "_voice_chatterbox_warn_lbl", None):
            self._voice_chatterbox_warn_lbl.configure(text=extra)

        inner = getattr(self, "_voice_install_inner", None)
        if inner is not None:
            self._voice_apply_inner_wrap(
                inner,
                self._voice_install_body_lbl,
                self._voice_install_meta_lbl,
                self._voice_chatterbox_warn_lbl,
            )
        if getattr(self, "_voice_engine_name_lbl", None):
            eng_nm = (meta or {}).get("name", "Chatterbox Turbo")
            eid_nm = (meta or {}).get("id")
            disp_map = getattr(self, "_voice_engine_display_by_id", None) or {}
            if eid_nm and eid_nm in disp_map:
                eng_nm = disp_map[eid_nm]
            self._voice_engine_name_lbl.configure(text=eng_nm)

    def _on_voice_omni_mode_change(self, choice):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if not tts:
            return
        # Clone-only (design mode hidden).
        tts.omnivoice_mode = "clone"
        self._schedule_persist_tts_cfg()

    def _on_voice_omni_steps_change(self, choice):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if not tts:
            return
        n = (getattr(self, "_voice_omni_steps_to_n", None) or {}).get(choice, 32)
        tts.omnivoice_num_step = int(n)
        self._schedule_persist_tts_cfg()

    def _on_voice_omni_instruct_keyrelease(self, _event=None):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        ent = getattr(self, "_voice_omni_instruct_entry", None)
        if not tts or not ent:
            return
        tts.omnivoice_instruct = (ent.get() or "").strip() or "female, neutral pitch"
        self._schedule_persist_tts_cfg()

    def _voice_refresh_install_meta(self):
        """Synchronise la ligne technique avec le menu (ex. retour sur l’onglet)."""
        if not getattr(self, "_voice_install_meta_lbl", None):
            return
        self._on_voice_model_selected()

    def _voice_sync_engine_menus_from_tts(self):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        cls = self._voice_tts_manager_class()
        if not tts or not cls or not getattr(self, "_voice_model_var", None):
            return
        eid = getattr(tts, "preferred_engine_id", None) or "chatterbox"
        if eid not in cls.KNOWN_ENGINES:
            return
        disp_map = getattr(self, "_voice_engine_display_by_id", None) or {}
        name = disp_map.get(eid) or cls.KNOWN_ENGINES[eid].get("name", "")
        if name and self._voice_model_var.get() != name:
            self._voice_model_var.set(name)

    def _refresh_voice_tab(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts is None:
            return

        for frame in (self._voice_locked, self._voice_install, self._voice_ready):
            frame.pack_forget()

        is_pro = self.orch.is_effective_pro()

        if not is_pro:
            self._voice_locked.pack(fill="x", expand=True)
            return

        self._voice_sync_engine_menus_from_tts()

        if not tts.is_installed():
            self._voice_refresh_install_meta()
            try:
                self._voice_progress_frame.grid_remove()
                self._voice_progress_bar.stop()
            except Exception:
                pass
            if getattr(self, "_voice_install_btn", None):
                self._voice_install_btn.configure(
                    state="normal",
                    text=s("voice.install.button", default="Install engine"),
                )
            if getattr(self, "_voice_progress_label", None):
                self._voice_progress_label.configure(text="", text_color=TXT2)
            self._voice_install.pack(fill="x", expand=True)
            return

        self._voice_ready.pack(fill="x", expand=True)
        self._voice_refresh_install_meta()
        omni_fr = getattr(self, "_voice_omni_fr", None)
        if omni_fr:
            if str(getattr(tts, "preferred_engine_id", "") or "").lower() == "omnivoice":
                omni_fr.pack(fill="x", pady=(0, 8))
            else:
                try:
                    omni_fr.pack_forget()
                except Exception:
                    pass

        if tts.enabled:
            self._voice_enabled_switch.select()
        else:
            self._voice_enabled_switch.deselect()

        self._voice_vol_slider.set(tts.volume * 100)
        self._voice_vol_label.configure(text=f"{int(tts.volume * 100)}%")
        self._voice_spd_slider.set(tts.speed * 100)
        self._voice_spd_label.configure(text=f"{tts.speed:.1f}x")

        if tts.auto_speak:
            self._voice_auto_switch.select()
        else:
            self._voice_auto_switch.deselect()

        vps = getattr(self, "_voice_payload_switch", None)
        if vps:
            if getattr(tts, "voice_payload_enabled", True):
                vps.select()
            else:
                vps.deselect()
        rps = getattr(self, "_voice_read_payload_switch", None)
        if rps:
            if getattr(tts, "read_aloud_payload", False):
                rps.select()
            else:
                rps.deselect()

        engine = tts.get_active_engine()
        lbl = self._voice_engine_status
        if engine and engine.is_available():
            vram = engine.get_vram_estimate_mb()
            vram_s = f" (~{vram} MB)" if vram else ""
            device = getattr(engine, "_device", "?")
            lbl.configure(text=f"✅ Ready on {device}{vram_s}", text_color=GREEN_BT)
            show_pt = (
                getattr(tts, "_pytorch_cuda_install_recommended", False)
                and not getattr(tts, "pytorch_cuda_offer_never", False)
                and not tts.installer.is_running
            )
            self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=show_pt)
            perf_txt = self._voice_ready_performance_warning_text(tts)
            if getattr(self, "_voice_ready_perf_warn_lbl", None):
                self._voice_ready_perf_warn_lbl.configure(text=perf_txt or "", text_color="#F59E0B", wraplength=0)
                if (perf_txt or "").strip():
                    self._voice_ready_perf_warn_lbl.pack(fill="x", pady=(0, 4))
                else:
                    self._voice_ready_perf_warn_lbl.pack_forget()
            rec = getattr(tts, "_pytorch_cuda_install_recommended", False) and not getattr(
                tts, "pytorch_cuda_offer_never", False
            )
            if rec and not getattr(self, "_voice_pytorch_cuda_auto_prompt_done_this_visit", True):
                if not getattr(self, "_voice_pytorch_cuda_prompt_pending", False):
                    self._voice_pytorch_cuda_prompt_pending = True
                    try:
                        self.root.after(600, lambda t=tts: self._voice_maybe_prompt_pytorch_cuda(t))
                    except Exception:
                        self._voice_pytorch_cuda_prompt_pending = False
        elif tts.is_installed():
            err = getattr(tts, "engine_load_error", None)
            if err:
                full_repair_needed = any(
                    marker in str(err).lower()
                    for marker in (
                        "torchcodec installed but cannot load ffmpeg",
                        "ffmpeg shared dlls",
                        "libtorchcodec_core",
                        "torchcodec still not importable",
                    )
                )
                needs_repair = any(
                    marker in str(err).lower()
                    for marker in ("no_manifest", "snapshot_unavailable", "repair/install", "manifest invalid")
                )
                if getattr(self, "_voice_engine_retry_btn", None):
                    self._voice_engine_retry_btn.configure(
                        text=(
                            s("voice.output.full_repair", default="Run full repair")
                            if full_repair_needed
                            else (
                                s("voice.install.retry", default="Repair/Install")
                                if needs_repair
                                else s("voice.output.retry_engine", default="Retry load")
                            )
                        )
                    )
                lbl.configure(
                    text=s("voice.output.engine_load_failed_short", default="❌ Load failed — detail below"),
                    text_color="#EF4444",
                )
                if getattr(self, "_voice_ready_perf_warn_lbl", None):
                    detail = (err or "").strip()
                    if len(detail) > 900:
                        detail = detail[:897] + "…"
                    self._voice_ready_perf_warn_lbl.configure(
                        text=detail,
                        text_color="#EF4444",
                        wraplength=640,
                    )
                    self._voice_ready_perf_warn_lbl.pack(fill="x", pady=(4, 4))
                self._voice_pack_engine_action_buttons(show_retry=True, show_pytorch=False)
            elif not getattr(self, "_voice_tts_loading", False):
                self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=False)
                lbl.configure(text="⏳ Loading…", text_color="#F59E0B")
                if getattr(self, "_voice_ready_perf_warn_lbl", None):
                    self._voice_ready_perf_warn_lbl.configure(text="")
                    self._voice_ready_perf_warn_lbl.pack_forget()
                self._voice_tts_loading = True

                def _load():
                    try:
                        tts.load_engine()
                    finally:
                        self._voice_tts_loading = False
                    try:
                        self.root.after(0, self._refresh_voice_tab)
                    except Exception:
                        pass

                threading.Thread(target=_load, daemon=True).start()
        else:
            self._voice_pack_engine_action_buttons(show_retry=False, show_pytorch=False)
            lbl.configure(text="❌ Not available", text_color="#EF4444")
            if getattr(self, "_voice_ready_perf_warn_lbl", None):
                self._voice_ready_perf_warn_lbl.configure(text="")
                self._voice_ready_perf_warn_lbl.pack_forget()

        voices = tts.get_all_voices()
        cloned = [v for v in voices if v.source == "cloned"]
        default_pkg = s("voice.packs.default_body", default="")
        more = s("voice.packs.more_patreon", default="Get more character voices on Patreon.")
        lead = s("voice.packs.installed_lead", default="Voice packs installed:")
        if cloned:
            names = ", ".join(v.name for v in cloned)
            self._voice_packs_label.configure(text=f"{lead} {names}\n{more}")
        else:
            self._voice_packs_label.configure(text=default_pkg)

    def _on_voice_retry_engine(self):
        tts = getattr(getattr(self, "orch", None), "tts_manager", None)
        if not tts:
            return
        err = str(getattr(tts, "engine_load_error", "") or "").lower()
        full_repair_needed = any(
            marker in err
            for marker in (
                "torchcodec installed but cannot load ffmpeg",
                "ffmpeg shared dlls",
                "libtorchcodec_core",
                "torchcodec still not importable",
            )
        )
        if full_repair_needed:
            self._voice_run_full_repair_install_bat()
            return
        needs_repair = any(
            marker in err
            for marker in ("no_manifest", "snapshot_unavailable", "repair/install", "manifest invalid")
        )
        if needs_repair:
            self._on_voice_install()
            return
        if getattr(tts, "clear_engine_load_error", None):
            tts.clear_engine_load_error()
        self._refresh_voice_tab()

    def _voice_run_full_repair_install_bat(self):
        app_root = Path(__file__).resolve().parent.parent.parent
        install_bat = app_root / "install.bat"
        if not install_bat.exists():
            self._notify("install.bat not found in app root.", restore_after_ms=6000)
            return
        try:
            subprocess.Popen(["cmd", "/c", str(install_bat)], cwd=str(app_root), shell=False)
            try:
                self.root.destroy()
            except Exception:
                pass
            sys.exit(0)
        except Exception as e:
            self._notify(f"Could not launch install.bat: {e}", restore_after_ms=9000)

    def _tts_install_sync_header_progress(self, pct: int, display_name: str):
        """Pendant install TTS (Voice) : même barre / titre que téléchargement modèle LLM."""
        try:
            p = max(0, min(100, int(pct)))
            self._set_header_title_text(self._get_alert("regular.download_progress", name=display_name, pct=p))
            self._update_download_progress_ui(p, display_name)
        except Exception:
            pass

    def _tts_install_restore_header(self):
        try:
            self._set_header_title_text(getattr(self, "_hdr_normal_text", "PerkySue"))
        except Exception:
            pass

    def _on_voice_install(self):
        tts = getattr(self.orch, "tts_manager", None)
        if not tts:
            return
        # Avoid UI dead-ends: installer can refuse concurrent installs (and won't call callbacks).
        if getattr(tts, "installer", None) and tts.installer.is_running:
            try:
                msg = self._get_alert("regular.tts_install_in_progress")
                if msg == "regular.tts_install_in_progress":
                    msg = "An install is already in progress."
                self._notify(
                    msg,
                    restore_after_ms=7000,
                )
            except Exception:
                pass
            try:
                self._refresh_voice_tab()
            except Exception:
                pass
            return

        eid = str(getattr(tts, "preferred_engine_id", None) or "chatterbox").lower()
        if eid == "omnivoice":
            prog_name = s("voice.install.progress_name_omnivoice", default="OmniVoice")
        else:
            prog_name = s("voice.install.progress_name_chatterbox", default="Chatterbox Turbo")

        self._voice_install_btn.configure(
            state="disabled",
            text=s("voice.install.button_working", default="Installing…"),
        )
        self._voice_progress_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._voice_progress_bar.start()
        try:
            self._tts_install_sync_header_progress(0, prog_name)
        except Exception:
            pass

        def _on_progress(state, pct, msg):
            def _update():
                self._voice_progress_label.configure(text=msg)
                if pct >= 100:
                    self._voice_progress_bar.stop()
                    self._voice_progress_bar.set(1.0)
                try:
                    self._tts_install_sync_header_progress(int(pct), prog_name)
                except Exception:
                    pass

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        def _on_done(success, error):
            def _finish():
                try:
                    self._tts_install_restore_header()
                except Exception:
                    pass
                self._voice_progress_bar.stop()
                if success:
                    self._voice_progress_label.configure(
                        text="✅ Installed! Loading engine...",
                        text_color=GREEN_BT,
                    )
                    tts._detect_install_state()
                    tts.load_engine()
                    self._persist_tts_cfg()
                    self.root.after(500, self._refresh_voice_tab)
                else:
                    self._voice_install_btn.configure(
                        state="normal",
                        text=s("voice.install.retry", default="Retry install"),
                    )
                    self._voice_progress_label.configure(text=f"❌ {error}", text_color="#EF4444")
                    try:
                        tts._engine_load_error = str(error or "")
                    except Exception:
                        pass
                    try:
                        self.root.after(300, self._refresh_voice_tab)
                    except Exception:
                        pass

            try:
                self.root.after(0, _finish)
            except Exception:
                pass

        if eid == "omnivoice":
            tts.installer.install_omnivoice(on_progress=_on_progress, on_done=_on_done)
        else:
            tts.installer.install_chatterbox(on_progress=_on_progress, on_done=_on_done)

    def _on_voice_toggle(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.enabled = _ctk_switch_is_on(self._voice_enabled_switch)
            self._persist_tts_cfg()

    def _on_voice_volume(self, val):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.volume = round(float(val) / 100.0, 2)
        self._voice_vol_label.configure(text=f"{int(float(val))}%")
        self._schedule_persist_tts_cfg()

    def _on_voice_speed(self, val):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.speed = round(float(val) / 100.0, 2)
        self._voice_spd_label.configure(text=f"{float(val) / 100:.1f}x")
        self._schedule_persist_tts_cfg()

    def _on_voice_auto_toggle(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.auto_speak = _ctk_switch_is_on(self._voice_auto_switch)
            self._persist_tts_cfg()

    def _on_voice_payload_toggle(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.voice_payload_enabled = _ctk_switch_is_on(self._voice_payload_switch)
            self._persist_tts_cfg()

    def _on_voice_read_payload_toggle(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.read_aloud_payload = _ctk_switch_is_on(self._voice_read_payload_switch)
            self._persist_tts_cfg()

    def _on_voice_test_speak(self):
        tts = getattr(self.orch, "tts_manager", None)
        if not tts or not tts.is_loaded():
            return
        text = self._voice_test_input.get("0.0", "end").strip()
        if not text:
            return
        self._voice_test_status.configure(text="⏳ Synthesizing...", text_color=MUTED)
        self.root.update_idletasks()
        tts_lang = ((self.cfg.get("tts") or {}).get("language") or "en").strip().lower() or "en"
        will_block = getattr(tts, "will_block_for_multilingual_model", lambda _l: False)(tts_lang)

        def _speak():
            if will_block:
                try:
                    self.root.after(0, lambda: self._notify(self._get_alert("regular.tts_loading"), restore_after_ms=15000))
                    self.root.after(0, lambda: self.set_status("tts_loading"))
                except Exception:
                    pass
            t0 = time.monotonic()
            try:
                result = tts.speak(text=text, blocking=True)
            finally:
                if will_block:
                    try:
                        self.root.after(0, lambda: self.set_status("ready"))
                    except Exception:
                        pass
            elapsed = time.monotonic() - t0

            def _update():
                if result:
                    self._voice_test_status.configure(
                        text=f"✅ {result.duration:.1f}s audio — RTF {result.rtf:.3f} — {elapsed:.1f}s total",
                        text_color=GREEN_BT,
                    )
                else:
                    self._voice_test_status.configure(text="❌ Failed", text_color="#EF4444")

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        threading.Thread(target=_speak, daemon=True).start()

    def _on_voice_test_stop(self):
        tts = getattr(self.orch, "tts_manager", None)
        if tts:
            tts.stop()
        self._voice_test_status.configure(text="⏹ Stopped", text_color=MUTED)

    def _chat_username(self) -> str:
        """Display name for the user in chat: identity.name, else localized 'You' (not 'User')."""
        identity = (self.cfg.get("identity") or {}).get("name") or ""
        name = identity.strip()
        if name:
            return name
        return s("chat.user_fallback", default="You")

    def _assistant_chat_name(self, tab: str = "chat") -> str:
        """Display name for the assistant in Chat/Help: use active skin name when not Default."""
        try:
            skin_id = self._effective_skin()
        except Exception:
            skin_id = "Default"
        skin_id = (skin_id or "Default").strip() or "Default"
        if skin_id != "Default":
            # Canonique ``Character/Locale`` (ex. Mike/FR) → afficher le prénom personnage.
            try:
                skin_name, _loc = split_skin_id(skin_id)
            except Exception:
                skin_name = skin_id.split("/", 1)[0].strip() if "/" in skin_id else skin_id
            if (skin_name or "").strip():
                return skin_name.strip()
        # Default: fall back to localized sender name.
        if (tab or "").strip().lower() == "help":
            return s("help.sender_name", default="PerkySue")
        return s("chat.sender_name", default="PerkySue")

    def _get_greeting_text(self, tab: str) -> str:
        """Greeting for the given tab ('chat' or 'help'): show LLM greeting when cached; else generic fallback or download hint."""
        ident = self.cfg.get("identity") or {}
        name = (ident.get("name") or "").strip()
        lang_cfg = (ident.get("first_language") or "auto").strip().lower() or "auto"
        # Effective language: if Auto, use last detected STT language; else English.
        if lang_cfg == "auto":
            try:
                detected = (getattr(self.orch, "last_stt_detected_language", None) or "").strip().lower() if getattr(self, "orch", None) else ""
            except Exception:
                detected = ""
            lang = detected or "en"
        else:
            lang = lang_cfg
        if tab == "help":
            cached = getattr(self, "_cached_greeting_help", None)
            loading = getattr(self, "_help_greeting_loading", False)
        else:
            cached = getattr(self, "_cached_greeting_chat", None)
            loading = getattr(self, "_chat_greeting_loading", False)
        try:
            if getattr(self, "orch", None) and getattr(self.orch, "llm", None) and self.orch.llm.is_available():
                if (cached or "").strip():
                    return (cached or "").strip()
                # LLM available but no cached greeting (request failed or returned empty). Once loading is done, show generic fallback so user always sees something.
                if not loading:
                    base = f"Hi {name}!" if name else "Hi!"
                    if tab == "help":
                        return f"👋 {base} Need help with PerkySue? Ask me anything."
                    return f"👋 {base} What would you like to talk about?"
                return ""
        except Exception:
            pass
        # No LLM available: show model-download hint.
        base = f"Hi {name}!" if name else "Hi!"
        return f"👋 {base} Please download a LLM in Settings → Recommended Models."

    def _request_llm_greeting(self, tab: str):
        """Request greeting only when the user opens this page. tab: 'chat' or 'help'. Fired only from _go(chat) or _go(help)."""
        ident = self.cfg.get("identity") or {}
        name = (ident.get("name") or "").strip()
        lang_cfg = (ident.get("first_language") or "auto").strip().lower() or "auto"
        if lang_cfg == "auto":
            try:
                detected = (getattr(self.orch, "last_stt_detected_language", None) or "").strip().lower() if getattr(self, "orch", None) else ""
            except Exception:
                detected = ""
            lang = detected or "en"
        else:
            lang = lang_cfg
        if not getattr(self, "orch", None) or not getattr(self.orch, "get_greeting_from_llm", None):
            return
        # If we already have a cached greeting for (name, lang), do NOT enter loading state.
        if tab == "help":
            if getattr(self, "_cached_greeting_key_help", None) == (name, lang) and (getattr(self, "_cached_greeting_help", "") or "").strip():
                return
        else:
            if getattr(self, "_cached_greeting_key_chat", None) == (name, lang) and (getattr(self, "_cached_greeting_chat", "") or "").strip():
                return

        if tab == "help":
            self._help_greeting_loading = True
            try:
                self._refresh_help_tab()
            except Exception:
                pass
        else:
            self._chat_greeting_loading = True
            try:
                self._refresh_chat_tab()
            except Exception:
                pass
        def do_request():
            result = self.orch.get_greeting_from_llm(lang, name, context=tab)
            if getattr(self, "root", None):
                self.root.after(0, lambda: self._on_llm_greeting_ready(result, name, lang, tab))
        threading.Thread(target=do_request, daemon=True).start()

    def _on_llm_greeting_ready(self, result, name, lang, tab):
        """Called on main thread when LLM greeting is ready; update cache for that tab only and refresh that tab."""
        if tab == "help":
            self._help_greeting_loading = False
        else:
            self._chat_greeting_loading = False
        text = (result or "").strip() if result else ""
        if text:
            if tab == "help":
                self._cached_greeting_help = text
                self._cached_greeting_key_help = (name, lang)
            else:
                self._cached_greeting_chat = text
                self._cached_greeting_key_chat = (name, lang)
        # Always refresh the corresponding tab so that any spinner disappears even if greeting failed.
        if tab == "help":
            if getattr(self, "_refresh_help_tab", None):
                self._refresh_help_tab()
        else:
            if getattr(self, "_refresh_chat_tab", None):
                self._refresh_chat_tab()

    def _on_chat_tab_changed(self, *args):
        """Legacy no-op (Chat/Help uses custom pill buttons now)."""
        return

    def _chat_strip_markdown(self, text: str) -> str:
        """Masque ** et * pour l'affichage : **gras** → gras, *italique* → italique (sans rendu gras/italique)."""
        if not text:
            return text
        t = text.replace("**", "")
        t = t.replace("*", "")
        return t

    def _orch_show_tts_tags_in_ui(self) -> bool:
        """True when Settings → Advanced → Debug mode is On — show raw [tags] in Chat/Help bubbles."""
        o = getattr(self, "orch", None)
        try:
            return bool(o and getattr(o, "_feedback_debug_mode", lambda: False)())
        except Exception:
            return False

    def _assistant_bubble_visible_text(self, raw_answer: str) -> str:
        """Chat/Help assistant bubble: strip TTS [tags] unless dev plugin is present."""
        md = self._chat_strip_markdown(raw_answer)
        if self._orch_show_tts_tags_in_ui():
            return md
        try:
            from services.tts.tag_sanitize import strip_all_bracket_tags_for_display

            return strip_all_bracket_tags_for_display(md)
        except Exception:
            return md

    _THINKING_DOT_FRAMES = ("⚪ ⚫ ⚫", "⚫ ⚪ ⚫", "⚫ ⚫ ⚪")
    # Animated thinking bubble only (not normal chat/help message text).
    _THINKING_DOT_FONT = ("Segoe UI", 9)

    def _cancel_thinking_dot_timers_for_tab(self, tab: str):
        """Annule seulement les timers de cet onglet (évite de couper l’animation de l’autre onglet)."""
        buckets = getattr(self, "_thinking_dot_timers", None) or {}
        d = buckets.get(tab) or {}
        for aid in list(d.values()):
            try:
                self.root.after_cancel(aid)
            except (tk.TclError, ValueError, AttributeError):
                pass
        buckets[tab] = {}

    def _start_thinking_dots_on_label(self, label, tab: str):
        """Cycle ⚪⚫⚫ → ⚫⚪⚫ → ⚫⚫⚪ jusqu’au prochain refresh de cet onglet."""
        if label is None or tab not in ("chat", "help"):
            return
        buckets = getattr(self, "_thinking_dot_timers", None)
        if buckets is None:
            return

        def tick(idx: int):
            wid = id(label)
            d = buckets.setdefault(tab, {})
            old = d.pop(wid, None)
            if old is not None:
                try:
                    self.root.after_cancel(old)
                except (tk.TclError, ValueError, AttributeError):
                    pass
            try:
                if not label.winfo_exists():
                    return
            except (tk.TclError, AttributeError):
                return
            try:
                label.configure(text=self._THINKING_DOT_FRAMES[idx % 3])
            except (tk.TclError, AttributeError):
                return

            def schedule_next():
                tick(idx + 1)

            try:
                aid = self.root.after(400, schedule_next)
                d[wid] = aid
            except (tk.TclError, AttributeError):
                pass

        tick(0)

    def _refresh_chat_tab(self):
        """Refresh model label, token bar, and message list from Ask history."""
        if not getattr(self, "_chat_model_lbl", None):
            return
        try:
            self._cancel_thinking_dot_timers_for_tab("chat")
            llm_name = "—"
            max_ctx = 4096
            if getattr(self, "orch", None) and self.orch.llm and self.orch.llm.is_available():
                llm_name = self.orch.llm.get_name()
            if getattr(self, "orch", None) and hasattr(self.orch, "get_effective_llm_n_ctx"):
                max_ctx = int(self.orch.get_effective_llm_n_ctx())
            else:
                raw = int(self.cfg.get("llm", {}).get("max_input_tokens") or self.cfg.get("llm", {}).get("n_ctx") or 0)
                max_ctx = raw if raw > 0 else 4096
            disp = (llm_name or "").strip()
            # UI: hide llama-server wrapper; show just the model name.
            m = re.match(r"(?i)^\s*llama-server\s*\(\s*(.+)\s*\)\s*$", disp)
            if m:
                disp = (m.group(1) or "").strip()
            elif re.match(r"(?i)^llama-server\s+", disp):
                disp = re.sub(r"(?i)^llama-server\s+", "", disp).strip()
            self._chat_model_lbl.configure(text=f"{disp or '—'}")
            sw = getattr(self, "_chat_continuous_switch", None)
            if sw and getattr(self, "orch", None) and hasattr(self.orch, "is_continuous_chat_enabled"):
                if self.orch.is_continuous_chat_enabled():
                    sw.select()
                else:
                    sw.deselect()

            history = getattr(self.orch, "_answer_history", []) if getattr(self, "orch", None) else []
            # When context limit was reached, show bar at full so it matches the alert (no 1388 vs 2048 inconsistency); cleared on New chat
            if getattr(self.orch, "_answer_context_limit_reached", False):
                current = max_ctx
            else:
                total_chars = sum(len((e.get("q") or "") + (e.get("a") or "")) for e in history)
                approx_tokens = max(0, total_chars // 4)
                current = approx_tokens  # afficher le compte réel (peut dépasser max_ctx)
            keep_last = 2
            try:
                if getattr(self, "orch", None):
                    keep_last = int(
                        ((getattr(self.orch, "config", {}) or {}).get("llm", {}) or {}).get("answer_context_keep", 2)
                    )
                else:
                    keep_last = int(((self.cfg.get("llm") or {}).get("answer_context_keep", 2)) or 2)
            except (TypeError, ValueError):
                keep_last = 2
            if keep_last not in (2, 3, 4):
                keep_last = 2
            self._chat_token_lbl.configure(text=f"{max_ctx} ctx: {current}/{max_ctx} · Q/A:{keep_last}")

            # Always show scrollable area (welcome + optional history)
            self._chat_messages_placeholder.grid_remove()
            self._chat_messages_inner.grid(row=3, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))

            for w in self._chat_messages_inner.winfo_children():
                w.destroy()
            self._chat_bubble_labels = []
            user_name = self._chat_username()
            wrap = self._chat_bubble_wraplength()
            running_chars = 0
            greeting = self._get_greeting_text("chat")
            if greeting:
                # First bubble: PerkySue greeting
                welcome_row = CTkFrame(self._chat_messages_inner, fg_color="transparent")
                welcome_row.pack(fill="x", pady=(0, 6))
                welcome_row.grid_columnconfigure(0, weight=1)
                CTkLabel(welcome_row, text=self._assistant_chat_name("chat"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                welcome_bubble = CTkFrame(welcome_row, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                welcome_bubble.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                iw = self._inner_bubble_wraplength(wrap)
                welcome_lbl = CTkLabel(
                    welcome_bubble,
                    text=self._assistant_bubble_visible_text(greeting),
                    font=("Segoe UI", 14),
                    text_color=TXT,
                    wraplength=iw,
                    justify="left",
                )
                welcome_lbl.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                self._chat_bubble_labels.append(welcome_lbl)
            elif getattr(self, "_chat_greeting_loading", False):
                spin_row = CTkFrame(self._chat_messages_inner, fg_color="transparent")
                spin_row.pack(fill="x", pady=(0, 6))
                spin_row.grid_columnconfigure(0, weight=1)
                CTkLabel(spin_row, text=self._assistant_chat_name("chat"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                welcome_bubble = CTkFrame(spin_row, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                welcome_bubble.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                spin_lbl = CTkLabel(
                    welcome_bubble,
                    text=self._THINKING_DOT_FRAMES[0],
                    font=self._THINKING_DOT_FONT,
                    text_color=TXT,
                )
                spin_lbl.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                self._start_thinking_dots_on_label(spin_lbl, "chat")
            for entry in history:
                q = (entry.get("q") or "").strip()
                a = (entry.get("a") or "").strip()
                if q:
                    running_chars += len(q)
                    row_u = CTkFrame(self._chat_messages_inner, fg_color="transparent")
                    row_u.pack(fill="x", pady=(0, 6))
                    row_u.grid_columnconfigure(1, weight=1)
                    lbl_u = CTkLabel(row_u, text=user_name, font=("Segoe UI", 12, "bold"), text_color=MUTED)
                    lbl_u.grid(row=0, column=1, sticky="e", padx=(0, 20))
                    bubble_u = CTkFrame(row_u, fg_color=ACCENT, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_u.grid(row=1, column=1, sticky="e", padx=(0, 20), pady=(2, 0))
                    iw = self._inner_bubble_wraplength(wrap)
                    lq = CTkLabel(
                        bubble_u,
                        text=self._chat_strip_markdown(q),
                        font=("Segoe UI", 14),
                        text_color=TXT,
                        wraplength=iw,
                        justify="right",
                    )
                    lq.pack(padx=(18, 18), pady=(10, 10), anchor="e")
                    self._chat_bubble_labels.append(lq)
                if a:
                    running_chars += len(a)
                    tokens_approx = running_chars // 4
                    is_llm_error = "LLM error" in a or "400" in a
                    row_p = CTkFrame(self._chat_messages_inner, fg_color="transparent")
                    row_p.pack(fill="x", pady=(0, 6))
                    row_p.grid_columnconfigure(0, weight=1)
                    CTkLabel(row_p, text=self._assistant_chat_name("chat"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                    if is_llm_error:
                        CTkLabel(row_p, text=f"~{tokens_approx} tok", font=("Segoe UI", 11), text_color=MUTED).grid(row=0, column=1, sticky="e", padx=(0, 8))
                    bubble_p = CTkFrame(row_p, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_p.grid(row=1, column=0, columnspan=(2 if is_llm_error else 1), sticky="w", padx=(8, 0), pady=(2, 0))
                    iw = self._inner_bubble_wraplength(wrap)
                    la = CTkLabel(bubble_p, text=self._assistant_bubble_visible_text(a), font=("Segoe UI", 14), text_color=TXT, wraplength=iw, justify="left")
                    la.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                    self._chat_bubble_labels.append(la)
                elif q:
                    row_th = CTkFrame(self._chat_messages_inner, fg_color="transparent")
                    row_th.pack(fill="x", pady=(0, 6))
                    row_th.grid_columnconfigure(0, weight=1)
                    CTkLabel(row_th, text=self._assistant_chat_name("chat"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                    bubble_th = CTkFrame(row_th, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_th.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                    lth = CTkLabel(
                        bubble_th,
                        text=self._THINKING_DOT_FRAMES[0],
                        font=self._THINKING_DOT_FONT,
                        text_color=TXT,
                    )
                    lth.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                    self._start_thinking_dots_on_label(lth, "chat")
            self._update_chat_bubble_wraplengths()
            self._chat_scrollregion_update()
            if history:
                self._chat_scroll_to_bottom()
            self._update_chat_free_notice_bar(wrap)
        except Exception:
            pass

    def _update_chat_free_notice_bar(self, wrap_hint: int = 520):
        """Fixed strip above Chat scroll: Free plan — show once session has ≥2 Q/A entries; stays until New chat."""
        fr = getattr(self, "_chat_free_notice_fr", None)
        lbl = getattr(self, "_chat_free_notice_lbl", None)
        if not fr or not lbl:
            return
        try:
            orch = getattr(self, "orch", None)
            history = getattr(orch, "_answer_history", []) if orch else []
            show = bool(orch and not orch.is_effective_pro() and len(history) >= 2)
            lbl.configure(text=s("chat.free_answer_notice"))
            try:
                wl = max(280, int(wrap_hint) - 32) if wrap_hint else 520
                lbl.configure(wraplength=wl)
            except Exception:
                pass
            if show:
                fr.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
            else:
                fr.grid_remove()
        except Exception:
            pass

    def _refresh_help_tab(self):
        """Refresh Help tab: model/token bar and message list from Help history.
        First message is normally the PerkySue 👋 greeting, unless a one-shot
        skip flag was set (e.g. when redirecting a locked Pro mode)."""
        if not getattr(self, "_help_model_lbl", None):
            return
        try:
            self._cancel_thinking_dot_timers_for_tab("help")
            llm_name = "—"
            max_ctx = 4096
            if getattr(self, "orch", None) and self.orch.llm and self.orch.llm.is_available():
                llm_name = self.orch.llm.get_name()
            if getattr(self, "orch", None) and hasattr(self.orch, "get_effective_llm_n_ctx"):
                max_ctx = int(self.orch.get_effective_llm_n_ctx())
            else:
                raw = int(self.cfg.get("llm", {}).get("max_input_tokens") or self.cfg.get("llm", {}).get("n_ctx") or 0)
                max_ctx = raw if raw > 0 else 4096
            disp = (llm_name or "").strip()
            m = re.match(r"(?i)^\s*llama-server\s*\(\s*(.+)\s*\)\s*$", disp)
            if m:
                disp = (m.group(1) or "").strip()
            elif re.match(r"(?i)^llama-server\s+", disp):
                disp = re.sub(r"(?i)^llama-server\s+", "", disp).strip()
            self._help_model_lbl.configure(text=f"{disp or '—'}")
            history = getattr(self.orch, "_help_history", []) if getattr(self, "orch", None) else []
            # When truncation was shown, bar at full so it matches the alert (same as Chat)
            if getattr(self.orch, "_help_context_limit_reached", False):
                current = max_ctx
            else:
                total_chars = sum(len((e.get("q") or "") + (e.get("a") or "")) for e in history)
                current = max(0, total_chars // 4)
            self._help_token_lbl.configure(text=f"{max_ctx} ctx: {current}/{max_ctx}")
            # Always show scrollable area (we have at least the welcome message)
            self._help_messages_placeholder.grid_remove()
            self._help_messages_inner.grid(row=2, column=0, sticky="nsew", padx=(16, 4), pady=(0, 8))
            for w in self._help_messages_inner.winfo_children():
                w.destroy()
            self._help_bubble_labels = []
            wrap = self._help_bubble_wraplength()
            user_name = self._chat_username()
            greeting = self._get_greeting_text("help")
            if getattr(self, "_help_skip_greeting_once", False):
                greeting = ""
                self._help_skip_greeting_once = False
            if greeting:
                # First bubble: PerkySue welcome
                welcome_row = CTkFrame(self._help_messages_inner, fg_color="transparent")
                welcome_row.pack(fill="x", pady=(0, 6))
                welcome_row.grid_columnconfigure(0, weight=1)
                CTkLabel(welcome_row, text=self._assistant_chat_name("help"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                welcome_bubble = CTkFrame(welcome_row, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                welcome_bubble.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                iw = self._inner_bubble_wraplength(wrap)
                welcome_lbl = CTkLabel(
                    welcome_bubble,
                    text=self._assistant_bubble_visible_text(greeting),
                    font=("Segoe UI", 14),
                    text_color=TXT,
                    wraplength=iw,
                    justify="left",
                )
                welcome_lbl.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                self._help_bubble_labels.append(welcome_lbl)
            elif getattr(self, "_help_greeting_loading", False):
                spin_row = CTkFrame(self._help_messages_inner, fg_color="transparent")
                spin_row.pack(fill="x", pady=(0, 6))
                spin_row.grid_columnconfigure(0, weight=1)
                CTkLabel(spin_row, text=self._assistant_chat_name("help"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                welcome_bubble = CTkFrame(spin_row, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                welcome_bubble.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                spin_lbl = CTkLabel(
                    welcome_bubble,
                    text=self._THINKING_DOT_FRAMES[0],
                    font=self._THINKING_DOT_FONT,
                    text_color=TXT,
                )
                spin_lbl.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                self._start_thinking_dots_on_label(spin_lbl, "help")
            for entry in history:
                q = (entry.get("q") or "").strip()
                a = (entry.get("a") or "").strip()
                if q:
                    row_u = CTkFrame(self._help_messages_inner, fg_color="transparent")
                    row_u.pack(fill="x", pady=(0, 6))
                    row_u.grid_columnconfigure(1, weight=1)
                    lbl_u = CTkLabel(row_u, text=user_name, font=("Segoe UI", 12, "bold"), text_color=MUTED)
                    lbl_u.grid(row=0, column=1, sticky="e", padx=(0, 20))
                    bubble_u = CTkFrame(row_u, fg_color=ACCENT, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_u.grid(row=1, column=1, sticky="e", padx=(0, 20), pady=(2, 0))
                    iw = self._inner_bubble_wraplength(wrap)
                    lq = CTkLabel(
                        bubble_u,
                        text=self._chat_strip_markdown(q),
                        font=("Segoe UI", 14),
                        text_color=TXT,
                        wraplength=iw,
                        justify="right",
                    )
                    lq.pack(padx=(18, 18), pady=(10, 10), anchor="e")
                    self._help_bubble_labels.append(lq)
                if a:
                    row_p = CTkFrame(self._help_messages_inner, fg_color="transparent")
                    row_p.pack(fill="x", pady=(0, 6))
                    row_p.grid_columnconfigure(0, weight=1)
                    CTkLabel(row_p, text=self._assistant_chat_name("help"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                    bubble_p = CTkFrame(row_p, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_p.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                    iw = self._inner_bubble_wraplength(wrap)
                    la = CTkLabel(bubble_p, text=self._assistant_bubble_visible_text(a), font=("Segoe UI", 14), text_color=TXT, wraplength=iw, justify="left")
                    la.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                    self._help_bubble_labels.append(la)
                elif q:
                    row_th = CTkFrame(self._help_messages_inner, fg_color="transparent")
                    row_th.pack(fill="x", pady=(0, 6))
                    row_th.grid_columnconfigure(0, weight=1)
                    CTkLabel(row_th, text=self._assistant_chat_name("help"), font=("Segoe UI", 12, "bold"), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(8, 0))
                    bubble_th = CTkFrame(row_th, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
                    bubble_th.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 0))
                    lth = CTkLabel(
                        bubble_th,
                        text=self._THINKING_DOT_FRAMES[0],
                        font=self._THINKING_DOT_FONT,
                        text_color=TXT,
                    )
                    lth.pack(padx=(16, 16), pady=(10, 10), anchor="w")
                    self._start_thinking_dots_on_label(lth, "help")
            self._update_help_bubble_wraplengths()
            self._help_scrollregion_update()
            self._help_scroll_to_bottom()
        except Exception:
            pass

    def _help_scrollregion_update(self):
        def _do():
            try:
                inner = getattr(self, "_help_messages_inner", None)
                if not inner:
                    return
                canvas = getattr(inner, "_parent_canvas", None)
                if canvas:
                    inner.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
                    self._help_scroll_to_bottom()
            except (tk.TclError, AttributeError):
                pass
        try:
            self.root.after(0, _do)
            self.root.after(50, _do)
        except Exception:
            pass

    def _help_scroll_to_bottom(self):
        try:
            inner = getattr(self, "_help_messages_inner", None)
            if not inner:
                return
            canvas = getattr(inner, "_parent_canvas", None)
            if canvas:
                canvas.yview_moveto(1.0)
        except (tk.TclError, AttributeError):
            pass

    def _help_bubble_wraplength(self):
        try:
            w = self._help_messages_inner.winfo_width()
            if w and w > 1:
                # Leave more room so label text never hugs the bubble edge.
                return max(280, min(460, w - 120))
        except (tk.TclError, AttributeError):
            pass
        return 300

    def _update_help_bubble_wraplengths(self):
        wrap = self._inner_bubble_wraplength(self._help_bubble_wraplength())
        for lbl in getattr(self, "_help_bubble_labels", []):
            try:
                if lbl.winfo_exists():
                    lbl.configure(wraplength=wrap)
            except (tk.TclError, AttributeError):
                pass

    def _chat_scrollregion_update(self):
        """Force la mise à jour du scrollregion après ajout de bulles pour que le scroll grandisse."""
        def _do():
            try:
                inner = getattr(self, "_chat_messages_inner", None)
                if not inner:
                    return
                canvas = getattr(inner, "_parent_canvas", None)
                if canvas:
                    inner.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
                    self._chat_scroll_to_bottom()
            except (tk.TclError, AttributeError):
                pass
        try:
            self.root.after(0, _do)
            self.root.after(50, _do)
        except Exception:
            pass

    def _chat_scroll_to_bottom(self):
        """Scroll la zone des messages tout en bas (dernier message visible)."""
        try:
            inner = getattr(self, "_chat_messages_inner", None)
            if not inner:
                return
            canvas = getattr(inner, "_parent_canvas", None)
            if canvas:
                canvas.yview_moveto(1.0)
        except (tk.TclError, AttributeError):
            pass

    def _inner_bubble_wraplength(self, outer_wrap: int) -> int:
        """Max line width inside a bubble — stay inside fill + border so text never hugs the stroke."""
        try:
            o = int(outer_wrap)
        except (TypeError, ValueError):
            o = 300
        return max(200, o - 52)

    def _chat_bubble_wraplength(self):
        """Largeur de repli des bulles : 300 en base, jusqu'à 500 si la fenêtre est élargie (responsive)."""
        try:
            w = self._chat_messages_inner.winfo_width()
            if w and w > 1:
                return max(280, min(460, w - 120))
        except (tk.TclError, AttributeError):
            pass
        return 300

    def _update_chat_bubble_wraplengths(self):
        """Met à jour le wraplength de toutes les bulles du chat selon la largeur actuelle (responsive)."""
        wrap = self._inner_bubble_wraplength(self._chat_bubble_wraplength())
        for lbl in getattr(self, "_chat_bubble_labels", []):
            try:
                if lbl.winfo_exists():
                    lbl.configure(wraplength=wrap)
            except (tk.TclError, AttributeError):
                pass

    def _update_chat_nav_indicator(self):
        """Affiche ou masque le triangle ⚠ à droite de l'onglet Chat dans la sidebar."""
        ind = getattr(self, "_nav_chat_indicator", None)
        if ind is not None:
            show = getattr(self, "_chat_needs_reset_indicator", False)
            ind.configure(text="⚠" if show else "")
            # Quand Chat actif : même fond que le menu (SEL_BG). Sinon transparent.
            ind.configure(fg_color=SEL_BG if (show and getattr(self, "_page", None) == "chat") else "transparent")
            if show:
                try:
                    ind.lift()  # Au-dessus du btn (place() le met derrière sans lift)
                except Exception:
                    pass

    def _update_help_nav_indicator(self):
        """Affiche ou masque le triangle ⚠ à droite de l'onglet Help dans la sidebar (même logique que Chat)."""
        ind = getattr(self, "_nav_help_indicator", None)
        if ind is not None:
            show = getattr(self, "_help_needs_reset_indicator", False)
            ind.configure(text="⚠" if show else "")
            ind.configure(fg_color=SEL_BG if (show and getattr(self, "_page", None) == "help") else "transparent")
            if show:
                try:
                    ind.lift()
                except Exception:
                    pass

    def _set_chat_reset_indicator_if_outside_chat(self):
        """Appelé quand limite contexte/output atteinte : afficher ⚠ sur Chat dans la sidebar ; si déjà sur Chat, faire clignoter New chat."""
        self._chat_needs_reset_indicator = True
        self._update_chat_nav_indicator()
        if getattr(self, "_page", None) == "chat" and getattr(self, "_chat_new_btn", None):
            self.root.after(100, self._start_chat_new_btn_blink)

    def _set_help_reset_indicator_if_outside_help(self):
        """Limite contexte/output Help atteinte : ⚠ sur Help dans la sidebar ; si déjà sur Help, clignoter New chat."""
        self._help_needs_reset_indicator = True
        self._update_help_nav_indicator()
        if getattr(self, "_page", None) == "help" and getattr(self, "_help_new_btn", None):
            self.root.after(100, self._start_help_new_btn_blink)

    def _start_chat_new_btn_blink(self):
        """Fait clignoter le bouton New chat en rouge (3×) pour inviter au reset après limite contexte."""
        btn = getattr(self, "_chat_new_btn", None)
        if not btn:
            return
        if getattr(self, "_chat_new_btn_blink_job", None):
            try:
                self.root.after_cancel(self._chat_new_btn_blink_job)
            except Exception:
                pass
            self._chat_new_btn_blink_job = None
        blink_times = 6
        blink_on_ms = 300
        blink_off_ms = 300
        normal_fg = CARD
        alert_fg = "#DC2626"

        def _blink_step(remaining):
            if remaining <= 0:
                # Reste rouge jusqu'au clic sur New chat (comme Help)
                btn.configure(fg_color=alert_fg)
                self._chat_new_btn_blink_job = None
                return
            is_on = (blink_times - remaining) % 2 == 0
            btn.configure(fg_color=alert_fg if is_on else normal_fg)
            self._chat_new_btn_blink_job = self.root.after(
                blink_on_ms if is_on else blink_off_ms,
                lambda: _blink_step(remaining - 1),
            )
        _blink_step(blink_times)

    def _start_help_new_btn_blink(self):
        """Fait clignoter le bouton New chat (Help) en rouge (3×) et le laisse rouge pour inviter au reset."""
        btn = getattr(self, "_help_new_btn", None)
        if not btn:
            return
        if getattr(self, "_help_new_btn_blink_job", None):
            try:
                self.root.after_cancel(self._help_new_btn_blink_job)
            except Exception:
                pass
            self._help_new_btn_blink_job = None
        blink_steps = 6  # 3× on/off
        blink_on_ms = 300
        blink_off_ms = 300
        normal_fg = CARD
        alert_fg = "#DC2626"

        def _blink_step(remaining):
            if remaining <= 0:
                # Stay red until user clicks New chat
                btn.configure(fg_color=alert_fg)
                self._help_new_btn_blink_job = None
                return
            is_on = (blink_steps - remaining) % 2 == 0
            btn.configure(fg_color=alert_fg if is_on else normal_fg)
            self._help_new_btn_blink_job = self.root.after(
                blink_on_ms if is_on else blink_off_ms,
                lambda: _blink_step(remaining - 1),
            )
        _blink_step(blink_steps)

    def _on_chat_new(self):
        """Clear Ask history and summaries so the LLM no longer receives previous Q/A; refresh chat tab. New greeting on next display."""
        self._chat_needs_reset_indicator = False
        self._update_chat_nav_indicator()
        self._cached_greeting_chat = None
        self._cached_greeting_key_chat = None
        self._request_llm_greeting("chat")
        if getattr(self, "_chat_new_btn_blink_job", None):
            try:
                self.root.after_cancel(self._chat_new_btn_blink_job)
            except Exception:
                pass
            self._chat_new_btn_blink_job = None
        if getattr(self, "_chat_new_btn", None):
            self._chat_new_btn.configure(fg_color=CARD)
        if getattr(self, "orch", None):
            self.orch.clear_answer_context()
        self._refresh_chat_tab()

    def _on_chat_save_log(self):
        """Save chat log to clipboard or file (reuse console log save if applicable)."""
        if getattr(self, "orch", None):
            history = getattr(self.orch, "_answer_history", [])
            if not history:
                self._notify(self._get_alert("regular.no_logs_to_save"), restore_after_ms=2000)
                return
            lines = []
            uname = self._chat_username()
            for e in history:
                q, a = e.get("q", ""), e.get("a", "")
                if q:
                    lines.append(f"{uname}: {q}")
                if a:
                    lines.append(f"PerkySue: {self._assistant_bubble_visible_text(a)}")
                lines.append("")
            text = "\n".join(lines).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._notify(self._get_alert("regular.all_logs_copied"), restore_after_ms=2000)
        else:
            self._notify(self._get_alert("regular.no_logs_to_save"), restore_after_ms=2000)

    def _on_help_new(self):
        """Clear Help history and refresh Help tab."""
        self._help_needs_reset_indicator = False
        self._update_help_nav_indicator()
        # Reset any "needs reset" blink state
        if getattr(self, "_help_new_btn_blink_job", None):
            try:
                self.root.after_cancel(self._help_new_btn_blink_job)
            except Exception:
                pass
            self._help_new_btn_blink_job = None
        if getattr(self, "_help_new_btn", None):
            try:
                self._help_new_btn.configure(fg_color=CARD)
            except Exception:
                pass
        # Reset greeting cache so a fresh Help greeting can be requested
        self._cached_greeting_help = None
        self._cached_greeting_key_help = None
        if getattr(self, "orch", None) and getattr(self.orch, "clear_help_context", None):
            self.orch.clear_help_context()
        # Request a new greeting and refresh
        self._request_llm_greeting("help")

    def _on_help_save_log(self):
        """Save Help Q/A log to a text file in the user's Downloads folder."""
        gh = self._get_greeting_text("help") or ""
        lines = [f"PerkySue: {self._assistant_bubble_visible_text(gh)}", ""]
        if getattr(self, "orch", None):
            history = getattr(self.orch, "_help_history", [])
            for e in history:
                q, a = e.get("q", ""), e.get("a", "")
                if q:
                    lines.append(f"{self._chat_username()}: {q}")
                if a:
                    lines.append(f"PerkySue: {self._assistant_bubble_visible_text(a)}")
                lines.append("")
        text = "\n".join(lines).strip()
        try:
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"PerkySue_Help_log_{ts}.txt"
            filepath = downloads / filename
            filepath.write_text(text, encoding="utf-8")
            self._notify(f"Saved to Downloads: {filename}", restore_after_ms=3000)
        except Exception as e:
            logger.exception("Help save log failed: %s", e)
            self._notify("Could not save file. Check permissions or path.", restore_after_ms=3000)

    def _on_help_send(self, event=None):
        self._on_help_send_click()

    def _on_help_send_click(self):
        """Send message from Help input (runs Help mode pipeline)."""
        text = (self._help_input.get() or "").strip()
        if not text:
            return
        self._help_input.delete(0, "end")
        if getattr(self, "orch", None) and getattr(self.orch, "run_help_text", None):
            self.orch.run_help_text(text)

    def _on_help_mic(self):
        """Start Help mode from Help tab (voice). Opens Help tab, shows Listening, starts recording."""
        if not getattr(self, "orch", None) or not getattr(self.orch, "_on_hotkey_toggle", None):
            return
        self._go("help")
        self.set_status("listening")
        def _run():
            try:
                self.orch._on_hotkey_toggle("help")
            except Exception:
                pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _on_chat_send(self, event=None):
        self._on_chat_send_click()

    def _on_chat_send_click(self):
        """Send message from chat input (same pipeline as Alt+A)."""
        text = (self._chat_input.get() or "").strip()
        if not text:
            return
        self._chat_input.delete(0, "end")
        if getattr(self, "orch", None) and getattr(self.orch, "run_answer_text", None):
            self.orch.run_answer_text(text)

    def _on_chat_mic(self):
        """Start Ask mode from chat (voice). Ouvre Chat, affiche Listening + micro rouge, lance l'enregistrement en thread (pas de double son STT)."""
        if not getattr(self, "orch", None) or not getattr(self.orch, "_on_hotkey_toggle", None):
            return
        if getattr(self.orch, "is_continuous_chat_enabled", None) and self.orch.is_continuous_chat_enabled():
            self.orch.set_continuous_chat_enabled(False)
            self._notify(
                s("chat.continuous_stopped", default="Continuous Chat stopped."),
                restore_after_ms=2500,
            )
            return
        self._go("chat")
        # Mettre à jour le statut sur le thread principal pour que la colonne gauche et le micro passent tout de suite en Listening/rouge
        self.set_status("listening")
        # Lancer l'enregistrement en arrière-plan pour ne pas bloquer la GUI (sons STT/LLM joués une seule fois par _record_and_process)
        def _run():
            try:
                self.orch._on_hotkey_toggle("answer", from_chat_ui=True)
            except Exception:
                pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _on_chat_continuous_toggle(self):
        orch = getattr(self, "orch", None)
        sw = getattr(self, "_chat_continuous_switch", None)
        if not orch or sw is None:
            return
        want = _ctk_switch_is_on(sw)
        ok, msg = orch.set_continuous_chat_enabled(want)
        now_on = bool(getattr(orch, "is_continuous_chat_enabled", None) and orch.is_continuous_chat_enabled())
        if now_on:
            sw.select()
        else:
            sw.deselect()
        if not ok and want:
            self._notify(
                s("chat.continuous_no_llm", default="Continuous Chat needs a working local LLM."),
                restore_after_ms=4000,
                blink_times=2,
            )
            return
        if now_on:
            self._go("chat")
            self._notify(
                s("chat.continuous_started", default="Continuous Chat started — speak naturally."),
                restore_after_ms=2500,
            )
        elif msg != "already_off":
            self._notify(
                s("chat.continuous_stopped", default="Continuous Chat stopped."),
                restore_after_ms=2500,
            )

    def _on_shortcut_edit_click(self, mode_id: str, slot: str = "main"):
        """Start listening for a new key combination for this mode/slot (main or altgr); show Listening state."""
        if not self._is_shortcut_editable_for_tier(mode_id):
            return
        if getattr(self, "_shortcuts_listening_mode", None) is not None:
            return
        self._shortcuts_listening_mode = mode_id
        self._shortcuts_listening_slot = slot
        data = self._shortcuts_hotkey_btns.get(mode_id)
        btn = None
        if isinstance(data, dict):
            btn, _ = data.get(slot, (None, None))
        else:
            btn, _ = data if data else (None, None)
        if btn:
            btn.configure(text="Listening...", fg_color=ACCENT, hover_color=SEL_BG, border_width=2, border_color=BLUE)
        self._shortcuts_listen_hint.configure(text="Press new key combination or ESC to cancel.")
        self.root.focus_set()
        if getattr(self, "orch", None) and hasattr(self.orch, "pause_hotkeys"):
            self.orch.pause_hotkeys()
        self._shortcuts_key_bind_id = self.root.bind("<KeyPress>", self._on_shortcut_key_capture, add="+")
        # Escape is handled by _on_escape_global (bound once at startup)

    def _on_shortcut_cancel_listen(self, event=None):
        """Cancel listening and restore button."""
        mode_id = getattr(self, "_shortcuts_listening_mode", None)
        if mode_id is None:
            return
        self._shortcuts_listening_mode = None
        slot = getattr(self, "_shortcuts_listening_slot", "main")
        try:
            self.root.unbind("<KeyPress>", self._shortcuts_key_bind_id)
        except Exception:
            pass
        self._shortcuts_listen_hint.configure(text="")
        self._shortcuts_refresh_hotkey_button(mode_id, slot=slot)
        if getattr(self, "orch", None) and hasattr(self.orch, "resume_hotkeys"):
            self.orch.resume_hotkeys()

    def _on_shortcut_key_capture(self, event):
        """Build hotkey string from event (use keycode for physical key, so AltGr+R gives r not layout character) and save."""
        mode_id = getattr(self, "_shortcuts_listening_mode", None)
        if mode_id is None:
            return
        mod_only = {"shift_l", "shift_r", "control_l", "control_r", "alt_l", "alt_r", "meta_l", "meta_r", "caps_lock"}
        keysym_lower = (event.keysym or "").lower()
        if keysym_lower in mod_only:
            return
        state = getattr(event, "state", 0) or 0
        parts = []
        if state & 0x0004:
            parts.append("ctrl")
        if state & 0x0008:
            parts.append("alt")
        if state & 0x0001:
            parts.append("shift")
        key = None
        is_altgr = (state & 0x0004) and (state & 0x0008)
        if is_altgr and len(keysym_lower) == 1 and keysym_lower in "abcdefghijklmnopqrstuvwxyz":
            key = keysym_lower
        if not key:
            keycode = getattr(event, "keycode", None)
            if keycode is not None and keycode in KEYCODE_TO_NAME:
                key = KEYCODE_TO_NAME[keycode]
        if not key and keysym_lower and keysym_lower not in mod_only:
            key = keysym_lower
        if key:
            parts.append(key)
        if not parts:
            return
        hotkey_str = "+".join(parts)
        hotkey_normalized = hotkey_str.lower().strip()
        self._shortcuts_listening_mode = None
        try:
            self.root.unbind("<KeyPress>", self._shortcuts_key_bind_id)
        except Exception:
            pass
        self._shortcuts_listen_hint.configure(text="")
        hotkeys_cfg = dict(self.cfg.get("hotkeys", {}))
        if getattr(self, "orch", None) and getattr(self.orch, "config", None):
            hotkeys_cfg = dict(self.orch.config.get("hotkeys", {}))
        slot = getattr(self, "_shortcuts_listening_slot", "main")
        config_key = mode_id if slot == "main" else (mode_id + "_altgr")
        # Vérifier si ce raccourci est déjà attribué à une autre fonction
        for other_id, other_hk in hotkeys_cfg.items():
            if other_id == "behavior" or other_id == config_key:
                continue
            if (other_hk or "").lower().strip() == hotkey_normalized:
                base = other_id.replace("_altgr", "")
                if base == "stop_recording":
                    other_name = "Stop Task"
                elif base == "reinject_last":
                    other_name = s("shortcuts.reinject_last_task")
                elif getattr(self, "orch", None) and getattr(self.orch, "modes", None) and base in self.orch.modes:
                    other_name = self.orch.modes[base].name
                else:
                    other_name = base.replace("custom", "Custom prompt ").replace("genz", "GenZ").title()
                self._notify(
                    self._get_alert("critical.shortcut_in_use", other_name=other_name),
                    restore_after_ms=5000,
                    blink_times=3,
                    blink_on_ms=300,
                    blink_off_ms=300,
                )
                self._shortcuts_refresh_hotkey_button(mode_id, slot=slot)
                if getattr(self, "orch", None) and hasattr(self.orch, "resume_hotkeys"):
                    self.orch.resume_hotkeys()
                return "break"
        hotkeys_cfg[config_key] = hotkey_str
        self._save_config({"hotkeys": hotkeys_cfg})
        self.cfg = self._load_cfg()
        self._shortcuts_refresh_hotkey_button(mode_id, slot=slot, hotkeys_override=hotkeys_cfg)
        self._trigger_save()
        if getattr(self, "orch", None) and hasattr(self.orch, "resume_hotkeys"):
            self.orch.resume_hotkeys()
        return "break"

    def _shortcuts_refresh_hotkey_button(self, mode_id: str, slot: str = None, hotkeys_override: dict = None):
        """Reset hotkey button to normal style and current value. hotkeys_override = config à utiliser pour l’affichage (nouveau shortcut visible tout de suite)."""
        if mode_id == "answer":
            self._shortcuts_refresh_hotkey_button("answer_free", slot=slot, hotkeys_override=hotkeys_override)
            self._shortcuts_refresh_hotkey_button("answer_pro", slot=slot, hotkeys_override=hotkeys_override)
            return
        data = self._shortcuts_hotkey_btns.get(mode_id)
        if not data or not isinstance(data, dict):
            return
        if hotkeys_override is not None:
            hotkeys_cfg = hotkeys_override
        else:
            hotkeys_cfg = dict(self.cfg.get("hotkeys", {}))
            if getattr(self, "orch", None) and getattr(self.orch, "config", None):
                hotkeys_cfg = dict(self.orch.config.get("hotkeys", {}))
        real_mode = mode_id
        if mode_id in ("answer_free", "answer_pro"):
            real_mode = "answer"

        def _dmain():
            hk = hotkeys_cfg.get(real_mode, "")
            return "+".join(p.capitalize() for p in (hk or "").lower().strip().split("+")) if hk else "—"
        def _daltgr():
            hk = hotkeys_cfg.get(real_mode + "_altgr", "")
            if hk:
                return "+".join(p.capitalize() for p in hk.lower().strip().split("+"))
            return "Ctrl+" + _dmain() if hotkeys_cfg.get(real_mode) else "—"
        for _s in (["main", "altgr"] if slot is None else [slot]):
            btn, _ = data.get(_s, (None, None))
            if not btn:
                continue
            display = _dmain() if _s == "main" else _daltgr()
            btn.configure(text=display, fg_color=INPUT, hover_color=SEL_BG, border_width=0)

    def _on_shortcuts_restore_default(self):
        """Restore hotkeys from App/configs/defaults.yaml and show Save & Restart."""
        try:
            defaults_path = self.paths._app / "configs" / "defaults.yaml"
            if not defaults_path.exists():
                return
            with open(defaults_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            default_hk = data.get("hotkeys") or {}
            if not isinstance(default_hk, dict):
                return
            # Replace hotkeys section atomically (not deep-merge), so removed keys from defaults
            # do not persist in Data/Configs/config.yaml.
            p = self.paths.user_config_file
            p.parent.mkdir(parents=True, exist_ok=True)
            current = {}
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        current = yaml.safe_load(f) or {}
                except Exception:
                    current = {}
            current["hotkeys"] = dict(default_hk)
            with open(p, "w", encoding="utf-8") as f:
                yaml.dump(current, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            self.cfg = self._load_cfg()
            # Affichage instantané des valeurs par défaut (avant Save & Restart)
            for mode_id in list(self._shortcuts_hotkey_btns.keys()):
                self._shortcuts_refresh_hotkey_button(mode_id, hotkeys_override=default_hk)
            self._shortcuts_listen_hint.configure(text="")
            self._trigger_save()
        except Exception:
            pass

    def _is_shortcut_editable_for_tier(self, mode_id: str) -> bool:
        """Return whether a shortcut is editable for current gating tier.
        Rule: Free tier can edit only transcribe (Alt+T) and help (Alt+H).
        """
        tier = "free"
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                tier = (self.orch.get_gating_tier() or "free")
        except Exception:
            tier = "free"
        tier_l = str(tier).lower()
        if mode_id in ("stop_recording", "reinject_last"):
            return True  # Always editable
        if tier_l == "free":
            return mode_id in ("transcribe", "help")
        return True

    def _refresh_shortcuts_plan_restrictions(self):
        """Refresh shortcuts editability in-place after plan change."""
        hotkey_cfg = (self.cfg.get("hotkeys") or {}) if isinstance(getattr(self, "cfg", None), dict) else {}
        for mode_id, slots in (getattr(self, "_shortcuts_hotkey_btns", {}) or {}).items():
            real_id = mode_id
            if mode_id in ("answer_free", "answer_pro"):
                real_id = "answer"
            editable = self._is_shortcut_editable_for_tier(real_id)
            for slot, pair in (slots or {}).items():
                try:
                    btn, edit_btn = pair
                except Exception:
                    continue
                # Refresh hotkey display text first (in case config changed)
                try:
                    if slot == "main":
                        disp = _format_display_hotkey(hotkey_cfg.get(real_id, ""))
                    else:
                        hk_main = hotkey_cfg.get(real_id, "")
                        hk_altgr = hotkey_cfg.get(real_id + "_altgr", "")
                        disp = _format_display_hotkey(hk_altgr) if hk_altgr else _derive_altgr_display(hk_main)
                    if btn is not None:
                        btn.configure(text=disp or "—")
                except Exception:
                    pass

                # Apply editable/non-editable visual + behavior
                try:
                    if btn is not None:
                        if editable:
                            btn.configure(fg_color=INPUT, hover_color=SEL_BG, text_color=TXT, cursor="hand2")
                        else:
                            btn.configure(fg_color=CARD, hover_color=CARD, text_color=MUTED, cursor="arrow")
                except Exception:
                    pass
                try:
                    if edit_btn is not None:
                        if editable:
                            edit_btn.configure(
                                fg_color=INPUT, hover_color=SEL_BG, text_color=TXT2, cursor="hand2",
                                command=(lambda mi=real_id, sl=slot: self._on_shortcut_edit_click(mi, sl)),
                            )
                        else:
                            edit_btn.configure(
                                fg_color=INPUT, hover_color=INPUT, text_color=MUTED, cursor="arrow",
                                command=(lambda: None),
                            )
                except Exception:
                    pass

    def _apply_free_plan_data_reset(self):
        """When switching to Free, clear paid personalization data.
        - identity.name -> ""
        - stt.whisper_keywords -> keep only first 3
        """
        try:
            current_kw = list(getattr(self, "_whisper_keywords", []) or [])
            trimmed_kw = current_kw[:3]
            self._save_config({
                "identity": {"name": ""},
                "stt": {"whisper_keywords": list(trimmed_kw)},
            })
            self.cfg = self._load_cfg()
        except Exception:
            trimmed_kw = (list(getattr(self, "_whisper_keywords", []) or [])[:3])

        # Live UI refresh (Prompt Modes page may already be built)
        try:
            self._whisper_keywords = list(trimmed_kw)
            if hasattr(self, "_rebuild_whisper_kw_tags"):
                self._rebuild_whisper_kw_tags()
        except Exception:
            pass
        try:
            if hasattr(self, "_identity_name_var"):
                self._identity_name_var.set("")
        except Exception:
            pass

        # Live orchestrator config + STT keyword reload
        try:
            if getattr(self, "orch", None) and isinstance(getattr(self.orch, "config", None), dict):
                ident = (self.orch.config.get("identity") or {})
                ident["name"] = ""
                self.orch.config["identity"] = ident
                stt_cfg = (self.orch.config.get("stt") or {})
                stt_cfg["whisper_keywords"] = list(trimmed_kw)
                self.orch.config["stt"] = stt_cfg
                if hasattr(self.orch, "reload_stt_keywords"):
                    self.orch.reload_stt_keywords()
        except Exception:
            pass

    def _refresh_prompt_modes_plan_restrictions(self):
        """Refresh plan-dependent restrictions inside the Prompt Modes page (no full rebuild)."""
        if not getattr(self, "pages", None) or "modes" not in self.pages:
            return

        # Plan tier for UI emulation / proofs-based gating.
        tier = "free"
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                tier = self.orch.get_gating_tier() or "free"
        except Exception:
            tier = "free"

        tier_l = str(tier).lower()
        self._whisper_kw_tier = tier_l
        if tier_l == "free":
            self._whisper_kw_limit = 3
        elif tier_l == "enterprise":
            self._whisper_kw_limit = None
        else:
            self._whisper_kw_limit = 10

        # Update Whisper keywords header text.
        kw_lbl = getattr(self, "_whisper_kw_title_lbl", None)
        if kw_lbl:
            if self._whisper_kw_limit is None:
                kw_lbl.configure(text=s("modes.stt_keywords.title_unlimited"))
            else:
                kw_lbl.configure(text=s("modes.stt_keywords.title_limit").format(limit=self._whisper_kw_limit))

        # Identity (Your Name) — champ sur la page User ; même logique Free / Pro.
        identity_edit_enabled = tier_l != "free"
        self._identity_edit_enabled = identity_edit_enabled
        name_entry = getattr(self, "_identity_name_entry", None)
        if name_entry:
            if identity_edit_enabled:
                try:
                    name_entry.configure(state="normal", text_color=TXT, fg_color=INPUT, cursor="xterm")
                    # Re-bind if it was previously disabled.
                    name_entry.bind("<FocusOut>", self._on_identity_name_change)
                    name_entry.bind("<Return>", self._on_identity_name_change)
                except Exception:
                    pass
            else:
                try:
                    name_entry.configure(state="disabled", text_color=MUTED, fg_color=CARD, cursor="arrow")
                except Exception:
                    pass

        # Refresh keyword tags counter + limit.
        try:
            self._rebuild_whisper_kw_tags()
        except Exception:
            pass

        # Prompt Modes action buttons (Edit/Test/Run Test): lock on Free, clickable redirect to Help.
        try:
            for mode_id, ui in (getattr(self, "_mode_ui", {}) or {}).items():
                locked = (tier_l == "free")
                edit_btn = ui.get("edit_btn")
                test_btn = ui.get("test_btn")
                run_btn = ui.get("run_btn")
                prompt_box = ui.get("prompt_box")
                save_btn = ui.get("save_btn")
                cancel_btn = ui.get("cancel_btn")
                test_frame = ui.get("test_frame")

                if locked:
                    # Force read-only UI if the mode was being edited.
                    try:
                        if prompt_box is not None:
                            self._set_prompt_box_readonly(prompt_box)
                    except Exception:
                        pass
                    try:
                        if test_frame is not None and test_frame.winfo_ismapped():
                            test_frame.pack_forget()
                    except Exception:
                        pass
                    try:
                        if save_btn is not None:
                            save_btn.pack_forget()
                        if cancel_btn is not None:
                            cancel_btn.pack_forget()
                    except Exception:
                        pass
                    try:
                        if edit_btn is not None and not edit_btn.winfo_ismapped():
                            edit_btn.pack(side="left", padx=(0, 6))
                        if test_btn is not None and not test_btn.winfo_ismapped():
                            test_btn.pack(side="left", padx=(0, 6))
                    except Exception:
                        pass

                def _locked_cmd(mid=mode_id):
                    self._go_help_locked_prompt_mode(mid, action="edit")

                def _locked_test_cmd(mid=mode_id):
                    self._go_help_locked_prompt_mode(mid, action="test")

                # Style + command
                if edit_btn is not None:
                    if locked:
                        edit_btn.configure(
                            fg_color=INPUT, hover_color=INPUT, text_color=MUTED, cursor="hand2", command=_locked_cmd
                        )
                    else:
                        edit_btn.configure(
                            fg_color=INPUT, hover_color=SEL_BG, text_color=TXT, cursor="hand2",
                            command=(lambda m=mode_id: self._on_mode_edit(m)),
                        )
                if test_btn is not None:
                    if locked:
                        test_btn.configure(
                            fg_color=INPUT, hover_color=INPUT, text_color=MUTED, cursor="hand2", command=_locked_test_cmd
                        )
                    else:
                        test_btn.configure(
                            fg_color=ACCENT, hover_color=SEL_BG, text_color="white", cursor="hand2",
                            command=(lambda m=mode_id: self._on_mode_test(m)),
                        )
                if run_btn is not None:
                    if locked:
                        run_btn.configure(
                            fg_color=INPUT, hover_color=INPUT, text_color=MUTED, cursor="hand2", command=_locked_test_cmd
                        )
                    else:
                        run_btn.configure(
                            fg_color=ACCENT, hover_color=SEL_BG, text_color="white", cursor="hand2",
                            command=(lambda m=mode_id: self._on_mode_run_test(m)),
                        )
        except Exception:
            pass

    def _go_help_locked_prompt_mode(self, mode_id: str, action: str = "edit"):
        """Redirect locked Prompt Modes action to Help with auto-posted first-person message."""
        try:
            self._go("help")
            # Keep Help type-in empty.
            hi = getattr(self, "_help_input", None)
            if hi is not None:
                try:
                    hi.delete(0, "end")
                except Exception:
                    pass
            if hasattr(self, "_mark_help_skip_greeting_once"):
                self._mark_help_skip_greeting_once()

            # On small context windows (2048), auto-redirect questions should start from a clean
            # Help context to avoid immediate context-limit errors due to prior Help history.
            try:
                max_ctx = 8192
                if getattr(self, "orch", None) and hasattr(self.orch, "get_effective_llm_n_ctx"):
                    max_ctx = int(self.orch.get_effective_llm_n_ctx())
                if max_ctx <= 2048 and getattr(self, "orch", None) and hasattr(self.orch, "clear_help_context"):
                    self.orch.clear_help_context()
            except Exception:
                pass

            # Build English template; orchestrator translates for user bubble when possible.
            mode_name = mode_id
            try:
                if getattr(self, "orch", None) and getattr(self.orch, "modes", None):
                    mobj = self.orch.modes.get(mode_id)
                    if mobj and getattr(mobj, "name", None):
                        mode_name = str(mobj.name)
            except Exception:
                pass
            hk = ""
            try:
                cfg = getattr(self, "orch", None) and getattr(self.orch, "config", None)
                if isinstance(cfg, dict):
                    hk = ((cfg.get("hotkeys") or {}).get(mode_id) or "").upper()
            except Exception:
                hk = ""
            suffix = f" ({hk})" if hk else ""
            if str(action).lower() == "test":
                hint_en = f"I'm trying to test Prompt Mode \"{mode_name}\"{suffix}. It's locked on the Free plan. How do I unlock Pro?"
            else:
                hint_en = f"I'm trying to edit Prompt Mode \"{mode_name}\"{suffix}. It's locked on the Free plan. How do I unlock Pro?"

            first_lang = "auto"
            try:
                if getattr(self, "orch", None) and hasattr(self.orch, "config"):
                    first_lang = (self.orch.config.get("identity") or {}).get("first_language", "auto")
            except Exception:
                first_lang = "auto"
            lang = (self.orch.last_stt_detected_language or "en")[:2] if (first_lang or "").strip().lower() == "auto" else (str(first_lang)[:2] if first_lang else "en")
            lang = (lang or "en").lower()

            if getattr(self, "orch", None) and hasattr(self.orch, "run_help_text"):
                self.orch.run_help_text(hint_en, source_lang=lang, translate_user_text=True, silent=True)
            self._notify_pro_locked()
        except Exception:
            pass

    def _rebuild_whisper_kw_tags(self):
        """Rebuild the tag widgets for Whisper keywords and update counter.
        Tags are sized to word length + 10px padding each side; wrap to next line when row is full.
        """
        for w in self._whisper_kw_tags_frame.winfo_children():
            w.destroy()

        if not self._whisper_keywords:
            self._whisper_kw_tags_frame.pack_forget()
            self._whisper_kw_count_lbl.configure(text=self._whisper_kw_tags_counter_text(0))
            return

        self._whisper_kw_tags_frame.pack(**self._whisper_kw_tags_pack_opts)
        # Utiliser la largeur de la card (moins les paddings) pour estimer la place disponible,
        # afin que les mots-clés ne soient pas empilés verticalement au premier affichage.
        self._whisper_kw_card.update_idletasks()
        try:
            card_w = max(0, int(self._whisper_kw_card.winfo_width()) - 40)
        except (tk.TclError, AttributeError, ValueError):
            card_w = 0
        try:
            frame_w = int(self._whisper_kw_tags_frame.winfo_width())
        except (tk.TclError, AttributeError, ValueError):
            frame_w = 0
        avail_w = max(260, card_w, frame_w if frame_w > 0 else 0)
        tag_gap = 6
        tag_vpad = 2
        row_height = 32
        current_row = None
        current_x = 0

        for i, word in enumerate(self._whisper_keywords):
            est_tag_w = 10 + max(20, min(200, len(word) * 8)) + 4 + 24 + 10 + tag_gap
            need_new_row = current_row is None or (current_x + est_tag_w > avail_w)
            if need_new_row:
                current_row = CTkFrame(self._whisper_kw_tags_frame, fg_color="transparent")
                current_row.pack(fill="x", pady=(0, tag_vpad))
                current_x = 0

            tag_f = CTkFrame(current_row, fg_color=SEL_BG, corner_radius=6, height=row_height - 2 * tag_vpad)
            lbl = CTkLabel(tag_f, text=word, font=("Segoe UI", 12), text_color=TXT)
            lbl.pack(side="left", padx=(10, 4), pady=4)
            idx = i
            rm_btn = CTkButton(
                tag_f, text="×", width=24, height=24, corner_radius=4,
                font=("Segoe UI", 14, "bold"), fg_color="transparent", hover_color=MUTED,
                text_color=TXT2, command=lambda i=idx: self._on_whisper_kw_remove(i),
            )
            rm_btn.pack(side="right", padx=(0, 10), pady=2)
            tag_f.update_idletasks()
            try:
                tag_w = tag_f.winfo_reqwidth()
            except (tk.TclError, AttributeError):
                tag_w = 20 + min(200, len(word) * 8) + 10 + 24 + 10
            tag_f.pack(side="left", padx=(0, tag_gap), pady=tag_vpad)
            current_x += tag_w + tag_gap

        self._whisper_kw_count_lbl.configure(text=self._whisper_kw_tags_counter_text(len(self._whisper_keywords)))

    def _on_whisper_kw_add(self, event=None):
        """Add the current entry text as a Whisper keyword, save and reload STT (limit depends on plan tier)."""
        text = (self._whisper_kw_entry.get() or "").strip()
        self._whisper_kw_entry.delete(0, "end")
        lim = getattr(self, "_whisper_kw_limit", None)
        if not text:
            return
        if lim is not None and len(self._whisper_keywords) >= lim:
            # Free tier limit reached: explain the limits in Help via KB.
            try:
                # Free: explain the limit; Pro: invite Enterprise for more keywords.
                if (getattr(self, "_whisper_kw_tier", "") or "").startswith("free"):
                    question = "Is there a limit to custom STT keywords?"
                else:
                    question = "On Pro, is there a limit to custom STT keywords? How can I unlock more keywords on Enterprise?"
                ident = self.cfg.get("identity") or {}
                first_lang = (ident.get("first_language") or "auto").strip().lower()
                src_lang = (first_lang if first_lang != "auto" else "en")[:2]

                self._go("help")
                if hasattr(self, "_mark_help_skip_greeting_once"):
                    self._mark_help_skip_greeting_once()

                # Keep Help type-in empty.
                hi = getattr(self, "_help_input", None)
                if hi is not None:
                    try:
                        hi.delete(0, "end")
                    except Exception:
                        pass

                if getattr(self, "orch", None) and hasattr(self.orch, "run_help_text"):
                    # Do not translate the user bubble; keep it simple and rely on Help response language.
                    self.orch.run_help_text(question, source_lang=src_lang, translate_user_text=False)
                self._notify("Keyword limit reached — see Help tab.", restore_after_ms=2500)
            except Exception:
                pass
            return
        if text in self._whisper_keywords:
            return
        self._whisper_keywords.append(text)
        self._rebuild_whisper_kw_tags()
        self._save_config({"stt": {"whisper_keywords": list(self._whisper_keywords)}})
        self.cfg = self._load_cfg()
        try:
            if self.orch:
                self.orch.reload_stt_keywords()
        except Exception:
            pass

    def _on_whisper_kw_remove(self, index: int):
        """Remove a Whisper keyword by index, save and reload STT."""
        if 0 <= index < len(self._whisper_keywords):
            self._whisper_keywords.pop(index)
            self._rebuild_whisper_kw_tags()
            self._save_config({"stt": {"whisper_keywords": list(self._whisper_keywords)}})
            self.cfg = self._load_cfg()
            try:
                if self.orch:
                    self.orch.reload_stt_keywords()
            except Exception:
                pass

    def _on_identity_name_change(self, event=None):
        """Persist the Identity → Your Name field to config and live Orchestrator config."""
        if not getattr(self, "_identity_edit_enabled", True):
            return
        if not hasattr(self, "_identity_name_var"):
            return
        name = (self._identity_name_var.get() or "").strip()
        self._identity_name_var.set(name)
        # Save to Data/Configs/config.yaml
        self._save_config({"identity": {"name": name}})
        self.cfg = self._load_cfg()
        # Also update in orchestrator.config so it is used without restart
        try:
            if getattr(self, "orch", None) and getattr(self.orch, "config", None):
                cfg = self.orch.config
                ident = cfg.get("identity") or {}
                ident["name"] = name
                cfg["identity"] = ident
        except Exception:
            pass

    # ─── Prompt Modes editing (section 3) ─────────────────────────────

    def _set_prompt_box_editable(self, box):
        """Switch a prompt textbox to editable mode (dark background, text selectable)."""
        try:
            box.configure(state="normal", fg_color=INPUT, cursor="xterm")
            # Remove click/key blockers if any
            for seq in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Key>"):
                box.unbind(seq)
        except Exception:
            pass

    def _set_prompt_box_readonly(self, box):
        """Switch a prompt textbox to read-only mode (grey background, non-selectable)."""
        try:
            box.configure(state="disabled", fg_color=CARD, cursor="arrow")
            def _block(e):
                return "break"
            for seq in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Key>"):
                box.bind(seq, _block)
        except Exception:
            pass

    def _on_prompt_modes_wheel(self, event):
        """Mouse wheel over Prompt Modes text areas → scroll inside text first, then page at top/bottom."""
        try:
            widget = event.widget
            if not hasattr(widget, "yview"):
                return
            y0, y1 = widget.yview()
            at_top = y0 <= 0.0
            at_bottom = y1 >= 1.0
            going_up = event.delta > 0
            going_down = event.delta < 0
            # If we're at a boundary, let the page handler take over.
            if (going_up and at_top) or (going_down and at_bottom):
                return
            step = 3
            direction = -step if going_up else step
            widget.yview_scroll(direction, "units")
            return "break"
        except Exception:
            return

    def _get_mode_ui(self, mode_id: str):
        return getattr(self, "_mode_ui", {}).get(mode_id)

    def _mode_sample_text(self, mode_id: str, code: str) -> str:
        """Return sample text for a mode and code (EN1/EN2/FR1/FR2).

        Source of truth = modes.yaml (App/configs + Data/Configs), déjà chargé par l'orchestrator
        dans self.orch.modes. On lit donc d'abord Mode.test_inputs, puis on retombe
        éventuellement sur les YAML si nécessaire.
        """
        code = (code or "").upper()
        if not code:
            return ""
        # 1) Primary: Mode.test_inputs depuis l'orchestrator (modes.yaml fusionné)
        if self.orch and getattr(self.orch, "modes", None):
            mode_obj = self.orch.modes.get(mode_id)
            if mode_obj is not None:
                ti = getattr(mode_obj, "test_inputs", None) or {}
                txt = ti.get(code, "") or ""
                if str(txt).strip():
                    return str(txt).strip()
        # 2) Fallback: rien trouvé
        return ""

    def _ensure_default_sample_for_mode(self, mode_id: str):
        """If test input is empty, prefill with the first available sample (EN1, EN2, FR1, FR2)."""
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        if ui["test_input"].get("1.0", "end-1c").strip():
            return
        for code in ("EN1", "EN2", "FR1", "FR2"):
            sample = self._mode_sample_text(mode_id, code)
            if sample:
                ui["test_input"].insert("1.0", sample)
                self._mode_active_sample[mode_id] = code
                break

    def _update_mode_sample_pills(self, mode_id: str):
        """Met à jour l'affichage des pills EN1/EN2/FR1/FR2 : le sélectionné en or + blanc (comme Appearance)."""
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        active = self._mode_active_sample.get(mode_id, "EN1")
        btns = ui.get("sample_btns") or {}
        for c, btn in btns.items():
            try:
                is_active = (c == active)
                btn.configure(
                    fg_color=SKIN_SELECTED_BORDER if is_active else INPUT,
                    text_color="white" if is_active else TXT2,
                )
            except Exception:
                continue

    def _on_mode_sample_click(self, mode_id: str, code: str):
        """Click on EN1/EN2/FR1/FR2 button: inject sample (or clear if empty); track active cell for Save; always update pill highlight."""
        self._mode_active_sample[mode_id] = code
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        sample = self._mode_sample_text(mode_id, code) or ""
        box = ui["test_input"]
        try:
            box.delete("1.0", "end")
            if sample:
                box.insert("1.0", sample)
        except Exception:
            pass
        self._update_mode_sample_pills(mode_id)

    def _on_mode_run_test(self, mode_id: str):
        """Actually run the LLM test for a mode, with audio feedback."""
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                if (self.orch.get_gating_tier() or "free").strip().lower() == "free":
                    self._go_help_locked_prompt_mode(mode_id, action="test")
                    return
        except Exception:
            pass
        ui = self._get_mode_ui(mode_id)
        if not ui or not self.orch:
            return

        # Default text if empty, to help first-time users (mode-specific samples).
        self._ensure_default_sample_for_mode(mode_id)

        sample_text = ui["test_input"].get("1.0", "end-1c").strip()
        if not sample_text:
            return

        # Refresh language indicator (config may have changed).
        try:
            ui["test_lang_lbl"].configure(text=self._test_panel_language_label())
        except Exception:
            pass

        # Son stt_stop depuis Default (comme fin de prise de parole) quelle que soit la skin.
        try:
            if getattr(self.orch, "sound_manager", None):
                sm = self.orch.sound_manager
                if hasattr(sm, "play_stt_stop_default_skin"):
                    sm.play_stt_stop_default_skin()
                else:
                    sm.play_stt_stop()
        except Exception:
            pass

        # Clear previous output
        out_box = ui["test_output"]
        out_box.configure(state="normal")
        out_box.delete("1.0", "end")
        # Help mode: do NOT put the full system prompt in the output box (avoids duplication and confusion).
        # Only show "Running test..." then the LLM response. Params + KB are in the system prompt sent to the API (see console logs).
        out_box.insert("1.0", "Running test with current mode prompt...")
        out_box.configure(state="disabled")

        def _worker():
            import logging
            log = logging.getLogger("perkysue")
            try:
                prompt_text = ui["prompt_box"].get("1.0", "end-1c")
                active_sample = (self._mode_active_sample.get(mode_id, "") or "").upper()
                forced_sl = "en" if active_sample.startswith("EN") else ("fr" if active_sample.startswith("FR") else None)
                result = self.orch.test_mode_prompt(
                    mode_id,
                    sample_text,
                    prompt_override=prompt_text,
                    source_lang_override=forced_sl,
                )
            except Exception as e:
                err_str = str(e)
                log.warning("Prompt Modes Run Test failed: %s", e)
                el = err_str.lower()
                if "timed out" in el or "read timeout" in el:
                    result_text = (
                        "Test failed: the LLM did not finish in time (request timeout).\n\n"
                        + self._get_alert("run_test_timeout_hint")
                    )
                    try:
                        msg = self._get_alert("critical.llm_request_timeout")
                        self.root.after(
                            0,
                            lambda m=msg: self._notify(
                                m, restore_after_ms=6000, blink_times=3, blink_on_ms=300, blink_off_ms=300, use_alert_gradient=True
                            ),
                        )
                    except Exception:
                        pass
                elif "400" in err_str or "Bad Request" in err_str:
                    result_text = f"Test failed: {e}\n\n" + self._get_alert("run_test_400_hint")
                    log.warning("Run Test 400: context may exceed Max input. Suggest user increase Settings → Performance → Max input.")
                    try:
                        msg = self._get_alert("critical.llm_error_400")
                        self.root.after(0, lambda: self._notify(msg, restore_after_ms=6000, blink_times=3, blink_on_ms=300, blink_off_ms=300))
                    except Exception:
                        pass
                else:
                    result_text = f"Test failed: {e}"
            else:
                result_text = result or "(empty response)"

            def _update():
                out_box.configure(state="normal")
                out_box.delete("1.0", "end")
                out_box.insert("1.0", result_text)
                out_box.configure(state="disabled")

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_mode_edit(self, mode_id: str):
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                if (self.orch.get_gating_tier() or "free").strip().lower() == "free":
                    self._go_help_locked_prompt_mode(mode_id, action="edit")
                    return
        except Exception:
            pass
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        box = ui["prompt_box"]
        self._set_prompt_box_editable(box)
        ui["initial_prompt"] = box.get("1.0", "end-1c")
        # Toggle buttons: Edit → Save/Cancel
        ui["edit_btn"].pack_forget()
        ui["save_btn"].pack(side="left", padx=(0, 6))
        ui["cancel_btn"].pack(side="left", padx=(0, 6))

    def _on_mode_cancel(self, mode_id: str):
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        box = ui["prompt_box"]
        self._set_prompt_box_editable(box)
        box.delete("1.0", "end")
        box.insert("1.0", ui.get("initial_prompt", ""))
        self._set_prompt_box_readonly(box)
        # Hide live test box on cancel and restore header Test button.
        if ui["test_frame"].winfo_ismapped():
            ui["test_frame"].pack_forget()
        ui["save_btn"].pack_forget()
        ui["cancel_btn"].pack_forget()
        if not ui["test_btn"].winfo_ismapped():
            ui["test_btn"].pack(side="left", padx=(0, 6))
        ui["edit_btn"].pack(side="left", padx=(0, 6))

    def _save_mode_prompt_override(self, mode_id: str, prompt: str, test_inputs: Optional[dict] = None):
        """Persist a mode's system_prompt and optionally test_inputs (EN1/EN2/FR1/FR2) to Data/Configs/modes.yaml."""
        modes_path = self.paths.configs / "modes.yaml"
        modes_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if modes_path.exists():
            try:
                with open(modes_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        mode_block = data.get(mode_id) or {}
        if not isinstance(mode_block, dict):
            mode_block = {}
        mode_obj = None
        if self.orch and getattr(self.orch, "modes", None):
            mode_obj = self.orch.modes.get(mode_id)
        if mode_obj:
            mode_block.setdefault("name", getattr(mode_obj, "name", mode_id))
            mode_block.setdefault("description", getattr(mode_obj, "description", ""))
            mode_block.setdefault("needs_llm", getattr(mode_obj, "needs_llm", True))
        mode_block["system_prompt"] = prompt
        if test_inputs is not None and isinstance(test_inputs, dict):
            mode_block["test_inputs"] = test_inputs
        data[mode_id] = mode_block
        with open(modes_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _on_mode_save(self, mode_id: str):
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        box = ui["prompt_box"]
        self._set_prompt_box_editable(box)
        new_prompt = box.get("1.0", "end-1c").rstrip()
        box.delete("1.0", "end")
        box.insert("1.0", new_prompt)
        self._set_prompt_box_readonly(box)

        # Build test_inputs: current 4 samples, with active cell = current test input text
        test_inputs_to_save = None
        try:
            mode_obj = self.orch.modes.get(mode_id) if (self.orch and getattr(self.orch, "modes", None)) else None
            current_test_text = (ui["test_input"].get("1.0", "end-1c") or "").strip()
            active = self._mode_active_sample.get(mode_id, "EN1")
            ti = dict(getattr(mode_obj, "test_inputs", None) or {})
            for k in ("EN1", "EN2", "FR1", "FR2"):
                ti.setdefault(k, "")
            ti[active] = current_test_text
            test_inputs_to_save = {k: (ti.get(k) or "") for k in ("EN1", "EN2", "FR1", "FR2")}
        except Exception:
            pass
        self._save_mode_prompt_override(mode_id, new_prompt, test_inputs_to_save)

        # Update live Mode object so changes apply immediately
        try:
            if self.orch and getattr(self.orch, "modes", None) and mode_id in self.orch.modes:
                self.orch.modes[mode_id].system_prompt = new_prompt
                if test_inputs_to_save is not None:
                    self.orch.modes[mode_id].test_inputs = test_inputs_to_save
        except Exception:
            pass

        # Close live test box on Save (UI rule) and restore header Test button.
        if ui["test_frame"].winfo_ismapped():
            ui["test_frame"].pack_forget()

        ui["save_btn"].pack_forget()
        ui["cancel_btn"].pack_forget()
        if not ui["test_btn"].winfo_ismapped():
            ui["test_btn"].pack(side="left", padx=(6, 6))
        ui["edit_btn"].pack(side="left", padx=(0, 6))

    def _modes_source_lang_for_test(self) -> str:
        """Raw modes.translate_source (same as test_mode_prompt → render_prompt)."""
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "_load_merged_config"):
                cfg = self.orch._load_merged_config()
            else:
                cfg = self.cfg or {}
            v = (cfg.get("modes") or {}).get("translate_source", "auto")
            return str(v).strip() or "auto"
        except Exception:
            return "auto"

    def _test_panel_language_label(self) -> str:
        """
        Affiche la langue utilisée pour le Test : Whisper (après dictée) ou config (translate_source).
        Affichage sous la forme « Last detected language: xx » pour clarifier l'origine.
        """
        try:
            if getattr(self, "orch", None):
                lang = (getattr(self.orch, "last_stt_detected_language", None) or "").strip()
                if lang:
                    return f"Last detected language: {lang}"
                raw = self._modes_source_lang_for_test().strip().lower()
                if raw and raw not in ("", "auto"):
                    return f"Last detected language: {raw}"
        except Exception:
            pass
        return ""

    def _on_mode_test(self, mode_id: str):
        """Open the live test box (if hidden). After first click, header Test button is hidden."""
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "get_gating_tier"):
                if (self.orch.get_gating_tier() or "free").strip().lower() == "free":
                    self._go_help_locked_prompt_mode(mode_id, action="test")
                    return
        except Exception:
            pass
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        if not self.orch:
            self._notify(self._get_alert("regular.llm_not_available"))
            return

        # Ensure the test frame is visible under the prompt editor.
        if not ui["test_frame"].winfo_ismapped():
            ui["test_frame"].pack(fill="x", padx=10, pady=(0, 8))

        # After first click, the header Test button becomes useless → hide it.
        if ui["test_btn"].winfo_ismapped():
            ui["test_btn"].pack_forget()

        try:
            ui["test_lang_lbl"].configure(text=self._test_panel_language_label())
        except Exception:
            pass

        # Default text if empty, to help first-time users (mode-specific samples).
        self._ensure_default_sample_for_mode(mode_id)
        self._update_mode_sample_pills(mode_id)

    def _on_mode_test_input_paste(self, mode_id: str):
        """Colle le presse-papiers dans la zone Test input du mode."""
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        try:
            text = self.root.clipboard_get()
        except Exception:
            return
        box = ui["test_input"]
        try:
            box.focus_set()
            box.insert("insert", text)
        except Exception:
            pass

    def _on_mode_test_output_copy(self, mode_id: str):
        """Copie le contenu de la preview LLM response dans le presse-papiers."""
        ui = self._get_mode_ui(mode_id)
        if not ui:
            return
        try:
            text = ui["test_output"].get("1.0", "end-1c") or ""
            self.root.clipboard_clear()
            self.root.clipboard_append(text.strip())
            self._notify(self._get_alert("regular.copied_to_clipboard"), restore_after_ms=1500)
        except Exception:
            pass

    def _refresh_console_full_box(self):
        """Remplit la zone Full Console avec _log_lines (et permet les insert futurs)."""
        if not getattr(self, "_console_full_text", None):
            return
        try:
            self._console_full_text.configure(state="normal")
            self._console_full_text.delete("0.0", "end")
            for line in getattr(self, "_log_lines", []):
                self._console_full_text.insert("end", line + "\n")
            self._console_full_text.see("end")
            self._console_full_text.configure(state="disabled")
        except (tk.TclError, AttributeError):
            pass

    def _refresh_console_last_boxes(self):
        """Rafraîchit Full Console et reconstruit Finalized / Temporary Logs depuis _console_entries à l'ouverture de l'onglet."""
        self._refresh_console_full_box()
        self._rebuild_finalized_logs_ui()

    def _mark_help_skip_greeting_once(self):
        """Next Help tab refresh will skip the greeting bubble (one-shot)."""
        self._help_skip_greeting_once = True

    def _refresh_console_pipeline_status(self):
        """Refresh Pipeline Status labels (STT/LLM) without rebuilding the Console page."""
        try:
            # LLM
            llm_active = False
            llm_name = "—"
            try:
                if self.orch and self.orch.llm and self.orch.llm.is_available():
                    llm_name = self.orch.llm.get_name()
                    llm_active = True
            except Exception:
                pass
            eff_free = False
            try:
                if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro"):
                    eff_free = not bool(self.orch.is_effective_pro())
            except Exception:
                eff_free = False
            dot = getattr(self, "_pipeline_llm_dot", None)
            lbl = getattr(self, "_pipeline_llm_lbl", None)
            if dot is not None:
                col = "#F59E0B" if (eff_free and llm_active) else (GREEN_BT if llm_active else "#EF4444")
                dot.configure(fg_color=col)
            if lbl is not None:
                if eff_free and llm_active:
                    text = f"{llm_name} {s('console.help_only_suffix')}"
                    col = MUTED
                else:
                    text = llm_name if llm_active else s("console.no_llm")
                    col = TXT if llm_active else MUTED
                lbl.configure(text=text, text_color=col)
        except Exception:
            pass

    def _append_finalized_entry_card(self, entry: dict, show_separator: bool = False):
        """Ajoute une carte (séparateur + contenu + Copy) dans Finalized / Temporary Logs. entry = {type, text, timestamp}. show_separator=True pour tracer la ligne avant cette carte."""
        inner = getattr(self, "_console_finalized_inner", None)
        if not inner:
            return
        try:
            if not inner.winfo_exists():
                return
        except tk.TclError:
            return
        text = (entry.get("text") or "").strip()
        ts = entry.get("timestamp") or ""
        kind = entry.get("type") or "stt"
        mode_id = (entry.get("mode_id") or "").strip().lower()
        # Effective gating for console logs: in Free, Pro-only entries remain visible but Copy is disabled.
        pro_locked = False
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "can_use_mode_effective"):
                # For summary cards, treat as pro-only in Free.
                if kind == "summary":
                    pro_locked = not bool(self.orch.is_effective_pro()) if hasattr(self.orch, "is_effective_pro") else False
                elif kind in ("llm", "llm_reasoning"):
                    # Console rule (Free): Copy is NOT allowed for ANY LLM entry (including Help).
                    # LLM entries stay visible for debugging, but Copy must redirect to Help.
                    pro_locked = not bool(self.orch.is_effective_pro()) if hasattr(self.orch, "is_effective_pro") else False
        except Exception:
            pro_locked = False
        if kind == "stt":
            source = "Whisper (STT)"
        elif kind == "summary":
            source = "PreviousAnswersSummary"
        elif kind == "llm_reasoning":
            source = s("console.llm_reasoning_source", default="LLM reasoning (thinking)")
        else:
            source = "LLM"
        # Ligne séparatrice : espacement uniforme entre les cellules (évite l'effet "collées")
        if show_separator:
            sep = CTkFrame(inner, height=1, fg_color="#3A3A42")
            sep.pack(fill="x", pady=(4, 4))
        # Carte : marges haut/bas pour garder un vrai espace entre les logs
        card = CTkFrame(inner, fg_color=CARD, corner_radius=8, border_width=1, border_color="#3A3A42")
        card.pack(fill="x", pady=(2, 4))
        card.grid_columnconfigure(0, weight=1)
        top_row = CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(6, 2))
        top_row.grid_columnconfigure(0, weight=1)
        shortcut = entry.get("shortcut") or ""
        nchars = len(text or "")
        header = f"[{ts}] | {source}" if ts else source
        if shortcut:
            header += f" | {shortcut}"
        header += f" | {nchars} chars"
        header_lbl = CTkLabel(top_row, text=header, font=("Consolas", 11), text_color=MUTED)
        header_lbl.grid(row=0, column=0, sticky="w")
        def _go_help_locked():
            try:
                # Navigate to Help and auto-send a short explanation request (type-in stays empty).
                self._go("help")
                # Keep Help type-in empty (auto-send only), and localize the question to the user's language.
                first_lang = "auto"
                try:
                    if getattr(self, "orch", None) and hasattr(self.orch, "config"):
                        first_lang = (self.orch.config.get("identity") or {}).get("first_language", "auto")
                except Exception:
                    first_lang = "auto"

                lang = (self.orch.last_stt_detected_language or "en")[:2] if (first_lang or "").strip().lower() == "auto" else (str(first_lang)[:2] if first_lang else "en")
                lang = (lang or "en").lower()
                hint_en = "I'm trying to use the \"Copy\" button in the Console, but it is locked on the Free plan. Why, and how do I unlock it (Pro)?"

                # Clear type-in so the user doesn't see the auto-generated prompt inside the textbox.
                hi = getattr(self, "_help_input", None)
                if hi is not None:
                    try:
                        hi.delete(0, "end")
                    except Exception:
                        pass

                if hasattr(self, "_mark_help_skip_greeting_once"):
                    self._mark_help_skip_greeting_once()

                # Auto-send the Help question.
                try:
                    if getattr(self, "orch", None) and hasattr(self.orch, "run_help_text"):
                        self.orch.run_help_text(hint_en, source_lang=lang, translate_user_text=True, silent=True)
                except Exception:
                    pass

                self._notify_pro_locked()
            except Exception:
                pass
        copy_btn = CTkButton(
            top_row, text=s("console.copy"), width=80, height=28, corner_radius=6, font=("Segoe UI", 13, "bold"),
            fg_color=(INPUT if pro_locked else ACCENT),
            hover_color=(INPUT if pro_locked else SEL_BG),
            text_color=(MUTED if pro_locked else "white"),
            command=(_go_help_locked if pro_locked else (lambda t=text: self._copy_to_clipboard(t))),
        )
        if pro_locked:
            try:
                copy_btn.configure(cursor="hand2")
            except Exception:
                pass
        copy_btn.grid(row=0, column=1, padx=(8, 0))
        # Label : wraplength = largeur réelle de la carte moins padding, pour ne pas dépasser le bord noir
        lbl_color = MUTED if pro_locked else TXT
        lbl = CTkLabel(card, text=text or "—", font=("Consolas", 12), text_color=lbl_color, wraplength=350, justify="left", anchor="w")
        lbl.pack(fill="x", padx=12, pady=(0, 6), anchor="w")

        def _set_wraplength_from_card(e=None, l=lbl, c=card):
            # Largeur réelle de la carte - padx 12*2 - marge droite (scrollbar / sécurité + 10px visibles)
            width = c.winfo_width() if e is None else getattr(e, "width", c.winfo_width())
            w = max(180, width - 60)
            try:
                l.configure(wraplength=w)
            except (tk.TclError, AttributeError):
                pass
        card.bind("<Configure>", _set_wraplength_from_card)
        self.root.after(150, lambda: _set_wraplength_from_card(None))

        # Molette : scroll de la section Finalized d'abord (comme Appearance)
        for w in (card, top_row, header_lbl, copy_btn, lbl):
            try:
                w.bind("<MouseWheel>", self._on_finalized_logs_wheel)
            except tk.TclError:
                pass
        try:
            c = getattr(inner, "_parent_canvas", None)
            if c:
                self.root.after(50, lambda canvas=c: canvas.yview_moveto(1.0))
        except Exception:
            pass

    def _copy_to_clipboard(self, content: str):
        if (content or "").strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(content.strip())
            self.root.update()
            self._notify(self._get_alert("regular.copied_to_clipboard"), restore_after_ms=1500)

    def _rebuild_finalized_logs_ui(self):
        """Reconstruit toutes les cartes Finalized / Temporary Logs depuis _console_entries (ex. à l'ouverture de l'onglet Console)."""
        inner = getattr(self, "_console_finalized_inner", None)
        if not inner:
            return
        try:
            for w in inner.winfo_children():
                w.destroy()
        except (tk.TclError, AttributeError):
            pass
        for i, entry in enumerate(getattr(self, "_console_entries", [])):
            self._append_finalized_entry_card(entry, show_separator=(i > 0))

    def _sync_last_reinject_payload_from_console(self) -> None:
        """
        Alt+R (`reinject_last`) should paste the latest **Finalized log** block (STT / reasoning / LLM / summary),
        i.e. the chronologically last non-empty entry in `_console_entries`, not only the last external injection
        (which can be Q+A formatting or voice-payload plain text while the log ends with the model reply).
        """
        entries = getattr(self, "_console_entries", None)
        orch = getattr(self, "orch", None)
        if not entries or orch is None:
            return
        for entry in reversed(entries):
            txt = (entry.get("text") or "").strip()
            if txt:
                orch._last_inject_payload = txt
                return

    def append_console_finalized_entries(
        self, raw_text: str, final_text: str, mode_id: str = "", reasoning_text: str = ""
    ):
        """Appelé par l'orchestrator après injection : STT, puis raisonnement LLM (optionnel), puis réponse LLM. mode_id pour le shortcut."""
        entries = getattr(self, "_console_entries", None)
        if entries is None:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        shortcut = ""
        if mode_id and getattr(self, "orch", None):
            hk = resolve_hotkey_string(self.orch.config.get("hotkeys") or {}, mode_id)
            shortcut = format_hotkey_display(hk)
        first = True
        appended = False
        if (raw_text or "").strip():
            entry = {"type": "stt", "text": (raw_text or "").strip(), "timestamp": ts, "shortcut": shortcut, "mode_id": mode_id}
            entries.append(entry)
            self._append_finalized_entry_card(entry, show_separator=not first)
            first = False
            appended = True
        if (reasoning_text or "").strip():
            entry = {
                "type": "llm_reasoning",
                "text": (reasoning_text or "").strip(),
                "timestamp": ts,
                "shortcut": shortcut,
                "mode_id": mode_id,
            }
            entries.append(entry)
            self._append_finalized_entry_card(entry, show_separator=not first)
            first = False
            appended = True
        if (final_text or "").strip() and final_text != raw_text:
            entry = {"type": "llm", "text": (final_text or "").strip(), "timestamp": ts, "shortcut": shortcut, "mode_id": mode_id}
            entries.append(entry)
            self._append_finalized_entry_card(entry, show_separator=not first)
            appended = True
        if appended:
            self._sync_last_reinject_payload_from_console()

    def append_previous_answers_summary(self, text: str):
        """Ajoute une entrée PreviousAnswersSummary unique dans Finalized / Temporary Logs."""
        entries = getattr(self, "_console_entries", None)
        if entries is None:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {
            "type": "summary",
            "text": (text or "").strip(),
            "timestamp": ts,
            "shortcut": "Alt+A Summary",
        }
        entries.append(entry)
        # Toujours dessiner un séparateur avant un summary pour le démarquer.
        self._append_finalized_entry_card(entry, show_separator=True)
        if (entry.get("text") or "").strip():
            self._sync_last_reinject_payload_from_console()

    def _go(self, name):
        if self._page == name: return
        for p in self.pages.values(): p.pack_forget()
        if name in self.pages:
            self.pages[name].pack(fill="both", expand=True)
        if name == "chat":
            # Custom pill tabs: show Chat panel + update pill styling
            try:
                if getattr(self, "_chat_panel", None) is not None:
                    self._chat_panel.tkraise()
            except Exception:
                pass
            try:
                if getattr(self, "_chat_pill_btn", None) is not None:
                    self._chat_pill_btn.configure(fg_color=SEL_BG, hover_color=SEL_BG, text_color=TXT)
                if getattr(self, "_help_pill_btn", None) is not None:
                    self._help_pill_btn.configure(fg_color=INPUT, hover_color=SEL_BG, text_color=TXT2)
            except Exception:
                pass
            self._refresh_chat_tab()
            if getattr(self, "_chat_needs_reset_indicator", False) and getattr(self, "_chat_new_btn", None):
                self.root.after(100, self._start_chat_new_btn_blink)
            self._request_llm_greeting("chat")
        elif name == "help":
            try:
                if getattr(self, "_help_panel", None) is not None:
                    self._help_panel.tkraise()
            except Exception:
                pass
            try:
                if getattr(self, "_help_pill_btn", None) is not None:
                    self._help_pill_btn.configure(fg_color=SEL_BG, hover_color=SEL_BG, text_color=TXT)
                if getattr(self, "_chat_pill_btn", None) is not None:
                    self._chat_pill_btn.configure(fg_color=INPUT, hover_color=SEL_BG, text_color=TXT2)
            except Exception:
                pass
            self._refresh_help_tab()
            self._request_llm_greeting("help")
            if getattr(self, "_help_needs_reset_indicator", False) and getattr(self, "_help_new_btn", None):
                self.root.after(100, self._start_help_new_btn_blink)
        elif name == "voice":
            self._voice_pytorch_cuda_auto_prompt_done_this_visit = False
            self._voice_pytorch_cuda_prompt_pending = False
            self._refresh_voice_tab()
        elif name == "brainstorm":
            try:
                ui = getattr(self, "_brainstorm_ui", None)
                if ui is not None and hasattr(ui, "refresh"):
                    ui.refresh()
            except Exception:
                pass
        elif name == "avatar_editor":
            try:
                ui = getattr(self, "_avatar_editor_ui", None)
                if ui is not None:
                    ui.refresh_list()
            except Exception:
                pass
        if name == "console":
            self._refresh_console_last_boxes()
        for pid, nav_tuple in self._nav.items():
            bar = nav_tuple[0]
            btn = nav_tuple[1]
            icon_lbl = nav_tuple[2] if len(nav_tuple) > 2 else None
            if pid == name:
                bar.configure(fg_color=GOLD)
                btn.configure(fg_color=SEL_BG, text_color=TXT)
                if icon_lbl is not None:
                    icon_lbl.configure(fg_color=SEL_BG, text_color=TXT)
            else:
                bar.configure(fg_color=SIDEBAR)
                btn.configure(fg_color="transparent", text_color=TXT2)
                if icon_lbl is not None:
                    icon_lbl.configure(fg_color="transparent", text_color=TXT2)
        if name == "settings":
            try:
                self._request_license_remote_sync(ignore_cooldown=False)
            except Exception:
                pass
        self._page = name
        self._update_chat_nav_indicator()  # Rafraîchir le fond du triangle selon l'onglet actif
        self._update_help_nav_indicator()

    def set_status(self, status_id: str):
        """Met à jour le statut sous l'avatar (thread-safe). Id: listening, processing, generating, injecting, tts_loading, speaking, ready, error, crash, no_speech."""
        def _update():
            if not getattr(self, "_status_lbl", None):
                return
            if getattr(self, "_status_anim_job", None):
                try:
                    self.root.after_cancel(self._status_anim_job)
                except Exception:
                    pass
                self._status_anim_job = None
            self._status_id = status_id
            emoji, label, color = _status_tuple(status_id)
            self._status_lbl.configure(text=f"{emoji} {label}", text_color=color)
            if status_id == "no_speech":
                # Message plus précis si l'orchestrateur a détecté un micro virtuel par défaut
                if getattr(self, "orch", None) and getattr(self.orch, "mic_warning", None):
                    self._show_header_alert("Check your Windows microphone")
                    # Rappeler le sous-message explicatif dans la bannière
                    self._notify(self.orch.mic_warning, restore_after_ms=8000)
                else:
                    self._show_header_alert("Check Your Microphone")
            else:
                self._dismiss_header_alert()
            # Contour de l'avatar principal = même couleur que l'event (espacement noir conservé)
            if getattr(self, "_main_avatar_label", None):
                self._main_avatar_label.configure(
                    cursor="hand2" if status_id in ("listening", "processing", "generating") else "arrow",
                )
                try:
                    main_path = get_avatar_path(self._effective_skin(), paths=self.paths)
                    _rd = 0
                    if status_id in ("speaking", "tts_loading", "listening"):
                        _rd = int(round(float(getattr(self, "_main_avatar_ring_offset_smooth", 0.0) or 0.0)))
                        _rd = max(-9, min(9, _rd))
                    new_main = create_avatar_circle(
                        180, "", 0, is_main=True, img_path=main_path, accent_color=color, ring_offset_px=_rd
                    )
                    self._main_avatar_label.configure(image=new_main)
                    self.main_avatar_img = new_main
                    if status_id not in ("speaking", "tts_loading", "listening"):
                        self._main_avatar_ring_offset_smooth = 0.0
                        self._main_avatar_ring_last_offset = 0
                except Exception:
                    pass
            if status_id in STATUS_PULSE:
                self._start_status_pulse(status_id)
            # Transcription Controls : couleur des boutons Start/Abort selon le statut
            start_btn = getattr(self, "_ctrl_start_btn", None)
            abort_btn = getattr(self, "_ctrl_abort_btn", None)
            if start_btn:
                if status_id == "listening":
                    start_btn.configure(fg_color=GREEN_BT, hover_color=GREEN_HV, text_color="white")
                elif status_id in ("processing", "generating"):
                    start_btn.configure(fg_color="#F59E0B", hover_color="#D97706", text_color="white")
                else:
                    start_btn.configure(fg_color=SEL_BG, hover_color=MUTED, text_color=TXT)
            if abort_btn:
                if status_id in ("listening", "processing", "generating"):
                    abort_btn.configure(fg_color="#EF4444", hover_color="#DC2626", text_color="white")
                else:
                    abort_btn.configure(fg_color=SEL_BG, hover_color=MUTED, text_color=TXT2)
            # Boutons micro Chat et Help : rouge pendant enregistrement / processing, violet sinon
            for mic_btn in [getattr(self, "_chat_mic_btn", None), getattr(self, "_help_mic_btn", None)]:
                if mic_btn:
                    if status_id in ("listening", "processing", "generating"):
                        mic_btn.configure(fg_color="#EF4444", hover_color="#DC2626", text_color="white")
                    else:
                        mic_btn.configure(fg_color=ACCENT, hover_color=SEL_BG, text_color=TXT)
            if status_id == "ready" and getattr(self, "_page", None) == "chat":
                try:
                    self._refresh_chat_tab()
                except Exception:
                    pass
            # Titre de la fenêtre = retour visuel (Listening, Processing, etc.)
            if status_id != "ready":
                emoji, label, _ = _status_tuple(status_id)
                self.root.title("PerkySue — %s %s" % (emoji, label))
            else:
                self.root.title(self._default_window_title())
        try:
            self.root.after(0, _update)
        except (tk.TclError, AttributeError):
            pass

    def _main_avatar_ring_anim_tick(self) -> None:
        """Modulation audio: anneau [-9..+9] px depuis le mètre PCM (sortie TTS ou micro en listening)."""
        if not getattr(self, "_main_avatar_label", None):
            try:
                self.root.after(200, self._main_avatar_ring_anim_tick)
            except Exception:
                pass
            return

        want_pb = False
        want_in = False
        tm = None
        try:
            orch = getattr(self, "orch", None)
            tm = getattr(orch, "tts_manager", None) if orch else None
            rec = getattr(orch, "recorder", None) if orch else None
            spk = bool(tm and getattr(tm, "is_speaking", None) and tm.is_speaking())
            sid = getattr(self, "_status_id", None)
            want_pb = spk or sid in ("speaking", "tts_loading")
            want_in = (sid == "listening") and rec and bool(getattr(rec, "is_recording", False))
        except Exception:
            want_pb = False
            want_in = False

        if want_pb and tm is not None and hasattr(tm, "get_playback_ring_offset_px"):
            try:
                target_off = float(tm.get_playback_ring_offset_px())
            except Exception:
                target_off = 0.0
        elif want_in and tm is not None and hasattr(tm, "get_input_ring_offset_px"):
            try:
                target_off = float(tm.get_input_ring_offset_px())
            except Exception:
                target_off = 0.0
        else:
            target_off = 0.0

        want = want_pb or want_in
        sm = float(getattr(self, "_main_avatar_ring_offset_smooth", 0.0) or 0.0)
        if want:
            # Lissage GUI plus marqué (inertie) pour limiter les à-coups visuels
            sm = sm * 0.66 + target_off * 0.34
        else:
            sm *= 0.72
            if abs(sm) < 0.08:
                sm = 0.0
        sm = max(-9.0, min(9.0, sm))
        self._main_avatar_ring_offset_smooth = sm
        ring_off = int(round(sm))
        ring_off = max(-9, min(9, ring_off))
        last = getattr(self, "_main_avatar_ring_last_offset", None)
        if ring_off != last:
            self._main_avatar_ring_last_offset = ring_off
            try:
                _, _, color = _status_tuple(getattr(self, "_status_id", "ready"))
                main_path = get_avatar_path(self._effective_skin(), paths=self.paths)
                new_main = create_avatar_circle(
                    180, "", 0, is_main=True, img_path=main_path, accent_color=color, ring_offset_px=ring_off
                )
                self._main_avatar_label.configure(image=new_main)
                self.main_avatar_img = new_main
            except Exception:
                pass

        interval = 40 if (want or abs(sm) > 0.05) else 135
        try:
            self.root.after(interval, self._main_avatar_ring_anim_tick)
        except Exception:
            pass

    def _tts_speaking_poll(self) -> None:
        """Keep a dedicated 'speaking' status in sync with TTS playback."""
        try:
            orch = getattr(self, "orch", None)
            tm = getattr(orch, "tts_manager", None) if orch else None
            is_speaking = bool(tm and getattr(tm, "is_speaking", None) and tm.is_speaking())

            cur = getattr(self, "_status_id", None)
            # Ne remplace pas listening/processing/injecting/error/crash ; generating/tts_loading → speaking dès que l'audio part.
            if is_speaking:
                if cur in (None, "ready", "speaking", "generating", "tts_loading"):
                    if cur != "speaking":
                        self.set_status("speaking")
            else:
                if cur == "speaking":
                    try:
                        cont = bool(
                            orch
                            and getattr(orch, "is_continuous_chat_enabled", None)
                            and orch.is_continuous_chat_enabled()
                        )
                    except Exception:
                        cont = False
                    self.set_status("listening" if cont else "ready")
        except Exception:
            pass

        try:
            self._tts_speaking_poll_job = self.root.after(180, self._tts_speaking_poll)
        except Exception:
            self._tts_speaking_poll_job = None

    def _start_status_pulse(self, status_id: str):
        """Pulse léger de couleur pour Listening et Processing."""
        colors = STATUS_PULSE.get(status_id)
        if not colors or not getattr(self, "_status_lbl", None):
            return
        emoji, label, _ = _status_tuple(status_id)
        self._pulse_tick = 0

        def _tick():
            if getattr(self, "_status_id", None) != status_id:
                self._status_anim_job = None
                return
            self._pulse_tick = (getattr(self, "_pulse_tick", 0) + 1) % 2
            col = colors[self._pulse_tick]
            try:
                self._status_lbl.configure(text=f"{emoji} {label}", text_color=col)
            except (tk.TclError, AttributeError):
                self._status_anim_job = None
                return
            self._status_anim_job = self.root.after(450, _tick)

        self._status_anim_job = self.root.after(350, _tick)

# ── PLAN MANAGEMENT (Settings page, top section) ─────────
# Text from settings.plan_management.* in en.yaml; only colors/layout here.
    _PLAN_CARD_STYLE = {
        "free": {
            "name_color": "#CCCCCC",
            "dot": "#555555", "bg": "#2a2a32", "border": "#3a3a44",
        },
        "pro": {
            "name_color": "#b89edf",
            "dot": "#8B5CF6", "bg": "#2f2748", "border": "#5e48a0",
        },
        "enterprise": {
            "name_color": "#D4AF37",
            "dot": "#D4AF37", "bg": "#2e2818", "border": "#5a4d28",
        },
    }
    # 3 equal grid columns: per-card width unchanged vs padx 4 everywhere; +4 px between cards; 4 px less outer inset.
    _PLAN_ROW_THREE_COL_PADX = ((0, 8), (4, 4), (8, 0))
    # Passive GET /check (window focus + opening Settings): keep Worker traffic low. Commerce wizards / Stripe reset this.
    _LICENSE_REMOTE_SYNC_MIN_GAP_SEC = 15 * 60

    def _plan_co_s(self, key: str, default_en: str) -> str:
        """Checkout row strings; YAML may be missing in some locales → English default."""
        v = s(f"settings.plan_management.checkout.{key}")
        return v.strip() if v.strip() else default_en

    def _plan_lk_s(self, key: str, default_en: str = "") -> str:
        v = s(f"settings.plan_management.link_subscription.{key}")
        return v.strip() if v.strip() else default_en

    def _plan_lk_err(self, key: str, default_en: str = "") -> str:
        v = s(f"settings.plan_management.link_subscription.errors.{key}")
        return v.strip() if v.strip() else default_en

    def _plan_tr_s(self, key: str, default_en: str = "") -> str:
        v = s(f"settings.plan_management.trial_request.{key}")
        return v.strip() if v.strip() else default_en

    def _plan_tr_err(self, key: str, default_en: str = "") -> str:
        v = s(f"settings.plan_management.trial_request.errors.{key}")
        return v.strip() if v.strip() else default_en

    def _plan_link_api_user_message(self, data: Any, http: int) -> str:
        """Message d’erreur lisible depuis la réponse JSON (y compris erreurs imbriquées type Stripe)."""
        d = data if isinstance(data, dict) else {}
        for k in ("message", "detail", "title", "description"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        err = d.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        if isinstance(err, dict):
            em = err.get("message") or err.get("type")
            if isinstance(em, str) and em.strip():
                return em.strip()
        errs = d.get("errors")
        if isinstance(errs, list) and errs:
            e0 = errs[0]
            if isinstance(e0, dict) and isinstance(e0.get("message"), str) and e0["message"].strip():
                return e0["message"].strip()
            if isinstance(e0, str) and e0.strip():
                return e0.strip()
        base = self._plan_lk_err("generic", "Something went wrong.")
        return f"{base} (HTTP {http})" if http is not None else base

    def _read_install_id_for_urls(self) -> str:
        try:
            p = getattr(self, "paths", None)
            if p is None:
                return ""
            path = Path(p.configs) / "install.id"
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    def _perkysue_site_base_for_commerce_urls(self) -> str:
        """HTTPS origin for /pro links. Matches ``PERKYSUE_LICENSE_API`` when set (staging Worker)
        so checkout + webhooks + ``GET /check`` share the same KV; default production ``https://perkysue.com``."""
        base = (os.environ.get("PERKYSUE_LICENSE_API") or "").strip().rstrip("/")
        if base:
            return base
        return "https://perkysue.com"

    def _url_perkysue_pro(self, interval: str) -> str:
        origin = self._perkysue_site_base_for_commerce_urls()
        iid = self._read_install_id_for_urls()
        q = [f"interval={quote(interval, safe='')}"]
        if iid:
            q.append(f"install_id={quote(iid)}")
        return f"{origin}/pro?" + "&".join(q)

    def _hide_plan_post_stripe_hint(self):
        fr = getattr(self, "_plan_post_stripe_hint_frame", None)
        if fr is None:
            return
        try:
            fr.pack_forget()
        except (tk.TclError, ValueError):
            pass

    def _show_plan_post_stripe_hint(self):
        """Plan B after opening Stripe: user sees restart option if focus /check is still on cooldown."""
        fr = getattr(self, "_plan_post_stripe_hint_frame", None)
        if fr is None:
            return
        try:
            fr.pack(fill="x", pady=(12, 0))
        except (tk.TclError, ValueError):
            pass

    def _relaunch_desktop_after_commerce(self):
        """Relaunch PerkySue without requiring Save & Restart (same as post-update restart)."""
        self._restart_app()

    def _on_plan_stripe_continue(self, url_fn):
        """Stripe monthly/yearly: reset passive /check cooldown, sync now, open browser, show restart hint."""
        try:
            self._reset_license_sync_cooldown()
            self._request_license_remote_sync(ignore_cooldown=True)
        except Exception:
            pass
        try:
            webbrowser.open(url_fn())
        except Exception:
            pass
        try:
            self._show_plan_post_stripe_hint()
        except Exception:
            pass

    def _plan_show_checkout_view(self, from_manage_upgrade: bool = False):
        """Replace the 3 plan cards with Pro checkout choices (trial / monthly / yearly)."""
        if not getattr(self, "_plan_checkout_grid", None):
            # Defensive fallback: on some environments, Settings can be partially rebuilt
            # and the checkout row is missing even though the button exists.
            try:
                if getattr(self, "_plan_body", None):
                    self._build_plan_checkout_row(self._plan_body)
            except Exception:
                pass
        if not getattr(self, "_plan_checkout_grid", None):
            try:
                if hasattr(self, "_notify"):
                    self._notify("Could not open trial options. Please reopen Settings.")
            except Exception:
                pass
            return
        try:
            self._hide_plan_post_stripe_hint()
        except Exception:
            pass
        try:
            self._reset_license_sync_cooldown()
            self._request_license_remote_sync(ignore_cooldown=True)
        except Exception:
            pass
        self._plan_checkout_upgrading_from_trial = bool(from_manage_upgrade)
        self._plan_checkout_visible = True
        try:
            self._plan_grid.pack_forget()
        except (tk.TclError, ValueError):
            pass
        try:
            self._plan_back_bar.pack(fill="x", pady=(0, 6))
        except (tk.TclError, ValueError):
            pass
        try:
            self._plan_checkout_grid.pack(fill="x", pady=(0, 0))
        except (tk.TclError, ValueError):
            pass
        try:
            self._refresh_plan_checkout_trial_dimmed()
        except Exception:
            pass

    def _plan_hide_checkout_view(self):
        if not getattr(self, "_plan_checkout_grid", None):
            return
        self._hide_plan_post_stripe_hint()
        self._plan_checkout_upgrading_from_trial = False
        self._plan_checkout_visible = False
        try:
            self._plan_checkout_grid.pack_forget()
        except (tk.TclError, ValueError):
            pass
        try:
            self._plan_back_bar.pack_forget()
        except (tk.TclError, ValueError):
            pass
        try:
            self._plan_grid.pack(fill="x", pady=(0, 4))
        except (tk.TclError, ValueError):
            pass

    def _plan_checkout_add_bullets(self, parent, lines: list, dot_color: str):
        """Short feature lines under checkout card price (pack layout)."""
        for line in lines:
            if not (line or "").strip():
                continue
            row = CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=1)
            CTkLabel(row, text="●", font=("Segoe UI", 8), text_color=dot_color).pack(side="left", padx=(0, 5), anchor="n")
            CTkLabel(
                row,
                text=line.strip(),
                font=("Segoe UI", 11),
                text_color="#B0B0B7",
                justify="left",
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

    def _build_plan_checkout_row(self, parent):
        """3 billing cards (trial · monthly · yearly) + back; lives inside _plan_body so it stays under the section title."""
        self._plan_checkout_visible = False
        self._plan_back_bar = CTkFrame(parent, fg_color="transparent")
        self._plan_back_btn = CTkButton(
            self._plan_back_bar,
            text=self._plan_co_s("back", "← All plans"),
            font=("Segoe UI", 12),
            fg_color="transparent",
            hover_color="#2a2a32",
            text_color=ACCENT,
            corner_radius=8,
            height=30,
            command=self._plan_hide_checkout_view,
        )
        self._plan_back_btn.pack(anchor="w")

        self._plan_checkout_grid = CTkFrame(parent, fg_color="transparent")
        self._plan_checkout_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="planco")

        sty = self._PLAN_CARD_STYLE["pro"]
        specs = [
            {
                "key": "preview",
                "name": self._plan_co_s("preview_name", "Pro Trial"),
                "price_main": self._plan_co_s("preview_price_main", "30J"),
                "price_tail": self._plan_co_s("preview_price_tail", "free"),
                "hint": self._plan_co_s("preview_hint", "No card · activate in-app"),
                "lines": [
                    self._plan_co_s("preview_line1", "All Pro LLM modes during trial"),
                    self._plan_co_s("preview_line2", "100% local · your machine"),
                ],
                "cta": self._plan_co_s("preview_cta", "Start trial"),
                # First checkout card: in-app trial activation (email + OTP), not the alpha URL.
                "use_trial_wizard": True,
            },
            {
                "key": "monthly",
                "name": self._plan_co_s("monthly_name", "Pro monthly"),
                "price_main": self._plan_co_s("monthly_price_main", "9.90 €"),
                "price_tail": self._plan_co_s("monthly_price_tail", "/mo"),
                "hint": self._plan_co_s("monthly_hint", "Stripe · cancel anytime"),
                "lines": [
                    self._plan_co_s("monthly_line1", "Full Pro features"),
                    self._plan_co_s("monthly_line2", "Billed every month"),
                ],
                "cta": self._plan_co_s("monthly_cta", "Continue"),
                "url_fn": lambda: self._url_perkysue_pro("month"),
            },
            {
                "key": "yearly",
                "name": self._plan_co_s("yearly_name", "Pro yearly"),
                "price_main": self._plan_co_s("yearly_price_main", "99 €"),
                "price_tail": self._plan_co_s("yearly_price_tail", "/yr"),
                "hint": self._plan_co_s("yearly_hint", ""),
                "save_line": self._plan_co_s("yearly_save", "≈17% vs 12× monthly"),
                "lines": [
                    self._plan_co_s("yearly_line1", "One payment per year"),
                    self._plan_co_s("yearly_line2", "Same features as monthly"),
                ],
                "cta": self._plan_co_s("yearly_cta", "Continue"),
                "url_fn": lambda: self._url_perkysue_pro("year"),
            },
        ]
        for col, spec in enumerate(specs):
            card = CTkFrame(
                self._plan_checkout_grid,
                fg_color=sty["bg"],
                corner_radius=12,
                border_width=1,
                border_color=sty["border"],
            )
            card.grid(row=0, column=col, sticky="nsew", padx=self._PLAN_ROW_THREE_COL_PADX[col], pady=2)
            inner = CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=10, pady=(10, 12))

            CTkLabel(inner, text=spec["name"], font=("Segoe UI", 15, "bold"), text_color=sty["name_color"]).pack(
                anchor="w", pady=(0, 6)
            )

            price_row = CTkFrame(inner, fg_color="transparent")
            price_row.pack(fill="x", pady=(0, 4))
            CTkLabel(price_row, text=spec["price_main"], font=("Segoe UI", 20, "bold"), text_color="#E8E8E8").pack(
                side="left", anchor="s"
            )
            CTkLabel(price_row, text=spec["price_tail"], font=("Segoe UI", 11), text_color=MUTED).pack(
                side="left", padx=(5, 0), pady=(0, 2), anchor="sw"
            )

            hint = (spec.get("hint") or "").strip()
            if hint:
                CTkLabel(
                    inner,
                    text=hint,
                    font=("Segoe UI", 10),
                    text_color="#9080a8",
                    wraplength=200,
                    justify="left",
                    anchor="w",
                ).pack(anchor="w", pady=(0, 6))

            save_line = (spec.get("save_line") or "").strip()
            if save_line:
                CTkLabel(
                    inner,
                    text=save_line,
                    font=("Segoe UI", 11, "bold"),
                    text_color="#c9b080",
                    anchor="w",
                ).pack(anchor="w", pady=(0, 4))

            feat_box = CTkFrame(inner, fg_color="transparent")
            feat_box.pack(fill="both", expand=True, pady=(0, 8))
            self._plan_checkout_add_bullets(feat_box, spec["lines"], sty["dot"])

            if spec.get("use_trial_wizard"):
                cta_cmd = self._open_trial_request_wizard
            else:
                url_fn = spec["url_fn"]
                cta_cmd = lambda fn=url_fn: self._on_plan_stripe_continue(fn)
            cta_btn = CTkButton(
                inner,
                text=spec["cta"],
                font=("Segoe UI", 12, "bold"),
                fg_color=ACCENT,
                hover_color="#9b6fe8",
                text_color="#FFFFFF",
                corner_radius=8,
                height=34,
                command=cta_cmd,
            )
            cta_btn.pack(fill="x", pady=(4, 0))
            if spec.get("use_trial_wizard"):
                self._plan_checkout_trial_card = card
                self._plan_checkout_trial_btn = cta_btn

        self._plan_post_stripe_hint_frame = CTkFrame(parent, fg_color="transparent")
        hint_box = CTkFrame(
            self._plan_post_stripe_hint_frame,
            fg_color="#1e1e26",
            corner_radius=10,
            border_width=1,
            border_color="#3A3A42",
        )
        hint_box.pack(fill="x", padx=0, pady=0)
        hint_inner = CTkFrame(hint_box, fg_color="transparent")
        hint_inner.pack(fill="x", padx=14, pady=12)
        CTkLabel(
            hint_inner,
            text=self._plan_co_s(
                "post_stripe_hint",
                "After paying in the browser, come back to this window — your plan refreshes automatically. "
                "If Pro does not show, restart the app.",
            ),
            font=("Segoe UI", 12),
            text_color=TXT2,
            justify="left",
            anchor="w",
            wraplength=720,
        ).pack(fill="x", pady=(0, 10))
        CTkButton(
            hint_inner,
            text=self._plan_co_s("post_stripe_restart", "Restart PerkySue"),
            font=("Segoe UI", 12, "bold"),
            fg_color=ACCENT,
            hover_color="#9b6fe8",
            text_color="#FFFFFF",
            corner_radius=8,
            height=32,
            command=self._relaunch_desktop_after_commerce,
        ).pack(anchor="w")

    def _refresh_plan_checkout_trial_dimmed(self):
        """Grey out the trial checkout card when user is already on Pro trial (upgrade path: monthly/yearly only)."""
        btn = getattr(self, "_plan_checkout_trial_btn", None)
        card = getattr(self, "_plan_checkout_trial_card", None)
        if btn is None or card is None:
            return
        orch = getattr(self, "orch", None)
        dim = False
        try:
            if orch and hasattr(orch, "is_pro_trial_active"):
                dim = bool(orch.is_pro_trial_active())
        except Exception:
            dim = False
        sty = self._PLAN_CARD_STYLE.get("pro", {})
        try:
            if dim:
                btn.configure(
                    state="normal",
                    fg_color="#2a2a32",
                    hover_color="#2a2a32",
                    text_color="#555555",
                    command=self._plan_trial_already_active_info,
                )
                card.configure(fg_color="#1a1a20", border_color="#2a2a32")
            else:
                btn.configure(
                    state="normal",
                    fg_color=ACCENT,
                    hover_color="#9b6fe8",
                    text_color="#FFFFFF",
                    command=self._open_trial_request_wizard,
                )
                card.configure(fg_color=sty.get("bg", "#1e1e26"), border_color=sty.get("border", "#3A3A42"))
        except (tk.TclError, ValueError):
            pass

    def _plan_trial_already_active_info(self):
        """Explain why trial card is dimmed instead of silently ignoring clicks."""
        try:
            if hasattr(self, "_notify"):
                self._notify("Trial already active on this machine. Choose monthly or yearly to upgrade.")
        except Exception:
            pass

    def _plan_manage_action(self):
        """On Pro trial-only: show checkout to upgrade. On paid Stripe Pro: Customer Portal."""
        orch = getattr(self, "orch", None)
        try:
            if orch and hasattr(orch, "has_valid_stripe_license") and orch.has_valid_stripe_license():
                self._plan_open_billing_portal()
                return
        except Exception:
            pass
        trial_days = None
        try:
            if orch and hasattr(orch, "trial_active_days_remaining"):
                trial_days = orch.trial_active_days_remaining()
        except Exception:
            trial_days = None
        if trial_days is not None:
            self._plan_show_checkout_view(from_manage_upgrade=True)
            return
        self._plan_open_billing_portal()

    def _plan_features_from_yaml(self, key: str):
        items = s_list(f"settings.plan_management.{key}.features")
        out = []
        for it in items:
            if isinstance(it, dict):
                out.append((it.get("text", ""), bool(it.get("locked", False))))
            elif isinstance(it, str):
                out.append((it, False))
        return out

    def _get_plan_defs(self):
        """Merge YAML strings + style for plan cards (free / pro / enterprise)."""
        merged = {}
        for key in ("free", "pro", "enterprise"):
            sty = self._PLAN_CARD_STYLE[key]
            base = f"settings.plan_management.{key}"
            entry = {
                **sty,
                "name": s(f"{base}.name"),
                "price": s(f"{base}.price"),
                "features": self._plan_features_from_yaml(key),
            }
            if key == "pro":
                entry["price_sub"] = s(f"{base}.price_sub")
                entry["btn_sub"] = s(f"{base}.trial_sub")
            else:
                entry["price_sub"] = None
                entry["btn_sub"] = None
            merged[key] = entry
        return merged

    def _is_plan_emulation_allowed(self) -> bool:
        """Plan emulation via config['plan'] only when extension module is active."""
        try:
            orch = getattr(self, "orch", None)
            if orch is not None:
                dev = orch._load_dev_plugin()
                if dev is not None:
                    return bool(dev.check_context(orch.paths.plugins))
        except Exception:
            pass
        return False

    def _plan_should_force_stripe_resync(self) -> bool:
        """True when license.json looks like a linked Stripe sub but tier is Free (tamper / stale signed cache)."""
        orch = getattr(self, "orch", None)
        if orch is None:
            return False
        try:
            if (orch.get_effective_tier() or "free").strip().lower() not in ("free",):
                return False
        except Exception:
            return False
        try:
            lic = orch.paths.configs / "license.json"
            if not lic.exists():
                return False
            raw = json.loads(lic.read_text(encoding="utf-8", errors="ignore") or "{}")
            if not isinstance(raw, dict):
                return False
            sid = raw.get("subscription_id")
            if not isinstance(sid, str) or not sid.strip().startswith("sub_"):
                return False
            cur = self._read_install_id_for_urls().strip()
            fid = raw.get("install_id")
            if not isinstance(fid, str) or fid.strip() != cur:
                return False
            marker = orch.paths.configs / "stripe_license_signed_once.marker"
            if marker.exists():
                return True
            if raw.get("license_payload") is not None or raw.get("license_signature") is not None:
                return True
        except Exception:
            return False
        return False

    def _effective_plan_for_ui(self) -> str:
        """Effective/proof-based plan mapped to UI cards (free|pro|enterprise)."""
        try:
            if getattr(self, "orch", None):
                if hasattr(self.orch, "get_effective_tier"):
                    eff = (self.orch.get_effective_tier() or "free").strip().lower()
                elif hasattr(self.orch, "get_gating_tier"):
                    eff = (self.orch.get_gating_tier() or "free").strip().lower()
                else:
                    eff = "free"
            else:
                eff = "free"
        except Exception:
            eff = "free"
        if eff == "enterprise":
            return "enterprise"
        if eff in ("pro", "pro_alpha"):
            return "pro"
        return "free"

    def _should_show_plan_link_existing_subscription(self) -> bool:
        """Show relink entry only for Free or trial — hide when Stripe Pro or Enterprise is active."""
        try:
            orch = getattr(self, "orch", None)
            if orch is None or not hasattr(orch, "get_gating_tier"):
                return True
            t = (orch.get_gating_tier() or "free").strip().lower()
            if t in ("pro", "enterprise"):
                return False
        except Exception:
            return True
        return True

    def _build_plan_management(self, parent):
        """Build the 3-card Plan Management section at top of Settings.
        All widgets are created once; _refresh_plan_cards updates them in-place
        (no destroy/rebuild) to avoid layout recalculation glitches on sections below.
        """
        raw_plan = (self.cfg.get("plan") or "").strip().lower() if isinstance(getattr(self, "cfg", None), dict) else ""
        if self._is_plan_emulation_allowed():
            self._plan_current = raw_plan if raw_plan in ("free", "pro", "enterprise") else "free"
        else:
            # Production behavior: always reflect proof-based tier, not config emulation.
            self._plan_current = self._effective_plan_for_ui()

        # Single outer block so checkout rows stay directly under "Plan management",
        # not at the bottom of the scrollable page (pack order issue if children of `parent`).
        self._plan_section = CTkFrame(parent, fg_color="transparent")
        self._plan_section.pack(fill="x", pady=(20, 16), padx=(0, 28))

        title_row = CTkFrame(self._plan_section, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 10))
        title_row.grid_columnconfigure(1, weight=1)
        CTkLabel(title_row, text=s("settings.plan_management.section_title"),
                 font=("Segoe UI", 20, "bold"), text_color=TXT
                 ).grid(row=0, column=0, sticky="w")
        self._plan_link_existing_lbl = CTkLabel(
            title_row,
            text=self._plan_lk_s("cta", "I already have a subscription"),
            font=("Segoe UI", 12, "underline"),
            text_color=SKIN_SELECTED_BORDER,
            cursor="hand2",
        )
        self._plan_link_existing_lbl.grid(row=0, column=2, sticky="e", pady=(4, 0))
        self._plan_link_existing_lbl.bind("<Button-1>", lambda _e: self._open_link_subscription_wizard())

        self._plan_body = CTkFrame(self._plan_section, fg_color="transparent")
        self._plan_body.pack(fill="x", pady=(0, 0))

        # Grid container (fixed height to prevent any collapse)
        self._plan_grid = CTkFrame(self._plan_body, fg_color="transparent")
        self._plan_grid.pack(fill="x", pady=(0, 4))
        self._plan_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="plan")

        CARD_MIN_H = 200
        keys = ["free", "pro", "enterprise"]
        self._plan_w = {}  # per-key dict of widget references
        plan_defs = self._get_plan_defs()

        for col, key in enumerate(keys):
            d = plan_defs[key]
            refs = {}

            # ── Card frame
            card = CTkFrame(self._plan_grid, fg_color=d["bg"], corner_radius=12,
                            border_width=1, border_color=d["border"])
            card.grid(row=0, column=col, sticky="nsew", padx=self._PLAN_ROW_THREE_COL_PADX[col], pady=2)
            refs["card"] = card

            def _on_click(_e, k=key):
                # Without dev plugin, disable plan emulation from UI.
                if not self._is_plan_emulation_allowed():
                    self._plan_current = self._effective_plan_for_ui()
                    self._refresh_plan_cards()
                    return
                prev_plan = self._plan_current
                self._plan_current = k
                # Persist for testing (no _trigger_save / _notify to avoid relayout)
                try:
                    if k == "free" and prev_plan != "free":
                        self._apply_free_plan_data_reset()
                    self._save_config({"plan": k})
                    if getattr(self, "orch", None) and isinstance(getattr(self.orch, "config", None), dict):
                        self.orch.config["plan"] = k
                    # Keep Save & Restart visible on plan switch, without forcing scroll.
                    if hasattr(self, "_trigger_save"):
                        self._trigger_save(scroll_to_bottom=False)
                except Exception:
                    pass
                self._refresh_plan_cards()
                try:
                    if hasattr(self, "_refresh_prompt_modes_plan_restrictions"):
                        self.root.after(50, self._refresh_prompt_modes_plan_restrictions)
                except Exception:
                    pass
                try:
                    if hasattr(self, "_refresh_shortcuts_plan_restrictions"):
                        self.root.after(50, self._refresh_shortcuts_plan_restrictions)
                except Exception:
                    pass
            refs["_on_click"] = _on_click
            card.bind("<Button-1>", _on_click)

            # ── Inner grid
            inner = CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=(10, 12))
            inner.bind("<Button-1>", _on_click)
            inner.grid_rowconfigure(2, weight=1)
            inner.grid_columnconfigure(0, weight=1)

            # Height spacer (uniform card height)
            spacer = CTkFrame(inner, fg_color="transparent", width=1, height=CARD_MIN_H)
            spacer.grid(row=0, column=1, rowspan=4)
            spacer.grid_propagate(False)

            # ── Row 0: name + badge
            top = CTkFrame(inner, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", pady=(0, 2))
            top.bind("<Button-1>", _on_click)
            top.grid_columnconfigure(1, weight=1)

            name_lbl = CTkLabel(top, text=d["name"], font=("Segoe UI", 15, "bold"),
                                text_color=d["name_color"])
            name_lbl.grid(row=0, column=0, sticky="w")
            name_lbl.bind("<Button-1>", _on_click)
            refs["name_lbl"] = name_lbl

            badge_lbl = CTkLabel(top, text=f" {s('settings.plan_management.badge_current')} ",
                                 font=("Segoe UI", 11, "bold"),
                                 text_color="#FFFFFF", fg_color=ACCENT,
                                 corner_radius=6, height=22)
            badge_lbl.bind("<Button-1>", _on_click)
            refs["badge_lbl"] = badge_lbl
            # Don't grid yet — _refresh will place it

            # ── Row 1: price area (fixed height)
            row1 = CTkFrame(inner, fg_color="transparent", height=44)
            row1.grid(row=1, column=0, sticky="ew", pady=(0, 4))
            row1.grid_propagate(False)
            row1.grid_columnconfigure(0, weight=0)
            row1.bind("<Button-1>", _on_click)

            # Pre-create price labels
            price_lbl = CTkLabel(row1, text=d["price"], font=("Segoe UI", 20, "bold"),
                                 text_color="#E8E8E8")
            price_lbl.bind("<Button-1>", _on_click)
            refs["price_lbl"] = price_lbl

            price_sub_lbl = None
            if d["price_sub"]:
                price_sub_lbl = CTkLabel(row1, text=d["price_sub"], font=("Segoe UI", 11),
                                         text_color=MUTED)
                price_sub_lbl.bind("<Button-1>", _on_click)
            refs["price_sub_lbl"] = price_sub_lbl

            # Pre-create status label (validity / "Active plan"); date filled in _refresh_plan_cards
            status_text = (
                s("settings.plan_management.status_valid_until_unknown")
                if key == "pro"
                else s("settings.plan_management.status_active_plan")
            )
            status_lbl = CTkLabel(row1, text=status_text, font=("Segoe UI", 12),
                                  text_color="#a89050")
            status_lbl.bind("<Button-1>", _on_click)
            refs["status_lbl"] = status_lbl

            # ── Row 2: features
            feat_f = CTkFrame(inner, fg_color="transparent")
            feat_f.grid(row=2, column=0, sticky="new", pady=(0, 0))
            feat_f.bind("<Button-1>", _on_click)

            feat_widgets = []
            for feat_text, _is_locked in d["features"]:
                row = CTkFrame(feat_f, fg_color="transparent", height=18)
                row.pack(fill="x", pady=0)
                row.pack_propagate(False)
                row.bind("<Button-1>", _on_click)
                dot_l = CTkLabel(row, text="●", font=("Segoe UI", 8), text_color=d["dot"])
                dot_l.pack(side="left", padx=(0, 5), pady=0)
                dot_l.bind("<Button-1>", _on_click)
                txt_l = CTkLabel(row, text=feat_text, font=("Segoe UI", 12), text_color="#B0B0B7")
                txt_l.pack(side="left", pady=0)
                txt_l.bind("<Button-1>", _on_click)
                feat_widgets.append((dot_l, txt_l, _is_locked))
            refs["feat_widgets"] = feat_widgets

            # ── Row 3: button area
            btn_f = CTkFrame(inner, fg_color="transparent")
            btn_f.grid(row=3, column=0, sticky="sew", pady=(6, 0))

            # Pre-create ALL button variants for this card (pack_forget/pack to switch)
            # "30 days · no card" sub-label (Pro only)
            trial_sub_lbl = None
            if key == "pro" and d["btn_sub"]:
                trial_sub_lbl = CTkLabel(btn_f, text=d["btn_sub"], font=("Segoe UI", 11),
                                         text_color="#9080b0")
            refs["trial_sub_lbl"] = trial_sub_lbl

            if key == "free":
                btn_active = CTkButton(btn_f, text=s("settings.plan_management.buttons.active"), font=("Segoe UI", 12, "bold"),
                                       fg_color="#2a2a32", hover_color="#2a2a32",
                                       text_color="#666666", corner_radius=8, height=34,
                                       border_width=1, border_color="#3a3a44",
                                       state="disabled")
                btn_dimmed = CTkButton(btn_f, text=s("settings.plan_management.buttons.free_tier"), font=("Segoe UI", 12),
                                       fg_color="#2a2a32", hover_color="#2a2a32",
                                       text_color="#444444", corner_radius=8, height=34,
                                       border_width=1, border_color="#333333",
                                       state="disabled")
                refs["btn_active"] = btn_active
                refs["btn_dimmed"] = btn_dimmed

            elif key == "pro":
                btn_manage = CTkButton(btn_f, text=s("settings.plan_management.buttons.manage"), font=("Segoe UI", 12, "bold"),
                                       fg_color=ACCENT, hover_color="#9b6fe8",
                                       text_color="#FFFFFF", corner_radius=8, height=34,
                                       command=self._plan_manage_action)
                btn_trial = CTkButton(btn_f, text=s("settings.plan_management.buttons.start_free_trial"), font=("Segoe UI", 12, "bold"),
                                      fg_color=ACCENT, hover_color="#9b6fe8",
                                      text_color="#FFFFFF", corner_radius=8, height=34)
                btn_get = CTkButton(btn_f, text=s("settings.plan_management.buttons.get_pro"), font=("Segoe UI", 12, "bold"),
                                    fg_color=ACCENT, hover_color="#9b6fe8",
                                    text_color="#FFFFFF", corner_radius=8, height=34)
                # Start free trial → second screen (3 checkout cards: trial / monthly / yearly).
                # The trial OTP wizard is wired on the first checkout card only (see _build_plan_checkout_row).
                btn_trial.configure(command=self._plan_show_checkout_view)
                btn_get.configure(command=self._plan_show_checkout_view)
                refs["btn_manage"] = btn_manage
                refs["btn_trial"] = btn_trial
                refs["btn_get"] = btn_get

            elif key == "enterprise":
                btn_active = CTkButton(btn_f, text=s("settings.plan_management.buttons.active"), font=("Segoe UI", 12, "bold"),
                                       fg_color="#2a2a32", hover_color="#2a2a32",
                                       text_color="#666666", corner_radius=8, height=34,
                                       border_width=1, border_color="#3a3a44",
                                       state="disabled")
                btn_sales = CTkButton(btn_f, text=s("settings.plan_management.buttons.contact_sales"), font=("Segoe UI", 12, "bold"),
                                      fg_color="transparent", hover_color="#2e2818",
                                      text_color="#c9a84c", corner_radius=8, height=34,
                                      border_width=1, border_color="#5a4d28",
                                      command=lambda: webbrowser.open("https://perkysue.com/enterprise"))
                refs["btn_active"] = btn_active
                refs["btn_sales"] = btn_sales

            self._plan_w[key] = refs

        self._build_plan_checkout_row(self._plan_body)

        # Initial paint
        self._refresh_plan_cards()

    def _refresh_plan_cards(self):
        """Update plan cards in-place — no destroy/rebuild, no layout recalc."""
        if not self._is_plan_emulation_allowed():
            self._plan_current = self._effective_plan_for_ui()
        cur = self._plan_current

        if getattr(self, "_plan_checkout_visible", False):
            if not self._is_plan_emulation_allowed() and self._effective_plan_for_ui() != "free":
                # Keep checkout open when Pro trial user opened it via Manage (upgrade to paid).
                if not getattr(self, "_plan_checkout_upgrading_from_trial", False):
                    self._plan_hide_checkout_view()

        plan_defs = self._get_plan_defs()
        for key, refs in self._plan_w.items():
            d = plan_defs[key]
            is_cur = (key == cur)
            dim = (key == "free" and cur in ("pro", "enterprise"))

            # ── Card border
            card = refs["card"]
            try:
                card.configure(
                    border_color=ACCENT if is_cur else "#3A3A42",
                    border_width=2 if is_cur else 1,
                )
            except (tk.TclError, ValueError):
                pass

            # ── Name color
            refs["name_lbl"].configure(text_color="#444444" if dim else d["name_color"])

            # ── Badge (Current) — show/hide via grid/grid_remove
            badge = refs["badge_lbl"]
            if is_cur:
                badge.grid(row=0, column=1, sticky="e")
            else:
                badge.grid_remove()

            # ── Row 1: price vs status — show/hide
            price_lbl = refs["price_lbl"]
            price_sub = refs["price_sub_lbl"]
            status_lbl = refs["status_lbl"]

            if is_cur and key in ("pro", "enterprise"):
                # Show status, hide price
                price_lbl.grid_remove()
                if price_sub:
                    price_sub.grid_remove()
                status_lbl.grid(row=0, column=0, sticky="w", pady=(10, 0))
                if key == "pro":
                    # Match get_header_banner_spec: trial line only when trial days exist and no paid Stripe license.
                    stripe_ok = False
                    try:
                        if getattr(self, "orch", None) and hasattr(self.orch, "has_valid_stripe_license"):
                            stripe_ok = bool(self.orch.has_valid_stripe_license())
                    except Exception:
                        stripe_ok = False
                    trial_days = None
                    try:
                        if getattr(self, "orch", None) and hasattr(self.orch, "trial_active_days_remaining"):
                            trial_days = self.orch.trial_active_days_remaining()
                    except Exception:
                        trial_days = None
                    try:
                        if trial_days is not None and not stripe_ok:
                            status_lbl.configure(
                                text=s("settings.plan_management.status_pro_trial_days").format(days=trial_days),
                                text_color="#a89050",
                            )
                        else:
                            loc = self._strings_locale_from_cfg()
                            exp = (
                                self.orch.get_license_expires_display(loc)
                                if getattr(self, "orch", None)
                                else None
                            )
                            cancels_end = False
                            try:
                                if getattr(self, "orch", None):
                                    cancels_end = bool(self.orch.get_license_cancel_at_period_end())
                            except Exception:
                                cancels_end = False
                            if exp:
                                sk = (
                                    "settings.plan_management.status_access_until_cancelled"
                                    if cancels_end
                                    else "settings.plan_management.status_valid_until"
                                )
                                status_lbl.configure(
                                    text=s(sk).format(date=exp),
                                    text_color="#a89050",
                                )
                            else:
                                status_lbl.configure(
                                    text=s("settings.plan_management.status_valid_until_unknown"),
                                    text_color="#a89050",
                                )
                    except Exception:
                        status_lbl.configure(
                            text=s("settings.plan_management.status_valid_until_unknown"),
                            text_color="#a89050",
                        )
                else:
                    status_lbl.configure(text=s("settings.plan_management.status_active_plan"), text_color="#a89050")
            else:
                # Show price, hide status
                status_lbl.grid_remove()
                price_c = "#444444" if dim else "#E8E8E8"
                price_lbl.configure(text_color=price_c)
                price_lbl.grid(row=0, column=0, sticky="nw", pady=(6, 0))
                if price_sub:
                    sub_c = "#333333" if dim else MUTED
                    price_sub.configure(text_color=sub_c)
                    price_sub.grid(row=0, column=1, sticky="nw", padx=(4, 0), pady=(10, 0))

            # ── Features: update colors
            for dot_l, txt_l, is_locked in refs["feat_widgets"]:
                if dim:
                    dot_l.configure(text_color="#333333")
                    txt_l.configure(text_color="#333333")
                elif is_locked:
                    dot_l.configure(text_color="#444444")
                    txt_l.configure(text_color="#444444")
                else:
                    dot_l.configure(text_color=d["dot"])
                    txt_l.configure(text_color="#B0B0B7")

            # ── Buttons: pack_forget all, then pack the right one
            # Collect all button widgets for this card
            all_btns = []
            for bk in ("btn_active", "btn_dimmed", "btn_manage", "btn_trial",
                        "btn_get", "btn_sales", "trial_sub_lbl"):
                w = refs.get(bk)
                if w is not None:
                    try:
                        w.pack_forget()
                    except (tk.TclError, ValueError):
                        pass

            if key == "free":
                if is_cur:
                    refs["btn_active"].pack(fill="x")
                elif dim:
                    refs["btn_dimmed"].pack(fill="x")

            elif key == "pro":
                if is_cur:
                    refs["btn_manage"].pack(fill="x")
                elif cur == "free":
                    sub = refs.get("trial_sub_lbl")
                    if sub:
                        sub.pack(pady=(0, 2))
                    refs["btn_trial"].pack(fill="x")
                else:
                    refs["btn_get"].pack(fill="x")

            elif key == "enterprise":
                if is_cur:
                    refs["btn_active"].pack(fill="x")
                else:
                    refs["btn_sales"].pack(fill="x")

        try:
            self._refresh_header_banner_if_idle()
        except Exception:
            pass

        link = getattr(self, "_plan_link_existing_lbl", None)
        if link is not None:
            try:
                if self._should_show_plan_link_existing_subscription():
                    link.grid(row=0, column=2, sticky="e", pady=(4, 0))
                else:
                    link.grid_remove()
            except Exception:
                pass

        try:
            self._refresh_user_billing_email_display()
        except Exception:
            pass

        try:
            if getattr(self, "_plan_checkout_visible", False):
                self._refresh_plan_checkout_trial_dimmed()
        except Exception:
            pass

        # After local JSON tamper, tier can read Free until GET /check overwrites; long passive cooldown could block recovery.
        try:
            orch = getattr(self, "orch", None)
            if (
                orch
                and not self._is_plan_emulation_allowed()
                and cur == "free"
                and self._plan_should_force_stripe_resync()
            ):
                now_m = time.monotonic()
                last_m = getattr(self, "_plan_forced_stripe_resync_mono", None)
                if last_m is None or now_m - last_m >= 15.0:
                    self._plan_forced_stripe_resync_mono = now_m
                    self._request_license_remote_sync(ignore_cooldown=True)
        except Exception:
            pass

        # One GET /check if license.json exists but no expiry field yet (Worker may use expiry_date, etc.)
        try:
            orch = getattr(self, "orch", None)
            if orch and not getattr(self, "_plan_license_expiry_sync_done", False) and cur == "pro":
                lic = orch.paths.configs / "license.json"
                if lic.exists() and orch.get_license_expires_display() is None:
                    self._plan_license_expiry_sync_done = True

                    def _bg_sync():
                        try:
                            orch.refresh_license_from_remote()
                        except Exception:
                            pass
                        try:
                            self.root.after(0, self._refresh_plan_cards)
                        except Exception:
                            pass

                    threading.Thread(target=_bg_sync, daemon=True).start()
        except Exception:
            pass

    def _refresh_user_billing_email_display(self):
        """Updates Utilisateur → billing e-mail row when license.json has billing_email."""
        lbl = getattr(self, "_user_billing_email_val", None)
        if lbl is None:
            return
        orch = getattr(self, "orch", None)
        em = ""
        try:
            if orch and hasattr(orch, "get_license_billing_email"):
                em = orch.get_license_billing_email() or ""
        except Exception:
            em = ""
        try:
            lbl.configure(text=em if em else s("user.billing.empty"))
        except Exception:
            pass

    def _plan_open_billing_portal(self):
        """Open Stripe Customer Portal (Worker POST /billing-portal → session URL)."""
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "request_billing_portal_url"):
            return

        def _run():
            try:
                ok, url_or_err = orch.request_billing_portal_url()
            except Exception as e:
                ok, url_or_err = False, str(e)

            def _ui():
                if ok:
                    try:
                        self._reset_license_sync_cooldown()
                        self._request_license_remote_sync(ignore_cooldown=True)
                    except Exception:
                        pass
                    try:
                        webbrowser.open(url_or_err)
                    except Exception:
                        pass
                    try:
                        self._refresh_plan_cards()
                        self._refresh_header_banner_if_idle()
                    except Exception:
                        pass
                    return
                try:
                    from tkinter import messagebox
                    messagebox.showinfo(
                        s("settings.plan_management.portal_title"),
                        s("settings.plan_management.portal_manage_unavailable"),
                        parent=self.root,
                    )
                except Exception:
                    pass

            try:
                self.root.after(0, _ui)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    # ── Wizard UI helpers (Plan Management style) ─────────────
    def _wizard_center_like_plan(self, dlg):
        """Center dialog like Plan Management wizards (x centered, y = root_y + 52)."""
        try:
            dlg.update_idletasks()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, _rh = self.root.winfo_width(), self.root.winfo_height()
            dw, _dh = dlg.winfo_width(), dlg.winfo_height()
            x = max(20, rx + (rw - dw) // 2)
            y = max(20, ry + 52)
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _wizard_prepare_toplevel(self, dlg, title: str, geometry: str):
        try:
            dlg.title(title)
        except Exception:
            pass
        try:
            dlg.geometry(geometry)
        except Exception:
            pass
        try:
            dlg.resizable(False, False)
            dlg.transient(self.root)
        except Exception:
            pass
        try:
            dlg.configure(fg_color=BG)
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

    def _wizard_make_shell(self, dlg, border_color=None):
        """Return (shell, content, inner_pad, content_pad_top, gold, gold_hover)."""
        gold = SKIN_SELECTED_BORDER
        gold_hover = "#d9a60f"
        border = border_color or gold
        inner_pad = 16
        content_pad_top = inner_pad + 5
        shell = CTkFrame(dlg, fg_color=CARD, corner_radius=18, border_width=2, border_color=border)
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        content = CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=inner_pad, pady=(content_pad_top, inner_pad))
        return shell, content, inner_pad, content_pad_top, gold, gold_hover

    def _open_trial_request_wizard(self):
        """Free Pro trial: email → Brevo OTP (same pattern as link-subscription) → Yes/No newsletter → activate."""
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "trial_verify"):
            try:
                if hasattr(self, "_notify"):
                    self._notify("Trial wizard unavailable. Please reopen Settings.")
            except Exception:
                pass
            return

        try:
            self._reset_license_sync_cooldown()
            self._request_license_remote_sync(ignore_cooldown=True)
        except Exception:
            pass

        if getattr(self, "_trial_req_wizard_dlg", None):
            try:
                if self._trial_req_wizard_dlg.winfo_exists():
                    try:
                        self._trial_req_wizard_dlg.deiconify()
                    except Exception:
                        pass
                    self._wizard_center_like_plan(self._trial_req_wizard_dlg)
                    self._trial_req_wizard_dlg.lift()
                    try:
                        self._trial_req_wizard_dlg.focus_force()
                    except Exception:
                        pass
                    return
            except Exception:
                pass

        try:
            dlg = CTkToplevel(self.root)
        except Exception:
            try:
                if hasattr(self, "_notify"):
                    self._notify("Could not open trial wizard. Please reopen Settings.")
            except Exception:
                pass
            return
        self._trial_req_wizard_dlg = dlg
        self._wizard_prepare_toplevel(dlg, self._plan_tr_s("wizard_title", "Start free trial"), "460x430")
        self._wizard_center_like_plan(dlg)

        tick = {"job": None}
        _shell, content, inner_pad, _content_pad_top, link_gold, link_gold_hover = self._wizard_make_shell(dlg, border_color=SKIN_SELECTED_BORDER)

        def _close_wizard():
            if tick["job"]:
                try:
                    dlg.after_cancel(tick["job"])
                except Exception:
                    pass
                tick["job"] = None
            try:
                dlg.destroy()
            except Exception:
                pass
            self._trial_req_wizard_dlg = None

        # content is provided by _wizard_make_shell (Plan Management style)

        headline_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
            anchor="center",
            justify="center",
        )
        intro_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="left",
            anchor="w",
            wraplength=404,
        )
        hint_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="center",
            anchor="center",
            wraplength=404,
        )
        status_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 12),
            text_color="#F87171",
            wraplength=404,
            justify="center",
            anchor="center",
        )
        # No textvariable: CustomTkinter only shows placeholder when textvariable is None
        # (see CTkEntry._activate_placeholder).
        _email_ph = self._plan_tr_s("email_placeholder", "your@email.com")
        email_entry = ctk.CTkEntry(
            content,
            placeholder_text=_email_ph,
            placeholder_text_color=MUTED,
            text_color=TXT,
            fg_color=CARD,
            height=38,
            font=("Segoe UI", 14),
            corner_radius=10,
            border_width=1,
            border_color=link_gold,
        )
        _ctk_entry_keep_placeholder_until_keystroke(email_entry)

        otp_row = CTkFrame(content, fg_color="transparent")
        otp_entries: list = []
        for _i in range(6):
            ent = ctk.CTkEntry(
                otp_row,
                width=44,
                height=48,
                font=("Segoe UI", 20, "bold"),
                justify="center",
                corner_radius=10,
                border_width=1,
                border_color=link_gold,
            )
            otp_entries.append(ent)

        for col, ent in enumerate(otp_entries):
            ent.grid(row=0, column=col, padx=4, sticky="nsew")
            otp_row.grid_columnconfigure(col, weight=1, uniform="otp")

        def _otp_clear():
            for ent in otp_entries:
                try:
                    ent.delete(0, "end")
                except Exception:
                    pass

        def _otp_code() -> str:
            parts = []
            for ent in otp_entries:
                raw = (ent.get() or "").strip()
                digits = "".join(c for c in raw if c.isdigit())
                parts.append(digits[-1:] if digits else "")
            return "".join(parts)

        def _wire_otp_entry(idx: int, ent):
            def _kr(_ev=None):
                raw = ent.get() or ""
                digits = "".join(c for c in raw if c.isdigit())
                if len(digits) > 1 or raw != digits:
                    ent.delete(0, "end")
                    if digits:
                        ent.insert(0, digits[-1])
                if (ent.get() or "").strip() and idx < 5:
                    try:
                        otp_entries[idx + 1].focus_set()
                    except Exception:
                        pass

            def _kp(ev):
                if ev.keysym == "Backspace" and not (ent.get() or "") and idx > 0:
                    try:
                        otp_entries[idx - 1].focus_set()
                        otp_entries[idx - 1].delete(0, "end")
                    except Exception:
                        pass

            ent.bind("<KeyRelease>", _kr)
            ent.bind("<KeyPress>", _kp)

        for i, ent in enumerate(otp_entries):
            _wire_otp_entry(i, ent)

        def _otp_paste_first(_ev=None):
            try:
                txt = dlg.clipboard_get()
            except Exception:
                return "break"
            digits = "".join(c for c in (txt or "") if c.isdigit())[:6]
            _otp_clear()
            for j, ch in enumerate(digits):
                try:
                    otp_entries[j].insert(0, ch)
                except Exception:
                    pass
            try:
                otp_entries[min(len(digits), 5)].focus_set()
            except Exception:
                pass
            return "break"

        if otp_entries:
            otp_entries[0].bind("<<Paste>>", _otp_paste_first)

        send_btn = CTkButton(
            content,
            text=self._plan_tr_s("send_code", "Send code"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
        )

        yn_title_lbl = CTkLabel(
            content,
            text=self._plan_tr_s("newsletter_title", "Newsletter preference"),
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="center",
            anchor="center",
            wraplength=404,
        )
        yn_hint_lbl = CTkLabel(
            content,
            text=self._plan_tr_s("newsletter_question", "Do you want to join the newsletter?"),
            font=("Segoe UI", 12),
            text_color=TXT2,
            justify="center",
            anchor="center",
            wraplength=404,
        )
        yn_row = CTkFrame(content, fg_color="transparent")
        yes_btn = CTkButton(
            yn_row,
            text=self._plan_tr_s("yes", "Yes"),
            font=("Segoe UI", 13, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            width=140,
            height=40,
            corner_radius=10,
        )
        no_btn = CTkButton(
            yn_row,
            text=self._plan_tr_s("no", "No"),
            font=("Segoe UI", 13, "bold"),
            fg_color="#2a2a32",
            hover_color="#343444",
            text_color=TXT,
            border_width=1,
            border_color="#4a4a58",
            width=140,
            height=40,
            corner_radius=10,
        )
        yes_btn.pack(side="left", padx=(0, 8), expand=True, fill="x")
        no_btn.pack(side="left", padx=(8, 0), expand=True, fill="x")

        resend_btn = CTkButton(
            content,
            text=self._plan_tr_s("resend", "Resend code"),
            font=("Segoe UI", 12, "bold"),
            fg_color="transparent",
            hover_color=SEL_BG,
            text_color=link_gold,
            height=36,
        )

        def _after_trial_success():
            try:
                orch.refresh_license_from_remote()
            except Exception:
                pass
            try:
                self._refresh_plan_cards()
            except Exception:
                pass
            try:
                self._refresh_user_billing_email_display()
            except Exception:
                pass
            try:
                self._refresh_header_banner_if_idle()
            except Exception:
                pass

        done_btn = CTkButton(
            content,
            text=self._plan_tr_s("success_cta", "Start using PerkySue"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
            command=lambda: (
                _close_wizard(),
                _after_trial_success(),
            ),
        )

        state = {"step": "email"}

        def _show_resend_cooldown(sec: int):
            if tick["job"]:
                try:
                    dlg.after_cancel(tick["job"])
                except Exception:
                    pass
                tick["job"] = None
            resend_btn.configure(state="disabled")
            box = {"left": max(0, int(sec))}

            def _tick_one():
                if not dlg.winfo_exists():
                    tick["job"] = None
                    return
                if box["left"] <= 0:
                    resend_btn.configure(
                        state="normal",
                        text=self._plan_tr_s("resend", "Resend code"),
                    )
                    tick["job"] = None
                    return
                resend_btn.configure(
                    text=self._plan_tr_s("resend_wait", "Resend ({s}s)").replace("{s}", str(box["left"]))
                )
                box["left"] -= 1
                tick["job"] = dlg.after(1000, _tick_one)

            _tick_one()

        def _set_busy(on: bool, msg: str = ""):
            st = "disabled" if on else "normal"
            send_btn.configure(state=st)
            resend_btn.configure(state=st)
            try:
                email_entry.configure(state=st)
            except Exception:
                pass
            for ent in otp_entries:
                try:
                    ent.configure(state=st)
                except Exception:
                    pass
            for b in (yes_btn, no_btn):
                try:
                    b.configure(state=st)
                except Exception:
                    pass
            if msg:
                status_lbl.configure(text=msg, text_color=TXT2)

        def _layout():
            for w in (
                headline_lbl,
                intro_lbl,
                hint_lbl,
                email_entry,
                otp_row,
                yn_title_lbl,
                yn_hint_lbl,
                yn_row,
                send_btn,
                resend_btn,
                done_btn,
                status_lbl,
            ):
                try:
                    w.pack_forget()
                except Exception:
                    pass
            status_lbl.configure(text="")
            if state["step"] == "email":
                headline_lbl.configure(text=self._plan_tr_s("wizard_title", "Start free trial"))
                intro_lbl.configure(
                    text=self._plan_tr_s(
                        "email_intro",
                        "Enter your email to get started — we'll send you a 6-digit code to confirm it's you.",
                    )
                )
                headline_lbl.pack(fill="x", pady=(0, 12))
                intro_lbl.pack(fill="x", pady=(0, 18))
                email_entry.pack(fill="x", pady=(0, 8))
                status_lbl.pack(fill="x", pady=(0, 6))
                send_btn.pack(fill="x")
                try:
                    dlg.after(70, lambda: email_entry.focus_set())
                except Exception:
                    pass
            elif state["step"] == "otp":
                headline_lbl.configure(text=self._plan_tr_s("otp_headline", "Verify your email"))
                headline_lbl.pack(fill="x", pady=(0, 10))
                hint_lbl.configure(
                    font=("Segoe UI", 13, "bold"),
                    text_color=TXT,
                    text=self._plan_tr_s(
                        "otp_hint",
                        "Enter the 6-digit code we sent you, then choose your newsletter preference.",
                    ),
                )
                hint_lbl.pack(fill="x", pady=(0, 14))
                otp_row.pack(fill="x", pady=(0, 12))
                yn_title_lbl.pack(fill="x", pady=(0, 4))
                yn_hint_lbl.pack(fill="x", pady=(0, 10))
                yn_row.pack(fill="x", pady=(0, 8))
                status_lbl.pack(fill="x", pady=(0, 6))
                resend_btn.pack(fill="x", pady=(0, 0))
                _otp_clear()
                _show_resend_cooldown(30)
                try:
                    dlg.after(80, lambda: otp_entries[0].focus_set())
                except Exception:
                    pass
            else:
                headline_lbl.configure(text=self._plan_tr_s("success_title", "You're all set! 🎉"))
                intro_lbl.configure(
                    text=self._plan_tr_s(
                        "success_body",
                        "Your 30-day free trial starts now. Enjoy every Pro feature — no limits, no credit card.",
                    ),
                    font=("Segoe UI", 13),
                    text_color=TXT2,
                )
                try:
                    done_btn.configure(text=self._plan_tr_s("success_cta", "Start using PerkySue"))
                except Exception:
                    pass
                headline_lbl.pack(fill="x", pady=(0, 14))
                intro_lbl.pack(fill="x", pady=(0, 24))
                done_btn.pack(fill="x")

        def _error_text(data: Any, http: int) -> str:
            d = data if isinstance(data, dict) else {}
            code = (d.get("error_code") or d.get("code") or "").strip().lower()
            if code == "trial_already_used":
                return self._plan_tr_err("trial_already_used", "This email has already used its free trial.")
            if code == "trial_ineligible_paid":
                return self._plan_tr_err(
                    "trial_ineligible_paid",
                    "This email was previously linked to a Pro subscription. Free trials are for new users only — but you can resubscribe anytime.",
                )
            if code == "invalid_email":
                return self._plan_tr_err("invalid_email", "Enter a valid email.")
            if code == "rate_limited":
                return self._plan_tr_err("rate_limited", "Too many attempts. Please wait a bit and try again.")
            if http == 0:
                return self._plan_tr_err("network", "Could not reach perkysue.com.")
            for k in ("message", "detail", "error"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return self._plan_tr_err("generic", "Could not activate trial right now.")

        def _do_send(is_resend: bool):
            em = (email_entry.get() or "").strip()
            if not em or "@" not in em:
                status_lbl.configure(text=self._plan_tr_err("invalid_email", "Enter a valid email."), text_color="#F87171")
                return
            status_lbl.configure(text="")

            def _run():
                if is_resend:
                    data, http = orch.trial_resend(em)
                else:
                    data, http = orch.trial_start(em)

                def _ui():
                    if not dlg.winfo_exists():
                        return
                    _set_busy(False)
                    if http == 0:
                        status_lbl.configure(text=self._plan_tr_err("network", "Could not reach perkysue.com."), text_color="#F87171")
                        return
                    if is_resend and http == 429:
                        sec = int((data or {}).get("retry_after_sec") or 30)
                        status_lbl.configure(text=self._plan_tr_err("cooldown", "Wait before resending."), text_color="#F87171")
                        _show_resend_cooldown(max(1, sec))
                        return
                    if not is_resend and data.get("ok") is False:
                        status_lbl.configure(text=_error_text(data, http), text_color="#F87171")
                        return
                    if data.get("ok"):
                        if not is_resend:
                            state["step"] = "otp"
                            _layout()
                        else:
                            status_lbl.configure(text=self._plan_tr_s("resent_ok", "New code sent."), text_color="#6ee7b7")
                            _show_resend_cooldown(30)
                        return
                    status_lbl.configure(text=_error_text(data, http), text_color="#F87171")

                try:
                    self.root.after(0, _ui)
                except Exception:
                    pass

            _set_busy(True, self._plan_tr_s("busy_sending", "Sending…"))
            threading.Thread(target=_run, daemon=True).start()

        def _run_trial(newsletter_opt_in: bool):
            em = (email_entry.get() or "").strip()
            code = _otp_code()
            if len(code) < 6:
                status_lbl.configure(
                    text=self._plan_tr_err("invalid_code", "Enter the 6-digit code from your email."),
                    text_color="#F87171",
                )
                return
            _set_busy(True, self._plan_tr_s("busy_verify", "Activating your trial…"))

            def _work():
                data, http = orch.trial_verify(em, code, newsletter_opt_in)

                def _ui():
                    if not dlg.winfo_exists():
                        return
                    _set_busy(False)
                    if http == 0:
                        status_lbl.configure(text=self._plan_tr_err("network", "Could not reach perkysue.com."), text_color="#F87171")
                        return
                    ok = bool((data or {}).get("activated")) or (
                        bool((data or {}).get("ok")) and bool((data or {}).get("expires_at"))
                    )
                    if ok:
                        state["step"] = "success"
                        _layout()
                        try:
                            self._refresh_plan_cards()
                            self._refresh_header_banner_if_idle()
                            self._refresh_user_billing_email_display()
                        except Exception:
                            pass
                        return
                    if (data or {}).get("error_code") == "invalid_code":
                        left = (data or {}).get("attempts_left")
                        extra = f" ({left})" if left is not None else ""
                        status_lbl.configure(
                            text=self._plan_tr_err("wrong_code", "Incorrect code.") + extra,
                            text_color="#F87171",
                        )
                        return
                    if http == 429 or ((data or {}).get("error") or "").lower().find("attempt") >= 0:
                        status_lbl.configure(text=self._plan_tr_err("attempts", "Too many attempts."), text_color="#F87171")
                        return
                    status_lbl.configure(text=_error_text(data, http), text_color="#F87171")

                try:
                    self.root.after(0, _ui)
                except Exception:
                    pass

            threading.Thread(target=_work, daemon=True).start()

        send_btn.configure(command=lambda: _do_send(False))
        resend_btn.configure(command=lambda: _do_send(True))
        yes_btn.configure(command=lambda: _run_trial(True))
        no_btn.configure(command=lambda: _run_trial(False))

        def _trial_email_return(_ev=None):
            if state["step"] == "email":
                _do_send(False)
            return "break"

        email_entry.bind("<Return>", _trial_email_return)

        def _center():
            try:
                dlg.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                x = max(20, rx + (rw - dw) // 2)
                y = max(20, ry + 52)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

        try:
            dlg.protocol("WM_DELETE_WINDOW", _close_wizard)
        except Exception:
            pass
        _layout()
        dlg.after(10, _center)

    def _open_link_subscription_wizard(self):
        """Stripe billing email → OTP (Brevo) → link install_id; refresh license without restart."""
        if not self._should_show_plan_link_existing_subscription():
            return
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "link_subscription_start"):
            return
        try:
            self._reset_license_sync_cooldown()
            self._request_license_remote_sync(ignore_cooldown=True)
        except Exception:
            pass
        if getattr(self, "_link_sub_wizard_dlg", None):
            try:
                if self._link_sub_wizard_dlg.winfo_exists():
                    self._link_sub_wizard_dlg.lift()
                    return
            except Exception:
                pass

        dlg = CTkToplevel(self.root)
        self._link_sub_wizard_dlg = dlg
        self._wizard_prepare_toplevel(dlg, self._plan_lk_s("wizard_title", "Link subscription"), "440x310")

        tick = {"job": None}
        _shell, content, inner_pad, content_pad_top, link_gold, link_gold_hover = self._wizard_make_shell(dlg, border_color=SKIN_SELECTED_BORDER)

        def _close_wizard():
            if tick["job"]:
                try:
                    dlg.after_cancel(tick["job"])
                except Exception:
                    pass
                tick["job"] = None
            try:
                dlg.destroy()
            except Exception:
                pass
            self._link_sub_wizard_dlg = None

        # content is provided by _wizard_make_shell (Plan Management style)

        headline_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
            anchor="center",
            justify="center",
        )
        email_intro_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="left",
            anchor="w",
            wraplength=390,
        )
        hint_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="center",
            anchor="center",
            wraplength=390,
        )

        # No textvariable: CustomTkinter only shows placeholder when textvariable is None
        # (see CTkEntry._activate_placeholder).
        _email_ph = self._plan_lk_s("email_placeholder", "your@email.com")
        email_entry = ctk.CTkEntry(
            content,
            placeholder_text=_email_ph,
            placeholder_text_color=MUTED,
            text_color=TXT,
            fg_color=CARD,
            height=38,
            font=("Segoe UI", 14),
            corner_radius=10,
            border_width=1,
            border_color=link_gold,
        )
        _ctk_entry_keep_placeholder_until_keystroke(email_entry)

        otp_row = CTkFrame(content, fg_color="transparent")
        otp_entries: list = []
        for _i in range(6):
            ent = ctk.CTkEntry(
                otp_row,
                width=44,
                height=48,
                font=("Segoe UI", 20, "bold"),
                justify="center",
                corner_radius=10,
                border_width=1,
                border_color=link_gold,
            )
            otp_entries.append(ent)

        for col, ent in enumerate(otp_entries):
            ent.grid(row=0, column=col, padx=4, sticky="nsew")
            otp_row.grid_columnconfigure(col, weight=1, uniform="otp")

        def _otp_clear():
            for ent in otp_entries:
                try:
                    ent.delete(0, "end")
                except Exception:
                    pass

        def _otp_code() -> str:
            parts = []
            for ent in otp_entries:
                raw = (ent.get() or "").strip()
                digits = "".join(c for c in raw if c.isdigit())
                parts.append(digits[-1:] if digits else "")
            return "".join(parts)

        def _wire_otp_entry(idx: int, ent):
            def _kr(_ev=None):
                raw = ent.get() or ""
                digits = "".join(c for c in raw if c.isdigit())
                if len(digits) > 1 or raw != digits:
                    ent.delete(0, "end")
                    if digits:
                        ent.insert(0, digits[-1])
                if (ent.get() or "").strip() and idx < 5:
                    try:
                        otp_entries[idx + 1].focus_set()
                    except Exception:
                        pass

            def _kp(ev):
                if ev.keysym == "Backspace" and not (ent.get() or "") and idx > 0:
                    try:
                        otp_entries[idx - 1].focus_set()
                        otp_entries[idx - 1].delete(0, "end")
                    except Exception:
                        pass

            ent.bind("<KeyRelease>", _kr)
            ent.bind("<KeyPress>", _kp)

        for i, ent in enumerate(otp_entries):
            _wire_otp_entry(i, ent)

        def _otp_paste_first(_ev=None):
            try:
                txt = dlg.clipboard_get()
            except Exception:
                return "break"
            digits = "".join(c for c in (txt or "") if c.isdigit())[:6]
            _otp_clear()
            for j, ch in enumerate(digits):
                try:
                    otp_entries[j].insert(0, ch)
                except Exception:
                    pass
            try:
                otp_entries[min(len(digits), 5)].focus_set()
            except Exception:
                pass
            return "break"

        if otp_entries:
            otp_entries[0].bind("<<Paste>>", _otp_paste_first)

        status_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 12),
            text_color="#F87171",
            wraplength=390,
            justify="center",
            anchor="center",
        )

        send_btn = CTkButton(
            content,
            text=self._plan_lk_s("send_code", "Send code"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
        )
        actions_otp = CTkFrame(content, fg_color="transparent")
        verify_btn = CTkButton(
            actions_otp,
            text=self._plan_lk_s("verify", "Verify & link"),
            font=("Segoe UI", 13, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=40,
            corner_radius=10,
        )
        resend_btn = CTkButton(
            actions_otp,
            text=self._plan_lk_s("resend", "Resend code"),
            font=("Segoe UI", 12),
            fg_color="transparent",
            hover_color=SEL_BG,
            text_color=link_gold,
            height=36,
        )
        close_btn = CTkButton(
            content,
            text=self._plan_lk_s("close", "Continue"),
            font=("Segoe UI", 14, "bold"),
            fg_color=link_gold,
            hover_color=link_gold_hover,
            text_color="#0E0E14",
            height=42,
            corner_radius=10,
            command=lambda: (_close_wizard(), self._refresh_plan_cards()),
        )

        state = {"step": "email"}

        def _set_busy(on: bool, msg: str = ""):
            st = "disabled" if on else "normal"
            send_btn.configure(state=st)
            verify_btn.configure(state=st)
            resend_btn.configure(state=st)
            try:
                email_entry.configure(state=st)
            except Exception:
                pass
            for ent in otp_entries:
                try:
                    ent.configure(state=st)
                except Exception:
                    pass
            if msg:
                status_lbl.configure(text=msg, text_color=TXT2)

        def _show_resend_cooldown(sec: int):
            if tick["job"]:
                try:
                    dlg.after_cancel(tick["job"])
                except Exception:
                    pass
                tick["job"] = None
            resend_btn.configure(state="disabled")
            box = {"left": max(0, int(sec))}

            def _tick_one():
                if not dlg.winfo_exists():
                    tick["job"] = None
                    return
                if box["left"] <= 0:
                    resend_btn.configure(
                        state="normal",
                        text=self._plan_lk_s("resend", "Resend code"),
                    )
                    tick["job"] = None
                    return
                resend_btn.configure(
                    text=self._plan_lk_s("resend_wait", "Resend ({s}s)").replace("{s}", str(box["left"]))
                )
                box["left"] -= 1
                tick["job"] = dlg.after(1000, _tick_one)

            _tick_one()

        def _layout_step():
            status_lbl.configure(text="")
            for w in (
                headline_lbl,
                email_intro_lbl,
                hint_lbl,
                email_entry,
                otp_row,
                send_btn,
                actions_otp,
                close_btn,
                status_lbl,
            ):
                try:
                    w.pack_forget()
                except Exception:
                    pass
            if state["step"] == "email":
                headline_lbl.configure(text=self._plan_lk_s("wizard_title", "Link your subscription"))
                headline_lbl.pack(fill="x", pady=(0, 15))
                email_intro_lbl.configure(
                    text=self._plan_lk_s(
                        "email_intro",
                        "Enter your email to get started — we'll send you a 6-digit code to confirm it's you.",
                    )
                )
                email_intro_lbl.pack(fill="x", pady=(0, 30))
                email_entry.pack(fill="x", pady=(0, 8))
                status_lbl.pack(fill="x", pady=(0, 6))
                send_btn.pack(fill="x", pady=(0, 0))
                try:
                    dlg.after(80, lambda: email_entry.focus_set())
                except Exception:
                    pass
            elif state["step"] == "otp":
                headline_lbl.configure(
                    text=self._plan_lk_s("otp_headline", "Verify your email")
                )
                headline_lbl.pack(fill="x", pady=(0, 13))
                hint_lbl.configure(
                    font=("Segoe UI", 13, "bold"),
                    text_color=TXT,
                    text=self._plan_lk_s("otp_hint", "Enter the 6-digit code we emailed you."),
                )
                hint_lbl.pack(fill="x", pady=(0, 32))
                otp_row.pack(fill="x", pady=(0, 10))
                status_lbl.pack(fill="x", pady=(0, 8))
                actions_otp.pack(fill="x", pady=(0, 0))
                verify_btn.pack(side="left")
                resend_btn.pack(side="right")
                _otp_clear()
                _show_resend_cooldown(30)
                try:
                    dlg.after(80, lambda: otp_entries[0].focus_set())
                except Exception:
                    pass
            else:
                headline_lbl.configure(text=self._plan_lk_s("success_title", "You're all set! 🎉"))
                headline_lbl.pack(fill="x", pady=(0, 13))
                hint_lbl.configure(
                    text=self._plan_lk_s(
                        "success_body",
                        "Your subscription is linked. Pro is active on this PC.",
                    ),
                    font=("Segoe UI", 13),
                    text_color=TXT2,
                )
                hint_lbl.pack(fill="x", pady=(0, 34))
                try:
                    close_btn.configure(text=self._plan_lk_s("success_cta", "Start using PerkySue"))
                except Exception:
                    pass
                close_btn.pack(fill="x", pady=(0, 0))

        def _after_link_refresh(billing_email: str = ""):
            try:
                orch.refresh_license_from_remote()
            except Exception:
                pass
            try:
                em = (billing_email or "").strip()
                if em and "@" in em:
                    orch.set_license_billing_email(em)
            except Exception:
                pass
            try:
                self._refresh_plan_cards()
            except Exception:
                pass
            try:
                self._refresh_user_billing_email_display()
            except Exception:
                pass
            try:
                self._refresh_header_banner_if_idle()
            except Exception:
                pass

        def _do_send(is_resend: bool):
            em = (email_entry.get() or "").strip()
            if not em or "@" not in em:
                status_lbl.configure(text=self._plan_lk_err("invalid_email", "Enter a valid email."), text_color="#F87171")
                return
            status_lbl.configure(text="")

            def _run():
                if is_resend:
                    data, http = orch.link_subscription_resend(em)
                else:
                    data, http = orch.link_subscription_start(em)

                def _ui():
                    if not dlg.winfo_exists():
                        return
                    _set_busy(False)
                    if http == 0:
                        status_lbl.configure(text=self._plan_lk_err("network", "Could not reach perkysue.com."), text_color="#F87171")
                        return
                    if is_resend and http == 429:
                        sec = int((data or {}).get("retry_after_sec") or 30)
                        status_lbl.configure(text=self._plan_lk_err("cooldown", "Wait before resending."), text_color="#F87171")
                        _show_resend_cooldown(max(1, sec))
                        return
                    if not is_resend and data.get("ok") is False:
                        if data.get("error_code") == "subscription_inactive":
                            status_lbl.configure(
                                text=self._plan_lk_err("inactive", "No active subscription for this email."),
                                text_color="#F87171",
                            )
                        else:
                            status_lbl.configure(
                                text=self._plan_link_api_user_message(data, http),
                                text_color="#F87171",
                            )
                        return
                    if data.get("ok"):
                        if not is_resend:
                            state["step"] = "otp"
                            _layout_step()
                        else:
                            status_lbl.configure(text=self._plan_lk_s("resent_ok", "New code sent."), text_color="#6ee7b7")
                            _show_resend_cooldown(30)
                        return
                    status_lbl.configure(
                        text=self._plan_link_api_user_message(data, http),
                        text_color="#F87171",
                    )

                self.root.after(0, _ui)

            _set_busy(True, self._plan_lk_s("busy_sending", "Sending…"))
            threading.Thread(target=_run, daemon=True).start()

        def _do_verify():
            em = (email_entry.get() or "").strip()
            code = _otp_code()
            if len(code) < 6:
                status_lbl.configure(text=self._plan_lk_err("invalid_code", "Enter the 6-digit code from your email."), text_color="#F87171")
                return

            def _run():
                data, http = orch.link_subscription_verify(em, code)

                def _ui():
                    if not dlg.winfo_exists():
                        return
                    _set_busy(False)
                    if http == 0:
                        status_lbl.configure(text=self._plan_lk_err("network", "Could not reach perkysue.com."), text_color="#F87171")
                        return
                    if data.get("ok"):
                        state["step"] = "done"
                        _layout_step()
                        _after_link_refresh(em)
                        return
                    if data.get("error_code") == "invalid_code":
                        left = data.get("attempts_left")
                        extra = f" ({left})" if left is not None else ""
                        status_lbl.configure(
                            text=self._plan_lk_err("wrong_code", "Incorrect code.") + extra,
                            text_color="#F87171",
                        )
                        return
                    if http == 429 or (data.get("error") or "").lower().find("attempt") >= 0:
                        status_lbl.configure(text=self._plan_lk_err("attempts", "Too many attempts."), text_color="#F87171")
                        return
                    status_lbl.configure(
                        text=self._plan_link_api_user_message(data, http),
                        text_color="#F87171",
                    )

                self.root.after(0, _ui)

            _set_busy(True, self._plan_lk_s("busy_verify", "Verifying…"))
            threading.Thread(target=_run, daemon=True).start()

        send_btn.configure(command=lambda: _do_send(False))
        verify_btn.configure(command=_do_verify)
        resend_btn.configure(command=lambda: _do_send(True))

        def _link_email_return(_ev=None):
            if state["step"] == "email":
                _do_send(False)
            return "break"

        email_entry.bind("<Return>", _link_email_return)

        def _after_link_done():
            _after_link_refresh((email_entry.get() or "").strip())

        close_btn.configure(
            command=lambda: (_close_wizard(), _after_link_done()),
        )

        try:
            dlg.protocol("WM_DELETE_WINDOW", _close_wizard)
        except Exception:
            pass

        def _center():
            try:
                dlg.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                x = max(20, rx + (rw - dw) // 2)
                y = max(20, ry + 52)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

        _layout_step()
        dlg.after(10, _center)

# ── PAGE SETTINGS ─────────────────────────────────────────
    def _mk_settings(self):
        pg = CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["settings"] = pg
        # Scroll rapide (40-120 u par cran) pour la page Settings.
        # Si le pointeur est au-dessus de la zone Appearance/skins, on laisse cette zone
        # gérer le scroll (et l'escalade vers la page) pour éviter un double défilement.
        try:
            c = pg._parent_canvas
            def _wheel_fast(e, frame=pg):
                try:
                    if getattr(self, "_is_widget_under_skin_area", None):
                        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
                        w_under = self.root.winfo_containing(px, py)
                        if w_under is not None and self._is_widget_under_skin_area(w_under):
                            return
                except Exception:
                    pass
                if getattr(frame, "_parent_canvas", None) is None:
                    return
                canv = frame._parent_canvas
                y0, y1 = canv.yview()
                at_top = y0 <= 0.0
                at_bottom = y1 >= 1.0
                going_up = e.delta > 0
                going_down = e.delta < 0
                if at_top and going_up:
                    return "break"
                if at_bottom and going_down:
                    return "break"
                step = 80
                u = -step if (e.delta > 0) else step
                if (y0, y1) != (0.0, 1.0):
                    Tooltip.hide_current()
                    canv.yview("scroll", u, "units")
                return "break"
            c.bind("<MouseWheel>", _wheel_fast)
        except Exception:
            pass

        # === SECTION 0 : PLAN MANAGEMENT ===
        self._build_plan_management(pg)

        # === SECTION 1 : APPEARANCE ===
        title_row = CTkFrame(pg, fg_color="transparent")
        title_row.pack(fill="x", pady=(20, 10), padx=(0, 28))
        title_row.grid_columnconfigure(1, weight=1)
        CTkLabel(title_row, text=s("settings.appearance.title"), font=("Segoe UI", 20, "bold"), text_color=TXT).grid(row=0, column=0, sticky="w")
        patreon_lbl = CTkLabel(title_row, text=s("settings.appearance.patreon_cta"), font=("Segoe UI", 17), text_color=GOLD, cursor="hand2")
        patreon_lbl.grid(row=0, column=1, sticky="e", pady=(4, 0))
        patreon_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://patreon.com/PerkySue"))

        skin_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        skin_card.pack(fill="x", pady=(0, 20), padx=(0, 28))
        # Filtre langue : présélection = langue UI (évite une grille pleine de doublons « Mike »).
        # Si le skin sauvegardé est dans une autre locale, on bascule le filtre sur cette locale pour le garder visible ; en dernier recours seulement « all ».
        discovered = discover_skins(self.paths)
        all_langs = sorted({s["lang"] for s in discovered}, key=lambda x: (x.upper() != "EN", x.upper()))
        self._skin_list_all = [{"id": "Default", "lang": None, "name": s("settings.appearance.default_skin"), "unlocked": True}] + discovered

        def _pick_filter_lang(pack_key: str):
            for L in all_langs:
                if skin_locale_codes_match(L, pack_key):
                    return L
            return None

        def _skins_for_filter(filt: str):
            if filt == "all":
                return list(self._skin_list_all)
            return [
                sk
                for sk in self._skin_list_all
                if sk.get("id") == "Default" or skin_locale_codes_match(sk.get("lang") or "", filt)
            ]

        ui_pack_key = skin_pack_lang_from_ui(self._strings_locale_from_cfg())
        initial_filter = _pick_filter_lang(ui_pack_key)
        if initial_filter is None and all_langs:
            initial_filter = all_langs[0]
        elif initial_filter is None:
            initial_filter = "all"

        preview_filtered = _skins_for_filter(initial_filter)
        cur_norm = normalize_skin_id(self.paths, (self.cfg.get("skin") or {}).get("active", "Default"))
        if cur_norm != "Default" and not any(sk.get("id") == cur_norm for sk in preview_filtered):
            _char, loc = split_skin_id(cur_norm)
            if loc:
                switch_to = _pick_filter_lang(loc)
                if switch_to:
                    initial_filter = switch_to
                    preview_filtered = _skins_for_filter(initial_filter)
        if cur_norm != "Default" and not any(sk.get("id") == cur_norm for sk in preview_filtered):
            initial_filter = "all"
            preview_filtered = _skins_for_filter(initial_filter)

        self._skin_filter_lang = tk.StringVar(value=initial_filter)
        filters_skin_f = CTkFrame(skin_card, fg_color="transparent")
        filters_skin_f.pack(fill="x", padx=25, pady=(15, 0))
        self._skin_filter_buttons = []
        for lang_id, lang_label in [("all", s("settings.appearance.filter_all"))] + [(x, x) for x in all_langs]:
            is_active = (lang_id == self._skin_filter_lang.get())
            bg_c = SEL_BG if is_active else INPUT
            btn = CTkButton(
                filters_skin_f, text=lang_label, width=0, height=26, corner_radius=6,
                fg_color=bg_c, hover_color=SEL_BG, font=("Segoe UI", 11),
                text_color=TXT if is_active else TXT2,
                command=lambda l=lang_id: self._on_skin_filter(l),
            )
            btn.pack(side="left", padx=(0, 8))
            self._skin_filter_buttons.append((lang_id, btn))

        self.inner_skin = CTkScrollableFrame(skin_card, fg_color="transparent", height=280)
        self.inner_skin.pack(fill="both", expand=True, pady=(10, 32), padx=(25, 4))
        self.inner_skin.grid_columnconfigure((0, 1, 2), weight=1)
        self._skin_btns = {}
        self._skin_cols = {}
        self._skin_list_filtered = self._filter_skin_list()
        current_skin = self._effective_skin()
        self._build_skin_grid(current_skin)
        self._last_skin_size = 120
        # Scroll spécifique à la zone skins (via inner_skin et ses enfants) ; design de la barre inchangé.
        self.inner_skin.bind("<MouseWheel>", self._on_skin_area_wheel)
        self.inner_skin.bind("<Configure>", self._on_skin_resize)
        self.root.after(100, self._skin_scrollregion_update)

        # === SECTION 2 : RECOMMENDED MODELS ===
        CTkLabel(pg, text=s("settings.recommended_models.title"), font=("Segoe UI", 20, "bold"), text_color=TXT).pack(anchor="w", pady=(20, 10))
        
        models_card = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        models_card.pack(fill="x", pady=(0, 20), padx=(0, 28))
        
        # Filtres Matériel (CPU, Vulkan, etc.) — cliquables pour filtrer la liste
        backend = os.environ.get("PERKYSUE_BACKEND", "cpu")
        backend_labels = [
            ("cpu", "CPU"),
            ("vulkan", "Vulkan"),
            ("nvidia-cuda-12.4", "Nvidia 12.4"),
            ("nvidia-cuda-13.1", "Nvidia 13.1"),
        ]
        self._model_filter_backend = tk.StringVar(value=backend)
        self._model_filter_favorites_only = tk.BooleanVar(value=False)
        self._model_filter_search = tk.StringVar(value="")
        self._inner_models_frame = None
        self._model_filter_buttons = []
        self._model_filter_favorite_btn = None
        filters_f = CTkFrame(models_card, fg_color="transparent")
        filters_f.pack(fill="x", padx=20, pady=(15, 0))
        for bid, label in backend_labels:
            is_active = (bid == backend)
            bg_c = SEL_BG if is_active else INPUT
            btn = CTkButton(
                filters_f, text=label, width=0, height=28, corner_radius=6,
                fg_color=bg_c, hover_color=SEL_BG, font=("Segoe UI", 12),
                text_color=TXT if is_active else TXT2,
                command=lambda b=bid: self._on_model_filter(b),
            )
            btn.pack(side="left", padx=(0, 10))
            self._model_filter_buttons.append((bid, btn))

        # Favorites toggle (same row, after backend pills); AND-combined with backend + search.
        fav_active = self._model_filter_favorites_only.get()
        fav_bg = SEL_BG if fav_active else INPUT
        self._model_filter_favorite_btn = CTkButton(
            filters_f, text="⭐", width=44, height=28, corner_radius=6,
            fg_color=fav_bg, hover_color=SEL_BG, font=("Segoe UI", 14),
            text_color=TXT if fav_active else TXT2,
            command=self._on_model_filter_favorites_toggle,
        )
        self._model_filter_favorite_btn.pack(side="left", padx=(0, 10))
        Tooltip(
            self._model_filter_favorite_btn,
            text=s("settings.recommended_models.filter_favorites_hint", default="Show favorites only"),
            bind_widgets=[self._model_filter_favorite_btn],
        )

        # Text search (same row, expands): name, family, author, id, filename, repo, params, quant.
        search_wrap = CTkFrame(filters_f, fg_color="transparent")
        search_wrap.pack(side="left", fill="x", expand=True, padx=(0, 0))
        self._model_filter_search_entry = ctk.CTkEntry(
            search_wrap,
            textvariable=self._model_filter_search,
            placeholder_text=s("settings.recommended_models.search_placeholder", default="Search models…"),
            font=("Segoe UI", 12),
            height=28,
            fg_color=INPUT,
            border_color="#3A3A42",
        )
        self._model_filter_search_entry.pack(fill="x", expand=True)

        # Grille des modèles (catalogue YAML, filtré par backend)
        # Same sub-scroll design as Appearance: right margin 4px from border.
        inner_models = CTkScrollableFrame(models_card, fg_color="transparent", height=450)
        inner_models.pack(fill="both", expand=True, padx=(25, 4), pady=(10, 15))
        inner_models.grid_columnconfigure((0, 1), weight=1, uniform="col")
        inner_models.bind("<MouseWheel>", self._on_models_area_wheel)
        self._inner_models_frame = inner_models
        self.inner_models = inner_models

        try:
            self._model_filter_search.trace_add("write", lambda *_a, _w=self: _w._refresh_models_grid())
        except Exception:
            self._model_filter_search_entry.bind("<KeyRelease>", lambda _e: self._refresh_models_grid())

        self._refresh_models_grid()

        # "More models" placeholder removed: models list now has its own scroll area.

        # === SECTION 3 : PERFORMANCE SETTINGS (mockup: STT, LLM, Max tokens) ===
        CTkLabel(pg, text=s("settings.performance.title"), font=("Segoe UI", 20, "bold"), text_color=TXT).pack(anchor="w", pady=(20, 10))
        perf_box = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        perf_box.pack(fill="x", pady=(0, 20), padx=(0, 28))
        padx_row = 20
        pady_row = 14
        stt_models = ["tiny", "base", "small", "medium", "large-v3"]
        stt_current = (self.cfg.get("stt") or {}).get("model") or "medium"
        if stt_current not in stt_models:
            stt_current = "medium"
        self._perf_stt = tk.StringVar(value=stt_current.capitalize())
        # STT Device: Auto/CPU/GPU for NVIDIA; grisé sur CPU pour les autres
        backend = os.environ.get("PERKYSUE_BACKEND", "")
        self._is_nvidia_stt = backend.startswith("nvidia-")
        stt_device_cfg = (self.cfg.get("stt") or {}).get("device", "auto")
        stt_device_display = "GPU" if stt_device_cfg == "cuda" else ("CPU" if stt_device_cfg == "cpu" else "Auto")
        stt_device_opts = ["Auto", "CPU", "GPU"] if self._is_nvidia_stt else ["CPU"]
        if stt_device_display not in stt_device_opts:
            stt_device_display = stt_device_opts[0]
        self._perf_stt_device = tk.StringVar(value=stt_device_display)
        # First language for UI / future LLM greeting (identity.first_language). Same codes as Whisper/STT.
        first_lang_cfg = (self.cfg.get("identity") or {}).get("first_language", "auto")
        first_language_opts = [
            "Auto", "en", "fr", "de", "es", "it", "pt", "nl", "pl", "ru", "ja", "zh", "ko", "ar", "hi",
            "tr", "sv", "da", "no", "fi", "el", "cs", "hu", "ro", "uk", "vi", "th", "id", "ms", "he",
            "bg", "hr", "sk", "sl", "et", "lv", "lt", "sr", "ca", "eu", "gl", "nb", "fa",
            "bn", "ta", "te", "mr", "ur", "my", "km", "lo", "ne", "si", "pa", "gu", "kn", "ml",
        ]
        first_lang_display = first_lang_cfg if first_lang_cfg in first_language_opts else "Auto"
        if first_lang_display not in first_language_opts:
            first_lang_display = "Auto"
        self._perf_first_language = tk.StringVar(value=first_lang_display)
        self._first_language_opts = first_language_opts
        self._perf_llm = tk.StringVar(value=(self.cfg.get("llm") or {}).get("model") or "")
        # Max input (context): prefer max_input_tokens, fallback n_ctx; 0 or missing = Auto
        llm_cfg = self.cfg.get("llm") or {}
        n_ctx_cfg = llm_cfg.get("max_input_tokens", llm_cfg.get("n_ctx"))
        if n_ctx_cfg is None or n_ctx_cfg == 0:
            max_input_val = "Auto"
        else:
            max_input_val = str(n_ctx_cfg)
        max_input_opts = ["Auto", "1024", "2048", "4096", "8192", "16384"]
        if max_input_val not in max_input_opts:
            max_input_val = "Auto"
        self._perf_max_input = tk.StringVar(value=max_input_val)
        # Max output: 0 = Auto (scale with context); prefer max_output_tokens, fallback max_tokens
        max_tok_cfg = llm_cfg.get("max_output_tokens", llm_cfg.get("max_tokens", 2048))
        try:
            max_tok_int = int(max_tok_cfg) if max_tok_cfg is not None and str(max_tok_cfg).strip() != "" else 0
        except (TypeError, ValueError):
            max_tok_int = 2048
        self._perf_max_tokens = tk.StringVar(value="Auto" if max_tok_int == 0 else str(max_tok_int))
        max_tokens_opts = ["Auto", "256", "512", "1024", "2048", "4096", "8192"]
        if self._perf_max_tokens.get() not in max_tokens_opts:
            self._perf_max_tokens.set("2048")
        _ctx_keep_cfg = llm_cfg.get("answer_context_keep", 2)
        try:
            _ctx_keep_int = int(_ctx_keep_cfg)
        except (TypeError, ValueError):
            _ctx_keep_int = 2
        if _ctx_keep_int not in (2, 3, 4):
            _ctx_keep_int = 2
        self._perf_answer_context_keep = tk.StringVar(value=str(_ctx_keep_int))
        answer_context_keep_opts = ["2", "3", "4"]
        _answer_ctx_keep_disabled = not bool(self.orch.is_effective_pro()) if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro") else True
        _inject_all_modes_cfg = llm_cfg.get("inject_all_modes_in_chat", True)
        if isinstance(_inject_all_modes_cfg, str):
            _inject_all_modes_on = _inject_all_modes_cfg.strip().lower() in ("1", "true", "yes", "on")
        else:
            _inject_all_modes_on = bool(_inject_all_modes_cfg)
        self._perf_inject_all_modes_chat = tk.StringVar(value="On" if _inject_all_modes_on else "Off")
        _inject_all_modes_disabled = not bool(self.orch.is_effective_pro()) if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro") else True
        audio_cfg = self.cfg.get("audio") or {}
        # Audio envoyé à l'écoute / au STT (mic / loopback PC / mix) — audio.capture_mode
        _cap_raw = str(audio_cfg.get("capture_mode") or "mic_only").strip().lower()
        if _cap_raw not in ("mic_only", "system_only", "mix"):
            _cap_raw = "mic_only"
        _lbl_mic = s("settings.performance.capture_mode.mic_only", default="Microphone")
        _lbl_sys = s("settings.performance.capture_mode.system_only", default="System audio")
        _lbl_mix = s("settings.performance.capture_mode.mix", default="System + Mic")
        self._perf_capture_labels = (_lbl_mic, _lbl_sys, _lbl_mix)
        self._perf_capture_cfg_order = ("mic_only", "system_only", "mix")
        self._perf_capture_display_to_cfg = dict(zip(self._perf_capture_labels, self._perf_capture_cfg_order))
        self._perf_capture_cfg_to_display = {v: k for k, v in self._perf_capture_display_to_cfg.items()}
        _capture_mode_disabled = not bool(self.orch.is_effective_pro()) if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro") else True
        if _capture_mode_disabled:
            _cap_raw = "mic_only"
        self._perf_capture_mode = tk.StringVar(value=self._perf_capture_cfg_to_display.get(_cap_raw, _lbl_mic))
        capture_opts = list(self._perf_capture_labels)
        mic_sel_opts, self._perf_mic_label_to_device_index, mic_cur_lbl = self._perf_mic_build_option_data(audio_cfg)
        self._perf_mic_device = tk.StringVar(value=mic_cur_lbl)
        # Silence timeout (seconds before auto-stop on silence)
        sil_cfg = audio_cfg.get("silence_timeout", 2.0)
        try:
            sil_val = f"{float(sil_cfg):.1f}"
        except (TypeError, ValueError):
            sil_val = "2.0"
        silence_opts = ["1.5", "2.0", "2.5", "3.0", "3.5", "4.0"]
        if sil_val not in silence_opts:
            sil_val = "3.0"
        self._perf_silence_timeout = tk.StringVar(value=sil_val)
        # VAD sensitivity preset (audio.vad_sensitivity) — quiet_room | normal | noisy
        _lbl_vq = s("settings.performance.vad_sensitivity.quiet_room", default="Quiet room / Low mic")
        _lbl_vn = s("settings.performance.vad_sensitivity.normal", default="Normal")
        _lbl_vy = s("settings.performance.vad_sensitivity.noisy", default="Noisy / Loud environment")
        self._perf_vad_labels = (_lbl_vq, _lbl_vn, _lbl_vy)
        self._perf_vad_cfg_order = ("quiet_room", "normal", "noisy")
        self._perf_vad_display_to_cfg = dict(zip(self._perf_vad_labels, self._perf_vad_cfg_order))
        self._perf_vad_cfg_to_display = {v: k for k, v in self._perf_vad_display_to_cfg.items()}

        def _initial_vad_cfg_key(ac: dict) -> str:
            vs = ac.get("vad_sensitivity")
            if isinstance(vs, str):
                k = vs.strip().lower()
                if k in self._perf_vad_cfg_order:
                    return k
            va = ac.get("vad_aggressiveness")
            if va is not None and not isinstance(va, bool):
                try:
                    av = max(0, min(3, int(float(va))))
                except (TypeError, ValueError):
                    return "normal"
                return {0: "quiet_room", 1: "quiet_room", 2: "normal", 3: "noisy"}.get(av, "normal")
            return "normal"

        _vad_cfg_key = _initial_vad_cfg_key(audio_cfg)
        self._perf_vad_sensitivity = tk.StringVar(
            value=self._perf_vad_cfg_to_display.get(_vad_cfg_key, _lbl_vn)
        )
        vad_sensitivity_opts = list(self._perf_vad_labels)
        # Max recording duration (seconds before hard stop)
        max_dur_cfg = audio_cfg.get("max_duration")
        if max_dur_cfg is not None:
            try:
                max_dur_val = str(int(float(max_dur_cfg)))
            except (TypeError, ValueError):
                max_dur_val = ""
        else:
            max_dur_val = ""
        if not max_dur_val:
            # Choix par défaut en fonction du backend et du modèle STT
            stt_model_name = (self.cfg.get("stt") or {}).get("model") or stt_current
            stt_model_name = str(stt_model_name).lower()
            backend_lower = backend.lower()
            if backend_lower.startswith("nvidia-"):
                max_dur_val = "180"
            else:
                if stt_model_name == "small":
                    max_dur_val = "120"
                else:
                    max_dur_val = "90"
        # Hard cap for one-shot RAM capture + single-pass STT; raise with care on low-RAM machines.
        max_duration_opts = ["60", "90", "120", "180", "240", "300", "360", "480", "600", "900"]
        if max_dur_val not in max_duration_opts:
            try:
                v = int(float(max_dur_val))
                v = max(60, min(900, v))
                ints = [int(x) for x in max_duration_opts]
                max_dur_val = str(min(ints, key=lambda t: abs(t - v)))
            except (TypeError, ValueError):
                max_dur_val = "120"
        self._perf_max_duration = tk.StringVar(value=max_dur_val)
        # LLM HTTP request timeout (llama-server / long generations) — merged config preferred
        _llm_merged = (getattr(self.orch, "config", None) or {}).get("llm") if getattr(self, "orch", None) else None
        llm_for_timeout = (_llm_merged or self.cfg.get("llm") or {})
        try:
            rt_val = int(llm_for_timeout.get("request_timeout", 180))
        except (TypeError, ValueError):
            rt_val = 180
        timeout_opts = ["120", "150", "180", "210", "240", "270", "300", "360"]
        if str(rt_val) not in timeout_opts:
            rt_val = 180
        self._perf_llm_request_timeout = tk.StringVar(value=str(rt_val))
        # Thinking models (llama-server --reasoning-budget); restart serveur / Apply LLM requis
        th_raw = str(llm_for_timeout.get("thinking", "off")).strip().lower()
        self._perf_thinking = tk.StringVar(value="On" if th_raw in ("on", "true", "1", "yes") else "Off")
        try:
            _tb = int(llm_for_timeout.get("thinking_budget", 512))
        except (TypeError, ValueError):
            _tb = 512
        _thinking_budget_opts = ["256", "512", "1024", "2048", "Unlimited"]
        _tb_disp = "Unlimited" if _tb < 0 else (str(_tb) if str(_tb) in _thinking_budget_opts else "512")
        self._perf_thinking_budget = tk.StringVar(value=_tb_disp)
        llm_files = []
        if self.paths.models_llm.exists():
            try:
                llm_files = sorted(f.name for f in self.paths.models_llm.glob("*.gguf"))
            except Exception:
                pass
        current_llm = self._perf_llm.get()
        if not current_llm and llm_files:
            self._perf_llm.set(llm_files[0])
        if current_llm and current_llm not in llm_files:
            llm_files = [current_llm] + [f for f in llm_files if f != current_llm]
        stt_opts = [m.capitalize() for m in stt_models]
        perf_rows = [
            (
                s("settings.performance.capture_mode_label", default="STT source"),
                "🎧",
                self._perf_capture_mode,
                capture_opts,
                _capture_mode_disabled,
            ),
            (
                s("settings.performance.mic_select", default="Microphone input"),
                "🎚️",
                self._perf_mic_device,
                mic_sel_opts,
                False,
            ),
            (s("settings.performance.silence_timeout"), "🎙️", self._perf_silence_timeout, silence_opts, False),
            (
                s("settings.performance.vad_sensitivity_label", default="Voice detection"),
                "🗣️",
                self._perf_vad_sensitivity,
                vad_sensitivity_opts,
                False,
            ),
            (s("settings.performance.max_duration"), "⏱️", self._perf_max_duration, max_duration_opts, False),
            (s("settings.performance.stt_model"), "🎤", self._perf_stt, stt_opts, False),
            (s("settings.performance.stt_device"), "🖥️", self._perf_stt_device, stt_device_opts, not self._is_nvidia_stt),
            (s("settings.performance.llm_model"), "📦", self._perf_llm, llm_files if llm_files else [s("settings.performance.no_gguf")], False),
            (s("settings.performance.max_input"), "📥", self._perf_max_input, max_input_opts, False),
            (s("settings.performance.max_output"), "🔢", self._perf_max_tokens, max_tokens_opts, False),
            (
                s("settings.performance.remember_last_qa", default="Remember last Q/A"),
                "🧩",
                self._perf_answer_context_keep,
                answer_context_keep_opts,
                _answer_ctx_keep_disabled,
            ),
            (
                s("settings.performance.inject_all_modes_chat", default="Inject all modes in chat"),
                "💬",
                self._perf_inject_all_modes_chat,
                ["Off", "On"],
                _inject_all_modes_disabled,
            ),
            (s("settings.performance.llm_request_timeout"), "⏲️", self._perf_llm_request_timeout, timeout_opts, False),
        ]
        for label, icon_emoji, var, options, disabled in perf_rows:
            row_f = CTkFrame(perf_box, fg_color="transparent")
            row_f.pack(fill="x", padx=padx_row, pady=pady_row)
            icon_padx = (0, 10)  # uniforme pour aligner toutes les icônes (STT Device avait 6px de plus)
            CTkLabel(row_f, text=icon_emoji, font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=icon_padx)
            CTkLabel(row_f, text=label, font=("Segoe UI", 14), text_color=TXT).pack(side="left", padx=(0, 12))
            _om_w = 220
            om = CTkOptionMenu(
                row_f, variable=var, values=options, width=_om_w, font=("Segoe UI", 13),
                fg_color=INPUT, button_color=SIDEBAR, button_hover_color=SEL_BG,
            )
            om.pack(side="right")
            if var is self._perf_llm:
                # Keep a direct reference so LLM choices can be refreshed from disk without restart when needed.
                self._perf_llm_om = om
            if var is self._perf_mic_device:
                self._perf_mic_device_om = om
            if disabled:
                om.configure(state="disabled")
        try:
            _rt = getattr(self, "root", None)
            if _rt is not None:
                _rt.after(200, self._refresh_perf_mic_device_menu)
                _rt.after(1200, self._refresh_perf_mic_device_menu)
        except Exception:
            pass
        # Thinking: Off/On + budget (llama-server)
        _thinking_allow_opts = ["Off", "On"]

        def _row_perf_option(label: str, icon_emoji: str, var, options: list, disabled: bool):
            row_f = CTkFrame(perf_box, fg_color="transparent")
            row_f.pack(fill="x", padx=padx_row, pady=pady_row)
            icon_padx = (0, 10)
            CTkLabel(row_f, text=icon_emoji, font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=icon_padx)
            CTkLabel(row_f, text=label, font=("Segoe UI", 14), text_color=TXT).pack(side="left", padx=(0, 12))
            om = CTkOptionMenu(
                row_f, variable=var, values=options, width=220, font=("Segoe UI", 13),
                fg_color=INPUT, button_color=SIDEBAR, button_hover_color=SEL_BG,
            )
            om.pack(side="right")
            if disabled:
                om.configure(state="disabled")
            return om

        self._perf_thinking_om = _row_perf_option(
            s("settings.performance.thinking_allow", default="Allow thinking"),
            "🧠",
            self._perf_thinking,
            _thinking_allow_opts,
            False,
        )
        self._perf_thinking_budget_om = _row_perf_option(
            s("settings.performance.thinking_budget", default="Thinking token budget"),
            "📊",
            self._perf_thinking_budget,
            _thinking_budget_opts,
            False,
        )

        _clipboard_paste_delay_opts = ["0", "1", "2", "3", "4", "5", "10", "15", "20", "25", "30", "45", "60"]
        try:
            _cbd_cfg = float((self.cfg.get("injection") or {}).get("clipboard_restore_delay_sec", 5))
        except (TypeError, ValueError):
            _cbd_cfg = 5.0
        _cbd_snap = int(round(_cbd_cfg))
        if str(_cbd_snap) not in _clipboard_paste_delay_opts:
            _cbd_snap = min(
                (int(x) for x in _clipboard_paste_delay_opts),
                key=lambda t: abs(t - _cbd_snap),
            )
        self._perf_clipboard_paste_delay = tk.StringVar(value=str(_cbd_snap))
        _row_perf_option(
            s("settings.performance.clipboard_paste_delay", default="Clipboard paste delay (s)"),
            "📋",
            self._perf_clipboard_paste_delay,
            _clipboard_paste_delay_opts,
            False,
        )

        def _sync_thinking_budget_menu(*_a):
            try:
                on = self._perf_thinking.get() == "On"
                self._perf_thinking_budget_om.configure(state="normal" if on else "disabled")
            except Exception:
                pass

        def _on_thinking_toggle(*_a):
            _sync_thinking_budget_menu()
            self._trigger_save()

        self._perf_thinking.trace_add("write", _on_thinking_toggle)
        _sync_thinking_budget_menu()
        if not llm_files:
            self._perf_llm.set("")
        # Afficher Save & Restart dès qu’un réglage Performance change (STT, LLM, Max tokens, timeouts, etc.)
        for var in (
            self._perf_capture_mode,
            self._perf_mic_device,
            self._perf_stt,
            self._perf_stt_device,
            self._perf_first_language,
            self._perf_llm,
            self._perf_max_input,
            self._perf_max_tokens,
            self._perf_answer_context_keep,
            self._perf_inject_all_modes_chat,
            self._perf_silence_timeout,
            self._perf_vad_sensitivity,
            self._perf_max_duration,
            self._perf_llm_request_timeout,
            self._perf_thinking_budget,
            self._perf_clipboard_paste_delay,
        ):
            var.trace_add("write", lambda *a: self._trigger_save())

        # === SECTION : Advanced (debug — not tied to distributor tooling) ===
        CTkLabel(pg, text=s("settings.advanced.title", default="Advanced"), font=("Segoe UI", 20, "bold"), text_color=TXT).pack(
            anchor="w", pady=(24, 10), padx=(0, 28)
        )
        adv_box = CTkFrame(pg, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        adv_box.pack(fill="x", pady=(0, 20), padx=(0, 28))
        adv_inner = CTkFrame(adv_box, fg_color="transparent")
        adv_inner.pack(fill="x", padx=20, pady=16)
        _fb_cfg = (self.cfg.get("feedback") or {})
        self._feedback_debug_mode_var = tk.StringVar(
            value="On" if bool(_fb_cfg.get("debug_mode", False)) else "Off"
        )
        row_dbg = CTkFrame(adv_inner, fg_color="transparent")
        row_dbg.pack(fill="x", pady=(0, 8))
        CTkLabel(row_dbg, text="🛠️", font=("Segoe UI", 14), text_color=TXT2, width=32).pack(side="left", padx=(0, 10))
        CTkLabel(row_dbg, text=s("settings.advanced.debug_mode", default="Debug mode"), font=("Segoe UI", 14), text_color=TXT).pack(
            side="left", padx=(0, 12)
        )
        CTkOptionMenu(
            row_dbg,
            variable=self._feedback_debug_mode_var,
            values=["Off", "On"],
            width=220,
            font=("Segoe UI", 13),
            fg_color=INPUT,
            button_color=SIDEBAR,
            button_hover_color=SEL_BG,
        ).pack(side="right")
        CTkLabel(
            adv_inner,
            text=s(
                "settings.advanced.debug_mode_hint",
                default="When On: Full Console shows full STT, selection, and exact LLM system/user (after context fit). Disk log still has no chat content. Raw TTS [tags] in Chat/Help paste; PreviousAnswersSummary in Alt+A when relevant.",
            ),
            font=("Segoe UI", 12),
            text_color=MUTED,
            wraplength=520,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=(42, 0))
        self._feedback_debug_mode_var.trace_add("write", lambda *a: self._trigger_save())

    def _refresh_llm_model_choices_from_disk(self):
        """Refresh the LLM dropdown choices from Data/Models/LLM without restart."""
        om = getattr(self, "_perf_llm_om", None)
        if om is None or self._perf_llm is None:
            return
        try:
            llm_files = []
            if self.paths.models_llm.exists():
                llm_files = sorted(f.name for f in self.paths.models_llm.glob("*.gguf"))
            values = llm_files if llm_files else [s("settings.performance.no_gguf")]
            om.configure(values=values)
            current = (self._perf_llm.get() or "").strip()
            if current in llm_files:
                return
            if llm_files:
                self._perf_llm.set(llm_files[0])
            else:
                self._perf_llm.set("")
        except Exception:
            pass


    def _load_model_catalog(self):
        """Load recommended models from App/configs/recommended_models.yaml."""
        path = self.paths._app / "configs" / "recommended_models.yaml"
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, list) else (data.get("models") or [])
        except Exception:
            return []

    @staticmethod
    def _model_matches_recommended_search(m: dict, query: str) -> bool:
        """Substring search on catalog fields; whitespace-separated tokens are ANDed."""
        q = (query or "").strip().lower()
        if not q:
            return True
        parts = [
            m.get("name"), m.get("family"), m.get("author"), m.get("id"),
            m.get("filename"), m.get("repo_id"), m.get("params"), m.get("quant"),
        ]
        blob = " ".join(str(p) for p in parts if p is not None).lower()
        tokens = [t for t in q.split() if t]
        if not tokens:
            return True
        return all(t in blob for t in tokens)

    def _models_with_status(self, catalog, backend, favorites_only=False, search_query=""):
        """Filter catalog by backend and set status (get / select / current / progress).
        If config says a model is current but its file was removed from disk, we clear
        the config and show that model as 'get' (download active)."""
        filtered = [m for m in catalog if not m.get("backends") or backend in m.get("backends", [])]
        if favorites_only:
            filtered = [
                m for m in filtered
                if m.get("stars") is not None and int(m.get("stars", 0)) > 0
            ]
        if search_query and str(search_query).strip():
            q = str(search_query).strip()
            filtered = [m for m in filtered if self._model_matches_recommended_search(m, q)]
        models_dir = self.paths.models_llm
        existing = set()
        if models_dir.exists():
            try:
                existing = {f for f in os.listdir(models_dir) if f.endswith(".gguf")}
            except Exception:
                pass
        current_fn = (self.cfg.get("llm") or {}).get("model") or ""
        # If configured current model was removed from folder, clear config so UI and app stay consistent
        if current_fn and current_fn not in existing:
            if "llm" not in self.cfg:
                self.cfg["llm"] = {}
            self.cfg["llm"]["model"] = ""
            self._save_config({"llm": {"model": ""}})
            if getattr(self, "_perf_llm", None):
                self._perf_llm.set("")
            current_fn = ""
        downloading = getattr(self, "_downloading_entry", None)
        download_pct = getattr(self, "_download_pct", 0)
        result = []
        for m in filtered:
            entry = dict(m)
            fn = entry.get("filename", "")
            if downloading and entry.get("filename") == downloading.get("filename") and entry.get("repo_id") == downloading.get("repo_id"):
                entry["status"] = "progress"
                entry["pct"] = int(min(100, max(0, download_pct)))
            elif fn == current_fn and fn in existing:
                entry["status"] = "current"
            elif fn in existing:
                entry["status"] = "select"
            else:
                entry["status"] = "get"
            result.append(entry)
        return result

    def _on_model_filter(self, backend_id):
        """Filter button clicked: set backend and refresh model list."""
        self._model_filter_backend.set(backend_id)
        self._refresh_models_grid()

    def _on_model_filter_favorites_toggle(self):
        """Toggle second filter: only models with stars (1–3) in YAML."""
        self._model_filter_favorites_only.set(not self._model_filter_favorites_only.get())
        self._refresh_models_grid()

    def _refresh_models_grid(self):
        """Clear and repopulate the model cards for the selected backend."""
        if not getattr(self, "_inner_models_frame", None):
            return
        inner = self._inner_models_frame
        self._progress_card_prog_lbl = None
        self._progress_card_prog_img_ref = None
        for w in inner.winfo_children():
            w.destroy()
        backend = self._model_filter_backend.get()
        fav_only = getattr(self, "_model_filter_favorites_only", None)
        favorites_only = fav_only.get() if fav_only is not None else False
        for bid, btn in self._model_filter_buttons:
            is_active = (bid == backend)
            btn.configure(
                fg_color=SEL_BG if is_active else INPUT,
                text_color=TXT if is_active else TXT2,
            )
        fb = getattr(self, "_model_filter_favorite_btn", None)
        if fb is not None and fb.winfo_exists():
            fa = favorites_only
            fb.configure(
                fg_color=SEL_BG if fa else INPUT,
                text_color=TXT if fa else TXT2,
            )
        catalog = self._load_model_catalog()
        search_q = ""
        sq = getattr(self, "_model_filter_search", None)
        if sq is not None:
            try:
                search_q = sq.get()
            except Exception:
                search_q = ""
        models_with_status = (
            self._models_with_status(
                catalog, backend, favorites_only=favorites_only, search_query=search_q
            )
            if catalog
            else MODELS
        )
        for i, m in enumerate(models_with_status):
            r = i // 2
            c = i % 2
            card, action_btn = self._create_model_card(inner, m)
            card.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            if action_btn is not None:
                Tooltip(card, content_builder=lambda tw, mdl=m: self._build_model_tooltip_content(tw, mdl), bind_widgets=[action_btn])

    def _model_tooltip_text(self, m):
        """Build multi-line tooltip text from catalog entry (fallback)."""
        lines = []
        desc = (m.get("description") or "").strip() or self._recommended_model_comment(m)
        if desc:
            lines.append(desc)
        if m.get("size_hint"):
            lines.append(f"Size: {m['size_hint']}")
        if m.get("languages") is not None:
            lang_tip = m.get("languages_tooltip") or ""
            if lang_tip:
                lines.append(f"Languages ({m['languages']}): {lang_tip}")
            else:
                lines.append(f"Languages: {m['languages']}")
        if m.get("popularity"):
            lines.append(f"Popularity: {m['popularity']}")
        if m.get("backends"):
            lines.append("Backends: " + ", ".join(m["backends"]))
        return "\n".join(lines) if lines else ""

    def _build_model_tooltip_content(self, tw, m):
        """Build rich tooltip: two-column layout (label grey, value white)."""
        inner = tk.Frame(tw, bg=CARD, highlightbackground="#3A3A42", highlightthickness=1)
        inner.pack(padx=1, pady=1, fill=tk.BOTH, expand=True)
        inner.grid_columnconfigure(1, weight=1)
        padx, pady = 14, 10
        row = 0

        def add_row(label_text, value_text, value_wraplength=220):
            nonlocal row
            py = (pady, 3) if row == 0 else (0, 3)
            lbl = tk.Label(inner, text=label_text + ":", font=("Segoe UI", 10), bg=CARD, fg=TXT2, anchor="w")
            lbl.grid(row=row, column=0, sticky="nw", padx=(padx, 12), pady=py)
            val = tk.Label(inner, text=str(value_text), font=("Segoe UI", 11), bg=CARD, fg=TXT, anchor="w", justify=tk.LEFT, wraplength=value_wraplength)
            val.grid(row=row, column=1, sticky="w", padx=(0, padx), pady=py)
            row += 1

        def _fmt_bool(v):
            if v is True or (isinstance(v, str) and v.lower() in ("true", "yes", "1")):
                val = s("common.yes", default="Yes")
                return val
            val = s("common.no", default="No")
            return val

        def _row_if(label, value, fmt=None):
            if value is not None and value != "":
                add_row(label, fmt(value) if fmt else value)

        def _tl(key, default):
            return s(f"settings.recommended_models.tooltip_labels.{key}", default=default)

        add_row(_tl("name", "Name"), m.get("name") or "?")
        _row_if(_tl("author", "Author"), m.get("author"))
        _row_if(_tl("family", "Family"), m.get("family"))
        _row_if(_tl("params", "Params"), m.get("params"))
        _row_if(_tl("quant", "Quant"), m.get("quant"))
        if "thinking" in m:
            add_row(_tl("thinking", "Thinking"), _fmt_bool(m.get("thinking")))
        if "uncensored" in m:
            add_row(_tl("uncensored", "Uncensored"), _fmt_bool(m.get("uncensored")))
        _row_if(_tl("languages", "Languages"), m.get("languages"))
        _row_if(_tl("size", "Size"), m.get("size_hint"))
        _row_if(_tl("speed", "Speed"), m.get("speed"))
        if m.get("stars") is not None:
            n = min(3, max(0, int(m.get("stars"))))
            add_row(_tl("favorite", "Favorite"), "⭐" * n if n else "—")
        _row_if(_tl("comment", "Comment"), self._recommended_model_comment(m))
        if m.get("good_for_qa"):
            add_row(_tl("alt_a_qa", "Alt+A QA"), s("common.yes", default="Yes"))
        _row_if(_tl("popularity", "Popularity"), m.get("popularity"))

    def _resolve_model_icon_path(self, icon_file: str) -> Optional[Path]:
        """Resolve icon_file (e.g. 'Gemma' or 'Gemma.png') to a path in App/assets/model-icons/. Case-insensitive."""
        if not icon_file or not getattr(self, "paths", None):
            return None
        icons_dir = self.paths.app_dir / "assets" / "model-icons"
        if not icons_dir.exists():
            return None
        base = icon_file if icon_file.lower().endswith(".png") else f"{icon_file}.png"
        path = icons_dir / base
        if path.exists():
            return path
        stem = Path(base).stem.lower()
        for f in icons_dir.iterdir():
            if f.suffix.lower() == ".png" and f.stem.lower() == stem:
                return f
        return None

    def _create_model_card(self, parent, m):
        card = CTkFrame(parent, fg_color=SIDEBAR, corner_radius=8, border_width=1, border_color="#3A3A42")
        card.grid_columnconfigure(1, weight=1)

        top_f = CTkFrame(card, fg_color="transparent")
        top_f.pack(fill="x", padx=15, pady=(15, 0))
        top_f.grid_columnconfigure(1, weight=1)

        letter = m.get("icon") or m.get("letter") or "?"
        color = m.get("color") or ACCENT
        icon_path = self._resolve_model_icon_path(m.get("icon_file") or "")
        if icon_path and HAS_PIL:
            try:
                pil_img = Image.open(icon_path).convert("RGBA")
                img = CTkImage(light_image=pil_img, dark_image=pil_img, size=(46, 46))
                icon = CTkLabel(top_f, text="", image=img)
                icon.image_ref = img
                icon.grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=0, sticky="nw")
            except Exception:
                icon = CTkButton(top_f, text=letter, width=46, height=46, corner_radius=10,
                                 fg_color=color, hover_color=color,
                                 font=("Segoe UI", 22, "bold"), text_color="white", state="disabled")
                icon.grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=0, sticky="nw")
        else:
            icon = CTkButton(top_f, text=letter, width=46, height=46, corner_radius=10,
                             fg_color=color, hover_color=color,
                             font=("Segoe UI", 22, "bold"), text_color="white", state="disabled")
            icon.grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=0, sticky="nw")

        txt_f = CTkFrame(top_f, fg_color="transparent")
        txt_f.grid(row=0, column=1, sticky="nsew")
        txt_f.grid_columnconfigure(0, weight=1)
        name = m.get("name", "?")
        name_lbl = CTkLabel(txt_f, text=name, font=("Segoe UI", 12, "bold"), text_color=TXT, anchor="w", wraplength=160, justify="left")
        name_lbl.grid(row=0, column=0, sticky="w")
        row2 = CTkFrame(txt_f, fg_color="transparent")
        row2.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        row2.grid_columnconfigure(0, weight=1)
        sub = m.get("params") or m.get("desc") or ""
        if sub:
            CTkLabel(row2, text=sub, font=("Segoe UI", 12), text_color=TXT).pack(side="left")
        stars_val = m.get("stars")
        if stars_val is not None and isinstance(stars_val, (int, float)):
            n = min(3, max(0, int(stars_val)))
            stars_str = "⭐" * n
            if stars_str:
                CTkLabel(row2, text=stars_str, font=("Segoe UI", 14), text_color=GOLD).pack(side="right")
        def _model_card_wraplength(_e=None, lbl=name_lbl, c=card):
            w = c.winfo_width() - 100
            if w > 80:
                lbl.configure(wraplength=max(80, w))
        card.bind("<Configure>", _model_card_wraplength)
        card.after(50, lambda: _model_card_wraplength(None))
        # Sub-scroll binding on card and key children, same pattern as Appearance/Finalized.
        for w in (card, top_f, txt_f, row2, name_lbl):
            try:
                w.bind("<MouseWheel>", self._on_models_area_wheel)
            except Exception:
                pass

        spacer = CTkFrame(card, fg_color="transparent", height=5)
        spacer.pack(fill="x")
        spacer.pack_propagate(False)

        bot_f = CTkFrame(card, fg_color="transparent")
        bot_f.pack(fill="x", padx=15, pady=(0, 15))
        
        # --- LOGIQUE DES 4 ETATS ---
        status = m.get("status", "get")
        action_btn = None

        if status == "progress":
            # Barre de progression (PIL → CTkImage). Référence gardée pour mise à jour sans refaire la grille.
            pct = m.get("pct", 0)
            pil_prog = create_progress_img(250, 32, pct)
            if pil_prog:
                prog_img = CTkImage(light_image=pil_prog, dark_image=pil_prog, size=(250, 32))
                prog_lbl = CTkLabel(bot_f, text="", image=prog_img, height=32)
                prog_lbl.image_ref = prog_img
                prog_lbl.pack(fill="x")
                self._progress_card_prog_lbl = prog_lbl
                self._progress_card_prog_img_ref = prog_img
            
        elif status == "select":
            btn = CTkButton(bot_f, text=s("settings.appearance.select"), height=32, corner_radius=6,
                            fg_color=INPUT, hover_color=SEL_BG,
                            font=("Segoe UI", 14, "bold"), text_color="white",
                            command=lambda e=m: self._select_model(e))
            btn.pack(fill="x")
            action_btn = btn
            
        elif status == "current":
            btn = CTkButton(bot_f, text=s("settings.recommended_models.current_model"), height=32, corner_radius=6, 
                            fg_color=INPUT, hover_color=INPUT, 
                            font=("Segoe UI", 14, "bold"), text_color=MUTED, state="disabled")
            btn.pack(fill="x")
            
        else:  # "get" — téléchargement si catalogue (repo_id + filename)
            cmd = None
            if m.get("repo_id") and m.get("filename"):
                cmd = lambda e=m: self._start_download(e)
            btn = CTkButton(bot_f, text=s("settings.recommended_models.get"), height=32, corner_radius=6,
                            fg_color=GREEN_BT, hover_color=GREEN_HV,
                            font=("Segoe UI", 14, "bold"), text_color="white",
                            command=cmd)
            btn.pack(fill="x")
            action_btn = btn

        return card, action_btn

    def _is_widget_under_models_area(self, widget):
        """True si widget est inner_models ou un de ses descendants."""
        inner = getattr(self, "inner_models", None)
        if not inner:
            return False
        w = widget
        while w:
            if w == inner:
                return True
            try:
                w = w.master
            except Exception:
                break
        return False

    def _on_models_area_wheel(self, event):
        """Roulette sur Recommended Models : scroll de la zone d'abord, puis page en butée."""
        inner = getattr(self, "inner_models", None)
        if not inner:
            return
        canvas = getattr(inner, "_parent_canvas", None)
        if not canvas:
            return
        step = 40
        y0, y1 = canvas.yview()
        at_top = y0 <= 0.0
        at_bottom = y1 >= 1.0
        going_up = event.delta > 0
        going_down = event.delta < 0
        if (going_up and at_top) or (going_down and at_bottom):
            return
        if going_up and not at_top:
            canvas.yview("scroll", -step, "units")
            return "break"
        if going_down and not at_bottom:
            canvas.yview("scroll", step, "units")
            return "break"

    def _first_run_maybe_download_default_llm(self):
        """Si aucun .gguf et pas déjà traité, lance hf_hub_download du modèle par défaut (YAML + PERKYSUE_BACKEND + VRAM)."""
        try:
            if not getattr(self, "orch", None):
                return
            if list(self.paths.models_llm.glob("*.gguf")):
                return
            done = self.paths.configs / "first_run_llm.done"
            if done.is_file():
                return
            from utils.installer_default_model import resolve_default_hf_entry

            entry = resolve_default_hf_entry(self.paths)
            if not entry:
                return
            self._first_run_llm_download_active = True
            self._first_run_llm_entry = entry
            self._start_download(entry)
        except Exception:
            pass

    def _start_download(self, entry):
        """Lance le téléchargement du modèle en arrière-plan et affiche la barre de progression."""
        Tooltip.hide_current()
        repo_id = entry.get("repo_id")
        filename = entry.get("filename")
        if not repo_id or not filename:
            return
        models_dir = str(self.paths.models_llm)
        widget = self
        last_refresh = [0.0]  # throttle: dernier refresh (thread-safe via list)

        try:
            from tqdm.auto import tqdm
        except ImportError:
            tqdm = None

        class ProgressTqdm(tqdm if tqdm else object):
            """tqdm qui met à jour la barre dans la GUI. Throttle ~4 FPS pour éviter freeze + Fail to allocate bitmap."""
            def __init__(self, *args, **kwargs):
                kwargs.pop("name", None)
                if tqdm:
                    super().__init__(*args, **kwargs)
            def update(self, n=1):
                if tqdm:
                    super().update(n)
                try:
                    pct = 100 * self.n / self.total if self.total else 0
                    widget._download_pct = min(100, pct)
                    now = time.time()
                    if now - last_refresh[0] >= 0.25:
                        last_refresh[0] = now
                        pct_int = int(widget._download_pct)
                        name = (widget._downloading_entry or {}).get("name") or "model"
                        widget.root.after(0, lambda: widget._update_download_progress_ui(pct_int, name))
                except Exception:
                    pass

        self._downloading_entry = dict(entry)
        self._download_pct = 0
        self.root.after(0, self._refresh_models_grid)
        name = entry.get("name") or "model"
        self._set_header_title_text(self._get_alert("regular.download_progress", name=name, pct=0))

        def do_download():
            err_msg = None
            try:
                from huggingface_hub import hf_hub_download
                kwargs = dict(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=models_dir,
                )
                if tqdm is not None:
                    kwargs["tqdm_class"] = ProgressTqdm
                hf_hub_download(**kwargs)
            except Exception as err:
                err_msg = str(err)
            finally:
                widget._downloading_entry = None
                widget._download_pct = 0
                widget.root.after(0, lambda e=err_msg: widget._on_download_done(e))

        threading.Thread(target=do_download, daemon=True).start()

    def _update_download_progress_ui(self, pct_int: int, name: str):
        """Met à jour uniquement le titre du header et la barre de progression de la carte (pas de refresh grille = pas de flash)."""
        self._set_header_title_text(self._get_alert("regular.download_progress", name=name, pct=pct_int))
        lbl = getattr(self, "_progress_card_prog_lbl", None)
        if lbl is not None:
            try:
                if lbl.winfo_exists():
                    pil_prog = create_progress_img(250, 32, pct_int)
                    if pil_prog:
                        new_img = CTkImage(light_image=pil_prog, dark_image=pil_prog, size=(250, 32))
                        self._progress_card_prog_img_ref = new_img
                        lbl.configure(image=new_img)
            except (tk.TclError, AttributeError):
                pass

    def _on_download_done(self, error_msg):
        """Rafraîchit la grille après téléchargement. Notification succès à la place du titre puis restauration après 4 s."""
        if error_msg:
            self._set_header_title_text(self._hdr_normal_text)
            try:
                from tkinter import messagebox
                messagebox.showerror("Download failed", error_msg, parent=self.root)
            except Exception:
                pass
            self._first_run_llm_download_active = False
            self._first_run_llm_entry = None
        else:
            self._set_header_title_text(self._get_alert("regular.download_success"))
            self.root.after(4000, lambda: self._set_header_title_text(self._hdr_normal_text))
            if getattr(self, "_first_run_llm_download_active", False) and getattr(self, "_first_run_llm_entry", None):
                self._first_run_llm_download_active = False
                ent = self._first_run_llm_entry or {}
                self._first_run_llm_entry = None
                fn = (ent.get("filename") or "").strip()
                if fn and getattr(self, "orch", None):
                    try:
                        if "llm" not in self.cfg:
                            self.cfg["llm"] = {}
                        self.cfg["llm"]["model"] = fn
                        self._save_config({"llm": {"model": fn}})
                        ok, msg = self.orch.reload_llm_runtime()
                        if ok:
                            self._notify(msg, restore_after_ms=3000)
                        else:
                            self._notify(msg, restore_after_ms=5000, blink_times=2, blink_on_ms=300, blink_off_ms=300)
                    except Exception:
                        pass
                try:
                    self.paths.configs.mkdir(parents=True, exist_ok=True)
                    (self.paths.configs / "first_run_llm.done").write_text("ok\n", encoding="utf-8")
                except Exception:
                    pass
        self._refresh_models_grid()

    def _select_model(self, entry):
        """Enregistre le modèle choisi en config, met à jour le dropdown Performance, affiche Save & Restart.
        Rafraîchit la grille des modèles pour que seul le nouveau soit affiché « Current » et l’ancien repasse en « Select »."""
        fn = entry.get("filename") or ""
        if "llm" not in self.cfg:
            self.cfg["llm"] = {}
        self.cfg["llm"]["model"] = fn
        if getattr(self, "_perf_llm", None):
            self._perf_llm.set(fn)
        self._trigger_save()
        self.root.after(0, self._refresh_models_grid)
        self._notify(self._get_alert("critical.save_restart"), restore_after_ms=4000, blink_times=3, blink_on_ms=300, blink_off_ms=300)

    def _trigger_save(self, scroll_to_bottom: bool = True):
        """Affiche le bouton Save & Restart dans la sidebar.
        Si scroll_to_bottom=False, évite un mouvement/relayout violent lors de clics (ex: plan cards).
        """
        try:
            updates = self._collect_settings_updates()
            if self._is_hot_reload_settings_change(updates):
                self._save_btn.configure(
                    text=s("settings.update_button", default="Update"),
                    command=self._on_apply_hot_reload,
                )
                self._save_note.configure(
                    text=s("settings.update_note", default="Apply now (no restart)")
                )
            else:
                self._save_btn.configure(text=s("settings.save_restart"), command=self._on_save_restart)
                self._save_note.configure(text=s("settings.save_sidebar_note"))
        except Exception:
            self._save_btn.configure(text=s("settings.save_restart"), command=self._on_save_restart)
            self._save_note.configure(text=s("settings.save_sidebar_note"))
        self._save_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        if not scroll_to_bottom:
            return
        try:
            c = getattr(self._sidebar_scroll, "_parent_canvas", None)
            if c:
                self.root.after(150, lambda: c.yview_moveto(1.0))
        except Exception:
            pass

    def _filter_skin_list(self):
        """Retourne la liste des skins filtrée par _skin_filter_lang (all = tous)."""
        if not getattr(self, "_skin_list_all", None):
            return [{"id": "Default", "lang": None, "name": s("settings.appearance.default_skin"), "unlocked": True}]
        lang = getattr(self, "_skin_filter_lang", tk.StringVar(value="all")).get()
        if lang == "all":
            return list(self._skin_list_all)
        return [
            sk
            for sk in self._skin_list_all
            if sk.get("id") == "Default" or skin_locale_codes_match(sk.get("lang") or "", lang)
        ]

    def _on_skin_filter(self, lang_id: str):
        """Change le filtre langue et reconstruit la grille des skins."""
        self._skin_filter_lang.set(lang_id)
        for lid, btn in getattr(self, "_skin_filter_buttons", []):
            is_active = (lid == lang_id)
            btn.configure(fg_color=SEL_BG if is_active else INPUT, text_color=TXT if is_active else TXT2)
        self._skin_list_filtered = self._filter_skin_list()
        self._build_skin_grid(self._effective_skin())

    def _build_skin_grid(self, current_skin: str):
        """Construit ou reconstruit la grille des skins dans inner_skin (scrollable)."""
        for w in getattr(self.inner_skin, "winfo_children", lambda: [])():
            w.destroy()
        self._skin_btns.clear()
        self._skin_cols.clear()
        filtered = getattr(self, "_skin_list_filtered", [])
        if not filtered:
            filtered = [{"id": "Default", "lang": None, "name": s("settings.appearance.default_skin"), "unlocked": True}]
        _default_skin_label = s("settings.appearance.default_skin")
        for i, skin in enumerate(filtered):
            skin_id = skin["id"]
            unlocked = skin.get("unlocked", True)
            display_name = skin.get("name", skin_id)
            lang = skin.get("lang")
            display_with_lang = _default_skin_label if skin_id == "Default" else (f"{display_name} ({lang.lower()})" if lang else display_name)
            is_sel = (skin_id == current_skin) or (current_skin and display_name == current_skin and skin_id != "Default")
            img_path = get_avatar_path(skin_id, paths=self.paths)
            show_lock = not unlocked and skin_id != "Default"
            row, col = i // 3, i % 3
            # Pas de bordure sur la cellule : la bordure dorée est uniquement sur la photo (create_avatar_circle).
            c = CTkFrame(self.inner_skin, fg_color="transparent", cursor="hand2")
            c.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            self._skin_cols[skin_id] = c
            lbl_img = CTkLabel(c, text="", cursor="hand2")
            lbl_img.pack()
            dn = display_with_lang or display_name or skin_id
            # Texte sous l’avatar : pas de "(Selected)" pour éviter le shift des colonnes au clic (sélection = bordure + couleur).
            lbl_txt = dn if unlocked else f"🔒 {dn}"
            name_color = SKIN_SELECTED_BORDER if is_sel else (TXT if unlocked else TXT2)
            name_lbl = CTkLabel(c, text=lbl_txt, font=("Segoe UI", 13), text_color=name_color, cursor="hand2")
            name_lbl.pack(pady=(2, 0))
            self._skin_btns[skin_id] = {
                "lbl": lbl_img,
                "is_sel": is_sel,
                "path": img_path,
                "locked": not unlocked,
                "name_lbl": name_lbl,
                "display_name": display_name,
                "display_with_lang": display_with_lang,
            }
            # Clic sur toute la cellule (frame + image + label) = sélection du skin.
            c.bind("<Button-1>", lambda e, sid=skin_id: self._on_skin_click(sid))
            for child in (lbl_img, name_lbl):
                child.bind("<Button-1>", lambda e, sid=skin_id: self._on_skin_click(sid))
            # Molette sur image/label/cellule : gérer le scroll Appearance et bloquer la propagation
            # (sinon la molette sur une photo déclenche aussi le scroll de la page).
            for w in (c, lbl_img, name_lbl):
                w.bind("<MouseWheel>", self._on_skin_area_wheel)
        # Espace en bas pour que le titre du dernier skin (ex. "Mike (fr) (Selected)") ne soit pas coupé par la marge
        num_rows = (len(filtered) + 2) // 3
        bottom_spacer = CTkFrame(self.inner_skin, fg_color="transparent", height=40)
        bottom_spacer.grid(row=num_rows, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        bottom_spacer.grid_propagate(False)
        size = getattr(self, "_last_skin_size", 120)
        for skin_id, data in self._skin_btns.items():
            color = SKIN_SELECTED_BORDER if data["is_sel"] else "#52525B"
            new_img = create_avatar_circle(size, color, 0, is_main=False, img_path=data["path"], show_lock=data["locked"])
            data["lbl"].configure(image=new_img)

    def _on_skin_click(self, skin_id: str):
        """Clic sur un skin : si locké → Patreon ; sinon sauvegarde + mise à jour immédiate (pas de restart)."""
        if not getattr(self, "_skin_btns", None) or skin_id not in self._skin_btns:
            return
        data = self._skin_btns[skin_id]
        if data.get("locked"):
            webbrowser.open("https://patreon.com/PerkySue")
            return
        self._save_config({"skin": {"active": skin_id}})
        self.cfg = self._load_cfg()
        orch = getattr(self, "orch", None)
        if orch and isinstance(getattr(orch, "config", None), dict):
            orch.config.setdefault("skin", {})["active"] = skin_id
        if orch and hasattr(self.orch, "sound_manager") and self.orch.sound_manager:
            self.orch.sound_manager.set_skin(skin_id)
            self.orch.sound_manager.play_stt_start()
        tm = getattr(getattr(self, "orch", None), "tts_manager", None)
        if tm:
            tm.on_skin_changed(skin_id)
        main_path = get_avatar_path(skin_id, paths=self.paths)
        _, _, status_color = _status_tuple(getattr(self, "_status_id", "ready"))
        _ring = int(round(float(getattr(self, "_main_avatar_ring_offset_smooth", 0.0) or 0.0)))
        _ring = max(-9, min(9, _ring))
        new_main = create_avatar_circle(180, "", 0, is_main=True, img_path=main_path, accent_color=status_color, ring_offset_px=_ring)
        self._main_avatar_label.configure(image=new_main)
        self.main_avatar_img = new_main
        for sid, d in self._skin_btns.items():
            d["is_sel"] = (sid == skin_id)
            try:
                if d.get("name_lbl"):
                    dn = d.get("display_with_lang") or d.get("display_name") or sid
                    d["name_lbl"].configure(
                        text=dn if not d.get("locked") else f"🔒 {dn}",
                        text_color=SKIN_SELECTED_BORDER if d["is_sel"] else (TXT if not d.get("locked") else TXT2),
                    )
            except Exception:
                pass
        size = getattr(self, "_last_skin_size", 120)
        for sid, d in self._skin_btns.items():
            color = SKIN_SELECTED_BORDER if d["is_sel"] else "#52525B"
            new_img = create_avatar_circle(size, color, 0, is_main=False, img_path=d["path"], show_lock=d.get("locked", False))
            d["lbl"].configure(image=new_img)

    def _is_widget_under_skin_area(self, widget):
        """True si widget est inner_skin ou un de ses descendants."""
        inner = getattr(self, "inner_skin", None)
        if not inner:
            return False
        w = widget
        while w:
            if w == inner:
                return True
            try:
                w = w.master
            except Exception:
                break
        return False

    def _skin_scrollregion_update(self):
        """Force la mise à jour du scrollregion du canvas Appearance après build de la grille."""
        try:
            canvas = getattr(self.inner_skin, "_parent_canvas", None)
            if canvas:
                canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _on_skin_area_wheel(self, event):
        """Roulette sur la zone skins : scroll rapide (40-120 u)."""
        canvas = getattr(self.inner_skin, "_parent_canvas", None)
        if not canvas:
            return
        # Step réduit pour un défilement plus fluide.
        step = 40
        delta = -step if (event.delta > 0) else step
        y0, y1 = canvas.yview()
        at_top = y0 <= 0.0
        at_bottom = y1 >= 1.0
        going_up = event.delta > 0
        going_down = event.delta < 0

        # Si on est déjà en haut et qu'on scrolle vers le haut, ou déjà en bas et qu'on scrolle vers le bas,
        # on ne consomme PAS l'événement : le scroll parent pourra prendre le relais.
        if (going_up and at_top) or (going_down and at_bottom):
            return

        # Sinon, on scrolle la zone skins et on consomme l'événement.
        if going_up and not at_top:
            canvas.yview("scroll", -step, "units")
            return "break"
        if going_down and not at_bottom:
            canvas.yview("scroll", step, "units")
            return "break"

    def _is_widget_under_finalized_logs_area(self, widget):
        """True si widget est _console_finalized_inner ou un de ses descendants."""
        inner = getattr(self, "_console_finalized_inner", None)
        if not inner:
            return False
        w = widget
        while w:
            if w == inner:
                return True
            try:
                w = w.master
            except Exception:
                break
        return False

    def _on_finalized_logs_wheel(self, event):
        """Roulette sur Finalized / Temporary Logs : scroll de la section d'abord, puis page en butée (comme Appearance)."""
        inner = getattr(self, "_console_finalized_inner", None)
        if not inner:
            return
        canvas = getattr(inner, "_parent_canvas", None)
        if not canvas:
            return
        step = 40
        y0, y1 = canvas.yview()
        at_top = y0 <= 0.0
        at_bottom = y1 >= 1.0
        going_up = event.delta > 0
        going_down = event.delta < 0
        if (going_up and at_top) or (going_down and at_bottom):
            return
        if going_up and not at_top:
            canvas.yview("scroll", -step, "units")
            return "break"
        if going_down and not at_bottom:
            canvas.yview("scroll", step, "units")
            return "break"

    def _on_skin_resize(self, event):
        col_width = event.width / 3
        new_size = int(col_width * 0.85)
        new_size = max(100, min(new_size, 175))
        
        current_size = getattr(self, "_last_skin_size", 0)
        if abs(new_size - current_size) < 2:
            return
            
        self._last_skin_size = new_size
        for sn, data in self._skin_btns.items():
            color = SKIN_SELECTED_BORDER if data["is_sel"] else "#52525B"
            new_img = create_avatar_circle(new_size, color, 0, is_main=False, img_path=data["path"], show_lock=data.get("locked", False))
            data["lbl"].configure(image=new_img)

    # ── FOOTER (mockup: GitHub + Beta) ─────────────────────────
    def _build_footer(self):
        ft = CTkFrame(self.root, height=44, fg_color=INPUT, corner_radius=0)
        self._footer_frame = ft
        ft.pack(fill="x", side="bottom")
        ft.pack_propagate(False)
        ft.grid_columnconfigure(2, weight=1)

        github_img = None
        discord_img = None
        max_logo_h = 24  # max height so logos stay small and keep aspect ratio

        def _logo_image(path, max_h=max_logo_h):
            if not HAS_PIL or not path or not path.exists():
                return None
            try:
                pil = Image.open(str(path)).convert("RGBA")
                w, h = pil.size
                if h <= 0:
                    return None
                scale = min(1.0, max_h / h)
                new_w = max(16, int(w * scale))
                new_h = max(16, int(h * scale))
                if (new_w, new_h) != (w, h):
                    pil = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                return CTkImage(light_image=pil, dark_image=pil, size=(new_w, new_h))
            except Exception:
                return None

        assets_dir = getattr(self, "paths", None) and (self.paths.app_dir / "assets")
        if assets_dir:
            github_img = _logo_image(assets_dir / "GitHub.png")
            discord_img = _logo_image(assets_dir / "Discord.png")

        github_btn = CTkButton(
            ft, text=f"  {s('common.footer.github')}" if not github_img else "", image=github_img if github_img else None,
            font=("Segoe UI", 12), fg_color=SIDEBAR, hover_color=SEL_BG,
            height=32, corner_radius=8, anchor="center",
            command=lambda: webbrowser.open("https://github.com/PerkySue/PerkySue"),
        )
        if github_img:
            github_btn.image_ref = github_img
        github_btn.grid(row=0, column=0, padx=(20, 8), pady=6, sticky="w")

        discord_btn = CTkButton(
            ft, text=f"  {s('common.footer.discord')}" if not discord_img else "", image=discord_img if discord_img else None,
            font=("Segoe UI", 12), fg_color=SIDEBAR, hover_color=SEL_BG,
            height=32, corner_radius=8, anchor="center",
            command=lambda: webbrowser.open("https://discord.gg/UaJHEzFgXy"),
        )
        if discord_img:
            discord_btn.image_ref = discord_img
        discord_btn.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")

        self._footer_tagline_lbl = CTkLabel(
            ft, text=s("common.footer.alpha_banner"),
            font=("Segoe UI", 11), text_color=MUTED,
        )
        self._footer_tagline_lbl.grid(row=0, column=2, padx=(0, 20), pady=6, sticky="e")
        try:
            self._refresh_footer_update_link()
        except Exception:
            pass

    # ── Updates (GitHub) ─────────────────────────────────────
    def _open_update_wizard(self):
        """Check GitHub releases, optionally download App/ update, then offer restart.

        UI must match the Plan Management wizard style (link subscription / trial).
        """
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "check_updates_from_github"):
            self._notify("Update check unavailable.", restore_after_ms=3500)
            return

        if getattr(self, "_update_wizard_dlg", None):
            try:
                if self._update_wizard_dlg.winfo_exists():
                    self._update_wizard_dlg.deiconify()
                    _center_dialog_on_root(self._update_wizard_dlg)
                    self._update_wizard_dlg.lift()
                    try:
                        self._update_wizard_dlg.focus_force()
                    except Exception:
                        pass
                    return
            except Exception:
                self._update_wizard_dlg = None

        dlg = CTkToplevel(self.root)
        self._update_wizard_dlg = dlg
        dlg.title(s("about.updates.wizard_title", default="Update"))
        dlg.geometry("440x310")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        try:
            dlg.configure(fg_color=BG)
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

        def _close():
            try:
                dlg.destroy()
            except Exception:
                pass
            self._update_wizard_dlg = None

        # Plan-wizard shell style
        link_gold = SKIN_SELECTED_BORDER
        inner_pad = 16
        content_pad_top = inner_pad + 5
        shell = CTkFrame(dlg, fg_color=CARD, corner_radius=18, border_width=2, border_color=link_gold)
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        content = CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=inner_pad, pady=(content_pad_top, inner_pad))

        headline_lbl = CTkLabel(
            content,
            text=s("about.updates.title", default="Updates"),
            font=("Segoe UI", 20, "bold"),
            text_color=TXT,
            anchor="center",
            justify="center",
        )
        headline_lbl.pack(fill="x", pady=(0, 10))

        body = CTkLabel(
            content,
            text=s("about.updates.body_checking", default="Checking GitHub releases…"),
            font=("Segoe UI", 13, "bold"),
            text_color=TXT,
            justify="center",
            anchor="center",
            wraplength=404,
        )
        body.pack(fill="x", pady=(0, 10))

        prog = CTkProgressBar(content, height=10, corner_radius=6)
        prog.pack(fill="x", pady=(0, 12))
        prog.set(0)

        status_lbl = CTkLabel(
            content,
            text="",
            font=("Segoe UI", 12),
            text_color="#F87171",
            wraplength=404,
            justify="center",
            anchor="center",
        )
        status_lbl.pack(fill="x", pady=(0, 8))

        btn_row = CTkFrame(content, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        cancel_btn = CTkButton(
            btn_row,
            text=s("about.updates.btn_cancel", default="Cancel"),
            font=("Segoe UI", 13, "bold"),
            fg_color=INPUT,
            hover_color=SEL_BG,
            height=40,
            corner_radius=10,
            command=_close,
        )
        cancel_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        action_btn = CTkButton(
            btn_row,
            text=s("about.updates.btn_check", default="Check for updates"),
            font=("Segoe UI", 13, "bold"),
            fg_color=link_gold,
            hover_color="#d9a60f",
            text_color="#1a1a1a",
            height=40,
            corner_radius=10,
        )
        action_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        state = {"latest": None}

        def _ui_progress(pct: float, txt: str = ""):
            try:
                prog.set(max(0.0, min(1.0, float(pct))))
            except Exception:
                pass
            if txt:
                try:
                    body.configure(text=txt)
                except Exception:
                    pass

        def _apply_info(info: dict):
            state["latest"] = info
            if info.get("update_available"):
                prog.set(1.0)
                body.configure(text=s("about.updates.body_available", default="New update available: {v}").format(v=info.get("latest_version", "")))
                action_btn.configure(text=s("about.updates.btn_update", default="Update"), command=_start_update, state="normal")
            else:
                prog.set(1.0)
                body.configure(text=s("about.updates.body_uptodate", default="You’re up to date ({v}).").format(v=info.get("current_version", "")))
                action_btn.configure(text=s("about.updates.btn_close", default="Close"), command=_close, state="normal")
            try:
                self._apply_update_info_to_ui(info)
            except Exception:
                pass

        def _kick_check():
            action_btn.configure(state="disabled")
            prog.set(0.15)
            body.configure(text=s("about.updates.body_checking", default="Checking GitHub releases…"))
            try:
                status_lbl.configure(text="")
            except Exception:
                pass

            def _run():
                try:
                    info = orch.check_updates_from_github()
                except Exception as e:
                    info = {"error": str(e)}

                def _post():
                    if info.get("error"):
                        prog.set(0)
                        body.configure(text=s("about.updates.body_check_failed", default="Could not check updates."))
                        try:
                            status_lbl.configure(text=str(info.get("error") or ""), text_color="#F87171")
                        except Exception:
                            pass
                        action_btn.configure(text=s("about.updates.btn_retry", default="Retry"), command=_kick_check, state="normal")
                        return
                    _apply_info(info)

                try:
                    self.root.after(0, _post)
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True).start()

        def _start_update():
            info = state.get("latest") or {}
            if not info.get("update_available"):
                _close()
                return
            action_btn.configure(state="disabled")
            cancel_btn.configure(state="disabled")
            prog.set(0.05)
            body.configure(text=s("about.updates.body_downloading", default="Downloading update…"))

            def _run():
                try:
                    ok, msg = orch.download_and_stage_app_update(
                        info,
                        progress_cb=lambda p, t="": self.root.after(0, lambda: _ui_progress(p, t)) if getattr(self, "root", None) else None,
                    )
                except Exception as e:
                    ok, msg = False, str(e)

                def _post():
                    cancel_btn.configure(state="normal")
                    if ok:
                        prog.set(1.0)
                        body.configure(text=msg or s("about.updates.body_ready_restart", default="Update installed. Restart to apply."))
                        action_btn.configure(text=s("about.updates.btn_restart", default="Restart to apply"), command=self._restart_app, state="normal")
                    else:
                        body.configure(text=msg or s("about.updates.body_failed", default="Update failed."))
                        action_btn.configure(text=s("about.updates.btn_update", default="Update"), command=_start_update, state="normal")
                        cancel_btn.configure(state="normal")

                try:
                    self.root.after(0, _post)
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True).start()

        dlg.protocol("WM_DELETE_WINDOW", _close)

        def _center():
            try:
                dlg.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                x = max(20, rx + (rw - dw) // 2)
                y = max(20, ry + 52)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

        try:
            dlg.after(10, _center)
        except Exception:
            _center()

        _kick_check()

    # ── Install ZIP (plugins/skins) ──────────────────────────
    def _default_downloads_dir(self) -> Path:
        """Best-effort Downloads folder (Windows-friendly)."""
        try:
            up = os.environ.get("USERPROFILE")
            if up:
                cand = Path(up) / "Downloads"
                if cand.exists():
                    return cand
        except Exception:
            pass
        try:
            cand = Path.home() / "Downloads"
            if cand.exists():
                return cand
        except Exception:
            pass
        return Path.home()

    def _safe_extract_zip_to_root(self, zip_path: Path, dest_root: Path) -> int:
        """Extract ZIP contents into dest_root, enforcing root-relative paths (no traversal). Returns extracted file count."""
        dest_root = Path(dest_root).resolve()
        extracted = 0

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            infos = zf.infolist()
            if len(infos) > 5000:
                raise ValueError("ZIP contains too many files.")

            total_uncompressed = 0
            for info in infos:
                try:
                    total_uncompressed += int(getattr(info, "file_size", 0) or 0)
                except Exception:
                    pass
            if total_uncompressed > 1024 * 1024 * 800:  # ~800MB safety cap
                raise ValueError("ZIP is too large.")

            for info in infos:
                name = (info.filename or "").replace("\\", "/")
                if not name or name.endswith("/"):
                    continue

                p = PurePosixPath(name)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError(f"Unsafe path in ZIP: {info.filename!r}")

                out_path = (dest_root / Path(*p.parts)).resolve()
                if not str(out_path).startswith(str(dest_root) + os.sep) and out_path != dest_root:
                    raise ValueError(f"Unsafe path in ZIP: {info.filename!r}")

                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1

        return extracted

    def _refresh_skins_after_zip_install(self) -> None:
        """If Settings → Appearance is already built, refresh the skin list/grid."""
        try:
            if not hasattr(self, "inner_skin") or self.inner_skin is None:
                return
            discovered = discover_skins(self.paths)
            self._skin_list_all = [{"id": "Default", "lang": None, "name": s("settings.appearance.default_skin"), "unlocked": True}] + discovered
            self._skin_list_filtered = self._filter_skin_list()
            self._build_skin_grid(self._effective_skin())
            try:
                self.root.after(100, self._skin_scrollregion_update)
            except Exception:
                pass
        except Exception:
            pass

    def _about_install_zip_from_downloads(self) -> None:
        """Pick a ZIP (from anywhere) and install it into the portable root (Data/, etc.)."""
        try:
            start_dir = str(self._default_downloads_dir())
        except Exception:
            start_dir = ""

        fp = filedialog.askopenfilename(
            title=s("about.zip_install.dialog_title", default="Select a ZIP to install"),
            initialdir=start_dir or None,
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if not fp:
            return

        try:
            zip_path = Path(fp)
            if not zip_path.exists():
                raise FileNotFoundError("ZIP file not found.")
            if zip_path.suffix.lower() != ".zip":
                raise ValueError("Not a .zip file.")

            dest_root = getattr(self, "paths", None).root if getattr(self, "paths", None) else (Path(__file__).resolve().parent.parent.parent)
            n = self._safe_extract_zip_to_root(zip_path, dest_root)
            self._refresh_skins_after_zip_install()
            self._notify(s("about.zip_install.success", default="Installed successfully ({n} files).").format(n=n), restore_after_ms=4000)
        except Exception as e:
            self._notify(
                s("about.zip_install.failed", default="Install failed: {err}").format(err=str(e)),
                restore_after_ms=6000,
                blink_times=2,
                blink_on_ms=300,
                blink_off_ms=300,
            )

    def _apply_update_info_to_ui(self, info: dict):
        self._latest_update_info = info
        body_lbl = getattr(self, "_about_updates_body", None)
        btn = getattr(self, "_about_updates_btn", None)
        if body_lbl is not None and btn is not None:
            if info.get("update_available"):
                body_lbl.configure(text=s("about.updates.body_available", default="New update available: {v}").format(v=info.get("latest_version", "")))
                btn.configure(text=s("about.updates.btn_update", default="Update"))
            else:
                body_lbl.configure(text=s("about.updates.body_idle", default="Check GitHub for the latest version."))
                btn.configure(text=s("about.updates.btn_check", default="Check for updates"))
        self._refresh_footer_update_link()

    def _refresh_footer_update_link(self):
        lbl = getattr(self, "_footer_tagline_lbl", None)
        if lbl is None:
            return
        info = getattr(self, "_latest_update_info", None) or {}
        if info.get("update_available"):
            v = info.get("latest_version", "")
            txt = s("about.updates.footer_link", default="New update available {v}").format(v=v)
            lbl.configure(text=txt, text_color="white", cursor="hand2")
            try:
                lbl.bind("<Button-1>", lambda _e: self._open_update_wizard())
            except Exception:
                pass
        else:
            lbl.configure(text=s("common.footer.alpha_banner"), text_color=MUTED, cursor="")
            try:
                lbl.unbind("<Button-1>")
            except Exception:
                pass

    def _restart_app(self):
        """Start a new PerkySue process and exit this one (update wizard, post-Stripe hint, etc.)."""
        try:
            stt_device = "auto"
            st = (self.cfg.get("stt") or {}) if isinstance(getattr(self, "cfg", None), dict) else {}
            if isinstance(st, dict):
                d = st.get("device")
                if isinstance(d, str) and d.strip():
                    stt_device = d.strip().lower()
        except Exception:
            stt_device = "auto"
        app_root = Path(__file__).resolve().parent.parent.parent
        main_py = app_root / "App" / "main.py"
        python_exe = app_root / "Python" / "python.exe"
        if not python_exe.exists():
            python_exe = sys.executable
        data_dir = str(self.paths.data.resolve())
        try:
            self.root.destroy()
        except Exception:
            pass
        if stt_device == "cuda" and getattr(self, "_is_nvidia_stt", False):
            install_bat = app_root / "install.bat"
            if install_bat.exists():
                subprocess.Popen(["cmd", "/c", str(install_bat)], cwd=str(app_root), shell=False)
                sys.exit(0)
        subprocess.Popen(
            [str(python_exe), str(main_py), "--data", data_dir],
            cwd=str(app_root),
        )
        sys.exit(0)

    def _maybe_auto_check_updates(self):
        if getattr(self, "_update_auto_checked", False):
            return
        self._update_auto_checked = True
        orch = getattr(self, "orch", None)
        if orch is None or not hasattr(orch, "check_updates_from_github"):
            return

        def _run():
            try:
                info = orch.check_updates_from_github()
            except Exception:
                return

            def _post():
                try:
                    self._apply_update_info_to_ui(info)
                except Exception:
                    pass

            try:
                self.root.after(0, _post)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    # ── PIPELINE STATUS & TRANSCRIPTION CONTROLS — methods ───

    def _poll_resources(self):
        """Polling périodique (3 s) des ressources système pour mettre à jour les barres."""
        if not getattr(self, "_poll_resources_active", False):
            return
        try:
            self._update_resource_bars()
        except Exception:
            pass
        try:
            # Rafraîchissement plus fréquent (≈ ComfyUI) : toutes les 1 seconde.
            self.root.after(1000, self._poll_resources)
        except (tk.TclError, AttributeError):
            pass

    def _update_resource_bars(self):
        """Recalcule les barres CPU/RAM/GPU/VRAM/Temp et met à jour les labels PIL."""
        bars = getattr(self, "_res_bar_labels", None)
        if not bars or len(bars) < 5:
            return

        # CPU / RAM via psutil
        cpu_pct = 0
        ram_pct = 0
        if HAS_PSUTIL:
            try:
                cpu_pct = int(psutil.cpu_percent(interval=None))
                ram_pct = int(psutil.virtual_memory().percent)
            except Exception:
                pass

        # GPU / VRAM / Temp via nvidia-smi
        gpu_pct, vram_pct, temp_c = 0, 0, 0
        nv = _get_nvidia_stats()
        has_gpu = nv is not None
        if nv:
            gpu_pct = nv["gpu_pct"]
            vram_pct = nv["vram_pct"]
            temp_c = nv["temp_c"]

        defs = [
            ("CPU", cpu_pct, "%", False),
            ("RAM", ram_pct, "%", False),
            ("GPU", gpu_pct, "%", False),
            ("VRAM", vram_pct, "%", False),
            ("Temp", temp_c, "°", True),
        ]

        for idx, (label, val, unit, is_temp) in enumerate(defs):
            # Skip GPU bars si pas de GPU NVIDIA
            if not has_gpu and idx >= 2:
                val = 0
            color = _resource_bar_color(label, val, is_temp=is_temp)
            pil_img = create_resource_bar_img(130, 38, val, label, color=color, unit=unit)
            if pil_img:
                tk_img = ImageTk.PhotoImage(pil_img)
                self._res_bar_imgs[idx] = tk_img  # garder la ref
                try:
                    bars[idx].configure(image=tk_img)
                except (tk.TclError, AttributeError):
                    pass

    def _on_start_click(self):
        """Démarre un enregistrement transcription (Alt+T) depuis le GUI."""
        if not self.orch:
            return
        # Empêcher double clic
        try:
            if self.orch._is_recording:
                return
        except Exception:
            pass
        # Lancer dans un thread pour ne pas bloquer le GUI
        def _run():
            try:
                self.orch._on_hotkey_toggle("transcribe")
            except Exception as e:
                logger.error("Start from GUI failed: %s", e)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _on_abort_click(self):
        """Stoppe l'enregistrement ou le processing en cours."""
        if not self.orch:
            return
        try:
            if self.orch.recorder and self.orch.recorder.is_recording:
                self.orch.stop_recording()
                return
        except Exception:
            pass
        try:
            tm = getattr(self.orch, "tts_manager", None)
            st = getattr(self, "_status_id", None)
            if tm and (st == "tts_loading" or tm.is_speaking()):
                tm.stop()
                self.set_status("ready")
                self._notify(self._get_alert("regular.tts_stopped"), restore_after_ms=3000)
                return
        except Exception:
            pass
        try:
            self.orch.request_cancel()
        except Exception:
            pass

    def _on_save_log_click(self):
        """Copie tous les finalized logs dans le presse-papiers."""
        entries = getattr(self, "_console_entries", [])
        if not entries:
            self._notify(self._get_alert("regular.no_logs_to_save"), restore_after_ms=1500)
            return
        eff_free = False
        try:
            if getattr(self, "orch", None) and hasattr(self.orch, "is_effective_pro"):
                eff_free = not bool(self.orch.is_effective_pro())
        except Exception:
            eff_free = False
        lines = []
        for e in entries:
            ts = e.get("timestamp", "")
            kind = "STT" if e.get("type") == "stt" else "LLM"
            shortcut = e.get("shortcut", "")
            mode_id = (e.get("mode_id") or "").strip().lower()
            prefix = f"[{ts}] [{kind}]"
            if shortcut:
                prefix += f" [{shortcut}]"
            txt = (e.get("text") or "").strip()
            # Free tier: do not export any LLM/summary content (avoid cheat), keep STT for bug reports.
            if eff_free and e.get("type") in ("llm", "summary"):
                txt = "⚠️ Locked (Pro) — content hidden in Free tier log."
            lines.append(f"{prefix}  {txt}")
        content = "\n\n".join(lines)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update()
        except (tk.TclError, AttributeError):
            pass
        self._notify(self._get_alert("regular.all_logs_copied"), restore_after_ms=1500)

    # ── Volume equalizer ──────────────────────────────────────

    def _update_volume_display(self):
        """Redessine les barres equalizer sur le canvas volume."""
        c = getattr(self, "_vol_canvas", None)
        if not c:
            return
        try:
            if not c.winfo_exists():
                return
        except tk.TclError:
            return
        c.delete("all")

        # Recalculate actual canvas size (might differ from requested if packed with fill/expand)
        try:
            c.update_idletasks()
            w = c.winfo_width()
            if w < 10:
                w = self._vol_canvas_w
        except Exception:
            w = self._vol_canvas_w
        h = self._vol_canvas_h
        n = self._vol_num_bars
        gap = 2
        bar_w = max(3, (w - (n - 1) * gap) // n)
        level = 0.0 if self._vol_muted else self._vol_level

        for i in range(n):
            frac = (i + 1) / n
            bar_h = max(3, int(h * 0.18 + h * 0.75 * frac))
            x0 = i * (bar_w + gap)
            y0 = h - bar_h
            x1 = x0 + bar_w
            y1 = h - 1

            threshold = frac - (0.5 / n)
            if level >= threshold:
                g_val = min(255, 140 + int(115 * frac))
                fill = f"#{0x00:02x}{g_val:02x}{0x00:02x}"
            else:
                fill = "#3A3A42"
            c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="", width=0)

    def _on_volume_click(self, event):
        """Clic ou drag sur le canvas equalizer → set volume proportionnel à la position X."""
        c = getattr(self, "_vol_canvas", None)
        if not c:
            return
        try:
            w = c.winfo_width()
            if w < 10:
                w = self._vol_canvas_w
        except Exception:
            w = self._vol_canvas_w
        x = event.x
        new_vol = max(0.0, min(1.0, x / w))
        self._vol_level = new_vol
        self._vol_muted = False
        self._vol_mute_btn.configure(text="🔊")
        self._apply_volume(new_vol)
        self._update_volume_display()

    def _on_mute_toggle(self):
        """Toggle mute/unmute."""
        self._vol_muted = not self._vol_muted
        if self._vol_muted:
            self._vol_mute_btn.configure(text="🔇")
            self._apply_volume(0.0)
        else:
            self._vol_mute_btn.configure(text="🔊")
            self._apply_volume(self._vol_level)
        self._update_volume_display()

    def _apply_volume(self, vol):
        """Applique le volume au SoundManager.
        Bug connu : SoundManager.set_volume() appelle mixer.set_volume() qui n'existe pas au niveau module.
        On corrige ici en settant sm.volume + volume sur chaque Sound déjà en cache.
        Pour les sons futurs, on patche aussi _play_file si pas encore fait."""
        try:
            if self.orch and self.orch.sound_manager:
                sm = self.orch.sound_manager
                sm.volume = max(0.0, min(1.0, vol))
                # Appliquer le volume sur chaque objet Sound déjà en cache
                for snd in sm._sound_cache.values():
                    try:
                        snd.set_volume(sm.volume)
                    except Exception:
                        pass
                # Monkey-patch _play_file une seule fois pour appliquer le volume aux futurs sons
                if not getattr(sm, "_volume_patched", False):
                    _orig_play = sm._play_file
                    def _patched_play(sound_file, _orig=_orig_play, _sm=sm):
                        result = _orig(sound_file)
                        # Appliquer le volume sur le son qu'on vient de cacher
                        cached = _sm._sound_cache.get(sound_file)
                        if cached:
                            try:
                                cached.set_volume(_sm.volume)
                            except Exception:
                                pass
                        return result
                    sm._play_file = _patched_play
                    sm._volume_patched = True
        except Exception:
            pass

    def _poll_logs(self):
        # Bound work per timer tick so the Tk thread stays responsive (Windows "Not responding"
        # if a burst of INFO logs arrives while STT/LLM runs on a worker thread).
        _max_lines_per_tick = 120
        try:
            for _ in range(_max_lines_per_tick):
                line = self.log_q.get_nowait()
                self._log_lines.append(line)
                if len(self._log_lines) > 2000:
                    self._log_lines.pop(0)
                if getattr(self, "_console_full_text", None) and getattr(self._console_full_text, "winfo_exists", None) and self._console_full_text.winfo_exists():
                    try:
                        self._console_full_text.configure(state="normal")
                        self._console_full_text.insert("end", line + "\n")
                        self._console_full_text.see("end")
                        self._console_full_text.configure(state="disabled")
                    except (tk.TclError, AttributeError):
                        pass
        except queue.Empty:
            pass
        self.root.after(100, self._poll_logs)

    def run(self):
        self.root.mainloop()

    def stop(self):
        sys.stdout = getattr(self, '_old_out', sys.stdout)
        try: self.root.destroy()
        except: pass

if __name__ == "__main__":
    w = PerkySueWidget()
    w.run()