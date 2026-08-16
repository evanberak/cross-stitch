"""
Core conversion engine for the photo-to-cross-stitch converter.

Deliberately UI-free so it can be unit-tested and later reused by a
non-Streamlit front end (see the Version 2 note in the brief).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sklearn.cluster import KMeans, MiniBatchKMeans

# --------------------------------------------------------------------------
# Palette data
# --------------------------------------------------------------------------

PALETTE_PATH = Path(__file__).with_name("palette_starter.csv")


@dataclass(frozen=True)
class Floss:
    number: str
    name: str
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb


def load_palette(path: Path | str = PALETTE_PATH) -> list[Floss]:
    """Load the thread palette from CSV. Never hard-code colors elsewhere."""
    out: list[Floss] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(
                Floss(
                    number=row["number"].strip(),
                    name=row["name"].strip(),
                    rgb=(int(row["r"]), int(row["g"]), int(row["b"])),
                )
            )
    return out


# --------------------------------------------------------------------------
# Color science: sRGB -> CIE L*a*b*, and CIE76 Delta E
# --------------------------------------------------------------------------

_D65 = np.array([95.047, 100.000, 108.883])


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: float array (..., 3) in 0-255. Returns L*a*b* (..., 3)."""
    arr = np.asarray(rgb, dtype=np.float64) / 255.0

    # Inverse companding
    mask = arr > 0.04045
    arr = np.where(mask, ((arr + 0.055) / 1.055) ** 2.4, arr / 12.92)

    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = arr @ m.T * 100.0
    xyz = xyz / _D65

    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)

    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def delta_e_matrix(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    """CIE76 Delta E between every row of lab_a and every row of lab_b."""
    diff = lab_a[:, None, :] - lab_b[None, :, :]
    return np.sqrt((diff**2).sum(axis=-1))


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------

# Ordered so that neighbours in the list are visually dissimilar.
SYMBOLS = list(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijkmnopqrstuvwxyz"
    "0123456789"
    "+-=<>*#@%&$?!~^"
)


def assign_symbols(labs: np.ndarray) -> list[str]:
    """
    Give visually distinct symbols to perceptually similar colors.

    Colors are ordered by lightness, then symbols are dealt out with a large
    stride so that two threads which look alike never end up with two
    lookalike glyphs sitting next to each other on the chart.
    """
    n = len(labs)
    order = np.argsort(labs[:, 0])  # darkest -> lightest
    stride = max(1, len(SYMBOLS) // max(n, 1))
    symbols = [""] * n
    for rank, idx in enumerate(order):
        symbols[idx] = SYMBOLS[(rank * stride) % len(SYMBOLS)]
    # Guard against any collision from the modulo wrap.
    seen: set[str] = set()
    spare = [s for s in SYMBOLS if s not in symbols]
    for i, s in enumerate(symbols):
        if s in seen and spare:
            symbols[i] = spare.pop(0)
        seen.add(symbols[i])
    return symbols


# --------------------------------------------------------------------------
# Image preparation
# --------------------------------------------------------------------------


def prepare_image(
    img: Image.Image,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    sharpen: float = 1.0,
    crop_box: tuple[float, float, float, float] | None = None,
) -> Image.Image:
    """EXIF-correct, RGB, adjusted and cropped. Fractional crop box (l,t,r,b)."""
    img = ImageOps.exif_transpose(img).convert("RGB")

    if crop_box:
        w, h = img.size
        l, t, r, b = crop_box
        box = (int(l * w), int(t * h), int(r * w), int(b * h))
        if box[2] - box[0] > 4 and box[3] - box[1] > 4:
            img = img.crop(box)

    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if sharpen != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpen)
    return img


def downsample_to_grid(img: Image.Image, stitch_w: int, stitch_h: int,
                       smoothing: float = 0.0) -> np.ndarray:
    """
    Resize to the stitch grid. BOX averaging (not nearest) is what makes this
    a real reduction rather than a naive pixelate — each stitch becomes the
    average of the photo region it covers.
    """
    if smoothing > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=smoothing))
    small = img.resize((stitch_w, stitch_h), Image.Resampling.BOX)
    return np.asarray(small, dtype=np.uint8)


# --------------------------------------------------------------------------
# Quantization + floss matching
# --------------------------------------------------------------------------


@dataclass
class PatternColor:
    floss: Floss
    symbol: str
    count: int

    @property
    def percent(self) -> float:
        return self._percent

    _percent: float = 0.0


@dataclass
class Pattern:
    """The full result of a conversion."""
    grid: np.ndarray               # (h, w) int indices into `colors`
    colors: list[PatternColor]
    stitch_w: int
    stitch_h: int
    fabric_count: float
    locked: list[str] = field(default_factory=list)

    @property
    def finished_inches(self) -> tuple[float, float]:
        return (self.stitch_w / self.fabric_count,
                self.stitch_h / self.fabric_count)

    @property
    def finished_cm(self) -> tuple[float, float]:
        w, h = self.finished_inches
        return (w * 2.54, h * 2.54)

    @property
    def total_stitches(self) -> int:
        return self.stitch_w * self.stitch_h

    def rgb_array(self) -> np.ndarray:
        lut = np.array([c.floss.rgb for c in self.colors], dtype=np.uint8)
        return lut[self.grid]

    def skeins_estimate(self, strands: int = 2) -> dict[str, float]:
        """
        Rough floss estimate. One 8m skein of 6-strand floss, used 2 strands
        over 14ct, covers very roughly 1500 stitches. Scales with strand count
        and inversely with fabric count. Deliberately conservative.
        """
        out = {}
        for c in self.colors:
            per_skein = 1500 * (2 / strands) * (14 / self.fabric_count) ** 2
            out[c.floss.number] = max(0.05, c.count / per_skein)
        return out


def _quantize(pixels: np.ndarray, n_colors: int, seed: int = 0) -> np.ndarray:
    """Cluster in LAB space so clusters follow human perception."""
    lab = srgb_to_lab(pixels)
    n_colors = min(n_colors, len(np.unique(pixels, axis=0)))
    if n_colors < 1:
        n_colors = 1
    if len(lab) > 20000:
        km = MiniBatchKMeans(n_clusters=n_colors, random_state=seed,
                             n_init=3, batch_size=2048)
    else:
        km = KMeans(n_clusters=n_colors, random_state=seed, n_init=4)
    labels = km.fit_predict(lab)
    return labels


def convert(
    img: Image.Image,
    stitch_w: int,
    stitch_h: int,
    max_colors: int,
    fabric_count: float,
    palette: list[Floss],
    smoothing: float = 0.0,
    locked_numbers: list[str] | None = None,
) -> Pattern:
    """Run the full pipeline and return a Pattern."""
    locked_numbers = locked_numbers or []
    arr = downsample_to_grid(img, stitch_w, stitch_h, smoothing)
    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3).astype(np.float64)

    labels = _quantize(flat, max_colors)

    # Cluster centroids, averaged in LAB then converted back via nearest floss.
    pal_rgb = np.array([f.rgb for f in palette], dtype=np.float64)
    pal_lab = srgb_to_lab(pal_rgb)
    flat_lab = srgb_to_lab(flat)

    # Locked colors always stay available and take priority in matching.
    locked_idx = [i for i, f in enumerate(palette) if f.number in locked_numbers]

    n_clusters = int(labels.max()) + 1
    sizes = np.bincount(labels, minlength=n_clusters)

    dists = np.full((n_clusters, len(palette)), np.inf)
    for k in range(n_clusters):
        member_lab = flat_lab[labels == k]
        if len(member_lab) == 0:
            continue
        centroid = member_lab.mean(axis=0, keepdims=True)
        dists[k] = delta_e_matrix(centroid, pal_lab)[0]

    # Locked threads are a promise, not a preference: each one is reserved to
    # whichever cluster it matches best, before general assignment runs. A
    # cluster can only be claimed once, so locking more threads than there are
    # clusters simply fills every cluster with locked colors.
    chosen_locked: dict[int, int] = {}
    if locked_idx:
        claims = sorted(
            ((dists[k, pi], k, pi) for pi in locked_idx for k in range(n_clusters)),
            key=lambda t: t[0],
        )
        taken_clusters: set[int] = set()
        taken_floss: set[int] = set()
        for _, k, pi in claims:
            if k in taken_clusters or pi in taken_floss:
                continue
            chosen_locked[k] = pi
            taken_clusters.add(k)
            taken_floss.add(pi)

    # Assign greedily, largest cluster first, preferring an unused thread.
    # Two clusters only share a thread when every remaining alternative is a
    # visibly worse match — that keeps the delivered color count close to what
    # the user asked for without inventing bad matches for tiny regions.
    chosen = [0] * n_clusters
    used: set[int] = set(chosen_locked.values())
    for k, pi in chosen_locked.items():
        chosen[k] = pi
    MERGE_TOLERANCE = 6.0  # Delta E; below ~2.3 is imperceptible
    for k in np.argsort(-sizes):
        k = int(k)
        if k in chosen_locked:
            continue
        d = dists[k]
        if not np.isfinite(d).any():
            continue
        best = int(np.argmin(d))
        if best in used:
            masked = d.copy()
            masked[list(used)] = np.inf
            alt = int(np.argmin(masked))
            if masked[alt] - d[best] <= MERGE_TOLERANCE:
                best = alt
        chosen[k] = best
        used.add(best)

    # Merge clusters that landed on the same floss.
    unique_floss = sorted(set(chosen))
    remap = {f: i for i, f in enumerate(unique_floss)}
    cluster_to_color = np.array(
        [remap[chosen[k]] if k < len(chosen) else 0 for k in range(labels.max() + 1)]
    )
    grid = cluster_to_color[labels].reshape(h, w)

    labs = pal_lab[unique_floss]
    symbols = assign_symbols(labs)

    counts = np.bincount(grid.ravel(), minlength=len(unique_floss))
    total = int(counts.sum())
    colors = []
    for i, pi in enumerate(unique_floss):
        pc = PatternColor(floss=palette[pi], symbol=symbols[i], count=int(counts[i]))
        pc._percent = 100.0 * counts[i] / total if total else 0.0
        colors.append(pc)

    # Present the legend most-used first — that is the order stitchers work in.
    order = np.argsort([-c.count for c in colors])
    reindex = np.zeros(len(colors), dtype=int)
    for new, old in enumerate(order):
        reindex[old] = new
    grid = reindex[grid]
    colors = [colors[i] for i in order]

    return Pattern(
        grid=grid,
        colors=colors,
        stitch_w=w,
        stitch_h=h,
        fabric_count=fabric_count,
        locked=locked_numbers,
    )


def replace_color(pattern: Pattern, index: int, new_floss: Floss) -> Pattern:
    """Manual color replacement — swap one legend entry for another thread."""
    pattern.colors[index] = PatternColor(
        floss=new_floss,
        symbol=pattern.colors[index].symbol,
        count=pattern.colors[index].count,
    )
    pattern.colors[index]._percent = (
        100.0 * pattern.colors[index].count / pattern.total_stitches
    )
    return pattern
