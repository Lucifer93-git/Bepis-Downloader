from __future__ import annotations

import contextlib
import io
import queue
import threading
import sys
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
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
REMOTE_VERSION = "https://raw.githubusercontent.com/Lucifer93-git/Bepis-Downloader/main/version.txt"

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
        self.geometry("1380x860")
        self.minsize(1120, 720)
        self.configure(fg_color=BG)
        self.log_queue = queue.Queue()
        self.worker = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_sidebar()
        self._build_content()
        self._build_statusbar()
        self.after(80, self._drain_log)
        self.show_home()

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

        # Dark translucent-looking title panel keeps text readable over the art.
        title_panel = ctk.CTkFrame(
            header,
            width=610,
            height=126,
            corner_radius=0,
            fg_color="#0a1528",
        )
        title_panel.place(x=0, y=0)
        title_panel.grid_propagate(False)
        title_panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            title_panel,
            text="◉",
            font=ctk.CTkFont(size=50),
            text_color="#8eb5ff",
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
            text=f"Browser: {cfg.get('browser','firefox').title()}   |   Page delay: {cfg.get('website_load_interval','5')}s   |   {APP_VERSION}",
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

    def _destination_fields(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(row, text="Save location", text_color=TEXT, width=110, anchor="w").pack(side="left")
        path = ctk.StringVar(value=str(Path.home()/"Downloads"))
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
        wrap = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        wrap.pack(fill="both", expand=True)
        self._title(wrap, "User Page Download", "Directly downloads from the rendered user page without opening every card detail page.")

        panel = ctk.CTkFrame(wrap, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
        panel.pack(fill="x", padx=34, pady=6)

        url = ctk.StringVar()
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(22,8))
        ctk.CTkLabel(row, text="User Page URL", text_color=TEXT, width=110, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=url, placeholder_text="https://db.bepis.moe/user/27373").pack(side="left", fill="x", expand=True, padx=8)

        hidden = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(panel, text="Show hidden cards", variable=hidden).pack(anchor="w", padx=142, pady=8)
        pages = self._page_fields(panel)
        base, folder = self._destination_fields(panel)

        ctk.CTkButton(
            panel, text="Start Download", height=46, fg_color=GREEN,
            command=lambda: self._start_user(url.get(), hidden.get(), pages.get(), base.get(), folder.get())
        ).pack(anchor="w", padx=142, pady=(14,22))
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
        self._make_console(wrap)

    def _fill_direct_tab(self, tab, game, kind):
        ids = ctk.StringVar()
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(18,8))
        ctk.CTkLabel(row, text="IDs", width=110, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=ids, placeholder_text="1234,1236,1240-1245").pack(side="left", fill="x", expand=True, padx=8)

        base, folder = self._destination_fields(tab)
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
            ctk.CTkEntry(row,textvariable=vars[key]).pack(side="left",fill="x",expand=True,padx=8)

        hidden=ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(tab,text="Show hidden cards",variable=hidden).pack(anchor="w",padx=136,pady=8)
        pages=self._page_fields(tab)
        base,folder=self._destination_fields(tab)
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

        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Browser",width=160,anchor="w").pack(side="left")
        ctk.CTkOptionMenu(row,values=["firefox","chrome","edge"],variable=browser).pack(side="left")

        row=ctk.CTkFrame(panel,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=12)
        ctk.CTkLabel(row,text="Page load delay",width=160,anchor="w").pack(side="left")
        ctk.CTkEntry(row,textvariable=delay,width=120).pack(side="left")

        ctk.CTkCheckBox(panel,text="Close browser after download",variable=close).pack(anchor="w",padx=184,pady=10)
        ctk.CTkButton(panel,text="Save Settings",command=lambda:self._save_settings(browser.get(),delay.get(),close.get())).pack(anchor="w",padx=184,pady=(10,20))

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

    def _start_user(self,url,hidden,pages,base,folder):
        ok,msg,norm=validate_user_url(url.strip())
        if not ok:
            return messagebox.showerror("Invalid User Page",msg)
        try:
            start,end=self._parse_pages(pages)
        except ValueError as exc:
            return messagebox.showerror("Invalid pages",str(exc))
        self._run_async({"mode":"user","url":norm,"show_hidden":hidden,"start_from":start,"end_at":end},base,folder)

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

        self.status.configure(text="● Working...",text_color="#ffd27a")

        def job():
            writer=QueueWriter(self.log_queue)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    dest=self._prepare(base,folder)
                    result=run_gui_download(data,dest)
                    print("\nFinished.")
                    print(f"Downloaded: {result.get('downloaded',0)}")
                    print(f"Skipped existing: {result.get('skipped',0)}")
                    if result.get('failed_ids'):
                        print("Failed: "+", ".join(result['failed_ids']))
            except Exception as exc:
                self.log_queue.put(f"\nError: {exc}\n")
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

    def _save_settings(self,browser,delay,close):
        try:
            value=int(delay)
            if value<5:
                raise ValueError
        except ValueError:
            return messagebox.showerror("Invalid delay","Page load delay must be 5 seconds or higher.")

        save_config_value("browser",browser)
        save_config_value("website_load_interval",str(value))
        save_config_value("close_browser_after_download","1" if close else "0")
        self.status_right.configure(text=f"Browser: {browser.title()}   |   Page delay: {value}s   |   {APP_VERSION}")
        messagebox.showinfo("Settings","Settings saved.")

    def check_updates(self):
        def job():
            try:
                request=urllib.request.Request(REMOTE_VERSION,headers={"User-Agent":"BepisDB-Downloader"})
                with urllib.request.urlopen(request,timeout=10) as response:
                    latest=response.read().decode().strip()

                if latest==APP_VERSION:
                    self.after(0,lambda:messagebox.showinfo("Updates",f"You're up to date: {APP_VERSION}"))
                else:
                    self.after(0,lambda:messagebox.showinfo(
                        "Update available",
                        f"Installed: {APP_VERSION}\nLatest: {latest}\n\nRun updater.py for the source build, or download the newest Windows build from GitHub."
                    ))
            except Exception as exc:
                self.after(0,lambda:messagebox.showerror("Update check",f"Could not check GitHub.\n\n{exc}"))

        threading.Thread(target=job,daemon=True).start()


if __name__ == "__main__":
    BepisApp().mainloop()
