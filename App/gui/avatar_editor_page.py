"""
Avatar Editor UI (optional plugin page).

Built into the app; shown in the sidebar only when Data/Plugins/avatar_editor is installed
and manifest enabled (see orchestrator._load_avatar_editor_plugin).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tkinter.simpledialog as simpledialog
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING, List, Optional

try:
    from ..utils.strings import s
    from ..utils import avatar_editor_fs as ae
    from ..utils.skin_paths import skins_data_root
except ImportError:
    from App.utils.strings import s
    from App.utils import avatar_editor_fs as ae
    from App.utils.skin_paths import skins_data_root

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import customtkinter as ctk
    from customtkinter import CTkButton, CTkFrame, CTkLabel, CTkScrollableFrame, CTkTextbox, CTkOptionMenu
except ImportError:
    ctk = None  # type: ignore
    CTkButton = CTkFrame = CTkLabel = CTkScrollableFrame = CTkTextbox = CTkOptionMenu = None  # type: ignore

if TYPE_CHECKING:
    from .widget import PerkySueWidget

logger = logging.getLogger("perkysue.gui.avatar_editor")

# Colors aligned with gui/widget.py (avoid circular import)
CARD = "#2D2D35"
TXT = "#FFFFFF"
TXT2 = "#A1A1AA"
MUTED = "#71717A"
SEL_BG = "#3F3F46"
ACCENT = "#8B5CF6"
GREEN_BT = "#22C55E"


class AvatarEditorPage:
    def __init__(self, widget: "PerkySueWidget"):
        self.widget = widget
        self._pg: Optional[CTkScrollableFrame] = None
        self._list_host: Optional[CTkFrame] = None
        self._edit_host: Optional[CTkFrame] = None
        self._cards_body: Optional[CTkFrame] = None
        self._edit_char_dir: Optional[Path] = None
        self._edit_personality_path: Optional[Path] = None
        self._personality_menu: Optional[CTkOptionMenu] = None
        self._personality_text: Optional[CTkTextbox] = None
        self._voice_locale_var: Optional[ctk.StringVar] = None  # type: ignore

    def _lbl(self, parent, text: str, **kw):
        return CTkLabel(parent, text=text, text_color=kw.pop("text_color", TXT), **kw)

    def mount(self, pg: CTkScrollableFrame) -> None:
        self._pg = pg
        self._bind_wheel(pg)
        rpad = (0, 28)

        self._list_host = CTkFrame(pg, fg_color="transparent")
        self._edit_host = CTkFrame(pg, fg_color="transparent")

        # --- List view ---
        self._lbl(
            self._list_host,
            text=s("avatar_editor.title", default="Avatar Editor"),
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w", pady=(0, 6), padx=rpad)
        self._lbl(
            self._list_host,
            text=s(
                "avatar_editor.blurb",
                default="Edit character packs under Data/Skins: profile image, voice sample (.wav), and tts_personality.yaml (character root or per-locale folder).",
            ),
            font=("Segoe UI", 13),
            text_color=TXT2,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 14), padx=rpad)

        row = CTkFrame(self._list_host, fg_color="transparent")
        row.pack(fill="x", pady=(0, 12), padx=rpad)
        CTkButton(
            row,
            text=s("avatar_editor.create_new", default="Create New"),
            fg_color=GREEN_BT,
            hover_color="#16A34A",
            text_color="white",
            width=160,
            command=self._on_create_new,
        ).pack(side="left", padx=(0, 10))

        self._cards_body = CTkFrame(self._list_host, fg_color="transparent")
        self._cards_body.pack(fill="both", expand=True, padx=rpad)

        # --- Edit view ---
        edit_top = CTkFrame(self._edit_host, fg_color="transparent")
        edit_top.pack(fill="x", pady=(0, 12), padx=rpad)
        CTkButton(
            edit_top,
            text=s("avatar_editor.back", default="← Back"),
            fg_color=SEL_BG,
            hover_color=MUTED,
            width=100,
            command=self._show_list,
        ).pack(side="left", padx=(0, 12))
        self._edit_title = CTkLabel(
            edit_top,
            text="",
            font=("Segoe UI", 18, "bold"),
            text_color=TXT,
        )
        self._edit_title.pack(side="left")

        card = CTkFrame(self._edit_host, fg_color=CARD, corner_radius=12, border_width=1, border_color="#3A3A42")
        card.pack(fill="both", expand=True, padx=rpad, pady=(0, 8))

        inner = CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        self._lbl(inner, text=s("avatar_editor.section_photo", default="Profile photo"), font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 6))
        ph = CTkFrame(inner, fg_color="transparent")
        ph.pack(fill="x", pady=(0, 10))
        CTkButton(
            ph,
            text=s("avatar_editor.choose_photo", default="Choose image…"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            command=self._on_choose_photo,
        ).pack(side="left", padx=(0, 8))
        CTkButton(
            ph,
            text=s("avatar_editor.open_folder", default="Open folder"),
            fg_color=SEL_BG,
            hover_color=MUTED,
            command=self._on_open_folder,
        ).pack(side="left")

        self._lbl(inner, text=s("avatar_editor.section_voice", default="Voice sample (.wav)"), font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(12, 6))
        vf = CTkFrame(inner, fg_color="transparent")
        vf.pack(fill="x", pady=(0, 6))
        self._voice_locale_var = ctk.StringVar(value="")
        self._voice_locale_menu = CTkOptionMenu(vf, values=[""], variable=self._voice_locale_var, width=200, fg_color=SEL_BG, button_color=SEL_BG)
        self._voice_locale_menu.pack(side="left", padx=(0, 10))
        CTkButton(
            vf,
            text=s("avatar_editor.choose_wav", default="Choose .wav…"),
            fg_color=ACCENT,
            hover_color=SEL_BG,
            command=self._on_choose_wav,
        ).pack(side="left")

        self._lbl(inner, text=s("avatar_editor.section_personality", default="TTS personality (YAML)"), font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(12, 6))
        pf = CTkFrame(inner, fg_color="transparent")
        pf.pack(fill="x", pady=(0, 6))
        self._personality_menu = CTkOptionMenu(
            pf,
            values=["—"],
            command=self._on_personality_file_picked,
            width=280,
            fg_color=SEL_BG,
            button_color=SEL_BG,
        )
        self._personality_menu.pack(side="left", padx=(0, 10))
        CTkButton(
            pf,
            text=s("avatar_editor.new_personality_file", default="Create root file"),
            fg_color=SEL_BG,
            hover_color=MUTED,
            command=self._on_create_personality,
        ).pack(side="left")

        self._personality_text = CTkTextbox(inner, height=220, font=("Consolas", 12), text_color=TXT, fg_color="#18181B")
        self._personality_text.pack(fill="both", expand=True, pady=(8, 10))

        btn_row = CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")
        CTkButton(
            btn_row,
            text=s("avatar_editor.save", default="Save personality"),
            fg_color=GREEN_BT,
            hover_color="#16A34A",
            text_color="white",
            command=self._on_save_personality,
        ).pack(side="left")

        self._show_list()

    def _bind_wheel(self, pg: CTkScrollableFrame) -> None:
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

    def refresh_list(self) -> None:
        if self._cards_body:
            self._rebuild_list_cards()

    def _clear(self, frame: CTkFrame) -> None:
        for w in frame.winfo_children():
            w.destroy()

    def _show_list(self) -> None:
        self._edit_host.pack_forget()
        self._list_host.pack(fill="both", expand=True)
        self._edit_char_dir = None
        self._edit_personality_path = None
        self._rebuild_list_cards()

    def _show_edit(self, char_dir: Path) -> None:
        self._edit_char_dir = char_dir
        self._list_host.pack_forget()
        self._edit_host.pack(fill="both", expand=True)
        self._edit_title.configure(text=char_dir.name)
        # Voice locale menu
        loc_labels: List[str] = [s("avatar_editor.voice_target_root", default="(root) voice_ref.wav")]
        loc_labels.extend(ae.list_locale_subdirs(char_dir))
        if self._voice_locale_menu and self._voice_locale_var:
            self._voice_locale_menu.configure(values=loc_labels)
            self._voice_locale_var.set(loc_labels[0])
        # Personality files
        cands = ae.personality_candidates(char_dir)
        if not cands:
            ae.ensure_default_personality(char_dir)
            cands = ae.personality_candidates(char_dir)
        labels = [f"{label}: {p.name}" for p, label in cands]
        paths = [p for p, _ in cands]
        if self._personality_menu:
            self._personality_menu.configure(values=labels if labels else ["—"])
            if paths:
                self._personality_menu.set(labels[0])
                self._edit_personality_path = paths[0]
                self._load_personality_text(paths[0])
            else:
                self._edit_personality_path = None
                self._personality_text.delete("1.0", "end")  # type: ignore[union-attr]

    def _on_personality_file_picked(self, choice: str) -> None:
        if not self._edit_char_dir:
            return
        for p, label in ae.personality_candidates(self._edit_char_dir):
            if f"{label}: {p.name}" == choice:
                self._edit_personality_path = p
                self._load_personality_text(p)
                return

    def _load_personality_text(self, path: Path) -> None:
        if not self._personality_text:
            return
        text, err = ae.read_text(path)
        self._personality_text.delete("1.0", "end")
        self._personality_text.insert("1.0", text if not err else f"# read error: {err}\n")
        self._edit_personality_path = path

    def _on_create_personality(self) -> None:
        if not self._edit_char_dir:
            return
        p = ae.ensure_default_personality(self._edit_char_dir)
        self._show_edit(self._edit_char_dir)
        if self._personality_menu:
            labels = [f"{lb}: {x.name}" for x, lb in ae.personality_candidates(self._edit_char_dir)]
            if labels:
                self._personality_menu.set(labels[0])
        self._load_personality_text(p)
        self._notify(s("avatar_editor.created_personality", default="Created tts_personality.yaml at character root."))

    def _on_save_personality(self) -> None:
        if not self._personality_text or not self._edit_personality_path:
            self._notify(s("avatar_editor.no_file", default="No personality file selected."), blink_times=1)
            return
        body = self._personality_text.get("1.0", "end")
        ok, err = ae.write_text(self._edit_personality_path, body.rstrip("\n") + "\n")
        if ok:
            self._notify(s("avatar_editor.saved", default="Saved."))
        else:
            self._notify(s("avatar_editor.save_failed", default=f"Save failed: {err}")[:500], blink_times=2)

    def _on_choose_photo(self) -> None:
        if not self._edit_char_dir:
            return
        fp = filedialog.askopenfilename(
            parent=self.widget.root,
            title=s("avatar_editor.pick_photo_title", default="Profile image"),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("PNG", "*.png"), ("All", "*.*")],
        )
        if not fp:
            return
        ok, msg = ae.install_profile_image(self._edit_char_dir, Path(fp))
        self._notify(msg if ok else s("avatar_editor.error", default="Error") + ": " + msg, blink_times=0 if ok else 2)

    def _on_choose_wav(self) -> None:
        if not self._edit_char_dir:
            return
        fp = filedialog.askopenfilename(
            parent=self.widget.root,
            title=s("avatar_editor.pick_wav_title", default="Voice sample"),
            filetypes=[("WAV", "*.wav"), ("All", "*.*")],
        )
        if not fp:
            return
        raw = (self._voice_locale_var.get() or "").strip()
        root_lbl = s("avatar_editor.voice_target_root", default="(root) voice_ref.wav")
        loc = None if raw == root_lbl else raw
        ok, msg = ae.install_voice_sample(self._edit_char_dir, loc, Path(fp))
        self._notify(msg if ok else s("avatar_editor.error", default="Error") + ": " + msg, blink_times=0 if ok else 2)

    def _on_open_folder(self) -> None:
        if not self._edit_char_dir:
            return
        p = str(self._edit_char_dir.resolve())
        try:
            if os.name == "nt":
                os.startfile(p)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            self._notify(str(e), blink_times=2)

    def _notify(self, msg: str, blink_times: int = 0) -> None:
        try:
            self.widget._notify(msg, restore_after_ms=4000, blink_times=blink_times)
        except Exception:
            logger.info("%s", msg)

    def _on_create_new(self) -> None:
        name = simpledialog.askstring(
            s("avatar_editor.new_title", default="New character"),
            s("avatar_editor.new_prompt", default="Folder name (under Data/Skins):"),
            parent=self.widget.root,
        )
        if not name:
            return
        ok, msg = ae.create_character_pack(self.widget.paths, name)
        if ok:
            self._notify(s("avatar_editor.created", default="Created pack:") + f" {msg}")
            self._show_edit(skins_data_root(self.widget.paths) / msg)
            return
        self._notify(msg, blink_times=2)

    def _rebuild_list_cards(self) -> None:
        if not self._cards_body:
            return
        self._clear(self._cards_body)
        rows = ae.list_skin_characters(self.widget.paths)
        if not rows:
            self._lbl(
                self._cards_body,
                text=s("avatar_editor.empty", default="No character folders under Data/Skins yet."),
                text_color=MUTED,
                font=("Segoe UI", 13),
            ).pack(anchor="w", pady=8)
            return

        for r in rows:
            name = r["name"]
            char_dir: Path = r["path"]
            card = CTkFrame(self._cards_body, fg_color=CARD, corner_radius=10, border_width=1, border_color="#3A3A42")
            card.pack(fill="x", pady=6)
            row = CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=10)
            # thumb
            thumb_f = CTkFrame(row, fg_color="#18181B", width=52, height=52, corner_radius=8)
            thumb_f.pack(side="left", padx=(0, 12))
            thumb_f.pack_propagate(False)
            prof = ae.character_profile_path(char_dir)
            if prof and HAS_PIL:
                try:
                    im = Image.open(prof).resize((44, 44))
                    ph = ctk.CTkImage(light_image=im, dark_image=im, size=(44, 44))
                    CTkLabel(thumb_f, text="", image=ph).place(relx=0.5, rely=0.5, anchor="center")
                except Exception:
                    self._lbl(thumb_f, text="?", font=("Segoe UI", 18), text_color=MUTED).place(relx=0.5, rely=0.5, anchor="center")
            else:
                self._lbl(thumb_f, text="🎭", font=("Segoe UI", 20), text_color=MUTED).place(relx=0.5, rely=0.5, anchor="center")

            mid = CTkFrame(row, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True)
            self._lbl(mid, text=name, font=("Segoe UI", 15, "bold")).pack(anchor="w")
            locs = r.get("locales") or []
            hint = ", ".join(locs[:6]) + ("…" if len(locs) > 6 else "")
            if not hint:
                hint = s("avatar_editor.no_locale_subdirs", default="No locale subfolders")
            self._lbl(mid, text=hint, font=("Segoe UI", 11), text_color=MUTED).pack(anchor="w")

            CTkButton(
                row,
                text=s("avatar_editor.edit", default="Edit"),
                width=72,
                fg_color=ACCENT,
                hover_color=SEL_BG,
                command=lambda d=char_dir: self._show_edit(d),
            ).pack(side="right")

def mount_avatar_editor_page(widget: "PerkySueWidget", pg: CTkScrollableFrame) -> AvatarEditorPage:
    ui = AvatarEditorPage(widget)
    ui.mount(pg)
    return ui
