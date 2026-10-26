<div align="center">

# Pixel Merger

**Rebuild one image out of the pixels of another, then watch every pixel fly to its new place.**

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-Tkinter-8b6cff)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

![Pixel Merger main window](docs/images/screenshot-main.png)

</div>

Pixel Merger takes a **source** image and rearranges its pixels so that, together, they resemble a **target**
image. No colour is changed and no pixel is added or removed: every pixel of the source is simply moved.
The app then animates the whole rearrangement, with each pixel travelling along a smooth arc to its new cell,
and lets you export the animation as a GIF.

| Target | Source | Result |
|:---:|:---:|:---:|
| ![Target image](docs/images/example-target.png) | ![Source image](docs/images/example-source.png) | ![Result](docs/images/example-result.png) |

## Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Features

- **Any two images:** PNG, JPEG, BMP, GIF or WebP, at any resolution.
- **Square crop for each image:** click or drag to move it, and use the slider to resize it.
- **Grid size of 64, 128, 256 or 512:** choose between a quick, blocky mosaic and a detailed one.
- **Smooth animation:** eased motion along curved paths, with play, pause, restart and 0.5×/1×/2× speed.
- **Export to GIF** at the chosen speed, ready to share.

## Installation

You need **Python 3.10 or newer**.

### Windows

1. Install Python from [python.org](https://www.python.org/downloads/). In the installer, tick
   **Add python.exe to PATH**. Tkinter is included.
2. Download this project: **Code → Download ZIP** on GitHub, then unzip it. If you use Git, run
   `git clone https://github.com/omroz14/Pixel-Merger.git` instead.
3. Open PowerShell in the project folder and run:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   py main.py
   ```

   If PowerShell refuses to run `Activate.ps1`, run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

### Linux (Debian, Ubuntu, Linux Mint)

Tkinter is a system package, so `pip` cannot install it.

```bash
sudo apt install python3-tk python3-venv git
git clone https://github.com/omroz14/Pixel-Merger.git
cd Pixel-Merger
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### macOS

Install Python from [python.org](https://www.python.org/downloads/) (it includes Tkinter), then:

```bash
git clone https://github.com/omroz14/Pixel-Merger.git
cd Pixel-Merger
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

1. Under **Target**, click **Load image…** and pick the picture you want to recreate.
2. Under **Source**, click **Load image…** and pick the picture whose pixels will be used.
3. Adjust each crop: click or drag on the preview to move the cyan square, and use **Crop size** to resize it.
   **Reset crop** centres the largest possible square.
4. Choose a **Grid** size. Larger grids look more detailed but take longer to compute.
5. Press **▶ Play**. Use **❚❚ Pause**, **⟲ Restart** and **Speed** to control playback.
6. Click **Export GIF…** to save the animation.

**Tip:** the result looks best when the two images have a similar range of light and dark areas. A colourful
source with plenty of contrast works well for almost any target.

## How it works

1. Both crops are resized to an N × N grid, where N is the chosen grid size.
2. The **luminance** of every cell is computed as `0.299·R + 0.587·G + 0.114·B`.
3. The cells of each image are sorted by luminance. The *k*-th darkest source pixel is assigned to the
   *k*-th darkest target cell, which gives a one-to-one mapping between the two grids.
4. Each pixel moves from its start cell to its destination along a straight line, bent into an arc by a sine
   bulge perpendicular to the path. A smoothstep easing curve, `3t² − 2t³`, makes it start and stop gently.
5. All 100 frames are computed at once with NumPy, then played back or written to the GIF.

The mapping is recomputed only when an image, a crop or the grid size changes.

### Project structure

| File | Contents |
|------|----------|
| `main.py` | The whole app: user interface, pixel mapping, frame rendering, playback and GIF export. |
| `requirements.txt` | Python dependencies (`numpy`, `Pillow`). |

## Settings

These constants at the top of `main.py` can be changed to taste:

| Constant | Default | Meaning |
|----------|---------|---------|
| `PANEL_PX` | `180` | Size of each image preview, in pixels |
| `ANIM_PX` | `320` | Size of the animation, in pixels (also the GIF size) |
| `FRAMES` | `100` | Number of animation frames |
| `BASE_FRAME_MS` | `40` | Delay between frames at 1× speed (40 ms = 25 fps) |
| `ARC_STRENGTH` | `0.15` | How far the paths curve; `0` gives straight lines |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'tkinter'` | Install Tkinter: `sudo apt install python3-tk` on Linux, or reinstall Python from python.org on Windows/macOS. |
| `ModuleNotFoundError: No module named 'numpy'` or `'PIL'` | Activate the virtual environment, then run `pip install -r requirements.txt`. |
| `py` or `python` is not recognised (Windows) | Reinstall Python and tick **Add python.exe to PATH**. |
| Computing takes a long time | The 512 grid moves over 260,000 pixels per frame. Use 128 or 256 for quicker results. |

## License

Released under the [MIT License](LICENSE). © 2026 Oliwier Mróz.
