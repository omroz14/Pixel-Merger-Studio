#!/usr/bin/env python3
"""
Pixel Merger: rearranges the pixels of a SOURCE image so they resemble
a TARGET image, then animates every pixel flying to its new cell.

Requires: Python 3, Pillow, NumPy (Tkinter ships with Python).
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

# --- Settings ---------------------------------------------------------------
PANEL_PX = 180                 # side length of each image preview
ANIM_PX = 320                  # side length of the animation
FRAMES = 100                   # number of animation frames (90-120 works well)
BASE_FRAME_MS = 40             # frame delay at 1x speed (40 ms = 25 fps)
GRID_CHOICES = ["64", "128", "256","512"]
SPEEDS = {"0.5×": 0.5, "1×": 1.0, "2×": 2.0}
LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)
ARC_STRENGTH = 0.15            # arc height as a fraction of the grid; 0 = straight lines



def ease_in_out(t):
    """Smoothstep easing: starts slow, speeds up, then slows down. t in [0, 1]."""
    return 3 * t**2 - 2 * t**3


class PixelSortApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pixel Merger")
        self.resizable(False, False)

        # Per-side state ("target" / "source"). The crop is stored in ORIGINAL
        # image pixel coordinates as [x, y, size], so the source resolution
        # doesn't matter.
        self.panels = {
            side: {"img": None, "photo": None, "canvas": None, "slider": None,
                   "scale": 1.0, "offset": (0, 0), "crop": [0, 0, 0]}
            for side in ("target", "source")
        }
        self.frames = []                 # precomputed PIL frames
        self.frame_idx = 0               # next frame to show
        self.playing = False
        self.after_id = None
        self.dirty = True                # True → mapping must be recomputed
        self.grid_var = tk.StringVar(value="64")
        self.speed_var = tk.StringVar(value="1×")
        self.status_var = tk.StringVar(value="Load a target and a source image to begin.")
        self._blank = ImageTk.PhotoImage(Image.new("RGB", (ANIM_PX, ANIM_PX), "#111"))
        self.anim_photo = None           # keep a reference or Tk drops the image

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # --- Image panels: target on the left, source on the right ---
        panels = tk.Frame(self, padx=10, pady=10)
        panels.pack()
        titles = {"target": "Target", "source": "Source"}
        for col, side in enumerate(("target", "source")):
            box = tk.LabelFrame(panels, text=titles[side], padx=8, pady=6)
            box.grid(row=0, column=col, padx=8)

            canvas = tk.Canvas(box, width=PANEL_PX, height=PANEL_PX,
                               bg="#222", highlightthickness=0)
            canvas.pack()
            # Clicking or dragging centres the crop square under the cursor.
            canvas.bind("<Button-1>", lambda e, s=side: self._move_crop_to_cursor(s, e))
            canvas.bind("<B1-Motion>", lambda e, s=side: self._move_crop_to_cursor(s, e))

            row = tk.Frame(box)
            row.pack(fill="x", pady=(6, 0))
            tk.Button(row, text="Load image…",
                      command=lambda s=side: self._load_image(s)).pack(side="left")
            tk.Button(row, text="Reset crop",
                      command=lambda s=side: self._reset_crop(s)).pack(side="right")

            slider = tk.Scale(box, from_=1, to=100, orient="horizontal",
                              label="Crop size (px)", length=PANEL_PX,
                              command=lambda v, s=side: self._on_slider(s, v))
            slider.pack(fill="x")

            self.panels[side]["canvas"] = canvas
            self.panels[side]["slider"] = slider
            self._draw_panel(side)

        # --- Animation display ---
        anim_box = tk.LabelFrame(self, text="Animation", padx=8, pady=6)
        anim_box.pack(padx=18, fill="x")
        self.anim_canvas = tk.Canvas(anim_box, width=ANIM_PX, height=ANIM_PX,
                                     bg="#111", highlightthickness=0)
        self.anim_canvas.pack()
        self.anim_item = self.anim_canvas.create_image(0, 0, anchor="nw", image=self._blank)

        # --- Control bar ---
        bar = tk.Frame(self, padx=12, pady=8)
        bar.pack(fill="x")
        tk.Button(bar, text="▶ Play", width=9, command=self.play).pack(side="left")
        tk.Button(bar, text="❚❚ Pause", width=9, command=self.pause).pack(side="left", padx=4)
        tk.Button(bar, text="⟲ Restart", width=9, command=self.restart).pack(side="left")

        tk.Label(bar, text="Speed").pack(side="left", padx=(16, 4))
        ttk.Combobox(bar, textvariable=self.speed_var, values=list(SPEEDS),
                     width=5, state="readonly").pack(side="left")

        tk.Label(bar, text="Grid").pack(side="left", padx=(12, 4))
        grid = ttk.Combobox(bar, textvariable=self.grid_var, values=GRID_CHOICES,
                            width=5, state="readonly")
        grid.pack(side="left")
        grid.bind("<<ComboboxSelected>>", lambda e: self._mark_dirty())

        tk.Button(bar, text="Export GIF…", command=self.export_gif).pack(side="right")

        # --- Status bar ---
        tk.Label(self, textvariable=self.status_var, anchor="w", padx=12, pady=4,
                 relief="sunken").pack(fill="x", side="bottom")

    # --------------------------------------------------------- Image loading
    def _load_image(self, side):
        path = filedialog.askopenfilename(
            title=f"Choose {side} image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path).convert("RGB")
        except OSError as exc:
            messagebox.showerror("Could not open image", str(exc))
            return

        # Build a preview that fits the panel while keeping the aspect ratio.
        w, h = img.size
        scale = min(PANEL_PX / w, PANEL_PX / h)
        preview = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

        p = self.panels[side]
        p["img"] = img
        p["photo"] = ImageTk.PhotoImage(preview)
        p["scale"] = scale
        p["offset"] = ((PANEL_PX - preview.width) // 2, (PANEL_PX - preview.height) // 2)

        # The slider's range depends on the image size.
        p["slider"].configure(from_=max(1, min(w, h) // 20), to=min(w, h))
        self._reset_crop(side)
        self._mark_dirty()
        self.status_var.set(f"Loaded {side} image ({w}×{h}).")

    # ------------------------------------------------------------ Crop handling
    def _clamp(self, side, x, y, size):
        """Keep the crop square fully inside the image."""
        w, h = self.panels[side]["img"].size
        size = max(1, min(int(size), w, h))
        x = min(max(round(x), 0), w - size)
        y = min(max(round(y), 0), h - size)
        return [x, y, size]

    def _reset_crop(self, side):
        """Center the largest possible square."""
        p = self.panels[side]
        if p["img"] is None:
            return
        w, h = p["img"].size
        size = min(w, h)
        p["crop"] = [(w - size) // 2, (h - size) // 2, size]
        p["slider"].set(size)            # triggers _on_slider, which is harmless here
        self._draw_panel(side)
        self._mark_dirty()

    def _on_slider(self, side, value):
        p = self.panels[side]
        if p["img"] is None:
            return
        x, y, old = p["crop"]
        new = int(float(value))
        # Resize around the current centre so the square doesn't jump away.
        cx, cy = x + old / 2, y + old / 2
        p["crop"] = self._clamp(side, cx - new / 2, cy - new / 2, new)
        self._draw_panel(side)
        self._mark_dirty()

    def _move_crop_to_cursor(self, side, event):
        p = self.panels[side]
        if p["img"] is None:
            return
        # Convert canvas pixels into original image pixels.
        ox, oy = p["offset"]
        ix = (event.x - ox) / p["scale"]
        iy = (event.y - oy) / p["scale"]
        size = p["crop"][2]
        p["crop"] = self._clamp(side, ix - size / 2, iy - size / 2, size)
        self._draw_panel(side)
        self._mark_dirty()

    def _draw_panel(self, side):
        p = self.panels[side]
        c = p["canvas"]
        c.delete("all")
        if p["photo"] is None:
            c.create_text(PANEL_PX / 2, PANEL_PX / 2, text="No image loaded", fill="#888")
            return
        ox, oy = p["offset"]
        c.create_image(ox, oy, image=p["photo"], anchor="nw")
        x, y, size = p["crop"]
        s = p["scale"]
        c.create_rectangle(ox + x * s, oy + y * s,
                           ox + (x + size) * s, oy + (y + size) * s,
                           outline="#00e5ff", width=2)

    def _mark_dirty(self):
        self.dirty = True
        self.status_var.set("Settings changed. Press Play or Restart to recompute.")

    # ------------------------------------------------ Mapping & frame rendering
    def _build_frames(self):
        """Compute the pixel permutation and render every animation frame."""
        n = int(self.grid_var.get())

        def prepare(side):
            """Crop to the square, resize to N×N. Returns (RGB array, luminance)."""
            p = self.panels[side]
            x, y, size = p["crop"]
            small = p["img"].crop((x, y, x + size, y + size)).resize((n, n), Image.LANCZOS)
            rgb = np.asarray(small, dtype=np.uint8).reshape(-1, 3)   # (N*N, 3)
            lum = rgb.astype(np.float32) @ LUMA                      # (N*N,)
            return rgb, lum

        src_rgb, src_lum = prepare("source")
        _, tgt_lum = prepare("target")

        # --- Permutation ---
        order_src = np.argsort(src_lum, kind="stable")
        order_tgt = np.argsort(tgt_lum, kind="stable")
        assignment = np.empty(n * n, dtype=np.int64)     # assignment[target] = source
        assignment[order_tgt] = order_src
        dest = np.empty_like(assignment)                 # dest[source] = target cell
        dest[assignment] = np.arange(n * n)

        # --- Start and end positions ---
        idx = np.arange(n * n)
        start_r, start_c = idx // n, idx % n
        end_r, end_c = dest // n, dest % n

        # --- Straight path per pixel, plus a unit vector perpendicular to it ---
        dr = end_r - start_r
        dc = end_c - start_c
        length = np.hypot(dr, dc) + 1e-6                 # avoid dividing by zero
        perp_r = -dc / length
        perp_c = dr / length
        arc_height = ARC_STRENGTH * n

        # --- Frames (vectorised) ---
        frames = []
        for f in range(FRAMES):
            e = ease_in_out(f / (FRAMES - 1))            # 0 → 1 with easing
            # Sine bulge: zero at the start and end, largest mid-flight.
            # This bends each path into an arc without moving the endpoints.
            bulge = np.sin(np.pi * e) * arc_height
            r = start_r + dr * e + bulge * perp_r
            c = start_c + dc * e + bulge * perp_c
            # Round to grid cells and keep everything inside the grid.
            r = np.clip(np.rint(r), 0, n - 1).astype(np.intp)
            c = np.clip(np.rint(c), 0, n - 1).astype(np.intp)
            grid = np.zeros((n, n, 3), dtype=np.uint8)   # black = empty cell
            grid[r, c] = src_rgb
            frames.append(Image.fromarray(grid).resize((ANIM_PX, ANIM_PX), Image.NEAREST))
        return frames

    def _ensure_frames(self):
        """Recompute the animation only when something changed."""
        if self.panels["target"]["img"] is None or self.panels["source"]["img"] is None:
            messagebox.showinfo("Missing images", "Please load both a target and a source image first.")
            return False
        if self.dirty:
            self.pause()
            self.status_var.set("Computing mapping…")
            self.update_idletasks()
            self.frames = self._build_frames()
            self.frame_idx = 0
            self.dirty = False
            n = self.grid_var.get()
            self.status_var.set(f"Ready: {FRAMES} frames on a {n}×{n} grid.")
        return True

    # ------------------------------------------------------------- Playback
    def _show_frame(self, i):
        self.anim_photo = ImageTk.PhotoImage(self.frames[i])
        self.anim_canvas.itemconfig(self.anim_item, image=self.anim_photo)

    def _tick(self):
        """Show one frame, then schedule the next one."""
        self.after_id = None
        if not self.playing:
            return
        self._show_frame(self.frame_idx)
        self.frame_idx += 1
        if self.frame_idx >= len(self.frames):   # just showed the last frame
            self.playing = False
            self.status_var.set("Finished. Press Restart to watch again.")
            return
        # Speed changes the delay between frames, not the frames themselves.
        delay = max(1, round(BASE_FRAME_MS / SPEEDS[self.speed_var.get()]))
        self.after_id = self.after(delay, self._tick)

    def play(self):
        if self.playing or not self._ensure_frames():
            return
        if self.frame_idx >= len(self.frames):   # finished earlier → start over
            self.frame_idx = 0
        self.playing = True
        self.status_var.set("Playing…")
        self._tick()

    def pause(self):
        self.playing = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.status_var.set("Paused.")

    def restart(self):
        if not self._ensure_frames():
            return
        self.pause()
        self.frame_idx = 0
        self.play()

    # --------------------------------------------------------------- Export
    def export_gif(self):
        if not self._ensure_frames():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".gif", initialfile="pixel_mosaic.gif",
            filetypes=[("GIF animation", "*.gif")])
        if not path:
            return
        self.status_var.set("Exporting GIF…")
        self.update_idletasks()
        # GIF frame delays under 20 ms are unreliable in many viewers.
        delay = max(20, round(BASE_FRAME_MS / SPEEDS[self.speed_var.get()]))
        self.frames[0].save(path, save_all=True, append_images=self.frames[1:],
                            duration=delay, loop=0)
        self.status_var.set(f"Saved {path}")


if __name__ == "__main__":
    PixelSortApp().mainloop()