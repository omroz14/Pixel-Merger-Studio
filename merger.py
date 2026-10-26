"""Pixel matching (which source pixel goes to which target cell) and the animation paths."""
import numpy as np
from PIL import Image

# --- Matching ------------------------------------------------------------------

MATCHES = (("colour", "Colour"), ("brightness", "Brightness"))
LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)
CHROMA_WEIGHT = 2.0


def to_oklab(rgb):
    """(N, 3) uint8 sRGB -> (N, 3) float32 OKLab. Distances in OKLab follow how different colours look."""
    c = rgb.astype(np.float32) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)   # undo the sRGB gamma
    lms = c @ np.array([[0.4122214708, 0.2119034982, 0.0883024619],
                        [0.5363325363, 0.6806995451, 0.2817188376],
                        [0.0514459929, 0.1073969566, 0.6299787005]], dtype=np.float32)
    lms = np.cbrt(lms)
    return lms @ np.array([[0.2104542553, 1.9779984951, 0.0259040371],
                           [0.7936177850, -2.4285922050, 0.7827717662],
                           [-0.0040720468, 0.4505937099, -0.8086757660]], dtype=np.float32)


def balanced_match(src, tgt):
    """Pairs every source point with one target point so that paired points are close.

    src, tgt: (N, D) float arrays of the same length. Both sets are split in half along
    the axis where they vary most, and each half is split again until single points remain.
    Each split keeps equal counts on both sides, so the result is a one-to-one pairing.
    Returns assignment with assignment[target index] = source index.
    """
    n, dims = src.shape
    order_s = np.arange(n)
    order_t = np.arange(n)
    seg = np.zeros(n, dtype=np.int64)     # segment id of each position; segments are contiguous
    pos = np.arange(n)
    while True:
        starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]])
        sizes = np.diff(np.r_[starts, n])
        if sizes.max() <= 1:
            break
        nseg = len(starts)
        local = pos - np.repeat(starts, sizes)        # position inside the segment
        sid = np.repeat(np.arange(nseg), sizes)
        s, t = src[order_s], tgt[order_t]
        # Variance of both sets together, per segment and axis.
        var = np.empty((nseg, dims))
        for d in range(dims):
            v = np.r_[s[:, d], t[:, d]]
            ids = np.r_[sid, sid]
            cnt = np.bincount(ids, minlength=nseg)
            mean = np.bincount(ids, v, nseg) / cnt
            var[:, d] = np.bincount(ids, v * v, nseg) / cnt - mean ** 2
        axis = np.repeat(var.argmax(axis=1), sizes)
        order_s = order_s[np.lexsort((s[pos, axis], sid))]
        order_t = order_t[np.lexsort((t[pos, axis], sid))]
        # Split each segment in two halves (a segment of one point stays whole).
        half = np.repeat(sizes // 2, sizes)
        seg = sid * 2 + ((local >= half) & (np.repeat(sizes, sizes) > 1))
    assignment = np.empty(n, dtype=np.int64)
    assignment[order_t] = order_s
    return assignment


def match(src_rgb, tgt_rgb, how):
    """assignment[target cell] = source pixel. src_rgb, tgt_rgb: (N, 3) uint8."""
    if how == "brightness":
        order_s = np.argsort(src_rgb.astype(np.float32) @ LUMA, kind="stable")
        order_t = np.argsort(tgt_rgb.astype(np.float32) @ LUMA, kind="stable")
        assignment = np.empty(len(src_rgb), dtype=np.int64)
        assignment[order_t] = order_s
        return assignment
    # Colour differences count double, or lightness (the widest axis) decides almost every split.
    w = np.array([1, CHROMA_WEIGHT, CHROMA_WEIGHT], dtype=np.float32)
    return balanced_match(to_oklab(src_rgb) * w, to_oklab(tgt_rgb) * w)


def from_oklab(lab):
    """Inverse of to_oklab: (N, 3) float OKLab -> (N, 3) uint8 sRGB (out-of-gamut colours are clipped)."""
    lms = lab @ np.array([[1.0, 1.0, 1.0],
                          [0.3963377774, -0.1055613458, -0.0894841775],
                          [0.2158037573, -0.0638541728, -1.2914855480]], dtype=np.float32)
    lin = (lms ** 3) @ np.array([[4.0767416621, -1.2684380046, -0.0041960863],
                                 [-3.3077115913, 2.6097574011, -0.7034186147],
                                 [0.2309699292, -0.3413193470, 1.7076147010]], dtype=np.float32)
    lin = np.clip(lin, 0, 1)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.rint(c * 255).astype(np.uint8)


def tint(src_rgb, tgt_rgb, amount):
    """Moves the hue and saturation of each pixel towards the target pixel it replaces, by amount in [0, 1].

    The lightness stays the pixel's own, so the mosaic keeps its texture. Both inputs are
    already paired: src_rgb[i] lands on the cell of tgt_rgb[i].
    """
    if amount <= 0:
        return src_rgb
    s, t = to_oklab(src_rgb), to_oklab(tgt_rgb)
    s[:, 1:] += (t[:, 1:] - s[:, 1:]) * amount
    return from_oklab(s)


# --- Motion --------------------------------------------------------------------

MOTIONS = (("arc", "Arc"), ("straight", "Straight"), ("swirl", "Swirl"),
           ("explode", "Explode"), ("cascade", "Cascade"), ("swarm", "Swarm"))
MOTION_NOTES = {
    "arc": "Every pixel flies along a gentle curve, all at once.",
    "straight": "The shortest way: straight lines, all at once.",
    "swirl": "Pixels spin around the centre like a whirlpool on their way.",
    "explode": "The image bursts outwards, then the pixels fall into place.",
    "cascade": "A wave from top to bottom: rows of the result fill in one after another.",
    "swarm": "Pixels leave at random moments, so the picture assembles like a swarm.",
}
ARC_STRENGTH = 0.15      # arc height as a fraction of the grid
SWIRL_TURNS = 0.75       # extra rotation around the centre, in full turns
EXPLODE_PUSH = 0.3       # how far pixels are thrown out, as a fraction of the grid
STAGGER = 0.6            # Cascade / Swarm: share of the animation used for start delays


def ease_in_out(t):
    """Smoothstep easing: starts slow, speeds up, then slows down. t in [0, 1]."""
    return 3 * t ** 2 - 2 * t ** 3


class Plan:
    """Start and end cell of every source pixel, plus everything needed to draw any frame."""

    def __init__(self, src_rgb, end_rgb, assignment, n, motion, bg):
        """src_rgb: colour of every source pixel; end_rgb: its colour once it lands (differs when tinted)."""
        self.n = n
        self.motion = motion
        self.colors = src_rgb
        self.end_colors = end_rgb
        self.tinted = not np.array_equal(src_rgb, end_rgb)
        self.bg = np.array(bg, dtype=np.uint8)
        dest = np.empty_like(assignment)
        dest[assignment] = np.arange(n * n)      # dest[source pixel] = target cell
        idx = np.arange(n * n)
        self.r0, self.c0 = (idx // n).astype(np.float32), (idx % n).astype(np.float32)
        self.r1, self.c1 = (dest // n).astype(np.float32), (dest % n).astype(np.float32)
        rng = np.random.default_rng(0)           # fixed seed: the same settings give the same animation
        if motion == "cascade":
            self.delay = self.r1 / max(1, n - 1) * STAGGER
        elif motion == "swarm":
            self.delay = rng.random(n * n, dtype=np.float32) * STAGGER
        else:
            self.delay = None
        # Explode: a small random spread so pixels from one spot don't fly as a clump.
        self.jitter = rng.normal(1.0, 0.25, n * n).astype(np.float32)

    def positions(self, t):
        """Row, column (floats) and eased progress of every pixel at time t in [0, 1]."""
        n = self.n
        if self.delay is not None:
            t = np.clip((t - self.delay) / (1 - STAGGER), 0, 1)
        e = ease_in_out(t)
        dr, dc = self.r1 - self.r0, self.c1 - self.c0
        r, c = self.r0 + dr * e, self.c0 + dc * e
        m = self.motion
        if m in ("arc", "cascade", "swarm"):
            # Sine bulge sideways: zero at both ends, largest mid-flight.
            length = np.hypot(dr, dc) + 1e-6
            bulge = np.sin(np.pi * e) * ARC_STRENGTH * n
            r, c = r + bulge * -dc / length, c + bulge * dr / length
        elif m == "swirl":
            # Rotate the straight-line position around the centre, more in the middle of the flight.
            mid = (n - 1) / 2
            angle = np.sin(np.pi * e) * SWIRL_TURNS * 2 * np.pi
            y, x = r - mid, c - mid
            cos, sin = np.cos(angle), np.sin(angle)
            r, c = mid + y * cos - x * sin, mid + y * sin + x * cos
        elif m == "explode":
            # Push away from the centre; the push peaks early, then the pixels settle.
            mid = (n - 1) / 2
            y, x = r - mid, c - mid
            dist = np.hypot(y, x) + 1e-6
            push = np.sin(np.pi * np.sqrt(e)) * EXPLODE_PUSH * n * self.jitter
            r, c = r + y / dist * push, c + x / dist * push
        return r, c, e

    def frame(self, t):
        """(n, n, 3) uint8 image at time t. Pixels pushed off the grid are hidden until they return."""
        n = self.n
        r, c, e = self.positions(t)
        r, c = np.rint(r).astype(np.intp), np.rint(c).astype(np.intp)
        inside = (r >= 0) & (r < n) & (c >= 0) & (c < n)
        grid = np.empty((n, n, 3), dtype=np.uint8)
        grid[:] = self.bg
        colors = self.colors
        if self.tinted:   # the colour shifts along with the flight
            e = np.broadcast_to(e, r.shape)[:, None]
            colors = np.rint(self.colors + (self.end_colors.astype(np.float32) - self.colors) * e).astype(np.uint8)
        grid[r[inside], c[inside]] = colors[inside]
        return grid

    def result(self):
        grid = np.empty((self.n * self.n, 3), dtype=np.uint8)
        grid[(self.r1 * self.n + self.c1).astype(np.intp)] = self.end_colors
        return grid.reshape(self.n, self.n, 3)


def prepare(img, crop, n):
    """Crops a PIL image to the square [x, y, size] and resizes it to n x n. Returns (n*n, 3) uint8."""
    x, y, size = crop
    small = img.crop((x, y, x + size, y + size)).resize((n, n), Image.LANCZOS, reducing_gap=3.0)
    return np.asarray(small, dtype=np.uint8).reshape(-1, 3)
