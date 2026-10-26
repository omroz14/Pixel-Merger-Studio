"""Application window: the two image panels, matching and motion settings, the stage and playback."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageOps, ImageTk

import merger
from theme import *

PANEL_W = 290      # width of each side panel (px)
PREVIEW_PX = 236   # side of the image previews in the side panels
FRAMES = 100       # frames in one animation
BASE_FRAME_MS = 40 # frame delay at 1x speed (40 ms = 25 fps)
EXPORT_MIN_PX = 512  # exported images and GIFs are the grid scaled up by a whole number, to at least this size
GIF_HOLD_MS = 1500 # the last GIF frame stays this long before the loop restarts

ANIMATION, RESULT, COMPARE = "Animation", "Result", "Compare"
MODES = (ANIMATION, RESULT, COMPARE)
SIDES = (("target", "TARGET", "the picture to rebuild"), ("source", "SOURCE", "where the pixels come from"))
GRIDS = ("64", "128", "256", "512", "1024")
SPEEDS = (("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0))
IMG_TYPES = [("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"), ("All files", "*.*")]
MATCH_NOTES = {
    "colour": "Each target pixel gets a source pixel of similar lightness and colour.",
    "brightness": "Only lightness counts. Strong structure, but colours land at random.",
}


def _label(options, key):
    return dict(options)[key]


def _key(options, label):
    return next(k for k, v in options if v == label)


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("Pixel Merger")
        self.geometry("1400x860")
        self.minsize(1120, 680)

        # Per side: the image at full resolution and the square crop [x, y, size] in its pixels.
        self.images = {"target": None, "source": None}
        self.crops = {"target": [0, 0, 0], "source": [0, 0, 0]}
        self.previews = {}        # per side: (bright PIL, dimmed PhotoImage, scale, offset) of the panel preview
        self._crop_photos = {}
        self.grid_n = 128
        self.how = "colour"
        self.tint = 50            # target colour blend (%)
        self.motion = "arc"
        self.speed = 1.0

        self._match_key = None    # settings the cached pairing was made with
        self._match = None        # (source pixels, target pixels, assignment)
        self.plan = None          # merger.Plan for the current settings; None = must be rebuilt
        self.frames = [None] * FRAMES   # rendered lazily, cleared with the plan
        self.frame_idx = 0
        self.playing = False
        self.mode = ANIMATION
        self._after_id = None
        self._photo = None

        self._build_ui()
        self._bind_keys()
        self.set_mode(ANIMATION)
        self._status("Open a target and a source image to begin.")

    # ---------- building the interface ----------

    def _make_panel(self, column):
        """A scrollable side panel in grid `column`. Returns the frame to put cards in."""
        panel = ctk.CTkScrollableFrame(self, width=PANEL_W, fg_color=BG, corner_radius=0,
                                       scrollbar_button_color=BG, scrollbar_button_hover_color=BORDER)
        panel.grid(row=0, column=column, sticky="ns", padx=(12, 0) if column == 0 else (0, 12), pady=12)
        return panel

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        left = self._make_panel(0)
        right = self._make_panel(2)
        self._build_left(left)
        self._build_right(right)
        self._build_main()

    def _build_left(self, left):
        """The two images and their crops."""
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", pady=(4, 14), padx=4)
        ctk.CTkLabel(head, text="Pixel Merger", font=FONT_TITLE, text_color=TEXT, height=26).pack(anchor="w")
        ctk.CTkLabel(head, text="rebuild one image from the pixels of another", font=FONT_SMALL,
                     text_color=MUTED, height=16).pack(anchor="w")

        self.canvases, self.lbl_files, self.rows_crop = {}, {}, {}
        for side, title, hint in SIDES:
            c = card(left, title, hint)
            cv = tk.Canvas(c, width=PREVIEW_PX, height=PREVIEW_PX, bg=SURFACE_2, highlightthickness=0,
                           cursor="hand2")
            cv.pack(padx=PAD)
            # Clicking or dragging centres the crop under the cursor; the wheel resizes it.
            cv.bind("<ButtonPress-1>", lambda e, s=side: self._on_preview_click(s, e))
            cv.bind("<B1-Motion>", lambda e, s=side: self._move_crop(s, e))
            cv.bind("<MouseWheel>", lambda e, s=side: self._wheel_crop(s, 1 if e.delta > 0 else -1))
            cv.bind("<Button-4>", lambda e, s=side: self._wheel_crop(s, 1))    # Linux wheel up
            cv.bind("<Button-5>", lambda e, s=side: self._wheel_crop(s, -1))   # Linux wheel down
            self.canvases[side] = cv
            self.lbl_files[side] = ctk.CTkLabel(c, text="No file loaded", font=FONT_SMALL, text_color=MUTED,
                                                justify="left", anchor="w")
            self.lbl_files[side].pack(fill="x", padx=PAD, pady=(6, 4))
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(fill="x", padx=PAD, pady=(0, 4))
            button(row, "Open…", lambda s=side: self.open_image(s), width=10).pack(
                side="left", fill="x", expand=True)
            button(row, "Reset crop", lambda s=side: self.reset_crop(s), width=10).pack(
                side="left", fill="x", expand=True, padx=(6, 0))
            self.rows_crop[side] = SliderRow(c, "Crop size", 5, 100, 100,
                                             lambda v, s=side: self._on_crop_size(s, v), fmt=lambda v: f"{v}%")
            self.rows_crop[side].enable(False)
            ctk.CTkFrame(c, fg_color="transparent", height=PAD - 6).pack()
            self._draw_preview(side)

        c = card(left, "SWAP")
        button(c, "⇄  Swap target and source", self.swap).pack(fill="x", padx=PAD, pady=(0, PAD))

    def _build_right(self, right):
        """How pixels are paired, how they move, export."""
        # MATCHING
        c = card(right, "MATCHING")
        self.match_tabs = segmented(c, [lbl for _, lbl in merger.MATCHES],
                                    lambda v: self.set_match(_key(merger.MATCHES, v)))
        self.match_tabs.set(_label(merger.MATCHES, self.how))
        self.match_tabs.pack(fill="x", padx=PAD)
        self.lbl_match = note(c, MATCH_NOTES[self.how], pady=(6, 8))
        self.row_tint = SliderRow(c, "Target colour", 0, 100, self.tint, self._on_tint, fmt=lambda v: f"{v}%")
        note(c, "Shifts each pixel's hue towards the target while keeping its own lightness. "
                "0% moves the pixels without changing a single colour. Raise it when the source "
                "lacks the target's colours and the result looks grey.", pady=(2, 10))
        ctk.CTkLabel(c, text="Grid", font=FONT, text_color=TEXT, height=20, anchor="w").pack(fill="x", padx=PAD)
        self.grid_tabs = segmented(c, GRIDS, lambda v: self.set_grid(int(v)))
        self.grid_tabs.set(str(self.grid_n))
        self.grid_tabs.pack(fill="x", padx=PAD, pady=(4, 0))
        note(c, "Pixels per side. Bigger grids look finer but take longer to compute. 1024 takes "
                "about 15 s to match, and its first playback runs slower.", pady=(6, PAD))

        # MOTION
        c = card(right, "MOTION")
        self.motion_grid = ChoiceGrid(c, merger.MOTIONS, self.motion, self.set_motion, cols=2)
        self.lbl_motion = note(c, merger.MOTION_NOTES[self.motion], pady=(8, 10))
        ctk.CTkLabel(c, text="Speed", font=FONT, text_color=TEXT, height=20, anchor="w").pack(fill="x", padx=PAD)
        self.speed_tabs = segmented(c, [lbl for lbl, _ in SPEEDS], self._on_speed)
        self.speed_tabs.set("1×")
        self.speed_tabs.pack(fill="x", padx=PAD, pady=(4, PAD))

        # EXPORT
        c = card(right, "EXPORT")
        ex = ctk.CTkFrame(c, fg_color="transparent")
        ex.pack(fill="x", padx=PAD, pady=(0, PAD))
        button(ex, "Save image", self.save_result, width=10).pack(side="left", fill="x", expand=True)
        button(ex, "Save GIF", self.save_gif, width=10).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _build_main(self):
        """The center: view tabs, the stage and the play bar."""
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        self.tabs = segmented(main, MODES, self.set_mode)
        self.tabs.grid(row=0, column=0, sticky="w", pady=(4, 10))
        ctk.CTkLabel(main, text="Space play · ← → step · 1–3 views", font=FONT_SMALL,
                     text_color=MUTED).grid(row=0, column=0, sticky="e", pady=(4, 10))

        frame = ctk.CTkFrame(main, fg_color=SURFACE, corner_radius=12)
        frame.grid(row=1, column=0, sticky="nsew")
        self.stage = tk.Canvas(frame, bg=SURFACE, highlightthickness=0)
        self.stage.pack(fill="both", expand=True, padx=8, pady=8)
        self.stage.bind("<Configure>", lambda e: self._draw())

        bar = ctk.CTkFrame(main, fg_color=SURFACE, corner_radius=12)
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bar.grid_columnconfigure(1, weight=1)
        self.btn_play = button(bar, "▶  Play", self.toggle_play, accent=True, width=130, height=38)
        self.btn_play.grid(row=0, column=0, rowspan=2, padx=PAD, pady=PAD - 2)
        self.timeline = ctk.CTkSlider(bar, from_=0, to=FRAMES - 1, number_of_steps=FRAMES - 1, height=16,
                                      fg_color=SURFACE_2, progress_color=ACCENT, button_color=TEXT,
                                      button_hover_color="#ffffff", command=self._on_scrub)
        self.timeline.set(0)
        self.timeline.grid(row=0, column=1, sticky="ew", padx=(0, PAD - 4), pady=(PAD, 0))
        self.lbl_status = ctk.CTkLabel(bar, text="", font=FONT_SMALL, text_color=MUTED, anchor="w", height=18)
        self.lbl_status.grid(row=1, column=1, sticky="ew", padx=(4, PAD), pady=(2, PAD - 4))

    def _bind_keys(self):
        self.bind("<space>", lambda e: self.toggle_play())
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        for i, m in enumerate(MODES, 1):
            self.bind(f"<Key-{i}>", lambda e, m=m: self.set_mode(m))

    # ---------- settings ----------

    def set_match(self, how):
        if how != self.how:
            self.how = how
            self.lbl_match.configure(text=MATCH_NOTES[how])
            self._invalidate()

    def _on_tint(self, v):
        if v != self.tint:
            self.tint = v
            self._invalidate()

    def set_grid(self, n):
        if n != self.grid_n:
            self.grid_n = n
            self._invalidate()

    def set_motion(self, motion):
        self.motion_grid.select(motion)
        self.lbl_motion.configure(text=merger.MOTION_NOTES[motion])
        if motion != self.motion:
            self.motion = motion
            self._invalidate()

    def _on_speed(self, label):
        self.speed = dict(SPEEDS)[label]

    def _invalidate(self):
        """A setting changed: the next frame is computed from scratch."""
        self._stop_timer()
        self.plan = None
        self.frames = [None] * FRAMES
        self._set_frame(0)
        self.btn_play.configure(text="▶  Play")
        if self._ready():
            self._status("Settings changed. Press Play to see the new animation.")
        self._draw()

    # ---------- images and crops ----------

    def open_image(self, side):
        path = filedialog.askopenfilename(title=f"Open the {side} image", filetypes=IMG_TYPES)
        if not path:
            return
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Could not load the image", str(exc))
            return
        self.images[side] = img
        self.lbl_files[side].configure(text=f"{os.path.basename(path)}\n{img.width} × {img.height} px",
                                       text_color=TEXT)
        self.rows_crop[side].enable(True)
        self._make_preview(side)
        self.reset_crop(side)
        if not self._ready():
            other = "source" if side == "target" else "target"
            self._status(f"Now open the {other} image.")
        else:
            self._status("Both images loaded. Drag on a preview to move its crop, then press Play.")

    def swap(self):
        if not any(self.images.values()):
            return
        for d in (self.images, self.crops):
            d["target"], d["source"] = d["source"], d["target"]
        texts = {side: lbl.cget("text") for side, lbl in self.lbl_files.items()}
        self.lbl_files["target"].configure(text=texts["source"])
        self.lbl_files["source"].configure(text=texts["target"])
        for side, _, _ in SIDES:
            img = self.images[side]
            self.lbl_files[side].configure(text_color=TEXT if img else MUTED)
            self.rows_crop[side].enable(img is not None)
            if img is not None:
                self._make_preview(side)
                self.rows_crop[side].set(self._crop_percent(side))
            self._draw_preview(side)
        self._invalidate()

    def _make_preview(self, side):
        img = self.images[side]
        scale = min(PREVIEW_PX / img.width, PREVIEW_PX / img.height)
        small = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        offset = ((PREVIEW_PX - small.width) // 2, (PREVIEW_PX - small.height) // 2)
        # The whole preview is drawn dimmed; the crop is drawn on top from the bright copy.
        dim = Image.blend(small, Image.new("RGB", small.size, hex_to_rgb(BG)), 0.6)
        self.previews[side] = (small, ImageTk.PhotoImage(dim), scale, offset)

    def _clamp(self, side, x, y, size):
        """Keeps the crop square fully inside the image."""
        w, h = self.images[side].size
        size = max(1, min(int(size), w, h))
        return [min(max(round(x), 0), w - size), min(max(round(y), 0), h - size), size]

    def _crop_percent(self, side):
        return round(self.crops[side][2] / min(self.images[side].size) * 100)

    def reset_crop(self, side):
        """The largest centred square."""
        img = self.images[side]
        if img is None:
            return
        size = min(img.size)
        self.crops[side] = [(img.width - size) // 2, (img.height - size) // 2, size]
        self.rows_crop[side].set(100)
        self._draw_preview(side)
        self._invalidate()

    def _set_crop_size(self, side, size):
        """Resizes around the current centre, so the square doesn't jump away."""
        x, y, old = self.crops[side]
        cx, cy = x + old / 2, y + old / 2
        self.crops[side] = self._clamp(side, cx - size / 2, cy - size / 2, size)
        self._draw_preview(side)
        self._invalidate()

    def _on_crop_size(self, side, percent):
        if self.images[side] is not None:
            self._set_crop_size(side, min(self.images[side].size) * percent / 100)

    def _wheel_crop(self, side, direction):
        if self.images[side] is None:
            return
        percent = min(100, max(5, self._crop_percent(side) + 5 * direction))
        self.rows_crop[side].set(percent)
        self._on_crop_size(side, percent)

    def _on_preview_click(self, side, e):
        if self.images[side] is None:
            self.open_image(side)         # the empty preview works as an "open" button
        else:
            self._move_crop(side, e)

    def _move_crop(self, side, e):
        if self.images[side] is None:
            return
        _, _, scale, (ox, oy) = self.previews[side]
        size = self.crops[side][2]
        ix, iy = (e.x - ox) / scale, (e.y - oy) / scale
        self.crops[side] = self._clamp(side, ix - size / 2, iy - size / 2, size)
        self._draw_preview(side)
        self._invalidate()

    def _draw_preview(self, side):
        cv = self.canvases[side]
        cv.delete("all")
        if self.images[side] is None:
            m = PREVIEW_PX // 2
            cv.create_rectangle(10, 10, PREVIEW_PX - 10, PREVIEW_PX - 10, outline=BORDER, dash=(6, 4), width=2)
            cv.create_text(m, m - 14, text="🖼", fill=MUTED, font=(FAMILY, -26))
            cv.create_text(m, m + 18, text="Click to open an image", fill=MUTED, font=FONT_SMALL)
            return
        small, dim, s, (ox, oy) = self.previews[side]
        cv.create_image(ox, oy, image=dim, anchor="nw")
        x, y, size = self.crops[side]
        box = (round(x * s), round(y * s), round((x + size) * s), round((y + size) * s))
        self._crop_photos[side] = ImageTk.PhotoImage(small.crop(box))   # keep a reference or Tk drops it
        cv.create_image(ox + box[0], oy + box[1], image=self._crop_photos[side], anchor="nw")
        cv.create_rectangle(ox + box[0], oy + box[1], ox + box[2], oy + box[3], outline=ACCENT, width=2)

    # ---------- the animation ----------

    def _ready(self):
        return all(img is not None for img in self.images.values())

    def _ensure_plan(self):
        """Builds the pairing and the motion plan if a setting changed. False if an image is missing."""
        if not self._ready():
            self._status("Open both a target and a source image first.")
            return False
        if self.plan is not None:
            return True
        n = self.grid_n
        key = (n, self.how, tuple(self.crops["target"]), tuple(self.crops["source"]),
               id(self.images["target"]), id(self.images["source"]))
        if key != self._match_key:
            self._status(f"Matching {n * n:,} pixels…")
            self.update_idletasks()
            src = merger.prepare(self.images["source"], self.crops["source"], n)
            tgt = merger.prepare(self.images["target"], self.crops["target"], n)
            self._match = (src, tgt, merger.match(src, tgt, self.how))
            self._match_key = key
            self._status(f"Matched {n * n:,} pixels.")
        src, tgt, assignment = self._match
        end = np.empty_like(src)
        end[assignment] = merger.tint(src[assignment], tgt, self.tint / 100)
        self.plan = merger.Plan(src, end, assignment, n, self.motion, hex_to_rgb(SURFACE))
        self.frames = [None] * FRAMES
        return True

    def _frame(self, i):
        if self.frames[i] is None:
            self.frames[i] = self.plan.frame(i / (FRAMES - 1))
        return self.frames[i]

    def _set_frame(self, i):
        self.frame_idx = i
        self.timeline.set(i)

    def _stop_timer(self):
        self.playing = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def toggle_play(self):
        if self.playing:
            self._stop_timer()
            self.btn_play.configure(text="▶  Resume")
            self._status("Paused. Drag the timeline to look at any moment.")
            return
        if not self._ensure_plan():
            return
        if self.frame_idx >= FRAMES - 1:      # finished earlier: start over
            self._set_frame(0)
        self.playing = True
        self.btn_play.configure(text="❚❚  Pause")
        if self.mode != ANIMATION:
            self.set_mode(ANIMATION)
        self._status(f"Playing · {_label(merger.MOTIONS, self.motion)} · {self.grid_n}×{self.grid_n} grid")
        self._tick()

    def _tick(self):
        self._after_id = None
        if not self.playing:
            return
        self._draw()
        if self.frame_idx >= FRAMES - 1:
            self._stop_timer()
            self.btn_play.configure(text="↺  Replay")
            self._status("Done. Play again, try another motion, or save a GIF.")
            return
        self._set_frame(self.frame_idx + 1)
        self._after_id = self.after(max(1, round(BASE_FRAME_MS / self.speed)), self._tick)

    def _on_scrub(self, v):
        self._stop_timer()
        if not self._ensure_plan():
            self.timeline.set(0)
            return
        self.frame_idx = int(round(v))
        self.btn_play.configure(text="▶  Resume" if self.frame_idx < FRAMES - 1 else "↺  Replay")
        if self.mode != ANIMATION:
            self.set_mode(ANIMATION)
        else:
            self._draw()

    def _step(self, d):
        if self._ready():
            self._on_scrub(min(FRAMES - 1, max(0, self.frame_idx + d)))
            self.timeline.set(self.frame_idx)

    # ---------- views ----------

    def set_mode(self, mode):
        self.mode = mode
        self.tabs.set(mode)
        self._draw()

    def _draw(self):
        if not self._ready():
            missing = " and ".join(s for s in ("target", "source") if self.images[s] is None)
            self._placeholder(f"Open the {missing} image\nin the panel on the left")
            return
        n = self.grid_n
        if self.mode == ANIMATION:
            if self.plan is None:
                self._show(merger.prepare(self.images["source"], self.crops["source"], n).reshape(n, n, 3),
                           f"ANIMATION · source · press Play to merge it into the target")
            else:
                self._show(self._frame(self.frame_idx),
                           f"ANIMATION · {_label(merger.MOTIONS, self.motion)} · "
                           f"frame {self.frame_idx + 1}/{FRAMES}")
        elif self._ensure_plan():
            result = self.plan.result()
            if self.mode == RESULT:
                self._show(result, f"RESULT · {n}×{n} · {_label(merger.MATCHES, self.how)} matching · "
                                   f"{self.tint}% target colour")
            else:
                target = merger.prepare(self.images["target"], self.crops["target"], n).reshape(n, n, 3)
                gap = np.empty((n, max(2, n // 16), 3), np.uint8)
                gap[:] = hex_to_rgb(SURFACE)
                self._show(np.hstack([target, gap, result]), "COMPARE · target  |  result")

    def _stage_size(self):
        return max(self.stage.winfo_width(), 50), max(self.stage.winfo_height(), 50)

    def _placeholder(self, text):
        self.stage.delete("all")
        w, h = self._stage_size()
        bw, bh = min(420, w - 40), min(220, h - 40)
        self.stage.create_rectangle(w // 2 - bw // 2, h // 2 - bh // 2, w // 2 + bw // 2, h // 2 + bh // 2,
                                    outline=BORDER, dash=(6, 4), width=2)
        self.stage.create_text(w // 2, h // 2 - 22, text="🖼", fill=MUTED, font=(FAMILY, -32))
        self.stage.create_text(w // 2, h // 2 + 22, text=text, fill=MUTED, font=FONT, justify="center")

    def _show(self, data, caption):
        """Draws an image scaled to fit the stage with sharp pixel edges, plus a caption."""
        img = Image.fromarray(data)
        w, h = self._stage_size()
        top = 30                            # room for the caption
        s = min((w - 24) / img.width, (h - top - 12) / img.height)
        dw, dh = max(1, round(img.width * s)), max(1, round(img.height * s))
        x0, y0 = (w - dw) // 2, top + (h - top - 12 - dh) // 2
        self._photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.NEAREST))
        self.stage.delete("all")
        self.stage.create_image(x0, y0, image=self._photo, anchor="nw")
        self.stage.create_text(10, 6, anchor="nw", fill=MUTED, font=FONT_SECTION, text=caption)

    # ---------- files ----------

    def _upscale(self, frame):
        """Grid image -> PIL, scaled up by a whole number so every pixel stays a crisp square."""
        k = max(1, -(-EXPORT_MIN_PX // self.grid_n))
        img = Image.fromarray(frame)
        return img.resize((img.width * k, img.height * k), Image.NEAREST)

    def save_result(self):
        if not self._ensure_plan():
            return
        path = filedialog.asksaveasfilename(title="Save image", defaultextension=".png",
                                            initialfile="pixel_merger.png",
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if not path:
            return
        self._upscale(self.plan.result()).save(path)
        self._status(f"Saved image: {os.path.basename(path)}")

    def save_gif(self):
        if not self._ensure_plan():
            return
        path = filedialog.asksaveasfilename(title="Save animation", defaultextension=".gif",
                                            initialfile="pixel_merger.gif", filetypes=[("GIF", "*.gif")])
        if not path:
            return
        self._stop_timer()
        self._status("Recording animation…")
        self.update_idletasks()
        imgs = [self._upscale(self._frame(i)) for i in range(FRAMES)]
        # GIF frame delays under 20 ms are unreliable in many viewers.
        delay = max(20, round(BASE_FRAME_MS / self.speed))
        imgs[0].save(path, save_all=True, append_images=imgs[1:],
                     duration=[delay] * (FRAMES - 1) + [GIF_HOLD_MS], loop=0)
        self._status(f"Saved animation: {os.path.basename(path)}")

    def _status(self, text):
        self.lbl_status.configure(text=text)
