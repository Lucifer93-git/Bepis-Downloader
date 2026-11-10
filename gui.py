from __future__ import annotations

import contextlib
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from tkinter import Menu, PhotoImage, filedialog, messagebox

import customtkinter as ctk
import certifi
import requests
from PIL import Image, ImageDraw, ImageFilter

from download import (
    load_config,
    normalize_gender,
    normalize_tags,
    parse_numeric_id_input,
    save_config_value,
    validate_search_url,
    validate_user_url,
)
from gui_backend import APP_VERSION, prepare_destination, run_gui_download

REPO_URL = "https://github.com/Lucifer93-git/Bepis-Downloader"
UPDATE_BRANCH = "r38-qol-alpha"
REMOTE_VERSION = f"https://raw.githubusercontent.com/Lucifer93-git/Bepis-Downloader/{UPDATE_BRANCH}/version.txt"
RELEASE_API = "https://api.github.com/repos/Lucifer93-git/Bepis-Downloader/releases/tags/{tag}"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#08111f"
PANEL = "#101b2e"
PANEL2 = "#0d1727"
BORDER = "#2c3c57"
TEXT = "#e9f0ff"
MUTED = "#9eb0d0"
PURPLE = "#7c3cff"
BLUE = "#2f8cff"
GREEN = "#22b573"
ORANGE = "#f39a2f"


def _asset_path(relative: str) -> Path:
    """Return a bundled/source asset path; works in PyInstaller onedir builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def _fallback_banner_image() -> Image.Image:
    """Create a Bepis-style dark blue/purple banner when no external art exists."""
    width, height = 1380, 126
    image = Image.new("RGB", (width, height), "#0a1528")
    draw = ImageDraw.Draw(image, "RGBA")

    # Smooth navy-to-indigo background.
    for x in range(width):
        t = x / max(1, width - 1)
        r = int(10 + 13 * t)
        g = int(21 + 10 * t)
        b = int(40 + 38 * t)
        draw.line((x, 0, x, height), fill=(r, g, b, 255))

    # Soft purple/blue glows echo the approved mockup without requiring an
    # external banner file.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((790, -110, 1160, 240), fill=(89, 70, 255, 95))
    gd.ellipse((1030, -90, 1400, 230), fill=(44, 119, 255, 75))
    gd.ellipse((620, -140, 910, 190), fill=(137, 66, 255, 50))
    glow = glow.filter(ImageFilter.GaussianBlur(48))
    image = Image.alpha_composite(image.convert("RGBA"), glow)

    # Subtle database-disc motif on the right.
    motif = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    md = ImageDraw.Draw(motif, "RGBA")
    for i, alpha in enumerate((55, 40, 25)):
        inset = i * 11
        md.ellipse((1110 + inset, 18 + inset//2, 1335 - inset, 108 - inset//2),
                   outline=(160, 192, 255, alpha), width=2)
    return image.convert("RGB")


class QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(str(text))
        return len(text or "")

    def flush(self):
        return None


class BepisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"BepisDB Downloader {APP_VERSION} - LuC!f3r")

        # Use the same BepisDB branding in the title bar/taskbar and the EXE.
        try:
            icon_ico = _asset_path("assets/app.ico")
            if icon_ico.exists():
                self.iconbitmap(str(icon_ico))
            icon_png = _asset_path("assets/app-icon.png")
            if icon_png.exists():
                self._window_icon = PhotoImage(file=str(icon_png))
                self.iconphoto(True, self._window_icon)
        except Exception:
            self._window_icon = None

        self.geometry("1380x860")
        self.minsize(1120, 720)
        self.configure(fg_color=BG)
        self.log_queue = queue.Queue()
        self.worker = None
        self.current_job_destination = None
        self.job_status_label = None
        self.job_progress_label = None
        self.open_folder_button = None
        self.copy_failed_button = None
        self.export_failed_button = None
        self.last_failed_ids = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_sidebar()
        self._build_content()
        self._build_statusbar()
        self.after(80, self._drain_log)
        self.bind_all("<Button-3>", self._show_context_menu, add="+")
        self.show_home()

    def _show_context_menu(self, event):
        """Show a standard Windows-style edit menu on entries and text boxes."""
        widget = event.widget
        widget_class = str(widget.winfo_class()).casefold()

        is_text = "text" in widget_class
        is_entry = "entry" in widget_class or "spinbox" in widget_class
        if not (is_text or is_entry):
            return

        menu = Menu(self, tearoff=0)

        # The log console should stay copy-oriented; editable fields get the
        # normal Cut/Copy/Paste actions.
        console_widget = None
        try:
            if hasattr(self, "console") and self.console.winfo_exists():
                console_widget = getattr(self.console, "_textbox", None)
        except Exception:
            pass

        is_console = widget is console_widget

        if not is_console:
            menu.add_command(
                label="Cut",
                command=lambda w=widget: w.event_generate("<<Cut>>"),
            )
        menu.add_command(
            label="Copy",
            command=lambda w=widget: w.event_generate("<<Copy>>"),
        )
        if not is_console:
            menu.add_command(
                label="Paste",
                command=lambda w=widget: w.event_generate("<<Paste>>"),
            )

        menu.add_separator()
        menu.add_command(
            label="Select All",
            command=lambda w=widget, text=is_text: self._select_all_widget(w, text),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _select_all_widget(widget, is_text):
        try:
            if is_text:
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "1.0")
                widget.see("insert")
            else:
                widget.selection_range(0, "end")
                widget.icursor("end")
        except Exception:
            pass

    def _update_progress_ui(self, message, percent=None):
        """Write updater progress to the console and bottom status bar."""
        if percent is None:
            status_text = f"● {message}"
            log_text = f"{message}\n"
        else:
            percent = max(0, min(100, int(percent)))
            status_text = f"● Updating... {percent}%"
            log_text = f"Downloading update: {percent}%\n"

        self.status.configure(text=status_text, text_color="#ffd27a")
        self.log_queue.put(log_text)

    def _build_header(self):
        """Build the top banner; gracefully falls back to the plain header."""
        header = ctk.CTkFrame(self, height=126, corner_radius=0, fg_color="#0d1a32")
        header.grid(row=0, column=0, columnspan=2, sticky="nsew")
        header.grid_propagate(False)

        banner_path = _asset_path("assets/banner.jpg")
        try:
            banner = Image.open(banner_path) if banner_path.exists() else _fallback_banner_image()
        except Exception:
            banner = _fallback_banner_image()

        self.header_banner_image = ctk.CTkImage(
            light_image=banner,
            dark_image=banner,
            size=(1380, 126),
        )
        ctk.CTkLabel(
            header,
            text="",
            image=self.header_banner_image,
            fg_color="transparent",
        ).place(x=0, y=0, relwidth=1, relheight=1)

        # Keep the title/logo layout over the banner itself. The custom banner
        # already includes a dark left-side fade for readability, so a solid
        # panel here would hide the artwork.
        title_panel = ctk.CTkFrame(
            header,
            width=610,
            height=126,
            corner_radius=0,
            fg_color="transparent",
        )
        title_panel.place(x=0, y=0)
        title_panel.grid_propagate(False)
        title_panel.grid_columnconfigure(1, weight=1)

        # BepisDB face/logo at the left, matching the Windows app icon.
        try:
            logo = Image.open(_asset_path("assets/app-icon.png"))
            self.header_logo_image = ctk.CTkImage(
                light_image=logo,
                dark_image=logo,
                size=(64, 64),
            )
            ctk.CTkLabel(
                title_panel,
                text="",
                image=self.header_logo_image,
                fg_color="transparent",
            ).grid(row=0, column=0, rowspan=2, padx=(28, 18), pady=22)
        except Exception:
            self.header_logo_image = None
            ctk.CTkLabel(
                title_panel,
                text="B",
                font=ctk.CTkFont(size=34, weight="bold"),
                text_color="#d8875d",
            ).grid(row=0, column=0, rowspan=2, padx=(34, 18), pady=22)

        ctk.CTkLabel(
            title_panel,
            text="BepisDB Downloader",
            font=ctk.CTkFont(size=35, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="sw", pady=(24, 0))

        ctk.CTkLabel(
            title_panel,
            text=f"{APP_VERSION}   •   Updated by LuC!f3r",
            font=ctk.CTkFont(size=16),
            text_color="#9db8ff",
        ).grid(row=1, column=1, sticky="nw", pady=(2, 20))

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=235, corner_radius=0, fg_color="#0b1423")
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        entries = [
            ("⌂  Home", self.show_home),
            ("◆  Koikatsu", lambda: self.show_game("KK")),
            ("◆  AI / HS2", lambda: self.show_game("AI_HS2")),
            ("●  User Page", self.show_user_page),
            ("⚙  Settings", self.show_settings),
            ("ⓘ  About", self.show_about),
            ("↻  Check for Updates", self.check_updates),
        ]
        for text, command in entries:
            ctk.CTkButton(
                self.sidebar, text=text, command=command, anchor="w", height=46,
                fg_color="transparent", hover_color="#1a2840", text_color=TEXT,
                font=ctk.CTkFont(size=16)
            ).pack(fill="x", padx=16, pady=(12 if text.startswith("⌂") else 3, 0))

    def _build_content(self):
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=46, corner_radius=0, fg_color="#0d1727")
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        self.status = ctk.CTkLabel(bar, text="● Ready", text_color="#8fb6ff")
        self.status.grid(row=0, column=0, padx=24, pady=10, sticky="w")
        cfg = load_config()
        self.status_right = ctk.CTkLabel(
            bar,
            text=f"Browser: {cfg.get('browser','firefox').title()} ({'Headless' if cfg.get('browser_mode','visible') == 'headless' else 'Visible'})   |   Page delay: {cfg.get('website_load_interval','5')}s   |   {APP_VERSION}",
            text_color=MUTED,
        )
        self.status_right.grid(row=0, column=1, padx=24, pady=10, sticky="e")

    def clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def _title(self, parent, title, subtitle=""):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=30, weight="bold"), text_color=TEXT).pack(anchor="w", padx=34, pady=(28, 2))
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, font=ctk.CTkFont(size=16), text_color=MUTED).pack(anchor="w", padx=34, pady=(0, 18))

    def _card(self, parent, title, desc, color, command):
        card = ctk.CTkFrame(parent, fg_color=PANEL, border_width=1, border_color=color, corner_radius=14)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(anchor="w", padx=22, pady=(22, 8))
        ctk.CTkLabel(card, text=desc, justify="left", wraplength=240, font=ctk.CTkFont(size=15), text_color=MUTED).pack(anchor="w", padx=22, pady=(0, 22))
        ctk.CTkButton(card, text="Open  →", command=command, fg_color=color, hover_color=color, height=42).pack(fill="x", padx=22, pady=(0, 22))
        return card

    def show_home(self):
        self.clear_content()
        wrap = ctk.CTkFrame(self.content, fg_color=BG)
        wrap.pack(fill="both", expand=True)
        self._title(wrap, "Select Download Mode", "Choose how you want to download from BepisDB.")
        cards = ctk.CTkFrame(wrap, fg_color="transparent")
        cards.pack(fill="x", padx=34, pady=6)
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1)

        self._card(cards, "Koikatsu", "Card IDs, scene IDs, URLs, tags, and search filters.", PURPLE, lambda: self.show_game("KK")).grid(row=0, column=0, padx=(0,8), sticky="nsew")
        self._card(cards, "AI / HS2", "AI Shoujo and Honey Select 2 cards, scenes, URLs, and searches.", BLUE, lambda: self.show_game("AI_HS2")).grid(row=0, column=1, padx=8, sticky="nsew")
        self._card(cards, "User Page", "Download directly from a BepisDB user profile, including hidden cards.", GREEN, self.show_user_page).grid(row=0, column=2, padx=8, sticky="nsew")
        self._card(cards, "Updates", "Check GitHub for a newer downloader version.", ORANGE, self.check_updates).grid(row=0, column=3, padx=(8,0), sticky="nsew")
        self._make_console(wrap)

    def _make_console(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=PANEL2, border_width=1, border_color=BORDER, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=34, pady=(18, 28))
        self.console = ctk.CTkTextbox(frame, fg_color="#07101d", text_color="#d7e5ff", font=("Consolas", 13), wrap="word")
        self.console.pack(fill="both", expand=True, padx=12, pady=12)
        self.console.insert("end", f"BepisDB Downloader {APP_VERSION}\nOriginal project by 0AwsD0 | Updated by LuC!f3r\nReady.\n")
        return frame

    def _make_job_status(self, parent):
        """Reusable download status strip; later this can move into the queue page."""
        frame = ctk.CTkFrame(
            parent, fg_color=PANEL, border_width=1, border_color=BLUE, corner_radius=12
        )
        frame.pack(fill="x", padx=34, pady=(14, 0))

        self.job_status_label = ctk.CTkLabel(
            frame, text="● Ready", text_color="#86e6b5",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.job_status_label.pack(side="left", padx=(22, 30), pady=14)

        self.job_progress_label = ctk.CTkLabel(
            frame,
            text="Page: 0 / ?     Downloaded: 0     Skipped: 0",
            text_color=TEXT,
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.job_progress_label.pack(side="left", padx=16, pady=14)

        self.open_folder_button = ctk.CTkButton(
            frame,
            text="Open Download Folder",
            width=180,
            state="disabled",
            command=self._open_job_folder,
        )
        self.open_folder_button.pack(side="right", padx=(8,18), pady=10)

        self.export_failed_button = ctk.CTkButton(
            frame,
            text="Export Failed",
            width=120,
            state="disabled",
            command=self._export_failed_ids,
        )
        self.export_failed_button.pack(side="right", padx=4, pady=10)

        self.copy_failed_button = ctk.CTkButton(
            frame,
            text="Copy Failed",
            width=120,
            state="disabled",
            command=self._copy_failed_ids,
        )
        self.copy_failed_button.pack(side="right", padx=4, pady=10)
        return frame

    def _open_job_folder(self):
        destination = self.current_job_destination
        if not destination:
            return
        path = Path(destination)
        if not path.exists():
            return messagebox.showerror("Folder unavailable", f"Folder does not exist:\n{path}")
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Open folder failed", str(exc))

    def _set_failed_ids(self, failed_ids):
        self.last_failed_ids = [str(value) for value in (failed_ids or []) if str(value).strip()]
        state = "normal" if self.last_failed_ids else "disabled"
        for button in (self.copy_failed_button, self.export_failed_button):
            try:
                if button and button.winfo_exists():
                    button.configure(state=state)
            except Exception:
                pass

    def _copy_failed_ids(self):
        if not self.last_failed_ids:
            return
        text = ", ".join(self.last_failed_ids)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            messagebox.showinfo("Failed IDs", f"Copied {len(self.last_failed_ids)} failed ID(s) to the clipboard.")
        except Exception as exc:
            messagebox.showerror("Copy failed", str(exc))

    def _export_failed_ids(self):
        if not self.last_failed_ids:
            return
        path = filedialog.asksaveasfilename(
            title="Export failed IDs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="bepis-failed-ids.txt",
        )
        if not path:
            return
        try:
            Path(path).write_text("\n".join(self.last_failed_ids) + "\n", encoding="utf-8")
            messagebox.showinfo("Failed IDs", f"Exported {len(self.last_failed_ids)} failed ID(s).")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def _recent_values(self, key):
        try:
            raw = load_config().get(key, "[]")
            values = json.loads(raw)
            if not isinstance(values, list):
                return []
            return [str(value).strip() for value in values if str(value).strip()][:10]
        except Exception:
            return []

    def _remember_recent(self, key, value):
        value = str(value or "").strip()
        if not value:
            return
        values = self._recent_values(key)
        values = [item for item in values if item.casefold() != value.casefold()]
        values.insert(0, value)
        save_config_value(key, json.dumps(values[:10], ensure_ascii=False))

    def _show_finish_notification(self, result):
        cfg = load_config()
        if cfg.get("notify_on_complete", "1") != "1" or not sys.platform.startswith("win"):
            return

        downloaded = int(result.get("downloaded", 0) or 0)
        skipped = int(result.get("skipped", 0) or 0)
        failed = len(result.get("failed_ids") or [])
        body = f"Downloaded: {downloaded}   Skipped: {skipped}   Failed: {failed}"

        # Windows toast without an extra dependency. If Windows blocks the toast
        # for any reason, fall back to the normal app notification sound.
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null; "
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$xml.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>BepisDB Downloader</text><text>"
            + body.replace("&", "and").replace("<", "").replace(">", "")
            + "</text></binding></visual></toast>'); "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('BepisDB Downloader').Show($toast);"
        )
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        except Exception:
            try:
                self.bell()
            except Exception:
                pass

    def _set_job_destination(self, destination):
        self.current_job_destination = str(destination) if destination else None
        try:
            if self.open_folder_button and self.open_folder_button.winfo_exists():
                self.open_folder_button.configure(
                    state="normal" if self.current_job_destination else "disabled"
                )
        except Exception:
            pass

    def _job_progress(self, state):
        """Receive backend progress safely from the worker thread."""
        def apply():
            try:
                if not self.job_progress_label or not self.job_progress_label.winfo_exists():
                    return
                phase = state.get("phase", "downloading")
                downloaded = int(state.get("downloaded", 0) or 0)
                skipped = int(state.get("skipped", 0) or 0)

                if "total_items" in state:
                    current = int(state.get("item", 0) or 0)
                    total = int(state.get("total_items", 0) or 0)
                    progress = f"Items: {current} / {total}     Downloaded: {downloaded}     Skipped: {skipped}"
                else:
                    page = int(state.get("page", 0) or 0)
                    total_pages = state.get("total_pages", "?")
                    progress = f"Page: {page} / {total_pages}     Downloaded: {downloaded}     Skipped: {skipped}"

                self.job_progress_label.configure(text=progress)
                if self.job_status_label and self.job_status_label.winfo_exists():
                    labels = {
                        "scanning": ("● Scanning...", "#ffd27a"),
                        "ready": ("● Pre-scan complete", "#86e6b5"),
                        "downloading": ("● Downloading...", "#8fb6ff"),
                        "complete": ("● Complete", "#86e6b5"),
                    }
                    text, color = labels.get(phase, ("● Working...", "#ffd27a"))
                    self.job_status_label.configure(text=text, text_color=color)

                if phase == "complete":
                    failed = int(state.get("failed", 0) or 0)
                    if failed:
                        self.job_status_label.configure(
                            text=f"● Complete with {failed} failed", text_color="#ffb36b"
                        )
            except Exception:
                pass
        self.after(0, apply)

    def _destination_fields(self, parent, game=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(row, text="Save location", text_color=TEXT, width=110, anchor="w").pack(side="left")
        cfg = load_config()
        game_key = "kk_default_folder" if game == "KK" else "ai_hs2_default_folder" if game == "AI_HS2" else ""
        game_path = cfg.get(game_key, "").strip() if game_key else ""
        default_path = game_path or cfg.get("default_save_location", "").strip()
        path = ctk.StringVar(
            value=default_path or str(Path.home()/"Downloads")
        )
        ctk.CTkEntry(row, textvariable=path).pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkButton(row, text="Browse", width=90, command=lambda: self._browse(path)).pack(side="left")

        folder = ctk.StringVar()
        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(row2, text="Folder name", text_color=TEXT, width=110, anchor="w").pack(side="left")
        ctk.CTkEntry(row2, textvariable=folder).pack(side="left", fill="x", expand=True, padx=8)
        return path, folder

    def _page_fields(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(row, text="Pages", text_color=TEXT, width=110, anchor="w").pack(side="left")
        pages = ctk.StringVar(value="1")
        ctk.CTkEntry(row, textvariable=pages, placeholder_text="1 or 2-4").pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(row, text="Examples: 1 = page 1 onward, 2-4 = pages 2 through 4", text_color=MUTED).pack(side="left", padx=8)
        return pages

    def show_user_page(self):
        self.clear_content()
        self.current_job_destination = None
        wrap = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        wrap.pack(fill="both", expand=True)
        self._title(wrap, "User Page Download", "Directly downloads from the rendered user page without opening every card detail page.")

        panel = ctk.CTkFrame(wrap, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
        panel.pack(fill="x", padx=34, pady=6)

        url = ctk.StringVar()
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(22,8))
        ctk.CTkLabel(row, text="User Page URL", text_color=TEXT, width=110, anchor="w").pack(side="left")
        recent_users = self._recent_values("recent_user_urls")
        ctk.CTkComboBox(
            row,
            variable=url,
            values=recent_users or [""],
        ).pack(side="left", fill="x", expand=True, padx=8)

        hidden = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(panel, text="Show hidden cards", variable=hidden).pack(anchor="w", padx=142, pady=8)
        pages = self._page_fields(panel)
        base, folder = self._destination_fields(panel)

        types = {
            "characters": ctk.BooleanVar(value=True),
            "clothing": ctk.BooleanVar(value=True),
            "scenes": ctk.BooleanVar(value=True),
        }
        type_row = ctk.CTkFrame(panel, fg_color="transparent")
        type_row.pack(fill="x", padx=24, pady=(10, 4))
        ctk.CTkLabel(type_row, text="Download types", text_color=TEXT, width=110, anchor="w").pack(side="left")
        ctk.CTkCheckBox(type_row, text="Characters", variable=types["characters"]).pack(side="left", padx=(8,18))
        ctk.CTkCheckBox(type_row, text="Clothing (KK)", variable=types["clothing"]).pack(side="left", padx=18)
        ctk.CTkCheckBox(type_row, text="Scenes", variable=types["scenes"]).pack(side="left", padx=18)
        ctk.CTkLabel(
            panel,
            text="Koikatsu: Characters, Clothing, Scenes   •   AI / HS2: Characters, Scenes",
            text_color=MUTED,
        ).pack(anchor="w", padx=142, pady=(0, 8))

        ctk.CTkButton(
            panel, text="Start Download", height=46, fg_color=GREEN,
            command=lambda: self._start_user(
                url.get(), hidden.get(), pages.get(), base.get(), folder.get(),
                {name for name, var in types.items() if var.get()},
            )
        ).pack(anchor="w", padx=142, pady=(14,22))

        self._make_job_status(wrap)
        self._make_console(wrap)

    def show_game(self, game):
        self.clear_content()
        wrap = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        wrap.pack(fill="both", expand=True)
        label = "Koikatsu (KK)" if game == "KK" else "AI Shoujo / Honey Select 2"
        self._title(wrap, label, "Direct IDs and listing/search downloads use the same safe completion and skip logic.")

        tabs = ctk.CTkTabview(wrap, fg_color=PANEL, segmented_button_selected_color=PURPLE if game=="KK" else BLUE)
        tabs.pack(fill="x", padx=34, pady=6)
        for name in ("Card IDs", "Scene IDs", "URL / Search"):
            tabs.add(name)

        self._fill_direct_tab(tabs.tab("Card IDs"), game, "card")
        self._fill_direct_tab(tabs.tab("Scene IDs"), game, "scene")
        self._fill_search_tab(tabs.tab("URL / Search"), game)
        self._make_job_status(wrap)
        self._make_console(wrap)

    def _fill_direct_tab(self, tab, game, kind):
        ids = ctk.StringVar()
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(18,8))
        ctk.CTkLabel(row, text="IDs", width=110, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=ids, placeholder_text="1234,1236,1240-1245").pack(side="left", fill="x", expand=True, padx=8)

        base, folder = self._destination_fields(tab, game)
        ctk.CTkButton(
            tab, text="Start Download", height=44,
            command=lambda: self._start_ids(game,kind,ids.get(),base.get(),folder.get())
        ).pack(anchor="w", padx=136, pady=(12,20))

    def _fill_search_tab(self, tab, game):
        vars = {k:ctk.StringVar() for k in ("url","name","tags","author","gender","personality")}
        labels = [("BepisDB URL","url"),("Name","name"),("Tags","tags")]
        if game=="KK":
            labels.append(("Card Author","author"))
        labels += [("Gender","gender"),("Personality","personality")]

        for title,key in labels:
            row=ctk.CTkFrame(tab,fg_color="transparent")
            row.pack(fill="x",padx=18,pady=5)
            ctk.CTkLabel(row,text=title,width=110,anchor="w").pack(side="left")
            if key == "url":
                ctk.CTkComboBox(
                    row,
                    variable=vars[key],
                    values=self._recent_values("recent_search_urls") or [""],
                ).pack(side="left",fill="x",expand=True,padx=8)
            else:
                ctk.CTkEntry(row,textvariable=vars[key]).pack(side="left",fill="x",expand=True,padx=8)

        hidden=ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(tab,text="Show hidden cards",variable=hidden).pack(anchor="w",padx=136,pady=8)
        pages=self._page_fields(tab)
        base,folder=self._destination_fields(tab, game)
        ctk.CTkButton(
            tab,text="Start Download",height=44,
            command=lambda:self._start_search(game,vars,hidden.get(),pages.get(),base.get(),folder.get())
        ).pack(anchor="w",padx=136,pady=(12,20))

    def show_settings(self):
        self.clear_content()
        wrap=ctk.CTkFrame(self.content,fg_color=BG)
        wrap.pack(fill="both",expand=True)
        self._title(wrap,"Settings","Saved in config.ini and reused on the next run.")

        panel=ctk.CTkFrame(wrap,fg_color=PANEL,border_width=1,border_color=BORDER,corner_radius=14)
        panel.pack(fill="x",padx=34,pady=8)

        cfg=load_config()
        browser=ctk.StringVar(value=cfg.get("browser","firefox"))
        delay=ctk.StringVar(value=cfg.get("website_load_interval","5"))
        close=ctk.BooleanVar(value=cfg.get("close_browser_after_download","0")=="1")
        browser_mode=ctk.StringVar(value=cfg.get("browser_mode","visible"))
        notify=ctk.BooleanVar(value=cfg.get("notify_on_complete","1")=="1")
        kk_default=ctk.StringVar(value=cfg.get("kk_default_folder",""))
        ai_default=ctk.StringVar(value=cfg.get("ai_hs2_default_folder",""))

        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Browser",width=160,anchor="w").pack(side="left")
        ctk.CTkOptionMenu(row,values=["firefox","chrome","edge"],variable=browser).pack(side="left")

        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Browser mode",width=160,anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row,
            values=["visible","headless"],
            variable=browser_mode,
            width=180,
        ).pack(side="left")
        ctk.CTkLabel(
            row,
            text="Headless = browser runs in background",
            text_color=MUTED,
        ).pack(side="left",padx=12)

        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Page load delay",width=160,anchor="w").pack(side="left")
        ctk.CTkEntry(row,textvariable=delay,width=120).pack(side="left")

        default_save=ctk.StringVar(value=cfg.get("default_save_location",""))
        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Default save location",width=160,anchor="w").pack(side="left")
        ctk.CTkEntry(row,textvariable=default_save).pack(side="left",fill="x",expand=True,padx=(0,8))
        ctk.CTkButton(
            row,
            text="Browse",
            width=90,
            command=lambda:self._browse(default_save),
        ).pack(side="left")

        for label, variable in (
            ("Koikatsu default folder", kk_default),
            ("AI / HS2 default folder", ai_default),
        ):
            row=ctk.CTkFrame(panel,fg_color="transparent")
            row.pack(fill="x",padx=24,pady=12)
            ctk.CTkLabel(row,text=label,width=160,anchor="w").pack(side="left")
            ctk.CTkEntry(row,textvariable=variable).pack(side="left",fill="x",expand=True,padx=(0,8))
            ctk.CTkButton(
                row,
                text="Browse",
                width=90,
                command=lambda v=variable:self._browse(v),
            ).pack(side="left")

        ctk.CTkCheckBox(panel,text="Windows notification when download finishes",variable=notify).pack(anchor="w",padx=184,pady=(8,4))
        ctk.CTkCheckBox(panel,text="Close browser after download",variable=close).pack(anchor="w",padx=184,pady=4)
        ctk.CTkButton(
            panel,
            text="Save Settings",
            command=lambda:self._save_settings(
                browser.get(),delay.get(),close.get(),default_save.get(),browser_mode.get(),
                notify.get(),kk_default.get(),ai_default.get()
            ),
        ).pack(anchor="w",padx=184,pady=(10,20))

    def show_about(self):
        self.clear_content()
        wrap=ctk.CTkFrame(self.content,fg_color=BG)
        wrap.pack(fill="both",expand=True)
        self._title(wrap,"About",f"BepisDB Downloader {APP_VERSION}")
        text=(
            "Original project: BepisDB-downloader by 0AwsD0\n"
            "https://github.com/0AwsD0/BepisDB-downloader\n\n"
            "Updated version by: LuC!f3r\n\n"
            "Firefox is the default browser. The downloader only closes the browser session it created when that option is enabled."
        )
        ctk.CTkLabel(wrap,text=text,justify="left",text_color=MUTED,font=ctk.CTkFont(size=16)).pack(anchor="w",padx=34,pady=12)
        ctk.CTkButton(wrap,text="Open GitHub",command=lambda:webbrowser.open(REPO_URL)).pack(anchor="w",padx=34,pady=10)

    def _browse(self,var):
        chosen=filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if chosen:
            var.set(chosen)

    def _parse_pages(self,text):
        import re
        value=(text or "1").strip()
        if value.isdigit() and int(value)>=1:
            return int(value),None
        match=re.fullmatch(r"(\d+)\s*-\s*(\d+)",value)
        if match and int(match.group(1))>=1 and int(match.group(2))>=int(match.group(1)):
            return int(match.group(1)),int(match.group(2))
        raise ValueError("Pages must be a number such as 2 or a range such as 2-4.")

    def _prepare(self,base,folder):
        if not base.strip():
            raise ValueError("Choose a save location.")
        dest=prepare_destination(base,folder)
        if dest is None:
            raise ValueError("Could not create or use the save location.")
        return dest

    def _start_user(self,url,hidden,pages,base,folder,selected_types):
        ok,msg,norm=validate_user_url(url.strip())
        if not ok:
            return messagebox.showerror("Invalid User Page",msg)
        if not selected_types:
            return messagebox.showerror("Select download types", "Select at least one card type to download.")
        try:
            start,end=self._parse_pages(pages)
        except ValueError as exc:
            return messagebox.showerror("Invalid pages",str(exc))
        self._remember_recent("recent_user_urls", norm)
        self._run_async({
            "mode":"user",
            "url":norm,
            "show_hidden":hidden,
            "start_from":start,
            "end_at":end,
            "selected_types":sorted(selected_types),
        },base,folder)

    def _start_ids(self,game,kind,raw,base,folder):
        try:
            items=parse_numeric_id_input(raw.strip(),game,kind)
        except Exception as exc:
            return messagebox.showerror("Invalid IDs",str(exc))

        label="Koikatsu (KK)" if game=="KK" else "AI Shoujo / Honey Select 2 (AI/HS2)"
        self._run_async({
            "mode":"ids","game":game,"label":label,
            "id_kind":"Card" if kind=="card" else "Scene",
            "id_items":items,
            "id_display":", ".join(x["display"] for x in items)
        },base,folder)

    def _start_search(self,game,vars,hidden,pages,base,folder):
        try:
            start,end=self._parse_pages(pages)
        except ValueError as exc:
            return messagebox.showerror("Invalid pages",str(exc))

        url=vars["url"].get().strip()
        detected={}
        if url:
            ok,msg,norm,detected=validate_search_url(url,game)
            if not ok:
                return messagebox.showerror("Invalid URL",msg)
            url=norm
            self._remember_recent("recent_search_urls", norm)

        try:
            gender=normalize_gender(vars["gender"].get().strip())
        except Exception as exc:
            return messagebox.showerror("Invalid gender",str(exc))

        label="Koikatsu (KK)" if game=="KK" else "AI Shoujo / Honey Select 2 (AI/HS2)"
        data={
            "mode":"game",
            "game":game,
            "label":label,
            "search_source":"BepisDB URL" if url else "Manual",
            "url":url,
            "name":vars["name"].get().strip() or detected.get("name",""),
            "tags":", ".join(normalize_tags(vars["tags"].get().strip())) or detected.get("tags",""),
            "author":vars["author"].get().strip() or detected.get("author",""),
            "gender":gender or detected.get("gender",""),
            "personality":vars["personality"].get().strip() or detected.get("personality",""),
            "show_hidden":hidden,
            "start_from":start,
            "end_at":end,
        }
        self._run_async(data,base,folder)

    def _run_async(self,data,base,folder):
        if self.worker and self.worker.is_alive():
            return messagebox.showinfo("Download running","A download is already running.")

        self._set_failed_ids([])
        self.status.configure(text="● Working...",text_color="#ffd27a")
        try:
            if self.job_status_label and self.job_status_label.winfo_exists():
                self.job_status_label.configure(text="● Preparing...", text_color="#ffd27a")
            if self.job_progress_label and self.job_progress_label.winfo_exists():
                if data.get("mode") == "ids":
                    self.job_progress_label.configure(text="Items: 0 / ?     Downloaded: 0     Skipped: 0")
                else:
                    self.job_progress_label.configure(text="Page: 0 / ?     Downloaded: 0     Skipped: 0")
        except Exception:
            pass

        def job():
            writer=QueueWriter(self.log_queue)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    dest=self._prepare(base,folder)
                    self.after(0, lambda d=dest: self._set_job_destination(d))
                    result=run_gui_download(data,dest,progress_callback=self._job_progress)
                    print("\nFinished.")
                    print(f"Downloaded: {result.get('downloaded',0)}")
                    print(f"Skipped existing: {result.get('skipped',0)}")
                    failed_ids = result.get('failed_ids') or []
                    self.after(0, lambda ids=list(failed_ids): self._set_failed_ids(ids))
                    self.after(0, lambda r=dict(result): self._show_finish_notification(r))
                    if failed_ids:
                        print("Failed: "+", ".join(failed_ids))
            except Exception as exc:
                self.log_queue.put(f"\nError: {exc}\n")
                self._job_progress({"phase":"complete","downloaded":0,"skipped":0,"failed":1})
            finally:
                self.after(0,lambda:self.status.configure(text="● Ready",text_color="#8fb6ff"))

        self.worker=threading.Thread(target=job,daemon=True)
        self.worker.start()

    def _drain_log(self):
        try:
            while True:
                text=self.log_queue.get_nowait()
                if hasattr(self,"console") and self.console.winfo_exists():
                    self.console.insert("end",text)
                    self.console.see("end")
        except queue.Empty:
            pass
        self.after(80,self._drain_log)

    def _save_settings(
        self,browser,delay,close,default_save="",browser_mode="visible",
        notify=True,kk_default="",ai_default=""
    ):
        try:
            value=int(delay)
            if value<5:
                raise ValueError
        except ValueError:
            return messagebox.showerror("Invalid delay","Page load delay must be 5 seconds or higher.")

        save_config_value("browser",browser)
        save_config_value("website_load_interval",str(value))
        save_config_value("close_browser_after_download","1" if close else "0")
        save_config_value("default_save_location",default_save.strip())
        save_config_value("notify_on_complete","1" if notify else "0")
        save_config_value("kk_default_folder",kk_default.strip())
        save_config_value("ai_hs2_default_folder",ai_default.strip())
        browser_mode = "headless" if str(browser_mode).strip().casefold() == "headless" else "visible"
        save_config_value("browser_mode",browser_mode)
        mode_label = "Headless" if browser_mode == "headless" else "Visible"
        self.status_right.configure(text=f"Browser: {browser.title()} ({mode_label})   |   Page delay: {value}s   |   {APP_VERSION}")
        messagebox.showinfo("Settings","Settings saved.")

    def _fetch_remote_version(self):
        """Fetch version.txt with packaged-app-friendly TLS and a Windows fallback."""
        headers = {"User-Agent": "BepisDB-Downloader"}
        primary_error = None

        try:
            response = requests.get(
                REMOTE_VERSION,
                headers=headers,
                timeout=12,
                verify=certifi.where(),
            )
            response.raise_for_status()
            value = response.text.strip()
            if value:
                return value
            raise RuntimeError("GitHub returned an empty version value.")
        except Exception as exc:
            primary_error = exc

        # Windows 10/11 includes curl.exe. Using it as a fallback avoids Python
        # TLS-stack quirks sometimes seen in packaged applications.
        if sys.platform.startswith("win"):
            try:
                result = subprocess.run(
                    ["curl.exe", "-fsSL", "--max-time", "15", REMOTE_VERSION],
                    capture_output=True,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=True,
                )
                value = result.stdout.strip()
                if value:
                    return value
            except Exception:
                pass

        raise RuntimeError(str(primary_error) if primary_error else "Update check failed.")

    def _release_tag_for_version(self, version):
        """Convert app versions to release tags, including prereleases."""
        value = str(version or "").strip()
        match = re.search(r"-(r\d+(?:-[A-Za-z0-9._-]+)?)$", value, re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid release tag in version: {value}")
        return match.group(1)

    def _release_info(self, version):
        """Return the matching GitHub release and its Windows ZIP asset."""
        tag = self._release_tag_for_version(version)
        url = RELEASE_API.format(tag=tag)
        response = requests.get(
            url,
            headers={"User-Agent": "BepisDB-Downloader"},
            timeout=15,
            verify=certifi.where(),
        )
        response.raise_for_status()
        release = response.json()

        asset = None
        for item in release.get("assets", []):
            name = str(item.get("name", ""))
            if "windows" in name.casefold() and name.casefold().endswith(".zip"):
                asset = item
                break

        if asset is None:
            raise RuntimeError(f"No Windows ZIP is attached to the {tag} release.")
        return release, asset

    def _show_update_dialog(self, latest):
        """Offer a real self-update instead of only telling users to download it."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Update available")
        dialog.geometry("520x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Update available",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=28, pady=(24, 8))

        ctk.CTkLabel(
            dialog,
            text=f"Installed: {APP_VERSION}\nLatest:    {latest}\n\n"
                 "The Windows build can download and install this update automatically.",
            justify="left",
            text_color=MUTED,
            font=ctk.CTkFont(size=15),
        ).pack(anchor="w", padx=28, pady=(0, 18))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=28, pady=(2, 22))

        def update_now():
            dialog.destroy()
            self._begin_self_update(latest)

        def open_release():
            try:
                tag = self._release_tag_for_version(latest)
                webbrowser.open(f"{REPO_URL}/releases/tag/{tag}")
            finally:
                dialog.destroy()

        ctk.CTkButton(
            buttons, text="Update now", fg_color=GREEN, command=update_now
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            buttons, text="Later", fg_color="#46536a", command=dialog.destroy
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            buttons, text="Open release", fg_color=BLUE, command=open_release
        ).pack(side="right")

    def _download_update_asset(self, asset, zip_path):
        """Download a release ZIP with retries and Windows curl fallback."""
        direct_url = str(asset.get("browser_download_url") or "").strip()
        api_url = str(asset.get("url") or "").strip()
        if not direct_url:
            raise RuntimeError("The Windows release asset has no download URL.")

        base_headers = {"User-Agent": "BepisDB-Downloader"}
        errors = []

        def download_with_requests(url, extra_headers=None, label="GitHub"):
            headers = dict(base_headers)
            if extra_headers:
                headers.update(extra_headers)

            for attempt in range(1, 5):
                try:
                    try:
                        if zip_path.exists():
                            zip_path.unlink()
                    except OSError:
                        pass

                    with requests.get(
                        url,
                        headers=headers,
                        stream=True,
                        allow_redirects=True,
                        timeout=(20, 180),
                        verify=certifi.where(),
                    ) as response:
                        if response.status_code in {502, 503, 504}:
                            raise requests.HTTPError(
                                f"{response.status_code} Server Error from {label}",
                                response=response,
                            )
                        response.raise_for_status()

                        total_bytes = int(response.headers.get("Content-Length") or 0)
                        downloaded_bytes = 0
                        last_percent = -1

                        with zip_path.open("wb") as handle:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                if not chunk:
                                    continue
                                handle.write(chunk)
                                downloaded_bytes += len(chunk)

                                if total_bytes > 0:
                                    percent = int(downloaded_bytes * 100 / total_bytes)
                                    if percent != last_percent:
                                        last_percent = percent
                                        self.after(
                                            0,
                                            lambda p=percent: self._update_progress_ui(
                                                "Downloading update...", p
                                            ),
                                        )

                    if not zip_path.exists() or zip_path.stat().st_size <= 0:
                        raise RuntimeError(f"{label} returned an empty update file.")
                    return True

                except Exception as exc:
                    errors.append(f"{label} attempt {attempt}: {exc}")
                    if attempt < 4:
                        delay = min(8, 2 ** attempt)
                        self.after(
                            0,
                            lambda a=attempt + 1, name=label: self._update_progress_ui(
                                f"Retrying {name} download (attempt {a}/4)..."
                            ),
                        )
                        time.sleep(delay)
            return False

        if download_with_requests(direct_url, label="GitHub release"):
            return

        if api_url and download_with_requests(
            api_url,
            extra_headers={"Accept": "application/octet-stream"},
            label="GitHub asset API",
        ):
            return

        if sys.platform.startswith("win"):
            try:
                try:
                    if zip_path.exists():
                        zip_path.unlink()
                except OSError:
                    pass

                self.after(
                    0,
                    lambda: self._update_progress_ui(
                        "GitHub download failed; trying Windows curl..."
                    ),
                )
                subprocess.run(
                    [
                        "curl.exe",
                        "-fL",
                        "--retry", "5",
                        "--retry-all-errors",
                        "--retry-delay", "2",
                        "--connect-timeout", "20",
                        "--max-time", "900",
                        "-A", "BepisDB-Downloader",
                        "-o", str(zip_path),
                        direct_url,
                    ],
                    capture_output=True,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=True,
                )
                if zip_path.exists() and zip_path.stat().st_size > 0:
                    return
                raise RuntimeError("Windows curl returned an empty update file.")
            except Exception as exc:
                errors.append(f"Windows curl: {exc}")

        detail = errors[-1] if errors else "Unknown download error."
        raise RuntimeError(
            "The update ZIP could not be downloaded after multiple retries and fallbacks.\n\n"
            f"Last error: {detail}"
        )

    def _begin_self_update(self, latest):
        """Download the release ZIP, launch the helper, then close this EXE."""
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                "Source build",
                "Automatic replacement is for the packaged Windows build.\n\n"
                "For the source build, run updater.py.",
            )
            return

        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                "Download running",
                "Finish the current card download before updating.",
            )
            return

        self._update_progress_ui("Checking release...")

        def job():
            temp_root = None
            try:
                release, asset = self._release_info(latest)
                download_url = asset.get("browser_download_url")
                if not download_url:
                    raise RuntimeError("The Windows release asset has no download URL.")

                self.after(0, lambda: self._update_progress_ui("Downloading update...", 0))

                temp_root = Path(tempfile.mkdtemp(prefix="bepis_self_update_"))
                zip_path = temp_root / "update.zip"
                extract_dir = temp_root / "extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)

                self._download_update_asset(asset, zip_path)

                self.after(0, lambda: self._update_progress_ui("Extracting update..."))
                with zipfile.ZipFile(zip_path, "r") as archive:
                    archive.extractall(extract_dir)

                self.after(0, lambda: self._update_progress_ui("Preparing installer..."))

                new_exe = extract_dir / "BepisDB-Downloader.exe"
                if not new_exe.exists():
                    raise RuntimeError("The downloaded Windows package is missing BepisDB-Downloader.exe.")

                install_dir = Path(sys.executable).resolve().parent
                installed_helper = install_dir / "BepisDB-Updater.exe"
                if not installed_helper.exists():
                    raise RuntimeError(
                        "BepisDB-Updater.exe is missing from this installation. "
                        "Install r34 manually once to enable future automatic updates."
                    )

                # Run the helper from temp so it can replace the installed copy too.
                helper_copy = temp_root / "BepisDB-Updater.exe"
                shutil.copy2(installed_helper, helper_copy)

                self.after(0, lambda: self._update_progress_ui("Closing application..."))

                subprocess.Popen(
                    [
                        str(helper_copy),
                        "--source", str(extract_dir),
                        "--target", str(install_dir),
                        "--pid", str(os.getpid()),
                        "--launch", "BepisDB-Downloader.exe",
                    ],
                    cwd=str(temp_root),
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    close_fds=True,
                )

                def close_for_update():
                    try:
                        self.destroy()
                    finally:
                        # The helper already has everything it needs. Exiting the
                        # process prevents background threads from keeping the
                        # PyInstaller image/DLLs locked during replacement.
                        os._exit(0)

                self.after(0, close_for_update)
                return

            except Exception as exc:
                if temp_root is not None:
                    shutil.rmtree(temp_root, ignore_errors=True)
                message = str(exc)
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Update failed",
                        f"The automatic update could not be installed.\n\n{message}\n\n"
                        "Your current installation was not replaced.",
                    ),
                )
                self.after(
                    0,
                    lambda: self.status.configure(
                        text="● Ready", text_color="#8fb6ff"
                    ),
                )

        threading.Thread(target=job, daemon=True).start()

    def check_updates(self):
        def job():
            try:
                latest = self._fetch_remote_version()

                if latest == APP_VERSION:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Updates",
                            f"You're up to date: {APP_VERSION}",
                        ),
                    )
                else:
                    # Confirm the release/Windows asset exists before offering
                    # automatic installation.
                    self._release_info(latest)
                    self.after(0, lambda: self._show_update_dialog(latest))
            except Exception as exc:
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Update check",
                        "Could not check GitHub.\n\n"
                        f"{exc}\n\n"
                        "You can still use the downloader normally.",
                    ),
                )

        threading.Thread(target=job, daemon=True).start()



if __name__ == "__main__":
    BepisApp().mainloop()
